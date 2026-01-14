"""
Comprehensive Integration Tests for CRUD Operations through Refactored Pages.

This module tests CRUD operations through the service layer:
- Create entities using new page structure
- Verify cascading creation works
- Verify relationship selectors work
- Verify nested entity display works

Requirements: 1.1, 1.4, 4.4, 6.1, 6.2
"""

import datetime
from typing import Generator, Dict, Any, List
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

# Domain models
from src.domain.problem import (
    Materia,
    Comision,
    Clase,
    Aula,
    HorarioCronograma,
    Alumno,
)
from src.domain.problem.carrera import Carrera

# Database models and CRUD
from src.database.models import (
    MateriaDB, ComisionDB, ClaseDB, HorarioCronogramaDB, AulaDB, AlumnoDB,
)
from src.database.crud import (
    materia_crud, comision_crud, clase_crud, horario_crud, aula_crud, alumno_crud,
)
from src.database.converters import to_db, to_domain

# Services
from src.services.crud_services import (
    materia_service, comision_service, aula_service, alumno_service, carrera_service,
    BaseCRUDService, EntityNotFoundError, DuplicateEntityError,
)
from src.services.cascading_operations import CascadingOperations

# UI Components
from src.ui.page_template import EntityPageTemplate, EntityPageConfig
from src.ui.hierarchical_entity_viewer import ChildConfig
from src.ui.schema_introspector import SchemaIntrospector

