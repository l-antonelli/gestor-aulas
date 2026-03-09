"""
Tests for Carrera-Materia Relationship.

This module tests the Carrera-Materia many-to-many relationship,
including relationship validation and cascading delete warnings.

Requirements: 8.1, 8.2, 8.4, 8.5
"""

import uuid
import pytest
from datetime import date
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool
from hypothesis import given, strategies as st, settings, assume

from src.domain.problem.materia import Materia
from src.domain.problem.carrera import Carrera
from src.services.crud_services import (
    MateriaService,
    CarreraService,
    EntityNotFoundError,
    carrera_service,
)
from src.database.models import MateriaDB, CarreraDB, PlanEstudioDB, PlanCarreraVersionDB
from src.services.relationship_registry import RelationshipRegistry

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
def sample_carrera():
    """Create a sample Carrera domain model."""
    return Carrera(
        codigo="ING-ELECT",
        nombre="Ingeniería Electrónica",
        titulo_otorgado="Ingeniero Electrónico",
        duracion_anios=5
    )


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
def plan_version(session, sample_carrera):
    """Create a plan version for the sample carrera (requires carrera to exist in DB first)."""
    carrera_svc = CarreraService()
    carrera_svc.create(session, sample_carrera)
    v = PlanCarreraVersionDB(
        id=str(uuid.uuid4()),
        carrera_codigo=sample_carrera.codigo,
        nombre="Plan Test",
        fecha_creacion=date(2025, 1, 1),
    )
    session.add(v)
    session.commit()
    return v


# =============================================================================
# CarreraService Basic Tests
# =============================================================================

class TestCarreraService:
    """Tests for CarreraService basic operations."""

    def test_create_carrera(self, session, sample_carrera):
        """Test creating a carrera through the service."""
        service = CarreraService()

        created = service.create(session, sample_carrera)

        assert created.codigo == sample_carrera.codigo
        assert created.nombre == sample_carrera.nombre
        assert created.titulo_otorgado == sample_carrera.titulo_otorgado
        assert created.duracion_anios == sample_carrera.duracion_anios

    def test_get_carrera(self, session, sample_carrera):
        """Test getting a carrera by ID."""
        service = CarreraService()
        service.create(session, sample_carrera)

        retrieved = service.get(session, "ING-ELECT")

        assert retrieved is not None
        assert retrieved.codigo == "ING-ELECT"
        assert retrieved.nombre == "Ingeniería Electrónica"

    def test_get_materias_empty(self, session, plan_version):
        """Test getting materias for a carrera with no associations."""
        service = CarreraService()

        materias = service.get_materias(session, "ING-ELECT", plan_version_id=plan_version.id)

        assert len(materias) == 0

    def test_add_materia_to_carrera(self, session, plan_version, sample_materia):
        """Test adding a materia to a carrera."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)

        result = carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)

        assert result is True

        materias = carrera_svc.get_materias(session, "ING-ELECT", plan_version_id=plan_version.id)
        assert len(materias) == 1
        assert materias[0].codigo == "MAT101"

    def test_add_materia_duplicate_returns_false(self, session, plan_version, sample_materia):
        """Test that adding the same materia twice returns False."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)

        result1 = carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)
        assert result1 is True

        result2 = carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)
        assert result2 is False

    def test_add_materia_nonexistent_carrera_raises_error(self, session, sample_materia, plan_version):
        """Test that adding materia to non-existent carrera raises error."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)

        with pytest.raises(EntityNotFoundError) as exc_info:
            carrera_svc.add_materia(session, "NONEXISTENT", "MAT101", plan_version_id=plan_version.id)

        assert "Carrera" in str(exc_info.value)

    def test_add_materia_nonexistent_materia_raises_error(self, session, plan_version):
        """Test that adding non-existent materia raises error."""
        carrera_svc = CarreraService()

        with pytest.raises(EntityNotFoundError) as exc_info:
            carrera_svc.add_materia(session, "ING-ELECT", "NONEXISTENT", plan_version_id=plan_version.id)

        assert "Materia" in str(exc_info.value)

    def test_remove_materia_from_carrera(self, session, plan_version, sample_materia):
        """Test removing a materia from a carrera."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)
        carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)

        result = carrera_svc.remove_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)

        assert result is True

        materias = carrera_svc.get_materias(session, "ING-ELECT", plan_version_id=plan_version.id)
        assert len(materias) == 0

    def test_remove_materia_nonexistent_returns_false(self, session, plan_version):
        """Test that removing non-existent association returns False."""
        carrera_svc = CarreraService()

        result = carrera_svc.remove_materia(session, "ING-ELECT", "NONEXISTENT", plan_version_id=plan_version.id)

        assert result is False

    def test_get_children_count(self, session, plan_version, sample_materia):
        """Test getting the count of materias for a carrera."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)

        count = carrera_svc.get_children_count(session, "ING-ELECT", plan_version_id=plan_version.id)
        assert count == 0

        carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)

        count = carrera_svc.get_children_count(session, "ING-ELECT", plan_version_id=plan_version.id)
        assert count == 1

    def test_create_plan_version(self, session, plan_version):
        """Test creating a new plan version."""
        carrera_svc = CarreraService()

        new_version = carrera_svc.create_plan_version(session, "ING-ELECT", "Plan 2025")
        assert new_version.nombre == "Plan 2025"
        assert new_version.carrera_codigo == "ING-ELECT"

        versions = carrera_svc.get_plan_versions(session, "ING-ELECT")
        assert len(versions) == 2

    def test_create_plan_version_with_copy(self, session, plan_version, sample_materia):
        """Test creating a new plan version by copying from existing."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materia_svc.create(session, sample_materia)
        carrera_svc.add_materia(session, "ING-ELECT", "MAT101", plan_version_id=plan_version.id)

        new_version = carrera_svc.create_plan_version(
            session, "ING-ELECT", "Plan 2025",
            copy_from_version_id=plan_version.id,
        )

        materias = carrera_svc.get_materias(session, "ING-ELECT", plan_version_id=new_version.id)
        assert len(materias) == 1
        assert materias[0].codigo == "MAT101"


