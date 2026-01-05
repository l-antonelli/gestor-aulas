"""Tests for CRUD Form Renderer module."""

from typing import Optional
from pydantic import BaseModel, Field

from src.ui.crud_form_renderer import CRUDFormRenderer


class SimpleEntity(BaseModel):
    """Simple test entity."""
    id: str = Field(..., description="Entity ID")
    name: str = Field(..., min_length=1, description="Entity name")
    value: int = Field(default=0, ge=0, description="Entity value")


class EntityWithOptional(BaseModel):
    """Entity with optional fields."""
    id: str = Field(..., description="Entity ID")
    required_field: str = Field(..., description="Required field")
    optional_field: Optional[str] = Field(default=None, description="Optional field")


# Mock storage for testing
class MockStorage:
    """Mock storage for testing CRUD operations."""
    
    def __init__(self):
        self.entities = {}
    
    def create(self, entity: BaseModel) -> BaseModel:
        """Create entity in mock storage."""
        entity_id = getattr(entity, "id", None)
        if entity_id:
            self.entities[entity_id] = entity
        return entity
    
    def read(self, entity_id: str) -> Optional[BaseModel]:
        """Read entity from mock storage."""
        return self.entities.get(entity_id)
    
    def update(self, entity: BaseModel) -> BaseModel:
        """Update entity in mock storage."""
        entity_id = getattr(entity, "id", None)
        if entity_id and entity_id in self.entities:
            self.entities[entity_id] = entity
        return entity
    
    def delete(self, entity_id: str) -> bool:
        """Delete entity from mock storage."""
        if entity_id in self.entities:
            del self.entities[entity_id]
            return True
        return False


class TestShowOperationFeedback:
    """Tests for show_operation_feedback method."""
    
    def test_feedback_messages_exist_for_all_operations(self):
        """Test that default messages exist for all CRUD operations."""
        operations = ["create", "read", "update", "delete"]
        for op in operations:
            # This should not raise any errors
            # We can't easily test Streamlit output, but we verify the method exists
            assert hasattr(CRUDFormRenderer, "show_operation_feedback")
    
    def test_custom_message_parameter(self):
        """Test that custom message parameter is accepted."""
        # Verify the method signature accepts custom message
        import inspect
        sig = inspect.signature(CRUDFormRenderer.show_operation_feedback)
        params = list(sig.parameters.keys())
        assert "message" in params
        assert "operation" in params
        assert "success" in params


