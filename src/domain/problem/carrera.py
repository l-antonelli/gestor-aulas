"""Carrera entity - University degree program."""

from pydantic import Field, field_validator

from src.domain.base import Entity


class Carrera(Entity):
    """
    Represents a university degree program.
    
    Attributes:
        codigo: Unique program code (e.g., "ING-ELECT")
        nombre: Program name
        titulo_otorgado: Degree title awarded upon completion
        duracion_anios: Duration in years
    """
    
    codigo: str = Field(..., min_length=1, description="Unique program code")
    nombre: str = Field(..., min_length=1, description="Program name")
    titulo_otorgado: str = Field(default="", description="Degree title awarded")
    duracion_anios: int = Field(default=5, ge=1, description="Duration in years")
    
    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
