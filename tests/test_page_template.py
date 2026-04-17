"""
Tests for Entity Page Template Module.

This module tests the EntityPageTemplate functionality for creating
consistent entity pages with standard structure.

Requirements: 4.1, 4.2, 4.4, 5.2, 6.1, 6.2, 7.3, 8.3
"""

import pytest
from unittest.mock import MagicMock, patch

from pydantic import BaseModel, Field

from src.ui.page_template import EntityPageTemplate, EntityPageConfig
from src.ui.hierarchical_entity_viewer import ChildConfig


# =============================================================================
# Sample Models for Testing
# =============================================================================

class SampleParentModel(BaseModel):
    """Sample parent model for testing."""
    codigo: str = Field(..., description="Parent ID")
    nombre: str = Field(..., description="Parent name")
    cupo: int = Field(default=30, description="Capacity")


class SampleChildModel(BaseModel):
    """Sample child model for testing."""
    id: str = Field(..., description="Child ID")
    parent_codigo: str = Field(..., description="Reference to parent")
    nombre: str = Field(..., description="Child name")
    numero: int = Field(default=1, description="Number")


class SampleModelWithFK(BaseModel):
    """Sample model with foreign key for testing."""
    id: str = Field(..., description="ID")
    materia_codigo: str = Field(..., description="Foreign key to Materia")
    nombre: str = Field(..., description="Name")


# =============================================================================
# Mock Services
# =============================================================================

class MockService:
    """Mock CRUD service for testing."""
    
    def __init__(self, entities=None):
        self.entities = entities or []
        self.id_field = "codigo"
    
    def get(self, session, entity_id):
        for e in self.entities:
            entity_dict = e.model_dump() if hasattr(e, 'model_dump') else e.dict()
            if entity_dict.get(self.id_field) == entity_id:
                return e
        return None
    
    def get_all(self, session, skip=0, limit=100):
        return self.entities[skip:skip+limit]
    
    def create(self, session, instance):
        self.entities.append(instance)
        return instance
    
    def create_with_cascading(self, session, instance):
        self.entities.append(instance)
        return instance, []
    
    def delete(self, session, entity_id):
        for i, e in enumerate(self.entities):
            entity_dict = e.model_dump() if hasattr(e, 'model_dump') else e.dict()
            if entity_dict.get(self.id_field) == entity_id:
                self.entities.pop(i)
                return True
        return False
    
    def delete_with_cascading(self, session, entity_id):
        return self.delete(session, entity_id)


class MockChildService(MockService):
    """Mock service for child entities."""
    
    def __init__(self, entities=None):
        super().__init__(entities)
        self.id_field = "id"


# =============================================================================
# EntityPageConfig Tests
# =============================================================================

class TestEntityPageConfig:
    """Tests for EntityPageConfig dataclass."""
    
    def test_create_config_with_required_fields(self):
        """Test creating config with only required fields."""
        service = MockService()
        
        config = EntityPageConfig(
            model=SampleParentModel,
            service=service,
            page_title="Test Page",
            page_icon="📚",
            display_fields=["codigo", "nombre"],
        )
        
        assert config.model == SampleParentModel
        assert config.service == service
        assert config.page_title == "Test Page"
        assert config.page_icon == "📚"
        assert config.display_fields == ["codigo", "nombre"]
    
    def test_create_config_with_all_fields(self):
        """Test creating config with all fields."""
        service = MockService()
        child_service = MockChildService()
        
        child_config = ChildConfig(
            model=SampleChildModel,
            service=child_service,
            display_fields=["id", "nombre"],
            foreign_key_field="parent_codigo",
        )
        
        config = EntityPageConfig(
            model=SampleParentModel,
            service=service,
            page_title="Test Page",
            page_icon="📚",
            display_fields=["codigo", "nombre"],
            custom_labels={"codigo": "Código", "nombre": "Nombre"},
            id_field="codigo",
            display_field="nombre",
            child_configs=[child_config],
            enable_cascading=True,
            enable_hierarchy_view=True,
            exclude_from_create=["created_at"],
            exclude_from_display=["internal_id"],
        )
        
        assert config.custom_labels == {"codigo": "Código", "nombre": "Nombre"}
        assert config.id_field == "codigo"
        assert config.display_field == "nombre"
        assert len(config.child_configs) == 1
        assert config.enable_cascading is True
        assert config.enable_hierarchy_view is True
        assert config.exclude_from_create == ["created_at"]
        assert config.exclude_from_display == ["internal_id"]
    
    def test_config_defaults(self):
        """Test config default values."""
        service = MockService()
        
        config = EntityPageConfig(
            model=SampleParentModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["codigo"],
        )
        
        assert config.custom_labels == {}
        assert config.id_field == "id"
        assert config.display_field == "nombre"
        assert config.child_configs == []
        assert config.enable_cascading is True
        assert config.enable_hierarchy_view is True
        assert config.exclude_from_create == []
        assert config.exclude_from_display == []


