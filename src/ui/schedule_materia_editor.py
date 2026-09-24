"""Editor inline de una materia dentro de un cronograma (ScheduleDB).

`render_schedule_materia_detail(schedule_id, materia_codigo, key_ns)`
renderiza el detalle completo de UNA materia dentro de un cronograma:

- Controles de horas: hs/sem, hs teoría, hs lab (con auto-save).
- Selector de cantidad de comisiones + botón "Reasignar comisiones"
  (round-robin balanceando por horas).
- `data_editor` con todos los entries de la materia (Día / Inicio /
  Fin / Comisión / Tipo / Hs).
- Resumen por comisión (clases / horas / horarios concretos).
- 10 chequeos estructurados con tildes/iconos (worst status cacheado
  para que el caller arme un badge en el header del expander).
- Botones "Guardar cambios" / "Descartar cambios" para persistir
  ediciones a `ScheduleEntryDB`.

Reusable desde el panel de validación unificado
(`validation_ui._render_detalle_por_materia`) cuando `source='schedule'`.

Las comisiones son entidades reales (`ComisionDB`) con
`schedule_id != None` que existen en el cronograma antes de generar
el plan. Cada `ScheduleEntryDB.comision_id` es FK a una de esas
comisiones. Este editor delega la edición de atributos de la
comisión (nombre, cupo, carrera_asignada) a la tabla de comisiones
de la página de Cronogramas; acá solo se opera sobre entries.

Diferencias respecto a `plan_materia_editor.render_plan_materia_detail`:
- No hay edición de cupo / coef / forecast (son del plan, no del
  cronograma).
- Sí hay 10 checks estructurados (vs validaciones cruzadas más
  acotadas en el plan).
- La unidad básica es el ScheduleEntry, no la ComisionDB.
"""

from __future__ import annotations

from datetime import time
from typing import Optional

import pandas as pd
import streamlit as st
from sqlmodel import select

from src.database.connection import get_session
from src.database.crud import get_or_create_config, materia_crud
from src.database.models import (
    ComisionDB,
    MateriaLaboratorioDB,
    ScheduleEntryDB,
)
from src.services.comision_service import (
    get_or_create_comision_by_numero,
    list_comisiones_for_schedule_materia,
)
from src.services.schedule_service import (
    add_schedule_entry,
    build_schedule_grid,
    delete_schedule_entry,
    duplicate_schedule,
    sync_preview_edits_to_schedule,
    update_schedule_entry,
)
from src.services.validations import _subset_sum_exists
from src.ui.calendar_render import render_editable_schedule_calendar


def _numero_de_entry(
    session, entry: ScheduleEntryDB,
    comisiones_map: dict[str, ComisionDB] | None = None,
) -> int | None:
    """Resuelve el `numero` de la comisión referenciada por un entry.
    Si el entry no tiene comisión asignada, devuelve None.

    Si se pasa `comisiones_map` (cache pre-cargado por id), usa eso;
    sino hace un get individual.
    """
    if not entry.comision_id:
        return None
    if comisiones_map is not None:
        c = comisiones_map.get(entry.comision_id)
        return c.numero if c else None
    c = session.get(ComisionDB, entry.comision_id)
    return c.numero if c else None


def _build_comisiones_map(
    session, schedule_id: str, materia_codigo: str,
) -> dict[str, ComisionDB]:
    """Devuelve dict {comision_id: ComisionDB} para la materia en el
    cronograma. Precarga usada por callers que iteran muchos entries."""
    coms = list_comisiones_for_schedule_materia(
        session, schedule_id, materia_codigo,
    )
    return {c.id: c for c in coms}


_DIA_ORD = {
    "Lunes": 0, "Martes": 1, "Miércoles": 2,
    "Jueves": 3, "Viernes": 4, "Sábado": 5,
}
_DIAS_LIST = list(_DIA_ORD.keys())

# Fallback si la config horaria no está disponible (paso de 15').
_BASE_TIME_OPTIONS = [
    f"{h:02d}:{m:02d}" for h in range(7, 23) for m in (0, 15, 30, 45)
] + ["23:00"]


def _opciones_horarias() -> list[str]:
    """Opciones HH:MM para los selectores de Inicio/Fin de los data
    editors, derivadas de ``ConfiguracionHoraria`` (granularidad +
    rango operativo) — la misma fuente que las listas de la plantilla
    Excel.

    Fix 2026-09-24 (reporte del usuario): antes era una lista
    hardcodeada con pasos de 30 minutos, así que las horas terminadas
    en :15/:45 sólo aparecían si alguna fila existente ya las traía.
    """
    from src.services.template_export_service import (
        _slots_horarios_validos,
    )
    try:
        with next(get_session()) as _s:
            _cfg = get_or_create_config(_s)
        return _slots_horarios_validos(
            _cfg.granularidad_minutos or 15,
            _cfg.hora_inicio_operativo,
            _cfg.hora_fin_operativo,
        )
    except Exception:  # noqa: BLE001
        return list(_BASE_TIME_OPTIONS)


def _fmt_hours(h: float) -> str:
    return f"{h:g}h"


def _parse_minutes(val) -> int | None:
    if val is None:
        return None
    if isinstance(val, str):
        try:
            h, m = val[:5].split(":")
            return int(h) * 60 + int(m)
        except (ValueError, IndexError):
            return None
    if hasattr(val, "hour") and hasattr(val, "minute"):
        return val.hour * 60 + val.minute
    return None


def _time_str(val) -> str:
    if val is None:
        return ""
    if isinstance(val, str):
        return val[:5]
    if hasattr(val, "strftime"):
        return val.strftime("%H:%M")
    return str(val)


def _entry_hours(row) -> float:
    hi = _parse_minutes(row["Inicio"])
    hf = _parse_minutes(row["Fin"])
    if hi is None or hf is None:
        return 0.0
    return round(max(0, hf - hi) / 60, 2)


# =============================================================================
# Dialogs para editar/agregar entries via calendario embebido
# =============================================================================

@st.dialog("Editar entrada", width="large")
def _dialog_edit_entry():
    """Dialog para editar una entry del cronograma desde el calendario.

    Lee de `st.session_state["_sme_pending_click"]` un dict con
    {schedule_id, entry_id, materia_codigo, dia, hora_inicio, hora_fin,
    comision, tipo_clase, _key, _save_as_copy}. Guarda la edicion en
    DB (o en una copia del cronograma si `_save_as_copy=True`).
    """
    pending = st.session_state.get("_sme_pending_click")
    if not pending:
        st.rerun()
        return

    _schedule_id = pending["schedule_id"]
    _save_as_copy = pending.get("_save_as_copy", False)
    _materia_codigo = pending["materia_codigo"]
    _dias_list = list(_DIA_ORD.keys())

    st.markdown(f"**Materia**: `{_materia_codigo}`")

    col_dia, col_ini, col_fin = st.columns(3)
    with col_dia:
        new_dia = st.selectbox(
            "Día",
            options=_dias_list,
            index=(
                _dias_list.index(pending["dia"])
                if pending["dia"] in _dias_list else 0
            ),
            key="_sme_dlg_dia",
        )
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="_sme_dlg_ini",
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="_sme_dlg_fin",
        )

    col_com, col_tipo = st.columns(2)
    with col_com:
        _pending_com = pending.get("comision") or 0
        new_comision = st.number_input(
            "Comisión (0 = sin asignar)",
            min_value=0, max_value=20, value=_pending_com,
            key="_sme_dlg_com",
        )
    with col_tipo:
        _tipo_options = ["sin determinar", "teorica", "laboratorio"]
        _pending_tipo = pending.get("tipo_clase") or "sin determinar"
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=_tipo_options,
            index=(
                _tipo_options.index(_pending_tipo)
                if _pending_tipo in _tipo_options else 0
            ),
            key="_sme_dlg_tipo",
            help=(
                "Sin determinar: la asignación automática elige "
                "cuál de los bloques con horas suficientes será de "
                "laboratorio. Teórica/Laboratorio: fuerza el tipo."
            ),
        )

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Guardar", type="primary", use_container_width=True):
            # Comparar contra el "baseline" — los valores actualmente
            # en DB. Si el dialog vino de un drag/resize del calendario,
            # `pending["dia"/"hora_*"]` ya tienen los nuevos valores
            # propuestos (precarga del dialog), pero `_baseline_*` tiene
            # los valores reales en DB para detectar el cambio.
            _base_dia = pending.get("_baseline_dia", pending["dia"])
            _base_hi = pending.get("_baseline_hi", pending["hora_inicio"])
            _base_hf = pending.get("_baseline_hf", pending["hora_fin"])

            cambios: dict = {}
            if new_dia != _base_dia:
                cambios["dia"] = new_dia
            if new_inicio != _base_hi:
                cambios["hora_inicio"] = new_inicio
            if new_fin != _base_hf:
                cambios["hora_fin"] = new_fin
            _new_com_val = new_comision if new_comision > 0 else None
            if _new_com_val != (pending.get("comision") or None):
                cambios["comision"] = _new_com_val
            _new_tipo_val = (
                None if new_tipo == "sin determinar" else new_tipo
            )
            if _new_tipo_val != (pending.get("tipo_clase") or None):
                cambios["tipo_clase"] = _new_tipo_val

            if cambios:
                _eff_sid = _maybe_save_as_copy(_schedule_id, _save_as_copy)
                with next(get_session()) as session:
                    update_schedule_entry(
                        session, pending["entry_id"], **cambios,
                    )
                st.session_state["_sme_toast"] = (
                    f"{_materia_codigo} actualizada"
                )
            else:
                st.session_state["_sme_toast"] = "Sin cambios"
            st.session_state["_sme_processed_click"] = pending["_key"]
            _invalidate_caches(pending)
            del st.session_state["_sme_pending_click"]
            st.rerun()
    with col2:
        if st.button("Eliminar", use_container_width=True):
            _maybe_save_as_copy(_schedule_id, _save_as_copy)
            with next(get_session()) as session:
                delete_schedule_entry(session, pending["entry_id"])
            st.session_state["_sme_toast"] = (
                f"{_materia_codigo} eliminada"
            )
            st.session_state["_sme_processed_click"] = pending["_key"]
            _invalidate_caches(pending)
            del st.session_state["_sme_pending_click"]
            st.rerun()
    with col3:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_sme_processed_click"] = pending["_key"]
            del st.session_state["_sme_pending_click"]
            st.rerun()


