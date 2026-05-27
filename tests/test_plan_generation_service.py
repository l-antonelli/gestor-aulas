"""Tests for plan_generation_service."""

import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CicloDB, MateriaDB, ScheduleDB, ScheduleEntryDB,
    PlanificacionCursadaDB, ComisionDB, HorarioDB,
    ConfiguracionHoraria, InscripcionHistoricaDB,
)
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    generate_plan_from_preview,
    preview_plan_from_schedule,
    activate_plan,
    generate_time_slots,
    build_timetable_grid,
    _derive_comisiones,
    apply_horario_edits,
    normalize_coef_asignacion,
    update_comision_coef,
    get_coef_sum_por_materia,
    get_inscriptos_esperados_por_comision,
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
    """Tests for generate_time_slots.

    hora_fin_operativo represents the START of the last time slot,
    not the end of operations. A slot starting at that time is always included.
    """

    def test_basic_slots(self):
        """hora_fin_operativo=11:00 means last slot starts at 11:00."""
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(11, 0),
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
            hora_fin_operativo=time(9, 30),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 4
        assert slots[0] == (time(8, 0), time(8, 30))
        assert slots[1] == (time(8, 30), time(9, 0))

    def test_single_slot_when_start_equals_fin(self):
        """When start == fin, exactly one slot is generated."""
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(8, 0),
            hora_fin_operativo=time(8, 0),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 1
        assert slots[0] == (time(8, 0), time(9, 0))

    def test_midnight_wrap(self):
        """Last slot 23:00-00:00 wraps around midnight correctly."""
        config = ConfiguracionHoraria(
            id=1,
            granularidad_minutos=60,
            hora_inicio_operativo=time(22, 0),
            hora_fin_operativo=time(23, 0),
        )
        slots = generate_time_slots(config)
        assert len(slots) == 2
        assert slots[0] == (time(22, 0), time(23, 0))
        assert slots[1] == (time(23, 0), time(0, 0))


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


def _make_entry(schedule_id, codigo, dia, hi, hf):
    """Helper to create a ScheduleEntryDB."""
    return ScheduleEntryDB(
        id=str(uuid.uuid4()),
        schedule_id=schedule_id,
        codigo_materia=codigo,
        dia=dia,
        hora_inicio=hi,
        hora_fin=hf,
    )


class TestDeriveComisionesParalelas:
    """Tests for _derive_comisiones with max_clases_paralelas constraint."""

    def test_max_paralelas_forces_minimum_comisiones(self):
        """3 entries in same slot, ratio says 1 comision → n_comisiones=3,
        flag 'needs_more_comisiones'."""
        entries = [
            _make_entry("s", "MAT1", "Lunes", time(8, 0), time(10, 0))
            for _ in range(3)
        ]

        n_com, max_par, flag, detail = _derive_comisiones(
            entries,
            horas_semanales=6,  # 6h total / 6h = 1 by ratio
            optativa=False,
            n_carreras=2,
        )

        assert max_par == 3
        assert n_com == 3
        assert flag == "needs_more_comisiones"

    def test_exclusive_carrera_with_parallel_classes(self):
        """Materia exclusive to 1 carrera with 2 parallel entries →
        n_comisiones=2 (not hardcoded 1)."""
        entries = [
            _make_entry("s", "MAT2", "Lunes", time(8, 0), time(10, 0))
            for _ in range(2)
        ]

        n_com, max_par, flag, detail = _derive_comisiones(
            entries,
            horas_semanales=2,
            optativa=False,
            n_carreras=1,
        )

        assert max_par == 2
        assert n_com == 2
        assert flag == "needs_more_comisiones"

    def test_optativa_respects_paralelas(self):
        """Optativa with 2 parallel entries → n_comisiones=2."""
        entries = [
            _make_entry("s", "OPT1", "Martes", time(14, 0), time(16, 0))
            for _ in range(2)
        ]

        n_com, max_par, flag, detail = _derive_comisiones(
            entries,
            horas_semanales=2,
            optativa=True,
            n_carreras=1,
        )

        assert max_par == 2
        assert n_com == 2
        assert flag == "needs_more_comisiones"

    def test_no_paralelas_optativa_stays_1(self):
        """Optativa with no parallel entries → stays 1 comision."""
        entries = [
            _make_entry("s", "OPT2", "Lunes", time(8, 0), time(10, 0)),
            _make_entry("s", "OPT2", "Martes", time(8, 0), time(10, 0)),
        ]

        n_com, max_par, flag, detail = _derive_comisiones(
            entries,
            horas_semanales=4,
            optativa=True,
            n_carreras=1,
        )

        assert max_par == 1
        assert n_com == 1
        assert flag == "exact"

    def test_shared_materia_exact_ratio_no_paralelas(self):
        """Shared materia with exact ratio and no paralelas → normal derivation."""
        entries = [
            _make_entry("s", "SH1", "Lunes", time(8, 0), time(10, 0)),
            _make_entry("s", "SH1", "Martes", time(8, 0), time(10, 0)),
            _make_entry("s", "SH1", "Miércoles", time(8, 0), time(10, 0)),
            _make_entry("s", "SH1", "Jueves", time(8, 0), time(10, 0)),
        ]

        n_com, max_par, flag, detail = _derive_comisiones(
            entries,
            horas_semanales=4,
            optativa=False,
            n_carreras=2,
        )

        assert max_par == 1
        assert n_com == 2  # 8h / 4h = 2
        assert flag == "exact"