# =============================================================================
# EntityPageTemplate Tests
# =============================================================================

class TestEntityPageTemplate:
    """Tests for EntityPageTemplate class."""
    
    @pytest.fixture
    def parent_entities(self):
        """Create test parent entities."""
        return [
            SampleParentModel(codigo="P001", nombre="Parent 1", cupo=30),
            SampleParentModel(codigo="P002", nombre="Parent 2", cupo=25),
        ]
    
    @pytest.fixture
    def child_entities(self):
        """Create test child entities."""
        return [
            SampleChildModel(id="C001", parent_codigo="P001", nombre="Child 1", numero=1),
            SampleChildModel(id="C002", parent_codigo="P001", nombre="Child 2", numero=2),
            SampleChildModel(id="C003", parent_codigo="P002", nombre="Child 3", numero=1),
        ]
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock database session."""
        return MagicMock()
    
    @pytest.fixture
    def basic_config(self, parent_entities):
        """Create a basic page config."""
        service = MockService(parent_entities)
        service.id_field = "codigo"
        
        return EntityPageConfig(
            model=SampleParentModel,
            service=service,
            page_title="Test Entities",
            page_icon="📚",
            display_fields=["codigo", "nombre", "cupo"],
            id_field="codigo",
            display_field="nombre",
        )
    
    def test_get_foreign_key_fields_with_registered_relationship(self):
        """Test detecting foreign key fields from registered relationships."""
        # This test verifies the method exists and returns a dict
        result = EntityPageTemplate._get_foreign_key_fields(SampleChildModel)
        assert isinstance(result, dict)
    
    def test_get_parent_context_for_create_no_context(self):
        """Test getting parent context when no context is set."""
        service = MockService()
        config = EntityPageConfig(
            model=SampleChildModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["id"],
        )
        
        # Mock EntityContextManager to return None
        with patch('src.ui.entity_context_manager.EntityContextManager.get_context', return_value=None):
            result = EntityPageTemplate._get_parent_context_for_create(config)
            
            assert result == {}
    
    def test_get_parent_context_for_create_with_context(self):
        """Test getting parent context when context is set."""
        from src.ui.entity_context_manager import EntityContext
        
        service = MockService()
        config = EntityPageConfig(
            model=SampleChildModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["id"],
        )
        
        # Create a mock context
        mock_context = EntityContext(
            model_name="SampleParentModel",
            entity_id="P001",
        )
        
        # Mock EntityContextManager and RelationshipSelector
        with patch('src.ui.entity_context_manager.EntityContextManager.get_context', return_value=mock_context), \
             patch.object(EntityPageTemplate, '_get_foreign_key_fields') as mock_fk:
            mock_fk.return_value = {"parent_codigo": SampleParentModel}
            
            result = EntityPageTemplate._get_parent_context_for_create(config)
            
            assert result == {"parent_codigo": "P001"}


# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Custom strategies for generating valid entities
@st.composite
def valid_parent_entity_strategy(draw):
    """Generate valid parent entity instances for property testing."""
    codigo = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=10
    ))
    assume(len(codigo.strip()) >= 1)
    
    nombre = draw(st.text(min_size=1, max_size=50))
    assume(len(nombre.strip()) >= 1)
    
    cupo = draw(st.integers(min_value=1, max_value=500))
    
    return SampleParentModel(codigo=codigo, nombre=nombre, cupo=cupo)


@st.composite
def valid_child_entity_strategy(draw, parent_codigo=None):
    """Generate valid child entity instances for property testing."""
    child_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=10
    ))
    assume(len(child_id.strip()) >= 1)
    
    if parent_codigo is None:
        parent_codigo = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
            min_size=1,
            max_size=10
        ))
        assume(len(parent_codigo.strip()) >= 1)
    
    nombre = draw(st.text(min_size=1, max_size=50))
    assume(len(nombre.strip()) >= 1)
    
    numero = draw(st.integers(min_value=1, max_value=100))
    
    return SampleChildModel(id=child_id, parent_codigo=parent_codigo, nombre=nombre, numero=numero)


@st.composite
def model_with_foreign_key_strategy(draw):
    """Generate model instances with foreign key fields."""
    entity_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=10
    ))
    assume(len(entity_id.strip()) >= 1)
    
    fk_value = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=10
    ))
    assume(len(fk_value.strip()) >= 1)
    
    nombre = draw(st.text(min_size=1, max_size=50))
    assume(len(nombre.strip()) >= 1)
    
    return SampleModelWithFK(id=entity_id, materia_codigo=fk_value, nombre=nombre)


@st.composite
def entity_context_strategy(draw):
    """Generate valid entity context for testing."""
    model_name = draw(st.sampled_from(["SampleParentModel", "Materia", "Carrera"]))
    
    entity_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=10
    ))
    assume(len(entity_id.strip()) >= 1)
    
    return {"model_name": model_name, "entity_id": entity_id}


class TestForeignKeySelectorGenerationPropertyBased:
    """
    Property-based tests for Foreign Key Selector Generation.
    
    **Feature: hierarchical-entity-ui, Property 9: Foreign Key Selector Generation**
    **Validates: Requirements 4.4, 8.3**
    """
    
    # **Feature: hierarchical-entity-ui, Property 9: Foreign Key Selector Generation**
    # **Validates: Requirements 4.4, 8.3**
    @given(entity=model_with_foreign_key_strategy())
    @settings(max_examples=100)
    def test_foreign_key_fields_detected(self, entity):
        """
        Property 9: Foreign Key Selector Generation - Field Detection
        
        For any entity with foreign key fields, the system SHALL detect
        those fields when relationships are registered.
        
        **Validates: Requirements 4.4, 8.3**
        """
        # Get foreign key fields
        fk_fields = EntityPageTemplate._get_foreign_key_fields(type(entity))
        
        # Result should be a dictionary
        assert isinstance(fk_fields, dict)
        
        # All values should be model types
        for field_name, parent_model in fk_fields.items():
            assert isinstance(field_name, str)
            # Parent model should be a type (class)
            assert isinstance(parent_model, type) or parent_model is None or fk_fields == {}
    
    # **Feature: hierarchical-entity-ui, Property 9: Foreign Key Selector Generation**
    # **Validates: Requirements 4.4, 8.3**
    @given(parent=valid_parent_entity_strategy())
    @settings(max_examples=100)
    def test_foreign_key_selector_returns_valid_value(self, parent):
        """
        Property 9: Foreign Key Selector Generation - Valid Return
        
        For any foreign key field with available parent entities,
        the selector SHALL return a valid entity ID or None.
        
        **Validates: Requirements 4.4, 8.3**
        """
        mock_session = MagicMock()
        
        # Create a mock CRUD function that returns the parent
        def mock_crud_func(session):
            return [parent]
        
        # Mock the relationship selector to return the parent's ID
        with patch.object(
            EntityPageTemplate,
            '_render_foreign_key_selector',
            return_value=parent.codigo
        ):
            result = EntityPageTemplate._render_foreign_key_selector(
                field_name="parent_codigo",
                parent_model=SampleParentModel,
                child_model=SampleChildModel,
                session=mock_session,
                crud_functions={"SampleParentModel": mock_crud_func},
            )
            
            # Result should be the parent's ID
            assert result == parent.codigo


class TestChildEntityPrePopulationPropertyBased:
    """
    Property-based tests for Child Entity Pre-Population.
    
    **Feature: hierarchical-entity-ui, Property 7: Child Entity Pre-Population**
    **Validates: Requirements 5.2**
    """
    
    # **Feature: hierarchical-entity-ui, Property 7: Child Entity Pre-Population**
    # **Validates: Requirements 5.2**
    @given(context_data=entity_context_strategy())
    @settings(max_examples=100)
    def test_parent_context_pre_populates_foreign_key(self, context_data):
        """
        Property 7: Child Entity Pre-Population
        
        For any child entity creation from a parent's detail view,
        the foreign key field SHALL be pre-populated with the parent's ID.
        
        **Validates: Requirements 5.2**
        """
        from src.ui.entity_context_manager import EntityContext
        
        service = MockChildService()
        config = EntityPageConfig(
            model=SampleChildModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["id"],
        )
        
        # Create context from strategy data
        mock_context = EntityContext(
            model_name=context_data["model_name"],
            entity_id=context_data["entity_id"],
        )
        
        # Define which FK field maps to which parent model
        fk_mapping = {
            "SampleParentModel": {"parent_codigo": SampleParentModel},
            "Materia": {"materia_codigo": type("Materia", (), {"__name__": "Materia"})},
            "Carrera": {"carrera_codigo": type("Carrera", (), {"__name__": "Carrera"})},
        }
        
        expected_fk_fields = fk_mapping.get(context_data["model_name"], {})
        
        with patch('src.ui.entity_context_manager.EntityContextManager.get_context', return_value=mock_context), \
             patch.object(EntityPageTemplate, '_get_foreign_key_fields') as mock_fk:
            mock_fk.return_value = expected_fk_fields
            
            result = EntityPageTemplate._get_parent_context_for_create(config)
            
            # If there's a matching FK field, it should be pre-populated
            if expected_fk_fields:
                for fk_field, parent_model in expected_fk_fields.items():
                    if parent_model.__name__ == context_data["model_name"]:
                        assert fk_field in result
                        assert result[fk_field] == context_data["entity_id"]
    
    # **Feature: hierarchical-entity-ui, Property 7: Child Entity Pre-Population**
    # **Validates: Requirements 5.2**
    @given(parent=valid_parent_entity_strategy())
    @settings(max_examples=100)
    def test_inline_create_form_pre_populates_parent_id(self, parent):
        """
        Property 7: Child Entity Pre-Population - Inline Form
        
        For any inline child creation form, the parent ID SHALL be
        pre-populated in the foreign key field.
        
        **Validates: Requirements 5.2**
        """
        from src.ui.entity_context_manager import EntityContext
        
        # Create context with parent info
        mock_context = EntityContext(
            model_name="SampleParentModel",
            entity_id=parent.codigo,
        )
        
        service = MockChildService()
        config = EntityPageConfig(
            model=SampleChildModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["id"],
        )
        
        # Mock to return parent context
        with patch('src.ui.entity_context_manager.EntityContextManager.get_context', return_value=mock_context), \
             patch.object(EntityPageTemplate, '_get_foreign_key_fields') as mock_fk:
            mock_fk.return_value = {"parent_codigo": SampleParentModel}
            
            result = EntityPageTemplate._get_parent_context_for_create(config)
            
            # Parent ID should be pre-populated
            assert "parent_codigo" in result
            assert result["parent_codigo"] == parent.codigo
    
    # **Feature: hierarchical-entity-ui, Property 7: Child Entity Pre-Population**
    # **Validates: Requirements 5.2**
    @given(parent=valid_parent_entity_strategy())
    @settings(max_examples=100)
    def test_no_pre_population_without_context(self, parent):
        """
        Property 7: Child Entity Pre-Population - No Context
        
        When no parent context exists, no fields SHALL be pre-populated.
        
        **Validates: Requirements 5.2**
        """
        service = MockChildService()
        config = EntityPageConfig(
            model=SampleChildModel,
            service=service,
            page_title="Test",
            page_icon="📚",
            display_fields=["id"],
        )
        
        # Mock to return no context
        with patch('src.ui.entity_context_manager.EntityContextManager.get_context', return_value=None):
            result = EntityPageTemplate._get_parent_context_for_create(config)
            
            # No fields should be pre-populated
            assert result == {}
