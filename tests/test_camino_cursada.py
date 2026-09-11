"""Tests para el chequeo camino de cursada (R13-camino).

Cubre el `_add_bloqueos_camino_cursada` que corre dentro de
`check_factibilidad_estructural`.

Casos:

- **Bloqueo real**: 2 materias en el mismo (carrera, año, cuatri) con
  horarios contiguos (gap < margen) y grupos de sede disjuntos → única
  comisión de cada una → no hay combinación factible.
- **Rescatado por alternativa**: agregando una segunda comisión con
  horario compatible, el DFS encuentra una combinación viable.
- **Grupo modo BLANDO / DURO vacío**: sin restricción de sede → nunca
  bloquea por camino.
- **Advertencia por cap**: al superar `MAX_COMBINACIONES_CAMINO`
  reporta advertencia en lugar de bloqueo.
- **Ignora optativas**: una materia optativa no participa del chequeo.
- **Ignora `carrera_asignada`**: aunque una comisión esté marcada con
  otra carrera, el chequeo usa el grupo de la materia.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    AulaDB,
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.factibilidad_service import (
    check_factibilidad_estructural,
)
from src.services.grupo_materia_service import create_grupo


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


# =============================================================================
# Helpers de seeding
# =============================================================================

def _seed_ciclo_y_carrera(session: Session) -> dict:
    """Seed base: 1 ciclo 2026-1C, 1 carrera A, 2 sedes (Pellegrini,
    Siberia), 1 aula por sede. Devuelve refs útiles."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="P1", ciclo_id="2026-1C",
    )
    car = CarreraDB(codigo="A", nombre="Carrera A")
    sede_p = SedeDB(id="pel", nombre="Pellegrini")
    sede_s = SedeDB(id="sib", nombre="Siberia")
    aula_p = AulaDB(
        id="aula-p", sede_id="pel", codigo_aula="AP",
        nombre="AP", capacidad=30, tipo="teorica",
    )
    aula_s = AulaDB(
        id="aula-s", sede_id="sib", codigo_aula="AS",
        nombre="AS", capacidad=30, tipo="teorica",
    )
    pv = PlanCarreraVersionDB(
        id="pv-A", carrera_codigo="A", nombre="Plan A",
        fecha_creacion=date(2026, 1, 1),
    )
    session.add_all([ciclo, plan, car, sede_p, sede_s, aula_p, aula_s, pv])
    session.add(CicloPlanVersionDB(
        ciclo_id="2026-1C", plan_version_id="pv-A",
    ))
    session.commit()
    return {"pel": "pel", "sib": "sib", "pv_id": "pv-A"}


def _add_materia_al_plan(
    session: Session,
    codigo: str,
    plan_version_id: str,
    carrera_codigo: str,
    anio: int,
    cuatri: str,
    grupo_id: str,
    optativa: bool = False,
) -> None:
    """Crea la materia, el plan_estudio entry, dictado y bridge."""
    if session.get(MateriaDB, codigo) is None:
        session.add(MateriaDB(
            codigo=codigo, nombre=f"Materia {codigo}",
            horas_semanales=2, horas_teoria=2, horas_laboratorio=0,
            grupo_id=grupo_id,
        ))
        session.add(DictadoDB(
            id=f"d-{codigo}", materia_codigo=codigo,
            dictado_codigo=f"{codigo}-2026-1C",
        ))
        session.add(DictadoCicloDB(
            dictado_id=f"d-{codigo}", ciclo_id="2026-1C",
        ))
        session.add(InscripcionHistoricaDB(
            materia_codigo=codigo, anio=2025,
            cuatrimestre="1C", inscriptos=20,
        ))
    session.add(PlanEstudioDB(
        id=str(uuid.uuid4()),
        plan_version_id=plan_version_id,
        materia_codigo=codigo,
        carrera_codigo=carrera_codigo,
        anio_plan=anio,
        cuatrimestre_plan=cuatri,
        optativa=optativa,
    ))
    session.commit()


def _add_comision(
    session: Session,
    materia_codigo: str,
    plan_id: str,
    numero: int = 1,
    horarios: list[tuple[str, int, int]] | None = None,
) -> str:
    """Agrega una comisión con los horarios `(dia, hi, hf)` dados.
    Devuelve el `com_id`."""
    com_id = str(uuid.uuid4())
    session.add(ComisionDB(
        id=com_id, materia_codigo=materia_codigo,
        plan_cursada_id=plan_id,
        comision_key=f"{materia_codigo}-{numero:03d}",
        nombre=f"Com {numero}", numero=numero, cupo=30,
    ))
    for dia, hi, hf in (horarios or []):
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com_id,
            codigo_materia=materia_codigo,
            dia=dia,
            hora_inicio=time(hi, 0),
            hora_fin=time(hf, 0),
            tipo_clase="teorica",
        ))
    session.commit()
    return com_id


