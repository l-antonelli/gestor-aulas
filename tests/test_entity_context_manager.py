"""
Tests for Entity Context Manager.

This module tests the entity context management functionality for
hierarchical entity navigation.
"""

import pytest
from unittest.mock import MagicMock, patch
from typing import Dict, Any

from src.ui.entity_context_manager import EntityContext, EntityContextManager
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision


# =============================================================================
# EntityContext Tests
# =============================================================================

class TestEntityContext:
    """Tests for EntityContext dataclass."""
    
    def test_create_entity_context(self):
        """Test creating an entity context with all fields."""
        context = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            parent_context=None,
            view_state={"selected_tab": 1}
        )
        
        assert context.model_name == "Materia"
        assert context.entity_id == "MAT101"
        assert context.parent_context is None
        assert context.view_state == {"selected_tab": 1}
    
    def test_create_entity_context_with_defaults(self):
        """Test creating an entity context with default values."""
        context = EntityContext(
            model_name="Carrera",
            entity_id="ING-ELECT"
        )
        
        assert context.parent_context is None
        assert context.view_state == {}
    
    def test_entity_context_with_parent(self):
        """Test creating a context with a parent context."""
        parent = EntityContext(
            model_name="Carrera",
            entity_id="ING-ELECT"
        )
        child = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            parent_context=parent
        )
        
        assert child.parent_context == parent
        assert child.parent_context.model_name == "Carrera"
    
    def test_entity_context_equality(self):
        """Test that two contexts with same model_name and entity_id are equal."""
        context1 = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            view_state={"tab": 1}
        )
        context2 = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            view_state={"tab": 2}  # Different view state
        )
        
        assert context1 == context2
    
    def test_entity_context_inequality_different_model(self):
        """Test that contexts with different model_name are not equal."""
        context1 = EntityContext(
            model_name="Materia",
            entity_id="MAT101"
        )
        context2 = EntityContext(
            model_name="Comision",
            entity_id="MAT101"
        )
        
        assert context1 != context2
    
    def test_entity_context_inequality_different_id(self):
        """Test that contexts with different entity_id are not equal."""
        context1 = EntityContext(
            model_name="Materia",
            entity_id="MAT101"
        )
        context2 = EntityContext(
            model_name="Materia",
            entity_id="MAT102"
        )
        
        assert context1 != context2
    
    def test_entity_context_hash(self):
        """Test that equal contexts have the same hash."""
        context1 = EntityContext(
            model_name="Materia",
            entity_id="MAT101"
        )
        context2 = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            view_state={"different": "state"}
        )
        
        assert hash(context1) == hash(context2)
    
    def test_entity_context_to_dict(self):
        """Test converting context to dictionary."""
        context = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            view_state={"tab": 1}
        )
        
        result = context.to_dict()
        
        assert result["model_name"] == "Materia"
        assert result["entity_id"] == "MAT101"
        assert result["view_state"] == {"tab": 1}
        assert "parent_context" not in result
    
    def test_entity_context_to_dict_with_parent(self):
        """Test converting context with parent to dictionary."""
        parent = EntityContext(
            model_name="Carrera",
            entity_id="ING-ELECT"
        )
        child = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            parent_context=parent
        )
        
        result = child.to_dict()
        
        assert result["model_name"] == "Materia"
        assert result["parent_context"]["model_name"] == "Carrera"
        assert result["parent_context"]["entity_id"] == "ING-ELECT"
    
    def test_entity_context_from_dict(self):
        """Test creating context from dictionary."""
        data = {
            "model_name": "Materia",
            "entity_id": "MAT101",
            "view_state": {"tab": 1}
        }
        
        context = EntityContext.from_dict(data)
        
        assert context.model_name == "Materia"
        assert context.entity_id == "MAT101"
        assert context.view_state == {"tab": 1}
        assert context.parent_context is None
    
    def test_entity_context_from_dict_with_parent(self):
        """Test creating context with parent from dictionary."""
        data = {
            "model_name": "Materia",
            "entity_id": "MAT101",
            "view_state": {},
            "parent_context": {
                "model_name": "Carrera",
                "entity_id": "ING-ELECT",
                "view_state": {}
            }
        }
        
        context = EntityContext.from_dict(data)
        
        assert context.model_name == "Materia"
        assert context.parent_context is not None
        assert context.parent_context.model_name == "Carrera"
    
    def test_entity_context_round_trip(self):
        """Test that to_dict and from_dict are inverses."""
        parent = EntityContext(
            model_name="Carrera",
            entity_id="ING-ELECT",
            view_state={"expanded": True}
        )
        original = EntityContext(
            model_name="Materia",
            entity_id="MAT101",
            parent_context=parent,
            view_state={"tab": 2}
        )
        
        # Round trip
        data = original.to_dict()
        restored = EntityContext.from_dict(data)
        
        assert restored == original
        assert restored.view_state == original.view_state
        assert restored.parent_context == original.parent_context


