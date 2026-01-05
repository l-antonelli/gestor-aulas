"""Tests for Assignment Validation Logic."""

import pytest
from datetime import date

from src.domain.problem.clase import Clase
from src.domain.problem.aula import Aula
from src.domain.solution.asignacion_aula import AsignacionAula
from src.services.assignment_validation import (
    DuplicateAssignmentError,
    AulaOccupiedError,
    CapacityExceededError,
    ConflictError,
    AssignmentConflict,
    validate_clase_assignment_uniqueness,
    validate_aula_availability,
    validate_capacity_constraint,
    detect_assignment_conflicts,
    validate_assignment,
)


# Test fixtures
@pytest.fixture
def sample_clases():
    """Create sample Clase entities for testing."""
    return [
        Clase(id="CLS-001", comision_id="COM-001", horario_id="HOR-001", dia="Lunes"),
        Clase(id="CLS-002", comision_id="COM-001", horario_id="HOR-002", dia="Martes"),
        Clase(id="CLS-003", comision_id="COM-002", horario_id="HOR-001", dia="Lunes"),
    ]


@pytest.fixture
def sample_aulas():
    """Create sample Aula entities for testing."""
    return [
        Aula(id="AULA-101", sede="Sede Central", nombre="Aula 101", capacidad=50, tipo="teorica"),
        Aula(id="AULA-102", sede="Sede Central", nombre="Aula 102", capacidad=30, tipo="practica"),
        Aula(id="AULA-103", sede="Sede Central", nombre="Aula 103", capacidad=100, tipo="anfiteatro"),
    ]


@pytest.fixture
def sample_assignments(sample_clases):
    """Create sample AsignacionAula entities for testing."""
    return [
        AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-101",
            fecha_asignacion=date(2025, 3, 1),
            vigente=True
        ),
    ]


class TestClaseAssignmentUniqueness:
    """Tests for validate_clase_assignment_uniqueness (Requirement 3.1)."""
    
    def test_no_existing_assignments(self):
        """Test that validation passes when there are no existing assignments."""
        validate_clase_assignment_uniqueness("CLS-001", [])
        # Should not raise
    
    def test_clase_not_assigned(self, sample_assignments):
        """Test that validation passes when the Clase has no assignment."""
        validate_clase_assignment_uniqueness("CLS-002", sample_assignments)
        # Should not raise
    
    def test_clase_already_assigned(self, sample_assignments):
        """Test that validation fails when Clase already has an active assignment."""
        with pytest.raises(DuplicateAssignmentError) as exc_info:
            validate_clase_assignment_uniqueness("CLS-001", sample_assignments)
        
        assert exc_info.value.clase_id == "CLS-001"
        assert exc_info.value.existing_assignment_id == "ASG-001"
    
    def test_inactive_assignment_ignored(self):
        """Test that inactive assignments are ignored."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-101",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        validate_clase_assignment_uniqueness("CLS-001", [inactive_assignment])
        # Should not raise


class TestAulaAvailability:
    """Tests for validate_aula_availability (Requirement 3.2)."""
    
    def test_aula_available_no_assignments(self, sample_clases):
        """Test that validation passes when there are no existing assignments."""
        validate_aula_availability("AULA-101", "HOR-001", [], sample_clases)
        # Should not raise
    
    def test_aula_available_different_horario(self, sample_clases, sample_assignments):
        """Test that validation passes when Aula is used at different horario."""
        validate_aula_availability("AULA-101", "HOR-002", sample_assignments, sample_clases)
        # Should not raise
    
    def test_aula_available_different_aula(self, sample_clases, sample_assignments):
        """Test that validation passes when different Aula is requested."""
        validate_aula_availability("AULA-102", "HOR-001", sample_assignments, sample_clases)
        # Should not raise
    
    def test_aula_occupied(self, sample_clases, sample_assignments):
        """Test that validation fails when Aula is already occupied at the horario."""
        with pytest.raises(AulaOccupiedError) as exc_info:
            validate_aula_availability("AULA-101", "HOR-001", sample_assignments, sample_clases)
        
        assert exc_info.value.aula_codigo == "AULA-101"
        assert exc_info.value.horario_id == "HOR-001"
        assert exc_info.value.existing_clase_id == "CLS-001"
    
    def test_inactive_assignment_ignored(self, sample_clases):
        """Test that inactive assignments are ignored."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-101",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        validate_aula_availability("AULA-101", "HOR-001", [inactive_assignment], sample_clases)
        # Should not raise


