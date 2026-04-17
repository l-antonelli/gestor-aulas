"""
Streamlit Pydantic UI Components.

This module provides reusable UI components for generating Streamlit forms
from Pydantic models, enabling automatic form generation, validation,
and CRUD operations.
"""

from src.ui.schema_introspector import SchemaIntrospector
from src.ui.widget_mapper import WidgetMapper
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer
from src.ui.crud_form_renderer import CRUDFormRenderer
from src.ui.serialization_utils import (
    SerializationUtils,
    SerializationError,
    DeserializationError,
)
from src.ui.relationship_selector import (
    RelationshipSelector,
    register_domain_relationships,
)

__all__ = [
    "SchemaIntrospector",
    "WidgetMapper",
    "FormInputRenderer",
    "FormOutputRenderer",
    "CRUDFormRenderer",
    "SerializationUtils",
    "SerializationError",
    "DeserializationError",
    "RelationshipSelector",
    "register_domain_relationships",
]
