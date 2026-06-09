"""
Tests for CRUD Service Layer.

This module tests the centralized CRUD service layer that handles
domain model operations with automatic conversion and error handling.
"""

import pytest
from unittest.mock import MagicMock, patch
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.services.crud_services import (
    BaseCRUDService,
    MateriaService,
    ComisionService,
    HorarioService,
    EntityNotFoundError,
    DuplicateEntityError,
    ValidationError,
    CascadingError,
    materia_service,
    comision_service,
    horario_service,
)
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario import Horario
from src.database.models import MateriaDB, ComisionDB, HorarioDB

# Import relationship definitions to register relationships
import src.services.relationship_definitions


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture(name="engine")
def engine_fixture():
    """Create an in-memory SQLite engine for testing."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    """Create a database session for testing."""
    with Session(engine) as session:
        yield session


@pytest.fixture
def sample_materia():
    """Create a sample Materia domain model."""
    return Materia(
        codigo="MAT101",
        nombre="Cálculo I",
        cupo=30,
        horas_semanales=4
    )


@pytest.fixture
def sample_comision():
    """Create a sample Comision domain model."""
    return Comision(
        id="MAT101-C1",
        materia_codigo="MAT101",
        nombre="Comision Unica",
        numero=1,
        cupo=30
    )


# =============================================================================
# BaseCRUDService Tests
# =============================================================================

class TestBaseCRUDService:
    """Tests for BaseCRUDService base class."""

    def test_service_initialization(self):
        """Test that service initializes with correct attributes."""
        service = MateriaService()

        assert service.domain_model == Materia
        assert service.db_model == MateriaDB
        assert service.id_field == "codigo"

    def test_get_entity_id(self, sample_materia):
        """Test extracting entity ID from domain model."""
        service = MateriaService()

        entity_id = service._get_entity_id(sample_materia)

        assert entity_id == "MAT101"

    def test_get_model_name(self):
        """Test getting human-readable model name."""
        service = MateriaService()

        name = service._get_model_name()

        assert name == "Materia"


# =============================================================================
# MateriaService Tests
# =============================================================================

class TestMateriaService:
    """Tests for MateriaService."""

    def test_create_materia(self, session, sample_materia):
        """Test creating a materia through the service."""
        service = MateriaService()

        created = service.create(session, sample_materia)

        assert created.codigo == sample_materia.codigo
        assert created.nombre == sample_materia.nombre
        assert created.cupo == sample_materia.cupo

    def test_create_duplicate_raises_error(self, session, sample_materia):
        """Test that creating a duplicate raises DuplicateEntityError."""
        service = MateriaService()

        # Create first
        service.create(session, sample_materia)

        # Try to create duplicate
        with pytest.raises(DuplicateEntityError) as exc_info:
            service.create(session, sample_materia)

        assert "MAT101" in str(exc_info.value)
        assert "Materia" in str(exc_info.value)

    def test_get_materia(self, session, sample_materia):
        """Test getting a materia by ID."""
        service = MateriaService()
        service.create(session, sample_materia)

        retrieved = service.get(session, "MAT101")

        assert retrieved is not None
        assert retrieved.codigo == "MAT101"
        assert retrieved.nombre == "Cálculo I"

    def test_get_nonexistent_returns_none(self, session):
        """Test that getting a non-existent entity returns None."""
        service = MateriaService()

        result = service.get(session, "NONEXISTENT")

        assert result is None

    def test_get_or_raise_found(self, session, sample_materia):
        """Test get_or_raise when entity exists."""
        service = MateriaService()
        service.create(session, sample_materia)

        retrieved = service.get_or_raise(session, "MAT101")

        assert retrieved.codigo == "MAT101"

    def test_get_or_raise_not_found(self, session):
        """Test get_or_raise raises EntityNotFoundError when not found."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.get_or_raise(session, "NONEXISTENT")

        assert "NONEXISTENT" in str(exc_info.value)
        assert "Materia" in str(exc_info.value)

    def test_get_all_materias(self, session):
        """Test getting all materias."""
        service = MateriaService()

        # Create multiple materias
        materias = [
            Materia(codigo="MAT101", nombre="Cálculo I", cupo=30, horas_semanales=4),
            Materia(codigo="MAT102", nombre="Cálculo II", cupo=25, horas_semanales=4),
            Materia(codigo="FIS101", nombre="Física I", cupo=35, horas_semanales=6),
        ]
        for m in materias:
            service.create(session, m)

        all_materias = service.get_all(session)

        assert len(all_materias) == 3
        codigos = {m.codigo for m in all_materias}
        assert codigos == {"MAT101", "MAT102", "FIS101"}

    def test_get_all_with_pagination(self, session):
        """Test pagination in get_all."""
        service = MateriaService()

        # Create 5 materias
        for i in range(5):
            m = Materia(codigo=f"MAT{i:03d}", nombre=f"Materia {i}", cupo=30, horas_semanales=4)
            service.create(session, m)

        # Get first 2
        first_page = service.get_all(session, skip=0, limit=2)
        assert len(first_page) == 2

        # Get next 2
        second_page = service.get_all(session, skip=2, limit=2)
        assert len(second_page) == 2

        # Get last 1
        third_page = service.get_all(session, skip=4, limit=2)
        assert len(third_page) == 1

    def test_update_materia(self, session, sample_materia):
        """Test updating a materia."""
        service = MateriaService()
        service.create(session, sample_materia)

        # Create updated version
        updated_materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I - Actualizado",
            cupo=40,
            horas_semanales=6
        )

        result = service.update(session, updated_materia)

        assert result.nombre == "Cálculo I - Actualizado"
        assert result.cupo == 40
        assert result.horas_semanales == 6

    def test_update_nonexistent_raises_error(self, session, sample_materia):
        """Test that updating a non-existent entity raises error."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.update(session, sample_materia)

        assert "MAT101" in str(exc_info.value)

    def test_delete_materia(self, session, sample_materia):
        """Test deleting a materia."""
        service = MateriaService()
        service.create(session, sample_materia)

        result = service.delete(session, "MAT101")

        assert result is True
        assert service.get(session, "MAT101") is None

    def test_delete_nonexistent_returns_false(self, session):
        """Test that deleting a non-existent entity returns False."""
        service = MateriaService()

        result = service.delete(session, "NONEXISTENT")

        assert result is False

    def test_delete_or_raise_found(self, session, sample_materia):
        """Test delete_or_raise when entity exists."""
        service = MateriaService()
        service.create(session, sample_materia)

        result = service.delete_or_raise(session, "MAT101")

        assert result is True

    def test_delete_or_raise_not_found(self, session):
        """Test delete_or_raise raises error when not found."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError):
            service.delete_or_raise(session, "NONEXISTENT")


