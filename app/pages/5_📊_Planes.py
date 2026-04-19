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
)
from src.ui.calendar_render import render_timetable_calendar
from src.domain.types import DIAS_SEMANA

init_db()


def _fmt_hours(h: float) -> str:
    """Format hours: '18h' if integer, '17.5h' otherwise."""
    return f"{h:g}h"


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
            if _prev_result.errors:
                for _err in _prev_result.errors:
                    st.error(_err)
            else:
                # Clear cached widget values from previous preview
                _stale_prefixes = (
                    f"prev_hsem_{_sel_sched_id}_",
                    f"prev_ncom_{_sel_sched_id}_",
                    f"prev_ecom_{_sel_sched_id}_",
                )
                for _sk in list(st.session_state.keys()):
                    if any(_sk.startswith(p) for p in _stale_prefixes):
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
                    ]
                }
                st.rerun()

        # =====================================================================
        # Phase 2: Preview comisiones
        # =====================================================================
        if _preview_key not in st.session_state:
            st.stop()

        _preview_data = st.session_state[_preview_key]
        _materias_preview = _preview_data["materias"]

        st.divider()
        st.markdown("### Previsualizacion de comisiones")

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

        # --- Render each materia ---
        for _mp_idx, mp in enumerate(_materias_preview):
            # --- Compute live header icon from current state ---
            _cur_ncom = st.session_state.get(
                f"prev_ncom_{_sel_sched_id}_{_mp_idx}", mp["n_comisiones"]
            )
            # Read fresh horas_semanales from DB
            with next(get_session()) as _hsem_session:
                _db_mat = _hsem_session.get(MateriaDB, mp["materia_codigo"])
                _db_hsem = float(_db_mat.horas_semanales) if _db_mat and _db_mat.horas_semanales else 0.0

            _cur_total = mp["total_horas_schedule"]
            _cur_paralelas = mp["max_clases_paralelas"]

            # Compute live flag for header (uses DB value, not widget value)
            if _db_hsem > 0 and _cur_total > 0:
                _hdr_ratio = _cur_total / _db_hsem
                _hdr_ratio_ok = abs(_hdr_ratio - round(_hdr_ratio)) < 0.01
                if _hdr_ratio_ok and round(_hdr_ratio) == _cur_ncom:
                    _live_icon = "\u2705"
                    _live_expand = False
                elif _cur_paralelas > _cur_ncom:
                    _live_icon = "\U0001f53a"
                    _live_expand = True
                else:
                    _live_icon = "\u26a0\ufe0f"
                    _live_expand = True
            elif _db_hsem == 0:
                _live_icon = "\u2753"
                _live_expand = True
            else:
                _live_icon = "\u2705"
                _live_expand = False

            _header = (
                f"{_live_icon} {mp['materia_codigo']} \u2014 "
                f"{mp['materia_nombre']} | "
                f"{_cur_ncom} comision(es)"
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
                    key=f"prev_hsem_{_sel_sched_id}_{_mp_idx}",
                    label_visibility="collapsed",
                )
                # Auto-save when value changes
                if _display_hsem != _db_hsem:
                    with next(get_session()) as _sess:
                        _mat = materia_crud.get(_sess, mp["materia_codigo"])
                        if _mat:
                            _mat.horas_semanales = (
                                _display_hsem if _display_hsem > 0 else None
                            )
                            _sess.add(_mat)
                            _sess.commit()
                            mp["horas_semanales"] = _display_hsem
                            st.toast(
                                f"{mp['materia_codigo']}: horas semanales "
                                f"actualizadas a {_fmt_hours(_display_hsem)}."
                            )
                            st.rerun()

                # --- b) Comisiones selector ---
                ic3.markdown("**Comisiones:**")
                new_n_com = ic4.number_input(
                    "n_com",
                    value=mp["n_comisiones"],
                    min_value=1,
                    key=f"prev_ncom_{_sel_sched_id}_{_mp_idx}",
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
                if st.button(
                    "Reasignar comisiones",
                    key=f"btn_reassign_{_sel_sched_id}_{_mp_idx}",
                    help=(
                        "Redistribuye las clases entre las comisiones "
                        "seleccionadas usando asignacion automatica "
                        "(round-robin). Actualiza la tabla de abajo."
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

                    _com_counts: Counter = Counter()
                    for _sk in sorted(
                        _slot_groups,
                        key=lambda k: (
                            _dia_ord.get(k[0], 9), k[1], k[2]
                        ),
                    ):
                        _grp = _slot_groups[_sk]
                        if len(_grp) > 1:
                            _avail = sorted(
                                range(1, _n_com + 1),
                                key=lambda c: _com_counts[c],
                            )
                            for _gi, _ge in enumerate(_grp):
                                _cn = _avail[_gi % len(_avail)]
                                _ge["comision_asignada"] = _cn
                                _com_counts[_cn] += 1
                        else:
                            _cn = min(
                                range(1, _n_com + 1),
                                key=lambda c: _com_counts[c],
                            )
                            _grp[0]["comision_asignada"] = _cn
                            _com_counts[_cn] += 1

                    mp["entries"] = _reassigned
                    mp["n_comisiones"] = _n_com
                    # Clear data_editor cache so it picks up new values
                    for _ck in list(st.session_state.keys()):
                        if _ck.startswith(f"prev_entries_{_sel_sched_id}_{_mp_idx}"):
                            del st.session_state[_ck]
                    st.toast(
                        f"Clases reasignadas entre {_n_com} comisiones."
                    )
                    st.rerun()

                # --- e) Editable entry table ---
                _entry_list = mp["entries"]
                _rows = []
                for _e in _entry_list:
                    _hi = _e["hora_inicio"]
                    _hf = _e["hora_fin"]
                    if isinstance(_hi, str):
                        _hi = time.fromisoformat(_hi)
                    if isinstance(_hf, str):
                        _hf = time.fromisoformat(_hf)
                    _rows.append({
                        "_eid": _e["entry_id"],
                        "Dia": _e["dia"],
                        "Inicio": _hi,
                        "Fin": _hf,
                        "Comision": _e["comision_asignada"],
                    })

                _df = (
                    pd.DataFrame(_rows)
                    if _rows
                    else pd.DataFrame(
                        columns=["_eid", "Dia", "Inicio", "Fin", "Comision"]
                    )
                )
                if not _df.empty:
                    _df["_sk"] = _df["Dia"].map(_dia_ord).fillna(9)
                    _df = (
                        _df.sort_values(["Comision", "_sk", "Inicio"])
                        .drop(columns="_sk")
                        .reset_index(drop=True)
                    )

                _com_options = list(range(1, _n_com + 1))

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
                        "Inicio": st.column_config.TimeColumn(
                            "Inicio", format="HH:mm",
                            required=True, width="small",
                        ),
                        "Fin": st.column_config.TimeColumn(
                            "Fin", format="HH:mm",
                            required=True, width="small",
                        ),
                        "Comision": st.column_config.SelectboxColumn(
                            "Comision",
                            options=_com_options,
                            required=True,
                            width="small",
                        ),
                    },
                    num_rows="dynamic",
                    use_container_width=True,
                    hide_index=True,
                    key=f"prev_entries_{_sel_sched_id}_{_mp_idx}",
                )
                st.caption(
                    "Edita horarios, dias y comisiones. "
                    "Usa + para agregar filas y el icono de "
                    "papelera (al seleccionar) para eliminar. "
                    "Los cambios se aplican al presionar "
                    "'Guardar cambios'."
                )

                # --- f) Summary section (always visible) ---
                st.divider()

                # Compute summary from current data_editor state
                _valid = _edited.dropna(subset=["Dia", "Inicio", "Fin"])
                _new_total = 0.0
                for _, _r in _valid.iterrows():
                    _thi = _r["Inicio"]
                    _thf = _r["Fin"]
                    if hasattr(_thi, "hour") and hasattr(_thf, "hour"):
                        _mins = (
                            _thf.hour * 60 + _thf.minute
                            - _thi.hour * 60 - _thi.minute
                        )
                        _new_total += max(0, _mins) / 60

                st.markdown(
                    f"**Resumen:** {len(_valid)} clases · "
                    f"{_fmt_hours(_new_total)} en cronograma · "
                    f"{_n_com} comision(es)"
                )

                # --- Validation messages (live, based on current editor state) ---
                _validations = []
                if _h_sem > 0 and _new_total > 0:
                    _ratio = _new_total / _h_sem
                    _ratio_int = abs(_ratio - round(_ratio)) < 0.01
                    if _ratio_int and round(_ratio) == _n_com:
                        st.success(
                            f"{_n_com} comision(es) × {_fmt_hours(_h_sem)}/sem = "
                            f"{_fmt_hours(_n_com * _h_sem)}. "
                            f"Coincide con las {_fmt_hours(_new_total)} del cronograma."
                        )
                    elif _ratio_int:
                        _expected = round(_ratio)
                        _validations.append(
                            f"Horas cronograma: {_fmt_hours(_new_total)} / "
                            f"{_fmt_hours(_h_sem)}/sem = "
                            f"{_expected} comision(es), pero se "
                            f"seleccionaron {_n_com}."
                        )
                    else:
                        _validations.append(
                            f"Horas cronograma: {_fmt_hours(_new_total)} / "
                            f"{_fmt_hours(_h_sem)}/sem = "
                            f"{_ratio:.2f} (no es entero). "
                            f"Revisar horarios o horas semanales."
                        )
                elif _h_sem == 0:
                    _validations.append(
                        "Sin dato de horas semanales. "
                        "Completalo para validar la cantidad de comisiones."
                    )

                if _paralelas > _n_com:
                    _validations.append(
                        f"Hay {_paralelas} clases en el mismo "
                        f"horario pero solo {_n_com} comision(es). "
                        f"Se necesitan al menos {_paralelas}."
                    )

                for _v in _validations:
                    st.warning(_v)

                # Build summary table
                _summary_rows = []
                for _cn in _com_options:
                    _ce = _valid[
                        _valid["Comision"] == _cn
                    ] if not _valid.empty else pd.DataFrame()
                    _horarios = []
                    for _, _r in _ce.iterrows():
                        _phi = _r["Inicio"]
                        _phf = _r["Fin"]
                        _phi_s = (
                            _phi.strftime("%H:%M")
                            if hasattr(_phi, "strftime")
                            else str(_phi)[:5]
                        )
                        _phf_s = (
                            _phf.strftime("%H:%M")
                            if hasattr(_phf, "strftime")
                            else str(_phf)[:5]
                        )
                        _horarios.append(
                            f"{str(_r['Dia'])[:3]} {_phi_s}-{_phf_s}"
                        )
                    _summary_rows.append({
                        "Comision": _cn,
                        "Clases": len(_ce),
                        "Horarios": ", ".join(_horarios) if _horarios else "\u2014",
                    })
                _summary_df = pd.DataFrame(_summary_rows)
                st.dataframe(
                    _summary_df,
                    use_container_width=True,
                    hide_index=True,
                )

                # Summary validations
                _empty_coms = [
                    r["Comision"] for _, r in _summary_df.iterrows()
                    if r["Clases"] == 0
                ]
                if _empty_coms:
                    st.warning(
                        f"Comision(es) {', '.join(str(c) for c in _empty_coms)} "
                        f"sin clases asignadas."
                    )

                # --- g) Save section ---
                # Detect changes
                _orig_cmp = _df[["Dia", "Inicio", "Fin", "Comision"]].reset_index(drop=True)
                _edit_cmp = _edited[["Dia", "Inicio", "Fin", "Comision"]].reset_index(drop=True)
                _has_changes = (
                    len(_orig_cmp) != len(_edit_cmp)
                    or not _orig_cmp.equals(_edit_cmp)
                )

                if _has_changes:
                    st.info(
                        "Hay cambios sin guardar en la tabla.",
                        icon="\U0001f4be",
                    )

                _save_label = (
                    "Guardar como copia" if _save_as_copy
                    else "Guardar cambios"
                )
                if st.button(
                    _save_label,
                    type="primary",
                    key=f"prev_save_{_sel_sched_id}_{_mp_idx}",
                    help=(
                        "Persiste los horarios y la asignacion de "
                        "comisiones al cronograma"
                        + (" (copia)" if _save_as_copy else "")
                        + "."
                    ),
                ):
                    # Build final entries from data_editor
                    _final = []
                    for _i, (_, _r) in enumerate(_valid.iterrows()):
                        _eid_v = (
                            _r["_eid"]
                            if pd.notna(_r.get("_eid"))
                            else f"new_{_mp_idx}_{_i}"
                        )
                        _com_v = (
                            int(_r["Comision"])
                            if pd.notna(_r.get("Comision"))
                            else 1
                        )
                        _final.append({
                            "entry_id": _eid_v,
                            "dia": _r["Dia"],
                            "hora_inicio": _r["Inicio"],
                            "hora_fin": _r["Fin"],
                            "comision_asignada": _com_v,
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

                    # Clear widget caches
                    for _ck in list(st.session_state.keys()):
                        if _ck.startswith((
                            f"prev_entries_{_sel_sched_id}_{_mp_idx}",
                            f"prev_ncom_{_sel_sched_id}_{_mp_idx}",
                            f"prev_hsem_{_sel_sched_id}_{_mp_idx}",
                        )):
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
                                    })

                            _de_df = (
                                pd.DataFrame(_de_rows)
                                if _de_rows
                                else pd.DataFrame(
                                    columns=["_hid", "Día", "Inicio", "Fin", "Comisión"]
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
                                    ),
                                    "Fin": st.column_config.TimeColumn(
                                        "Fin", format="HH:mm",
                                        required=True, width="small",
                                    ),
                                    "Comisión": st.column_config.SelectboxColumn(
                                        "Comisión",
                                        options=_com_name_options,
                                        required=True,
                                        width="medium",
                                    ),
                                },
                                num_rows="dynamic",
                                use_container_width=True,
                                hide_index=True,
                                key=f"de_horarios_{sel_plan_id}_{mat_codigo}",
                            )

                            # Detect changes
                            _de_orig_cmp = _de_df[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
                            _de_edit_cmp = _de_edited[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
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
