"""Gestion de Ciclos Lectivos - Hub del workflow de planificacion."""

import streamlit as st
from datetime import date
from src.database.connection import get_session, init_db
from src.database.models import CicloDB
from src.database.crud import ciclo_crud
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
)
from src.services.schedule_service import (
    create_schedule_from_file,
    get_schedules_for_ciclo,
    get_schedule_entries,
)
from src.services.plan_generation_service import (
    generate_plan_from_schedule,
    activate_plan,
)

init_db()

st.set_page_config(page_title="Ciclos", page_icon="📆", layout="wide")
st.title("📆 Gestion de Ciclos Lectivos")

# =============================================================================
# Ciclo selector (shared across tabs)
# =============================================================================
with next(get_session()) as session:
    ciclos = ciclo_crud.get_all(session, limit=100)

ciclo_ids = [c.id for c in ciclos]
ciclos_map = {c.id: c for c in ciclos}

tab_ciclos, tab_dictados, tab_schedules, tab_planes = st.tabs([
    "📋 Ciclos", "📚 Dictados", "📥 Schedules", "📊 Planes"
])

# =============================================================================
# Tab 1: Ciclos - List + Create + Delete
# =============================================================================
with tab_ciclos:
    st.subheader("Ciclos Registrados")

    if not ciclos:
        st.info("No hay ciclos registrados. Crea uno abajo.")
    else:
        ciclos_data = []
        for c in ciclos:
            ciclos_data.append({
                "ID": c.id,
                "Anio": c.anio,
                "Cuatrimestre": f"{c.numero}C",
                "Inicio": c.fecha_inicio.strftime("%d/%m/%Y"),
                "Fin": c.fecha_fin.strftime("%d/%m/%Y"),
                "Descripcion": c.descripcion,
            })
        st.dataframe(ciclos_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(ciclos_data)} ciclos")

        st.divider()
        st.subheader("Eliminar Ciclo")
        col1, col2 = st.columns([3, 1])
        with col1:
            ciclo_delete = st.selectbox(
                "Seleccionar ciclo a eliminar",
                options=ciclo_ids,
                key="delete_ciclo"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("Eliminar", type="secondary", key="btn_delete_ciclo"):
                with next(get_session()) as session:
                    if ciclo_crud.delete(session, ciclo_delete):
                        st.success(f"Ciclo {ciclo_delete} eliminado")
                        st.rerun()

    st.divider()
    st.subheader("Nuevo Ciclo")

    with st.form("create_ciclo"):
        col1, col2 = st.columns(2)

        with col1:
            anio = st.number_input("Anio", min_value=2020, max_value=2100, value=date.today().year)
            numero = st.selectbox("Cuatrimestre", options=[1, 2], format_func=lambda x: f"{x}C")

        with col2:
            fecha_inicio = st.date_input("Fecha de inicio")
            fecha_fin = st.date_input("Fecha de fin")

        descripcion = st.text_input("Descripcion (opcional)", placeholder="Ej: Cursado regular")

        submitted = st.form_submit_button("Guardar", type="primary")

        if submitted:
            ciclo_id = f"{anio}-{numero}C"

            if fecha_fin <= fecha_inicio:
                st.error("La fecha de fin debe ser posterior a la de inicio")
            else:
                ciclo = CicloDB(
                    id=ciclo_id,
                    anio=anio,
                    numero=numero,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    descripcion=descripcion or ""
                )
                try:
                    with next(get_session()) as session:
                        ciclo_crud.create(session, ciclo)
                    st.success(f"Ciclo '{ciclo_id}' creado")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear ciclo: {e}")


# =============================================================================
# Tab 2: Dictados - Create dictados for a ciclo
# =============================================================================
with tab_dictados:
    st.subheader("Dictados por Ciclo")

    if not ciclo_ids:
        st.info("Crea un ciclo primero en la pestana 'Ciclos'.")
    else:
        sel_ciclo_dict = st.selectbox(
            "Seleccionar Ciclo", options=ciclo_ids, key="sel_ciclo_dictados"
        )

        if sel_ciclo_dict:
            with next(get_session()) as session:
                dictados = get_dictados_for_ciclo(session, sel_ciclo_dict)

            if dictados:
                st.success(f"{len(dictados)} dictados existentes para {sel_ciclo_dict}")
                dict_data = []
                for d in dictados:
                    dict_data.append({
                        "Codigo": d.dictado_codigo,
                        "Materia": d.materia_codigo,
                        "Inicio": str(d.inicio_dictado) if d.inicio_dictado else "-",
                        "Fin": str(d.fin_dictado) if d.fin_dictado else "Pendiente",
                        "Activo": "Si" if d.activo else "No",
                    })
                st.dataframe(dict_data, use_container_width=True, hide_index=True)
            else:
                st.info("No hay dictados para este ciclo.")

            if st.button("Crear Dictados", type="primary", key="btn_create_dictados"):
                with next(get_session()) as session:
                    result = create_dictados_for_ciclo(session, sel_ciclo_dict)

                if result.errors:
                    for err in result.errors:
                        st.error(err)
                else:
                    msg_parts = []
                    if result.created:
                        msg_parts.append(f"{result.created} creados")
                    if result.linked:
                        msg_parts.append(f"{result.linked} vinculados (anuales)")
                    if result.skipped:
                        msg_parts.append(f"{result.skipped} ya existentes")
                    st.success(f"Dictados: {', '.join(msg_parts)}")
                    st.rerun()


# =============================================================================
# Tab 3: Schedules - Upload horario files
# =============================================================================
with tab_schedules:
    st.subheader("Schedules (Horarios cargados)")

    if not ciclo_ids:
        st.info("Crea un ciclo primero.")
    else:
        sel_ciclo_sched = st.selectbox(
            "Seleccionar Ciclo", options=ciclo_ids, key="sel_ciclo_schedules"
        )

        if sel_ciclo_sched:
            # Show existing schedules
            with next(get_session()) as session:
                schedules = get_schedules_for_ciclo(session, sel_ciclo_sched)

            if schedules:
                st.markdown(f"**{len(schedules)} schedule(s) existentes:**")
                for s in schedules:
                    with st.expander(f"{s.nombre} ({s.fecha_upload}) - {s.source_filename}"):
                        with next(get_session()) as session:
                            entries = get_schedule_entries(session, s.id)
                        if entries:
                            entry_data = [{
                                "Materia": e.codigo_materia,
                                "Dia": e.dia,
                                "Inicio": e.hora_inicio.strftime("%H:%M"),
                                "Fin": e.hora_fin.strftime("%H:%M"),
                            } for e in entries]
                            st.dataframe(entry_data, use_container_width=True, hide_index=True)
                            st.caption(f"{len(entries)} entries")
                        else:
                            st.caption("Sin entries")

            # Upload new schedule
            st.divider()
            st.markdown("**Cargar nuevo schedule**")
            nombre_sched = st.text_input(
                "Nombre del schedule",
                value=f"Horarios {sel_ciclo_sched}",
                key="schedule_nombre"
            )
            uploaded_file = st.file_uploader(
                "Archivo CSV o Excel",
                type=["csv", "xlsx", "xls"],
                key="schedule_file_upload"
            )

            if uploaded_file is not None:
                if st.button("Cargar Schedule", type="primary", key="btn_upload_schedule"):
                    with next(get_session()) as session:
                        result = create_schedule_from_file(
                            session, sel_ciclo_sched, nombre_sched, uploaded_file
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
                            f"Schedule '{nombre_sched}' creado con "
                            f"{result.entries_created} entries"
                        )
                        st.rerun()


# =============================================================================
# Tab 4: Planes - Generate and activate plans
# =============================================================================
with tab_planes:
    st.subheader("Planes de Cursada")

    if not ciclo_ids:
        st.info("Crea un ciclo primero.")
    else:
        sel_ciclo_plan = st.selectbox(
            "Seleccionar Ciclo", options=ciclo_ids, key="sel_ciclo_planes"
        )

        if sel_ciclo_plan:
            # Show existing plans
            with next(get_session()) as session:
                from sqlmodel import select
                from src.database.models import PlanificacionCursadaDB
                planes = session.exec(
                    select(PlanificacionCursadaDB)
                    .where(PlanificacionCursadaDB.ciclo_id == sel_ciclo_plan)
                ).all()

            if planes:
                for p in planes:
                    status = "ACTIVO" if p.activo else "inactivo"
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.markdown(f"**{p.nombre}** [{status}] - {p.descripcion or 'Sin descripcion'}")
                        st.caption(f"ID: {p.id} | Schedule: {p.schedule_id or 'N/A'}")
                    with col2:
                        if not p.activo:
                            if st.button("Activar", key=f"activate_{p.id}"):
                                with next(get_session()) as session:
                                    activate_plan(session, p.id)
                                st.success(f"Plan '{p.nombre}' activado")
                                st.rerun()
            else:
                st.info("No hay planes para este ciclo.")

            # Generate new plan
            st.divider()
            st.markdown("**Generar nuevo plan desde schedule**")

            with next(get_session()) as session:
                schedules = get_schedules_for_ciclo(session, sel_ciclo_plan)

            if not schedules:
                st.info("Primero carga un schedule en la pestana 'Schedules'.")
            else:
                sched_options = {s.id: f"{s.nombre} ({s.fecha_upload})" for s in schedules}
                sel_schedule = st.selectbox(
                    "Schedule base",
                    options=list(sched_options.keys()),
                    format_func=lambda x: sched_options[x],
                    key="sel_schedule_for_plan"
                )

                plan_nombre = st.text_input(
                    "Nombre del plan",
                    value=f"Plan {sel_ciclo_plan}",
                    key="plan_nombre"
                )

                if st.button("Generar Plan", type="primary", key="btn_generate_plan"):
                    with next(get_session()) as session:
                        result = generate_plan_from_schedule(
                            session, sel_schedule, plan_nombre, sel_ciclo_plan
                        )

                    if result.errors:
                        for err in result.errors:
                            st.error(err)

                    if result.comision_flags:
                        st.info("Notas sobre derivacion de comisiones:")
                        for flag in result.comision_flags:
                            st.text(f"  - {flag}")

                    if result.plan:
                        st.success(
                            f"Plan '{plan_nombre}' generado: "
                            f"{result.comisiones_created} comisiones, "
                            f"{result.horarios_created} horarios"
                        )
                        st.rerun()
