"""Gestión de Alumnos - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import alumno_service
from src.domain.problem.alumno import Alumno
from src.ui.page_template import EntityPageTemplate, EntityPageConfig

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Alumnos", page_icon="🎓", layout="wide")

# Configure the entity page
config = EntityPageConfig(
    model=Alumno,
    service=alumno_service,
    page_title="Gestión de Alumnos",
    page_icon="🎓",
    display_fields=["legajo", "nombre", "email", "dni"],
    custom_labels={
        "legajo": "Legajo",
        "nombre": "Nombre",
        "email": "Email",
        "dni": "DNI",
    },
    id_field="legajo",
    display_field="nombre",
    enable_cascading=False,  # Alumnos don't have cascading children
    enable_hierarchy_view=False,  # Alumnos don't have hierarchical children
    exclude_from_create=[],
)

# Render the page using EntityPageTemplate
with next(get_session()) as session:
    EntityPageTemplate.render_entity_page(config, session)
