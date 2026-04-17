"""Horario entity - Schedule entry linking a comision to a time slot."""

from datetime import time

from pydantic import Field, field_validator, model_validator

from src.domain.base import Entity
from src.domain.types import HorarioId, ComisionId, CodigoMateria, DiaSemana, DIAS_SEMANA


class Horario(Entity):
    """
    Represents a schedule entry: a comision meets on a given day/time.

    This entity replaces the former Clase + HorarioCronograma indirection,
    directly associating a comision with a day and time range.

    Attributes:
        id: Unique horario identifier (auto-generated)
        comision_id: Reference to parent Comision
        codigo_materia: Subject code (denormalized for convenience)
        dia: Day of the week
        hora_inicio: Start time
        hora_fin: End time (must be after hora_inicio)
    """

    id: HorarioId = Field(..., description="Unique horario identifier")
    comision_id: ComisionId = Field(..., description="Reference to parent Comision")
    codigo_materia: CodigoMateria = Field(..., description="Subject code (denormalized)")
    dia: DiaSemana = Field(..., description="Day of the week")
    hora_inicio: time = Field(..., description="Start time")
    hora_fin: time = Field(..., description="End time")

    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v

    @field_validator("comision_id")
    @classmethod
    def validate_comision_id(cls, v: str) -> str:
        """Validate that comision_id is not empty."""
        if not v or not v.strip():
            raise ValueError("comision_id cannot be empty")
        return v

    @field_validator("codigo_materia")
    @classmethod
    def validate_codigo_materia(cls, v: str) -> str:
        """Validate that codigo_materia is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo_materia cannot be empty")
        return v

    @field_validator("dia")
    @classmethod
    def validate_dia(cls, v: str) -> str:
        """Validate that dia is a valid day of the week."""
        if v not in DIAS_SEMANA:
            raise ValueError(f"dia must be one of {DIAS_SEMANA}")
        return v

    @model_validator(mode="after")
    def validate_time_range(self) -> "Horario":
        """Validate that hora_fin is after hora_inicio."""
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("hora_fin must be after hora_inicio")
        return self
