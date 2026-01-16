"""
Many-to-Many Relationship Selector Component.

Provides UI components for selecting multiple related entities in many-to-many relationships,
with support for validation and automatic data loading.
"""

from typing import Any, Callable, List, Optional, Type, Dict

import streamlit as st
from pydantic import BaseModel
from sqlmodel import Session

from src.services.relationship_registry import RelationshipRegistry


class ManyToManySelector:
    """Renders multi-select components for many-to-many relationships."""

    @staticmethod
    def render_many_to_many_selector(
        field_name: str,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        crud_func: Callable,
        session: Session,
        current_values: List[str] = None,
        key: str = None,
        label: str = None,
        help_text: str = None,
        required: bool = True,
    ) -> List[str]:
        """
        Render a multi-select dropdown for many-to-many relationships.
        
        Args:
            field_name: Name of the relationship field
            parent_model: The parent model class (entities being selected)
            child_model: The child model class (entity containing the relationship)
            crud_func: CRUD function to fetch parent entities
            session: Database session
            current_values: Currently selected entity IDs
            key: Streamlit widget key
            label: Custom label for the selector
            help_text: Help text to display
            required: Whether at least one selection is required
            
        Returns:
            List of selected entity IDs
        """
        # Get relationship metadata
        relationship = RelationshipRegistry.get_relationship(parent_model, child_model)
        
        if not relationship or not relationship.is_many_to_many:
            st.error(f"No many-to-many relationship found for {parent_model.__name__} ↔ {child_model.__name__}")
            return current_values or []
        
        # Load related entities
        try:
            entities = crud_func(session)
        except Exception as e:
            st.error(f"Error loading {parent_model.__name__} entities: {str(e)}")
            return current_values or []
        
        if not entities:
            st.warning(f"No {parent_model.__name__} entities found. Please create one first.")
            return current_values or []
        
        # Build display options
        display_fields = relationship.display_fields or ["codigo", "nombre"]
        options = []
        option_map = {}
        
        for entity in entities:
            # Get entity ID
            entity_id = ManyToManySelector._get_entity_id(entity)
            if entity_id is None:
                continue
            
            # Build display text
            display_parts = []
            for field in display_fields:
                if hasattr(entity, field):
                    value = getattr(entity, field)
                    if value is not None:
                        display_parts.append(str(value))
            
            display_text = " - ".join(display_parts) if display_parts else str(entity_id)
            
            options.append(display_text)
            option_map[display_text] = entity_id
        
        # Determine default selection
        default_selection = []
        if current_values:
            for option_text, entity_id in option_map.items():
                if entity_id in current_values:
                    default_selection.append(option_text)
        
        # Render multi-select
        widget_label = label or f"Seleccionar {parent_model.__name__}s"
        if required:
            widget_label += " *"
        
        selected_options = st.multiselect(
            label=widget_label,
            options=options,
            default=default_selection,
            key=key,
            help=help_text,
        )
        
        # Convert back to entity IDs
        selected_ids = [option_map[option] for option in selected_options]
        
        # Validation
        if required and not selected_ids:
            st.error(f"Debe seleccionar al menos un {parent_model.__name__}")
        
        return selected_ids
    
    @staticmethod
    def render_carrera_selector_for_materia(
        session: Session,
        current_carrera_codigos: List[str] = None,
        key: str = None,
    ) -> List[str]:
        """
        Convenience method for rendering carrera selector for materia forms.
        
        Args:
            session: Database session
            current_carrera_codigos: Currently selected carrera codigos
            key: Streamlit widget key
            
        Returns:
            List of selected carrera codigos
        """
        from src.domain.problem.carrera import Carrera
        from src.domain.problem.materia import Materia
        from src.services.crud_services import carrera_service
        
        return ManyToManySelector.render_many_to_many_selector(
            field_name="carreras",
            parent_model=Carrera,
            child_model=Materia,
            crud_func=carrera_service.get_all,
            session=session,
            current_values=current_carrera_codigos,
            key=key,
            label="Carreras",
            help_text="Seleccione las carreras a las que pertenece esta materia. Debe seleccionar al menos una.",
            required=True,
        )
    
    @staticmethod
    def _get_entity_id(entity: Any) -> Optional[str]:
        """
        Get the ID of an entity.
        
        Args:
            entity: The entity instance
        
        Returns:
            The entity ID or None
        """
        # Try common ID field names
        for id_field in ["codigo", "id", "legajo"]:
            if hasattr(entity, id_field):
                return str(getattr(entity, id_field))
        
        return None