# =============================================================================
# Carrera-Materia Relationship Registration Tests
# =============================================================================

class TestCarreraMateriaRelationshipRegistration:
    """Tests for Carrera-Materia relationship registration."""
    
    def test_carrera_materia_relationship_is_registered(self):
        """Test that Carrera-Materia relationship is registered."""
        relationship = RelationshipRegistry.get_relationship(Carrera, Materia)
        
        assert relationship is not None
        assert relationship.parent_model == Carrera
        assert relationship.child_model == Materia
    
    def test_carrera_materia_is_many_to_many(self):
        """Test that Carrera-Materia relationship is marked as many-to-many."""
        relationship = RelationshipRegistry.get_relationship(Carrera, Materia)
        
        assert relationship.is_many_to_many is True
        assert relationship.link_table == "plan_estudio"
        assert relationship.parent_link_field == "carrera_codigo"
        assert relationship.child_link_field == "materia_codigo"
    
    def test_carrera_materia_display_fields(self):
        """Test that Carrera-Materia relationship has correct display fields."""
        relationship = RelationshipRegistry.get_relationship(Carrera, Materia)
        
        assert "codigo" in relationship.display_fields
        assert "nombre" in relationship.display_fields
    
    def test_carrera_materia_search_fields(self):
        """Test that Carrera-Materia relationship has correct search fields."""
        relationship = RelationshipRegistry.get_relationship(Carrera, Materia)
        
        assert "codigo" in relationship.search_fields
        assert "nombre" in relationship.search_fields
    
    def test_carrera_materia_delete_behavior_is_restrict(self):
        """Test that Carrera-Materia relationship has restrict delete behavior."""
        relationship = RelationshipRegistry.get_relationship(Carrera, Materia)
        
        assert relationship.delete_behavior == "restrict"