class TestApplyHorarioEdits:
    """Tests for apply_horario_edits."""

    def _make_plan_with_horarios(self, session, ciclo, materias):
        """Helper: create plan with 1 comision, 2 horarios for MAT101."""
        result = generate_plan_from_schedule(session, "sched-1", "Edit Test", ciclo.id)
        assert result.plan is not None

        # Find MAT101 comision and its horarios
        mat_com = session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == result.plan.id)
            .where(ComisionDB.materia_codigo == "MAT101")
        ).first()
        assert mat_com is not None

        horarios = session.exec(
            select(HorarioDB).where(HorarioDB.comision_id == mat_com.id)
        ).all()
        return result.plan, mat_com, list(horarios)

    def test_update_existing_horario(self, session, ciclo, materias, schedule):
        plan, com, horarios = self._make_plan_with_horarios(session, ciclo, materias)
        h1 = horarios[0]

        edited = [
            {
                "horario_id": h1.id,
                "comision_numero": com.numero,
                "dia": "Viernes",
                "hora_inicio": time(10, 0),
                "hora_fin": time(12, 0),
            },
            {
                "horario_id": horarios[1].id,
                "comision_numero": com.numero,
                "dia": horarios[1].dia,
                "hora_inicio": horarios[1].hora_inicio,
                "hora_fin": horarios[1].hora_fin,
            },
        ]

        updated, created, deleted = apply_horario_edits(
            session, plan.id, "MAT101", edited,
        )

        assert updated == 1
        assert created == 0
        assert deleted == 0

        refreshed = session.get(HorarioDB, h1.id)
        assert refreshed.dia == "Viernes"
        assert refreshed.hora_inicio == time(10, 0)

    def test_create_new_horario(self, session, ciclo, materias, schedule):
        plan, com, horarios = self._make_plan_with_horarios(session, ciclo, materias)

        edited = [
            {
                "horario_id": h.id,
                "comision_numero": com.numero,
                "dia": h.dia,
                "hora_inicio": h.hora_inicio,
                "hora_fin": h.hora_fin,
            }
            for h in horarios
        ] + [{
            "horario_id": "new_0",
            "comision_numero": com.numero,
            "dia": "Sábado",
            "hora_inicio": time(9, 0),
            "hora_fin": time(11, 0),
        }]

        updated, created, deleted = apply_horario_edits(
            session, plan.id, "MAT101", edited,
        )

        assert updated == 0
        assert created == 1
        assert deleted == 0

    def test_delete_removed_horario(self, session, ciclo, materias, schedule):
        plan, com, horarios = self._make_plan_with_horarios(session, ciclo, materias)

        # Only keep first horario — second should be deleted
        edited = [{
            "horario_id": horarios[0].id,
            "comision_numero": com.numero,
            "dia": horarios[0].dia,
            "hora_inicio": horarios[0].hora_inicio,
            "hora_fin": horarios[0].hora_fin,
        }]

        updated, created, deleted = apply_horario_edits(
            session, plan.id, "MAT101", edited,
        )

        assert updated == 0
        assert created == 0
        assert deleted == 1

    def test_mixed_operations(self, session, ciclo, materias, schedule):
        plan, com, horarios = self._make_plan_with_horarios(session, ciclo, materias)

        edited = [
            # Update first
            {
                "horario_id": horarios[0].id,
                "comision_numero": com.numero,
                "dia": "Jueves",
                "hora_inicio": time(14, 0),
                "hora_fin": time(16, 0),
            },
            # Delete second (not in list)
            # Create new
            {
                "horario_id": "new_1",
                "comision_numero": com.numero,
                "dia": "Viernes",
                "hora_inicio": time(8, 0),
                "hora_fin": time(10, 0),
            },
        ]

        updated, created, deleted = apply_horario_edits(
            session, plan.id, "MAT101", edited,
        )

        assert updated == 1
        assert created == 1
        assert deleted == 1


