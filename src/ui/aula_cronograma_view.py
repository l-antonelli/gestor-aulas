"""Vista de cronograma semanal por aula.

Permite seleccionar un aula y ver todas las clases que tiene asignadas
en una semana específica del ciclo. Útil para detectar choques residuales
después de ediciones manuales y para inspeccionar la carga de un aula.

Implementa el indicador de divergencia: cuando una misma franja semanal
del aula es ocupada por distintos horarios en distintas semanas (porque
hubo ediciones manuales puntuales), se muestra cuántas semanas usan el
patrón actual vs. cuántas tienen variaciones.
"""

from __future__ import annotations

from typing import Optional

import streamlit as st
from sqlmodel import Session, select

from src.database.crud import get_or_create_config
from src.database.models import (
    AulaDB,
    CicloDB,
    ComisionDB,
    MateriaDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.plan_generation_service import TimetableBlock
from src.ui.calendar_render import render_timetable_calendar


def _sede_nombre_map(session: Session) -> dict[str, str]:
    """Devuelve {sede_id: nombre} para todas las sedes existentes."""
    return {s.id: s.nombre for s in session.exec(select(SedeDB)).all()}



DOW_NAMES = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]


def _build_plan_estudio_cache(
    session: Session, materia_codigos: set[str],
) -> dict[str, list[tuple[str, str, int | None, str | None]]]:
    """Pre-carga PlanEstudioDB para no consultar N veces.

    Devuelve ``materia_codigo -> [(carrera_codigo, carrera_nombre,
    anio_plan, cuatrimestre_plan)]``. Una materia puede aparecer en
    varias carreras (compartida).
    """
    from src.database.models import CarreraDB, PlanEstudioDB
    if not materia_codigos:
        return {}
    pe_rows = list(session.exec(
        select(PlanEstudioDB).where(
            PlanEstudioDB.materia_codigo.in_(materia_codigos)  # type: ignore[attr-defined]
        )
    ).all())
    carreras_codigos_usadas = {pe.carrera_codigo for pe in pe_rows}
    carreras_db = list(session.exec(
        select(CarreraDB).where(
            CarreraDB.codigo.in_(carreras_codigos_usadas)  # type: ignore[attr-defined]
        )
    ).all()) if carreras_codigos_usadas else []
    car_map = {c.codigo: c.nombre for c in carreras_db}
    rows = [(pe, car_map.get(pe.carrera_codigo, pe.carrera_codigo)) for pe in pe_rows]
    out: dict[str, list[tuple[str, str, int | None, str | None]]] = {}
    seen_per_materia: dict[str, set[tuple[str, int | None, str | None]]] = {}
    for pe, carrera_nombre in rows:
        key = (pe.carrera_codigo, pe.anio_plan, pe.cuatrimestre_plan)
        if pe.materia_codigo not in seen_per_materia:
            seen_per_materia[pe.materia_codigo] = set()
        if key in seen_per_materia[pe.materia_codigo]:
            continue
        seen_per_materia[pe.materia_codigo].add(key)
        out.setdefault(pe.materia_codigo, []).append(
            (pe.carrera_codigo, carrera_nombre, pe.anio_plan, pe.cuatrimestre_plan)
        )
    return out


def _carreras_para_clase(
    materia_codigo: str,
    cache: dict[str, list[tuple[str, str, int | None, str | None]]],
) -> dict:
    """Resume las carreras / años / cuatris de una materia para filtrar
    y mostrar."""
    entries = cache.get(materia_codigo, [])
    if not entries:
        return {
            "carreras_codigos": set(),
            "carreras_nombres": [],
            "anios": set(),
            "cuatris": set(),
            "label": "—",
        }
    carreras_codigos = {e[0] for e in entries}
    carreras_nombres = sorted({e[1] for e in entries})
    anios = {e[2] for e in entries if e[2] is not None}
    cuatris = {e[3] for e in entries if e[3] is not None}
    label = ", ".join(carreras_nombres)
    return {
        "carreras_codigos": carreras_codigos,
        "carreras_nombres": carreras_nombres,
        "anios": anios,
        "cuatris": cuatris,
        "label": label,
    }



_DEFAULT_FILTROS: dict = {
    "aula_id": None,
    "sedes": [],
    "carreras": [],
    "anios": [],
    "cuatris": [],
    "tipos": [],
    "dias": [],
    "comunes_mode": "Todas",
    "sin_aula": False,
    "buscar": "",
    "mostrar_cronograma": False,
}

_COMUNES_OPTS = ["Todas", "Sólo comunes", "Sólo exclusivas"]


