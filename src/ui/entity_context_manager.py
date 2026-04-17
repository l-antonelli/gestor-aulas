"""
Entity Context Manager.

Manages entity navigation context in Streamlit session state,
preserving parent context for back navigation and maintaining
view state across interactions.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple, Type

import streamlit as st
from pydantic import BaseModel


@dataclass
class EntityContext:
    """
    Represents the current entity navigation context.
    
    Attributes:
        model_name: The name of the model class (e.g., "Carrera", "Materia")
        entity_id: The unique identifier of the entity
        parent_context: Optional parent context for back navigation
        view_state: Optional dictionary to store view-specific state
    """
    model_name: str
    entity_id: str
    parent_context: Optional['EntityContext'] = None
    view_state: Dict[str, Any] = field(default_factory=dict)
    
    def __eq__(self, other: object) -> bool:
        """Two contexts are equal if they have the same model_name and entity_id."""
        if not isinstance(other, EntityContext):
            return False
        return self.model_name == other.model_name and self.entity_id == other.entity_id
    
    def __hash__(self) -> int:
        """Hash based on model_name and entity_id."""
        return hash((self.model_name, self.entity_id))
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert context to dictionary for serialization."""
        result = {
            "model_name": self.model_name,
            "entity_id": self.entity_id,
            "view_state": self.view_state,
        }
        if self.parent_context is not None:
            result["parent_context"] = self.parent_context.to_dict()
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'EntityContext':
        """Create context from dictionary."""
        parent_context = None
        if "parent_context" in data and data["parent_context"] is not None:
            parent_context = cls.from_dict(data["parent_context"])
        
        return cls(
            model_name=data["model_name"],
            entity_id=data["entity_id"],
            parent_context=parent_context,
            view_state=data.get("view_state", {}),
        )


class EntityContextManager:
    """
    Manages entity navigation context in session state.
    
    Uses Streamlit session state to persist the navigation context
    across page refreshes and interactions. Supports hierarchical
    navigation with parent context preservation.
    """
    
    SESSION_KEY = "entity_context"
    
    @staticmethod
    def get_context() -> Optional[EntityContext]:
        """
        Get the current entity context from session state.
        
        Returns:
            The current EntityContext, or None if no context is set.
        """
        if EntityContextManager.SESSION_KEY not in st.session_state:
            return None
        
        context_data = st.session_state[EntityContextManager.SESSION_KEY]
        if context_data is None:
            return None
        
        # Handle both dict and EntityContext objects
        if isinstance(context_data, EntityContext):
            return context_data
        elif isinstance(context_data, dict):
            return EntityContext.from_dict(context_data)
        
        return None
    
    @staticmethod
    def set_context(context: Optional[EntityContext]) -> None:
        """
        Set the entity context in session state.
        
        Args:
            context: The EntityContext to set, or None to clear.
        """
        if context is None:
            st.session_state[EntityContextManager.SESSION_KEY] = None
        else:
            # Store as dict for serialization compatibility
            st.session_state[EntityContextManager.SESSION_KEY] = context.to_dict()
    
    @staticmethod
    def set_selected_entity(
        model: Type[BaseModel],
        entity_id: str,
        parent_context: Optional[EntityContext] = None,
        view_state: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Set the currently selected entity.
        
        Preserves parent context for back navigation. If no parent_context
        is provided, the current context becomes the parent.
        
        Args:
            model: The model class of the entity.
            entity_id: The unique identifier of the entity.
            parent_context: Optional parent context. If None and there's
                          a current context, it becomes the parent.
            view_state: Optional view-specific state to preserve.
        """
        # Get current context to use as parent if not provided
        current_context = EntityContextManager.get_context()
        
        # Determine parent context
        if parent_context is None and current_context is not None:
            # Use current context as parent
            effective_parent = current_context
        else:
            effective_parent = parent_context
        
        # Create new context
        new_context = EntityContext(
            model_name=model.__name__,
            entity_id=entity_id,
            parent_context=effective_parent,
            view_state=view_state or {},
        )
        
        EntityContextManager.set_context(new_context)
    
    @staticmethod
    def get_selected_entity() -> Optional[Tuple[str, str]]:
        """
        Get the currently selected entity.
        
        Returns:
            A tuple of (model_name, entity_id), or None if no entity is selected.
        """
        context = EntityContextManager.get_context()
        if context is None:
            return None
        
        return (context.model_name, context.entity_id)
    
    @staticmethod
    def get_parent_context() -> Optional[EntityContext]:
        """
        Get the parent context for back navigation.
        
        Returns:
            The parent EntityContext, or None if at root level.
        """
        context = EntityContextManager.get_context()
        if context is None:
            return None
        
        return context.parent_context
    
    @staticmethod
    def clear_context() -> None:
        """Clear all entity context."""
        st.session_state[EntityContextManager.SESSION_KEY] = None
    
    @staticmethod
    def navigate_to_parent() -> Optional[EntityContext]:
        """
        Navigate to the parent context.
        
        Sets the current context to the parent context, effectively
        going back one level in the hierarchy.
        
        Returns:
            The new current context (the former parent), or None if at root.
        """
        parent = EntityContextManager.get_parent_context()
        EntityContextManager.set_context(parent)
        return parent
    
    @staticmethod
    def get_context_depth() -> int:
        """
        Get the depth of the current context hierarchy.
        
        Returns:
            The number of levels in the context hierarchy (0 if no context).
        """
        context = EntityContextManager.get_context()
        depth = 0
        
        while context is not None:
            depth += 1
            context = context.parent_context
        
        return depth
    
    @staticmethod
    def get_context_chain() -> list[EntityContext]:
        """
        Get the full chain of contexts from root to current.
        
        Returns:
            List of EntityContext from root (first) to current (last).
        """
        context = EntityContextManager.get_context()
        chain = []
        
        # Build chain from current to root
        while context is not None:
            chain.append(context)
            context = context.parent_context
        
        # Reverse to get root-to-current order
        chain.reverse()
        return chain
    
    @staticmethod
    def update_view_state(key: str, value: Any) -> None:
        """
        Update a value in the current context's view state.
        
        Args:
            key: The key to update.
            value: The value to set.
        """
        context = EntityContextManager.get_context()
        if context is None:
            return
        
        context.view_state[key] = value
        EntityContextManager.set_context(context)
    
    @staticmethod
    def get_view_state(key: str, default: Any = None) -> Any:
        """
        Get a value from the current context's view state.
        
        Args:
            key: The key to retrieve.
            default: Default value if key not found.
        
        Returns:
            The value for the key, or default if not found.
        """
        context = EntityContextManager.get_context()
        if context is None:
            return default
        
        return context.view_state.get(key, default)
    
    @staticmethod
    def is_at_root() -> bool:
        """
        Check if currently at the root level (no context or no parent).
        
        Returns:
            True if at root level, False otherwise.
        """
        context = EntityContextManager.get_context()
        return context is None or context.parent_context is None
