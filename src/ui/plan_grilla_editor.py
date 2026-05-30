"""Editor de la grilla horaria global del plan (espejo de Cronogramas → Editar).

Replica el flujo de la pestaña **Editar** de la página de Cronogramas
pero opera sobre los datos del plan (`ComisionDB` + `HorarioDB`) en
lugar de `ScheduleEntryDB`.

Punto de entrada: `render_plan_grilla_editor(plan_id, key_ns)`.

Features (paridad 1:1 con Cronogramas → Editar):

- Modo "Por grupo" con filtros Carrera/Año/Cuatri + Tipo (todas/Ciclo
  Básico/Específicas) + checkbox "Excluir comunes".
- Modo "Por materia" con búsqueda de materia + filtro a la materia
  elegida + tabla editable de entradas + resumen por comisión.
- Calendario editable con drag/resize/click/select.
- Dialogs: editar entrada (día/inicio/fin/comisión/tipo + Eliminar),
  agregar entrada (al seleccionar rango con materia activa).
- Para "agregar" requiere `sel_mat_add` (materia) + comisión existente
  o `➕ Nueva comisión` que crea la `ComisionDB` al vuelo.
"""

from __future__ import annotations

import uuid
from datetime import time
from typing import Optional

import pandas as pd
import streamlit as st
from sqlmodel import col, select

from src.database.connection import get_session
from src.database.crud import get_or_create_config, materia_crud
from src.database.models import (
    CarreraDB,
    CicloPlanVersionDB,
    ComisionDB,
    HorarioDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
)
from src.services.schedule_service import ScheduleBlock
from src.ui.calendar_render import render_editable_schedule_calendar


_DIAS_LIST = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]


def _coerce_time(val) -> time:
    """Convierte string HH:MM(:SS.mmm) o time a time."""
    if isinstance(val, time):
        return val
    s = str(val).split(".")[0]
    parts = s.split(":")
    return time(
        int(parts[0]),
        int(parts[1]),
        int(parts[2]) if len(parts) > 2 else 0,
    )


# =============================================================================
# Dialogs
# =============================================================================

