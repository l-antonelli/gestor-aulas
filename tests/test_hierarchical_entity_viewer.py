"""
Tests for Hierarchical Entity Viewer Component.

This module tests the hierarchical entity viewer functionality for
displaying and navigating parent-child entity relationships.
"""

import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from pydantic import BaseModel, Field

from src.ui.hierarchical_entity_viewer import (
    HierarchicalEntityViewer,
    HierarchyLevel,
    ChildConfig,
)
from src.ui.breadcrumb_navigation import BreadcrumbNavigation
from src.ui.entity_context_manager import EntityContextManager
from src.services.crud_services import BaseCRUDService


# =============================================================================
# Sample Models for Testing
# =============================================================================

class SampleParentModel(BaseModel):
    """Sample parent model for hierarchy testing."""
    codigo: str = Field(..., description="Parent ID")
    nombre: str = Field(..., description="Parent name")
    cupo: int = Field(default=30, description="Capacity")


class SampleChildModel(BaseModel):
    """Sample child model for hierarchy testing."""
    id: str = Field(..., description="Child ID")
    parent_codigo: str = Field(..., description="Reference to parent")
    nombre: str = Field(..., description="Child name")
    numero: int = Field(default=1, description="Number")


class SampleGrandchildModel(BaseModel):
    """Sample grandchild model for hierarchy testing."""
    id: str = Field(..., description="Grandchild ID")
    child_id: str = Field(..., description="Reference to child")
    dia: str = Field(..., description="Day")


# =============================================================================
# Mock Services
# =============================================================================

class MockParentService:
    """Mock service for parent entities."""
    
    def __init__(self, entities=None):
        self.entities = entities or []
    
    def get(self, session, entity_id):
        for e in self.entities:
            if e.codigo == entity_id:
                return e
        return None
    
    def get_all(self, session, skip=0, limit=100):
        return self.entities[skip:skip+limit]


class MockChildService:
    """Mock service for child entities."""
    
    def __init__(self, entities=None):
        self.entities = entities or []
    
    def get(self, session, entity_id):
        for e in self.entities:
            if e.id == entity_id:
                return e
        return None
    
    def get_all(self, session, skip=0, limit=100):
        return self.entities[skip:skip+limit]


# =============================================================================
# HierarchyLevel Tests
# =============================================================================

class TestHierarchyLevel:
    """Tests for HierarchyLevel dataclass."""
    
    def test_create_hierarchy_level(self):
        """Test creating a hierarchy level with all fields."""
        service = MockParentService()
        
        level = HierarchyLevel(
            model=SampleParentModel,
            service=service,
            display_fields=["codigo", "nombre"],
            id_field="codigo",
            display_field="nombre",
            icon="📚",
        )
        
        assert level.model == SampleParentModel
        assert level.service == service
        assert level.display_fields == ["codigo", "nombre"]
        assert level.id_field == "codigo"
        assert level.display_field == "nombre"
        assert level.icon == "📚"
        assert level.child_levels == []
    
    def test_create_hierarchy_level_with_children(self):
        """Test creating a hierarchy level with child levels."""
        parent_service = MockParentService()
        child_service = MockChildService()
        
        child_level = HierarchyLevel(
            model=SampleChildModel,
            service=child_service,
            display_fields=["id", "nombre"],
            id_field="id",
        )
        
        parent_level = HierarchyLevel(
            model=SampleParentModel,
            service=parent_service,
            display_fields=["codigo", "nombre"],
            id_field="codigo",
            child_levels=[child_level],
        )
        
        assert len(parent_level.child_levels) == 1
        assert parent_level.child_levels[0].model == SampleChildModel
    
    def test_hierarchy_level_defaults(self):
        """Test hierarchy level default values."""
        service = MockParentService()
        
        level = HierarchyLevel(
            model=SampleParentModel,
            service=service,
            display_fields=["codigo"],
        )
        
        assert level.id_field == "id"
        assert level.display_field == "nombre"
        assert level.icon == ""
        assert level.child_levels == []


# =============================================================================
# ChildConfig Tests
# =============================================================================

