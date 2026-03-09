"""Materia entity - Academic subject/course."""

from typing import Literal, Optional
from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import CodigoMateria


class Materia(Entity):
    """
    Represents an academic subject/course.

    Attributes:
        codigo: Unique subject code from the study plan (codigo_plan in source data)
        nombre: Subject name
        codigo_guarani: Optional code in the SIU Guarani system (may differ from codigo)
        cupo: Maximum capacity (optional, set later from enrollment data)
        horas_semanales: Weekly hours (optional, some special courses have no fixed hours)
        periodo: Course period type ("anual" or "cuatrimestral")
    """

    codigo: CodigoMateria = Field(..., description="Unique subject code (codigo_plan)")
    nombre: str = Field(..., min_length=1, description="Subject name")
    codigo_guarani: Optional[str] = Field(default=None, description="SIU Guarani system code")
    cupo: Optional[int] = Field(default=None, gt=0, description="Maximum capacity")
    horas_semanales: Optional[int] = Field(default=None, gt=0, description="Weekly hours")
    periodo: Literal["anual", "cuatrimestral"] = Field(
        default="cuatrimestral",
        description="Course period type"
    )
    active: bool = Field(default=True, description="Whether the materia is part of the current study plan")

    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
