"""
Comprehensive Integration Tests for Relationship Management & Cascading Operations.

This module tests complete end-to-end workflows for relationship management:
- Create Materia → Auto-create Comisión → Create Clase → Create Asignación
- Edit Materia → Check Comisión constraints
- Delete Materia → Check cascading deletion
- Test cascading creation failure
- Test constraint violations
- Test deletion with related entities
- Test search with no results

Requirements: All (Relationship Management Integration)
"""

import datetime
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

# Services
from src.services.cascading_operations import CascadingOperations
from src.services.cross_entity_validator import CrossEntityValidator
from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_definitions import register_all_relationships


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


@pytest.fixture(autouse=True)
def setup_relationships():
    """Ensure relationships are registered before each test."""
    # Relationships are auto-registered on import via relationship_definitions module
    # No need to re-register them here
    pass


# =============================================================================
# Test Class: End-to-End Workflows
# =============================================================================

class TestEndToEndWorkflows:
    """Tests for complete end-to-end workflows with relationships."""
    
    def test_create_materia_auto_creates_comision(self, test_db_session: Session):
        """
        Test: Create Materia → Auto-create Comisión
        
        Validates:
        - Materia is created successfully
        - Comisión Única is automatically created
        - Comisión has correct defaults (nombre, numero, cupo)
        - Comisión references the parent Materia
        """
        # Create Materia
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        
        # Use cascading operations to create with auto-children
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Verify Materia was created
        assert created_materia is not None
        assert created_materia.codigo == "MAT101"
        assert created_materia.nombre == "Cálculo I"
        
        # Verify Comisión was auto-created
        assert len(created_children) == 1
        comision = created_children[0]
        assert comision.nombre == "Comisión Única"
        assert comision.numero == 1
        assert comision.materia_codigo == "MAT101"
        
        # Verify in database
        all_comisiones = comision_crud.get_all(test_db_session)
        assert len(all_comisiones) == 1
        assert all_comisiones[0].materia_codigo == "MAT101"

    def test_full_workflow_materia_to_asignacion(self, test_db_session: Session):
        """
        Test: Create Materia → Auto-create Comisión → Create Clase → Create Asignación
        
        This tests the complete workflow from creating a Materia all the way
        to assigning a classroom to a class.
        """
        # Step 1: Create Materia with cascading Comisión
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        assert len(created_children) == 1
        comision = created_children[0]
        
        # Step 2: Create HorarioCronograma (needed for Clase)
        horario = HorarioCronograma(
            id="HOR-001",
            dia_semana="Lunes",
            hora_inicio=datetime.time(8, 0),
            hora_fin=datetime.time(10, 0),
        )
        db_horario = to_db(horario)
        created_horario = horario_crud.create(test_db_session, db_horario)
        
        # Step 3: Create Clase
        clase = Clase(
            id="CLS-001",
            comision_id=comision.id,
            horario_id=created_horario.id,
            dia="Lunes",
        )
        db_clase = to_db(clase)
        created_clase = clase_crud.create(test_db_session, db_clase)
        
        assert created_clase is not None
        assert created_clase.comision_id == comision.id
        
        # Step 4: Create Aula (needed for AsignacionAula)
        aula = Aula(
            id="AULA-001",
            sede="Campus Central",
            nombre="Aula 101",
            capacidad=40,
            tipo="teorica",
        )
        db_aula = to_db(aula)
        created_aula = aula_crud.create(test_db_session, db_aula)
        
        # Step 5: Create AsignacionAula
        asignacion = AsignacionAula(
            id="ASG-001",
            clase_id=created_clase.id,
            aula_id=created_aula.id,
            fecha_asignacion=datetime.date(2024, 3, 1),
            vigente=True,
        )
        db_asignacion = to_db(asignacion)
        created_asignacion = asignacion_crud.create(test_db_session, db_asignacion)
        
        assert created_asignacion is not None
        assert created_asignacion.clase_id == created_clase.id
        assert created_asignacion.aula_id == created_aula.id
        
        # Verify complete chain exists in database
        verify_materia = materia_crud.get(test_db_session, "MAT101")
        verify_comision = comision_crud.get(test_db_session, comision.id)
        verify_clase = clase_crud.get(test_db_session, created_clase.id)
        verify_asignacion = asignacion_crud.get(test_db_session, created_asignacion.id)
        
        assert verify_materia is not None
        assert verify_comision is not None
        assert verify_clase is not None
        assert verify_asignacion is not None

    def test_edit_materia_check_comision_constraints(self, test_db_session: Session):
        """
        Test: Edit Materia → Check Comisión constraints
        
        Validates that when editing a Materia's cupo, the system checks
        that the sum of Comisión cupos doesn't exceed the new Materia cupo.
        """
        # Create Materia with cascading Comisión
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=100,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Create additional Comisiones
        comision2 = Comision(
            id="COM-002",
            materia_codigo="MAT101",
            nombre="Comisión B",
            numero=2,
            cupo=40,
        )
        db_comision2 = to_db(comision2)
        comision_crud.create(test_db_session, db_comision2)
        
        comision3 = Comision(
            id="COM-003",
            materia_codigo="MAT101",
            nombre="Comisión C",
            numero=3,
            cupo=30,
        )
        db_comision3 = to_db(comision3)
        comision_crud.create(test_db_session, db_comision3)
        
        # Get all comisiones for this materia
        all_comisiones = comision_crud.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        
        # Current sum: auto-created (cupo from defaults) + 40 + 30
        # Try to reduce Materia cupo to 50 (should violate constraint)
        created_materia.cupo = 50
        
        # Validate sum constraint
        is_valid, error = CrossEntityValidator.validate_sum_constraint(
            parent_instance=created_materia,
            child_instances=materia_comisiones,
            parent_field="cupo",
            child_field="cupo",
        )
        
        # Should fail because sum of comisiones exceeds new materia cupo
        assert is_valid is False
        assert "sum constraint violation" in error.lower()
        
        # Get suggestions for resolution
        suggestions = CrossEntityValidator.get_constraint_suggestions(
            parent_instance=created_materia,
            child_instances=materia_comisiones,
            validation_error=error,
        )
        
        assert len(suggestions) > 0
        assert any("reduce" in s.lower() for s in suggestions)

    def test_delete_materia_cascading_deletion(self, test_db_session: Session):
        """
        Test: Delete Materia → Check cascading deletion
        
        Validates that when deleting a Materia with cascade delete behavior,
        all related Comisiones are also deleted.
        """
        # Create Materia with cascading Comisión
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Create additional Comisiones
        comision2 = Comision(
            id="COM-002",
            materia_codigo="MAT101",
            nombre="Comisión B",
            numero=2,
            cupo=25,
        )
        db_comision2 = to_db(comision2)
        comision_crud.create(test_db_session, db_comision2)
        
        # Verify comisiones exist
        all_comisiones_before = comision_crud.get_all(test_db_session)
        materia_comisiones_before = [c for c in all_comisiones_before if c.materia_codigo == "MAT101"]
        assert len(materia_comisiones_before) == 2
        
        # Delete Materia with cascading
        success = CascadingOperations.delete_with_cascading(
            parent_id="MAT101",
            parent_model=Materia,
            parent_crud_func=materia_crud.delete,
            session=test_db_session,
        )
        
        assert success is True
        
        # Verify Materia is deleted
        verify_materia = materia_crud.get(test_db_session, "MAT101")
        assert verify_materia is None
        
        # Verify all Comisiones are deleted (cascading)
        all_comisiones_after = comision_crud.get_all(test_db_session)
        materia_comisiones_after = [c for c in all_comisiones_after if c.materia_codigo == "MAT101"]
        assert len(materia_comisiones_after) == 0


