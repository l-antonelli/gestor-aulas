"""Tests for plan-scoped validation functions."""

import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CarreraDB, MateriaDB, CicloDB,
    PlanCarreraVersionDB, PlanEstudioDB, CicloPlanVersionDB,
    PlanificacionCursadaDB, ComisionDB, HorarioDB,
    DictadoDB, DictadoCicloDB,
)
from src.services.validations import (
    validar_conflictos_horarios_plan,
    validar_cobertura_plan,
    identificar_virtuales_plan,
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
def base_data(session):
    """Create carrera, plan version, ciclo, and link them together."""
    carrera = CarreraDB(codigo="ING", nombre="Ingenieria", duracion_anios=5)
    session.add(carrera)
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()), carrera_codigo="ING",
        nombre="Plan v1", fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()

    link = CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id)
    session.add(link)
    session.commit()

    return {"carrera": carrera, "pv": pv, "ciclo": ciclo}


class TestValidarConflictosHorariosPlan:
    """Tests for validar_conflictos_horarios_plan."""

    def test_no_conflicts_when_different_times(self, session, base_data):
        """Two materias at different times should not conflict."""
        pv = base_data["pv"]
        ciclo = base_data["ciclo"]

        # Two materias in same year/cuatrimestre
        m1 = MateriaDB(codigo="M1", nombre="Materia 1", periodo="cuatrimestral")
        m2 = MateriaDB(codigo="M2", nombre="Materia 2", periodo="cuatrimestral")
        session.add_all([m1, m2])
        session.flush()

        for m in [m1, m2]:
            session.add(PlanEstudioDB(
                plan_version_id=pv.id, materia_codigo=m.codigo,
                carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
            ))

        # Create plan with comisiones at different times
        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Test",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com1 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="M1",
            plan_cursada_id=plan.id, comision_key="M1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        com2 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="M2",
            plan_cursada_id=plan.id, comision_key="M2-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add_all([com1, com2])
        session.flush()

        # M1: Lunes 8-10, M2: Lunes 10-12 — no overlap
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com1.id,
            codigo_materia="M1", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com2.id,
            codigo_materia="M2", dia="Lunes",
            hora_inicio=time(10, 0), hora_fin=time(12, 0),
        ))
        session.commit()

        result = validar_conflictos_horarios_plan(session, plan.id)
        assert result.valid is True

    def test_detects_conflict_same_day_overlap(self, session, base_data):
        """Two materias overlapping on the same day should be detected."""
        pv = base_data["pv"]
        ciclo = base_data["ciclo"]

        m1 = MateriaDB(codigo="C1", nombre="Conflicto 1", periodo="cuatrimestral")
        m2 = MateriaDB(codigo="C2", nombre="Conflicto 2", periodo="cuatrimestral")
        session.add_all([m1, m2])
        session.flush()

        for m in [m1, m2]:
            session.add(PlanEstudioDB(
                plan_version_id=pv.id, materia_codigo=m.codigo,
                carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
            ))

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Conflict",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com1 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="C1",
            plan_cursada_id=plan.id, comision_key="C1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        com2 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="C2",
            plan_cursada_id=plan.id, comision_key="C2-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add_all([com1, com2])
        session.flush()

        # C1: Lunes 8-10, C2: Lunes 9-11 — overlap!
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com1.id,
            codigo_materia="C1", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com2.id,
            codigo_materia="C2", dia="Lunes",
            hora_inicio=time(9, 0), hora_fin=time(11, 0),
        ))
        session.commit()

        result = validar_conflictos_horarios_plan(session, plan.id)
        assert result.valid is False
        assert len(result.details) == 1
        assert "C1" in result.details[0] and "C2" in result.details[0]

    def test_different_years_no_conflict(self, session, base_data):
        """Materias in different years should NOT conflict even with same time."""
        pv = base_data["pv"]
        ciclo = base_data["ciclo"]

        m1 = MateriaDB(codigo="Y1", nombre="Year1", periodo="cuatrimestral")
        m2 = MateriaDB(codigo="Y2", nombre="Year2", periodo="cuatrimestral")
        session.add_all([m1, m2])
        session.flush()

        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="Y1",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="Y2",
            carrera_codigo="ING", anio_plan=2, cuatrimestre_plan="1C",
        ))

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="DiffYear",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com1 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="Y1",
            plan_cursada_id=plan.id, comision_key="Y1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        com2 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="Y2",
            plan_cursada_id=plan.id, comision_key="Y2-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add_all([com1, com2])
        session.flush()

        # Same time but different years — should NOT conflict
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com1.id,
            codigo_materia="Y1", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com2.id,
            codigo_materia="Y2", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.commit()

        result = validar_conflictos_horarios_plan(session, plan.id)
        assert result.valid is True

    def test_anual_included_in_cuatrimestral_check(self, session, base_data):
        """An annual materia should be checked against cuatrimestral materias
        of the same year."""
        pv = base_data["pv"]
        ciclo = base_data["ciclo"]

        m_cuatri = MateriaDB(codigo="CU1", nombre="Cuatrimestral", periodo="cuatrimestral")
        m_anual = MateriaDB(codigo="AN1", nombre="Anual", periodo="anual")
        session.add_all([m_cuatri, m_anual])
        session.flush()

        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="CU1",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="AN1",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="Anual",
        ))

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Anual",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com1 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="CU1",
            plan_cursada_id=plan.id, comision_key="CU1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        com2 = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="AN1",
            plan_cursada_id=plan.id, comision_key="AN1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add_all([com1, com2])
        session.flush()

        # Same time: should conflict because annual overlaps with 1C
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com1.id,
            codigo_materia="CU1", dia="Martes",
            hora_inicio=time(14, 0), hora_fin=time(16, 0),
        ))
        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com2.id,
            codigo_materia="AN1", dia="Martes",
            hora_inicio=time(14, 0), hora_fin=time(16, 0),
        ))
        session.commit()

        result = validar_conflictos_horarios_plan(session, plan.id)
        assert result.valid is False
        assert len(result.details) >= 1

    def test_nonexistent_plan(self, session):
        result = validar_conflictos_horarios_plan(session, "NONEXISTENT")
        assert result.valid is True


