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
        g_pel = create_grupo(session, "G_PEL", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL2", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB2", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL3", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB3", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL4", "DURO", [ctx["pel"]])
        g_libre = create_grupo(session, "G_LIBRE", "DURO", [])
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
        g_pel_duro = create_grupo(session, "G_PEL5", "DURO", [ctx["pel"]])
        g_blando = create_grupo(
            session, "G_BLND", "BLANDO", [ctx["pel"], ctx["sib"]],
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
        g_pel = create_grupo(session, "G_PEL6", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB6", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL7", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB7", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL8", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB8", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL9", "DURO", [ctx["pel"]])
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
        g_pel = create_grupo(session, "G_PEL10", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB10", "DURO", [ctx["sib"]])
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
        g_pel = create_grupo(session, "G_PEL11", "DURO", [ctx["pel"]])
        g_sib = create_grupo(session, "G_SIB11", "DURO", [ctx["sib"]])
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
