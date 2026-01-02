"""
Relationship Entity Selector Module.

Provides utilities for selecting related entities in forms,
enabling dropdown selection for foreign key fields.

This module implements the relationship entity selection mechanism
required by Requirement 6.3.
"""

from typing import Any, Callable, Dict, List, Optional, Type

import streamlit as st
from pydantic import BaseModel

from src.ui.schema_introspector import SchemaIntrospector


# Registry of relationship fields and their target entities
# Maps (model_class, field_name) -> (target_model, display_field, id_field)
RELATIONSHIP_REGISTRY: Dict[tuple, tuple] = {}


class RelationshipSelector:
    """
    Provides mechanisms for selecting related entities in forms.
    
    This class enables dropdown selection for foreign key fields,
    allowing users to select from existing entities when creating
    or updating records with relationships.
    """

    @staticmethod
    def register_relationship(
        source_model: Type[BaseModel],
        field_name: str,
        target_model: Type[BaseModel],
        display_field: str,
        id_field: str,
    ) -> None:
        """
        Register a relationship between models.
        
        Args:
            source_model: The model containing the foreign key field
            field_name: Name of the foreign key field
            target_model: The model being referenced
            display_field: Field to display in dropdown (e.g., "nombre")
            id_field: Field containing the ID value (e.g., "id", "codigo")
        """
        key = (source_model.__name__, field_name)
        RELATIONSHIP_REGISTRY[key] = (target_model, display_field, id_field)

    @staticmethod
    def get_relationship_info(
        model: Type[BaseModel],
        field_name: str,
    ) -> Optional[tuple]:
        """
        Get relationship information for a field.
        
        Args:
            model: The model class
            field_name: Name of the field
            
        Returns:
            Tuple of (target_model, display_field, id_field) or None
        """
        key = (model.__name__, field_name)
        return RELATIONSHIP_REGISTRY.get(key)

    @staticmethod
    def is_relationship_field(
        model: Type[BaseModel],
        field_name: str,
    ) -> bool:
        """
        Check if a field is a registered relationship field.
        
        Args:
            model: The model class
            field_name: Name of the field
            
        Returns:
            True if the field is a registered relationship
        """
        key = (model.__name__, field_name)
        return key in RELATIONSHIP_REGISTRY

    @staticmethod
    def render_relationship_selector(
        model: Type[BaseModel],
        field_name: str,
        get_entities_func: Callable[[], List[BaseModel]],
        key: str = None,
        default_value: Any = None,
        required: bool = True,
    ) -> Optional[str]:
        """
        Render a dropdown selector for a relationship field.
        
        Args:
            model: The model class containing the relationship field
            field_name: Name of the relationship field
            get_entities_func: Function that returns list of target entities
            key: Streamlit widget key
            default_value: Default selected value (ID)
            required: Whether selection is required
            
        Returns:
            Selected entity ID or None
        """
        relationship_info = RelationshipSelector.get_relationship_info(model, field_name)
        
        if relationship_info is None:
            # Not a registered relationship, fall back to text input
            label = field_name.replace("_", " ").title()
            if required:
                label = f"{label} *"
            return st.text_input(label, value=default_value or "", key=key)
        
        target_model, display_field, id_field = relationship_info
        
        # Get available entities
        entities = get_entities_func()
        
        if not entities:
            st.warning(f"No hay {target_model.__name__} disponibles")
            return None
        
        # Build options: {display_value: id_value}
        options = {}
        for entity in entities:
            display_value = getattr(entity, display_field, str(entity))
            id_value = getattr(entity, id_field)
            # Include ID in display for clarity
            options[f"{display_value} ({id_value})"] = id_value
        
        # Format label
        label = field_name.replace("_", " ").title()
        if required:
            label = f"{label} *"
        
        # Get field description
        description = SchemaIntrospector.get_field_description(model, field_name)
        
        # Find default index
        default_index = 0
        if default_value:
            for i, (display, id_val) in enumerate(options.items()):
                if id_val == default_value:
                    default_index = i
                    break
        
        # Render selectbox
        selected_display = st.selectbox(
            label,
            options=list(options.keys()),
            index=default_index,
            help=description if description else None,
            key=key,
        )
        
        return options.get(selected_display)

    @staticmethod
    def render_multi_relationship_selector(
        model: Type[BaseModel],
        field_name: str,
        get_entities_func: Callable[[], List[BaseModel]],
        key: str = None,
        default_values: List[Any] = None,
    ) -> List[str]:
        """
        Render a multi-select for relationship fields that accept multiple values.
        
        Args:
            model: The model class containing the relationship field
            field_name: Name of the relationship field
            get_entities_func: Function that returns list of target entities
            key: Streamlit widget key
            default_values: Default selected values (list of IDs)
            
        Returns:
            List of selected entity IDs
        """
        relationship_info = RelationshipSelector.get_relationship_info(model, field_name)
        
        if relationship_info is None:
            return []
        
        target_model, display_field, id_field = relationship_info
        
        # Get available entities
        entities = get_entities_func()
        
        if not entities:
            st.warning(f"No hay {target_model.__name__} disponibles")
            return []
        
        # Build options
        options = {}
        for entity in entities:
            display_value = getattr(entity, display_field, str(entity))
            id_value = getattr(entity, id_field)
            options[f"{display_value} ({id_value})"] = id_value
        
        # Format label
        label = field_name.replace("_", " ").title()
        
        # Get field description
        description = SchemaIntrospector.get_field_description(model, field_name)
        
        # Find default selections
        default_selections = []
        if default_values:
            for display, id_val in options.items():
                if id_val in default_values:
                    default_selections.append(display)
        
        # Render multiselect
        selected_displays = st.multiselect(
            label,
            options=list(options.keys()),
            default=default_selections,
            help=description if description else None,
            key=key,
        )
        
        return [options[display] for display in selected_displays]


