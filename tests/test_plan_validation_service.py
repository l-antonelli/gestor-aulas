"""Tests para plan_validation_service.

Cubre los 6 casos especificados en el plan:
- test_validar_plan_sin_comisiones
- test_cobertura_excluye_virtuales_optativas
- test_conflictos_ignorados_no_aparecen
- test_persist_y_get_latest
- test_is_validation_stale_por_cambio_de_horarios
- test_is_validation_stale_por_cambio_de_toggle
"""

import uuid
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
)
from src.services.dictado_service import create_dictados_for_ciclo
from src.services.plan_validation_service import (
    add_ignored_pair,
    get_latest_validation,
    is_validation_stale,
    persist_validation,
    validar_plan,
)


# -----------------------------------------------------------------------------
# Fixtures
# -----------------------------------------------------------------------------

@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def setup_basic(session):
    """Carrera + plan version + 2 materias + ciclo + plan vacio."""
    carrera = CarreraDB(codigo="ING", nombre="Ingenieria")
    session.add(carrera)
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()), carrera_codigo="ING",
        nombre="Plan v1", fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    )
    session.add_all([m1, m2])
    session.flush()

    for m in (m1, m2):
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo=m.codigo,
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))

    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))

    plan = PlanificacionCursadaDB(
        id=str(uuid.uuid4()), nombre="Plan Test",
        ciclo_id=ciclo.id, activo=False,
    )
    session.add(plan)
    session.commit()

    return {
        "ciclo": ciclo, "pv": pv,
        "m1": m1, "m2": m2,
        "plan": plan,
    }


def _add_comision_with_horario(
    session: Session, plan_id: str, materia_codigo: str,
    comision_key: str, dia: str, hora_inicio: time, hora_fin: time,
    numero: int = 1,
) -> ComisionDB:
    com = ComisionDB(
        id=str(uuid.uuid4()), materia_codigo=materia_codigo,
        plan_cursada_id=plan_id, comision_key=comision_key,
        nombre=f"Com {numero}", numero=numero, cupo=30,
    )
    session.add(com)
    session.flush()
    session.add(HorarioDB(
        id=str(uuid.uuid4()), comision_id=com.id,
        codigo_materia=materia_codigo, dia=dia,
        hora_inicio=hora_inicio, hora_fin=hora_fin,
    ))
    session.commit()
    return com


# -----------------------------------------------------------------------------
# Tests
# -----------------------------------------------------------------------------

class TestSinComisiones:
    def test_validar_plan_sin_comisiones(self, session, setup_basic):
        """Plan sin comisiones devuelve summary con error poblado."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        create_dictados_for_ciclo(session, ciclo.id)

        summary = validar_plan(session, plan.id)

        assert summary.error is not None
        assert "comisiones" in summary.error.lower()
        assert summary.n_clases == 0
        assert summary.n_materias == 0


class TestCoberturaConToggle:
    def test_cobertura_excluye_solo_optativas(
        self, session, setup_basic,
    ):
        """Toggle exclude_optativas filtra SOLO optativas; las virtuales
        siguen contando para cobertura."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        pv = setup_basic["pv"]

        # Marcar FIS101 como virtual (debe seguir contando)
        fis = setup_basic["m2"]
        fis.virtual = True
        session.add(fis)
        # Agregar una nueva materia OPTATIVA
        opt = MateriaDB(
            codigo="OPT101", nombre="Seminario Optativo",
            periodo="cuatrimestral", active=True, horas_semanales=3,
        )
        session.add(opt)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="OPT101",
            carrera_codigo="ING", anio_plan=4, cuatrimestre_plan="1C",
            optativa=True,
        ))
        session.commit()

        create_dictados_for_ciclo(session, ciclo.id)

        # Plan con comisiones para MAT101 unicamente
        _add_comision_with_horario(
            session, plan.id, "MAT101", "MAT101-001",
            "Lunes", time(8, 0), time(10, 0),
        )

        # Sin toggle: esperadas=3 (MAT101 + FIS101 virtual + OPT101)
        s_off = validar_plan(session, plan.id, exclude_optativas=False)
        assert s_off.error is None
        assert s_off.n_esperadas == 3
        assert "MAT101" in s_off.esperadas
        assert "FIS101" in s_off.esperadas  # virtual: cuenta
        assert "OPT101" in s_off.esperadas

        # Con toggle: OPT101 sale, FIS101 sigue (virtual no es optativa)
        s_on = validar_plan(session, plan.id, exclude_optativas=True)
        assert s_on.error is None
        assert s_on.n_esperadas == 2
        assert "OPT101" not in s_on.esperadas
        assert "FIS101" in s_on.esperadas  # virtual: sigue contando
        assert "MAT101" in s_on.esperadas


