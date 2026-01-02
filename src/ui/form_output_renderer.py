"""
Form Output Renderer Module.

Provides utilities for displaying Pydantic model instances in a formatted,
read-only layout using Streamlit components.
"""

import datetime
from enum import Enum
from typing import Any, Dict, List, Type, get_args, get_origin, Union

import streamlit as st
from pydantic import BaseModel

from src.ui.schema_introspector import SchemaIntrospector


class FormOutputRenderer:
    """Renders form output components for displaying Pydantic model instances."""

    @staticmethod
    def render_form_output(
        instance: BaseModel,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        show_descriptions: bool = True,
    ) -> None:
        """
        Display a Pydantic model instance in formatted layout.
        
        Args:
            instance: Pydantic model instance to display
            exclude_fields: Fields to exclude from display
            field_order: Custom field ordering
            custom_labels: Custom labels for fields (field_name -> label)
            show_descriptions: Whether to show field descriptions
        """
        exclude_fields = exclude_fields or []
        custom_labels = custom_labels or {}
        
        model = type(instance)
        fields = SchemaIntrospector.get_fields(model)
        
        # Determine field order
        if field_order:
            ordered_fields = [f for f in field_order if f in fields and f not in exclude_fields]
            remaining = [f for f in fields if f not in ordered_fields and f not in exclude_fields]
            ordered_fields.extend(remaining)
        else:
            ordered_fields = [f for f in fields if f not in exclude_fields]
        
        for field_name in ordered_fields:
            field_value = getattr(instance, field_name)
            field_type = SchemaIntrospector.get_field_type(model, field_name)
            description = SchemaIntrospector.get_field_description(model, field_name) if show_descriptions else None
            custom_label = custom_labels.get(field_name)
            
            FormOutputRenderer.render_field_output(
                field_name=field_name,
                field_value=field_value,
                field_type=field_type,
                custom_label=custom_label,
                description=description,
            )

    @staticmethod
    def render_field_output(
        field_name: str,
        field_value: Any,
        field_type: Type,
        custom_label: str = None,
        description: str = None,
    ) -> None:
        """
        Render a single field output.
        
        Args:
            field_name: Name of the field
            field_value: Value of the field
            field_type: Python type of the field
            custom_label: Custom label for the field
            description: Field description to display
        """
        label = custom_label or field_name.replace("_", " ").title()
        
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
        
        # Check if this is a nested Pydantic model
        if SchemaIntrospector.is_nested_model(field_type) and field_value is not None:
            FormOutputRenderer.render_nested_model(
                nested_instance=field_value,
                label=label,
                description=description,
            )
            return
        
        # Format the value for display
        formatted_value = FormOutputRenderer.format_field_value(field_value, field_type)
        
        # Display using Streamlit's metric or text
        col1, col2 = st.columns([1, 2])
        with col1:
            st.markdown(f"**{label}:**")
        with col2:
            st.text(formatted_value)
        
        if description:
            st.caption(f"_{description}_")

    @staticmethod
    def format_field_value(value: Any, field_type: Type) -> str:
        """
        Format a field value for display based on its type.
        
        Args:
            value: The value to format
            field_type: The Python type of the value
            
        Returns:
            Formatted string representation of the value
        """
        if value is None:
            return "—"  # Em dash for empty values
        
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
                origin = get_origin(field_type)
        
        # Handle datetime types
        if isinstance(value, datetime.datetime):
            return value.strftime("%Y-%m-%d %H:%M:%S")
        
        if isinstance(value, datetime.date):
            return value.strftime("%Y-%m-%d")
        
        if isinstance(value, datetime.time):
            return value.strftime("%H:%M:%S")
        
        # Handle boolean
        if isinstance(value, bool):
            return "✓ Sí" if value else "✗ No"
        
        # Handle Enum
        if isinstance(value, Enum):
            return str(value.value)
        
        # Handle lists and sets
        if isinstance(value, (list, set, frozenset)):
            if not value:
                return "—"
            items = [str(item.value) if isinstance(item, Enum) else str(item) for item in value]
            return ", ".join(items)
        
        # Handle numbers with formatting
        if isinstance(value, float):
            return f"{value:,.2f}"
        
        if isinstance(value, int):
            return f"{value:,}"
        
        # Default: convert to string
        return str(value)

    @staticmethod
    def render_nested_model(
        nested_instance: BaseModel,
        label: str = None,
        description: str = None,
        indent_level: int = 0,
    ) -> None:
        """
        Render nested Pydantic model in hierarchical structure.
        
        Args:
            nested_instance: The nested Pydantic model instance
            label: Label for the nested section
            description: Description of the nested model
            indent_level: Current indentation level for hierarchy
        """
        if label:
            st.markdown(f"**{label}:**")
        
        if description:
            st.caption(f"_{description}_")
        
        # Use an expander for nested models to maintain hierarchy
        with st.expander(f"📋 {type(nested_instance).__name__}", expanded=True):
            FormOutputRenderer.render_form_output(
                instance=nested_instance,
                show_descriptions=True,
            )

    @staticmethod
    def render_form_output_card(
        instance: BaseModel,
        title: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> None:
        """
        Display a Pydantic model instance in a card-style container.
        
        Args:
            instance: Pydantic model instance to display
            title: Optional title for the card
            exclude_fields: Fields to exclude from display
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
        """
        with st.container():
            if title:
                st.subheader(title)
            else:
                st.subheader(type(instance).__name__)
            
            st.divider()
            
            FormOutputRenderer.render_form_output(
                instance=instance,
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
            )

    @staticmethod
    def render_entity_list(
        entities: List[BaseModel],
        display_fields: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> None:
        """
        Display a list of entities in a table format.
        
        Args:
            entities: List of Pydantic model instances
            display_fields: Fields to display (if None, shows all)
            custom_labels: Custom labels for column headers
        """
        if not entities:
            st.info("No hay entidades para mostrar.")
            return
        
        custom_labels = custom_labels or {}
        model = type(entities[0])
        fields = SchemaIntrospector.get_fields(model)
        
        # Determine which fields to display
        if display_fields:
            columns = [f for f in display_fields if f in fields]
        else:
            columns = list(fields.keys())
        
        # Create column headers
        headers = [custom_labels.get(col, col.replace("_", " ").title()) for col in columns]
        
        # Build data for display
        data = []
        for entity in entities:
            row = {}
            for col, header in zip(columns, headers):
                value = getattr(entity, col)
                field_type = SchemaIntrospector.get_field_type(model, col)
                row[header] = FormOutputRenderer.format_field_value(value, field_type)
            data.append(row)
        
        # Display as dataframe
        st.dataframe(data, use_container_width=True)

    @staticmethod
    def get_display_data(
        instance: BaseModel,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
    ) -> Dict[str, str]:
        """
        Get formatted display data from a model instance without rendering.
        
        This is useful for testing or when you need the formatted data
        without Streamlit rendering.
        
        Args:
            instance: Pydantic model instance
            exclude_fields: Fields to exclude
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            
        Returns:
            Dictionary mapping labels to formatted values
        """
        exclude_fields = exclude_fields or []
        custom_labels = custom_labels or {}
        
        model = type(instance)
        fields = SchemaIntrospector.get_fields(model)
        
        # Determine field order
        if field_order:
            ordered_fields = [f for f in field_order if f in fields and f not in exclude_fields]
            remaining = [f for f in fields if f not in ordered_fields and f not in exclude_fields]
            ordered_fields.extend(remaining)
        else:
            ordered_fields = [f for f in fields if f not in exclude_fields]
        
        result = {}
        for field_name in ordered_fields:
            field_value = getattr(instance, field_name)
            field_type = SchemaIntrospector.get_field_type(model, field_name)
            label = custom_labels.get(field_name, field_name.replace("_", " ").title())
            
            # Handle nested models
            if SchemaIntrospector.is_nested_model(field_type) and field_value is not None:
                nested_data = FormOutputRenderer.get_display_data(field_value)
                result[label] = nested_data
            else:
                result[label] = FormOutputRenderer.format_field_value(field_value, field_type)
        
        return result
