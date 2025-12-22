"""Clase entity - Instance of a commission class at a specific time."""

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import ClaseId, ComisionId, HorarioId, DiaSemana, DIAS_SEMANA


class Clase(Entity):
    """
    Represents an instance of a commission class at a specific time.
    
    This is the central entity for assignment operations - each Clase
    needs to be assigned to an Aula.
    
    Attributes:
        id: Unique class instance identifier
        comision_id: Reference to parent Comision
        horario_id: Reference to HorarioCronograma
        dia: Day of the week for this class
    """
    
    id: ClaseId = Field(..., description="Unique class instance identifier")
    comision_id: ComisionId = Field(..., description="Reference to parent Comision")
    horario_id: HorarioId = Field(..., description="Reference to HorarioCronograma")
    dia: DiaSemana = Field(..., description="Day of the week")
    
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
    
    @field_validator("horario_id")
    @classmethod
    def validate_horario_id(cls, v: str) -> str:
        """Validate that horario_id is not empty."""
        if not v or not v.strip():
            raise ValueError("horario_id cannot be empty")
        return v
    
    @field_validator("dia")
    @classmethod
    def validate_dia(cls, v: str) -> str:
        """Validate that dia is a valid day of the week."""
        if v not in DIAS_SEMANA:
            raise ValueError(f"dia must be one of {DIAS_SEMANA}")
        return v
