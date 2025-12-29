"""Gestión de Alumnos."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import AlumnoDB
from src.database.crud import alumno_crud

st.set_page_config(page_title="Alumnos", page_icon="🎓", layout="wide")
st.title("🎓 Gestión de Alumnos")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nuevo Alumno"])

with tab_list:
    with next(get_session()) as session:
        alumnos = alumno_crud.get_all(session)
    
    if not alumnos:
        st.info("No hay alumnos registrados.")
    else:
        data = [
            {
                "Legajo": a.legajo,
                "Nombre": a.nombre,
                "Email": a.email,
                "DNI": a.dni,
            }
            for a in alumnos
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        
        st.subheader("Eliminar Alumno")
        legajo_delete = st.selectbox(
            "Seleccionar alumno a eliminar",
            options=[a.legajo for a in alumnos],
            format_func=lambda x: f"{x} - {next((a.nombre for a in alumnos if a.legajo == x), '')}",
            key="delete_alumno"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if alumno_crud.delete(session, legajo_delete):
                    st.success(f"Alumno {legajo_delete} eliminado")
                    st.rerun()

with tab_create:
    with st.form("create_alumno"):
        legajo = st.text_input("Legajo", placeholder="A-12345")
        nombre = st.text_input("Nombre completo", placeholder="Juan Pérez")
        email = st.text_input("Email", placeholder="jperez@fceia.unr.edu.ar")
        dni = st.text_input("DNI", placeholder="12345678", max_chars=8)
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not all([legajo, nombre, email, dni]):
                st.error("Todos los campos son obligatorios")
            elif len(dni) < 7:
                st.error("El DNI debe tener al menos 7 dígitos")
            else:
                alumno = AlumnoDB(
                    legajo=legajo,
                    nombre=nombre,
                    email=email,
                    dni=dni
                )
                try:
                    with next(get_session()) as session:
                        alumno_crud.create(session, alumno)
                    st.success(f"Alumno '{nombre}' creado exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear alumno: {e}")
