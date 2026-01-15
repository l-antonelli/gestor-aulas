"""
Entity Page Template Module.

Provides a unified template for creating consistent entity pages with
standard structure: tabs for Listado, Crear, Ver Detalle.

Requirements: 4.1, 4.2, 4.4, 6.1, 6.2, 7.3
"""

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Type

import streamlit as st
from pydantic import BaseModel
from sqlmodel import Session

from src.services.crud_services import BaseCRUDService
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.hierarchical_entity_viewer import ChildConfig
from src.ui.relationship_selector import RelationshipSelector
from src.services.relationship_registry import RelationshipRegistry


@dataclass
class EntityPageConfig:
    """
    Configuration for an entity page.
    
    Attributes:
        model: The Pydantic model class for the entity
        service: The CRUD service for the entity
        page_title: Title to display on the page
        page_icon: Emoji/icon for the page
        display_fields: Fields to display in lists and tables
        custom_labels: Custom labels for fields (field_name -> label)
        id_field: Name of the primary key field
        display_field: Field to use for display name in selectors
        child_configs: Configuration for child entity sections
        enable_cascading: Whether to enable cascading operations
        enable_hierarchy_view: Whether to enable hierarchical view
        exclude_from_create: Fields to exclude from create form
        exclude_from_display: Fields to exclude from detail display
        crud_functions: Dictionary mapping model names to CRUD functions
    """
    model: Type[BaseModel]
    service: BaseCRUDService
    page_title: str
    page_icon: str
    display_fields: List[str]
    custom_labels: Dict[str, str] = field(default_factory=dict)
    id_field: str = "id"
    display_field: str = "nombre"
    child_configs: List[ChildConfig] = field(default_factory=list)
    enable_cascading: bool = True
    enable_hierarchy_view: bool = True
    exclude_from_create: List[str] = field(default_factory=list)
    exclude_from_display: List[str] = field(default_factory=list)
    crud_functions: Dict[str, Callable] = field(default_factory=dict)


