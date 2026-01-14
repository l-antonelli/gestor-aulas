"""Gestión de Comisiones - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import comision_service, materia_service
from src.domain.problem.comision import Comision
from src.domain.problem.materia import Materia
from src.ui.page_template import EntityPageTemplate, EntityPageConfig
from src.ui.hierarchical_entity_viewer import ChildConfig

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Comisiones", page_icon="👥", layout="wide")

# Configure the entity page
config = EntityPageConfig(
    model=Comision,
    service=comision_service,
    page_title="Gestión de Comisiones",
    page_icon="👥",
    display_fields=["id", "materia_codigo", "nombre", "numero", "cupo", "descripcion"],
    custom_labels={
        "id": "ID",
        "materia_codigo": "Materia",
        "nombre": "Nombre",
        "numero": "Número",
        "cupo": "Cupo",
        "descripcion": "Descripción",
    },
    id_field="id",
    display_field="nombre",
    enable_cascading=False,  # Comisiones don't have cascading children by default
    enable_hierarchy_view=True,
    exclude_from_create=[],  # Include all fields in create form
    crud_functions={
        "Materia": lambda s: materia_service.get_all(s),
    },
)

# Render the page using EntityPageTemplate
with next(get_session()) as session:
    EntityPageTemplate.render_entity_page(config, session)
