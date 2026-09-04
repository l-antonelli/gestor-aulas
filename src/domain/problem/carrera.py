"""Carrera entity - University degree program."""

from typing import Optional
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
        cantidad_materias: Expected total number of materias in the curriculum (optional)
    """
    
    codigo: str = Field(
        ..., min_length=1,
        description=(
            "Código corto y único de la carrera (por ejemplo 'A' "
            "para Electrónica, 'M' para Mecánica). Se usa como "
            "identificador en cronogramas y filtros."
        ),
    )
    nombre: str = Field(
        ..., min_length=1,
        description="Nombre completo de la carrera.",
    )
    titulo_otorgado: str = Field(
        default="",
        description=(
            "Título que otorga la carrera al finalizar. Sólo se "
            "usa como referencia en la ficha de la carrera."
        ),
    )
    duracion_anios: int = Field(
        default=5, ge=1,
        description=(
            "Cantidad de años que dura el plan de estudio de la "
            "carrera."
        ),
    )
    cantidad_materias: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Cantidad total de materias esperadas en el plan de "
            "estudio. Se usa para calcular el porcentaje de "
            "completitud (cuántas ya están cargadas)."
        ),
    )
    dicta_recursado: bool = Field(
        default=True,
        description=(
            "Marcá si esta carrera permite recursar materias en "
            "el cuatrimestre 'inverso' (por ejemplo, cursar una "
            "materia del 1er cuatri también en el 2do como "
            "recursado). Destildar bloquea automáticamente esos "
            "dictados en Ciclos → Dictados."
        ),
    )

    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
