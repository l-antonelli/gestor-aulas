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
        "dicta_recursado": "Dicta recursado",
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
                                dicta_text = "Si" if carrera.dicta_recursado else "No"
                                st.write(f"**Dicta recursado:** {dicta_text}")
                                
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
            st.subheader("Planes de Estudio")

            carreras = carrera_service.get_all(session)

            if not carreras:
                st.info("No hay carreras registradas. Cree una carrera primero.")
            else:
                carrera_options = [(c.codigo, c.nombre) for c in carreras]

                selected_carrera = st.selectbox(
                    "Seleccionar Carrera",
                    options=[opt[0] for opt in carrera_options],
                    format_func=lambda x: f"{x} - {next((opt[1] for opt in carrera_options if opt[0] == x), '')}",
                    key="carrera_materias_view",
                )

                if selected_carrera:
                    # --- Version selector ---
                    plan_versions = carrera_service.get_plan_versions(session, selected_carrera)

                    if not plan_versions:
                        st.warning("Esta carrera no tiene versiones de plan de estudio.")
                    else:
                        version_options = {v.id: f"{v.nombre} ({v.fecha_creacion})" for v in plan_versions}

                        col_ver, col_new = st.columns([3, 1])
                        with col_ver:
                            selected_version_id = st.selectbox(
                                "Version del Plan",
                                options=list(version_options.keys()),
                                format_func=lambda x: version_options[x],
                                key="plan_version_select",
                            )
                        with col_new:
                            st.write("")
                            st.write("")
                            if st.button("Nueva Version", key="btn_new_version"):
                                st.session_state["creating_version"] = True

                        # Create new version form
                        if st.session_state.get("creating_version"):
                            with st.form("create_version_form"):
                                new_name = st.text_input("Nombre de la nueva version")
                                new_desc = st.text_input("Descripcion (opcional)")
                                copy_from = st.checkbox("Copiar materias de la version actual", value=True)
                                if st.form_submit_button("Crear"):
                                    if new_name.strip():
                                        carrera_service.create_plan_version(
                                            session,
                                            selected_carrera,
                                            new_name.strip(),
                                            descripcion=new_desc.strip(),
                                            copy_from_version_id=selected_version_id if copy_from else None,
                                        )
                                        st.session_state.pop("creating_version", None)
                                        st.success(f"Version '{new_name}' creada")
                                        st.rerun()
                                    else:
                                        st.error("El nombre no puede estar vacio")

                        # Edit version name/description
                        selected_version = next((v for v in plan_versions if v.id == selected_version_id), None)
                        if selected_version:
                            with st.expander("Editar version"):
                                edit_name = st.text_input("Nombre", value=selected_version.nombre, key="edit_ver_name")
                                edit_desc = st.text_input("Descripcion", value=selected_version.descripcion, key="edit_ver_desc")
                                if st.button("Guardar", key="btn_save_version"):
                                    carrera_service.update_plan_version(
                                        session, selected_version_id,
                                        nombre=edit_name.strip() or None,
                                        descripcion=edit_desc.strip(),
                                    )
                                    st.success("Version actualizada")
                                    st.rerun()

                        st.divider()

                        # Show status widget
                        st.markdown("### Estado de Completitud")
                        CarreraStatusWidget.render_inline_status(session, selected_carrera)

                        st.divider()

                        # Year selector
                        st.markdown("### Seleccionar Anio del Plan de Estudios")
                        selected_year = st.selectbox(
                            "Anio",
                            options=[1, 2, 3, 4, 5, 6],
                            format_func=lambda x: f"{x} Anio",
                            key="selected_year",
                        )

                        st.divider()

                        # Get all materias for this carrera, year, and version
                        materias_anuales = carrera_service.get_materias_by_year_and_semester(
                            session, selected_carrera, selected_year,
                            plan_version_id=selected_version_id,
                        )

                        anuales = [(m, a, c) for m, a, c in materias_anuales if c == "anual"]
                        primer_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "1C"]
                        segundo_cuatri = [(m, a, c) for m, a, c in materias_anuales if c == "2C"]

                        col1, col2, col3 = st.columns(3)

                        # Helper to render a column
                        def _render_period_column(title, materias_list, period_key, cuatrimestre_plan_value, periodo_filter):
                            with st.expander(f"{title} ({len(materias_list)})", expanded=True):
                                if materias_list:
                                    for materia, anio, cuatri in materias_list:
                                        col_mat, col_del = st.columns([4, 1])
                                        with col_mat:
                                            st.markdown(f"**{materia.codigo}**")
                                            st.caption(f"{materia.nombre}")
                                        with col_del:
                                            if st.button("X", key=f"del_{period_key}_{materia.codigo}", help="Desasociar"):
                                                try:
                                                    carrera_service.remove_materia(
                                                        session, selected_carrera, materia.codigo,
                                                        plan_version_id=selected_version_id,
                                                    )
                                                    st.success("Desasociada")
                                                    st.rerun()
                                                except Exception as e:
                                                    st.error(f"Error: {e}")
                                else:
                                    st.info(f"Sin materias {period_key}")

                                st.markdown("---")
                                st.markdown(f"**Asociar Materia {period_key}**")

                                all_materias = materia_service.get_all(session)
                                associated_codigos = {m.codigo for m, _, _ in materias_anuales}
                                available = [m for m in all_materias if m.codigo not in associated_codigos and m.periodo == periodo_filter]

                                if available:
                                    materia_to_add = st.selectbox(
                                        "Materia",
                                        options=[m.codigo for m in available],
                                        format_func=lambda x: f"{x} - {next((m.nombre for m in available if m.codigo == x), '')}",
                                        key=f"add_{period_key}_{selected_year}",
                                        label_visibility="collapsed",
                                    )
                                    if st.button("Asociar", key=f"btn_add_{period_key}_{selected_year}"):
                                        try:
                                            carrera_service.add_materia(
                                                session, selected_carrera, materia_to_add,
                                                plan_version_id=selected_version_id,
                                                anio_plan=selected_year,
                                                cuatrimestre_plan=cuatrimestre_plan_value,
                                            )
                                            st.success("Asociada")
                                            st.rerun()
                                        except Exception as e:
                                            st.error(f"Error: {e}")
                                else:
                                    st.caption(f"No hay materias disponibles")

                        with col1:
                            _render_period_column("Anuales", anuales, "anual", "anual", "anual")
                        with col2:
                            _render_period_column("1er Cuatrimestre", primer_cuatri, "1C", "1C", "cuatrimestral")
                        with col3:
                            _render_period_column("2do Cuatrimestre", segundo_cuatri, "2C", "2C", "cuatrimestral")


# Render the custom page
render_custom_carrera_page()