@st.dialog("Editar horario", width="large")
def _dialog_edit_horario():
    """Dialog para editar un HorarioDB del plan desde la grilla."""
    pending = st.session_state.get("_pge_pending_click")
    if not pending:
        st.rerun()
        return

    plan_id = pending["plan_id"]
    materia_codigo = pending["materia_codigo"]

    # Comisiones de esta materia en el plan
    with next(get_session()) as session:
        coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .where(ComisionDB.materia_codigo == materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())
        mat_db = session.get(MateriaDB, materia_codigo)

    if not coms:
        st.error("La materia no tiene comisiones en el plan. Cancelá.")
        if st.button("Cerrar"):
            del st.session_state["_pge_pending_click"]
            st.rerun()
        return

    com_options = {f"C{c.numero} — {c.nombre}": c.id for c in coms}
    com_keys = list(com_options.keys())
    current_com_id = pending.get("comision_id")
    current_idx = 0
    for i, (_, cid) in enumerate(com_options.items()):
        if cid == current_com_id:
            current_idx = i
            break

    st.markdown(
        f"**Materia**: `{materia_codigo}` "
        f"— {mat_db.nombre if mat_db else '?'}"
    )

    col_dia, col_ini, col_fin = st.columns(3)
    with col_dia:
        new_dia = st.selectbox(
            "Día",
            options=_DIAS_LIST,
            index=(
                _DIAS_LIST.index(pending["dia"])
                if pending["dia"] in _DIAS_LIST else 0
            ),
            key="_pge_dlg_dia",
        )
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="_pge_dlg_ini",
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="_pge_dlg_fin",
        )

    col_com, col_tipo = st.columns(2)
    with col_com:
        new_com_lbl = st.selectbox(
            "Comisión",
            options=com_keys, index=current_idx,
            key="_pge_dlg_com",
        )
        new_com_id = com_options[new_com_lbl]
    with col_tipo:
        tipo_options = ["sin determinar", "teorica", "laboratorio"]
        pending_tipo = pending.get("tipo_clase") or "sin determinar"
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=tipo_options,
            index=(
                tipo_options.index(pending_tipo)
                if pending_tipo in tipo_options else 0
            ),
            key="_pge_dlg_tipo",
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
            base_dia = pending.get("_baseline_dia", pending["dia"])
            base_hi = pending.get("_baseline_hi", pending["hora_inicio"])
            base_hf = pending.get("_baseline_hf", pending["hora_fin"])

            cambios: dict = {}
            if new_dia != base_dia:
                cambios["dia"] = new_dia
            if new_inicio != base_hi:
                cambios["hora_inicio"] = new_inicio
            if new_fin != base_hf:
                cambios["hora_fin"] = new_fin
            if new_com_id != pending.get("comision_id"):
                cambios["comision_id"] = new_com_id
            new_tipo_val = (
                None if new_tipo == "sin determinar" else new_tipo
            )
            if new_tipo_val != (pending.get("tipo_clase") or None):
                cambios["tipo_clase"] = new_tipo_val

            if cambios:
                with next(get_session()) as session:
                    h = session.get(HorarioDB, pending["horario_id"])
                    if h is not None:
                        for k, v in cambios.items():
                            setattr(h, k, v)
                        session.add(h)
                        session.commit()
                st.session_state["_pge_toast"] = (
                    f"{materia_codigo} actualizada"
                )
            else:
                st.session_state["_pge_toast"] = "Sin cambios"
            st.session_state["_pge_processed_click"] = pending["_key"]
            del st.session_state["_pge_pending_click"]
            st.rerun()
    with col2:
        if st.button("Eliminar", use_container_width=True):
            with next(get_session()) as session:
                h = session.get(HorarioDB, pending["horario_id"])
                if h is not None:
                    session.delete(h)
                    session.commit()
            st.session_state["_pge_toast"] = (
                f"{materia_codigo} eliminada"
            )
            st.session_state["_pge_processed_click"] = pending["_key"]
            del st.session_state["_pge_pending_click"]
            st.rerun()
    with col3:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_pge_processed_click"] = pending["_key"]
            del st.session_state["_pge_pending_click"]
            st.rerun()


@st.dialog("Agregar horario", width="large")
def _dialog_add_horario():
    """Dialog para crear un HorarioDB cuando el usuario seleccionó un
    rango vacío en la grilla con una materia activa."""
    pending = st.session_state.get("_pge_pending_select")
    if not pending:
        st.rerun()
        return

    plan_id = pending["plan_id"]
    materia_codigo = pending["materia_codigo"]

    with next(get_session()) as session:
        coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .where(ComisionDB.materia_codigo == materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())
        mat_db = session.get(MateriaDB, materia_codigo)
        default_cupo = mat_db.cupo if (mat_db and mat_db.cupo) else 30

    NEW_COM = "➕ Nueva comisión"
    com_options: dict[str, Optional[str]] = {
        f"C{c.numero} — {c.nombre}": c.id for c in coms
    }
    com_options[NEW_COM] = None

    st.markdown(
        f"**Materia**: `{materia_codigo}` "
        f"— {mat_db.nombre if mat_db else '?'}"
    )
    st.markdown(
        f"**{pending['dia']}** · "
        f"{pending['hora_inicio'].strftime('%H:%M')} - "
        f"{pending['hora_fin'].strftime('%H:%M')}"
    )

    col_com, col_tipo = st.columns(2)
    with col_com:
        new_com_lbl = st.selectbox(
            "Comisión",
            options=list(com_options.keys()), index=0,
            key="_pge_dlg_add_com",
            help="Elegí una comisión existente o creá una nueva.",
        )
    with col_tipo:
        tipo_options = ["sin determinar", "teorica", "laboratorio"]
        new_tipo = st.selectbox(
            "Tipo de clase",
            options=tipo_options, index=0,
            key="_pge_dlg_add_tipo",
        )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            tipo_val = None if new_tipo == "sin determinar" else new_tipo
            with next(get_session()) as session:
                target_com_id = com_options[new_com_lbl]
                if target_com_id is None:
                    max_num = max((c.numero for c in coms), default=0)
                    new_num = max_num + 1
                    new_com = ComisionDB(
                        id=str(uuid.uuid4()),
                        materia_codigo=materia_codigo,
                        plan_cursada_id=plan_id,
                        comision_key=f"{materia_codigo}-{new_num:03d}",
                        nombre=f"Comision {new_num}",
                        numero=new_num,
                        cupo=default_cupo,
                    )
                    session.add(new_com)
                    session.flush()
                    target_com_id = new_com.id

                new_h = HorarioDB(
                    id=str(uuid.uuid4()),
                    comision_id=target_com_id,
                    codigo_materia=materia_codigo,
                    dia=pending["dia"],
                    hora_inicio=pending["hora_inicio"],
                    hora_fin=pending["hora_fin"],
                    tipo_clase=tipo_val,
                )
                session.add(new_h)
                session.commit()
            st.session_state["_pge_toast"] = (
                f"{materia_codigo} agregada"
            )
            st.session_state["_pge_processed_select"] = pending["_key"]
            del st.session_state["_pge_pending_select"]
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_pge_processed_select"] = pending["_key"]
            del st.session_state["_pge_pending_select"]
            st.rerun()


