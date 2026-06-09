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


@st.dialog("Cambiar aula de una clase")
def _dialog_cambiar_aula(plan_id: str, clase_id: str) -> None:
    from src.database.connection import get_session
    from src.services.asignacion_aulas_service import (
        aplicar_edicion_manual,
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
            f"**Tipo:** {clase.tipo_clase or 'sin determinar'}  \n"
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
            key=f"dlg_modo_{clase_id}",
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
                    value=clase.fecha,
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

        # Aulas disponibles en TODAS las fechas/franjas elegidas.
        clase_ids = [c.id for c in clases_a_editar]
        aulas_disp = get_aulas_disponibles(session, plan_id, clase_ids)
        if not aulas_disp:
            st.warning(
                "No hay aulas compatibles disponibles en todas las "
                "fechas y franjas elegidas. Probá un rango más chico."
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
                res = validar_edicion_manual(session, clase_ids, sel_aula)
                if not res.ok:
                    for e in res.errores:
                        st.error(e)
                    return
                for w in res.warnings:
                    st.warning(w)
                n = aplicar_edicion_manual(session, clase_ids, sel_aula)
                st.success(f"{n} clase(s) actualizada(s).")
                st.rerun()
        with col_no:
            if st.button("Cancelar", key=f"dlg_cancel_{clase_id}"):
                st.rerun()


def render_aula_cronograma(
    session: Session, plan_id: str, key_ns: str = "aula_crono",
) -> None:
    """Punto de entrada de la vista. Selector de aula + selector de
    semana + calendar."""
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

    st.subheader("📅 Cronograma por aula")

    # Selector de aula: sólo las que tienen al menos una clase asignada.
    aulas_con_clases = list(session.exec(
        select(AulaDB).where(
            AulaDB.id.in_(  # type: ignore[attr-defined]
                select(ClaseDB.aula_id).where(
                    ClaseDB.plan_cursada_id == plan_id,
                    ClaseDB.aula_id.is_not(None),  # type: ignore[union-attr]
                ).distinct()  # type: ignore[attr-defined]
            )
        ).order_by(AulaDB.sede_id, AulaDB.nombre)  # type: ignore[attr-defined]
    ).all())
    if not aulas_con_clases:
        st.info(
            "Ninguna aula tiene clases asignadas todavía. Corré el LP "
            "primero desde el panel de asignación."
        )
        return

    sede_map = _sede_nombre_map(session)
    aula_options = {
        a.id: (
            f"{sede_map.get(a.sede_id, '?')} · {a.nombre} "
            f"(cap. {a.capacidad}, {a.tipo})"
        )
        for a in aulas_con_clases
    }
    sel_aula_id = st.selectbox(
        "Aula",
        options=list(aula_options.keys()),
        format_func=lambda x: aula_options[x],
        key=f"{key_ns}_aula",
    )
    if not sel_aula_id:
        return

    # Indicador de divergencias.
    div = _calcular_divergencias(session, plan_id, sel_aula_id, ciclo)
    cu, cd = st.columns(2)
    cu.metric("Horarios uniformes en el aula", div["n_uniformes"])
    cd.metric("Horarios con divergencias", div["n_divergentes"])
    if div["n_divergentes"] > 0:
        st.caption(
            "⚠️ Hay horarios donde algunas semanas usan esta aula y otras "
            "no (típicamente por ediciones manuales puntuales). "
            "Cambiá la semana abajo para verlos."
        )

    # Selector de semana.
    semanas = _semanas_del_ciclo(ciclo)
    if not semanas:
        st.info("El ciclo no tiene semanas válidas.")
        return
    hoy_lunes = _lunes_de_semana(date.today())
    default_semana = (
        hoy_lunes if hoy_lunes in semanas
        else semanas[0]
    )
    sel_semana = st.selectbox(
        "Semana",
        options=semanas,
        index=semanas.index(default_semana) if default_semana in semanas else 0,
        format_func=lambda d: (
            f"Semana del {d.strftime('%d/%m/%Y')}"
            f" – {(d + timedelta(days=6)).strftime('%d/%m/%Y')}"
        ),
        key=f"{key_ns}_semana",
    )
    if sel_semana is None:
        return

    clases = _clases_de_aula_en_semana(
        session, plan_id, sel_aula_id, sel_semana,
    )
    if not clases:
        st.info("Esta aula no tiene clases asignadas en la semana elegida.")
        return

    grid = _build_timetable_blocks(session, clases)
    config = get_or_create_config(session)
    render_timetable_calendar(
        grid_data=grid,
        config=config,
        key=f"{key_ns}_cal_{sel_aula_id}_{sel_semana.isoformat()}",
    )

    # Listado de clases de la semana con botón "Editar aula" por fila.
    st.markdown("**Clases de la semana en esta aula**")
    com_ids = {c.comision_id for c in clases}
    coms = list(session.exec(
        select(ComisionDB).where(ComisionDB.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    com_map = {c.id: c for c in coms}
    materias_db = list(session.exec(
        select(MateriaDB).where(MateriaDB.codigo.in_({c.materia_codigo for c in coms}))  # type: ignore[attr-defined]
    ).all()) if coms else []
    mat_map = {m.codigo: m for m in materias_db}
    clases_ord = sorted(clases, key=lambda c: (c.fecha, c.hora_inicio))
    for c in clases_ord:
        com = com_map.get(c.comision_id)
        mat = mat_map.get(com.materia_codigo) if com else None
        cola, colb = st.columns([5, 1])
        with cola:
            st.write(
                f"**{c.fecha.strftime('%a %d/%m')}** "
                f"{c.hora_inicio.strftime('%H:%M')}–"
                f"{c.hora_fin.strftime('%H:%M')} · "
                f"{mat.nombre if mat else (com.materia_codigo if com else '?')} "
                f"({com.nombre if com else '?'}) · "
                f"{c.tipo_clase or 'sin determinar'}"
                + (" · ✋ manual" if c.aula_asignada_manualmente else "")
            )
        with colb:
            if st.button(
                "Editar",
                key=f"{key_ns}_edit_{c.id}",
            ):
                _dialog_cambiar_aula(plan_id, c.id)
