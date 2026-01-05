"""
Relationship Selector Component.

Provides UI components for selecting related entities through dropdowns,
with support for search/filter functionality and automatic data loading.
"""

from typing import Any, Callable, List, Optional, Type, Dict

import streamlit as st
from pydantic import BaseModel
from sqlmodel import Session

from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_metadata import RelationshipMetadata


class RelationshipSelector:
    """Renders relationship selector dropdowns for foreign key fields."""

    @staticmethod
    def get_related_entities(
        model: Type[BaseModel],
        crud_func: Callable,
        session: Session,
    ) -> List[BaseModel]:
        """
        Get all entities of a model type from database.
        
        Args:
            model: The model class to fetch entities for
            crud_func: CRUD function to fetch entities (e.g., materia_crud.get_all)
            session: Database session
            
        Returns:
            List of model instances from the database
        """
        try:
            entities = crud_func(session)
            return entities
        except Exception as e:
            st.error(f"Error loading {model.__name__} entities: {str(e)}")
            return []

    @staticmethod
    def render_relationship_selector(
        field_name: str,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        crud_func: Callable,
        session: Session,
        default_value: Any = None,
        key: str = None,
        label: str = None,
    ) -> Any:
        """
        Render a dropdown to select a related entity.
        
        Args:
            field_name: Name of the foreign key field
            parent_model: The parent model class (entity being selected)
            child_model: The child model class (entity containing the foreign key)
            crud_func: CRUD function to fetch parent entities
            session: Database session
            default_value: Default selected value
            key: Streamlit widget key
            label: Custom label for the selector
            
        Returns:
            Selected entity ID or value
        """
        # Get relationship metadata
        relationship = RelationshipRegistry.get_relationship(parent_model, child_model)
        
        if not relationship:
            # Fallback to simple text input if no relationship defined
            st.warning(f"No relationship metadata found for {parent_model.__name__} → {child_model.__name__}")
            return st.text_input(
                label or field_name,
                value=default_value or "",
                key=key,
            )
        
        # Load related entities
        entities = RelationshipSelector.get_related_entities(
            model=parent_model,
            crud_func=crud_func,
            session=session,
        )
        
        if not entities:
            st.warning(f"No {parent_model.__name__} entities found. Please create one first.")
            return None
        
        # Build display options
        display_fields = relationship.display_fields
        options = []
        option_map = {}
        
        for entity in entities:
            # Get the ID field value (primary key)
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            
            # Determine the ID field
            id_field = None
            for field in ['id', 'codigo', 'legajo']:
                if field in entity_dict:
                    id_field = field
                    break
            
            if not id_field:
                continue
            
            entity_id = entity_dict[id_field]
            
            # Build display string from display_fields
            display_parts = []
            for field in display_fields:
                if field in entity_dict:
                    display_parts.append(f"{entity_dict[field]}")
            
            display_str = " - ".join(display_parts) if display_parts else str(entity_id)
            
            options.append(display_str)
            option_map[display_str] = entity_id
        
        # Find default index
        default_index = 0
        if default_value:
            for idx, (display_str, entity_id) in enumerate(option_map.items()):
                if entity_id == default_value:
                    default_index = idx
                    break
        
        # Render selectbox
        selected_display = st.selectbox(
            label or f"Select {parent_model.__name__}",
            options=options,
            index=default_index,
            key=key,
            help=f"Select a {parent_model.__name__} from the list",
        )
        
        # Return the actual ID value
        return option_map.get(selected_display)

    @staticmethod
    def render_searchable_selector(
        field_name: str,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        crud_func: Callable,
        session: Session,
        search_fields: List[str],
        default_value: Any = None,
        key: str = None,
        label: str = None,
    ) -> Any:
        """
        Render a searchable dropdown for selecting related entities.
        
        Supports filtering by multiple fields with case-insensitive search.
        Search context is persisted in session state and restored when returning.
        
        Args:
            field_name: Name of the foreign key field
            parent_model: The parent model class (entity being selected)
            child_model: The child model class (entity containing the foreign key)
            crud_func: CRUD function to fetch parent entities
            session: Database session
            search_fields: Fields to search by
            default_value: Default selected value
            key: Streamlit widget key
            label: Custom label for the selector
            
        Returns:
            Selected entity ID or value
        """
        # Get relationship metadata
        relationship = RelationshipRegistry.get_relationship(parent_model, child_model)
        
        if not relationship:
            # Fallback to simple selector
            return RelationshipSelector.render_relationship_selector(
                field_name=field_name,
                parent_model=parent_model,
                child_model=child_model,
                crud_func=crud_func,
                session=session,
                default_value=default_value,
                key=key,
                label=label,
            )
        
        # Load related entities
        entities = RelationshipSelector.get_related_entities(
            model=parent_model,
            crud_func=crud_func,
            session=session,
        )
        
        if not entities:
            st.warning(f"No {parent_model.__name__} entities found. Please create one first.")
            return None
        
        # Create search box with persistence
        search_key = f"{key}_search" if key else f"{field_name}_search"
        search_context_key = f"search_context_{parent_model.__name__}_{child_model.__name__}_{field_name}"
        
        # Initialize search context in session state if not present
        if search_context_key not in st.session_state:
            st.session_state[search_context_key] = ""
        
        # Render search box with persisted value
        search_term = st.text_input(
            "Search",
            key=search_key,
            value=st.session_state[search_context_key],
            placeholder=f"Search by {', '.join(search_fields)}...",
        )
        
        # Update search context in session state
        st.session_state[search_context_key] = search_term
        
        # Filter entities based on search term
        filtered_entities = entities
        if search_term:
            search_lower = search_term.lower()
            filtered_entities = []
            
            for entity in entities:
                entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
                
                # Check if search term matches any search field
                match_found = False
                for field in search_fields:
                    if field in entity_dict:
                        field_value = str(entity_dict[field]).lower()
                        if search_lower in field_value:
                            match_found = True
                            break
                
                if match_found:
                    filtered_entities.append(entity)
        
        # Display "No results" message if no matches
        if not filtered_entities:
            st.info("No results found. Try a different search term.")
            return default_value
        
        # Build display options from filtered entities
        display_fields = relationship.display_fields
        options = []
        option_map = {}
        
        for entity in filtered_entities:
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            
            # Determine the ID field
            id_field = None
            for field in ['id', 'codigo', 'legajo']:
                if field in entity_dict:
                    id_field = field
                    break
            
            if not id_field:
                continue
            
            entity_id = entity_dict[id_field]
            
            # Build display string from display_fields
            display_parts = []
            for field in display_fields:
                if field in entity_dict:
                    display_parts.append(f"{entity_dict[field]}")
            
            display_str = " - ".join(display_parts) if display_parts else str(entity_id)
            
            options.append(display_str)
            option_map[display_str] = entity_id
        
        # Find default index
        default_index = 0
        if default_value:
            for idx, (display_str, entity_id) in enumerate(option_map.items()):
                if entity_id == default_value:
                    default_index = idx
                    break
        
        # Render selectbox
        selected_display = st.selectbox(
            label or f"Select {parent_model.__name__}",
            options=options,
            index=default_index,
            key=f"{key}_select" if key else f"{field_name}_select",
            help=f"Select a {parent_model.__name__} from the filtered list",
        )
        
        # Return the actual ID value
        return option_map.get(selected_display)

    @staticmethod
    def get_foreign_key_fields(model: Type[BaseModel]) -> Dict[str, Type[BaseModel]]:
        """
        Detect foreign key fields in a model by checking registered relationships.
        
        Args:
            model: The model class to check for foreign keys
            
        Returns:
            Dictionary mapping foreign key field names to parent model classes
        """
        foreign_keys = {}
        
        # Get all relationships where this model is the child
        all_relationships = RelationshipRegistry.get_all_relationships()
        
        for relationship in all_relationships:
            if relationship.child_model == model:
                foreign_keys[relationship.foreign_key_field] = relationship.parent_model
        
        return foreign_keys

    @staticmethod
    def clear_search_context(
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        field_name: str,
    ) -> None:
        """
        Clear the search context for a specific relationship selector.
        
        This is useful when you want to reset the search state, for example
        after navigating to a different page or completing a form submission.
        
        Args:
            parent_model: The parent model class
            child_model: The child model class
            field_name: The foreign key field name
        """
        search_context_key = f"search_context_{parent_model.__name__}_{child_model.__name__}_{field_name}"
        if search_context_key in st.session_state:
            del st.session_state[search_context_key]
    
    @staticmethod
    def clear_all_search_contexts() -> None:
        """
        Clear all search contexts from session state.
        
        This is useful when you want to reset all search states, for example
        when logging out or starting a new session.
        """
        keys_to_delete = [
            key for key in st.session_state.keys()
            if key.startswith("search_context_")
        ]
        for key in keys_to_delete:
            del st.session_state[key]
    
    @staticmethod
    def get_search_context(
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        field_name: str,
    ) -> str:
        """
        Get the current search context for a specific relationship selector.
        
        Args:
            parent_model: The parent model class
            child_model: The child model class
            field_name: The foreign key field name
            
        Returns:
            The current search term, or empty string if not set
        """
        search_context_key = f"search_context_{parent_model.__name__}_{child_model.__name__}_{field_name}"
        return st.session_state.get(search_context_key, "")


