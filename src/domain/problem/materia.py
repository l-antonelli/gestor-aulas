"""Materia entity - Academic subject/course."""

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import CodigoMateria


class Materia(Entity):
    """
    Represents an academic subject/course.
    
    Attributes:
        codigo: Unique subject code (e.g., "MAT101")
        nombre: Subject name
        cupo: Maximum capacity (must be positive)
        horas_semanales: Weekly hours (must be positive)
    """
    
    codigo: CodigoMateria = Field(..., description="Unique subject code")
    nombre: str = Field(..., min_length=1, description="Subject name")
    cupo: int = Field(..., gt=0, description="Maximum capacity")
    horas_semanales: int = Field(..., gt=0, description="Weekly hours")
    
    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
