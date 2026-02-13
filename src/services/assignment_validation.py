"""Assignment validation logic for the classroom assignment system.

This module implements the validation constraints for classroom assignments:
- Horario assignment uniqueness (Requirement 3.1)
- Aula scheduling uniqueness (Requirement 3.2)
- Capacity constraint validation (Requirement 3.3)
- Conflict detection (Requirement 3.4)
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.domain.solution.asignacion_aula import AsignacionAula
from src.domain.problem.horario import Horario
from src.domain.problem.aula import Aula
from src.domain.types import CodigoAula, HorarioId


class DuplicateAssignmentError(Exception):
    """Raised when attempting to assign a Horario that already has an assignment."""

    def __init__(self, horario_id: HorarioId, existing_assignment_id: str):
        self.horario_id = horario_id
        self.existing_assignment_id = existing_assignment_id
        super().__init__(
            f"Horario '{horario_id}' already has an active assignment: '{existing_assignment_id}'"
        )


class AulaOccupiedError(Exception):
    """Raised when attempting to assign an Aula that is already occupied at the given time."""

    def __init__(self, aula_codigo: CodigoAula, dia: str, hora_inicio: str, existing_horario_id: HorarioId):
        self.aula_codigo = aula_codigo
        self.dia = dia
        self.hora_inicio = hora_inicio
        self.existing_horario_id = existing_horario_id
        super().__init__(
            f"Aula '{aula_codigo}' is already occupied on '{dia}' at '{hora_inicio}' "
            f"by horario '{existing_horario_id}'"
        )


class CapacityExceededError(Exception):
    """Raised when Aula capacity is insufficient for expected attendance."""

    def __init__(self, aula_codigo: CodigoAula, aula_capacity: int, expected_attendance: int):
        self.aula_codigo = aula_codigo
        self.aula_capacity = aula_capacity
        self.expected_attendance = expected_attendance
        super().__init__(
            f"Aula '{aula_codigo}' capacity ({aula_capacity}) is insufficient "
            f"for expected attendance ({expected_attendance})"
        )


class ConflictError(Exception):
    """Raised when a scheduling conflict is detected."""

    def __init__(self, conflicts: List["AssignmentConflict"]):
        self.conflicts = conflicts
        conflict_details = "; ".join(str(c) for c in conflicts)
        super().__init__(f"Assignment conflicts detected: {conflict_details}")


@dataclass(frozen=True)
class AssignmentConflict:
    """Details of a scheduling conflict between two assignments."""

    aula_codigo: CodigoAula
    dia: str
    hora_inicio: str
    existing_horario_id: HorarioId
    new_horario_id: HorarioId

    def __str__(self) -> str:
        return (
            f"Conflict at Aula '{self.aula_codigo}', dia '{self.dia}' hora '{self.hora_inicio}': "
            f"Horario '{self.existing_horario_id}' vs '{self.new_horario_id}'"
        )


def _times_overlap(h1: Horario, h2: Horario) -> bool:
    """Check whether two Horario entries overlap (same day and overlapping time ranges)."""
    if h1.dia != h2.dia:
        return False
    return not (h1.hora_fin <= h2.hora_inicio or h2.hora_fin <= h1.hora_inicio)


def validate_horario_assignment_uniqueness(
    horario_id: HorarioId,
    existing_assignments: Sequence[AsignacionAula],
) -> None:
    """
    Validate that a Horario does not already have an active assignment.

    Requirement 3.1: Each Horario is assigned to exactly one Aula.

    Args:
        horario_id: The ID of the Horario to check
        existing_assignments: Collection of existing AsignacionAula records

    Raises:
        DuplicateAssignmentError: If the Horario already has an active assignment
    """
    for assignment in existing_assignments:
        if assignment.horario_id == horario_id and assignment.vigente:
            raise DuplicateAssignmentError(horario_id, assignment.id)


def validate_aula_availability(
    aula_codigo: CodigoAula,
    new_horario: Horario,
    existing_assignments: Sequence[AsignacionAula],
    horarios: Sequence[Horario],
) -> None:
    """
    Validate that an Aula is available at a given Horario's time slot.

    Requirement 3.2: Each Aula hosts at most one Horario at any given time slot.

    Args:
        aula_codigo: The code of the Aula to check
        new_horario: The Horario to be assigned
        existing_assignments: Collection of existing AsignacionAula records
        horarios: Collection of Horario entities to look up schedule information

    Raises:
        AulaOccupiedError: If the Aula is already occupied at the given time
    """
    # Build a lookup for horario_id -> Horario
    horario_map = {h.id: h for h in horarios}

    for assignment in existing_assignments:
        if not assignment.vigente:
            continue

        if assignment.aula_id != aula_codigo:
            continue

        existing_horario = horario_map.get(assignment.horario_id)
        if existing_horario and _times_overlap(existing_horario, new_horario):
            raise AulaOccupiedError(
                aula_codigo,
                new_horario.dia,
                str(new_horario.hora_inicio),
                assignment.horario_id,
            )


def validate_capacity_constraint(
    aula: Aula,
    expected_attendance: int,
) -> None:
    """
    Validate that an Aula has sufficient capacity for expected attendance.

    Requirement 3.3: The assigned Aula capacity must be >= expected attendance.

    Args:
        aula: The Aula entity to check
        expected_attendance: The expected number of attendees

    Raises:
        CapacityExceededError: If the Aula capacity is insufficient
    """
    if aula.capacidad < expected_attendance:
        raise CapacityExceededError(aula.id, aula.capacidad, expected_attendance)


def detect_assignment_conflicts(
    new_horario: Horario,
    new_aula_codigo: CodigoAula,
    existing_assignments: Sequence[AsignacionAula],
    horarios: Sequence[Horario],
) -> List[AssignmentConflict]:
    """
    Detect any scheduling conflicts for a proposed assignment.

    Requirement 3.4: Reject conflicting assignment requests.

    This function checks for:
    1. Duplicate assignment of the same Horario
    2. Aula already occupied at an overlapping time slot

    Args:
        new_horario: The Horario to be assigned
        new_aula_codigo: The code of the Aula for the new assignment
        existing_assignments: Collection of existing AsignacionAula records
        horarios: Collection of Horario entities to look up schedule information

    Returns:
        List of AssignmentConflict objects describing any conflicts found
    """
    conflicts: List[AssignmentConflict] = []

    # Build a lookup for horario_id -> Horario
    horario_map = {h.id: h for h in horarios}

    for assignment in existing_assignments:
        if not assignment.vigente:
            continue

        # Check for same Aula at overlapping time
        if assignment.aula_id == new_aula_codigo:
            existing_horario = horario_map.get(assignment.horario_id)

            if existing_horario and _times_overlap(existing_horario, new_horario):
                conflicts.append(AssignmentConflict(
                    aula_codigo=new_aula_codigo,
                    dia=new_horario.dia,
                    hora_inicio=str(new_horario.hora_inicio),
                    existing_horario_id=assignment.horario_id,
                    new_horario_id=new_horario.id,
                ))

    return conflicts


def validate_assignment(
    new_horario: Horario,
    new_aula: Aula,
    expected_attendance: int,
    existing_assignments: Sequence[AsignacionAula],
    horarios: Sequence[Horario],
) -> None:
    """
    Perform all assignment validations.

    This is a convenience function that runs all validation checks:
    - Horario assignment uniqueness (3.1)
    - Aula scheduling uniqueness (3.2)
    - Capacity constraint (3.3)
    - Conflict detection (3.4)

    Args:
        new_horario: The Horario to be assigned
        new_aula: The Aula for the assignment
        expected_attendance: Expected number of attendees
        existing_assignments: Collection of existing AsignacionAula records
        horarios: Collection of Horario entities

    Raises:
        DuplicateAssignmentError: If Horario already has an assignment
        AulaOccupiedError: If Aula is already occupied
        CapacityExceededError: If Aula capacity is insufficient
        ConflictError: If any scheduling conflicts are detected
    """
    # Check Horario assignment uniqueness (3.1)
    validate_horario_assignment_uniqueness(new_horario.id, existing_assignments)

    # Check Aula availability (3.2)
    validate_aula_availability(
        new_aula.id,
        new_horario,
        existing_assignments,
        horarios,
    )

    # Check capacity constraint (3.3)
    validate_capacity_constraint(new_aula, expected_attendance)

    # Detect conflicts (3.4)
    conflicts = detect_assignment_conflicts(
        new_horario,
        new_aula.id,
        existing_assignments,
        horarios,
    )
    if conflicts:
        raise ConflictError(conflicts)
