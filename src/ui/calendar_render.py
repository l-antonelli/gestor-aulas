"""Componente reutilizable de calendario semanal basado en streamlit-calendar.

Convierte datos de grilla (ScheduleBlock / TimetableBlock) en eventos
FullCalendar y los renderiza con vista timeGridWeek.

Los eventos se definen como *recurrentes* usando daysOfWeek + startTime/endTime,
lo que permite que se muestren en cualquier semana sin depender de initialDate.
"""

from dataclasses import dataclass
from datetime import datetime, time
from typing import Optional

import streamlit as st
from streamlit_calendar import calendar

from src.database.models import ConfiguracionHoraria
from src.services.schedule_service import ScheduleBlock
from src.services.plan_generation_service import TimetableBlock

# ---------------------------------------------------------------------------
# Paleta de colores compartida
# ---------------------------------------------------------------------------
PALETTE = [
    "#1E88E5", "#F4511E", "#43A047", "#8E24AA",
    "#00897B", "#FFB300", "#3949AB", "#D81B60",
    "#039BE5", "#7CB342", "#6D4C41", "#546E7A",
]
TEXT_COLOR = "#FFFFFF"

# ---------------------------------------------------------------------------
# Mapeo dia castellano <-> dow FullCalendar (0=domingo, 1=lunes, ..., 6=sabado)
# ---------------------------------------------------------------------------
DIA_TO_DOW: dict[str, int] = {
    "Lunes": 1,
    "Martes": 2,
    "Miércoles": 3,
    "Jueves": 4,
    "Viernes": 5,
    "Sábado": 6,
}

# Python weekday(): 0=lunes, 1=martes, ..., 5=sabado, 6=domingo
_WEEKDAY_TO_DIA: dict[int, str] = {
    0: "Lunes",
    1: "Martes",
    2: "Miércoles",
    3: "Jueves",
    4: "Viernes",
    5: "Sábado",
}


def _fmt_time(t: time) -> str:
    """Formatea time como HH:MM:SS para FullCalendar."""
    return t.strftime("%H:%M:%S")


def parse_callback_datetime(iso_str: str) -> tuple[str, time]:
    """Parsea un datetime ISO de un callback de FullCalendar a (dia, time).

    Los callbacks devuelven fechas de la semana que se esta mostrando.
    Usamos weekday() para determinar el dia de la semana.

    Soporta formatos con y sin sufijo 'Z', y con timezone offset.
    Ejemplo: "2026-04-07T10:30:00" (un martes) -> ("Martes", time(10, 30))
    """
    clean = iso_str.replace("Z", "").split("+")[0]
    dt = datetime.fromisoformat(clean)
    dia = _WEEKDAY_TO_DIA.get(dt.weekday())
    if dia is None:
        raise ValueError(f"Weekday {dt.weekday()} no mapeado (domingo no soportado)")
    return dia, dt.time()


@dataclass
class CalendarAction:
    """Accion detectada desde un callback del calendario editable."""
    action: str  # "move", "click", "select"
    entry_id: Optional[str] = None
    materia_codigo: Optional[str] = None
    dia: Optional[str] = None
    hora_inicio: Optional[time] = None
    hora_fin: Optional[time] = None


def _inject_tab_fix(height: int = 700) -> None:
    """Workaround para bug de streamlit-calendar dentro de st.tabs.

    El iframe del componente se renderiza con altura 0 cuando no esta
    en el primer tab.  Forzamos la altura via CSS.
    Ref: https://github.com/im-perativa/streamlit-calendar/issues/31
    """
    st.markdown(
        f"""<style>
        iframe[title="streamlit_calendar.calendar"] {{
            height: {height}px !important;
        }}
        </style>""",
        unsafe_allow_html=True,
    )


def _build_calendar_options(
    config: ConfiguracionHoraria,
    hidden_days: list[int],
) -> dict:
    """Opciones comunes de FullCalendar para ambas funciones de render."""
    return {
        "initialView": "timeGridWeek",
        "slotMinTime": _fmt_time(config.hora_inicio_operativo),
        "slotMaxTime": _fmt_time(config.hora_fin_operativo),
        "allDaySlot": False,
        "locale": "es",
        "hiddenDays": hidden_days,
        "headerToolbar": {
            "left": "",
            "center": "",
            "right": "",
        },
        "dayHeaderFormat": {"weekday": "long"},
        "slotLabelFormat": {
            "hour": "2-digit",
            "minute": "2-digit",
            "hour12": False,
        },
        "expandRows": True,
        "height": 650,
        "eventDisplay": "block",
        "slotEventOverlap": False,
    }


