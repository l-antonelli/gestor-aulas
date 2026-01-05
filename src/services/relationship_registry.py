"""Registry for managing entity relationships."""

from typing import Type, List, Optional, Dict

from pydantic import BaseModel

from src.services.relationship_metadata import RelationshipMetadata


class RelationshipRegistry:
    """
    Registry to store and retrieve relationship metadata.
    
    This class maintains a central registry of all relationships in the system,
    allowing components to query relationship information dynamically.
    """
    
    # Class-level storage for relationships
    _relationships: Dict[str, RelationshipMetadata] = {}
    
    @classmethod
    def register_relationship(cls, metadata: RelationshipMetadata) -> None:
        """
        Register a relationship in the registry.
        
        Args:
            metadata: RelationshipMetadata instance to register
            
        Raises:
            ValueError: If relationship is already registered
        """
        key = metadata.get_relationship_key()
        
        if key in cls._relationships:
            raise ValueError(
                f"Relationship {key} is already registered. "
                f"Use a different parent-child combination or unregister first."
            )
        
        cls._relationships[key] = metadata
    
    @classmethod
    def get_relationships_for_model(cls, model: Type[BaseModel]) -> List[RelationshipMetadata]:
        """
        Get all relationships where the given model is the parent.
        
        Args:
            model: The parent model class
            
        Returns:
            List of RelationshipMetadata instances where model is the parent
        """
        return [
            metadata
            for metadata in cls._relationships.values()
            if metadata.parent_model == model
        ]
    
    @classmethod
    def get_relationship(
        cls,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel]
    ) -> Optional[RelationshipMetadata]:
        """
        Get relationship metadata between two models.
        
        Args:
            parent_model: The parent model class
            child_model: The child model class
            
        Returns:
            RelationshipMetadata if found, None otherwise
        """
        key = f"{parent_model.__name__}->{child_model.__name__}"
        return cls._relationships.get(key)
    
    @classmethod
    def unregister_relationship(
        cls,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel]
    ) -> bool:
        """
        Unregister a relationship from the registry.
        
        Args:
            parent_model: The parent model class
            child_model: The child model class
            
        Returns:
            True if relationship was unregistered, False if not found
        """
        key = f"{parent_model.__name__}->{child_model.__name__}"
        if key in cls._relationships:
            del cls._relationships[key]
            return True
        return False
    
    @classmethod
    def clear_registry(cls) -> None:
        """Clear all registered relationships. Useful for testing."""
        cls._relationships.clear()
    
    @classmethod
    def get_all_relationships(cls) -> List[RelationshipMetadata]:
        """Get all registered relationships."""
        return list(cls._relationships.values())
    
    @classmethod
    def is_registered(
        cls,
        parent_model: Type[BaseModel],
        child_model: Type[BaseModel]
    ) -> bool:
        """
        Check if a relationship is registered.
        
        Args:
            parent_model: The parent model class
            child_model: The child model class
            
        Returns:
            True if relationship is registered, False otherwise
        """
        key = f"{parent_model.__name__}->{child_model.__name__}"
        return key in cls._relationships