def _build_filtros_panel(
    key_ns: str,
    plan_estudio_cache: dict,
    sede_map: dict[str, str],
    aulas_con_clases: list[AulaDB],
) -> dict:
    """Renderiza el panel de filtros como un ``st.form`` con submit
    explícito. Sólo se aplican los filtros al apretar "Aplicar".

    El filtro **Sede** se procesa antes que **Aula** y restringe en
    cascada las aulas disponibles en el selector. Esto evita scrollear
    entre sedes cuando se busca una aula específica.

    Estado:
        - ``{key_ns}_filtros_aplicados``: dict con los filtros vigentes
          (lo que la tabla y el cronograma realmente usan). Default
          ``_DEFAULT_FILTROS``.
        - ``{key_ns}_form_*``: campos del form (se persisten entre
          reruns y se aplican al submit).

    Devuelve los filtros aplicados (dict).
    """
    state_key = f"{key_ns}_filtros_aplicados"
    if state_key not in st.session_state:
        st.session_state[state_key] = dict(_DEFAULT_FILTROS)
    aplicados: dict = st.session_state[state_key]

    # Opciones agregadas.
    todas_carreras: dict[str, str] = {}
    todos_anios: set[int] = set()
    todos_cuatris: set[str] = set()
    for entries in plan_estudio_cache.values():
        for codigo, nombre, anio, cuatri in entries:
            todas_carreras[codigo] = nombre
            if anio is not None:
                todos_anios.add(anio)
            if cuatri is not None:
                todos_cuatris.add(cuatri)
    carrera_opts_codes = sorted(
        todas_carreras.keys(), key=lambda c: todas_carreras[c],
    )
    anio_opts = sorted(todos_anios)
    cuatri_opts = sorted(todos_cuatris)
    sede_opts = sorted({
        sede_map.get(a.sede_id, "")
        for a in aulas_con_clases
        if sede_map.get(a.sede_id)
    })

    # El selector de aulas se reduce dinámicamente a la sede pendiente
    # (elegida en el form pero todavía no aplicada) — esto se hace
    # FUERA del form para que el cambio de sede gatille un rerun
    # inmediato y refresque la lista de aulas. Mantenemos el control
    # de "Aplicar" sólo para los filtros que afectan el resultado.
    sede_pendiente_key = f"{key_ns}_form_sedes"
    sedes_pendientes: list[str] = st.session_state.get(
        sede_pendiente_key, aplicados.get("sedes", []),
    )
    if sedes_pendientes:
        aulas_filtradas = [
            a for a in aulas_con_clases
            if sede_map.get(a.sede_id, "") in sedes_pendientes
        ]
    else:
        aulas_filtradas = list(aulas_con_clases)

    aula_opts = {
        a.id: (
            f"{sede_map.get(a.sede_id, '?')} · {a.nombre} "
            f"(cap. {a.capacidad}, {a.tipo})"
        )
        for a in aulas_filtradas
    }
    aula_id_options = ["__ALL__"] + list(aula_opts.keys())

    with st.expander("🎛️ Filtros", expanded=True):
        # ── Sede primero (afecta opciones de Aula en cascada).
        st.multiselect(
            "Sede del aula",
            options=sede_opts,
            default=aplicados.get("sedes", []),
            key=sede_pendiente_key,
            help=(
                "Si seleccionás una o más sedes, el selector de aulas "
                "de abajo queda restringido a esas sedes."
            ),
        )

        with st.form(key=f"{key_ns}_filtros_form", clear_on_submit=False):
            # Si la aula previamente aplicada ya no está disponible
            # (porque cambió la sede), reseteamos el default.
            aula_actual = aplicados.get("aula_id")
            if aula_actual not in aula_opts:
                aula_actual = None
            aula_default_idx = (
                aula_id_options.index(aula_actual)
                if aula_actual in aula_id_options else 0
            )
            sel_aula_id = st.selectbox(
                "Aula",
                options=aula_id_options,
                index=aula_default_idx,
                format_func=lambda x: (
                    "— Todas —" if x == "__ALL__" else aula_opts[x]
                ),
                key=f"{key_ns}_form_aula",
                help=(
                    "Si seleccionás un aula puntual, las métricas de "
                    "divergencia se restringen a esa aula. Si activás "
                    "'Mostrar cronograma' abajo, el calendario se ve "
                    "tanto con aula puntual como sin ella."
                ),
            )

            r2c1, r2c2, r2c3 = st.columns(3)
            with r2c1:
                sel_carreras = st.multiselect(
                    "Carrera",
                    options=carrera_opts_codes,
                    default=aplicados.get("carreras", []),
                    format_func=lambda c: f"{c} · {todas_carreras.get(c, c)}",
                    key=f"{key_ns}_form_carreras",
                )
            with r2c2:
                sel_anios = st.multiselect(
                    "Año del plan",
                    options=anio_opts,
                    default=aplicados.get("anios", []),
                    format_func=lambda a: f"{a}°",
                    key=f"{key_ns}_form_anios",
                )
            with r2c3:
                sel_cuatris = st.multiselect(
                    "Cuatrimestre del plan",
                    options=cuatri_opts,
                    default=aplicados.get("cuatris", []),
                    key=f"{key_ns}_form_cuatris",
                )

            r3c1, r3c2, r3c3 = st.columns(3)
            with r3c1:
                sel_tipos = st.multiselect(
                    "Tipo de clase",
                    options=["teorica", "laboratorio", "sin determinar"],
                    default=aplicados.get("tipos", []),
                    key=f"{key_ns}_form_tipos",
                )
            with r3c2:
                sel_dias = st.multiselect(
                    "Día de la semana",
                    options=DOW_NAMES,
                    default=aplicados.get("dias", []),
                    key=f"{key_ns}_form_dias",
                )
            with r3c3:
                comunes_default = aplicados.get("comunes_mode", "Todas")
                sel_comunes = st.selectbox(
                    "Compartidas entre carreras",
                    options=_COMUNES_OPTS,
                    index=(
                        _COMUNES_OPTS.index(comunes_default)
                        if comunes_default in _COMUNES_OPTS else 0
                    ),
                    key=f"{key_ns}_form_comunes",
                    help=(
                        "Comunes = materias que aparecen en más de "
                        "una carrera. Si además filtraste por carreras, "
                        "se interseca: comunes que pertenezcan a "
                        "alguna de las elegidas."
                    ),
                )

            sel_buscar = st.text_input(
                "Buscar materia (código o nombre)",
                value=aplicados.get("buscar", ""),
                key=f"{key_ns}_form_buscar",
                placeholder="Ej: '5.3' o 'Práctica Profesional'",
            )

            r4c1, r4c2, r4c3, r4c4 = st.columns([1, 1, 1, 1])
            with r4c1:
                sel_sin_aula = st.checkbox(
                    "Sólo sin asignar",
                    value=aplicados.get("sin_aula", False),
                    key=f"{key_ns}_form_sin_aula",
                    help=(
                        "Mostrar sólo los horarios que no tienen aula "
                        "del patrón asignada todavía."
                    ),
                )
            with r4c2:
                sel_mostrar_crono = st.checkbox(
                    "Mostrar cronograma",
                    value=aplicados.get("mostrar_cronograma", False),
                    key=f"{key_ns}_form_mostrar_crono",
                    help=(
                        "Renderiza el calendario consolidado del "
                        "esquema semanal con los horarios filtrados."
                    ),
                )
            with r4c3:
                aplicar = st.form_submit_button(
                    "✅ Aplicar filtros", type="primary",
                )
            with r4c4:
                limpiar = st.form_submit_button(
                    "🔄 Limpiar",
                )

        if limpiar:
            st.session_state[state_key] = dict(_DEFAULT_FILTROS)
            # Reseteo también los campos del form para que la próxima
            # render arranque limpio.
            for suf in (
                "_form_aula", "_form_sedes", "_form_carreras",
                "_form_anios", "_form_cuatris", "_form_tipos",
                "_form_dias", "_form_comunes", "_form_buscar",
                "_form_sin_aula", "_form_mostrar_crono",
            ):
                st.session_state.pop(f"{key_ns}{suf}", None)
            st.rerun()

        if aplicar:
            st.session_state[state_key] = {
                "aula_id": (
                    None if sel_aula_id == "__ALL__" else sel_aula_id
                ),
                "sedes": list(
                    st.session_state.get(sede_pendiente_key, [])
                ),
                "carreras": list(sel_carreras),
                "anios": list(sel_anios),
                "cuatris": list(sel_cuatris),
                "tipos": list(sel_tipos),
                "dias": list(sel_dias),
                "comunes_mode": sel_comunes,
                "sin_aula": bool(sel_sin_aula),
                "buscar": sel_buscar or "",
                "mostrar_cronograma": bool(sel_mostrar_crono),
            }
            st.rerun()

    return st.session_state[state_key]


