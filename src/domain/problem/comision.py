"""Comision entity - Division of a subject for student distribution."""

from typing import Optional
from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import ComisionId, CodigoMateria


class Comision(Entity):
    """
    Represents a division/section of a subject.

    A Materia can have multiple Comisiones to distribute students
    and facilitate teaching.

    Attributes:
        id: Unique commission identifier
        materia_codigo: Reference to parent Materia
        plan_cursada_id: Reference to the PlanificacionCursada this comision belongs to
        comision_key: Plan-agnostic key for comparison across plans
        nombre: Commission name/description
        numero: Commission number within the subject
        cupo: Maximum capacity for this commission
    """

    id: ComisionId = Field(..., description="Unique commission identifier")
    materia_codigo: CodigoMateria = Field(..., description="Reference to parent Materia")
    plan_cursada_id: Optional[str] = Field(default=None, description="Reference to PlanificacionCursada")
    comision_key: str = Field(default="", description="Plan-agnostic key for comparison")
    nombre: str = Field(..., min_length=1, description="Commission name")
    numero: int = Field(..., ge=1, description="Commission number")
    cupo: int = Field(..., gt=0, description="Maximum capacity")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v
    
    @field_validator("materia_codigo")
    @classmethod
    def validate_materia_codigo(cls, v: str) -> str:
        """Validate that materia_codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("materia_codigo cannot be empty")
        return v