class TestValidarCoberturaPlan:
    """Tests for validar_cobertura_plan."""

    def test_all_covered(self, session, base_data):
        """When all active dictados have comisiones with horarios, valid=True."""
        pv = base_data["pv"]
        ciclo = base_data["ciclo"]

        m1 = MateriaDB(codigo="COV1", nombre="Covered", periodo="cuatrimestral")
        session.add(m1)
        session.flush()

        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="COV1",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))

        # Create dictado for this materia
        dictado = DictadoDB(
            id=str(uuid.uuid4()), materia_codigo="COV1",
            dictado_codigo="COV1-2025-1C", activo=True,
        )
        session.add(dictado)
        session.flush()
        session.add(DictadoCicloDB(dictado_id=dictado.id, ciclo_id=ciclo.id))

        # Create plan with comision + horario
        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Covered",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="COV1",
            plan_cursada_id=plan.id, comision_key="COV1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add(com)
        session.flush()

        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id,
            codigo_materia="COV1", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.commit()

        result = validar_cobertura_plan(session, plan.id, ciclo.id)
        assert result.valid is True

    def test_missing_coverage(self, session, base_data):
        """A dictado without comision in the plan should be flagged."""
        ciclo = base_data["ciclo"]

        m1 = MateriaDB(codigo="MISS1", nombre="Missing", periodo="cuatrimestral")
        session.add(m1)
        session.flush()

        dictado = DictadoDB(
            id=str(uuid.uuid4()), materia_codigo="MISS1",
            dictado_codigo="MISS1-2025-1C", activo=True,
        )
        session.add(dictado)
        session.flush()
        session.add(DictadoCicloDB(dictado_id=dictado.id, ciclo_id=ciclo.id))

        # Plan without any comisiones for MISS1
        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Missing",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.commit()

        result = validar_cobertura_plan(session, plan.id, ciclo.id)
        assert result.valid is False
        assert "MISS1" in result.details[0]

    def test_inactive_dictado_not_checked(self, session, base_data):
        """An inactive dictado should not trigger a coverage warning."""
        ciclo = base_data["ciclo"]

        m1 = MateriaDB(codigo="INACT1", nombre="Inactive", periodo="cuatrimestral")
        session.add(m1)
        session.flush()

        dictado = DictadoDB(
            id=str(uuid.uuid4()), materia_codigo="INACT1",
            dictado_codigo="INACT1-2025-1C", activo=False,
        )
        session.add(dictado)
        session.flush()
        session.add(DictadoCicloDB(dictado_id=dictado.id, ciclo_id=ciclo.id))

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Inactive",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.commit()

        result = validar_cobertura_plan(session, plan.id, ciclo.id)
        assert result.valid is True


class TestIdentificarVirtualesPlan:
    """Tests for identificar_virtuales_plan."""

    def test_identifies_virtual_materias_with_horarios(self, session, base_data):
        """Virtual materias with horarios should appear in details."""
        ciclo = base_data["ciclo"]

        m_virtual = MateriaDB(
            codigo="VIR1", nombre="Virtual 1",
            periodo="cuatrimestral", virtual=True,
        )
        session.add(m_virtual)
        session.flush()

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Virtual",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="VIR1",
            plan_cursada_id=plan.id, comision_key="VIR1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add(com)
        session.flush()

        session.add(HorarioDB(
            id=str(uuid.uuid4()), comision_id=com.id,
            codigo_materia="VIR1", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(10, 0),
        ))
        session.commit()

        result = identificar_virtuales_plan(session, plan.id)
        assert result.valid is True
        assert len(result.details) == 1
        assert "VIR1" in result.details[0]
        assert "no necesita aula" in result.details[0]

    def test_no_virtual_materias(self, session, base_data):
        """Plan with no virtual materias should return empty details."""
        ciclo = base_data["ciclo"]

        m = MateriaDB(
            codigo="NOV1", nombre="Not Virtual",
            periodo="cuatrimestral", virtual=False,
        )
        session.add(m)
        session.flush()

        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="NoVirtual",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.flush()

        com = ComisionDB(
            id=str(uuid.uuid4()), materia_codigo="NOV1",
            plan_cursada_id=plan.id, comision_key="NOV1-001",
            nombre="Com 1", numero=1, cupo=30,
        )
        session.add(com)
        session.commit()

        result = identificar_virtuales_plan(session, plan.id)
        assert result.valid is True
        assert "No hay materias virtuales" in result.message

    def test_empty_plan(self, session, base_data):
        ciclo = base_data["ciclo"]
        plan = PlanificacionCursadaDB(
            id=str(uuid.uuid4()), nombre="Empty",
            ciclo_id=ciclo.id, activo=False,
        )
        session.add(plan)
        session.commit()

        result = identificar_virtuales_plan(session, plan.id)
        assert result.valid is True