# =============================================================================
# ComisionService Tests
# =============================================================================

class TestComisionService:
    """Tests for ComisionService."""

    def test_create_comision(self, session, sample_materia, sample_comision):
        """Test creating a comision through the service."""
        # First create the parent materia
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        service = ComisionService()
        created = service.create(session, sample_comision)

        assert created.id == sample_comision.id
        assert created.materia_codigo == "MAT101"
        assert created.nombre == "Comision Unica"

    def test_get_by_materia(self, session, sample_materia):
        """Test getting comisiones by materia codigo."""
        # Create materia
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        # Create multiple comisiones
        service = ComisionService()
        comisiones = [
            Comision(id="MAT101-C1", materia_codigo="MAT101", nombre="Comisión 1", numero=1, cupo=30),
            Comision(id="MAT101-C2", materia_codigo="MAT101", nombre="Comisión 2", numero=2, cupo=25),
        ]
        for c in comisiones:
            service.create(session, c)

        # Get by materia
        result = service.get_by_materia(session, "MAT101")

        assert len(result) == 2
        ids = {c.id for c in result}
        assert ids == {"MAT101-C1", "MAT101-C2"}


# =============================================================================
# Service Singleton Tests
# =============================================================================

class TestServiceSingletons:
    """Tests for pre-instantiated service singletons."""

    def test_materia_service_singleton(self):
        """Test that materia_service is properly instantiated."""
        assert materia_service is not None
        assert isinstance(materia_service, MateriaService)

    def test_comision_service_singleton(self):
        """Test that comision_service is properly instantiated."""
        assert comision_service is not None
        assert isinstance(comision_service, ComisionService)

    def test_horario_service_singleton(self):
        """Test that horario_service is properly instantiated."""
        assert horario_service is not None
        assert isinstance(horario_service, HorarioService)



# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Custom strategies for generating valid domain models
@st.composite
def valid_materia_strategy(draw):
    """Generate valid Materia instances for property testing."""
    # Generate a unique codigo (alphanumeric, 3-10 chars)
    codigo = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd')),
        min_size=3,
        max_size=10
    ))
    assume(len(codigo.strip()) >= 3)  # Ensure non-empty after strip

    # Generate nombre (non-empty string)
    nombre = draw(st.text(min_size=1, max_size=100))
    assume(len(nombre.strip()) >= 1)

    # Generate positive integers for cupo and horas_semanales
    cupo = draw(st.integers(min_value=1, max_value=500))
    horas_semanales = draw(st.integers(min_value=1, max_value=40))

    return Materia(
        codigo=codigo,
        nombre=nombre,
        cupo=cupo,
        horas_semanales=horas_semanales
    )


@st.composite
def valid_comision_strategy(draw, materia_codigo: str = "MAT001"):
    """Generate valid Comision instances for property testing."""
    # Generate a unique id
    id_suffix = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd')),
        min_size=1,
        max_size=5
    ))
    assume(len(id_suffix.strip()) >= 1)
    comision_id = f"{materia_codigo}-{id_suffix}"

    # Generate nombre
    nombre = draw(st.text(min_size=1, max_size=50))
    assume(len(nombre.strip()) >= 1)

    # Generate numero and cupo
    numero = draw(st.integers(min_value=1, max_value=20))
    cupo = draw(st.integers(min_value=1, max_value=500))

    return Comision(
        id=comision_id,
        materia_codigo=materia_codigo,
        nombre=nombre,
        numero=numero,
        cupo=cupo
    )


class TestCRUDServicePropertyBased:
    """
    Property-based tests for CRUD Service Layer.

    These tests verify universal properties that should hold across all inputs.
    """

    # **Feature: hierarchical-entity-ui, Property 1: CRUD Service Domain Model Round-Trip**
    # **Validates: Requirements 1.1, 1.3**
    @given(materia=valid_materia_strategy())
    @settings(max_examples=100)
    def test_materia_crud_round_trip(self, materia):
        """
        Property 1: CRUD Service Domain Model Round-Trip

        For any domain model instance, creating it via the CRUD service
        and then retrieving it SHALL return an equivalent domain model instance.

        **Validates: Requirements 1.1, 1.3**
        """
        # Create fresh engine and session for each test
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            service = MateriaService()

            # Create the materia
            created = service.create(session, materia)

            # Retrieve it
            retrieved = service.get(session, materia.codigo)

            # Verify round-trip preserves data
            assert retrieved is not None
            assert retrieved.codigo == materia.codigo
            assert retrieved.nombre == materia.nombre
            assert retrieved.cupo == materia.cupo
            assert retrieved.horas_semanales == materia.horas_semanales

    # **Feature: hierarchical-entity-ui, Property 1: CRUD Service Domain Model Round-Trip**
    # **Validates: Requirements 1.1, 1.3**
    @given(comision=valid_comision_strategy())
    @settings(max_examples=100)
    def test_comision_crud_round_trip(self, comision):
        """
        Property 1: CRUD Service Domain Model Round-Trip (Comision variant)

        For any Comision domain model instance, creating it via the CRUD service
        and then retrieving it SHALL return an equivalent domain model instance.

        **Validates: Requirements 1.1, 1.3**
        """
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            # First create the parent materia
            materia = Materia(
                codigo="MAT001",
                nombre="Test Materia",
                cupo=30,
                horas_semanales=4
            )
            materia_svc = MateriaService()
            materia_svc.create(session, materia)

            # Now create and retrieve the comision
            service = ComisionService()
            created = service.create(session, comision)

            # Retrieve it
            retrieved = service.get(session, comision.id)

            # Verify round-trip preserves data
            assert retrieved is not None
            assert retrieved.id == comision.id
            assert retrieved.materia_codigo == comision.materia_codigo
            assert retrieved.nombre == comision.nombre
            assert retrieved.numero == comision.numero
            assert retrieved.cupo == comision.cupo



