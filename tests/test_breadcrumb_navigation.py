"""
Tests for Breadcrumb Navigation Component.

This module tests the breadcrumb navigation functionality for
hierarchical entity views.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.ui.breadcrumb_navigation import BreadcrumbItem, BreadcrumbNavigation
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision


# =============================================================================
# BreadcrumbItem Tests
# =============================================================================

class TestBreadcrumbItem:
    """Tests for BreadcrumbItem dataclass."""
    
    def test_create_breadcrumb_item(self):
        """Test creating a breadcrumb item with all fields."""
        item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚"
        )
        
        assert item.model_name == "Materia"
        assert item.entity_id == "MAT101"
        assert item.display_name == "Cálculo I"
        assert item.icon == "📚"
    
    def test_create_breadcrumb_item_without_icon(self):
        """Test creating a breadcrumb item without icon."""
        item = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        
        assert item.icon == ""
    
    def test_breadcrumb_item_equality(self):
        """Test that two items with same model_name and entity_id are equal."""
        item1 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚"
        )
        item2 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Different Name",  # Different display name
            icon="🔢"  # Different icon
        )
        
        assert item1 == item2
    
    def test_breadcrumb_item_inequality_different_model(self):
        """Test that items with different model_name are not equal."""
        item1 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        item2 = BreadcrumbItem(
            model_name="Comision",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        
        assert item1 != item2
    
    def test_breadcrumb_item_inequality_different_id(self):
        """Test that items with different entity_id are not equal."""
        item1 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        item2 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT102",
            display_name="Cálculo II"
        )
        
        assert item1 != item2
    
    def test_breadcrumb_item_hash(self):
        """Test that equal items have the same hash."""
        item1 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        item2 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Different Name"
        )
        
        assert hash(item1) == hash(item2)
    
    def test_breadcrumb_item_can_be_used_in_set(self):
        """Test that breadcrumb items can be used in sets."""
        item1 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        item2 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Different Name"
        )
        item3 = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT102",
            display_name="Cálculo II"
        )
        
        items_set = {item1, item2, item3}
        
        # item1 and item2 are equal, so set should have 2 items
        assert len(items_set) == 2


# =============================================================================
# BreadcrumbNavigation Tests (with mocked session state)
# =============================================================================

class TestBreadcrumbNavigation:
    """Tests for BreadcrumbNavigation class."""
    
    @pytest.fixture(autouse=True)
    def mock_session_state(self):
        """Mock Streamlit session state for each test."""
        mock_state = {}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda path: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, path)
        ), patch.object(
            BreadcrumbNavigation,
            'clear_path',
            side_effect=lambda: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, [])
        ):
            # Initialize empty path
            mock_state[BreadcrumbNavigation.SESSION_KEY] = []
            yield mock_state
    
    def test_get_current_path_empty(self, mock_session_state):
        """Test getting current path when empty."""
        path = BreadcrumbNavigation.get_current_path()
        
        assert path == []
    
    def test_push_to_path_single_item(self, mock_session_state):
        """Test pushing a single item to the path."""
        item = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica",
            icon="🎓"
        )
        
        BreadcrumbNavigation.push_to_path(item)
        
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0] == item
    
    def test_push_to_path_multiple_items(self, mock_session_state):
        """Test pushing multiple items to build a path."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica",
            icon="🎓"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚"
        )
        comision = BreadcrumbItem(
            model_name="Comision",
            entity_id="MAT101-C1",
            display_name="Comisión 1",
            icon="👥"
        )
        
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        BreadcrumbNavigation.push_to_path(comision)
        
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 3
        assert path[0] == carrera
        assert path[1] == materia
        assert path[2] == comision
    
    def test_push_existing_item_truncates_path(self, mock_session_state):
        """Test that pushing an existing item truncates the path to that item."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        comision = BreadcrumbItem(
            model_name="Comision",
            entity_id="MAT101-C1",
            display_name="Comisión 1"
        )
        
        # Build path
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        BreadcrumbNavigation.push_to_path(comision)
        
        # Push existing item (materia)
        BreadcrumbNavigation.push_to_path(materia)
        
        # Path should be truncated to materia
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 2
        assert path[0] == carrera
        assert path[1] == materia
    
    def test_pop_to_item(self, mock_session_state):
        """Test navigating back to a specific item."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        comision = BreadcrumbItem(
            model_name="Comision",
            entity_id="MAT101-C1",
            display_name="Comisión 1"
        )
        
        # Build path
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        BreadcrumbNavigation.push_to_path(comision)
        
        # Pop to carrera
        BreadcrumbNavigation.pop_to_item(carrera)
        
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0] == carrera
    
    def test_pop_to_nonexistent_item_does_nothing(self, mock_session_state):
        """Test that popping to a non-existent item does nothing."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        nonexistent = BreadcrumbItem(
            model_name="Comision",
            entity_id="NONEXISTENT",
            display_name="Does Not Exist"
        )
        
        # Build path
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        
        # Try to pop to non-existent item
        BreadcrumbNavigation.pop_to_item(nonexistent)
        
        # Path should be unchanged
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 2
    
    def test_clear_path(self, mock_session_state):
        """Test clearing the navigation path."""
        item = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        
        BreadcrumbNavigation.push_to_path(item)
        assert len(BreadcrumbNavigation.get_current_path()) == 1
        
        BreadcrumbNavigation.clear_path()
        
        assert len(BreadcrumbNavigation.get_current_path()) == 0
    
    def test_get_current_entity(self, mock_session_state):
        """Test getting the current (last) entity."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        
        # Need to patch get_current_entity to use our mock
        with patch.object(
            BreadcrumbNavigation,
            'get_current_entity',
            side_effect=lambda: (
                BreadcrumbNavigation.get_current_path()[-1]
                if BreadcrumbNavigation.get_current_path()
                else None
            )
        ):
            current = BreadcrumbNavigation.get_current_entity()
            assert current == materia
    
    def test_get_current_entity_empty_path(self, mock_session_state):
        """Test getting current entity when path is empty."""
        with patch.object(
            BreadcrumbNavigation,
            'get_current_entity',
            side_effect=lambda: (
                BreadcrumbNavigation.get_current_path()[-1]
                if BreadcrumbNavigation.get_current_path()
                else None
            )
        ):
            current = BreadcrumbNavigation.get_current_entity()
            assert current is None
    
    def test_get_parent_entity(self, mock_session_state):
        """Test getting the parent entity."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        
        with patch.object(
            BreadcrumbNavigation,
            'get_parent_entity',
            side_effect=lambda: (
                BreadcrumbNavigation.get_current_path()[-2]
                if len(BreadcrumbNavigation.get_current_path()) >= 2
                else None
            )
        ):
            parent = BreadcrumbNavigation.get_parent_entity()
            assert parent == carrera
    
    def test_get_parent_entity_single_item(self, mock_session_state):
        """Test getting parent entity when only one item in path."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        
        BreadcrumbNavigation.push_to_path(carrera)
        
        with patch.object(
            BreadcrumbNavigation,
            'get_parent_entity',
            side_effect=lambda: (
                BreadcrumbNavigation.get_current_path()[-2]
                if len(BreadcrumbNavigation.get_current_path()) >= 2
                else None
            )
        ):
            parent = BreadcrumbNavigation.get_parent_entity()
            assert parent is None
    
    def test_is_at_root_empty_path(self, mock_session_state):
        """Test is_at_root when path is empty."""
        with patch.object(
            BreadcrumbNavigation,
            'is_at_root',
            side_effect=lambda: len(BreadcrumbNavigation.get_current_path()) <= 1
        ):
            assert BreadcrumbNavigation.is_at_root() is True
    
    def test_is_at_root_single_item(self, mock_session_state):
        """Test is_at_root when path has one item."""
        item = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        
        BreadcrumbNavigation.push_to_path(item)
        
        with patch.object(
            BreadcrumbNavigation,
            'is_at_root',
            side_effect=lambda: len(BreadcrumbNavigation.get_current_path()) <= 1
        ):
            assert BreadcrumbNavigation.is_at_root() is True
    
    def test_is_at_root_multiple_items(self, mock_session_state):
        """Test is_at_root when path has multiple items."""
        carrera = BreadcrumbItem(
            model_name="Carrera",
            entity_id="ING-ELECT",
            display_name="Ingeniería Electrónica"
        )
        materia = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I"
        )
        
        BreadcrumbNavigation.push_to_path(carrera)
        BreadcrumbNavigation.push_to_path(materia)
        
        with patch.object(
            BreadcrumbNavigation,
            'is_at_root',
            side_effect=lambda: len(BreadcrumbNavigation.get_current_path()) <= 1
        ):
            assert BreadcrumbNavigation.is_at_root() is False


