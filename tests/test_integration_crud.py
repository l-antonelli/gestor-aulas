"""
Comprehensive Integration Tests for CRUD Operations.

This module tests complete CRUD workflows end-to-end:
- Create entities through forms
- Read entities and display them
- Update entities with form modifications
- Delete entities with confirmation
- Verify database state after each operation

Requirements: All (Integration testing)
"""

import datetime
import os
import tempfile
from typing import Generator

import pytest
from sqlmodel import Session, SQLModel, create_engine

# Domain models
from src.domain.problem import (
    Materia,
    Comision,
    Horario,
    Aula,
)
# Database models and CRUD
from src.database.models import (
    MateriaDB, ComisionDB, HorarioDB,
    AulaDB,
)
from src.database.crud import (
    materia_crud, comision_crud, horario_crud,
    aula_crud,
)
from src.database.converters import to_db, to_domain

# UI Components
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer
from src.ui.serialization_utils import SerializationUtils


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create a temporary in-memory database for testing."""
    # Create in-memory SQLite database
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False}
    )

    # Create all tables
    SQLModel.metadata.create_all(engine)

    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_materia() -> Materia:
    """Create a sample Materia for testing."""
    return Materia(
        codigo="MAT101",
        nombre="Matemáticas I",
        cupo=30,
        horas_semanales=4,
    )


@pytest.fixture
def sample_aula() -> Aula:
    """Create a sample Aula for testing."""
    return Aula(
        id="AULA-001",
        sede="Campus Central",
        nombre="Aula 101",
        capacidad=40,
        tipo="teorica",
        descripcion="Aula de teoría",
    )


@pytest.fixture
def sample_horario() -> Horario:
    """Create a sample Horario for testing."""
    return Horario(
        id="HOR-001",
        comision_id="COM-001",
        codigo_materia="MAT101",
        dia="Lunes",
        hora_inicio=datetime.time(8, 0),
        hora_fin=datetime.time(10, 0),
    )


# =============================================================================
# Test Class: CRUD Operations End-to-End
# =============================================================================

class TestCRUDOperationsEndToEnd:
    """Tests for complete CRUD workflows."""

    def test_materia_create_read_update_delete(self, test_db_session: Session, sample_materia: Materia):
        """Test complete CRUD workflow for Materia entity."""
        # CREATE
        db_materia = to_db(sample_materia)
        created = materia_crud.create(test_db_session, db_materia)

        assert created is not None
        assert created.codigo == sample_materia.codigo

        # READ
        read_materia = materia_crud.get(test_db_session, sample_materia.codigo)

        assert read_materia is not None
        assert read_materia.nombre == sample_materia.nombre

        # UPDATE
        read_materia.cupo = 50
        updated = materia_crud.update(test_db_session, read_materia)

        assert updated.cupo == 50

        # DELETE
        deleted = materia_crud.delete(test_db_session, sample_materia.codigo)

        assert deleted is True
        assert materia_crud.get(test_db_session, sample_materia.codigo) is None

    def test_aula_create_read_update_delete(self, test_db_session: Session, sample_aula: Aula):
        """Test complete CRUD workflow for Aula entity."""
        # CREATE
        db_aula = to_db(sample_aula)
        created = aula_crud.create(test_db_session, db_aula)

        assert created is not None
        assert created.id == sample_aula.id

        # READ
        read_aula = aula_crud.get(test_db_session, sample_aula.id)

        assert read_aula is not None
        assert read_aula.capacidad == sample_aula.capacidad

        # UPDATE
        read_aula.capacidad = 60
        updated = aula_crud.update(test_db_session, read_aula)

        assert updated.capacidad == 60

        # DELETE
        deleted = aula_crud.delete(test_db_session, sample_aula.id)

        assert deleted is True
        assert aula_crud.get(test_db_session, sample_aula.id) is None

    def test_horario_create_read_update_delete(self, test_db_session: Session, sample_materia: Materia, sample_horario: Horario):
        """Test complete CRUD workflow for Horario entity."""
        # Create dependencies (materia, comision)
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comision A",
            numero=1,
            cupo=25,
        )
        db_comision = to_db(comision)
        comision_crud.create(test_db_session, db_comision)

        # CREATE
        db_horario = to_db(sample_horario)
        created = horario_crud.create(test_db_session, db_horario)

        assert created is not None
        assert created.id == sample_horario.id

        # READ
        read_horario = horario_crud.get(test_db_session, sample_horario.id)

        assert read_horario is not None
        assert read_horario.dia == sample_horario.dia

        # UPDATE
        read_horario.dia = "Martes"
        updated = horario_crud.update(test_db_session, read_horario)

        assert updated.dia == "Martes"

        # DELETE
        deleted = horario_crud.delete(test_db_session, sample_horario.id)

        assert deleted is True
        assert horario_crud.get(test_db_session, sample_horario.id) is None


class TestComisionCRUDWithDependencies:
    """Tests for Comision CRUD which depends on Materia."""

    def test_comision_crud_workflow(self, test_db_session: Session, sample_materia: Materia):
        """Test Comision CRUD with Materia dependency."""
        # First create the Materia
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        # Create Comision
        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comision A",
            numero=1,
            cupo=25,
        )
        db_comision = to_db(comision)
        created = comision_crud.create(test_db_session, db_comision)

        assert created is not None
        assert created.materia_codigo == sample_materia.codigo

        # READ
        read_comision = comision_crud.get(test_db_session, comision.id)
        assert read_comision is not None

        # UPDATE
        read_comision.cupo = 30
        updated = comision_crud.update(test_db_session, read_comision)
        assert updated.cupo == 30

        # DELETE
        deleted = comision_crud.delete(test_db_session, comision.id)
        assert deleted is True


class TestHorarioCRUDWithDependencies:
    """Tests for Horario CRUD which depends on Comision and Materia."""

    def test_horario_crud_workflow(
        self,
        test_db_session: Session,
        sample_materia: Materia,
        sample_horario: Horario,
    ):
        """Test Horario CRUD with dependencies."""
        # Create dependencies
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comision A",
            numero=1,
            cupo=25,
        )
        db_comision = to_db(comision)
        comision_crud.create(test_db_session, db_comision)

        # Create Horario
        db_horario = to_db(sample_horario)
        created = horario_crud.create(test_db_session, db_horario)

        assert created is not None
        assert created.comision_id == comision.id

        # READ
        read_horario = horario_crud.get(test_db_session, sample_horario.id)
        assert read_horario is not None

        # UPDATE
        read_horario.dia = "Martes"
        updated = horario_crud.update(test_db_session, read_horario)
        assert updated.dia == "Martes"

        # DELETE
        deleted = horario_crud.delete(test_db_session, sample_horario.id)
        assert deleted is True


# =============================================================================
# Test Class: Form Validation Integration
# =============================================================================

class TestFormValidationIntegration:
    """Tests for form validation with various constraint combinations."""

    def test_materia_validation_numeric_constraints(self):
        """Test Materia validation with numeric constraints."""
        # Valid data
        valid_data = {
            "codigo": "MAT101",
            "nombre": "Matematicas",
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Materia)
        assert is_valid is True

        # Invalid cupo (must be > 0)
        invalid_cupo = valid_data.copy()
        invalid_cupo["cupo"] = 0
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_cupo, Materia)
        assert is_valid is False
        assert "cupo" in errors

        # Invalid horas_semanales (must be > 0)
        invalid_horas = valid_data.copy()
        invalid_horas["horas_semanales"] = 0
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_horas, Materia)
        assert is_valid is False
        assert "horas_semanales" in errors

    def test_aula_validation_literal_type(self):
        """Test Aula validation with Literal type constraint."""
        # Valid data
        valid_data = {
            "id": "AULA-001",
            "sede": "Campus Central",
            "nombre": "Aula 101",
            "capacidad": 40,
            "tipo": "teorica",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Aula)
        assert is_valid is True

        # Invalid tipo (not in Literal options)
        invalid_tipo = valid_data.copy()
        invalid_tipo["tipo"] = "invalid_type"
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_tipo, Aula)
        assert is_valid is False
        assert "tipo" in errors

    def test_horario_validation_time_range(self):
        """Test Horario validation with time range."""
        # Valid data
        valid_data = {
            "id": "HOR-001",
            "comision_id": "COM-001",
            "codigo_materia": "MAT101",
            "dia": "Lunes",
            "hora_inicio": datetime.time(8, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Horario)
        assert is_valid is True

        # Invalid time range (end before start)
        invalid_time = valid_data.copy()
        invalid_time["hora_inicio"] = datetime.time(10, 0)
        invalid_time["hora_fin"] = datetime.time(8, 0)
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_time, Horario)
        assert is_valid is False


# =============================================================================
# Test Class: Serialization Round-Trip
# =============================================================================

class TestSerializationRoundTrip:
    """Tests for serialization/deserialization round-trips."""

    def test_materia_serialization_round_trip(self, sample_materia: Materia):
        """Test Materia serialization round-trip."""
        json_str = SerializationUtils.serialize_to_json(sample_materia)
        restored = SerializationUtils.deserialize_from_json(json_str, Materia)

        assert restored == sample_materia
        assert restored.codigo == sample_materia.codigo
        assert restored.cupo == sample_materia.cupo

    def test_aula_serialization_round_trip(self, sample_aula: Aula):
        """Test Aula serialization round-trip."""
        json_str = SerializationUtils.serialize_to_json(sample_aula)
        restored = SerializationUtils.deserialize_from_json(json_str, Aula)

        assert restored == sample_aula
        assert restored.tipo == sample_aula.tipo

    def test_horario_serialization_round_trip(self, sample_horario: Horario):
        """Test Horario serialization round-trip."""
        json_str = SerializationUtils.serialize_to_json(sample_horario)
        restored = SerializationUtils.deserialize_from_json(json_str, Horario)

        assert restored == sample_horario
        assert restored.hora_inicio == sample_horario.hora_inicio
        assert restored.hora_fin == sample_horario.hora_fin



# =============================================================================
# Test Class: Form Output Display
# =============================================================================

class TestFormOutputDisplay:
    """Tests for form output display functionality."""

    def test_materia_display_data(self, sample_materia: Materia):
        """Test Materia display data generation."""
        data = FormOutputRenderer.get_display_data(sample_materia)

        assert "Codigo" in data
        assert "Nombre" in data
        assert "Cupo" in data
        assert "Horas Semanales" in data

    def test_aula_display_data(self, sample_aula: Aula):
        """Test Aula display data generation."""
        data = FormOutputRenderer.get_display_data(sample_aula)

        assert "Id" in data
        assert "Sede" in data
        assert "Nombre" in data
        assert "Capacidad" in data
        assert "Tipo" in data

    def test_time_field_formatting(self, sample_horario: Horario):
        """Test time field formatting in display."""
        data = FormOutputRenderer.get_display_data(sample_horario)

        # Time should be formatted as HH:MM:SS
        assert "08:00:00" in data["Hora Inicio"]
        assert "10:00:00" in data["Hora Fin"]


# =============================================================================
# Test Class: Database State Verification
# =============================================================================

class TestDatabaseStateVerification:
    """Tests to verify database state after operations."""

    def test_create_verifies_in_database(self, test_db_session: Session, sample_materia: Materia):
        """Test that create operation persists to database."""
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        # Verify in database
        all_materias = materia_crud.get_all(test_db_session)
        assert len(all_materias) == 1
        assert all_materias[0].codigo == sample_materia.codigo

    def test_update_verifies_in_database(self, test_db_session: Session, sample_materia: Materia):
        """Test that update operation persists to database."""
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        # Update
        db_materia.cupo = 50
        materia_crud.update(test_db_session, db_materia)

        # Verify in database
        read_materia = materia_crud.get(test_db_session, sample_materia.codigo)
        assert read_materia.cupo == 50

    def test_delete_verifies_in_database(self, test_db_session: Session, sample_materia: Materia):
        """Test that delete operation removes from database."""
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        # Verify exists
        assert materia_crud.get(test_db_session, sample_materia.codigo) is not None

        # Delete
        materia_crud.delete(test_db_session, sample_materia.codigo)

        # Verify removed
        assert materia_crud.get(test_db_session, sample_materia.codigo) is None
        all_materias = materia_crud.get_all(test_db_session)
        assert len(all_materias) == 0

    def test_multiple_entities_in_database(self, test_db_session: Session):
        """Test multiple entities can be created and retrieved."""
        # Create multiple materias
        for i in range(5):
            materia = Materia(
                codigo=f"MAT{i:03d}",
                nombre=f"Materia {i}",
                cupo=30,
                horas_semanales=4,
            )
            db_materia = to_db(materia)
            materia_crud.create(test_db_session, db_materia)

        # Verify all exist
        all_materias = materia_crud.get_all(test_db_session)
        assert len(all_materias) == 5

    def test_domain_db_conversion_preserves_data(self, test_db_session: Session, sample_materia: Materia):
        """Test that domain <-> DB conversion preserves all data."""
        # Convert to DB and save
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)

        # Read back and convert to domain
        read_db = materia_crud.get(test_db_session, sample_materia.codigo)
        restored_domain = to_domain(read_db)

        # Verify all fields match
        assert restored_domain.codigo == sample_materia.codigo
        assert restored_domain.nombre == sample_materia.nombre
        assert restored_domain.cupo == sample_materia.cupo
        assert restored_domain.horas_semanales == sample_materia.horas_semanales
