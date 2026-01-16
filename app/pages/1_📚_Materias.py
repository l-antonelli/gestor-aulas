"""Gestión de Materias - Enhanced with Carrera relationship management.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import materia_service
from src.ui.materia_form_renderer import MateriaFormRenderer
from src.ui.carrera_status_widget import CarreraStatusWidget

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Materias", page_icon="📚", layout="wide")

# Custom page implementation with carrera relationship handling
def render_custom_materia_page():
    """Render the materia page with custom carrera relationship handling."""
    
    # Custom labels for form fields
    custom_labels = {
        "codigo": "Código",
        "nombre": "Nombre",
        "periodo": "Período",
        "anio_carrera": "Año",
        "cuatrimestre_carrera": "Cuatrimestre",
        "cupo": "Cupo",
        "horas_semanales": "Hs/Sem",
    }
    
    st.title("📚 Gestión de Materias")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📋 Lista", "➕ Crear", "🔍 Buscar"])
    
    with next(get_session()) as session:
        
        # Show carrera completeness warnings at the top (before tabs)
        with st.expander("📊 Estado de Completitud de Carreras", expanded=False):
            CarreraStatusWidget.render_summary_metrics(session)
            st.divider()
            CarreraStatusWidget.render_warnings_panel(session)
        
        with tab1:
            # List all materias with carrera information
            st.subheader("Lista de Materias")
            
            try:
                materias = materia_service.get_all(session)
                
                if not materias:
                    st.info("No hay materias registradas. Cree una nueva materia usando la pestaña 'Crear'.")
                else:
                    # Display materias with carrera information
                    for materia in materias:
                        with st.expander(f"📚 {materia.codigo} - {materia.nombre}"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.write(f"**Código:** {materia.codigo}")
                                st.write(f"**Nombre:** {materia.nombre}")
                                st.write(f"**Período:** {materia.periodo}")
                                st.write(f"**Año:** {materia.anio_carrera}")
                                st.write(f"**Cuatrimestre:** {materia.cuatrimestre_carrera}")
                            
                            with col2:
                                st.write(f"**Cupo:** {materia.cupo}")
                                st.write(f"**Horas/Semana:** {materia.horas_semanales}")
                                
                                # Show associated carreras
                                try:
                                    carreras = materia_service.get_carreras(session, materia.codigo)
                                    if carreras:
                                        carrera_names = [f"{c.codigo} - {c.nombre}" for c in carreras]
                                        st.write(f"**Carreras:** {', '.join(carrera_names)}")
                                    else:
                                        st.warning("⚠️ Sin carreras asignadas")
                                except Exception as e:
                                    st.error(f"Error al cargar carreras: {str(e)}")
                            
                            # Action buttons
                            col_edit, col_delete = st.columns(2)
                            
                            with col_edit:
                                if st.button("✏️ Editar", key=f"edit_{materia.codigo}"):
                                    st.session_state["edit_materia"] = materia.codigo
                                    st.rerun()
                            
                            with col_delete:
                                if st.button("🗑️ Eliminar", key=f"delete_{materia.codigo}"):
                                    st.session_state["delete_materia"] = materia.codigo
                                    st.rerun()
                    
                    # Handle edit action
                    if "edit_materia" in st.session_state:
                        materia_codigo = st.session_state["edit_materia"]
                        st.subheader(f"Editar Materia: {materia_codigo}")
                        
                        form_data = MateriaFormRenderer.render_materia_update_form(
                            materia_codigo=materia_codigo,
                            session=session,
                            custom_labels=custom_labels,
                        )
                        
                        if form_data:
                            updated_materia = MateriaFormRenderer.update_materia_with_carreras(
                                form_data=form_data,
                                session=session,
                            )
                            
                            if updated_materia:
                                st.success("✅ Materia actualizada exitosamente")
                                del st.session_state["edit_materia"]
                                st.rerun()
                    
                    # Handle delete action
                    if "delete_materia" in st.session_state:
                        materia_codigo = st.session_state["delete_materia"]
                        st.subheader(f"Eliminar Materia: {materia_codigo}")
                        
                        st.warning("⚠️ ¿Está seguro que desea eliminar esta materia? Esta acción no se puede deshacer.")
                        
                        col_confirm, col_cancel = st.columns(2)
                        
                        with col_confirm:
                            if st.button("🗑️ Confirmar Eliminación", type="primary"):
                                try:
                                    success = materia_service.delete(session, materia_codigo)
                                    if success:
                                        st.success("✅ Materia eliminada exitosamente")
                                        del st.session_state["delete_materia"]
                                        st.rerun()
                                    else:
                                        st.error("❌ No se pudo eliminar la materia")
                                except Exception as e:
                                    st.error(f"❌ Error al eliminar: {str(e)}")
                        
                        with col_cancel:
                            if st.button("❌ Cancelar"):
                                del st.session_state["delete_materia"]
                                st.rerun()
            
            except Exception as e:
                st.error(f"Error al cargar materias: {str(e)}")
        
        with tab2:
            # Create new materia
            st.subheader("Crear Nueva Materia")
            
            form_data = MateriaFormRenderer.render_materia_create_form(
                session=session,
                custom_labels=custom_labels,
            )
            
            if form_data:
                created_materia = MateriaFormRenderer.create_materia_with_carreras(
                    form_data=form_data,
                    session=session,
                )
                
                if created_materia:
                    st.success("✅ Materia creada exitosamente")
                    st.rerun()
        
        with tab3:
            # Search functionality
            st.subheader("Buscar Materias")
            
            search_term = st.text_input("Buscar por código o nombre:")
            
            if search_term:
                try:
                    all_materias = materia_service.get_all(session)
                    filtered_materias = [
                        m for m in all_materias
                        if search_term.lower() in m.codigo.lower() or search_term.lower() in m.nombre.lower()
                    ]
                    
                    if filtered_materias:
                        st.write(f"Encontradas {len(filtered_materias)} materia(s):")
                        for materia in filtered_materias:
                            st.write(f"📚 {materia.codigo} - {materia.nombre}")
                    else:
                        st.info("No se encontraron materias que coincidan con la búsqueda.")
                
                except Exception as e:
                    st.error(f"Error en la búsqueda: {str(e)}")

# Render the custom page
render_custom_materia_page()