def _build_horario_rows_v2(
    horarios_db: list,
    com_map: dict[str, ComisionDB],
    mat_map: dict[str, MateriaDB],
    aula_map: dict[str, AulaDB],
    plan_estudio_cache: dict,
    *,
    dictado_virtual_por_materia: dict[str, bool | None] | None = None,
) -> list[dict]:
    """Arma una fila por ``HorarioDB`` leyendo directamente
    ``HorarioDB.aula_id`` (el patrón persistido). NO infiere por
    mayoría sobre ``ClaseDB``; las excepciones puntuales no se ven en
    esta vista (van en otra pestaña).

    Cada fila tiene:
      - id, día, hora_inicio, hora_fin, tipo_clase del horario.
      - aula del patrón (objeto AulaDB o None).
      - info derivada de la materia (carreras, año, cuatri, etc.).
      - `es_virtual`: bool resuelto via jerarquia horario > dictado >
        materia (para diferenciar "no tiene aula porque el LP no
        corrio" de "no tiene aula porque es virtual").
    """
    from src.services.resolucion_jerarquica import resolve_virtual
    _dv = dictado_virtual_por_materia or {}
    rows: list[dict] = []
    for h in horarios_db:
        com = com_map.get(h.comision_id)
        mat_codigo = com.materia_codigo if com else (h.codigo_materia or "")
        mat = mat_map.get(mat_codigo) if mat_codigo else None
        carr_info = _carreras_para_clase(mat_codigo, plan_estudio_cache)
        es_virtual = resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=_dv.get(mat_codigo),
            materia_virtual=(mat.virtual if mat else False),
        )
        rows.append({
            "horario_id": h.id,
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "comision_id": h.comision_id,
            "comision_nombre": com.nombre if com else "?",
            "materia_codigo": mat_codigo,
            "materia_nombre": mat.nombre if mat else mat_codigo,
            "tipo_clase": h.tipo_clase,
            "aula_id": h.aula_id,
            "aula_obj": aula_map.get(h.aula_id) if h.aula_id else None,
            "es_virtual": es_virtual,
            **carr_info,
        })
    dia_idx = {d: i for i, d in enumerate(DOW_NAMES)}
    rows.sort(key=lambda r: (
        dia_idx.get(r["dia"], 99),
        r["hora_inicio"],
        r["materia_nombre"],
    ))
    return rows


def _aplicar_filtros_horarios_v2(
    rows: list[dict], filtros: dict, sede_map: dict[str, str],
) -> list[dict]:
    """Filtra filas-por-horario según el dict de filtros del panel."""
    f_carreras: set[str] = set(filtros.get("carreras") or [])
    f_anios: set[int] = set(filtros.get("anios") or [])
    f_cuatris: set[str] = set(filtros.get("cuatris") or [])
    f_tipos: set[str] = set(filtros.get("tipos") or [])
    f_dias: set[str] = set(filtros.get("dias") or [])
    f_sedes: set[str] = set(filtros.get("sedes") or [])
    f_busca: str = (filtros.get("buscar") or "").strip().lower()
    f_aula: str | None = filtros.get("aula_id")
    f_comunes_mode: str = filtros.get("comunes_mode") or "Todas"
    f_sin_aula: bool = bool(filtros.get("sin_aula"))

    out: list[dict] = []
    for r in rows:
        carr_codes: set[str] = r.get("carreras_codigos", set())
        if f_aula and r.get("aula_id") != f_aula:
            continue
        if f_sin_aula and r.get("aula_id") is not None:
            continue
        if f_carreras and not (carr_codes & f_carreras):
            continue
        if f_comunes_mode == "Sólo comunes":
            if len(carr_codes) < 2:
                continue
        elif f_comunes_mode == "Sólo exclusivas":
            if len(carr_codes) != 1:
                continue
        if f_anios and not (r.get("anios", set()) & f_anios):
            continue
        if f_cuatris and not (r.get("cuatris", set()) & f_cuatris):
            continue
        if f_tipos:
            tipo_label = r.get("tipo_clase") or "sin determinar"
            if tipo_label not in f_tipos:
                continue
        if f_dias and r.get("dia") not in f_dias:
            continue
        if f_sedes:
            aula = r.get("aula_obj")
            sede_id = aula.sede_id if aula else None
            sede_nombre = sede_map.get(sede_id, "") if sede_id else ""
            if sede_nombre not in f_sedes:
                continue
        if f_busca:
            mat_codigo = r.get("materia_codigo", "") or ""
            mat_nombre = r.get("materia_nombre", "") or ""
            if (
                f_busca not in mat_codigo.lower()
                and f_busca not in mat_nombre.lower()
            ):
                continue
        out.append(r)
    return out


def _build_grid_from_rows(
    rows: list[dict],
    sede_map: dict[str, str] | None = None,
) -> dict[str, list[TimetableBlock]]:
    """Construye el grid tipo ``TimetableBlock`` a partir de filas
    agrupadas por horario (esquema semanal). Sirve para el calendario
    consolidado del cronograma. Incluye la etiqueta del aula del
    patrón para que se vea adentro del bloque del calendario.
    """
    sede_map = sede_map or {}
    grid: dict[str, list[TimetableBlock]] = {}
    for r in rows:
        if r["dia"] not in DOW_NAMES:
            continue
        aula = r.get("aula_obj")
        if aula is not None:
            sede_nombre = sede_map.get(aula.sede_id, "?")
            aula_label = f"{sede_nombre} · {aula.nombre}"
        else:
            aula_label = None
        block = TimetableBlock(
            materia_codigo=r["materia_codigo"],
            materia_nombre=r["materia_nombre"],
            comision_nombre=r["comision_nombre"],
            hora_inicio=r["hora_inicio"],
            hora_fin=r["hora_fin"],
            virtual=False,
            en_periodo=True,
            aula_label=aula_label,
        )
        grid.setdefault(r["dia"], []).append(block)
    return grid


