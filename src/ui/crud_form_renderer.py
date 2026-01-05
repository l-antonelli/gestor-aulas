"""
CRUD Form Renderer Module.

Provides utilities for rendering complete CRUD forms with database integration,
combining form input, validation, and database operations.
"""

from typing import Any, Callable, Dict, List, Optional, Type

import streamlit as st
from pydantic import BaseModel, ValidationError
from sqlmodel import Session

from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer
from src.services.cascading_operations import CascadingOperations
from src.services.relationship_registry import RelationshipRegistry
from src.services.cross_entity_validator import CrossEntityValidator


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
        enable_cascading: bool = True,
        session: Session = None,
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
            enable_cascading: Whether to enable cascading entity creation
            session: Database session (required if enable_cascading=True)
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
                    
                    # Validate cross-entity constraints if session is provided
                    if session is not None:
                        validation_errors = CRUDFormRenderer._validate_cross_entity_constraints(
                            instance=instance,
                            model=model,
                            session=session,
                            operation="create",
                        )
                        
                        if validation_errors:
                            CRUDFormRenderer._display_constraint_errors(validation_errors)
                            return None
                    
                    # Check if cascading is enabled and session is provided
                    if enable_cascading and session is not None:
                        # Check if this model has cascading relationships
                        relationships = RelationshipRegistry.get_relationships_for_model(model)
                        has_cascading = any(r.cascading_create for r in relationships)
                        
                        if has_cascading:
                            # Use cascading creation
                            created, children = CascadingOperations.create_with_cascading(
                                parent_instance=instance,
                                parent_crud_func=crud_create_func,
                                session=session,
                            )
                            
                            # Display success message with cascading info
                            CRUDFormRenderer.show_operation_feedback(
                                operation="create",
                                success=True,
                                message=success_message,
                            )
                            
                            # Display confirmation for cascading entities
                            if children:
                                CRUDFormRenderer._show_cascading_confirmation(
                                    parent=created,
                                    children=children,
                                )
                            
                            return created
                    
                    # Standard creation (no cascading)
                    created = crud_create_func(session, instance)
                    
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
                    
                    # Validate cross-entity constraints if session is provided
                    if 'session' in kwargs:
                        validation_errors = CRUDFormRenderer._validate_cross_entity_constraints(
                            instance=updated_instance,
                            model=model,
                            session=kwargs['session'],
                            operation="update",
                            entity_id=entity_id,
                        )
                        
                        if validation_errors:
                            CRUDFormRenderer._display_constraint_errors(validation_errors)
                            return None
                    
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
        enable_cascading: bool = True,
        session: Session = None,
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
            enable_cascading: Whether to enable cascading deletion
            session: Database session (required if enable_cascading=True)
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
        
        # Check for related entities if cascading is enabled
        if enable_cascading and session is not None:
            relationships = RelationshipRegistry.get_relationships_for_model(model)
            
            # Check for restrict relationships
            restrict_warnings = []
            cascade_warnings = []
            
            for relationship in relationships:
                children = CascadingOperations._get_children(
                    parent_id=entity_id,
                    relationship=relationship,
                    session=session,
                )
                
                if children:
                    if relationship.delete_behavior == "restrict":
                        restrict_warnings.append(
                            f"⚠️ No se puede eliminar: existen {len(children)} "
                            f"{relationship.get_child_model_name()} relacionados"
                        )
                    elif relationship.delete_behavior == "cascade":
                        cascade_warnings.append(
                            f"🔗 Se eliminarán también {len(children)} "
                            f"{relationship.get_child_model_name()} relacionados"
                        )
            
            # Show restrict warnings (these prevent deletion)
            if restrict_warnings:
                for warning in restrict_warnings:
                    st.error(warning)
                st.info("Elimine primero las entidades relacionadas antes de continuar.")
                return False
            
            # Show cascade warnings (these are informational)
            if cascade_warnings:
                st.warning("⚠️ Eliminación en cascada:")
                for warning in cascade_warnings:
                    st.markdown(f"- {warning}")
        
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
                    # Use cascading deletion if enabled
                    if enable_cascading and session is not None:
                        result = CascadingOperations.delete_with_cascading(
                            parent_id=entity_id,
                            parent_model=model,
                            parent_crud_func=crud_delete_func,
                            session=session,
                        )
                    else:
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
                        
                except ValueError as e:
                    # Handle restrict behavior errors
                    CRUDFormRenderer.show_operation_feedback(
                        operation="delete",
                        success=False,
                        message=str(e),
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

    @staticmethod
    def _show_cascading_confirmation(
        parent: BaseModel,
        children: List[BaseModel],
    ) -> None:
        """
        Display confirmation message for cascading entity creation.
        
        Args:
            parent: The parent entity that was created
            children: List of child entities that were auto-created
        """
        if not children:
            return
        
        # Create a nice info box showing what was created
        with st.expander("✨ Entidades relacionadas creadas automáticamente", expanded=True):
            st.info(
                f"Se crearon automáticamente {len(children)} entidad(es) relacionada(s) "
                f"con {type(parent).__name__}."
            )
            
            for child in children:
                child_type = type(child).__name__
                child_id = CascadingOperations._get_primary_key_value(child)
                
                # Try to get a display name
                display_name = "Sin nombre"
                if hasattr(child, "nombre"):
                    display_name = child.nombre
                elif hasattr(child, "name"):
                    display_name = child.name
                
                st.markdown(f"- **{child_type}**: {display_name} (ID: {child_id})")

    @staticmethod
    def _validate_cross_entity_constraints(
        instance: BaseModel,
        model: Type[BaseModel],
        session: Session,
        operation: str = "create",
        entity_id: str = None,
    ) -> List[str]:
        """
        Validate cross-entity constraints for an instance.
        
        Args:
            instance: The entity instance to validate
            model: The model class
            session: Database session for querying related entities
            operation: Operation type ("create" or "update")
            entity_id: Entity ID (for update operations)
        
        Returns:
            List of validation error messages (empty if valid)
        """
        from sqlmodel import select
        
        errors = []
        
        # Get relationships where this model is a child
        # We need to check if this instance violates any parent constraints
        all_relationships = RelationshipRegistry.get_all_relationships()
        
        for relationship in all_relationships:
            # Check if this model is the child in the relationship
            if relationship.child_model != model:
                continue
            
            # Get the foreign key value
            foreign_key_field = relationship.foreign_key_field
            if not hasattr(instance, foreign_key_field):
                continue
            
            parent_id = getattr(instance, foreign_key_field)
            if parent_id is None:
                continue
            
            # Get the parent instance
            parent_model_db = CRUDFormRenderer._get_db_model_for_domain_model(
                relationship.parent_model
            )
            if parent_model_db is None:
                continue
            
            parent_instance = session.get(parent_model_db, parent_id)
            if parent_instance is None:
                errors.append(
                    f"Parent {relationship.get_parent_model_name()} with ID '{parent_id}' not found"
                )
                continue
            
            # Get all sibling instances (other children of the same parent)
            child_model_db = CRUDFormRenderer._get_db_model_for_domain_model(
                relationship.child_model
            )
            if child_model_db is None:
                continue
            
            # Query all children
            statement = select(child_model_db).where(
                getattr(child_model_db, foreign_key_field) == parent_id
            )
            all_children = list(session.exec(statement).all())
            
            # For update operations, exclude the current instance
            if operation == "update" and entity_id:
                all_children = [
                    child for child in all_children
                    if CRUDFormRenderer._get_entity_id(child) != entity_id
                ]
            
            # Add the new/updated instance to the list for validation
            # Convert instance to DB model if needed
            instance_db = CRUDFormRenderer._convert_to_db_model(instance, child_model_db)
            all_children.append(instance_db)
            
            # Run validation rules from relationship metadata
            if relationship.validation_rules:
                is_valid, rule_errors = CrossEntityValidator.validate_relationship(
                    parent_instance=parent_instance,
                    child_instance=instance_db,
                    validation_rules=relationship.validation_rules,
                )
                if not is_valid:
                    errors.extend(rule_errors)
            
            # Check sum constraints (e.g., sum of comision cupos <= materia cupo)
            # This is a common pattern, so we check if both parent and child have a "cupo" field
            if hasattr(parent_instance, "cupo") and hasattr(instance_db, "cupo"):
                is_valid, error_msg = CrossEntityValidator.validate_sum_constraint(
                    parent_instance=parent_instance,
                    child_instances=all_children,
                    parent_field="cupo",
                    child_field="cupo",
                )
                if not is_valid:
                    errors.append(error_msg)
                    # Add suggestions
                    suggestions = CrossEntityValidator.get_constraint_suggestions(
                        parent_instance=parent_instance,
                        child_instances=all_children,
                        validation_error=error_msg,
                    )
                    errors.extend([f"💡 Sugerencia: {s}" for s in suggestions])
        
        return errors
    
    @staticmethod
    def _display_constraint_errors(errors: List[str]) -> None:
        """
        Display constraint violation errors with suggestions.
        
        Args:
            errors: List of error messages
        """
        st.error("❌ Errores de validación de restricciones:")
        
        for error in errors:
            if error.startswith("💡"):
                st.info(error)
            else:
                st.markdown(f"- {error}")
    
    @staticmethod
    def _get_db_model_for_domain_model(domain_model: Type[BaseModel]) -> Optional[Type]:
        """
        Get the corresponding database model for a domain model.
        
        Args:
            domain_model: The domain model class
        
        Returns:
            The database model class or None if not found
        """
        from src.database.models import (
            MateriaDB, ComisionDB, AlumnoDB, ClaseDB, AulaDB,
            InscripcionDB, AsistenciaDB, AsignacionAulaDB,
            HorarioCronogramaDB, CarreraDB, ProfesorDB, CicloDB, DictadoDB
        )
        from src.domain.problem.materia import Materia
        from src.domain.problem.comision import Comision
        from src.domain.problem.alumno import Alumno
        from src.domain.problem.clase import Clase
        from src.domain.problem.aula import Aula
        from src.domain.solution.inscripcion import Inscripcion
        from src.domain.solution.asistencia import Asistencia
        from src.domain.solution.asignacion_aula import AsignacionAula
        
        # Mapping from domain models to DB models
        mapping = {
            Materia: MateriaDB,
            Comision: ComisionDB,
            Alumno: AlumnoDB,
            Clase: ClaseDB,
            Aula: AulaDB,
            Inscripcion: InscripcionDB,
            Asistencia: AsistenciaDB,
            AsignacionAula: AsignacionAulaDB,
        }
        
        # Also check by name for models that might be passed directly as DB models
        if domain_model in [MateriaDB, ComisionDB, AlumnoDB, ClaseDB, AulaDB,
                            InscripcionDB, AsistenciaDB, AsignacionAulaDB,
                            HorarioCronogramaDB, CarreraDB, ProfesorDB, CicloDB, DictadoDB]:
            return domain_model
        
        return mapping.get(domain_model)
    
    @staticmethod
    def _convert_to_db_model(instance: BaseModel, db_model: Type) -> Any:
        """
        Convert a domain model instance to a database model instance.
        
        Args:
            instance: The domain model instance
            db_model: The database model class
        
        Returns:
            Database model instance
        """
        # If already a DB model, return as is
        if isinstance(instance, db_model):
            return instance
        
        # Convert using model_dump
        if hasattr(instance, "model_dump"):
            data = instance.model_dump()
        else:
            data = dict(instance)
        
        return db_model(**data)
    
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
        for id_field in ["id", "codigo", "legajo"]:
            if hasattr(entity, id_field):
                return str(getattr(entity, id_field))
        
        return None

