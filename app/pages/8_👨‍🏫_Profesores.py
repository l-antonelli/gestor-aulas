"""Gestión de Profesores."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import ProfesorDB
from src.database.crud import profesor_crud

st.set_page_config(page_title="Profesores", page_icon="👨‍🏫", layout="wide")
st.title("👨‍🏫 Gestión de Profesores")

tab_list, tab_create, tab_edit = st.tabs(["📋 Listado", "➕ Nuevo Profesor", "✏️ Editar"])

with tab_list:
    with next(get_session()) as session:
        profesores = profesor_crud.get_all(session, limit=500)
    
    if not profesores:
        st.info("No hay profesores registrados.")
    else:
        data = [
            {
                "ID": p.id,
                "Nombre": p.nombre,
                "Email": p.email or "-",
                "DNI": p.dni or "-",
            }
            for p in profesores
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(profesores)} profesores")
        
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            id_delete = st.selectbox(
                "Eliminar profesor",
                options=[p.id for p in profesores],
                format_func=lambda x: f"{x} - {next((p.nombre for p in profesores if p.id == x), '')}"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar"):
                with next(get_session()) as session:
                    profesor_crud.delete(session, id_delete)
                st.rerun()

with tab_create:
    with st.form("create_profesor"):
        col1, col2 = st.columns(2)
        with col1:
            prof_id = st.text_input("ID", placeholder="PROF-001")
            nombre = st.text_input("Nombre completo", placeholder="Juan Pérez")
        with col2:
            email = st.text_input("Email", placeholder="jperez@fceia.unr.edu.ar")
            dni = st.text_input("DNI (opcional)", placeholder="12345678")
        
        if st.form_submit_button("💾 Guardar", type="primary"):
            if not prof_id or not nombre:
                st.error("ID y nombre son obligatorios")
            else:
                profesor = ProfesorDB(
                    id=prof_id,
                    nombre=nombre,
                    email=email,
                    dni=dni
                )
                try:
                    with next(get_session()) as session:
                        profesor_crud.create(session, profesor)
                    st.success(f"Profesor '{nombre}' creado")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

with tab_edit:
    with next(get_session()) as session:
        profesores = profesor_crud.get_all(session, limit=500)
    
    if not profesores:
        st.info("No hay profesores para editar.")
    else:
        id_edit = st.selectbox(
            "Seleccionar profesor",
            options=[p.id for p in profesores],
            format_func=lambda x: f"{x} - {next((p.nombre for p in profesores if p.id == x), '')}"
        )
        prof_sel = next((p for p in profesores if p.id == id_edit), None)
        
        if prof_sel:
            with st.form("edit_profesor"):
                st.text_input("ID", value=prof_sel.id, disabled=True)
                col1, col2 = st.columns(2)
                with col1:
                    nombre = st.text_input("Nombre", value=prof_sel.nombre)
                with col2:
                    email = st.text_input("Email", value=prof_sel.email or "")
                    dni = st.text_input("DNI", value=prof_sel.dni or "")
                
                if st.form_submit_button("💾 Guardar Cambios", type="primary"):
                    with next(get_session()) as session:
                        p = session.get(ProfesorDB, id_edit)
                        if p:
                            p.nombre = nombre
                            p.email = email
                            p.dni = dni
                            session.add(p)
                            session.commit()
                            st.success("Profesor actualizado")
                            st.rerun()
