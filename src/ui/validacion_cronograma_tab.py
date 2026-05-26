"""Renderer of the cronograma validation tab (extracted from Planes).

Originally lived in app/pages/5_📊_Planes.py as the body of `with tab_cronogramas:`.
Moved to app/pages/6_📅_Cronogramas.py tab 'Validar' to keep the validation
flow in the Cronogramas page. Encapsulated as a function so that internal
`return` statements (originally `st.stop()`) only abort this tab, not the
whole page.
"""

from __future__ import annotations

import uuid
from datetime import time, timedelta
from typing import Any

import pandas as pd
import streamlit as st
from sqlmodel import select, func, col

from src.database.connection import get_session
from src.database.models import (
    PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB, MateriaDB,
    ScheduleDB, ScheduleEntryDB,
    CicloPlanVersionDB, PlanCarreraVersionDB, PlanEstudioDB,
    CarreraDB, ConfiguracionHoraria, MateriaLaboratorioDB,
)
from src.database.crud import (
    ciclo_crud, materia_crud, get_or_create_config, update_config,
)
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
    get_all_schedules,
    duplicate_schedule,
    sync_preview_edits_to_schedule,
)
from src.services.plan_generation_service import (
    preview_plan_from_schedule,
)
from src.services.dictado_service import (
    get_dictado_codigos_for_ciclo,
    get_materias_esperadas_from_dictados,
    has_dictados_for_ciclo,
    set_activo_for_materias_in_ciclo,
)
from src.services.cronograma_validation_service import (
    _get_faltantes_por_carrera as _service_get_faltantes_por_carrera,
)
from src.services.validations import (
    validar_factibilidad_particion_horas,
)
from src.domain.types import DIAS_SEMANA


# ---------------------------------------------------------------------------
# Local helpers (originally defined in 5_📊_Planes.py)
# ---------------------------------------------------------------------------

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


# Las funciones `_get_materias_esperadas` y `_get_faltantes_por_carrera`
# vivian aca como duplicado de las del service. Ahora delegamos en
# `src/services/cronograma_validation_service.py` y `dictado_service.py`
# para que la fuente de verdad sea unica: dictados activos del ciclo.


# ---------------------------------------------------------------------------
# Tab renderer
# ---------------------------------------------------------------------------

