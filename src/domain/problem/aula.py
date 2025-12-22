"""Aula entity - Physical classroom space."""

from typing import Literal

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import CodigoAula


# Valid classroom types
TipoAula = Literal["teorica", "practica", "laboratorio", "anfiteatro"]


class Aula(Entity):
    """
    Represents a physical classroom space.
    
    Attributes:
        codigo: Unique classroom code (e.g., "AULA-101")
        capacidad: Maximum seating capacity (must be positive)
        tipo: Type of classroom (teorica, practica, laboratorio, anfiteatro)
    """
    
    codigo: CodigoAula = Field(..., description="Unique classroom code")
    capacidad: int = Field(..., gt=0, description="Maximum seating capacity")
    tipo: TipoAula = Field(..., description="Type of classroom")
    
    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
