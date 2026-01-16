"""Gestión de Carreras - Enhanced with materia completeness tracking.

Requirements: 7.1, 7.2, 7.4, 7.5, 8.1
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import carrera_service, materia_service
from src.domain.problem.carrera import Carrera
from src.ui.carrera_status_widget import CarreraStatusWidget
from src.ui.form_input_renderer import FormInputRenderer

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Carreras", page_icon="🎓", layout="wide")


def render_custom_carrera_page():
    """Render the carrera page with custom editing functionality."""
    
    # Custom labels for form fields
    custom_labels = {
        "codigo": "Código",
        "nombre": "Nombre",
        "titulo_otorgado": "Título Otorgado",
        "duracion_anios": "Duración (años)",
        "cantidad_materias": "Cantidad de Materias",
    }
    
    st.title("🎓 Gestión de Carreras")
    
    # Create tabs
    tab1, tab2, tab3 = st.tabs(["📋 Lista", "➕ Crear", "📚 Materias por Carrera"])
    
    with next(get_session()) as session:
        
        with tab1:
            # List all carreras
            st.subheader("Lista de Carreras")
            
            try:
                carreras = carrera_service.get_all(session)
                
                if not carreras:
                    st.info("No hay carreras registradas. Cree una nueva carrera usando la pestaña 'Crear'.")
                else:
                    # Display carreras
                    for carrera in carreras:
                        with st.expander(f"🎓 {carrera.codigo} - {carrera.nombre}"):
                            col1, col2 = st.columns(2)
                            
                            with col1:
                                st.write(f"**Código:** {carrera.codigo}")
                                st.write(f"**Nombre:** {carrera.nombre}")
                                st.write(f"**Título Otorgado:** {carrera.titulo_otorgado}")
                            
                            with col2:
                                st.write(f"**Duración:** {carrera.duracion_anios} años")
                                cantidad_text = str(carrera.cantidad_materias) if carrera.cantidad_materias else "No definida"
                                st.write(f"**Cantidad de Materias:** {cantidad_text}")
                                
                                # Show completeness status
                                try:
                                    CarreraStatusWidget.render_inline_status(session, carrera.codigo)
                                except Exception as e:
                                    st.error(f"Error al cargar estado: {str(e)}")
                            
                            # Action buttons
                            col_edit, col_delete = st.columns(2)
                            
                            with col_edit:
                                if st.button("✏️ Editar", key=f"edit_{carrera.codigo}"):
                                    st.session_state["edit_carrera"] = carrera.codigo
                                    st.rerun()
                            
                            with col_delete:
                                if st.button("🗑️ Eliminar", key=f"delete_{carrera.codigo}"):
                                    st.session_state["delete_carrera"] = carrera.codigo
                                    st.rerun()
                    
                    # Handle edit action
                    if "edit_carrera" in st.session_state:
                        carrera_codigo = st.session_state["edit_carrera"]
                        st.subheader(f"Editar Carrera: {carrera_codigo}")
                        
                        # Get existing carrera
                        try:
                            existing_carrera = carrera_service.get(session, carrera_codigo)
                            if existing_carrera is None:
                                st.error(f"Carrera con código '{carrera_codigo}' no encontrada")
                                del st.session_state["edit_carrera"]
                                st.rerun()
                        except Exception as e:
                            st.error(f"Error al cargar carrera: {str(e)}")
                            del st.session_state["edit_carrera"]
                            st.rerun()
                        
                        # Extract default values
                        if hasattr(existing_carrera, "model_dump"):
                            default_values = existing_carrera.model_dump()
                        else:
                            default_values = dict(existing_carrera)
                        
                        # Render edit form
                        with st.form(key=f"edit_carrera_{carrera_codigo}_form"):
                            # Show codigo as read-only
                            st.text_input(
                                "Código",
                                value=carrera_codigo,
                                disabled=True,
                                key=f"edit_{carrera_codigo}_codigo_display",
                            )
                            
                            # Render other fields
                            form_data = FormInputRenderer.render_form_input(
                                model=Carrera,
                                key=f"edit_{carrera_codigo}_input",
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
                                del st.session_state["edit_carrera"]
                                st.rerun()
                            
                            if submitted:
                                # Add back the codigo field
                                form_data["codigo"] = carrera_codigo
                                
                                # Validate form data
                                is_valid, errors = FormInputRenderer.validate_form_data(form_data, Carrera)
                                
                                if not is_valid:
                                    FormInputRenderer.display_validation_errors(errors)
                                else:
                                    try:
                                        # Create carrera instance and update
                                        carrera = Carrera(**form_data)
                                        updated_carrera = carrera_service.update(session, carrera)
                                        
                                        if updated_carrera:
                                            st.success("✅ Carrera actualizada exitosamente")
                                            del st.session_state["edit_carrera"]
                                            st.rerun()
                                        else:
                                            st.error("❌ No se pudo actualizar la carrera")
                                    except Exception as e:
                                        st.error(f"❌ Error al actualizar: {str(e)}")
                    
                    # Handle delete action
                    if "delete_carrera" in st.session_state:
                        carrera_codigo = st.session_state["delete_carrera"]
                        st.subheader(f"Eliminar Carrera: {carrera_codigo}")
                        
                        st.warning("⚠️ ¿Está seguro que desea eliminar esta carrera? Esta acción no se puede deshacer.")
                        
                        # Check if carrera has materias
                        try:
                            materias = carrera_service.get_materias(session, carrera_codigo)
                            if materias:
                                st.error(f"❌ No se puede eliminar: la carrera tiene {len(materias)} materia(s) asociada(s)")
                                st.info("💡 Primero debe desasociar todas las materias de esta carrera.")
                        except Exception:
                            pass
                        
                        col_confirm, col_cancel = st.columns(2)
                        
                        with col_confirm:
                            if st.button("🗑️ Confirmar Eliminación", type="primary"):
                                try:
                                    success = carrera_service.delete(session, carrera_codigo)
                                    if success:
                                        st.success("✅ Carrera eliminada exitosamente")
                                        del st.session_state["delete_carrera"]
                                        st.rerun()
                                    else:
                                        st.error("❌ No se pudo eliminar la carrera")
                                except Exception as e:
                                    st.error(f"❌ Error al eliminar: {str(e)}")
                        
                        with col_cancel:
                            if st.button("❌ Cancelar"):
                                del st.session_state["delete_carrera"]
                                st.rerun()
            
            except Exception as e:
                st.error(f"Error al cargar carreras: {str(e)}")
        
        with tab2:
            # Create new carrera
            st.subheader("Crear Nueva Carrera")
            
            with st.form(key="create_carrera_form"):
                form_data = FormInputRenderer.render_form_input(
                    model=Carrera,
                    key="create_carrera_input",
                    custom_labels=custom_labels,
                )
                
                submitted = st.form_submit_button("Crear Carrera", type="primary")
                
                if submitted:
                    # Validate form data
                    is_valid, errors = FormInputRenderer.validate_form_data(form_data, Carrera)
                    
                    if not is_valid:
                        FormInputRenderer.display_validation_errors(errors)
                    else:
                        try:
                            # Create carrera instance
                            carrera = Carrera(**form_data)
                            created_carrera = carrera_service.create(session, carrera)
                            
                            if created_carrera:
                                st.success("✅ Carrera creada exitosamente")
                                st.rerun()
                            else:
                                st.error("❌ No se pudo crear la carrera")
                        except Exception as e:
                            st.error(f"❌ Error al crear: {str(e)}")
        
        with tab3:
            # Manage Carrera-Materia relationships
            st.subheader("📚 Materias por Carrera")
            
            carreras = carrera_service.get_all(session)
            
            if not carreras:
                st.info("No hay carreras registradas. Cree una carrera primero.")
            else:
                carrera_options = [(c.codigo, c.nombre) for c in carreras]
                
                selected_carrera = st.selectbox(
                    "Seleccionar Carrera",
                    options=[opt[0] for opt in carrera_options],
                    format_func=lambda x: f"{x} - {next((opt[1] for opt in carrera_options if opt[0] == x), '')}",
                    key="carrera_materias_view"
                )
                
                if selected_carrera:
                    # Get materias for this carrera
                    materias = carrera_service.get_materias(session, selected_carrera)
                    
                    # Show status widget
                    st.markdown("### Estado de Completitud")
                    CarreraStatusWidget.render_inline_status(session, selected_carrera)
                    
                    st.divider()
                    
                    col1, col2 = st.columns([3, 1])
                    
                    with col1:
                        if materias:
                            st.write(f"**{len(materias)} materia(s) asociada(s):**")
                            for m in materias:
                                col_materia, col_remove = st.columns([4, 1])
                                with col_materia:
                                    st.markdown(f"- **{m.codigo}**: {m.nombre} (Cupo: {m.cupo})")
                                with col_remove:
                                    if st.button("🗑️", key=f"remove_{selected_carrera}_{m.codigo}", help="Desasociar materia"):
                                        try:
                                            carrera_service.remove_materia(session, selected_carrera, m.codigo)
                                            st.success(f"Materia {m.codigo} desasociada")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                        else:
                            st.info("Esta carrera no tiene materias asociadas.")
                    
                    with col2:
                        # Add materia to carrera
                        with st.expander("➕ Asociar Materia"):
                            all_materias = materia_service.get_all(session)
                            # Filter out already associated materias
                            associated_codigos = {m.codigo for m in materias}
                            available_materias = [m for m in all_materias if m.codigo not in associated_codigos]
                            
                            if available_materias:
                                materia_to_add = st.selectbox(
                                    "Materia",
                                    options=[m.codigo for m in available_materias],
                                    format_func=lambda x: f"{x} - {next((m.nombre for m in available_materias if m.codigo == x), '')}",
                                    key="add_materia_to_carrera"
                                )
                                
                                if st.button("Asociar", key="btn_add_materia"):
                                    try:
                                        carrera_service.add_materia(session, selected_carrera, materia_to_add)
                                        st.success(f"Materia {materia_to_add} asociada a {selected_carrera}")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            else:
                                st.info("No hay materias disponibles para asociar.")


# Render the custom page
render_custom_carrera_page()
