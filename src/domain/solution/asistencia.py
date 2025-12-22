"""Asistencia entity - Student attendance record for a class."""

from datetime import date

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import AsistenciaId, Legajo, ClaseId


class Asistencia(Entity):
    """
    Represents a student's attendance record for a specific class.
    
    This entity resolves the M:M relationship between Alumno and Clase,
    allowing tracking of actual presence and feeding prediction models.
    
    Attributes:
        id: Unique attendance record identifier
        alumno_legajo: Reference to the Alumno
        clase_id: Reference to the Clase
        fecha: Date of the class session
        presente: Whether the student was present
    """
    
    id: AsistenciaId = Field(..., description="Unique attendance record identifier")
    alumno_legajo: Legajo = Field(..., description="Reference to Alumno")
    clase_id: ClaseId = Field(..., description="Reference to Clase")
    fecha: date = Field(..., description="Date of the class session")
    presente: bool = Field(..., description="Whether student was present")
    
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
    
    @field_validator("clase_id")
    @classmethod
    def validate_clase_id(cls, v: str) -> str:
        """Validate that clase_id is not empty."""
        if not v or not v.strip():
            raise ValueError("clase_id cannot be empty")
        return v