# =============================================================================
# Tests
# =============================================================================


class TestCaminoCursadaBloqueo:

    def test_dos_materias_disjuntas_contiguas_bloquean(self, session):
        """M1 en grupo Pellegrini-DURO, M2 en grupo Siberia-DURO.
        Ambas Lunes contiguas (M1 8-10, M2 10-12, gap=0 < 30 margen).
        Cada una con 1 comisión → sin alternativas → bloqueo."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert len(camino_bloqueos) == 1
        assert not reporte.factible
        # Detalle menciona ambas materias y ambas sedes.
        det = camino_bloqueos[0].detalle
        assert "M1" in det and "M2" in det
        assert "Pellegrini" in det and "Siberia" in det

    def test_alternativa_de_comision_rescata_camino(self, session):
        """M1 en Pellegrini, M2 en Siberia. M2 con 2 comisiones: una
        contigua a M1 (bloquea) y otra con margen suficiente. El DFS
        debería encontrar la combinación viable."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL2", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB2", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        _add_comision(
            session, "M1", "plan-1", numero=1,
            horarios=[("Lunes", 8, 10)],
        )
        # Comisión conflictiva (contigua sin margen).
        _add_comision(
            session, "M2", "plan-1", numero=1,
            horarios=[("Lunes", 10, 12)],
        )
        # Comisión salvadora (otro día — no hay par en riesgo).
        _add_comision(
            session, "M2", "plan-1", numero=2,
            horarios=[("Martes", 10, 12)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert camino_bloqueos == []

    def test_margen_suficiente_no_bloquea(self, session):
        """Aunque sedes disjuntas, si el gap es >= margen no hay
        problema de traslado."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL3", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB3", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        _add_comision(
            session, "M1", "plan-1", horarios=[("Lunes", 8, 10)],
        )
        _add_comision(
            session, "M2", "plan-1", horarios=[("Lunes", 11, 13)],
        )  # gap = 60 min >= 30 default

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert camino_bloqueos == []


class TestGruposPermisivos:

    def test_grupo_duro_vacio_no_bloquea(self, session):
        """Grupo DURO con lista vacía = fallback permisivo. Como una
        de las materias tiene "cualquier sede", el par nunca genera
        conflicto."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL4", sedes_duras=[ctx["pel"]])
        g_libre = create_grupo(session, "G_LIBRE", sedes_duras=[])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_libre.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])

        reporte = check_factibilidad_estructural(session, "plan-1")
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []

    def test_grupo_blando_no_bloquea(self, session):
        """BLANDO acepta todas las sedes (dura ∪ blanda), no restringe
        a nivel camino."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel_duro = create_grupo(session, "G_PEL5", sedes_duras=[ctx["pel"]])
        g_blando = create_grupo(
            session, "G_BLND",
            sedes_blandas_ordenadas=[ctx["pel"], ctx["sib"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel_duro.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_blando.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])

        reporte = check_factibilidad_estructural(session, "plan-1")
        # BLANDO significa "cualquier sede posible" a nivel camino →
        # M2 puede ir a Pellegrini con M1, no hay bloqueo.
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []


class TestOptativasIgnoradas:

    def test_optativa_no_participa(self, session):
        """Una materia optativa en el mismo grupo curricular no se
        cuenta en el chequeo (aun si sus sedes disjuntas)."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL6", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB6", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
            optativa=True,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])

        reporte = check_factibilidad_estructural(session, "plan-1")
        # M2 optativa → skip. Sólo queda M1 → no hay pares → no bloqueo.
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []


class TestCarreraAsignadaIgnorada:

    def test_carrera_asignada_no_afecta_camino(self, session):
        """`ComisionDB.carrera_asignada` es etiqueta visual — no debe
        modificar el chequeo de camino. La resolución usa siempre el
        grupo de la materia."""
        ctx = _seed_ciclo_y_carrera(session)
        # 2da carrera para poder setear carrera_asignada.
        session.add(CarreraDB(codigo="B", nombre="Carrera B"))
        session.commit()
        g_pel = create_grupo(session, "G_PEL7", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB7", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        cid = _add_comision(
            session, "M2", "plan-1", horarios=[("Lunes", 10, 12)],
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        # Marcar M2 como si fuera para B (no debe cambiar nada).
        com = session.get(ComisionDB, cid)
        assert com is not None
        com.carrera_asignada = "B"
        session.add(com)
        session.commit()

        reporte = check_factibilidad_estructural(session, "plan-1")
        # Sigue detectándose el bloqueo (el grupo de M2 sigue siendo
        # Siberia — la etiqueta a B no cambia esto).
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] != []