class TestCapacityConstraint:
    """Tests for validate_capacity_constraint (Requirement 3.3)."""
    
    def test_capacity_sufficient(self, sample_aulas):
        """Test that validation passes when capacity is sufficient."""
        aula = sample_aulas[0]  # capacidad=50
        validate_capacity_constraint(aula, 40)
        # Should not raise
    
    def test_capacity_exact(self, sample_aulas):
        """Test that validation passes when capacity equals expected attendance."""
        aula = sample_aulas[0]  # capacidad=50
        validate_capacity_constraint(aula, 50)
        # Should not raise
    
    def test_capacity_exceeded(self, sample_aulas):
        """Test that validation fails when capacity is insufficient."""
        aula = sample_aulas[1]  # capacidad=30
        with pytest.raises(CapacityExceededError) as exc_info:
            validate_capacity_constraint(aula, 35)
        
        assert exc_info.value.aula_codigo == "AULA-102"
        assert exc_info.value.aula_capacity == 30
        assert exc_info.value.expected_attendance == 35


class TestConflictDetection:
    """Tests for detect_assignment_conflicts (Requirement 3.4)."""
    
    def test_no_conflicts_empty_assignments(self, sample_clases):
        """Test that no conflicts are detected with empty assignments."""
        new_clase = sample_clases[0]
        conflicts = detect_assignment_conflicts(new_clase, "AULA-101", [], sample_clases)
        assert conflicts == []
    
    def test_no_conflicts_different_aula(self, sample_clases, sample_assignments):
        """Test that no conflicts are detected when using different Aula."""
        new_clase = sample_clases[2]  # CLS-003, HOR-001
        conflicts = detect_assignment_conflicts(
            new_clase, "AULA-102", sample_assignments, sample_clases
        )
        assert conflicts == []
    
    def test_no_conflicts_different_horario(self, sample_clases, sample_assignments):
        """Test that no conflicts are detected when using different horario."""
        new_clase = sample_clases[1]  # CLS-002, HOR-002
        conflicts = detect_assignment_conflicts(
            new_clase, "AULA-101", sample_assignments, sample_clases
        )
        assert conflicts == []
    
    def test_conflict_detected(self, sample_clases, sample_assignments):
        """Test that conflict is detected when Aula is occupied at same horario."""
        new_clase = sample_clases[2]  # CLS-003, HOR-001
        conflicts = detect_assignment_conflicts(
            new_clase, "AULA-101", sample_assignments, sample_clases
        )
        
        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.aula_codigo == "AULA-101"
        assert conflict.horario_id == "HOR-001"
        assert conflict.existing_clase_id == "CLS-001"
        assert conflict.new_clase_id == "CLS-003"
    
    def test_inactive_assignment_ignored(self, sample_clases):
        """Test that inactive assignments don't cause conflicts."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-101",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        new_clase = sample_clases[2]  # CLS-003, HOR-001
        conflicts = detect_assignment_conflicts(
            new_clase, "AULA-101", [inactive_assignment], sample_clases
        )
        assert conflicts == []


class TestValidateAssignment:
    """Tests for the combined validate_assignment function."""
    
    def test_valid_assignment(self, sample_clases, sample_aulas):
        """Test that a valid assignment passes all validations."""
        new_clase = sample_clases[1]  # CLS-002, HOR-002
        new_aula = sample_aulas[0]  # AULA-101, capacidad=50
        
        validate_assignment(
            new_clase=new_clase,
            new_aula=new_aula,
            expected_attendance=40,
            existing_assignments=[],
            clases=sample_clases
        )
        # Should not raise
    
    def test_fails_on_duplicate_assignment(self, sample_clases, sample_aulas, sample_assignments):
        """Test that validation fails when Clase already has an assignment."""
        new_clase = sample_clases[0]  # CLS-001 - already assigned
        new_aula = sample_aulas[1]  # AULA-102
        
        with pytest.raises(DuplicateAssignmentError):
            validate_assignment(
                new_clase=new_clase,
                new_aula=new_aula,
                expected_attendance=20,
                existing_assignments=sample_assignments,
                clases=sample_clases
            )
    
    def test_fails_on_aula_occupied(self, sample_clases, sample_aulas, sample_assignments):
        """Test that validation fails when Aula is occupied."""
        new_clase = sample_clases[2]  # CLS-003, HOR-001
        new_aula = sample_aulas[0]  # AULA-101 - occupied at HOR-001
        
        with pytest.raises(AulaOccupiedError):
            validate_assignment(
                new_clase=new_clase,
                new_aula=new_aula,
                expected_attendance=20,
                existing_assignments=sample_assignments,
                clases=sample_clases
            )
    
    def test_fails_on_capacity_exceeded(self, sample_clases, sample_aulas):
        """Test that validation fails when capacity is exceeded."""
        new_clase = sample_clases[1]  # CLS-002
        new_aula = sample_aulas[1]  # AULA-102, capacidad=30
        
        with pytest.raises(CapacityExceededError):
            validate_assignment(
                new_clase=new_clase,
                new_aula=new_aula,
                expected_attendance=50,
                existing_assignments=[],
                clases=sample_clases
            )
