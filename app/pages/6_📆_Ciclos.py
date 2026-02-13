"""Gestión de Ciclos Lectivos."""

import streamlit as st
from datetime import date
from src.database.connection import get_session
from src.database.models import CicloDB
from src.database.crud import ciclo_crud

st.set_page_config(page_title="Ciclos", page_icon="📆", layout="wide")
st.title("📆 Gestión de Ciclos Lectivos")

tab_list, tab_create = st.tabs(["📋 Listado", "➕ Nuevo Ciclo"])

with tab_list:
    with next(get_session()) as session:
        ciclos = ciclo_crud.get_all(session, limit=100)
        ciclos_data = []
        for c in ciclos:
            ciclos_data.append({
                "ID": c.id,
                "Año": c.anio,
                "Cuatrimestre": f"{c.numero}°",
                "Inicio": c.fecha_inicio.strftime("%d/%m/%Y"),
                "Fin": c.fecha_fin.strftime("%d/%m/%Y"),
                "Descripción": c.descripcion,
            })
    
    if not ciclos_data:
        st.info("No hay ciclos registrados. Crea uno en la pestaña 'Nuevo Ciclo'.")
    else:
        st.dataframe(ciclos_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(ciclos_data)} ciclos")
        
        # Delete section
        st.divider()
        st.subheader("Eliminar Ciclo")
        col1, col2 = st.columns([3, 1])
        with col1:
            ciclo_delete = st.selectbox(
                "Seleccionar ciclo a eliminar",
                options=[c.id for c in ciclos],
                key="delete_ciclo"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                with next(get_session()) as session:
                    if ciclo_crud.delete(session, ciclo_delete):
                        st.success(f"Ciclo {ciclo_delete} eliminado")
                        st.rerun()

with tab_create:
    with st.form("create_ciclo"):
        col1, col2 = st.columns(2)
        
        with col1:
            anio = st.number_input("Año", min_value=2020, max_value=2100, value=date.today().year)
            numero = st.selectbox("Cuatrimestre", options=[1, 2], format_func=lambda x: f"{x}° Cuatrimestre")
        
        with col2:
            fecha_inicio = st.date_input("Fecha de inicio")
            fecha_fin = st.date_input("Fecha de fin")
        
        descripcion = st.text_input("Descripción (opcional)", placeholder="Ej: Cursado regular")
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
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
