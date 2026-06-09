"""Gestion de Planes de Cursada - Hub central de planificacion.

Flujo: Cronograma (schedule) → Validar cobertura → Generar Plan → Clases
"""

import uuid
import streamlit as st
import pandas as pd
from collections import Counter
from datetime import time, timedelta
from sqlmodel import select, func, col
from src.database.connection import get_session, init_db
from src.database.models import (
    PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB, MateriaDB,
    ScheduleDB, ScheduleEntryDB,
    CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
    CarreraDB, ConfiguracionHoraria,
)
from src.database.crud import ciclo_crud, get_or_create_config, update_config
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    generate_plan_from_preview,
    preview_plan_from_schedule,
    activate_plan,
    generate_time_slots,
    build_timetable_grid,
    MateriaPreview,
    EntryPreview,
    SchedulePreviewResult,
)
from src.services.clase_generation_service import generate_clases_for_plan
from src.ui.calendar_render import render_timetable_calendar
from src.domain.types import DIAS_SEMANA

init_db()


def _fmt_hours(h: float) -> str:
    """Format hours: '18h' if integer, '17.5h' otherwise."""
    return f"{h:g}h"


def _parse_minutes(val) -> int | None:
    """Parse a time value to total minutes. Handles time objects and 'HH:MM' strings."""
    if hasattr(val, "hour"):
        return val.hour * 60 + val.minute
    if isinstance(val, str) and ":" in val:
        parts = val.split(":")
        try:
            return int(parts[0]) * 60 + int(parts[1])
        except ValueError:
            return None
    return None


def _time_str(val) -> str:
    """Convert a time value to 'HH:MM' string."""
    if hasattr(val, "strftime"):
        return val.strftime("%H:%M")
    if isinstance(val, str):
        return val[:5]
    return str(val)


_BASE_TIME_OPTIONS = [
    f"{h:02d}:{m:02d}" for h in range(7, 24) for m in (0, 15, 30, 45)
]


st.set_page_config(page_title="Planes de Cursada", page_icon="📊", layout="wide")
st.title("📊 Planes de Cursada")

# =============================================================================
# Data loading
# =============================================================================
with next(get_session()) as session:
    ciclos = ciclo_crud.get_all(session, limit=100)

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}

if not ciclo_ids:
    st.info("No hay ciclos registrados. Crea uno en la pagina de Ciclos.")
    st.stop()

(
    tab_generar, tab_general, tab_detalle, tab_grilla,
    tab_clases, tab_aulas, tab_config,
) = st.tabs([
    "📥 Generar Plan",
    "📋 Vista General", "🔍 Detalle del Plan",
    "📋 Grilla Horaria", "📅 Clases", "🏛️ Aulas", "⚙️ Configuración",
])


