"""Gestión de Aulas - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import aula_service
from src.domain.problem.aula import Aula
from src.ui.page_template import EntityPageTemplate, EntityPageConfig

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Aulas", page_icon="🏛️", layout="wide")

# Configure the entity page
config = EntityPageConfig(
    model=Aula,
    service=aula_service,
    page_title="Gestión de Aulas",
    page_icon="🏛️",
    display_fields=["id", "sede", "nombre", "capacidad", "tipo", "descripcion"],
    custom_labels={
        "id": "ID",
        "sede": "Sede",
        "nombre": "Nombre",
        "capacidad": "Capacidad",
        "tipo": "Tipo",
        "descripcion": "Descripción",
    },
    id_field="id",
    display_field="nombre",
    enable_cascading=False,  # Aulas don't have cascading children
    enable_hierarchy_view=False,  # Aulas don't have hierarchical children
    exclude_from_create=[],
)

# Render the page using EntityPageTemplate
with next(get_session()) as session:
    EntityPageTemplate.render_entity_page(config, session)