@st.dialog("Editar aula del horario")
def _dialog_cambiar_aula_horario(plan_id: str, horario_id: str) -> None:
    """Diálogo para cambiar el aula del PATRÓN (HorarioDB.aula_id).

    Modos:
    - Ver solo libres: muestra aulas compatibles sin ocupación en la
      franja. Comportamiento clásico.
    - Ver todas: incluye aulas ocupadas. Al elegir una ocupada, ofrece
      resolver el conflicto con el desplazado (swap, reasignar a otra
      libre, o dejar sin aula).

    Los cambios se propagan a las ClaseDB que heredan (no a las que
    tienen excepción manual).
    """
    from src.database.connection import get_session
    from src.database.models import HorarioDB
    from src.services.asignacion_aulas_service import (
        get_aulas_disponibles_para_horario,
    )

    with next(get_session()) as session:
        horario = session.get(HorarioDB, horario_id)
        if horario is None:
            st.error("Horario no encontrado.")
            return
        com = session.get(ComisionDB, horario.comision_id)
        mat_codigo = com.materia_codigo if com else "?"
        mat = session.get(MateriaDB, mat_codigo) if mat_codigo != "?" else None

        st.markdown(
            f"**Materia:** {mat.nombre if mat else mat_codigo}  \n"
            f"**Comisión:** {com.nombre if com else '?'}  \n"
            f"**Día/Hora:** {horario.dia} "
            f"{horario.hora_inicio.strftime('%H:%M')}–"
            f"{horario.hora_fin.strftime('%H:%M')}  \n"
            f"**Tipo actual:** {horario.tipo_clase or 'sin determinar'}"
        )
        if horario.aula_id:
            aula_actual = session.get(AulaDB, horario.aula_id)
            if aula_actual:
                sede_actual = session.get(SedeDB, aula_actual.sede_id)
                sede_nombre = sede_actual.nombre if sede_actual else "?"
                st.caption(
                    f"Aula actual: **{sede_nombre} · "
                    f"{aula_actual.nombre}** (cap. {aula_actual.capacidad})"
                )
        else:
            st.caption("Aula actual: **sin asignar**")

        st.info(
            "El cambio afecta a todo el horario: todas las clases de "
            "ese horario semanal heredarán la nueva aula."
        )

        # Tipo de clase del patrón.
        tipo_actual = horario.tipo_clase if horario.tipo_clase in (
            "teorica", "laboratorio"
        ) else "teorica"
        nuevo_tipo = st.selectbox(
            "Tipo de clase",
            options=["teorica", "laboratorio"],
            index=["teorica", "laboratorio"].index(tipo_actual),
            key=f"dlg_h_tipo_{horario_id}",
        )
        cambiando_tipo = (
            horario.tipo_clase is not None and nuevo_tipo != horario.tipo_clase
        )

        # =================================================================
        # Selector de vista: sólo libres vs. todas las aulas
        # =================================================================
        vista = st.radio(
            "Aulas a mostrar",
            options=["libres", "todas"],
            format_func=lambda v: (
                "Sólo aulas libres en esta franja"
                if v == "libres"
                else "Todas las aulas (incluidas las ocupadas)"
            ),
            index=0,
            key=f"dlg_h_vista_{horario_id}",
            horizontal=True,
        )

        sede_map = _sede_nombre_map(session)

        if vista == "libres":
            aulas_disp = get_aulas_disponibles_para_horario(
                session, plan_id, horario_id,
                tipo_objetivo=(nuevo_tipo if cambiando_tipo else None),
            )
            if not aulas_disp:
                st.warning(
                    "No hay aulas compatibles libres en esa franja "
                    "semanal. Cambiá a **Todas las aulas** para elegir "
                    "una ocupada y resolver el conflicto, o cambiá el "
                    "tipo de clase."
                )
                _render_boton_cancelar(horario_id)
                return

            opciones = ["__NONE__"] + [a.id for a in aulas_disp]
            labels = {
                "__NONE__": "— Sin asignar —",
                **{
                    a.id: (
                        f"{sede_map.get(a.sede_id, '?')} · {a.nombre} "
                        f"(cap. {a.capacidad}, {a.tipo})"
                    )
                    for a in aulas_disp
                },
            }
            default_idx = 0
            if horario.aula_id and horario.aula_id in [a.id for a in aulas_disp]:
                default_idx = opciones.index(horario.aula_id)
            sel_aula = st.selectbox(
                "Aula asignada",
                options=opciones,
                index=default_idx,
                format_func=lambda x: labels[x],
                key=f"dlg_h_aula_{horario_id}",
            )

            _render_confirmar_libre(
                session, plan_id, horario_id, sel_aula,
                nuevo_tipo if cambiando_tipo else None,
            )
            return

        # ---------------------------------------------------------------
        # Vista: TODAS las aulas — con soporte de cascada de desplazamientos
        # ---------------------------------------------------------------
        _render_flujo_cascada(
            session, plan_id, horario_id, sede_map,
            nuevo_tipo if cambiando_tipo else None,
        )


def _render_boton_cancelar(horario_id: str) -> None:
    """Botón Cancelar para las ramas de salida temprana del dialog."""
    if st.button("Cancelar", key=f"dlg_h_cancel_only_{horario_id}"):
        # Limpiar cualquier estado de cascada acumulado.
        _limpiar_estado_cascada(horario_id)
        st.rerun()


# =============================================================================
# Flujo de cascada de reasignación (UI recursiva)
# =============================================================================
#
# La cascada se persiste en st.session_state bajo la key
# `_STATE_KEY_PREFIX + <root_horario_id>`. Es un dict que representa un
# NodoCascada (lo mismo pero como dict serializable), con las
# decisiones tomadas por el usuario nivel por nivel.
#
# La estructura:
# {
#   "horario_id": "H1",
#   "aula_elegida": "A2",              # o None
#   "accion": "reassign",              # libre/swap/reassign/sin_aula
#   "hijos": {                         # dict indexado por horario_id
#     "H2": {                          # decisión para el desplazado H2
#       "horario_id": "H2",
#       "aula_elegida": "A5",
#       "accion": "reassign",
#       "hijos": {...}                 # recursivo
#     },
#     "H3": {...}                      # otro desplazado
#   }
# }
#
# Cuando el usuario cambia una decisión, cualquier subárbol que ya no
# corresponda se debe podar. `_actualizar_decision` maneja eso.


_STATE_KEY_PREFIX = "reasig_cascada_"


def _get_state(root_horario_id: str) -> dict:
    """Devuelve (creando si no existe) el árbol de decisiones para la
    raíz. Formato: ver comentario de bloque arriba."""
    key = _STATE_KEY_PREFIX + root_horario_id
    if key not in st.session_state:
        st.session_state[key] = {
            "horario_id": root_horario_id,
            "aula_elegida": None,
            "accion": "libre",
            "hijos": {},
        }
    return st.session_state[key]


