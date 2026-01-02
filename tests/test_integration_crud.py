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
    Alumno,
    Materia,
    Comision,
    Clase,
    Aula,
    HorarioCronograma,
)
from src.domain.solution import (
    Inscripcion,
    Asistencia,
    AsignacionAula,
)

# Database models and CRUD
from src.database.models import (
    AlumnoDB, MateriaDB, ComisionDB, HorarioCronogramaDB,
    AulaDB, ClaseDB, InscripcionDB, AsistenciaDB, AsignacionAulaDB,
)
from src.database.crud import (
    alumno_crud, materia_crud, comision_crud, horario_crud,
    aula_crud, clase_crud, inscripcion_crud, asistencia_crud, asignacion_crud,
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
def sample_alumno() -> Alumno:
    """Create a sample Alumno for testing."""
    return Alumno(
        legajo="A-12345",
        email="test@example.com",
        nombre="Juan Pérez",
        dni="12345678",
    )


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
def sample_horario() -> HorarioCronograma:
    """Create a sample HorarioCronograma for testing."""
    return HorarioCronograma(
        id="HOR-001",
        dia_semana="Lunes",
        hora_inicio=datetime.time(8, 0),
        hora_fin=datetime.time(10, 0),
    )


# =============================================================================
# Test Class: CRUD Operations End-to-End
# =============================================================================

class TestCRUDOperationsEndToEnd:
    """Tests for complete CRUD workflows."""

    def test_alumno_create_read_update_delete(self, test_db_session: Session, sample_alumno: Alumno):
        """Test complete CRUD workflow for Alumno entity."""
        # CREATE
        db_alumno = to_db(sample_alumno)
        created = alumno_crud.create(test_db_session, db_alumno)
        
        assert created is not None
        assert created.legajo == sample_alumno.legajo
        assert created.nombre == sample_alumno.nombre
        
        # READ
        read_alumno = alumno_crud.get(test_db_session, sample_alumno.legajo)
        
        assert read_alumno is not None
        assert read_alumno.legajo == sample_alumno.legajo
        assert read_alumno.email == sample_alumno.email
        
        # UPDATE
        read_alumno.nombre = "Juan Pérez Actualizado"
        updated = alumno_crud.update(test_db_session, read_alumno)
        
        assert updated.nombre == "Juan Pérez Actualizado"
        
        # Verify update persisted
        verify_update = alumno_crud.get(test_db_session, sample_alumno.legajo)
        assert verify_update.nombre == "Juan Pérez Actualizado"
        
        # DELETE
        deleted = alumno_crud.delete(test_db_session, sample_alumno.legajo)
        
        assert deleted is True
        
        # Verify deletion
        verify_delete = alumno_crud.get(test_db_session, sample_alumno.legajo)
        assert verify_delete is None

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

    def test_horario_create_read_update_delete(self, test_db_session: Session, sample_horario: HorarioCronograma):
        """Test complete CRUD workflow for HorarioCronograma entity."""
        # CREATE
        db_horario = to_db(sample_horario)
        created = horario_crud.create(test_db_session, db_horario)
        
        assert created is not None
        assert created.id == sample_horario.id
        
        # READ
        read_horario = horario_crud.get(test_db_session, sample_horario.id)
        
        assert read_horario is not None
        assert read_horario.dia_semana == sample_horario.dia_semana
        
        # UPDATE
        read_horario.dia_semana = "Martes"
        updated = horario_crud.update(test_db_session, read_horario)
        
        assert updated.dia_semana == "Martes"
        
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
            nombre="Comisión A",
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


class TestClaseCRUDWithDependencies:
    """Tests for Clase CRUD which depends on Comision and Horario."""

    def test_clase_crud_workflow(
        self,
        test_db_session: Session,
        sample_materia: Materia,
        sample_horario: HorarioCronograma,
    ):
        """Test Clase CRUD with dependencies."""
        # Create dependencies
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)
        
        db_horario = to_db(sample_horario)
        horario_crud.create(test_db_session, db_horario)
        
        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comisión A",
            numero=1,
            cupo=25,
        )
        db_comision = to_db(comision)
        comision_crud.create(test_db_session, db_comision)
        
        # Create Clase
        clase = Clase(
            id="CLS-001",
            comision_id=comision.id,
            horario_id=sample_horario.id,
            dia="Lunes",
        )
        db_clase = to_db(clase)
        created = clase_crud.create(test_db_session, db_clase)
        
        assert created is not None
        assert created.comision_id == comision.id
        
        # READ
        read_clase = clase_crud.get(test_db_session, clase.id)
        assert read_clase is not None
        
        # UPDATE
        read_clase.dia = "Martes"
        updated = clase_crud.update(test_db_session, read_clase)
        assert updated.dia == "Martes"
        
        # DELETE
        deleted = clase_crud.delete(test_db_session, clase.id)
        assert deleted is True


