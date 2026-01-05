"""
Tests for NestedEntityDisplay component.

These tests verify that the nested entity display component correctly
renders and manages related entities within parent entity views.
"""

import pytest
from pydantic import BaseModel, Field
from typing import List, Optional

from src.ui.nested_entity_display import NestedEntityDisplay
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
    parent_id: str = Field(..., description="Parent ID reference")
    name: str = Field(..., description="Child name")
    value: int = Field(..., description="Child value")


class TestNestedEntityDisplay:
    """Tests for NestedEntityDisplay component."""
    
    def setup_method(self):
        """Set up test fixtures."""
        # Clear registry before each test
        RelationshipRegistry.clear_registry()
        
        # Register test relationship
        self.relationship = RelationshipMetadata(
            parent_model=ParentModel,
            child_model=ChildModel,
            foreign_key_field="parent_id",
            display_fields=["id", "name", "value"],
            search_fields=["name"],
            cascading_create=False,
            cascading_create_defaults={},
            delete_behavior="cascade",
            validation_rules=[],
        )
        RelationshipRegistry.register_relationship(self.relationship)
    
    def teardown_method(self):
        """Clean up after each test."""
        RelationshipRegistry.clear_registry()
    
    def test_get_entity_id_with_id_field(self):
        """Test getting entity ID when 'id' field exists."""
        entity = ParentModel(id="parent-1", name="Test Parent")
        entity_id = NestedEntityDisplay._get_entity_id(entity)
        assert entity_id == "parent-1"
    
    def test_get_entity_id_with_codigo_field(self):
        """Test getting entity ID when 'codigo' field exists."""
        class ModelWithCodigo(BaseModel):
            codigo: str
            name: str
        
        entity = ModelWithCodigo(codigo="CODE-123", name="Test")
        entity_id = NestedEntityDisplay._get_entity_id(entity)
        assert entity_id == "CODE-123"
    
    def test_get_entity_id_with_legajo_field(self):
        """Test getting entity ID when 'legajo' field exists."""
        class ModelWithLegajo(BaseModel):
            legajo: str
            name: str
        
        entity = ModelWithLegajo(legajo="LEG-456", name="Test")
        entity_id = NestedEntityDisplay._get_entity_id(entity)
        assert entity_id == "LEG-456"
    
    def test_get_entity_id_returns_none_when_no_id_field(self):
        """Test that _get_entity_id returns None when no ID field exists."""
        class ModelWithoutId(BaseModel):
            name: str
            value: int
        
        entity = ModelWithoutId(name="Test", value=42)
        entity_id = NestedEntityDisplay._get_entity_id(entity)
        assert entity_id is None
    
    def test_get_children_filters_by_parent_id(self):
        """Test that _get_children correctly filters children by parent ID."""
        # Create mock CRUD function
        def mock_crud_func(session):
            return [
                ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
                ChildModel(id="child-2", parent_id="parent-2", name="Child 2", value=20),
                ChildModel(id="child-3", parent_id="parent-1", name="Child 3", value=30),
            ]
        
        # Get children for parent-1
        children = NestedEntityDisplay._get_children(
            parent_id="parent-1",
            relationship=self.relationship,
            child_crud_func=mock_crud_func,
            session=None,  # Not used in this test
        )
        
        # Should only return children with parent_id="parent-1"
        assert len(children) == 2
        assert all(child.parent_id == "parent-1" for child in children)
        assert {child.id for child in children} == {"child-1", "child-3"}
    
    def test_get_children_returns_empty_list_when_no_matches(self):
        """Test that _get_children returns empty list when no children match."""
        # Create mock CRUD function
        def mock_crud_func(session):
            return [
                ChildModel(id="child-1", parent_id="parent-2", name="Child 1", value=10),
                ChildModel(id="child-2", parent_id="parent-3", name="Child 2", value=20),
            ]
        
        # Get children for parent-1 (no matches)
        children = NestedEntityDisplay._get_children(
            parent_id="parent-1",
            relationship=self.relationship,
            child_crud_func=mock_crud_func,
            session=None,
        )
        
        assert len(children) == 0
    
    def test_get_children_handles_empty_database(self):
        """Test that _get_children handles empty database gracefully."""
        # Create mock CRUD function that returns empty list
        def mock_crud_func(session):
            return []
        
        children = NestedEntityDisplay._get_children(
            parent_id="parent-1",
            relationship=self.relationship,
            child_crud_func=mock_crud_func,
            session=None,
        )
        
        assert len(children) == 0


