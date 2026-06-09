"""Shared fixtures and helpers for tests.

`make_aula` y `ensure_sede` se usan en tests que arman aulas inline. Antes
del refactor de `Sede` a entidad propia, los tests hacían
`AulaDB(id="a1", sede="S1", ...)` directo. Ahora `sede` es FK; estos
helpers crean (o reusan) la sede para que los tests sigan siendo concisos.
"""

from __future__ import annotations

import uuid
from typing import Optional

from sqlmodel import Session, select

from src.database.models import AulaDB, SedeDB


def ensure_sede(session: Session, nombre: str) -> SedeDB:
    """Devuelve la `SedeDB` con ese nombre, creándola si no existe.

    Idempotente: dos llamadas con el mismo `nombre` devuelven la misma sede.
    """
    existing = session.exec(
        select(SedeDB).where(SedeDB.nombre == nombre)
    ).first()
    if existing is not None:
        return existing
    sede = SedeDB(id=str(uuid.uuid4()), nombre=nombre)
    session.add(sede)
    session.commit()
    session.refresh(sede)
    return sede


def make_aula(
    session: Session,
    *,
    id: Optional[str] = None,
    sede_nombre: str = "TestSede",
    codigo_aula: Optional[str] = None,
    nombre: str = "Aula Test",
    capacidad: int = 30,
    tipo: str = "teorica",
    descripcion: str = "",
) -> AulaDB:
    """Factory helper que crea (y persiste) una `AulaDB` con sede asociada.

    Si `id` es None, se autogenera un UUID. Si `codigo_aula` es None, usa
    el `id` (o un placeholder único) para satisfacer la constraint UNIQUE.
    No commitea — el test puede commitear cuando le convenga.
    """
    sede = ensure_sede(session, sede_nombre)
    aula_id = id or str(uuid.uuid4())
    aula = AulaDB(
        id=aula_id,
        sede_id=sede.id,
        codigo_aula=codigo_aula or aula_id,
        nombre=nombre,
        capacidad=capacidad,
        tipo=tipo,
        descripcion=descripcion,
    )
    session.add(aula)
    return aula
