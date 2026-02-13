"""Tests for Assignment Validation Logic."""

import pytest
from datetime import date, time

from src.domain.problem.horario import Horario
from src.domain.problem.aula import Aula
from src.domain.solution.asignacion_aula import AsignacionAula
from src.services.assignment_validation import (
    DuplicateAssignmentError,
    AulaOccupiedError,
    CapacityExceededError,
    ConflictError,
    AssignmentConflict,
    validate_horario_assignment_uniqueness,
    validate_aula_availability,
    validate_capacity_constraint,
    detect_assignment_conflicts,
    validate_assignment,
)


# Test fixtures
@pytest.fixture
def sample_horarios():
    """Create sample Horario entities for testing."""
    return [
        Horario(
            id="HOR-001",
            comision_id="COM-001",
            codigo_materia="MAT101",
            dia="Lunes",
            hora_inicio=time(8, 0),
            hora_fin=time(10, 0),
        ),
        Horario(
            id="HOR-002",
            comision_id="COM-001",
            codigo_materia="MAT101",
            dia="Martes",
            hora_inicio=time(8, 0),
            hora_fin=time(10, 0),
        ),
        Horario(
            id="HOR-003",
            comision_id="COM-002",
            codigo_materia="MAT102",
            dia="Lunes",
            hora_inicio=time(8, 0),
            hora_fin=time(10, 0),
        ),
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
def sample_assignments(sample_horarios):
    """Create sample AsignacionAula entities for testing."""
    return [
        AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 3, 1),
            vigente=True
        ),
    ]


class TestHorarioAssignmentUniqueness:
    """Tests for validate_horario_assignment_uniqueness (Requirement 3.1)."""

    def test_no_existing_assignments(self):
        """Test that validation passes when there are no existing assignments."""
        validate_horario_assignment_uniqueness("HOR-001", [])
        # Should not raise

    def test_horario_not_assigned(self, sample_assignments):
        """Test that validation passes when the Horario has no assignment."""
        validate_horario_assignment_uniqueness("HOR-002", sample_assignments)
        # Should not raise

    def test_horario_already_assigned(self, sample_assignments):
        """Test that validation fails when Horario already has an active assignment."""
        with pytest.raises(DuplicateAssignmentError) as exc_info:
            validate_horario_assignment_uniqueness("HOR-001", sample_assignments)

        assert exc_info.value.horario_id == "HOR-001"
        assert exc_info.value.existing_assignment_id == "ASG-001"

    def test_inactive_assignment_ignored(self):
        """Test that inactive assignments are ignored."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        validate_horario_assignment_uniqueness("HOR-001", [inactive_assignment])
        # Should not raise


class TestAulaAvailability:
    """Tests for validate_aula_availability (Requirement 3.2)."""

    def test_aula_available_no_assignments(self, sample_horarios):
        """Test that validation passes when there are no existing assignments."""
        validate_aula_availability("AULA-101", sample_horarios[0], [], sample_horarios)
        # Should not raise

    def test_aula_available_different_horario(self, sample_horarios, sample_assignments):
        """Test that validation passes when Aula is used at different horario time."""
        # HOR-002 is on Martes, existing assignment is HOR-001 on Lunes
        validate_aula_availability("AULA-101", sample_horarios[1], sample_assignments, sample_horarios)
        # Should not raise

    def test_aula_available_different_aula(self, sample_horarios, sample_assignments):
        """Test that validation passes when different Aula is requested."""
        validate_aula_availability("AULA-102", sample_horarios[2], sample_assignments, sample_horarios)
        # Should not raise

    def test_aula_occupied(self, sample_horarios, sample_assignments):
        """Test that validation fails when Aula is already occupied at the same time."""
        # HOR-003 overlaps with HOR-001 (same day, same time)
        with pytest.raises(AulaOccupiedError) as exc_info:
            validate_aula_availability("AULA-101", sample_horarios[2], sample_assignments, sample_horarios)

        assert exc_info.value.aula_codigo == "AULA-101"
        assert exc_info.value.existing_horario_id == "HOR-001"

    def test_inactive_assignment_ignored(self, sample_horarios):
        """Test that inactive assignments are ignored."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        validate_aula_availability("AULA-101", sample_horarios[2], [inactive_assignment], sample_horarios)
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

    def test_no_conflicts_empty_assignments(self, sample_horarios):
        """Test that no conflicts are detected with empty assignments."""
        new_horario = sample_horarios[0]
        conflicts = detect_assignment_conflicts(new_horario, "AULA-101", [], sample_horarios)
        assert conflicts == []

    def test_no_conflicts_different_aula(self, sample_horarios, sample_assignments):
        """Test that no conflicts are detected when using different Aula."""
        new_horario = sample_horarios[2]  # HOR-003, Lunes 8-10
        conflicts = detect_assignment_conflicts(
            new_horario, "AULA-102", sample_assignments, sample_horarios
        )
        assert conflicts == []

    def test_no_conflicts_different_time(self, sample_horarios, sample_assignments):
        """Test that no conflicts are detected when using different time."""
        new_horario = sample_horarios[1]  # HOR-002, Martes 8-10
        conflicts = detect_assignment_conflicts(
            new_horario, "AULA-101", sample_assignments, sample_horarios
        )
        assert conflicts == []

    def test_conflict_detected(self, sample_horarios, sample_assignments):
        """Test that conflict is detected when Aula is occupied at overlapping time."""
        new_horario = sample_horarios[2]  # HOR-003, Lunes 8-10 (overlaps HOR-001)
        conflicts = detect_assignment_conflicts(
            new_horario, "AULA-101", sample_assignments, sample_horarios
        )

        assert len(conflicts) == 1
        conflict = conflicts[0]
        assert conflict.aula_codigo == "AULA-101"
        assert conflict.existing_horario_id == "HOR-001"
        assert conflict.new_horario_id == "HOR-003"

    def test_inactive_assignment_ignored(self, sample_horarios):
        """Test that inactive assignments don't cause conflicts."""
        inactive_assignment = AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 3, 1),
            vigente=False
        )
        new_horario = sample_horarios[2]  # HOR-003, Lunes 8-10
        conflicts = detect_assignment_conflicts(
            new_horario, "AULA-101", [inactive_assignment], sample_horarios
        )
        assert conflicts == []


