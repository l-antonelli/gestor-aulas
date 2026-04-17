"""
Hierarchical Entity Viewer Component.

Provides UI components for rendering hierarchical entity views with
drill-down navigation, displaying parent-child relationships and
enabling navigation between related entities.

Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
"""

from dataclasses import dataclass, field
from typing import List, Optional, Type

import streamlit as st
from pydantic import BaseModel
from sqlmodel import Session

from src.services.crud_services import BaseCRUDService
from src.ui.breadcrumb_navigation import BreadcrumbNavigation
from src.ui.entity_context_manager import EntityContextManager


@dataclass
class HierarchyLevel:
    """
    Configuration for a level in the entity hierarchy.
    
    Attributes:
        model: The model class for this hierarchy level
        service: The CRUD service for this model
        display_fields: Fields to display in lists
        id_field: The primary key field name
        display_field: Field to use for display name
        icon: Optional emoji/icon for this entity type
        child_levels: Optional list of child hierarchy levels
    """
    model: Type[BaseModel]
    service: BaseCRUDService
    display_fields: List[str]
    id_field: str = "id"
    display_field: str = "nombre"
    icon: str = ""
    child_levels: List['HierarchyLevel'] = field(default_factory=list)


@dataclass
class ChildConfig:
    """
    Configuration for displaying child entities.
    
    Attributes:
        model: The child model class
        service: The CRUD service for the child model
        display_fields: Fields to display for each child
        foreign_key_field: Field in child that references parent
        id_field: The primary key field name
        display_field: Field to use for display name
        icon: Optional emoji/icon for this entity type
        allow_create: Whether to allow creating new children
        allow_edit: Whether to allow editing children
        allow_delete: Whether to allow deleting children
    """
    model: Type[BaseModel]
    service: BaseCRUDService
    display_fields: List[str]
    foreign_key_field: str
    id_field: str = "id"
    display_field: str = "nombre"
    icon: str = ""
    allow_create: bool = True
    allow_edit: bool = True
    allow_delete: bool = True