# =============================================================================
# Helper: faltantes por carrera (legacy, ya no usado en esta pagina)
# =============================================================================
def _get_faltantes_por_carrera(
    session, ciclo_id: str, materias_en_schedule: set[str],
) -> list[dict]:
    """Return enriched faltantes grouped by carrera with plan info and reasons.

    NOTA: La fuente de verdad para faltantes ahora es
    `src/services/cronograma_validation_service.py::_get_faltantes_por_carrera`,
    que toma como base los dictados activos del ciclo. Este helper queda
    sin uso aca (la pestaña Validacion se movio a Cronogramas) pero se
    deja por si algun consumidor externo lo importaba.
    """
    ciclo = ciclo_crud.get(session, ciclo_id)
    if not ciclo:
        return []
    cuatri_ciclo = f"{ciclo.numero}C"  # "1C" or "2C"

    # Get plan versions linked to this ciclo
    cpv_rows = session.exec(
        select(CicloPlanVersionDB).where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    result = []
    for cpv in cpv_rows:
        pv = session.get(PlanCarreraVersionDB, cpv.plan_version_id)
        if not pv:
            continue
        carrera = session.get(CarreraDB, pv.carrera_codigo)
        if not carrera:
            continue

        # Get all plan_estudio entries for this plan version
        pe_rows = session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.plan_version_id == pv.id)
            .order_by(PlanEstudioDB.anio_plan, PlanEstudioDB.cuatrimestre_plan)
        ).all()

        # Filter to missing materias only
        faltantes_pe = [
            pe for pe in pe_rows
            if pe.materia_codigo not in materias_en_schedule
        ]
        if not faltantes_pe:
            continue

        # Batch load materia info
        falt_codigos = list({pe.materia_codigo for pe in faltantes_pe})
        mats_db = session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(falt_codigos))
        ).all()
        mat_map = {m.codigo: m for m in mats_db}

        materias_faltantes = []
        for pe in faltantes_pe:
            mat = mat_map.get(pe.materia_codigo)
            if not mat:
                continue

            cuatri = pe.cuatrimestre_plan
            if cuatri and cuatri == cuatri_ciclo:
                razon = f"Materia del {cuatri_ciclo}, sin horarios"
            elif cuatri and cuatri.lower() == "anual":
                razon = "Materia anual, se espera en ambos cuatrimestres"
            elif cuatri:
                if carrera.dicta_recursado:
                    razon = f"Es de {cuatri}, incluida por recursado"
                else:
                    razon = f"Es de {cuatri} (carrera no dicta recursado)"
            else:
                razon = "Sin cuatrimestre asignado en el plan"

            materias_faltantes.append({
                "codigo": mat.codigo,
                "nombre": mat.nombre,
                "anio_plan": pe.anio_plan,
                "cuatrimestre_plan": pe.cuatrimestre_plan,
                "optativa": pe.optativa,
                "periodo": mat.periodo,
                "horas_semanales": mat.horas_semanales,
                "virtual": mat.virtual,
                "razon": razon,
            })

        if materias_faltantes:
            result.append({
                "carrera_codigo": carrera.codigo,
                "carrera_nombre": carrera.nombre,
                "plan_version_nombre": pv.nombre,
                "dicta_recursado": carrera.dicta_recursado,
                "materias": materias_faltantes,
            })

    result.sort(key=lambda x: x["carrera_codigo"])
    return result



