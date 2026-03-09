"""Tests for dictado_service."""

import pytest
from datetime import date

from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.database.models import CicloDB, MateriaDB
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
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
def ciclo_1c(session):
    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.commit()
    return ciclo


@pytest.fixture
def ciclo_2c(session):
    ciclo = CicloDB(
        id="2025-2C", anio=2025, numero=2,
        fecha_inicio=date(2025, 8, 11), fecha_fin=date(2025, 12, 5),
    )
    session.add(ciclo)
    session.commit()
    return ciclo


@pytest.fixture
def materias(session):
    m1 = MateriaDB(
        codigo="MAT101", nombre="Calculo I",
        periodo="cuatrimestral", active=True,
    )
    m2 = MateriaDB(
        codigo="FIS101", nombre="Fisica I",
        periodo="anual", active=True,
    )
    m3 = MateriaDB(
        codigo="HIS101", nombre="Historia",
        periodo="cuatrimestral", active=False,
    )
    session.add_all([m1, m2, m3])
    session.commit()
    return [m1, m2, m3]


class TestCreateDictadosForCiclo:

    def test_creates_cuatrimestral_dictados(self, session, ciclo_1c, materias):
        result = create_dictados_for_ciclo(session, "2025-1C")

        # MAT101 (cuatrimestral, active) + FIS101 (anual, active, 1C creates)
        assert result.created == 2
        assert result.skipped == 0
        assert result.errors == []

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        assert len(dictados) == 2

        codigos = {d.dictado_codigo for d in dictados}
        assert "MAT101-2025-1C" in codigos
        assert "FIS101-2025" in codigos

    def test_inactive_materia_skipped(self, session, ciclo_1c, materias):
        result = create_dictados_for_ciclo(session, "2025-1C")

        dictados = get_dictados_for_ciclo(session, "2025-1C")
        materia_codigos = {d.materia_codigo for d in dictados}
        # HIS101 is inactive, should not have a dictado
        assert "HIS101" not in materia_codigos

    def test_idempotent(self, session, ciclo_1c, materias):
        result1 = create_dictados_for_ciclo(session, "2025-1C")
        result2 = create_dictados_for_ciclo(session, "2025-1C")

        assert result2.created == 0
        assert result2.skipped == 2  # MAT101 + FIS101

    def test_anual_2c_links_existing(self, session, ciclo_1c, ciclo_2c, materias):
        # Create dictados for 1C first
        result_1c = create_dictados_for_ciclo(session, "2025-1C")
        assert result_1c.created == 2

        # Create dictados for 2C
        result_2c = create_dictados_for_ciclo(session, "2025-2C")

        # MAT101 cuatrimestral: new dictado created
        # FIS101 anual: should link existing dictado from 1C
        assert result_2c.created == 1  # MAT101 cuatrimestral
        assert result_2c.linked == 1  # FIS101 anual

        # FIS101 dictado should be linked to both ciclos
        dictados_1c = get_dictados_for_ciclo(session, "2025-1C")
        dictados_2c = get_dictados_for_ciclo(session, "2025-2C")

        fis_1c = [d for d in dictados_1c if d.materia_codigo == "FIS101"]
        fis_2c = [d for d in dictados_2c if d.materia_codigo == "FIS101"]

        assert len(fis_1c) == 1
        assert len(fis_2c) == 1
        # Same dictado
        assert fis_1c[0].id == fis_2c[0].id
        # fin_dictado should be set to 2C fecha_fin
        assert fis_2c[0].fin_dictado == date(2025, 12, 5)

    def test_anual_2c_without_1c_creates_new(self, session, ciclo_2c, materias):
        # Only 2C exists, no 1C dictados
        result = create_dictados_for_ciclo(session, "2025-2C")

        # Both materias should create new dictados
        assert result.created == 2
        assert result.linked == 0

    def test_invalid_ciclo(self, session):
        result = create_dictados_for_ciclo(session, "NONEXISTENT")
        assert len(result.errors) == 1
        assert "no encontrado" in result.errors[0]

    def test_no_active_materias(self, session, ciclo_1c):
        # Only inactive materia
        m = MateriaDB(codigo="X", nombre="X", periodo="cuatrimestral", active=False)
        session.add(m)
        session.commit()

        result = create_dictados_for_ciclo(session, "2025-1C")
        assert result.created == 0