# =============================================================================
# Cascading Operations Tests
# =============================================================================

class TestCascadingOperations:
    """Tests for cascading operations in CRUD services."""

    def test_create_with_cascading_creates_parent(self, session, sample_materia):
        """Test that create_with_cascading creates the parent entity."""
        service = MateriaService()

        created, children = service.create_with_cascading(session, sample_materia)

        assert created.codigo == sample_materia.codigo
        assert created.nombre == sample_materia.nombre

    def test_create_with_cascading_does_not_create_comision(self, session, sample_materia):
        """Test that create_with_cascading does NOT create comisiones (cascading_create=False)."""
        service = MateriaService()

        created, children = service.create_with_cascading(session, sample_materia)

        # No cascading children should be created
        assert len(children) == 0

        # Verify no comisiones exist
        comision_svc = ComisionService()
        comisiones = comision_svc.get_by_materia(session, sample_materia.codigo)
        assert len(comisiones) == 0

    def test_create_with_cascading_duplicate_raises_error(self, session, sample_materia):
        """Test that create_with_cascading raises error for duplicates."""
        service = MateriaService()

        # Create first
        service.create_with_cascading(session, sample_materia)

        # Try to create duplicate
        with pytest.raises(DuplicateEntityError):
            service.create_with_cascading(session, sample_materia)

    def test_get_children_returns_child_entities(self, session, sample_materia):
        """Test that get_children returns all child entities."""
        # Create materia (no cascading comision creation)
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        # Add comisiones manually
        comision_svc = ComisionService()
        for i, name in enumerate(["Comision 1", "Comision 2"], start=1):
            comision = Comision(
                id=f"MAT101-C{i}",
                materia_codigo="MAT101",
                nombre=name,
                numero=i,
                cupo=25
            )
            comision_svc.create(session, comision)

        # Get children
        children = materia_svc.get_children(session, "MAT101", Comision)

        assert len(children) == 2
        ids = {c.id for c in children}
        assert "MAT101-C1" in ids
        assert "MAT101-C2" in ids

    def test_delete_with_cascading_deletes_children(self, session, sample_materia):
        """Test that delete_with_cascading deletes child entities."""
        # Create materia and a comision manually
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        comision_svc = ComisionService()
        comision = Comision(
            id="MAT101-C1",
            materia_codigo="MAT101",
            nombre="Comision Unica",
            numero=1,
            cupo=25
        )
        comision_svc.create(session, comision)

        # Verify comision exists
        comisiones_before = comision_svc.get_by_materia(session, "MAT101")
        assert len(comisiones_before) == 1

        # Delete with cascading
        result = materia_svc.delete_with_cascading(session, "MAT101")

        assert result is True

        # Verify materia is deleted
        assert materia_svc.get(session, "MAT101") is None

        # Verify comisiones are deleted
        comisiones_after = comision_svc.get_by_materia(session, "MAT101")
        assert len(comisiones_after) == 0

    def test_delete_with_cascading_nonexistent_raises_error(self, session):
        """Test that delete_with_cascading raises error for non-existent entity."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError):
            service.delete_with_cascading(session, "NONEXISTENT")



class TestCascadingCreationPropertyBased:
    """
    Property-based tests for cascading creation operations.

    **Feature: hierarchical-entity-ui, Property 2: CRUD Service Cascading Creation**
    **Validates: Requirements 1.4**
    """

    # **Feature: hierarchical-entity-ui, Property 2: CRUD Service Cascading Creation**
    # **Validates: Requirements 1.4**
    @given(materia=valid_materia_strategy())
    @settings(max_examples=100)
    def test_cascading_creation_does_not_create_comision(self, materia):
        """
        Property 2: CRUD Service Cascading Creation

        With cascading_create=False for Materia→Comision, creating a materia
        via create_with_cascading SHALL NOT create comisiones automatically.
        Comisiones are now created from horario loading.

        **Validates: Requirements 1.4**
        """
        # Create fresh engine and session for each test
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            service = MateriaService()

            # Create with cascading
            created_parent, created_children = service.create_with_cascading(session, materia)

            # Verify parent was created
            assert created_parent.codigo == materia.codigo

            # No children should be created (cascading_create=False)
            assert len(created_children) == 0

            # Verify no comisiones exist
            comision_svc = ComisionService()
            comisiones = comision_svc.get_by_materia(session, materia.codigo)
            assert len(comisiones) == 0



# =============================================================================
# Error Handling Tests
# =============================================================================

class TestErrorHandling:
    """Tests for error handling in CRUD services."""

    def test_entity_not_found_error_message(self):
        """Test EntityNotFoundError has descriptive message."""
        error = EntityNotFoundError("Materia", "MAT999")

        assert "Materia" in str(error)
        assert "MAT999" in str(error)
        assert error.model_name == "Materia"
        assert error.entity_id == "MAT999"

    def test_duplicate_entity_error_message(self):
        """Test DuplicateEntityError has descriptive message."""
        error = DuplicateEntityError("Materia", "MAT101")

        assert "Materia" in str(error)
        assert "MAT101" in str(error)
        assert error.model_name == "Materia"
        assert error.entity_id == "MAT101"

    def test_validation_error_message(self):
        """Test ValidationError has descriptive message."""
        error = ValidationError("Materia", "cupo must be positive")

        assert "Materia" in str(error)
        assert "cupo must be positive" in str(error)
        assert error.model_name == "Materia"

    def test_relationship_error_message(self):
        """Test RelationshipError has descriptive message."""
        from src.services.crud_services import RelationshipError

        error = RelationshipError("Comision", "materia_codigo", "INVALID")

        assert "Comision" in str(error)
        assert "materia_codigo" in str(error)
        assert "INVALID" in str(error)

    def test_cascading_error_message(self):
        """Test CascadingError has descriptive message."""
        error = CascadingError("create", "Materia", "Comision", "Failed to create child")

        assert "create" in str(error)
        assert "Materia" in str(error)
        assert "Comision" in str(error)
        assert "Failed to create child" in str(error)

    def test_get_nonexistent_entity_returns_none(self, session):
        """Test that getting a non-existent entity returns None (not error)."""
        service = MateriaService()

        result = service.get(session, "NONEXISTENT")

        assert result is None

    def test_get_or_raise_nonexistent_raises_error(self, session):
        """Test that get_or_raise raises EntityNotFoundError."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.get_or_raise(session, "NONEXISTENT")

        assert exc_info.value.model_name == "Materia"
        assert exc_info.value.entity_id == "NONEXISTENT"

    def test_create_duplicate_raises_error(self, session, sample_materia):
        """Test that creating a duplicate raises DuplicateEntityError."""
        service = MateriaService()

        service.create(session, sample_materia)

        with pytest.raises(DuplicateEntityError) as exc_info:
            service.create(session, sample_materia)

        assert exc_info.value.model_name == "Materia"
        assert exc_info.value.entity_id == "MAT101"

    def test_update_nonexistent_raises_error(self, session, sample_materia):
        """Test that updating a non-existent entity raises EntityNotFoundError."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.update(session, sample_materia)

        assert exc_info.value.model_name == "Materia"
        assert exc_info.value.entity_id == "MAT101"

    def test_delete_or_raise_nonexistent_raises_error(self, session):
        """Test that delete_or_raise raises EntityNotFoundError."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.delete_or_raise(session, "NONEXISTENT")

        assert exc_info.value.model_name == "Materia"
        assert exc_info.value.entity_id == "NONEXISTENT"

    def test_delete_with_cascading_nonexistent_raises_error(self, session):
        """Test that delete_with_cascading raises EntityNotFoundError."""
        service = MateriaService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            service.delete_with_cascading(session, "NONEXISTENT")

        assert exc_info.value.model_name == "Materia"
        assert exc_info.value.entity_id == "NONEXISTENT"



