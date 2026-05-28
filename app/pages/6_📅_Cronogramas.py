"""Gestion independiente de cronogramas de horarios.

Permite cargar, visualizar, editar y duplicar cronogramas sin necesidad
de asociarlos a un ciclo.  Luego desde Planes se puede seleccionar
un cronograma existente para generar un plan de cursada.
"""

from datetime import time

import pandas as pd
import streamlit as st
from streamlit import column_config
from sqlmodel import select, col, func

from src.database.connection import get_session, init_db
from src.database.models import (
    ScheduleDB, ScheduleEntryDB, MateriaDB, CicloDB, ConfiguracionHoraria,
    CarreraDB, PlanCarreraVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, get_or_create_config
from src.services.schedule_service import (
    create_schedule_standalone,
    create_empty_schedule,
    get_all_schedules,
    duplicate_schedule,
    delete_schedule,
    add_schedule_entry,
    update_schedule_entry,
    delete_schedule_entry,
    build_schedule_grid,
)
from src.services.cronograma_validation_service import (
    validar_cronograma,
    persist_validation,
    get_latest_validation,
    is_validation_stale,
    parse_details_json,
)
from src.ui.calendar_render import render_schedule_calendar, render_editable_schedule_calendar

init_db()

st.set_page_config(page_title="Cronogramas", page_icon="📅", layout="wide")
st.title("📅 Cronogramas")

# =============================================================================
# Data loading
# =============================================================================
with next(get_session()) as session:
    all_schedules = get_all_schedules(session)
    ciclos = ciclo_crud.get_all(session, limit=100)
    config = get_or_create_config(session)
    all_materias = list(session.exec(select(MateriaDB).where(MateriaDB.active == True)).all())
    all_carreras = list(session.exec(select(CarreraDB)).all())

    # Materias comunes: aparecen en 2+ carreras via PlanEstudioDB
    _shared_q = (
        select(PlanEstudioDB.materia_codigo)
        .group_by(PlanEstudioDB.materia_codigo)
        .having(func.count(PlanEstudioDB.carrera_codigo.distinct()) > 1)
    )
    materias_comunes: set[str] = set(session.exec(_shared_q).all())

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}
materias_map = {m.codigo: m.nombre for m in all_materias}
carreras_map = {c.codigo: c.nombre for c in all_carreras}



def _es_ciclo_basico(codigo: str) -> bool:
    """Determina si un codigo de materia pertenece al ciclo basico (F/FB/FI)."""
    return codigo.startswith(("F", "FB", "FI"))


def _aplicar_filtro_tipo(grid_data: dict, filtro_tipo: str, excluir_comunes: bool) -> dict:
    """Aplica filtros de tipo de materia y exclusion de comunes sobre grid_data."""
    if not grid_data:
        return grid_data

    if filtro_tipo == "Ciclo Básico (F/FB)":
        grid_data = {
            dia: [b for b in blocks if _es_ciclo_basico(b.materia_codigo)]
            for dia, blocks in grid_data.items()
        }
    elif filtro_tipo == "Específicas de carrera":
        grid_data = {
            dia: [b for b in blocks if not _es_ciclo_basico(b.materia_codigo)]
            for dia, blocks in grid_data.items()
        }

    if excluir_comunes:
        grid_data = {
            dia: [b for b in blocks if b.materia_codigo not in materias_comunes]
            for dia, blocks in grid_data.items()
        }

    # Quitar dias vacios
    return {d: bs for d, bs in grid_data.items() if bs}


# =============================================================================
# Dialog: confirmar agregar entrada desde el calendario
# =============================================================================
@st.dialog("Agregar entrada")
def _dialog_confirm_add():
    pending = st.session_state.get("edit_pending_add")
    if not pending:
        st.rerun()
        return

    mat_nombre = materias_map.get(pending["materia"], pending["materia"])
    st.markdown(f"**{mat_nombre}** ({pending['materia']})")
    st.markdown(
        f"**{pending['dia']}** · "
        f"{pending['hora_inicio'].strftime('%H:%M')} - "
        f"{pending['hora_fin'].strftime('%H:%M')}"
    )

    add_comision = st.number_input(
        "Comisión (opcional, 0 = sin asignar)",
        min_value=0, max_value=20,
        value=pending.get("comision") or 0,
        key="dlg_add_comision",
    )

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            _com_val = add_comision if add_comision > 0 else None
            with next(get_session()) as session:
                add_schedule_entry(
                    session,
                    pending["schedule_id"],
                    pending["materia"],
                    pending["dia"],
                    pending["hora_inicio"],
                    pending["hora_fin"],
                    comision=_com_val,
                )
            st.session_state["_edit_processed_select"] = pending["_key"]
            st.session_state["_edit_toast"] = (
                f"{mat_nombre} agregada: {pending['dia']} "
                f"{pending['hora_inicio'].strftime('%H:%M')}-"
                f"{pending['hora_fin'].strftime('%H:%M')}"
            )
            del st.session_state["edit_pending_add"]
            st.rerun()
    with col2:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_edit_processed_select"] = pending["_key"]
            del st.session_state["edit_pending_add"]
            st.rerun()