@st.dialog("Agregar entrada", width="large")
def _dialog_add_entry():
    """Dialog para crear una entry nueva con tipo + comisión cuando el
    usuario seleccionó un rango vacío en el calendario."""
    pending = st.session_state.get("_sme_pending_select")
    if not pending:
        st.rerun()
        return

    _schedule_id = pending["schedule_id"]
    _save_as_copy = pending.get("_save_as_copy", False)
    _materia_codigo = pending["materia_codigo"]

    st.markdown(f"**Materia**: `{_materia_codigo}`")
    st.markdown(
        f"**{pending['dia']}** · "
        f"{pending['hora_inicio'].strftime('%H:%M')} - "
        f"{pending['hora_fin'].strftime('%H:%M')}"
    )

    col_com, col_tipo = st.columns(2)
    with col_com:
        new_comision = st.number_input(
            "Comisión (0 = sin asignar)",
            min_value=0, max_value=20, value=0,
            key="_sme_dlg_add_com",
        )
    with col_tipo:
        _tipo_options = ["sin determinar", "teorica", "laboratorio"]
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=_tipo_options, index=0,
            key="_sme_dlg_add_tipo",
        )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            _com_val = new_comision if new_comision > 0 else None
            _tipo_val = None if new_tipo == "sin determinar" else new_tipo
            _eff_sid = _maybe_save_as_copy(_schedule_id, _save_as_copy)
            with next(get_session()) as session:
                # Resolver o crear la comisión matching por número.
                _com_id = None
                if _com_val:
                    _com_obj = get_or_create_comision_by_numero(
                        session, _materia_codigo, _com_val,
                        schedule_id=_eff_sid,
                    )
                    _com_id = _com_obj.id
                add_schedule_entry(
                    session, _eff_sid, _materia_codigo,
                    pending["dia"], pending["hora_inicio"], pending["hora_fin"],
                    comision_id=_com_id, tipo_clase=_tipo_val,
                )
            st.session_state["_sme_toast"] = (
                f"{_materia_codigo} agregada"
            )
            st.session_state["_sme_processed_select"] = pending["_key"]
            _invalidate_caches(pending)
            del st.session_state["_sme_pending_select"]
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_sme_processed_select"] = pending["_key"]
            del st.session_state["_sme_pending_select"]
            st.rerun()


def _maybe_save_as_copy(schedule_id: str, save_as_copy: bool) -> str:
    """Si `save_as_copy=True`, duplica el cronograma y devuelve el id
    de la copia; sino devuelve el original. La copia se nombra con el
    valor de `st.session_state['_sme_copy_name']` o un default.

    Cuidado: la duplicacion se aplica una sola vez por sesion (cacheada
    en `_sme_active_copy_<orig_id>`) para que ediciones sucesivas
    sigan apuntando a la misma copia hasta que el usuario apague el
    toggle.
    """
    if not save_as_copy:
        return schedule_id
    _cache_key = f"_sme_active_copy_{schedule_id}"
    if _cache_key in st.session_state:
        return st.session_state[_cache_key]
    _copy_name = (
        st.session_state.get("_sme_copy_name")
        or f"Copia (auto)"
    )
    with next(get_session()) as session:
        _copy = duplicate_schedule(session, schedule_id, _copy_name)
    st.session_state[_cache_key] = _copy.id
    st.toast(f"Cronograma duplicado en '{_copy_name}'.")
    return _copy.id


def _invalidate_caches(pending: dict) -> None:
    """Limpia los caches del editor para que el data_editor se
    reconstruya desde DB despues de mutar entries via calendario."""
    _kp = pending.get("_kp")
    if not _kp:
        return
    for _k in list(st.session_state.keys()):
        if isinstance(_k, str) and _k.startswith(_kp):
            # Mantener `_chk_worst` para no titilar el icono mientras
            # se recalcula
            if _k.endswith("_chk_worst"):
                continue
            del st.session_state[_k]


# =============================================================================
# Entrypoint
# =============================================================================