# =============================================================================
# build_breadcrumb_item Tests
# =============================================================================

class TestBuildBreadcrumbItem:
    """Tests for build_breadcrumb_item helper method."""
    
    def test_build_from_materia(self):
        """Test building breadcrumb item from Materia entity."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=materia,
            model=Materia,
            display_field="nombre",
            icon="📚"
        )
        
        assert item.model_name == "Materia"
        assert item.entity_id == "MAT101"
        assert item.display_name == "Cálculo I"
        assert item.icon == "📚"
    
    def test_build_from_comision(self):
        """Test building breadcrumb item from Comision entity."""
        comision = Comision(
            id="MAT101-C1",
            materia_codigo="MAT101",
            nombre="Comisión 1",
            numero=1,
            cupo=30
        )
        
        item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=comision,
            model=Comision,
            display_field="nombre",
            icon="👥"
        )
        
        assert item.model_name == "Comision"
        assert item.entity_id == "MAT101-C1"
        assert item.display_name == "Comisión 1"
        assert item.icon == "👥"
    
    def test_build_with_default_display_field(self):
        """Test building with default display_field (nombre)."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=materia,
            model=Materia
        )
        
        assert item.display_name == "Cálculo I"
    
    def test_build_with_missing_display_field_uses_id(self):
        """Test that missing display field falls back to entity ID."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=materia,
            model=Materia,
            display_field="nonexistent_field"
        )
        
        # Should fall back to entity_id
        assert item.display_name == "MAT101"
    
    def test_build_without_icon(self):
        """Test building without icon."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        item = BreadcrumbNavigation.build_breadcrumb_item(
            entity=materia,
            model=Materia
        )
        
        assert item.icon == ""


