"""Aula entity - Physical classroom space."""

from typing import Literal

from pydantic import Field, field_validator

from src.domain.base import Entity


# Valid classroom types
TipoAula = Literal["teorica", "practica", "laboratorio", "anfiteatro"]


class Aula(Entity):
    """
    Represents a physical classroom space.
    
    Attributes:
        id: Unique classroom identifier
        sede: Building/location where the classroom is located
        nombre: Classroom name (e.g., "AULA 01", "LABORATORIO 1")
        capacidad: Maximum seating capacity (must be positive)
        tipo: Type of classroom (teorica, practica, laboratorio, anfiteatro)
        descripcion: Optional description or notes
    """
    
    id: str = Field(..., description="Unique classroom identifier")
    sede: str = Field(..., description="Building/location")
    nombre: str = Field(..., min_length=1, description="Classroom name")
    capacidad: int = Field(..., gt=0, description="Maximum seating capacity")
    tipo: TipoAula = Field(default="teorica", description="Type of classroom")
    descripcion: str = Field(default="", description="Optional description")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v
    
    @field_validator("sede")
    @classmethod
    def validate_sede(cls, v: str) -> str:
        """Validate that sede is not empty."""
        if not v or not v.strip():
            raise ValueError("sede cannot be empty")
        return v