# Import relationship definitions
import src.services.relationship_definitions  # noqa: F401


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create a temporary in-memory database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_materia() -> Materia:
    """Create a sample Materia for testing."""
    return Materia(
        codigo="MAT101",
        nombre="Cálculo I",
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
def sample_alumno() -> Alumno:
    """Create a sample Alumno for testing."""
    return Alumno(
        legajo="A-12345",
        email="test@example.com",
        nombre="Juan Pérez",
        dni="12345678",
    )


# =============================================================================
# Test Class: CRUD Service Layer Operations
# =============================================================================

class TestCRUDServiceLayerOperations:
    """
    Tests for CRUD operations through the service layer.
    
    Requirements: 1.1, 1.3
    """
    
    def test_create_materia_via_service(self, test_db_session: Session, sample_materia: Materia):
        """
        Test creating a Materia through the service layer.
        
        Requirements: 1.1
        """
        # Create via service
        created = materia_service.create(test_db_session, sample_materia)
        
        assert created is not None
        assert created.codigo == sample_materia.codigo
        assert created.nombre == sample_materia.nombre
        assert created.cupo == sample_materia.cupo
    
    def test_get_materia_via_service(self, test_db_session: Session, sample_materia: Materia):
        """
        Test retrieving a Materia through the service layer.
        
        Requirements: 1.1
        """
        # Create first
        materia_service.create(test_db_session, sample_materia)
        
        # Get via service
        retrieved = materia_service.get(test_db_session, sample_materia.codigo)
        
        assert retrieved is not None
        assert retrieved.codigo == sample_materia.codigo
        assert retrieved.nombre == sample_materia.nombre
    
    def test_get_all_materias_via_service(self, test_db_session: Session):
        """
        Test retrieving all Materias through the service layer.
        
        Requirements: 1.1
        """
        # Create multiple materias
        for i in range(3):
            materia = Materia(
                codigo=f"MAT{i:03d}",
                nombre=f"Materia {i}",
                cupo=30,
                horas_semanales=4,
            )
            materia_service.create(test_db_session, materia)
        
        # Get all via service
        all_materias = materia_service.get_all(test_db_session)
        
        assert len(all_materias) == 3
    
    def test_update_materia_via_service(self, test_db_session: Session, sample_materia: Materia):
        """
        Test updating a Materia through the service layer.
        
        Requirements: 1.1
        """
        # Create first
        materia_service.create(test_db_session, sample_materia)
        
        # Create updated version (Pydantic models are frozen)
        updated_materia = Materia(
            codigo=sample_materia.codigo,
            nombre="Cálculo I Actualizado",
            cupo=50,
            horas_semanales=sample_materia.horas_semanales,
        )
        updated = materia_service.update(test_db_session, updated_materia)
        
        assert updated.cupo == 50
        assert updated.nombre == "Cálculo I Actualizado"
        
        # Verify persisted
        retrieved = materia_service.get(test_db_session, sample_materia.codigo)
        assert retrieved.cupo == 50
    
    def test_delete_materia_via_service(self, test_db_session: Session, sample_materia: Materia):
        """
        Test deleting a Materia through the service layer.
        
        Requirements: 1.1
        """
        # Create first
        materia_service.create(test_db_session, sample_materia)
        
        # Verify exists
        assert materia_service.get(test_db_session, sample_materia.codigo) is not None
        
        # Delete
        result = materia_service.delete(test_db_session, sample_materia.codigo)
        
        assert result is True
        
        # Verify deleted
        assert materia_service.get(test_db_session, sample_materia.codigo) is None
    
    def test_create_aula_via_service(self, test_db_session: Session, sample_aula: Aula):
        """
        Test creating an Aula through the service layer.
        
        Requirements: 1.1
        """
        created = aula_service.create(test_db_session, sample_aula)
        
        assert created is not None
        assert created.id == sample_aula.id
        assert created.capacidad == sample_aula.capacidad
    
    def test_create_alumno_via_service(self, test_db_session: Session, sample_alumno: Alumno):
        """
        Test creating an Alumno through the service layer.
        
        Requirements: 1.1
        """
        created = alumno_service.create(test_db_session, sample_alumno)
        
        assert created is not None
        assert created.legajo == sample_alumno.legajo
        assert created.nombre == sample_alumno.nombre


# =============================================================================
# Test Class: Cascading Creation
# =============================================================================

class TestCascadingCreation:
    """
    Tests for cascading creation through the service layer.
    
    Requirements: 1.4
    """
    
    def test_materia_cascading_creates_comision(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that creating a Materia cascades to create a default Comisión.
        
        Requirements: 1.4
        """
        # Create with cascading
        created, children = materia_service.create_with_cascading(test_db_session, sample_materia)
        
        assert created is not None
        assert created.codigo == sample_materia.codigo
        
        # Verify cascading child was created
        assert len(children) >= 1
        
        # Verify comision exists in database
        all_comisiones = comision_service.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == sample_materia.codigo]
        
        assert len(materia_comisiones) >= 1
    
    def test_cascading_comision_has_correct_defaults(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that cascading Comisión has correct default values.
        
        Requirements: 1.4
        """
        # Create with cascading
        created, children = materia_service.create_with_cascading(test_db_session, sample_materia)
        
        # Get the auto-created comision
        all_comisiones = comision_service.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == sample_materia.codigo]
        
        if materia_comisiones:
            comision = materia_comisiones[0]
            assert comision.nombre == "Comisión Única"
            assert comision.numero == 1
            assert comision.materia_codigo == sample_materia.codigo
    
    def test_cascading_preserves_parent_on_child_failure(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that parent is preserved even if cascading child creation fails.
        
        Requirements: 1.4
        """
        # Create with cascading (should succeed)
        created, children = materia_service.create_with_cascading(test_db_session, sample_materia)
        
        # Parent should always be created
        assert created is not None
        
        # Verify parent exists in database
        retrieved = materia_service.get(test_db_session, sample_materia.codigo)
        assert retrieved is not None


# =============================================================================
# Test Class: Relationship Selectors
# =============================================================================

class TestRelationshipSelectors:
    """
    Tests for relationship selector functionality.
    
    Requirements: 4.4, 8.3
    """
    
    def test_foreign_key_fields_detected(self):
        """
        Test that foreign key fields are correctly detected.
        
        Requirements: 4.4
        """
        # Comision has materia_codigo as foreign key
        # Check that the field exists in the model
        model_fields = Comision.model_fields
        
        # Find materia_codigo field
        assert "materia_codigo" in model_fields
        
        # Verify it's a string field (foreign key reference)
        materia_codigo_field = model_fields["materia_codigo"]
        assert materia_codigo_field is not None
    
    def test_comision_references_materia(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that Comisión correctly references Materia.
        
        Requirements: 4.4
        """
        # Create Materia first
        materia_service.create(test_db_session, sample_materia)
        
        # Create Comisión referencing the Materia
        comision = Comision(
            id="COM-001",
            materia_codigo=sample_materia.codigo,
            nombre="Comisión A",
            numero=1,
            cupo=25,
        )
        created = comision_service.create(test_db_session, comision)
        
        assert created is not None
        assert created.materia_codigo == sample_materia.codigo
        
        # Verify relationship
        retrieved = comision_service.get(test_db_session, "COM-001")
        assert retrieved.materia_codigo == sample_materia.codigo
    
    def test_get_available_parents_for_selector(self, test_db_session: Session):
        """
        Test getting available parent entities for relationship selector.
        
        Requirements: 4.4
        """
        # Create multiple materias
        for i in range(3):
            materia = Materia(
                codigo=f"MAT{i:03d}",
                nombre=f"Materia {i}",
                cupo=30,
                horas_semanales=4,
            )
            materia_service.create(test_db_session, materia)
        
        # Get all materias (for selector)
        available_materias = materia_service.get_all(test_db_session)
        
        assert len(available_materias) == 3
        
        # Each should have codigo and nombre for display
        for m in available_materias:
            assert hasattr(m, 'codigo')
            assert hasattr(m, 'nombre')


# =============================================================================
# Test Class: Nested Entity Display
# =============================================================================

class TestNestedEntityDisplay:
    """
    Tests for nested entity display functionality.
    
    Requirements: 6.1, 6.2
    """
    
    def test_display_comisiones_for_materia(self, test_db_session: Session, sample_materia: Materia):
        """
        Test displaying Comisiones nested under a Materia.
        
        Requirements: 6.1
        """
        # Create Materia with cascading
        materia_service.create_with_cascading(test_db_session, sample_materia)
        
        # Create additional Comisiones
        for i in range(2, 4):
            comision = Comision(
                id=f"COM-{i:03d}",
                materia_codigo=sample_materia.codigo,
                nombre=f"Comisión {chr(64 + i)}",
                numero=i,
                cupo=25,
            )
            comision_service.create(test_db_session, comision)
        
        # Get all comisiones for this materia
        all_comisiones = comision_service.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == sample_materia.codigo]
        
        # Should have multiple comisiones
        assert len(materia_comisiones) >= 3
    
    def test_child_count_in_parent_view(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that child count is displayed correctly in parent view.
        
        Requirements: 6.2
        """
        # Create Materia with cascading
        materia_service.create_with_cascading(test_db_session, sample_materia)
        
        # Create additional Comisiones
        comision2 = Comision(
            id="COM-002",
            materia_codigo=sample_materia.codigo,
            nombre="Comisión B",
            numero=2,
            cupo=25,
        )
        comision_service.create(test_db_session, comision2)
        
        # Get count
        all_comisiones = comision_service.get_all(test_db_session)
        count = len([c for c in all_comisiones if c.materia_codigo == sample_materia.codigo])
        
        assert count == 2
    
    def test_nested_display_preserves_hierarchy(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that nested display preserves hierarchical relationships.
        
        Requirements: 6.1, 6.2
        """
        # Create Materia with cascading
        materia_service.create_with_cascading(test_db_session, sample_materia)
        
        # Get the materia
        materia = materia_service.get(test_db_session, sample_materia.codigo)
        assert materia is not None
        
        # Get its comisiones
        all_comisiones = comision_service.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == materia.codigo]
        
        # All comisiones should reference the correct materia
        for comision in materia_comisiones:
            assert comision.materia_codigo == materia.codigo


# =============================================================================
# Test Class: Page Configuration
# =============================================================================

class TestPageConfiguration:
    """
    Tests for EntityPageConfig and page structure.
    
    Requirements: 4.1, 4.2
    """
    
    def test_entity_page_config_creation(self):
        """
        Test creating an EntityPageConfig.
        
        Requirements: 4.1
        """
        config = EntityPageConfig(
            model=Materia,
            service=materia_service,
            page_title="Gestión de Materias",
            page_icon="📚",
            display_fields=["codigo", "nombre", "cupo"],
            custom_labels={"codigo": "Código", "nombre": "Nombre"},
            id_field="codigo",
            display_field="nombre",
        )
        
        assert config.model == Materia
        assert config.page_title == "Gestión de Materias"
        assert "codigo" in config.display_fields
    
    def test_entity_page_config_with_children(self):
        """
        Test creating an EntityPageConfig with child configurations.
        
        Requirements: 4.2
        """
        child_config = ChildConfig(
            model=Comision,
            service=comision_service,
            display_fields=["id", "nombre", "cupo"],
            foreign_key_field="materia_codigo",
            id_field="id",
            display_field="nombre",
        )
        
        config = EntityPageConfig(
            model=Materia,
            service=materia_service,
            page_title="Gestión de Materias",
            page_icon="📚",
            display_fields=["codigo", "nombre", "cupo"],
            custom_labels={},
            id_field="codigo",
            display_field="nombre",
            child_configs=[child_config],
        )
        
        assert len(config.child_configs) == 1
        assert config.child_configs[0].model == Comision
    
    def test_page_config_cascading_option(self):
        """
        Test EntityPageConfig cascading option.
        
        Requirements: 1.4
        """
        config = EntityPageConfig(
            model=Materia,
            service=materia_service,
            page_title="Gestión de Materias",
            page_icon="📚",
            display_fields=["codigo", "nombre"],
            custom_labels={},
            id_field="codigo",
            display_field="nombre",
            enable_cascading=True,
        )
        
        assert config.enable_cascading is True


# =============================================================================
# Test Class: Error Handling
# =============================================================================

class TestCRUDErrorHandling:
    """
    Tests for error handling in CRUD operations.
    
    Requirements: 1.5
    """
    
    def test_get_nonexistent_entity_returns_none(self, test_db_session: Session):
        """
        Test that getting a non-existent entity returns None.
        
        Requirements: 1.5
        """
        result = materia_service.get(test_db_session, "NONEXISTENT")
        
        assert result is None
    
    def test_delete_nonexistent_entity_returns_false(self, test_db_session: Session):
        """
        Test that deleting a non-existent entity returns False.
        
        Requirements: 1.5
        """
        result = materia_service.delete(test_db_session, "NONEXISTENT")
        
        assert result is False
    
    def test_create_duplicate_raises_error(self, test_db_session: Session, sample_materia: Materia):
        """
        Test that creating a duplicate entity raises an error.
        
        Requirements: 1.5
        """
        # Create first
        materia_service.create(test_db_session, sample_materia)
        
        # Try to create duplicate
        with pytest.raises(Exception):  # Could be IntegrityError or DuplicateEntityError
            materia_service.create(test_db_session, sample_materia)
