"""Gestión de Materias - Refactored to use CRUD Service and EntityPageTemplate.

Requirements: 7.1, 7.2, 7.4, 7.5
"""

import streamlit as st
from src.database.connection import get_session, init_db
from src.services.crud_services import materia_service, comision_service
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.ui.page_template import EntityPageTemplate, EntityPageConfig
from src.ui.hierarchical_entity_viewer import ChildConfig

# Import relationship definitions to register relationships
import src.services.relationship_definitions  # noqa: F401

# Initialize database
init_db()

st.set_page_config(page_title="Materias", page_icon="📚", layout="wide")

# Configure child entities for hierarchical view
comision_child_config = ChildConfig(
    model=Comision,
    service=comision_service,
    display_fields=["id", "nombre", "numero", "cupo"],
    foreign_key_field="materia_codigo",
    id_field="id",
    display_field="nombre",
    icon="👥",
    allow_create=True,
    allow_edit=True,
    allow_delete=True,
)

# Configure the entity page
config = EntityPageConfig(
    model=Materia,
    service=materia_service,
    page_title="Gestión de Materias",
    page_icon="📚",
    display_fields=["codigo", "nombre", "periodo", "anio_carrera", "cuatrimestre_carrera", "cupo", "horas_semanales"],
    custom_labels={
        "codigo": "Código",
        "nombre": "Nombre",
        "periodo": "Período",
        "anio_carrera": "Año",
        "cuatrimestre_carrera": "Cuatrimestre",
        "cupo": "Cupo",
        "horas_semanales": "Hs/Sem",
    },
    id_field="codigo",
    display_field="nombre",
    child_configs=[comision_child_config],
    enable_cascading=True,  # Materias have cascading creation of default Comision
    enable_hierarchy_view=True,
    exclude_from_create=[],
)

# Render the page using EntityPageTemplate
with next(get_session()) as session:
    EntityPageTemplate.render_entity_page(config, session)