def render_tab(ciclo_ids: list[str], ciclos_map: dict) -> None:
    """Render the cronograma validation tab.

    Args:
        ciclo_ids: List of ciclo IDs to choose from in the selectbox.
        ciclos_map: Map ciclo_id → CicloDB for any extra info.
    """
    st.subheader("Prevalidacion de cronograma contra ciclo")
    st.caption(
        "Selecciona un ciclo y un cronograma para prevalidar los datos. "
        "Podes ajustar comisiones, horarios y horas teoria/lab antes de "
        "generar un plan. Cada validacion queda registrada en el historial."
    )

    with st.expander("ℹ️ Que significa validar?", expanded=False):
        st.markdown(
            """
            **Validar un cronograma contra un ciclo** compara las materias
            presentes en el cronograma con las que se esperan dictar en ese
            ciclo, y verifica condiciones estructurales que necesita el
            siguiente paso (generar plan + asignar aulas).

            **Materias esperadas = `Dictados` activos del ciclo**. Los dictados
            se gestionan en **📆 Ciclos → 📚 Dictados**: ahi se decide para
            cada materia del plan si se va a dictar este cuatrimestre y como
            (`activo`, `virtual`). Si una materia esta marcada `activo=False`,
            no aparece en faltantes ni se considera esperada.

            **Que se controla**:

            - **Cobertura**: cuantas materias esperadas (dictados activos) estan
              cubiertas, cuales faltan (con detalle por carrera y dictado
              codigo), y cuales aparecen en el cronograma sin tener un dictado
              activo en el ciclo (extras).
            - **Laboratorios**: cuantas materias del cronograma tienen
              laboratorios compatibles asignados, y como esta configurado su
              modo:
                - **fijo** (`horas_laboratorio > 0`): el LP usara los slots
                  para fijar lab.
                - **reserva ad-hoc** (`horas_laboratorio = 0`): el LP no fija
                  lab; los docentes lo reservan caso por caso durante el
                  ejercicio.
                - **pendiente** (`horas_laboratorio is None`): falta definir;
                  bloqueante.
            - **Particion teoria/lab**: para cada comision de materia con lab
              fijo, que las clases puedan dividirse en subconjuntos que sumen
              `horas_teoria` y `horas_laboratorio`.

            La pagina **Planes** empieza desde un cronograma validado para
            generar el plan + asignar aulas + fijar la agenda concreta de
            clases.
            """
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
                _sched_options = {s.id: s.nombre for s in schedules}
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
            return

        # --- Pre-validation button ---
        _prevalidation_key = f"prevalidation_{_sel_sched_id}"
        _preview_key = f"preview_{_sel_sched_id}"

        # Pre-check: el ciclo necesita tener dictados creados para que la
        # prevalidacion tenga "materias esperadas" contra las cuales comparar.
        with next(get_session()) as _dchk_sess:
            _has_dictados = has_dictados_for_ciclo(_dchk_sess, sel_ciclo_crono)
        if not _has_dictados:
            st.error(
                "Este ciclo no tiene dictados creados. "
                "Ir a **📆 Ciclos → 📚 Dictados**, seleccionar este ciclo "
                "y apretar **Crear Dictados** antes de prevalidar."
            )
            return

        if st.button(
            "Prevalidar cronograma contra ciclo",
            type="primary",
            key=f"btn_prevalidar_{_sel_sched_id}",
            help=(
                "Analiza el cronograma seleccionado comparando las materias "
                "con los dictados activos de este ciclo."
            ),
        ):
            with next(get_session()) as session:
                _entries = get_schedule_entries(session, _sel_sched_id)
                _esperadas = get_materias_esperadas_from_dictados(
                    session, sel_ciclo_crono,
                )
                _dictado_codigos = get_dictado_codigos_for_ciclo(
                    session, sel_ciclo_crono, only_active=True,
                )
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
                _faltantes_por_carrera = _service_get_faltantes_por_carrera(
                    session, sel_ciclo_crono, _esperadas,
                    _materias_en_sched, _dictado_codigos,
                )

                # --- Atributos por materia esperada (para filtro virt+opt) ---
                _esp_attrs: dict[str, dict] = {}
                if _esperadas:
                    _esp_codes = list(_esperadas.keys())
                    _esp_mats = session.exec(
                        select(MateriaDB).where(
                            col(MateriaDB.codigo).in_(_esp_codes)
                        )
                    ).all()
                    _esp_mat_map = {m.codigo: m for m in _esp_mats}
                    # PE rows para optativa por materia (cualquier plan que la marque)
                    _pe_opt = session.exec(
                        select(PlanEstudioDB.materia_codigo, PlanEstudioDB.optativa)
                        .where(PlanEstudioDB.materia_codigo.in_(_esp_codes))
                    ).all()
                    _opt_set = {mc for mc, opt in _pe_opt if opt}
                    for _mc in _esp_codes:
                        _m_obj = _esp_mat_map.get(_mc)
                        _esp_attrs[_mc] = {
                            "virtual": bool(_m_obj.virtual) if _m_obj else False,
                            "optativa": _mc in _opt_set,
                            "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
                        }

                # --- Extras enriquecidas con carrera + atributos ---
                _extras_por_carrera: list[dict] = []
                if _extra:
                    # Pull MateriaDB para los extras
                    _ext_mats = session.exec(
                        select(MateriaDB).where(
                            col(MateriaDB.codigo).in_(list(_extra))
                        )
                    ).all()
                    _ext_mat_map = {m.codigo: m for m in _ext_mats}
                    # PE rows para mapping a carrera
                    _ext_pe = session.exec(
                        select(PlanEstudioDB)
                        .join(PlanCarreraVersionDB,
                              PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id)
                        .join(CicloPlanVersionDB,
                              PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id)
                        .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_crono)
                        .where(PlanEstudioDB.materia_codigo.in_(list(_extra)))
                    ).all()
                    _by_carr: dict[str, list[dict]] = {}
                    _seen: set[tuple[str, str]] = set()
                    for _pe in _ext_pe:
                        _key = (_pe.carrera_codigo, _pe.materia_codigo)
                        if _key in _seen:
                            continue
                        _seen.add(_key)
                        _m_obj = _ext_mat_map.get(_pe.materia_codigo)
                        _by_carr.setdefault(_pe.carrera_codigo, []).append({
                            "codigo": _pe.materia_codigo,
                            "nombre": _m_obj.nombre if _m_obj else "?",
                            "anio_plan": _pe.anio_plan,
                            "cuatrimestre_plan": _pe.cuatrimestre_plan,
                            "optativa": bool(_pe.optativa),
                            "virtual": bool(_m_obj.virtual) if _m_obj else False,
                            "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
                        })
                    # Materias en cronograma que no están en ningún plan del ciclo
                    _no_plan_extras = set(_extra) - {
                        m["codigo"] for ms in _by_carr.values() for m in ms
                    }
                    for _cc, _mlist in _by_carr.items():
                        _carr = session.get(CarreraDB, _cc)
                        _extras_por_carrera.append({
                            "carrera_codigo": _cc,
                            "carrera_nombre": _carr.nombre if _carr else _cc,
                            "materias": _mlist,
                        })
                    if _no_plan_extras:
                        _np_list = []
                        for _mc in sorted(_no_plan_extras):
                            _m_obj = _ext_mat_map.get(_mc)
                            _np_list.append({
                                "codigo": _mc,
                                "nombre": _m_obj.nombre if _m_obj else "?",
                                "anio_plan": None,
                                "cuatrimestre_plan": None,
                                "optativa": False,
                                "virtual": bool(_m_obj.virtual) if _m_obj else False,
                                "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
                            })
                        _extras_por_carrera.append({
                            "carrera_codigo": "—",
                            "carrera_nombre": "Sin carrera asignada",
                            "materias": _np_list,
                        })
                    _extras_por_carrera.sort(key=lambda x: x["carrera_codigo"])

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

                _dictado_count = len(_dictado_codigos)

            st.session_state[_prevalidation_key] = {
                "n_materias": len(_mat_codigos),
                "n_clases": _total_clases,
                "total_horas": _total_horas,
                "n_esperadas": len(_esperadas),
                "n_cubiertas": len(_cubiertas),
                "n_faltantes": len(_faltantes_set),
                "faltantes_por_carrera": _faltantes_por_carrera,
                "extras_por_carrera": _extras_por_carrera,
                "extra": [
                    {"codigo": cod, "nombre": _mat_map.get(cod, "?")}
                    for cod in sorted(_extra)
                ],
                "esperadas": _esperadas,
                "esperadas_attrs": _esp_attrs,
                "mat_map": _mat_map,
                "dictado_codigos": _dictado_codigos,
                "dictado_count_at_validation": _dictado_count,
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
            return

        _pv = st.session_state[_prevalidation_key]

        # --- Staleness check for Phase 1 ---
        _stored_pv_count = _pv.get("schedule_entry_count")
        _stored_dict_count = _pv.get("dictado_count_at_validation")
        if _stored_pv_count is not None:
            with next(get_session()) as _stale_sess:
                _current_pv_count = _stale_sess.exec(
                    select(func.count(ScheduleEntryDB.id))
                    .where(ScheduleEntryDB.schedule_id == _sel_sched_id)
                ).one()
                from src.services.dictado_service import (
                    count_active_dictados_for_ciclo as _cnt_dict,
                )
                _current_dict_count = _cnt_dict(
                    _stale_sess, sel_ciclo_crono,
                )
            if _current_pv_count != _stored_pv_count:
                st.warning(
                    f"El cronograma fue modificado desde la \u00faltima "
                    f"prevalidaci\u00f3n ({_stored_pv_count} \u2192 "
                    f"{_current_pv_count} entradas). "
                    f"Presion\u00e1 **Prevalidar** para actualizar."
                )
            elif (
                _stored_dict_count is not None
                and _current_dict_count != _stored_dict_count
            ):
                st.warning(
                    f"Los dictados del ciclo cambiaron desde la \u00faltima "
                    f"prevalidaci\u00f3n ({_stored_dict_count} \u2192 "
                    f"{_current_dict_count} activos). "
                    f"Presion\u00e1 **Prevalidar** para actualizar."
                )

        st.divider()
        st.markdown("### Resumen de cobertura")

        # Toggle excluir virtuales y optativas (no requieren aula)
        _exclude_vo = st.toggle(
            "Excluir virtuales y optativas del cómputo",
            value=st.session_state.get(
                f"prev_exclude_vo_{_sel_sched_id}", False,
            ),
            key=f"prev_exclude_vo_{_sel_sched_id}",
            help=(
                "Las materias virtuales y optativas no requieren asignación "
                "de aula y suelen poder coordinarse después. Excluirlas da "
                "una visión más realista del bloque a planificar."
            ),
        )

        # Recompute metrics si está activado el toggle
        _esp_attrs_ui = _pv.get("esperadas_attrs") or {}
        _esp_set_full = set(_pv.get("esperadas", {}).keys())
        if _exclude_vo and _esp_attrs_ui:
            _esp_relevantes = {
                mc for mc in _esp_set_full
                if not (
                    _esp_attrs_ui.get(mc, {}).get("virtual")
                    or _esp_attrs_ui.get(mc, {}).get("optativa")
                )
            }
        else:
            _esp_relevantes = _esp_set_full

        _materias_sched_set = set(_pv.get("mat_map", {}).keys())
        _cubiertas_disp = _materias_sched_set & _esp_relevantes
        _faltantes_disp_set = _esp_relevantes - _materias_sched_set
        _n_esp_disp = len(_esp_relevantes)
        _n_cub_disp = len(_cubiertas_disp)
        _n_falt_disp = len(_faltantes_disp_set)

        _pv_c1, _pv_c2, _pv_c3, _pv_c4, _pv_c5, _pv_c6 = st.columns(6)
        _pv_c1.metric("Materias", _pv["n_materias"])
        _pv_c2.metric("Clases", _pv["n_clases"])
        _pv_c3.metric("Horas cronograma", _fmt_hours(_pv['total_horas']))
        _pv_c4.metric(
            "Esperadas",
            _n_esp_disp,
            delta=(
                None if not _exclude_vo
                else f"−{_pv['n_esperadas'] - _n_esp_disp} virt/opt"
            ),
            delta_color="off",
        )
        _pv_c5.metric("Cubiertas", f"{_n_cub_disp}/{_n_esp_disp}")
        _pv_c6.metric("Faltantes", _n_falt_disp)

        # --- Materias faltantes y extras agrupadas por carrera ---
        _fpc = _pv["faltantes_por_carrera"]
        if isinstance(_fpc, dict):
            st.warning("Datos de prevalidacion desactualizados. Presiona 'Prevalidar' de nuevo.")
            _fpc = []

        _epc = _pv.get("extras_por_carrera") or []

        # Mapa por código de carrera para combinar faltantes + extras
        _grupos: dict[str, dict] = {}
        for _ci in _fpc:
            _grupos[_ci["carrera_codigo"]] = {
                "carrera_codigo": _ci["carrera_codigo"],
                "carrera_nombre": _ci["carrera_nombre"],
                "plan_version_nombre": _ci.get("plan_version_nombre", ""),
                "dicta_recursado": _ci.get("dicta_recursado", False),
                "faltantes": _ci["materias"],
                "extras": [],
            }
        for _ei in _epc:
            _cc = _ei["carrera_codigo"]
            if _cc in _grupos:
                _grupos[_cc]["extras"] = _ei["materias"]
            else:
                _grupos[_cc] = {
                    "carrera_codigo": _cc,
                    "carrera_nombre": _ei["carrera_nombre"],
                    "plan_version_nombre": "",
                    "dicta_recursado": False,
                    "faltantes": [],
                    "extras": _ei["materias"],
                }

        if _grupos:
            st.markdown("**Detalle por carrera**")
            for _cc in sorted(_grupos.keys()):
                _g = _grupos[_cc]
                # Aplicar filtro virt/opt sobre faltantes para el badge
                _fal_filt = [
                    _mf for _mf in _g["faltantes"]
                    if not (
                        _exclude_vo and (_mf.get("virtual") or _mf.get("optativa"))
                    )
                ]
                _ext_list = _g["extras"]
                _n_fc = len(_fal_filt)
                _n_ec = len(_ext_list)
                if _n_fc == 0 and _n_ec == 0:
                    continue
                _rec_tag = " · dicta recursado" if _g["dicta_recursado"] else ""
                _plan_tag = (
                    f" · Plan: {_g['plan_version_nombre']}"
                    if _g["plan_version_nombre"] else ""
                )
                _exp_lbl = (
                    f"{_g['carrera_nombre']} ({_g['carrera_codigo']})"
                    f"{_plan_tag} — "
                    f"📭 {_n_fc} faltante(s) · 📥 {_n_ec} no esperada(s)"
                    f"{_rec_tag}"
                )
                with st.expander(_exp_lbl, expanded=False):
                    if _fal_filt:
                        st.markdown(f"**Faltantes ({_n_fc})**")
                        _ft_rows = []
                        for _mf in _fal_filt:
                            _anio = f"{_mf['anio_plan']}°" if _mf["anio_plan"] else "—"
                            _cuatri = _mf["cuatrimestre_plan"] or "—"
                            _ft_rows.append({
                                "Código": _mf["codigo"],
                                "Nombre": _mf["nombre"],
                                "Año": _anio,
                                "Cuatri": _cuatri,
                                "h/sem": _mf["horas_semanales"] or "—",
                                "Optativa": "Sí" if _mf.get("optativa") else "—",
                                "Virtual": "Sí" if _mf.get("virtual") else "—",
                                "Anual": "Sí" if _mf.get("periodo") == "anual" else "—",
                                "Dictado": _mf.get("dictado_codigo", "—"),
                            })
                        st.dataframe(
                            pd.DataFrame(_ft_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                        # Action: desactivar dictados de faltantes seleccionadas
                        _fal_options = {
                            f"{_mf['codigo']} — {_mf['nombre']}": _mf["codigo"]
                            for _mf in _fal_filt
                        }
                        _fal_sel_labels = st.multiselect(
                            "Desactivar dictados de:",
                            options=list(_fal_options.keys()),
                            key=f"prev_falt_sel_{_sel_sched_id}_{_cc}",
                            help=(
                                "Marca como Inactivo el dictado de las materias "
                                "elegidas. Útil para sacarlas del set de esperadas "
                                "sin tener que cargar horarios."
                            ),
                        )
                        if _fal_sel_labels:
                            if st.button(
                                f"⚪ Desactivar {len(_fal_sel_labels)} dictado(s)",
                                key=f"prev_falt_btn_{_sel_sched_id}_{_cc}",
                            ):
                                _codes = [_fal_options[l] for l in _fal_sel_labels]
                                with next(get_session()) as _ds:
                                    _n = set_activo_for_materias_in_ciclo(
                                        _ds, sel_ciclo_crono, _codes, activo=False,
                                    )
                                st.session_state.pop(_prevalidation_key, None)
                                st.toast(f"{_n} dictado(s) desactivado(s).")
                                st.rerun()

                    if _ext_list:
                        st.markdown(
                            f"**No esperadas — con horarios pero sin dictado activo "
                            f"({_n_ec})**"
                        )
                        _ex_rows = []
                        for _ex in _ext_list:
                            _anio = f"{_ex['anio_plan']}°" if _ex.get("anio_plan") else "—"
                            _cuatri = _ex.get("cuatrimestre_plan") or "—"
                            _ex_rows.append({
                                "Código": _ex["codigo"],
                                "Nombre": _ex["nombre"],
                                "Año": _anio,
                                "Cuatri": _cuatri,
                                "Optativa": "Sí" if _ex.get("optativa") else "—",
                                "Virtual": "Sí" if _ex.get("virtual") else "—",
                                "Anual": "Sí" if _ex.get("periodo") == "anual" else "—",
                            })
                        st.dataframe(
                            pd.DataFrame(_ex_rows),
                            use_container_width=True,
                            hide_index=True,
                        )
                        # Action: activar dictados de extras seleccionadas
                        _ex_options = {
                            f"{_ex['codigo']} — {_ex['nombre']}": _ex["codigo"]
                            for _ex in _ext_list
                        }
                        _ex_sel_labels = st.multiselect(
                            "Activar dictados de:",
                            options=list(_ex_options.keys()),
                            key=f"prev_ext_sel_{_sel_sched_id}_{_cc}",
                            help=(
                                "Pone Activo el dictado de las materias seleccionadas "
                                "(creándolo si no existía). Pasan a contarse como "
                                "esperadas y dejan de aparecer como 'no esperadas'."
                            ),
                        )
                        if _ex_sel_labels:
                            if st.button(
                                f"🟢 Activar {len(_ex_sel_labels)} dictado(s)",
                                key=f"prev_ext_btn_{_sel_sched_id}_{_cc}",
                            ):
                                _codes = [_ex_options[l] for l in _ex_sel_labels]
                                with next(get_session()) as _ds:
                                    _n = set_activo_for_materias_in_ciclo(
                                        _ds, sel_ciclo_crono, _codes, activo=True,
                                    )
                                st.session_state.pop(_prevalidation_key, None)
                                st.toast(f"{_n} dictado(s) activado(s).")
                                st.rerun()

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
                                    "tipo_clase": ep.tipo_clase,
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
            return

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
        _hsem_map = {
            cod: float(hs) if hs else 0.0
            for cod, hs, _ht, _hl in _batch_mats
        }
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
                            "dictado_codigo": _mf.get("dictado_codigo", "?"),
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
            return

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

        # --- Botones para abrir/cerrar todos los expanders ---
        _force_expand_key = f"_force_expand_all_{_sel_sched_id}"
        _be1, _be2, _be3 = st.columns([1, 1, 6])
        with _be1:
            if st.button(
                "Abrir todos",
                key=f"btn_expand_all_{_sel_sched_id}",
                help="Expandir todas las materias visibles.",
            ):
                st.session_state[_force_expand_key] = "open"
                st.rerun()
        with _be2:
            if st.button(
                "Cerrar todos",
                key=f"btn_collapse_all_{_sel_sched_id}",
                help="Colapsar todas las materias visibles.",
            ):
                st.session_state[_force_expand_key] = "close"
                st.rerun()
        # Consumir el flag: se aplica solo en este render y se borra para
        # que el usuario pueda colapsar/abrir individualmente sin que el
        # flag global lo pise en el proximo rerun.
        _force_expand_mode = st.session_state.pop(_force_expand_key, None)

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

            # Use cached worst check status from previous render if available.
            # El icono refleja el estado actual; el expander queda abierto si
            # ya fue interactuado por el usuario (presencia de _init_df indica
            # que se abrio al menos una vez en esta sesion).
            _cached_worst = st.session_state.get(
                f"_chk_worst_{_sel_sched_id}_{_mat_code}"
            )
            _was_opened = (
                f"_init_df_{_sel_sched_id}_{_mat_code}" in st.session_state
                or f"prev_entries_{_sel_sched_id}_{_mat_code}" in st.session_state
            )
            if _cached_worst:
                _icon_map_only = {
                    "ok": "\u2705",
                    "warn": "\u26a0\ufe0f",
                    "error": "\U0001f53a",
                    "info": "\u2753",
                }
                _live_icon = _icon_map_only.get(_cached_worst, "\u2705")
                # Mantener abierto si: tiene problemas O ya fue abierto
                _live_expand = _cached_worst in ("warn", "error", "info") or _was_opened
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
                    _live_expand = _was_opened

            # Sufijo de modo lab: ad-hoc (reserva) si tiene lab asignado y hl=0
            _hdr_lab_db = _hlab_map.get(_mat_code)
            _hdr_has_lab = _mat_code in _labs_set
            if _hdr_has_lab and _hdr_lab_db is not None and _hdr_lab_db == 0:
                _lab_suffix = " \u00b7 \u2139\ufe0f lab por reserva"
            elif _hdr_has_lab and _hdr_lab_db is not None and _hdr_lab_db > 0:
                _lab_suffix = f" \u00b7 \U0001f9ea lab fijo {_hdr_lab_db:g}h"
            else:
                _lab_suffix = ""

            _header = (
                f"{_live_icon} {mp['materia_codigo']} \u2014 "
                f"{mp['materia_nombre']} | "
                f"{_cur_ncom} com \u00b7 {_fmt_hours(_cur_total)} \u00b7 "
                f"h/sem: {_fmt_hours(_db_hsem) if _db_hsem > 0 else '?'}"
                f"{_lab_suffix}"
            )

            # Override por boton global Abrir/Cerrar todos
            if _force_expand_mode == "open":
                _eff_expand = True
            elif _force_expand_mode == "close":
                _eff_expand = False
            else:
                _eff_expand = _live_expand

            with st.expander(_header, expanded=_eff_expand):
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

                # Recompute Hs en _edited para que el resumen y validaciones
                # cuenten correctamente las filas nuevas (la columna esta
                # disabled y no se actualiza automaticamente al editar).
                if not _edited.empty:
                    _edited = _edited.copy()
                    _edited["Hs"] = _edited.apply(_entry_hours, axis=1)

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

                # --- Checks 7-10: Particion teoria/laboratorio ---
                _ht = _hteo_map.get(_mat_code)
                _hl = _hlab_map.get(_mat_code)
                _has_lab = _mat_code in _labs_set
                _has_thl_data = _ht is not None or _hl is not None

                # Check 7: Hs teoria + Hs laboratorio = Hs semanales
                if _has_thl_data:
                    _ht_v = _ht or 0.0
                    _hl_v = _hl or 0.0
                    _sum_thl = round(_ht_v + _hl_v, 2)
                    if _h_sem > 0 and abs(_sum_thl - _h_sem) < 0.01:
                        _checks.append({"id": "thl_sum", "label": "Hs te\u00f3rica + Hs lab = Hs semanales",
                            "status": "ok",
                            "detail": f"{_ht_v:g} + {_hl_v:g} = {_sum_thl:g} = {_h_sem:g}"})
                    elif _h_sem == 0:
                        _checks.append({"id": "thl_sum", "label": "Hs te\u00f3rica + Hs lab = Hs semanales",
                            "status": "info",
                            "detail": "Sin dato de h/sem para comparar"})
                    else:
                        _checks.append({"id": "thl_sum", "label": "Hs te\u00f3rica + Hs lab = Hs semanales",
                            "status": "error",
                            "detail": f"{_ht_v:g} + {_hl_v:g} = {_sum_thl:g} \u2260 {_h_sem:g}"})
                elif _has_lab:
                    _checks.append({"id": "thl_sum", "label": "Hs te\u00f3rica + Hs lab = Hs semanales",
                        "status": "warn",
                        "detail": "Materia con lab asignado pero sin Hs te\u00f3rica/lab definidas. Completar arriba."})

                # Check 8: caso reserva ad-hoc (lab asignado + hl == 0)
                if _has_lab and _hl is not None and _hl == 0 and _ht is not None:
                    _checks.append({"id": "thl_reserva", "label": "Modo lab",
                        "status": "info",
                        "detail": "Reserva ad-hoc (Hs lab = 0): el LP no fija lab; los docentes lo reservan caso por caso."})
                elif _has_lab and _hl is not None and _hl > 0:
                    _checks.append({"id": "thl_reserva", "label": "Modo lab",
                        "status": "ok",
                        "detail": f"Lab fijo: {_hl:g}h por comisi\u00f3n entran al LP."})
                elif _has_lab and _hl is None:
                    _checks.append({"id": "thl_reserva", "label": "Modo lab",
                        "status": "warn",
                        "detail": "Materia con lab asignado pero sin Hs lab definidas."})

                # Check 9: predeterminados consistentes con Hs lab
                # Suma de duraciones por tipo en _valid (usando columna 'Tipo')
                if _has_lab and _hl is not None and _hl > 0:
                    _pre_lab_sum = 0.0
                    _pre_teo_sum = 0.0
                    _per_com_lab: dict = {}
                    _per_com_teo: dict = {}
                    for _cn in _com_options:
                        _per_com_lab[_cn] = 0.0
                        _per_com_teo[_cn] = 0.0
                    for _, _r in _valid.iterrows():
                        _hi_m = _parse_minutes(_r["Inicio"])
                        _hf_m = _parse_minutes(_r["Fin"])
                        if _hi_m is None or _hf_m is None:
                            continue
                        _dur = max(0, _hf_m - _hi_m) / 60
                        _tipo = str(_r.get("Tipo", "sin determinar")).strip()
                        _cn = _r.get("Comision")
                        if _tipo == "laboratorio":
                            _pre_lab_sum += _dur
                            if _cn in _per_com_lab:
                                _per_com_lab[_cn] += _dur
                        elif _tipo == "teorica":
                            _pre_teo_sum += _dur
                            if _cn in _per_com_teo:
                                _per_com_teo[_cn] += _dur

                    # Violacion por comision (predeterminados > Hs lab)
                    _ht_v = _ht or 0.0
                    _violators_lab = [
                        (cn, h) for cn, h in _per_com_lab.items()
                        if h > _hl + 0.01
                    ]
                    _violators_teo = [
                        (cn, h) for cn, h in _per_com_teo.items()
                        if h > _ht_v + 0.01
                    ]
                    if not _violators_lab and not _violators_teo:
                        _det_parts = []
                        if _pre_lab_sum > 0:
                            _det_parts.append(f"predeterminadas como lab: {_pre_lab_sum:g}h")
                        if _pre_teo_sum > 0:
                            _det_parts.append(f"predeterminadas como te\u00f3ricas: {_pre_teo_sum:g}h")
                        _det = "; ".join(_det_parts) if _det_parts else "Todas 'sin determinar' (LP decide)"
                        _checks.append({"id": "thl_predet", "label": "Predeterminados consistentes",
                            "status": "ok", "detail": _det})
                    else:
                        _msgs = []
                        for cn, h in _violators_lab:
                            _msgs.append(f"C{cn}: lab predeterminado {h:g}h > Hs lab {_hl:g}h")
                        for cn, h in _violators_teo:
                            _msgs.append(f"C{cn}: te\u00f3rica predeterminada {h:g}h > Hs te\u00f3rica {_ht_v:g}h")
                        _checks.append({"id": "thl_predet", "label": "Predeterminados consistentes",
                            "status": "error", "detail": "; ".join(_msgs)})

                # Check 10: factibilidad de particion subset-sum por comision
                if _has_lab and _hl is not None and _hl > 0 and _ht is not None:
                    from src.services.validations import _subset_sum_exists
                    _expected_total = _ht + _hl
                    _infactibles = []
                    for _cn in _com_options:
                        _ce = _valid[_valid["Comision"] == _cn] if not _valid.empty else pd.DataFrame()
                        _durs = []
                        for _, _r in _ce.iterrows():
                            _hi_m = _parse_minutes(_r["Inicio"])
                            _hf_m = _parse_minutes(_r["Fin"])
                            if _hi_m is None or _hf_m is None:
                                continue
                            _durs.append(max(0, _hf_m - _hi_m) / 60)
                        if not _durs:
                            continue
                        _total_c = sum(_durs)
                        if abs(_total_c - _expected_total) > 0.01:
                            _infactibles.append(
                                f"C{_cn}: total {_total_c:g}h \u2260 Hs te\u00f3rica + lab ({_expected_total:g}h)"
                            )
                            continue
                        if not _subset_sum_exists(_durs, _hl):
                            _durs_str = ", ".join(f"{d:g}" for d in _durs)
                            _infactibles.append(
                                f"C{_cn}: clases [{_durs_str}] no se pueden particionar para sumar Hs lab {_hl:g}h"
                            )
                    if not _infactibles:
                        _checks.append({"id": "thl_partition", "label": "Partici\u00f3n te\u00f3rica/lab factible",
                            "status": "ok",
                            "detail": f"Cada comisi\u00f3n puede dividirse en {_ht:g}h te\u00f3rica + {_hl:g}h lab"})
                    else:
                        _checks.append({"id": "thl_partition", "label": "Partici\u00f3n te\u00f3rica/lab factible",
                            "status": "error", "detail": "; ".join(_infactibles)})

                # Cache worst check status for header icon on next render.
                # 'info' es informativo (ej. modo reserva) y no degrada el ✅.
                _worst = "ok"
                for _ck in _checks:
                    if _ck["status"] == "error":
                        _worst = "error"
                        break
                    if _ck["status"] == "warn" and _worst != "error":
                        _worst = "warn"
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
                        help=(
                            "Persiste los horarios y la asignacion de "
                            "comisiones al cronograma"
                            + (" (copia)" if _save_as_copy else "")
                            + "."
                            + (" \u26a0\ufe0f El cronograma cambio en DB; "
                               "tus cambios se aplican igual sobre el "
                               "estado actual."
                               if _is_stale else "")
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
                _falt_dic = _falt.get("dictado_codigo", "?")
                _falt_header = (
                    f"\U0001f4ed {_falt_code} \u2014 "
                    f"{_falt['materia_nombre']} | "
                    f"Dictado {_falt_dic} sin horarios \u00b7 "
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