# =============================================================================
# EntityContextManager Tests (with mocked session state)
# =============================================================================

class TestEntityContextManager:
    """Tests for EntityContextManager class."""
    
    @pytest.fixture(autouse=True)
    def mock_session_state(self):
        """Mock Streamlit session state for each test."""
        mock_state: Dict[str, Any] = {}
        
        with patch('src.ui.entity_context_manager.st') as mock_st:
            mock_st.session_state = mock_state
            yield mock_state
    
    def test_get_context_empty(self, mock_session_state):
        """Test getting context when none is set."""
        context = EntityContextManager.get_context()
        
        assert context is None
    
    def test_set_and_get_context(self, mock_session_state):
        """Test setting and getting a context."""
        context = EntityContext(
            model_name="Materia",
            entity_id="MAT101"
        )
        
        EntityContextManager.set_context(context)
        retrieved = EntityContextManager.get_context()
        
        assert retrieved is not None
        assert retrieved.model_name == "Materia"
        assert retrieved.entity_id == "MAT101"
    
    def test_set_context_none_clears(self, mock_session_state):
        """Test that setting context to None clears it."""
        context = EntityContext(
            model_name="Materia",
            entity_id="MAT101"
        )
        
        EntityContextManager.set_context(context)
        EntityContextManager.set_context(None)
        
        assert EntityContextManager.get_context() is None
    
    def test_set_selected_entity(self, mock_session_state):
        """Test setting selected entity."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        context = EntityContextManager.get_context()
        
        assert context is not None
        assert context.model_name == "Materia"
        assert context.entity_id == "MAT101"
    
    def test_set_selected_entity_preserves_parent(self, mock_session_state):
        """Test that setting selected entity preserves current as parent."""
        # Set initial context
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        # Set child entity (should use current as parent)
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        context = EntityContextManager.get_context()
        
        assert context is not None
        assert context.model_name == "Comision"
        assert context.entity_id == "MAT101-C1"
        assert context.parent_context is not None
        assert context.parent_context.model_name == "Materia"
        assert context.parent_context.entity_id == "MAT101"
    
    def test_set_selected_entity_with_explicit_parent(self, mock_session_state):
        """Test setting selected entity with explicit parent context."""
        parent = EntityContext(
            model_name="Carrera",
            entity_id="ING-ELECT"
        )
        
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
            parent_context=parent
        )
        
        context = EntityContextManager.get_context()
        
        assert context is not None
        assert context.parent_context is not None
        assert context.parent_context.model_name == "Carrera"
    
    def test_set_selected_entity_with_view_state(self, mock_session_state):
        """Test setting selected entity with view state."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
            view_state={"selected_tab": 2, "expanded": True}
        )
        
        context = EntityContextManager.get_context()
        
        assert context is not None
        assert context.view_state == {"selected_tab": 2, "expanded": True}
    
    def test_get_selected_entity(self, mock_session_state):
        """Test getting selected entity."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        result = EntityContextManager.get_selected_entity()
        
        assert result is not None
        assert result == ("Materia", "MAT101")
    
    def test_get_selected_entity_none(self, mock_session_state):
        """Test getting selected entity when none is set."""
        result = EntityContextManager.get_selected_entity()
        
        assert result is None
    
    def test_get_parent_context(self, mock_session_state):
        """Test getting parent context."""
        # Build hierarchy
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        parent = EntityContextManager.get_parent_context()
        
        assert parent is not None
        assert parent.model_name == "Materia"
        assert parent.entity_id == "MAT101"
    
    def test_get_parent_context_at_root(self, mock_session_state):
        """Test getting parent context when at root."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        parent = EntityContextManager.get_parent_context()
        
        assert parent is None
    
    def test_clear_context(self, mock_session_state):
        """Test clearing context."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        EntityContextManager.clear_context()
        
        assert EntityContextManager.get_context() is None
    
    def test_navigate_to_parent(self, mock_session_state):
        """Test navigating to parent context."""
        # Build hierarchy
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        # Navigate to parent
        result = EntityContextManager.navigate_to_parent()
        
        assert result is not None
        assert result.model_name == "Materia"
        
        # Current context should now be the parent
        current = EntityContextManager.get_context()
        assert current is not None
        assert current.model_name == "Materia"
    
    def test_navigate_to_parent_at_root(self, mock_session_state):
        """Test navigating to parent when at root."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        result = EntityContextManager.navigate_to_parent()
        
        assert result is None
        assert EntityContextManager.get_context() is None
    
    def test_get_context_depth_empty(self, mock_session_state):
        """Test getting context depth when empty."""
        depth = EntityContextManager.get_context_depth()
        
        assert depth == 0
    
    def test_get_context_depth_single(self, mock_session_state):
        """Test getting context depth with single context."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        depth = EntityContextManager.get_context_depth()
        
        assert depth == 1
    
    def test_get_context_depth_hierarchy(self, mock_session_state):
        """Test getting context depth with hierarchy."""
        # Build 3-level hierarchy
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        # Create a mock Clase model for testing
        class MockClase:
            __name__ = "Clase"
        
        EntityContextManager.set_selected_entity(
            model=MockClase,
            entity_id="CLS001"
        )
        
        depth = EntityContextManager.get_context_depth()
        
        assert depth == 3
    
    def test_get_context_chain_empty(self, mock_session_state):
        """Test getting context chain when empty."""
        chain = EntityContextManager.get_context_chain()
        
        assert chain == []
    
    def test_get_context_chain_single(self, mock_session_state):
        """Test getting context chain with single context."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        chain = EntityContextManager.get_context_chain()
        
        assert len(chain) == 1
        assert chain[0].model_name == "Materia"
    
    def test_get_context_chain_hierarchy(self, mock_session_state):
        """Test getting context chain with hierarchy."""
        # Build hierarchy
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        chain = EntityContextManager.get_context_chain()
        
        assert len(chain) == 2
        # Chain should be root-to-current order
        assert chain[0].model_name == "Materia"
        assert chain[1].model_name == "Comision"
    
    def test_update_view_state(self, mock_session_state):
        """Test updating view state."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        EntityContextManager.update_view_state("selected_tab", 2)
        
        context = EntityContextManager.get_context()
        assert context is not None
        assert context.view_state.get("selected_tab") == 2
    
    def test_update_view_state_no_context(self, mock_session_state):
        """Test updating view state when no context exists."""
        # Should not raise an error
        EntityContextManager.update_view_state("key", "value")
        
        # Context should still be None
        assert EntityContextManager.get_context() is None
    
    def test_get_view_state(self, mock_session_state):
        """Test getting view state."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
            view_state={"tab": 1, "expanded": True}
        )
        
        tab = EntityContextManager.get_view_state("tab")
        expanded = EntityContextManager.get_view_state("expanded")
        missing = EntityContextManager.get_view_state("missing", "default")
        
        assert tab == 1
        assert expanded is True
        assert missing == "default"
    
    def test_get_view_state_no_context(self, mock_session_state):
        """Test getting view state when no context exists."""
        result = EntityContextManager.get_view_state("key", "default")
        
        assert result == "default"
    
    def test_is_at_root_no_context(self, mock_session_state):
        """Test is_at_root when no context exists."""
        assert EntityContextManager.is_at_root() is True
    
    def test_is_at_root_single_context(self, mock_session_state):
        """Test is_at_root with single context (no parent)."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        
        assert EntityContextManager.is_at_root() is True
    
    def test_is_at_root_with_parent(self, mock_session_state):
        """Test is_at_root when context has parent."""
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101"
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="MAT101-C1"
        )
        
        assert EntityContextManager.is_at_root() is False



# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Custom strategies for generating valid entity contexts
@st.composite
def valid_entity_context_strategy(draw, max_depth: int = 0):
    """
    Generate valid EntityContext instances for property testing.
    
    Args:
        max_depth: Maximum depth of parent context chain (0 = no parent)
    """
    # Generate model_name from common entity types
    model_name = draw(st.sampled_from(["Carrera", "Materia", "Comision", "Clase", "Alumno"]))
    
    # Generate entity_id (alphanumeric, 1-20 chars)
    entity_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=20
    ))
    assume(len(entity_id.strip()) >= 1)
    
    # Generate optional view_state
    view_state = draw(st.fixed_dictionaries({
        "selected_tab": st.integers(min_value=0, max_value=5),
        "expanded": st.booleans(),
    }))
    
    # Generate parent context if depth allows
    parent_context = None
    if max_depth > 0:
        has_parent = draw(st.booleans())
        if has_parent:
            parent_context = draw(valid_entity_context_strategy(max_depth=max_depth - 1))
    
    return EntityContext(
        model_name=model_name,
        entity_id=entity_id,
        parent_context=parent_context,
        view_state=view_state
    )


@st.composite
def valid_navigation_sequence_strategy(draw):
    """
    Generate a valid sequence of navigation steps.
    
    Returns a list of (model_name, entity_id) tuples representing
    a navigation sequence from root to leaf.
    """
    # Generate sequence length (1-4 for realistic hierarchy depth)
    depth = draw(st.integers(min_value=1, max_value=4))
    
    # Define hierarchy order
    hierarchy = ["Carrera", "Materia", "Comision", "Clase"]
    
    sequence = []
    for i in range(min(depth, len(hierarchy))):
        model_name = hierarchy[i]
        entity_id = draw(st.text(
            alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
            min_size=1,
            max_size=15
        ))
        assume(len(entity_id.strip()) >= 1)
        sequence.append((model_name, entity_id))
    
    assume(len(sequence) >= 1)
    return sequence


from contextlib import contextmanager


@contextmanager
def mock_streamlit_session():
    """Context manager to mock Streamlit session state."""
    mock_state: Dict[str, Any] = {}
    
    with patch('src.ui.entity_context_manager.st') as mock_st:
        mock_st.session_state = mock_state
        yield mock_state


class TestContextPreservationPropertyBased:
    """
    Property-based tests for Context Preservation on Navigation.
    
    **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    **Validates: Requirements 5.1, 5.3**
    """
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(sequence=valid_navigation_sequence_strategy())
    @settings(max_examples=100)
    def test_navigation_preserves_parent_chain(self, sequence):
        """
        Property 6: Context Preservation on Navigation - Parent Chain
        
        For any navigation from parent to child entity, the parent context
        SHALL be preserved and accessible for back navigation.
        
        **Validates: Requirements 5.1, 5.3**
        """
        with mock_streamlit_session():
            # Clear any existing context
            EntityContextManager.clear_context()
            
            # Navigate through the sequence
            for model_name, entity_id in sequence:
                # Create a mock model with the correct name
                mock_model = type(model_name, (), {"__name__": model_name})
                EntityContextManager.set_selected_entity(
                    model=mock_model,
                    entity_id=entity_id
                )
            
            # Verify the context chain
            chain = EntityContextManager.get_context_chain()
            
            # Chain length should match sequence length
            assert len(chain) == len(sequence)
            
            # Each item in chain should match the sequence
            for i, (expected_model, expected_id) in enumerate(sequence):
                assert chain[i].model_name == expected_model
                assert chain[i].entity_id == expected_id
            
            # Verify parent relationships
            for i in range(1, len(chain)):
                assert chain[i].parent_context is not None
                assert chain[i].parent_context == chain[i - 1]
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(sequence=valid_navigation_sequence_strategy())
    @settings(max_examples=100)
    def test_navigate_to_parent_restores_previous_context(self, sequence):
        """
        Property 6: Context Preservation on Navigation - Back Navigation
        
        For any navigation sequence, navigating back to parent SHALL
        restore the previous context state.
        
        **Validates: Requirements 5.1, 5.3**
        """
        assume(len(sequence) >= 2)  # Need at least 2 items to test back navigation
        
        with mock_streamlit_session():
            # Clear any existing context
            EntityContextManager.clear_context()
            
            # Navigate through the sequence
            for model_name, entity_id in sequence:
                mock_model = type(model_name, (), {"__name__": model_name})
                EntityContextManager.set_selected_entity(
                    model=mock_model,
                    entity_id=entity_id
                )
            
            # Navigate back one level
            parent = EntityContextManager.navigate_to_parent()
            
            # Parent should be the second-to-last item in sequence
            expected_model, expected_id = sequence[-2]
            assert parent is not None
            assert parent.model_name == expected_model
            assert parent.entity_id == expected_id
            
            # Current context should now be the parent
            current = EntityContextManager.get_context()
            assert current is not None
            assert current.model_name == expected_model
            assert current.entity_id == expected_id
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(sequence=valid_navigation_sequence_strategy())
    @settings(max_examples=100)
    def test_context_depth_matches_navigation_depth(self, sequence):
        """
        Property 6: Context Preservation on Navigation - Depth Consistency
        
        For any navigation sequence, the context depth SHALL equal
        the number of navigation steps taken.
        
        **Validates: Requirements 5.1, 5.3**
        """
        with mock_streamlit_session():
            # Clear any existing context
            EntityContextManager.clear_context()
            
            # Navigate through the sequence
            for model_name, entity_id in sequence:
                mock_model = type(model_name, (), {"__name__": model_name})
                EntityContextManager.set_selected_entity(
                    model=mock_model,
                    entity_id=entity_id
                )
            
            # Verify depth matches sequence length
            depth = EntityContextManager.get_context_depth()
            assert depth == len(sequence)
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(context=valid_entity_context_strategy(max_depth=3))
    @settings(max_examples=100)
    def test_context_serialization_round_trip(self, context):
        """
        Property 6: Context Preservation on Navigation - Serialization
        
        For any entity context, serializing to dict and deserializing
        SHALL produce an equivalent context.
        
        **Validates: Requirements 5.1, 5.3**
        """
        # Round trip through dict (no session state needed for this test)
        data = context.to_dict()
        restored = EntityContext.from_dict(data)
        
        # Contexts should be equal
        assert restored == context
        assert restored.model_name == context.model_name
        assert restored.entity_id == context.entity_id
        assert restored.view_state == context.view_state
        
        # Parent chain should be preserved
        original_parent = context.parent_context
        restored_parent = restored.parent_context
        
        while original_parent is not None:
            assert restored_parent is not None
            assert restored_parent == original_parent
            original_parent = original_parent.parent_context
            restored_parent = restored_parent.parent_context
        
        assert restored_parent is None
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(sequence=valid_navigation_sequence_strategy())
    @settings(max_examples=100)
    def test_clear_context_removes_all_state(self, sequence):
        """
        Property 6: Context Preservation on Navigation - Clear
        
        For any navigation state, clearing context SHALL remove
        all navigation state.
        
        **Validates: Requirements 5.1, 5.3**
        """
        with mock_streamlit_session():
            # Navigate through the sequence
            for model_name, entity_id in sequence:
                mock_model = type(model_name, (), {"__name__": model_name})
                EntityContextManager.set_selected_entity(
                    model=mock_model,
                    entity_id=entity_id
                )
            
            # Verify we have context
            assert EntityContextManager.get_context() is not None
            
            # Clear context
            EntityContextManager.clear_context()
            
            # Verify all state is cleared
            assert EntityContextManager.get_context() is None
            assert EntityContextManager.get_selected_entity() is None
            assert EntityContextManager.get_parent_context() is None
            assert EntityContextManager.get_context_depth() == 0
            assert EntityContextManager.get_context_chain() == []
            assert EntityContextManager.is_at_root() is True
    
    # **Feature: hierarchical-entity-ui, Property 6: Context Preservation on Navigation**
    # **Validates: Requirements 5.1, 5.3**
    @given(sequence=valid_navigation_sequence_strategy())
    @settings(max_examples=100)
    def test_is_at_root_reflects_parent_presence(self, sequence):
        """
        Property 6: Context Preservation on Navigation - Root Detection
        
        For any navigation state, is_at_root SHALL return True only
        when there is no parent context.
        
        **Validates: Requirements 5.1, 5.3**
        """
        with mock_streamlit_session():
            # Clear any existing context
            EntityContextManager.clear_context()
            
            # Initially at root
            assert EntityContextManager.is_at_root() is True
            
            # Navigate through the sequence
            for i, (model_name, entity_id) in enumerate(sequence):
                mock_model = type(model_name, (), {"__name__": model_name})
                EntityContextManager.set_selected_entity(
                    model=mock_model,
                    entity_id=entity_id
                )
                
                # After first navigation, should be at root (no parent)
                # After subsequent navigations, should not be at root
                if i == 0:
                    assert EntityContextManager.is_at_root() is True
                else:
                    assert EntityContextManager.is_at_root() is False