# =============================================================================
# Filtros auxiliares
# =============================================================================

def _aplicar_filtro_tipo_materia(
    grid_data: dict[str, list[ScheduleBlock]],
    filtro_tipo: str,
    excluir_comunes: bool,
    materias_carreras_count: dict[str, int],
) -> dict[str, list[ScheduleBlock]]:
    """Aplica los filtros 'Tipo de materia' (Ciclo Básico / Específicas)
    y 'Excluir materias comunes (multi-carrera)' al grid_data."""
    if not grid_data:
        return grid_data

    def _is_ciclo_basico(codigo: str) -> bool:
        return codigo.upper().startswith(("F", "FB"))

    def _passes(b: ScheduleBlock) -> bool:
        if filtro_tipo == "Ciclo Básico (F/FB)":
            if not _is_ciclo_basico(b.materia_codigo):
                return False
        elif filtro_tipo == "Específicas de carrera":
            if _is_ciclo_basico(b.materia_codigo):
                return False
        if excluir_comunes:
            n_carr = materias_carreras_count.get(b.materia_codigo, 0)
            if n_carr > 1:
                return False
        return True

    out = {
        dia: [b for b in blocks if _passes(b)]
        for dia, blocks in grid_data.items()
    }
    return {d: bs for d, bs in out.items() if bs}


# =============================================================================
# Build grid
# =============================================================================

def _build_plan_grid(
    plan_id: str,
) -> tuple[dict[str, list[ScheduleBlock]], dict[str, str]]:
    """Construye la grilla del plan completo a partir de
    ComisionDB+HorarioDB. Devuelve (grid_data, materias_map) donde
    materias_map es {codigo: nombre}.
    """
    grid: dict[str, list[ScheduleBlock]] = {}
    materias_map: dict[str, str] = {}
    with next(get_session()) as session:
        coms = list(session.exec(
            select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
        ).all())
        com_by_id = {c.id: c for c in coms}
        com_ids = list(com_by_id.keys())
        if not com_ids:
            return grid, materias_map
        hs = list(session.exec(
            select(HorarioDB).where(col(HorarioDB.comision_id).in_(com_ids))
        ).all())
        mat_codes = list({c.materia_codigo for c in coms})
        mats = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codes))
        ).all())
        materias_map = {m.codigo: m.nombre for m in mats}

    for h in hs:
        c = com_by_id.get(h.comision_id)
        if c is None:
            continue
        mat_nombre = materias_map.get(c.materia_codigo, c.materia_codigo)
        block = ScheduleBlock(
            entry_id=h.id,
            materia_codigo=c.materia_codigo,
            materia_nombre=mat_nombre,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            comision=c.numero,
        )
        grid.setdefault(h.dia, []).append(block)

    return grid, materias_map


# =============================================================================
# Entrypoint
# =============================================================================