def _compute_hidden_days(config: ConfiguracionHoraria) -> list[int]:
    """Calcula los dias ocultos (no operativos) para FullCalendar."""
    dias_config = {d.strip() for d in config.dias_operativos.split(",") if d.strip()}
    all_dow = {0, 1, 2, 3, 4, 5, 6}  # 0=domingo
    active_dow = {DIA_TO_DOW[d] for d in dias_config if d in DIA_TO_DOW}
    return sorted(all_dow - active_dow)


def _render_legend(mat_colors: dict[str, tuple[str, str]], mat_names: dict[str, str]) -> None:
    """Renderiza la leyenda de colores de materias."""
    codes = sorted(mat_colors.keys())
    if not codes:
        return
    st.divider()
    st.markdown("**Materias:**")
    n_cols = min(len(codes), 4) or 1
    legend_cols = st.columns(n_cols)
    for i, code in enumerate(codes):
        with legend_cols[i % n_cols]:
            bg, fg = mat_colors[code]
            nombre = mat_names.get(code, code)
            st.markdown(
                f'<div style="background-color:{bg};color:{fg};'
                f'padding:2px 8px;border-radius:3px;margin-bottom:4px;'
                f'font-size:0.85em;">'
                f'<b>{code}</b> — {nombre}</div>',
                unsafe_allow_html=True,
            )


def _assign_colors(grid_data: dict) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    """Asigna colores a materias y construye lookup de nombres."""
    all_mat_codes = sorted({
        b.materia_codigo for blocks in grid_data.values() for b in blocks
    })
    mat_colors = {
        code: (PALETTE[i % len(PALETTE)], TEXT_COLOR)
        for i, code in enumerate(all_mat_codes)
    }
    mat_names: dict[str, str] = {}
    for blocks in grid_data.values():
        for b in blocks:
            mat_names.setdefault(b.materia_codigo, b.materia_nombre)
    return mat_colors, mat_names


# ---------------------------------------------------------------------------
# Render para Cronogramas (ScheduleBlock) — read-only
# ---------------------------------------------------------------------------
def render_schedule_calendar(
    grid_data: dict[str, list[ScheduleBlock]],
    config: ConfiguracionHoraria,
    key: str = "schedule_cal",
) -> Optional[dict]:
    """Renderiza un cronograma como calendario semanal FullCalendar (read-only).

    Usa eventos recurrentes (daysOfWeek + startTime/endTime) para que se
    muestren en cualquier semana sin depender de una fecha fija.
    """
    if not grid_data:
        st.info("El cronograma no tiene entradas.")
        return None

    mat_colors, mat_names = _assign_colors(grid_data)

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))
            events.append({
                "title": f"{b.materia_codigo} - {b.materia_nombre}",
                "daysOfWeek": [dow],
                "startTime": _fmt_time(b.hora_inicio),
                "endTime": _fmt_time(b.hora_fin),
                "backgroundColor": bg,
                "textColor": fg,
                "borderColor": bg,
            })

    hidden_days = _compute_hidden_days(config)
    options = _build_calendar_options(config, hidden_days)

    _inject_tab_fix(options["height"])
    result = calendar(
        events=events,
        options=options,
        callbacks=[],
        key=key,
    )

    _render_legend(mat_colors, mat_names)

    return result


# ---------------------------------------------------------------------------
# Render para Planes / Grilla Horaria (TimetableBlock) — read-only
# ---------------------------------------------------------------------------
def render_timetable_calendar(
    grid_data: dict[str, list[TimetableBlock]],
    config: ConfiguracionHoraria,
    key: str = "timetable_cal",
) -> Optional[dict]:
    """Renderiza un plan de cursada como calendario semanal FullCalendar (read-only).

    Similar a render_schedule_calendar pero con informacion de comision,
    indicadores de virtual y de periodo.
    """
    if not grid_data:
        st.info("No hay horarios para mostrar.")
        return None

    mat_colors, mat_names = _assign_colors(grid_data)

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))

            v_tag = " [V]" if b.virtual else ""
            title = f"{b.materia_codigo}{v_tag} - {b.comision_nombre}"

            border_color = "#FF9800" if b.en_periodo is False else bg

            events.append({
                "title": title,
                "daysOfWeek": [dow],
                "startTime": _fmt_time(b.hora_inicio),
                "endTime": _fmt_time(b.hora_fin),
                "backgroundColor": bg,
                "textColor": fg,
                "borderColor": border_color,
            })

    hidden_days = _compute_hidden_days(config)
    options = _build_calendar_options(config, hidden_days)

    _inject_tab_fix(options["height"])
    result = calendar(
        events=events,
        options=options,
        callbacks=[],
        key=key,
    )

    _render_legend(mat_colors, mat_names)

    st.markdown(
        '<div style="font-size:0.85em;margin-top:8px;">'
        '<span style="display:inline-block;width:14px;height:14px;'
        'border:3px solid #FF9800;border-radius:2px;vertical-align:middle;'
        'margin-right:4px;"></span> Fuera del cuatrimestre planificado · '
        '[V] Virtual'
        '</div>',
        unsafe_allow_html=True,
    )

    return result


