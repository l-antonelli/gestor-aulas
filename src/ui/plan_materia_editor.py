"""Editor inline de una materia dentro de un plan de cursada.

`render_plan_materia_detail(plan_id, materia_codigo, key_ns)` renderiza
el detalle completo de UNA materia: comisiones, horarios, cupo,
coeficiente de asignación y override de método de forecast. Reusable
desde:
- El panel de validación unificado (`validation_ui._render_detalle_por_materia`)
- El editor de plan en `app/pages/5_📊_Planes.py` (eventualmente
  reemplazando el "Desglose por Materia" actual).

La función NO renderiza el header de la materia (nombre, año, etc) —
asume que el caller ya está dentro de un contenedor relevante. Foco
estricto en la edición.

Asume:
- El plan_id existe y pertenece a un ciclo.
- materia_codigo tiene comisiones en el plan (caso vacío: muestra
  bloque "Agregar comisión" pero no hay nada para editar).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Optional

import pandas as pd
import streamlit as st
from sqlmodel import col, select

from src.database.connection import get_session
from src.database.crud import get_or_create_config, materia_crud
from src.database.models import (
    CicloDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanificacionCursadaDB,
)
from src.domain.types import DIAS_SEMANA
from src.services.plan_generation_service import (
    apply_horario_edits,
    build_timetable_grid,
    generate_time_slots,
)
from src.services.validations import validar_factibilidad_particion_horas
from src.services.schedule_service import ScheduleBlock
from src.ui.calendar_render import render_editable_schedule_calendar


_DIA_ORD = {
    "Lunes": 0, "Martes": 1, "Miércoles": 2,
    "Jueves": 3, "Viernes": 4, "Sábado": 5,
}


# =============================================================================
# Dialogs para editar/agregar HorarioDB via calendario embebido
# =============================================================================

@st.dialog("Editar horario", width="large")
def _dialog_edit_horario():
    """Dialog para editar un HorarioDB del plan desde el calendario.

    Diferencias respecto al de cronograma:
    - Selector de comisión existente (opciones: comisiones de la materia
      en el plan).
    - Comisión es obligatoria (HorarioDB.comision_id es FK no nullable).
    """
    pending = st.session_state.get("_pme_pending_click")
    if not pending:
        st.rerun()
        return

    _plan_id = pending["plan_id"]
    _materia_codigo = pending["materia_codigo"]
    _dias_list = list(_DIA_ORD.keys())

    # Comisiones existentes para esta materia en el plan
    with next(get_session()) as session:
        _coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == _plan_id)
            .where(ComisionDB.materia_codigo == _materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())
    if not _coms:
        st.error("La materia no tiene comisiones. Cancelá y agregá una primero.")
        if st.button("Cerrar"):
            del st.session_state["_pme_pending_click"]
            st.rerun()
        return

    _com_options = {f"C{c.numero} — {c.nombre}": c.id for c in _coms}
    _com_keys = list(_com_options.keys())
    _current_com_id = pending.get("comision_id")
    _current_idx = 0
    if _current_com_id:
        for _i, (_lbl, _cid) in enumerate(_com_options.items()):
            if _cid == _current_com_id:
                _current_idx = _i
                break

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
            key="_pme_dlg_dia",
        )
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="_pme_dlg_ini",
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="_pme_dlg_fin",
        )

    col_com, col_tipo = st.columns(2)
    with col_com:
        new_com_lbl = st.selectbox(
            "Comisión",
            options=_com_keys,
            index=_current_idx,
            key="_pme_dlg_com",
        )
        new_com_id = _com_options[new_com_lbl]
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
            key="_pme_dlg_tipo",
            help=(
                "Sin determinar: el LP elige cuál de los bloques con "
                "horas suficientes será de laboratorio. "
                "Teórica/Laboratorio: forzar el tipo."
            ),
        )

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Guardar", type="primary", use_container_width=True):
            # Comparar contra baseline (DB) para detectar cambios reales
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
            if new_com_id != pending.get("comision_id"):
                cambios["comision_id"] = new_com_id
            _new_tipo_val = (
                None if new_tipo == "sin determinar" else new_tipo
            )
            if _new_tipo_val != (pending.get("tipo_clase") or None):
                cambios["tipo_clase"] = _new_tipo_val

            if cambios:
                with next(get_session()) as session:
                    _h = session.get(HorarioDB, pending["horario_id"])
                    if _h is not None:
                        for _k, _v in cambios.items():
                            setattr(_h, _k, _v)
                        session.add(_h)
                        session.commit()
                st.session_state["_pme_toast"] = (
                    f"{_materia_codigo} actualizada"
                )
            else:
                st.session_state["_pme_toast"] = "Sin cambios"
            st.session_state["_pme_processed_click"] = pending["_key"]
            _pme_invalidate_caches(pending)
            del st.session_state["_pme_pending_click"]
            st.rerun()
    with col2:
        if st.button("Eliminar", use_container_width=True):
            with next(get_session()) as session:
                _h = session.get(HorarioDB, pending["horario_id"])
                if _h is not None:
                    session.delete(_h)
                    session.commit()
            st.session_state["_pme_toast"] = (
                f"{_materia_codigo} eliminada"
            )
            st.session_state["_pme_processed_click"] = pending["_key"]
            _pme_invalidate_caches(pending)
            del st.session_state["_pme_pending_click"]
            st.rerun()
    with col3:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_pme_processed_click"] = pending["_key"]
            del st.session_state["_pme_pending_click"]
            st.rerun()


@st.dialog("Agregar horario", width="large")
def _dialog_add_horario():
    """Dialog para crear un HorarioDB nuevo cuando el usuario seleccionó
    un rango vacío en el calendario."""
    import uuid as _uuid
    pending = st.session_state.get("_pme_pending_select")
    if not pending:
        st.rerun()
        return

    _plan_id = pending["plan_id"]
    _materia_codigo = pending["materia_codigo"]

    # Comisiones existentes para esta materia en el plan
    with next(get_session()) as session:
        _coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == _plan_id)
            .where(ComisionDB.materia_codigo == _materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())
        # Default cupo si hay que crear comision nueva
        _mat_db = session.get(MateriaDB, _materia_codigo)
        _default_cupo = (_mat_db.cupo if (_mat_db and _mat_db.cupo) else 30)

    _NEW_COM_LABEL = "➕ Nueva comisión"
    _com_options: dict[str, Optional[str]] = {
        f"C{c.numero} — {c.nombre}": c.id for c in _coms
    }
    _com_options[_NEW_COM_LABEL] = None
    _com_keys = list(_com_options.keys())

    st.markdown(f"**Materia**: `{_materia_codigo}`")
    st.markdown(
        f"**{pending['dia']}** · "
        f"{pending['hora_inicio'].strftime('%H:%M')} - "
        f"{pending['hora_fin'].strftime('%H:%M')}"
    )

    col_com, col_tipo = st.columns(2)
    with col_com:
        new_com_lbl = st.selectbox(
            "Comisión",
            options=_com_keys, index=0,
            key="_pme_dlg_add_com",
            help="Elegí una comisión existente o creá una nueva.",
        )
    with col_tipo:
        _tipo_options = ["sin determinar", "teorica", "laboratorio"]
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=_tipo_options, index=0,
            key="_pme_dlg_add_tipo",
        )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            _tipo_val = None if new_tipo == "sin determinar" else new_tipo
            with next(get_session()) as session:
                _target_com_id = _com_options[new_com_lbl]
                if _target_com_id is None:
                    # Crear comision nueva
                    _max_num = max(
                        (c.numero for c in _coms), default=0,
                    )
                    _new_num = _max_num + 1
                    _new_com = ComisionDB(
                        id=str(_uuid.uuid4()),
                        materia_codigo=_materia_codigo,
                        plan_cursada_id=_plan_id,
                        comision_key=f"{_materia_codigo}-{_new_num:03d}",
                        nombre=f"Comision {_new_num}",
                        numero=_new_num,
                        cupo=_default_cupo,
                    )
                    session.add(_new_com)
                    session.flush()
                    _target_com_id = _new_com.id

                _new_h = HorarioDB(
                    id=str(_uuid.uuid4()),
                    comision_id=_target_com_id,
                    codigo_materia=_materia_codigo,
                    dia=pending["dia"],
                    hora_inicio=pending["hora_inicio"],
                    hora_fin=pending["hora_fin"],
                    tipo_clase=_tipo_val,
                )
                session.add(_new_h)
                session.commit()
            st.session_state["_pme_toast"] = (
                f"{_materia_codigo} agregada"
            )
            st.session_state["_pme_processed_select"] = pending["_key"]
            _pme_invalidate_caches(pending)
            del st.session_state["_pme_pending_select"]
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_pme_processed_select"] = pending["_key"]
            del st.session_state["_pme_pending_select"]
            st.rerun()


def _pme_invalidate_caches(pending: dict) -> None:
    """Limpia los caches del editor para forzar recarga desde DB."""
    _kp = pending.get("_kp")
    if not _kp:
        return
    for _k in list(st.session_state.keys()):
        if isinstance(_k, str) and _k.startswith(_kp):
            del st.session_state[_k]


def _render_plan_editable_calendar(
    *, plan_id: str, materia_codigo: str, kp: str,
) -> None:
    """Renderiza el calendario semanal editable filtrado a la materia.

    Soporta drag/resize/click/select. Las mutaciones pasan por dialogs
    de confirmación (`_dialog_edit_horario`, `_dialog_add_horario`).
    Si hay un dialog pendiente, se muestra read-only para evitar
    callbacks replayados.
    """
    # Si hay dialog activo, render read-only
    if (
        "_pme_pending_click" in st.session_state
        or "_pme_pending_select" in st.session_state
    ):
        _render_plan_calendar_readonly(plan_id, materia_codigo, kp)
        return

    # Cargar grid: convertimos HorarioDB → ScheduleBlock para reusar el
    # calendario editable (que requiere entry_id por bloque).
    with next(get_session()) as session:
        config = get_or_create_config(session)
        _coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .where(ComisionDB.materia_codigo == materia_codigo)
        ).all())
        _com_by_id = {c.id: c for c in _coms}
        _com_ids = list(_com_by_id.keys())
        _hs: list[HorarioDB] = []
        if _com_ids:
            _hs = list(session.exec(
                select(HorarioDB).where(col(HorarioDB.comision_id).in_(_com_ids))
            ).all())
        _mat_db = session.get(MateriaDB, materia_codigo)
        _mat_nombre = _mat_db.nombre if _mat_db else materia_codigo

    grid_filt: dict[str, list[ScheduleBlock]] = {}
    for h in _hs:
        com = _com_by_id.get(h.comision_id)
        block = ScheduleBlock(
            entry_id=h.id,
            materia_codigo=materia_codigo,
            materia_nombre=_mat_nombre,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            comision=com.numero if com else None,
        )
        grid_filt.setdefault(h.dia, []).append(block)

    st.markdown(
        "**🗓️ Calendario** — drag para mover/redimensionar, click "
        "para editar, drag sobre celdas vacías para agregar"
    )
    action = render_editable_schedule_calendar(
        grid_filt, config,
        key=f"{kp}_cal_edit",
        allow_empty=True,
        color_by_comision=True,
    )

    if action is None:
        return

    _key_str = (
        f"{action.action}|{getattr(action, 'entry_id', '') or ''}|"
        f"{action.dia}|{action.hora_inicio}|{action.hora_fin}"
    )

    # Cache global de actions procesadas (cap 200, FIFO)
    _processed_set: set = st.session_state.setdefault(
        "_pme_processed_actions", set(),
    )
    _processed_list: list = st.session_state.setdefault(
        "_pme_processed_actions_order", [],
    )
    if _key_str in _processed_set:
        return
    _processed_set.add(_key_str)
    _processed_list.append(_key_str)
    while len(_processed_list) > 200:
        _evicted = _processed_list.pop(0)
        _processed_set.discard(_evicted)

    if action.action == "move":
        if not action.entry_id:
            return
        with next(get_session()) as session:
            _h = session.get(HorarioDB, action.entry_id)
            if _h is None:
                return
            _baseline_dia = _h.dia
            _baseline_hi = _h.hora_inicio
            _baseline_hf = _h.hora_fin
            _tipo = _h.tipo_clase
            _com_id = _h.comision_id
        st.session_state["_pme_pending_click"] = {
            "plan_id": plan_id,
            "horario_id": action.entry_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "comision_id": _com_id,
            "tipo_clase": _tipo,
            "_baseline_dia": _baseline_dia,
            "_baseline_hi": _baseline_hi,
            "_baseline_hf": _baseline_hf,
            "_kp": kp,
            "_key": _key_str,
        }
        _dialog_edit_horario()

    elif action.action == "click":
        if not action.entry_id:
            return
        with next(get_session()) as session:
            _h = session.get(HorarioDB, action.entry_id)
            _tipo = _h.tipo_clase if _h else None
            _com_id = _h.comision_id if _h else None
        st.session_state["_pme_pending_click"] = {
            "plan_id": plan_id,
            "horario_id": action.entry_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "comision_id": _com_id,
            "tipo_clase": _tipo,
            "_kp": kp,
            "_key": _key_str,
        }
        _dialog_edit_horario()

    elif action.action == "select":
        st.session_state["_pme_pending_select"] = {
            "plan_id": plan_id,
            "materia_codigo": materia_codigo,
            "dia": action.dia,
            "hora_inicio": action.hora_inicio,
            "hora_fin": action.hora_fin,
            "_kp": kp,
            "_key": _key_str,
        }
        _dialog_add_horario()


def _render_plan_calendar_readonly(
    plan_id: str, materia_codigo: str, kp: str,
) -> None:
    """Calendario read-only (usado mientras hay un dialog abierto)."""
    from src.ui.calendar_render import render_timetable_calendar
    with next(get_session()) as session:
        plan = session.get(PlanificacionCursadaDB, plan_id)
        if plan is None or not plan.ciclo_id:
            return
        config = get_or_create_config(session)
        grid = build_timetable_grid(
            session, plan_id, config,
            filtered_materia_codigos={materia_codigo},
            ciclo_id=plan.ciclo_id,
        )
    if grid:
        render_timetable_calendar(
            grid, config, key=f"{kp}_cal_ro_dialog",
        )


def _editar_horas_materia(
    mat_db: MateriaDB, kp: str, ciclo: Optional[CicloDB],
) -> None:
    """Controles editables de hs/sem, hs teoría, hs lab + validación
    cruzada (auto-save al cambiar). Mismos controles que el editor del
    cronograma — se aplican al catálogo de la materia (afecta a todos
    los planes y cronogramas que la referencien)."""
    db_hsem = float(mat_db.horas_semanales or 0.0)
    db_hteo = mat_db.horas_teoria
    db_hlab = mat_db.horas_laboratorio

    # ¿Tiene laboratorio asignado? Para decidir si mostramos hteo/hlab.
    with next(get_session()) as session:
        has_lab = session.exec(
            select(MateriaLaboratorioDB)
            .where(MateriaLaboratorioDB.materia_codigo == mat_db.codigo)
            .limit(1)
        ).first() is not None

    ic1, ic2, ic3, ic4 = st.columns(4)
    ic1.markdown("**Horas semanales:**")
    new_hsem = ic2.number_input(
        "h/sem", value=db_hsem, min_value=0.0, step=0.25, format="%.2f",
        key=f"{kp}_hsem", label_visibility="collapsed",
    )
    if new_hsem != db_hsem:
        with next(get_session()) as _s:
            _m = materia_crud.get(_s, mat_db.codigo)
            if _m:
                _m.horas_semanales = new_hsem if new_hsem > 0 else None
                _s.add(_m)
                _s.commit()
                db_hsem = new_hsem
                st.toast(
                    f"{mat_db.codigo}: hs/sem actualizadas a {new_hsem:g}h."
                )

    if has_lab or db_hteo is not None or db_hlab is not None:
        hl_c1, hl_c2, hl_c3, hl_c4 = st.columns(4)
        hl_c1.markdown("**Hs teoría:**")
        new_hteo = hl_c2.number_input(
            "h_teo",
            value=float(db_hteo) if db_hteo is not None else 0.0,
            min_value=0.0, step=0.25, format="%.2f",
            key=f"{kp}_hteo", label_visibility="collapsed",
            help="Horas semanales de teoría. Junto con Hs lab debe sumar Hs semanales.",
        )
        hl_c3.markdown("**Hs laboratorio:**")
        new_hlab = hl_c4.number_input(
            "h_lab",
            value=float(db_hlab) if db_hlab is not None else 0.0,
            min_value=0.0, step=0.25, format="%.2f",
            key=f"{kp}_hlab", label_visibility="collapsed",
            help=(
                "Horas semanales fijas como laboratorio. Si tiene lab "
                "asignado pero Hs lab = 0, se asume reserva ad-hoc "
                "(decide el docente fuera del LP)."
            ),
        )

        sum_thl = round(new_hteo + new_hlab, 2)
        sum_ok = abs(sum_thl - round(db_hsem, 2)) < 0.01
        if not sum_ok:
            st.warning(
                f"Hs teoría ({new_hteo:g}) + Hs lab ({new_hlab:g}) = "
                f"{sum_thl:g} ≠ Hs semanales ({db_hsem:g}). Ajustá los valores."
            )
        if has_lab and new_hlab == 0 and sum_ok:
            st.caption(
                "ℹ️ Tiene laboratorios asignados con **Hs lab = 0** → "
                "reserva ad-hoc: el LP no fija lab; los docentes lo "
                "reservan caso por caso."
            )

        # Auto-save si suma OK y hay cambios
        hteo_changed = db_hteo is None or abs(new_hteo - db_hteo) > 0.001
        hlab_changed = db_hlab is None or abs(new_hlab - db_hlab) > 0.001
        if sum_ok and (hteo_changed or hlab_changed):
            with next(get_session()) as _s:
                _m = materia_crud.get(_s, mat_db.codigo)
                if _m:
                    _m.horas_teoria = new_hteo
                    _m.horas_laboratorio = new_hlab
                    _s.add(_m)
                    _s.commit()
                    st.toast(
                        f"{mat_db.codigo}: Hs teoría/lab actualizadas a "
                        f"{new_hteo:g}/{new_hlab:g}."
                    )


def _render_plan_checks(
    plan_id: str, materia_codigo: str,
    mat_coms: list[ComisionDB],
    horarios_by_comision: dict[str, list[HorarioDB]],
    mat_db: Optional[MateriaDB],
) -> str:
    """Renderiza los 10 chequeos estructurados del editor de materia,
    espejados del schedule_materia_editor pero sobre comisiones reales
    + horarios del plan. Retorna worst status (`ok`/`warn`/`error`/`info`)
    para que el caller lo cachee y el header del expander lo muestre.
    """
    import pandas as pd
    from src.ui.schedule_materia_editor import _compute_checks

    if not mat_db:
        return "info"

    db_hsem = float(mat_db.horas_semanales or 0.0)
    db_hteo = mat_db.horas_teoria
    db_hlab = mat_db.horas_laboratorio

    with next(get_session()) as session:
        has_lab = session.exec(
            select(MateriaLaboratorioDB)
            .where(MateriaLaboratorioDB.materia_codigo == materia_codigo)
            .limit(1)
        ).first() is not None

    n_com = len(mat_coms)
    com_options = [c.numero for c in mat_coms]

    # Construir DataFrame compatible con _compute_checks: columnas
    # Día, Inicio, Fin, Comisión (numero), Tipo, Hs.
    rows = []
    for c in mat_coms:
        for h in horarios_by_comision.get(c.id, []):
            dur = (
                h.hora_fin.hour * 60 + h.hora_fin.minute
                - h.hora_inicio.hour * 60 - h.hora_inicio.minute
            ) / 60.0
            rows.append({
                "Día": h.dia,
                "Inicio": h.hora_inicio.strftime("%H:%M"),
                "Fin": h.hora_fin.strftime("%H:%M"),
                "Comisión": c.numero,
                "Tipo": h.tipo_clase or "sin determinar",
                "Hs": round(max(0.0, dur), 2),
            })
    valid_df = pd.DataFrame(rows) if rows else pd.DataFrame(
        columns=["Día", "Inicio", "Fin", "Comisión", "Tipo", "Hs"],
    )

    total = float(valid_df["Hs"].sum()) if not valid_df.empty else 0.0

    # Max paralelas (mismo slot)
    paralelas = 0
    if not valid_df.empty:
        slots: dict[tuple, int] = {}
        for _, r in valid_df.iterrows():
            key = (str(r["Día"]), str(r["Inicio"])[:5], str(r["Fin"])[:5])
            slots[key] = slots.get(key, 0) + 1
        paralelas = max(slots.values()) if slots else 0

    # Horas por comision
    hours_by_com: dict[int, float] = {c.numero: 0.0 for c in mat_coms}
    if not valid_df.empty:
        for _, r in valid_df.iterrows():
            cn = r.get("Comisión")
            if cn in hours_by_com:
                hours_by_com[cn] += float(r["Hs"])
    hours_by_com = {c: round(h, 2) for c, h in hours_by_com.items()}

    checks = _compute_checks(
        h_sem=db_hsem, n_com=n_com, total=total,
        paralelas=paralelas, hours_by_com=hours_by_com,
        has_lab=has_lab, h_teo=db_hteo, h_lab=db_hlab,
        valid_df=valid_df, com_options=com_options,
    )

    # Worst status
    worst = "ok"
    for ck in checks:
        if ck["status"] == "error":
            worst = "error"
            break
        if ck["status"] == "warn" and worst != "error":
            worst = "warn"
    if worst == "ok" and not any(c["status"] == "ok" for c in checks):
        worst = "info"

    # Render
    icon_map = {"ok": "✅", "warn": "⚠️", "error": "🔺", "info": "ℹ️"}
    for ck in checks:
        ico = icon_map.get(ck["status"], "•")
        st.markdown(f"{ico} **{ck['label']}:** {ck['detail']}")

    return worst


def render_plan_materia_detail(
    plan_id: str, materia_codigo: str, key_ns: str,
    *,
    pending_revalidate_key: Optional[str] = None,
    invalidate_cache_keys: Optional[list[str]] = None,
) -> None:
    """Renderiza el editor completo de una materia dentro del plan.

    Args:
        plan_id: id del PlanificacionCursadaDB.
        materia_codigo: código de la materia a editar.
        key_ns: namespace para las keys de session_state (debe ser único
            por instancia para evitar colisiones cuando se rendea más de
            un editor en la misma página).
        pending_revalidate_key: si se provee, al final del render se
            compara el conteo vivo de comisiones+horarios del plan con
            el snapshot del último validar_plan; si cambió, se marca
            este flag para que el panel padre auto-revalide en el
            próximo rerun.
        invalidate_cache_keys: keys de session_state a popear cuando se
            detecta cambio (para invalidar el summary cacheado).
    """
    # Toast de confirmacion despues de un dialog (rerun no permite
    # st.toast directo desde el handler).
    _toast_msg = st.session_state.pop("_pme_toast", None)
    if _toast_msg:
        st.toast(_toast_msg)

    # Key prefix para todos los caches del editor
    _kp = f"{key_ns}_{plan_id}_{materia_codigo}"
    # Carga inicial: plan, ciclo, materia, comisiones, horarios.
    with next(get_session()) as session:
        plan = session.get(PlanificacionCursadaDB, plan_id)
        if plan is None:
            st.error(f"Plan '{plan_id}' no encontrado.")
            return
        mat_db = session.get(MateriaDB, materia_codigo)
        ciclo = (
            session.get(CicloDB, plan.ciclo_id) if plan.ciclo_id else None
        )

        mat_coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .where(ComisionDB.materia_codigo == materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())

        com_ids = [c.id for c in mat_coms]
        all_horarios: list[HorarioDB] = []
        if com_ids:
            all_horarios = list(session.exec(
                select(HorarioDB).where(col(HorarioDB.comision_id).in_(com_ids))
            ).all())
        horarios_by_comision: dict[str, list[HorarioDB]] = {}
        for h in all_horarios:
            horarios_by_comision.setdefault(h.comision_id, []).append(h)

        config = get_or_create_config(session)
        time_slots = generate_time_slots(config)

    dias_list = sorted(DIAS_SEMANA, key=lambda d: [
        "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"
    ].index(d))

    # --- 1. Catálogo de horas (editable, auto-save) ---
    st.markdown("##### 📚 Catálogo de horas")
    if mat_db is not None:
        _editar_horas_materia(mat_db, _kp, ciclo)
        st.caption(f"**Período**: {mat_db.periodo} (catálogo, read-only).")

    st.divider()

    # --- 2. Calendario editable (drag/click/select + dialogs) ---
    st.markdown("##### 🗓️ Calendario")
    _render_plan_editable_calendar(
        plan_id=plan_id, materia_codigo=materia_codigo, kp=_kp,
    )

    # --- Particion teoria/lab a nivel materia (solo flags por comision) ---
    with next(get_session()) as _part_sess:
        _part_res = validar_factibilidad_particion_horas(
            _part_sess, plan_cursada_id=plan_id,
        )
    _infactibles_set: set[tuple[str, int]] = set()
    for _det in _part_res.details or []:
        try:
            _hdr = _det.split(":", 1)[0].strip()
            _parts = _hdr.split()
            if len(_parts) >= 2 and _parts[1].startswith("C"):
                _mc = _parts[0]
                _cn = int(_parts[1][1:])
                _infactibles_set.add((_mc, _cn))
        except (ValueError, IndexError):
            pass

    # Sin comisiones: solo el boton de agregar
    if not mat_coms:
        st.divider()
        st.info(
            "Esta materia no tiene comisiones en el plan. Agregá la "
            "primera comisión para empezar a cargar horarios."
        )
        _render_add_comision_button(plan_id, materia_codigo, mat_coms, key_ns)
        return

    st.divider()

    # --- 3. Editor masivo de horarios (data_editor) ---
    st.markdown("##### ✏️ Edición masiva de horarios")
    _render_bulk_horario_editor(
        plan_id, materia_codigo, mat_coms, horarios_by_comision, key_ns,
    )

    st.divider()

    # --- 4. Inscriptos esperados (peso total + total manual + forecast) ---
    st.markdown("##### 👥 Inscriptos esperados")
    _render_coef_y_forecast_header(
        plan, ciclo, materia_codigo, mat_coms, key_ns,
    )

    st.divider()

    # --- 5. Comisiones (cada una en su propio expander) ---
    st.markdown(f"##### 🎓 Comisiones ({len(mat_coms)})")
    for com in mat_coms:
        _render_comision_row(
            com, materia_codigo, mat_coms,
            horarios_by_comision.get(com.id, []),
            _infactibles_set, dias_list, time_slots, key_ns,
        )

    _render_add_comision_button(plan_id, materia_codigo, mat_coms, key_ns)

    # --- 6. Validaciones (10 checks) ---
    st.divider()
    st.markdown("##### ✅ Validaciones de la materia")
    _worst = _render_plan_checks(
        plan_id, materia_codigo, mat_coms, horarios_by_comision, mat_db,
    )
    # Cachear worst para que el header del expander del caller (en
    # validation_ui._render_detalle_por_materia) muestre el icono al
    # proximo render.
    st.session_state[f"{_kp}_chk_worst"] = _worst


# =============================================================================
# Bulk horario editor (data_editor)
# =============================================================================

def _render_bulk_horario_editor(
    plan_id: str, materia_codigo: str,
    mat_coms: list[ComisionDB],
    horarios_by_comision: dict[str, list[HorarioDB]],
    key_ns: str,
) -> None:
    """Editor en tabla con todos los horarios de la materia (data_editor)."""
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
                "Día", options=list(_de_dia_ord.keys()),
                required=True, width="medium",
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
                "Comisión", options=_com_name_options,
                required=True, width="medium",
            ),
            "Tipo": st.column_config.SelectboxColumn(
                "Tipo",
                options=["sin determinar", "teorica", "laboratorio"],
                default="sin determinar", width="small",
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        key=f"{key_ns}_de_horarios_{plan_id}_{materia_codigo}",
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
            key=f"{key_ns}_de_save_{plan_id}_{materia_codigo}",
            type="primary",
        ):
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
                    _row["Comisión"], mat_coms[0].numero,
                )
                _de_edit_rows.append({
                    "horario_id": _hid_v,
                    "comision_numero": _com_num,
                    "dia": _row["Día"],
                    "hora_inicio": _row["Inicio"],
                    "hora_fin": _row["Fin"],
                    "tipo_clase": (
                        None
                        if (_row.get("Tipo") or "sin determinar") == "sin determinar"
                        else str(_row["Tipo"])
                    ),
                })

            with next(get_session()) as session:
                _u, _c, _d = apply_horario_edits(
                    session, plan_id, materia_codigo, _de_edit_rows,
                )
            st.toast(
                f"Horarios actualizados: {_u} modificados, "
                f"{_c} agregados, {_d} eliminados"
            )
            st.rerun()


# =============================================================================
# Header: coef + forecast
# =============================================================================

def _render_coef_y_forecast_header(
    plan: PlanificacionCursadaDB,
    ciclo: CicloDB | None,
    materia_codigo: str,
    mat_coms: list[ComisionDB],
    key_ns: str,
) -> None:
    """Header con: peso total + total esperado (con override manual) +
    forecast info + selector de método. El override de valor manual va
    en un input dedicado; si está seteado el forecast histórico queda
    cubierto por el manual.
    """
    from src.services.forecast_service import (
        METODO_LABELS as _M_LABELS,
        METODOS_DISPONIBLES as _M_AVAIL,
        get_forecast_for_materia as _get_fc,
        get_metodo_override as _get_ov,
        get_valor_override as _get_vov,
        set_metodo_override as _set_ov,
        set_valor_override as _set_vov,
    )
    from src.services.plan_generation_service import (
        normalize_coef_asignacion as _norm_coef,
        get_inscriptos_esperados_por_comision as _get_esperados,
    )

    # --- Peso (suma de coef_asignacion) ---
    _peso_sum = sum(c.coef_asignacion for c in mat_coms)
    _peso_ok = abs(_peso_sum - 1.0) < 0.01
    _peso_color = "🟢" if _peso_ok else "🟡"

    _cuatri_ciclo = f"{ciclo.numero}C" if ciclo else "?"

    # Determinar el cuatri donde aplica el override (Anual si la materia
    # tiene serie anual, sino el del ciclo).
    with next(get_session()) as _sess:
        _fc_cuatri_res = _get_fc(_sess, plan.id, materia_codigo, _cuatri_ciclo)
        _fc_anual_res = _get_fc(_sess, plan.id, materia_codigo, "Anual")
        _esperados_map = _get_esperados(_sess, plan.id)
        _ov_cuatri = "Anual" if _fc_anual_res else _cuatri_ciclo
        _ov_metodo_actual = _get_ov(_sess, plan.id, materia_codigo, _ov_cuatri)
        _ov_valor_actual = _get_vov(_sess, plan.id, materia_codigo, _ov_cuatri)

    _fc_used = _fc_anual_res if _fc_anual_res is not None else _fc_cuatri_res
    _is_manual = _fc_used is not None and _fc_used.metodo == "manual"

    # --- Fila 1: Peso total + Normalizar ---
    _h1_c1, _h1_c2 = st.columns([4, 1])
    _h1_c1.markdown(
        f"**Peso total:** {_peso_color} {_peso_sum:.2f} "
        f"(debe ser ~1.0 — la suma de pesos por materia distribuye "
        f"los inscriptos esperados entre las comisiones)"
    )
    with _h1_c2:
        if not _peso_ok and st.button(
            "Normalizar",
            key=f"{key_ns}_norm_coef_{plan.id}_{materia_codigo}",
            help="Reasigna pesos uniformemente (1/n)",
            use_container_width=True,
        ):
            with next(get_session()) as _norm_s:
                _norm_coef(_norm_s, plan.id, materia_codigo)
            st.toast("Pesos normalizados.")
            st.rerun()

    # --- Fila 2: Total esperado (override manual) ---
    _h2_c1, _h2_c2 = st.columns([1, 3])
    with _h2_c1:
        _esp_input = st.number_input(
            "Total esperado (manual)",
            min_value=0.0,
            value=float(_ov_valor_actual) if _ov_valor_actual is not None else 0.0,
            step=1.0, format="%.0f",
            key=f"{key_ns}_vov_{plan.id}_{materia_codigo}",
            help=(
                "Valor manual de inscriptos esperados. Si está en 0 y "
                "no hay serie histórica, el forecast queda en 0. Para "
                "volver al forecast automático, usar el botón 'Quitar "
                "manual' a la derecha."
            ),
        )
    with _h2_c2:
        if _ov_valor_actual is not None:
            _esp_caption = (
                f"📌 **Override manual activo:** {_ov_valor_actual:.0f} "
                f"esperados (ignorando forecast histórico)."
            )
            st.markdown(_esp_caption)
            if st.button(
                "Quitar manual",
                key=f"{key_ns}_clr_vov_{plan.id}_{materia_codigo}",
                help="Vuelve al forecast histórico automático.",
            ):
                with next(get_session()) as _s:
                    _set_vov(_s, plan.id, materia_codigo, _ov_cuatri, None)
                st.toast("Override manual eliminado.")
                st.rerun()
        else:
            if _fc_used is not None:
                _src = "Anual" if _fc_anual_res else _cuatri_ciclo
                st.markdown(
                    f"**Forecast {_src} (automático):** "
                    f"{_fc_used.valor:.0f} · "
                    f"método: {_M_LABELS.get(_fc_used.metodo, _fc_used.metodo)}"
                    f"{' (override)' if _ov_metodo_actual else ' (default plan)'}"
                )
            else:
                st.markdown(
                    "**Forecast:** — *(sin serie histórica)*. "
                    "Ingresá un total esperado manual a la izquierda "
                    "para distribuir entre las comisiones."
                )

    # Persistir el override de valor cuando el usuario lo cambia
    _esp_input_val = _esp_input if _esp_input > 0 else None
    if _esp_input_val != _ov_valor_actual:
        with next(get_session()) as _s:
            _set_vov(
                _s, plan.id, materia_codigo, _ov_cuatri, _esp_input_val,
            )
        st.rerun()

    # --- Fila 3: Selector de método (solo si NO está activo override manual) ---
    if not _is_manual and _fc_used is not None:
        _ov_options = ["Default plan"] + [_M_LABELS[m] for m in _M_AVAIL]
        _ov_keys: list[str | None] = [None] + list(_M_AVAIL)
        _ov_idx = 0
        if _ov_metodo_actual in _M_AVAIL:
            _ov_idx = _ov_keys.index(_ov_metodo_actual)
        _ov_choice = st.selectbox(
            "Método de forecast (override)",
            options=list(range(len(_ov_keys))),
            format_func=lambda i: _ov_options[i],
            index=_ov_idx,
            key=f"{key_ns}_fc_ov_{plan.id}_{materia_codigo}",
            help=(
                "Override del método de forecast para esta materia. "
                "'Default plan' usa el método configurado a nivel plan."
            ),
        )
        _ov_new = _ov_keys[_ov_choice]
        if _ov_new != _ov_metodo_actual:
            with next(get_session()) as _s:
                _set_ov(_s, plan.id, materia_codigo, _ov_cuatri, _ov_new)
            st.rerun()

    # Guardar en session_state para que _render_comision_row pueda leerlo
    st.session_state[f"_pme_esperados_{plan.id}_{materia_codigo}"] = _esperados_map


# =============================================================================
# Loop por comision
# =============================================================================

def _render_comision_row(
    com: ComisionDB,
    materia_codigo: str,
    mat_coms: list[ComisionDB],
    com_horarios: list[HorarioDB],
    infactibles_set: set[tuple[str, int]],
    dias_list: list[str],
    time_slots: list,
    key_ns: str,
) -> None:
    """Render de una comisión dentro de su propio expander.

    Layout (de arriba a abajo):
    1. Header del expander: nombre · #N · peso actual · esperados · flag
       de partición infactible si aplica.
    2. Fila editable: Nombre / Peso / Esperados (read-only).
    3. Lista de horarios con botón de borrar por horario.
    4. Popover "Agregar horario".
    5. Botón "Eliminar comisión" al pie.
    """
    from src.services.plan_generation_service import (
        update_comision_coef as _upd_coef,
    )

    _esperados_map = st.session_state.get(
        f"_pme_esperados_{com.plan_cursada_id}_{materia_codigo}", {}
    )
    _esperados_val = _esperados_map.get(com.id)

    _flag_part = (
        " · ⚠️ partición teoría/lab infactible"
        if (materia_codigo, com.numero) in infactibles_set
        else ""
    )
    _esp_str = (
        f"{_esperados_val:.0f} esperados"
        if _esperados_val is not None else "esperados —"
    )
    _hdr = (
        f"{com.nombre}  ·  #{com.numero}  ·  "
        f"peso {com.coef_asignacion:.2f}  ·  {_esp_str}{_flag_part}"
    )

    with st.expander(_hdr, expanded=False):
        # --- Fila editable: nombre / peso / esperados (read-only) ---
        col_name, col_peso, col_esp = st.columns([3, 1.5, 1.5])
        with col_name:
            new_name = st.text_input(
                "Nombre",
                value=com.nombre,
                key=f"{key_ns}_com_name_{com.id}",
            )
        with col_peso:
            new_peso = st.number_input(
                "Peso",
                value=float(com.coef_asignacion),
                min_value=0.0, max_value=1.0,
                step=0.05, format="%.2f",
                key=f"{key_ns}_com_coef_{com.id}",
                help=(
                    "Fracción del total esperado de la materia que se "
                    "asigna a esta comisión. La suma de pesos por "
                    "materia debe ser ≈1.0. Inscriptos esperados de "
                    "esta comisión = total esperado × peso."
                ),
            )
        with col_esp:
            if _esperados_val is not None:
                st.metric(
                    "Esperados",
                    f"{_esperados_val:.0f}",
                    label_visibility="visible",
                    help=(
                        "Calculado como total esperado de la materia × "
                        "peso de esta comisión."
                    ),
                )
            else:
                st.caption("Esperados: —")

        # Persist peso change immediately (sin botón)
        if abs(new_peso - com.coef_asignacion) > 1e-9:
            with next(get_session()) as _coef_s:
                _upd_coef(_coef_s, com.id, new_peso)
            st.rerun()

        # Save name change si cambió
        if new_name != com.nombre:
            if st.button(
                "💾 Guardar nombre",
                key=f"{key_ns}_save_com_{com.id}",
            ):
                with next(get_session()) as session:
                    db_com = session.get(ComisionDB, com.id)
                    if db_com:
                        db_com.nombre = new_name
                        session.add(db_com)
                        session.commit()
                st.success("Comisión actualizada")
                st.rerun()

        # --- Horarios listados ---
        st.markdown("**Horarios**")
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
                    if st.button(
                        "✕", key=f"{key_ns}_del_h_{h.id}",
                        help="Eliminar horario",
                    ):
                        with next(get_session()) as session:
                            db_h = session.get(HorarioDB, h.id)
                            if db_h:
                                session.delete(db_h)
                                session.commit()
                        st.success("Horario eliminado")
                        st.rerun()
        else:
            st.caption("Sin horarios cargados.")

        # --- Add horario popover ---
        with st.popover("➕ Agregar horario"):
            add_dia = st.selectbox(
                "Día", options=dias_list,
                key=f"{key_ns}_add_h_dia_{com.id}",
            )
            time_options = sorted({s for slot in time_slots for s in slot})
            time_labels = {t: t.strftime("%H:%M") for t in time_options}
            add_inicio = st.selectbox(
                "Hora inicio",
                options=time_options,
                format_func=lambda t: time_labels[t],
                key=f"{key_ns}_add_h_ini_{com.id}",
            )
            add_fin = st.selectbox(
                "Hora fin",
                options=time_options,
                format_func=lambda t: time_labels[t],
                index=min(1, len(time_options) - 1),
                key=f"{key_ns}_add_h_fin_{com.id}",
            )
            if st.button(
                "Agregar",
                key=f"{key_ns}_btn_add_h_{com.id}",
                type="primary",
            ):
                if add_fin <= add_inicio:
                    st.error(
                        "La hora de fin debe ser posterior a la de inicio"
                    )
                else:
                    with next(get_session()) as session:
                        new_h = HorarioDB(
                            id=str(uuid.uuid4()),
                            comision_id=com.id,
                            codigo_materia=materia_codigo,
                            dia=add_dia,
                            hora_inicio=add_inicio,
                            hora_fin=add_fin,
                        )
                        session.add(new_h)
                        session.commit()
                    st.success("Horario agregado")
                    st.rerun()

        st.divider()

        # --- Eliminar comisión (al pie del expander) ---
        if st.button(
            "🗑️ Eliminar comisión",
            key=f"{key_ns}_del_com_{com.id}",
            help="Borra la comisión y todos sus horarios. Irreversible.",
        ):
            with next(get_session()) as session:
                hs = session.exec(
                    select(HorarioDB).where(HorarioDB.comision_id == com.id)
                ).all()
                for h in hs:
                    session.delete(h)
                db_com = session.get(ComisionDB, com.id)
                if db_com:
                    session.delete(db_com)
                session.commit()
            st.success(f"Comisión '{com.nombre}' eliminada")
            st.rerun()


# =============================================================================
# Add comision button
# =============================================================================

def _render_add_comision_button(
    plan_id: str, materia_codigo: str,
    mat_coms: list[ComisionDB], key_ns: str,
) -> None:
    """Boton para crear una nueva comision a la materia."""
    if st.button(
        "➕ Agregar comision",
        key=f"{key_ns}_add_com_{materia_codigo}",
    ):
        with next(get_session()) as session:
            max_num = max((c.numero for c in mat_coms), default=0)
            new_numero = max_num + 1
            mat_db = session.get(MateriaDB, materia_codigo)
            cupo_default = (
                mat_db.cupo if (mat_db and mat_db.cupo) else 30
            )

            new_com = ComisionDB(
                id=str(uuid.uuid4()),
                materia_codigo=materia_codigo,
                plan_cursada_id=plan_id,
                comision_key=f"{materia_codigo}-{new_numero:03d}",
                nombre=f"Comision {new_numero}",
                numero=new_numero,
                cupo=cupo_default,
            )
            session.add(new_com)
            session.commit()
        st.success(f"Comision {new_numero} agregada")
        st.rerun()
