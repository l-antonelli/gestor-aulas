"""Sede entity - Physical location where aulas are housed."""

import uuid

from pydantic import Field, field_validator

from src.domain.base import Entity


class Sede(Entity):
    """Sede física donde se ubican las aulas.

    Attributes:
        id: UUID opaco autogenerado.
        nombre: Nombre de la sede (único globalmente).
    """

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    nombre: str = Field(..., min_length=1, description="Nombre de la sede")

    @field_validator("nombre")
    @classmethod
    def validate_nombre(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("nombre cannot be empty")
        return v.strip()