# =============================================================================
# Helper: render del editor de Plan (reutilizable desde Detalle y desde wizard)
# =============================================================================
def _render_plan_editor(
    sel_plan_id: str, planes_detalle: list, key_ns: str = "detalle",
) -> None:
    """Renderiza el editor del plan: metadata, estadisticas y panel de
    validacion unificado.

    El panel de validacion (`render_validation(source='plan', ...)`)
    incluye cobertura, conflictos de horarios, particion teoria/lab,
    detalle por carrera, detalle por materia con editor inline
    (comisiones, horarios, coef, forecast) y vista calendario.

    Reutilizable desde el tab Detalle (con selector externo) y desde el
    paso 2 del wizard de Generar Plan (con plan_id ya conocido).

    Args:
        sel_plan_id: id del plan a editar.
        planes_detalle: lista de PlanificacionCursadaDB que contiene al
            menos el plan en cuestion (se busca por id).
        key_ns: namespace para las keys de session_state que NO incluyen
            el plan_id. Default "detalle"; el wizard pasa "wizard" para
            evitar colisiones si ambas pestañas se renderean en el mismo run.
    """
    sel_plan = next(p for p in planes_detalle if p.id == sel_plan_id)
    sel_ciclo_detalle = sel_plan.ciclo_id
    
    # --- Editable metadata ---
    st.markdown("#### Metadata")
    with st.form(f"edit_plan_{key_ns}_{sel_plan_id}"):
        nuevo_nombre = st.text_input("Nombre", value=sel_plan.nombre)
        nueva_desc = st.text_area("Descripcion", value=sel_plan.descripcion or "")
    
        # Selector de método de forecast default del plan
        from src.services.forecast_service import (
            METODO_LABELS as _PM_LABELS,
            METODOS_DISPONIBLES as _PM_AVAIL,
        )
        _curr_metodo = sel_plan.forecast_metodo_default or "media_movil"
        _curr_idx = (
            _PM_AVAIL.index(_curr_metodo)
            if _curr_metodo in _PM_AVAIL else 0
        )
        nuevo_metodo = st.selectbox(
            "Método de forecast (default del plan)",
            options=list(_PM_AVAIL),
            index=_curr_idx,
            format_func=lambda m: _PM_LABELS.get(m, m),
            help=(
                "Método aplicado por defecto a todas las materias "
                "del plan al calcular inscriptos esperados. "
                "Editable por materia más abajo (override)."
            ),
        )
        save_meta = st.form_submit_button("Guardar", type="primary")
    
        if save_meta:
            with next(get_session()) as session:
                db_plan = session.get(PlanificacionCursadaDB, sel_plan_id)
                if db_plan:
                    db_plan.nombre = nuevo_nombre
                    db_plan.descripcion = nueva_desc
                    db_plan.forecast_metodo_default = nuevo_metodo
                    session.add(db_plan)
                    session.commit()
                    st.success("Metadata actualizada")
                    st.rerun()
    
    st.divider()
    
    # --- Statistics panel ---
    st.markdown("#### Estadisticas")
    with next(get_session()) as session:
        n_materias = session.exec(
            select(func.count(func.distinct(ComisionDB.materia_codigo)))
            .where(ComisionDB.plan_cursada_id == sel_plan_id)
        ).one()
        n_comisiones = session.exec(
            select(func.count(ComisionDB.id))
            .where(ComisionDB.plan_cursada_id == sel_plan_id)
        ).one()
        n_horarios = session.exec(
            select(func.count(HorarioDB.id))
            .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)
            .where(ComisionDB.plan_cursada_id == sel_plan_id)
        ).one()
        n_clases = session.exec(
            select(func.count(ClaseDB.id))
            .where(ClaseDB.plan_cursada_id == sel_plan_id)
        ).one()
        n_clases_con_aula = session.exec(
            select(func.count(ClaseDB.id))
            .where(ClaseDB.plan_cursada_id == sel_plan_id)
            .where(ClaseDB.aula_id.is_not(None))  # type: ignore[union-attr]
        ).one()
    
    s1, s2, s3, s4, s5 = st.columns(5)
    s1.metric("Materias", n_materias)
    s2.metric("Comisiones", n_comisiones)
    s3.metric("Horarios", n_horarios)
    s4.metric("Clases", n_clases)
    s5.metric("Con Aula", n_clases_con_aula)
    
    st.divider()
    
    # --- Validations panel ---
    st.markdown("#### Validaciones")
    from src.ui.validation_ui import render_validation
    render_validation(
        source="plan",
        plan_id=sel_plan_id,
        key_ns=f"plan_val_{key_ns}_{sel_plan_id}",
    )



# =============================================================================
# Tab 1: Generar Plan (wizard simplificado de 2 pasos)
# =============================================================================
#
# Filosofia:
# - Paso 1: Seleccion (ciclo + cronograma validado + metadata) y crear el plan
#           inmediatamente como borrador (activo=False).
# - Paso 2: Edicion del plan recien creado, embebiendo el editor del tab
#           "Detalle del Plan". El usuario hace los ajustes que quiera.
#           Cancelar = borra el plan en cascada. Confirmar = sale del modo
#           wizard y redirige al tab Detalle con el plan preseleccionado.
#
# Future work: hoy los datos de catalogo (horas_semanales, horas_teoria,
# horas_laboratorio) se muestran read-only en Detalle. Si quisieramos
# permitir overrides por plan sin tocar el catalogo, agregar una tabla
# `PlanMateriaConfigDB(plan_id, materia_codigo, horas_semanales,
# horas_teoria, horas_laboratorio)` consultada cuando el plan los necesita.


def _wizard_reset() -> None:
    """Limpia las keys del wizard."""
    for k in list(st.session_state.keys()):
        if isinstance(k, str) and k.startswith("wizard_"):
            del st.session_state[k]


