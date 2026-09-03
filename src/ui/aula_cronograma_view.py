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
    y mostrar.

    Devuelve además ``ubicaciones``: set de tuplas
    ``(carrera_codigo, anio, cuatri)`` con las combinaciones exactas
    en las que la materia aparece en ``PlanEstudioDB``. Sirve para
    filtrar con semántica **estricta** (la tupla completa tiene que
    existir), en contraste con los sets sueltos ``carreras_codigos``
    / ``anios`` / ``cuatris`` que pueden dar falsos positivos si se
    combinan como filtros independientes.
    """
    entries = cache.get(materia_codigo, [])
    if not entries:
        return {
            "carreras_codigos": set(),
            "carreras_nombres": [],
            "anios": set(),
            "cuatris": set(),
            "ubicaciones": set(),
            "label": "—",
        }
    carreras_codigos = {e[0] for e in entries}
    carreras_nombres = sorted({e[1] for e in entries})
    anios = {e[2] for e in entries if e[2] is not None}
    cuatris = {e[3] for e in entries if e[3] is not None}
    ubicaciones: set[tuple[str, int | None, str | None]] = {
        (e[0], e[2], e[3]) for e in entries
    }
    label = ", ".join(carreras_nombres)
    return {
        "carreras_codigos": carreras_codigos,
        "carreras_nombres": carreras_nombres,
        "anios": anios,
        "cuatris": cuatris,
        "ubicaciones": ubicaciones,
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
    "excluir_virtuales": False,
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

            # Filtro por ubicación en el plan de estudio. Los tres
            # campos operan como una TUPLA: la materia tiene que estar
            # en `PlanEstudioDB` con la combinación exacta (dimensión
            # vacía = "cualquiera"). Se agrupan visualmente para que
            # el usuario entienda que actúan combinados y no como
            # filtros independientes.
            with st.container(border=True):
                st.markdown(
                    "**📚 Ubicación en el plan de estudio**"
                )
                st.caption(
                    "Filtran combinados: la materia tiene que estar en "
                    "el plan de estudio con esa **combinación exacta** "
                    "de carrera/año/cuatrimestre. Dejar un campo vacío "
                    "significa 'cualquiera' en esa dimensión."
                )
                r2c1, r2c2, r2c3 = st.columns(3)
                with r2c1:
                    sel_carreras = st.multiselect(
                        "Carrera",
                        options=carrera_opts_codes,
                        default=aplicados.get("carreras", []),
                        format_func=lambda c: (
                            f"{c} · {todas_carreras.get(c, c)}"
                        ),
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

            r4c1, r4c2, r4c3, r4c4, r4c5 = st.columns([1, 1, 1, 1, 1])
            with r4c1:
                sel_sin_aula = st.checkbox(
                    "Sólo sin asignar",
                    value=aplicados.get("sin_aula", False),
                    key=f"{key_ns}_form_sin_aula",
                    help=(
                        "Mostrar sólo los horarios que no tienen aula "
                        "asignada todavía."
                    ),
                )
            with r4c2:
                sel_excl_virt = st.checkbox(
                    "Excluir virtuales",
                    value=aplicados.get("excluir_virtuales", False),
                    key=f"{key_ns}_form_excluir_virtuales",
                    help=(
                        "Ocultar los horarios virtuales (no requieren "
                        "aula física). Útil combinado con 'Sólo sin "
                        "asignar' para revisar sólo los que faltan "
                        "asignar de verdad."
                    ),
                )
            with r4c3:
                sel_mostrar_crono = st.checkbox(
                    "Mostrar cronograma",
                    value=aplicados.get("mostrar_cronograma", False),
                    key=f"{key_ns}_form_mostrar_crono",
                    help=(
                        "Renderiza el calendario consolidado del "
                        "esquema semanal con los horarios filtrados."
                    ),
                )
            with r4c4:
                aplicar = st.form_submit_button(
                    "✅ Aplicar filtros", type="primary",
                )
            with r4c5:
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
                "_form_sin_aula", "_form_excluir_virtuales",
                "_form_mostrar_crono",
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
                "excluir_virtuales": bool(sel_excl_virt),
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
    f_excl_virt: bool = bool(filtros.get("excluir_virtuales"))

    # Filtro estricto de (carrera, anio, cuatri): la materia tiene que
    # tener AL MENOS una ubicación en PlanEstudioDB que satisfaga las
    # dimensiones filtradas. Cada dimensión vacía se interpreta como
    # "cualquiera". Evita falsos positivos que se daban antes cuando
    # las 3 dimensiones se filtraban con intersecciones independientes
    # (ej. F14 aparecía en Electrónica 5º 1C porque estaba en A/1/1C,
    # en E/2/1C y en M/5/1C — la tupla (A, 5, 1C) no existía pero
    # cada dimensión pasaba por su cuenta).
    filtro_combinado_activo = bool(f_carreras or f_anios or f_cuatris)

    out: list[dict] = []
    for r in rows:
        carr_codes: set[str] = r.get("carreras_codigos", set())
        if f_aula and r.get("aula_id") != f_aula:
            continue
        if f_excl_virt and r.get("es_virtual"):
            continue
        if f_sin_aula and r.get("aula_id") is not None:
            continue
        if filtro_combinado_activo:
            ubicaciones: set[tuple[str, int | None, str | None]] = (
                r.get("ubicaciones", set())
            )
            if not any(
                (not f_carreras or car in f_carreras)
                and (not f_anios or anio in f_anios)
                and (not f_cuatris or cuatri in f_cuatris)
                for car, anio, cuatri in ubicaciones
            ):
                continue
        if f_comunes_mode == "Sólo comunes":
            if len(carr_codes) < 2:
                continue
        elif f_comunes_mode == "Sólo exclusivas":
            if len(carr_codes) != 1:
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


def _render_horario_expander(
    session: "Session",
    plan_id: str,
    key_ns: str,
    r: dict,
    sede_map: dict,
) -> None:
    """Renderiza un horario del listado como expander plegable con
    controles de edición inline.

    Título condensado: "Día HH:MM–HH:MM · Materia · Código · Comisión
    · Sede · Aula". Adentro: detalles + selector de tipo + selector
    de aula. Cuando el usuario cambia algo, aparece un botón "Ver
    cambio propuesto" que abre el diálogo de confirmación con el
    preview de cascada.
    """
    from src.database.models import HorarioDB, AulaDB

    aula = r.get("aula_obj")
    sede_nombre = sede_map.get(aula.sede_id, "?") if aula else "—"
    if aula:
        aula_label = f"{sede_nombre} · {aula.nombre}"
    elif r.get("es_virtual"):
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

    dia = r["dia"]
    hi = r["hora_inicio"].strftime("%H:%M")
    hf = r["hora_fin"].strftime("%H:%M")
    materia = r["materia_nombre"]
    codigo = r.get("materia_codigo", "?")
    comision = r["comision_nombre"]
    horario_id = r["horario_id"]

    # Título condensado. En un renglón, evitando emojis para no ruidear.
    titulo = (
        f"{dia} {hi}–{hf} · {materia} · {codigo} · "
        f"{comision} · {aula_label}"
    )

    with st.expander(titulo, expanded=False):
        # Detalles.
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(
                f"**Materia:** {materia}  \n"
                f"**Código:** {codigo}  \n"
                f"**Comisión:** {comision}  \n"
                f"**Día y horario:** {dia} {hi}–{hf}"
            )
        with c2:
            st.markdown(
                f"**Carreras:** {carrera_lbl}  \n"
                f"**Año/Cuatri:** {anio_lbl} · {cuatri_lbl}  \n"
                f"**Aula actual:** {aula_label}  \n"
                f"**Tipo:** {r.get('tipo_clase') or 'sin determinar'}"
            )

        st.divider()

        # Controles de edición inline.
        _render_controles_edicion_horario(
            session, plan_id, key_ns, horario_id,
        )


def _render_controles_edicion_horario(
    session: "Session",
    plan_id: str,
    key_ns: str,
    horario_id: str,
) -> None:
    """Renderiza los controles de edición inline de un horario: selector
    de tipo, selector de aula (libres o todas), y botón "Ver cambio
    propuesto" que abre el diálogo de confirmación cuando hay cambios.
    """
    from src.database.models import HorarioDB
    from src.services.asignacion_aulas_service import (
        get_aulas_disponibles_para_horario,
        get_aulas_todas_para_horario,
    )

    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        st.error("Horario no encontrado.")
        return

    # Tipo de clase.
    tipo_actual = horario.tipo_clase if horario.tipo_clase in (
        "teorica", "laboratorio"
    ) else "teorica"
    nuevo_tipo = st.selectbox(
        "Tipo de clase",
        options=["teorica", "laboratorio"],
        index=["teorica", "laboratorio"].index(tipo_actual),
        key=f"{key_ns}_exp_tipo_{horario_id}",
    )
    cambiando_tipo = (
        horario.tipo_clase is not None
        and nuevo_tipo != horario.tipo_clase
    )

    # Vista de aulas: solo libres o todas.
    vista = st.radio(
        "Aulas a mostrar",
        options=["libres", "todas"],
        format_func=lambda v: (
            "Sólo aulas libres en esta franja"
            if v == "libres"
            else "Todas las aulas (incluidas las ocupadas)"
        ),
        index=0,
        key=f"{key_ns}_exp_vista_{horario_id}",
        horizontal=True,
    )

    sede_map = _sede_nombre_map(session)

    if vista == "libres":
        aulas_disp = get_aulas_disponibles_para_horario(
            session, plan_id, horario_id,
            tipo_objetivo=(nuevo_tipo if cambiando_tipo else None),
        )
        if not aulas_disp:
            st.info(
                "No hay aulas compatibles libres en esta franja. "
                "Cambiá a 'Todas las aulas' para elegir una ocupada "
                "y resolver el conflicto."
            )
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
            key=f"{key_ns}_exp_aula_libres_{horario_id}",
        )
        aula_arg = None if sel_aula == "__NONE__" else sel_aula
        hay_cambio = (aula_arg != horario.aula_id) or cambiando_tipo

        if hay_cambio:
            if st.button(
                "Ver cambio propuesto",
                type="primary",
                key=f"{key_ns}_exp_ver_libres_{horario_id}",
            ):
                # Sembrar el estado de cascada con la decisión simple.
                estado = _get_state(horario_id)
                estado["aula_elegida"] = aula_arg
                estado["accion"] = "libre" if aula_arg else "sin_aula"
                estado["hijos"] = {}
                _open_confirmar_dialog(
                    plan_id, horario_id,
                    nuevo_tipo if cambiando_tipo else None,
                )
        else:
            st.caption("Sin cambios respecto del estado actual.")
        return

    # Vista: TODAS las aulas — con soporte de cascada.
    _render_flujo_cascada_inline(
        session, plan_id, horario_id, sede_map,
        nuevo_tipo if cambiando_tipo else None, key_ns,
    )


def _render_flujo_cascada_inline(
    session: "Session",
    plan_id: str,
    root_horario_id: str,
    sede_map: dict,
    nuevo_tipo: Optional[str],
    key_ns: str,
) -> None:
    """Como `_render_flujo_cascada` pero adaptado para vivir dentro
    del expander en lugar del popup. La confirmación final abre un
    popup con el preview y los calendarios."""
    from src.database.models import HorarioDB
    from src.services.asignacion_aulas_service import (
        get_aulas_todas_para_horario,
    )

    horario_root = session.get(HorarioDB, root_horario_id)
    if horario_root is None:
        st.error("Horario no encontrado.")
        return

    estado = _get_state(root_horario_id)

    candidatas = get_aulas_todas_para_horario(
        session, plan_id, root_horario_id,
        tipo_objetivo=nuevo_tipo,
    )
    if not candidatas:
        st.warning(
            "No hay aulas compatibles con este horario "
            "(considerá cambiar el tipo)."
        )
        return

    reservas = _recolectar_reservas_cascada(
        session, estado, horario_id_actual=root_horario_id,
    )
    aula_elegida = _render_selector_aula(
        session, sede_map, candidatas,
        estado_actual=estado["aula_elegida"],
        aula_original=horario_root.aula_id,
        widget_key=f"{key_ns}_expc_{root_horario_id}_root_sel",
        horario_actual=horario_root,
        reservas_en_cascada=reservas,
    )

    if aula_elegida != estado["aula_elegida"]:
        estado["aula_elegida"] = aula_elegida
        estado["accion"] = _accion_para_aula_raiz(candidatas, aula_elegida)
        _podar_hijos_no_afectados(session, plan_id, estado)

    if aula_elegida is None:
        st.info(
            "Se dejará este horario sin aula. Podés reasignarlo más "
            "adelante."
        )
    else:
        cand_root = next(
            (c for c in candidatas if c.aula.id == aula_elegida), None,
        )
        if cand_root and cand_root.libre_en_franja:
            st.success(f"El aula **{cand_root.aula.nombre}** está libre.")
        elif cand_root and cand_root.ocupantes:
            n_ocupantes = len(cand_root.ocupantes)
            st.warning(
                f"⚠️ Este cambio afecta **{n_ocupantes} horario(s)** del "
                f"plan que están usando el aula **{cand_root.aula.nombre}** "
                f"en franjas que se solapan con {horario_root.dia} "
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

    # Detectar si hay cambios respecto del estado actual.
    hay_cambio = (
        estado["aula_elegida"] != horario_root.aula_id
        or nuevo_tipo is not None
        or bool(estado.get("hijos"))
    )
    if hay_cambio:
        if st.button(
            "Ver cambio propuesto",
            type="primary",
            key=f"{key_ns}_expc_ver_{root_horario_id}",
        ):
            _open_confirmar_dialog(plan_id, root_horario_id, nuevo_tipo)
    else:
        st.caption("Sin cambios respecto del estado actual.")


@st.dialog("Confirmar cambio de aula", width="large")
def _open_confirmar_dialog(
    plan_id: str,
    root_horario_id: str,
    nuevo_tipo: Optional[str],
) -> None:
    """Popup de confirmación con el preview del cambio y calendarios
    de cada aula afectada. Aplica la cascada al confirmar.
    """
    from src.database.connection import get_session
    from src.services.asignacion_aulas_service import (
        cambiar_aula_horario,
        aplicar_cascada,
    )
    from src.database.models import HorarioDB

    with next(get_session()) as session:
        estado = _get_state(root_horario_id)
        _confirmar_cascada(
            session, plan_id, root_horario_id, estado, nuevo_tipo,
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


def _buscar_nodo_en_estado(root: dict, horario_id: str) -> Optional[dict]:
    """DFS por el árbol de decisiones (dicts) buscando el nodo con
    ``horario_id``. Devuelve el dict del nodo o None si no está."""
    if root.get("horario_id") == horario_id:
        return root
    for hijo in root.get("hijos", {}).values():
        r = _buscar_nodo_en_estado(hijo, horario_id)
        if r is not None:
            return r
    return None


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
        marcar_manual=nodo_dict.get("marcar_manual"),
    )



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


def _recolectar_reservas_cascada(
    session,
    root_estado: dict,
    horario_id_actual: str,
) -> dict[str, list[tuple[str, "object", "object", "object"]]]:
    """Recorre el árbol de decisiones y devuelve las aulas ya elegidas
    por otros nodos.

    Devuelve un dict ``aula_id -> lista de (horario_id, dia, hi, hf)``
    excluyendo la decisión del propio ``horario_id_actual`` (para no
    marcarse a sí mismo).

    Usado para marcar en el selector de aula del nodo actual cuáles
    aulas ya están reservadas en este cambio.
    """
    from src.database.models import HorarioDB

    reservas: dict[str, list[tuple]] = {}

    def _dfs(nodo: dict):
        aid = nodo.get("aula_elegida")
        hid = nodo.get("horario_id")
        if aid and hid and hid != horario_id_actual:
            h = session.get(HorarioDB, hid)
            if h is not None:
                reservas.setdefault(aid, []).append(
                    (hid, h.dia, h.hora_inicio, h.hora_fin)
                )
        for hijo in nodo.get("hijos", {}).values():
            _dfs(hijo)

    _dfs(root_estado)
    return reservas


def _render_selector_aula(
    session, sede_map: dict, candidatas: list,
    estado_actual: Optional[str], aula_original: Optional[str],
    widget_key: str,
    horario_actual=None,
    reservas_en_cascada: Optional[dict] = None,
) -> Optional[str]:
    """Renderiza el selectbox de aula para un horario. Devuelve el
    aula elegida (o None si "sin asignar").

    Si se pasan ``horario_actual`` y ``reservas_en_cascada``, las
    aulas que otro nodo de la cascada ya haya elegido y cuya franja
    solape con la del ``horario_actual`` se filtran del listado —
    no se pueden elegir porque generarían choque residual.
    """
    from src.database.models import ComisionDB, MateriaDB
    from src.services.asignacion_aulas_service import solapamiento_franjas

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

    # Filtrar candidatas que ya fueron elegidas por otro nodo de la
    # cascada con franja solapada al horario actual.
    aulas_filtradas: set[str] = set()
    if horario_actual is not None and reservas_en_cascada:
        for aid, ocupaciones in reservas_en_cascada.items():
            for _, dia, hi, hf in ocupaciones:
                sol = solapamiento_franjas(
                    dia, hi, hf,
                    horario_actual.dia,
                    horario_actual.hora_inicio,
                    horario_actual.hora_fin,
                )
                if sol is not None:
                    aulas_filtradas.add(aid)
                    break

    candidatas_disponibles = [
        c for c in candidatas if c.aula.id not in aulas_filtradas
    ]

    opciones = ["__NONE__"] + [c.aula.id for c in candidatas_disponibles]
    labels = {"__NONE__": "— Sin asignar —"}
    for c in candidatas_disponibles:
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

    if aulas_filtradas:
        st.caption(
            f"ℹ️ {len(aulas_filtradas)} aula(s) no aparecen en el listado "
            f"porque ya están siendo reasignadas a otro horario en este "
            f"cambio."
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
        if tipo_sol == "parcial":
            st.caption(
                "ℹ️ Este horario dura distinto que el que estás editando. "
                "Cuidado si le asignás la misma aula: en el tramo que no "
                "coinciden, esta aula quedaría con dos materias al mismo "
                "tiempo."
            )

        # Candidatas para este desplazado.
        cands_hijo = get_aulas_todas_para_horario(
            session, plan_id, oc_horario.id,
        )

        # Reservas: aulas ya elegidas por otros nodos de la cascada.
        root_estado = _get_state(root_horario_id)
        reservas = _recolectar_reservas_cascada(
            session, root_estado, horario_id_actual=oc_horario.id,
        )
        aula_elegida = _render_selector_aula(
            session, sede_map, cands_hijo,
            estado_actual=hijo["aula_elegida"],
            aula_original=None,  # el desplazado no tiene "aula preferida"
            widget_key=(
                f"dlg_casc_{root_horario_id}_lvl{nivel}_{oc_horario.id}"
            ),
            horario_actual=oc_horario,
            reservas_en_cascada=reservas,
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


def _render_calendarios_impacto(
    session: "Session",
    plan_id: str,
    plan,
) -> None:
    """Muestra un calendario por cada aula involucrada en la cascada,
    con dos vistas apiladas verticalmente: estado actual (arriba) y
    estado resultante (abajo).

    Las materias tocadas por la cascada se resaltan a todo color; las
    demás materias del aula se pintan en gris atenuado para dejar
    visualmente destacados sólo los bloques relevantes.

    "Aulas involucradas" = todas las aulas que:
    - eran usadas por algún horario tocado por la cascada (antes),
    - van a ser usadas por algún horario tocado por la cascada (después).
    """
    from src.database.models import HorarioDB, ComisionDB, MateriaDB, AulaDB
    from src.services.plan_generation_service import TimetableBlock

    # Set de aulas involucradas.
    aulas_ids: set[str] = set()
    for ef in plan.efectos:
        if ef.aula_futura:
            aulas_ids.add(ef.aula_futura)
        h = session.get(HorarioDB, ef.horario_id)
        if h and h.aula_id:
            aulas_ids.add(h.aula_id)

    if not aulas_ids:
        st.info(
            "No hay aulas involucradas en el cambio (todos los horarios "
            "afectados quedan sin aula)."
        )
        return

    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    horarios_plan = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
        )
    ).all())

    # Efectos indexados y set de materias tocadas por la cascada (para
    # resaltar en los calendarios; el resto se atenúa).
    efectos_por_h = {ef.horario_id: ef for ef in plan.efectos}
    materias_tocadas: set[str] = set()
    for ef in plan.efectos:
        h = session.get(HorarioDB, ef.horario_id)
        if h is None:
            continue
        com = session.get(ComisionDB, h.comision_id)
        if com and com.materia_codigo:
            materias_tocadas.add(com.materia_codigo)

    sede_map = _sede_nombre_map(session)
    config = get_or_create_config(session)

    # Paleta consistente: la misma materia tiene que tener el mismo
    # color en TODOS los calendarios (antes/después de cada aula).
    # Se prioriza a las materias tocadas por la cascada — quedan con
    # los primeros colores de la paleta (más distintivos), y el orden
    # es determinístico (sorted) para que sucesivas invocaciones no
    # bailen los colores.
    from src.ui.calendar_render import PALETTE, TEXT_COLOR
    mat_color_override: dict[str, tuple[str, str]] = {}
    materias_priorizadas = sorted(materias_tocadas)
    for i, codigo in enumerate(materias_priorizadas):
        mat_color_override[codigo] = (
            PALETTE[i % len(PALETTE)], TEXT_COLOR,
        )

    aulas_ordenadas = sorted(aulas_ids)
    for idx, aula_id in enumerate(aulas_ordenadas):
        aula = session.get(AulaDB, aula_id)
        if aula is None:
            continue
        sede_nombre = sede_map.get(aula.sede_id, "?")

        grid_antes: dict[str, list[TimetableBlock]] = {}
        grid_despues: dict[str, list[TimetableBlock]] = {}

        for h in horarios_plan:
            com = session.get(ComisionDB, h.comision_id)
            mat = (
                session.get(MateriaDB, com.materia_codigo) if com else None
            )
            mat_nombre = (
                mat.nombre if mat
                else (com.materia_codigo if com else "?")
            )
            mat_codigo = com.materia_codigo if com else "?"
            com_nombre = com.nombre if com else "?"

            # Antes: horarios cuya aula_id actual es la aula que estamos
            # dibujando.
            if h.aula_id == aula_id:
                block = TimetableBlock(
                    materia_codigo=mat_codigo,
                    materia_nombre=mat_nombre,
                    comision_nombre=com_nombre,
                    hora_inicio=h.hora_inicio,
                    hora_fin=h.hora_fin,
                    virtual=False,
                    en_periodo=True,
                    aula_label=aula.nombre,
                )
                grid_antes.setdefault(h.dia, []).append(block)

            # Después: aula final tras aplicar la cascada.
            ef = efectos_por_h.get(h.id)
            aula_final = ef.aula_futura if ef else h.aula_id
            if aula_final == aula_id:
                tocado = ef is not None
                block = TimetableBlock(
                    materia_codigo=mat_codigo,
                    materia_nombre=(
                        f"★ {mat_nombre}" if tocado else mat_nombre
                    ),
                    comision_nombre=com_nombre,
                    hora_inicio=h.hora_inicio,
                    hora_fin=h.hora_fin,
                    virtual=False,
                    en_periodo=True,
                    aula_label=aula.nombre,
                )
                grid_despues.setdefault(h.dia, []).append(block)

        titulo_exp = (
            f"{sede_nombre} · {aula.nombre} "
            f"(cap. {aula.capacidad}, {aula.tipo})"
        )
        # Primera aula abierta por default; el resto plegadas.
        with st.expander(titulo_exp, expanded=(idx == 0)):
            st.caption(
                "Los bloques en color son las materias afectadas por el "
                "cambio; el resto queda en gris para no distraer. "
                "★ = horario tocado por la cascada."
            )
            col_antes, col_despues = st.columns(2)
            with col_antes:
                st.markdown("**Antes**")
                if not grid_antes:
                    st.info(
                        "El aula estaba libre en las franjas visibles."
                    )
                else:
                    render_timetable_calendar(
                        grid_data=grid_antes,
                        config=config,
                        key=f"cal_impacto_antes_{aula_id}",
                        titulo_compacto=True,
                        resaltar_codigos=materias_tocadas,
                        mostrar_leyenda=False,
                        mat_color_override=mat_color_override,
                        height_px=380,
                    )
            with col_despues:
                st.markdown("**Después**")
                if not grid_despues:
                    st.info(
                        "El aula quedaría libre en las franjas visibles."
                    )
                else:
                    render_timetable_calendar(
                        grid_data=grid_despues,
                        config=config,
                        key=f"cal_impacto_despues_{aula_id}",
                        titulo_compacto=True,
                        resaltar_codigos=materias_tocadas,
                        mostrar_leyenda=False,
                        mat_color_override=mat_color_override,
                        height_px=380,
                    )


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

    # Tabla plana con todos los efectos + checkbox "Marcar como
    # manual" por cada horario que va a recibir aula. La decisión se
    # persiste al dict del estado (`marcar_manual`) para que
    # `_dict_a_nodo_cascada` la propague al servicio.
    if plan.efectos:
        st.caption(
            "Cada asignación tiene una casilla **'Marcar como manual'** "
            "del lado **Después**: si queda tildada, el asignador la va "
            "a **respetar** en corridas futuras (mientras el toggle "
            "'Respetar ediciones manuales' esté activado). Destildala "
            "si querés que el asignador pueda volver a decidir esa aula."
        )
        for ef in plan.efectos:
            h = session.get(HorarioDB, ef.horario_id)
            com = session.get(ComisionDB, h.comision_id) if h else None
            mat = session.get(MateriaDB, com.materia_codigo) if com else None
            mat_nombre = (
                mat.nombre if mat
                else (com.materia_codigo if com else "?")
            )
            com_nombre = com.nombre if com else "?"
            aula_previa = (
                session.get(AulaDB, h.aula_id)
                if h and h.aula_id else None
            )
            aula_previa_txt = (
                aula_previa.nombre if aula_previa else "_sin aula_"
            )
            aula_futura = (
                session.get(AulaDB, ef.aula_futura)
                if ef.aula_futura else None
            )
            aula_futura_txt = (
                aula_futura.nombre if aula_futura else "**sin aula**"
            )
            franja_txt = (
                f"{h.dia} {h.hora_inicio.strftime('%H:%M')}–"
                f"{h.hora_fin.strftime('%H:%M')}"
                if h else ""
            )

            icono = "✅" if ef.ok and not ef.warnings else (
                "⚠️" if ef.ok else "❌"
            )
            indent = "&nbsp;" * (4 * ef.nivel)

            # Buscar el nodo correspondiente en el estado para leer/
            # setear `marcar_manual`.
            nodo_est = _buscar_nodo_en_estado(estado, ef.horario_id)

            with st.container(border=True):
                # Fila 1: cabecera con todos los datos + checkbox manual
                # (a la derecha). Se colapsa toda la info identificatoria
                # del horario en una sola línea para máxima compacidad.
                col_head, col_chk = st.columns([5, 2])
                with col_head:
                    header_parts = [
                        f"{indent}{icono} **{mat_nombre}** — {com_nombre}",
                    ]
                    if franja_txt:
                        header_parts.append(
                            f"<small>· {franja_txt}</small>"
                        )
                    st.markdown(
                        " ".join(header_parts),
                        unsafe_allow_html=True,
                    )
                with col_chk:
                    if ef.aula_futura is not None and nodo_est is not None:
                        default_manual = nodo_est.get("marcar_manual")
                        if default_manual is None:
                            default_manual = True
                        chk_key = (
                            f"dlg_casc_{root_horario_id}_manual_"
                            f"{ef.horario_id}"
                        )
                        val = st.checkbox(
                            "🔒 Marcar como manual",
                            value=default_manual,
                            key=chk_key,
                            help=(
                                "Si queda tildada, el asignador va a "
                                "respetar esta aula en corridas futuras."
                            ),
                        )
                        nodo_est["marcar_manual"] = val

                # Fila 2: antes → después en línea, sin repetir headers.
                st.markdown(
                    f"{indent}<small>"
                    f"**Antes:** 🏛️ {aula_previa_txt} &nbsp;→&nbsp; "
                    f"**Después:** 🏛️ {aula_futura_txt}"
                    f"</small>",
                    unsafe_allow_html=True,
                )

                for err in ef.errores:
                    st.error(err)
                for w in ef.warnings:
                    st.warning(w)

    # Vista de calendarios: uno por cada aula afectada.
    st.divider()
    st.markdown("### Vista antes / después por aula")
    _render_calendarios_impacto(session, plan_id, plan)

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
        _render_horario_expander(
            session, plan_id, key_ns, r, sede_map,
        )