class EntityPageTemplate:
    """
    Template for creating consistent entity pages.
    
    Provides a standard page structure with tabs for:
    - Listado: Display all entities in a table with delete option
    - Crear: Form for creating new entities
    - Ver Detalle: View entity details with nested children
    
    Requirements: 4.1, 4.2, 4.4, 6.1, 6.2, 7.3
    """
    
    @staticmethod
    def render_entity_page(
        config: EntityPageConfig,
        session: Session,
    ) -> None:
        """
        Render a complete entity page with standard structure.
        
        Creates tabs for: Listado, Crear, Ver Detalle
        
        Args:
            config: Configuration for the entity page
            session: Database session
        """
        # Page header
        st.title(f"{config.page_icon} {config.page_title}")
        
        # Create tabs
        tab_list, tab_create, tab_view = st.tabs([
            "📋 Listado",
            "➕ Crear",
            "👁️ Ver Detalle"
        ])
        
        with tab_list:
            EntityPageTemplate.render_list_tab(config, session)
        
        with tab_create:
            EntityPageTemplate.render_create_tab(config, session)
        
        with tab_view:
            EntityPageTemplate.render_detail_tab(config, session)
    
    @staticmethod
    def render_list_tab(
        config: EntityPageConfig,
        session: Session,
    ) -> None:
        """
        Render the list tab with entity table and delete option.
        
        Args:
            config: Configuration for the entity page
            session: Database session
        """
        # Get all entities
        entities = config.service.get_all(session)
        
        if not entities:
            st.info(f"No hay {config.model.__name__} registrados. Crea uno en la pestaña 'Crear'.")
            return
        
        # Build table data
        table_data = []
        for entity in entities:
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            
            row = {}
            for field_name in config.display_fields:
                if field_name in entity_dict:
                    # Use custom label if available
                    label = config.custom_labels.get(field_name, field_name.replace("_", " ").title())
                    row[label] = entity_dict[field_name]
            
            table_data.append(row)
        
        # Display table
        st.dataframe(table_data, use_container_width=True, hide_index=True)
        st.caption(f"Total: {len(table_data)} {config.model.__name__}")
        
        # Delete section
        st.divider()
        st.subheader(f"Eliminar {config.model.__name__}")
        
        # Build options for delete selector
        entity_options = []
        for entity in entities:
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            entity_id = str(entity_dict.get(config.id_field, ""))
            display_name = str(entity_dict.get(config.display_field, entity_id))
            entity_options.append((entity_id, display_name))
        
        col1, col2 = st.columns([3, 1])
        
        with col1:
            selected_id = st.selectbox(
                f"Seleccionar {config.model.__name__} a eliminar",
                options=[opt[0] for opt in entity_options],
                format_func=lambda x: f"{x} - {next((opt[1] for opt in entity_options if opt[0] == x), '')}",
                key=f"delete_{config.model.__name__}"
            )
        
        with col2:
            st.write("")
            st.write("")
            if st.button("🗑️ Eliminar", type="secondary", key=f"delete_btn_{config.model.__name__}"):
                try:
                    if config.enable_cascading:
                        result = config.service.delete_with_cascading(session, selected_id)
                    else:
                        result = config.service.delete(session, selected_id)
                    
                    if result:
                        st.success(f"{config.model.__name__} {selected_id} eliminado")
                        st.rerun()
                    else:
                        st.error(f"Error al eliminar {config.model.__name__}")
                except ValueError as e:
                    st.error(str(e))
                except Exception as e:
                    st.error(f"Error al eliminar: {str(e)}")

    
    @staticmethod
    def render_create_tab(
        config: EntityPageConfig,
        session: Session,
    ) -> None:
        """
        Render the create tab with form and relationship selectors.
        
        Args:
            config: Configuration for the entity page
            session: Database session
        """
        # Check for cascading info message
        if config.enable_cascading:
            from src.services.relationship_registry import RelationshipRegistry
            relationships = RelationshipRegistry.get_relationships_for_model(config.model)
            has_cascading = any(r.cascading_create for r in relationships)
            
            if has_cascading:
                st.info(f"💡 Al crear un {config.model.__name__} se generarán automáticamente entidades relacionadas.")
        
        # Check for success message in session state
        success_key = f"{config.model.__name__}_created"
        if st.session_state.get(success_key):
            created_info = st.session_state[success_key]
            st.success(f"✅ {config.model.__name__} '{created_info.get('display_name', '')}' creado exitosamente")
            
            if created_info.get('children'):
                st.info(f"🔗 Se crearon automáticamente {len(created_info['children'])} entidad(es) relacionada(s)")
            
            st.balloons()
            st.session_state[success_key] = None
        
        # Detect foreign key fields for relationship selectors
        foreign_keys = EntityPageTemplate._get_foreign_key_fields(config.model)
        
        # Get parent context for pre-population
        parent_context = EntityPageTemplate._get_parent_context_for_create(config)
        
        # Render create form
        form_key = f"create_{config.model.__name__}_form"
        
        with st.form(key=form_key):
            st.subheader(f"Crear {config.model.__name__}")
            
            form_data = {}
            
            # Get all fields from model
            fields = list(config.model.model_fields.keys())
            
            # Exclude specified fields
            fields_to_render = [f for f in fields if f not in config.exclude_from_create]
            
            for field_name in fields_to_render:
                # Check if this is a foreign key field
                if field_name in foreign_keys:
                    parent_model = foreign_keys[field_name]
                    
                    # Check if we have a pre-populated value from parent context
                    default_value = parent_context.get(field_name)
                    
                    # Render relationship selector
                    value = EntityPageTemplate._render_foreign_key_selector(
                        field_name=field_name,
                        parent_model=parent_model,
                        child_model=config.model,
                        session=session,
                        default_value=default_value,
                        custom_label=config.custom_labels.get(field_name),
                        crud_functions=config.crud_functions,
                    )
                    form_data[field_name] = value
                else:
                    # Render normal field input
                    value = FormInputRenderer.render_field_input(
                        model=config.model,
                        field_name=field_name,
                        key=f"{form_key}_{field_name}",
                        custom_label=config.custom_labels.get(field_name),
                        session=session,
                        crud_functions=config.crud_functions,
                    )
                    form_data[field_name] = value
            
            submitted = st.form_submit_button("💾 Guardar", type="primary")
            
            if submitted:
                # Validate required fields
                missing_fields = []
                for field_name, value in form_data.items():
                    field_info = config.model.model_fields.get(field_name)
                    if field_info and field_info.is_required():
                        if value is None or (isinstance(value, str) and not value.strip()):
                            missing_fields.append(field_name)
                
                if missing_fields:
                    st.error(f"❌ Por favor complete los campos obligatorios: {', '.join(missing_fields)}")
                    return
                
                try:
                    # Create model instance
                    instance = config.model(**form_data)
                    
                    # Create with or without cascading
                    if config.enable_cascading:
                        created, children = config.service.create_with_cascading(session, instance)
                        
                        # Store success info
                        entity_dict = created.model_dump() if hasattr(created, 'model_dump') else created.dict()
                        st.session_state[success_key] = {
                            'id': entity_dict.get(config.id_field),
                            'display_name': entity_dict.get(config.display_field, entity_dict.get(config.id_field)),
                            'children': [
                                {'type': type(c).__name__, 'id': str(getattr(c, 'id', getattr(c, 'codigo', '')))}
                                for c in children
                            ] if children else []
                        }
                    else:
                        created = config.service.create(session, instance)
                        
                        entity_dict = created.model_dump() if hasattr(created, 'model_dump') else created.dict()
                        st.session_state[success_key] = {
                            'id': entity_dict.get(config.id_field),
                            'display_name': entity_dict.get(config.display_field, entity_dict.get(config.id_field)),
                            'children': []
                        }
                    
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"❌ Error al crear: {str(e)}")

    
    @staticmethod
    def render_detail_tab(
        config: EntityPageConfig,
        session: Session,
    ) -> None:
        """
        Render the detail tab with entity view and nested children.
        
        Args:
            config: Configuration for the entity page
            session: Database session
        """
        # Get all entities for selector
        entities = config.service.get_all(session)
        
        if not entities:
            st.info(f"No hay {config.model.__name__} para ver.")
            return
        
        # Build options for selector
        entity_options = []
        for entity in entities:
            entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
            entity_id = str(entity_dict.get(config.id_field, ""))
            display_name = str(entity_dict.get(config.display_field, entity_id))
            entity_options.append((entity_id, display_name))
        
        # Entity selector
        selected_id = st.selectbox(
            f"Seleccionar {config.model.__name__}",
            options=[opt[0] for opt in entity_options],
            format_func=lambda x: f"{x} - {next((opt[1] for opt in entity_options if opt[0] == x), '')}",
            key=f"view_{config.model.__name__}"
        )
        
        if not selected_id:
            return
        
        # Get selected entity
        entity = config.service.get(session, selected_id)
        
        if not entity:
            st.error(f"{config.model.__name__} con ID '{selected_id}' no encontrado")
            return
        
        # Display entity details
        entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
        
        st.subheader(f"Detalle de {config.model.__name__}: {entity_dict.get(config.display_field, selected_id)}")
        
        # Display fields
        with st.expander("📄 Información", expanded=True):
            for field_name in config.display_fields:
                if field_name in entity_dict and field_name not in config.exclude_from_display:
                    label = config.custom_labels.get(field_name, field_name.replace("_", " ").title())
                    value = entity_dict[field_name]
                    st.text(f"{label}: {value}")
        
        # Display nested children if configured
        if config.child_configs and config.enable_hierarchy_view:
            st.divider()
            
            for child_config in config.child_configs:
                EntityPageTemplate._render_child_section(
                    parent_entity=entity,
                    parent_id=selected_id,
                    child_config=child_config,
                    session=session,
                )
    
    @staticmethod
    def _render_child_section(
        parent_entity: BaseModel,
        parent_id: str,
        child_config: ChildConfig,
        session: Session,
    ) -> None:
        """
        Render a section for child entities.
        
        Args:
            parent_entity: The parent entity instance
            parent_id: The parent entity ID
            child_config: Configuration for the child entity type
            session: Database session
        """
        child_model = child_config.model
        child_service = child_config.service
        
        # Get all children and filter by parent
        all_children = child_service.get_all(session)
        children = [
            c for c in all_children
            if (c.model_dump() if hasattr(c, 'model_dump') else c.dict()).get(child_config.foreign_key_field) == parent_id
        ]
        
        # Section header with count
        child_icon = f"{child_config.icon} " if child_config.icon else ""
        section_title = f"{child_icon}{child_model.__name__} ({len(children)})"
        
        with st.expander(section_title, expanded=len(children) > 0):
            if not children:
                st.info(f"No hay {child_model.__name__} asociados")
            else:
                # Display each child
                for child in children:
                    child_dict = child.model_dump() if hasattr(child, 'model_dump') else child.dict()
                    child_id = str(child_dict.get(child_config.id_field, ""))
                    
                    # Check if we're editing this child
                    edit_key = f"edit_{child_model.__name__}_{child_id}_{parent_id}"
                    is_editing = st.session_state.get(edit_key, False)
                    
                    if is_editing:
                        # Render inline edit form
                        EntityPageTemplate._render_inline_edit_form(
                            child=child,
                            child_id=child_id,
                            parent_id=parent_id,
                            child_config=child_config,
                            session=session,
                        )
                    else:
                        col1, col2, col3 = st.columns([3, 1, 1])
                        
                        with col1:
                            # Display configured fields
                            parts = []
                            for f in child_config.display_fields:
                                if f in child_dict:
                                    parts.append(f"**{f}**: {child_dict[f]}")
                            st.markdown(" | ".join(parts) if parts else f"ID: {child_id}")
                        
                        with col2:
                            if child_config.allow_edit:
                                if st.button(
                                    "✏️",
                                    key=f"edit_btn_{child_model.__name__}_{child_id}_{parent_id}",
                                    help="Editar",
                                ):
                                    st.session_state[edit_key] = True
                                    st.rerun()
                        
                        with col3:
                            if child_config.allow_delete:
                                if st.button(
                                    "🗑️",
                                    key=f"delete_child_{child_model.__name__}_{child_id}_{parent_id}",
                                    help="Eliminar",
                                ):
                                    try:
                                        child_service.delete(session, child_id)
                                        st.success(f"{child_model.__name__} eliminado")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {str(e)}")
                    
                    st.divider()
            
            # Quick add button
            if child_config.allow_create:
                add_key = f"show_add_{child_model.__name__}_{parent_id}"
                
                if st.button(
                    f"➕ Agregar {child_model.__name__}",
                    key=f"add_btn_{child_model.__name__}_{parent_id}",
                    use_container_width=True,
                ):
                    st.session_state[add_key] = True
                
                # Show inline create form if button was clicked
                if st.session_state.get(add_key, False):
                    EntityPageTemplate._render_inline_create_form(
                        parent_id=parent_id,
                        child_config=child_config,
                        session=session,
                    )

    
    @staticmethod
    def _render_inline_create_form(
        parent_id: str,
        child_config: ChildConfig,
        session: Session,
    ) -> None:
        """
        Render an inline form for creating a child entity.
        
        Pre-populates the foreign key field with the parent ID.
        
        Args:
            parent_id: The parent entity ID
            child_config: Configuration for the child entity type
            session: Database session
        """
        child_model = child_config.model
        form_key = f"inline_create_{child_model.__name__}_{parent_id}"
        
        st.markdown("---")
        st.markdown(f"**Crear nuevo {child_model.__name__}**")
        
        with st.form(key=form_key):
            form_data = {}
            
            # Get all fields from model
            fields = list(child_model.model_fields.keys())
            
            for field_name in fields:
                if field_name == child_config.foreign_key_field:
                    # Pre-populate and show as read-only
                    st.text_input(
                        field_name.replace("_", " ").title(),
                        value=parent_id,
                        disabled=True,
                        key=f"{form_key}_{field_name}_display",
                    )
                    form_data[field_name] = parent_id
                else:
                    # Render normal field input
                    value = FormInputRenderer.render_field_input(
                        model=child_model,
                        field_name=field_name,
                        key=f"{form_key}_{field_name}",
                        session=session,
                    )
                    form_data[field_name] = value
            
            col1, col2 = st.columns(2)
            
            with col1:
                cancel = st.form_submit_button("Cancelar", use_container_width=True)
            
            with col2:
                submit = st.form_submit_button("Crear", type="primary", use_container_width=True)
            
            if cancel:
                add_key = f"show_add_{child_model.__name__}_{parent_id}"
                st.session_state[add_key] = False
                st.rerun()
            
            if submit:
                try:
                    # Validate cross-entity constraints before creating
                    validation_errors = EntityPageTemplate._validate_child_cupo_constraint(
                        parent_id=parent_id,
                        child_config=child_config,
                        form_data=form_data,
                        session=session,
                        operation="create",
                    )
                    
                    if validation_errors:
                        for error in validation_errors:
                            if error.startswith("💡"):
                                st.info(error)
                            else:
                                st.error(error)
                        return
                    
                    instance = child_model(**form_data)
                    child_config.service.create(session, instance)
                    
                    add_key = f"show_add_{child_model.__name__}_{parent_id}"
                    st.session_state[add_key] = False
                    
                    st.success(f"✅ {child_model.__name__} creado exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al crear: {str(e)}")
    
    @staticmethod
    def _render_inline_edit_form(
        child: BaseModel,
        child_id: str,
        parent_id: str,
        child_config: ChildConfig,
        session: Session,
    ) -> None:
        """
        Render an inline form for editing a child entity.
        
        Args:
            child: The child entity instance to edit
            child_id: The child entity ID
            parent_id: The parent entity ID
            child_config: Configuration for the child entity type
            session: Database session
        """
        child_model = child_config.model
        form_key = f"inline_edit_{child_model.__name__}_{child_id}_{parent_id}"
        edit_key = f"edit_{child_model.__name__}_{child_id}_{parent_id}"
        
        # Get current values
        child_dict = child.model_dump() if hasattr(child, 'model_dump') else child.dict()
        
        st.markdown(f"**Editar {child_model.__name__}**")
        
        with st.form(key=form_key):
            form_data = {}
            
            # Get all fields from model
            fields = list(child_model.model_fields.keys())
            
            for field_name in fields:
                current_value = child_dict.get(field_name)
                
                if field_name == child_config.id_field:
                    # Show ID as read-only
                    st.text_input(
                        field_name.replace("_", " ").title(),
                        value=str(current_value) if current_value else "",
                        disabled=True,
                        key=f"{form_key}_{field_name}_display",
                    )
                    form_data[field_name] = current_value
                elif field_name == child_config.foreign_key_field:
                    # Show foreign key as read-only
                    st.text_input(
                        field_name.replace("_", " ").title(),
                        value=parent_id,
                        disabled=True,
                        key=f"{form_key}_{field_name}_display",
                    )
                    form_data[field_name] = parent_id
                else:
                    # Render normal field input with current value as default
                    value = FormInputRenderer.render_field_input(
                        model=child_model,
                        field_name=field_name,
                        key=f"{form_key}_{field_name}",
                        default_value=current_value,
                        session=session,
                    )
                    form_data[field_name] = value
            
            col1, col2 = st.columns(2)
            
            with col1:
                cancel = st.form_submit_button("Cancelar", use_container_width=True)
            
            with col2:
                submit = st.form_submit_button("Guardar", type="primary", use_container_width=True)
            
            if cancel:
                st.session_state[edit_key] = False
                st.rerun()
            
            if submit:
                try:
                    # Validate cross-entity constraints before updating
                    validation_errors = EntityPageTemplate._validate_child_cupo_constraint(
                        parent_id=parent_id,
                        child_config=child_config,
                        form_data=form_data,
                        session=session,
                        operation="update",
                        exclude_child_id=child_id,
                    )
                    
                    if validation_errors:
                        for error in validation_errors:
                            if error.startswith("💡"):
                                st.info(error)
                            else:
                                st.error(error)
                        return
                    
                    instance = child_model(**form_data)
                    child_config.service.update(session, instance)
                    
                    st.session_state[edit_key] = False
                    
                    st.success(f"✅ {child_model.__name__} actualizado exitosamente")
                    st.rerun()
                except Exception as e:
                    st.error(f"❌ Error al actualizar: {str(e)}")
    
    @staticmethod
    def _validate_child_cupo_constraint(
        parent_id: str,
        child_config: ChildConfig,
        form_data: Dict[str, Any],
        session: Session,
        operation: str = "create",
        exclude_child_id: str = None,
    ) -> List[str]:
        """
        Validate cupo constraint for child entities.
        
        Ensures that the sum of child cupos doesn't exceed parent cupo.
        
        Args:
            parent_id: The parent entity ID
            child_config: Configuration for the child entity type
            form_data: Form data for the new/updated child
            session: Database session
            operation: "create" or "update"
            exclude_child_id: Child ID to exclude (for updates)
            
        Returns:
            List of validation error messages (empty if valid)
        """
        from src.services.relationship_registry import RelationshipRegistry
        
        errors = []
        child_model = child_config.model
        
        # Check if child has a cupo field
        if "cupo" not in form_data:
            return errors
        
        new_cupo = form_data.get("cupo")
        if new_cupo is None:
            return errors
        
        # Find the relationship to get parent model
        all_relationships = RelationshipRegistry.get_all_relationships()
        parent_model = None
        
        for rel in all_relationships:
            if rel.child_model == child_model and rel.foreign_key_field == child_config.foreign_key_field:
                parent_model = rel.parent_model
                break
        
        if parent_model is None:
            return errors
        
        # Get parent service
        from src.services.crud_services import (
            materia_service, comision_service, clase_service,
            alumno_service, aula_service, horario_service, carrera_service
        )
        
        service_map = {
            'Materia': materia_service,
            'Comision': comision_service,
            'Clase': clase_service,
            'Alumno': alumno_service,
            'Aula': aula_service,
            'HorarioCronograma': horario_service,
            'Carrera': carrera_service,
        }
        
        parent_service = service_map.get(parent_model.__name__)
        if parent_service is None:
            return errors
        
        # Get parent instance
        parent_instance = parent_service.get(session, parent_id)
        if parent_instance is None:
            return errors
        
        # Check if parent has cupo field and if it's not None
        if not hasattr(parent_instance, "cupo"):
            return errors
        
        parent_cupo = getattr(parent_instance, "cupo", None)
        if parent_cupo is None:
            # No limit set on parent, skip validation
            return errors
        
        # Get all existing children
        all_children = child_config.service.get_all(session)
        siblings = [
            c for c in all_children
            if (c.model_dump() if hasattr(c, 'model_dump') else c.dict()).get(child_config.foreign_key_field) == parent_id
        ]
        
        # For updates, exclude the current child
        if operation == "update" and exclude_child_id:
            siblings = [
                c for c in siblings
                if str((c.model_dump() if hasattr(c, 'model_dump') else c.dict()).get(child_config.id_field, "")) != exclude_child_id
            ]
        
        # Calculate sum of existing sibling cupos
        existing_sum = 0
        for sibling in siblings:
            sibling_dict = sibling.model_dump() if hasattr(sibling, 'model_dump') else sibling.dict()
            sibling_cupo = sibling_dict.get("cupo", 0)
            if sibling_cupo is not None:
                existing_sum += sibling_cupo
        
        # Check if new total exceeds parent cupo
        new_total = existing_sum + new_cupo
        
        if new_total > parent_cupo:
            available = parent_cupo - existing_sum
            errors.append(
                f"❌ La suma de cupos de {child_model.__name__} ({new_total}) "
                f"excede el cupo de {parent_model.__name__} ({parent_cupo})"
            )
            errors.append(
                f"💡 Sugerencia: El cupo máximo disponible es {available}. "
                f"Reduzca el cupo a {available} o menos."
            )
            errors.append(
                f"💡 Sugerencia: Alternativamente, aumente el cupo de {parent_model.__name__} "
                f"de {parent_cupo} a al menos {new_total}."
            )
        
        return errors
    
    @staticmethod
    def _get_foreign_key_fields(model: Type[BaseModel]) -> Dict[str, Type[BaseModel]]:
        """
        Detect foreign key fields in a model by checking registered relationships.
        
        Args:
            model: The model class to check for foreign keys
            
        Returns:
            Dictionary mapping foreign key field names to parent model classes
        """
        return RelationshipSelector.get_foreign_key_fields(model)
    
    @staticmethod
    def _render_foreign_key_selector(
        field_name: str,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel],
        session: Session,
        default_value: Any = None,
        custom_label: str = None,
        crud_functions: Dict[str, Callable] = None,
    ) -> Any:
        """
        Render a relationship selector for a foreign key field.
        
        Args:
            field_name: Name of the foreign key field
            parent_model: The parent model class
            child_model: The child model class
            session: Database session
            default_value: Default value to pre-populate
            custom_label: Custom label for the field
            crud_functions: Dictionary mapping model names to CRUD functions
            
        Returns:
            Selected entity ID
        """
        crud_functions = crud_functions or {}
        parent_model_name = parent_model.__name__
        
        # Get CRUD function for parent model
        crud_func = crud_functions.get(parent_model_name)
        
        if crud_func is None:
            # Try to get from service registry
            from src.services.crud_services import (
                materia_service, comision_service, clase_service,
                alumno_service, aula_service, horario_service
            )
            
            service_map = {
                'Materia': lambda s: materia_service.get_all(s),
                'Comision': lambda s: comision_service.get_all(s),
                'Clase': lambda s: clase_service.get_all(s),
                'Alumno': lambda s: alumno_service.get_all(s),
                'Aula': lambda s: aula_service.get_all(s),
                'HorarioCronograma': lambda s: horario_service.get_all(s),
            }
            
            crud_func = service_map.get(parent_model_name)
        
        if crud_func is None:
            # Fallback to text input
            label = custom_label or field_name.replace("_", " ").title()
            return st.text_input(label, value=default_value or "", key=f"fk_{field_name}")
        
        # Get relationship metadata
        relationship = RelationshipRegistry.get_relationship(parent_model, child_model)
        
        label = custom_label or field_name.replace("_", " ").title()
        
        # Use searchable selector if search fields are defined
        if relationship and relationship.search_fields:
            return RelationshipSelector.render_searchable_selector(
                field_name=field_name,
                parent_model=parent_model,
                child_model=child_model,
                crud_func=crud_func,
                session=session,
                search_fields=relationship.search_fields,
                default_value=default_value,
                key=f"fk_selector_{field_name}",
                label=label,
            )
        else:
            return RelationshipSelector.render_relationship_selector(
                field_name=field_name,
                parent_model=parent_model,
                child_model=child_model,
                crud_func=crud_func,
                session=session,
                default_value=default_value,
                key=f"fk_selector_{field_name}",
                label=label,
            )
    
    @staticmethod
    def _get_parent_context_for_create(config: EntityPageConfig) -> Dict[str, Any]:
        """
        Get parent context values for pre-populating foreign key fields.
        
        Checks entity context manager for parent entity information.
        
        Args:
            config: Configuration for the entity page
            
        Returns:
            Dictionary mapping field names to pre-populated values
        """
        from src.ui.entity_context_manager import EntityContextManager
        
        pre_populated = {}
        
        # Get current context
        context = EntityContextManager.get_context()
        if context is None:
            return pre_populated
        
        # Get foreign key fields for this model
        foreign_keys = EntityPageTemplate._get_foreign_key_fields(config.model)
        
        # Check if any foreign key matches the parent context
        for fk_field, parent_model in foreign_keys.items():
            if parent_model.__name__ == context.model_name:
                pre_populated[fk_field] = context.entity_id
        
        return pre_populated