with tab_generar:
    st.subheader("Generar Plan de Cursada")

    _wizard_plan_id = st.session_state.get("wizard_plan_id")

    # ----- Paso 1: Seleccion + crear borrador -----
    if _wizard_plan_id is None:
        st.markdown("### Paso 1: Seleccionar cronograma y crear borrador")
        st.caption(
            "Solo se pueden usar cronogramas **validados y vigentes** "
            "(sin cambios desde la última validación). Al continuar, se "
            "crea un plan **borrador** (inactivo) con las comisiones y "
            "horarios derivados. En el paso siguiente lo podés editar "
            "libremente sin afectar al cronograma ni al catálogo."
        )

        sel_ciclo_w = st.selectbox(
            "Ciclo",
            options=ciclo_ids,
            key="wizard_sel_ciclo",
        )

        from src.services.cronograma_validation_service import (
            get_latest_validation,
            is_validation_stale,
        )
        from src.services.schedule_service import get_schedules_for_ciclo

        with next(get_session()) as _ws:
            _w_scheds = get_schedules_for_ciclo(_ws, sel_ciclo_w)
            _w_sched_status: dict[str, dict] = {}
            for s in _w_scheds:
                _val = get_latest_validation(_ws, s.id, sel_ciclo_w)
                _stale = (
                    is_validation_stale(_ws, _val) if _val is not None else False
                )
                if _val is None:
                    _badge, _ok = "⚪ Sin validar", False
                elif _stale:
                    _badge, _ok = "🟡 Validado pero desactualizado", False
                else:
                    _badge, _ok = "🟢 Validado y vigente", True
                _w_sched_status[s.id] = {
                    "schedule": s, "badge": _badge, "ok": _ok,
                }

        if not _w_scheds:
            st.info(
                "No hay cronogramas cargados para este ciclo. "
                "Cargá uno desde **📅 Cronogramas**."
            )
        else:
            _w_valid_ids = [
                sid for sid, s in _w_sched_status.items() if s["ok"]
            ]
            if not _w_valid_ids:
                st.warning(
                    "Ningún cronograma del ciclo está validado y vigente. "
                    "Andá a **📅 Cronogramas → ✅ Validar** para habilitar uno."
                )
                for sid, s in _w_sched_status.items():
                    st.markdown(
                        f"- {s['badge']} — **{s['schedule'].nombre}**"
                    )
            else:
                _sel_sched_w = st.selectbox(
                    "Cronograma (solo validados y vigentes)",
                    options=_w_valid_ids,
                    format_func=lambda sid: (
                        f"{_w_sched_status[sid]['badge']} — "
                        f"{_w_sched_status[sid]['schedule'].nombre}"
                    ),
                    key="wizard_sel_sched",
                )

                _no_validos = [
                    (sid, s) for sid, s in _w_sched_status.items()
                    if not s["ok"]
                ]
                if _no_validos:
                    with st.expander(
                        f"Cronogramas no disponibles ({len(_no_validos)})",
                        expanded=False,
                    ):
                        for sid, s in _no_validos:
                            st.markdown(
                                f"- {s['badge']} — **{s['schedule'].nombre}**"
                            )

                st.divider()
                st.markdown("**Datos del plan**")
                _w_nombre = st.text_input(
                    "Nombre del plan",
                    value=f"Plan {sel_ciclo_w} ({_w_sched_status[_sel_sched_w]['schedule'].nombre})",
                    key="wizard_nombre_input",
                )
                _w_descripcion = st.text_area(
                    "Descripción (opcional)",
                    value="",
                    key="wizard_descripcion_input",
                    height=80,
                )

                from src.services.forecast_service import (
                    METODOS_DISPONIBLES as _W_METODOS,
                    METODO_LABELS as _W_M_LABELS,
                )
                _w_metodo = st.selectbox(
                    "Método de forecast por defecto",
                    options=list(_W_METODOS),
                    index=0,
                    format_func=lambda m: _W_M_LABELS.get(m, m),
                    key="wizard_metodo_input",
                    help=(
                        "Se aplica a todas las materias del plan al calcular "
                        "inscriptos esperados. Editable por materia después."
                    ),
                )

                if st.button(
                    "Crear borrador y continuar →",
                    type="primary",
                    key="wizard_create_draft",
                    disabled=not _w_nombre.strip(),
                ):
                    from src.services.plan_generation_service import (
                        preview_plan_from_schedule,
                        generate_plan_from_preview,
                    )
                    with next(get_session()) as _gs:
                        _gen_preview = preview_plan_from_schedule(_gs, _sel_sched_w)
                        _result = generate_plan_from_preview(
                            _gs,
                            _sel_sched_w,
                            _w_nombre.strip(),
                            sel_ciclo_w,
                            _gen_preview.materias,
                            descripcion=_w_descripcion,
                            forecast_metodo_default=_w_metodo,
                        )
                    if _result.errors:
                        for err in _result.errors:
                            st.error(err)
                    else:
                        _new_id = _result.plan.id if _result.plan else None
                        if _new_id:
                            st.session_state["wizard_plan_id"] = _new_id
                            st.toast(
                                f"Borrador creado: {_result.comisiones_created} "
                                f"comision(es), {_result.horarios_created} horario(s)."
                            )
                            st.rerun()

    # ----- Paso 2: Edicion del plan recien creado -----
    else:
        with next(get_session()) as _es:
            _wizard_plan = _es.get(PlanificacionCursadaDB, _wizard_plan_id)
        if _wizard_plan is None:
            st.error(
                "El plan borrador ya no existe. Empezá de nuevo."
            )
            _wizard_reset()
            if st.button("Volver al inicio", key="wizard_back_to_step1"):
                st.rerun()
        else:
            _bc1, _bc2, _bc3 = st.columns([2, 2, 4])
            with _bc1:
                if st.button(
                    "🗑️ Cancelar (borra el plan)",
                    key="wizard_cancel",
                    help=(
                        "Borra el plan borrador y todas sus comisiones, "
                        "horarios y clases. No se puede deshacer."
                    ),
                ):
                    from src.services.plan_generation_service import (
                        delete_plan_cascade,
                    )
                    with next(get_session()) as _ds:
                        delete_plan_cascade(_ds, _wizard_plan_id)
                    _wizard_reset()
                    st.toast("Plan borrador eliminado.")
                    st.rerun()
            with _bc2:
                if st.button(
                    "✅ Confirmar y salir del wizard",
                    type="primary",
                    key="wizard_confirm",
                    help=(
                        "Sale del modo wizard. El plan ya está creado como "
                        "borrador. Activarlo desde Vista General cuando esté listo."
                    ),
                ):
                    # Pre-seleccionar el plan en Detalle
                    st.session_state["planes_sel_ciclo_detalle"] = _wizard_plan.ciclo_id
                    st.session_state["planes_sel_plan"] = _wizard_plan_id
                    _wizard_reset()
                    st.toast("Plan listo. Andá a 🔍 Detalle del Plan para seguir editándolo.")
                    st.rerun()
            with _bc3:
                st.markdown(
                    f"### Editando: **{_wizard_plan.nombre}** "
                    f"<span style='color:#888;font-size:0.85em'>"
                    f"(borrador inactivo)</span>",
                    unsafe_allow_html=True,
                )

            st.caption(
                "💡 Editá comisiones, horarios, tipo de clase, coeficientes "
                "y método de forecast. Los cambios afectan solo a este plan, "
                "no al cronograma ni al catálogo. Si cerrás esta pestaña sin "
                "Confirmar ni Cancelar, el plan queda como borrador en "
                "**Vista General**."
            )
            st.divider()

            # Embeber el editor del plan in-place. La lista pasada como
            # `planes_detalle` solo necesita contener este plan.
            _render_plan_editor(
                _wizard_plan_id, [_wizard_plan], key_ns="wizard",
            )



