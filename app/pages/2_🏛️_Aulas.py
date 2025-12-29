"""Gestión de Aulas."""

import streamlit as st
from src.database.connection import get_session
from src.database.models import AulaDB
from src.database.crud import aula_crud

st.set_page_config(page_title="Aulas", page_icon="🏛️", layout="wide")
st.title("🏛️ Gestión de Aulas")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nueva Aula"])

with tab_list:
    with next(get_session()) as session:
        aulas = aula_crud.get_all(session)
    
    if not aulas:
        st.info("No hay aulas registradas.")
    else:
        data = [
            {
                "Código": a.codigo,
                "Capacidad": a.capacidad,
                "Tipo": a.tipo,
            }
            for a in aulas
        ]
        st.dataframe(data, use_container_width=True, hide_index=True)
        
        st.subheader("Eliminar Aula")
        codigo_delete = st.selectbox(
            "Seleccionar aula a eliminar",
            options=[a.codigo for a in aulas],
            key="delete_aula"
        )
        if st.button("🗑️ Eliminar", type="secondary"):
            with next(get_session()) as session:
                if aula_crud.delete(session, codigo_delete):
                    st.success(f"Aula {codigo_delete} eliminada")
                    st.rerun()

with tab_create:
    with st.form("create_aula"):
        codigo = st.text_input("Código", placeholder="AULA-101")
        capacidad = st.number_input("Capacidad", min_value=1, value=50)
        tipo = st.selectbox("Tipo", options=["teorica", "laboratorio", "taller"])
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not codigo:
                st.error("Código es obligatorio")
            else:
                aula = AulaDB(codigo=codigo, capacidad=capacidad, tipo=tipo)
                try:
                    with next(get_session()) as session:
                        aula_crud.create(session, aula)
                    st.success(f"Aula '{codigo}' creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear aula: {e}")
