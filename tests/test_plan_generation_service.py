"""Tests for plan_generation_service."""

import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CicloDB, MateriaDB, ScheduleDB, ScheduleEntryDB,
    PlanificacionCursadaDB, ComisionDB, HorarioDB,
    ConfiguracionHoraria,
)
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    activate_plan,
    generate_time_slots,
    build_timetable_grid,
)


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
def ciclo(session):
    c = CicloDB(
        id="2025-2C", anio=2025, numero=2,
        fecha_inicio=date(2025, 8, 11), fecha_fin=date(2025, 12, 5),
    )
    session.add(c)
    session.commit()
    return c


@pytest.fixture
def materias(session):
    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        horas_semanales=4, cupo=30,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        horas_semanales=6, cupo=25,
    )
    session.add_all([m1, m2])
    session.commit()
    return [m1, m2]


@pytest.fixture
def schedule(session, ciclo, materias):
    s = ScheduleDB(
        id="sched-1", ciclo_id="2025-2C",
        nombre="Test Schedule", fecha_upload=date(2025, 7, 1),
    )
    session.add(s)
    session.flush()

    entries = [
        ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id="sched-1",
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ),
        ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id="sched-1",
            codigo_materia="MAT101", dia="Miércoles",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ),
        ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id="sched-1",
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(14, 0), hora_fin=time(17, 0),
        ),
        ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id="sched-1",
            codigo_materia="FIS101", dia="Jueves",
            hora_inicio=time(14, 0), hora_fin=time(17, 0),
        ),
    ]
    session.add_all(entries)
    session.commit()
    return s


class TestGeneratePlanFromSchedule:

    def test_generates_plan_with_comisiones_and_horarios(self, session, schedule):
        result = generate_plan_from_schedule(
            session, "sched-1", "Plan Test", "2025-2C"
        )

        assert result.plan is not None
        assert result.plan.nombre == "Plan Test"
        assert result.plan.activo is False
        assert result.comisiones_created >= 2
        assert result.horarios_created == 4
        assert result.errors == []

    def test_comision_has_plan_cursada_id(self, session, schedule):
        result = generate_plan_from_schedule(
            session, "sched-1", "Plan Test", "2025-2C"
        )

        comisiones = session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == result.plan.id)
        ).all()

        assert len(comisiones) >= 2
        for c in comisiones:
            assert c.comision_key != ""

    def test_invalid_schedule(self, session, ciclo):
        result = generate_plan_from_schedule(
            session, "NONEXISTENT", "Test", "2025-2C"
        )

        assert result.plan is None
        assert any("no encontrado" in e for e in result.errors)


class TestActivatePlan:

    def test_activate_plan(self, session, schedule):
        result = generate_plan_from_schedule(
            session, "sched-1", "Plan A", "2025-2C"
        )
        plan_id = result.plan.id

        success = activate_plan(session, plan_id)
        assert success is True

        plan = session.get(PlanificacionCursadaDB, plan_id)
        assert plan.activo is True

    def test_activate_deactivates_others(self, session, schedule):
        # Generate two plans
        result_a = generate_plan_from_schedule(
            session, "sched-1", "Plan A", "2025-2C"
        )
        activate_plan(session, result_a.plan.id)

        result_b = generate_plan_from_schedule(
            session, "sched-1", "Plan B", "2025-2C"
        )
        activate_plan(session, result_b.plan.id)

        plan_a = session.get(PlanificacionCursadaDB, result_a.plan.id)
        plan_b = session.get(PlanificacionCursadaDB, result_b.plan.id)

        assert plan_a.activo is False
        assert plan_b.activo is True

    def test_activate_nonexistent_returns_false(self, session):
        assert activate_plan(session, "NONEXISTENT") is False


class TestGenerateTimeSlots:
    """Tests for generate_time_slots."""

    def test_basic_slots(self):
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(12, 0),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 4
        assert slots[0] == (time(8, 0), time(9, 0))
        assert slots[-1] == (time(11, 0), time(12, 0))

    def test_30_min_granularity(self):
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=30,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(10, 0),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 4
        assert slots[0] == (time(8, 0), time(8, 30))
        assert slots[1] == (time(8, 30), time(9, 0))

    def test_incomplete_slot_excluded(self):
        """If remaining time is less than granularity, no extra slot is created."""
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(9, 30),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 1
        assert slots[0] == (time(8, 0), time(9, 0))

    def test_empty_when_range_too_small(self):
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(8, 30),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 0


class TestBuildTimetableGrid:
    """Tests for build_timetable_grid."""

    def test_builds_grid_from_plan(self, session, ciclo, materias, schedule):
        """build_timetable_grid returns blocks grouped by day."""
        result = generate_plan_from_schedule(session, schedule.id, "Test Plan", ciclo.id)
        assert result.plan is not None

        config = ConfiguracionHoraria(
            id=1, granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(22, 0),
        )
        grid = build_timetable_grid(session, result.plan.id, config)

        assert len(grid) > 0
        # Should have "Lunes" since our fixtures create a Lunes entry
        assert "Lunes" in grid
        blocks = grid["Lunes"]
        assert len(blocks) >= 1
        assert blocks[0].materia_codigo == "MAT101"

    def test_empty_grid_for_plan_without_comisiones(self, session):
        """A plan with no comisiones returns an empty grid."""
        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Empty", ciclo_id="fake", activo=False,
        )
        session.add(plan)
        session.flush()

        config = ConfiguracionHoraria(id=1)
        grid = build_timetable_grid(session, plan.id, config)
        assert grid == {}

    def test_filter_by_materia(self, session, ciclo, materias, schedule):
        """Filtering by materia codes limits the grid output."""
        result = generate_plan_from_schedule(session, schedule.id, "Test Plan", ciclo.id)
        config = ConfiguracionHoraria(id=1)

        # Filter to only MAT101
        grid = build_timetable_grid(
            session, result.plan.id, config,
            filtered_materia_codigos={"MAT101"},
        )

        all_codes = {b.materia_codigo for blocks in grid.values() for b in blocks}
        assert "MAT101" in all_codes
        # FIS101 should not appear
        assert "FIS101" not in all_codes
