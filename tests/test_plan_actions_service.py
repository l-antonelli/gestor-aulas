"""Tests para plan_actions_service.preview/aplicar_auto_completar_tipos."""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CicloDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanificacionCursadaDB,
)
from src.services.plan_actions_service import (
    aplicar_auto_completar_tipos,
    preview_auto_completar_tipos,
)


@pytest.fixture(name="session")
def session_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def _seed(session: Session) -> str:
    """Seed mínimo: un ciclo + plan vacío. Devuelve plan_id."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test",
        ciclo_id="2026-1C", activo=True,
    )
    session.add_all([ciclo, plan])
    session.commit()
    return "plan-1"


def _add_materia_con_horarios(
    session: Session,
    plan_id: str,
    codigo: str,
    *,
    hteo: float | None,
    hlab: float | None,
    horarios_tipos: list[str | None],
) -> list[HorarioDB]:
    """Crea materia + comisión + n horarios (uno por cada tipo en
    ``horarios_tipos``)."""
    materia = MateriaDB(
        codigo=codigo, nombre=f"Mat {codigo}",
        horas_semanales=(hteo or 0) + (hlab or 0),
        horas_teoria=hteo, horas_laboratorio=hlab,
    )
    com_id = str(uuid.uuid4())
    com = ComisionDB(
        id=com_id, materia_codigo=codigo, plan_cursada_id=plan_id,
        comision_key=f"{codigo}-001", nombre="Com 1", numero=1, cupo=30,
    )
    session.add_all([materia, com])
    horarios = []
    for i, tipo in enumerate(horarios_tipos):
        h = HorarioDB(
            id=f"{codigo}-h{i}",
            comision_id=com_id,
            codigo_materia=codigo,
            dia="Lunes",
            hora_inicio=time(8 + i * 2, 0),
            hora_fin=time(10 + i * 2, 0),
            tipo_clase=tipo,
        )
        session.add(h)
        horarios.append(h)
    session.commit()
    return horarios


class TestPreviewAutoCompletar:

    def test_solo_teoria_propone_teorica(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MT",
            hteo=4, hlab=0, horarios_tipos=[None, None],
        )
        prev = preview_auto_completar_tipos(session, plan_id)
        assert prev.total == 2
        assert len(prev.a_teorica) == 2
        assert len(prev.a_laboratorio) == 0
        assert all(it.tipo_propuesto == "teorica" for it in prev.a_teorica)
        assert all(it.razon == "hlab=0" for it in prev.a_teorica)

    def test_solo_lab_propone_laboratorio(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "ML",
            hteo=0, hlab=2, horarios_tipos=[None],
        )
        prev = preview_auto_completar_tipos(session, plan_id)
        assert len(prev.a_laboratorio) == 1
        assert prev.a_laboratorio[0].tipo_propuesto == "laboratorio"
        assert prev.a_laboratorio[0].razon == "hteo=0"

    def test_mixta_no_se_toca(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MIX",
            hteo=2, hlab=2, horarios_tipos=[None, None],
        )
        prev = preview_auto_completar_tipos(session, plan_id)
        assert prev.total == 0
        assert "MIX" in prev.materias_mixtas

    def test_sin_horas_se_reporta(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MX",
            hteo=None, hlab=None, horarios_tipos=[None],
        )
        prev = preview_auto_completar_tipos(session, plan_id)
        assert prev.total == 0
        assert "MX" in prev.materias_sin_horas

    def test_no_pisa_horarios_ya_tipados(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MT",
            hteo=4, hlab=0, horarios_tipos=["teorica", None, "laboratorio"],
        )
        prev = preview_auto_completar_tipos(session, plan_id)
        # Solo el horario None debe aparecer.
        assert len(prev.a_teorica) == 1
        assert prev.a_teorica[0].horario_id == "MT-h1"

    def test_plan_vacio_devuelve_preview_vacio(self, session):
        plan_id = _seed(session)
        prev = preview_auto_completar_tipos(session, plan_id)
        assert prev.total == 0
        assert prev.materias_sin_horas == []
        assert prev.materias_mixtas == []


class TestAplicarAutoCompletar:

    def test_aplica_y_persiste(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MT",
            hteo=4, hlab=0, horarios_tipos=[None, None],
        )
        prev = aplicar_auto_completar_tipos(session, plan_id)
        assert prev.total == 2
        # Re-leer de la DB.
        h = session.get(HorarioDB, "MT-h0")
        assert h is not None and h.tipo_clase == "teorica"

    def test_idempotente(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MT",
            hteo=4, hlab=0, horarios_tipos=[None],
        )
        aplicar_auto_completar_tipos(session, plan_id)
        # Segunda corrida: ya no hay nada para hacer.
        prev2 = aplicar_auto_completar_tipos(session, plan_id)
        assert prev2.total == 0

    def test_aplica_lab_correctamente(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "ML",
            hteo=0, hlab=4, horarios_tipos=[None],
        )
        aplicar_auto_completar_tipos(session, plan_id)
        h = session.get(HorarioDB, "ML-h0")
        assert h is not None and h.tipo_clase == "laboratorio"

    def test_no_toca_materia_mixta(self, session):
        plan_id = _seed(session)
        _add_materia_con_horarios(
            session, plan_id, "MIX",
            hteo=2, hlab=2, horarios_tipos=[None, None],
        )
        aplicar_auto_completar_tipos(session, plan_id)
        h = session.get(HorarioDB, "MIX-h0")
        assert h is not None and h.tipo_clase is None


# =============================================================================
# Cambio de horario con preview de validaciones
# =============================================================================


from src.services.plan_actions_service import (
    aplicar_cambio_horario,
    preview_cambio_horario,
)


class TestCambioHorario:

    def test_preview_horario_inexistente(self, session):
        plan_id = _seed(session)
        prev = preview_cambio_horario(
            session, plan_id, "noexiste", "Lunes",
            time(8, 0), time(10, 0),
        )
        assert prev.error is not None
        assert prev.es_seguro is False

    def test_preview_hora_fin_invalida(self, session):
        plan_id = _seed(session)
        h = _add_materia_con_horarios(
            session, plan_id, "M1",
            hteo=4, hlab=0, horarios_tipos=[None],
        )[0]
        prev = preview_cambio_horario(
            session, plan_id, h.id, "Martes",
            time(10, 0), time(8, 0),  # fin < inicio
        )
        assert prev.error is not None
        assert "fin" in prev.error.lower()

    def test_preview_sin_conflictos_es_seguro(self, session):
        plan_id = _seed(session)
        h = _add_materia_con_horarios(
            session, plan_id, "M1",
            hteo=4, hlab=0, horarios_tipos=[None],
        )[0]
        # Mover a otro día/franja, sin otras comisiones del plan.
        prev = preview_cambio_horario(
            session, plan_id, h.id, "Miércoles",
            time(14, 0), time(16, 0),
        )
        assert prev.error is None
        assert prev.es_seguro is True
        assert prev.conflictos_agregados == []
        # Y NO se persistió el cambio.
        h_after = session.get(HorarioDB, h.id)
        assert h_after is not None
        assert h_after.dia != "Miércoles"

    def test_aplicar_persiste(self, session):
        plan_id = _seed(session)
        h = _add_materia_con_horarios(
            session, plan_id, "M1",
            hteo=4, hlab=0, horarios_tipos=[None],
        )[0]
        ok = aplicar_cambio_horario(
            session, h.id, "Viernes", time(15, 0), time(17, 0),
        )
        assert ok is True
        h_after = session.get(HorarioDB, h.id)
        assert h_after is not None
        assert h_after.dia == "Viernes"
        assert h_after.hora_inicio == time(15, 0)
        assert h_after.hora_fin == time(17, 0)

    def test_aplicar_horario_inexistente(self, session):
        plan_id = _seed(session)
        ok = aplicar_cambio_horario(
            session, "noexiste", "Lunes",
            time(8, 0), time(10, 0),
        )
        assert ok is False

    def test_preview_duplicado_mismo_dia(self, session):
        plan_id = _seed(session)
        # Materia con dos horarios el lunes (h0 8-10, h1 10-12) — caso
        # típico de comisión con dos clases mismo día (no es lo normal).
        hs = _add_materia_con_horarios(
            session, plan_id, "M1",
            hteo=4, hlab=0, horarios_tipos=[None, None],
        )
        h0, h1 = hs[0], hs[1]
        # Intento mover h0 al jueves donde está libre → no debería detectar duplicado.
        prev = preview_cambio_horario(
            session, plan_id, h0.id, "Jueves",
            time(14, 0), time(16, 0),
        )
        assert prev.duplicados_mismo_dia == []
        # Ahora intento mover h0 al lunes (donde sigue h1) → debería detectar.
        prev2 = preview_cambio_horario(
            session, plan_id, h0.id, "Lunes",
            time(14, 0), time(16, 0),
        )
        assert len(prev2.duplicados_mismo_dia) == 1
        assert prev2.duplicados_mismo_dia[0]["horario_id"] == h1.id
        assert prev2.es_seguro is False