# =============================================================================
# Tab 3: Vista General
# =============================================================================
with tab_general:
    st.subheader("Vista General de Planes")

    sel_ciclo_general = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_general"
    )

    if sel_ciclo_general:
        with next(get_session()) as session:
            planes = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_general)
            ).all()

        if not planes:
            st.info("No hay planes para este ciclo. Carga un cronograma y genera uno desde la pestana Cronogramas.")
        else:
            for plan in planes:
                status_badge = "🟢 ACTIVO" if plan.activo else "⚪ inactivo"

                with st.container(border=True):
                    col_info, col_metrics, col_actions = st.columns([3, 4, 2])

                    with col_info:
                        st.markdown(f"### {plan.nombre}")
                        st.markdown(f"**Estado:** {status_badge}")
                        st.caption(plan.descripcion or "Sin descripcion")
                        st.caption(f"Schedule: {plan.schedule_id or 'N/A'}")

                    with col_metrics:
                        with next(get_session()) as session:
                            n_comisiones = session.exec(
                                select(func.count(ComisionDB.id))
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_materias = session.exec(
                                select(func.count(func.distinct(ComisionDB.materia_codigo)))
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_horarios = session.exec(
                                select(func.count(HorarioDB.id))
                                .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)
                                .where(ComisionDB.plan_cursada_id == plan.id)
                            ).one()
                            n_clases = session.exec(
                                select(func.count(ClaseDB.id))
                                .where(ClaseDB.plan_cursada_id == plan.id)
                            ).one()

                        m1, m2, m3, m4 = st.columns(4)
                        m1.metric("Materias", n_materias)
                        m2.metric("Comisiones", n_comisiones)
                        m3.metric("Horarios", n_horarios)
                        m4.metric("Clases", n_clases)

                    with col_actions:
                        if not plan.activo:
                            if st.button("Activar", key=f"gen_activate_{plan.id}"):
                                with next(get_session()) as session:
                                    activate_plan(session, plan.id)
                                st.success(f"Plan '{plan.nombre}' activado")
                                st.rerun()

                        if st.button("Eliminar", key=f"gen_delete_{plan.id}", type="secondary"):
                            with next(get_session()) as session:
                                # Delete in FK order: clases → horarios → comisiones → plan
                                clases = session.exec(
                                    select(ClaseDB).where(ClaseDB.plan_cursada_id == plan.id)
                                ).all()
                                for c in clases:
                                    session.delete(c)

                                comisiones = session.exec(
                                    select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)
                                ).all()
                                for com in comisiones:
                                    horarios = session.exec(
                                        select(HorarioDB).where(HorarioDB.comision_id == com.id)
                                    ).all()
                                    for h in horarios:
                                        session.delete(h)
                                    session.delete(com)

                                db_plan = session.get(PlanificacionCursadaDB, plan.id)
                                if db_plan:
                                    session.delete(db_plan)
                                session.commit()
                            st.success(f"Plan '{plan.nombre}' eliminado")
                            st.rerun()

            st.caption(f"Total: {len(planes)} plan(es) para {sel_ciclo_general}")


