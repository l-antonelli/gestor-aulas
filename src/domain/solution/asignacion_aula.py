"""AsignacionAula entity - Classroom assignment for a horario."""

from datetime import date

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import AsignacionId, HorarioId


class AsignacionAula(Entity):
    """
    Represents the assignment of a classroom to a horario.

    This entity resolves the M:M relationship between Horario and Aula,
    allowing management of assignments and conflict detection.

    Attributes:
        id: Unique assignment identifier
        horario_id: Reference to the Horario being assigned
        aula_id: Reference to the assigned Aula
        ciclo_id: Reference to the Ciclo (academic period)
        fecha_asignacion: Date when the assignment was made
        vigente: Whether the assignment is currently active
    """

    id: AsignacionId = Field(..., description="Unique assignment identifier")
    horario_id: HorarioId = Field(..., description="Reference to Horario")
    aula_id: str = Field(..., description="Reference to assigned Aula")
    ciclo_id: str = Field(..., description="Reference to Ciclo (academic period)")
    fecha_asignacion: date = Field(..., description="Date of assignment")
    vigente: bool = Field(default=True, description="Whether assignment is active")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v

    @field_validator("horario_id")
    @classmethod
    def validate_horario_id(cls, v: str) -> str:
        """Validate that horario_id is not empty."""
        if not v or not v.strip():
            raise ValueError("horario_id cannot be empty")
        return v

    @field_validator("aula_id")
    @classmethod
    def validate_aula_id(cls, v: str) -> str:
        """Validate that aula_id is not empty."""
        if not v or not v.strip():
            raise ValueError("aula_id cannot be empty")
        return v

    @field_validator("ciclo_id")
    @classmethod
    def validate_ciclo_id(cls, v: str) -> str:
        """Validate that ciclo_id is not empty."""
        if not v or not v.strip():
            raise ValueError("ciclo_id cannot be empty")
        return v
