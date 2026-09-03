"""Servicio de auditoria de cambios (Fase 3 del refactor de dictados).

Instrumenta las entidades del catalogo/configuracion con hooks
SQLAlchemy `after_insert/update/delete` que insertan una fila en
`ChangeLogDB` por cada mutacion. Los servicios de dominio ademas
pueden emitir eventos explicitos con `razon` y `origin` proporcionados
por el llamador (ej. "aceptado desde cronograma X" desde la UI de
validacion).

Entidades trackeadas (whitelist en `TRACKED_ENTITIES`):
- MateriaDB (campos: `virtual`, `active`, `dicta_recursado`, `optativa`,
  `horas_teoria`, `horas_laboratorio`).
- CarreraDB (campo: `dicta_recursado`).
- DictadoDB (campo: `virtual`; alta/baja completas).
- DictadoCicloDB (alta/baja: aparicion/desaparicion del dictado en un
  ciclo).
- SedeDB (campo: `es_default_comunes`).

Los cambios en HorarioDB, ComisionDB, ClaseDB, etc. NO se auditan
(demasiado ruido; son datos de operacion, no politica).

Uso desde servicios de dominio para emitir un evento explicito:

    from src.services.change_log_service import emit_event
    emit_event(
        session,
        entity_type="MateriaDB", entity_id="MAT101",
        entity_label="MAT101 - Calculo I",
        action="updated",
        field="dicta_recursado",
        old_value=None, new_value=True,
        reason="Promovido desde el panel de divergencias del ciclo 2026-1C",
        origin="ui:ciclos",
    )
"""

from __future__ import annotations

import json
import uuid
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import event, inspect
from sqlmodel import Session, select

from src.database.models import (
    CarreraDB,
    ChangeLogDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    MateriaDB,
    PlanificacionCursadaDB,
    ScheduleDB,
    ScheduleEntryDB,
    SedeDB,
)


# =============================================================================
# Configuracion: que entidades y campos trackear
# =============================================================================

# {entity_class: {"label_fn": callable, "fields": set[str] | None}}
# Si `fields` es None, se auditan alta/baja pero no `updated` por campo
# (usar para bridges como DictadoCicloDB). Si es un set, se emite
# `updated` solo si esos campos cambian.
TRACKED_ENTITIES: dict[type, dict] = {
    MateriaDB: {
        "label_fn": lambda o: f"{o.codigo} - {o.nombre}",
        "fields": {
            "virtual", "active", "dicta_recursado", "optativa",
            "horas_teoria", "horas_laboratorio",
        },
    },
    CarreraDB: {
        "label_fn": lambda o: f"{o.codigo} - {o.nombre}",
        "fields": {"dicta_recursado"},
    },
    DictadoDB: {
        "label_fn": lambda o: o.dictado_codigo or o.materia_codigo,
        "fields": {"virtual"},
    },
    DictadoCicloDB: {
        # bridge: label = "{dictado_id} en {ciclo_id}". No hay campos
        # updatable (es una tabla de join), solo alta/baja.
        "label_fn": lambda o: f"{o.dictado_id} en {o.ciclo_id}",
        "fields": None,
    },
    SedeDB: {
        "label_fn": lambda o: o.nombre,
        "fields": {"es_default_comunes"},
    },
    # Nivel plan (Fase 1 del tracker de plan).
    PlanificacionCursadaDB: {
        "label_fn": lambda o: o.nombre,
        "fields": {
            "nombre", "descripcion", "ciclo_id",
            "forecast_metodo_default",
        },
    },
    ComisionDB: {
        "label_fn": lambda o: (
            f"{o.materia_codigo} · {o.nombre}"
            if o.nombre else o.materia_codigo
        ),
        "fields": {
            "nombre", "numero", "cupo", "coef_asignacion",
            "dictado_id", "carrera_asignada",
        },
    },
    HorarioDB: {
        "label_fn": lambda o: (
            f"{o.codigo_materia} · {o.dia} "
            f"{o.hora_inicio.strftime('%H:%M')}"
        ),
        "fields": {
            "aula_id", "tipo_clase", "dia",
            "hora_inicio", "hora_fin",
            "virtual", "aula_asignada_manualmente",
        },
    },
    # Pre-plan: cronogramas (templates que después generan un plan).
    ScheduleDB: {
        "label_fn": lambda o: o.nombre,
        "fields": {"nombre", "ciclo_id"},
    },
    ScheduleEntryDB: {
        "label_fn": lambda o: (
            f"{o.codigo_materia} · {o.dia} "
            f"{o.hora_inicio.strftime('%H:%M')}"
        ),
        "fields": {
            "dia", "hora_inicio", "hora_fin",
            "comision_id", "tipo_clase", "virtual",
        },
    },
}