def _limpiar_estado_cascada(root_horario_id: str) -> None:
    """Elimina el árbol de decisiones del session_state (al cerrar
    diálogo o cancelar)."""
    key = _STATE_KEY_PREFIX + root_horario_id
    if key in st.session_state:
        del st.session_state[key]
    # Además, limpiar keys de widgets internos del árbol (heurística:
    # cualquier key que empiece con "dlg_casc_<root>").
    prefix = f"dlg_casc_{root_horario_id}_"
    to_del = [k for k in st.session_state if k.startswith(prefix)]
    for k in to_del:
        del st.session_state[k]


def _nodo_hijo(padre_dict: dict, horario_id: str) -> dict:
    """Obtiene (o crea con defaults) el nodo hijo de ``padre_dict``
    para ``horario_id``. Default: 'sin_aula' hasta que el usuario elija."""
    if horario_id not in padre_dict["hijos"]:
        padre_dict["hijos"][horario_id] = {
            "horario_id": horario_id,
            "aula_elegida": None,
            "accion": "sin_aula",
            "hijos": {},
        }
    return padre_dict["hijos"][horario_id]


def _podar_hijos_no_afectados(
    session, plan_id: str, nodo_dict: dict,
) -> None:
    """Si el nodo cambió de aula, poda los hijos que ya no son
    afectados por la nueva decisión."""
    from src.services.asignacion_aulas_service import get_horarios_afectados
    if nodo_dict["aula_elegida"] is None:
        # Sin aula → no hay hijos.
        nodo_dict["hijos"] = {}
        return
    afectados = get_horarios_afectados(
        session, plan_id, nodo_dict["horario_id"], nodo_dict["aula_elegida"],
    )
    afectados_ids = {h.id for h in afectados}
    # Preservar sólo los hijos que corresponden a horarios afectados
    # por la aula elegida actual.
    nodo_dict["hijos"] = {
        hid: h for hid, h in nodo_dict["hijos"].items()
        if hid in afectados_ids
    }


def _dict_a_nodo_cascada(nodo_dict: dict):
    """Convierte el dict del session_state en un NodoCascada real
    (para pasar al servicio de validación/aplicación)."""
    from src.services.asignacion_aulas_service import NodoCascada
    return NodoCascada(
        horario_id=nodo_dict["horario_id"],
        aula_elegida=nodo_dict["aula_elegida"],
        accion=nodo_dict["accion"],
        hijos=[
            _dict_a_nodo_cascada(h)
            for h in nodo_dict["hijos"].values()
        ],
    )


def _render_flujo_cascada(
    session,
    plan_id: str,
    root_horario_id: str,
    sede_map: dict,
    nuevo_tipo: str | None,
) -> None:
    """Renderiza el flujo de vista 'Todas las aulas' con soporte de
    cascada. La raíz es siempre ``root_horario_id`` (el horario que el
    usuario abrió el diálogo para editar).

    Sub-diseño:
    - Selector de aula al tope (todas las aulas compatibles).
    - Si se elige un aula libre o "sin asignar" → confirmar directo.
    - Si se elige un aula con ocupantes → renderiza recursivamente un
      bloque por cada ocupante con sus propias opciones.
    - Preview global al pie con validaciones cruzadas.
    """
    from src.database.models import HorarioDB
    from src.services.asignacion_aulas_service import (
        get_aulas_todas_para_horario,
    )

    horario_root = session.get(HorarioDB, root_horario_id)
    if horario_root is None:
        st.error("Horario no encontrado.")
        return

    estado = _get_state(root_horario_id)

    # === Selector de aula del nodo raíz ===
    candidatas = get_aulas_todas_para_horario(
        session, plan_id, root_horario_id,
        tipo_objetivo=nuevo_tipo,
    )
    if not candidatas:
        st.warning(
            "No hay aulas compatibles con este horario "
            "(considerá cambiar el tipo)."
        )
        _render_boton_cancelar(root_horario_id)
        return

    aula_elegida = _render_selector_aula(
        session, sede_map, candidatas,
        estado_actual=estado["aula_elegida"],
        aula_original=horario_root.aula_id,
        widget_key=f"dlg_casc_{root_horario_id}_root_sel",
    )

    # Actualizar estado si cambió.
    if aula_elegida != estado["aula_elegida"]:
        estado["aula_elegida"] = aula_elegida
        # Determinar acción raíz según lo elegido.
        estado["accion"] = _accion_para_aula_raiz(candidatas, aula_elegida)
        _podar_hijos_no_afectados(session, plan_id, estado)

    # Si eligió "sin asignar" o aula libre, es flujo simple.
    if aula_elegida is None:
        st.info(
            "Se dejará este horario sin aula. Podés reasignarlo más "
            "adelante."
        )
        _confirmar_cascada(session, plan_id, root_horario_id, estado,
                           nuevo_tipo)
        return

    cand_root = next((c for c in candidatas if c.aula.id == aula_elegida),
                     None)
    if cand_root is None:
        _render_boton_cancelar(root_horario_id)
        return

    if cand_root.libre_en_franja:
        st.success(f"El aula **{cand_root.aula.nombre}** está libre.")
        _confirmar_cascada(session, plan_id, root_horario_id, estado,
                           nuevo_tipo)
        return

    # === Aula con ocupantes → renderizar cada uno con sus opciones ===
    st.divider()
    n_ocupantes = len(cand_root.ocupantes)
    st.warning(
        f"⚠️ Este cambio afecta **{n_ocupantes} horario(s)** del plan "
        f"que están usando el aula **{cand_root.aula.nombre}** en franjas "
        f"que se solapan con {horario_root.dia} "
        f"{horario_root.hora_inicio.strftime('%H:%M')}"
        f"–{horario_root.hora_fin.strftime('%H:%M')}. "
        f"Decidí qué hacer con cada uno:"
    )

    for oc in cand_root.ocupantes:
        _render_nodo_desplazado(
            session, plan_id, root_horario_id,
            padre_dict=estado, oc_horario=oc, sede_map=sede_map,
            nivel=1,
        )

    _confirmar_cascada(session, plan_id, root_horario_id, estado, nuevo_tipo)


def _accion_para_aula_raiz(candidatas, aula_id: Optional[str]) -> str:
    """Determina la acción de la raíz según el aula elegida.

    - aula_id is None → "sin_aula" (raíz sin aula).
    - libre → "libre".
    - ocupada → "reassign" (cada ocupante se resuelve por su hijo).

    Nota: no ofrecemos "swap" explícito en la UI porque cuando el
    usuario "intercambia", en realidad está eligiendo un aula ocupada
    (que activa la cascada) y para el desplazado elige el aula
    original del editado (usando el selector de reasignar). El backend
    trata esto como "reassign" y funciona idéntico.
    """
    if aula_id is None:
        return "sin_aula"
    cand = next((c for c in candidatas if c.aula.id == aula_id), None)
    if cand is None:
        return "libre"
    if cand.libre_en_franja:
        return "libre"
    return "reassign"