class TestInscripcionCRUDWithDependencies:
    """Tests for Inscripcion CRUD which depends on Alumno and Comision."""

    def test_inscripcion_crud_workflow(
        self,
        test_db_session: Session,
        sample_alumno: Alumno,
        sample_materia: Materia,
    ):
        """Test Inscripcion CRUD with dependencies."""
        # Create dependencies
        db_alumno = to_db(sample_alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        db_materia = to_db(sample_materia)
        materia_crud.create(test_db_session, db_materia)
        
        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comisión A",
            numero=1,
            cupo=25,
        )
        db_comision = to_db(comision)
        comision_crud.create(test_db_session, db_comision)
        
        # Create Inscripcion
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo=sample_alumno.legajo,
            comision_id=comision.id,
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        db_inscripcion = to_db(inscripcion)
        created = inscripcion_crud.create(test_db_session, db_inscripcion)
        
        assert created is not None
        assert created.alumno_legajo == sample_alumno.legajo
        
        # READ
        read_inscripcion = inscripcion_crud.get(test_db_session, inscripcion.id)
        assert read_inscripcion is not None
        
        # UPDATE
        read_inscripcion.activa = False
        updated = inscripcion_crud.update(test_db_session, read_inscripcion)
        assert updated.activa is False
        
        # DELETE
        deleted = inscripcion_crud.delete(test_db_session, inscripcion.id)
        assert deleted is True


# =============================================================================
# Test Class: Form Validation Integration
# =============================================================================

class TestFormValidationIntegration:
    """Tests for form validation with various constraint combinations."""

    def test_alumno_validation_all_constraints(self):
        """Test Alumno validation with all constraints."""
        # Valid data
        valid_data = {
            "legajo": "A-12345",
            "email": "test@example.com",
            "nombre": "Juan Pérez",
            "dni": "12345678",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Alumno)
        assert is_valid is True
        assert errors == {}
        
        # Invalid email
        invalid_email = valid_data.copy()
        invalid_email["email"] = "invalid-email"
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_email, Alumno)
        assert is_valid is False
        assert "email" in errors
        
        # Invalid DNI (too short)
        invalid_dni = valid_data.copy()
        invalid_dni["dni"] = "123"
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_dni, Alumno)
        assert is_valid is False
        assert "dni" in errors
        
        # Empty required field
        empty_nombre = valid_data.copy()
        empty_nombre["nombre"] = ""
        is_valid, errors = FormInputRenderer.validate_form_data(empty_nombre, Alumno)
        assert is_valid is False

    def test_materia_validation_numeric_constraints(self):
        """Test Materia validation with numeric constraints."""
        # Valid data
        valid_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
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
        """Test HorarioCronograma validation with time range."""
        # Valid data
        valid_data = {
            "id": "HOR-001",
            "dia_semana": "Lunes",
            "hora_inicio": datetime.time(8, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, HorarioCronograma)
        assert is_valid is True
        
        # Invalid time range (end before start)
        invalid_time = valid_data.copy()
        invalid_time["hora_inicio"] = datetime.time(10, 0)
        invalid_time["hora_fin"] = datetime.time(8, 0)
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_time, HorarioCronograma)
        assert is_valid is False

    def test_multiple_validation_errors(self):
        """Test that multiple validation errors are captured."""
        # Multiple invalid fields
        invalid_data = {
            "legajo": "",  # Empty
            "email": "invalid",  # No @
            "nombre": "",  # Empty
            "dni": "123",  # Too short
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Alumno)
        assert is_valid is False
        # Should have multiple errors
        assert len(errors) >= 1


# =============================================================================
# Test Class: Serialization Round-Trip
# =============================================================================

class TestSerializationRoundTrip:
    """Tests for serialization/deserialization round-trips."""

    def test_alumno_serialization_round_trip(self, sample_alumno: Alumno):
        """Test Alumno serialization round-trip."""
        json_str = SerializationUtils.serialize_to_json(sample_alumno)
        restored = SerializationUtils.deserialize_from_json(json_str, Alumno)
        
        assert restored == sample_alumno
        assert restored.legajo == sample_alumno.legajo
        assert restored.email == sample_alumno.email
        assert restored.nombre == sample_alumno.nombre
        assert restored.dni == sample_alumno.dni

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

    def test_horario_serialization_round_trip(self, sample_horario: HorarioCronograma):
        """Test HorarioCronograma serialization round-trip."""
        json_str = SerializationUtils.serialize_to_json(sample_horario)
        restored = SerializationUtils.deserialize_from_json(json_str, HorarioCronograma)
        
        assert restored == sample_horario
        assert restored.hora_inicio == sample_horario.hora_inicio
        assert restored.hora_fin == sample_horario.hora_fin

    def test_inscripcion_serialization_round_trip(self):
        """Test Inscripcion serialization round-trip with date field."""
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        
        json_str = SerializationUtils.serialize_to_json(inscripcion)
        restored = SerializationUtils.deserialize_from_json(json_str, Inscripcion)
        
        assert restored == inscripcion
        assert restored.fecha_inscripcion == inscripcion.fecha_inscripcion
        assert restored.activa == inscripcion.activa

    def test_asistencia_serialization_round_trip(self):
        """Test Asistencia serialization round-trip."""
        asistencia = Asistencia(
            id="ASI-001",
            alumno_legajo="A-12345",
            clase_id="CLS-001",
            fecha=datetime.date(2024, 3, 15),
            presente=True,
        )
        
        json_str = SerializationUtils.serialize_to_json(asistencia)
        restored = SerializationUtils.deserialize_from_json(json_str, Asistencia)
        
        assert restored == asistencia

    def test_asignacion_serialization_round_trip(self):
        """Test AsignacionAula serialization round-trip."""
        asignacion = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-001",
            fecha_asignacion=datetime.date(2024, 3, 1),
            vigente=True,
        )
        
        json_str = SerializationUtils.serialize_to_json(asignacion)
        restored = SerializationUtils.deserialize_from_json(json_str, AsignacionAula)
        
        assert restored == asignacion