# =============================================================================
# Context vars para propagar origin/reason a los hooks automaticos
# =============================================================================

_current_origin: ContextVar[str] = ContextVar("_current_origin", default="auto")
_current_reason: ContextVar[str] = ContextVar("_current_reason", default="")
# Cuando está True, los hooks automáticos de insert/update/delete NO
# emiten filas en ChangeLogDB. Se usa en operaciones bulk (típicamente
# el LP) que emiten un evento agregado explícito en lugar de N filas
# individuales.
_current_skip_hooks: ContextVar[bool] = ContextVar(
    "_current_skip_hooks", default=False,
)


class change_context:
    """Context manager para setear origen + razon de las mutaciones
    capturadas por hooks automaticos.

    Uso:

        with change_context(origin="ui:ciclos", reason="..."):
            session.commit()

    Con ``skip_hooks=True`` los hooks automáticos no emiten filas
    durante el bloque. Sirve para operaciones bulk (LP) que registran
    su cambio mediante un evento agregado explícito y no quieren
    generar N filas individuales. Ejemplo:

        with change_context(skip_hooks=True):
            apply_solution(...)  # muta 100 HorarioDB sin emitir hooks
        # Después, un solo emit_event(...) por corrida.

    Al salir del bloque, restaura los valores previos.
    """

    def __init__(
        self,
        *,
        origin: str = "auto",
        reason: str = "",
        skip_hooks: bool = False,
    ):
        self.origin = origin
        self.reason = reason
        self.skip_hooks = skip_hooks
        self._tokens: list = []

    def __enter__(self):
        self._tokens.append((_current_origin, _current_origin.set(self.origin)))
        self._tokens.append((_current_reason, _current_reason.set(self.reason)))
        self._tokens.append(
            (_current_skip_hooks, _current_skip_hooks.set(self.skip_hooks))
        )
        return self

    def __exit__(self, *args):
        for var, token in reversed(self._tokens):
            var.reset(token)


# =============================================================================
# Emission API
# =============================================================================

def _json_safe(value: Any) -> Optional[str]:
    """Serializa un valor a JSON string, o None si es None."""
    if value is None:
        return None
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return json.dumps(str(value))


def emit_event(
    session: Session,
    *,
    entity_type: str,
    entity_id: str,
    entity_label: str = "",
    action: str,
    field: Optional[str] = None,
    old_value: Any = None,
    new_value: Any = None,
    reason: str = "",
    origin: str = "auto",
) -> ChangeLogDB:
    """Emite un evento explicito al change log.

    A diferencia de los hooks automaticos, permite proporcionar `reason`
    y `origin` con contexto de dominio. Los servicios que quieren
    dejar traza rica deberian usar esto en vez de dejar que los hooks
    capturen todo.
    """
    if action not in {"created", "updated", "deleted"}:
        raise ValueError(f"Action invalida: '{action}'")
    entry = ChangeLogDB(
        id=str(uuid.uuid4()),
        entity_type=entity_type,
        entity_id=entity_id,
        entity_label=entity_label,
        action=action,
        field=field,
        old_value=_json_safe(old_value),
        new_value=_json_safe(new_value),
        reason=reason,
        when=datetime.utcnow(),
        origin=origin,
    )
    session.add(entry)
    # No commit acá: dejamos que el caller lo haga junto con su unidad
    # de trabajo. Si el caller nunca commitea, el evento tampoco persiste.
    return entry


# =============================================================================
# Hooks automaticos
# =============================================================================

def _label(instance: Any) -> str:
    cfg = TRACKED_ENTITIES.get(type(instance))
    if cfg is None:
        return ""
    try:
        return cfg["label_fn"](instance) or ""
    except Exception:
        return ""


def _entity_pk(instance: Any) -> str:
    """Devuelve la PK como string. Para bridges compuestos, une con `+`."""
    inspector = inspect(instance)
    # `identity` puede ser None despues del flush en after_insert.
    # Fallback: leer atributos que estan en la lista `primary_key` del
    # mapper.
    pk_values = []
    for col in inspector.mapper.primary_key:
        pk_values.append(getattr(instance, col.name, None))
    if not pk_values or all(v is None for v in pk_values):
        return ""
    if len(pk_values) == 1:
        return str(pk_values[0]) if pk_values[0] is not None else ""
    return "+".join(
        str(v) if v is not None else "" for v in pk_values
    )


