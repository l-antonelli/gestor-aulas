"""Service for loading horarios and auto-creating comisiones."""

import math
import uuid
from dataclasses import dataclass, field
from datetime import time
from typing import List, Optional

from pydantic import BaseModel, Field as PydanticField, field_validator
from sqlmodel import Session, col, select

from src.database.models import ComisionDB, HorarioDB, MateriaDB
from src.database.crud import comision_crud, horario_crud, materia_crud
from src.domain.types import DIAS_SEMANA


class HorarioInput(BaseModel):
    """Input data for a single horario entry."""
    codigo_materia: str = PydanticField(min_length=1)
    comision_nombre: str = PydanticField(default="Comision Unica", min_length=1)
    dia: str
    hora_inicio: time
    hora_fin: time

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


@dataclass
class CodeResolution:
    """Result of resolving a materia code."""
    original_code: str
    resolved_code: Optional[str] = None
    resolution_type: str = "direct"  # "direct", "guarani", "unresolved"
    materia: Optional[MateriaDB] = field(default=None, repr=False)


@dataclass
class LoadResult:
    """Result of a horario loading operation."""
    comisiones_created: int = 0
    horarios_created: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    guarani_remaps: list[CodeResolution] = field(default_factory=list)
    unresolved_codes: list[str] = field(default_factory=list)
    comision_flags: list[str] = field(default_factory=list)


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

    # Ambiguous or not found
    return CodeResolution(
        original_code=codigo,
        resolved_code=None,
        resolution_type="unresolved",
    )


def _next_comision_numero(session: Session, materia_codigo: str) -> int:
    """Get the next autoincrement comision numero for a materia."""
    existing = session.exec(
        select(ComisionDB)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .order_by(col(ComisionDB.numero).desc())
    ).first()
    return (existing.numero + 1) if existing else 1


def _get_or_create_comision(
    session: Session,
    materia_codigo: str,
    comision_nombre: str,
    materia_cupo: Optional[int],
) -> tuple[ComisionDB, bool]:
    """Get existing comision or create a new one. Returns (comision, was_created)."""
    existing = session.exec(
        select(ComisionDB)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .where(ComisionDB.nombre == comision_nombre)
    ).first()

    if existing:
        return existing, False

    numero = _next_comision_numero(session, materia_codigo)
    comision_id = f"{materia_codigo}-C{numero}"

    comision = ComisionDB(
        id=comision_id,
        materia_codigo=materia_codigo,
        nombre=comision_nombre,
        numero=numero,
        cupo=materia_cupo or 0,
    )
    created = comision_crud.create(session, comision)
    return created, True


def derive_comision_count(
    total_weekly_hours_from_schedule: float,
    horas_semanales: Optional[int],
) -> tuple[int, str]:
    """
    Derive how many comisiones a materia should have.

    Returns (count, flag) where flag describes the derivation quality:
    - "exact": total_horas / horas_semanales is an exact integer
    - "ceil": used ceil(), rows can be evenly split among comisiones
    - "indivisible": ceil() gives a count that can't evenly split the schedule rows
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


def load_horarios_from_data(
    session: Session,
    data: List[HorarioInput],
) -> LoadResult:
    """
    Load horarios from structured data, auto-creating comisiones as needed.

    For each entry:
    1. Resolves the materia code (trying codigo_plan, then codigo_guarani)
    2. Gets or creates the comision for that (materia, comision_nombre) pair
    3. Creates the Horario record

    Code resolution:
    - If codigo matches a materia.codigo directly -> use it
    - If not, check codigo_guarani: if exactly 1 match -> remap and flag
    - If 0 or 2+ guarani matches -> skip row and report as unresolved
    """
    result = LoadResult()

    for i, entry in enumerate(data):
        resolution = _resolve_materia_code(session, entry.codigo_materia)

        if resolution.resolution_type == "unresolved":
            result.unresolved_codes.append(entry.codigo_materia)
            result.errors.append(
                f"Fila {i+1}: Materia '{entry.codigo_materia}' no existe "
                f"(ni como codigo_plan ni como codigo_guarani)"
            )
            continue

        if resolution.resolution_type == "guarani":
            result.guarani_remaps.append(resolution)
            result.warnings.append(
                f"Fila {i+1}: Codigo '{resolution.original_code}' resuelto via "
                f"codigo_guarani -> '{resolution.resolved_code}'"
            )

        # At this point resolution_type is "direct" or "guarani",
        # so materia and resolved_code are guaranteed non-None.
        assert resolution.materia is not None
        assert resolution.resolved_code is not None
        materia = resolution.materia
        materia_codigo = resolution.resolved_code

        try:
            comision, was_created = _get_or_create_comision(
                session,
                materia_codigo,
                entry.comision_nombre,
                materia.cupo,
            )
            if was_created:
                result.comisiones_created += 1
        except Exception as e:
            result.errors.append(f"Fila {i+1}: Error creando comision: {e}")
            continue

        try:
            horario_id = f"HOR-{uuid.uuid4().hex[:8].upper()}"
            horario = HorarioDB(
                id=horario_id,
                comision_id=comision.id,
                codigo_materia=materia_codigo,
                dia=entry.dia,
                hora_inicio=entry.hora_inicio,
                hora_fin=entry.hora_fin,
            )
            horario_crud.create(session, horario)
            result.horarios_created += 1
        except Exception as e:
            result.errors.append(f"Fila {i+1}: Error creando horario: {e}")
            continue

    return result
