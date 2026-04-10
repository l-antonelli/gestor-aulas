"""Gestion independiente de cronogramas de horarios.

Permite cargar, visualizar, editar y duplicar cronogramas sin necesidad
de asociarlos a un ciclo.  Luego desde Planes se puede seleccionar
un cronograma existente para generar un plan de cursada.
"""

import streamlit as st
from datetime import time
from sqlmodel import select, col, func

from src.database.connection import get_session, init_db
from src.database.models import (
    ScheduleDB, ScheduleEntryDB, MateriaDB, CicloDB, ConfiguracionHoraria,
    CarreraDB, PlanCarreraVersionDB, PlanEstudioDB,
)
from src.database.crud import ciclo_crud, get_or_create_config
from src.services.schedule_service import (
    create_schedule_standalone,
    get_all_schedules,
    get_schedule_entries,
    duplicate_schedule,
    delete_schedule,
    add_schedule_entry,
    update_schedule_entry,
    delete_schedule_entry,
    build_schedule_grid,
)
from src.services.plan_generation_service import generate_time_slots
from src.domain.types import DIAS_SEMANA

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

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}
materias_map = {m.codigo: m.nombre for m in all_materias}
carreras_map = {c.codigo: c.nombre for c in all_carreras}

PALETTE = [
    "#E3F2FD", "#FFF3E0", "#E8F5E9", "#FCE4EC",
    "#F3E5F5", "#E0F7FA", "#FFF9C4", "#F1F8E9",
    "#FFEBEE", "#E8EAF6", "#E0F2F1", "#FBE9E7",
]


