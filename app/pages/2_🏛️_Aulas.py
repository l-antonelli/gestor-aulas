"""Gestión de Aulas."""

import streamlit as st
import uuid
from src.database.connection import get_session
from src.database.models import AulaDB
from src.database.crud import aula_crud

st.set_page_config(page_title="Aulas", page_icon="🏛️", layout="wide")
st.title("🏛️ Gestión de Aulas")

TIPOS_AULA = ["teorica", "laboratorio", "anfiteatro", "practica"]
SEDES = ["SEDE-PELLEGRINI", "CIVIL-ECA", "IMAE", "ETA", "REACTOR", "MEC"]

tab_list, tab_create, tab_edit = st.tabs(["📋 Listado", "➕ Nueva Aula", "✏️ Editar"])

# =============================================================================
# Tab 1: Listado
# =============================================================================
with tab_list:
    with next(get_session()) as session:
        aulas = aula_crud.get_all(session, limit=500)
    
    if not aulas:
        st.info("No hay aulas registradas.")
    else:
        # Group by sede
        sedes_data = {}
        for a in aulas:
            if a.sede not in sedes_data:
                sedes_data[a.sede] = []
            sedes_data[a.sede].append(a)
        
        # Filter by sede
        sede_filter = st.selectbox(
            "Filtrar por sede",
            options=["Todas"] + list(sedes_data.keys()),
            key="filter_sede"
        )
        
        if sede_filter == "Todas":
            aulas_filtered = aulas
        else:
            aulas_filtered = sedes_data.get(sede_filter, [])
        
        data = [
            {
                "ID": a.id,
                "Sede": a.sede,
                "Nombre": a.nombre,
                "Capacidad": a.capacidad,
                "Tipo": a.tipo,
                "Descripción": a.descripcion or "-",
            }
            for a in aulas_filtered
        ]
        data.sort(key=lambda x: (x["Sede"], x["Nombre"]))
        
        st.dataframe(data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(aulas_filtered)} aulas")
        
        # Delete section
        st.divider()
        st.subheader("Eliminar Aula")
        col1, col2 = st.columns([3, 1])
        with col1:
            id_delete = st.selectbox(
                "Seleccionar aula a eliminar",
                options=[a.id for a in aulas],
                format_func=lambda x: f"{x}",
                key="delete_aula"
            )
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary"):
                with next(get_session()) as session:
                    if aula_crud.delete(session, id_delete):
                        st.success(f"Aula {id_delete} eliminada")
                        st.rerun()

# =============================================================================
# Tab 2: Crear
# =============================================================================
with tab_create:
    with st.form("create_aula"):
        col1, col2 = st.columns(2)
        
        with col1:
            sede = st.selectbox("Sede", options=SEDES)
            nombre = st.text_input("Nombre", placeholder="AULA 01")
            capacidad = st.number_input("Capacidad", min_value=1, value=50)
        
        with col2:
            tipo = st.selectbox("Tipo", options=TIPOS_AULA)
            descripcion = st.text_area("Descripción (opcional)", placeholder="Notas adicionales...")
        
        submitted = st.form_submit_button("💾 Guardar", type="primary")
        
        if submitted:
            if not nombre:
                st.error("Nombre es obligatorio")
            else:
                # Generate ID from sede + nombre
                aula_id = f"{sede}_{nombre.replace(' ', '-').upper()}"
                aula = AulaDB(
                    id=aula_id,
                    sede=sede,
                    nombre=nombre,
                    capacidad=capacidad,
                    tipo=tipo,
                    descripcion=descripcion
                )
                try:
                    with next(get_session()) as session:
                        aula_crud.create(session, aula)
                    st.success(f"Aula '{aula_id}' creada exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error al crear aula: {e}")

# =============================================================================
# Tab 3: Editar
# =============================================================================
with tab_edit:
    with next(get_session()) as session:
        aulas = aula_crud.get_all(session, limit=500)
    
    if not aulas:
        st.info("No hay aulas para editar.")
    else:
        aula_id_edit = st.selectbox(
            "Seleccionar aula a editar",
            options=[a.id for a in aulas],
            format_func=lambda x: f"{x}",
            key="edit_aula_select"
        )
        
        # Get selected aula
        aula_selected = next((a for a in aulas if a.id == aula_id_edit), None)
        
        if aula_selected:
            with st.form("edit_aula"):
                st.text_input("ID", value=aula_selected.id, disabled=True)
                
                col1, col2 = st.columns(2)
                
                with col1:
                    sede_idx = SEDES.index(aula_selected.sede) if aula_selected.sede in SEDES else 0
                    sede = st.selectbox("Sede", options=SEDES, index=sede_idx, key="edit_sede")
                    nombre = st.text_input("Nombre", value=aula_selected.nombre, key="edit_nombre")
                    capacidad = st.number_input("Capacidad", min_value=1, value=aula_selected.capacidad, key="edit_cap")
                
                with col2:
                    tipo_idx = TIPOS_AULA.index(aula_selected.tipo) if aula_selected.tipo in TIPOS_AULA else 0
                    tipo = st.selectbox("Tipo", options=TIPOS_AULA, index=tipo_idx, key="edit_tipo")
                    descripcion = st.text_area("Descripción", value=aula_selected.descripcion or "", key="edit_desc")
                
                submitted = st.form_submit_button("💾 Guardar Cambios", type="primary")
                
                if submitted:
                    if not nombre:
                        st.error("Nombre es obligatorio")
                    else:
                        with next(get_session()) as session:
                            aula_db = session.get(AulaDB, aula_id_edit)
                            if aula_db:
                                aula_db.sede = sede
                                aula_db.nombre = nombre
                                aula_db.capacidad = capacidad
                                aula_db.tipo = tipo
                                aula_db.descripcion = descripcion
                                session.add(aula_db)
                                session.commit()
                                st.success(f"Aula '{aula_id_edit}' actualizada")
                                st.rerun()
