"""Tests for schedule_service."""

import io
import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import CicloDB, MateriaDB, ScheduleDB, ScheduleEntryDB
from src.services.schedule_service import (
    clonar_plan_a_cronograma,
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


# =============================================================================
# Fase F · Clonar plan a cronograma
# =============================================================================


class TestClonarPlanACronograma:
    """Tests para `clonar_plan_a_cronograma` (Fase F del rediseño 2026-09-15).

    Los tests arman un plan de cursada con comisiones + horarios y
    verifican que el schedule clonado sea equivalente estructuralmente
    pero con IDs nuevos y sin arrastrar `aula_id`.
    """

    def _armar_plan_con_datos(self, session, ciclo, materias):
        """Helper: crea un plan del ciclo con 2 comisiones + 3 horarios.

        - MAT101: 1 comisión con 2 horarios (uno con aula, otro sin).
        - FIS101: 1 comisión con 1 horario y `carrera_asignada`.
        """
        from src.database.models import (
            AulaDB, ComisionDB, HorarioDB, PlanificacionCursadaDB, SedeDB,
        )

        # Aula + sede (dummy) para poblar aula_id en algún horario.
        sede = SedeDB(id=str(uuid.uuid4()), nombre="Test-Sede")
        session.add(sede)
        session.flush()
        aula = AulaDB(
            id=str(uuid.uuid4()), sede_id=sede.id,
            codigo_aula="101", nombre="Aula 101",
            capacidad=50, tipo="Aula",
        )
        session.add(aula)
        session.flush()

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Plan Consolidado",
            ciclo_id=ciclo.id,
        )
        session.add(plan)
        session.flush()

        c_mat = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="MAT101",
            plan_cursada_id=plan.id,
            comision_key="MAT101-001", nombre="M1", numero=1,
            cupo=40, descripcion="descripcion mat",
            coef_asignacion=0.7,
        )
        c_fis = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="FIS101",
            plan_cursada_id=plan.id,
            comision_key="FIS101-001", nombre="F1", numero=1,
            cupo=30, descripcion="descripcion fis",
            coef_asignacion=1.0,
            carrera_asignada="ING",
        )
        session.add_all([c_mat, c_fis])
        session.flush()

        # Horarios: uno con aula, otros sin.
        h_mat_1 = HorarioDB(
            id=str(uuid.uuid4()), comision_id=c_mat.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            tipo_clase="teorica", aula_id=aula.id,
            virtual=False,
        )
        h_mat_2 = HorarioDB(
            id=str(uuid.uuid4()), comision_id=c_mat.id,
            codigo_materia="MAT101", dia="Miércoles",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            tipo_clase="laboratorio", aula_id=None,
        )
        h_fis = HorarioDB(
            id=str(uuid.uuid4()), comision_id=c_fis.id,
            codigo_materia="FIS101", dia="Martes",
            hora_inicio=time(14, 0), hora_fin=time(17, 0),
            virtual=True,
        )
        session.add_all([h_mat_1, h_mat_2, h_fis])
        session.commit()

        # También agregamos una carrera para el FK de carrera_asignada.
        from src.database.models import CarreraDB
        session.add(CarreraDB(codigo="ING", nombre="Ing"))
        session.commit()

        return {
            "plan": plan, "c_mat": c_mat, "c_fis": c_fis,
            "h_mat_1": h_mat_1, "h_mat_2": h_mat_2, "h_fis": h_fis,
            "aula": aula, "sede": sede,
        }

    def test_clona_estructura_completa(self, session, ciclo, materias):
        data = self._armar_plan_con_datos(session, ciclo, materias)
        plan = data["plan"]

        sched = clonar_plan_a_cronograma(
            session, plan.id, "Copia consolidada",
        )

        # Schedule creado y linkeado al mismo ciclo del plan.
        assert sched.nombre == "Copia consolidada"
        assert sched.ciclo_id == plan.ciclo_id
        assert sched.source_filename == f"clon:plan:{plan.id}"

        # 2 comisiones nuevas, con IDs distintos a los del plan.
        from src.database.models import ComisionDB
        coms_sched = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert len(coms_sched) == 2
        ids_plan = {data["c_mat"].id, data["c_fis"].id}
        ids_sched = {c.id for c in coms_sched}
        assert ids_plan.isdisjoint(ids_sched)

        # 3 entries nuevas.
        entries = get_schedule_entries(session, sched.id)
        assert len(entries) == 3

    def test_comision_preserva_atributos(self, session, ciclo, materias):
        data = self._armar_plan_con_datos(session, ciclo, materias)
        sched = clonar_plan_a_cronograma(session, data["plan"].id, "clon")

        from src.database.models import ComisionDB
        coms = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        by_mat = {c.materia_codigo: c for c in coms}

        # MAT101
        assert by_mat["MAT101"].nombre == "M1"
        assert by_mat["MAT101"].numero == 1
        assert by_mat["MAT101"].cupo == 40
        assert by_mat["MAT101"].descripcion == "descripcion mat"
        assert by_mat["MAT101"].coef_asignacion == 0.7
        assert by_mat["MAT101"].plan_cursada_id is None  # es del schedule
        assert by_mat["MAT101"].schedule_id == sched.id
        assert by_mat["MAT101"].dictado_id is None  # no se propaga

        # FIS101 con carrera_asignada
        assert by_mat["FIS101"].carrera_asignada == "ING"

    def test_entry_no_arrastra_aula_id(self, session, ciclo, materias):
        """Regresión de la Fase F: `HorarioDB.aula_id` del plan NO se
        propaga a `ScheduleEntryDB` — las entries del cronograma no
        tienen concepto de aula asignada.
        """
        data = self._armar_plan_con_datos(session, ciclo, materias)
        sched = clonar_plan_a_cronograma(session, data["plan"].id, "clon")

        entries = get_schedule_entries(session, sched.id)
        # ScheduleEntryDB no tiene atributo aula_id — la estructura misma
        # lo enforza. Verificamos que los atributos que sí se propagan
        # estén correctos.
        by_key = {(e.codigo_materia, e.dia): e for e in entries}

        e_lunes = by_key[("MAT101", "Lunes")]
        assert e_lunes.tipo_clase == "teorica"
        assert e_lunes.virtual is False

        e_mie = by_key[("MAT101", "Miércoles")]
        assert e_mie.tipo_clase == "laboratorio"

        e_mar = by_key[("FIS101", "Martes")]
        assert e_mar.virtual is True

        # Todos los entries deben tener comision_id apuntando a las
        # comisiones nuevas del schedule.
        from src.database.models import ComisionDB
        coms_sched_ids = {
            c.id for c in session.exec(
                select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
            ).all()
        }
        for e in entries:
            assert e.comision_id in coms_sched_ids

    def test_horas_y_dias_se_preservan(self, session, ciclo, materias):
        data = self._armar_plan_con_datos(session, ciclo, materias)
        sched = clonar_plan_a_cronograma(session, data["plan"].id, "clon")

        entries = get_schedule_entries(session, sched.id)
        by_key = {(e.codigo_materia, e.dia): e for e in entries}
        assert by_key[("MAT101", "Lunes")].hora_inicio == time(8, 0)
        assert by_key[("MAT101", "Lunes")].hora_fin == time(11, 0)
        assert by_key[("FIS101", "Martes")].hora_inicio == time(14, 0)
        assert by_key[("FIS101", "Martes")].hora_fin == time(17, 0)

    def test_ciclo_id_override(self, session, ciclo, materias):
        """Si se pasa ciclo_id_override, el schedule queda linkeado ahí
        en vez de al ciclo del plan.
        """
        data = self._armar_plan_con_datos(session, ciclo, materias)

        # Ciclo destino distinto.
        ciclo_2026 = CicloDB(
            id="2026-1C", anio=2026, numero=1,
            fecha_inicio=date(2026, 3, 1), fecha_fin=date(2026, 7, 5),
        )
        session.add(ciclo_2026)
        session.commit()

        sched = clonar_plan_a_cronograma(
            session, data["plan"].id, "clon2026",
            ciclo_id_override=ciclo_2026.id,
        )
        assert sched.ciclo_id == ciclo_2026.id
        assert sched.ciclo_id != data["plan"].ciclo_id

    def test_plan_inexistente_falla(self, session):
        with pytest.raises(ValueError, match="no existe"):
            clonar_plan_a_cronograma(session, "plan-fantasma", "x")

    def test_ciclo_override_inexistente_falla(
        self, session, ciclo, materias,
    ):
        data = self._armar_plan_con_datos(session, ciclo, materias)
        with pytest.raises(ValueError, match="no existe"):
            clonar_plan_a_cronograma(
                session, data["plan"].id, "x",
                ciclo_id_override="ciclo-fantasma",
            )

    def test_plan_vacio_crea_schedule_sin_entries(
        self, session, ciclo, materias,
    ):
        """Un plan sin comisiones se clona como schedule vacío — no
        levanta errores."""
        from src.database.models import PlanificacionCursadaDB
        plan_vacio = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Plan vacío",
            ciclo_id=ciclo.id,
        )
        session.add(plan_vacio)
        session.commit()

        sched = clonar_plan_a_cronograma(
            session, plan_vacio.id, "clon vacío",
        )
        assert sched.nombre == "clon vacío"
        assert get_schedule_entries(session, sched.id) == []
