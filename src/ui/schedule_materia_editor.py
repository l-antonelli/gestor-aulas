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

Las "comisiones" del cronograma son **auto-derivadas**: viven como
`ScheduleEntryDB.comision` (int) por entry; no hay tabla `ComisionDB`
hasta que se genera el plan. Por eso el editor opera directamente
sobre `ScheduleEntryDB` y no sobre `ComisionDB`.

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
from src.database.crud import materia_crud
from src.database.models import (
    MateriaLaboratorioDB,
    ScheduleEntryDB,
)
from src.services.schedule_service import sync_preview_edits_to_schedule
from src.services.validations import _subset_sum_exists


_DIA_ORD = {
    "Lunes": 0, "Martes": 1, "Miércoles": 2,
    "Jueves": 3, "Viernes": 4, "Sábado": 5,
}
_DIAS_LIST = list(_DIA_ORD.keys())

_BASE_TIME_OPTIONS = [
    "08:00", "08:30", "09:00", "09:30", "10:00", "10:30",
    "11:00", "11:30", "12:00", "12:30", "13:00", "13:30",
    "14:00", "14:30", "15:00", "15:30", "16:00", "16:30",
    "17:00", "17:30", "18:00", "18:30", "19:00", "19:30",
    "20:00", "20:30", "21:00", "21:30", "22:00",
]


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
# Entrypoint
# =============================================================================

def render_schedule_materia_detail(
    schedule_id: str, materia_codigo: str, key_ns: str,
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

    # Catálogo
    db_hsem = float(mat_db.horas_semanales or 0.0)
    db_hteo = mat_db.horas_teoria
    db_hlab = mat_db.horas_laboratorio

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
                "asignado pero Hs lab = 0, se asume reserva ad-hoc "
                "(decide el docente fuera del LP)."
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
                "reserva ad-hoc: el LP no fija lab; los docentes lo "
                "reservan caso por caso."
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
    derived_ncom = _derive_n_comisiones(entries)
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
        # Persistir directamente en DB
        with next(get_session()) as _s:
            _entries_db = list(_s.exec(
                select(ScheduleEntryDB)
                .where(ScheduleEntryDB.schedule_id == schedule_id)
                .where(ScheduleEntryDB.codigo_materia == materia_codigo)
            ).all())
            for _e in _entries_db:
                if _e.id in new_assignments:
                    _e.comision = new_assignments[_e.id]
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
    _current_fp = tuple(sorted(
        (e.id, e.dia, str(e.hora_inicio), str(e.hora_fin),
         e.comision or 0, e.tipo_clase or "")
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
            rows.append({
                "_eid": e.id,
                "Día": e.dia,
                "Inicio": _time_str(e.hora_inicio),
                "Fin": _time_str(e.hora_fin),
                "Comisión": e.comision or 1,
                "Tipo": e.tipo_clase or "sin determinar",
            })
        df = (
            pd.DataFrame(rows)
            if rows
            else pd.DataFrame(
                columns=["_eid", "Día", "Inicio", "Fin", "Comisión", "Tipo"]
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
            e.id: (e.comision or 1) for e in entries
        }
        st.session_state[fp_key] = _current_fp
    else:
        df = st.session_state[init_key]

    # Time options dinámicos
    existing_times: set[str] = set()
    if not df.empty:
        for tc in ["Inicio", "Fin"]:
            existing_times.update(df[tc].dropna().astype(str).str[:5])
    time_opts = sorted(set(_BASE_TIME_OPTIONS) | existing_times)

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
    # 10 chequeos estructurados
    # =========================================================================
    checks = _compute_checks(
        h_sem=db_hsem, n_com=n_com, total=new_total,
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
        if ck["status"] == "info" and worst not in ("error", "warn"):
            # info no degrada del ok inicial; el ok se mantiene salvo que
            # explicitamente todos sean info y no haya ok. Para badge,
            # info se trata como ok salvo que no haya ningun ok.
            pass
    # Si el peor es 'info' pero no hay ningun 'ok', degradar a info
    if worst == "ok" and not any(c["status"] == "ok" for c in checks):
        worst = "info"

    st.session_state[
        f"{_kp}_chk_worst"
    ] = worst

    # Render checks
    icon_map = {"ok": "✅", "warn": "⚠️", "error": "🔺", "info": "ℹ️"}
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
    orig_cmp = df[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
    edit_cmp = edited[["Día", "Inicio", "Fin", "Comisión"]].reset_index(drop=True)
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
                _persist_edits(
                    schedule_id, materia_codigo, valid_df,
                )
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

def _derive_n_comisiones(entries: list[ScheduleEntryDB]) -> int:
    """Derivar n_comisiones del set de entries (max comision asignada o 1)."""
    if not entries:
        return 1
    max_com = max((e.comision or 1) for e in entries)
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


def _persist_edits(
    schedule_id: str, materia_codigo: str, valid_df: pd.DataFrame,
) -> None:
    """Persiste las ediciones del data_editor a ScheduleEntryDB.

    Reusa `sync_preview_edits_to_schedule` que ya soporta upsert por
    entry_id (con prefijo "new_" para filas nuevas) y elimina filas
    que ya no están en el set.
    """
    sync_entries = []
    for i, (_, r) in enumerate(valid_df.iterrows()):
        eid = (
            r["_eid"]
            if pd.notna(r.get("_eid"))
            else f"new_{materia_codigo}_{i}"
        )
        com = (
            int(r["Comisión"]) if pd.notna(r.get("Comisión")) else 1
        )
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
            "comision": com,
            "tipo_clase": tipo,
        })

    with next(get_session()) as session:
        sync_preview_edits_to_schedule(
            session, schedule_id, materia_codigo, sync_entries,
        )


# =============================================================================
# Computación de los 10 chequeos estructurados
# =============================================================================

def _compute_checks(
    *,
    h_sem: float, n_com: int, total: float, paralelas: int,
    hours_by_com: dict[int, float],
    has_lab: bool,
    h_teo: Optional[float], h_lab: Optional[float],
    valid_df: pd.DataFrame,
    com_options: list[int],
) -> list[dict]:
    """Computa los 10 checks documentados en VALIDACIONES.md.

    Cada check es un dict con `id`, `label`, `status`, `detail`.
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
                "Reserva ad-hoc (Hs lab = 0): el LP no fija lab; "
                "los docentes lo reservan caso por caso."
            ),
        })
    elif has_lab and h_lab is not None and h_lab > 0:
        checks.append({
            "id": "thl_reserva",
            "label": "Modo lab",
            "status": "ok",
            "detail": f"Lab fijo: {h_lab:g}h por comisión entran al LP.",
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
                else "Todas 'sin determinar' (LP decide)"
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

    return checks