# ============================================================================
# Backward Compatibility API
# ============================================================================
# The following methods provide backward compatibility with the old API
# that used a simple dictionary-based registry.

# Global registry for backward compatibility
RELATIONSHIP_REGISTRY: Dict[tuple, tuple] = {}


def register_domain_relationships() -> None:
    """
    Register all domain relationships using the old API format.
    
    This function provides backward compatibility by converting
    RelationshipRegistry entries to the old RELATIONSHIP_REGISTRY format.
    """
    from src.domain.problem.materia import Materia
    from src.domain.problem.comision import Comision
    from src.domain.problem.clase import Clase
    from src.domain.problem.alumno import Alumno
    from src.domain.problem.aula import Aula
    from src.domain.problem.horario_cronograma import HorarioCronograma
    from src.domain.solution.inscripcion import Inscripcion
    from src.domain.solution.asistencia import Asistencia
    from src.domain.solution.asignacion_aula import AsignacionAula
    
    # Register relationships using old API
    RelationshipSelector.register_relationship(
        source_model=Comision,
        field_name="materia_codigo",
        target_model=Materia,
        display_field="nombre",
        id_field="codigo",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Clase,
        field_name="comision_id",
        target_model=Comision,
        display_field="nombre",
        id_field="id",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Clase,
        field_name="horario_id",
        target_model=HorarioCronograma,
        display_field="dia_semana",
        id_field="id",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Inscripcion,
        field_name="alumno_legajo",
        target_model=Alumno,
        display_field="nombre",
        id_field="legajo",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Inscripcion,
        field_name="comision_id",
        target_model=Comision,
        display_field="nombre",
        id_field="id",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Asistencia,
        field_name="alumno_legajo",
        target_model=Alumno,
        display_field="nombre",
        id_field="legajo",
    )
    
    RelationshipSelector.register_relationship(
        source_model=Asistencia,
        field_name="clase_id",
        target_model=Clase,
        display_field="id",
        id_field="id",
    )
    
    RelationshipSelector.register_relationship(
        source_model=AsignacionAula,
        field_name="clase_id",
        target_model=Clase,
        display_field="id",
        id_field="id",
    )
    
    RelationshipSelector.register_relationship(
        source_model=AsignacionAula,
        field_name="aula_id",
        target_model=Aula,
        display_field="nombre",
        id_field="id",
    )