class TestCapExcedido:

    def test_cap_excedido_genera_advertencia(self, session, monkeypatch):
        """Con muchas comisiones podemos superar el cap. Bajamos el cap
        artificialmente para gatillarlo con un test chico."""
        import src.services.factibilidad_service as fs_mod
        monkeypatch.setattr(
            fs_mod, "MAX_COMBINACIONES_CAMINO", 3, raising=True,
        )
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL8", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB8", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        # 2 y 2 = 4 combinaciones > cap=3. Ambas materias tienen
        # sedes disjuntas. Cada comisión M2 es contigua a AMBAS
        # comisiones M1 → todas las combinaciones son incompatibles →
        # el DFS agota el espacio y activa la vía de "excede cap".
        _add_comision(
            session, "M1", "plan-1", numero=1,
            horarios=[("Lunes", 8, 10)],
        )
        _add_comision(
            session, "M1", "plan-1", numero=2,
            horarios=[("Lunes", 12, 14)],
        )
        # M2-c1: contigua a M1-c1 (10-8=0<30) y contigua a M1-c2 (12-10=0<30).
        _add_comision(
            session, "M2", "plan-1", numero=1,
            horarios=[("Lunes", 10, 12)],
        )
        # M2-c2: contigua a M1-c1 (8-6=0<30) y contigua a M1-c2 (14-12=0<30).
        _add_comision(
            session, "M2", "plan-1", numero=2,
            horarios=[("Lunes", 6, 8), ("Lunes", 14, 16)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")
        # No hay bloqueo, hay advertencia.
        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        camino_adv = [
            b for b in reporte.advertencias if b.codigo_regla == "R13-camino"
        ]
        assert camino_bloqueos == []
        assert len(camino_adv) == 1
        assert "excede" in camino_adv[0].titulo.lower()


class TestGruposNoRelevantes:

    def test_una_sola_materia_en_grupo_curricular_no_chequea(self, session):
        """Con una sola materia en (carrera, año, cuatri), no hay
        pares → no aplica R13-camino."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL9", sedes_duras=[ctx["pel"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        reporte = check_factibilidad_estructural(session, "plan-1")
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []

    def test_grupo_cuatri_opuesto_no_participa(self, session):
        """Materias en cuatrimestre distinto al ciclo (1C vs 2C) no
        entran al chequeo."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL10", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB10", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "2C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "2C", g_sib.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])
        # El ciclo es 1C → grupo 2C se ignora.
        reporte = check_factibilidad_estructural(session, "plan-1")
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []

    def test_anuales_se_juntan_con_1c(self, session):
        """Materias Anuales entran al grupo del ciclo — si están en
        Anual y hay otra en 1C con sedes disjuntas, se bloquea."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(session, "G_PEL11", sedes_duras=[ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB11", sedes_duras=[ctx["sib"]])
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "Anual", g_sib.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])

        reporte = check_factibilidad_estructural(session, "plan-1")
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] != []


class TestCaminoCursadaSolapamiento:
    """Chequeo de camino cursada debe descartar combinaciones donde
    dos comisiones de distintas materias se solapan horariamente
    (no sólo por margen intersede). Reproducido a partir del caso
    real de Electrónica 3° 1C donde FB12 tenía 3 comisiones y todas
    quedaban descartadas por solapar con otras obligatorias del
    cuatrimestre — el pre-check anterior no lo detectaba y el LP
    resolvía como si nada.
    """

    def test_dos_materias_con_unica_comision_solapada_bloquean(
        self, session,
    ):
        """M1 y M2 ambas Lunes 10-12 (misma sede DURO). No hay
        margen intersede que rescate (mismo grupo de sede). El chequeo
        debe bloquear por 'ninguna combinación cursable' — no puede
        cursarse dos materias en la misma franja."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_SOLAP1", sedes_duras=[ctx["pel"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_comision(
            session, "M1", "plan-1", horarios=[("Lunes", 10, 12)],
        )
        _add_comision(
            session, "M2", "plan-1", horarios=[("Lunes", 10, 12)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert len(camino_bloqueos) == 1, (
            "Dos materias obligatorias solapadas deberían bloquear "
            "el camino de cursada"
        )
        assert not reporte.factible

    def test_todas_las_comisiones_de_una_materia_solapan_con_otras(
        self, session,
    ):
        """Reproduce el caso Electrónica 3° 1C: FB12 tiene 3
        comisiones, cada una solapa con al menos otra materia
        obligatoria del mismo (carrera, año, cuatri). El chequeo
        debe bloquear porque no hay ninguna comisión de FB12 que
        deje cursar todas las obligatorias."""
        ctx = _seed_ciclo_y_carrera(session)
        # Todas Pellegrini (no importan intersede — sólo solapamiento).
        g_pel = create_grupo(
            session, "G_PEL_SOLAP2", sedes_duras=[ctx["pel"]],
        )
        for mc in ("FB12", "FB20", "E4", "E5"):
            _add_materia_al_plan(
                session, mc, ctx["pv_id"], "A", 1, "1C", g_pel.id,
            )
        # FB12 tiene 3 comisiones, cada una solapa con alguna otra:
        # com 1 Lunes 10-12 solapa con FB20 Lunes 10:30-13
        # com 2 Lunes 14:45-16:45 solapa con E4 Lunes 13:45-17:45
        # com 3 Lunes 18:15-20:15 solapa con E5 Lunes 17-20
        _add_comision(
            session, "FB12", "plan-1", numero=1,
            horarios=[("Lunes", 10, 12)],
        )
        _add_comision(
            session, "FB12", "plan-1", numero=2,
            horarios=[("Lunes", 14, 16)],
        )
        _add_comision(
            session, "FB12", "plan-1", numero=3,
            horarios=[("Lunes", 18, 20)],
        )
        # FB20 Lunes 10:30-13 (solapa con FB12 com 1).
        _add_comision(
            session, "FB20", "plan-1",
            horarios=[("Lunes", 10, 13)],
        )
        # E4 Lunes 13-17 (solapa con FB12 com 2).
        _add_comision(
            session, "E4", "plan-1",
            horarios=[("Lunes", 13, 17)],
        )
        # E5 Lunes 17-20 (solapa con FB12 com 3).
        _add_comision(
            session, "E5", "plan-1",
            horarios=[("Lunes", 17, 20)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert len(camino_bloqueos) == 1
        assert not reporte.factible
        # El detalle debe mencionar FB12 (la materia sin escape).
        det = camino_bloqueos[0].detalle
        assert "FB12" in det

    def test_solapamiento_evitable_por_comision_alternativa_no_bloquea(
        self, session,
    ):
        """M1 tiene 2 comisiones: com 1 solapa con M2, com 2 no.
        El DFS debe encontrar la combinación viable."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_SOLAP3", sedes_duras=[ctx["pel"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        # M1 com 1 solapa; M1 com 2 no.
        _add_comision(
            session, "M1", "plan-1", numero=1,
            horarios=[("Lunes", 10, 12)],
        )
        _add_comision(
            session, "M1", "plan-1", numero=2,
            horarios=[("Martes", 10, 12)],
        )
        _add_comision(
            session, "M2", "plan-1",
            horarios=[("Lunes", 10, 12)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")

        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] == []

    def test_solapamiento_parcial_bloquea(self, session):
        """Solapamiento no tiene que ser exacto — basta con que las
        franjas se pisen en algún instante."""
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_SOLAP4", sedes_duras=[ctx["pel"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        # M1 Lunes 10-12, M2 Lunes 11-13 → solapan 11-12.
        _add_comision(
            session, "M1", "plan-1", horarios=[("Lunes", 10, 12)],
        )
        _add_comision(
            session, "M2", "plan-1", horarios=[("Lunes", 11, 13)],
        )

        reporte = check_factibilidad_estructural(session, "plan-1")
        assert [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ] != []


class TestCaminoCursadaExcepcionesIgnoradas:
    """Cuando el par bloqueante figura en ``IgnoredConflictDB`` para el
    plan, el chequeo camino lo saltea. Reutiliza la misma tabla que
    usa el detalle del plan para "conflictos ignorados" — permite
    modelar casos reales donde dos materias del mismo (carrera, año,
    cuatri) se dictan en paralelo porque en la práctica las cursan
    grupos de alumnos distintos (ej. IA-1.2 vs IA0 en el plan de IA).
    """

    def test_par_ignorado_no_bloquea(self, session):
        """M1 y M2 se solapan pero el par (M1, M2) está en
        IgnoredConflictDB para el plan → sin bloqueo."""
        from src.database.models import IgnoredConflictDB
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_IGN1", sedes_duras=[ctx["pel"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 10, 12)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])
        # Registrar excepción explícita.
        a, b = sorted(("M1", "M2"))
        session.add(IgnoredConflictDB(
            plan_cursada_id="plan-1",
            materia_a=a, materia_b=b,
            razon="Grupos de alumnos distintos por año de plan",
        ))
        session.commit()

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert camino_bloqueos == []

    def test_par_ignorado_de_otro_plan_no_afecta(self, session):
        """La excepción está registrada pero para OTRO plan → el
        chequeo del plan actual sigue bloqueando."""
        from src.database.models import IgnoredConflictDB
        ctx = _seed_ciclo_y_carrera(session)
        # Segundo plan al que le vamos a asociar la excepción.
        session.add(PlanificacionCursadaDB(
            id="plan-otro", nombre="Otro", ciclo_id="2026-1C",
        ))
        session.commit()
        g_pel = create_grupo(
            session, "G_PEL_IGN2", sedes_duras=[ctx["pel"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 10, 12)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])
        # Excepción registrada para OTRO plan.
        a, b = sorted(("M1", "M2"))
        session.add(IgnoredConflictDB(
            plan_cursada_id="plan-otro",
            materia_a=a, materia_b=b,
            razon="Excepción de otro plan",
        ))
        session.commit()

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert len(camino_bloqueos) == 1

    def test_par_ignorado_no_afecta_otros_pares_bloqueantes(self, session):
        """Ignorar (M1, M2) no debería salvar un bloqueo entre M1 y
        M3 (par distinto)."""
        from src.database.models import IgnoredConflictDB
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_IGN3", sedes_duras=[ctx["pel"]],
        )
        for mc in ("M1", "M2", "M3"):
            _add_materia_al_plan(
                session, mc, ctx["pv_id"], "A", 1, "1C", g_pel.id,
            )
        # M1 solapa con M2 (ignorado) y con M3 (no ignorado).
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 10, 12)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])
        _add_comision(session, "M3", "plan-1", horarios=[("Lunes", 11, 13)])
        a, b = sorted(("M1", "M2"))
        session.add(IgnoredConflictDB(
            plan_cursada_id="plan-1",
            materia_a=a, materia_b=b,
            razon="test",
        ))
        session.commit()

        reporte = check_factibilidad_estructural(session, "plan-1")

        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        # M1-M3 sigue bloqueando; M2-M3 no chocan (10-12 vs 11-13 se
        # solapan sólo si están ambas activas, pero como M1-M2 está
        # ignorado y M1-M3 sigue chocando, el DFS no encuentra
        # combinación viable de todas modos → 1 bloqueo).
        assert len(camino_bloqueos) == 1

    def test_par_ignorado_no_afecta_bloqueo_intersede(self, session):
        """El par ignorado sólo aplica a solapamientos horarios
        (donde el concepto 'los cursan distintos alumnos' tiene
        sentido). Un bloqueo por margen intersede sigue disparándose
        aunque el par esté marcado como ignorado — el traslado físico
        entre sedes es un problema del cronograma, no de alumnos."""
        from src.database.models import IgnoredConflictDB
        ctx = _seed_ciclo_y_carrera(session)
        g_pel = create_grupo(
            session, "G_PEL_IGN4", sedes_duras=[ctx["pel"]],
        )
        g_sib = create_grupo(
            session, "G_SIB_IGN4", sedes_duras=[ctx["sib"]],
        )
        _add_materia_al_plan(
            session, "M1", ctx["pv_id"], "A", 1, "1C", g_pel.id,
        )
        _add_materia_al_plan(
            session, "M2", ctx["pv_id"], "A", 1, "1C", g_sib.id,
        )
        # Contiguos con gap 0 (< margen 30). Sedes disjuntas.
        _add_comision(session, "M1", "plan-1", horarios=[("Lunes", 8, 10)])
        _add_comision(session, "M2", "plan-1", horarios=[("Lunes", 10, 12)])
        a, b = sorted(("M1", "M2"))
        session.add(IgnoredConflictDB(
            plan_cursada_id="plan-1",
            materia_a=a, materia_b=b,
            razon="test",
        ))
        session.commit()

        reporte = check_factibilidad_estructural(session, "plan-1")

        # Debe bloquear igual: la excepción sólo cubre solapamiento.
        camino_bloqueos = [
            b for b in reporte.bloqueos if b.codigo_regla == "R13-camino"
        ]
        assert len(camino_bloqueos) == 1