class TestChildConfig:
    """Tests for ChildConfig dataclass."""
    
    def test_create_child_config(self):
        """Test creating a child config with all fields."""
        service = MockChildService()
        
        config = ChildConfig(
            model=SampleChildModel,
            service=service,
            display_fields=["id", "nombre"],
            foreign_key_field="parent_codigo",
            id_field="id",
            display_field="nombre",
            icon="👥",
            allow_create=True,
            allow_edit=True,
            allow_delete=False,
        )
        
        assert config.model == SampleChildModel
        assert config.service == service
        assert config.display_fields == ["id", "nombre"]
        assert config.foreign_key_field == "parent_codigo"
        assert config.id_field == "id"
        assert config.display_field == "nombre"
        assert config.icon == "👥"
        assert config.allow_create is True
        assert config.allow_edit is True
        assert config.allow_delete is False
    
    def test_child_config_defaults(self):
        """Test child config default values."""
        service = MockChildService()
        
        config = ChildConfig(
            model=SampleChildModel,
            service=service,
            display_fields=["id"],
            foreign_key_field="parent_codigo",
        )
        
        assert config.id_field == "id"
        assert config.display_field == "nombre"
        assert config.icon == ""
        assert config.allow_create is True
        assert config.allow_edit is True
        assert config.allow_delete is True


# =============================================================================
# HierarchicalEntityViewer Tests
# =============================================================================