def render_plan_grilla_editor(
    plan_id: str, key_ns: str = "plan_grilla",
) -> None:
    """Renderiza el editor completo de la grilla horaria del plan.

    Espejo de Cronogramas → Editar pero sobre HorarioDB+ComisionDB.
    """
    # Toast pendiente de accion anterior
    if "_pge_toast" in st.session_state:
        st.toast(st.session_state.pop("_pge_toast"))

    st.subheader("Editar grilla horaria del plan")
    st.caption(
        "Arrastrá bloques para cambiar día/hora. Redimensioná para "
        "ajustar duración. Click sobre un bloque para editar/eliminar. "
        "Drag sobre celdas vacías para agregar (requiere materia activa)."
    )

    with next(get_session()) as session:
        plan = session.get(PlanificacionCursadaDB, plan_id)
        if plan is None or not plan.ciclo_id:
            st.error(f"Plan '{plan_id}' no encontrado o sin ciclo.")
            return
        config = get_or_create_config(session)

        # Carreras del ciclo
        pv_ids = list(session.exec(
            select(CicloPlanVersionDB.plan_version_id)
            .where(CicloPlanVersionDB.ciclo_id == plan.ciclo_id)
        ).all())
        carreras_ciclo = []
        if pv_ids:
            carreras_ciclo = list(session.exec(
                select(CarreraDB)
                .join(
                    PlanCarreraVersionDB,
                    CarreraDB.codigo == PlanCarreraVersionDB.carrera_codigo,  # type: ignore[arg-type]
                )
                .where(col(PlanCarreraVersionDB.id).in_(pv_ids))
                .distinct()
            ).all())

        # Mapa de materias del plan (para format_func + búsqueda)
        all_mat_codes = list(session.exec(
            select(ComisionDB.materia_codigo)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .distinct()
        ).all())
        all_mats_db = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(all_mat_codes))
        ).all()) if all_mat_codes else []
        materias_map: dict[str, str] = {
            m.codigo: m.nombre for m in all_mats_db
        }

        # Conteo de carreras por materia (para 'excluir comunes')
        pe_rows = list(session.exec(
            select(PlanEstudioDB.materia_codigo, PlanEstudioDB.carrera_codigo)
            .where(col(PlanEstudioDB.plan_version_id).in_(pv_ids))
            .where(col(PlanEstudioDB.materia_codigo).in_(all_mat_codes))
        ).all()) if all_mat_codes and pv_ids else []
        materias_carreras: dict[str, set[str]] = {}
        for mc, cc in pe_rows:
            materias_carreras.setdefault(mc, set()).add(cc)
        materias_carreras_count: dict[str, int] = {
            mc: len(carrs) for mc, carrs in materias_carreras.items()
        }

    # --- Modo de edicion ---
    edit_modo = st.radio(
        "Modo de edición",
        options=["Por grupo", "Por materia"],
        horizontal=True,
        key=f"{key_ns}_modo",
        help=(
            "'Por grupo' filtra por carrera/año/cuatrimestre. "
            "'Por materia' permite enfocarse en una sola materia "
            "(útil para materias compartidas entre carreras)."
        ),
    )

    action = None
    sel_mat_add: Optional[str] = None

    # Si hay un dialog activo, no procesamos acciones del calendario
    dialog_active = (
        "_pge_pending_click" in st.session_state
        or "_pge_pending_select" in st.session_state
    )

    # =========================================================================
    # Mode: Por materia
    # =========================================================================
    if edit_modo == "Por materia":
        sm_busqueda = st.text_input(
            "🔍 Buscar materia por nombre o código",
            key=f"{key_ns}_sm_buscar",
            placeholder="Ej: fisica III, FB10, algebra...",
        )
        sm_all = sorted(materias_map.keys())
        if sm_busqueda.strip():
            t = sm_busqueda.strip().lower()
            sm_opts = [
                c for c in sm_all
                if t in c.lower() or t in materias_map[c].lower()
            ]
        else:
            sm_opts = sm_all
        if not sm_opts:
            sm_opts = sm_all

        sm_sel = st.selectbox(
            "Materia",
            options=sm_opts,
            index=None,
            format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
            placeholder="Seleccioná una materia...",
            key=f"{key_ns}_sm_materia",
        )

        if sm_sel:
            sel_mat_add = sm_sel
            grid_full, _ = _build_plan_grid(plan_id)
            sm_grid = {
                dia: [b for b in blocks if b.materia_codigo == sm_sel]
                for dia, blocks in grid_full.items()
            }
            sm_grid = {d: bs for d, bs in sm_grid.items() if bs}

            sm_n = sum(len(bs) for bs in sm_grid.values())
            if sm_n > 0:
                st.caption(
                    f"{sm_n} entrada(s) para "
                    f"**{materias_map.get(sm_sel, sm_sel)}**. "
                    f"Drag sobre rango vacío para agregar."
                )
            else:
                st.info(
                    f"No hay entradas para "
                    f"**{materias_map.get(sm_sel, sm_sel)}**. "
                    f"Drag sobre la grilla para agregar la primera."
                )

            st.divider()

            if not dialog_active:
                action = render_editable_schedule_calendar(
                    sm_grid, config,
                    key=f"{key_ns}_cal_sm_{sm_sel}",
                    allow_empty=True,
                    color_by_comision=True,
                )

            # --- Tabla editable ---
            st.divider()
            st.markdown("##### Entradas y comisiones")
            _render_tabla_editable_por_materia(plan_id, sm_sel, key_ns)

        else:
            st.caption(
                "Seleccioná una materia para ver y editar sus horarios "
                "en el plan."
            )

    # =========================================================================
    # Mode: Por grupo
    # =========================================================================
    else:
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            carrera_opts = [
                f"{c.codigo} - {c.nombre}" for c in carreras_ciclo
            ]
            f_carrera = st.selectbox(
                "Carrera", options=carrera_opts,
                index=None, placeholder="Seleccionar carrera...",
                key=f"{key_ns}_filtro_carrera",
            )
        with col_f2:
            f_anio = st.selectbox(
                "Año de cursada",
                options=[1, 2, 3, 4, 5, 6],
                index=None, placeholder="Seleccionar año...",
                key=f"{key_ns}_filtro_anio",
            )
        with col_f3:
            f_cuatri = st.selectbox(
                "Cuatrimestre",
                options=["1C", "2C", "Anual"],
                index=None, placeholder="Seleccionar cuatrimestre...",
                key=f"{key_ns}_filtro_cuatri",
            )

        col_f4, col_f5 = st.columns(2)
        with col_f4:
            f_tipo = st.selectbox(
                "Tipo de materia",
                options=[
                    "Todas", "Ciclo Básico (F/FB)", "Específicas de carrera",
                ],
                key=f"{key_ns}_filtro_tipo",
            )
        with col_f5:
            f_excluir_comunes = st.checkbox(
                "Excluir materias comunes (multi-carrera)",
                key=f"{key_ns}_excluir_comunes",
            )

        all_filters_set = (
            f_carrera is not None and f_anio is not None
            and f_cuatri is not None
        )

        filtered_mats: Optional[set[str]] = None
        if all_filters_set:
            with next(get_session()) as session:
                eq = (
                    select(PlanEstudioDB.materia_codigo)
                    .where(col(PlanEstudioDB.plan_version_id).in_(pv_ids))
                )
                e_carrera_cod = f_carrera.split(" - ")[0]
                eq = eq.where(PlanEstudioDB.carrera_codigo == e_carrera_cod)
                eq = eq.where(PlanEstudioDB.anio_plan == int(f_anio))
                if f_cuatri == "Anual":
                    eq = eq.where(
                        col(PlanEstudioDB.cuatrimestre_plan).in_(
                            ["Anual", "anual"]
                        )
                    )
                else:
                    eq = eq.where(PlanEstudioDB.cuatrimestre_plan == f_cuatri)
                filtered_mats = set(session.exec(eq.distinct()).all())

        if not all_filters_set:
            st.caption(
                "Seleccioná Carrera, Año y Cuatrimestre para ver y "
                "editar las materias del plan."
            )
        else:
            grid_full, _ = _build_plan_grid(plan_id)
            mats_en_plan: set[str] = set()
            for blocks in grid_full.values():
                for b in blocks:
                    mats_en_plan.add(b.materia_codigo)

            mats_disponibles = mats_en_plan
            if filtered_mats is not None:
                mats_disponibles = mats_en_plan & filtered_mats

            mat_list = sorted(
                mats_disponibles,
                key=lambda c: materias_map.get(c, c),
            )
            mats_sel = st.multiselect(
                "Materias a mostrar",
                options=mat_list,
                default=mat_list,
                format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                key=f"{key_ns}_filtro_materias",
            )
            selected_set = set(mats_sel) if mats_sel else mats_disponibles

            st.divider()

            grid_data = grid_full
            if grid_data:
                grid_data = {
                    dia: [
                        b for b in blocks
                        if b.materia_codigo in selected_set
                    ]
                    for dia, blocks in grid_data.items()
                }
                grid_data = {d: bs for d, bs in grid_data.items() if bs}

            grid_data = _aplicar_filtro_tipo_materia(
                grid_data, f_tipo, f_excluir_comunes,
                materias_carreras_count,
            )

            if not dialog_active:
                action = render_editable_schedule_calendar(
                    grid_data, config, key=f"{key_ns}_cal_pg",
                    color_by_comision=False,
                )

            # --- Selector de materia para agregar ---
            st.divider()
            mat_options_base = sorted(
                c for c in materias_map
                if filtered_mats is None or c in filtered_mats
            )
            busqueda_mat = st.text_input(
                "🔍 Buscar materia por nombre o código",
                key=f"{key_ns}_buscar_materia",
                placeholder="Ej: algebra, F0301, programacion...",
            )
            if busqueda_mat.strip():
                t = busqueda_mat.strip().lower()
                mat_opts = [
                    c for c in mat_options_base
                    if t in c.lower() or t in materias_map[c].lower()
                ]
            else:
                mat_opts = mat_options_base

            if mat_opts:
                sel_mat_add = st.selectbox(
                    "Materia (para agregar al seleccionar un rango)",
                    options=mat_opts,
                    index=None,
                    format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                    placeholder="Seleccioná una materia...",
                    key=f"{key_ns}_add_materia",
                )
            else:
                if busqueda_mat.strip():
                    st.warning(
                        f"No se encontraron materias para "
                        f"'{busqueda_mat}'"
                    )
                else:
                    st.info(
                        "No hay materias disponibles con los filtros "
                        "actuales."
                    )

    # =========================================================================
    # Procesar acciones del calendario
    # =========================================================================
    if action is not None:
        # Cache global de actions (cap 200, FIFO)
        processed_set: set = st.session_state.setdefault(
            "_pge_processed_actions", set(),
        )
        processed_list: list = st.session_state.setdefault(
            "_pge_processed_actions_order", [],
        )
        key_str = (
            f"{action.action}|{getattr(action, 'entry_id', '') or ''}|"
            f"{action.dia}|{action.hora_inicio}|{action.hora_fin}"
        )
        if key_str in processed_set:
            return
        processed_set.add(key_str)
        processed_list.append(key_str)
        while len(processed_list) > 200:
            ev = processed_list.pop(0)
            processed_set.discard(ev)

        if action.action == "move":
            # Drag/resize: abrir dialog precargado con nuevos valores
            if not action.entry_id:
                return
            with next(get_session()) as session:
                h = session.get(HorarioDB, action.entry_id)
                if h is None:
                    return
                baseline_dia = h.dia
                baseline_hi = h.hora_inicio
                baseline_hf = h.hora_fin
                tipo = h.tipo_clase
                com_id = h.comision_id
            st.session_state["_pge_pending_click"] = {
                "plan_id": plan_id,
                "horario_id": action.entry_id,
                "materia_codigo": action.materia_codigo,
                "dia": action.dia,
                "hora_inicio": action.hora_inicio,
                "hora_fin": action.hora_fin,
                "comision_id": com_id,
                "tipo_clase": tipo,
                "_baseline_dia": baseline_dia,
                "_baseline_hi": baseline_hi,
                "_baseline_hf": baseline_hf,
                "_key": key_str,
            }
            _dialog_edit_horario()

        elif action.action == "click":
            if not action.entry_id:
                return
            with next(get_session()) as session:
                h = session.get(HorarioDB, action.entry_id)
                tipo = h.tipo_clase if h else None
                com_id = h.comision_id if h else None
            st.session_state["_pge_pending_click"] = {
                "plan_id": plan_id,
                "horario_id": action.entry_id,
                "materia_codigo": action.materia_codigo,
                "dia": action.dia,
                "hora_inicio": action.hora_inicio,
                "hora_fin": action.hora_fin,
                "comision_id": com_id,
                "tipo_clase": tipo,
                "_key": key_str,
            }
            _dialog_edit_horario()

        elif action.action == "select" and sel_mat_add:
            st.session_state["_pge_pending_select"] = {
                "plan_id": plan_id,
                "materia_codigo": sel_mat_add,
                "dia": action.dia,
                "hora_inicio": action.hora_inicio,
                "hora_fin": action.hora_fin,
                "_key": key_str,
            }
            _dialog_add_horario()