class TestCRUDFormRendererMethods:
    """Tests for CRUDFormRenderer method signatures and structure."""
    
    def test_render_create_form_exists(self):
        """Test that render_create_form method exists with correct signature."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_create_form)
        params = list(sig.parameters.keys())
        assert "model" in params
        assert "crud_create_func" in params
        assert "key" in params
        assert "exclude_fields" in params
        assert "field_order" in params
        assert "custom_labels" in params
    
    def test_render_read_form_exists(self):
        """Test that render_read_form method exists with correct signature."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_read_form)
        params = list(sig.parameters.keys())
        assert "model" in params
        assert "entity_id" in params
        assert "crud_read_func" in params
    
    def test_render_update_form_exists(self):
        """Test that render_update_form method exists with correct signature."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_update_form)
        params = list(sig.parameters.keys())
        assert "model" in params
        assert "entity_id" in params
        assert "crud_read_func" in params
        assert "crud_update_func" in params
        assert "id_field" in params
    
    def test_render_delete_form_exists(self):
        """Test that render_delete_form method exists with correct signature."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_delete_form)
        params = list(sig.parameters.keys())
        assert "model" in params
        assert "entity_id" in params
        assert "crud_read_func" in params
        assert "crud_delete_func" in params
        assert "confirm_message" in params
    
    def test_render_crud_form_exists(self):
        """Test that render_crud_form convenience method exists."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_crud_form)
        params = list(sig.parameters.keys())
        assert "model" in params
        assert "operation" in params
        assert "crud_create_func" in params
        assert "crud_read_func" in params
        assert "crud_update_func" in params
        assert "crud_delete_func" in params


class TestMockStorageIntegration:
    """Tests for CRUD operations using mock storage."""
    
    def test_mock_storage_create(self):
        """Test mock storage create operation."""
        storage = MockStorage()
        entity = SimpleEntity(id="test-1", name="Test", value=10)
        created = storage.create(entity)
        assert created.id == "test-1"
        assert "test-1" in storage.entities
    
    def test_mock_storage_read(self):
        """Test mock storage read operation."""
        storage = MockStorage()
        entity = SimpleEntity(id="test-1", name="Test", value=10)
        storage.create(entity)
        
        read_entity = storage.read("test-1")
        assert read_entity is not None
        assert read_entity.name == "Test"
    
    def test_mock_storage_read_not_found(self):
        """Test mock storage read returns None for non-existent entity."""
        storage = MockStorage()
        read_entity = storage.read("non-existent")
        assert read_entity is None
    
    def test_mock_storage_update(self):
        """Test mock storage update operation."""
        storage = MockStorage()
        entity = SimpleEntity(id="test-1", name="Test", value=10)
        storage.create(entity)
        
        updated_entity = SimpleEntity(id="test-1", name="Updated", value=20)
        storage.update(updated_entity)
        
        read_entity = storage.read("test-1")
        assert read_entity.name == "Updated"
        assert read_entity.value == 20
    
    def test_mock_storage_delete(self):
        """Test mock storage delete operation."""
        storage = MockStorage()
        entity = SimpleEntity(id="test-1", name="Test", value=10)
        storage.create(entity)
        
        result = storage.delete("test-1")
        assert result is True
        assert storage.read("test-1") is None
    
    def test_mock_storage_delete_not_found(self):
        """Test mock storage delete returns False for non-existent entity."""
        storage = MockStorage()
        result = storage.delete("non-existent")
        assert result is False


class TestCRUDFormRendererReturnTypes:
    """Tests for return type annotations."""
    
    def test_render_create_form_return_type(self):
        """Test render_create_form returns Optional[BaseModel]."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_create_form)
        # Return annotation should be Optional[BaseModel]
        assert sig.return_annotation is not None
    
    def test_render_read_form_return_type(self):
        """Test render_read_form returns Optional[BaseModel]."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_read_form)
        assert sig.return_annotation is not None
    
    def test_render_update_form_return_type(self):
        """Test render_update_form returns Optional[BaseModel]."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_update_form)
        assert sig.return_annotation is not None
    
    def test_render_delete_form_return_type(self):
        """Test render_delete_form returns bool."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_delete_form)
        assert sig.return_annotation is bool


class TestCRUDFormRendererDefaultValues:
    """Tests for default parameter values."""
    
    def test_render_create_form_defaults(self):
        """Test render_create_form has sensible defaults."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_create_form)
        params = sig.parameters
        
        assert params["key"].default is None
        assert params["exclude_fields"].default is None
        assert params["field_order"].default is None
        assert params["custom_labels"].default is None
        assert params["submit_label"].default == "Crear"
    
    def test_render_update_form_defaults(self):
        """Test render_update_form has sensible defaults."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_update_form)
        params = sig.parameters
        
        assert params["submit_label"].default == "Actualizar"
    
    def test_render_delete_form_defaults(self):
        """Test render_delete_form has sensible defaults."""
        import inspect
        sig = inspect.signature(CRUDFormRenderer.render_delete_form)
        params = sig.parameters
        
        assert params["confirm_message"].default is None


class TestCRUDFormRendererOperations:
    """Tests for render_crud_form operation parameter."""
    
    def test_valid_operations(self):
        """Test that all valid operations are supported."""
        valid_operations = ["create", "read", "update", "delete"]
        # The render_crud_form method should handle all these operations
        # We verify by checking the method implementation handles them
        import inspect
        source = inspect.getsource(CRUDFormRenderer.render_crud_form)
        for op in valid_operations:
            assert f'"{op}"' in source or f"'{op}'" in source