@st.dialog("Editar entrada", width="large")
def _dialog_edit_entry():
    pending = st.session_state.get("edit_pending_click")
    if not pending:
        st.rerun()
        return

    all_mat_codes = sorted(materias_map.keys())
    dias_list = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    # --- Campos editables ---
    dlg_busqueda = st.text_input(
        "🔍 Buscar materia",
        key="dlg_buscar_mat",
        placeholder="Nombre o código...",
    )
    if dlg_busqueda.strip():
        _term = dlg_busqueda.strip().lower()
        dlg_mat_opts = [c for c in all_mat_codes if _term in c.lower() or _term in materias_map[c].lower()]
    else:
        dlg_mat_opts = all_mat_codes

    if not dlg_mat_opts:
        dlg_mat_opts = all_mat_codes  # fallback si no hay match

    # Mantener materia actual seleccionada si esta en la lista filtrada
    dlg_idx = dlg_mat_opts.index(pending["materia"]) if pending["materia"] in dlg_mat_opts else 0

    new_mat = st.selectbox(
        "Materia",
        options=dlg_mat_opts,
        index=dlg_idx,
        format_func=lambda x: f"{materias_map[x]} — {x}",
        key="dlg_edit_mat",
    )
    col_dia, col_ini, col_fin = st.columns(3)
    with col_dia:
        new_dia = st.selectbox(
            "Dia",
            options=dias_list,
            index=dias_list.index(pending["dia"]) if pending["dia"] in dias_list else 0,
            key="dlg_edit_dia",
        )
    with col_ini:
        new_inicio = st.time_input(
            "Inicio", value=pending["hora_inicio"], key="dlg_edit_ini",
        )
    with col_fin:
        new_fin = st.time_input(
            "Fin", value=pending["hora_fin"], key="dlg_edit_fin",
        )

    _pending_com = pending.get("comision") or 0
    new_comision = st.number_input(
        "Comisión (0 = sin asignar)",
        min_value=0, max_value=20, value=_pending_com,
        key="dlg_edit_comision",
    )

    st.divider()

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Guardar", type="primary", use_container_width=True):
            cambios = {}
            if new_mat != pending["materia"]:
                cambios["codigo_materia"] = new_mat
            if new_dia != pending["dia"]:
                cambios["dia"] = new_dia
            if new_inicio != pending["hora_inicio"]:
                cambios["hora_inicio"] = new_inicio
            if new_fin != pending["hora_fin"]:
                cambios["hora_fin"] = new_fin
            _new_com_val = new_comision if new_comision > 0 else None
            if _new_com_val != (pending.get("comision") or None):
                cambios["comision"] = _new_com_val
            mat_label = materias_map.get(new_mat, new_mat)
            if cambios:
                with next(get_session()) as session:
                    update_schedule_entry(session, pending["entry_id"], **cambios)
                st.session_state["_edit_toast"] = (
                    f"{mat_label} actualizada: {new_dia} "
                    f"{new_inicio.strftime('%H:%M')}-{new_fin.strftime('%H:%M')}"
                )
            else:
                st.session_state["_edit_toast"] = "Sin cambios"
            st.session_state["_edit_processed_click"] = pending["_key"]
            del st.session_state["edit_pending_click"]
            st.rerun()
    with col2:
        if st.button("Eliminar", use_container_width=True):
            mat_label = materias_map.get(pending["materia"], pending["materia"])
            with next(get_session()) as session:
                delete_schedule_entry(session, pending["entry_id"])
            st.session_state["_edit_processed_click"] = pending["_key"]
            st.session_state["_edit_toast"] = (
                f"{mat_label} eliminada ({pending['dia']} "
                f"{pending['hora_inicio'].strftime('%H:%M')}-"
                f"{pending['hora_fin'].strftime('%H:%M')})"
            )
            del st.session_state["edit_pending_click"]
            st.rerun()
    with col3:
        if st.button("Cancelar", use_container_width=True):
            st.session_state["_edit_processed_click"] = pending["_key"]
            del st.session_state["edit_pending_click"]
            st.rerun()


# =============================================================================
# Tabs
# =============================================================================
tab_lista, tab_cargar, tab_visualizar, tab_editar, tab_validar = st.tabs([
    "📋 Lista", "📤 Cargar", "👁 Visualizar", "✏️ Editar", "✅ Validar",
])


