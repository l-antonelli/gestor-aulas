"""Gestión de Materias."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import MateriaDB
from src.database.crud import materia_crud

st.set_page_config(page_title="Materias", page_icon="📚", layout="wide")
st.title("📚 Gestión de Materias")

# Tabs for different operations
tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Materia"])

with tab_list:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session)
    
    if not materias:
        st.info("No hay materias registradas. Crea una en la pestaña 'Nueva Materia'.")
    else:
        # Display as table
        data = [
            {
                "Código": m.codigo,
                "Nombre": m.nombre,
                "Cupo": m.cupo,
                "Horas Semanales": m.horas_semanales,
            }
            for m in materias
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        
        # Delete section
        st.subheader("Eliminar Materia")
        codigo_delete = st.selectbox(
            "Seleccionar materia a eliminar",
            options=[m.codigo for m in materias],
            key="delete_materia"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if materia_crud.delete(session, codigo_delete):
                    st.success(f"Materia {codigo_delete} eliminada")
                    st.rerun()

with tab_create:
    with st.form("create_materia"):
        codigo = st.text_input("Código", placeholder="MAT101")
        nombre = st.text_input("Nombre", placeholder="Análisis Matemático I")
        cupo = st.number_input("Cupo máximo", min_value=1, value=100)
        horas = st.number_input("Horas semanales", min_value=1, value=6)
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not codigo or not nombre:
                st.error("Código y nombre son obligatorios")
            else:
                materia = MateriaDB(
                    codigo=codigo,
                    nombre=nombre,
                    cupo=cupo,
                    horas_semanales=horas
                )
                try:
                    with next(get_session()) as session:
                        materia_crud.create(session, materia)
                    st.success(f"Materia '{nombre}' creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear materia: {e}")
