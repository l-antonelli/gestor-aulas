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

# Color fijo para "materias comunes" (compartidas por ≥2 carreras) cuando
# se colorea por carrera. No tienen una carrera única que las identifique,
# así que se las agrupa visualmente en un mismo color neutro.
COMUN_COLOR = ("#757575", TEXT_COLOR)
COMUN_LABEL = "Común (varias carreras)"

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
    comision: Optional[int] = None


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
        "timeZone": "UTC",
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


def _legend_por_comision(
    grid_data, com_colors: dict[int, tuple[str, str]],
) -> dict[str, tuple[str, str]]:
    """Etiquetas de la leyenda de comisiones.

    Prefiere el NOMBRE de la comisión (arbitrario, legible: "Mañana",
    "A", "1") con el número como fallback — fix auditoría H18,
    2026-09-23. `0` es el centinela "sin comisión asignada".
    """
    nombre_por_num: dict[int, str] = {}
    for blocks in grid_data.values():
        for b in blocks:
            _n = (
                getattr(b, "comision_numero", None)
                or getattr(b, "comision", None)
                or 0
            )
            if _n and not nombre_por_num.get(_n):
                _nom = getattr(b, "comision_nombre", None)
                if _nom:
                    nombre_por_num[_n] = str(_nom)
    return {
        (
            nombre_por_num.get(cn)
            or (f"C{cn}" if cn > 0 else "Sin asignar")
        ): color
        for cn, color in com_colors.items()
    }