class HierarchicalEntityViewer:
    """
    Renders hierarchical entity views with drill-down navigation.
    
    This component enables viewing entities in their hierarchical context,
    supporting navigation from parent to child entities while maintaining
    breadcrumb navigation and context preservation.
    
    Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6
    """
    
    @staticmethod
    def render_entity_hierarchy(
        root_model: Type[BaseModel],
        root_service: BaseCRUDService,
        hierarchy_config: List[HierarchyLevel],
        session: Session,
        entity_id: Optional[str] = None,
        display_fields: Optional[List[str]] = None,
        id_field: str = "id",
        display_field: str = "nombre",
        icon: str = "",
    ) -> None:
        """
        Render a hierarchical view starting from root entity.
        
        If entity_id is provided, shows that specific entity with its children.
        Otherwise, shows a list of all root entities.
        
        Args:
            root_model: The root model class (e.g., Carrera)
            root_service: The CRUD service for the root model
            hierarchy_config: Configuration for each level of hierarchy
            session: Database session
            entity_id: Optional ID to start from a specific entity
            display_fields: Fields to display for root entities
            id_field: The primary key field name
            display_field: Field to use for display name
            icon: Optional emoji/icon for root entity type
        """
        # Render breadcrumb navigation
        BreadcrumbNavigation.render_breadcrumb()
        
        if entity_id:
            # Show specific entity with children
            entity = root_service.get(session, entity_id)
            if entity:
                # Find matching hierarchy config
                child_configs = HierarchicalEntityViewer._get_child_configs_for_model(
                    root_model, hierarchy_config
                )
                
                HierarchicalEntityViewer.render_entity_with_children(
                    entity=entity,
                    model=root_model,
                    child_configs=child_configs,
                    session=session,
                    id_field=id_field,
                    display_field=display_field,
                    icon=icon,
                )
            else:
                st.error(f"Entidad con ID '{entity_id}' no encontrada")
        else:
            # Show list of all root entities
            entities = root_service.get_all(session)
            
            if not entities:
                st.info(f"No hay {root_model.__name__} registrados")
                return
            
            st.subheader(f"📋 {root_model.__name__}s")
            
            for entity in entities:
                entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
                eid = str(entity_dict.get(id_field, ""))
                name = str(entity_dict.get(display_field, eid))
                
                # Display entity with drill-down button
                col1, col2 = st.columns([4, 1])
                
                with col1:
                    # Display configured fields
                    if display_fields:
                        parts = []
                        for f in display_fields:
                            if f in entity_dict:
                                parts.append(f"**{f}**: {entity_dict[f]}")
                        st.markdown(" | ".join(parts))
                    else:
                        st.markdown(f"**{name}** ({eid})")
                
                with col2:
                    if st.button(
                        "Ver →",
                        key=f"drill_{root_model.__name__}_{eid}",
                        use_container_width=True,
                    ):
                        HierarchicalEntityViewer.handle_drill_down(
                            entity=entity,
                            model=root_model,
                            id_field=id_field,
                            display_field=display_field,
                            icon=icon,
                        )
                        st.rerun()
                
                st.divider()
    
    @staticmethod
    def render_entity_with_children(
        entity: BaseModel,
        model: Type[BaseModel],
        child_configs: List[ChildConfig],
        session: Session,
        id_field: str = "id",
        display_field: str = "nombre",
        icon: str = "",
    ) -> None:
        """
        Render an entity with its child entities.
        
        Shows entity details followed by collapsible sections for each
        type of child entity.
        
        Args:
            entity: The entity instance to display
            model: The model class of the entity
            child_configs: Configuration for each type of child entity
            session: Database session
            id_field: The primary key field name
            display_field: Field to use for display name
            icon: Optional emoji/icon for this entity type
        """
        entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
        entity_id = str(entity_dict.get(id_field, ""))
        entity_name = str(entity_dict.get(display_field, entity_id))
        
        # Entity header
        header_icon = f"{icon} " if icon else ""
        st.header(f"{header_icon}{entity_name}")
        
        # Entity details
        with st.expander("📄 Detalles", expanded=True):
            for field_name, value in entity_dict.items():
                st.text(f"{field_name}: {value}")
        
        # Child entity sections
        for child_config in child_configs:
            HierarchicalEntityViewer._render_child_section(
                parent_entity=entity,
                parent_id=entity_id,
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
        Render a section for a specific type of child entity.
        
        Args:
            parent_entity: The parent entity instance
            parent_id: The parent entity ID
            child_config: Configuration for the child entity type
            session: Database session
        """
        child_model = child_config.model
        child_service = child_config.service
        
        # Get child count
        children_count = HierarchicalEntityViewer.render_child_summary(
            parent_id=parent_id,
            child_model=child_model,
            child_service=child_service,
            foreign_key_field=child_config.foreign_key_field,
            session=session,
        )
        
        # Section header with count
        child_icon = f"{child_config.icon} " if child_config.icon else ""
        section_title = f"{child_icon}{child_model.__name__} ({children_count})"
        
        with st.expander(section_title, expanded=children_count > 0):
            # Get children
            children = HierarchicalEntityViewer._get_children_for_parent(
                parent_id=parent_id,
                child_service=child_service,
                foreign_key_field=child_config.foreign_key_field,
                session=session,
            )
            
            if not children:
                st.info(f"No hay {child_model.__name__} asociados")
            else:
                # Display each child with drill-down option
                for child in children:
                    child_dict = child.model_dump() if hasattr(child, 'model_dump') else child.dict()
                    child_id = str(child_dict.get(child_config.id_field, ""))
                    child_name = str(child_dict.get(child_config.display_field, child_id))
                    
                    col1, col2, col3 = st.columns([3, 1, 1])
                    
                    with col1:
                        # Display configured fields
                        parts = []
                        for f in child_config.display_fields:
                            if f in child_dict:
                                parts.append(f"**{f}**: {child_dict[f]}")
                        st.markdown(" | ".join(parts) if parts else f"**{child_name}**")
                    
                    with col2:
                        if st.button(
                            "Ver →",
                            key=f"drill_{child_model.__name__}_{child_id}_{parent_id}",
                            use_container_width=True,
                        ):
                            HierarchicalEntityViewer.handle_drill_down(
                                entity=child,
                                model=child_model,
                                id_field=child_config.id_field,
                                display_field=child_config.display_field,
                                icon=child_config.icon,
                            )
                            st.rerun()
                    
                    with col3:
                        if child_config.allow_delete:
                            if st.button(
                                "🗑️",
                                key=f"delete_{child_model.__name__}_{child_id}_{parent_id}",
                                use_container_width=True,
                            ):
                                # Store delete confirmation state
                                confirm_key = f"confirm_delete_{child_model.__name__}_{child_id}"
                                st.session_state[confirm_key] = True
                    
                    st.divider()
            
            # Quick add button
            if child_config.allow_create:
                if st.button(
                    f"➕ Agregar {child_model.__name__}",
                    key=f"add_{child_model.__name__}_{parent_id}",
                    use_container_width=True,
                ):
                    # Store state to show creation form
                    state_key = f"show_create_{child_model.__name__}_{parent_id}"
                    st.session_state[state_key] = True
    
    @staticmethod
    def render_child_summary(
        parent_id: str,
        child_model: Type[BaseModel],
        child_service: BaseCRUDService,
        foreign_key_field: str,
        session: Session,
    ) -> int:
        """
        Render a summary of child entities with count.
        
        Args:
            parent_id: The parent entity's ID
            child_model: The child model class
            child_service: The CRUD service for the child model
            foreign_key_field: Field in child that references parent
            session: Database session
            
        Returns:
            The count of children.
        """
        children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id=parent_id,
            child_service=child_service,
            foreign_key_field=foreign_key_field,
            session=session,
        )
        return len(children)
    
    @staticmethod
    def _get_children_for_parent(
        parent_id: str,
        child_service: BaseCRUDService,
        foreign_key_field: str,
        session: Session,
    ) -> List[BaseModel]:
        """
        Get all child entities for a parent.
        
        Args:
            parent_id: The parent entity's ID
            child_service: The CRUD service for the child model
            foreign_key_field: Field in child that references parent
            session: Database session
            
        Returns:
            List of child domain model instances
        """
        # Get all children and filter by parent
        all_children = child_service.get_all(session)
        
        children = []
        for child in all_children:
            child_dict = child.model_dump() if hasattr(child, 'model_dump') else child.dict()
            if child_dict.get(foreign_key_field) == parent_id:
                children.append(child)
        
        return children

    
    @staticmethod
    def handle_drill_down(
        entity: BaseModel,
        model: Type[BaseModel],
        id_field: str = "id",
        display_field: str = "nombre",
        icon: str = "",
    ) -> None:
        """
        Handle drill-down navigation to a child entity.
        
        Updates session state to navigate to the selected entity,
        including breadcrumb and context updates.
        
        Args:
            entity: The entity to navigate to
            model: The model class of the entity
            id_field: The primary key field name
            display_field: Field to use for display name
            icon: Optional emoji/icon for this entity type
        """
        entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
        entity_id = str(entity_dict.get(id_field, ""))
        
        # Build breadcrumb item
        breadcrumb_item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=entity,
            model=model,
            display_field=display_field,
            icon=icon,
        )
        
        # Update breadcrumb navigation
        BreadcrumbNavigation.push_to_path(breadcrumb_item)
        
        # Update entity context
        EntityContextManager.set_selected_entity(
            model=model,
            entity_id=entity_id,
        )
    
    @staticmethod
    def _get_child_configs_for_model(
        model: Type[BaseModel],
        hierarchy_config: List[HierarchyLevel],
    ) -> List[ChildConfig]:
        """
        Get child configurations for a model from hierarchy config.
        
        Args:
            model: The model class to find children for
            hierarchy_config: The full hierarchy configuration
            
        Returns:
            List of ChildConfig for the model's children
        """
        child_configs = []
        
        for level in hierarchy_config:
            if level.model == model:
                # Found the model, convert child_levels to ChildConfigs
                for child_level in level.child_levels:
                    # We need to find the foreign key field
                    # Convention: parent_model_name + "_" + id_field (lowercase)
                    parent_name = model.__name__.lower()
                    fk_field = f"{parent_name}_{level.id_field}"
                    
                    # Check if the child model has this field
                    if fk_field not in child_level.model.model_fields:
                        # Try alternative naming conventions
                        fk_field = f"{parent_name}_codigo"
                        if fk_field not in child_level.model.model_fields:
                            fk_field = f"{parent_name}_id"
                    
                    child_configs.append(ChildConfig(
                        model=child_level.model,
                        service=child_level.service,
                        display_fields=child_level.display_fields,
                        foreign_key_field=fk_field,
                        id_field=child_level.id_field,
                        display_field=child_level.display_field,
                        icon=child_level.icon,
                    ))
                break
            
            # Recursively search in child levels
            if level.child_levels:
                child_configs = HierarchicalEntityViewer._get_child_configs_for_model(
                    model, level.child_levels
                )
                if child_configs:
                    break
        
        return child_configs
    
    @staticmethod
    def get_children_count(
        parent_id: str,
        child_service: BaseCRUDService,
        foreign_key_field: str,
        session: Session,
    ) -> int:
        """
        Get the count of child entities for a parent.
        
        This is a convenience method that returns just the count
        without fetching all child data.
        
        Args:
            parent_id: The parent entity's ID
            child_service: The CRUD service for the child model
            foreign_key_field: Field in child that references parent
            session: Database session
            
        Returns:
            The count of children
        """
        children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id=parent_id,
            child_service=child_service,
            foreign_key_field=foreign_key_field,
            session=session,
        )
        return len(children)