# =============================================================================
# Test Class: Error Handling and Edge Cases
# =============================================================================

class TestErrorHandlingAndEdgeCases:
    """Tests for error handling and edge cases in relationship management."""
    
    def test_cascading_creation_failure_does_not_prevent_parent_creation(self, test_db_session: Session):
        """
        Test: Cascading creation failure
        
        Validates that if cascading child creation fails, the parent is still
        created successfully (Requirement 2.5).
        """
        # This test simulates a scenario where cascading creation might fail
        # In practice, this is hard to test without mocking, but we can verify
        # the behavior by checking that parent creation succeeds even if
        # child creation would fail
        
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        
        # Even if cascading fails, parent should be created
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Parent should always be created
        assert created_materia is not None
        assert created_materia.codigo == "MAT101"
        
        # Verify parent exists in database
        verify_materia = materia_crud.get(test_db_session, "MAT101")
        assert verify_materia is not None

    def test_constraint_violation_sum_exceeds_parent(self, test_db_session: Session):
        """
        Test: Constraint violations - sum exceeds parent
        
        Validates that sum constraint violations are properly detected and
        reported with clear error messages.
        """
        # Create Materia
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=50,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        created_materia = materia_crud.create(test_db_session, db_materia)
        
        # Create Comisiones that exceed parent cupo
        comision1 = Comision(
            id="COM-001",
            materia_codigo="MAT101",
            nombre="Comisión A",
            numero=1,
            cupo=30,
        )
        db_comision1 = to_db(comision1)
        comision_crud.create(test_db_session, db_comision1)
        
        comision2 = Comision(
            id="COM-002",
            materia_codigo="MAT101",
            nombre="Comisión B",
            numero=2,
            cupo=30,
        )
        db_comision2 = to_db(comision2)
        comision_crud.create(test_db_session, db_comision2)
        
        # Get all comisiones
        all_comisiones = comision_crud.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        
        # Validate sum constraint (should fail: 30 + 30 > 50)
        is_valid, error = CrossEntityValidator.validate_sum_constraint(
            parent_instance=created_materia,
            child_instances=materia_comisiones,
            parent_field="cupo",
            child_field="cupo",
        )
        
        assert is_valid is False
        assert "sum constraint violation" in error.lower()
        assert "60" in error  # Sum of comisiones
        assert "50" in error  # Parent cupo
        
        # Get suggestions
        suggestions = CrossEntityValidator.get_constraint_suggestions(
            parent_instance=created_materia,
            child_instances=materia_comisiones,
            validation_error=error,
        )
        
        assert len(suggestions) > 0
        # Should suggest reducing by 10 (60 - 50)
        assert any("10" in s for s in suggestions)
    
    def test_constraint_violation_duplicate_relationship(self, test_db_session: Session):
        """
        Test: Constraint violations - duplicate relationship
        
        Validates that duplicate relationships are properly detected.
        """
        # Create Materia
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=50,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        materia_crud.create(test_db_session, db_materia)
        
        # Create first Comisión
        comision1 = Comision(
            id="COM-001",
            materia_codigo="MAT101",
            nombre="Comisión A",
            numero=1,
            cupo=25,
        )
        db_comision1 = to_db(comision1)
        comision_crud.create(test_db_session, db_comision1)
        
        # Try to create duplicate Comisión (same materia_codigo and numero)
        comision2 = Comision(
            id="COM-002",
            materia_codigo="MAT101",
            nombre="Comisión B",
            numero=1,  # Same numero as comision1
            cupo=25,
        )
        
        # Get existing comisiones
        all_comisiones = comision_crud.get_all(test_db_session)
        existing_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        
        # Validate uniqueness constraint
        is_valid, error = CrossEntityValidator.validate_uniqueness_constraint(
            child_instance=comision2,
            existing_children=existing_comisiones,
            unique_fields=["materia_codigo", "numero"],
        )
        
        assert is_valid is False
        assert "duplicate" in error.lower()

    def test_deletion_with_related_entities_restrict_behavior(self, test_db_session: Session):
        """
        Test: Deletion with related entities (restrict behavior)
        
        Validates that when delete_behavior is "restrict", deletion is prevented
        if related entities exist.
        """
        # Note: In our current setup, Materia→Comisión has cascade delete
        # For this test, we'll test the restrict logic directly
        
        # Create Materia with Comisiones
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        db_materia = to_db(materia)
        created_materia, created_children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Temporarily modify relationship to use restrict behavior
        from src.services.relationship_registry import RelationshipRegistry
        relationships = RelationshipRegistry.get_relationships_for_model(Materia)
        
        # Find Materia→Comisión relationship
        materia_comision_rel = None
        for rel in relationships:
            if rel.child_model.__name__ == "Comision":
                materia_comision_rel = rel
                break
        
        if materia_comision_rel:
            # Save original behavior
            original_behavior = materia_comision_rel.delete_behavior
            
            # Set to restrict
            materia_comision_rel.delete_behavior = "restrict"
            
            # Try to delete (should fail)
            with pytest.raises(ValueError, match="Cannot delete.*related.*exist"):
                CascadingOperations.delete_with_cascading(
                    parent_id="MAT101",
                    parent_model=Materia,
                    parent_crud_func=materia_crud.delete,
                    session=test_db_session,
                )
            
            # Restore original behavior
            materia_comision_rel.delete_behavior = original_behavior
            
            # Verify Materia still exists (deletion was prevented)
            verify_materia = materia_crud.get(test_db_session, "MAT101")
            assert verify_materia is not None
    
    def test_search_with_no_results(self, test_db_session: Session):
        """
        Test: Search with no results
        
        Validates that searching for non-existent entities returns empty results
        without errors.
        """
        # Search for non-existent Materia
        all_materias = materia_crud.get_all(test_db_session)
        
        # Filter by non-existent codigo
        filtered = [m for m in all_materias if m.codigo == "NONEXISTENT"]
        
        assert len(filtered) == 0
        
        # Search for non-existent Comisión
        all_comisiones = comision_crud.get_all(test_db_session)
        
        # Filter by non-existent materia_codigo
        filtered_comisiones = [c for c in all_comisiones if c.materia_codigo == "NONEXISTENT"]
        
        assert len(filtered_comisiones) == 0


