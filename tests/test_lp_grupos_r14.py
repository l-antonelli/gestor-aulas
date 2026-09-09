"""Tests de integración LP × Grupos de Materias (R10/R12/R14).

Cubre el refactor del LP a la resolución vía `GrupoMateriaDB`:

- **R10 DURO / DURO-vacío**: filtrado de `compat` por sede según el
  modo del grupo.
- **R12 BLANDO**: `sede_preferida_por_horario[h]` sale de la primera
  sede del grupo BLANDO. En modo DURO no hay preferencia.
- **Etiqueta visual**: `ComisionDB.carrera_asignada` no interviene en
  la resolución.
- **R14 misma sede por comisión**: genera las variables `y[c, s]` y
  restricciones ``Σ_s y[c, s] = 1`` sólo cuando el toggle está ON.

Los tests que necesitan `pulp` verifican estructura del modelo (no lo
resuelven). Los que sólo tocan `build_inputs` corren sin pulp.
"""

from __future__ import annotations

import uuid
from datetime import date, time

import pytest

# `asignacion_aulas_service` importa `pulp` a nivel módulo. Si el
# entorno no lo tiene, todo el archivo se saltea limpio.
pulp = pytest.importorskip("pulp")

from sqlalchemy.pool import StaticPool  # noqa: E402
from sqlmodel import Session, SQLModel, create_engine  # noqa: E402