def _render_legend(
    mat_colors: dict[str, tuple[str, str]],
    mat_names: dict[str, str],
    title: str = "Materias:",
) -> None:
    """Renderiza la leyenda de colores."""
    codes = sorted(mat_colors.keys())
    if not codes:
        return
    st.divider()
    st.markdown(f"**{title}**")
    n_cols = min(len(codes), 4) or 1
    legend_cols = st.columns(n_cols)
    for i, code in enumerate(codes):
        with legend_cols[i % n_cols]:
            bg, fg = mat_colors[code]
            nombre = mat_names.get(code, "")
            label = f"<b>{code}</b> — {nombre}" if nombre else f"<b>{code}</b>"
            st.markdown(
                f'<div style="background-color:{bg};color:{fg};'
                f'padding:2px 8px;border-radius:3px;margin-bottom:4px;'
                f'font-size:0.85em;">'
                f'{label}</div>',
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
    color_by_comision: bool = False,
) -> Optional[dict]:
    """Renderiza un cronograma como calendario semanal FullCalendar (read-only).

    Usa eventos recurrentes (daysOfWeek + startTime/endTime) para que se
    muestren en cualquier semana sin depender de una fecha fija.

    Args:
        color_by_comision: Si True, asigna colores por numero de comision
            en vez de por materia. Util cuando se filtra por una sola
            materia para distinguir comisiones.
    """
    if not grid_data:
        st.info("El cronograma no tiene entradas.")
        return None

    mat_colors, mat_names = _assign_colors(grid_data)

    # Fix auditoría H18 (2026-09-23): `ScheduleBlock` expone
    # `comision_numero` / `comision_nombre`, no `comision` — el
    # coloreo por comisión estaba muerto (todas caían al 0 y se
    # pintaban con el primer color de la paleta). Se mantiene
    # `comision` como fallback para blocks legacy.
    def _num_comision(b) -> int:
        return (
            getattr(b, "comision_numero", None)
            or getattr(b, "comision", None)
            or 0
        )

    _com_colors: dict[int, tuple[str, str]] = {}
    if color_by_comision:
        _com_nums = sorted({
            _num_comision(b)
            for blocks in grid_data.values() for b in blocks
        })
        _com_colors = {
            cn: (PALETTE[i % len(PALETTE)], TEXT_COLOR)
            for i, cn in enumerate(_com_nums)
        }

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            com = _num_comision(b) or None
            # Fase I.3 · Preferimos el NOMBRE de la comisión (arbitrario,
            # legible: "Mañana", "A", "Nocturno", "1") sobre el número.
            # El número queda como fallback si no hay nombre.
            _com_nombre = getattr(b, "comision_nombre", None)
            if _com_nombre:
                com_tag = f" [{_com_nombre}]"
            elif com:
                com_tag = f" [{com}]"
            else:
                com_tag = ""
            if color_by_comision:
                bg, fg = _com_colors.get(com or 0, (PALETTE[0], TEXT_COLOR))
            else:
                bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))
            events.append({
                "title": f"{b.materia_codigo}{com_tag} - {b.materia_nombre}",
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

    if color_by_comision:
        _com_legend_colors = _legend_por_comision(grid_data, _com_colors)
        _com_legend_names = {k: "" for k in _com_legend_colors}
        _render_legend(_com_legend_colors, _com_legend_names, title="Comisiones:")
    else:
        _render_legend(mat_colors, mat_names)

    return result


# ---------------------------------------------------------------------------
# Render para Planes / Grilla Horaria (TimetableBlock) — read-only
# ---------------------------------------------------------------------------
GRIS_ATENUADO = ("#3a3a3a", "#9a9a9a")


def render_timetable_calendar(
    grid_data: dict[str, list[TimetableBlock]],
    config: ConfiguracionHoraria,
    key: str = "timetable_cal",
    color_by_carrera: bool = False,
    dias_visibles: Optional[list[str]] = None,
    hora_min_override: Optional[time] = None,
    hora_max_override: Optional[time] = None,
    titulo_compacto: bool = False,
    resaltar_codigos: Optional[set[str]] = None,
    mostrar_leyenda: bool = True,
    mat_color_override: Optional[dict[str, tuple[str, str]]] = None,
    height_px: Optional[int] = None,
) -> Optional[dict]:
    """Renderiza un plan de cursada como calendario semanal FullCalendar (read-only).

    Similar a render_schedule_calendar pero con informacion de comision,
    indicadores de virtual y de periodo.

    Args:
        color_by_carrera: si True, los bloques se colorean por
            ``carrera_codigo`` (en vez de por materia, default). Util
            cuando se quiere ver visualmente "todos los horarios de una
            misma carrera son del mismo color" — por ejemplo en el
            inspector de franja para detectar bloques que NO se pueden
            mover entre si por ser de la misma carrera/cohorte.
            Bloques con carrera_codigo=None caen al color por materia.
        mat_color_override: mapping ``materia_codigo -> (bg, fg)``
            precomputado. Cuando se pasa, las materias listadas usan
            ese color exacto; el resto de las materias sigue la
            asignación automática. Sirve para mantener consistencia
            de color entre varios calendarios (ej. en el diálogo de
            cascada donde la misma materia aparece en varias aulas).
    """
    if not grid_data:
        st.info("No hay horarios para mostrar.")
        return None

    mat_colors, mat_names = _assign_colors(grid_data)
    if mat_color_override:
        mat_colors.update(mat_color_override)

    # Coloreo por carrera (opcional): mapping carrera_codigo -> color.
    # Los bloques sin carrera (materias comunes a ≥2 carreras) se colorean
    # con COMUN_COLOR y se agrupan bajo una sola entrada en la leyenda.
    car_colors: dict[str, tuple[str, str]] = {}
    car_names: dict[str, str] = {}
    hay_comunes = False
    if color_by_carrera:
        carreras = sorted({
            b.carrera_codigo
            for blocks in grid_data.values() for b in blocks
            if b.carrera_codigo
        })
        for i, c in enumerate(carreras):
            car_colors[c] = (PALETTE[i % len(PALETTE)], TEXT_COLOR)
        for blocks in grid_data.values():
            for b in blocks:
                if b.carrera_codigo and b.carrera_codigo not in car_names:
                    car_names[b.carrera_codigo] = (
                        b.carrera_label or b.carrera_codigo
                    )
                if not b.carrera_codigo:
                    hay_comunes = True

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            # Resaltado: si se pasó ``resaltar_codigos`` y la materia
            # del bloque NO está en el set, se pinta gris atenuado
            # (para dejar visualmente destacados sólo los relevantes).
            if (
                resaltar_codigos is not None
                and b.materia_codigo not in resaltar_codigos
            ):
                bg, fg = GRIS_ATENUADO
            elif color_by_carrera:
                if b.carrera_codigo and b.carrera_codigo in car_colors:
                    bg, fg = car_colors[b.carrera_codigo]
                else:
                    # Materia común a varias carreras: color neutro fijo.
                    bg, fg = COMUN_COLOR
            else:
                bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))

            v_tag = " 💻" if b.virtual else ""
            if titulo_compacto:
                # Modo compacto: solo código + comisión, una sola línea.
                # Pensado para vistas con muchos bloques solapados
                # (inspector de franja) donde el ancho de la columna
                # es chico y el detalle completo va en la tabla.
                title = (
                    f"{b.materia_codigo}{v_tag} · "
                    f"{b.comision_nombre}"
                )
            else:
                # Modo completo: materia (codigo + nombre), comision y
                # aula del patron. Fase I.3 del rediseño 2026-09-21:
                # emoji del **tipo predeterminado** (📖 teo / 🧪 lab)
                # explícito, para diferenciarlo del tipo derivado del
                # aula asignada por el LP (donde no ponemos icono
                # porque el aula al lado ya lo aclara).
                _tipo = getattr(b, "tipo_clase", None)
                _tipo_icon = ""
                if not b.virtual:
                    if _tipo == "teorica":
                        _tipo_icon = "📖"
                    elif _tipo == "laboratorio":
                        _tipo_icon = "🧪"
                if b.virtual:
                    aula_line = "💻 Virtual (no requiere aula)"
                    _prefix_icon = ""
                elif b.aula_label:
                    aula_line = b.aula_label
                    _prefix_icon = _tipo_icon or "🏛️"
                else:
                    aula_line = "Sin aula"
                    _prefix_icon = _tipo_icon or "📄"
                title = (
                    f"{b.materia_codigo}{v_tag} — {b.materia_nombre}\n"
                    f"{b.comision_nombre}\n"
                    f"{_prefix_icon} {aula_line}"
                )

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
    if dias_visibles is not None:
        # Restringir adicionalmente a los dias_visibles solicitados.
        # Domingo (0) siempre oculto; el resto, sólo los pedidos.
        visibles_dow = {
            DIA_TO_DOW[d] for d in dias_visibles if d in DIA_TO_DOW
        }
        hidden_days = [
            dow for dow in range(7) if dow not in visibles_dow
        ]
    options = _build_calendar_options(config, hidden_days)
    # Override del rango horario visible (independiente de la
    # ConfiguracionHoraria). Util para el inspector de franja, que
    # quiere acotar la vista a los horarios efectivamente mostrados.
    if hora_min_override is not None:
        options["slotMinTime"] = _fmt_time(hora_min_override)
    if hora_max_override is not None:
        options["slotMaxTime"] = _fmt_time(hora_max_override)
    # Override de altura (para vistas embebidas donde el default de
    # 650px es demasiado alto — ej. calendarios apilados en un
    # diálogo o inspector).
    if height_px is not None:
        options["height"] = height_px

    _inject_tab_fix(options["height"])
    result = calendar(
        events=events,
        options=options,
        callbacks=[],
        key=key,
    )

    if mostrar_leyenda:
        if color_by_carrera and (car_colors or hay_comunes):
            legend_colors = dict(car_colors)
            legend_names = dict(car_names)
            if hay_comunes:
                # Usamos el label como "código" para que la leyenda quede
                # legible (no muestra "__comun__ — ...").
                legend_colors[COMUN_LABEL] = COMUN_COLOR
                legend_names[COMUN_LABEL] = ""
            _render_legend(legend_colors, legend_names, title="Carreras:")
        else:
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
    color_by_comision: bool = False,
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

    # Color by comision: assign colors per comision number instead of materia
    # Fix auditoría H18 (2026-09-23): `ScheduleBlock` expone
    # `comision_numero`, no `comision` — ver comentario homólogo en
    # `render_schedule_calendar`.
    def _num_comision(b) -> int:
        return (
            getattr(b, "comision_numero", None)
            or getattr(b, "comision", None)
            or 0
        )

    _com_colors: dict[int, tuple[str, str]] = {}
    if color_by_comision:
        _com_nums = sorted({
            _num_comision(b)
            for blocks in grid_data.values() for b in blocks
        })
        _com_colors = {
            cn: (PALETTE[i % len(PALETTE)], TEXT_COLOR)
            for i, cn in enumerate(_com_nums)
        }

    events = []
    for dia, blocks in grid_data.items():
        dow = DIA_TO_DOW.get(dia)
        if dow is None:
            continue
        for b in blocks:
            com = _num_comision(b) or None
            # Fase I.3 · Nombre de la comisión como etiqueta primaria.
            # Fallback al número si no hay nombre (compat con blocks
            # históricos que no populan `comision_nombre`).
            _com_nombre = getattr(b, "comision_nombre", None)
            if _com_nombre:
                com_tag = f" [{_com_nombre}]"
            elif com:
                com_tag = f" [{com}]"
            else:
                com_tag = ""
            if color_by_comision:
                bg, fg = _com_colors.get(com or 0, (PALETTE[0], TEXT_COLOR))
            else:
                bg, fg = mat_colors.get(b.materia_codigo, (PALETTE[0], TEXT_COLOR))

            # Fase I.3 · Iconos del bloque:
            #   💻 → horario virtual (sin aula).
            #   📖 → teórica **predeterminada** por el usuario.
            #   🧪 → laboratorio **predeterminado** por el usuario.
            #   📄 → "automático" pero SIN aula asignada aún (el LP
            #        todavía no corrió sobre este horario).
            #   Sin icono de tipo → el tipo se deriva del aula
            #        asignada por el LP (el aula al lado ya lo aclara).
            # Notación distinta entre tipo predeterminado (📖/🧪) y
            # tipo derivado del aula post-LP (sin icono explícito):
            # así el usuario puede distinguir "esto lo dijo la
            # cátedra" de "esto lo puso el LP".
            #
            # Bugfix (2026-09-22, task #346): antes cuando había tipo
            # predeterminado + aula asignada se mostraba `📖 🏛️ Aula 42`
            # (dos iconos consecutivos). El icono del tipo ya dice
            # "clase teórica/lab"; el 🏛️ frente al aula es redundante
            # y visualmente ruidoso. Regla nueva: si hay tipo
            # predeterminado (📖/🧪), NO se antepone 🏛️ al aula; el
            # 🏛️ sólo aparece cuando el tipo se deriva por el LP.
            _virtual = getattr(b, "virtual", False)
            _tipo = getattr(b, "tipo_clase", None)
            _aula_label = getattr(b, "aula_label", None)
            _tipo_icon = ""
            if _virtual:
                aula_txt = "💻 Virtual"
            else:
                if _tipo == "teorica":
                    _tipo_icon = "📖"
                elif _tipo == "laboratorio":
                    _tipo_icon = "🧪"
                elif _aula_label is None and hasattr(b, "aula_label"):
                    # Block del plan sin tipo predeterminado y sin
                    # aula asignada — señal de "por asignar".
                    _tipo_icon = "📄"
                # Si tipo=None Y hay aula, no ponemos icono explícito:
                # el aula (o el AulaDB.tipo si se propaga) desambigua.

                if _aula_label:
                    # Sin tipo predeterminado → prefijamos 🏛️. Con
                    # tipo predeterminado → el 📖/🧪 va aparte, así
                    # que el aula queda "pelada" (sin icono adicional).
                    aula_txt = (
                        _aula_label if _tipo_icon
                        else f"🏛️ {_aula_label}"
                    )
                elif hasattr(b, "aula_label"):
                    aula_txt = "Sin aula"
                else:
                    aula_txt = ""

            # Título en tres líneas:
            #   1) código de materia [nombre_comision]  · (badge de carreras si aplica)
            #   2) nombre de la materia
            #   3) icono de tipo + aula (o "💻 Virtual" cuando aplica)
            _carreras = getattr(b, "carreras_label", None)
            # Para no saturar la línea 1, sólo agregamos el badge de
            # carreras cuando es una materia COMÚN (>=2 carreras).
            if _carreras and _carreras.startswith("Común"):
                linea1 = f"{b.materia_codigo}{com_tag} · {_carreras}"
            else:
                linea1 = f"{b.materia_codigo}{com_tag}"
            linea2 = b.materia_nombre
            # Prefijamos el icono del tipo al texto del aula. Si el
            # tipo se derivará del aula por el LP, no hay icono → la
            # línea empieza directamente con el aula.
            _l3_parts = [p for p in (_tipo_icon, aula_txt) if p]
            linea3 = " ".join(_l3_parts) if _l3_parts else ""
            title = "\n".join(
                part for part in (linea1, linea2, linea3) if part
            )
            events.append({
                "id": b.entry_id,
                "title": title,
                "daysOfWeek": [dow],
                "startTime": _fmt_time(b.hora_inicio),
                "endTime": _fmt_time(b.hora_fin),
                "backgroundColor": bg,
                "textColor": fg,
                "borderColor": bg,
                "extendedProps": {
                    "materia_codigo": b.materia_codigo,
                    "materia_nombre": b.materia_nombre,
                    "comision": com,
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
        /* Preservar los saltos de línea del título (3 filas:
           código+comisión, nombre, aula+modalidad). Sin esto el
           `\\n` se colapsa como espacio y todo queda en una fila. */
        .fc-event-title,
        .fc-event-title-container { white-space: pre-line !important; }
    """

    # Leyenda arriba del calendario (referencia visual para edicion)
    if color_by_comision:
        _com_legend_colors = _legend_por_comision(grid_data, _com_colors)
        _com_legend_names = {k: "" for k in _com_legend_colors}
        _render_legend(_com_legend_colors, _com_legend_names, title="Comisiones:")
    else:
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
                    comision=ext.get("comision"),
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
