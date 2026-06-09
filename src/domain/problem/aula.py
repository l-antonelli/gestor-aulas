"""Aula entity - Physical classroom space."""

import uuid
from typing import Literal

from pydantic import Field, field_validator

from src.domain.base import Entity


# Valid classroom types
TipoAula = Literal["teorica", "practica", "laboratorio", "anfiteatro"]


class Aula(Entity):
    """Espacio físico donde se dictan las clases.

    Attributes:
        id: UUID opaco autogenerado. No se ingresa manualmente.
        sede_id: FK hacia `Sede`. Referencia la sede donde está el aula.
        codigo_aula: Código display editable. Único globalmente. Si se crea
            sin valor, se autoderiva como ``f"{sede.nombre}-{nombre}"``
            con espacios reemplazados por guiones.
        nombre: Nombre del aula (e.g., "AULA 01", "LABORATORIO 1").
        capacidad: Capacidad máxima en alumnos (positiva).
        tipo: Tipo (teorica, practica, laboratorio, anfiteatro).
        descripcion: Descripción opcional.
    """

    id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="UUID opaco autogenerado",
    )
    sede_id: str = Field(..., description="FK a la sede donde está el aula")
    codigo_aula: str = Field(..., min_length=1, description="Código display único")
    nombre: str = Field(..., min_length=1, description="Nombre del aula")
    capacidad: int = Field(..., gt=0, description="Capacidad máxima")
    tipo: TipoAula = Field(default="teorica", description="Tipo de aula")
    descripcion: str = Field(default="", description="Descripción opcional")

    @field_validator("sede_id")
    @classmethod
    def validate_sede_id(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("sede_id cannot be empty")
        return v

    @field_validator("codigo_aula")
    @classmethod
    def validate_codigo_aula(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("codigo_aula cannot be empty")
        return v.strip()