def _on_after_insert(mapper, connection, target) -> None:
    if _current_skip_hooks.get():
        return
    cfg = TRACKED_ENTITIES.get(type(target))
    if cfg is None:
        return
    _insert_row(
        connection,
        entity_type=type(target).__name__,
        entity_id=_entity_pk(target),
        entity_label=_label(target),
        action="created",
    )


def _on_after_delete(mapper, connection, target) -> None:
    if _current_skip_hooks.get():
        return
    cfg = TRACKED_ENTITIES.get(type(target))
    if cfg is None:
        return
    _insert_row(
        connection,
        entity_type=type(target).__name__,
        entity_id=_entity_pk(target),
        entity_label=_label(target),
        action="deleted",
    )


def _on_after_update(mapper, connection, target) -> None:
    if _current_skip_hooks.get():
        return
    cfg = TRACKED_ENTITIES.get(type(target))
    if cfg is None:
        return
    fields = cfg.get("fields")
    if fields is None:
        return  # bridge sin campos updatable
    state = inspect(target)
    # Para cada campo trackeado, ver si cambio.
    for field in fields:
        attr = state.attrs.get(field)
        if attr is None:
            continue
        history = attr.load_history()
        if not history.has_changes():
            continue
        old = history.deleted[0] if history.deleted else None
        new = history.added[0] if history.added else attr.value
        _insert_row(
            connection,
            entity_type=type(target).__name__,
            entity_id=_entity_pk(target),
            entity_label=_label(target),
            action="updated",
            field=field,
            old_value=_json_safe(old),
            new_value=_json_safe(new),
        )


def _insert_row(
    connection,
    *,
    entity_type: str,
    entity_id: str,
    entity_label: str,
    action: str,
    field: Optional[str] = None,
    old_value: Optional[str] = None,
    new_value: Optional[str] = None,
) -> None:
    """Inserta la fila usando `connection.execute` (no session), porque
    los hooks corren en el flush, no en el commit."""
    origin = _current_origin.get()
    reason = _current_reason.get()
    connection.execute(
        ChangeLogDB.__table__.insert().values(
            id=str(uuid.uuid4()),
            entity_type=entity_type,
            entity_id=entity_id,
            entity_label=entity_label,
            action=action,
            field=field,
            old_value=old_value,
            new_value=new_value,
            reason=reason,
            when=datetime.utcnow(),
            origin=origin,
        )
    )


def _register_hooks() -> None:
    """Registra los hooks SQLAlchemy sobre TRACKED_ENTITIES.

    Idempotente: `event.listens_for` con la misma callable no duplica.
    Se llama al importar el modulo desde `connection.init_db`.
    """
    for entity_cls in TRACKED_ENTITIES:
        event.listen(entity_cls, "after_insert", _on_after_insert)
        event.listen(entity_cls, "after_update", _on_after_update)
        event.listen(entity_cls, "after_delete", _on_after_delete)


_register_hooks()


# =============================================================================
# Query API
# =============================================================================

def get_log_for_entity(
    session: Session,
    entity_type: str,
    entity_id: str,
    *,
    limit: int = 50,
) -> list[ChangeLogDB]:
    """Historial de una entidad puntual, ordenado del mas reciente al
    mas viejo."""
    return list(session.exec(
        select(ChangeLogDB)
        .where(ChangeLogDB.entity_type == entity_type)
        .where(ChangeLogDB.entity_id == entity_id)
        .order_by(ChangeLogDB.when.desc())  # type: ignore[attr-defined]
        .limit(limit)
    ).all())


def get_recent_log(
    session: Session,
    *,
    limit: int = 100,
    entity_types: Optional[list[str]] = None,
) -> list[ChangeLogDB]:
    """Feed global de mutaciones recientes. Opcionalmente filtrado por
    tipo de entidad."""
    stmt = select(ChangeLogDB).order_by(
        ChangeLogDB.when.desc()  # type: ignore[attr-defined]
    ).limit(limit)
    if entity_types:
        from sqlmodel import col as _col
        stmt = stmt.where(_col(ChangeLogDB.entity_type).in_(entity_types))
    return list(session.exec(stmt).all())