# =============================================================================
# Tab 1: Lista
# =============================================================================
with tab_lista:
    st.subheader("Cronogramas existentes")
    st.caption(
        "Cada fila muestra el estado de validacion contra el ultimo "
        "ciclo evaluado. Para validar un cronograma o ver el detalle, "
        "abrilo en la pestana **Validar**."
    )

    if not all_schedules:
        st.info("No hay cronogramas cargados. Usa la pestana 'Cargar' para subir uno.")
    else:
        for s in all_schedules:
            with next(get_session()) as session:
                n_entries = session.exec(
                    select(func.count(ScheduleEntryDB.id)).where(
                        ScheduleEntryDB.schedule_id == s.id
                    )
                ).one()
                # Latest validation across any ciclo (for badge)
                _latest_val = get_latest_validation(session, s.id)
                _val_stale = (
                    is_validation_stale(session, _latest_val)
                    if _latest_val else False
                )

            # Badge de estado de validacion
            if _latest_val is None:
                _val_badge = "⚪ sin validar"
            elif _val_stale:
                _val_badge = (
                    f"🟡 validado vs {_latest_val.ciclo_id} pero modificado"
                )
            elif not _latest_val.particion_valid or _latest_val.n_faltantes > 0:
                _val_badge = (
                    f"🔴 con issues vs {_latest_val.ciclo_id} "
                    f"({_latest_val.n_faltantes} faltantes, "
                    f"{_latest_val.particion_n_infactibles} part. infactibles)"
                )
            else:
                _val_badge = f"🟢 validado vs {_latest_val.ciclo_id}"

            ciclo_label = s.ciclo_id if s.ciclo_id else "sin ciclo"
            _header = (
                f"**{s.nombre}** \u2014 {n_entries} entradas \u2014 "
                f"ciclo upload: {ciclo_label} \u2014 {s.fecha_upload} \u2014 "
                f"{_val_badge}"
            )
            with st.expander(_header):
                # Nombre editable
                _new_name = st.text_input(
                    "Nombre del cronograma",
                    value=s.nombre,
                    key=f"name_edit_{s.id}",
                    help="Editar y presionar Enter para guardar.",
                )
                if _new_name != s.nombre and _new_name.strip():
                    with next(get_session()) as session:
                        _sched = session.get(ScheduleDB, s.id)
                        if _sched:
                            _sched.nombre = _new_name.strip()
                            session.add(_sched)
                            session.commit()
                    st.toast(f"Nombre actualizado a '{_new_name.strip()}'.")
                    st.rerun()

                # Mini-resumen de la ultima validacion (si existe)
                if _latest_val is not None:
                    _val_caption = (
                        f"Ultima validacion: **{_latest_val.validated_at:%Y-%m-%d %H:%M}** "
                        f"vs ciclo **{_latest_val.ciclo_id}** \u00b7 "
                        f"cubiertas {_latest_val.n_cubiertas}/{_latest_val.n_esperadas} \u00b7 "
                        f"con lab: {_latest_val.n_con_lab_asignado} "
                        f"({_latest_val.n_lab_fijo} fijo, "
                        f"{_latest_val.n_lab_reserva} reserva, "
                        f"{_latest_val.n_lab_pendiente} pendiente) \u00b7 "
                        f"particion: "
                        f"{'OK' if _latest_val.particion_valid else f'{_latest_val.particion_n_infactibles} infactibles'}"
                    )
                    if _val_stale:
                        st.warning(
                            _val_caption
                            + "\n\n\u26a0\ufe0f El cronograma fue modificado "
                            "desde esta validacion. Re-validar en la pestana "
                            "**Validar** para refrescar."
                        )
                    else:
                        st.info(_val_caption)
                else:
                    st.caption(
                        "Este cronograma todavia no fue validado contra "
                        "ningun ciclo. Abrir la pestana **Validar** para hacerlo."
                    )

                # Acciones (duplicar, eliminar)
                col_dup, col_del = st.columns([1, 1])
                with col_dup:
                    new_name = st.text_input(
                        "Nombre de la copia",
                        value=f"{s.nombre} (copia)",
                        key=f"dup_name_{s.id}",
                    )
                    if st.button("Duplicar", key=f"dup_{s.id}"):
                        with next(get_session()) as session:
                            duplicate_schedule(session, s.id, new_name)
                        st.success(f"Cronograma duplicado como '{new_name}'")
                        st.rerun()
                with col_del:
                    st.warning("Esta accion es irreversible.")
                    if st.button("Eliminar", key=f"del_{s.id}", type="primary"):
                        with next(get_session()) as session:
                            delete_schedule(session, s.id)
                        st.success("Cronograma eliminado")
                        st.rerun()


# =============================================================================
# Tab 2: Cargar
# =============================================================================
with tab_cargar:
    st.subheader("Crear nuevo cronograma")

    modo_carga = st.radio(
        "Modo de creación",
        options=["Crear vacío", "Cargar desde archivo"],
        horizontal=True,
        key="crono_modo",
    )

    nombre = st.text_input("Nombre del cronograma", key="crono_nombre")

    ciclo_sel = st.selectbox(
        "Ciclo (opcional)",
        options=["(ninguno)"] + ciclo_ids,
        key="crono_ciclo",
    )
    ciclo_id_val = ciclo_sel if ciclo_sel != "(ninguno)" else None

    if modo_carga == "Cargar desde archivo":
        uploaded = st.file_uploader(
            "Archivo CSV o Excel con horarios",
            type=["csv", "xlsx", "xls"],
            key="crono_upload",
        )

        if st.button("Crear cronograma", disabled=not nombre or not uploaded):
            with next(get_session()) as session:
                result = create_schedule_standalone(
                    session, nombre, uploaded, ciclo_id=ciclo_id_val
                )
            if result.errors:
                for e in result.errors:
                    st.error(e)
            if result.warnings:
                for w in result.warnings:
                    st.warning(w)
            if result.schedule:
                st.success(
                    f"Cronograma '{result.schedule.nombre}' creado con "
                    f"{result.entries_created} entradas."
                )
                st.rerun()
    else:
        st.info("Se creará un cronograma sin entradas. Podés agregar horarios desde la pestaña Editar.")
        if st.button("Crear cronograma vacío", disabled=not nombre):
            with next(get_session()) as session:
                try:
                    schedule = create_empty_schedule(
                        session, nombre, ciclo_id=ciclo_id_val
                    )
                    st.success(f"Cronograma '{schedule.nombre}' creado. Usá la pestaña Editar para agregar entradas.")
                    st.rerun()
                except ValueError as e:
                    st.error(str(e))


