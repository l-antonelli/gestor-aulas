"""AsignacionAula entity - Classroom assignment for a class."""

from datetime import date

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import AsignacionId, ClaseId, CodigoAula


class AsignacionAula(Entity):
    """
    Represents the assignment of a classroom to a class.
    
    This entity resolves the M:M relationship between Clase and Aula,
    allowing management of assignments and conflict detection.
    
    Attributes:
        id: Unique assignment identifier
        clase_id: Reference to the Clase being assigned
        aula_codigo: Reference to the assigned Aula
        fecha_asignacion: Date when the assignment was made
        vigente: Whether the assignment is currently active
    """
    
    id: AsignacionId = Field(..., description="Unique assignment identifier")
    clase_id: ClaseId = Field(..., description="Reference to Clase")
    aula_codigo: CodigoAula = Field(..., description="Reference to assigned Aula")
    fecha_asignacion: date = Field(..., description="Date of assignment")
    vigente: bool = Field(default=True, description="Whether assignment is active")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v
    
    @field_validator("clase_id")
    @classmethod
    def validate_clase_id(cls, v: str) -> str:
        """Validate that clase_id is not empty."""
        if not v or not v.strip():
            raise ValueError("clase_id cannot be empty")
        return v
    
    @field_validator("aula_codigo")
    @classmethod
    def validate_aula_codigo(cls, v: str) -> str:
        """Validate that aula_codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("aula_codigo cannot be empty")
        return v
