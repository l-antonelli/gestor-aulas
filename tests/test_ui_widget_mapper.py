"""Tests for Widget Mapper module."""

import pytest
import datetime
from enum import Enum
from typing import List, Literal, Optional, Set

from src.ui.widget_mapper import WidgetMapper


class TestWidgetMapperGetWidgetType:
    """Tests for WidgetMapper.get_widget_type method."""

    def test_str_maps_to_text_input(self):
        """Test that str type maps to text_input."""
        assert WidgetMapper.get_widget_type(str) == "text_input"

    def test_int_maps_to_number_input(self):
        """Test that int type maps to number_input."""
        assert WidgetMapper.get_widget_type(int) == "number_input"

    def test_float_maps_to_number_input(self):
        """Test that float type maps to number_input."""
        assert WidgetMapper.get_widget_type(float) == "number_input"

    def test_bool_maps_to_checkbox(self):
        """Test that bool type maps to checkbox."""
        assert WidgetMapper.get_widget_type(bool) == "checkbox"

    def test_date_maps_to_date_input(self):
        """Test that date type maps to date_input."""
        assert WidgetMapper.get_widget_type(datetime.date) == "date_input"

    def test_datetime_maps_to_date_input(self):
        """Test that datetime type maps to date_input."""
        assert WidgetMapper.get_widget_type(datetime.datetime) == "date_input"

    def test_time_maps_to_time_input(self):
        """Test that time type maps to time_input."""
        assert WidgetMapper.get_widget_type(datetime.time) == "time_input"

    def test_list_maps_to_multiselect(self):
        """Test that list type maps to multiselect."""
        assert WidgetMapper.get_widget_type(list) == "multiselect"
        assert WidgetMapper.get_widget_type(List[str]) == "multiselect"

    def test_set_maps_to_multiselect(self):
        """Test that set type maps to multiselect."""
        assert WidgetMapper.get_widget_type(set) == "multiselect"
        assert WidgetMapper.get_widget_type(Set[str]) == "multiselect"

    def test_literal_maps_to_selectbox(self):
        """Test that Literal type maps to selectbox."""
        assert WidgetMapper.get_widget_type(Literal["a", "b", "c"]) == "selectbox"

    def test_enum_maps_to_selectbox(self):
        """Test that Enum type maps to selectbox."""
        class Color(Enum):
            RED = "red"
            GREEN = "green"
        
        assert WidgetMapper.get_widget_type(Color) == "selectbox"

    def test_optional_str_maps_to_text_input(self):
        """Test that Optional[str] maps to text_input."""
        assert WidgetMapper.get_widget_type(Optional[str]) == "text_input"

    def test_optional_int_maps_to_number_input(self):
        """Test that Optional[int] maps to number_input."""
        assert WidgetMapper.get_widget_type(Optional[int]) == "number_input"

    def test_unknown_type_defaults_to_text_input(self):
        """Test that unknown types default to text_input."""
        class CustomClass:
            pass
        
        assert WidgetMapper.get_widget_type(CustomClass) == "text_input"


class TestWidgetMapperApplyConstraints:
    """Tests for WidgetMapper.apply_constraints_to_widget method."""

    def test_number_input_gt_constraint(self):
        """Test gt constraint is converted to min_value."""
        params = WidgetMapper.apply_constraints_to_widget(
            "number_input", 
            {"gt": 0}
        )
        assert params["min_value"] == 1

    def test_number_input_ge_constraint(self):
        """Test ge constraint is converted to min_value."""
        params = WidgetMapper.apply_constraints_to_widget(
            "number_input", 
            {"ge": 1}
        )
        assert params["min_value"] == 1

    def test_number_input_lt_constraint(self):
        """Test lt constraint is converted to max_value."""
        params = WidgetMapper.apply_constraints_to_widget(
            "number_input", 
            {"lt": 100}
        )
        assert params["max_value"] == 99

    def test_number_input_le_constraint(self):
        """Test le constraint is converted to max_value."""
        params = WidgetMapper.apply_constraints_to_widget(
            "number_input", 
            {"le": 100}
        )
        assert params["max_value"] == 100

    def test_text_input_max_length_constraint(self):
        """Test max_length constraint is converted to max_chars."""
        params = WidgetMapper.apply_constraints_to_widget(
            "text_input", 
            {"max_length": 50}
        )
        assert params["max_chars"] == 50

    def test_empty_constraints_returns_empty_dict(self):
        """Test empty constraints returns empty dict."""
        params = WidgetMapper.apply_constraints_to_widget("text_input", {})
        assert params == {}


class TestWidgetMapperGetSelectboxOptions:
    """Tests for WidgetMapper._get_selectbox_options method."""

    def test_literal_options(self):
        """Test getting options from Literal type."""
        options = WidgetMapper._get_selectbox_options(Literal["a", "b", "c"])
        assert options == ["a", "b", "c"]

    def test_enum_options(self):
        """Test getting options from Enum type."""
        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"
        
        options = WidgetMapper._get_selectbox_options(Status)
        assert options == ["active", "inactive"]

    def test_non_enum_returns_empty(self):
        """Test non-enum/literal types return empty list."""
        options = WidgetMapper._get_selectbox_options(str)
        assert options == []


class TestWidgetMapperGetElementType:
    """Tests for WidgetMapper._get_element_type method."""

    def test_list_str_element_type(self):
        """Test getting element type from List[str]."""
        element_type = WidgetMapper._get_element_type(List[str])
        assert element_type == str

    def test_list_int_element_type(self):
        """Test getting element type from List[int]."""
        element_type = WidgetMapper._get_element_type(List[int])
        assert element_type == int

    def test_set_str_element_type(self):
        """Test getting element type from Set[str]."""
        element_type = WidgetMapper._get_element_type(Set[str])
        assert element_type == str

    def test_non_collection_defaults_to_str(self):
        """Test non-collection types default to str."""
        element_type = WidgetMapper._get_element_type(str)
        assert element_type == str