class TestValidateAssignment:
    """Tests for the combined validate_assignment function."""

    def test_valid_assignment(self, sample_horarios, sample_aulas):
        """Test that a valid assignment passes all validations."""
        new_horario = sample_horarios[1]  # HOR-002, Martes 8-10
        new_aula = sample_aulas[0]  # AULA-101, capacidad=50

        validate_assignment(
            new_horario=new_horario,
            new_aula=new_aula,
            expected_attendance=40,
            existing_assignments=[],
            horarios=sample_horarios
        )
        # Should not raise

    def test_fails_on_duplicate_assignment(self, sample_horarios, sample_aulas, sample_assignments):
        """Test that validation fails when Horario already has an assignment."""
        new_horario = sample_horarios[0]  # HOR-001 - already assigned
        new_aula = sample_aulas[1]  # AULA-102

        with pytest.raises(DuplicateAssignmentError):
            validate_assignment(
                new_horario=new_horario,
                new_aula=new_aula,
                expected_attendance=20,
                existing_assignments=sample_assignments,
                horarios=sample_horarios
            )

    def test_fails_on_aula_occupied(self, sample_horarios, sample_aulas, sample_assignments):
        """Test that validation fails when Aula is occupied."""
        new_horario = sample_horarios[2]  # HOR-003, Lunes 8-10 (overlaps HOR-001)
        new_aula = sample_aulas[0]  # AULA-101 - occupied at overlapping time

        with pytest.raises(AulaOccupiedError):
            validate_assignment(
                new_horario=new_horario,
                new_aula=new_aula,
                expected_attendance=20,
                existing_assignments=sample_assignments,
                horarios=sample_horarios
            )

    def test_fails_on_capacity_exceeded(self, sample_horarios, sample_aulas):
        """Test that validation fails when capacity is exceeded."""
        new_horario = sample_horarios[1]  # HOR-002
        new_aula = sample_aulas[1]  # AULA-102, capacidad=30

        with pytest.raises(CapacityExceededError):
            validate_assignment(
                new_horario=new_horario,
                new_aula=new_aula,
                expected_attendance=50,
                existing_assignments=[],
                horarios=sample_horarios
            )
