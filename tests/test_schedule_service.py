"""Tests for schedule_service."""

import io
import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.database.models import CicloDB, MateriaDB, ScheduleDB, ScheduleEntryDB
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
    sync_preview_edits_to_schedule,
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
    m1 = MateriaDB(codigo="MAT101", nombre="Calculo I")
    m2 = MateriaDB(codigo="FIS101", nombre="Fisica I")
    session.add_all([m1, m2])
    session.commit()
    return [m1, m2]


class _FakeFile:
    """Fake file-like object for testing."""
    def __init__(self, content: str, name: str = "test.csv"):
        self.name = name
        self._buffer = io.StringIO(content)

    def read(self, *args, **kwargs):
        return self._buffer.read(*args, **kwargs)

    def seek(self, *args, **kwargs):
        return self._buffer.seek(*args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._buffer, name)


class TestCreateScheduleFromFile:

    def test_creates_schedule_with_entries(self, session, ciclo, materias):
        csv_content = (
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Lunes,08:00,10:00\n"
            "FIS101,Martes,14:00,16:00\n"
        )
        fake_file = _FakeFile(csv_content)

        result = create_schedule_from_file(
            session, "2025-2C", "Horarios 2C 2025", fake_file
        )

        assert result.schedule is not None
        assert result.entries_created == 2
        assert result.errors == []

        # Verify schedule exists
        schedules = get_schedules_for_ciclo(session, "2025-2C")
        assert len(schedules) == 1
        assert schedules[0].nombre == "Horarios 2C 2025"

        # Verify entries
        entries = get_schedule_entries(session, result.schedule.id)
        assert len(entries) == 2

    def test_unresolved_materia_skipped(self, session, ciclo, materias):
        csv_content = (
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Lunes,08:00,10:00\n"
            "NONEXIST,Martes,14:00,16:00\n"
        )
        fake_file = _FakeFile(csv_content)

        result = create_schedule_from_file(
            session, "2025-2C", "Test", fake_file
        )

        assert result.entries_created == 1
        assert any("NONEXIST" in e for e in result.errors)

    def test_invalid_ciclo(self, session):
        csv_content = "codigo_materia,dia,hora_inicio,hora_fin\nMAT101,Lunes,08:00,10:00\n"
        fake_file = _FakeFile(csv_content)

        result = create_schedule_from_file(
            session, "NONEXISTENT", "Test", fake_file
        )

        assert result.schedule is None
        assert any("no encontrado" in e for e in result.errors)

    def test_invalid_file_format(self, session, ciclo):
        csv_content = "wrong_col1,wrong_col2\nfoo,bar\n"
        fake_file = _FakeFile(csv_content)

        result = create_schedule_from_file(
            session, "2025-2C", "Test", fake_file
        )

        assert result.entries_created == 0
        assert len(result.errors) > 0

    def test_guarani_resolution(self, session, ciclo):
        # Create materia with guarani code
        m = MateriaDB(codigo="MAT200", nombre="Algebra", codigo_guarani="G200")
        session.add(m)
        session.commit()

        csv_content = (
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "G200,Lunes,08:00,10:00\n"
        )
        fake_file = _FakeFile(csv_content)

        result = create_schedule_from_file(
            session, "2025-2C", "Test", fake_file
        )

        assert result.entries_created == 1
        assert len(result.warnings) == 1
        assert "codigo_guarani" in result.warnings[0]

        entries = get_schedule_entries(session, result.schedule.id)
        assert entries[0].codigo_materia == "MAT200"


class TestSyncPreviewEditsToSchedule:
    """Tests for sync_preview_edits_to_schedule."""

    def _make_schedule(self, session, ciclo):
        """Helper: create schedule with 2 entries for MAT101."""
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="Sync Test", fecha_upload=date.today(),
        )
        session.add(sched)
        session.flush()

        e1 = ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        e2 = ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Martes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        )
        session.add_all([e1, e2])
        session.commit()
        return sched, [e1, e2]

    def test_sync_updates_existing_entry(self, session, ciclo, materias):
        sched, [e1, e2] = self._make_schedule(session, ciclo)

        edited = [
            {"entry_id": e1.id, "dia": "Miércoles",
             "hora_inicio": time(10, 0), "hora_fin": time(12, 0)},
            {"entry_id": e2.id, "dia": e2.dia,
             "hora_inicio": e2.hora_inicio, "hora_fin": e2.hora_fin},
        ]

        updated, created, deleted = sync_preview_edits_to_schedule(
            session, sched.id, "MAT101", edited,
        )

        assert updated == 1
        assert created == 0
        assert deleted == 0

        refreshed = session.get(ScheduleEntryDB, e1.id)
        assert refreshed.dia == "Miércoles"
        assert refreshed.hora_inicio == time(10, 0)

    def test_sync_creates_new_entry(self, session, ciclo, materias):
        sched, [e1, e2] = self._make_schedule(session, ciclo)

        edited = [
            {"entry_id": e1.id, "dia": e1.dia,
             "hora_inicio": e1.hora_inicio, "hora_fin": e1.hora_fin},
            {"entry_id": e2.id, "dia": e2.dia,
             "hora_inicio": e2.hora_inicio, "hora_fin": e2.hora_fin},
            {"entry_id": "new_0_0", "dia": "Jueves",
             "hora_inicio": time(14, 0), "hora_fin": time(16, 0)},
        ]

        updated, created, deleted = sync_preview_edits_to_schedule(
            session, sched.id, "MAT101", edited,
        )

        assert updated == 0
        assert created == 1
        assert deleted == 0

        all_entries = get_schedule_entries(session, sched.id)
        mat_entries = [e for e in all_entries if e.codigo_materia == "MAT101"]
        assert len(mat_entries) == 3

    def test_sync_deletes_removed_entry(self, session, ciclo, materias):
        sched, [e1, e2] = self._make_schedule(session, ciclo)

        # Only include e1 — e2 should be deleted
        edited = [
            {"entry_id": e1.id, "dia": e1.dia,
             "hora_inicio": e1.hora_inicio, "hora_fin": e1.hora_fin},
        ]

        updated, created, deleted = sync_preview_edits_to_schedule(
            session, sched.id, "MAT101", edited,
        )

        assert updated == 0
        assert created == 0
        assert deleted == 1

        all_entries = get_schedule_entries(session, sched.id)
        mat_entries = [e for e in all_entries if e.codigo_materia == "MAT101"]
        assert len(mat_entries) == 1

    def test_sync_mixed_operations(self, session, ciclo, materias):
        sched, [e1, e2] = self._make_schedule(session, ciclo)

        edited = [
            # e1: update dia
            {"entry_id": e1.id, "dia": "Viernes",
             "hora_inicio": e1.hora_inicio, "hora_fin": e1.hora_fin},
            # e2 removed (not in list) → delete
            # new entry → create
            {"entry_id": "new_1_0", "dia": "Sábado",
             "hora_inicio": time(9, 0), "hora_fin": time(11, 0)},
        ]

        updated, created, deleted = sync_preview_edits_to_schedule(
            session, sched.id, "MAT101", edited,
        )

        assert updated == 1
        assert created == 1
        assert deleted == 1
