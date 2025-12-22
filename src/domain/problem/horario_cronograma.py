"""HorarioCronograma entity - Time slot in the academic schedule."""

from datetime import time

from pydantic import Field, field_validator, model_validator

from src.domain.base import Entity
from src.domain.types import HorarioId, DiaSemana, DIAS_SEMANA


class HorarioCronograma(Entity):
    """
    Represents a time slot in the academic schedule.
    
    Attributes:
        id: Unique schedule slot identifier
        dia_semana: Day of the week
        hora_inicio: Start time
        hora_fin: End time (must be after hora_inicio)
    """
    
    id: HorarioId = Field(..., description="Unique schedule slot identifier")
    dia_semana: DiaSemana = Field(..., description="Day of the week")
    hora_inicio: time = Field(..., description="Start time")
    hora_fin: time = Field(..., description="End time")
    
    @field_validator("id")
    @classmethod
    def validate_id(cls, v: str) -> str:
        """Validate that id is not empty."""
        if not v or not v.strip():
            raise ValueError("id cannot be empty")
        return v
    
    @field_validator("dia_semana")
    @classmethod
    def validate_dia_semana(cls, v: str) -> str:
        """Validate that dia_semana is a valid day."""
        if v not in DIAS_SEMANA:
            raise ValueError(f"dia_semana must be one of {DIAS_SEMANA}")
        return v
    
    @model_validator(mode="after")
    def validate_time_range(self) -> "HorarioCronograma":
        """Validate that hora_fin is after hora_inicio."""
        if self.hora_fin <= self.hora_inicio:
            raise ValueError("hora_fin must be after hora_inicio")
        return self
