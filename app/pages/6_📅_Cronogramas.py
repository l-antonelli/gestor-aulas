"""Gestion independiente de cronogramas de horarios.

Permite cargar, visualizar, editar y duplicar cronogramas sin necesidad
de asociarlos a un ciclo.  Luego desde Planes se puede seleccionar
un cronograma existente para generar un plan de cursada.
"""

import streamlit as st
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

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Confirmar", type="primary", use_container_width=True):
            with next(get_session()) as session:
                add_schedule_entry(
                    session,
                    pending["schedule_id"],
                    pending["materia"],
                    pending["dia"],
                    pending["hora_inicio"],
                    pending["hora_fin"],
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
tab_lista, tab_cargar, tab_visualizar, tab_editar = st.tabs([
    "📋 Lista", "📤 Cargar", "👁 Visualizar", "✏️ Editar",
])


# =============================================================================
# Tab 1: Lista
# =============================================================================
with tab_lista:
    st.subheader("Cronogramas existentes")

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

            ciclo_label = s.ciclo_id if s.ciclo_id else "sin ciclo"
            with st.expander(
                f"**{s.nombre}** — {n_entries} entradas — ciclo: {ciclo_label} "
                f"— {s.fecha_upload}"
            ):
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
            # --- Filtros fila 1: carrera, año, cuatrimestre ---
            col_f1, col_f2, col_f3 = st.columns(3)
            with col_f1:
                carrera_opts = ["Todas"] + [
                    f"{c.codigo} - {c.nombre}" for c in all_carreras
                ]
                viz_filtro_carrera = st.selectbox(
                    "Carrera", options=carrera_opts, key="viz_filtro_carrera"
                )
            with col_f2:
                viz_filtro_anio = st.selectbox(
                    "Año de cursada",
                    options=["Todos", 1, 2, 3, 4, 5, 6],
                    key="viz_filtro_anio",
                )
            with col_f3:
                viz_filtro_cuatri = st.selectbox(
                    "Cuatrimestre",
                    options=["Todos", "1C", "2C", "Anual"],
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

            # Determinar materias filtradas via PlanEstudioDB
            viz_filtered_mats = None
            if (viz_filtro_carrera != "Todas"
                    or viz_filtro_anio != "Todos"
                    or viz_filtro_cuatri != "Todos"):
                with next(get_session()) as session:
                    q = select(PlanEstudioDB.materia_codigo)
                    if viz_filtro_carrera != "Todas":
                        carrera_cod = viz_filtro_carrera.split(" - ")[0]
                        q = q.where(PlanEstudioDB.carrera_codigo == carrera_cod)
                    if viz_filtro_anio != "Todos":
                        q = q.where(PlanEstudioDB.anio_plan == int(viz_filtro_anio))
                    if viz_filtro_cuatri != "Todos":
                        if viz_filtro_cuatri == "Anual":
                            q = q.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            q = q.where(PlanEstudioDB.cuatrimestre_plan == viz_filtro_cuatri)
                    viz_filtered_mats = set(session.exec(q.distinct()).all())

            # --- Multiselect de materias ---
            with next(get_session()) as session:
                grid_data = build_schedule_grid(session, sel_id)

            # Materias presentes en el cronograma
            _viz_mats_en_schedule = set()
            for _blocks in grid_data.values():
                for _b in _blocks:
                    _viz_mats_en_schedule.add(_b.materia_codigo)

            # Intersectar con filtros de plan si aplican
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
        sel_edit_id = st.selectbox(
            "Seleccionar cronograma",
            options=list(schedule_options_edit.keys()),
            format_func=lambda x: schedule_options_edit[x],
            key="edit_schedule",
        )

        if sel_edit_id:
            # --- Filtros fila 1: carrera, año, cuatrimestre ---
            col_ef1, col_ef2, col_ef3 = st.columns(3)
            with col_ef1:
                edit_carrera_opts = ["Todas"] + [
                    f"{c.codigo} - {c.nombre}" for c in all_carreras
                ]
                edit_filtro_carrera = st.selectbox(
                    "Carrera", options=edit_carrera_opts, key="edit_filtro_carrera"
                )
            with col_ef2:
                edit_filtro_anio = st.selectbox(
                    "Año de cursada",
                    options=["Todos", 1, 2, 3, 4, 5, 6],
                    key="edit_filtro_anio",
                )
            with col_ef3:
                edit_filtro_cuatri = st.selectbox(
                    "Cuatrimestre",
                    options=["Todos", "1C", "2C", "Anual"],
                    key="edit_filtro_cuatri",
                )

            # --- Filtros fila 2: tipo de materia, excluir comunes ---
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

            # Determinar materias filtradas via PlanEstudioDB
            edit_filtered_mats = None
            if (edit_filtro_carrera != "Todas"
                    or edit_filtro_anio != "Todos"
                    or edit_filtro_cuatri != "Todos"):
                with next(get_session()) as session:
                    eq = select(PlanEstudioDB.materia_codigo)
                    if edit_filtro_carrera != "Todas":
                        e_carrera_cod = edit_filtro_carrera.split(" - ")[0]
                        eq = eq.where(PlanEstudioDB.carrera_codigo == e_carrera_cod)
                    if edit_filtro_anio != "Todos":
                        eq = eq.where(PlanEstudioDB.anio_plan == int(edit_filtro_anio))
                    if edit_filtro_cuatri != "Todos":
                        if edit_filtro_cuatri == "Anual":
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan.in_(["Anual", "anual"]))
                        else:
                            eq = eq.where(PlanEstudioDB.cuatrimestre_plan == edit_filtro_cuatri)
                    edit_filtered_mats = set(session.exec(eq.distinct()).all())

            # --- Selector de materia para agregar (con buscador) ---
            # Filtrar lista segun filtros de carrera/año/cuatrimestre
            if edit_filtered_mats is not None:
                mat_options_base = sorted(c for c in materias_map if c in edit_filtered_mats)
            else:
                mat_options_base = sorted(materias_map.keys())

            busqueda_mat = st.text_input(
                "🔍 Buscar materia por nombre o código",
                key="edit_buscar_materia",
                placeholder="Ej: algebra, F0301, programacion...",
            )

            if busqueda_mat.strip():
                termino = busqueda_mat.strip().lower()
                mat_options = [
                    c for c in mat_options_base
                    if termino in c.lower() or termino in materias_map[c].lower()
                ]
            else:
                mat_options = mat_options_base

            if mat_options:
                sel_mat_add = st.selectbox(
                    "Materia (para agregar al seleccionar un rango)",
                    options=mat_options,
                    format_func=lambda x: f"{materias_map[x]} — {x}",
                    key="edit_add_materia",
                )
            else:
                sel_mat_add = None
                if busqueda_mat.strip():
                    st.warning(f"No se encontraron materias para '{busqueda_mat}'")
                else:
                    st.info("No hay materias disponibles con los filtros actuales.")

            # --- Multiselect de materias ---
            with next(get_session()) as session:
                grid_data_full = build_schedule_grid(session, sel_edit_id)

            # Materias presentes en el cronograma
            _edit_mats_en_schedule = set()
            for _blocks in grid_data_full.values():
                for _b in _blocks:
                    _edit_mats_en_schedule.add(_b.materia_codigo)

            # Intersectar con filtros de plan si aplican
            _edit_mats_disponibles = _edit_mats_en_schedule
            if edit_filtered_mats is not None:
                _edit_mats_disponibles = _edit_mats_en_schedule & edit_filtered_mats

            _edit_mat_list = sorted(_edit_mats_disponibles, key=lambda c: materias_map.get(c, c))
            edit_materias_sel = st.multiselect(
                "Materias a mostrar",
                options=_edit_mat_list,
                default=_edit_mat_list,
                format_func=lambda x: f"{materias_map.get(x, x)} — {x}",
                key="edit_filtro_materias",
            )
            _edit_selected_set = set(edit_materias_sel) if edit_materias_sel else _edit_mats_disponibles

            st.divider()

            # --- Calendario editable ---
            grid_data = grid_data_full

            # Aplicar filtro de materias seleccionadas
            if grid_data:
                grid_data = {
                    dia: [b for b in blocks if b.materia_codigo in _edit_selected_set]
                    for dia, blocks in grid_data.items()
                }
                grid_data = {d: bs for d, bs in grid_data.items() if bs}

            # Aplicar filtros de tipo y comunes
            grid_data = _aplicar_filtro_tipo(grid_data, edit_filtro_tipo, edit_excluir_comunes)

            action = render_editable_schedule_calendar(
                grid_data, config, key="edit_cal",
            )

            # --- Procesar acciones ---
            if action is not None:
                if action.action == "move":
                    # Deduplicar: no re-procesar el mismo move tras rerun
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
                        mat_nombre = materias_map.get(action.materia_codigo, action.materia_codigo or "")
                        st.session_state["_edit_toast"] = (
                            f"{mat_nombre} movida a {action.dia} "
                            f"{action.hora_inicio.strftime('%H:%M')}-"
                            f"{action.hora_fin.strftime('%H:%M')}"
                        )
                        st.session_state["_edit_processed_move"] = move_key
                        st.rerun()

                elif action.action == "click":
                    # Deduplicar: no re-procesar el mismo click tras rerun
                    click_key = f"{action.entry_id}|{action.dia}|{action.hora_inicio}"
                    if st.session_state.get("_edit_processed_click") != click_key:
                        st.session_state["edit_pending_click"] = {
                            "entry_id": action.entry_id,
                            "materia": action.materia_codigo,
                            "dia": action.dia,
                            "hora_inicio": action.hora_inicio,
                            "hora_fin": action.hora_fin,
                            "_key": click_key,
                        }
                        _dialog_edit_entry()

                elif action.action == "select" and sel_mat_add:
                    # Deduplicar: no re-procesar el mismo select tras rerun
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