from src.database.models import (  # noqa: E402
    AulaDB,
    CarreraDB,
    CicloDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    InscripcionHistoricaDB,
    MateriaDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_service import (  # noqa: E402
    LPConfig,
    build_inputs,
)
from src.services.grupo_materia_service import create_grupo  # noqa: E402


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


def _seed_basico(session: Session) -> dict:
    """Ciclo 2026-1C, plan-1 vacío, 2 sedes con 1 aula cada una."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test", ciclo_id="2026-1C",
    )
    sede_a = SedeDB(id="SA", nombre="Sede A")
    sede_b = SedeDB(id="SB", nombre="Sede B")
    session.add_all([ciclo, plan, sede_a, sede_b])
    aula_a = AulaDB(
        id="aula-a", sede_id="SA", codigo_aula="aa",
        nombre="Aula A", capacidad=30, tipo="teorica",
    )
    aula_b = AulaDB(
        id="aula-b", sede_id="SB", codigo_aula="ab",
        nombre="Aula B", capacidad=30, tipo="teorica",
    )
    session.add_all([aula_a, aula_b])
    session.commit()
    return {"sede_a_id": "SA", "sede_b_id": "SB"}


def _add_materia_comision_horario(
    session: Session,
    materia_codigo: str,
    plan_id: str,
    ciclo: CicloDB,
    horas: float = 2.0,
    esperados: int = 20,
    dia: str = "Lunes",
    hi: int = 8,
    hf: int = 10,
    tipo_clase: str | None = "teorica",
    n_horarios: int = 1,
    comision_id: str | None = None,
    grupo_id: str | None = None,
) -> tuple[str, list[str]]:
    """Crea materia + dictado + comisión + N horarios. Devuelve
    ``(comision_id, [horario_ids])``."""
    if session.get(MateriaDB, materia_codigo) is None:
        session.add(MateriaDB(
            codigo=materia_codigo, nombre=f"Materia {materia_codigo}",
            horas_semanales=horas * n_horarios,
            horas_teoria=horas * n_horarios if tipo_clase != "laboratorio" else 0,
            horas_laboratorio=horas * n_horarios if tipo_clase == "laboratorio" else 0,
            grupo_id=grupo_id,
        ))
        session.add(DictadoDB(
            id=f"d-{materia_codigo}",
            materia_codigo=materia_codigo,
            dictado_codigo=f"{materia_codigo}-2026-1C",
        ))
        session.add(DictadoCicloDB(
            dictado_id=f"d-{materia_codigo}", ciclo_id=ciclo.id,
        ))
        session.add(InscripcionHistoricaDB(
            materia_codigo=materia_codigo, anio=ciclo.anio - 1,
            cuatrimestre=f"{ciclo.numero}C", inscriptos=esperados,
        ))

    com_id = comision_id or str(uuid.uuid4())
    if session.get(ComisionDB, com_id) is None:
        session.add(ComisionDB(
            id=com_id,
            materia_codigo=materia_codigo,
            plan_cursada_id=plan_id,
            comision_key=f"{materia_codigo}-001",
            nombre="Comisión 1",
            numero=1,
            cupo=30,
        ))

    hids: list[str] = []
    for i in range(n_horarios):
        hid = str(uuid.uuid4())
        hids.append(hid)
        session.add(HorarioDB(
            id=hid,
            comision_id=com_id,
            codigo_materia=materia_codigo,
            dia=dia,
            hora_inicio=time(hi + i * 3, 0),
            hora_fin=time(hf + i * 3, 0),
            tipo_clase=tipo_clase,
        ))
    session.commit()
    return com_id, hids


# =============================================================================
# R10 — Filtrado DURO
# =============================================================================


class TestR10Duro:

    def test_grupo_duro_una_sede_filtra_aulas_de_otras_sedes(self, session):
        """Materia en grupo DURO=[SA]: compat con aulas de SB debe ser
        False, con aulas de SA True."""
        ctx = _seed_basico(session)
        g_duro = create_grupo(session, "G_DURO", "DURO", [ctx["sede_a_id"]])
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g_duro.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        # aula-a (sede A) admite; aula-b (sede B) no.
        assert inputs.compat[(hids[0], "aula-a")] is True
        assert inputs.compat[(hids[0], "aula-b")] is False

    def test_grupo_duro_dos_sedes_admite_ambas(self, session):
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_2SEDES", "DURO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        assert inputs.compat[(hids[0], "aula-a")] is True
        assert inputs.compat[(hids[0], "aula-b")] is True

    def test_grupo_duro_lista_vacia_fallback_permisivo(self, session):
        """DURO con lista vacía = todas admisibles."""
        _seed_basico(session)
        g = create_grupo(session, "G_VACIO", "DURO", [])
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        # Sin restricción de sede: ambas aulas admiten.
        assert inputs.compat[(hids[0], "aula-a")] is True
        assert inputs.compat[(hids[0], "aula-b")] is True


# =============================================================================
# R12 — Preferencia BLANDA
# =============================================================================


class TestR12Blando:

    def test_grupo_blando_preferida_es_la_primera(self, session):
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_BLANDO", "BLANDO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        assert inputs.sede_preferida_por_horario[hids[0]] == "SA"

    def test_grupo_blando_no_filtra_sedes(self, session):
        """BLANDO admite todas las sedes de la lista, aunque no sean la
        primera."""
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_BLANDO2", "BLANDO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        # BLANDO no filtra: ambas aulas siguen compat.
        assert inputs.compat[(hids[0], "aula-a")] is True
        assert inputs.compat[(hids[0], "aula-b")] is True

    def test_grupo_duro_no_setea_preferida(self, session):
        ctx = _seed_basico(session)
        g = create_grupo(session, "G_DURO2", "DURO", [ctx["sede_a_id"]])
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        # En DURO no hay preferencia — todas las sedes del set son
        # equivalentes a nivel objetivo.
        assert inputs.sede_preferida_por_horario[hids[0]] is None

    def test_grupo_blando_vacio_no_setea_preferida(self, session):
        _seed_basico(session)
        g = create_grupo(session, "G_BLANDO_VACIO", "BLANDO", [])
        ciclo = session.get(CicloDB, "2026-1C")
        _, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        assert inputs.sede_preferida_por_horario[hids[0]] is None


# =============================================================================
# Etiqueta visual: carrera_asignada NO afecta la resolución
# =============================================================================


class TestCarreraAsignadaEsSoloEtiqueta:

    def test_carrera_asignada_no_afecta_r10(self, session):
        """`ComisionDB.carrera_asignada` fue etiqueta visual desde el
        rediseño de grupos. Modificarla no debe cambiar qué sedes son
        admisibles para el horario."""
        ctx = _seed_basico(session)
        # Crear una carrera 'X' para referenciar en carrera_asignada.
        session.add(CarreraDB(codigo="X", nombre="Carrera X"))
        session.commit()
        # Materia en grupo DURO [SA].
        g = create_grupo(session, "G_ETQ", "DURO", [ctx["sede_a_id"]])
        ciclo = session.get(CicloDB, "2026-1C")
        cid, hids = _add_materia_comision_horario(
            session, "MAT1", "plan-1", ciclo, grupo_id=g.id,
        )
        # Setear carrera_asignada en la comisión (marca visual).
        com = session.get(ComisionDB, cid)
        assert com is not None
        com.carrera_asignada = "X"
        session.add(com)
        session.commit()

        inputs = build_inputs(session, "plan-1", LPConfig())
        # A pesar del override, sigue admitiéndose sólo SA.
        assert inputs.compat[(hids[0], "aula-a")] is True
        assert inputs.compat[(hids[0], "aula-b")] is False


# =============================================================================
# R14 — Misma sede por comisión
# =============================================================================


class TestR14MismaSedePorComision:

    def _seed_materia_multihorario(
        self, session, ctx, grupo_id: str,
    ):
        """Crea 1 materia + 1 comisión con 2 horarios distintos, con
        grupo=[SA, SB] (ambas sedes admisibles)."""
        ciclo = session.get(CicloDB, "2026-1C")
        return _add_materia_comision_horario(
            session, "MAT_MULTI", "plan-1", ciclo,
            grupo_id=grupo_id, n_horarios=2,
            dia="Lunes", hi=8, hf=10,
        )

    def test_r14_off_no_crea_variables_y(self, session):
        from src.services.asignacion_aulas_service import build_model
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_2S", "DURO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        self._seed_materia_multihorario(session, ctx, g.id)
        inputs = build_inputs(session, "plan-1", LPConfig())
        prob, vars_dict = build_model(
            inputs, LPConfig(forzar_misma_sede_por_comision=False),
        )
        assert vars_dict["y_sede_comision"] == {}

    def test_r14_on_crea_variables_y_para_comision_multihorario(
        self, session,
    ):
        from src.services.asignacion_aulas_service import build_model
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_2S", "DURO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        cid, hids = self._seed_materia_multihorario(session, ctx, g.id)
        inputs = build_inputs(session, "plan-1", LPConfig())
        prob, vars_dict = build_model(
            inputs, LPConfig(forzar_misma_sede_por_comision=True),
        )
        y = vars_dict["y_sede_comision"]
        # Debe haber 2 variables: (cid, SA) y (cid, SB).
        assert (cid, "SA") in y
        assert (cid, "SB") in y

    def test_r14_on_no_crea_y_para_comision_de_un_solo_horario(
        self, session,
    ):
        """Comisiones con un único horario tienen R14 trivial → no se
        crean variables auxiliares."""
        from src.services.asignacion_aulas_service import build_model
        ctx = _seed_basico(session)
        g = create_grupo(
            session, "G_2S", "DURO",
            [ctx["sede_a_id"], ctx["sede_b_id"]],
        )
        ciclo = session.get(CicloDB, "2026-1C")
        cid, hids = _add_materia_comision_horario(
            session, "MAT_UNO", "plan-1", ciclo,
            grupo_id=g.id, n_horarios=1,
        )
        inputs = build_inputs(session, "plan-1", LPConfig())
        prob, vars_dict = build_model(
            inputs, LPConfig(forzar_misma_sede_por_comision=True),
        )
        assert vars_dict["y_sede_comision"] == {}

    def test_r14_solo_sedes_candidatas_generan_variables(self, session):
        """Si la materia está en un grupo DURO=[SA] (una sola sede), aunque
        R14 esté ON, sólo debería generar una variable y[c, SA] — no y[c, SB]
        porque no hay aulas candidatas en SB para esta comisión."""
        from src.services.asignacion_aulas_service import build_model
        ctx = _seed_basico(session)
        g = create_grupo(session, "G_1S", "DURO", [ctx["sede_a_id"]])
        cid, hids = self._seed_materia_multihorario(session, ctx, g.id)
        inputs = build_inputs(session, "plan-1", LPConfig())
        prob, vars_dict = build_model(
            inputs, LPConfig(forzar_misma_sede_por_comision=True),
        )
        y = vars_dict["y_sede_comision"]
        assert (cid, "SA") in y
        assert (cid, "SB") not in y  # sin candidaturas de aula en SB

    def test_r14_default_es_off(self, session):
        """Verificamos que el default de `LPConfig` deja R14 desactivada
        para no alterar el comportamiento previo del solver."""
        cfg = LPConfig()
        assert cfg.forzar_misma_sede_por_comision is False