def _render_selector_aula(
    session, sede_map: dict, candidatas: list,
    estado_actual: Optional[str], aula_original: Optional[str],
    widget_key: str,
) -> Optional[str]:
    """Renderiza el selectbox de aula para un horario. Devuelve el
    aula elegida (o None si "sin asignar")."""
    from src.database.models import ComisionDB, MateriaDB

    def _label(c) -> str:
        base = (
            f"{sede_map.get(c.aula.sede_id, '?')} · {c.aula.nombre} "
            f"(cap. {c.aula.capacidad}, {c.aula.tipo})"
        )
        n_oc = len(c.ocupantes)
        if n_oc == 0:
            return f"[LIBRE] {base}"
        # Buscar detalles de los ocupantes para dar contexto.
        nombres = []
        for oc in c.ocupantes[:2]:  # primeros 2 para no saturar la label
            com = session.get(ComisionDB, oc.comision_id)
            mat_cod = com.materia_codigo if com else "?"
            nombres.append(mat_cod)
        detalle = ", ".join(nombres)
        if n_oc > 2:
            detalle += f", +{n_oc - 2}"
        return f"[{n_oc} horario{'s' if n_oc != 1 else ''} afectado{'s' if n_oc != 1 else ''}] {base} — {detalle}"

    opciones = ["__NONE__"] + [c.aula.id for c in candidatas]
    labels = {"__NONE__": "— Sin asignar —"}
    for c in candidatas:
        labels[c.aula.id] = _label(c)

    # Determinar índice default: preservar estado_actual, o sino usar
    # aula_original, o sino "sin asignar".
    default_id = estado_actual if estado_actual else aula_original
    if default_id in opciones:
        default_idx = opciones.index(default_id)
    else:
        default_idx = 0

    sel = st.selectbox(
        "Aula",
        options=opciones,
        index=default_idx,
        format_func=lambda x: labels[x],
        key=widget_key,
    )
    return None if sel == "__NONE__" else sel


def _render_nodo_desplazado(
    session, plan_id: str, root_horario_id: str,
    padre_dict: dict, oc_horario, sede_map: dict,
    nivel: int,
) -> None:
    """Renderiza recursivamente un nodo desplazado. Cada nodo puede
    tener sus propios hijos si el usuario elige un aula también
    ocupada."""
    from src.database.models import ComisionDB, MateriaDB, HorarioDB
    from src.services.asignacion_aulas_service import (
        get_aulas_todas_para_horario,
        tipo_solapamiento,
        solapamiento_franjas,
    )

    # Buscar meta del horario ocupante para el título del bloque.
    com = session.get(ComisionDB, oc_horario.comision_id)
    mat = session.get(MateriaDB, com.materia_codigo) if com else None
    mat_nombre = (
        mat.nombre if mat else (com.materia_codigo if com else "?")
    )
    com_nombre = com.nombre if com else "?"
    padre_h = session.get(HorarioDB, padre_dict["horario_id"])
    tipo_sol = tipo_solapamiento(
        padre_h.dia, padre_h.hora_inicio, padre_h.hora_fin,
        oc_horario.dia, oc_horario.hora_inicio, oc_horario.hora_fin,
    ) if padre_h else "sin_solape"

    # Rango de solapamiento (para info al usuario).
    rango_str = ""
    if tipo_sol == "parcial" and padre_h:
        rango = solapamiento_franjas(
            padre_h.dia, padre_h.hora_inicio, padre_h.hora_fin,
            oc_horario.dia, oc_horario.hora_inicio, oc_horario.hora_fin,
        )
        if rango:
            rango_str = (
                f" · solapa en {rango[0].strftime('%H:%M')}"
                f"–{rango[1].strftime('%H:%M')}"
            )
    elif tipo_sol == "identico":
        rango_str = " · misma franja"

    hijo = _nodo_hijo(padre_dict, oc_horario.id)

    with st.container(border=True):
        indent = "&nbsp;" * (4 * (nivel - 1))
        st.markdown(
            f"{indent}**{mat_nombre}** — {com_nombre} "
            f"({oc_horario.dia} "
            f"{oc_horario.hora_inicio.strftime('%H:%M')}"
            f"–{oc_horario.hora_fin.strftime('%H:%M')}){rango_str}"
        )

        # Candidatas para este desplazado.
        cands_hijo = get_aulas_todas_para_horario(
            session, plan_id, oc_horario.id,
        )

        aula_elegida = _render_selector_aula(
            session, sede_map, cands_hijo,
            estado_actual=hijo["aula_elegida"],
            aula_original=None,  # el desplazado no tiene "aula preferida"
            widget_key=(
                f"dlg_casc_{root_horario_id}_lvl{nivel}_{oc_horario.id}"
            ),
        )

        # Actualizar estado del hijo si cambió.
        if aula_elegida != hijo["aula_elegida"]:
            hijo["aula_elegida"] = aula_elegida
            hijo["accion"] = _accion_para_aula_hijo(cands_hijo, aula_elegida)
            _podar_hijos_no_afectados(session, plan_id, hijo)

        # Si eligió un aula ocupada, mostrar los sub-nodos recursivamente.
        if aula_elegida is not None:
            cand = next(
                (c for c in cands_hijo if c.aula.id == aula_elegida), None,
            )
            if cand is not None and cand.ocupantes:
                st.caption(
                    f"⚠️ El aula elegida también está ocupada por "
                    f"{len(cand.ocupantes)} horario(s):"
                )
                for oc2 in cand.ocupantes:
                    _render_nodo_desplazado(
                        session, plan_id, root_horario_id,
                        padre_dict=hijo, oc_horario=oc2,
                        sede_map=sede_map, nivel=nivel + 1,
                    )


def _accion_para_aula_hijo(candidatas, aula_id: Optional[str]) -> str:
    """Como _accion_para_aula_raiz pero para nodos internos: nunca
    devuelve 'swap' (sólo válido en la raíz)."""
    if aula_id is None:
        return "sin_aula"
    cand = next((c for c in candidatas if c.aula.id == aula_id), None)
    if cand is None or cand.libre_en_franja:
        return "reassign" if cand and not cand.libre_en_franja else "reassign"
    return "reassign"