# =============================================================================
# Tab 3: Detalle del Plan (editable)
# =============================================================================
with tab_detalle:
    st.subheader("Detalle del Plan")

    sel_ciclo_detalle = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_detalle"
    )

    if sel_ciclo_detalle:
        with next(get_session()) as session:
            planes_detalle = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_detalle)
            ).all()

        if not planes_detalle:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options = {p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}" for p in planes_detalle}
            sel_plan_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options.keys()),
                format_func=lambda x: plan_options[x],
                key="planes_sel_plan_detalle"
            )

            if sel_plan_id:
                _render_plan_editor(sel_plan_id, planes_detalle)




# =============================================================================
# Tab 4: Grilla Horaria (visual read-only timetable)
# =============================================================================
with tab_grilla:
    st.subheader("Grilla Horaria")
    st.caption(
        "Editor del plan en formato cronograma semanal. Replica la "
        "funcionalidad de **Cronogramas → Editar** pero opera sobre "
        "los horarios y comisiones del plan. Útil para resolver "
        "conflictos de cursada (superposiciones del mismo cuatri/"
        "carrera) editando directamente en la grilla."
    )

    sel_ciclo_grilla = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_grilla"
    )

    if sel_ciclo_grilla:
        with next(get_session()) as session:
            planes_grilla = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_grilla)
            ).all()

        if not planes_grilla:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options_grilla = {
                p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}"
                for p in planes_grilla
            }
            sel_plan_grilla_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options_grilla.keys()),
                format_func=lambda x: plan_options_grilla[x],
                key="planes_sel_plan_grilla"
            )

            if sel_plan_grilla_id:
                from src.ui.plan_grilla_editor import (
                    render_plan_grilla_editor,
                )
                render_plan_grilla_editor(
                    sel_plan_grilla_id, key_ns="plan_grilla",
                )