# =============================================================================
# Test Class: Form Output Display
# =============================================================================

class TestFormOutputDisplay:
    """Tests for form output display functionality."""

    def test_alumno_display_data(self, sample_alumno: Alumno):
        """Test Alumno display data generation."""
        data = FormOutputRenderer.get_display_data(sample_alumno)
        
        assert "Legajo" in data
        assert "Email" in data
        assert "Nombre" in data
        assert "Dni" in data
        
        assert data["Legajo"] == sample_alumno.legajo
        assert data["Email"] == sample_alumno.email

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

    def test_boolean_field_formatting(self):
        """Test boolean field formatting in display."""
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        
        data = FormOutputRenderer.get_display_data(inscripcion)
        
        # Boolean should be formatted as "✓ Sí" or "✗ No"
        assert data["Activa"] == "✓ Sí"
        
        # Test False value
        inscripcion_inactive = Inscripcion(
            id="INS-002",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=False,
        )
        data_inactive = FormOutputRenderer.get_display_data(inscripcion_inactive)
        assert data_inactive["Activa"] == "✗ No"

    def test_date_field_formatting(self):
        """Test date field formatting in display."""
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        
        data = FormOutputRenderer.get_display_data(inscripcion)
        
        # Date should be formatted as YYYY-MM-DD
        assert data["Fecha Inscripcion"] == "2024-03-01"

    def test_time_field_formatting(self, sample_horario: HorarioCronograma):
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

    def test_create_verifies_in_database(self, test_db_session: Session, sample_alumno: Alumno):
        """Test that create operation persists to database."""
        db_alumno = to_db(sample_alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        # Verify in database
        all_alumnos = alumno_crud.get_all(test_db_session)
        assert len(all_alumnos) == 1
        assert all_alumnos[0].legajo == sample_alumno.legajo

    def test_update_verifies_in_database(self, test_db_session: Session, sample_alumno: Alumno):
        """Test that update operation persists to database."""
        db_alumno = to_db(sample_alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        # Update
        db_alumno.nombre = "Nombre Actualizado"
        alumno_crud.update(test_db_session, db_alumno)
        
        # Verify in database
        read_alumno = alumno_crud.get(test_db_session, sample_alumno.legajo)
        assert read_alumno.nombre == "Nombre Actualizado"

    def test_delete_verifies_in_database(self, test_db_session: Session, sample_alumno: Alumno):
        """Test that delete operation removes from database."""
        db_alumno = to_db(sample_alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        # Verify exists
        assert alumno_crud.get(test_db_session, sample_alumno.legajo) is not None
        
        # Delete
        alumno_crud.delete(test_db_session, sample_alumno.legajo)
        
        # Verify removed
        assert alumno_crud.get(test_db_session, sample_alumno.legajo) is None
        all_alumnos = alumno_crud.get_all(test_db_session)
        assert len(all_alumnos) == 0

    def test_multiple_entities_in_database(self, test_db_session: Session):
        """Test multiple entities can be created and retrieved."""
        # Create multiple alumnos
        for i in range(5):
            alumno = Alumno(
                legajo=f"A-{i:05d}",
                email=f"test{i}@example.com",
                nombre=f"Alumno {i}",
                dni=f"1234567{i}",
            )
            db_alumno = to_db(alumno)
            alumno_crud.create(test_db_session, db_alumno)
        
        # Verify all exist
        all_alumnos = alumno_crud.get_all(test_db_session)
        assert len(all_alumnos) == 5

    def test_domain_db_conversion_preserves_data(self, test_db_session: Session, sample_alumno: Alumno):
        """Test that domain <-> DB conversion preserves all data."""
        # Convert to DB and save
        db_alumno = to_db(sample_alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        # Read back and convert to domain
        read_db = alumno_crud.get(test_db_session, sample_alumno.legajo)
        restored_domain = to_domain(read_db)
        
        # Verify all fields match
        assert restored_domain.legajo == sample_alumno.legajo
        assert restored_domain.email == sample_alumno.email
        assert restored_domain.nombre == sample_alumno.nombre
        assert restored_domain.dni == sample_alumno.dni
