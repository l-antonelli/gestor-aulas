"""Widget de historial de cambios (Fase 3b).

Componentes reutilizables para renderizar el `ChangeLogDB`:

- `render_historial_entidad(entity_type, entity_id, ...)`: pestaña
  "Historial" para una entidad puntual. Se llama desde la pagina de
  Materias, Carreras, Ciclos, etc.
- `render_feed_global(...)`: feed global de mutaciones recientes.
  Se llama desde el dashboard.

Los eventos se muestran en formato timeline compacto con:
- Emoji segun action (➕/✏️/🗑️).
- Etiqueta humana de entidad.
- Campo + old→new (para updated).
- Timestamp relativo ("hace 3 días").
- Origin + razon si estan seteados.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta

import streamlit as st

from src.database.connection import get_session
from src.database.models import ChangeLogDB
from src.services.change_log_service import (
    get_log_for_entity,
    get_recent_log,
)


ACTION_EMOJI = {
    "created": "➕",
    "updated": "✏️",
    "deleted": "🗑️",
}

ORIGIN_LABEL = {
    "auto": "sistema",
    "ui:ciclos": "UI Ciclos",
    "ui:validacion": "UI Validación",
    "ui:planes": "UI Planes",
    "ui:materias": "UI Materias",
    "ui:carreras": "UI Carreras",
    "script": "script",
}

ENTITY_LABEL = {
    "MateriaDB": "Materia",
    "CarreraDB": "Carrera",
    "DictadoDB": "Dictado",
    "DictadoCicloDB": "Dictado en ciclo",
    "SedeDB": "Sede",
    "HorarioDB": "Horario",
    "ComisionDB": "Comisión",
    "PlanificacionCursadaDB": "Plan de cursada",
    "ScheduleDB": "Cronograma",
    "ScheduleEntryDB": "Entrada de cronograma",
    "LPRunDB": "Corrida del asignador",
}


def _fmt_when(when: datetime) -> str:
    """Timestamp relativo: 'hace 3m', 'hace 2h', 'hace 4d', 'YYYY-MM-DD'."""
    delta = datetime.utcnow() - when
    if delta.total_seconds() < 60:
        return "hace unos segundos"
    if delta.total_seconds() < 3600:
        return f"hace {int(delta.total_seconds() // 60)} min"
    if delta.total_seconds() < 86400:
        return f"hace {int(delta.total_seconds() // 3600)} h"
    if delta.days < 30:
        return f"hace {delta.days} días"
    return when.strftime("%Y-%m-%d")


def _fmt_value(raw: str | None) -> str:
    """Formatea un valor JSON serializado a algo legible."""
    if raw is None:
        return "—"
    try:
        v = json.loads(raw)
    except json.JSONDecodeError:
        return str(raw)
    if v is None:
        return "None (heredar)"
    if isinstance(v, bool):
        return "Sí" if v else "No"
    return str(v)


def _fmt_origin(origin: str) -> str:
    return ORIGIN_LABEL.get(origin, origin)


def _render_row(entry: ChangeLogDB) -> None:
    """Renderiza una fila del timeline."""
    emoji = ACTION_EMOJI.get(entry.action, "•")
    when = _fmt_when(entry.when)
    origin = _fmt_origin(entry.origin)

    if entry.action == "updated" and entry.field:
        old = _fmt_value(entry.old_value)
        new = _fmt_value(entry.new_value)
        detalle = (
            f"**{entry.field}**: `{old}` → `{new}`"
        )
    elif entry.action == "created":
        detalle = "**creada**"
    elif entry.action == "deleted":
        detalle = "**borrada**"
    else:
        detalle = entry.action

    reason_line = f"  \n  💬 _{entry.reason}_" if entry.reason else ""
    label_line = (
        f"  \n  🏷️ {entry.entity_label}"
        if entry.entity_label else ""
    )
    st.markdown(
        f"{emoji} {detalle}"
        f"  \n  <span style='color:#888;font-size:0.85em'>"
        f"{when} · origen: {origin}</span>"
        f"{label_line}{reason_line}",
        unsafe_allow_html=True,
    )


def render_historial_entidad(
    entity_type: str,
    entity_id: str,
    *,
    limit: int = 50,
    empty_message: str = (
        "Sin cambios registrados para esta entidad."
    ),
) -> None:
    """Pestaña "Historial" para una entidad puntual."""
    with next(get_session()) as _s:
        entries = get_log_for_entity(
            _s, entity_type, entity_id, limit=limit,
        )
    if not entries:
        st.caption(empty_message)
        return
    st.caption(
        f"Últimos {len(entries)} cambio(s). Los cambios manuales "
        "quedan marcados con su origen (UI, script). Los del sistema "
        "aparecen como `sistema` (hooks automáticos)."
    )
    for e in entries:
        _render_row(e)
        st.markdown("<hr style='margin:8px 0;opacity:.2'>", unsafe_allow_html=True)


def render_feed_global(
    *,
    limit: int = 50,
    days: int = 30,
    key_ns: str = "feed_global",
) -> None:
    """Feed global de cambios recientes.

    Args:
        limit: max entradas a mostrar.
        days: filtro por antiguedad (ignora eventos > `days` dias).
        key_ns: namespace para keys de widgets streamlit.
    """
    with next(get_session()) as _s:
        entries = get_recent_log(_s, limit=limit)

    # Filtro por antiguedad.
    cutoff = datetime.utcnow() - timedelta(days=days)
    entries = [e for e in entries if e.when >= cutoff]

    if not entries:
        st.info(
            f"Sin cambios en los últimos {days} días."
        )
        return

    # Filtros UI.
    _fc1, _fc2 = st.columns([2, 1])
    with _fc1:
        _tipos = sorted({e.entity_type for e in entries})
        _tipos_sel = st.multiselect(
            "Tipo de entidad",
            options=_tipos,
            default=_tipos,
            format_func=lambda t: ENTITY_LABEL.get(t, t),
            key=f"{key_ns}_tipos",
        )
    with _fc2:
        _orig_options = sorted({e.origin for e in entries})
        _orig_sel = st.multiselect(
            "Origen",
            options=_orig_options,
            default=_orig_options,
            format_func=_fmt_origin,
            key=f"{key_ns}_origins",
        )

    filtered = [
        e for e in entries
        if e.entity_type in _tipos_sel and e.origin in _orig_sel
    ]
    st.caption(
        f"Mostrando {len(filtered)} de {len(entries)} eventos "
        f"de los últimos {days} días."
    )
    for e in filtered:
        _render_row(e)
        st.markdown("<hr style='margin:8px 0;opacity:.2'>", unsafe_allow_html=True)