def _confirmar_cascada(
    session, plan_id: str, root_horario_id: str,
    estado: dict, nuevo_tipo: str | None,
) -> None:
    """Renderiza el preview global y los botones Confirmar/Cancelar."""
    from src.services.asignacion_aulas_service import (
        cambiar_aula_horario,
        validar_y_planificar_cascada,
        aplicar_cascada,
    )
    from src.database.models import HorarioDB, ComisionDB, MateriaDB, AulaDB

    st.divider()
    st.markdown("### Resumen del cambio")

    cascada = _dict_a_nodo_cascada(estado)
    plan = validar_y_planificar_cascada(session, plan_id, cascada)

    if plan.errores_globales:
        for err in plan.errores_globales:
            st.error(err)

    # Tabla plana con todos los efectos.
    if plan.efectos:
        for ef in plan.efectos:
            h = session.get(HorarioDB, ef.horario_id)
            com = session.get(ComisionDB, h.comision_id) if h else None
            mat = session.get(MateriaDB, com.materia_codigo) if com else None
            mat_nombre = (
                mat.nombre if mat
                else (com.materia_codigo if com else "?")
            )
            com_nombre = com.nombre if com else "?"
            aula = (
                session.get(AulaDB, ef.aula_futura)
                if ef.aula_futura else None
            )
            aula_txt = aula.nombre if aula else "**sin aula**"

            icono = "✅" if ef.ok and not ef.warnings else (
                "⚠️" if ef.ok else "❌"
            )
            indent = "&nbsp;" * (4 * ef.nivel)
            st.markdown(
                f"{indent}{icono} **{mat_nombre}** — {com_nombre} → "
                f"{aula_txt}"
            )
            for err in ef.errores:
                st.error(f"{indent}&nbsp;&nbsp;{err}")
            for w in ef.warnings:
                st.warning(f"{indent}&nbsp;&nbsp;{w}")

    st.divider()
    col_ok, col_no = st.columns(2)
    with col_ok:
        btn_disabled = not plan.ok
        if st.button(
            "Confirmar",
            type="primary",
            key=f"dlg_casc_{root_horario_id}_ok",
            disabled=btn_disabled,
            help=(
                None if not btn_disabled
                else "Hay incompatibilidades — corregí antes de confirmar."
            ),
        ):
            # Ajuste de tipo (si aplica) antes de la cascada.
            if nuevo_tipo is not None:
                h = session.get(HorarioDB, root_horario_id)
                _res_tipo = cambiar_aula_horario(
                    session, root_horario_id,
                    h.aula_id if h else None,
                    nuevo_tipo=nuevo_tipo,
                )
                if not _res_tipo.ok:
                    for e in _res_tipo.errores:
                        st.error(e)
                    return
            res = aplicar_cascada(session, plan_id, cascada)
            if not res.ok:
                for e in res.errores:
                    st.error(e)
                return
            n_afectados = len(plan.efectos)
            st.success(
                f"Se aplicaron los cambios en {n_afectados} horario(s). "
                "Las clases heredaron los cambios."
            )
            _limpiar_estado_cascada(root_horario_id)
            st.rerun()
    with col_no:
        if st.button(
            "Cancelar",
            key=f"dlg_casc_{root_horario_id}_cancel",
        ):
            _limpiar_estado_cascada(root_horario_id)
            st.rerun()


def _render_confirmar_libre(
    session: "Session",
    plan_id: str,
    horario_id: str,
    sel_aula: str,
    nuevo_tipo: str | None,
) -> None:
    """Rama simple: aula libre o "sin asignar". Un solo botón
    Confirmar / Cancelar."""
    from src.services.asignacion_aulas_service import cambiar_aula_horario

    col_ok, col_no = st.columns(2)
    with col_ok:
        if st.button(
            "Confirmar", type="primary",
            key=f"dlg_h_ok_libre_{horario_id}",
        ):
            aula_arg = None if sel_aula == "__NONE__" else sel_aula
            res = cambiar_aula_horario(
                session, horario_id, aula_arg, nuevo_tipo=nuevo_tipo,
            )
            if not res.ok:
                for e in res.errores:
                    st.error(e)
                return
            for w in res.warnings:
                st.warning(w)
            st.success(
                "Aula actualizada. Las clases del horario heredaron "
                "el cambio."
            )
            st.rerun()
    with col_no:
        if st.button(
            "Cancelar", key=f"dlg_h_cancel_libre_{horario_id}",
        ):
            st.rerun()




