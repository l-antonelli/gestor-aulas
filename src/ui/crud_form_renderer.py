"""
CRUD Form Renderer Module.

Provides utilities for rendering complete CRUD forms with database integration,
combining form input, validation, and database operations.
"""

from typing import Any, Callable, Dict, List, Optional, Type

import streamlit as st
from pydantic import BaseModel, ValidationError

from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer


class CRUDFormRenderer:
    """Renders complete CRUD forms with database integration."""

    @staticmethod
    def render_create_form(
        model: Type[BaseModel],
        crud_create_func: Callable,
        key: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        submit_label: str = "Crear",
        success_message: str = "Entidad creada exitosamente",
        **kwargs,
    ) -> Optional[BaseModel]:
        """
        Render form for creating new entity.
        
        Args:
            model: Pydantic model class
            crud_create_func: Function to call for database create operation.
                             Should accept (session, entity) and return created entity.
            key: Streamlit key prefix for form state
            exclude_fields: Fields to exclude from form
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            submit_label: Label for submit button
            success_message: Message to display on successful creation
            **kwargs: Additional arguments passed to crud_create_func
            
        Returns:
            Created entity instance or None if cancelled/failed
        """
        form_key = key or f"create_{model.__name__}"
        
        with st.form(key=form_key):
            st.subheader(f"Crear {model.__name__}")
            
            form_data = FormInputRenderer.render_form_input(
                model=model,
                key=f"{form_key}_input",
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
            )
            
            submitted = st.form_submit_button(submit_label)
            
            if submitted:
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, model)
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                try:
                    # Create model instance
                    instance = model(**form_data)
                    
                    # Call CRUD create function
                    created = crud_create_func(instance, **kwargs)
                    
                    CRUDFormRenderer.show_operation_feedback(
                        operation="create",
                        success=True,
                        message=success_message,
                    )
                    return created
                    
                except ValidationError as e:
                    errors = {}
                    for error in e.errors():
                        field_name = str(error["loc"][0]) if error["loc"] else "general"
                        if field_name not in errors:
                            errors[field_name] = []
                        errors[field_name].append(error.get("msg", "Validation error"))
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                    
                except Exception as e:
                    CRUDFormRenderer.show_operation_feedback(
                        operation="create",
                        success=False,
                        message=f"Error al crear: {str(e)}",
                    )
                    return None
        
        return None

    @staticmethod
    def render_read_form(
        model: Type[BaseModel],
        entity_id: str,
        crud_read_func: Callable,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        title: str = None,
        **kwargs,
    ) -> Optional[BaseModel]:
        """
        Render form for reading/displaying entity.
        
        Args:
            model: Pydantic model class
            entity_id: ID of the entity to read
            crud_read_func: Function to call for database read operation.
                           Should accept (session, id) and return entity or None.
            exclude_fields: Fields to exclude from display
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            title: Optional title for the display
            **kwargs: Additional arguments passed to crud_read_func
            
        Returns:
            Entity instance or None if not found
        """
        try:
            entity = crud_read_func(entity_id, **kwargs)
            
            if entity is None:
                CRUDFormRenderer.show_operation_feedback(
                    operation="read",
                    success=False,
                    message=f"Entidad con ID '{entity_id}' no encontrada",
                )
                return None
            
            # Display entity using FormOutputRenderer
            display_title = title or f"Detalle de {model.__name__}"
            FormOutputRenderer.render_form_output_card(
                instance=entity,
                title=display_title,
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
            )
            
            return entity
            
        except Exception as e:
            CRUDFormRenderer.show_operation_feedback(
                operation="read",
                success=False,
                message=f"Error al leer: {str(e)}",
            )
            return None

    @staticmethod
    def render_update_form(
        model: Type[BaseModel],
        entity_id: str,
        crud_read_func: Callable,
        crud_update_func: Callable,
        key: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        id_field: str = None,
        submit_label: str = "Actualizar",
        success_message: str = "Entidad actualizada exitosamente",
        **kwargs,
    ) -> Optional[BaseModel]:
        """
        Render form for updating entity with pre-populated values.
        
        Args:
            model: Pydantic model class
            entity_id: ID of the entity to update
            crud_read_func: Function to call for database read operation.
                           Should accept (session, id) and return entity or None.
            crud_update_func: Function to call for database update operation.
                             Should accept (session, entity) and return updated entity.
            key: Streamlit key prefix for form state
            exclude_fields: Fields to exclude from form
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            id_field: Name of the ID field (to exclude from editing)
            submit_label: Label for submit button
            success_message: Message to display on successful update
            **kwargs: Additional arguments passed to crud functions
            
        Returns:
            Updated entity instance or None if cancelled/failed
        """
        form_key = key or f"update_{model.__name__}_{entity_id}"
        
        # First, read the existing entity
        try:
            existing_entity = crud_read_func(entity_id, **kwargs)
            
            if existing_entity is None:
                CRUDFormRenderer.show_operation_feedback(
                    operation="read",
                    success=False,
                    message=f"Entidad con ID '{entity_id}' no encontrada",
                )
                return None
                
        except Exception as e:
            CRUDFormRenderer.show_operation_feedback(
                operation="read",
                success=False,
                message=f"Error al leer entidad: {str(e)}",
            )
            return None
        
        # Extract default values from existing entity
        if hasattr(existing_entity, "model_dump"):
            default_values = existing_entity.model_dump()
        else:
            default_values = dict(existing_entity)
        
        # Determine fields to exclude (including ID field if specified)
        all_exclude = list(exclude_fields or [])
        if id_field and id_field not in all_exclude:
            all_exclude.append(id_field)
        
        with st.form(key=form_key):
            st.subheader(f"Editar {model.__name__}")
            
            # Show ID field as read-only if specified
            if id_field:
                st.text_input(
                    id_field.replace("_", " ").title(),
                    value=str(default_values.get(id_field, entity_id)),
                    disabled=True,
                    key=f"{form_key}_id_display",
                )
            
            form_data = FormInputRenderer.render_form_input(
                model=model,
                key=f"{form_key}_input",
                exclude_fields=all_exclude,
                field_order=field_order,
                custom_labels=custom_labels,
                default_values=default_values,
            )
            
            submitted = st.form_submit_button(submit_label)
            
            if submitted:
                # Add back the ID field
                if id_field:
                    form_data[id_field] = default_values.get(id_field, entity_id)
                
                # Validate form data
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, model)
                
                if not is_valid:
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                try:
                    # Create updated model instance
                    updated_instance = model(**form_data)
                    
                    # Call CRUD update function
                    result = crud_update_func(updated_instance, **kwargs)
                    
                    CRUDFormRenderer.show_operation_feedback(
                        operation="update",
                        success=True,
                        message=success_message,
                    )
                    return result
                    
                except ValidationError as e:
                    errors = {}
                    for error in e.errors():
                        field_name = str(error["loc"][0]) if error["loc"] else "general"
                        if field_name not in errors:
                            errors[field_name] = []
                        errors[field_name].append(error.get("msg", "Validation error"))
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                    
                except Exception as e:
                    CRUDFormRenderer.show_operation_feedback(
                        operation="update",
                        success=False,
                        message=f"Error al actualizar: {str(e)}",
                    )
                    return None
        
        return None

    @staticmethod
    def render_delete_form(
        model: Type[BaseModel],
        entity_id: str,
        crud_read_func: Callable,
        crud_delete_func: Callable,
        key: str = None,
        display_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
        confirm_message: str = None,
        success_message: str = "Entidad eliminada exitosamente",
        **kwargs,
    ) -> bool:
        """
        Render confirmation form for deleting entity.
        
        Args:
            model: Pydantic model class
            entity_id: ID of the entity to delete
            crud_read_func: Function to call for database read operation.
                           Should accept (session, id) and return entity or None.
            crud_delete_func: Function to call for database delete operation.
                             Should accept (session, id) and return bool.
            key: Streamlit key prefix for form state
            display_fields: Fields to display in confirmation
            custom_labels: Custom labels for fields
            confirm_message: Custom confirmation message
            success_message: Message to display on successful deletion
            **kwargs: Additional arguments passed to crud functions
            
        Returns:
            True if deleted, False if cancelled or failed
        """
        form_key = key or f"delete_{model.__name__}_{entity_id}"
        confirm_key = f"{form_key}_confirmed"
        
        # Initialize confirmation state
        if confirm_key not in st.session_state:
            st.session_state[confirm_key] = False
        
        # First, read the entity to display
        try:
            entity = crud_read_func(entity_id, **kwargs)
            
            if entity is None:
                CRUDFormRenderer.show_operation_feedback(
                    operation="read",
                    success=False,
                    message=f"Entidad con ID '{entity_id}' no encontrada",
                )
                return False
                
        except Exception as e:
            CRUDFormRenderer.show_operation_feedback(
                operation="read",
                success=False,
                message=f"Error al leer entidad: {str(e)}",
            )
            return False
        
        # Display entity details
        st.subheader(f"Eliminar {model.__name__}")
        
        # Show warning
        default_confirm = "¿Está seguro que desea eliminar esta entidad? Esta acción no se puede deshacer."
        st.warning(confirm_message or default_confirm)
        
        # Display entity info
        with st.expander("Ver detalles de la entidad", expanded=True):
            FormOutputRenderer.render_form_output(
                instance=entity,
                exclude_fields=None,
                field_order=display_fields,
                custom_labels=custom_labels,
            )
        
        # Confirmation buttons
        col1, col2 = st.columns(2)
        
        with col1:
            if st.button("❌ Cancelar", key=f"{form_key}_cancel", use_container_width=True):
                st.session_state[confirm_key] = False
                st.info("Operación cancelada")
                return False
        
        with col2:
            if st.button("🗑️ Confirmar Eliminación", key=f"{form_key}_confirm", type="primary", use_container_width=True):
                try:
                    result = crud_delete_func(entity_id, **kwargs)
                    
                    if result:
                        CRUDFormRenderer.show_operation_feedback(
                            operation="delete",
                            success=True,
                            message=success_message,
                        )
                        st.session_state[confirm_key] = False
                        return True
                    else:
                        CRUDFormRenderer.show_operation_feedback(
                            operation="delete",
                            success=False,
                            message="No se pudo eliminar la entidad",
                        )
                        return False
                        
                except Exception as e:
                    CRUDFormRenderer.show_operation_feedback(
                        operation="delete",
                        success=False,
                        message=f"Error al eliminar: {str(e)}",
                    )
                    return False
        
        return False

    @staticmethod
    def show_operation_feedback(
        operation: str,
        success: bool,
        message: str = None,
    ) -> None:
        """
        Display feedback message after CRUD operation.
        
        Args:
            operation: Type of operation (create, read, update, delete)
            success: Whether the operation was successful
            message: Custom message to display
        """
        # Default messages for each operation
        default_messages = {
            "create": {
                True: "✅ Entidad creada exitosamente",
                False: "❌ Error al crear la entidad",
            },
            "read": {
                True: "✅ Entidad cargada exitosamente",
                False: "❌ Error al cargar la entidad",
            },
            "update": {
                True: "✅ Entidad actualizada exitosamente",
                False: "❌ Error al actualizar la entidad",
            },
            "delete": {
                True: "✅ Entidad eliminada exitosamente",
                False: "❌ Error al eliminar la entidad",
            },
        }
        
        # Get message
        if message:
            display_message = message
        else:
            op_messages = default_messages.get(operation, default_messages["read"])
            display_message = op_messages.get(success, "Operación completada")
        
        # Display with appropriate style
        if success:
            st.success(display_message)
        else:
            st.error(display_message)

    @staticmethod
    def render_crud_form(
        model: Type[BaseModel],
        crud_create_func: Callable = None,
        crud_read_func: Callable = None,
        crud_update_func: Callable = None,
        crud_delete_func: Callable = None,
        entity_id: str = None,
        operation: str = "create",
        key: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        id_field: str = None,
        **kwargs,
    ) -> Optional[Any]:
        """
        Render a complete CRUD form based on the specified operation.
        
        This is a convenience method that combines all CRUD operations
        into a single interface.
        
        Args:
            model: Pydantic model class
            crud_create_func: Function for create operation
            crud_read_func: Function for read operation
            crud_update_func: Function for update operation
            crud_delete_func: Function for delete operation
            entity_id: ID of entity (required for read, update, delete)
            operation: One of "create", "read", "update", "delete"
            key: Streamlit key prefix
            exclude_fields: Fields to exclude
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            id_field: Name of the ID field
            **kwargs: Additional arguments passed to CRUD functions
            
        Returns:
            Result of the operation (entity or bool for delete)
        """
        if operation == "create":
            if crud_create_func is None:
                st.error("Create function not provided")
                return None
            return CRUDFormRenderer.render_create_form(
                model=model,
                crud_create_func=crud_create_func,
                key=key,
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
                **kwargs,
            )
        
        elif operation == "read":
            if crud_read_func is None:
                st.error("Read function not provided")
                return None
            if entity_id is None:
                st.error("Entity ID required for read operation")
                return None
            return CRUDFormRenderer.render_read_form(
                model=model,
                entity_id=entity_id,
                crud_read_func=crud_read_func,
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
                **kwargs,
            )
        
        elif operation == "update":
            if crud_read_func is None or crud_update_func is None:
                st.error("Read and Update functions required for update operation")
                return None
            if entity_id is None:
                st.error("Entity ID required for update operation")
                return None
            return CRUDFormRenderer.render_update_form(
                model=model,
                entity_id=entity_id,
                crud_read_func=crud_read_func,
                crud_update_func=crud_update_func,
                key=key,
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
                id_field=id_field,
                **kwargs,
            )
        
        elif operation == "delete":
            if crud_read_func is None or crud_delete_func is None:
                st.error("Read and Delete functions required for delete operation")
                return None
            if entity_id is None:
                st.error("Entity ID required for delete operation")
                return None
            return CRUDFormRenderer.render_delete_form(
                model=model,
                entity_id=entity_id,
                crud_read_func=crud_read_func,
                crud_delete_func=crud_delete_func,
                key=key,
                custom_labels=custom_labels,
                **kwargs,
            )
        
        else:
            st.error(f"Unknown operation: {operation!r}")
            return None
