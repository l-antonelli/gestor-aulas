"""Gestión de Materias - Enhanced with Carrera relationship management.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import materia_service
from src.ui.materia_form_renderer import MateriaFormRenderer
from src.ui.carrera_status_widget import CarreraStatusWidget
from src.ui.materia_carrera_editor import MateriaCarreraEditor

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
        "virtual": "Virtual",
        "optativa": "Optativa",
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
            st.subheader("Lista de Materias")

            try:
                materias = materia_service.get_all(session, limit=10000)

                if not materias:
                    st.info("No hay materias registradas.")

                # --- Edit mode: show only the editor ---
                elif "edit_materia" in st.session_state:
                    materia_codigo = st.session_state["edit_materia"]
                    st.subheader(f"Editar Materia: {materia_codigo}")

                    try:
                        from src.ui.form_input_renderer import FormInputRenderer
                        from src.domain.problem.materia import Materia

                        existing_materia = materia_service.get(session, materia_codigo)
                        if existing_materia is None:
                            st.error(f"Materia '{materia_codigo}' no encontrada")
                            del st.session_state["edit_materia"]
                            st.rerun()

                        default_values = (
                            existing_materia.model_dump()
                            if hasattr(existing_materia, "model_dump")
                            else dict(existing_materia)
                        )

                        edit_tab1, edit_tab2 = st.tabs([
                            "Datos Basicos", "Carreras",
                        ])

                        with edit_tab1:
                            with st.form(key=f"edit_materia_{materia_codigo}_form"):
                                st.text_input("Codigo", value=materia_codigo, disabled=True)

                                form_data = FormInputRenderer.render_form_input(
                                    model=Materia,
                                    key=f"edit_{materia_codigo}_input",
                                    exclude_fields=["codigo"],
                                    custom_labels=custom_labels,
                                    default_values=default_values,
                                )

                                col_submit, col_cancel = st.columns(2)
                                with col_submit:
                                    submitted = st.form_submit_button("Guardar", type="primary")
                                with col_cancel:
                                    cancelled = st.form_submit_button("Cancelar")

                                if cancelled:
                                    del st.session_state["edit_materia"]
                                    st.rerun()

                                if submitted:
                                    form_data["codigo"] = materia_codigo
                                    is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
                                    if not is_valid:
                                        FormInputRenderer.display_validation_errors(errors)
                                    else:
                                        try:
                                            updated = materia_service.update(session, Materia(**form_data))
                                            if updated:
                                                st.success("Materia actualizada")
                                                del st.session_state["edit_materia"]
                                                st.rerun()
                                            else:
                                                st.error("No se pudo actualizar")
                                        except Exception as e:
                                            st.error(f"Error: {e}")

                        with edit_tab2:
                            MateriaCarreraEditor.render_associations_editor(
                                session=session,
                                materia_codigo=materia_codigo,
                                key=f"edit_{materia_codigo}_carreras",
                            )

                        st.divider()
                        if st.button("Volver a la lista", key=f"close_edit_{materia_codigo}"):
                            del st.session_state["edit_materia"]
                            st.rerun()

                    except Exception as e:
                        st.error(f"Error al cargar materia: {e}")
                        del st.session_state["edit_materia"]
                        st.rerun()

                # --- Delete confirmation ---
                elif "delete_materia" in st.session_state:
                    materia_codigo = st.session_state["delete_materia"]
                    st.subheader(f"Eliminar Materia: {materia_codigo}")
                    st.warning("Esta accion no se puede deshacer.")

                    col_confirm, col_cancel = st.columns(2)
                    with col_confirm:
                        if st.button("Confirmar", type="primary"):
                            try:
                                if materia_service.delete(session, materia_codigo):
                                    st.success("Materia eliminada")
                                    del st.session_state["delete_materia"]
                                    st.rerun()
                                else:
                                    st.error("No se pudo eliminar")
                            except Exception as e:
                                st.error(f"Error: {e}")
                    with col_cancel:
                        if st.button("Cancelar"):
                            del st.session_state["delete_materia"]
                            st.rerun()

                # --- Normal list view ---
                else:
                    # Search filter
                    search = st.text_input("Filtrar por codigo o nombre", key="materias_filter")

                    display_materias = materias
                    if search:
                        sl = search.lower()
                        display_materias = [
                            m for m in materias
                            if sl in m.codigo.lower() or sl in m.nombre.lower()
                        ]
                        st.caption(f"{len(display_materias)} de {len(materias)} materias")

                    for materia in display_materias:
                        with st.expander(f"{materia.codigo} — {materia.nombre}"):
                            col1, col2 = st.columns(2)

                            with col1:
                                st.write(f"**Codigo:** {materia.codigo}")
                                st.write(f"**Nombre:** {materia.nombre}")
                                st.write(f"**Periodo:** {materia.periodo}")
                                st.write(f"**Horas/Semana:** {materia.horas_semanales or '-'}")

                            with col2:
                                st.write(f"**Cupo:** {materia.cupo or '-'}")
                                st.write(f"**Virtual:** {'Si' if materia.virtual else 'No'}")
                                st.write(f"**Optativa:** {'Si' if materia.optativa else 'No'}")
                                try:
                                    carreras = materia_service.get_carreras(session, materia.codigo)
                                    if carreras:
                                        st.write(f"**Carreras:** {', '.join(c.codigo for c in carreras)}")
                                    else:
                                        st.caption("Sin carreras asignadas")
                                except Exception:
                                    pass

                            col_edit, col_delete = st.columns(2)
                            with col_edit:
                                if st.button("Editar", key=f"edit_{materia.codigo}"):
                                    st.session_state["edit_materia"] = materia.codigo
                                    st.rerun()
                            with col_delete:
                                if st.button("Eliminar", key=f"delete_{materia.codigo}"):
                                    st.session_state["delete_materia"] = materia.codigo
                                    st.rerun()

            except Exception as e:
                st.error(f"Error al cargar materias: {e}")
        
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
