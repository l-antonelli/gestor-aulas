"""Assignment validation logic for the classroom assignment system.

This module implements the validation constraints for classroom assignments:
- Clase assignment uniqueness (Requirement 3.1)
- Aula scheduling uniqueness (Requirement 3.2)
- Capacity constraint validation (Requirement 3.3)
- Conflict detection (Requirement 3.4)
"""

from dataclasses import dataclass
from typing import List, Optional, Sequence

from src.domain.solution.asignacion_aula import AsignacionAula
from src.domain.problem.clase import Clase
from src.domain.problem.aula import Aula
from src.domain.types import ClaseId, CodigoAula, HorarioId


class DuplicateAssignmentError(Exception):
    """Raised when attempting to assign a Clase that already has an assignment."""
    
    def __init__(self, clase_id: ClaseId, existing_assignment_id: str):
        self.clase_id = clase_id
        self.existing_assignment_id = existing_assignment_id
        super().__init__(
            f"Clase '{clase_id}' already has an active assignment: '{existing_assignment_id}'"
        )


class AulaOccupiedError(Exception):
    """Raised when attempting to assign an Aula that is already occupied at the given time."""
    
    def __init__(self, aula_codigo: CodigoAula, horario_id: HorarioId, existing_clase_id: ClaseId):
        self.aula_codigo = aula_codigo
        self.horario_id = horario_id
        self.existing_clase_id = existing_clase_id
        super().__init__(
            f"Aula '{aula_codigo}' is already occupied at horario '{horario_id}' "
            f"by clase '{existing_clase_id}'"
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
    horario_id: HorarioId
    existing_clase_id: ClaseId
    new_clase_id: ClaseId
    
    def __str__(self) -> str:
        return (
            f"Conflict at Aula '{self.aula_codigo}', Horario '{self.horario_id}': "
            f"Clase '{self.existing_clase_id}' vs '{self.new_clase_id}'"
        )



def validate_clase_assignment_uniqueness(
    clase_id: ClaseId,
    existing_assignments: Sequence[AsignacionAula],
) -> None:
    """
    Validate that a Clase does not already have an active assignment.
    
    Requirement 3.1: Each Clase is assigned to exactly one Aula at any given HorarioCronograma.
    
    Args:
        clase_id: The ID of the Clase to check
        existing_assignments: Collection of existing AsignacionAula records
        
    Raises:
        DuplicateAssignmentError: If the Clase already has an active assignment
    """
    for assignment in existing_assignments:
        if assignment.clase_id == clase_id and assignment.vigente:
            raise DuplicateAssignmentError(clase_id, assignment.id)


def validate_aula_availability(
    aula_codigo: CodigoAula,
    horario_id: HorarioId,
    existing_assignments: Sequence[AsignacionAula],
    clases: Sequence[Clase],
) -> None:
    """
    Validate that an Aula is available at a given HorarioCronograma.
    
    Requirement 3.2: Each Aula hosts at most one Clase at any given HorarioCronograma.
    
    Args:
        aula_codigo: The code of the Aula to check
        horario_id: The ID of the HorarioCronograma to check
        existing_assignments: Collection of existing AsignacionAula records
        clases: Collection of Clase entities to look up horario information
        
    Raises:
        AulaOccupiedError: If the Aula is already occupied at the given time
    """
    # Build a lookup for clase_id -> horario_id
    clase_horario_map = {clase.id: clase.horario_id for clase in clases}
    
    for assignment in existing_assignments:
        if not assignment.vigente:
            continue
            
        if assignment.aula_codigo != aula_codigo:
            continue
            
        # Get the horario_id for the assigned clase
        assigned_clase_horario = clase_horario_map.get(assignment.clase_id)
        
        if assigned_clase_horario == horario_id:
            raise AulaOccupiedError(aula_codigo, horario_id, assignment.clase_id)


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
        raise CapacityExceededError(aula.codigo, aula.capacidad, expected_attendance)


def detect_assignment_conflicts(
    new_clase: Clase,
    new_aula_codigo: CodigoAula,
    existing_assignments: Sequence[AsignacionAula],
    clases: Sequence[Clase],
) -> List[AssignmentConflict]:
    """
    Detect any scheduling conflicts for a proposed assignment.
    
    Requirement 3.4: Reject conflicting assignment requests.
    
    This function checks for:
    1. Duplicate assignment of the same Clase
    2. Aula already occupied at the same HorarioCronograma
    
    Args:
        new_clase: The Clase to be assigned
        new_aula_codigo: The code of the Aula for the new assignment
        existing_assignments: Collection of existing AsignacionAula records
        clases: Collection of Clase entities to look up horario information
        
    Returns:
        List of AssignmentConflict objects describing any conflicts found
    """
    conflicts: List[AssignmentConflict] = []
    
    # Build a lookup for clase_id -> Clase
    clase_map = {clase.id: clase for clase in clases}
    
    for assignment in existing_assignments:
        if not assignment.vigente:
            continue
        
        # Check for same Aula at same HorarioCronograma
        if assignment.aula_codigo == new_aula_codigo:
            existing_clase = clase_map.get(assignment.clase_id)
            
            if existing_clase and existing_clase.horario_id == new_clase.horario_id:
                conflicts.append(AssignmentConflict(
                    aula_codigo=new_aula_codigo,
                    horario_id=new_clase.horario_id,
                    existing_clase_id=assignment.clase_id,
                    new_clase_id=new_clase.id,
                ))
    
    return conflicts


def validate_assignment(
    new_clase: Clase,
    new_aula: Aula,
    expected_attendance: int,
    existing_assignments: Sequence[AsignacionAula],
    clases: Sequence[Clase],
) -> None:
    """
    Perform all assignment validations.
    
    This is a convenience function that runs all validation checks:
    - Clase assignment uniqueness (3.1)
    - Aula scheduling uniqueness (3.2)
    - Capacity constraint (3.3)
    - Conflict detection (3.4)
    
    Args:
        new_clase: The Clase to be assigned
        new_aula: The Aula for the assignment
        expected_attendance: Expected number of attendees
        existing_assignments: Collection of existing AsignacionAula records
        clases: Collection of Clase entities
        
    Raises:
        DuplicateAssignmentError: If Clase already has an assignment
        AulaOccupiedError: If Aula is already occupied
        CapacityExceededError: If Aula capacity is insufficient
        ConflictError: If any scheduling conflicts are detected
    """
    # Check Clase assignment uniqueness (3.1)
    validate_clase_assignment_uniqueness(new_clase.id, existing_assignments)
    
    # Check Aula availability (3.2)
    validate_aula_availability(
        new_aula.codigo, 
        new_clase.horario_id, 
        existing_assignments, 
        clases
    )
    
    # Check capacity constraint (3.3)
    validate_capacity_constraint(new_aula, expected_attendance)
    
    # Detect conflicts (3.4)
    conflicts = detect_assignment_conflicts(
        new_clase, 
        new_aula.codigo, 
        existing_assignments, 
        clases
    )
    if conflicts:
        raise ConflictError(conflicts)
