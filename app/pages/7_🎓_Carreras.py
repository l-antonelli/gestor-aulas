"""Gestión de Carreras - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5, 8.1
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import carrera_service, materia_service
from src.domain.problem.carrera import Carrera
from src.domain.problem.materia import Materia
from src.ui.page_template import EntityPageTemplate, EntityPageConfig
from src.ui.hierarchical_entity_viewer import HierarchicalEntityViewer, ChildConfig, HierarchyLevel

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Carreras", page_icon="🎓", layout="wide")

# Configure child entities for hierarchical view
# Note: Carrera -> Materia is a many-to-many relationship through MateriaCarreraLink
# We'll display associated materias in the detail view

# Configure the entity page
config = EntityPageConfig(
    model=Carrera,
    service=carrera_service,
    page_title="Gestión de Carreras",
    page_icon="🎓",
    display_fields=["codigo", "nombre", "titulo_otorgado", "duracion_anios"],
    custom_labels={
        "codigo": "Código",
        "nombre": "Nombre",
        "titulo_otorgado": "Título Otorgado",
        "duracion_anios": "Duración (años)",
    },
    id_field="codigo",
    display_field="nombre",
    enable_cascading=False,  # Carreras don't have cascading children
    enable_hierarchy_view=True,
    exclude_from_create=[],
)

# Render the page using EntityPageTemplate
with next(get_session()) as session:
    EntityPageTemplate.render_entity_page(config, session)
    
    # Add a section for managing Carrera-Materia relationships
    st.divider()
    st.subheader("📚 Materias por Carrera")
    
    # Get all carreras for selector
    carreras = carrera_service.get_all(session)
    
    if carreras:
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
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                if materias:
                    st.write(f"**{len(materias)} materia(s) asociada(s):**")
                    for m in materias:
                        st.markdown(f"- **{m.codigo}**: {m.nombre} (Cupo: {m.cupo})")
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
