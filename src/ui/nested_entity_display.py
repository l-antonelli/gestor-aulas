"""
Nested Entity Display Component.

Provides UI components for displaying and managing related entities
within the parent entity's view, supporting inline editing, deletion,
and creation of related entities.
"""

from typing import Callable, List, Optional, Type

import streamlit as st
from pydantic import BaseModel
from sqlmodel import Session

from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_metadata import RelationshipMetadata
from src.ui.form_output_renderer import FormOutputRenderer
from src.ui.form_input_renderer import FormInputRenderer


class NestedEntityDisplay:
    """Displays and manages related entities within parent entity view."""

    @staticmethod
    def render_nested_entities(
        parent_instance: BaseModel,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        child_crud_func: Callable,
        session: Session,
        on_edit: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
        on_create: Optional[Callable] = None,
    ) -> None:
        """
        Render a section displaying all related entities.
        
        Includes options to view, edit, delete, and create new related entities.
        
        Args:
            parent_instance: The parent entity instance
            parent_model: The parent model class
            child_model: The child model class
            child_crud_func: CRUD function to fetch child entities
            session: Database session
            on_edit: Optional callback when entity is edited
            on_delete: Optional callback when entity is deleted
            on_create: Optional callback when entity is created
        """
        # Get relationship metadata
        relationship = RelationshipRegistry.get_relationship(parent_model, child_model)
        
        if not relationship:
            st.warning(
                f"No relationship metadata found for {parent_model.__name__} → {child_model.__name__}"
            )
            return
        
        # Get parent ID
        parent_id = NestedEntityDisplay._get_entity_id(parent_instance)
        
        if not parent_id:
            st.error("Cannot display nested entities: parent ID not found")
            return
        
        # Fetch related entities
        related_entities = NestedEntityDisplay._get_children(
            parent_id=parent_id,
            relationship=relationship,
            child_crud_func=child_crud_func,
            session=session,
        )
        
        # Render section with collapsible expander
        child_name = child_model.__name__
        entity_count = len(related_entities)
        
        with st.expander(
            f"📋 {child_name} relacionados ({entity_count})",
            expanded=True
        ):
            # Display list of related entities
            if related_entities:
                NestedEntityDisplay.render_nested_entity_list(
                    related_entities=related_entities,
                    child_model=child_model,
                    display_fields=relationship.display_fields,
                    on_edit=on_edit,
                    on_delete=on_delete,
                )
            else:
                st.info(f"No hay {child_name} relacionados.")
            
            # Add button to create new related entity
            st.divider()
            if st.button(
                f"➕ Agregar {child_name}",
                key=f"add_{child_name}_{parent_id}",
                use_container_width=True,
            ):
                # Store state to show creation form
                state_key = f"show_create_form_{child_name}_{parent_id}"
                st.session_state[state_key] = True
            
            # Show creation form if button was clicked
            state_key = f"show_create_form_{child_name}_{parent_id}"
            if st.session_state.get(state_key, False):
                created = NestedEntityDisplay.render_add_related_entity_form(
                    parent_instance=parent_instance,
                    parent_model=parent_model,
                    child_model=child_model,
                    relationship=relationship,
                    session=session,
                )
                
                if created:
                    st.session_state[state_key] = False
                    if on_create:
                        on_create(created)
                    st.rerun()

    @staticmethod
    def render_nested_entity_list(
        related_entities: List[BaseModel],
        child_model: Type[BaseModel],
        display_fields: List[str],
        on_edit: Optional[Callable] = None,
        on_delete: Optional[Callable] = None,
    ) -> None:
        """
        Render a table/list of related entities.
        
        Args:
            related_entities: List of child entity instances
            child_model: The child model class
            display_fields: Fields to display for each entity
            on_edit: Optional callback when edit is clicked
            on_delete: Optional callback when delete is clicked
        """
        if not related_entities:
            return
        
        # Initialize session state for bulk selection
        bulk_selection_key = f"bulk_selection_{child_model.__name__}"
        if bulk_selection_key not in st.session_state:
            st.session_state[bulk_selection_key] = set()
        
        # Render bulk action controls if there are entities
        if len(related_entities) > 1:
            NestedEntityDisplay.render_bulk_action_controls(
                related_entities=related_entities,
                child_model=child_model,
                on_delete=on_delete,
            )
            st.divider()
        
        # Build table data
        for idx, entity in enumerate(related_entities):
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            entity_id = NestedEntityDisplay._get_entity_id(entity)
            
            # Create a container for each entity
            with st.container():
                col_checkbox, col_content, col_actions = st.columns([0.5, 3.5, 1])
                
                with col_checkbox:
                    # Checkbox for bulk selection (only show if multiple entities)
                    if len(related_entities) > 1:
                        checkbox_key = f"select_{child_model.__name__}_{entity_id}_{idx}"
                        is_selected = st.checkbox(
                            "",
                            key=checkbox_key,
                            value=entity_id in st.session_state[bulk_selection_key],
                            label_visibility="collapsed",
                        )
                        
                        # Update selection state
                        if is_selected:
                            st.session_state[bulk_selection_key].add(entity_id)
                        else:
                            st.session_state[bulk_selection_key].discard(entity_id)
                
                with col_content:
                    # Display entity fields
                    display_parts = []
                    for field in display_fields:
                        if field in entity_dict:
                            value = entity_dict[field]
                            formatted_value = FormOutputRenderer.format_field_value(
                                value,
                                type(value)
                            )
                            display_parts.append(f"**{field}**: {formatted_value}")
                    
                    st.markdown(" | ".join(display_parts))
                
                with col_actions:
                    # Action buttons
                    NestedEntityDisplay.render_nested_entity_actions(
                        entity=entity,
                        entity_id=entity_id,
                        child_model=child_model,
                        on_edit=on_edit,
                        on_delete=on_delete,
                        index=idx,
                    )
                
                st.divider()

    @staticmethod
    def render_nested_entity_actions(
        entity: BaseModel,
        entity_id: str,
        child_model: Type[BaseModel],
        on_edit: Optional[Callable],
        on_delete: Optional[Callable],
        index: int,
    ) -> None:
        """
        Render action buttons (edit, delete) for a related entity.
        
        Args:
            entity: The entity instance
            entity_id: The entity ID
            child_model: The child model class
            on_edit: Optional callback when edit is clicked
            on_delete: Optional callback when delete is clicked
            index: Index of the entity in the list (for unique keys)
        """
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button(
                "✏️",
                key=f"edit_{child_model.__name__}_{entity_id}_{index}",
                help="Editar",
                use_container_width=True,
            ):
                if on_edit:
                    on_edit(entity)
                else:
                    st.info("Funcionalidad de edición no implementada")
        
        with col2:
            if st.button(
                "🗑️",
                key=f"delete_{child_model.__name__}_{entity_id}_{index}",
                help="Eliminar",
                use_container_width=True,
                type="secondary",
            ):
                # Store delete confirmation state
                confirm_key = f"confirm_delete_{child_model.__name__}_{entity_id}"
                st.session_state[confirm_key] = True
        
        # Show delete confirmation if button was clicked
        confirm_key = f"confirm_delete_{child_model.__name__}_{entity_id}"
        if st.session_state.get(confirm_key, False):
            st.warning("⚠️ ¿Está seguro que desea eliminar esta entidad?")
            
            col_cancel, col_confirm = st.columns(2)
            
            with col_cancel:
                if st.button(
                    "Cancelar",
                    key=f"cancel_delete_{child_model.__name__}_{entity_id}_{index}",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = False
                    st.rerun()
            
            with col_confirm:
                if st.button(
                    "Confirmar",
                    key=f"confirm_delete_btn_{child_model.__name__}_{entity_id}_{index}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = False
                    if on_delete:
                        on_delete(entity)
                    st.rerun()

    @staticmethod
    def render_bulk_action_controls(
        related_entities: List[BaseModel],
        child_model: Type[BaseModel],
        on_delete: Optional[Callable] = None,
    ) -> None:
        """
        Render bulk action controls for selected entities.
        
        Args:
            related_entities: List of all child entity instances
            child_model: The child model class
            on_delete: Optional callback when delete is clicked
        """
        bulk_selection_key = f"bulk_selection_{child_model.__name__}"
        selected_ids = st.session_state.get(bulk_selection_key, set())
        
        # Header with selection info and actions
        col1, col2, col3, col4 = st.columns([2, 1, 1, 1])
        
        with col1:
            st.markdown(f"**Seleccionados: {len(selected_ids)} de {len(related_entities)}**")
        
        with col2:
            # Select all button
            if st.button(
                "Seleccionar todos",
                key=f"select_all_{child_model.__name__}",
                use_container_width=True,
                disabled=len(selected_ids) == len(related_entities),
            ):
                # Select all entities
                all_ids = {NestedEntityDisplay._get_entity_id(e) for e in related_entities}
                st.session_state[bulk_selection_key] = all_ids
                st.rerun()
        
        with col3:
            # Clear selection button
            if st.button(
                "Limpiar selección",
                key=f"clear_selection_{child_model.__name__}",
                use_container_width=True,
                disabled=len(selected_ids) == 0,
            ):
                st.session_state[bulk_selection_key] = set()
                st.rerun()
        
        with col4:
            # Bulk delete button
            if st.button(
                "🗑️ Eliminar seleccionados",
                key=f"bulk_delete_{child_model.__name__}",
                use_container_width=True,
                disabled=len(selected_ids) == 0,
                type="secondary",
            ):
                # Store bulk delete confirmation state
                confirm_key = f"confirm_bulk_delete_{child_model.__name__}"
                st.session_state[confirm_key] = True
        
        # Show bulk delete confirmation if button was clicked
        confirm_key = f"confirm_bulk_delete_{child_model.__name__}"
        if st.session_state.get(confirm_key, False):
            st.warning(
                f"⚠️ ¿Está seguro que desea eliminar {len(selected_ids)} entidades?"
            )
            
            col_cancel, col_confirm = st.columns(2)
            
            with col_cancel:
                if st.button(
                    "Cancelar",
                    key=f"cancel_bulk_delete_{child_model.__name__}",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = False
                    st.rerun()
            
            with col_confirm:
                if st.button(
                    "Confirmar eliminación",
                    key=f"confirm_bulk_delete_btn_{child_model.__name__}",
                    type="primary",
                    use_container_width=True,
                ):
                    st.session_state[confirm_key] = False
                    
                    # Perform bulk delete
                    if on_delete:
                        results = NestedEntityDisplay.perform_bulk_delete(
                            related_entities=related_entities,
                            selected_ids=selected_ids,
                            on_delete=on_delete,
                        )
                        
                        # Display results summary
                        NestedEntityDisplay.display_bulk_operation_results(
                            operation="delete",
                            results=results,
                        )
                        
                        # Clear selection
                        st.session_state[bulk_selection_key] = set()
                        st.rerun()

    @staticmethod
    def perform_bulk_delete(
        related_entities: List[BaseModel],
        selected_ids: set,
        on_delete: Callable,
    ) -> dict:
        """
        Perform bulk delete operation on selected entities.
        
        Args:
            related_entities: List of all child entity instances
            selected_ids: Set of selected entity IDs
            on_delete: Callback function to delete an entity
            
        Returns:
            Dictionary with operation results (success_count, failed_count, errors)
        """
        results = {
            "success_count": 0,
            "failed_count": 0,
            "errors": [],
        }
        
        for entity in related_entities:
            entity_id = NestedEntityDisplay._get_entity_id(entity)
            
            if entity_id in selected_ids:
                try:
                    on_delete(entity)
                    results["success_count"] += 1
                except Exception as e:
                    results["failed_count"] += 1
                    results["errors"].append(f"Error eliminando {entity_id}: {str(e)}")
        
        return results

    @staticmethod
    def display_bulk_operation_results(
        operation: str,
        results: dict,
    ) -> None:
        """
        Display summary of bulk operation results.
        
        Args:
            operation: The operation performed (e.g., "delete", "edit")
            results: Dictionary with operation results
        """
        success_count = results.get("success_count", 0)
        failed_count = results.get("failed_count", 0)
        errors = results.get("errors", [])
        
        if success_count > 0:
            st.success(
                f"✅ Operación completada: {success_count} entidades {operation}das exitosamente"
            )
        
        if failed_count > 0:
            st.error(
                f"❌ {failed_count} entidades fallaron durante la operación"
            )
            
            # Show error details in expander
            if errors:
                with st.expander("Ver detalles de errores"):
                    for error in errors:
                        st.text(error)

    @staticmethod
    def render_add_related_entity_form(
        parent_instance: BaseModel,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        relationship: RelationshipMetadata,
        session: Session,
    ) -> Optional[BaseModel]:
        """
        Render form to create a new related entity with parent pre-populated.
        
        Args:
            parent_instance: The parent entity instance
            parent_model: The parent model class
            child_model: The child model class
            relationship: The relationship metadata
            session: Database session
            
        Returns:
            Created entity instance or None if cancelled/failed
        """
        parent_id = NestedEntityDisplay._get_entity_id(parent_instance)
        form_key = f"create_{child_model.__name__}_{parent_id}"
        
        st.subheader(f"Crear {child_model.__name__}")
        
        with st.form(key=form_key):
            # Pre-populate foreign key field with parent ID
            default_values = {
                relationship.foreign_key_field: parent_id
            }
            
            # Render form input, excluding the foreign key field (it's pre-populated)
            form_data = FormInputRenderer.render_form_input(
                model=child_model,
                key=f"{form_key}_input",
                exclude_fields=[relationship.foreign_key_field],
                default_values=default_values,
            )
            
            # Add back the foreign key field
            form_data[relationship.foreign_key_field] = parent_id
            
            # Show the parent relationship as read-only
            st.text_input(
                relationship.foreign_key_field.replace("_", " ").title(),
                value=str(parent_id),
                disabled=True,
                key=f"{form_key}_parent_display",
            )
            
            col1, col2 = st.columns(2)
            
            with col1:
                cancel = st.form_submit_button("Cancelar", use_container_width=True)
            
            with col2:
                submit = st.form_submit_button(
                    "Crear",
                    type="primary",
                    use_container_width=True,
                )
            
            if cancel:
                return None
            
            if submit:
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, child_model)
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                try:
                    # Create model instance
                    instance = child_model(**form_data)
                    
                    # Save to database
                    from src.database.crud import CRUDBase
                    crud = CRUDBase[child_model](child_model)
                    created = crud.create(session, instance)
                    
                    st.success(f"✅ {child_model.__name__} creado exitosamente")
                    return created
                    
                except Exception as e:
                    st.error(f"❌ Error al crear: {str(e)}")
                    return None
        
        return None

    @staticmethod
    def _get_entity_id(entity: BaseModel) -> Optional[str]:
        """
        Get the ID value from an entity instance.
        
        Tries common ID field names: id, codigo, legajo.
        
        Args:
            entity: The entity instance
            
        Returns:
            The ID value or None if not found
        """
        entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
        
        for field in ['id', 'codigo', 'legajo']:
            if field in entity_dict:
                return entity_dict[field]
        
        return None

    @staticmethod
    def _get_children(
        parent_id: str,
        relationship: RelationshipMetadata,
        child_crud_func: Callable,
        session: Session,
    ) -> List[BaseModel]:
        """
        Get all child entities for a parent.
        
        Args:
            parent_id: The parent entity ID
            relationship: The relationship metadata
            child_crud_func: CRUD function to fetch children
            session: Database session
            
        Returns:
            List of child entity instances
        """
        try:
            # Get all children
            all_children = child_crud_func(session)
            
            # Filter by parent ID
            foreign_key_field = relationship.foreign_key_field
            related_children = []
            
            for child in all_children:
                child_dict = child.model_dump() if hasattr(child, 'model_dump') else child.dict()
                
                if child_dict.get(foreign_key_field) == parent_id:
                    related_children.append(child)
            
            return related_children
            
        except Exception as e:
            st.error(f"Error loading related entities: {str(e)}")
            return []