# =============================================================================
# Property-Based Tests
# =============================================================================

# Custom strategies for generating valid domain models
@st.composite
def valid_carrera_strategy(draw):
    """Generate valid Carrera instances for property testing."""
    # Generate a unique codigo (alphanumeric with hyphens, 3-15 chars)
    codigo = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd'), whitelist_characters='-'),
        min_size=3,
        max_size=15
    ))
    assume(len(codigo.strip()) >= 3)
    assume(not codigo.startswith('-') and not codigo.endswith('-'))
    
    # Generate nombre (non-empty string)
    nombre = draw(st.text(min_size=1, max_size=100))
    assume(len(nombre.strip()) >= 1)
    
    # Generate titulo_otorgado
    titulo = draw(st.text(min_size=0, max_size=100))
    
    # Generate duracion_anios
    duracion = draw(st.integers(min_value=1, max_value=10))
    
    return Carrera(
        codigo=codigo,
        nombre=nombre,
        titulo_otorgado=titulo,
        duracion_anios=duracion
    )


@st.composite
def valid_materia_strategy(draw):
    """Generate valid Materia instances for property testing."""
    # Generate a unique codigo (alphanumeric, 3-10 chars)
    codigo = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd')),
        min_size=3,
        max_size=10
    ))
    assume(len(codigo.strip()) >= 3)
    
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


