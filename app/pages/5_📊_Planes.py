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
    CarreraDB, ConfiguracionHoraria, MateriaLaboratorioDB,
)
from src.database.crud import ciclo_crud, materia_crud, get_or_create_config, update_config
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
    get_all_schedules,
    duplicate_schedule,
    sync_preview_edits_to_schedule,
)
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    generate_plan_from_preview,
    preview_plan_from_schedule,
    activate_plan,
    generate_time_slots,
    build_timetable_grid,
    apply_horario_edits,
    MateriaPreview,
    EntryPreview,
    SchedulePreviewResult,
)
from src.services.clase_generation_service import generate_clases_for_plan
from src.services.validations import (
    validar_conflictos_horarios_plan,
    validar_cobertura_plan,
    identificar_virtuales_plan,
    validar_factibilidad_particion_horas,
)
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

tab_cronogramas, tab_generar, tab_general, tab_detalle, tab_grilla, tab_clases, tab_config = st.tabs([
    "🔍 Validación de Cronogramas", "📥 Generar Plan",
    "📋 Vista General", "🔍 Detalle del Plan",
    "📋 Grilla Horaria", "📅 Clases", "⚙️ Configuración",
])


# =============================================================================
# Helper: get materias expected for a ciclo (from plan versions)
# =============================================================================
def _get_materias_esperadas(session, ciclo_id: str) -> dict[str, str]:
    """Return {materia_codigo: materia_nombre} for all materias in plan versions of a ciclo."""
    statement = (
        select(MateriaDB.codigo, MateriaDB.nombre)
        .join(PlanEstudioDB, MateriaDB.codigo == PlanEstudioDB.materia_codigo)
        .join(PlanCarreraVersionDB, PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id)
        .join(CicloPlanVersionDB, PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
        .distinct()
    )
    rows = session.exec(statement).all()
    return {codigo: nombre for codigo, nombre in rows}


def _get_faltantes_por_carrera(
    session, ciclo_id: str, materias_en_schedule: set[str],
) -> list[dict]:
    """Return enriched faltantes grouped by carrera with plan info and reasons.

    Each element is a dict with keys: carrera_codigo, carrera_nombre,
    plan_version_nombre, dicta_recursado, materias (list of dicts with
    codigo, nombre, anio_plan, cuatrimestre_plan, optativa, periodo,
    horas_semanales, virtual, razon).
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
# Tab 1: Validación de Cronogramas
# =============================================================================
with tab_cronogramas:
    st.subheader("Validación de Cronogramas")
    st.caption(
        "Seleccioná un ciclo y un cronograma para prevalidar los datos de "
        "horarios. Podés ajustar comisiones y horarios antes de generar un plan."
    )

    # --- Restore persisted selections (survive page navigation) ---
    _P_CICLO = "_persist_planes_ciclo_crono"
    _P_CRONO = "_persist_planes_cronograma"
    if _P_CICLO in st.session_state and "planes_sel_ciclo_crono" not in st.session_state:
        _v = st.session_state[_P_CICLO]
        if _v in ciclo_ids:
            st.session_state["planes_sel_ciclo_crono"] = _v

    # --- Selection row ---
    _vc_c1, _vc_c2 = st.columns(2)
    with _vc_c1:
        sel_ciclo_crono = st.selectbox(
            "Ciclo",
            options=ciclo_ids,
            key="planes_sel_ciclo_crono",
            help="Ciclo lectivo contra el cual se valida el cronograma.",
        )
    st.session_state[_P_CICLO] = sel_ciclo_crono

    if sel_ciclo_crono:
        # --- Cronograma selector in second column ---
        with next(get_session()) as session:
            schedules = get_schedules_for_ciclo(session, sel_ciclo_crono)

        with _vc_c2:
            if schedules:
                _sched_options = {
                    s.id: f"{s.nombre} ({s.source_filename}, {s.fecha_upload})"
                    for s in schedules
                }
                # Restore cronograma selection if widget key was cleared
                if _P_CRONO in st.session_state and "planes_sel_cronograma" not in st.session_state:
                    _v = st.session_state[_P_CRONO]
                    if _v in _sched_options:
                        st.session_state["planes_sel_cronograma"] = _v

                _sel_sched_id = st.selectbox(
                    "Cronograma",
                    options=list(_sched_options.keys()),
                    format_func=lambda x: _sched_options[x],
                    key="planes_sel_cronograma",
                    help="Cronograma cargado para este ciclo.",
                )
                st.session_state[_P_CRONO] = _sel_sched_id
            else:
                st.info("No hay cronogramas cargados para este ciclo.")
                _sel_sched_id = None

        if not schedules or not _sel_sched_id:
            st.stop()

        # --- Pre-validation button ---
        _prevalidation_key = f"prevalidation_{_sel_sched_id}"
        _preview_key = f"preview_{_sel_sched_id}"

        if st.button(
            "Prevalidar cronograma contra ciclo",
            type="primary",
            key=f"btn_prevalidar_{_sel_sched_id}",
            help=(
                "Analiza el cronograma seleccionado comparando las materias "
                "con las esperadas por los planes de estudio del ciclo."
            ),
        ):
            with next(get_session()) as session:
                _entries = get_schedule_entries(session, _sel_sched_id)
                _esperadas = _get_materias_esperadas(session, sel_ciclo_crono)
                _mat_codigos = list({e.codigo_materia for e in _entries})
                _mat_map: dict[str, str] = {}
                if _mat_codigos:
                    _mats = session.exec(
                        select(MateriaDB).where(
                            col(MateriaDB.codigo).in_(_mat_codigos)
                        )
                    ).all()
                    _mat_map = {m.codigo: m.nombre for m in _mats}

                _materias_en_sched = {e.codigo_materia for e in _entries}
                _cubiertas = _materias_en_sched & set(_esperadas.keys())
                _faltantes_set = set(_esperadas.keys()) - _materias_en_sched
                _extra = _materias_en_sched - set(_esperadas.keys())
                _faltantes_por_carrera = _get_faltantes_por_carrera(
                    session, sel_ciclo_crono, _materias_en_sched,
                )

                # Compute totals
                _total_clases = len(_entries)
                _total_horas = 0.0
                for _e in _entries:
                    _mins = (
                        _e.hora_fin.hour * 60 + _e.hora_fin.minute
                        - _e.hora_inicio.hour * 60 - _e.hora_inicio.minute
                    )
                    _total_horas += max(0, _mins) / 60

                # Particion-de-horas feasibility check
                _part_result = validar_factibilidad_particion_horas(
                    session, schedule_id=_sel_sched_id,
                )

            st.session_state[_prevalidation_key] = {
                "n_materias": len(_mat_codigos),
                "n_clases": _total_clases,
                "total_horas": _total_horas,
                "n_esperadas": len(_esperadas),
                "n_cubiertas": len(_cubiertas),
                "n_faltantes": len(_faltantes_set),
                "faltantes_por_carrera": _faltantes_por_carrera,
                "extra": [
                    {"codigo": cod, "nombre": _mat_map.get(cod, "?")}
                    for cod in sorted(_extra)
                ],
                "esperadas": _esperadas,
                "mat_map": _mat_map,
                "schedule_entry_count": _total_clases,
                "particion_valid": _part_result.valid,
                "particion_message": _part_result.message,
                "particion_details": list(_part_result.details or []),
            }
            # Clear any previous preview when re-prevalidating
            st.session_state.pop(_preview_key, None)
            st.rerun()

        # =====================================================================
        # Phase 1: Pre-validation results
        # =====================================================================
        if _prevalidation_key not in st.session_state:
            st.stop()

        _pv = st.session_state[_prevalidation_key]

        # --- Staleness check for Phase 1 ---
        _stored_pv_count = _pv.get("schedule_entry_count")
        if _stored_pv_count is not None:
            with next(get_session()) as _stale_sess:
                _current_pv_count = _stale_sess.exec(
                    select(func.count(ScheduleEntryDB.id))
                    .where(ScheduleEntryDB.schedule_id == _sel_sched_id)
                ).one()
            if _current_pv_count != _stored_pv_count:
                st.warning(
                    f"El cronograma fue modificado desde la \u00faltima "
                    f"prevalidaci\u00f3n ({_stored_pv_count} \u2192 "
                    f"{_current_pv_count} entradas). "
                    f"Presion\u00e1 **Prevalidar** para actualizar."
                )

        st.divider()
        st.markdown("### Resumen de cobertura")

        _pv_c1, _pv_c2, _pv_c3, _pv_c4, _pv_c5, _pv_c6 = st.columns(6)
        _pv_c1.metric("Materias", _pv["n_materias"])
        _pv_c2.metric("Clases", _pv["n_clases"])
        _pv_c3.metric("Horas cronograma", _fmt_hours(_pv['total_horas']))
        _pv_c4.metric("Esperadas", _pv["n_esperadas"])
        _pv_c5.metric("Cubiertas", f"{_pv['n_cubiertas']}/{_pv['n_esperadas']}")
        _pv_c6.metric("Faltantes", _pv["n_faltantes"])

        # --- Materias faltantes (per carrera expanders) ---
        _fpc = _pv["faltantes_por_carrera"]
        # Guard: invalidate stale session_state with old dict format
        if isinstance(_fpc, dict):
            st.warning("Datos de prevalidacion desactualizados. Presiona 'Prevalidar' de nuevo.")
            _fpc = []
        if _fpc:
            st.markdown(f"**Materias faltantes ({_pv['n_faltantes']})**")
            for _ci in _fpc:
                _n_fc = len(_ci["materias"])
                _rec_tag = " · dicta recursado" if _ci["dicta_recursado"] else ""
                _exp_lbl = (
                    f"{_ci['carrera_nombre']} ({_ci['carrera_codigo']}) "
                    f"— Plan: {_ci['plan_version_nombre']} "
                    f"— {_n_fc} faltante(s){_rec_tag}"
                )
                with st.expander(_exp_lbl, expanded=False):
                    _ft_rows = []
                    for _mf in _ci["materias"]:
                        _anio = f"{_mf['anio_plan']}°" if _mf["anio_plan"] else "—"
                        _cuatri = _mf["cuatrimestre_plan"] or "—"
                        _tags = []
                        if _mf["optativa"]:
                            _tags.append("optativa")
                        if _mf["virtual"]:
                            _tags.append("virtual")
                        if _mf["periodo"] == "anual":
                            _tags.append("anual")
                        _ft_rows.append({
                            "Código": _mf["codigo"],
                            "Nombre": _mf["nombre"],
                            "Año": _anio,
                            "Cuatri": _cuatri,
                            "h/sem": _mf["horas_semanales"] or "—",
                            "Notas": ", ".join(_tags) if _tags else "",
                            "Razón": _mf["razon"],
                        })
                    st.dataframe(
                        pd.DataFrame(_ft_rows),
                        use_container_width=True,
                        hide_index=True,
                    )

        # --- Particion de horas (teoria/laboratorio) ---
        _part_valid = _pv.get("particion_valid")
        if _part_valid is not None:
            _part_msg = _pv.get("particion_message", "")
            _part_dets = _pv.get("particion_details") or []
            if _part_valid:
                st.success(f"Partición teoría/lab: {_part_msg}")
            else:
                st.error(f"Partición teoría/lab: {_part_msg}")
                if _part_dets:
                    with st.expander(
                        f"Detalle de particiones infactibles ({len(_part_dets)})",
                        expanded=False,
                    ):
                        for _d in _part_dets:
                            st.markdown(f"- {_d}")

        # --- Materias extras (collapsed) ---
        if _pv["extra"]:
            with st.expander(
                f"Materias no esperadas ({len(_pv['extra'])})", expanded=False,
            ):
                for _ex in _pv["extra"]:
                    st.markdown(f"- {_ex['nombre']} (`{_ex['codigo']}`)")

        # --- Original/copy toggle (once, global) ---
        _save_as_copy = st.toggle(
            "Guardar cambios como copia del cronograma",
            value=st.session_state.get("save_as_copy", False),
            key="save_as_copy",
            help=(
                "Si esta activo, al guardar se crea una copia del cronograma "
                "con las modificaciones, sin alterar el original."
            ),
        )
        if _save_as_copy:
            _sel_sched_obj = next(
                (s for s in schedules if s.id == _sel_sched_id), None
            )
            _default_copy_name = (
                f"{_sel_sched_obj.nombre} (ajustado)"
                if _sel_sched_obj
                else "Copia"
            )
            st.text_input(
                "Nombre de la copia",
                value=st.session_state.get("copy_name", _default_copy_name),
                key="copy_name",
            )

        # --- Preview button ---
        if st.button(
            "Prevalidar y Visualizar Comisiones",
            type="primary",
            key=f"btn_visualizar_{_sel_sched_id}",
            help="Genera la previsualizacion de comisiones a partir del cronograma.",
        ):
            with next(get_session()) as session:
                _prev_result = preview_plan_from_schedule(session, _sel_sched_id)

                # Build materia → carrera/año/cuatri mapping for grouping
                _pv_ids = session.exec(
                    select(CicloPlanVersionDB.plan_version_id)
                    .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_crono)
                ).all()
                _pe_rows = session.exec(
                    select(
                        PlanEstudioDB.materia_codigo,
                        PlanEstudioDB.carrera_codigo,
                        PlanEstudioDB.anio_plan,
                        PlanEstudioDB.cuatrimestre_plan,
                    )
                    .where(PlanEstudioDB.plan_version_id.in_(_pv_ids))
                ).all() if _pv_ids else []
                # materia → list of (carrera, anio, cuatri)
                _mat_carreras: dict[str, list[dict]] = {}
                for _mc, _cc, _anio, _cuatri in _pe_rows:
                    _mat_carreras.setdefault(_mc, []).append({
                        "carrera": _cc, "anio": _anio,
                        "cuatrimestre": _cuatri,
                    })
                # Carrera names
                _all_carr_codes = list({_cc for _mc, _cc, _, _ in _pe_rows})
                _carr_names: dict[str, str] = {}
                if _all_carr_codes:
                    _carr_db = session.exec(
                        select(CarreraDB).where(
                            col(CarreraDB.codigo).in_(_all_carr_codes)
                        )
                    ).all()
                    _carr_names = {c.codigo: c.nombre for c in _carr_db}

            if _prev_result.errors:
                for _err in _prev_result.errors:
                    st.error(_err)
            else:
                # Clear cached widget values from previous preview
                _stale_prefixes = (
                    f"prev_hsem_{_sel_sched_id}_",
                    f"prev_ncom_{_sel_sched_id}_",
                    f"prev_ecom_{_sel_sched_id}_",
                    f"prev_entries_{_sel_sched_id}_",
                    f"_init_df_{_sel_sched_id}_",
                    f"_has_changes_{_sel_sched_id}_",
                    f"_chk_worst_{_sel_sched_id}_",
                    f"_saved_com_{_sel_sched_id}_",
                    f"_reassign_msg_{_sel_sched_id}_",
                )
                for _sk in list(st.session_state.keys()):
                    if isinstance(_sk, str) and any(
                        _sk.startswith(p) for p in _stale_prefixes
                    ):
                        del st.session_state[_sk]

                # Store as dicts for serialization
                st.session_state[_preview_key] = {
                    "materias": [
                        {
                            "materia_codigo": mp.materia_codigo,
                            "materia_nombre": mp.materia_nombre,
                            "horas_semanales": mp.horas_semanales,
                            "total_horas_schedule": mp.total_horas_schedule,
                            "n_comisiones": mp.n_comisiones,
                            "max_clases_paralelas": mp.max_clases_paralelas,
                            "flag": mp.flag,
                            "flag_detail": mp.flag_detail,
                            "entries": [
                                {
                                    "entry_id": ep.entry_id,
                                    "dia": ep.dia,
                                    "hora_inicio": ep.hora_inicio,
                                    "hora_fin": ep.hora_fin,
                                    "comision_asignada": ep.comision_asignada,
                                }
                                for ep in mp.entries
                            ],
                        }
                        for mp in _prev_result.materias
                    ],
                    "mat_carreras": _mat_carreras,
                    "carrera_nombres": _carr_names,
                    "schedule_entry_count": sum(
                        len(mp.entries) for mp in _prev_result.materias
                    ),
                }
                st.rerun()

        # =====================================================================
        # Phase 2: Preview comisiones
        # =====================================================================
        if _preview_key not in st.session_state:
            st.stop()

        _preview_data = st.session_state[_preview_key]
        _materias_preview = _preview_data["materias"]
        _mat_carreras = _preview_data.get("mat_carreras", {})
        _carrera_nombres = _preview_data.get("carrera_nombres", {})

        # --- Staleness check for Phase 2 ---
        _is_stale = False
        _stored_prev_count = _preview_data.get("schedule_entry_count")
        if _stored_prev_count is not None:
            with next(get_session()) as _stale_sess2:
                _current_prev_count = _stale_sess2.exec(
                    select(func.count(ScheduleEntryDB.id))
                    .where(ScheduleEntryDB.schedule_id == _sel_sched_id)
                ).one()
            if _current_prev_count != _stored_prev_count:
                _is_stale = True

        st.divider()
        st.markdown("### Previsualizacion de comisiones")
        if _is_stale:
            st.error(
                f"\u26a0\ufe0f El cronograma fue modificado desde la "
                f"\u00faltima previsualizaci\u00f3n ({_stored_prev_count}"
                f" \u2192 {_current_prev_count} entradas). "
                f"Los datos mostrados pueden estar desactualizados. "
                f"**Guardar est\u00e1 deshabilitado** para evitar "
                f"sobreescribir cambios. Presion\u00e1 "
                f"'Prevalidar y Visualizar Comisiones' para actualizar."
            )

        _n_flagged = sum(
            1 for mp in _materias_preview
            if mp["flag"] in ("uncertain", "no_data", "needs_more_comisiones")
        )
        _n_total = len(_materias_preview)
        _total_comisiones = sum(mp["n_comisiones"] for mp in _materias_preview)

        _mc1, _mc2, _mc3 = st.columns(3)
        _mc1.metric("Materias", _n_total)
        _mc2.metric("Comisiones totales", _total_comisiones)
        _mc3.metric("Requieren revision", _n_flagged)

        if _n_flagged > 0:
            st.warning(
                f"{_n_flagged} materia(s) tienen derivacion incierta. "
                f"Revisa y corregi antes de generar el plan."
            )

        # --- Build per-materia index for fast lookup ---
        _mp_by_code = {mp["materia_codigo"]: (_i, mp) for _i, mp in enumerate(_materias_preview)}

        # --- Batch-read horas_semanales/teoria/laboratorio, optativa, labs ---
        _all_mat_codes = [mp["materia_codigo"] for mp in _materias_preview]
        with next(get_session()) as _batch_session:
            _batch_mats = _batch_session.exec(
                select(
                    MateriaDB.codigo,
                    MateriaDB.horas_semanales,
                    MateriaDB.horas_teoria,
                    MateriaDB.horas_laboratorio,
                )
                .where(col(MateriaDB.codigo).in_(_all_mat_codes))
            ).all() if _all_mat_codes else []
            # Optativa: a materia is optativa if ANY plan_estudio entry marks it
            _opt_rows = _batch_session.exec(
                select(PlanEstudioDB.materia_codigo)
                .where(
                    PlanEstudioDB.materia_codigo.in_(_all_mat_codes),
                    PlanEstudioDB.optativa == True,
                )
                .distinct()
            ).all() if _all_mat_codes else []
            # Materias que tienen al menos un laboratorio compatible asignado
            _lab_rows = _batch_session.exec(
                select(MateriaLaboratorioDB.materia_codigo)
                .where(col(MateriaLaboratorioDB.materia_codigo).in_(_all_mat_codes))
                .distinct()
            ).all() if _all_mat_codes else []
        _hsem_map = {cod: float(h) if h else 0.0 for cod, *_ in _batch_mats}
        _hteo_map = {
            cod: float(ht) if ht is not None else None
            for cod, _hs, ht, _hl in _batch_mats
        }
        _hlab_map = {
            cod: float(hl) if hl is not None else None
            for cod, _hs, _ht, hl in _batch_mats
        }
        _optativa_set: set[str] = set(_opt_rows)
        _labs_set: set[str] = set(_lab_rows)

        def _precheck_status(mp_data, db_hsem):
            """Quick pre-check returning worst status: 'ok', 'warn', 'error', 'no_data'."""
            _issues = []
            _t = mp_data["total_horas_schedule"]
            _n = mp_data["n_comisiones"]
            _p = mp_data["max_clases_paralelas"]
            if db_hsem == 0:
                _issues.append("no_data")
            elif db_hsem > 0 and _t > 0:
                _expected = _n * db_hsem
                if abs(_expected - _t) > 0.01:
                    _issues.append("hsem_mismatch")
            if _p > _n:
                _issues.append("paralelas")
            if "paralelas" in _issues:
                return "error"
            elif "no_data" in _issues:
                return "no_data"
            elif _issues:
                return "warn"
            else:
                return "ok"

        _mp_status = {}
        for _mc, (_idx, _mpd) in _mp_by_code.items():
            _mp_status[_mc] = _precheck_status(_mpd, _hsem_map.get(_mc, 0.0))

        # --- Build faltantes data for Phase 2 display ---
        _faltantes_flat: dict[str, dict] = {}
        _faltantes_carreras: dict[str, list[dict]] = {}
        _fpc_phase2 = st.session_state.get(_prevalidation_key, {}).get(
            "faltantes_por_carrera", []
        )
        if isinstance(_fpc_phase2, list):
            for _ci in _fpc_phase2:
                for _mf in _ci["materias"]:
                    _mc = _mf["codigo"]
                    if _mc in _mp_by_code:
                        continue  # already in schedule
                    if _mc not in _faltantes_flat:
                        _faltantes_flat[_mc] = {
                            "materia_codigo": _mc,
                            "materia_nombre": _mf["nombre"],
                            "horas_semanales": _mf["horas_semanales"] or 0,
                            "optativa": _mf.get("optativa", False),
                            "virtual": _mf.get("virtual", False),
                            "periodo": _mf.get("periodo", "cuatrimestral"),
                        }
                    _faltantes_carreras.setdefault(_mc, []).append({
                        "carrera": _ci["carrera_codigo"],
                        "anio": _mf["anio_plan"],
                        "cuatrimestre": _mf["cuatrimestre_plan"],
                    })

        # Add faltantes optativas to the set
        for _fmc, _fdata in _faltantes_flat.items():
            if _fdata.get("optativa"):
                _optativa_set.add(_fmc)

        # --- Summary table per carrera ---
        _carrera_summary_rows = []
        _all_carrera_codes = sorted(_carrera_nombres.keys())
        for _cc in _all_carrera_codes:
            # Find materias for this carrera that are in the preview
            _cc_mats = set()
            for _mc, _locs in _mat_carreras.items():
                if any(loc["carrera"] == _cc for loc in _locs):
                    _cc_mats.add(_mc)
            _cc_in_preview = [c for c in _cc_mats if c in _mp_by_code]
            # Count faltantes for this carrera
            _cc_falt_mats = set()
            for _fmc, _flocs in _faltantes_carreras.items():
                if any(fl["carrera"] == _cc for fl in _flocs):
                    _cc_falt_mats.add(_fmc)
            _cc_falt_count = len(_cc_falt_mats)
            if not _cc_in_preview and _cc_falt_count == 0:
                continue
            _cc_ok = sum(1 for c in _cc_in_preview if _mp_status.get(c) == "ok")
            _cc_warn = sum(1 for c in _cc_in_preview if _mp_status.get(c) == "warn")
            _cc_error = sum(1 for c in _cc_in_preview if _mp_status.get(c) == "error")
            _cc_nodata = sum(1 for c in _cc_in_preview if _mp_status.get(c) == "no_data")
            _carrera_summary_rows.append({
                "Carrera": _cc,
                "Nombre": _carrera_nombres.get(_cc, ""),
                "Materias": len(_cc_in_preview),
                "\u2705": _cc_ok,
                "\u26a0\ufe0f": _cc_warn,
                "\U0001f53a": _cc_error,
                "\u2753": _cc_nodata,
                "\U0001f4ed": _cc_falt_count,
            })

        if _carrera_summary_rows:
            st.markdown("#### Resumen por carrera")
            st.dataframe(
                pd.DataFrame(_carrera_summary_rows),
                use_container_width=True,
                hide_index=True,
            )
            st.caption(
                "\u2705 Todo OK · "
                "\u26a0\ufe0f Requiere revisi\u00f3n · "
                "\U0001f53a Error (clases paralelas > comisiones) · "
                "\u2753 Sin dato de horas semanales · "
                "\U0001f4ed Faltantes (sin horarios en cronograma)"
            )

        # --- Pre-compute materia → set of distinct carreras (for comunes/exclusivas) ---
        _mat_carrera_set: dict[str, set[str]] = {}
        for _mc, _locs in _mat_carreras.items():
            _mat_carrera_set[_mc] = {loc["carrera"] for loc in _locs}

        # --- Filters ---
        st.markdown("#### Filtros")
        _pf1, _pf2, _pf3, _pf4 = st.columns(4)
        with _pf1:
            _prev_carrera_opts = ["Todas"] + [
                f"{r['Carrera']} - {r['Nombre']}"
                for r in _carrera_summary_rows
            ]
            _prev_filt_carrera = st.selectbox(
                "Carrera", options=_prev_carrera_opts,
                index=0,
                key=f"prev_filt_carrera_{_sel_sched_id}",
            )
        with _pf2:
            _prev_filt_anio = st.selectbox(
                "A\u00f1o", options=["Todos", 1, 2, 3, 4, 5, 6],
                index=0,
                key=f"prev_filt_anio_{_sel_sched_id}",
            )
        with _pf3:
            _prev_filt_cuatri = st.selectbox(
                "Cuatrimestre",
                options=["Todos", "1C", "2C", "Anual"],
                index=0,
                key=f"prev_filt_cuatri_{_sel_sched_id}",
            )
        with _pf4:
            _prev_filt_tipo = st.selectbox(
                "Tipo",
                options=["Todas", "Comunes", "Exclusivas"],
                index=0,
                key=f"prev_filt_tipo_{_sel_sched_id}",
                help=(
                    "Comunes: materias compartidas entre 2+ carreras. "
                    "Exclusivas: materias de una sola carrera."
                ),
            )

        _tf1, _tf2, _tf3 = st.columns(3)
        with _tf1:
            _show_faltantes = st.toggle(
                "Incluir faltantes",
                value=False,
                key=f"prev_filt_faltantes_{_sel_sched_id}",
                help="Mostrar materias faltantes del plan para poder cargar sus horarios.",
            )
        with _tf2:
            _hide_optativas = st.toggle(
                "Excluir optativas",
                value=False,
                key=f"prev_filt_optativas_{_sel_sched_id}",
                help="Ocultar materias marcadas como optativas/electivas en el plan de estudios.",
            )
        with _tf3:
            _only_with_lab = st.toggle(
                "Solo con lab asignado",
                value=False,
                key=f"prev_filt_lab_{_sel_sched_id}",
                help=(
                    "Mostrar unicamente materias que tienen al menos un "
                    "laboratorio compatible asignado en MateriaLaboratorioDB."
                ),
            )

        # Resolve filter values
        _filt_cc = None if _prev_filt_carrera == "Todas" else _prev_filt_carrera.split(" - ")[0]
        _filt_anio = None if _prev_filt_anio == "Todos" else int(_prev_filt_anio)
        _filt_cuatri = None if _prev_filt_cuatri == "Todos" else _prev_filt_cuatri

        # Find materia codes matching carrera/año/cuatri filters
        _filtered_codes: set[str] = set()
        for _mc, _locs in _mat_carreras.items():
            for _loc in _locs:
                _cc_ok = _filt_cc is None or _loc["carrera"] == _filt_cc
                _anio_ok = _filt_anio is None or _loc["anio"] == _filt_anio
                _cuatri_ok = _filt_cuatri is None or _loc["cuatrimestre"] == _filt_cuatri
                if _cc_ok and _anio_ok and _cuatri_ok:
                    _filtered_codes.add(_mc)
                    break

        # Apply comunes/exclusivas filter
        if _prev_filt_tipo == "Comunes":
            _filtered_codes = {
                c for c in _filtered_codes
                if len(_mat_carrera_set.get(c, set())) > 1
            }
        elif _prev_filt_tipo == "Exclusivas":
            _filtered_codes = {
                c for c in _filtered_codes
                if len(_mat_carrera_set.get(c, set())) == 1
            }

        # Filter faltantes with same criteria
        _filtered_faltantes: set[str] = set()
        if _show_faltantes:
            _falt_carrera_set: dict[str, set[str]] = {
                mc: {l["carrera"] for l in locs}
                for mc, locs in _faltantes_carreras.items()
            }
            for _mc, _locs in _faltantes_carreras.items():
                for _loc in _locs:
                    _cc_ok = _filt_cc is None or _loc["carrera"] == _filt_cc
                    _anio_ok = _filt_anio is None or _loc["anio"] == _filt_anio
                    _cuatri_ok = _filt_cuatri is None or _loc["cuatrimestre"] == _filt_cuatri
                    if _cc_ok and _anio_ok and _cuatri_ok:
                        _filtered_faltantes.add(_mc)
                        break
            # Apply comunes/exclusivas to faltantes too
            if _prev_filt_tipo == "Comunes":
                _filtered_faltantes = {
                    c for c in _filtered_faltantes
                    if len(_falt_carrera_set.get(c, set())) > 1
                }
            elif _prev_filt_tipo == "Exclusivas":
                _filtered_faltantes = {
                    c for c in _filtered_faltantes
                    if len(_falt_carrera_set.get(c, set())) == 1
                }

        # Apply optativas filter to both sets
        if _hide_optativas:
            _filtered_codes = {
                c for c in _filtered_codes if c not in _optativa_set
            }
            _filtered_faltantes = {
                c for c in _filtered_faltantes if c not in _optativa_set
            }

        # Apply "solo con lab asignado" filter
        if _only_with_lab:
            _filtered_codes = {c for c in _filtered_codes if c in _labs_set}
            _filtered_faltantes = {
                c for c in _filtered_faltantes if c in _labs_set
            }

        # Build sorted display list: only materias in preview AND matching filter
        _display_indices = sorted(
            [_mp_by_code[c][0] for c in _filtered_codes if c in _mp_by_code]
        )

        if not _display_indices and not _filtered_faltantes:
            st.info("No hay materias para estos filtros.")
            st.stop()

        # Build description text
        _filt_parts = []
        _filt_parts.append(_filt_cc if _filt_cc else "Todas las carreras")
        if _filt_anio is not None:
            _filt_parts.append(f"{_filt_anio}\u00b0 a\u00f1o")
        if _filt_cuatri is not None:
            _filt_parts.append(_filt_cuatri)
        if _prev_filt_tipo != "Todas":
            _filt_parts.append(_prev_filt_tipo.lower())
        _count_text = f"**{len(_display_indices)} materia(s)**"
        if _filtered_faltantes:
            _count_text += f" + {len(_filtered_faltantes)} faltante(s)"
        st.markdown(
            f"{_count_text} \u2014 "
            f"{' \u00b7 '.join(_filt_parts)}"
        )

        # --- Render filtered materias ---
        for _mp_idx in _display_indices:
            mp = _materias_preview[_mp_idx]
            _mat_code = mp["materia_codigo"]
            # --- Compute live header icon from current state ---
            _cur_ncom = st.session_state.get(
                f"prev_ncom_{_sel_sched_id}_{_mat_code}", mp["n_comisiones"]
            )
            _db_hsem = _hsem_map.get(mp["materia_codigo"], 0.0)
            _cur_total = mp["total_horas_schedule"]
            _cur_paralelas = mp["max_clases_paralelas"]

            # Use cached worst check status from previous render if available
            _cached_worst = st.session_state.get(
                f"_chk_worst_{_sel_sched_id}_{_mat_code}"
            )
            if _cached_worst:
                _icon_map = {
                    "ok": ("\u2705", False),
                    "warn": ("\u26a0\ufe0f", True),
                    "error": ("\U0001f53a", True),
                    "info": ("\u2753", True),
                }
                _live_icon, _live_expand = _icon_map.get(
                    _cached_worst, ("\u2705", False)
                )
            else:
                # Quick pre-checks for header icon (first render only)
                _hdr_issues = []
                if _db_hsem == 0:
                    _hdr_issues.append("no_data")
                elif _db_hsem > 0 and _cur_total > 0:
                    _expected = _cur_ncom * _db_hsem
                    if abs(_expected - _cur_total) > 0.01:
                        _hdr_issues.append("hsem_mismatch")
                if _cur_paralelas > _cur_ncom:
                    _hdr_issues.append("paralelas")

                if "paralelas" in _hdr_issues:
                    _live_icon = "\U0001f53a"
                    _live_expand = True
                elif "no_data" in _hdr_issues:
                    _live_icon = "\u2753"
                    _live_expand = True
                elif _hdr_issues:
                    _live_icon = "\u26a0\ufe0f"
                    _live_expand = True
                else:
                    _live_icon = "\u2705"
                    _live_expand = False

            _header = (
                f"{_live_icon} {mp['materia_codigo']} \u2014 "
                f"{mp['materia_nombre']} | "
                f"{_cur_ncom} com \u00b7 {_fmt_hours(_cur_total)} \u00b7 "
                f"h/sem: {_fmt_hours(_db_hsem) if _db_hsem > 0 else '?'}"
            )

            with st.expander(_header, expanded=_live_expand):
                # --- a) Horas semanales (reference only) ---
                _dia_ord = {
                    "Lunes": 0, "Martes": 1, "Mi\u00e9rcoles": 2,
                    "Jueves": 3, "Viernes": 4, "S\u00e1bado": 5,
                }
                ic1, ic2, ic3, ic4 = st.columns(4)
                ic1.markdown("**Horas semanales:**")
                _display_hsem = ic2.number_input(
                    "h/sem",
                    value=_db_hsem,
                    min_value=0.0,
                    step=0.25,
                    format="%.2f",
                    key=f"prev_hsem_{_sel_sched_id}_{_mat_code}",
                    label_visibility="collapsed",
                )
                # Auto-save when value changes (no rerun to preserve edits)
                if _display_hsem != _db_hsem:
                    with next(get_session()) as _sess:
                        _mat = materia_crud.get(_sess, _mat_code)
                        if _mat:
                            _mat.horas_semanales = (
                                _display_hsem if _display_hsem > 0 else None
                            )
                            _sess.add(_mat)
                            _sess.commit()
                            _hsem_map[_mat_code] = _display_hsem
                            mp["horas_semanales"] = _display_hsem
                            _db_hsem = _display_hsem
                            st.toast(
                                f"{_mat_code}: horas semanales "
                                f"actualizadas a {_fmt_hours(_display_hsem)}."
                            )

                # --- a.2) Horas teoria / laboratorio (solo si tiene lab asignado o ya tiene valores) ---
                _has_lab = _mat_code in _labs_set
                _db_hteo = _hteo_map.get(_mat_code)
                _db_hlab = _hlab_map.get(_mat_code)
                _has_hteo_hlab_data = _db_hteo is not None or _db_hlab is not None

                if _has_lab or _has_hteo_hlab_data:
                    _hl_c1, _hl_c2, _hl_c3, _hl_c4 = st.columns(4)
                    _hl_c1.markdown("**Hs teor\u00eda:**")
                    _new_hteo = _hl_c2.number_input(
                        "h_teo",
                        value=float(_db_hteo) if _db_hteo is not None else 0.0,
                        min_value=0.0,
                        step=0.25,
                        format="%.2f",
                        key=f"prev_hteo_{_sel_sched_id}_{_mat_code}",
                        label_visibility="collapsed",
                        help=(
                            "Horas semanales que se dictan como teor\u00eda. "
                            "Junto con Hs lab debe sumar Hs semanales."
                        ),
                    )
                    _hl_c3.markdown("**Hs laboratorio:**")
                    _new_hlab = _hl_c4.number_input(
                        "h_lab",
                        value=float(_db_hlab) if _db_hlab is not None else 0.0,
                        min_value=0.0,
                        step=0.25,
                        format="%.2f",
                        key=f"prev_hlab_{_sel_sched_id}_{_mat_code}",
                        label_visibility="collapsed",
                        help=(
                            "Horas semanales fijas como laboratorio. "
                            "Si tiene lab asignado pero Hs lab = 0, se "
                            "asume reserva ad-hoc (decide el docente "
                            "durante el ejercicio del plan, fuera del LP)."
                        ),
                    )

                    # Validacion: ht + hl == hsem
                    _sum_thl = round(_new_hteo + _new_hlab, 2)
                    _hsem_round = round(_display_hsem, 2)
                    _sum_ok = abs(_sum_thl - _hsem_round) < 0.01

                    if not _sum_ok:
                        st.warning(
                            f"Hs teor\u00eda ({_new_hteo:g}) + Hs laboratorio "
                            f"({_new_hlab:g}) = {_sum_thl:g} \u2260 Hs "
                            f"semanales ({_hsem_round:g}). Ajust\u00e1 los "
                            f"valores antes de guardar."
                        )

                    # Mensaje informativo: caso reserva
                    if _has_lab and _new_hlab == 0 and _sum_ok:
                        st.caption(
                            "\u2139\ufe0f Tiene laboratorios asignados con "
                            "**Hs lab = 0** \u2192 se trata como reserva "
                            "ad-hoc: el LP no fija laboratorio, los docentes "
                            "lo reservan caso por caso durante el ejercicio."
                        )

                    # Auto-save solo si la suma es valida y cambio algun valor
                    _hteo_changed = (
                        _db_hteo is None or abs(_new_hteo - _db_hteo) > 0.001
                    )
                    _hlab_changed = (
                        _db_hlab is None or abs(_new_hlab - _db_hlab) > 0.001
                    )
                    if _sum_ok and (_hteo_changed or _hlab_changed):
                        with next(get_session()) as _sess:
                            _mat = materia_crud.get(_sess, _mat_code)
                            if _mat:
                                _mat.horas_teoria = _new_hteo
                                _mat.horas_laboratorio = _new_hlab
                                _sess.add(_mat)
                                _sess.commit()
                                _hteo_map[_mat_code] = _new_hteo
                                _hlab_map[_mat_code] = _new_hlab
                                st.toast(
                                    f"{_mat_code}: Hs te\u00f3rica/lab "
                                    f"actualizadas a "
                                    f"{_new_hteo:g}/{_new_hlab:g}."
                                )

                # --- b) Comisiones selector ---
                ic3.markdown("**Comisiones:**")
                new_n_com = ic4.number_input(
                    "n_com",
                    value=mp["n_comisiones"],
                    min_value=1,
                    key=f"prev_ncom_{_sel_sched_id}_{_mat_code}",
                    label_visibility="collapsed",
                    help=(
                        "Cantidad de comisiones. Cambiar este valor "
                        "actualiza las opciones de la columna Comision "
                        "en la tabla. Usa 'Reasignar comisiones' para "
                        "redistribuir las clases automaticamente."
                    ),
                )

                # Update stored value if user changed it
                if new_n_com != mp["n_comisiones"]:
                    mp["n_comisiones"] = new_n_com

                _h_sem = _display_hsem or 0
                _n_com = new_n_com
                _paralelas = mp["max_clases_paralelas"]

                # --- c) Reasignar comisiones button ---
                _cached_has_changes = st.session_state.get(
                    f"_has_changes_{_sel_sched_id}_{_mat_code}", False
                )
                if _cached_has_changes:
                    st.info(
                        "Hay cambios sin guardar en la tabla de abajo.",
                        icon="\U0001f4be",
                    )
                if st.button(
                    "Reasignar comisiones",
                    key=f"btn_reassign_{_sel_sched_id}_{_mat_code}",
                    help=(
                        "Redistribuye las clases entre las comisiones "
                        "seleccionadas usando asignacion automatica "
                        "(round-robin). Actualiza la tabla de abajo."
                        + (" ⚠️ Descarta cambios sin guardar."
                           if _cached_has_changes else "")
                    ),
                ):
                    _entries_rr = mp["entries"]
                    _reassigned = [dict(e) for e in _entries_rr]
                    _slot_groups: dict[tuple, list[dict]] = {}
                    for _ne in _reassigned:
                        _hi = _ne["hora_inicio"]
                        _hf = _ne["hora_fin"]
                        _sk = (_ne["dia"], str(_hi), str(_hf))
                        _slot_groups.setdefault(_sk, []).append(_ne)

                    def _entry_dur(e):
                        """Duration in hours for a single entry."""
                        _m = _parse_minutes(e["hora_fin"])
                        _m0 = _parse_minutes(e["hora_inicio"])
                        if _m is not None and _m0 is not None:
                            return max(0, _m - _m0) / 60
                        return 0.0

                    # Balance by accumulated hours (not count)
                    _com_hours: dict[int, float] = {
                        c: 0.0 for c in range(1, _n_com + 1)
                    }
                    for _sk in sorted(
                        _slot_groups,
                        key=lambda k: (
                            _dia_ord.get(k[0], 9), k[1], k[2]
                        ),
                    ):
                        _grp = _slot_groups[_sk]
                        _grp_dur = _entry_dur(_grp[0])
                        if len(_grp) > 1:
                            # Parallel classes: assign to comisiones
                            # with fewest hours
                            _avail = sorted(
                                range(1, _n_com + 1),
                                key=lambda c: _com_hours[c],
                            )
                            for _gi, _ge in enumerate(_grp):
                                _cn = _avail[_gi % len(_avail)]
                                _ge["comision_asignada"] = _cn
                                _com_hours[_cn] += _grp_dur
                        else:
                            _cn = min(
                                range(1, _n_com + 1),
                                key=lambda c: _com_hours[c],
                            )
                            _grp[0]["comision_asignada"] = _cn
                            _com_hours[_cn] += _grp_dur

                    mp["entries"] = _reassigned
                    mp["n_comisiones"] = _n_com
                    # Clear data_editor cache so it picks up new values
                    # (both new _mat_code keys and legacy _mp_idx keys)
                    for _ck in list(st.session_state.keys()):
                        if isinstance(_ck, str) and _ck.startswith((
                            f"prev_entries_{_sel_sched_id}_{_mat_code}",
                            f"prev_entries_{_sel_sched_id}_{_mp_idx}",
                            f"_init_df_{_sel_sched_id}_{_mat_code}",
                            f"_init_df_{_sel_sched_id}_{_mp_idx}",
                            f"_has_changes_{_sel_sched_id}_{_mat_code}",
                            f"_has_changes_{_sel_sched_id}_{_mp_idx}",
                        )):
                            del st.session_state[_ck]
                    _dist = ", ".join(
                        f"C{c}: {_fmt_hours(_com_hours[c])}"
                        for c in sorted(_com_hours)
                    )
                    # Store persistent message for next render
                    st.session_state[
                        f"_reassign_msg_{_sel_sched_id}_{_mat_code}"
                    ] = _dist
                    st.rerun()

                # Show persistent reasignar result if available
                _reassign_msg_key = (
                    f"_reassign_msg_{_sel_sched_id}_{_mat_code}"
                )
                if _reassign_msg_key in st.session_state:
                    st.success(
                        f"Comisiones reasignadas: "
                        f"{st.session_state[_reassign_msg_key]}. "
                        f"Guardá para persistir.",
                        icon="\U0001f504",
                    )
                    # Clear after showing once
                    del st.session_state[_reassign_msg_key]

                # --- e) Editable entry table ---
                _com_options = list(range(1, _n_com + 1))

                # Compute hours for each entry
                def _entry_hours(row):
                    hi_m = _parse_minutes(row["Inicio"])
                    hf_m = _parse_minutes(row["Fin"])
                    if hi_m is not None and hf_m is not None:
                        return round(max(0, hf_m - hi_m) / 60, 2)
                    return 0.0

                # Cache initial DataFrame to prevent Streamlit from
                # resetting data_editor edits across reruns.
                _init_key = f"_init_df_{_sel_sched_id}_{_mat_code}"
                _saved_key = f"_saved_com_{_sel_sched_id}_{_mat_code}"
                if _init_key not in st.session_state:
                    _entry_list = mp["entries"]
                    _rows = []
                    for _e in _entry_list:
                        _rows.append({
                            "_eid": _e["entry_id"],
                            "Dia": _e["dia"],
                            "Inicio": _time_str(_e["hora_inicio"]),
                            "Fin": _time_str(_e["hora_fin"]),
                            "Comision": _e["comision_asignada"],
                            "Tipo": _e.get("tipo_clase") or "sin determinar",
                        })

                    _df = (
                        pd.DataFrame(_rows)
                        if _rows
                        else pd.DataFrame(
                            columns=["_eid", "Dia", "Inicio", "Fin", "Comision", "Tipo"]
                        )
                    )
                    if not _df.empty:
                        _df["_sk"] = _df["Dia"].map(_dia_ord).fillna(9)
                        _df = (
                            _df.sort_values(["Comision", "_sk", "Inicio"])
                            .drop(columns="_sk")
                            .reset_index(drop=True)
                        )
                    if not _df.empty:
                        _df["Hs"] = _df.apply(_entry_hours, axis=1)
                    else:
                        _df["Hs"] = pd.Series(dtype=float)
                    st.session_state[_init_key] = _df
                    # Store saved (DB) comision state on first build only
                    if _saved_key not in st.session_state:
                        st.session_state[_saved_key] = {
                            _e["entry_id"]: _e["comision_asignada"]
                            for _e in mp["entries"]
                        }
                else:
                    _df = st.session_state[_init_key]

                # Build dynamic time options (base + any non-standard existing)
                _existing_times = set()
                if not _df.empty:
                    for _tc in ["Inicio", "Fin"]:
                        _existing_times.update(
                            _df[_tc].dropna().astype(str).str[:5]
                        )
                _time_opts = sorted(set(_BASE_TIME_OPTIONS) | _existing_times)

                _edited = st.data_editor(
                    _df,
                    column_config={
                        "_eid": None,
                        "Dia": st.column_config.SelectboxColumn(
                            "Dia",
                            options=list(_dia_ord.keys()),
                            required=True,
                            width="medium",
                        ),
                        "Inicio": st.column_config.SelectboxColumn(
                            "Inicio",
                            options=_time_opts,
                            required=True,
                            width="small",
                        ),
                        "Fin": st.column_config.SelectboxColumn(
                            "Fin",
                            options=_time_opts,
                            required=True,
                            width="small",
                        ),
                        "Comision": st.column_config.SelectboxColumn(
                            "Comision",
                            options=_com_options,
                            required=True,
                            width="small",
                        ),
                        "Tipo": st.column_config.SelectboxColumn(
                            "Tipo",
                            options=["sin determinar", "teorica", "laboratorio"],
                            default="sin determinar",
                            help="sin determinar (LP decide), teorica o laboratorio",
                            width="small",
                        ),
                        "Hs": st.column_config.NumberColumn(
                            "Hs", format="%.1f", width="small", disabled=True,
                        ),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key=f"prev_entries_{_sel_sched_id}_{_mat_code}",
                )
                st.caption(
                    "Edita horarios, dias y comisiones. "
                    "Usa + para agregar filas y el icono de "
                    "papelera (al seleccionar) para eliminar. "
                    "Los cambios se aplican al presionar "
                    "'Guardar cambios'. "
                    "La columna Hs se recalcula al guardar."
                )

                # --- f) Summary section (always visible) ---
                st.divider()

                # Compute summary from current data_editor state
                _valid = _edited.dropna(subset=["Dia", "Inicio", "Fin"])
                _new_total = 0.0
                for _, _r in _valid.iterrows():
                    _hi_m = _parse_minutes(_r["Inicio"])
                    _hf_m = _parse_minutes(_r["Fin"])
                    if _hi_m is not None and _hf_m is not None:
                        _new_total += max(0, _hf_m - _hi_m) / 60

                st.markdown(
                    f"**Resumen:** {len(_valid)} clases · "
                    f"{_fmt_hours(_new_total)} en cronograma · "
                    f"{_n_com} comision(es)"
                )

                # --- Compute hours per comision (used by checks and summary) ---
                _hours_by_com = {}
                for _cn in _com_options:
                    _ce = _valid[
                        _valid["Comision"] == _cn
                    ] if not _valid.empty else pd.DataFrame()
                    _com_h = 0.0
                    for _, _r in _ce.iterrows():
                        _hi_m = _parse_minutes(_r["Inicio"])
                        _hf_m = _parse_minutes(_r["Fin"])
                        if _hi_m is not None and _hf_m is not None:
                            _com_h += max(0, _hf_m - _hi_m) / 60
                    _hours_by_com[_cn] = round(_com_h, 2)

                # --- Structured validation checks ---
                _checks = []

                # Check 1: h/sem × comisiones = total
                if _h_sem > 0 and _new_total > 0:
                    _expected = _n_com * _h_sem
                    if abs(_expected - _new_total) < 0.01:
                        _checks.append({"id": "hsem_x_com", "label": "h/sem \u00d7 comisiones = total",
                            "status": "ok", "detail": f"{_fmt_hours(_h_sem)} \u00d7 {_n_com} = {_fmt_hours(_expected)}, cronograma: {_fmt_hours(_new_total)}"})
                    else:
                        _checks.append({"id": "hsem_x_com", "label": "h/sem \u00d7 comisiones = total",
                            "status": "warn", "detail": f"{_fmt_hours(_h_sem)} \u00d7 {_n_com} = {_fmt_hours(_expected)}, pero cronograma tiene {_fmt_hours(_new_total)}"})
                else:
                    _checks.append({"id": "hsem_x_com", "label": "h/sem \u00d7 comisiones = total",
                        "status": "info" if _h_sem == 0 else "ok",
                        "detail": "Sin dato de h/sem" if _h_sem == 0 else "Sin horas en cronograma"})

                # Check 2: total_horas / n_com divisible (solo con >1 comision)
                if _n_com > 1 and _new_total > 0:
                    _h_per_com = _new_total / _n_com
                    _rem = _h_per_com % 0.25
                    _is_clean = _rem < 0.01 or _rem > 0.24
                    if _is_clean:
                        _checks.append({"id": "divisible", "label": "Horas divisibles entre comisiones",
                            "status": "ok", "detail": f"{_fmt_hours(_new_total)} / {_n_com} = {_fmt_hours(_h_per_com)} por comisi\u00f3n"})
                    else:
                        _checks.append({"id": "divisible", "label": "Horas divisibles entre comisiones",
                            "status": "warn", "detail": f"{_fmt_hours(_new_total)} / {_n_com} = {_h_per_com:.2f}h (no cae en bloques de 15 min)"})

                # Check 3: Comisiones equilibradas
                _unique_hours = set(h for h in _hours_by_com.values() if h > 0)
                if len(_unique_hours) <= 1:
                    _bal_val = list(_unique_hours)[0] if _unique_hours else 0
                    _checks.append({"id": "balanced", "label": "Comisiones equilibradas",
                        "status": "ok",
                        "detail": f"Todas las comisiones tienen {_fmt_hours(_bal_val)} asignadas" if _bal_val > 0 else "Sin clases asignadas"})
                else:
                    _detail_parts = [f"C{cn}: {_fmt_hours(h)}" for cn, h in _hours_by_com.items()]
                    _checks.append({"id": "balanced", "label": "Comisiones equilibradas",
                        "status": "warn", "detail": f"Distribuci\u00f3n desigual: {', '.join(_detail_parts)}"})

                # Check 4: Clases paralelas <= comisiones
                if _paralelas > _n_com:
                    _checks.append({"id": "paralelas", "label": "Clases paralelas \u2264 comisiones",
                        "status": "error", "detail": f"{_paralelas} paralelas pero solo {_n_com} comision(es)"})
                else:
                    _checks.append({"id": "paralelas", "label": "Clases paralelas \u2264 comisiones",
                        "status": "ok", "detail": f"{_paralelas} paralela(s), {_n_com} comision(es)"})

                # Check 5: Sin comisiones vacias
                _empty_coms = [cn for cn, h in _hours_by_com.items() if h == 0]
                if _empty_coms:
                    _checks.append({"id": "empty_com", "label": "Sin comisiones vac\u00edas",
                        "status": "warn", "detail": f"Comision(es) {', '.join(str(c) for c in _empty_coms)} sin clases"})
                else:
                    _checks.append({"id": "empty_com", "label": "Sin comisiones vac\u00edas",
                        "status": "ok", "detail": "Todas las comisiones tienen clases"})

                # Check 6: Horas semanales definidas
                if _h_sem > 0:
                    _checks.append({"id": "hsem_set", "label": "Horas semanales definidas",
                        "status": "ok", "detail": f"{_fmt_hours(_h_sem)}"})
                else:
                    _checks.append({"id": "hsem_set", "label": "Horas semanales definidas",
                        "status": "warn", "detail": "Sin dato. Completar para validar."})

                # Cache worst check status for header icon on next render
                _worst = "ok"
                for _ck in _checks:
                    if _ck["status"] == "error":
                        _worst = "error"
                        break
                    if _ck["status"] == "warn" and _worst != "error":
                        _worst = "warn"
                    if _ck["status"] == "info" and _worst == "ok":
                        _worst = "info"
                st.session_state[f"_chk_worst_{_sel_sched_id}_{_mat_code}"] = _worst

                # Render checks as detailed rows
                for _ck in _checks:
                    _ico = {"ok": "\u2705", "warn": "\u26a0\ufe0f", "error": "\U0001f53a", "info": "\u2139\ufe0f"}[_ck["status"]]
                    st.markdown(f"{_ico} **{_ck['label']}:** {_ck['detail']}")

                # Build summary table per comision
                _summary_rows = []
                for _cn in _com_options:
                    _ce = _valid[
                        _valid["Comision"] == _cn
                    ] if not _valid.empty else pd.DataFrame()
                    _horarios = []
                    for _, _r in _ce.iterrows():
                        _phi_s = str(_r["Inicio"])[:5]
                        _phf_s = str(_r["Fin"])[:5]
                        _horarios.append(
                            f"{str(_r['Dia'])[:3]} {_phi_s}-{_phf_s}"
                        )
                    _summary_rows.append({
                        "Comision": _cn,
                        "Clases": len(_ce),
                        "Horas": _fmt_hours(_hours_by_com.get(_cn, 0)),
                        "Horarios": ", ".join(_horarios) if _horarios else "\u2014",
                    })
                _summary_df = pd.DataFrame(_summary_rows)
                st.dataframe(
                    _summary_df,
                    use_container_width=True,
                    hide_index=True,
                )

                # --- g) Save section ---
                # Detect changes and cache for next render's early indicator
                _orig_cmp = _df[["Dia", "Inicio", "Fin", "Comision"]].reset_index(drop=True)
                _edit_cmp = _edited[["Dia", "Inicio", "Fin", "Comision"]].reset_index(drop=True)
                _has_changes = (
                    len(_orig_cmp) != len(_edit_cmp)
                    or not _orig_cmp.equals(_edit_cmp)
                )
                st.session_state[f"_has_changes_{_sel_sched_id}_{_mat_code}"] = _has_changes

                # Detect comision-specific changes vs SAVED (DB) state
                _saved_coms = st.session_state.get(_saved_key, {})
                _n_com_changed = 0
                _n_other_changed = 0
                if not _edited.empty and _saved_coms:
                    for _, _r in _edited.iterrows():
                        _eid = _r.get("_eid")
                        if pd.notna(_eid) and _eid in _saved_coms:
                            if int(_r["Comision"]) != _saved_coms[_eid]:
                                _n_com_changed += 1
                        elif pd.isna(_eid):
                            _n_other_changed += 1  # new row
                    # Detect deleted rows
                    _edit_eids = set(
                        _edited["_eid"].dropna().tolist()
                    )
                    _deleted = len(
                        set(_saved_coms.keys()) - _edit_eids
                    )
                    _n_other_changed += _deleted

                # Build change summary
                _change_parts = []
                if _n_com_changed > 0:
                    _change_parts.append(
                        f"{_n_com_changed} comision(es) modificada(s)"
                    )
                if _n_other_changed > 0:
                    _change_parts.append(
                        f"{_n_other_changed} fila(s) agregada(s)/eliminada(s)"
                    )

                if _change_parts:
                    st.warning(
                        f"\U0001f504 Cambios sin guardar: "
                        f"{', '.join(_change_parts)}.",
                    )

                _sc1, _sc2 = st.columns([3, 1])
                with _sc2:
                    if _has_changes and st.button(
                        "Descartar cambios",
                        key=f"prev_discard_{_sel_sched_id}_{_mat_code}",
                        help="Descarta todas las ediciones y vuelve al estado guardado.",
                    ):
                        # Restore mp["entries"] from saved state
                        _saved_com_map = st.session_state.get(
                            _saved_key, {}
                        )
                        if _saved_com_map:
                            for _e in mp["entries"]:
                                _orig_com = _saved_com_map.get(
                                    _e["entry_id"]
                                )
                                if _orig_com is not None:
                                    _e["comision_asignada"] = _orig_com
                        for _ck in list(st.session_state.keys()):
                            if isinstance(_ck, str) and _ck.startswith((
                                f"prev_entries_{_sel_sched_id}_{_mat_code}",
                                f"prev_entries_{_sel_sched_id}_{_mp_idx}",
                                f"_init_df_{_sel_sched_id}_{_mat_code}",
                                f"_init_df_{_sel_sched_id}_{_mp_idx}",
                                f"_has_changes_{_sel_sched_id}_{_mat_code}",
                                f"_has_changes_{_sel_sched_id}_{_mp_idx}",
                            )):
                                del st.session_state[_ck]
                        st.toast("Cambios descartados.")
                        st.rerun()

                _save_label = (
                    "Guardar como copia" if _save_as_copy
                    else "Guardar cambios"
                )
                with _sc1:
                    _do_save = st.button(
                        _save_label,
                        type="primary",
                        key=f"prev_save_{_sel_sched_id}_{_mat_code}",
                        disabled=_is_stale,
                        help=(
                            "Persiste los horarios y la asignacion de "
                            "comisiones al cronograma"
                            + (" (copia)" if _save_as_copy else "")
                            + "."
                        ),
                    )
                if _do_save:
                    # Build final entries from data_editor
                    _final = []
                    for _i, (_, _r) in enumerate(_valid.iterrows()):
                        _eid_v = (
                            _r["_eid"]
                            if pd.notna(_r.get("_eid"))
                            else f"new_{_mat_code}_{_i}"
                        )
                        _com_v = (
                            int(_r["Comision"])
                            if pd.notna(_r.get("Comision"))
                            else 1
                        )
                        _hi_str = str(_r["Inicio"])[:5]
                        _hf_str = str(_r["Fin"])[:5]
                        _tipo_raw_v = _r.get("Tipo")
                        _tipo_v = None if (not _tipo_raw_v or _tipo_raw_v == "sin determinar") else str(_tipo_raw_v)
                        _final.append({
                            "entry_id": _eid_v,
                            "dia": _r["Dia"],
                            "hora_inicio": time.fromisoformat(_hi_str) if ":" in _hi_str else _r["Inicio"],
                            "hora_fin": time.fromisoformat(_hf_str) if ":" in _hf_str else _r["Fin"],
                            "comision_asignada": _com_v,
                            "tipo_clase": _tipo_v,
                        })

                    mp["entries"] = _final
                    mp["total_horas_schedule"] = _new_total
                    mp["n_comisiones"] = _n_com

                    # Recalculate flag
                    if _h_sem > 0 and _new_total > 0:
                        _ratio = _new_total / _h_sem
                        if (
                            abs(_ratio - round(_ratio)) < 0.01
                            and round(_ratio) == _n_com
                        ):
                            mp["flag"] = "exact"
                            mp["flag_detail"] = (
                                f"{_n_com} × {_h_sem}h/sem = "
                                f"{_fmt_hours(_new_total)}. OK."
                            )
                        else:
                            mp["flag"] = "uncertain"
                            mp["flag_detail"] = (
                                f"{_fmt_hours(_new_total)} / {_h_sem}h/sem = "
                                f"{_ratio:.2f}. Revisar."
                            )
                    else:
                        mp["flag"] = "no_data" if _h_sem == 0 else "exact"
                        mp["flag_detail"] = (
                            f"{len(_final)} entradas, "
                            f"{_fmt_hours(_new_total)}."
                        )

                    # Persist edits to schedule DB
                    with next(get_session()) as _sync_session:
                        _effective_sid = _sel_sched_id
                        _copy_name = st.session_state.get("copy_name")
                        if _save_as_copy:
                            _sel_obj = next(
                                (s for s in schedules if s.id == _sel_sched_id),
                                None,
                            )
                            _copy = duplicate_schedule(
                                _sync_session, _sel_sched_id,
                                _copy_name or (
                                    f"{_sel_obj.nombre} (copia)"
                                    if _sel_obj else "Copia"
                                ),
                            )
                            _effective_sid = _copy.id

                        _sync_entries = []
                        for _fe in _final:
                            _sync_entries.append({
                                "entry_id": _fe["entry_id"],
                                "dia": _fe["dia"],
                                "hora_inicio": _fe["hora_inicio"],
                                "hora_fin": _fe["hora_fin"],
                                "comision": _fe.get("comision_asignada"),
                                "tipo_clase": _fe.get("tipo_clase") or None,
                            })
                        _u, _c, _d = sync_preview_edits_to_schedule(
                            _sync_session, _effective_sid,
                            mp["materia_codigo"], _sync_entries,
                        )

                    _action = (
                        f"Copia '{_copy_name}' creada"
                        if _save_as_copy
                        else "Cronograma actualizado"
                    )
                    st.toast(
                        f"{_action}: {_u} modificados, "
                        f"{_c} agregados, {_d} eliminados"
                    )

                    # Clear widget caches (including saved state —
                    # it will be rebuilt from the new entries on next render)
                    for _ck in list(st.session_state.keys()):
                        if _ck.startswith((
                            f"prev_entries_{_sel_sched_id}_{_mat_code}",
                            f"prev_ncom_{_sel_sched_id}_{_mat_code}",
                            f"prev_hsem_{_sel_sched_id}_{_mat_code}",
                            f"_chk_worst_{_sel_sched_id}_{_mat_code}",
                            f"_init_df_{_sel_sched_id}_{_mat_code}",
                            f"_has_changes_{_sel_sched_id}_{_mat_code}",
                            f"_saved_com_{_sel_sched_id}_{_mat_code}",
                        )):
                            del st.session_state[_ck]
                    st.rerun()

        # --- Render filtered faltantes ---
        if _filtered_faltantes:
            st.divider()
            st.markdown(
                f"#### \U0001f4ed Materias faltantes ({len(_filtered_faltantes)})"
            )
            st.caption(
                "Materias esperadas en el plan pero sin horarios en el cronograma. "
                "Pod\u00e9s agregar clases directamente ac\u00e1."
            )
            _dia_ord_falt = {
                "Lunes": 0, "Martes": 1, "Mi\u00e9rcoles": 2,
                "Jueves": 3, "Viernes": 4, "S\u00e1bado": 5,
            }
            for _falt_code in sorted(_filtered_faltantes):
                _falt = _faltantes_flat[_falt_code]
                _falt_hsem_db = _hsem_map.get(_falt_code, 0.0)
                _falt_header = (
                    f"\U0001f4ed {_falt_code} \u2014 "
                    f"{_falt['materia_nombre']} | "
                    f"Sin horarios \u00b7 "
                    f"h/sem: {_fmt_hours(_falt_hsem_db) if _falt_hsem_db > 0 else '?'}"
                )

                with st.expander(_falt_header, expanded=True):
                    _fc1, _fc2, _fc3, _fc4 = st.columns(4)
                    _fc1.markdown("**Horas semanales:**")
                    _falt_display_hsem = _fc2.number_input(
                        "h/sem",
                        value=_falt_hsem_db,
                        min_value=0.0,
                        step=0.25,
                        format="%.2f",
                        key=f"prev_hsem_{_sel_sched_id}_falt_{_falt_code}",
                        label_visibility="collapsed",
                    )
                    if _falt_display_hsem != _falt_hsem_db:
                        with next(get_session()) as _sess:
                            _mat = materia_crud.get(_sess, _falt_code)
                            if _mat:
                                _mat.horas_semanales = (
                                    _falt_display_hsem
                                    if _falt_display_hsem > 0 else None
                                )
                                _sess.add(_mat)
                                _sess.commit()
                                _hsem_map[_falt_code] = _falt_display_hsem
                                st.toast(
                                    f"{_falt_code}: horas semanales "
                                    f"actualizadas a {_fmt_hours(_falt_display_hsem)}."
                                )

                    _fc3.markdown("**Comisiones:**")
                    _falt_ncom = _fc4.number_input(
                        "n_com",
                        value=1,
                        min_value=1,
                        key=f"prev_ncom_{_sel_sched_id}_falt_{_falt_code}",
                        label_visibility="collapsed",
                    )

                    # Empty data editor for adding entries
                    _falt_com_options = list(range(1, _falt_ncom + 1))
                    _falt_df = pd.DataFrame(
                        columns=["_eid", "Dia", "Inicio", "Fin", "Comision", "Tipo"]
                    )
                    _falt_df["Hs"] = pd.Series(dtype=float)

                    _falt_edited = st.data_editor(
                        _falt_df,
                        column_config={
                            "_eid": None,
                            "Dia": st.column_config.SelectboxColumn(
                                "Dia",
                                options=list(_dia_ord_falt.keys()),
                                required=True,
                                width="medium",
                            ),
                            "Inicio": st.column_config.SelectboxColumn(
                                "Inicio",
                                options=_BASE_TIME_OPTIONS,
                                required=True,
                                width="small",
                            ),
                            "Fin": st.column_config.SelectboxColumn(
                                "Fin",
                                options=_BASE_TIME_OPTIONS,
                                required=True,
                                width="small",
                            ),
                            "Comision": st.column_config.SelectboxColumn(
                                "Comision",
                                options=_falt_com_options,
                                required=True,
                                width="small",
                            ),
                            "Tipo": st.column_config.SelectboxColumn(
                                "Tipo",
                                options=["sin determinar", "teorica", "laboratorio"],
                                default="sin determinar",
                                width="small",
                            ),
                            "Hs": st.column_config.NumberColumn(
                                "Hs", format="%.1f",
                                width="small", disabled=True,
                            ),
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                        key=f"prev_entries_{_sel_sched_id}_falt_{_falt_code}",
                    )
                    st.caption(
                        "Agreg\u00e1 filas con + para cargar los horarios "
                        "de esta materia. La columna Hs se recalcula al guardar."
                    )

                    # Save button (only if there are valid entries)
                    _falt_valid = _falt_edited.dropna(
                        subset=["Dia", "Inicio", "Fin"]
                    )
                    if not _falt_valid.empty:
                        if st.button(
                            "Guardar horarios",
                            type="primary",
                            key=f"prev_save_{_sel_sched_id}_falt_{_falt_code}",
                            disabled=_is_stale,
                            help=(
                                "Guarda los horarios cargados en el "
                                "cronograma. Despu\u00e9s de guardar, "
                                "presion\u00e1 'Prevalidar y Visualizar "
                                "Comisiones' para actualizar la vista."
                            ),
                        ):
                            _falt_final = []
                            for _i, (_, _r) in enumerate(
                                _falt_valid.iterrows()
                            ):
                                _com_v = (
                                    int(_r["Comision"])
                                    if pd.notna(_r.get("Comision"))
                                    else 1
                                )
                                _fhi = str(_r["Inicio"])[:5]
                                _fhf = str(_r["Fin"])[:5]
                                _ftipo_raw = _r.get("Tipo")
                                _ftipo = None if (not _ftipo_raw or _ftipo_raw == "sin determinar") else str(_ftipo_raw)
                                _falt_final.append({
                                    "entry_id": f"new_falt_{_falt_code}_{_i}",
                                    "dia": _r["Dia"],
                                    "hora_inicio": time.fromisoformat(_fhi) if ":" in _fhi else _r["Inicio"],
                                    "hora_fin": time.fromisoformat(_fhf) if ":" in _fhf else _r["Fin"],
                                    "comision": _com_v,
                                    "tipo_clase": _ftipo,
                                })

                            with next(get_session()) as _sync_sess:
                                _effective_sid = _sel_sched_id
                                if _save_as_copy:
                                    _sel_obj = next(
                                        (s for s in schedules
                                         if s.id == _sel_sched_id),
                                        None,
                                    )
                                    _copy_name_v = st.session_state.get(
                                        "copy_name"
                                    )
                                    _copy = duplicate_schedule(
                                        _sync_sess, _sel_sched_id,
                                        _copy_name_v or (
                                            f"{_sel_obj.nombre} (copia)"
                                            if _sel_obj else "Copia"
                                        ),
                                    )
                                    _effective_sid = _copy.id

                                _u, _c, _d = sync_preview_edits_to_schedule(
                                    _sync_sess, _effective_sid,
                                    _falt_code, _falt_final,
                                )

                            st.toast(
                                f"Horarios guardados para {_falt_code}: "
                                f"{_c} creados. Presion\u00e1 'Prevalidar "
                                f"y Visualizar' para actualizar."
                            )
                            # Clear widget caches
                            for _ck in list(st.session_state.keys()):
                                if _ck.startswith(
                                    f"prev_entries_{_sel_sched_id}_falt_{_falt_code}"
                                ):
                                    del st.session_state[_ck]
                            st.rerun()


# =============================================================================
# Tab 2: Generar Plan (placeholder — task 12)
# =============================================================================
with tab_generar:
    st.subheader("Generar Plan de Cursada")
    st.info(
        "Seleccioná un cronograma ya validado desde la pestaña "
        "'Validación de Cronogramas' y luego generá el plan acá."
    )
    st.caption("Funcionalidad en desarrollo.")


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
                sel_plan = next(p for p in planes_detalle if p.id == sel_plan_id)

                # --- Editable metadata ---
                st.markdown("#### Metadata")
                with st.form(f"edit_plan_{sel_plan_id}"):
                    nuevo_nombre = st.text_input("Nombre", value=sel_plan.nombre)
                    nueva_desc = st.text_area("Descripcion", value=sel_plan.descripcion or "")
                    save_meta = st.form_submit_button("Guardar", type="primary")

                    if save_meta:
                        with next(get_session()) as session:
                            db_plan = session.get(PlanificacionCursadaDB, sel_plan_id)
                            if db_plan:
                                db_plan.nombre = nuevo_nombre
                                db_plan.descripcion = nueva_desc
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

                has_blocker = False

                if st.button("Validar plan", key=f"btn_validate_{sel_plan_id}"):
                    with next(get_session()) as session:
                        v_conflicts = validar_conflictos_horarios_plan(session, sel_plan_id)
                        v_coverage = validar_cobertura_plan(session, sel_plan_id, sel_ciclo_detalle)
                        v_virtual = identificar_virtuales_plan(session, sel_plan_id)

                    st.session_state[f"validation_results_{sel_plan_id}"] = {
                        "conflicts": v_conflicts,
                        "coverage": v_coverage,
                        "virtual": v_virtual,
                    }

                # Display stored results
                vr_key = f"validation_results_{sel_plan_id}"
                if vr_key in st.session_state:
                    vr = st.session_state[vr_key]

                    # BLOCKER: Conflictos de horarios
                    v_conflicts = vr["conflicts"]
                    if not v_conflicts.valid:
                        has_blocker = True
                        st.error(f"BLOQUEANTE: {v_conflicts.message}")
                        with st.expander("Detalles de conflictos", expanded=False):
                            for d in v_conflicts.details:
                                st.text(f"  - {d}")
                    else:
                        st.success(v_conflicts.message)

                    # WARNING: Cobertura
                    v_coverage = vr["coverage"]
                    if not v_coverage.valid:
                        st.warning(f"ADVERTENCIA: {v_coverage.message}")
                        with st.expander("Materias sin cobertura", expanded=False):
                            for d in v_coverage.details:
                                st.text(f"  - {d}")
                    else:
                        st.success(v_coverage.message)

                    # INFO: Virtuales
                    v_virtual = vr["virtual"]
                    if v_virtual.details:
                        st.info(f"INFO: {v_virtual.message}")
                        with st.expander("Materias virtuales", expanded=False):
                            for d in v_virtual.details:
                                st.text(f"  - {d}")
                    else:
                        st.info(v_virtual.message)

                    # Activation gate
                    if has_blocker:
                        st.error(
                            "No se puede activar el plan: hay conflictos bloqueantes. "
                            "Resuelva los conflictos y vuelva a validar."
                        )
                    elif not sel_plan.activo:
                        if st.button(
                            "Activar plan",
                            type="primary",
                            key=f"btn_activate_validated_{sel_plan_id}",
                        ):
                            with next(get_session()) as session:
                                activate_plan(session, sel_plan_id)
                            st.success(f"Plan '{sel_plan.nombre}' activado")
                            st.rerun()

                st.divider()

                # --- Filters ---
                st.markdown("#### Filtros")
                with next(get_session()) as session:
                    # Get carreras linked to this ciclo's plan versions
                    plan_version_ids = session.exec(
                        select(CicloPlanVersionDB.plan_version_id)
                        .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_detalle)
                    ).all()

                    carreras_in_ciclo = []
                    if plan_version_ids:
                        carreras_in_ciclo = session.exec(
                            select(CarreraDB)
                            .join(PlanCarreraVersionDB, CarreraDB.codigo == PlanCarreraVersionDB.carrera_codigo)
                            .where(PlanCarreraVersionDB.id.in_(plan_version_ids))
                            .distinct()
                        ).all()

                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    carrera_options = [f"{c.codigo} - {c.nombre}" for c in carreras_in_ciclo]
                    filtro_carrera = st.selectbox(
                        "Carrera", options=carrera_options,
                        index=None, placeholder="Seleccionar carrera...",
                        key="detalle_filtro_carrera",
                    )
                with col_f2:
                    filtro_anio = st.selectbox(
                        "Año", options=[1, 2, 3, 4, 5, 6],
                        index=None, placeholder="Seleccionar año...",
                        key="detalle_filtro_anio",
                    )
                with col_f3:
                    filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["1C", "2C", "Anual"],
                        index=None, placeholder="Seleccionar cuatrimestre...",
                        key="detalle_filtro_cuatri",
                    )

                # Determine which materia_codigos pass the filter
                # Require all 3 filters to show materias (avoid loading everything)
                _all_filters_set = (
                    filtro_carrera is not None
                    and filtro_anio is not None
                    and filtro_cuatri is not None
                )
                filtered_materia_codigos: set[str] | None = None
                if _all_filters_set:
                    with next(get_session()) as session:
                        query = (
                            select(PlanEstudioDB.materia_codigo)
                            .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
                        )
                        carrera_cod = filtro_carrera.split(" - ")[0]
                        query = query.where(PlanEstudioDB.carrera_codigo == carrera_cod)
                        query = query.where(PlanEstudioDB.anio_plan == int(filtro_anio))
                        if filtro_cuatri == "Anual":
                            query = query.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            query = query.where(PlanEstudioDB.cuatrimestre_plan == filtro_cuatri)
                        filtered_materia_codigos = set(session.exec(query.distinct()).all())

                st.divider()

                # --- Breakdown by materia (editable) ---
                st.markdown("#### Desglose por Materia")

                if not _all_filters_set:
                    st.caption(
                        "Seleccioná Carrera, Año y Cuatrimestre para ver "
                        "las materias del plan."
                    )
                    filtered_materia_codigos = set()  # empty → nothing shown

                with next(get_session()) as session:
                    # Load config for time slot generation
                    config = get_or_create_config(session)
                    time_slots = generate_time_slots(config)

                with next(get_session()) as session:
                    comisiones = list(session.exec(
                        select(ComisionDB)
                        .where(ComisionDB.plan_cursada_id == sel_plan_id)
                        .order_by(ComisionDB.materia_codigo, ComisionDB.numero)
                    ).all())

                    # Group by materia
                    by_materia: dict[str, list[ComisionDB]] = {}
                    for c in comisiones:
                        by_materia.setdefault(c.materia_codigo, []).append(c)

                    # Get materia names
                    materia_codigos = list(by_materia.keys())
                    materias_map: dict[str, str] = {}
                    if materia_codigos:
                        materias_db = session.exec(
                            select(MateriaDB).where(col(MateriaDB.codigo).in_(materia_codigos))
                        ).all()
                        materias_map = {m.codigo: m.nombre for m in materias_db}

                    # Load horarios for all comisiones in one query
                    comision_ids = [c.id for c in comisiones]
                    all_horarios: list[HorarioDB] = []
                    if comision_ids:
                        all_horarios = list(session.exec(
                            select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
                        ).all())
                    horarios_by_comision: dict[str, list[HorarioDB]] = {}
                    for h in all_horarios:
                        horarios_by_comision.setdefault(h.comision_id, []).append(h)

                # Apply filter
                display_materias = sorted(by_materia.keys())
                if filtered_materia_codigos is not None:
                    display_materias = [m for m in display_materias if m in filtered_materia_codigos]

                if not display_materias:
                    st.info("No hay materias que coincidan con los filtros.")
                else:
                    dias_list = sorted(DIAS_SEMANA, key=lambda d: [
                        "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"
                    ].index(d))

                    for mat_codigo in display_materias:
                        mat_coms = by_materia[mat_codigo]
                        mat_nombre = materias_map.get(mat_codigo, mat_codigo)
                        label = f"{mat_nombre} ({mat_codigo}) - {len(mat_coms)} comision(es)"

                        with st.expander(label, expanded=False):
                            # --- Bulk horario editor (data_editor) ---
                            _de_dia_ord = {
                                "Lunes": 0, "Martes": 1, "Miércoles": 2,
                                "Jueves": 3, "Viernes": 4, "Sábado": 5,
                            }
                            _de_rows = []
                            for _de_com in mat_coms:
                                for _de_h in horarios_by_comision.get(_de_com.id, []):
                                    _de_rows.append({
                                        "_hid": _de_h.id,
                                        "Día": _de_h.dia,
                                        "Inicio": _de_h.hora_inicio,
                                        "Fin": _de_h.hora_fin,
                                        "Comisión": _de_com.nombre,
                                        "Tipo": _de_h.tipo_clase or "sin determinar",
                                    })

                            _de_df = (
                                pd.DataFrame(_de_rows)
                                if _de_rows
                                else pd.DataFrame(
                                    columns=["_hid", "Día", "Inicio", "Fin", "Comisión", "Tipo"]
                                )
                            )
                            if not _de_df.empty:
                                _de_df["_sk"] = _de_df["Día"].map(_de_dia_ord).fillna(9)
                                _de_df = (
                                    _de_df.sort_values(["Comisión", "_sk", "Inicio"])
                                    .drop(columns="_sk")
                                    .reset_index(drop=True)
                                )

                            _com_name_options = [c.nombre for c in mat_coms]
                            _de_edited = st.data_editor(
                                _de_df,
                                column_config={
                                    "_hid": None,
                                    "Día": st.column_config.SelectboxColumn(
                                        "Día",
                                        options=list(_de_dia_ord.keys()),
                                        required=True,
                                        width="medium",
                                    ),
                                    "Inicio": st.column_config.TimeColumn(
                                        "Inicio", format="HH:mm",
                                        required=True, width="small",
                                        step=timedelta(minutes=15),
                                    ),
                                    "Fin": st.column_config.TimeColumn(
                                        "Fin", format="HH:mm",
                                        required=True, width="small",
                                        step=timedelta(minutes=15),
                                    ),
                                    "Comisión": st.column_config.SelectboxColumn(
                                        "Comisión",
                                        options=_com_name_options,
                                        required=True,
                                        width="medium",
                                    ),
                                    "Tipo": st.column_config.SelectboxColumn(
                                        "Tipo",
                                        options=["sin determinar", "teorica", "laboratorio"],
                                        default="sin determinar",
                                        width="small",
                                    ),
                                },
                                num_rows="dynamic",
                                use_container_width=True,
                                hide_index=True,
                                key=f"de_horarios_{sel_plan_id}_{mat_codigo}",
                            )

                            # Detect changes
                            _de_orig_cmp = _de_df[["Día", "Inicio", "Fin", "Comisión", "Tipo"]].reset_index(drop=True)
                            _de_edit_cmp = _de_edited[["Día", "Inicio", "Fin", "Comisión", "Tipo"]].reset_index(drop=True)
                            _de_has_changes = (
                                len(_de_orig_cmp) != len(_de_edit_cmp)
                                or not _de_orig_cmp.equals(_de_edit_cmp)
                            )

                            if _de_has_changes:
                                if st.button(
                                    "💾 Guardar cambios de horarios",
                                    key=f"de_save_{sel_plan_id}_{mat_codigo}",
                                    type="primary",
                                ):
                                    # Build edited rows for apply_horario_edits
                                    _com_name_to_num = {c.nombre: c.numero for c in mat_coms}
                                    _de_valid = _de_edited.dropna(subset=["Día", "Inicio", "Fin"])
                                    _de_edit_rows = []
                                    for _idx, _row in _de_valid.iterrows():
                                        _hid_v = (
                                            _row["_hid"]
                                            if pd.notna(_row.get("_hid"))
                                            else f"new_{_idx}"
                                        )
                                        _com_num = _com_name_to_num.get(
                                            _row["Comisión"],
                                            mat_coms[0].numero,
                                        )
                                        _de_edit_rows.append({
                                            "horario_id": _hid_v,
                                            "comision_numero": _com_num,
                                            "dia": _row["Día"],
                                            "hora_inicio": _row["Inicio"],
                                            "hora_fin": _row["Fin"],
                                            "tipo_clase": None if (_row.get("Tipo") or "sin determinar") == "sin determinar" else str(_row["Tipo"]),
                                        })

                                    with next(get_session()) as session:
                                        _u, _c, _d = apply_horario_edits(
                                            session, sel_plan_id,
                                            mat_codigo, _de_edit_rows,
                                        )
                                    st.toast(
                                        f"Horarios actualizados: {_u} modificados, "
                                        f"{_c} agregados, {_d} eliminados"
                                    )
                                    st.rerun()

                            st.divider()
                            for com in mat_coms:
                                st.markdown(f"##### {com.nombre} (#{com.numero})")

                                # --- Editable comision fields ---
                                col_name, col_cupo, col_del = st.columns([3, 2, 1])
                                with col_name:
                                    new_name = st.text_input(
                                        "Nombre", value=com.nombre,
                                        key=f"com_name_{com.id}",
                                        label_visibility="collapsed",
                                    )
                                with col_cupo:
                                    new_cupo = st.number_input(
                                        "Cupo", value=max(com.cupo, 1), min_value=1,
                                        key=f"com_cupo_{com.id}",
                                    )
                                with col_del:
                                    st.write("")
                                    if st.button("🗑️", key=f"del_com_{com.id}", help="Eliminar comision"):
                                        with next(get_session()) as session:
                                            # Delete horarios first, then comision
                                            hs = session.exec(
                                                select(HorarioDB).where(HorarioDB.comision_id == com.id)
                                            ).all()
                                            for h in hs:
                                                session.delete(h)
                                            db_com = session.get(ComisionDB, com.id)
                                            if db_com:
                                                session.delete(db_com)
                                            session.commit()
                                        st.success(f"Comision '{com.nombre}' eliminada")
                                        st.rerun()

                                # Save comision changes if modified
                                if new_name != com.nombre or new_cupo != com.cupo:
                                    if st.button("💾 Guardar comision", key=f"save_com_{com.id}"):
                                        with next(get_session()) as session:
                                            db_com = session.get(ComisionDB, com.id)
                                            if db_com:
                                                db_com.nombre = new_name
                                                db_com.cupo = new_cupo
                                                session.add(db_com)
                                                session.commit()
                                        st.success("Comision actualizada")
                                        st.rerun()

                                # --- Horarios ---
                                com_horarios = horarios_by_comision.get(com.id, [])
                                if com_horarios:
                                    for h in sorted(com_horarios, key=lambda x: (x.dia, x.hora_inicio)):
                                        col_h_info, col_h_del = st.columns([5, 1])
                                        with col_h_info:
                                            st.text(
                                                f"  {h.dia} "
                                                f"{h.hora_inicio.strftime('%H:%M')}-"
                                                f"{h.hora_fin.strftime('%H:%M')}"
                                            )
                                        with col_h_del:
                                            if st.button("✕", key=f"del_h_{h.id}", help="Eliminar horario"):
                                                with next(get_session()) as session:
                                                    db_h = session.get(HorarioDB, h.id)
                                                    if db_h:
                                                        session.delete(db_h)
                                                        session.commit()
                                                st.success("Horario eliminado")
                                                st.rerun()
                                else:
                                    st.caption("Sin horarios")

                                # --- Add horario form ---
                                with st.popover("➕ Agregar horario"):
                                    add_dia = st.selectbox(
                                        "Dia", options=dias_list,
                                        key=f"add_h_dia_{com.id}",
                                    )

                                    # Build time options from config slots
                                    time_options = sorted(
                                        {s for slot in time_slots for s in slot}
                                    )
                                    time_labels = {t: t.strftime("%H:%M") for t in time_options}

                                    add_inicio = st.selectbox(
                                        "Hora inicio",
                                        options=time_options,
                                        format_func=lambda t: time_labels[t],
                                        key=f"add_h_ini_{com.id}",
                                    )
                                    add_fin = st.selectbox(
                                        "Hora fin",
                                        options=time_options,
                                        format_func=lambda t: time_labels[t],
                                        index=min(1, len(time_options) - 1),
                                        key=f"add_h_fin_{com.id}",
                                    )

                                    if st.button("Agregar", key=f"btn_add_h_{com.id}", type="primary"):
                                        if add_fin <= add_inicio:
                                            st.error("La hora de fin debe ser posterior a la de inicio")
                                        else:
                                            with next(get_session()) as session:
                                                new_h = HorarioDB(
                                                    id=str(uuid.uuid4()),
                                                    comision_id=com.id,
                                                    codigo_materia=mat_codigo,
                                                    dia=add_dia,
                                                    hora_inicio=add_inicio,
                                                    hora_fin=add_fin,
                                                )
                                                session.add(new_h)
                                                session.commit()
                                            st.success("Horario agregado")
                                            st.rerun()

                                if com != mat_coms[-1]:
                                    st.divider()

                            # --- Add comision button ---
                            st.divider()
                            if st.button(f"➕ Agregar comision", key=f"add_com_{mat_codigo}"):
                                with next(get_session()) as session:
                                    # Determine next numero
                                    max_num = max(c.numero for c in mat_coms) if mat_coms else 0
                                    new_numero = max_num + 1
                                    mat_db = session.get(MateriaDB, mat_codigo)
                                    cupo_default = mat_db.cupo if mat_db and mat_db.cupo else 30

                                    new_com = ComisionDB(
                                        id=str(uuid.uuid4()),
                                        materia_codigo=mat_codigo,
                                        plan_cursada_id=sel_plan_id,
                                        comision_key=f"{mat_codigo}-{new_numero:03d}",
                                        nombre=f"Comision {new_numero}",
                                        numero=new_numero,
                                        cupo=cupo_default,
                                    )
                                    session.add(new_com)
                                    session.commit()
                                st.success(f"Comision {new_numero} agregada")
                                st.rerun()


# =============================================================================
# Tab 4: Grilla Horaria (visual read-only timetable)
# =============================================================================
with tab_grilla:
    st.subheader("Grilla Horaria")
    st.caption("Visualizacion de horarios en formato de cronograma semanal.")

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
                # --- Filters ---
                with next(get_session()) as session:
                    grilla_pv_ids = session.exec(
                        select(CicloPlanVersionDB.plan_version_id)
                        .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_grilla)
                    ).all()

                    grilla_carreras = []
                    if grilla_pv_ids:
                        grilla_carreras = session.exec(
                            select(CarreraDB)
                            .join(PlanCarreraVersionDB, CarreraDB.codigo == PlanCarreraVersionDB.carrera_codigo)
                            .where(PlanCarreraVersionDB.id.in_(grilla_pv_ids))
                            .distinct()
                        ).all()

                col_gf1, col_gf2, col_gf3 = st.columns(3)
                with col_gf1:
                    g_carrera_opts = ["Todas"] + [f"{c.codigo} - {c.nombre}" for c in grilla_carreras]
                    g_filtro_carrera = st.selectbox(
                        "Carrera", options=g_carrera_opts, key="grilla_filtro_carrera"
                    )
                with col_gf2:
                    g_filtro_anio = st.selectbox(
                        "Año", options=["Todos", 1, 2, 3, 4, 5, 6], key="grilla_filtro_anio"
                    )
                with col_gf3:
                    g_filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["Todos", "1C", "2C", "Anual"],
                        key="grilla_filtro_cuatri"
                    )

                # Determine filtered materia codigos
                g_filtered_mats = None
                if g_filtro_carrera != "Todas" or g_filtro_anio != "Todos" or g_filtro_cuatri != "Todos":
                    with next(get_session()) as session:
                        g_query = (
                            select(PlanEstudioDB.materia_codigo)
                            .where(PlanEstudioDB.plan_version_id.in_(grilla_pv_ids))
                        )
                        if g_filtro_carrera != "Todas":
                            g_carrera_cod = g_filtro_carrera.split(" - ")[0]
                            g_query = g_query.where(PlanEstudioDB.carrera_codigo == g_carrera_cod)
                        if g_filtro_anio != "Todos":
                            g_query = g_query.where(PlanEstudioDB.anio_plan == int(g_filtro_anio))
                        if g_filtro_cuatri != "Todos":
                            if g_filtro_cuatri == "Anual":
                                g_query = g_query.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                            else:
                                g_query = g_query.where(PlanEstudioDB.cuatrimestre_plan == g_filtro_cuatri)
                        g_filtered_mats = set(session.exec(g_query.distinct()).all())

                # --- Filter: solo materias del cuatrimestre ---
                solo_cuatri = st.checkbox(
                    "Solo materias del cuatrimestre del ciclo",
                    value=False,
                    key="grilla_solo_cuatri",
                )

                st.divider()

                # --- Build grid data ---
                with next(get_session()) as session:
                    config = get_or_create_config(session)
                    grid_data = build_timetable_grid(
                        session, sel_plan_grilla_id, config, g_filtered_mats,
                        ciclo_id=sel_ciclo_grilla,
                    )

                # Apply cuatrimestre filter if checkbox is checked
                if solo_cuatri and grid_data:
                    for dia in grid_data:
                        grid_data[dia] = [b for b in grid_data[dia] if b.en_periodo is not False]

                render_timetable_calendar(grid_data, config, key="grilla_cal")


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