class TestErrorHandlingPropertyBased:
    """
    Property-based tests for error handling in CRUD services.

    **Feature: hierarchical-entity-ui, Property 3: CRUD Service Error Handling**
    **Validates: Requirements 1.5**
    """

    # **Feature: hierarchical-entity-ui, Property 3: CRUD Service Error Handling**
    # **Validates: Requirements 1.5**
    @given(materia=valid_materia_strategy())
    @settings(max_examples=100)
    def test_duplicate_creation_raises_error(self, materia):
        """
        Property 3: CRUD Service Error Handling (Duplicate Creation)

        For any invalid CRUD operation (creating duplicate ID), the service
        SHALL raise an appropriate exception with a descriptive message.

        **Validates: Requirements 1.5**
        """
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            service = MateriaService()

            # Create first instance
            service.create(session, materia)

            # Try to create duplicate - should raise DuplicateEntityError
            with pytest.raises(DuplicateEntityError) as exc_info:
                service.create(session, materia)

            # Verify error has descriptive message
            assert materia.codigo in str(exc_info.value)
            assert "Materia" in str(exc_info.value)

    # **Feature: hierarchical-entity-ui, Property 3: CRUD Service Error Handling**
    # **Validates: Requirements 1.5**
    @given(entity_id=st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
        min_size=1,
        max_size=20
    ))
    @settings(max_examples=100)
    def test_update_nonexistent_raises_error(self, entity_id):
        """
        Property 3: CRUD Service Error Handling (Update Non-existent)

        For any invalid CRUD operation (updating non-existent entity), the service
        SHALL raise an appropriate exception with a descriptive message.

        **Validates: Requirements 1.5**
        """
        # Skip empty or whitespace-only IDs
        assume(len(entity_id.strip()) >= 1)

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            service = MateriaService()

            # Create a materia with the generated ID
            materia = Materia(
                codigo=entity_id,
                nombre="Test Materia",
                cupo=30,
                horas_semanales=4
            )

            # Try to update without creating first - should raise EntityNotFoundError
            with pytest.raises(EntityNotFoundError) as exc_info:
                service.update(session, materia)

            # Verify error has descriptive message
            assert entity_id.strip() in str(exc_info.value)
            assert "Materia" in str(exc_info.value)

    # **Feature: hierarchical-entity-ui, Property 3: CRUD Service Error Handling**
    # **Validates: Requirements 1.5**
    @given(entity_id=st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Ll', 'Nd')),
        min_size=1,
        max_size=20
    ))
    @settings(max_examples=100)
    def test_get_or_raise_nonexistent_raises_error(self, entity_id):
        """
        Property 3: CRUD Service Error Handling (Get Non-existent)

        For any invalid CRUD operation (getting non-existent entity with get_or_raise),
        the service SHALL raise an appropriate exception with a descriptive message.

        **Validates: Requirements 1.5**
        """
        # Skip empty or whitespace-only IDs
        assume(len(entity_id.strip()) >= 1)

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            service = MateriaService()

            # Try to get non-existent entity - should raise EntityNotFoundError
            with pytest.raises(EntityNotFoundError) as exc_info:
                service.get_or_raise(session, entity_id)

            # Verify error has descriptive message
            assert entity_id in str(exc_info.value)
            assert "Materia" in str(exc_info.value)