# =============================================================================
# Tab 3: Visualizar
# =============================================================================
with tab_visualizar:
    st.subheader("Visualizar cronograma")

    if not all_schedules:
        st.info("No hay cronogramas para visualizar.")
    else:
        schedule_options = {s.id: f"{s.nombre} ({s.fecha_upload})" for s in all_schedules}
        sel_id = st.selectbox(
            "Seleccionar cronograma",
            options=list(schedule_options.keys()),
            format_func=lambda x: schedule_options[x],
            key="viz_schedule",
        )

        if sel_id:
            viz_modo = st.radio(
                "Modo de visualización",
                options=["Por grupo", "Por materia"],
                horizontal=True,
                key="viz_modo",
                help=(
                    "'Por grupo' filtra por carrera/año/cuatrimestre. "
                    "'Por materia' permite enfocarse en una sola materia "
                    "(útil para materias compartidas entre carreras)."
                ),
            )

            # =================================================================
            # Mode: Por materia
            # =================================================================
            if viz_modo == "Por materia":
                _vm_busqueda = st.text_input(
                    "🔍 Buscar materia por nombre o código",
                    key="viz_sm_buscar",
                    placeholder="Ej: fisica III, FB10, algebra...",
                )
                _vm_all = sorted(materias_map.keys())
                if _vm_busqueda.strip():
                    _vm_term = _vm_busqueda.strip().lower()
                    _vm_opts = [
                        c for c in _vm_all
                        if _vm_term in c.lower()
                        or _vm_term in materias_map[c].lower()
                    ]
                else:
                    _vm_opts = _vm_all
                if not _vm_opts:
                    _vm_opts = _vm_all

                _vm_sel = st.selectbox(
                    "Materia",
                    options=_vm_opts,
                    index=None,
                    format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                    placeholder="Seleccioná una materia...",
                    key="viz_sm_materia",
                )

                if _vm_sel:
                    with next(get_session()) as session:
                        _vm_grid = build_schedule_grid(session, sel_id)

                    _vm_grid = {
                        dia: [b for b in blocks if b.materia_codigo == _vm_sel]
                        for dia, blocks in _vm_grid.items()
                    }
                    _vm_grid = {d: bs for d, bs in _vm_grid.items() if bs}

                    _vm_n = sum(len(bs) for bs in _vm_grid.values())
                    if _vm_n > 0:
                        st.caption(
                            f"{_vm_n} entrada(s) para "
                            f"**{materias_map.get(_vm_sel, _vm_sel)}**."
                        )
                    else:
                        st.info(
                            f"No hay entradas para "
                            f"**{materias_map.get(_vm_sel, _vm_sel)}** "
                            f"en este cronograma."
                        )

                    st.divider()

                    if _vm_grid:
                        render_schedule_calendar(
                            _vm_grid, config,
                            key=f"viz_cal_mat_{_vm_n}",
                            color_by_comision=True,
                        )
                else:
                    st.caption(
                        "Seleccioná una materia para ver sus horarios "
                        "en el cronograma."
                    )

            # =================================================================
            # Mode: Por grupo (carrera/año/cuatri)
            # =================================================================
            else:
                # --- Filtros fila 1: carrera, año, cuatrimestre ---
                col_f1, col_f2, col_f3 = st.columns(3)
                with col_f1:
                    carrera_opts = [
                        f"{c.codigo} - {c.nombre}" for c in all_carreras
                    ]
                    viz_filtro_carrera = st.selectbox(
                        "Carrera", options=carrera_opts,
                        index=None, placeholder="Seleccionar carrera...",
                        key="viz_filtro_carrera",
                    )
                with col_f2:
                    viz_filtro_anio = st.selectbox(
                        "Año de cursada",
                        options=[1, 2, 3, 4, 5, 6],
                        index=None, placeholder="Seleccionar año...",
                        key="viz_filtro_anio",
                    )
                with col_f3:
                    viz_filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["1C", "2C", "Anual"],
                        index=None, placeholder="Seleccionar cuatrimestre...",
                        key="viz_filtro_cuatri",
                    )

                # --- Filtros fila 2: tipo de materia, excluir comunes ---
                col_f4, col_f5 = st.columns(2)
                with col_f4:
                    viz_filtro_tipo = st.selectbox(
                        "Tipo de materia",
                        options=["Todas", "Ciclo Básico (F/FB)", "Específicas de carrera"],
                        key="viz_filtro_tipo",
                    )
                with col_f5:
                    viz_excluir_comunes = st.checkbox(
                        "Excluir materias comunes (multi-carrera)",
                        key="viz_excluir_comunes",
                    )

                _viz_all_filters_set = (
                    viz_filtro_carrera is not None
                    and viz_filtro_anio is not None
                    and viz_filtro_cuatri is not None
                )

                # Determinar materias filtradas via PlanEstudioDB
                viz_filtered_mats: set[str] | None = None
                if _viz_all_filters_set:
                    with next(get_session()) as session:
                        q = select(PlanEstudioDB.materia_codigo)
                        carrera_cod = viz_filtro_carrera.split(" - ")[0]
                        q = q.where(PlanEstudioDB.carrera_codigo == carrera_cod)
                        q = q.where(PlanEstudioDB.anio_plan == int(viz_filtro_anio))
                        if viz_filtro_cuatri == "Anual":
                            q = q.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            q = q.where(PlanEstudioDB.cuatrimestre_plan == viz_filtro_cuatri)
                        viz_filtered_mats = set(session.exec(q.distinct()).all())

                if not _viz_all_filters_set:
                    st.caption(
                        "Seleccioná Carrera, Año y Cuatrimestre para ver "
                        "las materias del cronograma."
                    )
                else:
                    # --- Multiselect de materias ---
                    with next(get_session()) as session:
                        grid_data = build_schedule_grid(session, sel_id)

                    # Materias presentes en el cronograma
                    _viz_mats_en_schedule = set()
                    for _blocks in grid_data.values():
                        for _b in _blocks:
                            _viz_mats_en_schedule.add(_b.materia_codigo)

                    # Intersectar con filtros de plan
                    _viz_mats_disponibles = _viz_mats_en_schedule
                    if viz_filtered_mats is not None:
                        _viz_mats_disponibles = _viz_mats_en_schedule & viz_filtered_mats

                    _viz_mat_list = sorted(_viz_mats_disponibles, key=lambda c: materias_map.get(c, c))
                    viz_materias_sel = st.multiselect(
                        "Materias a mostrar",
                        options=_viz_mat_list,
                        default=_viz_mat_list,
                        format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                        key="viz_filtro_materias",
                    )
                    _viz_selected_set = set(viz_materias_sel) if viz_materias_sel else _viz_mats_disponibles

                    st.divider()

                    # Aplicar filtro de materias seleccionadas
                    if grid_data:
                        grid_data = {
                            dia: [b for b in blocks if b.materia_codigo in _viz_selected_set]
                            for dia, blocks in grid_data.items()
                        }
                        grid_data = {d: bs for d, bs in grid_data.items() if bs}

                    # Aplicar filtros de tipo y comunes
                    grid_data = _aplicar_filtro_tipo(grid_data, viz_filtro_tipo, viz_excluir_comunes)

                    render_schedule_calendar(grid_data, config, key="viz_cal")