class TestHierarchicalEntityViewer:
    """Tests for HierarchicalEntityViewer class."""
    
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
    
    def test_get_children_for_parent(self, child_entities, mock_session):
        """Test getting children for a specific parent."""
        child_service = MockChildService(child_entities)
        
        children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id="P001",
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        assert len(children) == 2
        assert all(c.parent_codigo == "P001" for c in children)
    
    def test_get_children_for_parent_no_children(self, child_entities, mock_session):
        """Test getting children when parent has no children."""
        child_service = MockChildService(child_entities)
        
        children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id="P999",  # Non-existent parent
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        assert len(children) == 0
    
    def test_get_children_count(self, child_entities, mock_session):
        """Test getting count of children for a parent."""
        child_service = MockChildService(child_entities)
        
        count = HierarchicalEntityViewer.get_children_count(
            parent_id="P001",
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        assert count == 2
    
    def test_get_children_count_no_children(self, child_entities, mock_session):
        """Test getting count when parent has no children."""
        child_service = MockChildService(child_entities)
        
        count = HierarchicalEntityViewer.get_children_count(
            parent_id="P999",
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        assert count == 0
    
    def test_render_child_summary(self, child_entities, mock_session):
        """Test render_child_summary returns correct count."""
        child_service = MockChildService(child_entities)
        
        count = HierarchicalEntityViewer.render_child_summary(
            parent_id="P001",
            child_model=SampleChildModel,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        assert count == 2


    def test_handle_drill_down_updates_breadcrumb(self, parent_entities):
        """Test that handle_drill_down updates breadcrumb navigation."""
        entity = parent_entities[0]
        
        # Mock session state
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ), patch.object(
            EntityContextManager,
            'set_selected_entity',
            return_value=None
        ):
            HierarchicalEntityViewer.handle_drill_down(
                entity=entity,
                model=SampleParentModel,
                id_field="codigo",
                display_field="nombre",
                icon="📚",
            )
            
            # Verify breadcrumb was updated
            path = BreadcrumbNavigation.get_current_path()
            assert len(path) == 1
            assert path[0].model_name == "SampleParentModel"
            assert path[0].entity_id == "P001"
            assert path[0].display_name == "Parent 1"
    
    def test_handle_drill_down_updates_context(self, parent_entities):
        """Test that handle_drill_down updates entity context."""
        entity = parent_entities[0]
        
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        context_calls = []
        
        def capture_context(model, entity_id, **kwargs):
            context_calls.append((model, entity_id))
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ), patch.object(
            EntityContextManager,
            'set_selected_entity',
            side_effect=capture_context
        ):
            HierarchicalEntityViewer.handle_drill_down(
                entity=entity,
                model=SampleParentModel,
                id_field="codigo",
                display_field="nombre",
            )
            
            # Verify context was updated
            assert len(context_calls) == 1
            assert context_calls[0][0] == SampleParentModel
            assert context_calls[0][1] == "P001"
    
    def test_get_child_configs_for_model(self):
        """Test getting child configs from hierarchy configuration."""
        parent_service = MockParentService()
        child_service = MockChildService()
        
        child_level = HierarchyLevel(
            model=SampleChildModel,
            service=child_service,
            display_fields=["id", "nombre"],
            id_field="id",
            display_field="nombre",
            icon="👥",
        )
        
        parent_level = HierarchyLevel(
            model=SampleParentModel,
            service=parent_service,
            display_fields=["codigo", "nombre"],
            id_field="codigo",
            child_levels=[child_level],
        )
        
        hierarchy_config = [parent_level]
        
        child_configs = HierarchicalEntityViewer._get_child_configs_for_model(
            SampleParentModel, hierarchy_config
        )
        
        assert len(child_configs) == 1
        assert child_configs[0].model == SampleChildModel
        assert child_configs[0].display_fields == ["id", "nombre"]
    
    def test_get_child_configs_for_model_not_found(self):
        """Test getting child configs when model not in hierarchy."""
        parent_service = MockParentService()
        
        parent_level = HierarchyLevel(
            model=SampleParentModel,
            service=parent_service,
            display_fields=["codigo", "nombre"],
            id_field="codigo",
        )
        
        hierarchy_config = [parent_level]
        
        # Try to get configs for a model not in hierarchy
        child_configs = HierarchicalEntityViewer._get_child_configs_for_model(
            SampleChildModel, hierarchy_config
        )
        
        assert len(child_configs) == 0



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
def parent_with_children_strategy(draw):
    """
    Generate a parent entity with a list of child entities.
    
    Returns a tuple of (parent, list_of_children).
    """
    # Generate parent
    parent = draw(valid_parent_entity_strategy())
    
    # Generate 0-5 children for this parent
    num_children = draw(st.integers(min_value=0, max_value=5))
    
    children = []
    seen_ids = set()
    
    for _ in range(num_children):
        # Generate unique child ID
        attempts = 0
        while attempts < 10:
            child_id = draw(st.text(
                alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
                min_size=1,
                max_size=10
            ))
            if child_id.strip() and child_id not in seen_ids:
                seen_ids.add(child_id)
                break
            attempts += 1
        else:
            continue
        
        nombre = draw(st.text(min_size=1, max_size=50))
        if not nombre.strip():
            nombre = "Child"
        
        numero = draw(st.integers(min_value=1, max_value=100))
        
        child = SampleChildModel(
            id=child_id,
            parent_codigo=parent.codigo,
            nombre=nombre,
            numero=numero
        )
        children.append(child)
    
    return (parent, children)


@st.composite
def multiple_parents_with_children_strategy(draw):
    """
    Generate multiple parents, each with their own children.
    
    Returns a tuple of (list_of_parents, list_of_all_children).
    """
    # Generate 1-3 parents
    num_parents = draw(st.integers(min_value=1, max_value=3))
    
    parents = []
    all_children = []
    seen_parent_ids = set()
    seen_child_ids = set()
    
    for _ in range(num_parents):
        # Generate unique parent ID
        attempts = 0
        while attempts < 10:
            parent_codigo = draw(st.text(
                alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
                min_size=1,
                max_size=10
            ))
            if parent_codigo.strip() and parent_codigo not in seen_parent_ids:
                seen_parent_ids.add(parent_codigo)
                break
            attempts += 1
        else:
            continue
        
        parent_nombre = draw(st.text(min_size=1, max_size=50))
        if not parent_nombre.strip():
            parent_nombre = "Parent"
        
        parent_cupo = draw(st.integers(min_value=1, max_value=500))
        
        parent = SampleParentModel(codigo=parent_codigo, nombre=parent_nombre, cupo=parent_cupo)
        parents.append(parent)
        
        # Generate 0-3 children for this parent
        num_children = draw(st.integers(min_value=0, max_value=3))
        
        for _ in range(num_children):
            # Generate unique child ID
            attempts = 0
            while attempts < 10:
                child_id = draw(st.text(
                    alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
                    min_size=1,
                    max_size=10
                ))
                if child_id.strip() and child_id not in seen_child_ids:
                    seen_child_ids.add(child_id)
                    break
                attempts += 1
            else:
                continue
            
            child_nombre = draw(st.text(min_size=1, max_size=50))
            if not child_nombre.strip():
                child_nombre = "Child"
            
            child_numero = draw(st.integers(min_value=1, max_value=100))
            
            child = SampleChildModel(
                id=child_id,
                parent_codigo=parent_codigo,
                nombre=child_nombre,
                numero=child_numero
            )
            all_children.append(child)
    
    assume(len(parents) >= 1)
    return (parents, all_children)


class TestHierarchicalChildRetrievalPropertyBased:
    """
    Property-based tests for Hierarchical Child Retrieval.
    
    **Feature: hierarchical-entity-ui, Property 4: Hierarchical Child Retrieval**
    **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
    """
    
    # **Feature: hierarchical-entity-ui, Property 4: Hierarchical Child Retrieval**
    # **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
    @given(data=parent_with_children_strategy())
    @settings(max_examples=100)
    def test_child_retrieval_returns_all_children_for_parent(self, data):
        """
        Property 4: Hierarchical Child Retrieval - All Children Retrieved
        
        For any parent entity, the hierarchical viewer SHALL retrieve and
        display all child entities that reference that parent via foreign key.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
        """
        parent, children = data
        mock_session = MagicMock()
        
        # Create service with all children
        child_service = MockChildService(children)
        
        # Get children for parent
        retrieved_children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id=parent.codigo,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        # All children should be retrieved
        assert len(retrieved_children) == len(children)
        
        # All retrieved children should reference the parent
        for child in retrieved_children:
            assert child.parent_codigo == parent.codigo
    
    # **Feature: hierarchical-entity-ui, Property 4: Hierarchical Child Retrieval**
    # **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
    @given(data=multiple_parents_with_children_strategy())
    @settings(max_examples=100)
    def test_child_retrieval_only_returns_children_for_specific_parent(self, data):
        """
        Property 4: Hierarchical Child Retrieval - Parent Isolation
        
        For any parent entity, the hierarchical viewer SHALL only retrieve
        children that belong to that specific parent, not children of other parents.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
        """
        parents, all_children = data
        assume(len(parents) >= 1)
        
        mock_session = MagicMock()
        
        # Create service with all children from all parents
        child_service = MockChildService(all_children)
        
        # For each parent, verify only their children are retrieved
        for parent in parents:
            retrieved_children = HierarchicalEntityViewer._get_children_for_parent(
                parent_id=parent.codigo,
                child_service=child_service,
                foreign_key_field="parent_codigo",
                session=mock_session,
            )
            
            # Count expected children for this parent
            expected_children = [c for c in all_children if c.parent_codigo == parent.codigo]
            
            # Verify count matches
            assert len(retrieved_children) == len(expected_children)
            
            # Verify all retrieved children belong to this parent
            for child in retrieved_children:
                assert child.parent_codigo == parent.codigo
    
    # **Feature: hierarchical-entity-ui, Property 4: Hierarchical Child Retrieval**
    # **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
    @given(data=parent_with_children_strategy())
    @settings(max_examples=100)
    def test_child_retrieval_preserves_child_data(self, data):
        """
        Property 4: Hierarchical Child Retrieval - Data Integrity
        
        For any parent entity, the retrieved children SHALL have their
        data preserved exactly as stored.
        
        **Validates: Requirements 2.1, 2.2, 2.3, 8.1**
        """
        parent, children = data
        mock_session = MagicMock()
        
        # Create service with all children
        child_service = MockChildService(children)
        
        # Get children for parent
        retrieved_children = HierarchicalEntityViewer._get_children_for_parent(
            parent_id=parent.codigo,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        # Create lookup for original children
        original_by_id = {c.id: c for c in children}
        
        # Verify each retrieved child matches original
        for retrieved in retrieved_children:
            original = original_by_id.get(retrieved.id)
            assert original is not None
            assert retrieved.id == original.id
            assert retrieved.parent_codigo == original.parent_codigo
            assert retrieved.nombre == original.nombre
            assert retrieved.numero == original.numero



class TestRelatedEntityCountPropertyBased:
    """
    Property-based tests for Related Entity Count Accuracy.
    
    **Feature: hierarchical-entity-ui, Property 8: Related Entity Count Accuracy**
    **Validates: Requirements 6.3**
    """
    
    # **Feature: hierarchical-entity-ui, Property 8: Related Entity Count Accuracy**
    # **Validates: Requirements 6.3**
    @given(data=parent_with_children_strategy())
    @settings(max_examples=100)
    def test_child_count_matches_actual_children(self, data):
        """
        Property 8: Related Entity Count Accuracy
        
        For any parent entity, the displayed count of related child entities
        SHALL equal the actual number of children in the database.
        
        **Validates: Requirements 6.3**
        """
        parent, children = data
        mock_session = MagicMock()
        
        # Create service with all children
        child_service = MockChildService(children)
        
        # Get count using the viewer method
        count = HierarchicalEntityViewer.get_children_count(
            parent_id=parent.codigo,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        # Count should match actual number of children
        assert count == len(children)
    
    # **Feature: hierarchical-entity-ui, Property 8: Related Entity Count Accuracy**
    # **Validates: Requirements 6.3**
    @given(data=multiple_parents_with_children_strategy())
    @settings(max_examples=100)
    def test_child_count_accurate_for_each_parent(self, data):
        """
        Property 8: Related Entity Count Accuracy - Multiple Parents
        
        For any set of parent entities, each parent's child count SHALL
        accurately reflect only the children belonging to that specific parent.
        
        **Validates: Requirements 6.3**
        """
        parents, all_children = data
        assume(len(parents) >= 1)
        
        mock_session = MagicMock()
        
        # Create service with all children from all parents
        child_service = MockChildService(all_children)
        
        # For each parent, verify count is accurate
        for parent in parents:
            count = HierarchicalEntityViewer.get_children_count(
                parent_id=parent.codigo,
                child_service=child_service,
                foreign_key_field="parent_codigo",
                session=mock_session,
            )
            
            # Count expected children for this parent
            expected_count = sum(1 for c in all_children if c.parent_codigo == parent.codigo)
            
            # Verify count matches
            assert count == expected_count
    
    # **Feature: hierarchical-entity-ui, Property 8: Related Entity Count Accuracy**
    # **Validates: Requirements 6.3**
    @given(data=parent_with_children_strategy())
    @settings(max_examples=100)
    def test_render_child_summary_returns_accurate_count(self, data):
        """
        Property 8: Related Entity Count Accuracy - Summary Method
        
        For any parent entity, the render_child_summary method SHALL return
        the accurate count of children.
        
        **Validates: Requirements 6.3**
        """
        parent, children = data
        mock_session = MagicMock()
        
        # Create service with all children
        child_service = MockChildService(children)
        
        # Get count using render_child_summary
        count = HierarchicalEntityViewer.render_child_summary(
            parent_id=parent.codigo,
            child_model=SampleChildModel,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        # Count should match actual number of children
        assert count == len(children)
    
    # **Feature: hierarchical-entity-ui, Property 8: Related Entity Count Accuracy**
    # **Validates: Requirements 6.3**
    @given(parent=valid_parent_entity_strategy())
    @settings(max_examples=100)
    def test_child_count_zero_for_parent_with_no_children(self, parent):
        """
        Property 8: Related Entity Count Accuracy - Zero Children
        
        For any parent entity with no children, the count SHALL be zero.
        
        **Validates: Requirements 6.3**
        """
        mock_session = MagicMock()
        
        # Create service with no children
        child_service = MockChildService([])
        
        # Get count
        count = HierarchicalEntityViewer.get_children_count(
            parent_id=parent.codigo,
            child_service=child_service,
            foreign_key_field="parent_codigo",
            session=mock_session,
        )
        
        # Count should be zero
        assert count == 0
