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

from collections import defaultdict
from datetime import date, timedelta

import streamlit as st
from sqlmodel import Session, select

from src.database.crud import get_or_create_config
from src.database.models import (
    AulaDB,
    CicloDB,
    ClaseDB,
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


def _lunes_de_semana(d: date) -> date:
    """Devuelve el lunes de la semana de ``d``."""
    return d - timedelta(days=d.weekday())


def _semanas_del_ciclo(ciclo: CicloDB) -> list[date]:
    """Lista de lunes de cada semana del ciclo."""
    out: list[date] = []
    cur = _lunes_de_semana(ciclo.fecha_inicio)
    while cur <= ciclo.fecha_fin:
        out.append(cur)
        cur += timedelta(days=7)
    return out


def _clases_de_aula_en_semana(
    session: Session, plan_id: str, aula_id: str, lunes: date,
) -> list[ClaseDB]:
    domingo = lunes + timedelta(days=6)
    clases = session.exec(
        select(ClaseDB).where(
            ClaseDB.plan_cursada_id == plan_id,
            ClaseDB.aula_id == aula_id,
            ClaseDB.fecha >= lunes,
            ClaseDB.fecha <= domingo,
        )
    ).all()
    return list(clases)


def _build_timetable_blocks(
    session: Session, clases: list[ClaseDB],
) -> dict[str, list[TimetableBlock]]:
    """Construye el dict día -> [TimetableBlock] que pide
    ``render_timetable_calendar``."""
    DOW_TO_DIA = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    grid: dict[str, list[TimetableBlock]] = {}
    if not clases:
        return grid
    com_ids = {c.comision_id for c in clases}
    materias_codigos = set()
    comisiones_db = list(session.exec(
        select(ComisionDB).where(ComisionDB.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    com_map = {c.id: c for c in comisiones_db}
    for c in comisiones_db:
        materias_codigos.add(c.materia_codigo)
    materias_db = list(session.exec(
        select(MateriaDB).where(MateriaDB.codigo.in_(materias_codigos))  # type: ignore[attr-defined]
    ).all()) if materias_codigos else []
    mat_map = {m.codigo: m for m in materias_db}

    for c in clases:
        com = com_map.get(c.comision_id)
        mat_code = com.materia_codigo if com else "?"
        mat = mat_map.get(mat_code)
        dow = c.fecha.weekday()
        if dow >= len(DOW_TO_DIA):
            continue
        dia = DOW_TO_DIA[dow]
        block = TimetableBlock(
            materia_codigo=mat_code,
            materia_nombre=mat.nombre if mat else mat_code,
            comision_nombre=com.nombre if com else "?",
            hora_inicio=c.hora_inicio,
            hora_fin=c.hora_fin,
            virtual=False,
            en_periodo=True,
        )
        grid.setdefault(dia, []).append(block)
    return grid


def _calcular_divergencias(
    session: Session, plan_id: str, aula_id: str, ciclo: CicloDB,
) -> dict:
    """Para cada (horario_id, comision_id) que en algún momento del ciclo
    tuvo ese aula asignada, cuenta en cuántas semanas del ciclo el aula
    fue efectivamente la asignada.

    Devuelve un dict con dos números:
        - n_uniformes: horarios donde TODAS las clases del ciclo apuntan
          a este aula.
        - n_divergentes: horarios donde algunas clases apuntan acá y
          otras a otra aula (o sin aula).
    """
    todas = list(session.exec(
        select(ClaseDB).where(
            ClaseDB.plan_cursada_id == plan_id,
            ClaseDB.fecha >= ciclo.fecha_inicio,
            ClaseDB.fecha <= ciclo.fecha_fin,
        )
    ).all())
    por_horario: dict[str, list[ClaseDB]] = defaultdict(list)
    for c in todas:
        por_horario[c.horario_id].append(c)

    n_uniformes = 0
    n_divergentes = 0
    for hid, lista in por_horario.items():
        aulas = {c.aula_id for c in lista}
        if aulas == {aula_id}:
            n_uniformes += 1
        elif aula_id in aulas:
            n_divergentes += 1
    return {"n_uniformes": n_uniformes, "n_divergentes": n_divergentes}


@st.dialog("Editar asignación de una clase")
def _dialog_cambiar_aula(plan_id: str, clase_id: str) -> None:
    from src.database.connection import get_session
    from src.services.asignacion_aulas_service import (
        aplicar_edicion_manual,
        cambiar_tipo_clase_puntual,
        clases_del_rango,
        get_aulas_disponibles,
        validar_edicion_manual,
    )

    with next(get_session()) as session:
        clase = session.get(ClaseDB, clase_id)
        if clase is None:
            st.error("Clase no encontrada.")
            return
        com = session.get(ComisionDB, clase.comision_id)
        mat_codigo = com.materia_codigo if com else "?"
        mat = session.get(MateriaDB, mat_codigo) if mat_codigo != "?" else None

        st.markdown(
            f"**Materia:** {mat.nombre if mat else mat_codigo}  \n"
            f"**Comisión:** {com.nombre if com else '?'}  \n"
            f"**Tipo actual:** {clase.tipo_clase or 'sin determinar'}  \n"
            f"**Día/Hora:** {clase.fecha.strftime('%a %d/%m')} "
            f"{clase.hora_inicio.strftime('%H:%M')}–"
            f"{clase.hora_fin.strftime('%H:%M')}"
        )
        if clase.aula_id:
            aula_actual = session.get(AulaDB, clase.aula_id)
            if aula_actual:
                sede_actual = session.get(SedeDB, aula_actual.sede_id)
                sede_nombre = sede_actual.nombre if sede_actual else "?"
                st.caption(
                    f"Aula actual: **{sede_nombre} · "
                    f"{aula_actual.nombre}** (cap. {aula_actual.capacidad})"
                )

        modo = st.radio(
            "Alcance del cambio",
            options=[
                "Esta clase puntual",
                "Rango de fechas",
                "De hoy en adelante",
            ],
            index=1,  # Default: rango (esquema semanal completo).
            key=f"dlg_modo_{clase_id}",
            help=(
                "Por default se edita TODO el rango (esquema semanal). "
                "Para cambios de una sola fecha usá 'Esta clase puntual'."
            ),
        )

        # ── Selector de tipo de clase (sólo habilitado en modo puntual)
        tipo_actual = clase.tipo_clase if clase.tipo_clase in (
            "teorica", "laboratorio"
        ) else "teorica"
        nuevo_tipo = st.selectbox(
            "Tipo de clase",
            options=["teorica", "laboratorio"],
            index=["teorica", "laboratorio"].index(tipo_actual),
            key=f"dlg_tipo_{clase_id}",
            help=(
                "Cambiá el tipo sólo si esta clase puntual se va a "
                "dictar excepcionalmente como laboratorio (o como "
                "teórica). Sólo afecta esta fecha; el resto de las "
                "semanas mantiene el tipo original."
            ),
        )
        cambiando_tipo = (
            nuevo_tipo != (clase.tipo_clase or "teorica")
            and clase.tipo_clase is not None
        )
        if cambiando_tipo and modo != "Esta clase puntual":
            st.error(
                "El cambio de tipo de clase sólo se admite con alcance "
                "'Esta clase puntual'. Cambiá el alcance arriba."
            )
            return
        if cambiando_tipo:
            st.warning(
                f"Vas a cambiar el tipo de **{clase.tipo_clase}** → "
                f"**{nuevo_tipo}** sólo para esta clase puntual. La "
                "aula original quedará liberada para esa fecha y franja."
            )

        ciclo_id_clase = clase.plan_cursada_id
        plan = session.get(PlanificacionCursadaDB, ciclo_id_clase)
        ciclo = session.get(CicloDB, plan.ciclo_id) if plan and plan.ciclo_id else None
        fecha_desde: date | None = clase.fecha
        fecha_hasta: date | None = clase.fecha
        if modo == "Rango de fechas" and ciclo:
            c1, c2 = st.columns(2)
            with c1:
                fecha_desde = st.date_input(
                    "Desde",
                    value=ciclo.fecha_inicio,
                    min_value=ciclo.fecha_inicio,
                    max_value=ciclo.fecha_fin,
                    key=f"dlg_fd_{clase_id}",
                )
            with c2:
                fecha_hasta = st.date_input(
                    "Hasta",
                    value=ciclo.fecha_fin,
                    min_value=ciclo.fecha_inicio,
                    max_value=ciclo.fecha_fin,
                    key=f"dlg_fh_{clase_id}",
                )
        elif modo == "De hoy en adelante" and ciclo:
            fecha_desde = date.today()
            fecha_hasta = ciclo.fecha_fin

        clases_a_editar = (
            [clase]
            if modo == "Esta clase puntual"
            else clases_del_rango(
                session, clase_id,
                fecha_desde=fecha_desde, fecha_hasta=fecha_hasta,
            )
        )
        st.caption(f"Se editarán **{len(clases_a_editar)} clase(s)**.")

        # Aulas disponibles según el tipo objetivo (si cambia tipo, usamos
        # ese filtro; si no, dejamos el comportamiento histórico).
        clase_ids = [c.id for c in clases_a_editar]
        aulas_disp = get_aulas_disponibles(
            session, plan_id, clase_ids,
            tipo_objetivo=(nuevo_tipo if cambiando_tipo else None),
        )
        if not aulas_disp:
            st.warning(
                "No hay aulas compatibles disponibles en todas las "
                "fechas y franjas elegidas. Probá un rango más chico "
                "o cambiá el tipo de clase."
            )
            return
        sede_map = _sede_nombre_map(session)
        opciones = {
            a.id: (
                f"{sede_map.get(a.sede_id, '?')} · {a.nombre} "
                f"(cap. {a.capacidad}, {a.tipo})"
            )
            for a in aulas_disp
        }
        sel_aula = st.selectbox(
            "Aula nueva",
            options=list(opciones.keys()),
            format_func=lambda x: opciones[x],
            key=f"dlg_aula_{clase_id}",
        )

        col_ok, col_no = st.columns(2)
        with col_ok:
            if st.button("Confirmar", type="primary", key=f"dlg_ok_{clase_id}"):
                if cambiando_tipo:
                    res = cambiar_tipo_clase_puntual(
                        session, clase.id, nuevo_tipo, sel_aula,
                    )
                    if not res.ok:
                        for e in res.errores:
                            st.error(e)
                        return
                    for w in res.warnings:
                        st.warning(w)
                    st.success(
                        f"Tipo cambiado a **{nuevo_tipo}** y aula "
                        "reasignada para esta clase puntual."
                    )
                    st.rerun()
                else:
                    res = validar_edicion_manual(
                        session, clase_ids, sel_aula,
                    )
                    if not res.ok:
                        for e in res.errores:
                            st.error(e)
                        return
                    for w in res.warnings:
                        st.warning(w)
                    n = aplicar_edicion_manual(
                        session, clase_ids, sel_aula,
                    )
                    st.success(f"{n} clase(s) actualizada(s).")
                    st.rerun()
        with col_no:
            if st.button("Cancelar", key=f"dlg_cancel_{clase_id}"):
                st.rerun()


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


def _aplicar_filtros(
    clases: list[ClaseDB],
    info_por_clase: dict[str, dict],
    filtros: dict,
    aula_map: dict[str, AulaDB],
    sede_map: dict[str, str],
) -> list[ClaseDB]:
    """Filtra una lista de ``ClaseDB`` según el dict de filtros.

    Reglas relevantes:

    - ``comunes_mode='Sólo comunes'``: una materia es común si pertenece
      a más de una carrera. Si además hay carreras seleccionadas, la
      materia debe pertenecer a (cualquiera de) las carreras
      seleccionadas y NO ser exclusiva (es decir, también debe aparecer
      en otra carrera fuera o dentro del set seleccionado, lo que es
      lo mismo que ``len(carreras_codigos) >= 2``).
    - ``comunes_mode='Sólo exclusivas'``: la materia debe pertenecer a
      una única carrera (``len(carreras_codigos) == 1``), y si hay
      carreras seleccionadas debe ser justamente alguna de ellas.
    - ``comunes_mode='Todas'``: sin filtro extra.

    El filtro ``carreras`` (multiselect) sigue actuando como restricción
    independiente: si está seteado, sólo pasan materias que tengan
    intersección con ese set.
    """
    out: list[ClaseDB] = []
    f_carreras: set[str] = set(filtros.get("carreras") or [])
    f_anios: set[int] = set(filtros.get("anios") or [])
    f_cuatris: set[str] = set(filtros.get("cuatris") or [])
    f_tipos: set[str] = set(filtros.get("tipos") or [])
    f_dias: set[str] = set(filtros.get("dias") or [])
    f_sedes: set[str] = set(filtros.get("sedes") or [])
    f_solo_manuales: bool = bool(filtros.get("solo_manuales"))
    f_busca: str = (filtros.get("buscar") or "").strip().lower()
    f_aula: str | None = filtros.get("aula_id")
    f_comunes_mode: str = filtros.get("comunes_mode") or "Todas"

    for c in clases:
        info = info_por_clase.get(c.id, {})
        carr_codes: set[str] = info.get("carreras_codigos", set())
        if f_aula and c.aula_id != f_aula:
            continue
        if f_carreras and not (carr_codes & f_carreras):
            continue
        if f_comunes_mode == "Sólo comunes":
            # Común = aparece en >=2 carreras.
            if len(carr_codes) < 2:
                continue
        elif f_comunes_mode == "Sólo exclusivas":
            if len(carr_codes) != 1:
                continue
        if f_anios and not (info["anios"] & f_anios):
            continue
        if f_cuatris and not (info["cuatris"] & f_cuatris):
            continue
        if f_tipos:
            tipo_label = c.tipo_clase or "sin determinar"
            if tipo_label not in f_tipos:
                continue
        if f_dias:
            dia_label = DOW_NAMES[c.fecha.weekday()] if c.fecha.weekday() < 7 else ""
            if dia_label not in f_dias:
                continue
        if f_sedes:
            aula = aula_map.get(c.aula_id) if c.aula_id else None
            sede_id = aula.sede_id if aula else None
            sede_nombre = sede_map.get(sede_id, "") if sede_id else ""
            if sede_nombre not in f_sedes:
                continue
        if f_solo_manuales and not c.aula_asignada_manualmente:
            continue
        if f_busca:
            mat_codigo = info.get("materia_codigo", "") or ""
            mat_nombre = info.get("materia_nombre", "") or ""
            if (
                f_busca not in mat_codigo.lower()
                and f_busca not in mat_nombre.lower()
            ):
                continue
        out.append(c)
    return out


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
) -> list[dict]:
    """Arma una fila por ``HorarioDB`` leyendo directamente
    ``HorarioDB.aula_id`` (el patrón persistido). NO infiere por
    mayoría sobre ``ClaseDB``; las excepciones puntuales no se ven en
    esta vista (van en otra pestaña).

    Cada fila tiene:
      - id, día, hora_inicio, hora_fin, tipo_clase del horario.
      - aula del patrón (objeto AulaDB o None).
      - info derivada de la materia (carreras, año, cuatri, etc.).
    """
    rows: list[dict] = []
    for h in horarios_db:
        com = com_map.get(h.comision_id)
        mat_codigo = com.materia_codigo if com else (h.codigo_materia or "")
        mat = mat_map.get(mat_codigo) if mat_codigo else None
        carr_info = _carreras_para_clase(mat_codigo, plan_estudio_cache)
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


@st.dialog("Editar aula del patrón semanal")
def _dialog_cambiar_aula_horario(plan_id: str, horario_id: str) -> None:
    """Diálogo para cambiar el aula del PATRÓN (HorarioDB.aula_id).

    Permite además modificar el ``tipo_clase`` del patrón. Los cambios
    se propagan a las ``ClaseDB`` que heredan (no a las que tienen
    excepción manual).
    """
    from src.database.connection import get_session
    from src.database.models import HorarioDB
    from src.services.asignacion_aulas_service import (
        cambiar_aula_horario,
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
            "El cambio afecta el patrón semanal: todas las clases del "
            "horario heredarán la nueva aula. Las excepciones puntuales "
            "previas (clases con override manual) se mantienen."
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

        aulas_disp = get_aulas_disponibles_para_horario(
            session, plan_id, horario_id,
            tipo_objetivo=(nuevo_tipo if cambiando_tipo else None),
        )
        if not aulas_disp:
            st.warning(
                "No hay aulas compatibles libres en esa franja "
                "semanal. Probá cambiar el tipo o liberá el aula "
                "asignada a otro horario."
            )
            return

        sede_map = _sede_nombre_map(session)
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
        # Default = aula actual si sigue disponible, si no la primera.
        default_idx = 0
        if horario.aula_id and horario.aula_id in [a.id for a in aulas_disp]:
            default_idx = opciones.index(horario.aula_id)
        sel_aula = st.selectbox(
            "Aula del patrón",
            options=opciones,
            index=default_idx,
            format_func=lambda x: labels[x],
            key=f"dlg_h_aula_{horario_id}",
        )

        col_ok, col_no = st.columns(2)
        with col_ok:
            if st.button(
                "Confirmar", type="primary",
                key=f"dlg_h_ok_{horario_id}",
            ):
                aula_arg = None if sel_aula == "__NONE__" else sel_aula
                tipo_arg = nuevo_tipo if cambiando_tipo else None
                res = cambiar_aula_horario(
                    session, horario_id, aula_arg, nuevo_tipo=tipo_arg,
                )
                if not res.ok:
                    for e in res.errores:
                        st.error(e)
                    return
                for w in res.warnings:
                    st.warning(w)
                st.success(
                    "Patrón actualizado. Las clases del horario "
                    "(sin excepciones manuales) heredaron el cambio."
                )
                st.rerun()
        with col_no:
            if st.button(
                "Cancelar", key=f"dlg_h_cancel_{horario_id}",
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

    st.subheader("📅 Patrón semanal de aulas")
    st.caption(
        "El LP asigna aulas al patrón semanal (lo que se repite todas "
        "las semanas). Las clases puntuales heredan automáticamente. "
        "Si todavía no corriste el LP, los horarios aparecen como "
        "'Sin asignar' y podés editarlos a mano."
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

    # Filas (1 por HorarioDB), leyendo aula_id directamente del patrón.
    rows = _build_horario_rows_v2(
        horarios_db, com_map, mat_map, aula_map, plan_estudio_cache,
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
        st.markdown("**Cronograma del patrón semanal**")
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
    st.markdown("**Patrón semanal (filtros aplicados)**")
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

    MAX_FILAS = 300
    if len(rows_filtradas) > MAX_FILAS:
        st.caption(
            f"Mostrando los primeros {MAX_FILAS} de "
            f"{len(rows_filtradas)}. Refiná los filtros."
        )
        rows_filtradas = rows_filtradas[:MAX_FILAS]

    for r in rows_filtradas:
        aula = r.get("aula_obj")
        sede_nombre = sede_map.get(aula.sede_id, "?") if aula else "—"
        aula_label = (
            f"{sede_nombre} · {aula.nombre}" if aula else "📭 Sin asignar"
        )
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