class TestConflictosIgnorados:
    def test_conflictos_ignorados_no_aparecen(self, session, setup_basic):
        """Un par agregado a IgnoredConflictDB no aparece como conflicto
        activo y se cuenta en n_conflictos_ignorados."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        create_dictados_for_ciclo(session, ciclo.id)

        # Conflicto: ambas materias en Lunes 8-10 (mismo año/cuatri)
        _add_comision_with_horario(
            session, plan.id, "MAT101", "MAT101-001",
            "Lunes", time(8, 0), time(10, 0),
        )
        _add_comision_with_horario(
            session, plan.id, "FIS101", "FIS101-001",
            "Lunes", time(8, 0), time(10, 0),
        )

        s_pre = validar_plan(session, plan.id)
        assert s_pre.n_conflictos_horarios >= 1
        assert s_pre.n_conflictos_ignorados == 0

        # Ignorar el par MAT101 vs FIS101
        add_ignored_pair(
            session, plan.id, "MAT101", "FIS101", razon="prueba",
        )

        s_post = validar_plan(session, plan.id)
        # No debe aparecer como conflicto activo
        assert s_post.n_conflictos_horarios == 0
        # Debe aparecer en ignorados
        assert s_post.n_conflictos_ignorados >= 1
        assert len(s_post.conflictos_ignorados) >= 1


class TestPersistencia:
    def test_persist_y_get_latest(self, session, setup_basic):
        """Round-trip: validar → persistir → leer ultima validacion."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        create_dictados_for_ciclo(session, ciclo.id)

        _add_comision_with_horario(
            session, plan.id, "MAT101", "MAT101-001",
            "Lunes", time(8, 0), time(10, 0),
        )

        summary = validar_plan(session, plan.id)
        record = persist_validation(session, summary)

        assert record.id is not None
        assert record.plan_cursada_id == plan.id
        assert record.n_materias == summary.n_materias
        assert record.n_esperadas == summary.n_esperadas
        assert record.excluir_optativas == summary.excluir_optativas

        latest = get_latest_validation(session, plan.id)
        assert latest is not None
        assert latest.id == record.id


class TestStaleness:
    def test_is_validation_stale_por_cambio_de_horarios(
        self, session, setup_basic,
    ):
        """Agregar un horario nuevo invalida la validacion persistida."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        create_dictados_for_ciclo(session, ciclo.id)

        com = _add_comision_with_horario(
            session, plan.id, "MAT101", "MAT101-001",
            "Lunes", time(8, 0), time(10, 0),
        )

        summary = validar_plan(session, plan.id)
        record = persist_validation(session, summary)

        assert is_validation_stale(session, record) is False

        # Agregar otro horario a la misma comision → cambia horario_count
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id,
            codigo_materia="MAT101", dia="Martes",
            hora_inicio=time(10, 0), hora_fin=time(12, 0),
        ))
        session.commit()

        assert is_validation_stale(session, record) is True

    def test_is_validation_stale_por_cambio_de_toggle(
        self, session, setup_basic,
    ):
        """Cambiar el toggle exclude_optativas invalida la validacion."""
        ciclo = setup_basic["ciclo"]
        plan = setup_basic["plan"]
        create_dictados_for_ciclo(session, ciclo.id)

        _add_comision_with_horario(
            session, plan.id, "MAT101", "MAT101-001",
            "Lunes", time(8, 0), time(10, 0),
        )

        # Persistir validacion con toggle OFF
        summary = validar_plan(session, plan.id, exclude_optativas=False)
        record = persist_validation(session, summary)

        # Sin pasar toggle, no es stale (snapshot stable)
        assert is_validation_stale(session, record) is False

        # Pasando el mismo toggle, no es stale
        assert is_validation_stale(
            session, record, current_exclude_optativas=False,
        ) is False

        # Pasando toggle distinto, es stale
        assert is_validation_stale(
            session, record, current_exclude_optativas=True,
        ) is True
