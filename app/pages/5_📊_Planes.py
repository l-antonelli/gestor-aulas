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
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
    get_all_schedules,
)
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
from src.services.validations import (
    validar_conflictos_horarios_plan,
    validar_cobertura_plan,
    identificar_virtuales_plan,
)
from src.ui.calendar_render import render_timetable_calendar
from src.domain.types import DIAS_SEMANA

init_db()

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

tab_cronogramas, tab_general, tab_detalle, tab_grilla, tab_clases, tab_config = st.tabs([
    "📥 Cronogramas", "📋 Vista General", "🔍 Detalle del Plan",
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


# =============================================================================
# Tab 1: Cronogramas (Schedules)
# =============================================================================
with tab_cronogramas:
    st.subheader("Cronogramas")
    st.caption("Carga un archivo CSV/Excel con los horarios. "
               "Luego valida la cobertura y genera un plan de cursada.")

    sel_ciclo_crono = st.selectbox(
        "Seleccionar Ciclo", options=ciclo_ids, key="planes_sel_ciclo_crono"
    )

    if sel_ciclo_crono:
        # --- Existing schedules ---
        with next(get_session()) as session:
            schedules = get_schedules_for_ciclo(session, sel_ciclo_crono)

        if schedules:
            st.markdown(f"**{len(schedules)} cronograma(s) cargado(s):**")

            for s in schedules:
                with st.expander(f"{s.nombre} — {s.source_filename} ({s.fecha_upload})"):
                    with next(get_session()) as session:
                        entries = get_schedule_entries(session, s.id)

                        # Build materia name lookup
                        mat_codigos = list({e.codigo_materia for e in entries})
                        mat_map: dict[str, str] = {}
                        if mat_codigos:
                            mats = session.exec(
                                select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codigos))
                            ).all()
                            mat_map = {m.codigo: m.nombre for m in mats}

                    if entries:
                        entry_data = [{
                            "Materia": f"{mat_map.get(e.codigo_materia, '?')} ({e.codigo_materia})",
                            "Dia": e.dia,
                            "Inicio": e.hora_inicio.strftime("%H:%M"),
                            "Fin": e.hora_fin.strftime("%H:%M"),
                        } for e in entries]
                        st.dataframe(entry_data, use_container_width=True, hide_index=True)
                        st.caption(f"{len(entries)} entradas")
                    else:
                        st.caption("Sin entradas")

                    # --- Coverage validation ---
                    st.divider()
                    st.markdown("**Validacion de cobertura**")
                    with next(get_session()) as session:
                        esperadas = _get_materias_esperadas(session, sel_ciclo_crono)

                    if not esperadas:
                        st.warning("El ciclo no tiene versiones de plan de estudio asignadas. "
                                   "No se puede validar cobertura.")
                    else:
                        materias_en_schedule = {e.codigo_materia for e in entries}
                        cubiertas = materias_en_schedule & set(esperadas.keys())
                        faltantes = set(esperadas.keys()) - materias_en_schedule
                        extra = materias_en_schedule - set(esperadas.keys())

                        vc1, vc2, vc3 = st.columns(3)
                        vc1.metric("Cubiertas", f"{len(cubiertas)}/{len(esperadas)}")
                        vc2.metric("Faltantes", len(faltantes))
                        vc3.metric("Extra", len(extra))

                        if faltantes:
                            with st.expander(f"Materias faltantes ({len(faltantes)})", expanded=True):
                                for cod in sorted(faltantes):
                                    st.write(f"- **{esperadas[cod]}** ({cod})")

                        if extra:
                            with st.expander(f"Materias no esperadas ({len(extra)})"):
                                for cod in sorted(extra):
                                    nombre = mat_map.get(cod, "?")
                                    st.write(f"- **{nombre}** ({cod})")

                    # --- Actions ---
                    st.divider()
                    col_gen, col_del = st.columns([3, 1])

                    with col_gen:
                        st.markdown("**Generar plan desde este cronograma**")
                        plan_nombre = st.text_input(
                            "Nombre del plan",
                            value=f"Plan {sel_ciclo_crono}",
                            key=f"plan_nombre_{s.id}"
                        )

                    with col_del:
                        st.markdown("&nbsp;")  # spacing
                        if st.button("Eliminar cronograma", key=f"btn_del_crono_{s.id}", type="secondary"):
                            with next(get_session()) as session:
                                # Delete entries first, then schedule
                                entries_to_del = session.exec(
                                    select(ScheduleEntryDB)
                                    .where(ScheduleEntryDB.schedule_id == s.id)
                                ).all()
                                for e in entries_to_del:
                                    session.delete(e)
                                db_sched = session.get(ScheduleDB, s.id)
                                if db_sched:
                                    session.delete(db_sched)
                                session.commit()
                            st.success(f"Cronograma '{s.nombre}' eliminado")
                            st.rerun()

                    # --- Preview / Generate flow ---
                    preview_key = f"preview_{s.id}"

                    if st.button("Previsualizar comisiones", type="primary", key=f"btn_preview_{s.id}"):
                        with next(get_session()) as session:
                            preview_result = preview_plan_from_schedule(session, s.id)
                        if preview_result.errors:
                            for err in preview_result.errors:
                                st.error(err)
                        else:
                            # Clear cached widget values from previous preview
                            # so number_inputs pick up fresh DB values
                            stale_prefixes = (
                                f"prev_hsem_{s.id}_",
                                f"prev_ncom_{s.id}_",
                                f"prev_ecom_{s.id}_",
                            )
                            for sk in list(st.session_state.keys()):
                                if any(sk.startswith(p) for p in stale_prefixes):
                                    del st.session_state[sk]

                            # Store in session state as dicts for serialization
                            st.session_state[preview_key] = {
                                "materias": [
                                    {
                                        "materia_codigo": mp.materia_codigo,
                                        "materia_nombre": mp.materia_nombre,
                                        "horas_semanales": mp.horas_semanales,
                                        "total_horas_schedule": mp.total_horas_schedule,
                                        "n_comisiones": mp.n_comisiones,
                                        "max_duplicados": mp.max_duplicados,
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
                                    for mp in preview_result.materias
                                ]
                            }
                            st.rerun()

                    # --- Show preview if available ---
                    if preview_key in st.session_state:
                        preview_data = st.session_state[preview_key]
                        materias_preview = preview_data["materias"]

                        st.divider()
                        st.markdown("### Previsualizacion de comisiones")

                        n_flagged = sum(
                            1 for mp in materias_preview
                            if mp["flag"] in ("uncertain", "no_data")
                        )
                        n_total = len(materias_preview)
                        total_comisiones = sum(mp["n_comisiones"] for mp in materias_preview)

                        mc1, mc2, mc3 = st.columns(3)
                        mc1.metric("Materias", n_total)
                        mc2.metric("Comisiones totales", total_comisiones)
                        mc3.metric("Requieren revision", n_flagged)

                        if n_flagged > 0:
                            st.warning(
                                f"{n_flagged} materia(s) tienen derivacion incierta. "
                                f"Revisa y corregí antes de generar el plan."
                            )

                        # Render each materia
                        for mp_idx, mp in enumerate(materias_preview):
                            flag = mp["flag"]
                            flag_icons = {
                                "exact": "✅",
                                "duplicates": "🔄",
                                "uncertain": "⚠️",
                                "no_data": "❓",
                            }
                            icon = flag_icons.get(flag, "")

                            header = (
                                f"{icon} {mp['materia_codigo']} — {mp['materia_nombre']} "
                                f"| {mp['n_comisiones']} comision(es)"
                            )
                            expanded = flag in ("uncertain", "no_data")

                            with st.expander(header, expanded=expanded):
                                # Info row
                                ic1, ic2, ic3, ic4 = st.columns(4)
                                ic1.markdown(f"**Horas semanales:**")
                                new_h_sem = ic2.number_input(
                                    "h/sem",
                                    value=mp["horas_semanales"] or 0,
                                    min_value=0,
                                    key=f"prev_hsem_{s.id}_{mp_idx}",
                                    label_visibility="collapsed",
                                )
                                ic3.markdown(f"**Comisiones:**")
                                new_n_com = ic4.number_input(
                                    "n_com",
                                    value=mp["n_comisiones"],
                                    min_value=1,
                                    key=f"prev_ncom_{s.id}_{mp_idx}",
                                    label_visibility="collapsed",
                                )

                                # Update stored values if user changed them
                                if new_h_sem != (mp["horas_semanales"] or 0):
                                    mp["horas_semanales"] = new_h_sem if new_h_sem > 0 else None
                                if new_n_com != mp["n_comisiones"]:
                                    mp["n_comisiones"] = new_n_com

                                st.caption(
                                    f"Total horas en cronograma: {mp['total_horas_schedule']:.1f}h · "
                                    f"Max duplicados: {mp['max_duplicados']} · "
                                    f"Flag: {mp['flag_detail']}"
                                )

                                # --- Editable entry table ---
                                entry_list = mp["entries"]
                                _dia_ord = {
                                    "Lunes": 0, "Martes": 1, "Miércoles": 2,
                                    "Jueves": 3, "Viernes": 4, "Sábado": 5,
                                }

                                _rows = []
                                for _e in entry_list:
                                    _hi = _e["hora_inicio"]
                                    _hf = _e["hora_fin"]
                                    if isinstance(_hi, str):
                                        _hi = time.fromisoformat(_hi)
                                    if isinstance(_hf, str):
                                        _hf = time.fromisoformat(_hf)
                                    _rows.append({
                                        "_eid": _e["entry_id"],
                                        "Día": _e["dia"],
                                        "Inicio": _hi,
                                        "Fin": _hf,
                                        "Comisión": _e["comision_asignada"],
                                    })

                                _df = (
                                    pd.DataFrame(_rows)
                                    if _rows
                                    else pd.DataFrame(
                                        columns=["_eid", "Día", "Inicio", "Fin", "Comisión"]
                                    )
                                )
                                if not _df.empty:
                                    _df["_sk"] = _df["Día"].map(_dia_ord).fillna(9)
                                    _df = (
                                        _df.sort_values(["Comisión", "_sk", "Inicio"])
                                        .drop(columns="_sk")
                                        .reset_index(drop=True)
                                    )

                                _edited = st.data_editor(
                                    _df,
                                    column_config={
                                        "_eid": None,
                                        "Día": st.column_config.SelectboxColumn(
                                            "Día",
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
                                        "Comisión": st.column_config.NumberColumn(
                                            "Comisión", min_value=1, step=1,
                                            default=1, required=True, width="small",
                                        ),
                                    },
                                    num_rows="dynamic",
                                    use_container_width=True,
                                    hide_index=True,
                                    key=f"prev_entries_{s.id}_{mp_idx}",
                                )

                                # --- Detect changes ---
                                _orig_cmp = _df[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
                                _edit_cmp = _edited[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
                                _has_changes = (
                                    len(_orig_cmp) != len(_edit_cmp)
                                    or not _orig_cmp.equals(_edit_cmp)
                                )

                                if _has_changes:
                                    _valid = _edited.dropna(subset=["Día", "Inicio", "Fin"])
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

                                    _h_sem = mp["horas_semanales"] or 0
                                    _sug_n = mp["n_comisiones"]
                                    if _h_sem > 0 and _new_total > 0:
                                        _ratio = _new_total / _h_sem
                                        if _ratio >= 1 and abs(_ratio - round(_ratio)) < 0.01:
                                            _sug_n = round(_ratio)

                                    st.info(
                                        f"Cambios: {len(_valid)} entradas, "
                                        f"{_new_total:.1f}h total"
                                        + (f" → {_sug_n} comisiones" if _h_sem > 0 else "")
                                    )

                                    # --- Build reassigned entries for preview ---
                                    _preview_entries = []
                                    for _i, (_, _r) in enumerate(_valid.iterrows()):
                                        _eid_v = (
                                            _r["_eid"]
                                            if pd.notna(_r.get("_eid"))
                                            else f"new_{mp_idx}_{_i}"
                                        )
                                        _com_v = (
                                            int(_r["Comisión"])
                                            if pd.notna(_r.get("Comisión"))
                                            else 1
                                        )
                                        _preview_entries.append({
                                            "entry_id": _eid_v,
                                            "dia": _r["Día"],
                                            "hora_inicio": _r["Inicio"],
                                            "hora_fin": _r["Fin"],
                                            "comision_asignada": _com_v,
                                        })

                                    # Compute reassignment
                                    _reassigned = [dict(e) for e in _preview_entries]
                                    if _reassigned:
                                        _slot_groups: dict[tuple, list[dict]] = {}
                                        for _ne in _reassigned:
                                            _sk = (_ne["dia"], _ne["hora_inicio"], _ne["hora_fin"])
                                            _slot_groups.setdefault(_sk, []).append(_ne)

                                        _com_counts: Counter = Counter()
                                        for _sk in sorted(
                                            _slot_groups,
                                            key=lambda k: (_dia_ord.get(k[0], 9), k[1], k[2]),
                                        ):
                                            _grp = _slot_groups[_sk]
                                            if len(_grp) > 1:
                                                _avail = sorted(
                                                    range(1, _sug_n + 1),
                                                    key=lambda c: _com_counts[c],
                                                )
                                                for _gi, _ge in enumerate(_grp):
                                                    _cn = _avail[_gi % len(_avail)]
                                                    _ge["comision_asignada"] = _cn
                                                    _com_counts[_cn] += 1
                                            else:
                                                _cn = min(
                                                    range(1, _sug_n + 1),
                                                    key=lambda c: _com_counts[c],
                                                )
                                                _grp[0]["comision_asignada"] = _cn
                                                _com_counts[_cn] += 1

                                    # --- Show reassignment preview ---
                                    st.markdown("**Preview de reasignación:**")
                                    for _cn in range(1, _sug_n + 1):
                                        _ce = [
                                            e for e in _reassigned
                                            if e["comision_asignada"] == _cn
                                        ]
                                        _ce.sort(
                                            key=lambda e: (
                                                _dia_ord.get(e["dia"], 9),
                                                e["hora_inicio"],
                                            )
                                        )
                                        st.markdown(
                                            f"**Comisión {_cn}** "
                                            f"({len(_ce)} clases)"
                                        )
                                        for _pe in _ce:
                                            _phi = _pe["hora_inicio"]
                                            _phf = _pe["hora_fin"]
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
                                            st.text(
                                                f"  {_pe['dia']:12s} "
                                                f"{_phi_s} - {_phf_s}"
                                            )

                                    # --- Action buttons ---
                                    _col_accept, _col_recalc = st.columns(2)
                                    with _col_accept:
                                        _do_accept = st.button(
                                            "Aceptar (sin reasignar)",
                                            key=f"prev_accept_{s.id}_{mp_idx}",
                                        )
                                    with _col_recalc:
                                        _do_recalc = st.button(
                                            "Aceptar con Reasignación",
                                            key=f"prev_recalc_{s.id}_{mp_idx}",
                                            type="primary",
                                        )

                                    if _do_accept or _do_recalc:
                                        _final = (
                                            _reassigned if _do_recalc
                                            else _preview_entries
                                        )
                                        mp["entries"] = _final
                                        mp["total_horas_schedule"] = _new_total
                                        mp["n_comisiones"] = _sug_n

                                        # Recalculate flag
                                        if _h_sem > 0 and _new_total > 0:
                                            _ratio = _new_total / _h_sem
                                            if _ratio >= 1 and abs(_ratio - round(_ratio)) < 0.01:
                                                mp["flag"] = "exact"
                                                mp["flag_detail"] = (
                                                    f"Ajustado: {_new_total:.0f}h / "
                                                    f"{_h_sem}h = {_sug_n} comisiones."
                                                )
                                            else:
                                                mp["flag"] = "uncertain"
                                                mp["flag_detail"] = (
                                                    f"Ajustado: {_new_total:.0f}h / "
                                                    f"{_h_sem}h = {_ratio:.2f} (no entero)."
                                                )
                                        else:
                                            mp["flag_detail"] = (
                                                f"Ajustado: {_new_total:.0f}h, "
                                                f"{len(_final)} entradas."
                                            )

                                        # Clear widget caches
                                        for _ck in list(st.session_state.keys()):
                                            if _ck.startswith((
                                                f"prev_entries_{s.id}_{mp_idx}",
                                                f"prev_ncom_{s.id}_{mp_idx}",
                                                f"prev_hsem_{s.id}_{mp_idx}",
                                            )):
                                                del st.session_state[_ck]
                                        st.rerun()

                        # --- Generate button ---
                        st.divider()
                        if st.button(
                            "Confirmar y generar plan",
                            type="primary",
                            key=f"btn_confirm_gen_{s.id}",
                        ):
                            # Reconstruct MateriaPreview objects from session state
                            final_previews = []
                            for mp in materias_preview:
                                entry_previews = [
                                    EntryPreview(
                                        entry_id=e["entry_id"],
                                        dia=e["dia"],
                                        hora_inicio=e["hora_inicio"],
                                        hora_fin=e["hora_fin"],
                                        comision_asignada=e["comision_asignada"],
                                    )
                                    for e in mp["entries"]
                                ]
                                final_previews.append(MateriaPreview(
                                    materia_codigo=mp["materia_codigo"],
                                    materia_nombre=mp["materia_nombre"],
                                    horas_semanales=mp["horas_semanales"],
                                    total_horas_schedule=mp["total_horas_schedule"],
                                    n_comisiones=mp["n_comisiones"],
                                    max_duplicados=mp["max_duplicados"],
                                    flag=mp["flag"],
                                    flag_detail=mp["flag_detail"],
                                    entries=entry_previews,
                                ))

                            # Also update horas_semanales in DB if user corrected
                            with next(get_session()) as session:
                                for mp in materias_preview:
                                    if mp["horas_semanales"]:
                                        mat_db = session.get(MateriaDB, mp["materia_codigo"])
                                        if mat_db and mat_db.horas_semanales != mp["horas_semanales"]:
                                            mat_db.horas_semanales = mp["horas_semanales"]
                                            session.add(mat_db)
                                session.commit()

                            with next(get_session()) as session:
                                gen_result = generate_plan_from_preview(
                                    session, s.id, plan_nombre,
                                    sel_ciclo_crono, final_previews
                                )

                            if gen_result.errors:
                                for err in gen_result.errors:
                                    st.error(err)
                            if gen_result.comision_flags:
                                st.info("Notas:")
                                for flag_msg in gen_result.comision_flags:
                                    st.text(f"  - {flag_msg}")
                            if gen_result.plan:
                                # Clean up preview state
                                del st.session_state[preview_key]
                                st.success(
                                    f"Plan '{plan_nombre}' generado: "
                                    f"{gen_result.comisiones_created} comisiones, "
                                    f"{gen_result.horarios_created} horarios"
                                )
                                st.rerun()

        else:
            st.info("No hay cronogramas para este ciclo.")

        # --- Select existing standalone schedule ---
        st.divider()
        st.markdown("**Seleccionar cronograma existente**")
        st.caption("Usa un cronograma cargado desde la pagina Cronogramas.")
        with next(get_session()) as session:
            all_scheds = get_all_schedules(session)
        # Filter out schedules already associated with this ciclo
        available_scheds = [
            s for s in all_scheds
            if s.ciclo_id is None or s.ciclo_id != sel_ciclo_crono
        ]
        if available_scheds:
            sched_options = {
                s.id: f"{s.nombre} ({s.fecha_upload})"
                + (f" — ciclo: {s.ciclo_id}" if s.ciclo_id else " — sin ciclo")
                for s in available_scheds
            }
            sel_existing = st.selectbox(
                "Cronograma",
                options=["(ninguno)"] + list(sched_options.keys()),
                format_func=lambda x: sched_options[x] if x != "(ninguno)" else "(ninguno)",
                key="planes_sel_existing_sched",
            )
            if sel_existing and sel_existing != "(ninguno)":
                if st.button("Asociar al ciclo y usar", key="btn_associate_sched"):
                    with next(get_session()) as session:
                        sched_db = session.get(ScheduleDB, sel_existing)
                        if sched_db:
                            sched_db.ciclo_id = sel_ciclo_crono
                            session.add(sched_db)
                            session.commit()
                            st.success(
                                f"Cronograma '{sched_db.nombre}' asociado al ciclo "
                                f"{sel_ciclo_crono}. Ya aparece arriba."
                            )
                            st.rerun()
        else:
            st.caption("No hay cronogramas disponibles. Carga uno desde la pagina Cronogramas.")

        # --- Upload new schedule ---
        st.divider()
        st.markdown("**O cargar nuevo cronograma**")
        nombre_sched = st.text_input(
            "Nombre del cronograma",
            value=f"Horarios {sel_ciclo_crono}",
            key="crono_nombre"
        )
        uploaded_file = st.file_uploader(
            "Archivo CSV o Excel",
            type=["csv", "xlsx", "xls"],
            key="crono_file_upload"
        )

        if uploaded_file is not None:
            if st.button("Cargar Cronograma", type="primary", key="btn_upload_crono"):
                with next(get_session()) as session:
                    result = create_schedule_from_file(
                        session, sel_ciclo_crono, nombre_sched, uploaded_file
                    )
                if result.errors:
                    st.warning("Errores durante la carga:")
                    for err in result.errors:
                        st.text(f"  - {err}")
                if result.warnings:
                    for w in result.warnings:
                        st.info(w)
                if result.schedule:
                    st.success(
                        f"Cronograma '{nombre_sched}' cargado con "
                        f"{result.entries_created} entradas"
                    )
                    st.rerun()


# =============================================================================
# Tab 2: Vista General
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
                    carrera_options = ["Todas"] + [f"{c.codigo} - {c.nombre}" for c in carreras_in_ciclo]
                    filtro_carrera = st.selectbox(
                        "Carrera", options=carrera_options, key="detalle_filtro_carrera"
                    )
                with col_f2:
                    filtro_anio = st.selectbox(
                        "Año", options=["Todos", 1, 2, 3, 4, 5, 6], key="detalle_filtro_anio"
                    )
                with col_f3:
                    filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["Todos", "1C", "2C", "Anual"],
                        key="detalle_filtro_cuatri"
                    )

                # Determine which materia_codigos pass the filter
                filtered_materia_codigos = None  # None means "all"
                if filtro_carrera != "Todas" or filtro_anio != "Todos" or filtro_cuatri != "Todos":
                    with next(get_session()) as session:
                        query = (
                            select(PlanEstudioDB.materia_codigo)
                            .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
                        )
                        if filtro_carrera != "Todas":
                            carrera_cod = filtro_carrera.split(" - ")[0]
                            query = query.where(PlanEstudioDB.carrera_codigo == carrera_cod)
                        if filtro_anio != "Todos":
                            query = query.where(PlanEstudioDB.anio_plan == int(filtro_anio))
                        if filtro_cuatri != "Todos":
                            if filtro_cuatri == "Anual":
                                query = query.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                            else:
                                query = query.where(PlanEstudioDB.cuatrimestre_plan == filtro_cuatri)
                        filtered_materia_codigos = set(session.exec(query.distinct()).all())

                st.divider()

                # --- Breakdown by materia (editable) ---
                st.markdown("#### Desglose por Materia")

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