# =============================================================================
# Register Default Relationships for Domain Models
# =============================================================================

def register_domain_relationships():
    """
    Register all known relationships between domain models.
    
    This function should be called during application initialization
    to set up the relationship registry.
    """
    # Import domain models
    from src.domain.problem import (
        Alumno, Materia, Comision, Clase, Aula, HorarioCronograma
    )
    from src.domain.solution import (
        Inscripcion, Asistencia, AsignacionAula
    )
    
    # Comision -> Materia
    RelationshipSelector.register_relationship(
        source_model=Comision,
        field_name="materia_codigo",
        target_model=Materia,
        display_field="nombre",
        id_field="codigo",
    )
    
    # Clase -> Comision
    RelationshipSelector.register_relationship(
        source_model=Clase,
        field_name="comision_id",
        target_model=Comision,
        display_field="nombre",
        id_field="id",
    )
    
    # Clase -> HorarioCronograma
    RelationshipSelector.register_relationship(
        source_model=Clase,
        field_name="horario_id",
        target_model=HorarioCronograma,
        display_field="dia_semana",
        id_field="id",
    )
    
    # Inscripcion -> Alumno
    RelationshipSelector.register_relationship(
        source_model=Inscripcion,
        field_name="alumno_legajo",
        target_model=Alumno,
        display_field="nombre",
        id_field="legajo",
    )
    
    # Inscripcion -> Comision
    RelationshipSelector.register_relationship(
        source_model=Inscripcion,
        field_name="comision_id",
        target_model=Comision,
        display_field="nombre",
        id_field="id",
    )
    
    # Asistencia -> Alumno
    RelationshipSelector.register_relationship(
        source_model=Asistencia,
        field_name="alumno_legajo",
        target_model=Alumno,
        display_field="nombre",
        id_field="legajo",
    )
    
    # Asistencia -> Clase
    RelationshipSelector.register_relationship(
        source_model=Asistencia,
        field_name="clase_id",
        target_model=Clase,
        display_field="id",
        id_field="id",
    )
    
    # AsignacionAula -> Clase
    RelationshipSelector.register_relationship(
        source_model=AsignacionAula,
        field_name="clase_id",
        target_model=Clase,
        display_field="id",
        id_field="id",
    )
    
    # AsignacionAula -> Aula
    RelationshipSelector.register_relationship(
        source_model=AsignacionAula,
        field_name="aula_id",
        target_model=Aula,
        display_field="nombre",
        id_field="id",
    )


# Auto-register relationships when module is imported
# This can be disabled by setting SKIP_AUTO_REGISTER = True before import
SKIP_AUTO_REGISTER = False

def _auto_register():
    """Auto-register relationships if not skipped."""
    if not SKIP_AUTO_REGISTER:
        try:
            register_domain_relationships()
        except ImportError:
            # Domain models not available, skip registration
            pass

# Perform auto-registration
_auto_register()
