"""Service for loading horarios and auto-creating comisiones."""

import uuid
from dataclasses import dataclass, field
from datetime import time
from typing import List

from pydantic import BaseModel, Field as PydanticField, field_validator
from sqlmodel import Session, select

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
        if hora_inicio and v <= hora_inicio:
            raise ValueError("hora_fin debe ser posterior a hora_inicio")
        return v


@dataclass
class LoadResult:
    """Result of a horario loading operation."""
    comisiones_created: int = 0
    horarios_created: int = 0
    errors: list[str] = field(default_factory=list)


def _next_comision_numero(session: Session, materia_codigo: str) -> int:
    """Get the next autoincrement comision numero for a materia."""
    existing = session.exec(
        select(ComisionDB)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .order_by(ComisionDB.numero.desc())
    ).first()
    return (existing.numero + 1) if existing else 1


def _get_or_create_comision(
    session: Session,
    materia_codigo: str,
    comision_nombre: str,
    materia_cupo: int,
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
        cupo=materia_cupo,
    )
    created = comision_crud.create(session, comision)
    return created, True


def load_horarios_from_data(
    session: Session,
    data: List[HorarioInput],
) -> LoadResult:
    """
    Load horarios from structured data, auto-creating comisiones as needed.

    For each entry:
    1. Validates the referenced materia exists
    2. Gets or creates the comision for that (materia, comision_nombre) pair
    3. Creates the Horario record
    """
    result = LoadResult()

    for i, entry in enumerate(data):
        materia = materia_crud.get(session, entry.codigo_materia)
        if materia is None:
            result.errors.append(
                f"Fila {i+1}: Materia '{entry.codigo_materia}' no existe"
            )
            continue

        try:
            comision, was_created = _get_or_create_comision(
                session,
                entry.codigo_materia,
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
                codigo_materia=entry.codigo_materia,
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