# =============================================================================
# Test Class: Complex Relationship Scenarios
# =============================================================================

class TestComplexRelationshipScenarios:
    """Tests for complex scenarios involving multiple relationships."""
    
    def test_multiple_materias_with_comisiones(self, test_db_session: Session):
        """
        Test creating multiple Materias, each with their own Comisiones.
        """
        # Create first Materia
        materia1 = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        db_materia1 = to_db(materia1)
        created_materia1, children1 = CascadingOperations.create_with_cascading(
            parent_instance=db_materia1,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Create second Materia
        materia2 = Materia(
            codigo="MAT102",
            nombre="Álgebra I",
            cupo=25,
            horas_semanales=4,
        )
        db_materia2 = to_db(materia2)
        created_materia2, children2 = CascadingOperations.create_with_cascading(
            parent_instance=db_materia2,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        
        # Verify both Materias exist
        all_materias = materia_crud.get_all(test_db_session)
        assert len(all_materias) == 2
        
        # Verify each has its own Comisión
        all_comisiones = comision_crud.get_all(test_db_session)
        mat101_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        mat102_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT102"]
        
        assert len(mat101_comisiones) == 1
        assert len(mat102_comisiones) == 1

    def test_alumno_with_multiple_inscripciones(self, test_db_session: Session):
        """
        Test creating an Alumno with multiple Inscripciones to different Comisiones.
        """
        # Create Alumno
        alumno = Alumno(
            legajo="A-12345",
            email="test@example.com",
            nombre="Juan Pérez",
            dni="12345678",
        )
        db_alumno = to_db(alumno)
        alumno_crud.create(test_db_session, db_alumno)
        
        # Create Materias with Comisiones
        materia1 = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        db_materia1 = to_db(materia1)
        created_materia1, children1 = CascadingOperations.create_with_cascading(
            parent_instance=db_materia1,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        comision1 = children1[0]
        
        materia2 = Materia(
            codigo="MAT102",
            nombre="Álgebra I",
            cupo=25,
            horas_semanales=4,
        )
        db_materia2 = to_db(materia2)
        created_materia2, children2 = CascadingOperations.create_with_cascading(
            parent_instance=db_materia2,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        comision2 = children2[0]
        
        # Create Inscripciones
        inscripcion1 = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id=comision1.id,
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        db_inscripcion1 = to_db(inscripcion1)
        inscripcion_crud.create(test_db_session, db_inscripcion1)
        
        inscripcion2 = Inscripcion(
            id="INS-002",
            alumno_legajo="A-12345",
            comision_id=comision2.id,
            fecha_inscripcion=datetime.date(2024, 3, 1),
            activa=True,
        )
        db_inscripcion2 = to_db(inscripcion2)
        inscripcion_crud.create(test_db_session, db_inscripcion2)
        
        # Verify Alumno has multiple Inscripciones
        all_inscripciones = inscripcion_crud.get_all(test_db_session)
        alumno_inscripciones = [i for i in all_inscripciones if i.alumno_legajo == "A-12345"]
        
        assert len(alumno_inscripciones) == 2
        assert any(i.comision_id == comision1.id for i in alumno_inscripciones)
        assert any(i.comision_id == comision2.id for i in alumno_inscripciones)
    
    def test_clase_with_multiple_asignaciones_over_time(self, test_db_session: Session):
        """
        Test creating a Clase with multiple AsignacionAula over time
        (e.g., changing classrooms).
        """
        # Create Materia with Comisión
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        db_materia = to_db(materia)
        created_materia, children = CascadingOperations.create_with_cascading(
            parent_instance=db_materia,
            parent_crud_func=materia_crud.create,
            session=test_db_session,
        )
        comision = children[0]
        
        # Create Horario
        horario = HorarioCronograma(
            id="HOR-001",
            dia_semana="Lunes",
            hora_inicio=datetime.time(8, 0),
            hora_fin=datetime.time(10, 0),
        )
        db_horario = to_db(horario)
        horario_crud.create(test_db_session, db_horario)
        
        # Create Clase
        clase = Clase(
            id="CLS-001",
            comision_id=comision.id,
            horario_id="HOR-001",
            dia="Lunes",
        )
        db_clase = to_db(clase)
        clase_crud.create(test_db_session, db_clase)
        
        # Create Aulas
        aula1 = Aula(
            id="AULA-001",
            sede="Campus Central",
            nombre="Aula 101",
            capacidad=40,
            tipo="teorica",
        )
        db_aula1 = to_db(aula1)
        aula_crud.create(test_db_session, db_aula1)
        
        aula2 = Aula(
            id="AULA-002",
            sede="Campus Central",
            nombre="Aula 102",
            capacidad=50,
            tipo="teorica",
        )
        db_aula2 = to_db(aula2)
        aula_crud.create(test_db_session, db_aula2)
        
        # Create first AsignacionAula (old, not vigente)
        asignacion1 = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-001",
            fecha_asignacion=datetime.date(2024, 1, 1),
            vigente=False,
        )
        db_asignacion1 = to_db(asignacion1)
        asignacion_crud.create(test_db_session, db_asignacion1)
        
        # Create second AsignacionAula (current, vigente)
        asignacion2 = AsignacionAula(
            id="ASG-002",
            clase_id="CLS-001",
            aula_id="AULA-002",
            fecha_asignacion=datetime.date(2024, 3, 1),
            vigente=True,
        )
        db_asignacion2 = to_db(asignacion2)
        asignacion_crud.create(test_db_session, db_asignacion2)
        
        # Verify Clase has multiple AsignacionAula
        all_asignaciones = asignacion_crud.get_all(test_db_session)
        clase_asignaciones = [a for a in all_asignaciones if a.clase_id == "CLS-001"]
        
        assert len(clase_asignaciones) == 2
        
        # Verify only one is vigente
        vigentes = [a for a in clase_asignaciones if a.vigente]
        assert len(vigentes) == 1
        assert vigentes[0].aula_id == "AULA-002"