# =============================================================================
# Tab 5: Clases
# =============================================================================
with tab_clases:
    st.subheader("Clases del Plan")

    sel_ciclo_clases = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_clases"
    )

    if sel_ciclo_clases:
        with next(get_session()) as session:
            planes_clases = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_clases)
            ).all()

        if not planes_clases:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options_clases = {p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}" for p in planes_clases}
            sel_plan_clases_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options_clases.keys()),
                format_func=lambda x: plan_options_clases[x],
                key="planes_sel_plan_clases"
            )

            if sel_plan_clases_id:
                with next(get_session()) as session:
                    n_clases_total = session.exec(
                        select(func.count(ClaseDB.id))
                        .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                    ).one()

                if n_clases_total == 0:
                    st.info("Este plan no tiene clases generadas.")
                    if st.button("Generar Clases", type="primary", key="btn_generar_clases"):
                        with next(get_session()) as session:
                            result = generate_clases_for_plan(session, sel_plan_clases_id)

                        if result.errors:
                            for err in result.errors:
                                st.error(err)
                        else:
                            st.success(f"{result.clases_created} clases generadas")
                            st.rerun()
                else:
                    # Summary metrics
                    with next(get_session()) as session:
                        n_ejecutadas = session.exec(
                            select(func.count(ClaseDB.id))
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .where(ClaseDB.executed == True)  # noqa: E712
                        ).one()
                        n_con_aula = session.exec(
                            select(func.count(ClaseDB.id))
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .where(ClaseDB.aula_id.is_not(None))  # type: ignore[union-attr]
                        ).one()

                    n_pendientes = n_clases_total - n_ejecutadas

                    c1, c2, c3, c4 = st.columns(4)
                    c1.metric("Total", n_clases_total)
                    c2.metric("Ejecutadas", n_ejecutadas)
                    c3.metric("Pendientes", n_pendientes)
                    c4.metric("Con Aula", n_con_aula)

                    st.divider()

                    # Filterable table
                    with next(get_session()) as session:
                        clases = session.exec(
                            select(ClaseDB)
                            .where(ClaseDB.plan_cursada_id == sel_plan_clases_id)
                            .order_by(ClaseDB.fecha, ClaseDB.hora_inicio)
                        ).all()

                        # Build lookup for comision → materia
                        comision_ids = list({c.comision_id for c in clases})
                        com_materia_map: dict[str, str] = {}
                        com_nombre_map: dict[str, str] = {}
                        if comision_ids:
                            coms = session.exec(
                                select(ComisionDB).where(col(ComisionDB.id).in_(comision_ids))
                            ).all()
                            for com in coms:
                                com_materia_map[com.id] = com.materia_codigo
                                com_nombre_map[com.id] = com.nombre

                    # Filter controls
                    col_f1, col_f2 = st.columns(2)
                    materias_en_clases = sorted(set(com_materia_map.values()))
                    with col_f1:
                        filtro_materia = st.selectbox(
                            "Filtrar por Materia",
                            options=["Todas"] + materias_en_clases,
                            key="clases_filtro_materia"
                        )
                    with col_f2:
                        filtro_estado = st.selectbox(
                            "Filtrar por Estado",
                            options=["Todos", "Ejecutadas", "Pendientes"],
                            key="clases_filtro_estado"
                        )

                    # Apply filters
                    filtered = clases
                    if filtro_materia != "Todas":
                        filtered = [c for c in filtered if com_materia_map.get(c.comision_id) == filtro_materia]
                    if filtro_estado == "Ejecutadas":
                        filtered = [c for c in filtered if c.executed]
                    elif filtro_estado == "Pendientes":
                        filtered = [c for c in filtered if not c.executed]

                    if filtered:
                        clases_data = [{
                            "Fecha": c.fecha.strftime("%d/%m/%Y"),
                            "Dia": c.fecha.strftime("%A"),
                            "Inicio": c.hora_inicio.strftime("%H:%M"),
                            "Fin": c.hora_fin.strftime("%H:%M"),
                            "Materia": com_materia_map.get(c.comision_id, "?"),
                            "Comision": com_nombre_map.get(c.comision_id, "?"),
                            "Ejecutada": "Si" if c.executed else "No",
                            "Aula": c.aula_id or "-",
                        } for c in filtered]
                        st.dataframe(clases_data, use_container_width=True, hide_index=True)
                        st.caption(f"Mostrando {len(filtered)} de {n_clases_total} clases")
                    else:
                        st.info("No hay clases que coincidan con los filtros.")


