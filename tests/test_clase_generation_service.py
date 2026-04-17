"""Tests for clase_generation_service."""

import uuid
import pytest
from datetime import date, time

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import (
    CicloDB, MateriaDB, PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB,
)
from src.services.clase_generation_service import (
    generate_clases_for_plan,
    _expand_dates,
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
def setup_data(session):
    """Create a full setup: ciclo, materia, plan, comision, horario."""
    ciclo = CicloDB(
        id="2025-2C", anio=2025, numero=2,
        # 2025-08-11 is Monday, 2025-08-22 is Friday (2 weeks)
        fecha_inicio=date(2025, 8, 11), fecha_fin=date(2025, 8, 22),
    )
    materia = MateriaDB(codigo="MAT101", nombre="Calculo I")

    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test",
        ciclo_id="2025-2C", activo=True,
    )

    comision = ComisionDB(
        id="com-1", materia_codigo="MAT101",
        plan_cursada_id="plan-1", comision_key="MAT101-001",
        nombre="Comision 1", numero=1, cupo=30,
    )

    horario = HorarioDB(
        id="hor-1", comision_id="com-1", codigo_materia="MAT101",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
    )

    session.add_all([ciclo, materia, plan, comision, horario])
    session.commit()
    return {"ciclo": ciclo, "plan": plan, "comision": comision, "horario": horario}


class TestExpandDates:

    def test_expand_mondays(self):
        # 2025-08-11 to 2025-08-22: Monday 11, Monday 18
        dates = _expand_dates(date(2025, 8, 11), date(2025, 8, 22), "Lunes")
        assert dates == [date(2025, 8, 11), date(2025, 8, 18)]

    def test_expand_fridays(self):
        # 2025-08-11 to 2025-08-22: Friday 15, Friday 22
        dates = _expand_dates(date(2025, 8, 11), date(2025, 8, 22), "Viernes")
        assert dates == [date(2025, 8, 15), date(2025, 8, 22)]

    def test_expand_no_match(self):
        # 2025-08-11 to 2025-08-15 (Mon-Fri): no Saturday
        dates = _expand_dates(date(2025, 8, 11), date(2025, 8, 15), "Sábado")
        assert dates == []

    def test_expand_invalid_dia(self):
        dates = _expand_dates(date(2025, 8, 11), date(2025, 8, 22), "Domingo")
        assert dates == []

    def test_expand_single_day(self):
        # Range is exactly one Monday
        dates = _expand_dates(date(2025, 8, 11), date(2025, 8, 11), "Lunes")
        assert dates == [date(2025, 8, 11)]


class TestGenerateClasesForPlan:

    def test_generates_clases(self, session, setup_data):
        result = generate_clases_for_plan(session, "plan-1")

        # 2 Mondays in the range
        assert result.clases_created == 2
        assert result.errors == []

        clases = session.exec(
            select(ClaseDB).where(ClaseDB.plan_cursada_id == "plan-1")
        ).all()
        assert len(clases) == 2

        # Check fields
        for clase in clases:
            assert clase.comision_id == "com-1"
            assert clase.horario_id == "hor-1"
            assert clase.hora_inicio == time(8, 0)
            assert clase.hora_fin == time(10, 0)
            assert clase.executed is False
            assert clase.aula_id is None

    def test_invalid_plan(self, session):
        result = generate_clases_for_plan(session, "NONEXISTENT")
        assert result.clases_created == 0
        assert any("no encontrado" in e for e in result.errors)

    def test_multiple_horarios(self, session, setup_data):
        # Add a Wednesday horario
        hor2 = HorarioDB(
            id="hor-2", comision_id="com-1", codigo_materia="MAT101",
            dia="Miércoles", hora_inicio=time(14, 0), hora_fin=time(16, 0),
        )
        session.add(hor2)
        session.commit()

        result = generate_clases_for_plan(session, "plan-1")

        # 2 Mondays + 2 Wednesdays
        assert result.clases_created == 4