class TestRelationshipValidationPropertyBased:
    """Property-based tests for relationship validation."""

    @given(carrera=valid_carrera_strategy(), materia=valid_materia_strategy())
    @settings(max_examples=100)
    def test_relationship_validation_requires_existing_entities(self, carrera, materia):
        """Property 10: Relationship Validation - FK references must exist."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            carrera_svc = CarreraService()
            materia_svc = MateriaService()

            materia_svc.create(session, materia)

            # Create a plan version for the test (needs carrera first)
            # Test 1: Adding materia to non-existent carrera should fail
            with pytest.raises(EntityNotFoundError) as exc_info:
                carrera_svc.add_materia(session, carrera.codigo, materia.codigo, plan_version_id="dummy")

            assert exc_info.value.model_name == "Carrera"
            assert exc_info.value.entity_id == carrera.codigo

        with Session(engine) as session:
            carrera_svc = CarreraService()

            carrera_svc.create(session, carrera)

            # Create plan version
            v = PlanCarreraVersionDB(
                id=str(uuid.uuid4()), carrera_codigo=carrera.codigo,
                nombre="Test", fecha_creacion=date(2025, 1, 1),
            )
            session.add(v)
            session.commit()

            nonexistent_materia_codigo = materia.codigo + "_NONEXISTENT"

            with pytest.raises(EntityNotFoundError) as exc_info:
                carrera_svc.add_materia(session, carrera.codigo, nonexistent_materia_codigo, plan_version_id=v.id)

            assert exc_info.value.model_name == "Materia"

        engine2 = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine2)

        with Session(engine2) as session:
            carrera_svc = CarreraService()
            materia_svc = MateriaService()

            carrera_svc.create(session, carrera)
            materia_svc.create(session, materia)

            v = PlanCarreraVersionDB(
                id=str(uuid.uuid4()), carrera_codigo=carrera.codigo,
                nombre="Test", fecha_creacion=date(2025, 1, 1),
            )
            session.add(v)
            session.commit()

            result = carrera_svc.add_materia(session, carrera.codigo, materia.codigo, plan_version_id=v.id)

            assert result is True

            materias = carrera_svc.get_materias(session, carrera.codigo, plan_version_id=v.id)
            assert len(materias) == 1
            assert materias[0].codigo == materia.codigo


class TestCascadingDeleteWarningPropertyBased:
    """Property-based tests for cascading delete warning."""

    @given(carrera=valid_carrera_strategy(), materia=valid_materia_strategy())
    @settings(max_examples=100)
    def test_cascading_delete_warning_for_carrera_with_materias(self, carrera, materia):
        """Property 11: Cascading Delete Warning."""
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        SQLModel.metadata.create_all(engine)

        with Session(engine) as session:
            carrera_svc = CarreraService()
            materia_svc = MateriaService()

            carrera_svc.create(session, carrera)
            materia_svc.create(session, materia)

            v = PlanCarreraVersionDB(
                id=str(uuid.uuid4()), carrera_codigo=carrera.codigo,
                nombre="Test", fecha_creacion=date(2025, 1, 1),
            )
            session.add(v)
            session.commit()

            carrera_svc.add_materia(session, carrera.codigo, materia.codigo, plan_version_id=v.id)

            count = carrera_svc.get_children_count(session, carrera.codigo, plan_version_id=v.id)
            assert count == 1

            materias = carrera_svc.get_materias(session, carrera.codigo, plan_version_id=v.id)
            assert len(materias) == 1

            carrera_svc.remove_materia(session, carrera.codigo, materia.codigo, plan_version_id=v.id)

            count_after = carrera_svc.get_children_count(session, carrera.codigo, plan_version_id=v.id)
            assert count_after == 0

            # Must delete the plan version before deleting the carrera
            session.delete(v)
            session.commit()

            result = carrera_svc.delete(session, carrera.codigo)
            assert result is True

            assert carrera_svc.get(session, carrera.codigo) is None


# =============================================================================
# Integration Tests
# =============================================================================

class TestCarreraMateriaIntegration:
    """Integration tests for Carrera-Materia relationship."""

    def test_multiple_materias_per_carrera(self, session, plan_version):
        """Test that a carrera can have multiple materias."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        materias = [
            Materia(codigo="MAT101", nombre="Calculo I", cupo=30, horas_semanales=4),
            Materia(codigo="MAT102", nombre="Calculo II", cupo=25, horas_semanales=4),
            Materia(codigo="FIS101", nombre="Fisica I", cupo=35, horas_semanales=6),
        ]

        for m in materias:
            materia_svc.create(session, m)
            carrera_svc.add_materia(session, "ING-ELECT", m.codigo, plan_version_id=plan_version.id)

        result = carrera_svc.get_materias(session, "ING-ELECT", plan_version_id=plan_version.id)
        assert len(result) == 3

        codigos = {m.codigo for m in result}
        assert codigos == {"MAT101", "MAT102", "FIS101"}

    def test_materia_in_multiple_carreras(self, session, sample_materia):
        """Test that a materia can belong to multiple carreras (M:N)."""
        carrera_svc = CarreraService()
        materia_svc = MateriaService()

        carreras = [
            Carrera(codigo="ING-ELECT", nombre="Ingenieria Electronica", titulo_otorgado="Ing. Electronico", duracion_anios=5),
            Carrera(codigo="ING-SIST", nombre="Ingenieria en Sistemas", titulo_otorgado="Ing. en Sistemas", duracion_anios=5),
            Carrera(codigo="LIC-MAT", nombre="Licenciatura en Matematica", titulo_otorgado="Lic. en Matematica", duracion_anios=4),
        ]

        versions = []
        for c in carreras:
            carrera_svc.create(session, c)
            v = PlanCarreraVersionDB(
                id=str(uuid.uuid4()), carrera_codigo=c.codigo,
                nombre="Test", fecha_creacion=date(2025, 1, 1),
            )
            session.add(v)
            versions.append(v)
        session.commit()

        materia_svc.create(session, sample_materia)

        for c, v in zip(carreras, versions):
            carrera_svc.add_materia(session, c.codigo, sample_materia.codigo, plan_version_id=v.id)

        for c, v in zip(carreras, versions):
            materias = carrera_svc.get_materias(session, c.codigo, plan_version_id=v.id)
            assert len(materias) == 1
            assert materias[0].codigo == sample_materia.codigo

    def test_carrera_service_singleton(self):
        """Test that carrera_service singleton is properly instantiated."""
        assert carrera_service is not None
        assert isinstance(carrera_service, CarreraService)
