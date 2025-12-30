"""Gestión de Carreras."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import CarreraDB
from src.database.crud import carrera_crud

st.set_page_config(page_title="Carreras", page_icon="🎓", layout="wide")
st.title("🎓 Gestión de Carreras")

tab_list, tab_create, tab_edit = st.tabs(["📋 Listado", "➕ Nueva Carrera", "✏️ Editar"])

with tab_list:
    with next(get_session()) as session:
        carreras = carrera_crud.get_all(session, limit=100)
    
    if not carreras:
        st.info("No hay carreras registradas.")
    else:
        data = [
            {
                "Código": c.codigo,
                "Nombre": c.nombre,
                "Título": c.titulo_otorgado,
                "Duración (años)": c.duracion_anios,
            }
            for c in carreras
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        
        st.divider()
        col1, col2 = st.columns([3, 1])
        with col1:
            codigo_delete = st.selectbox("Eliminar carrera", options=[c.codigo for c in carreras])
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar"):
                with next(get_session()) as session:
                    carrera_crud.delete(session, codigo_delete)
                st.rerun()

with tab_create:
    with st.form("create_carrera"):
        codigo = st.text_input("Código", placeholder="ING-ELECT")
        nombre = st.text_input("Nombre", placeholder="Ingeniería Electrónica")
        titulo = st.text_input("Título otorgado", placeholder="Ingeniero/a Electrónico/a")
        duracion = st.number_input("Duración (años)", min_value=1, max_value=10, value=5)
        
        if st.form_submit_button("💾 Guardar", type="primary"):
            if not codigo or not nombre:
                st.error("Código y nombre son obligatorios")
            else:
                carrera = CarreraDB(
                    codigo=codigo,
                    nombre=nombre,
                    titulo_otorgado=titulo,
                    duracion_anios=duracion
                )
                try:
                    with next(get_session()) as session:
                        carrera_crud.create(session, carrera)
                    st.success(f"Carrera '{nombre}' creada")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")

with tab_edit:
    with next(get_session()) as session:
        carreras = carrera_crud.get_all(session, limit=100)
    
    if not carreras:
        st.info("No hay carreras para editar.")
    else:
        codigo_edit = st.selectbox("Seleccionar carrera", options=[c.codigo for c in carreras])
        carrera_sel = next((c for c in carreras if c.codigo == codigo_edit), None)
        
        if carrera_sel:
            with st.form("edit_carrera"):
                st.text_input("Código", value=carrera_sel.codigo, disabled=True)
                nombre = st.text_input("Nombre", value=carrera_sel.nombre)
                titulo = st.text_input("Título otorgado", value=carrera_sel.titulo_otorgado)
                duracion = st.number_input("Duración (años)", min_value=1, max_value=10, value=carrera_sel.duracion_anios)
                
                if st.form_submit_button("💾 Guardar Cambios", type="primary"):
                    with next(get_session()) as session:
                        c = session.get(CarreraDB, codigo_edit)
                        if c:
                            c.nombre = nombre
                            c.titulo_otorgado = titulo
                            c.duracion_anios = duracion
                            session.add(c)
                            session.commit()
                            st.success("Carrera actualizada")
                            st.rerun()