# =============================================================================
# Entity-Specific Service Tests
# =============================================================================

from src.services.crud_services import (
    aula_service,
    AulaService,
)
from src.domain.problem.aula import Aula
from src.domain.problem.horario import Horario
from datetime import time


class TestEntitySpecificServices:
    """Tests for entity-specific service classes."""

    def test_aula_service_create_and_get(self, session):
        """Test AulaService create and get operations."""
        service = AulaService()

        aula = Aula(
            id="AULA-101",
            sede_id="sede-test",
            codigo_aula="AULA-101",
            nombre="Aula 101",
            capacidad=50,
            tipo="teorica",
            descripcion="Aula de teoría"
        )

        created = service.create(session, aula)

        assert created.id == "AULA-101"
        assert created.nombre == "Aula 101"
        assert created.capacidad == 50

        retrieved = service.get(session, "AULA-101")
        assert retrieved is not None
        assert retrieved.id == "AULA-101"

    def test_horario_service_create_and_get(self, session, sample_materia):
        """Test HorarioService create and get operations."""
        # Create materia and comision first (dependencies)
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        comision_svc = ComisionService()
        comision_svc.create(session, Comision(
            id="MAT101-C1", materia_codigo="MAT101",
            nombre="Comision Unica", numero=1, cupo=30
        ))

        service = HorarioService()

        horario = Horario(
            id="HOR-001",
            comision_id="MAT101-C1",
            codigo_materia="MAT101",
            dia="Lunes",
            hora_inicio=time(8, 0),
            hora_fin=time(10, 0)
        )

        created = service.create(session, horario)

        assert created.id == "HOR-001"
        assert created.comision_id == "MAT101-C1"
        assert created.codigo_materia == "MAT101"
        assert created.dia == "Lunes"

        retrieved = service.get(session, "HOR-001")
        assert retrieved is not None
        assert retrieved.id == "HOR-001"

    def test_horario_service_get_by_comision(self, session, sample_materia):
        """Test HorarioService get_by_comision method."""
        # Create materia and comision first
        materia_svc = MateriaService()
        materia_svc.create(session, sample_materia)

        comision_svc = ComisionService()
        comision_svc.create(session, Comision(
            id="MAT101-C1", materia_codigo="MAT101",
            nombre="Comision Unica", numero=1, cupo=30
        ))

        # Create a horario
        horario_svc = HorarioService()
        horario = Horario(
            id="HOR-001",
            comision_id="MAT101-C1",
            codigo_materia="MAT101",
            dia="Lunes",
            hora_inicio=time(8, 0),
            hora_fin=time(10, 0)
        )
        horario_svc.create(session, horario)

        # Get horarios by comision
        horarios = horario_svc.get_by_comision(session, "MAT101-C1")

        assert len(horarios) == 1
        assert horarios[0].id == "HOR-001"

    def test_service_singletons_are_correct_types(self):
        """Test that service singletons are correctly instantiated."""
        from src.services.crud_services import (
            materia_service, comision_service,
            aula_service, horario_service
        )

        assert isinstance(materia_service, MateriaService)
        assert isinstance(comision_service, ComisionService)
        assert isinstance(aula_service, AulaService)
        assert isinstance(horario_service, HorarioService)
