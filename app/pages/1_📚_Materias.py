"""Gestión de Materias - Enhanced with Carrera relationship management.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import materia_service
from src.ui.materia_form_renderer import MateriaFormRenderer
from src.ui.carrera_status_widget import CarreraStatusWidget
from src.ui.materia_carrera_editor import MateriaCarreraEditor
from src.services.crud_services import comision_service, horario_service

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
                            
                            with col2:
                                st.write(f"**Cupo:** {materia.cupo}")
                                st.write(f"**Horas/Semana:** {materia.horas_semanales}")
                                
                                # Show associated carreras (read-only)
                                try:
                                    carreras = materia_service.get_carreras(session, materia.codigo)
                                    if carreras:
                                        carrera_names = [f"{c.codigo}" for c in carreras]
                                        st.write(f"**Carreras:** {', '.join(carrera_names)}")
                                        st.caption("💡 Gestione año/cuatrimestre en 'Planes de Estudio'")
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
                    
                    # Handle edit action - with carrera and comision management
                    if "edit_materia" in st.session_state:
                        materia_codigo = st.session_state["edit_materia"]
                        st.subheader(f"Editar Materia: {materia_codigo}")
                        
                        # Get existing materia
                        try:
                            from src.ui.form_input_renderer import FormInputRenderer
                            from src.domain.problem.materia import Materia
                            
                            existing_materia = materia_service.get(session, materia_codigo)
                            if existing_materia is None:
                                st.error(f"Materia con código '{materia_codigo}' no encontrada")
                                del st.session_state["edit_materia"]
                                st.rerun()
                            
                            # Extract default values
                            if hasattr(existing_materia, "model_dump"):
                                default_values = existing_materia.model_dump()
                            else:
                                default_values = dict(existing_materia)
                            
                            # Create tabs for different aspects
                            edit_tab1, edit_tab2, edit_tab3 = st.tabs([
                                "📝 Datos Básicos",
                                "🎓 Carreras",
                                "👥 Comisiones"
                            ])
                            
                            with edit_tab1:
                                st.markdown("### Editar Datos de la Materia")
                                
                                with st.form(key=f"edit_materia_{materia_codigo}_form"):
                                    # Show codigo as read-only
                                    st.text_input(
                                        "Código",
                                        value=materia_codigo,
                                        disabled=True,
                                        key=f"edit_{materia_codigo}_codigo_display",
                                    )
                                    
                                    # Render other fields (excluding codigo)
                                    form_data = FormInputRenderer.render_form_input(
                                        model=Materia,
                                        key=f"edit_{materia_codigo}_input",
                                        exclude_fields=["codigo"],
                                        custom_labels=custom_labels,
                                        default_values=default_values,
                                    )
                                    
                                    col_submit, col_cancel = st.columns(2)
                                    
                                    with col_submit:
                                        submitted = st.form_submit_button("💾 Guardar Cambios", type="primary")
                                    
                                    with col_cancel:
                                        cancelled = st.form_submit_button("❌ Cancelar")
                                    
                                    if cancelled:
                                        del st.session_state["edit_materia"]
                                        st.rerun()
                                    
                                    if submitted:
                                        # Add back the codigo field
                                        form_data["codigo"] = materia_codigo
                                        
                                        # Validate form data
                                        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                                        
                                        if not is_valid:
                                            FormInputRenderer.display_validation_errors(errors)
                                        else:
                                            try:
                                                # Create materia instance and update
                                                materia = Materia(**form_data)
                                                updated_materia = materia_service.update(session, materia)
                                                
                                                if updated_materia:
                                                    st.success("✅ Materia actualizada exitosamente")
                                                    st.rerun()
                                                else:
                                                    st.error("❌ No se pudo actualizar la materia")
                                            except Exception as e:
                                                st.error(f"❌ Error al actualizar: {str(e)}")
                            
                            with edit_tab2:
                                # Carrera associations editor
                                MateriaCarreraEditor.render_associations_editor(
                                    session=session,
                                    materia_codigo=materia_codigo,
                                    key=f"edit_{materia_codigo}_carreras"
                                )
                            
                            with edit_tab3:
                                # Read-only comisiones view
                                st.markdown("### 👥 Comisiones")
                                st.caption("Las comisiones se crean automaticamente al cargar horarios.")
                                comisiones = comision_service.get_by_materia(session, materia_codigo)
                                if not comisiones:
                                    st.info("No hay comisiones para esta materia.")
                                else:
                                    for com in comisiones:
                                        with st.expander(f"{com.nombre} (#{com.numero})"):
                                            st.write(f"**ID:** {com.id}")
                                            st.write(f"**Cupo:** {com.cupo}")
                                            horarios = horario_service.get_by_comision(session, com.id)
                                            if horarios:
                                                st.write("**Horarios:**")
                                                for h in horarios:
                                                    st.write(f"  - {h.dia} {h.hora_inicio.strftime('%H:%M')}-{h.hora_fin.strftime('%H:%M')}")
                            
                            # Close button at the bottom
                            st.divider()
                            if st.button("✅ Cerrar Editor", key=f"close_edit_{materia_codigo}"):
                                del st.session_state["edit_materia"]
                                st.rerun()
                                
                        except Exception as e:
                            st.error(f"Error al cargar materia: {str(e)}")
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