# =============================================================================
# Tab Aulas: LP de asignacion de aulas
# =============================================================================
with tab_aulas:
    st.subheader("Asignación de aulas")
    sel_ciclo_aulas = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids,
        key="planes_sel_ciclo_aulas",
    )

    if sel_ciclo_aulas:
        with next(get_session()) as session:
            planes_aulas = session.exec(
                select(PlanificacionCursadaDB)
                .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_aulas)
            ).all()

        if not planes_aulas:
            st.info("No hay planes para este ciclo.")
        else:
            plan_options_aulas = {
                p.id: f"{p.nombre} {'[ACTIVO]' if p.activo else ''}"
                for p in planes_aulas
            }
            sel_plan_aulas_id = st.selectbox(
                "Seleccionar Plan",
                options=list(plan_options_aulas.keys()),
                format_func=lambda x: plan_options_aulas[x],
                key="planes_sel_plan_aulas",
            )

            if sel_plan_aulas_id:
                from src.ui.asignacion_panel import render_panel
                with next(get_session()) as session:
                    render_panel(session, sel_plan_aulas_id, key_ns="asig")


# =============================================================================
# Tab 5: Configuración Horaria
# =============================================================================
with tab_config:
    st.subheader("Configuración Horaria")
    st.caption("Parametros globales que afectan la generacion de franjas horarias.")

    with next(get_session()) as session:
        config = get_or_create_config(session)

    with st.form("config_horaria_form"):
        col1, col2 = st.columns(2)

        with col1:
            granularidad = st.number_input(
                "Granularidad (minutos)",
                min_value=5, max_value=60, value=config.granularidad_minutos,
                step=5,
                help="Duración de cada franja horaria en minutos",
            )
            step_td = timedelta(minutes=config.granularidad_minutos)
            hora_inicio = st.time_input(
                "Hora inicio operativo",
                value=config.hora_inicio_operativo,
                step=step_td,
            )

        with col2:
            hora_fin = st.time_input(
                "Inicio última franja",
                value=config.hora_fin_operativo,
                step=step_td,
                help="Hora de inicio de la última franja horaria (ej: 23:00 para cubrir 23:00-00:00)",
            )
            # Parse dias_operativos
            dias_actuales = [d.strip() for d in config.dias_operativos.split(",") if d.strip()]
            all_dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
            dias_seleccionados = st.multiselect(
                "Dias operativos",
                options=all_dias,
                default=[d for d in dias_actuales if d in all_dias],
            )

        save_config = st.form_submit_button("Guardar configuración", type="primary")

        if save_config:
            if hora_fin < hora_inicio:
                st.error("La última franja no puede ser anterior a la hora de inicio")
            elif not dias_seleccionados:
                st.error("Debe seleccionar al menos un dia operativo")
            else:
                with next(get_session()) as session:
                    new_config = ConfiguracionHoraria(
                        id=1,
                        granularidad_minutos=granularidad,
                        hora_inicio_operativo=hora_inicio,
                        hora_fin_operativo=hora_fin,
                        dias_operativos=",".join(dias_seleccionados),
                    )
                    update_config(session, new_config)
                st.success("Configuración guardada")
                st.rerun()

    # --- Preview of generated time slots ---
    st.divider()
    st.markdown("#### Preview de franjas horarias")

    with next(get_session()) as session:
        config = get_or_create_config(session)
    slots = generate_time_slots(config)

    if slots:
        slot_data = [{
            "Franja": i + 1,
            "Inicio": s.strftime("%H:%M"),
            "Fin": e.strftime("%H:%M"),
        } for i, (s, e) in enumerate(slots)]
        st.dataframe(slot_data, use_container_width=True, hide_index=True)
        st.caption(f"{len(slots)} franjas de {config.granularidad_minutos} minutos")
    else:
        st.warning("No se generaron franjas. Verifique la configuración.")