def render_aula_cronograma(
    session: Session, plan_id: str, key_ns: str = "aula_crono",
) -> None:
    """Panel de gestión del **patrón semanal** de aulas del plan.

    Cada fila representa un ``HorarioDB`` (la franja semanal del
    plan). El aula que se muestra es la del PATRÓN
    (``HorarioDB.aula_id``); el LP la asigna y las ``ClaseDB`` heredan.
    Esta vista NO trabaja con clases puntuales ni excepciones por
    fecha; eso quedará en otra pestaña.
    """
    from src.database.models import HorarioDB

    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        st.error("Plan no encontrado.")
        return
    if plan.ciclo_id is None:
        st.error("El plan no tiene ciclo asociado.")
        return
    ciclo = session.get(CicloDB, plan.ciclo_id)
    if ciclo is None:
        st.error("Ciclo del plan no encontrado.")
        return

    st.subheader("📅 Aulas asignadas por horario")
    st.caption(
        "La asignación automática elige un aula para cada horario "
        "semanal del plan (lo que se repite todas las semanas). Si "
        "todavía no corriste la asignación, los horarios aparecen "
        "como 'Sin asignar' y podés editarlos a mano."
    )

    # Comisiones del plan.
    coms = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    if not coms:
        st.info(
            "El plan no tiene comisiones cargadas todavía. Generá la "
            "grilla horaria desde el panel correspondiente."
        )
        return
    com_map = {c.id: c for c in coms}
    materia_codigos = {c.materia_codigo for c in coms}

    # Horarios del plan (vía comisiones).
    com_ids = list(com_map.keys())
    horarios_db = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.comision_id.in_(com_ids)  # type: ignore[attr-defined]
        )
    ).all()) if com_ids else []
    if not horarios_db:
        st.info(
            "El plan tiene comisiones pero ningún horario cargado."
        )
        return

    materias_db = list(session.exec(
        select(MateriaDB).where(
            MateriaDB.codigo.in_(materia_codigos)  # type: ignore[attr-defined]
        )
    ).all()) if materia_codigos else []
    mat_map = {m.codigo: m for m in materias_db}

    plan_estudio_cache = _build_plan_estudio_cache(session, materia_codigos)

    aulas_db = list(session.exec(select(AulaDB)).all())
    aula_map = {a.id: a for a in aulas_db}
    # Para el filtro de "Aula", listamos todas las aulas que tienen
    # algún horario del plan asignado (no las que tienen clases — no
    # nos importa el nivel de clases acá).
    aula_ids_en_patron = {
        h.aula_id for h in horarios_db if h.aula_id is not None
    }
    aulas_con_uso = [a for a in aulas_db if a.id in aula_ids_en_patron]
    aulas_con_uso.sort(key=lambda a: (a.sede_id, a.nombre))

    sede_map = _sede_nombre_map(session)

    # Precargar virtualidad del dictado por materia del ciclo del plan
    # para resolver `resolve_virtual` en cada fila.
    from src.database.models import DictadoCicloDB, DictadoDB
    dictado_virtual_por_materia: dict[str, bool | None] = {}
    if plan.ciclo_id is not None:
        for mc, v in session.exec(
            select(DictadoDB.materia_codigo, DictadoDB.virtual)
            .join(
                DictadoCicloDB,
                DictadoDB.id == DictadoCicloDB.dictado_id,  # type: ignore[arg-type]
            )
            .where(DictadoCicloDB.ciclo_id == plan.ciclo_id)
        ).all():
            dictado_virtual_por_materia[mc] = v

    # Filas (1 por HorarioDB), leyendo aula_id directamente del patrón.
    rows = _build_horario_rows_v2(
        horarios_db, com_map, mat_map, aula_map, plan_estudio_cache,
        dictado_virtual_por_materia=dictado_virtual_por_materia,
    )

    # Panel de filtros.
    filtros = _build_filtros_panel(
        key_ns, plan_estudio_cache, sede_map, aulas_con_uso,
    )
    mostrar_cronograma = bool(filtros.get("mostrar_cronograma"))

    rows_filtradas = _aplicar_filtros_horarios_v2(rows, filtros, sede_map)

    # Cronograma consolidado del patrón.
    if mostrar_cronograma:
        st.divider()
        st.markdown("**Vista de cronograma semanal**")
        grid = _build_grid_from_rows(rows_filtradas, sede_map)
        if grid:
            config = get_or_create_config(session)
            render_timetable_calendar(
                grid_data=grid,
                config=config,
                key=f"{key_ns}_cal_patron",
            )
        else:
            st.info(
                "No hay horarios que matcheen los filtros activos."
            )

    # Tabla del patrón.
    st.divider()
    st.markdown("**Horarios asignados (filtros aplicados)**")
    n_sin_aula = sum(1 for r in rows if r.get("aula_id") is None)
    st.caption(
        f"{len(rows_filtradas)} de {len(rows)} horarios matchean los "
        f"filtros. {n_sin_aula} horarios sin aula asignada en total."
    )

    if not rows_filtradas:
        st.info(
            "Ninguno de los horarios matchea los filtros. Ajustá los "
            "filtros y apretá '✅ Aplicar filtros'."
        )
        return

    # =====================================================
    # Paginación
    # =====================================================
    _page_size_key = f"{key_ns}_page_size"
    _page_num_key = f"{key_ns}_page_num"
    if _page_size_key not in st.session_state:
        st.session_state[_page_size_key] = 20
    if _page_num_key not in st.session_state:
        st.session_state[_page_num_key] = 1

    _pag_c1, _pag_c2, _pag_c3 = st.columns([2, 2, 6])
    with _pag_c1:
        page_size = st.selectbox(
            "Por página",
            options=[10, 20, 30, 50, 100],
            index=[10, 20, 30, 50, 100].index(
                st.session_state[_page_size_key]
            ),
            key=f"{key_ns}_page_size_sel",
        )
    total_rows = len(rows_filtradas)
    total_pages = max(1, (total_rows + page_size - 1) // page_size)
    # Si cambió page_size y la página actual ya no existe, resetear a 1.
    if st.session_state[_page_num_key] > total_pages:
        st.session_state[_page_num_key] = 1
    st.session_state[_page_size_key] = page_size

    with _pag_c2:
        page_num = st.number_input(
            f"Página (1–{total_pages})",
            min_value=1,
            max_value=total_pages,
            value=st.session_state[_page_num_key],
            step=1,
            key=f"{key_ns}_page_num_input",
        )
        st.session_state[_page_num_key] = page_num
    with _pag_c3:
        start = (page_num - 1) * page_size + 1
        end = min(page_num * page_size, total_rows)
        st.caption(
            f"Mostrando {start}–{end} de {total_rows} horarios "
            f"(página {page_num} de {total_pages})."
        )

    start_idx = (page_num - 1) * page_size
    rows_filtradas = rows_filtradas[start_idx:start_idx + page_size]

    for r in rows_filtradas:
        aula = r.get("aula_obj")
        sede_nombre = sede_map.get(aula.sede_id, "?") if aula else "—"
        if aula:
            aula_label = f"{sede_nombre} · {aula.nombre}"
        elif r.get("es_virtual"):
            # No requiere aula: el horario es virtual (resuelto por
            # jerarquía horario > dictado > materia).
            aula_label = "💻 Virtual (no requiere aula)"
        else:
            aula_label = "📭 Sin asignar"
        anios = r.get("anios", set())
        cuatris = r.get("cuatris", set())
        anio_lbl = (
            "/".join(f"{a}°" for a in sorted(anios)) if anios else "—"
        )
        cuatri_lbl = (
            "/".join(sorted(cuatris)) if cuatris else "—"
        )
        carrera_lbl = r.get("label", "—")
        cola, colb, colc = st.columns([4, 4, 1])
        with cola:
            st.markdown(
                f"**{r['dia']}** "
                f"{r['hora_inicio'].strftime('%H:%M')}–"
                f"{r['hora_fin'].strftime('%H:%M')} · "
                f"{r['materia_nombre']} ({r['comision_nombre']})"
            )
            st.caption(
                f"📚 {carrera_lbl} · {anio_lbl} · {cuatri_lbl} · "
                f"tipo: {r.get('tipo_clase') or 'sin determinar'}"
            )
        with colb:
            st.markdown(f"🏛️ {aula_label}")
        with colc:
            if st.button(
                "Editar",
                key=f"{key_ns}_edit_h_{r['horario_id']}",
                help=(
                    "Reasigna el aula del patrón. Las clases del "
                    "horario sin excepción manual heredarán el cambio."
                ),
            ):
                _dialog_cambiar_aula_horario(plan_id, r["horario_id"])