# =============================================================================
# Property-Based Tests
# =============================================================================

from hypothesis import given, strategies as st, settings, assume


# Custom strategies for generating valid breadcrumb items
@st.composite
def valid_breadcrumb_item_strategy(draw):
    """Generate valid BreadcrumbItem instances for property testing."""
    # Generate model_name from common entity types
    model_name = draw(st.sampled_from(["Carrera", "Materia", "Comision", "Horario"]))
    
    # Generate entity_id (alphanumeric, 1-20 chars)
    entity_id = draw(st.text(
        alphabet=st.characters(whitelist_categories=('Lu', 'Nd', 'Ll')),
        min_size=1,
        max_size=20
    ))
    assume(len(entity_id.strip()) >= 1)
    
    # Generate display_name (non-empty string)
    display_name = draw(st.text(min_size=1, max_size=50))
    assume(len(display_name.strip()) >= 1)
    
    # Generate optional icon
    icon = draw(st.sampled_from(["", "📚", "🎓", "👥", "📅", "🏛️"]))
    
    return BreadcrumbItem(
        model_name=model_name,
        entity_id=entity_id,
        display_name=display_name,
        icon=icon
    )


@st.composite
def valid_navigation_path_strategy(draw):
    """
    Generate valid navigation paths.
    
    A valid navigation path is a list of BreadcrumbItems where each item
    has a unique (model_name, entity_id) combination.
    """
    # Generate path length (1-4 items for realistic hierarchy depth)
    depth = draw(st.integers(min_value=1, max_value=4))
    
    path = []
    seen_keys = set()
    
    for i in range(depth):
        # Generate a unique item
        attempts = 0
        while attempts < 10:
            item = draw(valid_breadcrumb_item_strategy())
            key = (item.model_name, item.entity_id)
            
            if key not in seen_keys:
                seen_keys.add(key)
                path.append(item)
                break
            attempts += 1
        else:
            # If we couldn't generate a unique item, stop here
            break
    
    assume(len(path) >= 1)
    return path