# =============================================================================
# Tabla editable (modo Por materia)
# =============================================================================

def _render_tabla_editable_por_materia(
    plan_id: str, materia_codigo: str, key_ns: str,
) -> None:
    """Tabla data_editor con todos los horarios de la materia activa,
    agrupados por comisión, con auto-save al cambiar."""
    from streamlit import column_config

    with next(get_session()) as session:
        coms = list(session.exec(
            select(ComisionDB)
            .where(ComisionDB.plan_cursada_id == plan_id)
            .where(ComisionDB.materia_codigo == materia_codigo)
            .order_by(ComisionDB.numero)  # type: ignore[arg-type]
        ).all())
        com_by_num = {c.numero: c for c in coms}
        com_by_id = {c.id: c for c in coms}
        com_ids = list(com_by_id.keys())
        hs: list[HorarioDB] = []
        if com_ids:
            hs = list(session.exec(
                select(HorarioDB)
                .where(col(HorarioDB.comision_id).in_(com_ids))
                .order_by(HorarioDB.dia, HorarioDB.hora_inicio)  # type: ignore[arg-type]
            ).all())
        mat_db = session.get(MateriaDB, materia_codigo)
        default_cupo = mat_db.cupo if (mat_db and mat_db.cupo) else 30

    if not coms and not hs:
        st.info(
            "Esta materia no tiene comisiones ni horarios en el plan. "
            "Agregá horarios desde el calendario para empezar."
        )
        return

    max_com = max(c.numero for c in coms) if coms else 1
    com_options = list(range(1, max_com + 3))

    df = pd.DataFrame([
        {
            "horario_id": h.id,
            "Día": h.dia,
            "Inicio": h.hora_inicio,
            "Fin": h.hora_fin,
            "Comisión": (com_by_id[h.comision_id].numero if h.comision_id in com_by_id else 1),
            "Tipo": h.tipo_clase or "sin determinar",
        }
        for h in hs
    ]) if hs else pd.DataFrame(
        columns=["horario_id", "Día", "Inicio", "Fin", "Comisión", "Tipo"]
    )

    de_key = f"{key_ns}_de_{plan_id}_{materia_codigo}_{len(hs)}"

    def _get_or_create_com(session, num: int) -> ComisionDB:
        if num in com_by_num:
            return com_by_num[num]
        # Crear comision nueva al vuelo
        new_com = ComisionDB(
            id=str(uuid.uuid4()),
            materia_codigo=materia_codigo,
            plan_cursada_id=plan_id,
            comision_key=f"{materia_codigo}-{num:03d}",
            nombre=f"Comision {num}",
            numero=num,
            cupo=default_cupo,
        )
        session.add(new_com)
        session.flush()
        com_by_num[num] = new_com
        com_by_id[new_com.id] = new_com
        return new_com

    def _on_change():
        edited = st.session_state.get(de_key)
        if not edited:
            return
        saved = 0
        deleted = 0
        created = 0
        with next(get_session()) as sess:
            for idx_str, changes in (edited.get("edited_rows") or {}).items():
                idx = int(idx_str)
                if idx >= len(hs):
                    continue
                h = hs[idx]
                cambios: dict = {}
                if "Día" in changes:
                    cambios["dia"] = changes["Día"]
                if "Inicio" in changes:
                    cambios["hora_inicio"] = _coerce_time(changes["Inicio"])
                if "Fin" in changes:
                    cambios["hora_fin"] = _coerce_time(changes["Fin"])
                if "Comisión" in changes:
                    new_num = int(changes["Comisión"])
                    new_com = _get_or_create_com(sess, new_num)
                    cambios["comision_id"] = new_com.id
                if "Tipo" in changes:
                    tv = changes["Tipo"]
                    cambios["tipo_clase"] = (
                        None if tv == "sin determinar" else tv
                    )
                if cambios:
                    db_h = sess.get(HorarioDB, h.id)
                    if db_h is not None:
                        for k, v in cambios.items():
                            setattr(db_h, k, v)
                        sess.add(db_h)
                        saved += 1

            for idx in edited.get("deleted_rows") or []:
                if idx < len(hs):
                    db_h = sess.get(HorarioDB, hs[idx].id)
                    if db_h is not None:
                        sess.delete(db_h)
                        deleted += 1

            for row in edited.get("added_rows") or []:
                if row.get("Día") and row.get("Inicio") and row.get("Fin"):
                    new_num = int(row.get("Comisión") or 1)
                    new_com = _get_or_create_com(sess, new_num)
                    tipo_raw = row.get("Tipo")
                    tipo_val = (
                        None
                        if (not tipo_raw or tipo_raw == "sin determinar")
                        else tipo_raw
                    )
                    new_h = HorarioDB(
                        id=str(uuid.uuid4()),
                        comision_id=new_com.id,
                        codigo_materia=materia_codigo,
                        dia=row["Día"],
                        hora_inicio=_coerce_time(row["Inicio"]),
                        hora_fin=_coerce_time(row["Fin"]),
                        tipo_clase=tipo_val,
                    )
                    sess.add(new_h)
                    created += 1
            sess.commit()

        parts = []
        if saved:
            parts.append(f"{saved} modificada(s)")
        if created:
            parts.append(f"{created} agregada(s)")
        if deleted:
            parts.append(f"{deleted} eliminada(s)")
        if parts:
            st.session_state["_pge_toast"] = ", ".join(parts).capitalize()

    st.data_editor(
        df,
        column_config={
            "horario_id": None,
            "Día": column_config.SelectboxColumn(
                options=_DIAS_LIST, width="small",
            ),
            "Inicio": column_config.TimeColumn(format="HH:mm", width="small"),
            "Fin": column_config.TimeColumn(format="HH:mm", width="small"),
            "Comisión": column_config.SelectboxColumn(
                options=com_options,
                help="Número de comisión (se crea al vuelo si no existe)",
                width="small",
            ),
            "Tipo": column_config.SelectboxColumn(
                options=["sin determinar", "teorica", "laboratorio"],
                default="sin determinar",
                help=(
                    "sin determinar (LP decide), teorica o laboratorio"
                ),
                width="small",
            ),
        },
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        on_change=_on_change,
        key=de_key,
    )

    # Resumen por comisión
    if hs:
        rows_summary = []
        for cn in com_options:
            cn_horarios = [
                h for h in hs
                if (com_by_id[h.comision_id].numero if h.comision_id in com_by_id else None) == cn
            ]
            horarios_str = []
            for h in cn_horarios:
                hi = h.hora_inicio.strftime("%H:%M")
                hf = h.hora_fin.strftime("%H:%M")
                horarios_str.append(f"{h.dia[:3]} {hi}-{hf}")
            if cn_horarios or cn in com_by_num:
                rows_summary.append({
                    "Comisión": cn,
                    "Clases": len(cn_horarios),
                    "Horarios": (
                        ", ".join(horarios_str) if horarios_str else "—"
                    ),
                })
        if rows_summary:
            st.caption("Resumen por comisión")
            st.dataframe(
                pd.DataFrame(rows_summary),
                use_container_width=True, hide_index=True,
            )