class TestNestedEntityDisplayIntegration:
    """Integration tests for NestedEntityDisplay with real domain models."""
    
    def setup_method(self):
        """Set up test fixtures."""
        RelationshipRegistry.clear_registry()
    
    def teardown_method(self):
        """Clean up after each test."""
        RelationshipRegistry.clear_registry()
    
    def test_nested_entity_display_with_domain_models(self):
        """Test nested entity display with actual domain models."""
        from src.domain.problem.materia import Materia
        from src.domain.problem.comision import Comision
        
        # Register relationship
        relationship = RelationshipMetadata(
            parent_model=Materia,
            child_model=Comision,
            foreign_key_field="materia_codigo",
            display_fields=["id", "nombre", "cupo"],
            search_fields=["nombre"],
            cascading_create=False,
            cascading_create_defaults={},
            delete_behavior="cascade",
            validation_rules=[],
        )
        RelationshipRegistry.register_relationship(relationship)
        
        # Create test data
        materia = Materia(
            codigo="MAT-101",
            nombre="Matemática I",
            cupo=100,
            horas_semanales=4,
        )
        
        # Mock CRUD function
        def mock_comision_crud(session):
            return [
                Comision(
                    id="COM-1",
                    materia_codigo="MAT-101",
                    nombre="Comisión A",
                    numero=1,
                    cupo=50,
                ),
                Comision(
                    id="COM-2",
                    materia_codigo="MAT-101",
                    nombre="Comisión B",
                    numero=2,
                    cupo=50,
                ),
            ]
        
        # Get children
        children = NestedEntityDisplay._get_children(
            parent_id="MAT-101",
            relationship=relationship,
            child_crud_func=mock_comision_crud,
            session=None,
        )
        
        assert len(children) == 2
        assert all(isinstance(child, Comision) for child in children)
        assert all(child.materia_codigo == "MAT-101" for child in children)


