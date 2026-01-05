"""
Breadcrumb Navigation Component.

Provides UI components for displaying and managing breadcrumb navigation
for hierarchical entity views, showing the current navigation path and
enabling navigation back to parent entities.
"""

from dataclasses import dataclass, field
from typing import Callable, List, Optional, Type

import streamlit as st
from pydantic import BaseModel


@dataclass
class BreadcrumbItem:
    """
    Represents an item in the breadcrumb trail.
    
    Attributes:
        model_name: The name of the model class (e.g., "Carrera", "Materia")
        entity_id: The unique identifier of the entity
        display_name: Human-readable name to display in the breadcrumb
        icon: Optional emoji/icon to display before the name
    """
    model_name: str
    entity_id: str
    display_name: str
    icon: str = ""
    
    def __eq__(self, other: object) -> bool:
        """Two breadcrumb items are equal if they have the same model_name and entity_id."""
        if not isinstance(other, BreadcrumbItem):
            return False
        return self.model_name == other.model_name and self.entity_id == other.entity_id
    
    def __hash__(self) -> int:
        """Hash based on model_name and entity_id."""
        return hash((self.model_name, self.entity_id))


class BreadcrumbNavigation:
    """
    Manages breadcrumb navigation for hierarchical entities.
    
    Uses Streamlit session state to persist the navigation path across
    page refreshes and interactions.
    """
    
    SESSION_KEY = "breadcrumb_path"
    
    @staticmethod
    def render_breadcrumb(
        navigation_path: Optional[List[BreadcrumbItem]] = None,
        on_navigate: Optional[Callable[[BreadcrumbItem], None]] = None,
    ) -> Optional[BreadcrumbItem]:
        """
        Render breadcrumb trail.
        
        Displays a clickable breadcrumb trail showing the current navigation
        path. When a breadcrumb item is clicked, navigates to that entity.
        
        Args:
            navigation_path: List of breadcrumb items representing the path.
                           If None, uses the path from session state.
            on_navigate: Optional callback when a breadcrumb item is clicked.
                        Receives the clicked BreadcrumbItem.
        
        Returns:
            The clicked BreadcrumbItem if navigation occurred, None otherwise.
        """
        # Get path from session state if not provided
        if navigation_path is None:
            navigation_path = BreadcrumbNavigation.get_current_path()
        
        if not navigation_path:
            return None
        
        clicked_item = None
        
        # Create breadcrumb container
        breadcrumb_parts = []
        
        for idx, item in enumerate(navigation_path):
            is_last = idx == len(navigation_path) - 1
            
            # Build display text with icon
            display_text = f"{item.icon} {item.display_name}" if item.icon else item.display_name
            
            if is_last:
                # Last item is not clickable, shown as current location
                breadcrumb_parts.append(f"**{display_text}**")
            else:
                breadcrumb_parts.append(display_text)
        
        # Render the breadcrumb trail
        breadcrumb_text = " > ".join(breadcrumb_parts)
        st.markdown(f"📍 {breadcrumb_text}")
        
        # Render clickable buttons for navigation (except last item)
        if len(navigation_path) > 1:
            cols = st.columns(len(navigation_path) - 1)
            
            for idx, item in enumerate(navigation_path[:-1]):
                with cols[idx]:
                    display_text = f"{item.icon} {item.display_name}" if item.icon else item.display_name
                    button_key = f"breadcrumb_nav_{item.model_name}_{item.entity_id}_{idx}"
                    
                    if st.button(
                        f"← {display_text}",
                        key=button_key,
                        help=f"Volver a {item.display_name}",
                        use_container_width=True,
                    ):
                        # Navigate to this item
                        BreadcrumbNavigation.pop_to_item(item)
                        clicked_item = item
                        
                        if on_navigate:
                            on_navigate(item)
        
        return clicked_item
    
    @staticmethod
    def push_to_path(item: BreadcrumbItem) -> None:
        """
        Add an item to the navigation path.
        
        Updates session state with the new path. If the item already exists
        in the path, navigates to that item instead of adding a duplicate.
        
        Args:
            item: The BreadcrumbItem to add to the path.
        """
        current_path = BreadcrumbNavigation.get_current_path()
        
        # Check if item already exists in path
        for idx, existing_item in enumerate(current_path):
            if existing_item == item:
                # Item exists, truncate path to this item
                BreadcrumbNavigation._set_path(current_path[:idx + 1])
                return
        
        # Add new item to path
        current_path.append(item)
        BreadcrumbNavigation._set_path(current_path)
    
    @staticmethod
    def pop_to_item(item: BreadcrumbItem) -> None:
        """
        Navigate back to a specific item in the path.
        
        Removes all items after the specified item from the path.
        
        Args:
            item: The BreadcrumbItem to navigate to.
        """
        current_path = BreadcrumbNavigation.get_current_path()
        
        # Find the item in the path
        for idx, existing_item in enumerate(current_path):
            if existing_item == item:
                # Truncate path to this item (inclusive)
                BreadcrumbNavigation._set_path(current_path[:idx + 1])
                return
        
        # Item not found, do nothing
        pass
    
    @staticmethod
    def get_current_path() -> List[BreadcrumbItem]:
        """
        Get the current navigation path from session state.
        
        Returns:
            List of BreadcrumbItem representing the current path.
            Returns empty list if no path is set.
        """
        if BreadcrumbNavigation.SESSION_KEY not in st.session_state:
            st.session_state[BreadcrumbNavigation.SESSION_KEY] = []
        
        return list(st.session_state[BreadcrumbNavigation.SESSION_KEY])
    
    @staticmethod
    def clear_path() -> None:
        """Clear the navigation path."""
        st.session_state[BreadcrumbNavigation.SESSION_KEY] = []
    
    @staticmethod
    def _set_path(path: List[BreadcrumbItem]) -> None:
        """
        Set the navigation path in session state.
        
        Args:
            path: The new navigation path.
        """
        st.session_state[BreadcrumbNavigation.SESSION_KEY] = path
    
    @staticmethod
    def build_breadcrumb_item(
        entity: BaseModel,
        model: Type[BaseModel],
        display_field: str = "nombre",
        icon: str = "",
    ) -> BreadcrumbItem:
        """
        Build a breadcrumb item from an entity.
        
        Extracts ID and display name from the entity to create a
        BreadcrumbItem.
        
        Args:
            entity: The entity instance to create a breadcrumb for.
            model: The model class of the entity.
            display_field: The field to use for the display name.
                          Defaults to "nombre".
            icon: Optional emoji/icon to display.
        
        Returns:
            A BreadcrumbItem representing the entity.
        """
        # Get entity data
        entity_dict = entity.model_dump() if hasattr(entity, 'model_dump') else entity.dict()
        
        # Extract entity ID (try common ID field names)
        entity_id = None
        for id_field in ['id', 'codigo', 'legajo']:
            if id_field in entity_dict:
                entity_id = str(entity_dict[id_field])
                break
        
        if entity_id is None:
            # Fallback: use first field value
            entity_id = str(list(entity_dict.values())[0]) if entity_dict else "unknown"
        
        # Extract display name
        display_name = str(entity_dict.get(display_field, entity_id))
        
        return BreadcrumbItem(
            model_name=model.__name__,
            entity_id=entity_id,
            display_name=display_name,
            icon=icon,
        )
    
    @staticmethod
    def get_current_entity() -> Optional[BreadcrumbItem]:
        """
        Get the current (last) entity in the navigation path.
        
        Returns:
            The last BreadcrumbItem in the path, or None if path is empty.
        """
        path = BreadcrumbNavigation.get_current_path()
        return path[-1] if path else None
    
    @staticmethod
    def get_parent_entity() -> Optional[BreadcrumbItem]:
        """
        Get the parent entity (second to last) in the navigation path.
        
        Returns:
            The parent BreadcrumbItem, or None if path has less than 2 items.
        """
        path = BreadcrumbNavigation.get_current_path()
        return path[-2] if len(path) >= 2 else None
    
    @staticmethod
    def is_at_root() -> bool:
        """
        Check if currently at the root level (no navigation path).
        
        Returns:
            True if the navigation path is empty or has only one item.
        """
        path = BreadcrumbNavigation.get_current_path()
        return len(path) <= 1
