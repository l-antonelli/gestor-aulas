# Services module
# Contains: Assignment validation logic

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

__all__ = [
    "DuplicateAssignmentError",
    "AulaOccupiedError",
    "CapacityExceededError",
    "ConflictError",
    "AssignmentConflict",
    "validate_horario_assignment_uniqueness",
    "validate_aula_availability",
    "validate_capacity_constraint",
    "detect_assignment_conflicts",
    "validate_assignment",
]
