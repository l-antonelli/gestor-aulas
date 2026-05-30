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
from src.database.crud import get_or_create_config
from src.database.models import (
    CicloDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanificacionCursadaDB,
)
from src.domain.types import DIAS_SEMANA
from src.services.plan_generation_service import (
    apply_horario_edits,
    generate_time_slots,
)
from src.services.validations import validar_factibilidad_particion_horas


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

    # --- Datos del catálogo (read-only) ---
    if mat_db is not None:
        _cat1, _cat2, _cat3, _cat4 = st.columns(4)
        _cat1.markdown(f"**hs/sem**: {mat_db.horas_semanales or '—'}")
        _cat2.markdown(f"**hs teoría**: {mat_db.horas_teoria or '—'}")
        _cat3.markdown(f"**hs lab**: {mat_db.horas_laboratorio or '—'}")
        _cat4.markdown(f"**período**: {mat_db.periodo}")
        st.caption(
            "Datos del catálogo (read-only). Para modificarlos, ir a "
            "**📚 Materias**."
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
        st.info(
            "Esta materia no tiene comisiones en el plan. Agregá la "
            "primera comisión para empezar a cargar horarios."
        )
        _render_add_comision_button(plan_id, materia_codigo, mat_coms, key_ns)
        return

    # --- Bulk horario editor (data_editor) ---
    _render_bulk_horario_editor(
        plan_id, materia_codigo, mat_coms, horarios_by_comision, key_ns,
    )

    st.divider()

    # --- Coef sums + forecast info ---
    _render_coef_y_forecast_header(
        plan, ciclo, materia_codigo, mat_coms, key_ns,
    )

    # --- Loop por comision: edicion de campos + horarios ---
    for com in mat_coms:
        _render_comision_row(
            com, materia_codigo, mat_coms,
            horarios_by_comision.get(com.id, []),
            _infactibles_set, dias_list, time_slots, key_ns,
        )
        if com != mat_coms[-1]:
            st.divider()

    # --- Add comision button ---
    st.divider()
    _render_add_comision_button(plan_id, materia_codigo, mat_coms, key_ns)


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
    """Resumen de coef + forecast + selector de método override."""
    from src.services.forecast_service import (
        METODO_LABELS as _M_LABELS,
        METODOS_DISPONIBLES as _M_AVAIL,
        get_forecast_for_materia as _get_fc,
        get_metodo_override as _get_ov,
        set_metodo_override as _set_ov,
    )
    from src.services.plan_generation_service import (
        normalize_coef_asignacion as _norm_coef,
        get_inscriptos_esperados_por_comision as _get_esperados,
    )

    _coef_sum = sum(c.coef_asignacion for c in mat_coms)
    _coef_ok = abs(_coef_sum - 1.0) < 0.01
    _coef_color = "🟢" if _coef_ok else "🟡"

    _cuatri_ciclo = f"{ciclo.numero}C" if ciclo else "?"

    with next(get_session()) as _fc_sess:
        _fc_cuatri_res = _get_fc(_fc_sess, plan.id, materia_codigo, _cuatri_ciclo)
        _fc_anual_res = _get_fc(_fc_sess, plan.id, materia_codigo, "Anual")
        _esperados_map = _get_esperados(_fc_sess, plan.id)
        _ov_cuatri = "Anual" if _fc_anual_res else _cuatri_ciclo
        _ov_actual = _get_ov(_fc_sess, plan.id, materia_codigo, _ov_cuatri)

    _fc_used = (
        _fc_anual_res if _fc_anual_res is not None else _fc_cuatri_res
    )

    _info_c1, _info_c2, _info_c3 = st.columns([2, 3, 1])
    _info_c1.markdown(
        f"**Coef total:** {_coef_color} {_coef_sum:.2f} "
        f"(debe ser ~1.0)"
    )
    if _fc_used is not None:
        _src = "Anual" if _fc_anual_res else _cuatri_ciclo
        _info_c2.markdown(
            f"**Forecast {_src}:** {_fc_used.valor:.0f} "
            f"·  método: {_M_LABELS.get(_fc_used.metodo, _fc_used.metodo)}"
            f"{' (override)' if _ov_actual else ' (default plan)'}"
        )
    else:
        _info_c2.markdown(
            "**Forecast:** — *(sin serie histórica en Inscriptos)*"
        )
    with _info_c3:
        if not _coef_ok and st.button(
            "Normalizar",
            key=f"{key_ns}_norm_coef_{plan.id}_{materia_codigo}",
            help="Reasigna coef uniformemente (1/n)",
        ):
            with next(get_session()) as _norm_s:
                _norm_coef(_norm_s, plan.id, materia_codigo)
            st.toast("Coef normalizados.")
            st.rerun()

    if _fc_used is not None:
        _ov_options = ["Default plan"] + [_M_LABELS[m] for m in _M_AVAIL]
        _ov_keys: list[str | None] = [None] + list(_M_AVAIL)
        _ov_idx = 0
        if _ov_actual in _M_AVAIL:
            _ov_idx = _ov_keys.index(_ov_actual)
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
        if _ov_new != _ov_actual:
            with next(get_session()) as _ov_s:
                _set_ov(_ov_s, plan.id, materia_codigo, _ov_cuatri, _ov_new)
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
    """Render de una comision: nombre/cupo/coef/borrar + horarios + agregar."""
    from src.services.plan_generation_service import (
        update_comision_coef as _upd_coef,
    )

    _esperados_map = st.session_state.get(
        f"_pme_esperados_{com.plan_cursada_id}_{materia_codigo}", {}
    )

    _com_flag = (
        " ⚠️ partición teoría/lab infactible"
        if (materia_codigo, com.numero) in infactibles_set
        else ""
    )
    st.markdown(f"##### {com.nombre} (#{com.numero}){_com_flag}")

    col_name, col_cupo, col_coef, col_esp, col_del = st.columns(
        [3, 1.5, 1.5, 1.2, 0.6]
    )
    with col_name:
        new_name = st.text_input(
            "Nombre", value=com.nombre,
            key=f"{key_ns}_com_name_{com.id}",
            label_visibility="collapsed",
        )
    with col_cupo:
        new_cupo = st.number_input(
            "Cupo", value=max(com.cupo, 1), min_value=1,
            key=f"{key_ns}_com_cupo_{com.id}",
        )
    with col_coef:
        new_coef = st.number_input(
            "Coef", value=float(com.coef_asignacion),
            min_value=0.0, max_value=1.0,
            step=0.05, format="%.2f",
            key=f"{key_ns}_com_coef_{com.id}",
            help=(
                "Fracción de inscriptos esperados que se asignan a "
                "esta comisión. La suma por materia debe ser ≈1.0."
            ),
        )
    with col_esp:
        if com.id in _esperados_map:
            st.metric(
                "Esperados",
                f"{_esperados_map[com.id]:.0f}",
                label_visibility="visible",
            )
        else:
            st.caption("Esperados: —")
    with col_del:
        st.write("")
        if st.button(
            "🗑️", key=f"{key_ns}_del_com_{com.id}",
            help="Eliminar comision",
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
            st.success(f"Comision '{com.nombre}' eliminada")
            st.rerun()

    # Persist coef change immediately (no extra button)
    if abs(new_coef - com.coef_asignacion) > 1e-9:
        with next(get_session()) as _coef_s:
            _upd_coef(_coef_s, com.id, new_coef)
        st.rerun()

    # Save comision changes if modified (name/cupo)
    if new_name != com.nombre or new_cupo != com.cupo:
        if st.button(
            "💾 Guardar comision", key=f"{key_ns}_save_com_{com.id}",
        ):
            with next(get_session()) as session:
                db_com = session.get(ComisionDB, com.id)
                if db_com:
                    db_com.nombre = new_name
                    db_com.cupo = new_cupo
                    session.add(db_com)
                    session.commit()
            st.success("Comision actualizada")
            st.rerun()

    # --- Horarios listados con botón de borrar ---
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
        st.caption("Sin horarios")

    # --- Add horario popover ---
    with st.popover("➕ Agregar horario"):
        add_dia = st.selectbox(
            "Dia", options=dias_list,
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
            "Agregar", key=f"{key_ns}_btn_add_h_{com.id}", type="primary",
        ):
            if add_fin <= add_inicio:
                st.error("La hora de fin debe ser posterior a la de inicio")
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
