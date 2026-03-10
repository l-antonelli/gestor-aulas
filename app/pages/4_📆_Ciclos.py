"""Gestion de Ciclos Lectivos - Creacion de ciclos y dictados."""

import streamlit as st
from datetime import date
from sqlmodel import select
from src.database.connection import get_session, init_db
from src.database.models import CicloDB, CicloPlanVersionDB, PlanCarreraVersionDB
from src.database.crud import ciclo_crud
from src.services.dictado_service import (
    create_dictados_for_ciclo,
    get_dictados_for_ciclo,
)
from src.services.crud_services import carrera_service

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

tab_ciclos, tab_dictados = st.tabs([
    "📋 Ciclos", "📚 Dictados"
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

    # Get all plan versions for the multi-select (outside form for dynamic content)
    with next(get_session()) as session:
        all_carreras = carrera_service.get_all(session)
        all_versions = []
        for c in all_carreras:
            versions = carrera_service.get_plan_versions(session, c.codigo)
            for v in versions:
                all_versions.append(v)

    version_options = {v.id: f"{v.carrera_codigo} - {v.nombre}" for v in all_versions}
    # Default: latest version per carrera
    latest_by_carrera = {}
    for v in all_versions:
        if v.carrera_codigo not in latest_by_carrera:
            latest_by_carrera[v.carrera_codigo] = v.id
        else:
            # Keep the one with later fecha_creacion
            existing = next(vv for vv in all_versions if vv.id == latest_by_carrera[v.carrera_codigo])
            if v.fecha_creacion >= existing.fecha_creacion:
                latest_by_carrera[v.carrera_codigo] = v.id
    default_version_ids = list(latest_by_carrera.values())

    with st.form("create_ciclo"):
        col1, col2 = st.columns(2)

        with col1:
            anio = st.number_input("Anio", min_value=2020, max_value=2100, value=date.today().year)
            numero = st.selectbox("Cuatrimestre", options=[1, 2], format_func=lambda x: f"{x}C")

        with col2:
            fecha_inicio = st.date_input("Fecha de inicio")
            fecha_fin = st.date_input("Fecha de fin")

        descripcion = st.text_input("Descripcion (opcional)", placeholder="Ej: Cursado regular")

        # Plan version selection
        if version_options:
            selected_versions = st.multiselect(
                "Versiones de plan a asignar",
                options=list(version_options.keys()),
                default=default_version_ids,
                format_func=lambda x: version_options[x],
                help="Seleccione las versiones de plan de estudio que aplican a este ciclo. "
                     "Los dictados se crearan para las materias de estas versiones.",
            )
        else:
            selected_versions = []
            st.warning("No hay versiones de plan disponibles. Cree planes de estudio primero.")

        submitted = st.form_submit_button("Guardar", type="primary")

        if submitted:
            ciclo_id = f"{anio}-{numero}C"

            if fecha_fin <= fecha_inicio:
                st.error("La fecha de fin debe ser posterior a la de inicio")
            elif not selected_versions:
                st.error("Debe seleccionar al menos una version de plan")
            else:
                ciclo = CicloDB(
                    id=ciclo_id,
                    anio=anio,
                    numero=numero,
                    fecha_inicio=fecha_inicio,
                    fecha_fin=fecha_fin,
                    descripcion=descripcion or "",
                )
                try:
                    with next(get_session()) as session:
                        ciclo_crud.create(session, ciclo)
                        # Create CicloPlanVersion links
                        for vid in selected_versions:
                            link = CicloPlanVersionDB(ciclo_id=ciclo_id, plan_version_id=vid)
                            session.add(link)
                        session.commit()
                    st.success(f"Ciclo '{ciclo_id}' creado con {len(selected_versions)} version(es) de plan")
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
            # Show assigned plan versions
            with next(get_session()) as session:
                assigned_versions = session.exec(
                    select(PlanCarreraVersionDB)
                    .join(CicloPlanVersionDB, PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id)
                    .where(CicloPlanVersionDB.ciclo_id == sel_ciclo_dict)
                ).all()

            if assigned_versions:
                st.markdown("**Versiones de plan asignadas:**")
                for v in assigned_versions:
                    st.caption(f"- {v.carrera_codigo}: {v.nombre}")
            else:
                st.warning(
                    "Este ciclo no tiene versiones de plan asignadas. "
                    "Los dictados no se pueden crear sin versiones asignadas."
                )

            st.divider()

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