class TestCoefAsignacion:
    """Tests para coef_asignacion en comisiones."""

    def _setup_plan_con_2_comisiones(self, session, ciclo, materias):
        """Setup helper: crea schedule con 2 entries paralelas → 2 comisiones."""
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="Test", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        # Dos entries paralelas en mismo slot → 2 comisiones
        for _ in range(2):
            session.add(ScheduleEntryDB(
                id=str(uuid.uuid4()), schedule_id=sched.id,
                codigo_materia="MAT101", dia="Lunes",
                hora_inicio=time(8, 0), hora_fin=time(11, 0),
            ))
        session.commit()
        plan = generate_plan_from_schedule(session, sched.id, "P1", ciclo.id).plan
        return plan

    def test_coef_uniforme_al_crear(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        comisiones = list(session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
        ).all())
        assert len(comisiones) == 2
        for c in comisiones:
            assert abs(c.coef_asignacion - 0.5) < 1e-9

    def test_normalize_reasigna_uniformemente(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        comisiones = list(session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
        ).all())
        # Romper la uniformidad
        comisiones[0].coef_asignacion = 0.7
        comisiones[1].coef_asignacion = 0.3
        session.add(comisiones[0])
        session.add(comisiones[1])
        session.commit()

        n = normalize_coef_asignacion(session, plan.id, "MAT101")
        assert n == 2

        for c in session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
        ).all():
            assert abs(c.coef_asignacion - 0.5) < 1e-9

    def test_update_coef_clamp(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        c = session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
        ).first()
        # Valor fuera de rango → clamp
        update_comision_coef(session, c.id, 1.5)
        session.refresh(c)
        assert c.coef_asignacion == 1.0
        update_comision_coef(session, c.id, -0.2)
        session.refresh(c)
        assert c.coef_asignacion == 0.0

    def test_get_coef_sum_por_materia(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        sums = get_coef_sum_por_materia(session, plan.id)
        assert "MAT101" in sums
        assert abs(sums["MAT101"] - 1.0) < 1e-9

    def test_inscriptos_esperados_por_comision(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        # Cargar serie historica para MAT101 cuatri "2C" (igual al ciclo)
        for anio, v in [(2022, 180), (2023, 200), (2024, 220)]:
            session.add(InscripcionHistoricaDB(
                materia_codigo="MAT101", anio=anio,
                cuatrimestre="2C", inscriptos=v,
            ))
        session.commit()

        # forecast_metodo_default del plan = "media_movil" → media = 200
        esperados = get_inscriptos_esperados_por_comision(session, plan.id)
        assert len(esperados) == 2
        for v in esperados.values():
            assert abs(v - 100.0) < 1e-9  # 200 × 0.5

    def test_inscriptos_esperados_sin_serie(self, session, ciclo, materias):
        plan = self._setup_plan_con_2_comisiones(session, ciclo, materias)
        esperados = get_inscriptos_esperados_por_comision(session, plan.id)
        assert esperados == {}


class TestGenerateFromPreviewExtended:
    """Tests del wizard: descripcion + forecast_metodo_default al generar."""

    def test_setea_forecast_metodo_default(self, session, ciclo, materias):
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="T", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        prev = preview_plan_from_schedule(session, sched.id)
        result = generate_plan_from_preview(
            session, sched.id, "Plan X", ciclo.id, prev.materias,
            descripcion="Desc test", forecast_metodo_default="ses",
        )
        assert result.plan is not None
        assert result.plan.forecast_metodo_default == "ses"
        assert result.plan.descripcion == "Desc test"

    def test_default_forecast_es_media_movil(self, session, ciclo, materias):
        sched = ScheduleDB(
            id=str(uuid.uuid4()), ciclo_id=ciclo.id,
            nombre="T", fecha_upload=date(2025, 3, 1),
        )
        session.add(sched)
        session.flush()
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        prev = preview_plan_from_schedule(session, sched.id)
        result = generate_plan_from_preview(
            session, sched.id, "Plan", ciclo.id, prev.materias,
        )
        assert result.plan.forecast_metodo_default == "media_movil"