# =============================================================================
# Tab 4: Editar
# =============================================================================
with tab_editar:
    # Mostrar toast pendiente de accion anterior
    if "_edit_toast" in st.session_state:
        st.toast(st.session_state.pop("_edit_toast"))

    st.subheader("Editar entradas de cronograma")
    st.caption(
        "Arrastra bloques para cambiar dia/hora. "
        "Redimensiona para ajustar duracion. "
        "Hace click en un bloque para eliminarlo. "
        "Selecciona un rango vacio para agregar una entrada."
    )

    if not all_schedules:
        st.info("No hay cronogramas para editar.")
    else:
        schedule_options_edit = {
            s.id: f"{s.nombre} ({s.fecha_upload})" for s in all_schedules
        }
        # Consumir buffer de pre-seleccion (viene de Validacion → Editar).
        # Setear `edit_schedule` ANTES de instanciar el widget.
        _pending = st.session_state.pop("_pending_edit_schedule_id", None)
        if _pending and _pending in schedule_options_edit:
            st.session_state["edit_schedule"] = _pending
        sel_edit_id = st.selectbox(
            "Seleccionar cronograma",
            options=list(schedule_options_edit.keys()),
            format_func=lambda x: schedule_options_edit[x],
            key="edit_schedule",
        )

        if sel_edit_id:
            edit_modo = st.radio(
                "Modo de edición",
                options=["Por grupo", "Por materia"],
                horizontal=True,
                key="edit_modo",
                help=(
                    "'Por grupo' filtra por carrera/año/cuatrimestre. "
                    "'Por materia' permite enfocarse en una sola materia "
                    "(útil para materias compartidas entre carreras)."
                ),
            )

            action = None
            sel_mat_add = None

            # =================================================================
            # Mode: Por materia
            # =================================================================
            if edit_modo == "Por materia":
                _sm_busqueda = st.text_input(
                    "🔍 Buscar materia por nombre o código",
                    key="edit_sm_buscar",
                    placeholder="Ej: fisica III, FB10, algebra...",
                )
                _sm_all = sorted(materias_map.keys())
                if _sm_busqueda.strip():
                    _sm_term = _sm_busqueda.strip().lower()
                    _sm_opts = [
                        c for c in _sm_all
                        if _sm_term in c.lower()
                        or _sm_term in materias_map[c].lower()
                    ]
                else:
                    _sm_opts = _sm_all
                if not _sm_opts:
                    _sm_opts = _sm_all

                _sm_sel = st.selectbox(
                    "Materia",
                    options=_sm_opts,
                    index=None,
                    format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                    placeholder="Seleccioná una materia...",
                    key="edit_sm_materia",
                )

                if _sm_sel:
                    sel_mat_add = _sm_sel

                    with next(get_session()) as session:
                        _sm_grid = build_schedule_grid(session, sel_edit_id)

                    # Filter to only selected materia
                    _sm_grid = {
                        dia: [b for b in blocks if b.materia_codigo == _sm_sel]
                        for dia, blocks in _sm_grid.items()
                    }
                    _sm_grid = {d: bs for d, bs in _sm_grid.items() if bs}

                    _sm_n = sum(len(bs) for bs in _sm_grid.values())
                    if _sm_n > 0:
                        st.caption(
                            f"{_sm_n} entrada(s) para "
                            f"**{materias_map.get(_sm_sel, _sm_sel)}**. "
                            f"Seleccioná un rango vacío en la grilla para agregar."
                        )
                    else:
                        st.info(
                            f"No hay entradas para "
                            f"**{materias_map.get(_sm_sel, _sm_sel)}**. "
                            f"Seleccioná un rango en la grilla para agregar la primera."
                        )

                    st.divider()

                    action = render_editable_schedule_calendar(
                        _sm_grid, config,
                        key=f"edit_cal_{_sm_n}",
                        allow_empty=True,
                        color_by_comision=True,
                    )

                    # --- Tabla editable de entradas ---
                    st.divider()
                    st.markdown("##### Entradas y comisiones")

                    with next(get_session()) as session:
                        _sm_entries = list(session.exec(
                            select(ScheduleEntryDB)
                            .where(ScheduleEntryDB.schedule_id == sel_edit_id)
                            .where(ScheduleEntryDB.codigo_materia == _sm_sel)
                            .order_by(ScheduleEntryDB.dia, ScheduleEntryDB.hora_inicio)
                        ).all())

                    _dias_orden = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
                    _sm_max_com = max(
                        max((e.comision or 0) for e in _sm_entries), 1,
                    ) if _sm_entries else 1
                    _sm_com_options = list(range(0, _sm_max_com + 3))

                    _sm_df = pd.DataFrame([
                        {
                            "entry_id": e.id,
                            "Día": e.dia,
                            "Inicio": e.hora_inicio,
                            "Fin": e.hora_fin,
                            "Comisión": e.comision or 0,
                            "Tipo": e.tipo_clase or "sin determinar",
                        }
                        for e in _sm_entries
                    ]) if _sm_entries else pd.DataFrame(
                        columns=["entry_id", "Día", "Inicio", "Fin", "Comisión", "Tipo"]
                    )

                    _sm_de_key = f"sm_de_{sel_edit_id}_{_sm_sel}_{len(_sm_entries)}"

                    def _coerce_time(val) -> time:
                        """Convierte string HH:MM:SS.mmm o time a time."""
                        if isinstance(val, time):
                            return val
                        s = str(val).split(".")[0]  # strip millis
                        parts = s.split(":")
                        return time(int(parts[0]), int(parts[1]),
                                    int(parts[2]) if len(parts) > 2 else 0)

                    def _sm_on_change():
                        """Autoguardar cambios del data_editor."""
                        edited = st.session_state.get(_sm_de_key)
                        if not edited:
                            return
                        _saved = 0
                        _deleted = 0
                        _created = 0
                        with next(get_session()) as sess:
                            # Edited rows
                            for idx_str, changes in (
                                edited.get("edited_rows") or {}
                            ).items():
                                idx = int(idx_str)
                                if idx < len(_sm_entries):
                                    _e = _sm_entries[idx]
                                    _cambios = {}
                                    if "Día" in changes:
                                        _cambios["dia"] = changes["Día"]
                                    if "Inicio" in changes:
                                        _cambios["hora_inicio"] = _coerce_time(changes["Inicio"])
                                    if "Fin" in changes:
                                        _cambios["hora_fin"] = _coerce_time(changes["Fin"])
                                    if "Comisión" in changes:
                                        _cv = int(changes["Comisión"])
                                        _cambios["comision"] = _cv if _cv > 0 else None
                                    if "Tipo" in changes:
                                        _tv = changes["Tipo"]
                                        _cambios["tipo_clase"] = None if _tv == "sin determinar" else _tv
                                    if _cambios:
                                        update_schedule_entry(
                                            sess, _e.id, **_cambios,
                                        )
                                        _saved += 1
                            # Deleted rows
                            for idx in edited.get("deleted_rows") or []:
                                if idx < len(_sm_entries):
                                    delete_schedule_entry(
                                        sess, _sm_entries[idx].id,
                                    )
                                    _deleted += 1
                            # Added rows
                            for row in edited.get("added_rows") or []:
                                if row.get("Día") and row.get("Inicio") and row.get("Fin"):
                                    _cv = int(row.get("Comisión") or 0)
                                    _tipo_raw = row.get("Tipo")
                                    _tipo = None if (not _tipo_raw or _tipo_raw == "sin determinar") else _tipo_raw
                                    add_schedule_entry(
                                        sess,
                                        sel_edit_id,
                                        _sm_sel,
                                        row["Día"],
                                        _coerce_time(row["Inicio"]),
                                        _coerce_time(row["Fin"]),
                                        comision=_cv if _cv > 0 else None,
                                        tipo_clase=_tipo,
                                    )
                                    _created += 1
                        _parts = []
                        if _saved:
                            _parts.append(f"{_saved} modificada(s)")
                        if _created:
                            _parts.append(f"{_created} agregada(s)")
                        if _deleted:
                            _parts.append(f"{_deleted} eliminada(s)")
                        if _parts:
                            st.session_state["_edit_toast"] = (
                                ", ".join(_parts).capitalize()
                            )

                    st.data_editor(
                        _sm_df,
                        column_config={
                            "entry_id": None,
                            "Día": column_config.SelectboxColumn(
                                options=_dias_orden, width="small",
                            ),
                            "Inicio": column_config.TimeColumn(
                                format="HH:mm", width="small",
                            ),
                            "Fin": column_config.TimeColumn(
                                format="HH:mm", width="small",
                            ),
                            "Comisión": column_config.SelectboxColumn(
                                options=_sm_com_options,
                                help="0 = sin asignar",
                                width="small",
                            ),
                            "Tipo": column_config.SelectboxColumn(
                                options=["sin determinar", "teorica", "laboratorio"],
                                default="sin determinar",
                                help="Tipo de clase: sin determinar (LP decide), teorica o laboratorio",
                                width="small",
                            ),
                        },
                        num_rows="dynamic",
                        use_container_width=True,
                        hide_index=True,
                        on_change=_sm_on_change,
                        key=_sm_de_key,
                    )

                    # --- Resumen por comisión ---
                    if _sm_entries:
                        _sm_summary_rows = []
                        for _cn in _sm_com_options:
                            _cn_entries = [
                                e for e in _sm_entries if (e.comision or 0) == _cn
                            ]
                            _horarios = []
                            for _e in _cn_entries:
                                _hi = _e.hora_inicio.strftime("%H:%M")
                                _hf = _e.hora_fin.strftime("%H:%M")
                                _horarios.append(
                                    f"{_e.dia[:3]} {_hi}-{_hf}"
                                )
                            if _cn_entries or _cn > 0:
                                _sm_summary_rows.append({
                                    "Comisión": _cn if _cn > 0 else "Sin asignar",
                                    "Clases": len(_cn_entries),
                                    "Horarios": ", ".join(_horarios) if _horarios else "—",
                                })
                        if _sm_summary_rows:
                            st.caption("Resumen por comisión")
                            st.dataframe(
                                pd.DataFrame(_sm_summary_rows),
                                use_container_width=True,
                                hide_index=True,
                            )

                else:
                    st.caption(
                        "Seleccioná una materia para ver y editar "
                        "sus horarios en el cronograma."
                    )

            # =================================================================
            # Mode: Por grupo (carrera/año/cuatri)
            # =================================================================
            else:
                col_ef1, col_ef2, col_ef3 = st.columns(3)
                with col_ef1:
                    edit_carrera_opts = [
                        f"{c.codigo} - {c.nombre}" for c in all_carreras
                    ]
                    edit_filtro_carrera = st.selectbox(
                        "Carrera", options=edit_carrera_opts,
                        index=None, placeholder="Seleccionar carrera...",
                        key="edit_filtro_carrera",
                    )
                with col_ef2:
                    edit_filtro_anio = st.selectbox(
                        "Año de cursada",
                        options=[1, 2, 3, 4, 5, 6],
                        index=None, placeholder="Seleccionar año...",
                        key="edit_filtro_anio",
                    )
                with col_ef3:
                    edit_filtro_cuatri = st.selectbox(
                        "Cuatrimestre",
                        options=["1C", "2C", "Anual"],
                        index=None, placeholder="Seleccionar cuatrimestre...",
                        key="edit_filtro_cuatri",
                    )

                col_ef4, col_ef5 = st.columns(2)
                with col_ef4:
                    edit_filtro_tipo = st.selectbox(
                        "Tipo de materia",
                        options=["Todas", "Ciclo Básico (F/FB)", "Específicas de carrera"],
                        key="edit_filtro_tipo",
                    )
                with col_ef5:
                    edit_excluir_comunes = st.checkbox(
                        "Excluir materias comunes (multi-carrera)",
                        key="edit_excluir_comunes",
                    )

                _edit_all_filters_set = (
                    edit_filtro_carrera is not None
                    and edit_filtro_anio is not None
                    and edit_filtro_cuatri is not None
                )

                edit_filtered_mats: set[str] | None = None
                if _edit_all_filters_set:
                    with next(get_session()) as session:
                        eq = select(PlanEstudioDB.materia_codigo)
                        e_carrera_cod = edit_filtro_carrera.split(" - ")[0]
                        eq = eq.where(PlanEstudioDB.carrera_codigo == e_carrera_cod)
                        eq = eq.where(PlanEstudioDB.anio_plan == int(edit_filtro_anio))
                        if edit_filtro_cuatri == "Anual":
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan == edit_filtro_cuatri)
                        edit_filtered_mats = set(session.exec(eq.distinct()).all())

                if not _edit_all_filters_set:
                    st.caption(
                        "Seleccioná Carrera, Año y Cuatrimestre para ver "
                        "y editar las materias del cronograma."
                    )
                else:
                    with next(get_session()) as session:
                        grid_data_full = build_schedule_grid(session, sel_edit_id)

                    _edit_mats_en_schedule = set()
                    for _blocks in grid_data_full.values():
                        for _b in _blocks:
                            _edit_mats_en_schedule.add(_b.materia_codigo)

                    _edit_mats_disponibles = _edit_mats_en_schedule
                    if edit_filtered_mats is not None:
                        _edit_mats_disponibles = _edit_mats_en_schedule & edit_filtered_mats

                    _edit_mat_list = sorted(
                        _edit_mats_disponibles,
                        key=lambda c: materias_map.get(c, c),
                    )
                    edit_materias_sel = st.multiselect(
                        "Materias a mostrar",
                        options=_edit_mat_list,
                        default=_edit_mat_list,
                        format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                        key="edit_filtro_materias",
                    )
                    _edit_selected_set = (
                        set(edit_materias_sel)
                        if edit_materias_sel
                        else _edit_mats_disponibles
                    )

                    st.divider()

                    grid_data = grid_data_full
                    if grid_data:
                        grid_data = {
                            dia: [
                                b for b in blocks
                                if b.materia_codigo in _edit_selected_set
                            ]
                            for dia, blocks in grid_data.items()
                        }
                        grid_data = {d: bs for d, bs in grid_data.items() if bs}

                    grid_data = _aplicar_filtro_tipo(
                        grid_data, edit_filtro_tipo, edit_excluir_comunes,
                    )

                    action = render_editable_schedule_calendar(
                        grid_data, config, key="edit_cal",
                    )

                    # --- Selector de materia para agregar ---
                    st.divider()
                    mat_options_base = sorted(
                        c for c in materias_map
                        if c in edit_filtered_mats
                    )

                    busqueda_mat = st.text_input(
                        "🔍 Buscar materia por nombre o código",
                        key="edit_buscar_materia",
                        placeholder="Ej: algebra, F0301, programacion...",
                    )

                    if busqueda_mat.strip():
                        termino = busqueda_mat.strip().lower()
                        mat_options = [
                            c for c in mat_options_base
                            if termino in c.lower()
                            or termino in materias_map[c].lower()
                        ]
                    else:
                        mat_options = mat_options_base

                    if mat_options:
                        sel_mat_add = st.selectbox(
                            "Materia (para agregar al seleccionar un rango)",
                            options=mat_options,
                            index=None,
                            format_func=lambda x: f"{materias_map[x]} — {x}",
                            placeholder="Seleccioná una materia...",
                            key="edit_add_materia",
                        )
                    else:
                        if busqueda_mat.strip():
                            st.warning(
                                f"No se encontraron materias para "
                                f"'{busqueda_mat}'"
                            )
                        else:
                            st.info(
                                "No hay materias disponibles con "
                                "los filtros actuales."
                            )

            # =================================================================
            # Shared: process calendar actions
            # =================================================================
            if action is not None:
                if action.action == "move":
                    move_key = f"{action.entry_id}|{action.dia}|{action.hora_inicio}|{action.hora_fin}"
                    if st.session_state.get("_edit_processed_move") != move_key:
                        with next(get_session()) as session:
                            update_schedule_entry(
                                session,
                                action.entry_id,
                                dia=action.dia,
                                hora_inicio=action.hora_inicio,
                                hora_fin=action.hora_fin,
                            )
                        mat_nombre = materias_map.get(
                            action.materia_codigo,
                            action.materia_codigo or "",
                        )
                        st.session_state["_edit_toast"] = (
                            f"{mat_nombre} movida a {action.dia} "
                            f"{action.hora_inicio.strftime('%H:%M')}-"
                            f"{action.hora_fin.strftime('%H:%M')}"
                        )
                        st.session_state["_edit_processed_move"] = move_key
                        st.rerun()

                elif action.action == "click":
                    click_key = f"{action.entry_id}|{action.dia}|{action.hora_inicio}"
                    if st.session_state.get("_edit_processed_click") != click_key:
                        st.session_state["edit_pending_click"] = {
                            "entry_id": action.entry_id,
                            "materia": action.materia_codigo,
                            "dia": action.dia,
                            "hora_inicio": action.hora_inicio,
                            "hora_fin": action.hora_fin,
                            "comision": action.comision,
                            "_key": click_key,
                        }
                        _dialog_edit_entry()

                elif action.action == "select" and sel_mat_add:
                    select_key = f"{action.dia}|{action.hora_inicio}|{action.hora_fin}"
                    if st.session_state.get("_edit_processed_select") != select_key:
                        st.session_state["edit_pending_add"] = {
                            "schedule_id": sel_edit_id,
                            "materia": sel_mat_add,
                            "dia": action.dia,
                            "hora_inicio": action.hora_inicio,
                            "hora_fin": action.hora_fin,
                            "_key": select_key,
                        }
                        _dialog_confirm_add()


# =============================================================================
# Tab 5: Validar contra ciclo
# =============================================================================
with tab_validar:
    # Cargar ciclos para el selector
    with next(get_session()) as _v_session:
        _v_ciclos = ciclo_crud.get_all(_v_session, limit=100)
    _v_ciclo_ids = [c.id for c in _v_ciclos]
    _v_ciclos_map = {c.id: c for c in _v_ciclos}

    if not _v_ciclo_ids:
        st.info(
            "No hay ciclos registrados. Crear uno en la pagina de Ciclos "
            "antes de validar cronogramas."
        )
    else:
        from src.ui.validacion_cronograma_tab import render_tab as _render_validacion_tab
        _render_validacion_tab(_v_ciclo_ids, _v_ciclos_map)
