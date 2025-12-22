"""Inscripcion entity - Student enrollment in a commission."""

from datetime import date

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import InscripcionId, Legajo, ComisionId


class Inscripcion(Entity):
    """
    Represents a student's enrollment in a commission.
    
    This entity resolves the M:M relationship between Alumno and Materia/Comision,
    allowing management of enrollments and calculation of expected demand.
    
    Attributes:
        id: Unique inscription identifier
        alumno_legajo: Reference to the enrolled Alumno
        comision_id: Reference to the Comision
        fecha_inscripcion: Date when the enrollment was registered
        activa: Whether the enrollment is currently active
    """
    
    id: InscripcionId = Field(..., description="Unique inscription identifier")
    alumno_legajo: Legajo = Field(..., description="Reference to enrolled Alumno")
    comision_id: ComisionId = Field(..., description="Reference to Comision")
    fecha_inscripcion: date = Field(..., description="Enrollment registration date")
    activa: bool = Field(default=True, description="Whether enrollment is active")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v
    
    @field_validator("alumno_legajo")
    @classmethod
    def validate_alumno_legajo(cls, v: str) -> str:
        """Validate that alumno_legajo is not empty."""
        if not v or not v.strip():
            raise ValueError("alumno_legajo cannot be empty")
        return v
    
    @field_validator("comision_id")
    @classmethod
    def validate_comision_id(cls, v: str) -> str:
        """Validate that comision_id is not empty."""
        if not v or not v.strip():
            raise ValueError("comision_id cannot be empty")
        return v
