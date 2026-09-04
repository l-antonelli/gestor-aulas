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

    codigo: CodigoMateria = Field(
        ...,
        description=(
            "Código único de la materia según el plan de estudio. "
            "Se usa para identificarla en cronogramas, comisiones y "
            "reportes."
        ),
    )
    nombre: str = Field(
        ..., min_length=1,
        description="Nombre completo de la materia.",
    )
    codigo_guarani: Optional[str] = Field(
        default=None,
        description=(
            "Código en el sistema Guaraní (SIU) — sólo si es "
            "distinto al del plan de estudio. Opcional."
        ),
    )
    cupo: Optional[int] = Field(
        default=None, gt=0,
        description=(
            "Cantidad máxima de alumnos por comisión. Se completa "
            "generalmente a partir de datos de inscripción."
        ),
    )
    horas_semanales: Optional[float] = Field(
        default=None, gt=0,
        description=(
            "Total de horas semanales de cursada declaradas por la "
            "materia. Puede incluir teóricas + laboratorio."
        ),
    )
    horas_teoria: Optional[float] = Field(
        default=None, ge=0,
        description=(
            "Horas semanales que se dictan como teoría. Sumado a "
            "'horas laboratorio' debería igualar 'horas semanales'."
        ),
    )
    horas_laboratorio: Optional[float] = Field(
        default=None, ge=0,
        description=(
            "Horas semanales que se dictan como laboratorio. Deja "
            "en 0 si la materia no tiene componente práctico."
        ),
    )
    periodo: Literal["anual", "cuatrimestral"] = Field(
        default="cuatrimestral",
        description=(
            "Duración de la materia: anual (dos cuatrimestres) o "
            "cuatrimestral (uno)."
        ),
    )
    active: bool = Field(
        default=True,
        description=(
            "Marcá si la materia sigue vigente en el plan de "
            "estudio actual. Destildá para archivar materias que "
            "ya no se dictan (dejan de aparecer en filtros y "
            "reportes)."
        ),
    )
    virtual: bool = Field(
        default=False,
        description=(
            "Marcá si esta materia se dicta siempre a distancia y "
            "no ocupa aulas físicas. Se puede sobreescribir por "
            "ciclo desde Ciclos → Dictados."
        ),
    )
    optativa: bool = Field(
        default=False,
        description=(
            "Marcá si es materia optativa (electiva). Las materias "
            "optativas no cuentan como obligatorias en la cursada "
            "y suelen tratarse aparte en los reportes."
        ),
    )
    dicta_recursado: Optional[bool] = Field(
        default=None,
        description=(
            "Sólo tocar si la materia tiene un régimen de "
            "recursado distinto al de su carrera. Dejar vacío para "
            "usar la configuración de la carrera; marcar Sí para "
            "que se dicte también en el cuatrimestre 'inverso' "
            "(recursado); marcar No para bloquearlo explícitamente."
        ),
    )

    @field_validator("codigo")
    @classmethod
    def validate_codigo(cls, v: str) -> str:
        """Validate that codigo is not empty."""
        if not v or not v.strip():
            raise ValueError("codigo cannot be empty")
        return v
