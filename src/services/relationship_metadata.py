"""Relationship metadata for managing entity relationships."""

from dataclasses import dataclass, field
from typing import Type, List, Dict, Any, Callable, Optional

from pydantic import BaseModel


@dataclass
class RelationshipMetadata:
    """
    Metadata for a one-to-many relationship between entities.
    
    This class defines the structure and behavior of relationships,
    including cascading operations, display configuration, and validation rules.
    
    Attributes:
        parent_model: The parent entity model class
        child_model: The child entity model class
        foreign_key_field: Field in child that references parent
        display_fields: Fields to show in lists/dropdowns
        search_fields: Fields to search by in selectors
        cascading_create: Whether to auto-create child when parent is created
        cascading_create_defaults: Defaults for auto-created child entities
        delete_behavior: How to handle deletion ("cascade", "restrict", "soft_delete")
        validation_rules: Custom validation functions for the relationship
    """
    
    parent_model: Type[BaseModel]
    child_model: Type[BaseModel]
    foreign_key_field: str
    display_fields: List[str]
    search_fields: List[str] = field(default_factory=list)
    cascading_create: bool = False
    cascading_create_defaults: Dict[str, Any] = field(default_factory=dict)
    delete_behavior: str = "restrict"
    validation_rules: List[Callable] = field(default_factory=list)
    
    def __post_init__(self):
        """Validate metadata structure after initialization."""
        self._validate_metadata()
    
    def _validate_metadata(self) -> None:
        """
        Validate that the metadata structure is correct.
        
        Raises:
            ValueError: If metadata is invalid
        """
        # Validate parent_model and child_model are BaseModel subclasses
        if not issubclass(self.parent_model, BaseModel):
            raise ValueError(f"parent_model must be a BaseModel subclass, got {self.parent_model}")
        
        if not issubclass(self.child_model, BaseModel):
            raise ValueError(f"child_model must be a BaseModel subclass, got {self.child_model}")
        
        # Validate foreign_key_field exists in child_model
        if self.foreign_key_field not in self.child_model.model_fields:
            raise ValueError(
                f"foreign_key_field '{self.foreign_key_field}' not found in {self.child_model.__name__}"
            )
        
        # Validate display_fields exist in child_model
        for field_name in self.display_fields:
            if field_name not in self.child_model.model_fields:
                raise ValueError(
                    f"display_field '{field_name}' not found in {self.child_model.__name__}"
                )
        
        # Validate search_fields exist in child_model
        for field_name in self.search_fields:
            if field_name not in self.child_model.model_fields:
                raise ValueError(
                    f"search_field '{field_name}' not found in {self.child_model.__name__}"
                )
        
        # Validate delete_behavior is valid
        valid_behaviors = ["cascade", "restrict", "soft_delete"]
        if self.delete_behavior not in valid_behaviors:
            raise ValueError(
                f"delete_behavior must be one of {valid_behaviors}, got '{self.delete_behavior}'"
            )
        
        # Validate cascading_create_defaults fields exist in child_model
        for field_name in self.cascading_create_defaults.keys():
            if field_name not in self.child_model.model_fields:
                raise ValueError(
                    f"cascading_create_defaults field '{field_name}' not found in {self.child_model.__name__}"
                )
    
    def get_parent_model_name(self) -> str:
        """Get the name of the parent model."""
        return self.parent_model.__name__
    
    def get_child_model_name(self) -> str:
        """Get the name of the child model."""
        return self.child_model.__name__
    
    def get_relationship_key(self) -> str:
        """Get a unique key for this relationship."""
        return f"{self.get_parent_model_name()}->{self.get_child_model_name()}"
