"""
Widget Mapping Module.

Maps Python/Pydantic types to appropriate Streamlit widgets.
"""

import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Set, Type, get_args, get_origin, Union

import streamlit as st
from pydantic import BaseModel

from src.ui.schema_introspector import SchemaIntrospector


class WidgetMapper:
    """Maps Python/Pydantic types to appropriate Streamlit widgets."""

    # Mapping of Python types to Streamlit widget names
    TYPE_TO_WIDGET: Dict[Type, str] = {
        str: "text_input",
        int: "number_input",
        float: "number_input",
        bool: "checkbox",
        datetime.date: "date_input",
        datetime.datetime: "date_input",
        datetime.time: "time_input",
        list: "multiselect",
        set: "multiselect",
    }

    @staticmethod
    def get_widget_type(field_type: Type, constraints: Dict[str, Any] = None) -> str:
        """
        Determine the appropriate Streamlit widget for a field type.
        
        Args:
            field_type: The Python type of the field
            constraints: Optional constraints that may affect widget selection
            
        Returns:
            Name of the Streamlit widget to use
        """
        constraints = constraints or {}
        
        # Handle Optional types (Union[X, None])
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
                origin = get_origin(field_type)
        
        # Handle Literal types (use selectbox)
        if origin is Literal:
            return "selectbox"
        
        # Handle Enum types
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return "selectbox"
        
        # Handle List/Set types
        if origin in (list, List, set, Set):
            return "multiselect"
        
        # Handle nested Pydantic models
        if SchemaIntrospector.is_nested_model(field_type):
            return "nested_form"
        
        # Look up in type mapping
        if field_type in WidgetMapper.TYPE_TO_WIDGET:
            return WidgetMapper.TYPE_TO_WIDGET[field_type]
        
        # Default to text_input for unknown types
        return "text_input"

    @staticmethod
    def apply_constraints_to_widget(
        widget_type: str, 
        constraints: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Convert Pydantic constraints to Streamlit widget parameters.
        
        Args:
            widget_type: The Streamlit widget type
            constraints: Pydantic field constraints
            
        Returns:
            Dictionary of Streamlit widget parameters
        """
        widget_params = {}
        
        if widget_type == "number_input":
            if "gt" in constraints:
                widget_params["min_value"] = constraints["gt"] + 1
            if "ge" in constraints:
                widget_params["min_value"] = constraints["ge"]
            if "lt" in constraints:
                widget_params["max_value"] = constraints["lt"] - 1
            if "le" in constraints:
                widget_params["max_value"] = constraints["le"]
        
        elif widget_type == "text_input":
            if "max_length" in constraints:
                widget_params["max_chars"] = constraints["max_length"]
        
        elif widget_type == "text_area":
            if "max_length" in constraints:
                widget_params["max_chars"] = constraints["max_length"]
        
        return widget_params

    @staticmethod
    def render_widget(
        field_name: str,
        field_type: Type,
        constraints: Dict[str, Any] = None,
        default_value: Any = None,
        description: str = None,
        key: str = None,
        required: bool = True,
    ) -> Any:
        """
        Render a Streamlit widget for a field.
        
        Args:
            field_name: Name of the field (used as label)
            field_type: Python type of the field
            constraints: Pydantic field constraints
            default_value: Default value for the widget
            description: Help text for the widget
            key: Streamlit widget key
            required: Whether the field is required
            
        Returns:
            The value entered by the user
        """
        constraints = constraints or {}
        widget_type = WidgetMapper.get_widget_type(field_type, constraints)
        widget_params = WidgetMapper.apply_constraints_to_widget(widget_type, constraints)
        
        # Format label
        label = field_name.replace("_", " ").title()
        if required:
            label = f"{label} *"
        
        # Add help text
        if description:
            widget_params["help"] = description
        
        # Add key
        if key:
            widget_params["key"] = key
        
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
        
        # Render appropriate widget
        if widget_type == "text_input":
            return st.text_input(
                label,
                value=default_value or "",
                **widget_params
            )
        
        elif widget_type == "number_input":
            # Determine if int or float
            is_float = field_type == float
            step = 0.1 if is_float else 1
            value = default_value if default_value is not None else (0.0 if is_float else 0)

            # Coerce all numeric params to matching type for Streamlit
            if is_float:
                value = float(value)
                if "min_value" in widget_params:
                    widget_params["min_value"] = float(widget_params["min_value"])
                if "max_value" in widget_params:
                    widget_params["max_value"] = float(widget_params["max_value"])

            # Ensure default value respects min_value constraint
            if "min_value" in widget_params:
                min_val = widget_params["min_value"]
                if value < min_val:
                    value = min_val

            # Ensure default value respects max_value constraint
            if "max_value" in widget_params:
                max_val = widget_params["max_value"]
                if value > max_val:
                    value = max_val

            return st.number_input(
                label,
                value=value,
                step=step,
                **widget_params
            )
        
        elif widget_type == "checkbox":
            return st.checkbox(
                label,
                value=default_value if default_value is not None else False,
                **widget_params
            )
        
        elif widget_type == "date_input":
            value = default_value if default_value is not None else datetime.date.today()
            return st.date_input(
                label,
                value=value,
                **widget_params
            )
        
        elif widget_type == "time_input":
            value = default_value if default_value is not None else datetime.time(9, 0)
            return st.time_input(
                label,
                value=value,
                **widget_params
            )
        
        elif widget_type == "selectbox":
            # Get options from Literal or Enum
            options = WidgetMapper._get_selectbox_options(field_type)
            index = 0
            if default_value is not None and default_value in options:
                index = options.index(default_value)
            return st.selectbox(
                label,
                options=options,
                index=index,
                **widget_params
            )
        
        elif widget_type == "multiselect":
            # Get element type from List/Set
            element_type = WidgetMapper._get_element_type(field_type)
            options = WidgetMapper._get_selectbox_options(element_type)
            default = list(default_value) if default_value else []
            return st.multiselect(
                label,
                options=options,
                default=default,
                **widget_params
            )
        
        elif widget_type == "nested_form":
            # For nested models, we'll handle this in FormInputRenderer
            st.write(f"**{label}** (nested model)")
            return None
        
        # Fallback to text input
        return st.text_input(
            label,
            value=str(default_value) if default_value else "",
            **widget_params
        )

    @staticmethod
    def _get_selectbox_options(field_type: Type) -> List[Any]:
        """Get options for selectbox from Literal or Enum type."""
        origin = get_origin(field_type)
        
        # Handle Literal types
        if origin is Literal:
            return list(get_args(field_type))
        
        # Handle Enum types
        if isinstance(field_type, type) and issubclass(field_type, Enum):
            return [e.value for e in field_type]
        
        return []

    @staticmethod
    def _get_element_type(field_type: Type) -> Type:
        """Get the element type from a List or Set type."""
        origin = get_origin(field_type)
        if origin in (list, List, set, Set):
            args = get_args(field_type)
            if args:
                return args[0]
        return str