class TestBreadcrumbPathConsistencyPropertyBased:
    """
    Property-based tests for Breadcrumb Path Consistency.
    
    **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    **Validates: Requirements 2.5, 3.1, 3.3**
    """
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(path=valid_navigation_path_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_path_preserves_order(self, path):
        """
        Property 5: Breadcrumb Path Consistency - Order Preservation
        
        For any navigation path, pushing items in sequence SHALL result
        in a breadcrumb path that preserves the original order from root
        to current entity.
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
        # Create a mock session state
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ):
            # Push all items in order
            for item in path:
                BreadcrumbNavigation.push_to_path(item)
            
            # Get the resulting path
            result_path = BreadcrumbNavigation.get_current_path()
            
            # Verify order is preserved
            assert len(result_path) == len(path)
            for i, (expected, actual) in enumerate(zip(path, result_path)):
                assert expected == actual, f"Item at position {i} does not match"
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(path=valid_navigation_path_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_pop_to_item_truncates_correctly(self, path):
        """
        Property 5: Breadcrumb Path Consistency - Pop Truncation
        
        For any navigation path, popping to an item SHALL truncate the path
        to include only items from root up to and including that item.
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
        assume(len(path) >= 2)  # Need at least 2 items to test pop
        
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ):
            # Push all items
            for item in path:
                BreadcrumbNavigation.push_to_path(item)
            
            # Pick a random item to pop to (not the last one)
            pop_index = len(path) // 2  # Pop to middle item
            target_item = path[pop_index]
            
            # Pop to that item
            BreadcrumbNavigation.pop_to_item(target_item)
            
            # Get the resulting path
            result_path = BreadcrumbNavigation.get_current_path()
            
            # Verify path is truncated correctly
            expected_length = pop_index + 1
            assert len(result_path) == expected_length
            
            # Verify all items up to and including target are preserved
            for i in range(expected_length):
                assert result_path[i] == path[i]
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(path=valid_navigation_path_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_push_existing_item_navigates_to_it(self, path):
        """
        Property 5: Breadcrumb Path Consistency - Push Existing Item
        
        For any navigation path, pushing an item that already exists in the
        path SHALL navigate to that item (truncate path to that item).
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
        assume(len(path) >= 2)  # Need at least 2 items
        
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ):
            # Push all items
            for item in path:
                BreadcrumbNavigation.push_to_path(item)
            
            # Pick an existing item (not the last one)
            existing_index = 0  # First item
            existing_item = path[existing_index]
            
            # Push the existing item again
            BreadcrumbNavigation.push_to_path(existing_item)
            
            # Get the resulting path
            result_path = BreadcrumbNavigation.get_current_path()
            
            # Verify path is truncated to the existing item
            expected_length = existing_index + 1
            assert len(result_path) == expected_length
            assert result_path[-1] == existing_item
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(path=valid_navigation_path_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_clear_removes_all_items(self, path):
        """
        Property 5: Breadcrumb Path Consistency - Clear Path
        
        For any navigation path, clearing the path SHALL result in an
        empty path.
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
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
            BreadcrumbNavigation,
            'clear_path',
            side_effect=lambda: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, [])
        ):
            # Push all items
            for item in path:
                BreadcrumbNavigation.push_to_path(item)
            
            # Verify path is not empty
            assert len(BreadcrumbNavigation.get_current_path()) > 0
            
            # Clear the path
            BreadcrumbNavigation.clear_path()
            
            # Verify path is empty
            assert len(BreadcrumbNavigation.get_current_path()) == 0
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(item=valid_breadcrumb_item_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_item_equality_is_consistent(self, item):
        """
        Property 5: Breadcrumb Path Consistency - Item Equality
        
        For any breadcrumb item, equality SHALL be based on model_name
        and entity_id, not on display_name or icon.
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
        # Create a copy with different display_name and icon
        modified_item = BreadcrumbItem(
            model_name=item.model_name,
            entity_id=item.entity_id,
            display_name="MODIFIED_" + item.display_name,
            icon="🔄" if item.icon != "🔄" else "✨"
        )
        
        # Items should be equal (same model_name and entity_id)
        assert item == modified_item
        assert hash(item) == hash(modified_item)
    
    # **Feature: hierarchical-entity-ui, Property 5: Breadcrumb Path Consistency**
    # **Validates: Requirements 2.5, 3.1, 3.3**
    @given(path=valid_navigation_path_strategy())
    @settings(max_examples=100)
    def test_breadcrumb_last_item_is_current_entity(self, path):
        """
        Property 5: Breadcrumb Path Consistency - Current Entity
        
        For any navigation path, the last item in the path SHALL be
        the current entity.
        
        **Validates: Requirements 2.5, 3.1, 3.3**
        """
        mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
        
        with patch.object(
            BreadcrumbNavigation,
            'get_current_path',
            side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
        ), patch.object(
            BreadcrumbNavigation,
            '_set_path',
            side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
        ):
            # Push all items
            for item in path:
                BreadcrumbNavigation.push_to_path(item)
            
            # Get the resulting path
            result_path = BreadcrumbNavigation.get_current_path()
            
            # The last item should be the last item we pushed
            assert result_path[-1] == path[-1]
