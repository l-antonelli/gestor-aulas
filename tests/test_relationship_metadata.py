"""Tests for relationship metadata and registry."""

import pytest
from pydantic import BaseModel, Field

from src.services.relationship_metadata import RelationshipMetadata
from src.services.relationship_registry import RelationshipRegistry


# Test models
class ParentModel(BaseModel):
    """Test parent model."""
    id: str = Field(..., description="Parent ID")
    name: str = Field(..., description="Parent name")


class ChildModel(BaseModel):
    """Test child model."""
    id: str = Field(..., description="Child ID")
    parent_id: str = Field(..., description="Reference to parent")
    value: int = Field(..., description="Some value")


class TestRelationshipMetadata:
    """Tests for RelationshipMetadata class."""
    
    def test_valid_metadata_creation(self):
        """Test creating valid relationship metadata."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id", "value"],
            search_fields=["value"],
            cascading_create=True,
            cascading_create_defaults={"value": 0},
            delete_behavior="cascade",
        )
        
        assert metadata.parent_model == ParentModel
        assert metadata.child_model == ChildModel
        assert metadata.foreign_key_field == "parent_id"
        assert metadata.display_fields == ["id", "value"]
        assert metadata.cascading_create is True
        assert metadata.delete_behavior == "cascade"
    
    def test_invalid_parent_model(self):
        """Test that non-BaseModel parent raises error."""
        with pytest.raises(ValueError, match="parent_model must be a BaseModel subclass"):
            RelationshipMetadata(
                parent_model=str,  # Not a BaseModel
                child_model=ChildModel,
                foreign_key_field="parent_id",
                display_fields=["id"],
            )
    
    def test_invalid_child_model(self):
        """Test that non-BaseModel child raises error."""
        with pytest.raises(ValueError, match="child_model must be a BaseModel subclass"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=int,  # Not a BaseModel
                foreign_key_field="parent_id",
                display_fields=["id"],
            )
    
    def test_invalid_foreign_key_field(self):
        """Test that invalid foreign key field raises error."""
        with pytest.raises(ValueError, match="foreign_key_field 'invalid_field' not found"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=ChildModel,
                foreign_key_field="invalid_field",
                display_fields=["id"],
            )
    
    def test_invalid_display_field(self):
        """Test that invalid display field raises error."""
        with pytest.raises(ValueError, match="display_field 'invalid_field' not found"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=ChildModel,
                foreign_key_field="parent_id",
                display_fields=["id", "invalid_field"],
            )
    
    def test_invalid_search_field(self):
        """Test that invalid search field raises error."""
        with pytest.raises(ValueError, match="search_field 'invalid_field' not found"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=ChildModel,
                foreign_key_field="parent_id",
                display_fields=["id"],
                search_fields=["invalid_field"],
            )
    
    def test_invalid_delete_behavior(self):
        """Test that invalid delete behavior raises error."""
        with pytest.raises(ValueError, match="delete_behavior must be one of"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=ChildModel,
                foreign_key_field="parent_id",
                display_fields=["id"],
                delete_behavior="invalid",
            )
    
    def test_invalid_cascading_defaults_field(self):
        """Test that invalid cascading defaults field raises error."""
        with pytest.raises(ValueError, match="cascading_create_defaults field 'invalid_field' not found"):
            RelationshipMetadata(
                parent_model=ParentModel,
                child_model=ChildModel,
                foreign_key_field="parent_id",
                display_fields=["id"],
                cascading_create_defaults={"invalid_field": "value"},
            )
    
    def test_get_relationship_key(self):
        """Test getting relationship key."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        assert metadata.get_relationship_key() == "ParentModel->ChildModel"
    
    def test_get_model_names(self):
        """Test getting model names."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        assert metadata.get_parent_model_name() == "ParentModel"
        assert metadata.get_child_model_name() == "ChildModel"


class TestRelationshipRegistry:
    """Tests for RelationshipRegistry class."""
    
    def setup_method(self):
        """Clear registry before each test."""
        RelationshipRegistry.clear_registry()
    
    def teardown_method(self):
        """Clear registry after each test."""
        RelationshipRegistry.clear_registry()
    
    def test_register_relationship(self):
        """Test registering a relationship."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        
        assert RelationshipRegistry.is_registered(ParentModel, ChildModel)
    
    def test_register_duplicate_relationship(self):
        """Test that registering duplicate relationship raises error."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        
        with pytest.raises(ValueError, match="Relationship .* is already registered"):
            RelationshipRegistry.register_relationship(metadata)
    
    def test_get_relationship(self):
        """Test getting a registered relationship."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        
        retrieved = RelationshipRegistry.get_relationship(ParentModel, ChildModel)
        assert retrieved is not None
        assert retrieved.parent_model == ParentModel
        assert retrieved.child_model == ChildModel
    
    def test_get_nonexistent_relationship(self):
        """Test getting a non-existent relationship returns None."""
        result = RelationshipRegistry.get_relationship(ParentModel, ChildModel)
        assert result is None
    
    def test_get_relationships_for_model(self):
        """Test getting all relationships for a parent model."""
        
        class AnotherChildModel(BaseModel):
            id: str
            parent_id: str
        
        metadata1 = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        metadata2 = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=AnotherChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata1)
        RelationshipRegistry.register_relationship(metadata2)
        
        relationships = RelationshipRegistry.get_relationships_for_model(ParentModel)
        assert len(relationships) == 2
        assert metadata1 in relationships
        assert metadata2 in relationships
    
    def test_unregister_relationship(self):
        """Test unregistering a relationship."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        assert RelationshipRegistry.is_registered(ParentModel, ChildModel)
        
        result = RelationshipRegistry.unregister_relationship(ParentModel, ChildModel)
        assert result is True
        assert not RelationshipRegistry.is_registered(ParentModel, ChildModel)
    
    def test_unregister_nonexistent_relationship(self):
        """Test unregistering non-existent relationship returns False."""
        result = RelationshipRegistry.unregister_relationship(ParentModel, ChildModel)
        assert result is False
    
    def test_get_all_relationships(self):
        """Test getting all registered relationships."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        
        all_relationships = RelationshipRegistry.get_all_relationships()
        assert len(all_relationships) == 1
        assert metadata in all_relationships
    
    def test_clear_registry(self):
        """Test clearing the registry."""
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],
        )
        
        RelationshipRegistry.register_relationship(metadata)
        assert len(RelationshipRegistry.get_all_relationships()) == 1
        
        RelationshipRegistry.clear_registry()
        assert len(RelationshipRegistry.get_all_relationships()) == 0
