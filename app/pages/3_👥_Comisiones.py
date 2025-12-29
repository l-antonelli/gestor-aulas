"""Gestión de Comisiones."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import ComisionDB, MateriaDB
from src.database.crud import comision_crud, materia_crud

st.set_page_config(page_title="Comisiones", page_icon="👥", layout="wide")
st.title("👥 Gestión de Comisiones")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Comisión"])

with tab_list:
    with next(get_session()) as session:
        comisiones = comision_crud.get_all(session)
        # Eager load materia names
        comisiones_data = []
        for c in comisiones:
            materia = materia_crud.get(session, c.materia_codigo)
            comisiones_data.append({
                "ID": c.id,
                "Materia": f"{c.materia_codigo} - {materia.nombre if materia else 'N/A'}",
                "Número": c.numero,
                "Cupo": c.cupo,
                "Descripción": c.descripcion or "-",
            })
    
    if not comisiones_data:
        st.info("No hay comisiones registradas.")
    else:
        st.dataframe(comisiones_data, use_container_width=True, hide_index=True)
        
        st.subheader("Eliminar Comisión")
        id_delete = st.selectbox(
            "Seleccionar comisión a eliminar",
            options=[c.id for c in comisiones],
            key="delete_comision"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if comision_crud.delete(session, id_delete):
                    st.success(f"Comisión {id_delete} eliminada")
                    st.rerun()

with tab_create:
    with next(get_session()) as session:
        materias = materia_crud.get_all(session)
    
    if not materias:
        st.warning("Primero debes crear al menos una materia.")
    else:
        with st.form("create_comision"):
            materia_codigo = st.selectbox(
                "Materia",
                options=[m.codigo for m in materias],
                format_func=lambda x: f"{x} - {next((m.nombre for m in materias if m.codigo == x), '')}"
            )
            numero = st.number_input("Número de comisión", min_value=1, value=1)
            cupo = st.number_input("Cupo", min_value=1, value=30)
            descripcion = st.text_input("Descripción (opcional)", placeholder="Turno mañana")
            
            submitted = st.form_submit_button("💾 Guardar", type="primary")
            
            if submitted:
                comision_id = f"{materia_codigo}-C{numero}"
                comision = ComisionDB(
                    id=comision_id,
                    materia_codigo=materia_codigo,
                    nombre=f"Comisión {numero}",
                    numero=numero,
                    cupo=cupo,
                    descripcion=descripcion
                )
                try:
                    with next(get_session()) as session:
                        comision_crud.create(session, comision)
                    st.success(f"Comisión '{comision_id}' creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear comisión: {e}")