# ---------------------------------------------------------------------------
# Render editable para Cronogramas (ScheduleBlock) — drag/drop/resize/click
# ---------------------------------------------------------------------------
def render_editable_schedule_calendar(
    grid_data: dict[str, list[ScheduleBlock]],
    config: ConfiguracionHoraria,
    key: str = "editable_schedule_cal",
    allow_empty: bool = False,
) -> Optional[CalendarAction]:
    """Renderiza un cronograma editable como calendario semanal FullCalendar.

    Habilita drag & drop, resize, click en eventos y seleccion de rangos.
    Retorna un CalendarAction si el usuario interactuo, o None si no hubo accion.

    Usa eventos recurrentes (daysOfWeek). Los callbacks devuelven fechas
    concretas de la semana visible, que se parsean con weekday() para
    recuperar el dia de la semana.

    Args:
        allow_empty: Si True, renderiza la grilla vacía (para poder
            seleccionar rangos) en vez de mostrar un mensaje informativo.
    """
    if not grid_data and not allow_empty:
        st.info("El cronograma no tiene entradas.")
        return None

    mat_colors, mat_names = _assign_colors(grid_data)

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))
            events.append({
                "id": b.entry_id,
                "title": f"{b.materia_codigo} - {b.materia_nombre}",
                "daysOfWeek": [dow],
                "startTime": _fmt_time(b.hora_inicio),
                "endTime": _fmt_time(b.hora_fin),
                "backgroundColor": bg,
                "textColor": fg,
                "borderColor": bg,
                "extendedProps": {
                    "materia_codigo": b.materia_codigo,
                    "materia_nombre": b.materia_nombre,
                },
            })

    hidden_days = _compute_hidden_days(config)
    options = _build_calendar_options(config, hidden_days)
    options.update({
        "editable": True,
        "selectable": True,
        "unselectAuto": True,
        "eventStartEditable": True,
        "eventDurationEditable": True,
        "snapDuration": "00:15:00",
    })

    custom_css = """
        .fc-event { cursor: grab; }
        .fc-event:active { cursor: grabbing; }
        .fc-highlight { background: rgba(30, 136, 229, 0.15); }
    """

    # Leyenda arriba del calendario (referencia visual para edicion)
    _render_legend(mat_colors, mat_names)

    _inject_tab_fix(options["height"])
    result = calendar(
        events=events,
        options=options,
        custom_css=custom_css,
        callbacks=["eventClick", "eventChange", "select"],
        key=key,
    )

    if not result:
        return None

    # eventChange: drag & drop o resize
    if "eventChange" in result:
        evt = result["eventChange"].get("event", {})
        entry_id = evt.get("id")
        ext = evt.get("extendedProps", {})
        new_start = evt.get("start")
        new_end = evt.get("end")
        if entry_id and new_start and new_end:
            try:
                dia, hora_inicio = parse_callback_datetime(new_start)
                _, hora_fin = parse_callback_datetime(new_end)
                return CalendarAction(
                    action="move",
                    entry_id=entry_id,
                    materia_codigo=ext.get("materia_codigo"),
                    dia=dia,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
            except (ValueError, KeyError):
                pass

    # eventClick: click sobre un evento
    if "eventClick" in result:
        evt = result["eventClick"].get("event", {})
        entry_id = evt.get("id")
        ext = evt.get("extendedProps", {})
        start = evt.get("start")
        end = evt.get("end")
        if entry_id and start and end:
            try:
                dia, hora_inicio = parse_callback_datetime(start)
                _, hora_fin = parse_callback_datetime(end)
                return CalendarAction(
                    action="click",
                    entry_id=entry_id,
                    materia_codigo=ext.get("materia_codigo"),
                    dia=dia,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
            except (ValueError, KeyError):
                pass

    # select: seleccion de rango vacio
    if "select" in result:
        sel = result["select"]
        start = sel.get("start")
        end = sel.get("end")
        if start and end:
            try:
                dia, hora_inicio = parse_callback_datetime(start)
                _, hora_fin = parse_callback_datetime(end)
                return CalendarAction(
                    action="select",
                    dia=dia,
                    hora_inicio=hora_inicio,
                    hora_fin=hora_fin,
                )
            except (ValueError, KeyError):
                pass

    return None