def render_schedule_materia_detail(
    schedule_id: str, materia_codigo: str, key_ns: str,
    *,
    save_as_copy: bool = False,
    pending_revalidate_key: Optional[str] = None,
    invalidate_cache_keys: Optional[list[str]] = None,
) -> str:
    """Renderea el editor de una materia del cronograma.

    Returns:
        worst status entre los 10 chequeos: 'ok' | 'warn' | 'error' | 'info'.
        Útil para que el caller arme un badge en el header del expander.
    """
    # Todas las keys de session_state incluyen schedule_id+materia_codigo
    # para evitar contaminacion cruzada cuando el usuario salta entre
    # cronogramas o renderea la misma materia bajo cronogramas distintos.
    # `_kp` es el "key prefix" base que combina ambos.
    _kp = f"{key_ns}_{schedule_id}_{materia_codigo}"

    # Toast de confirmacion despues de un dialog (rerun no permite
    # st.toast directo desde el handler).
    _toast_msg = st.session_state.pop("_sme_toast", None)
    if _toast_msg:
        st.toast(_toast_msg)

    # --- Carga de datos ---
    with next(get_session()) as session:
        mat_db = materia_crud.get(session, materia_codigo)
        if mat_db is None:
            st.error(f"Materia '{materia_codigo}' no encontrada.")
            return "error"

        entries = list(session.exec(
            select(ScheduleEntryDB)
            .where(ScheduleEntryDB.schedule_id == schedule_id)
            .where(ScheduleEntryDB.codigo_materia == materia_codigo)
        ).all())

        # ¿Tiene laboratorio asignado?
        has_lab = session.exec(
            select(MateriaLaboratorioDB)
            .where(MateriaLaboratorioDB.materia_codigo == materia_codigo)
            .limit(1)
        ).first() is not None

        # Config global (para el check "horarios vs config").
        _config_global = get_or_create_config(session)

    # Catálogo
    db_hsem = float(mat_db.horas_semanales or 0.0)
    db_hteo = mat_db.horas_teoria
    db_hlab = mat_db.horas_laboratorio

    # --- Calendario editable filtrado a la materia (drag/drop/click/select) ---
    _render_editable_calendar(
        schedule_id=schedule_id,
        materia_codigo=materia_codigo,
        kp=_kp,
        save_as_copy=save_as_copy,
    )

    # --- Controles de horas ---
    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.markdown("**Horas semanales:**")
    new_hsem = ic2.number_input(
        "h/sem", value=db_hsem, min_value=0.0, step=0.25, format="%.2f",
        key=f"{_kp}_hsem",
        label_visibility="collapsed",
    )
    if new_hsem != db_hsem:
        with next(get_session()) as _s:
            _m = materia_crud.get(_s, materia_codigo)
            if _m:
                _m.horas_semanales = new_hsem if new_hsem > 0 else None
                _s.add(_m)
                _s.commit()
                db_hsem = new_hsem
                st.toast(
                    f"{materia_codigo}: hs/sem actualizadas a "
                    f"{_fmt_hours(new_hsem)}."
                )

    has_thl_data = db_hteo is not None or db_hlab is not None
    new_hteo: Optional[float] = None
    new_hlab: Optional[float] = None
    if has_lab or has_thl_data:
        hl_c1, hl_c2, hl_c3, hl_c4 = st.columns(4)
        hl_c1.markdown("**Hs teoría:**")
        new_hteo = hl_c2.number_input(
            "h_teo",
            value=float(db_hteo) if db_hteo is not None else 0.0,
            min_value=0.0, step=0.25, format="%.2f",
            key=f"{_kp}_hteo",
            label_visibility="collapsed",
            help=(
                "Horas semanales de teoría. Junto con Hs lab debe sumar "
                "Hs semanales."
            ),
        )
        hl_c3.markdown("**Hs laboratorio:**")
        new_hlab = hl_c4.number_input(
            "h_lab",
            value=float(db_hlab) if db_hlab is not None else 0.0,
            min_value=0.0, step=0.25, format="%.2f",
            key=f"{_kp}_hlab",
            label_visibility="collapsed",
            help=(
                "Horas semanales fijas como laboratorio. Si tiene lab "
                "asignado pero Hs lab = 0, se asume reserva puntual "
                "(la decide el docente por afuera del sistema)."
            ),
        )

        sum_thl = round(new_hteo + new_hlab, 2)
        sum_ok = abs(sum_thl - round(db_hsem, 2)) < 0.01
        if not sum_ok:
            st.warning(
                f"Hs teoría ({new_hteo:g}) + Hs lab ({new_hlab:g}) = "
                f"{sum_thl:g} ≠ Hs semanales ({db_hsem:g}). "
                f"Ajustá los valores."
            )
        if has_lab and new_hlab == 0 and sum_ok:
            st.caption(
                "ℹ️ Tiene laboratorios asignados con **Hs lab = 0** → "
                "reserva puntual: la asignación automática no fija "
                "el lab; los docentes lo reservan caso por caso."
            )

        # Auto-save si suma OK y hay cambios
        hteo_changed = db_hteo is None or abs(new_hteo - db_hteo) > 0.001
        hlab_changed = db_hlab is None or abs(new_hlab - db_hlab) > 0.001
        if sum_ok and (hteo_changed or hlab_changed):
            with next(get_session()) as _s:
                _m = materia_crud.get(_s, materia_codigo)
                if _m:
                    _m.horas_teoria = new_hteo
                    _m.horas_laboratorio = new_hlab
                    _s.add(_m)
                    _s.commit()
                    db_hteo = new_hteo
                    db_hlab = new_hlab
                    st.toast(
                        f"{materia_codigo}: Hs teoría/lab actualizadas a "
                        f"{new_hteo:g}/{new_hlab:g}."
                    )

    # --- Selector cantidad de comisiones ---
    derived_ncom = _derive_n_comisiones(
        entries, schedule_id=schedule_id, materia_codigo=materia_codigo,
    )
    ncom_key = f"{_kp}_ncom"
    ic3.markdown("**Comisiones:**")
    n_com = ic4.number_input(
        "n_com", value=st.session_state.get(ncom_key, derived_ncom),
        min_value=1,
        key=ncom_key,
        label_visibility="collapsed",
        help=(
            "Cantidad de comisiones. Cambiar este valor actualiza las "
            "opciones de la columna Comision en la tabla. Usá "
            "'Reasignar comisiones' para redistribuir las clases."
        ),
    )

    # --- Botón Reasignar comisiones ---
    cached_has_changes = st.session_state.get(
        f"{_kp}_has_changes", False
    )
    if cached_has_changes:
        st.info("Hay cambios sin guardar en la tabla de abajo.", icon="💾")

    if st.button(
        "Reasignar comisiones",
        key=f"{_kp}_btn_reassign",
        help=(
            "Redistribuye las clases entre las comisiones balanceando "
            "por horas (round-robin)."
            + (" ⚠️ Descarta cambios sin guardar."
               if cached_has_changes else "")
        ),
    ):
        new_assignments = _reassign_round_robin(entries, n_com)
        # Persistir directamente en DB. `new_assignments` mapea
        # entry_id -> numero de comisión; resolvemos cada numero a un
        # ComisionDB (creándola si no existe) y guardamos comision_id.
        with next(get_session()) as _s:
            _entries_db = list(_s.exec(
                select(ScheduleEntryDB)
                .where(ScheduleEntryDB.schedule_id == schedule_id)
                .where(ScheduleEntryDB.codigo_materia == materia_codigo)
            ).all())
            _num_to_id: dict[int, str] = {}
            for _e in _entries_db:
                if _e.id in new_assignments:
                    _num = new_assignments[_e.id]
                    if _num not in _num_to_id:
                        _num_to_id[_num] = get_or_create_comision_by_numero(
                            _s, materia_codigo, _num,
                            schedule_id=schedule_id,
                        ).id
                    _e.comision_id = _num_to_id[_num]
                    _s.add(_e)
            _s.commit()
        # Invalidar cache del data_editor
        for _k in list(st.session_state.keys()):
            if isinstance(_k, str) and _k.startswith((
                f"{_kp}_init_df",
                f"{_kp}_de",
                f"{_kp}_has_changes",
            )):
                del st.session_state[_k]
        st.toast("Comisiones reasignadas.")
        st.rerun()

    # --- Data editor con entries ---
    com_options = list(range(1, n_com + 1))

    init_key = f"{_kp}_init_df"
    saved_key = f"{_kp}_saved"
    fp_key = f"{_kp}_fp"

    # Fingerprint del estado actual de DB: si los entries cambiaron por
    # fuera del editor (otro tab, otro usuario, recarga), invalidamos el
    # cache para que el data_editor refleje la realidad.
    with next(get_session()) as _sfp:
        _com_map_fp = _build_comisiones_map(_sfp, schedule_id, materia_codigo)
    _current_fp = tuple(sorted(
        (e.id, e.dia, str(e.hora_inicio), str(e.hora_fin),
         (_com_map_fp.get(e.comision_id).numero if e.comision_id and _com_map_fp.get(e.comision_id) else 0),
         e.tipo_clase or "")
        for e in entries
    ))
    _cached_fp = st.session_state.get(fp_key)
    _has_unsaved = st.session_state.get(f"{_kp}_has_changes", False)
    # Solo invalidar si NO hay cambios sin guardar (sino borrarlos seria
    # destructivo).
    if _cached_fp != _current_fp and not _has_unsaved:
        for _k in (init_key, saved_key):
            st.session_state.pop(_k, None)

    if init_key not in st.session_state:
        rows = []
        for e in entries:
            _num = _com_map_fp.get(e.comision_id).numero if e.comision_id and _com_map_fp.get(e.comision_id) else 1
            rows.append({
                "_eid": e.id,
                "Día": e.dia,
                "Inicio": _time_str(e.hora_inicio),
                "Fin": _time_str(e.hora_fin),
                "Comisión": _num,
                "Tipo": e.tipo_clase or "sin determinar",
                # 2026-09-23: virtual como booleano; None (heredar
                # histórico) se muestra como False — "un nulo se
                # interpreta como falso por defecto".
                "Virtual": bool(e.virtual),
            })
        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=[
                    "_eid", "Día", "Inicio", "Fin",
                    "Comisión", "Tipo", "Virtual",
                ]
            )
        )
        if not df.empty:
            df["_sk"] = df["Día"].map(_DIA_ORD).fillna(9)
            df = (
                df.sort_values(["Comisión", "_sk", "Inicio"])
                .drop(columns="_sk")
                .reset_index(drop=True)
            )
            df["Hs"] = df.apply(_entry_hours, axis=1)
        else:
            df["Hs"] = pd.Series(dtype=float)
        st.session_state[init_key] = df
        st.session_state[saved_key] = {
            e.id: (
                _com_map_fp.get(e.comision_id).numero
                if e.comision_id and _com_map_fp.get(e.comision_id)
                else 1
            )
            for e in entries
        }
        st.session_state[fp_key] = _current_fp
    else:
        df = st.session_state[init_key]

    # Time options dinámicos
    existing_times: set[str] = set()
    if not df.empty:
        for tc in ["Inicio", "Fin"]:
            existing_times.update(df[tc].dropna().astype(str).str[:5])
    time_opts = sorted(set(_opciones_horarias()) | existing_times)

    edited = st.data_editor(
        df,
        column_config={
            "_eid": None,
            "Día": st.column_config.SelectboxColumn(
                "Día", options=_DIAS_LIST, required=True, width="medium",
            ),
            "Inicio": st.column_config.SelectboxColumn(
                "Inicio", options=time_opts, required=True, width="small",
            ),
            "Fin": st.column_config.SelectboxColumn(
                "Fin", options=time_opts, required=True, width="small",
            ),
            "Comisión": st.column_config.SelectboxColumn(
                "Comisión", options=com_options, required=True, width="small",
            ),
            "Tipo": st.column_config.SelectboxColumn(
                "Tipo",
                options=["sin determinar", "teorica", "laboratorio"],
                default="sin determinar",
                help=(
                    "Dejalo en 'sin determinar' salvo que sea "
                    "estrictamente necesario fijarlo ya: el tipo lo "
                    "resuelve la asignación automática (LP). Elegí "
                    "teórica o laboratorio sólo si hace falta "
                    "predeterminarlo."
                ),
                width="small",
            ),
            "Virtual": st.column_config.CheckboxColumn(
                "Virtual",
                default=False,
                help=(
                    "Sólo para excepciones: tildá cuando ESTA clase "
                    "se dicta virtual aunque el dictado sea "
                    "presencial. Si toda la materia es virtual, se "
                    "configura en el dictado, no acá. Destildado = "
                    "presencial. Un laboratorio no puede ser virtual."
                ),
                width="small",
            ),
            "Hs": st.column_config.NumberColumn(
                "Hs", format="%.1f", width="small", disabled=True,
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{_kp}_de",
    )

    st.caption(
        "Editá horarios, días y comisiones. Usá + para agregar filas y "
        "el icono de papelera para eliminar. Los cambios se aplican al "
        "presionar 'Guardar cambios'. La columna Hs se recalcula al guardar."
    )

    # --- Resumen y validaciones ---
    if not edited.empty:
        edited = edited.copy()
        edited["Hs"] = edited.apply(_entry_hours, axis=1)

    valid_df = edited.dropna(subset=["Día", "Inicio", "Fin"])
    new_total = sum(_entry_hours(r) for _, r in valid_df.iterrows())
    paralelas = _max_clases_paralelas(valid_df)

    st.markdown(
        f"**Resumen:** {len(valid_df)} clases · "
        f"{_fmt_hours(new_total)} en cronograma · "
        f"{n_com} comision(es)"
    )

    # Hours by comision
    hours_by_com: dict[int, float] = {c: 0.0 for c in com_options}
    for _, r in valid_df.iterrows():
        cn = r.get("Comisión")
        if cn in hours_by_com:
            hours_by_com[cn] += _entry_hours(r)
    hours_by_com = {c: round(h, 2) for c, h in hours_by_com.items()}

    # =========================================================================
    # Caso especial: materia sin horarios (Faltante)
    # =========================================================================
    # Si la materia no tiene ninguna entry en el cronograma, es una
    # "Faltante" (dictado creado en el ciclo pero sin horarios
    # cargados). En ese caso muchos checks no aplican (n_com derivado,
    # comisiones vacías, etc.) y sólo confunden. Mostramos un check
    # único consistente con el badge "📭 Faltante" de la tabla resumen.
    sin_entries = len(valid_df) == 0

    if sin_entries:
        checks = [{
            "id": "materia_faltante",
            "label": "Faltante",
            "status": "faltante",
            "detail": (
                "Esta materia tiene un dictado en el ciclo pero no "
                "tiene horarios cargados en el cronograma. Cargá las "
                "clases con el calendario de arriba (drag sobre celdas "
                "vacías) o **borrá el dictado desde el panel de Ciclos** "
                "si la materia no se va a dictar."
            ),
        }]
    else:
        # =====================================================================
        # 10 chequeos estructurados (solo si hay horarios cargados)
        # =====================================================================
        checks = _compute_checks(
            h_sem=db_hsem, n_com=n_com, total=new_total,
            paralelas=paralelas, hours_by_com=hours_by_com,
            has_lab=has_lab, h_teo=db_hteo, h_lab=db_hlab,
            valid_df=valid_df, com_options=com_options,
            config_global=_config_global,
        )

    # Worst status — `faltante` tiene su propio nivel para que el icono
    # del header coincida con el badge 📭 de la tabla resumen.
    worst = "ok"
    for ck in checks:
        if ck["status"] == "faltante":
            worst = "faltante"
            break
        if ck["status"] == "error":
            worst = "error"
            break
        if ck["status"] == "warn" and worst != "error":
            worst = "warn"
    if worst == "ok" and not any(c["status"] == "ok" for c in checks):
        worst = "info"

    st.session_state[f"{_kp}_chk_worst"] = worst

    # Render checks
    icon_map = {
        "ok": "✅", "warn": "⚠️", "error": "🔺", "info": "ℹ️",
        "faltante": "📭",
    }
    for ck in checks:
        ico = icon_map.get(ck["status"], "•")
        st.markdown(f"{ico} **{ck['label']}:** {ck['detail']}")

    # --- Resumen por comisión ---
    summary_rows = []
    for cn in com_options:
        ce = (
            valid_df[valid_df["Comisión"] == cn]
            if not valid_df.empty else pd.DataFrame()
        )
        horarios = []
        for _, r in ce.iterrows():
            phi = str(r["Inicio"])[:5]
            phf = str(r["Fin"])[:5]
            horarios.append(f"{str(r['Día'])[:3]} {phi}-{phf}")
        summary_rows.append({
            "Comisión": cn,
            "Clases": len(ce),
            "Horas": _fmt_hours(hours_by_com.get(cn, 0)),
            "Horarios": ", ".join(horarios) if horarios else "—",
        })
    st.dataframe(
        pd.DataFrame(summary_rows),
        use_container_width=True, hide_index=True,
    )

    # --- Save / Discard ---
    _cmp_cols = ["Día", "Inicio", "Fin", "Comisión", "Tipo", "Virtual"]
    orig_cmp = df[_cmp_cols].reset_index(drop=True)
    edit_cmp = edited[_cmp_cols].reset_index(drop=True)
    has_changes = (
        len(orig_cmp) != len(edit_cmp) or not orig_cmp.equals(edit_cmp)
    )
    st.session_state[
        f"{_kp}_has_changes"
    ] = has_changes

    if has_changes:
        sc1, sc2 = st.columns([3, 1])
        with sc2:
            if st.button(
                "Descartar cambios",
                key=f"{_kp}_discard",
                help="Descarta ediciones y vuelve al estado guardado.",
            ):
                for _k in list(st.session_state.keys()):
                    if isinstance(_k, str) and _k.startswith((
                        f"{_kp}_init_df",
                        f"{_kp}_de",
                        f"{_kp}_has_changes",
                    )):
                        del st.session_state[_k]
                st.toast("Cambios descartados.")
                st.rerun()
        with sc1:
            if st.button(
                "💾 Guardar cambios",
                type="primary",
                key=f"{_kp}_save",
            ):
                try:
                    _persist_edits(
                        schedule_id, materia_codigo, valid_df,
                    )
                except ValueError as _exc:
                    # Validaciones de coherencia (2026-09-23):
                    # inicio >= fin o laboratorio virtual.
                    st.error(f"No se pudo guardar: {_exc}")
                else:
                    # Limpiar caches
                    for _k in list(st.session_state.keys()):
                        if isinstance(_k, str) and _k.startswith((
                            f"{_kp}_init_df",
                            f"{_kp}_de",
                            f"{_kp}_has_changes",
                            f"{_kp}_saved",
                            f"{_kp}_chk_worst",
                        )):
                            del st.session_state[_k]
                    st.toast("Cronograma actualizado.")
                    st.rerun()

    return worst


# =============================================================================
# Helpers
# =============================================================================

def _derive_n_comisiones(
    entries: list[ScheduleEntryDB],
    schedule_id: str | None = None,
    materia_codigo: str | None = None,
) -> int:
    """Derivar n_comisiones del set de entries (max comision asignada o 1).

    ``schedule_id`` / ``materia_codigo`` acotan la resolución de las
    comisiones referenciadas (fix auditoría H8.4, 2026-09-23: sin el
    scope, un ``comision_id`` que apuntara a una comisión de OTRO
    cronograma — dato corrupto tipo import cross-schedule, como el
    caso FB15 documentado en el commit 6b21c1f — contribuía su
    ``numero`` al máximo e inflaba el resultado).
    """
    if not entries:
        return 1
    # Resolver los numeros de las comisiones referenciadas.
    com_ids = {e.comision_id for e in entries if e.comision_id}
    max_com = 1
    if com_ids:
        with next(get_session()) as _s:
            _stmt = select(ComisionDB).where(
                ComisionDB.id.in_(com_ids)  # type: ignore[attr-defined]
            )
            if schedule_id is not None:
                _stmt = _stmt.where(ComisionDB.schedule_id == schedule_id)
            if materia_codigo is not None:
                _stmt = _stmt.where(
                    ComisionDB.materia_codigo == materia_codigo
                )
            for c in _s.exec(_stmt).all():
                if c.numero > max_com:
                    max_com = c.numero
    # Constraint: paralelas
    paralelas = _max_paralelas_in_entries(entries)
    return max(max_com, paralelas, 1)


def _max_paralelas_in_entries(entries: list[ScheduleEntryDB]) -> int:
    """Máximo de clases en paralelo (mismo día/horario)."""
    slots: dict[tuple, int] = {}
    for e in entries:
        key = (
            e.dia,
            (e.hora_inicio.hour, e.hora_inicio.minute),
            (e.hora_fin.hour, e.hora_fin.minute),
        )
        slots[key] = slots.get(key, 0) + 1
    return max(slots.values()) if slots else 0


def _max_clases_paralelas(valid_df: pd.DataFrame) -> int:
    """Máximo de clases en paralelo desde el data_editor en vivo."""
    if valid_df.empty:
        return 0
    slots: dict[tuple, int] = {}
    for _, r in valid_df.iterrows():
        key = (
            str(r["Día"]),
            str(r["Inicio"])[:5],
            str(r["Fin"])[:5],
        )
        slots[key] = slots.get(key, 0) + 1
    return max(slots.values()) if slots else 0


def _reassign_round_robin(
    entries: list[ScheduleEntryDB], n_com: int,
) -> dict[str, int]:
    """Redistribuye entries entre comisiones balanceando por horas.

    Returns:
        dict de {entry_id: comision}.
    """
    # Agrupar por slot (día + hora_inicio + hora_fin) — clases paralelas
    # van a comisiones distintas
    slot_groups: dict[tuple, list[ScheduleEntryDB]] = {}
    for e in entries:
        key = (
            e.dia,
            (e.hora_inicio.hour, e.hora_inicio.minute),
            (e.hora_fin.hour, e.hora_fin.minute),
        )
        slot_groups.setdefault(key, []).append(e)

    com_hours: dict[int, float] = {c: 0.0 for c in range(1, n_com + 1)}
    assignments: dict[str, int] = {}

    for key in sorted(
        slot_groups,
        key=lambda k: (_DIA_ORD.get(k[0], 9), k[1], k[2]),
    ):
        group = slot_groups[key]
        # Duración del slot (igual para todas las paralelas)
        e0 = group[0]
        dur = (
            e0.hora_fin.hour * 60 + e0.hora_fin.minute
            - e0.hora_inicio.hour * 60 - e0.hora_inicio.minute
        ) / 60.0

        if len(group) > 1:
            # Paralelas: a comisiones distintas, prefiriendo las que
            # tienen menos horas
            avail = sorted(
                range(1, n_com + 1), key=lambda c: com_hours[c]
            )
            for i, e in enumerate(group):
                cn = avail[i % len(avail)]
                assignments[e.id] = cn
                com_hours[cn] += dur
        else:
            cn = min(range(1, n_com + 1), key=lambda c: com_hours[c])
            assignments[group[0].id] = cn
            com_hours[cn] += dur

    return assignments


def _validar_filas_editor(valid_df: pd.DataFrame) -> list[str]:
    """Validaciones de coherencia de las filas de un data editor de
    horarios, antes de persistir (2026-09-23).

    Reglas:
    - ``hora_inicio`` debe ser estrictamente menor que ``hora_fin``.
    - Una clase de tipo ``laboratorio`` no puede ser virtual.

    Devuelve la lista de mensajes de error (vacía si todo está bien).
    Compartida por el editor por materia, el editor "Por materia" del
    tab Ver/Editar y los ajustes manuales del importador.
    """
    errores: list[str] = []
    for _idx, r in valid_df.iterrows():
        _hi = str(r.get("Inicio", ""))[:5]
        _hf = str(r.get("Fin", ""))[:5]
        _dia = r.get("Día", "?")
        if ":" in _hi and ":" in _hf and _hi >= _hf:
            errores.append(
                f"{_dia} {_hi}–{_hf}: la hora de inicio debe ser "
                "anterior a la hora de fin."
            )
        _tipo = str(r.get("Tipo", "") or "")
        _virt = bool(r.get("Virtual", False))
        if _tipo == "laboratorio" and _virt:
            errores.append(
                f"{_dia} {_hi}–{_hf}: una clase de laboratorio no "
                "puede ser virtual — el laboratorio requiere un aula "
                "física."
            )
    return errores


def _persist_edits(
    schedule_id: str, materia_codigo: str, valid_df: pd.DataFrame,
) -> None:
    """Persiste las ediciones del data_editor a ScheduleEntryDB.

    Reusa `sync_preview_edits_to_schedule` que ya soporta upsert por
    entry_id (con prefijo "new_" para filas nuevas) y elimina filas
    que ya no están en el set.

    Convierte el numero de comisión (columna "Comisión") a comision_id
    usando `get_or_create_comision_by_numero` — crea la ComisionDB si
    todavía no existe para ese (schedule, materia, numero).

    Raises:
        ValueError: si alguna fila rompe las reglas de coherencia
            (``_validar_filas_editor``): inicio >= fin, o laboratorio
            marcado virtual.
    """
    _errs = _validar_filas_editor(valid_df)
    if _errs:
        raise ValueError("; ".join(_errs))
    sync_entries = []
    # Pre-resolver numero -> comision_id para no crear duplicados en
    # la misma pasada (evita race si aparece un mismo numero varias
    # veces en el batch).
    _num_to_id: dict[int, str] = {}
    with next(get_session()) as _s0:
        for _, r in valid_df.iterrows():
            _num_raw = r.get("Comisión")
            if pd.isna(_num_raw):
                continue
            _num = int(_num_raw)
            if _num not in _num_to_id:
                _num_to_id[_num] = get_or_create_comision_by_numero(
                    _s0, materia_codigo, _num,
                    schedule_id=schedule_id,
                ).id

    for i, (_, r) in enumerate(valid_df.iterrows()):
        eid = (
            r["_eid"]
            if pd.notna(r.get("_eid"))
            else f"new_{materia_codigo}_{i}"
        )
        com_num = (
            int(r["Comisión"]) if pd.notna(r.get("Comisión")) else 1
        )
        com_id = _num_to_id.get(com_num)
        hi_str = str(r["Inicio"])[:5]
        hf_str = str(r["Fin"])[:5]
        tipo_raw = r.get("Tipo")
        tipo = (
            None
            if (not tipo_raw or tipo_raw == "sin determinar")
            else str(tipo_raw)
        )
        sync_entries.append({
            "entry_id": eid,
            "dia": r["Día"],
            "hora_inicio": (
                time.fromisoformat(hi_str) if ":" in hi_str else r["Inicio"]
            ),
            "hora_fin": (
                time.fromisoformat(hf_str) if ":" in hf_str else r["Fin"]
            ),
            "comision_id": com_id,
            "tipo_clase": tipo,
            # 2026-09-23: la columna Virtual (checkbox) se persiste
            # como booleano — un nulo se interpreta como False. Antes
            # el sync recibía None y pisaba el flag de las entries.
            "virtual": bool(r.get("Virtual", False)),
        })

    with next(get_session()) as session:
        sync_preview_edits_to_schedule(
            session, schedule_id, materia_codigo, sync_entries,
        )


# =============================================================================
# Computación de los 10 chequeos estructurados
# =============================================================================


def compute_materia_checks_from_db(
    schedule_id: str, materia_codigo: str,
) -> dict:
    """Computa los chequeos estructurales de una materia leyendo el
    estado persistido en DB (sin depender de un data_editor en vivo).

    Consumido por `Ver / Editar` en `6_📅_Cronogramas.py` y por las
    tarjetas per-materia del preview del importer, para renderar
    validaciones inline sin duplicar la lógica del editor por-materia.

    Returns:
        dict con:
        - ``checks``: lista de dicts ``{id, label, status, detail}``
          (misma forma que ``_compute_checks``). Cuando la materia no
          tiene ninguna entry, contiene un único check
          ``materia_faltante`` (misma semántica que en el editor).
        - ``worst``: ``'ok' | 'warn' | 'error' | 'info' | 'faltante'``
          — misma prioridad que en `render_schedule_materia_detail`.
        - ``estado``: label corto para el badge externo, uno de
          ``"OK" | "Revisión" | "Sin horarios" | "Sin datos"``. Es un
          subconjunto de los seis estados de
          ``validation_ui._estado_de_materia`` (`VALIDACIONES.md`
          § 3.2): los que dependen del cruce con el ciclo
          (``Conflictiva``, ``No esperada``, ``Faltante``) necesitan
          el summary de ``validar_cronograma`` y no se computan acá.
          ``"Sin horarios"`` significa "sin entries en ESTE
          cronograma", sin verificar si la materia tiene dictado en el
          ciclo (fix auditoría 2026-09-23: antes se llamaba
          ``"Faltante"`` y generaba falsos positivos con el
          vocabulario del panel Validar). ``"Sin datos"`` cubre
          materia fuera del catálogo y materia con entries pero sin
          ``horas_semanales`` (prioridad sobre ``"Revisión"``, igual
          criterio que ``_estado_de_materia``).
        - ``n_entries``: cantidad de entries persistidas.
        - ``n_comisiones``: cantidad de ``ComisionDB`` reales del
          ``(cronograma, materia)`` — fix auditoría H8 (2026-09-23):
          antes se usaba el **máximo número** de comisión, que con
          numeración con huecos (comisiones 1 y 3) inventaba
          comisiones inexistentes y contradecía al panel Validar.
    """
    from src.database.crud import get_or_create_config, materia_crud

    with next(get_session()) as session:
        mat_db = materia_crud.get(session, materia_codigo)
        if mat_db is None:
            # Guard temprano (fix auditoría 2026-09-23: antes se
            # ejecutaban las otras cuatro queries antes de chequear).
            return {
                "checks": [{
                    "id": "materia_no_catalogo",
                    "label": "Materia no está en el catálogo",
                    "status": "error",
                    "detail": (
                        f"El código '{materia_codigo}' no aparece en el "
                        "catálogo de materias."
                    ),
                }],
                "worst": "error",
                "estado": "Sin datos",
                "n_entries": 0,
                "n_comisiones": 0,
            }
        entries = list(session.exec(
            select(ScheduleEntryDB)
            .where(ScheduleEntryDB.schedule_id == schedule_id)
            .where(ScheduleEntryDB.codigo_materia == materia_codigo)
        ).all())
        has_lab = session.exec(
            select(MateriaLaboratorioDB)
            .where(MateriaLaboratorioDB.materia_codigo == materia_codigo)
            .limit(1)
        ).first() is not None
        config_global = get_or_create_config(session)
        com_map = _build_comisiones_map(session, schedule_id, materia_codigo)

    if not entries:
        # Materia sin horarios cargados EN ESTE cronograma. No es el
        # "Faltante" del panel Validar (eso implica dictado en el
        # ciclo, que acá no se cruza).
        return {
            "checks": [{
                "id": "materia_faltante",
                "label": "Sin horarios",
                "status": "faltante",
                "detail": (
                    "Esta materia no tiene horarios cargados en el "
                    "cronograma. Cargá clases desde el editor por "
                    "materia o desde el importer masivo."
                ),
            }],
            "worst": "faltante",
            "estado": "Sin horarios",
            "n_entries": 0,
            "n_comisiones": 0,
        }

    # Reconstruir el DataFrame que `_compute_checks` espera.
    #
    # Fix auditoría H8 (2026-09-23): las entries sin comisión asignada
    # (o con `comision_id` que no resuelve dentro de este cronograma —
    # dato corrupto tipo cross-schedule) ya NO se colapsan en la
    # comisión 1: van con el centinela 0, quedan fuera de
    # `hours_by_com`, y se reportan con un check propio. Antes
    # inflaban las horas de la comisión 1 y contradecían la fila
    # "Sin asignar" del resumen por comisión de la misma pantalla.
    _SIN_COM = 0
    rows = []
    n_sin_comision = 0
    for e in entries:
        _com = com_map.get(e.comision_id) if e.comision_id else None
        if _com is None:
            _num = _SIN_COM
            n_sin_comision += 1
        else:
            _num = _com.numero
        rows.append({
            "_eid": e.id,
            "Día": e.dia,
            "Inicio": _time_str(e.hora_inicio),
            "Fin": _time_str(e.hora_fin),
            "Comisión": _num,
            "Tipo": e.tipo_clase or "sin determinar",
        })
    valid_df = pd.DataFrame(rows)
    valid_df["Hs"] = valid_df.apply(_entry_hours, axis=1)

    h_sem = float(mat_db.horas_semanales or 0.0)
    h_teo = mat_db.horas_teoria
    h_lab = mat_db.horas_laboratorio

    # Fix auditoría H8 (2026-09-23): `n_com` es la CANTIDAD de
    # comisiones reales del (cronograma, materia); la numeración es
    # etiqueta, no cardinalidad. Sin piso de `paralelas`: así el check
    # "Clases paralelas ≤ comisiones" recupera su función (antes el
    # piso lo volvía estructuralmente incapaz de fallar y el problema
    # real se disfrazaba de "comisiones vacías").
    n_com = max(len(com_map), 1)
    com_options = (
        sorted({c.numero for c in com_map.values()})
        if com_map else [1]
    )

    hours_by_com: dict[int, float] = {c: 0.0 for c in com_options}
    for _, r in valid_df.iterrows():
        cn = r.get("Comisión")
        if cn in hours_by_com:
            hours_by_com[cn] += _entry_hours(r)
    hours_by_com = {c: round(h, 2) for c, h in hours_by_com.items()}

    total = sum(_entry_hours(r) for _, r in valid_df.iterrows())
    paralelas = _max_clases_paralelas(valid_df)

    checks = _compute_checks(
        h_sem=h_sem, n_com=n_com, total=total,
        paralelas=paralelas, hours_by_com=hours_by_com,
        has_lab=has_lab, h_teo=h_teo, h_lab=h_lab,
        valid_df=valid_df, com_options=com_options,
        config_global=config_global,
    )

    if n_sin_comision:
        checks.append({
            "id": "entries_sin_comision",
            "label": "Horarios sin comisión asignada",
            "status": "warn",
            "detail": (
                f"{n_sin_comision} horario(s) sin comisión asignada "
                "(o con una comisión que no pertenece a este "
                "cronograma) — no entran al cálculo de h/sem × "
                "comisiones. Asignalos desde el editor por materia."
            ),
        })

    # Chequeo lab + virtual (2026-09-23): una clase de laboratorio no
    # puede ser virtual — el laboratorio requiere aula física. El
    # importador y los editores lo bloquean; este chequeo lo hace
    # visible cuando el dato ya está persistido (por ejemplo entradas
    # cargadas antes de la regla).
    _lab_virtuales = [
        e for e in entries
        if e.tipo_clase == "laboratorio" and e.virtual is True
    ]
    if _lab_virtuales:
        _ej = _lab_virtuales[0]
        checks.append({
            "id": "lab_virtual",
            "label": "Laboratorio marcado virtual",
            "status": "error",
            "detail": (
                f"{len(_lab_virtuales)} clase(s) de laboratorio "
                f"marcada(s) como virtuales (ej: {_ej.dia} "
                f"{_ej.hora_inicio.strftime('%H:%M')}). El "
                "laboratorio requiere aula física — destildá Virtual "
                "o cambiá el tipo."
            ),
        })

    # Worst status con la misma prioridad que el editor.
    worst = "ok"
    for ck in checks:
        if ck["status"] == "faltante":
            worst = "faltante"
            break
        if ck["status"] == "error":
            worst = "error"
            break
        if ck["status"] == "warn" and worst != "error":
            worst = "warn"
    if worst == "ok" and not any(c["status"] == "ok" for c in checks):
        worst = "info"

    # `estado` para el badge externo. La categoría "Sin datos" cubre
    # `h_sem is None` (que el editor deja como info/warn en algunos
    # checks pero necesita representarse como estado propio en el badge
    # tal como en `_estado_de_materia`).
    if mat_db.horas_semanales is None:
        estado = "Sin datos"
    elif worst == "faltante":
        estado = "Sin horarios"
    elif worst in ("warn", "error"):
        estado = "Revisión"
    else:
        estado = "OK"

    return {
        "checks": checks,
        "worst": worst,
        "estado": estado,
        "n_entries": len(entries),
        "n_comisiones": n_com,
    }


CHECK_ICON_MAP = {
    "ok": "✅", "warn": "⚠️", "error": "🔺", "info": "ℹ️",
    "faltante": "📭",
}

ESTADO_ICON_MAP = {
    "OK": "✅",
    "Revisión": "🔎",
    # "Sin horarios" = sin entries en ESTE cronograma (sin cruce con el
    # ciclo). 📭 Faltante queda reservado al panel Validar, que sí
    # verifica dictado en el ciclo (auditoría 2026-09-23).
    "Sin horarios": "📄",
    "Faltante": "📭",
    "Sin datos": "❓",
}


def render_materia_checks_inline(
    result: dict, *, materia_codigo: str, materia_nombre: str,
    as_expander: bool = True,
) -> None:
    """Renderea el resultado de `compute_materia_checks_from_db` como
    un expander (o container) con el badge del estado.

    Consumido por el tab "Ver / Editar" tanto en modo "Por materia"
    (una sola materia visible) como en modo "Por grupo" (loop de
    expanders, uno por materia del filtro), y por las tarjetas del
    preview del importer.

    ``as_expander=False`` renderea un ``st.container(border=True)`` en
    vez de un expander — para los callers que ya están DENTRO de un
    expander (el loop per-materia del importer): Streamlit 1.52 tolera
    expanders anidados pero el rótulo quedaba duplicado y los chequeos
    a dos clics (auditoría 2026-09-23).

    No renderea el calendario ni los controles de edición — sólo el
    listado de chequeos con sus iconos.
    """
    estado = result.get("estado", "OK")
    icon = ESTADO_ICON_MAP.get(estado, "•")
    n_entries = result.get("n_entries", 0)
    n_com = result.get("n_comisiones", 0)

    _resumen = (
        f"{icon} **{materia_codigo}** · {materia_nombre} — {estado}"
    )
    if n_entries:
        _resumen += (
            f"  ·  {n_entries} entrada(s) · {n_com} comisión(es)"
        )

    if as_expander:
        _ctx = st.expander(_resumen, expanded=(estado != "OK"))
    else:
        _ctx = st.container(border=True)
    with _ctx:
        if not as_expander:
            st.markdown(f"**Chequeos estructurales** — {estado}")
        for ck in result.get("checks", []):
            ico = CHECK_ICON_MAP.get(ck.get("status", "info"), "•")
            st.markdown(
                f"{ico} **{ck.get('label', '')}:** "
                f"{ck.get('detail', '')}"
            )


def _compute_checks(
    *,
    h_sem: float, n_com: int, total: float, paralelas: int,
    hours_by_com: dict[int, float],
    has_lab: bool,
    h_teo: Optional[float], h_lab: Optional[float],
    valid_df: pd.DataFrame,
    com_options: list[int],
    config_global=None,
) -> list[dict]:
    """Computa los 10 checks documentados en VALIDACIONES.md.

    Cada check es un dict con `id`, `label`, `status`, `detail`.

    `config_global`: opcional. Si se pasa una `ConfiguracionHoraria`,
    se computa el eje adicional "Horarios dentro de config"
    (día operativo + rango + granularidad) — Fase I.1 del rediseño
    2026-09-21.
    """
    checks: list[dict] = []

    # 1. hsem_x_com
    if h_sem > 0 and total > 0:
        expected = n_com * h_sem
        if abs(expected - total) < 0.01:
            checks.append({
                "id": "hsem_x_com",
                "label": "h/sem × comisiones = total",
                "status": "ok",
                "detail": (
                    f"{_fmt_hours(h_sem)} × {n_com} = {_fmt_hours(expected)}, "
                    f"cronograma: {_fmt_hours(total)}"
                ),
            })
        else:
            checks.append({
                "id": "hsem_x_com",
                "label": "h/sem × comisiones = total",
                "status": "warn",
                "detail": (
                    f"{_fmt_hours(h_sem)} × {n_com} = {_fmt_hours(expected)}, "
                    f"pero cronograma tiene {_fmt_hours(total)}"
                ),
            })
    else:
        checks.append({
            "id": "hsem_x_com",
            "label": "h/sem × comisiones = total",
            "status": "info" if h_sem == 0 else "ok",
            "detail": (
                "Sin dato de h/sem"
                if h_sem == 0
                else "Sin horas en cronograma"
            ),
        })

    # 2. divisible
    if n_com > 1 and total > 0:
        h_per = total / n_com
        rem = h_per % 0.25
        is_clean = rem < 0.01 or rem > 0.24
        if is_clean:
            checks.append({
                "id": "divisible",
                "label": "Horas divisibles entre comisiones",
                "status": "ok",
                "detail": (
                    f"{_fmt_hours(total)} / {n_com} = {_fmt_hours(h_per)} "
                    f"por comisión"
                ),
            })
        else:
            checks.append({
                "id": "divisible",
                "label": "Horas divisibles entre comisiones",
                "status": "warn",
                "detail": (
                    f"{_fmt_hours(total)} / {n_com} = {h_per:.2f}h "
                    f"(no cae en bloques de 15 min)"
                ),
            })

    # 3. balanced
    unique_hours = {h for h in hours_by_com.values() if h > 0}
    if len(unique_hours) <= 1:
        bal_val = next(iter(unique_hours), 0)
        checks.append({
            "id": "balanced",
            "label": "Comisiones equilibradas",
            "status": "ok",
            "detail": (
                f"Todas las comisiones tienen {_fmt_hours(bal_val)} asignadas"
                if bal_val > 0
                else "Sin clases asignadas"
            ),
        })
    else:
        det = ", ".join(f"C{cn}: {_fmt_hours(h)}" for cn, h in hours_by_com.items())
        checks.append({
            "id": "balanced",
            "label": "Comisiones equilibradas",
            "status": "warn",
            "detail": f"Distribución desigual: {det}",
        })

    # 4. paralelas
    if paralelas > n_com:
        checks.append({
            "id": "paralelas",
            "label": "Clases paralelas ≤ comisiones",
            "status": "error",
            "detail": (
                f"{paralelas} paralelas pero solo {n_com} comision(es)"
            ),
        })
    else:
        checks.append({
            "id": "paralelas",
            "label": "Clases paralelas ≤ comisiones",
            "status": "ok",
            "detail": f"{paralelas} paralela(s), {n_com} comision(es)",
        })

    # 5. empty_com
    empty = [cn for cn, h in hours_by_com.items() if h == 0]
    if empty:
        checks.append({
            "id": "empty_com",
            "label": "Sin comisiones vacías",
            "status": "warn",
            "detail": (
                f"Comision(es) {', '.join(str(c) for c in empty)} sin clases"
            ),
        })
    else:
        checks.append({
            "id": "empty_com",
            "label": "Sin comisiones vacías",
            "status": "ok",
            "detail": "Todas las comisiones tienen clases",
        })

    # 6. hsem_set
    if h_sem > 0:
        checks.append({
            "id": "hsem_set",
            "label": "Horas semanales definidas",
            "status": "ok",
            "detail": _fmt_hours(h_sem),
        })
    else:
        checks.append({
            "id": "hsem_set",
            "label": "Horas semanales definidas",
            "status": "warn",
            "detail": "Sin dato. Completar para validar.",
        })

    # 7. thl_sum
    has_thl = h_teo is not None or h_lab is not None
    if has_thl:
        ht_v = h_teo or 0.0
        hl_v = h_lab or 0.0
        sum_thl = round(ht_v + hl_v, 2)
        if h_sem > 0 and abs(sum_thl - h_sem) < 0.01:
            checks.append({
                "id": "thl_sum",
                "label": "Hs teórica + Hs lab = Hs semanales",
                "status": "ok",
                "detail": f"{ht_v:g} + {hl_v:g} = {sum_thl:g} = {h_sem:g}",
            })
        elif h_sem == 0:
            checks.append({
                "id": "thl_sum",
                "label": "Hs teórica + Hs lab = Hs semanales",
                "status": "info",
                "detail": "Sin dato de h/sem para comparar",
            })
        else:
            checks.append({
                "id": "thl_sum",
                "label": "Hs teórica + Hs lab = Hs semanales",
                "status": "error",
                "detail": f"{ht_v:g} + {hl_v:g} = {sum_thl:g} ≠ {h_sem:g}",
            })
    elif has_lab:
        checks.append({
            "id": "thl_sum",
            "label": "Hs teórica + Hs lab = Hs semanales",
            "status": "warn",
            "detail": (
                "Materia con lab asignado pero sin Hs teórica/lab "
                "definidas. Completar arriba."
            ),
        })

    # 8. thl_reserva
    if has_lab and h_lab is not None and h_lab == 0 and h_teo is not None:
        checks.append({
            "id": "thl_reserva",
            "label": "Modo lab",
            "status": "info",
            "detail": (
                "Reserva puntual (Hs lab = 0): la asignación "
                "automática no fija el lab; los docentes lo "
                "reservan caso por caso."
            ),
        })
    elif has_lab and h_lab is not None and h_lab > 0:
        checks.append({
            "id": "thl_reserva",
            "label": "Modo lab",
            "status": "ok",
            "detail": (
                f"Lab fijo: {h_lab:g}h por comisión entran a la "
                "asignación."
            ),
        })
    elif has_lab and h_lab is None:
        checks.append({
            "id": "thl_reserva",
            "label": "Modo lab",
            "status": "warn",
            "detail": (
                "Materia con lab asignado pero sin Hs lab definidas."
            ),
        })

    # 9. thl_predet
    if has_lab and h_lab is not None and h_lab > 0:
        ht_v = h_teo or 0.0
        per_com_lab: dict[int, float] = {c: 0.0 for c in com_options}
        per_com_teo: dict[int, float] = {c: 0.0 for c in com_options}
        pre_lab_sum = 0.0
        pre_teo_sum = 0.0
        for _, r in valid_df.iterrows():
            dur = _entry_hours(r)
            tipo = str(r.get("Tipo", "sin determinar")).strip()
            cn = r.get("Comisión")
            if tipo == "laboratorio":
                pre_lab_sum += dur
                if cn in per_com_lab:
                    per_com_lab[cn] += dur
            elif tipo == "teorica":
                pre_teo_sum += dur
                if cn in per_com_teo:
                    per_com_teo[cn] += dur

        violators_lab = [
            (cn, h) for cn, h in per_com_lab.items() if h > h_lab + 0.01
        ]
        violators_teo = [
            (cn, h) for cn, h in per_com_teo.items() if h > ht_v + 0.01
        ]
        if not violators_lab and not violators_teo:
            det_parts = []
            if pre_lab_sum > 0:
                det_parts.append(
                    f"predeterminadas como lab: {pre_lab_sum:g}h"
                )
            if pre_teo_sum > 0:
                det_parts.append(
                    f"predeterminadas como teóricas: {pre_teo_sum:g}h"
                )
            det = (
                "; ".join(det_parts)
                if det_parts
                else "Todas 'sin determinar' (lo decide la asignación automática)"
            )
            checks.append({
                "id": "thl_predet",
                "label": "Predeterminados consistentes",
                "status": "ok",
                "detail": det,
            })
        else:
            msgs = []
            for cn, h in violators_lab:
                msgs.append(
                    f"C{cn}: lab predeterminado {h:g}h > Hs lab {h_lab:g}h"
                )
            for cn, h in violators_teo:
                msgs.append(
                    f"C{cn}: teórica predeterminada {h:g}h > "
                    f"Hs teórica {ht_v:g}h"
                )
            checks.append({
                "id": "thl_predet",
                "label": "Predeterminados consistentes",
                "status": "error",
                "detail": "; ".join(msgs),
            })

    # 10. thl_partition
    if has_lab and h_lab is not None and h_lab > 0 and h_teo is not None:
        expected_total = h_teo + h_lab
        infactibles = []
        for cn in com_options:
            ce = (
                valid_df[valid_df["Comisión"] == cn]
                if not valid_df.empty else pd.DataFrame()
            )
            durs = []
            for _, r in ce.iterrows():
                d = _entry_hours(r)
                if d > 0:
                    durs.append(d)
            if not durs:
                continue
            total_c = sum(durs)
            if abs(total_c - expected_total) > 0.01:
                infactibles.append(
                    f"C{cn}: total {total_c:g}h ≠ Hs teórica + lab "
                    f"({expected_total:g}h)"
                )
                continue
            if not _subset_sum_exists(durs, h_lab):
                durs_str = ", ".join(f"{d:g}" for d in durs)
                infactibles.append(
                    f"C{cn}: clases [{durs_str}] no se pueden "
                    f"particionar para sumar Hs lab {h_lab:g}h"
                )
        if not infactibles:
            checks.append({
                "id": "thl_partition",
                "label": "Partición teórica/lab factible",
                "status": "ok",
                "detail": (
                    f"Cada comisión puede dividirse en {h_teo:g}h teórica "
                    f"+ {h_lab:g}h lab"
                ),
            })
        else:
            checks.append({
                "id": "thl_partition",
                "label": "Partición teórica/lab factible",
                "status": "error",
                "detail": "; ".join(infactibles),
            })

    # 11. config_horaria — cada horario respeta día operativo + rango
    # operativo + granularidad de `ConfiguracionHoraria` (Fase I.1
    # del rediseño 2026-09-21). Antes esto solo se veía como sección
    # aparte al final del panel; ahora es un check más de la lista
    # para que no se descuelgue del resto y el badge quede alineado.
    if config_global is not None and not valid_df.empty:
        _dias_ok = {
            d.strip() for d in (config_global.dias_operativos or "").split(",")
            if d.strip()
        }
        _gran = int(config_global.granularidad_minutos or 15) or 15

        # Nota (bugfix 2026-09-22): las celdas del `data_editor` de
        # Streamlit pueden devolver `str` en vez de `datetime.time`
        # (dependiendo de qué campo se editó por última vez). Usamos
        # el helper `_parse_minutes` que ya normaliza ambos casos +
        # `_time_str` para el label, en vez de acceder a `.hour`
        # directamente.
        _base = _parse_minutes(config_global.hora_inicio_operativo) or 0
        _fin_op = _parse_minutes(config_global.hora_fin_operativo) or 0
        if (
            config_global.hora_fin_operativo.hour == 0
            and config_global.hora_fin_operativo.minute == 0
        ):
            _fin_op = 24 * 60

        _out_rows: list[str] = []
        for _, _row in valid_df.iterrows():
            _dia = _row.get("Día")
            _ini = _row.get("Inicio")
            _fin = _row.get("Fin")
            if _ini is None or _fin is None or _dia is None:
                continue
            _razones: list[str] = []
            if _dias_ok and _dia not in _dias_ok:
                _razones.append("día no operativo")
            _hi = _parse_minutes(_ini)
            _hf = _parse_minutes(_fin)
            if _hi is None or _hf is None:
                # Fila sin hora parseable — no se puede validar.
                continue
            # `00:00` como fin lo interpretamos como fin de día (24:00).
            if _hf == 0:
                _hf = 24 * 60
            if _hi < _base:
                _razones.append(
                    f"inicio {_time_str(_ini)} < "
                    f"{config_global.hora_inicio_operativo.strftime('%H:%M')}"
                )
            if _hf > _fin_op:
                _razones.append(
                    f"fin {_time_str(_fin)} > "
                    f"{config_global.hora_fin_operativo.strftime('%H:%M')}"
                )
            if _hi >= _base and (_hi - _base) % _gran != 0:
                _razones.append(
                    f"inicio no múltiplo de {_gran} min"
                )
            if _base < _hf <= _fin_op and (_hf - _base) % _gran != 0:
                _razones.append(
                    f"fin no múltiplo de {_gran} min"
                )
            if _razones:
                _out_rows.append(
                    f"{_dia} {_time_str(_ini)}–"
                    f"{_time_str(_fin)}: "
                    + ", ".join(_razones)
                )

        if _out_rows:
            checks.append({
                "id": "config_horaria",
                "label": "Horarios respetan la configuración",
                "status": "warn",
                "detail": (
                    f"{len(_out_rows)} horario(s) rompen día operativo / "
                    f"rango / granularidad: "
                    + "; ".join(_out_rows[:3])
                    + (
                        f" … (+{len(_out_rows) - 3} más)"
                        if len(_out_rows) > 3 else ""
                    )
                ),
            })
        else:
            checks.append({
                "id": "config_horaria",
                "label": "Horarios respetan la configuración",
                "status": "ok",
                "detail": (
                    f"Todos los horarios caen dentro del rango "
                    f"{config_global.hora_inicio_operativo.strftime('%H:%M')}-"
                    f"{config_global.hora_fin_operativo.strftime('%H:%M')} "
                    f"y son múltiplos de {_gran} min."
                ),
            })

    return checks


# =============================================================================
# Calendario editable filtrado a la materia
# =============================================================================

def _render_editable_calendar(
    *, schedule_id: str, materia_codigo: str, kp: str,
    save_as_copy: bool,
) -> None:
    """Renderiza el calendario semanal editable filtrado a la materia.

    Soporta:
    - **drag/resize** sobre eventos existentes → actualiza dia + horarios.
    - **click** sobre evento → abre dialog de "Editar entrada" (con
      tipo de clase + comisión + eliminar).
    - **select** (drag sobre celdas vacías) → abre dialog "Agregar
      entrada" pre-llenando dia/inicio/fin/materia.

    Si `save_as_copy=True`, todas las mutaciones se aplican a una
    copia del cronograma (creada al primer save) en lugar del original.
    """
    with next(get_session()) as session:
        config = get_or_create_config(session)
        grid_full = build_schedule_grid(session, schedule_id)

    # Filtrar a la materia
    grid_filt: dict[str, list] = {
        dia: [b for b in blocks if b.materia_codigo == materia_codigo]
        for dia, blocks in grid_full.items()
    }
    grid_filt = {d: bs for d, bs in grid_filt.items() if bs}

    # Si hay un dialog pendiente, NO procesar nuevas acciones del
    # calendario: el dialog en si causa rerun con su Guardar/Cancelar
    # y FullCalendar puede estar replayendo el ultimo evento.
    if (
        "_sme_pending_click" in st.session_state
        or "_sme_pending_select" in st.session_state
    ):
        # Aun asi rendereamos el calendario para que el usuario lo vea,
        # pero ignoramos cualquier action.
        with next(get_session()) as _ro_sess:
            from src.ui.calendar_render import render_schedule_calendar
            render_schedule_calendar(
                grid_filt, config,
                key=f"{kp}_cal_ro_dialog",
                color_by_comision=True,
            )
        return

    st.markdown(
        "**🗓️ Calendario** — drag para mover/redimensionar, click "
        "para editar, drag sobre celdas vacías para agregar"
    )
    action = render_editable_schedule_calendar(
        grid_filt, config,
        key=f"{kp}_cal_edit",
        allow_empty=True,  # permitir seleccionar rangos aunque no haya entries
        color_by_comision=True,
    )

    if action is None:
        return

    # Each action produces a unique "key" so we don't reprocess the
    # same action across reruns.
    _key_str = (
        f"{action.action}|{getattr(action, 'entry_id', '') or ''}|"
        f"{action.dia}|{action.hora_inicio}|{action.hora_fin}"
    )

    # Cache global de actions procesadas en esta sesion (no por accion).
    # Si el mismo evento ya fue procesado, ignoramos. Esto deduplica
    # callbacks de FullCalendar que se replayan en reruns. Cap el set
    # a 200 entries (FIFO mediante list+set) para evitar leak.
    _processed_set: set = st.session_state.setdefault(
        "_sme_processed_actions", set(),
    )
    _processed_list: list = st.session_state.setdefault(
        "_sme_processed_actions_order", [],
    )
    if _key_str in _processed_set:
        return
    _processed_set.add(_key_str)
    _processed_list.append(_key_str)
    # Evict oldest si supera el cap
    while len(_processed_list) > 200:
        _evicted = _processed_list.pop(0)
        _processed_set.discard(_evicted)

    if action.action == "move":
        # Tratar el move EXACTAMENTE como un click: abrir el dialog de
        # edicion con los nuevos valores propuestos. Eso evita que un
        # drag accidental (o que FullCalendar mande eventChange por un
        # click sin drag real) modifique la DB sin confirmacion.
        # IMPORTANTE: el `pending["dia"/"hora_*"]` lleva los nuevos
        # valores propuestos (precarga del dialog), pero `_baseline_*`
        # lleva los valores actuales en DB para comparar al guardar y
        # detectar el cambio del move correctamente.
        if not action.entry_id:
            return
        with next(get_session()) as session:
            _entry = session.get(ScheduleEntryDB, action.entry_id)
            if _entry is None:
                return
            _baseline_dia = _entry.dia
            _baseline_hi = _entry.hora_inicio
            _baseline_hf = _entry.hora_fin
            _tipo = _entry.tipo_clase
            _com = _numero_de_entry(session, _entry)
        st.session_state["_sme_pending_click"] = {
            "schedule_id": schedule_id,
            "entry_id": action.entry_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "comision": _com,
            "tipo_clase": _tipo,
            "_baseline_dia": _baseline_dia,
            "_baseline_hi": _baseline_hi,
            "_baseline_hf": _baseline_hf,
            "_kp": kp,
            "_save_as_copy": save_as_copy,
            "_key": _key_str,
        }
        _dialog_edit_entry()

    elif action.action == "click":
        if not action.entry_id:
            return
        # Buscar el comision/tipo actual de la entry (no viene en CalendarAction)
        with next(get_session()) as session:
            _entry = session.get(ScheduleEntryDB, action.entry_id)
            _tipo = _entry.tipo_clase if _entry else None
        st.session_state["_sme_pending_click"] = {
            "schedule_id": schedule_id,
            "entry_id": action.entry_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "comision": action.comision,
            "tipo_clase": _tipo,
            "_kp": kp,
            "_save_as_copy": save_as_copy,
            "_key": _key_str,
        }
        _dialog_edit_entry()

    elif action.action == "select":
        st.session_state["_sme_pending_select"] = {
            "schedule_id": schedule_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "_kp": kp,
            "_save_as_copy": save_as_copy,
            "_key": _key_str,
        }
        _dialog_add_entry()
