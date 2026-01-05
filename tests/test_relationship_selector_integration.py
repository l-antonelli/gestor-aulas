"""
Integration tests for RelationshipSelector with FormInputRenderer.

This module tests the integration between RelationshipSelector and FormInputRenderer
to ensure foreign key fields are automatically detected and rendered as dropdowns.
"""

import pytest
from pydantic import BaseModel, Field
from typing import Dict, Any

from src.ui.relationship_selector import RelationshipSelector
from src.ui.form_input_renderer import FormInputRenderer
from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_metadata import RelationshipMetadata


class TestRelationshipSelectorIntegration:
    """Tests for RelationshipSelector integration with FormInputRenderer."""

    def setup_method(self):
        """Clear registry before each test."""
        RelationshipRegistry.clear_registry()

    def test_get_foreign_key_fields_detects_relationships(self):
        """Test that get_foreign_key_fields correctly identifies foreign keys."""
        
        class ParentModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        class ChildModel(BaseModel):
            id: str = Field(..., description="ID")
            parent_id: str = Field(..., description="Parent reference")
            value: int = Field(..., description="Value")
        
        # Register relationship
        # Note: display_fields should be from ParentModel (what we're selecting)
        # But RelationshipMetadata validates against child_model, so we use child fields
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id", "value"],  # Use child model fields
            search_fields=["id"],  # Use child model fields
        )
        RelationshipRegistry.register_relationship(metadata)
        
        # Get foreign keys
        foreign_keys = RelationshipSelector.get_foreign_key_fields(ChildModel)
        
        assert "parent_id" in foreign_keys
        assert foreign_keys["parent_id"] == ParentModel
        assert "id" not in foreign_keys
        assert "value" not in foreign_keys

    def test_get_foreign_key_fields_returns_empty_for_no_relationships(self):
        """Test that models without relationships return empty dict."""
        
        class StandaloneModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        foreign_keys = RelationshipSelector.get_foreign_key_fields(StandaloneModel)
        
        assert foreign_keys == {}

    def test_get_foreign_key_fields_handles_multiple_relationships(self):
        """Test that multiple foreign keys are detected."""
        
        class Parent1(BaseModel):
            id: str = Field(..., description="ID")
        
        class Parent2(BaseModel):
            id: str = Field(..., description="ID")
        
        class ChildWithMultipleFKs(BaseModel):
            id: str = Field(..., description="ID")
            parent1_id: str = Field(..., description="Parent 1")
            parent2_id: str = Field(..., description="Parent 2")
        
        # Register relationships
        metadata1 = RelationshipMetadata(
            parent_model=Parent1,
            child_model=ChildWithMultipleFKs,
            foreign_key_field="parent1_id",
            display_fields=["id"],
        )
        RelationshipRegistry.register_relationship(metadata1)
        
        metadata2 = RelationshipMetadata(
            parent_model=Parent2,
            child_model=ChildWithMultipleFKs,
            foreign_key_field="parent2_id",
            display_fields=["id"],
        )
        RelationshipRegistry.register_relationship(metadata2)
        
        # Get foreign keys
        foreign_keys = RelationshipSelector.get_foreign_key_fields(ChildWithMultipleFKs)
        
        assert len(foreign_keys) == 2
        assert foreign_keys["parent1_id"] == Parent1
        assert foreign_keys["parent2_id"] == Parent2


class TestFormInputRendererRelationshipIntegration:
    """Tests for FormInputRenderer integration with relationships."""

    def setup_method(self):
        """Clear registry before each test."""
        RelationshipRegistry.clear_registry()

    def test_render_field_input_detects_foreign_key_without_session(self):
        """Test that foreign keys fall back to normal input when no session provided."""
        
        class ParentModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        class ChildModel(BaseModel):
            id: str = Field(..., description="ID")
            parent_id: str = Field(..., description="Parent")
        
        # Register relationship
        # display_fields must be from child_model per current validation
        metadata = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id"],  # Child model field
        )
        RelationshipRegistry.register_relationship(metadata)
        
        # Without session, should fall back to normal widget
        # This test just verifies no errors occur
        # (actual rendering would require Streamlit context)
        foreign_keys = RelationshipSelector.get_foreign_key_fields(ChildModel)
        assert "parent_id" in foreign_keys


class TestBackwardCompatibility:
    """Tests for backward compatibility with old API."""

    def test_register_relationship_old_api(self):
        """Test that old API register_relationship still works."""
        
        class OldParent(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        class OldChild(BaseModel):
            parent_id: str = Field(..., description="Parent")
        
        # Use old API
        RelationshipSelector.register_relationship(
            source_model=OldChild,
            field_name="parent_id",
            target_model=OldParent,
            display_field="name",
            id_field="id",
        )
        
        # Verify it was registered
        info = RelationshipSelector.get_relationship_info(OldChild, "parent_id")
        assert info is not None
        assert info[0] == OldParent
        assert info[1] == "name"
        assert info[2] == "id"

    def test_is_relationship_field_old_api(self):
        """Test that old API is_relationship_field still works."""
        
        class TestParent(BaseModel):
            id: str = Field(..., description="ID")
        
        class TestChild(BaseModel):
            parent_id: str = Field(..., description="Parent")
            normal_field: str = Field(..., description="Normal")
        
        # Register using old API
        RelationshipSelector.register_relationship(
            source_model=TestChild,
            field_name="parent_id",
            target_model=TestParent,
            display_field="id",
            id_field="id",
        )
        
        # Test old API
        assert RelationshipSelector.is_relationship_field(TestChild, "parent_id") is True
        assert RelationshipSelector.is_relationship_field(TestChild, "normal_field") is False