# =============================================================================
# Helper: render schedule grid
# =============================================================================
def _render_schedule_grid(grid_data, config):
    """Renderizar grilla semanal a partir de build_schedule_grid output."""
    if not grid_data:
        st.info("El cronograma no tiene entradas.")
        return

    time_slots = generate_time_slots(config)
    if not time_slots:
        st.warning("No hay franjas horarias configuradas.")
        return

    dias_config = [d.strip() for d in config.dias_operativos.split(",") if d.strip()]
    dias_order = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
    active_dias = [d for d in dias_order if d in dias_config]
    if not active_dias:
        active_dias = [d for d in dias_order if d in grid_data]

    # Asignar colores por materia
    all_mat_codes = sorted({
        b.materia_codigo for blocks in grid_data.values() for b in blocks
    })
    mat_colors = {
        code: PALETTE[i % len(PALETTE)]
        for i, code in enumerate(all_mat_codes)
    }

    # Header
    header_cols = st.columns([1] + [2] * len(active_dias))
    with header_cols[0]:
        st.markdown("**Hora**")
    for idx, dia in enumerate(active_dias):
        with header_cols[idx + 1]:
            st.markdown(f"**{dia}**")

    # Filas por franja horaria
    for slot_start, slot_end in time_slots:
        row_cols = st.columns([1] + [2] * len(active_dias))
        with row_cols[0]:
            st.caption(slot_start.strftime("%H:%M"))

        for idx, dia in enumerate(active_dias):
            with row_cols[idx + 1]:
                day_blocks = grid_data.get(dia, [])
                overlapping = [
                    b for b in day_blocks
                    if b.hora_inicio < slot_end and b.hora_fin > slot_start
                ]
                for b in overlapping:
                    color = mat_colors.get(b.materia_codigo, "#E0E0E0")
                    st.markdown(
                        f'<div style="background-color:{color};'
                        f'padding:2px 6px;border-radius:4px;'
                        f'margin-bottom:2px;font-size:0.8em;">'
                        f'<b>{b.materia_codigo}</b><br>'
                        f'<span style="font-size:0.75em;">{b.materia_nombre}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

    # Leyenda
    st.divider()
    st.markdown("**Materias:**")
    n_cols = min(len(all_mat_codes), 4) or 1
    legend_cols = st.columns(n_cols)
    for i, code in enumerate(all_mat_codes):
        with legend_cols[i % n_cols]:
            nombre = next(
                (b.materia_nombre for blocks in grid_data.values()
                 for b in blocks if b.materia_codigo == code),
                code,
            )
            color = mat_colors[code]
            st.markdown(
                f'<div style="background-color:{color};'
                f'padding:2px 8px;border-radius:3px;margin-bottom:4px;'
                f'font-size:0.85em;">'
                f'<b>{code}</b> — {nombre}</div>',
                unsafe_allow_html=True,
            )


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
    st.subheader("Cargar nuevo cronograma")

    nombre = st.text_input("Nombre del cronograma", key="crono_nombre")

    ciclo_sel = st.selectbox(
        "Ciclo (opcional)",
        options=["(ninguno)"] + ciclo_ids,
        key="crono_ciclo",
    )
    ciclo_id_val = ciclo_sel if ciclo_sel != "(ninguno)" else None

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
            # --- Filtros ---
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

            st.divider()

            with next(get_session()) as session:
                grid_data = build_schedule_grid(session, sel_id)

            # Aplicar filtro de materias a la grilla
            if viz_filtered_mats is not None and grid_data:
                grid_data = {
                    dia: [b for b in blocks if b.materia_codigo in viz_filtered_mats]
                    for dia, blocks in grid_data.items()
                }
                # Quitar dias vacios
                grid_data = {d: bs for d, bs in grid_data.items() if bs}

            _render_schedule_grid(grid_data, config)


# =============================================================================
# Tab 4: Editar
# =============================================================================
with tab_editar:
    st.subheader("Editar entradas de cronograma")

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
            with next(get_session()) as session:
                entries = get_schedule_entries(session, sel_edit_id)

            if not entries:
                st.info("Este cronograma no tiene entradas.")
            else:
                # Agrupar por materia
                by_materia: dict[str, list] = {}
                for e in entries:
                    by_materia.setdefault(e.codigo_materia, []).append(e)

                dias_list = sorted(DIAS_SEMANA)

                for mat_code in sorted(by_materia.keys()):
                    mat_entries = by_materia[mat_code]
                    mat_nombre = materias_map.get(mat_code, mat_code)
                    with st.expander(f"**{mat_nombre}** ({mat_code}) — {len(mat_entries)} entrada(s)"):
                        for e in mat_entries:
                            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 1, 1])

                            with c1:
                                new_dia = st.selectbox(
                                    "Dia",
                                    options=dias_list,
                                    index=dias_list.index(e.dia) if e.dia in dias_list else 0,
                                    key=f"dia_{e.id}",
                                )
                            with c2:
                                new_inicio = st.time_input(
                                    "Inicio",
                                    value=e.hora_inicio,
                                    key=f"ini_{e.id}",
                                )
                            with c3:
                                new_fin = st.time_input(
                                    "Fin",
                                    value=e.hora_fin,
                                    key=f"fin_{e.id}",
                                )
                            with c4:
                                if st.button("Guardar", key=f"save_{e.id}"):
                                    cambios = {}
                                    if new_dia != e.dia:
                                        cambios["dia"] = new_dia
                                    if new_inicio != e.hora_inicio:
                                        cambios["hora_inicio"] = new_inicio
                                    if new_fin != e.hora_fin:
                                        cambios["hora_fin"] = new_fin
                                    if cambios:
                                        with next(get_session()) as session:
                                            update_schedule_entry(session, e.id, **cambios)
                                        st.success("Actualizado")
                                        st.rerun()
                                    else:
                                        st.info("Sin cambios")
                            with c5:
                                if st.button("X", key=f"del_entry_{e.id}"):
                                    with next(get_session()) as session:
                                        delete_schedule_entry(session, e.id)
                                    st.rerun()

            # Agregar nueva entrada
            st.divider()
            st.markdown("**Agregar entrada**")
            ac1, ac2, ac3, ac4, ac5 = st.columns([3, 2, 2, 2, 1])
            with ac1:
                mat_options = sorted(materias_map.keys())
                new_mat = st.selectbox(
                    "Materia",
                    options=mat_options,
                    format_func=lambda x: f"{x} — {materias_map[x]}",
                    key="add_materia",
                )
            with ac2:
                add_dia = st.selectbox("Dia", options=sorted(DIAS_SEMANA), key="add_dia")
            with ac3:
                add_inicio = st.time_input("Inicio", value=time(8, 0), key="add_inicio")
            with ac4:
                add_fin = st.time_input("Fin", value=time(10, 0), key="add_fin")
            with ac5:
                st.write("")  # spacer
                if st.button("Agregar", key="add_entry_btn"):
                    with next(get_session()) as session:
                        add_schedule_entry(
                            session, sel_edit_id, new_mat, add_dia, add_inicio, add_fin
                        )
                    st.success("Entrada agregada")
                    st.rerun()