# Add backward compatibility methods to RelationshipSelector class
@staticmethod
def register_relationship(
    source_model: Type[BaseModel],
    field_name: str,
    target_model: Type[BaseModel],
    display_field: str,
    id_field: str,
) -> None:
    """
    Register a relationship using the old API format.
    
    This method provides backward compatibility with the old API.
    
    Args:
        source_model: The model containing the foreign key
        field_name: The foreign key field name
        target_model: The model being referenced
        display_field: Field to display in dropdowns
        id_field: Field containing the ID value
    """
    key = (source_model.__name__, field_name)
    RELATIONSHIP_REGISTRY[key] = (target_model, display_field, id_field)


@staticmethod
def get_relationship_info(
    source_model: Type[BaseModel],
    field_name: str,
) -> Optional[tuple]:
    """
    Get relationship info using the old API format.
    
    Args:
        source_model: The model containing the foreign key
        field_name: The foreign key field name
        
    Returns:
        Tuple of (target_model, display_field, id_field) or None
    """
    key = (source_model.__name__, field_name)
    return RELATIONSHIP_REGISTRY.get(key)


@staticmethod
def is_relationship_field(
    source_model: Type[BaseModel],
    field_name: str,
) -> bool:
    """
    Check if a field is a relationship field using the old API.
    
    Args:
        source_model: The model to check
        field_name: The field name to check
        
    Returns:
        True if the field is a relationship field, False otherwise
    """
    key = (source_model.__name__, field_name)
    return key in RELATIONSHIP_REGISTRY


# Add these methods to the RelationshipSelector class
RelationshipSelector.register_relationship = register_relationship
RelationshipSelector.get_relationship_info = get_relationship_info
RelationshipSelector.is_relationship_field = is_relationship_field

# Auto-register domain relationships when module is imported
register_domain_relationships()
