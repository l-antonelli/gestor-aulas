"""Utilidades para resolucion de codigos de materia y derivacion de comisiones.

Funciones auxiliares usadas por schedule_service y plan_generation_service.
"""

import math
from dataclasses import dataclass, field
from datetime import time
from typing import Optional

from pydantic import BaseModel, Field as PydanticField, field_validator
from sqlmodel import Session, func, select

from src.database.models import MateriaDB
from src.database.crud import materia_crud
from src.domain.types import DIAS_SEMANA


class HorarioInput(BaseModel):
    """Input data for a single horario entry (used by horario_file_parser).

    Extendido en Fase C2 del rediseño 2026-09-15 con `tipo_clase` y
    `virtual`, que la plantilla generada por
    ``template_export_service`` expone como dropdowns. Ambos son
    opcionales y siguen la semántica del modelo:

    - ``tipo_clase``: None = por determinar (default histórico);
      ``"teorica"`` / ``"laboratorio"`` cuando la cátedra lo declara.
    - ``virtual``: booleano — desde 2026-09-23 un valor vacío en el
      archivo se interpreta como ``False`` (presencial). ``None``
      sólo sobrevive por compatibilidad con llamadores viejos.
    - ``comision_codigo`` (2026-09-23): código numérico de la
      comisión declarado por la cátedra en la plantilla nueva —
      mapea a ``ComisionDB.numero``. ``None`` = esquema histórico
      (texto libre en ``comision_nombre``, número autoderivado).
    """
    codigo_materia: str = PydanticField(min_length=1)
    comision_nombre: str = PydanticField(default="Comision Unica", min_length=1)
    comision_codigo: Optional[int] = PydanticField(default=None, ge=1)
    dia: str
    hora_inicio: time
    hora_fin: time
    tipo_clase: Optional[str] = PydanticField(default=None)
    virtual: Optional[bool] = PydanticField(default=None)

    @field_validator("dia")
    @classmethod
    def validate_dia(cls, v: str) -> str:
        if v not in DIAS_SEMANA:
            raise ValueError(f"Dia invalido: {v}. Debe ser uno de {sorted(DIAS_SEMANA)}")
        return v

    @field_validator("hora_fin")
    @classmethod
    def validate_hora_fin(cls, v: time, info) -> time:
        hora_inicio = info.data.get("hora_inicio")
        # time(0,0) = midnight, valid for classes that end at midnight (e.g. 20:00-00:00)
        if hora_inicio and v != time(0, 0) and v <= hora_inicio:
            raise ValueError("hora_fin debe ser posterior a hora_inicio")
        return v

    @field_validator("tipo_clase")
    @classmethod
    def validate_tipo_clase(cls, v: Optional[str]) -> Optional[str]:
        if v is None or v == "":
            return None
        if v not in ("teorica", "laboratorio"):
            raise ValueError(
                f"tipo_clase invalido: '{v}'. "
                "Debe ser 'teorica', 'laboratorio' o vacio."
            )
        return v


@dataclass
class CodeResolution:
    """Result of resolving a materia code."""
    original_code: str
    resolved_code: Optional[str] = None
    resolution_type: str = "direct"  # "direct", "guarani", "unresolved"
    materia: Optional[MateriaDB] = field(default=None, repr=False)


def _resolve_materia_code(session: Session, codigo: str) -> CodeResolution:
    """
    Resolve a materia code, trying codigo_plan first, then codigo_guarani.

    Returns CodeResolution with resolution_type:
    - "direct": found by codigo (codigo_plan)
    - "guarani": found by codigo_guarani with unique 1:1 mapping
    - "unresolved": not found or ambiguous guarani match
    """
    # Try direct match on codigo (= codigo_plan)
    materia = materia_crud.get(session, codigo)
    if materia is not None:
        return CodeResolution(
            original_code=codigo,
            resolved_code=codigo,
            resolution_type="direct",
            materia=materia,
        )

    # Try matching by codigo_guarani
    matches = session.exec(
        select(MateriaDB).where(MateriaDB.codigo_guarani == codigo)
    ).all()

    if len(matches) == 1:
        materia = matches[0]
        return CodeResolution(
            original_code=codigo,
            resolved_code=materia.codigo,
            resolution_type="guarani",
            materia=materia,
        )

    # 2026-09-23: resolución por NOMBRE exacto (case-insensitive) —
    # la plantilla nueva permite elegir la materia por nombre y dejar
    # el código vacío; el parser propaga el nombre en `codigo` y acá
    # se cruza contra el catálogo. Sólo matchea si el nombre es único.
    matches_nombre = session.exec(
        select(MateriaDB).where(
            func.lower(MateriaDB.nombre) == codigo.strip().lower()
        )
    ).all()
    if len(matches_nombre) == 1:
        materia = matches_nombre[0]
        return CodeResolution(
            original_code=codigo,
            resolved_code=materia.codigo,
            resolution_type="nombre",
            materia=materia,
        )

    # Ambiguous or not found
    return CodeResolution(
        original_code=codigo,
        resolved_code=None,
        resolution_type="unresolved",
    )


def derive_comision_count(
    total_weekly_hours_from_schedule: float,
    horas_semanales: Optional[float],
) -> tuple[int, str]:
    """
    Derive how many comisiones a materia should have.

    Returns (count, flag) where flag describes the derivation quality:
    - "exact": total_horas / horas_semanales is an exact integer
    - "ceil": used ceil(), rows can be evenly split among comisiones
    - "no_data": horas_semanales is missing, defaulting to 1
    """
    if not horas_semanales or horas_semanales <= 0:
        return 1, "no_data"

    ratio = total_weekly_hours_from_schedule / horas_semanales

    if ratio <= 0:
        return 1, "no_data"

    # Exact integer?
    if abs(ratio - round(ratio)) < 0.01:
        return max(1, round(ratio)), "exact"

    # Use ceil
    n = max(1, math.ceil(ratio))
    return n, "ceil"
