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
            # Manage Carrera-Materia relationships with year-based curriculum view
            st.subheader("📚 Planes de Estudio")
            
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
                    # Show status widget
                    st.markdown("### Estado de Completitud")
                    CarreraStatusWidget.render_inline_status(session, selected_carrera)
                    
                    st.divider()
                    
                    # Year selector
                    st.markdown("### Seleccionar Año del Plan de Estudios")
                    selected_year = st.selectbox(
                        "Año",
                        options=[1, 2, 3, 4, 5, 6],
                        format_func=lambda x: f"{x}° Año",
                        key="selected_year"
                    )
                    
                    st.divider()
                    
                    # Get all materias for this carrera and year
                    materias_anuales = carrera_service.get_materias_by_year_and_semester(
                        session, selected_carrera, selected_year
                    )
                    
                    # Filter by period type
                    anuales = [(m, a, c) for m, a, c in materias_anuales if c == "anual"]
                    primer_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "1C"]
                    segundo_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "2C"]
                    
                    # 3-column layout
                    col1, col2, col3 = st.columns(3)
                    
                    # Column 1: Anuales
                    with col1:
                        with st.expander(f"📅 Anuales ({len(anuales)})", expanded=True):
                            if anuales:
                                for materia, anio, cuatri in anuales:
                                    col_mat, col_del = st.columns([4, 1])
                                    with col_mat:
                                        st.markdown(f"**{materia.codigo}**")
                                        st.caption(f"{materia.nombre}")
                                    with col_del:
                                        if st.button("🗑️", key=f"del_anual_{materia.codigo}", help="Desasociar"):
                                            try:
                                                carrera_service.remove_materia(session, selected_carrera, materia.codigo)
                                                st.success("Desasociada")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                            else:
                                st.info("Sin materias anuales")
                            
                            # Add materia anual
                            st.markdown("---")
                            st.markdown("**➕ Asociar Materia Anual**")
                            
                            all_materias = materia_service.get_all(session)
                            associated_codigos = {m.codigo for m, _, _ in materias_anuales}
                            available_anuales = [m for m in all_materias if m.codigo not in associated_codigos and m.periodo == "anual"]
                            
                            if available_anuales:
                                materia_to_add = st.selectbox(
                                    "Materia",
                                    options=[m.codigo for m in available_anuales],
                                    format_func=lambda x: f"{x} - {next((m.nombre for m in available_anuales if m.codigo == x), '')}",
                                    key=f"add_anual_{selected_year}",
                                    label_visibility="collapsed"
                                )
                                
                                if st.button("Asociar", key=f"btn_add_anual_{selected_year}"):
                                    try:
                                        carrera_service.add_materia(
                                            session, selected_carrera, materia_to_add,
                                            anio_plan=selected_year,
                                            cuatrimestre_plan="anual"
                                        )
                                        st.success("Asociada")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            else:
                                st.caption("No hay materias anuales disponibles")
                    
                    # Column 2: 1er Cuatrimestre
                    with col2:
                        with st.expander(f"📘 1er Cuatrimestre ({len(primer_cuatri)})", expanded=True):
                            if primer_cuatri:
                                for materia, anio, cuatri in primer_cuatri:
                                    col_mat, col_del = st.columns([4, 1])
                                    with col_mat:
                                        st.markdown(f"**{materia.codigo}**")
                                        st.caption(f"{materia.nombre}")
                                    with col_del:
                                        if st.button("🗑️", key=f"del_1c_{materia.codigo}", help="Desasociar"):
                                            try:
                                                carrera_service.remove_materia(session, selected_carrera, materia.codigo)
                                                st.success("Desasociada")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                            else:
                                st.info("Sin materias en 1C")
                            
                            # Add materia 1C
                            st.markdown("---")
                            st.markdown("**➕ Asociar Materia 1C**")
                            
                            all_materias = materia_service.get_all(session)
                            associated_codigos = {m.codigo for m, _, _ in materias_anuales}
                            available_1c = [m for m in all_materias if m.codigo not in associated_codigos and m.periodo == "cuatrimestral"]
                            
                            if available_1c:
                                materia_to_add = st.selectbox(
                                    "Materia",
                                    options=[m.codigo for m in available_1c],
                                    format_func=lambda x: f"{x} - {next((m.nombre for m in available_1c if m.codigo == x), '')}",
                                    key=f"add_1c_{selected_year}",
                                    label_visibility="collapsed"
                                )
                                
                                if st.button("Asociar", key=f"btn_add_1c_{selected_year}"):
                                    try:
                                        carrera_service.add_materia(
                                            session, selected_carrera, materia_to_add,
                                            anio_plan=selected_year,
                                            cuatrimestre_plan="1C"
                                        )
                                        st.success("Asociada")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            else:
                                st.caption("No hay materias cuatrimestrales disponibles")
                    
                    # Column 3: 2do Cuatrimestre
                    with col3:
                        with st.expander(f"📗 2do Cuatrimestre ({len(segundo_cuatri)})", expanded=True):
                            if segundo_cuatri:
                                for materia, anio, cuatri in segundo_cuatri:
                                    col_mat, col_del = st.columns([4, 1])
                                    with col_mat:
                                        st.markdown(f"**{materia.codigo}**")
                                        st.caption(f"{materia.nombre}")
                                    with col_del:
                                        if st.button("🗑️", key=f"del_2c_{materia.codigo}", help="Desasociar"):
                                            try:
                                                carrera_service.remove_materia(session, selected_carrera, materia.codigo)
                                                st.success("Desasociada")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error: {e}")
                            else:
                                st.info("Sin materias en 2C")
                            
                            # Add materia 2C
                            st.markdown("---")
                            st.markdown("**➕ Asociar Materia 2C**")
                            
                            all_materias = materia_service.get_all(session)
                            associated_codigos = {m.codigo for m, _, _ in materias_anuales}
                            available_2c = [m for m in all_materias if m.codigo not in associated_codigos and m.periodo == "cuatrimestral"]
                            
                            if available_2c:
                                materia_to_add = st.selectbox(
                                    "Materia",
                                    options=[m.codigo for m in available_2c],
                                    format_func=lambda x: f"{x} - {next((m.nombre for m in available_2c if m.codigo == x), '')}",
                                    key=f"add_2c_{selected_year}",
                                    label_visibility="collapsed"
                                )
                                
                                if st.button("Asociar", key=f"btn_add_2c_{selected_year}"):
                                    try:
                                        carrera_service.add_materia(
                                            session, selected_carrera, materia_to_add,
                                            anio_plan=selected_year,
                                            cuatrimestre_plan="2C"
                                        )
                                        st.success("Asociada")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {e}")
                            else:
                                st.caption("No hay materias cuatrimestrales disponibles")


# Render the custom page
render_custom_carrera_page()