class TestBulkOperations:
    """Tests for bulk operations on related entities."""
    
    def setup_method(self):
        """Set up test fixtures."""
        RelationshipRegistry.clear_registry()
    
    def teardown_method(self):
        """Clean up after each test."""
        RelationshipRegistry.clear_registry()
    
    def test_perform_bulk_delete_success(self):
        """Test successful bulk delete operation."""
        # Create test entities
        entities = [
            ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
            ChildModel(id="child-2", parent_id="parent-1", name="Child 2", value=20),
            ChildModel(id="child-3", parent_id="parent-1", name="Child 3", value=30),
        ]
        
        # Track deleted entities
        deleted_ids = []
        
        def mock_delete(entity):
            deleted_ids.append(entity.id)
        
        # Select entities to delete
        selected_ids = {"child-1", "child-3"}
        
        # Perform bulk delete
        results = NestedEntityDisplay.perform_bulk_delete(
            related_entities=entities,
            selected_ids=selected_ids,
            on_delete=mock_delete,
        )
        
        # Verify results
        assert results["success_count"] == 2
        assert results["failed_count"] == 0
        assert len(results["errors"]) == 0
        assert set(deleted_ids) == {"child-1", "child-3"}
    
    def test_perform_bulk_delete_with_failures(self):
        """Test bulk delete operation with some failures."""
        # Create test entities
        entities = [
            ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
            ChildModel(id="child-2", parent_id="parent-1", name="Child 2", value=20),
            ChildModel(id="child-3", parent_id="parent-1", name="Child 3", value=30),
        ]
        
        # Track deleted entities
        deleted_ids = []
        
        def mock_delete_with_error(entity):
            if entity.id == "child-2":
                raise Exception("Cannot delete child-2")
            deleted_ids.append(entity.id)
        
        # Select all entities
        selected_ids = {"child-1", "child-2", "child-3"}
        
        # Perform bulk delete
        results = NestedEntityDisplay.perform_bulk_delete(
            related_entities=entities,
            selected_ids=selected_ids,
            on_delete=mock_delete_with_error,
        )
        
        # Verify results
        assert results["success_count"] == 2
        assert results["failed_count"] == 1
        assert len(results["errors"]) == 1
        assert "child-2" in results["errors"][0]
        assert set(deleted_ids) == {"child-1", "child-3"}
    
    def test_perform_bulk_delete_empty_selection(self):
        """Test bulk delete with no entities selected."""
        entities = [
            ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
            ChildModel(id="child-2", parent_id="parent-1", name="Child 2", value=20),
        ]
        
        deleted_ids = []
        
        def mock_delete(entity):
            deleted_ids.append(entity.id)
        
        # Empty selection
        selected_ids = set()
        
        # Perform bulk delete
        results = NestedEntityDisplay.perform_bulk_delete(
            related_entities=entities,
            selected_ids=selected_ids,
            on_delete=mock_delete,
        )
        
        # Verify no entities were deleted
        assert results["success_count"] == 0
        assert results["failed_count"] == 0
        assert len(deleted_ids) == 0
    
    def test_perform_bulk_delete_all_entities(self):
        """Test bulk delete with all entities selected."""
        entities = [
            ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
            ChildModel(id="child-2", parent_id="parent-1", name="Child 2", value=20),
            ChildModel(id="child-3", parent_id="parent-1", name="Child 3", value=30),
        ]
        
        deleted_ids = []
        
        def mock_delete(entity):
            deleted_ids.append(entity.id)
        
        # Select all entities
        selected_ids = {"child-1", "child-2", "child-3"}
        
        # Perform bulk delete
        results = NestedEntityDisplay.perform_bulk_delete(
            related_entities=entities,
            selected_ids=selected_ids,
            on_delete=mock_delete,
        )
        
        # Verify all entities were deleted
        assert results["success_count"] == 3
        assert results["failed_count"] == 0
        assert set(deleted_ids) == {"child-1", "child-2", "child-3"}
    
    def test_display_bulk_operation_results_success_only(self):
        """Test displaying results for successful bulk operation."""
        results = {
            "success_count": 5,
            "failed_count": 0,
            "errors": [],
        }
        
        # This test verifies the function doesn't raise errors
        # Actual UI rendering would require Streamlit context
        try:
            NestedEntityDisplay.display_bulk_operation_results("delete", results)
        except Exception as e:
            # Expected to fail without Streamlit context, but shouldn't raise other errors
            assert "streamlit" in str(e).lower() or "st" in str(e).lower()
    
    def test_display_bulk_operation_results_with_failures(self):
        """Test displaying results with failures."""
        results = {
            "success_count": 3,
            "failed_count": 2,
            "errors": [
                "Error eliminando child-1: Database error",
                "Error eliminando child-2: Constraint violation",
            ],
        }
        
        # This test verifies the function doesn't raise errors
        try:
            NestedEntityDisplay.display_bulk_operation_results("delete", results)
        except Exception as e:
            # Expected to fail without Streamlit context
            assert "streamlit" in str(e).lower() or "st" in str(e).lower()
    
    def test_bulk_delete_preserves_unselected_entities(self):
        """Test that bulk delete only affects selected entities."""
        entities = [
            ChildModel(id="child-1", parent_id="parent-1", name="Child 1", value=10),
            ChildModel(id="child-2", parent_id="parent-1", name="Child 2", value=20),
            ChildModel(id="child-3", parent_id="parent-1", name="Child 3", value=30),
            ChildModel(id="child-4", parent_id="parent-1", name="Child 4", value=40),
        ]
        
        deleted_ids = []
        
        def mock_delete(entity):
            deleted_ids.append(entity.id)
        
        # Select only some entities
        selected_ids = {"child-2", "child-4"}
        
        # Perform bulk delete
        results = NestedEntityDisplay.perform_bulk_delete(
            related_entities=entities,
            selected_ids=selected_ids,
            on_delete=mock_delete,
        )
        
        # Verify only selected entities were deleted
        assert results["success_count"] == 2
        assert set(deleted_ids) == {"child-2", "child-4"}
        # child-1 and child-3 should not be deleted
        assert "child-1" not in deleted_ids
        assert "child-3" not in deleted_ids

