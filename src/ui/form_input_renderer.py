"""
Form Input Renderer Module.

Provides utilities for generating form input components from Pydantic models,
enabling automatic form generation with validation support.
"""

from typing import Any, Callable, Dict, List, Optional, Tuple, Type

import streamlit as st
from pydantic import BaseModel, ValidationError

from src.ui.schema_introspector import SchemaIntrospector
from src.ui.widget_mapper import WidgetMapper


# Error message templates for different constraint types
CONSTRAINT_ERROR_MESSAGES = {
    "gt": "Value must be greater than {constraint_value}",
    "ge": "Value must be greater than or equal to {constraint_value}",
    "lt": "Value must be less than {constraint_value}",
    "le": "Value must be less than or equal to {constraint_value}",
    "min_length": "Value must have at least {constraint_value} characters",
    "max_length": "Value must have at most {constraint_value} characters",
    "pattern": "Value must match the pattern: {constraint_value}",
    "required": "This field is required",
    "type_error": "Invalid value type. Expected {expected_type}",
    "value_error": "Invalid value",
}


class ValidationErrorHandler:
    """Handles validation error generation and formatting."""
    
    @staticmethod
    def generate_error_message(
        error_type: str,
        constraint_value: Any = None,
        expected_type: str = None,
        custom_message: str = None,
    ) -> str:
        """
        Generate a descriptive error message for a validation error.
        
        Args:
            error_type: Type of validation error (gt, ge, lt, le, min_length, etc.)
            constraint_value: The constraint value that was violated
            expected_type: Expected type for type errors
            custom_message: Custom error message to use instead of template
            
        Returns:
            Formatted error message string
        """
        if custom_message:
            return custom_message
        
        template = CONSTRAINT_ERROR_MESSAGES.get(error_type, "Validation error")
        
        return template.format(
            constraint_value=constraint_value,
            expected_type=expected_type,
        )
    
    @staticmethod
    def parse_pydantic_error(error: Dict[str, Any]) -> Tuple[str, str]:
        """
        Parse a Pydantic validation error into field name and message.
        
        Args:
            error: Pydantic error dictionary from ValidationError.errors()
            
        Returns:
            Tuple of (field_name, error_message)
        """
        field_name = str(error["loc"][0]) if error["loc"] else "general"
        error_type = error.get("type", "value_error")
        error_msg = error.get("msg", "Validation error")
        
        # Extract constraint info from context if available
        ctx = error.get("ctx", {})
        
        # Map Pydantic error types to our constraint types
        constraint_mapping = {
            "greater_than": "gt",
            "greater_than_equal": "ge",
            "less_than": "lt",
            "less_than_equal": "le",
            "string_too_short": "min_length",
            "string_too_long": "max_length",
            "string_pattern_mismatch": "pattern",
            "missing": "required",
            "value_error": "value_error",
        }
        
        mapped_type = constraint_mapping.get(error_type, error_type)
        
        # Use Pydantic's message if it's descriptive, otherwise generate our own
        if error_msg and error_msg != "Validation error":
            return field_name, error_msg
        
        # Generate message from constraint
        constraint_value = ctx.get("limit_value") or ctx.get("min_length") or ctx.get("max_length")
        return field_name, ValidationErrorHandler.generate_error_message(
            mapped_type, constraint_value
        )
    
    @staticmethod
    def format_field_name(field_name: str) -> str:
        """Format field name for display in error messages."""
        return field_name.replace("_", " ").title()


class FormInputRenderer:
    """Renders form input components from Pydantic models."""

    @staticmethod
    def render_form_input(
        model: Type[BaseModel],
        key: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        default_values: Dict[str, Any] = None,
    ) -> Dict[str, Any]:
        """
        Generate form input fields for all model attributes.
        
        Args:
            model: Pydantic model class
            key: Streamlit key prefix for form state
            exclude_fields: Fields to exclude from form
            field_order: Custom field ordering
            custom_labels: Custom labels for fields (field_name -> label)
            default_values: Default values to pre-populate fields
            
        Returns:
            Dictionary of input values keyed by field name
        """
        exclude_fields = exclude_fields or []
        custom_labels = custom_labels or {}
        default_values = default_values or {}
        
        fields = SchemaIntrospector.get_fields(model)
        
        # Determine field order
        if field_order:
            # Use custom order, but only include fields that exist
            ordered_fields = [f for f in field_order if f in fields and f not in exclude_fields]
            # Add any remaining fields not in custom order
            remaining = [f for f in fields if f not in ordered_fields and f not in exclude_fields]
            ordered_fields.extend(remaining)
        else:
            ordered_fields = [f for f in fields if f not in exclude_fields]
        
        form_data = {}
        
        for field_name in ordered_fields:
            value = FormInputRenderer.render_field_input(
                model=model,
                field_name=field_name,
                key=f"{key}_{field_name}" if key else field_name,
                custom_label=custom_labels.get(field_name),
                default_value=default_values.get(field_name),
            )
            form_data[field_name] = value
        
        return form_data

    @staticmethod
    def render_field_input(
        model: Type[BaseModel],
        field_name: str,
        key: str = None,
        custom_label: str = None,
        default_value: Any = None,
    ) -> Any:
        """
        Render a single field input widget.
        
        Args:
            model: Pydantic model class
            field_name: Name of the field to render
            key: Streamlit widget key
            custom_label: Custom label for the field
            default_value: Default value to pre-populate
            
        Returns:
            The value entered by the user
        """
        field_type = SchemaIntrospector.get_field_type(model, field_name)
        constraints = SchemaIntrospector.get_field_constraints(model, field_name)
        is_required = SchemaIntrospector.is_field_required(model, field_name)
        description = SchemaIntrospector.get_field_description(model, field_name)
        
        # Use provided default or get from model
        if default_value is None:
            default_value = SchemaIntrospector.get_default_value(model, field_name)
        
        # Use custom label or field name
        label = custom_label or field_name
        
        # Check if this is a nested model
        if SchemaIntrospector.is_nested_model(field_type):
            nested_model = SchemaIntrospector.get_nested_model(field_type)
            st.subheader(label.replace("_", " ").title())
            if description:
                st.caption(description)
            return FormInputRenderer.render_form_input(
                model=nested_model,
                key=f"{key}_nested" if key else f"{field_name}_nested",
                default_values=default_value.model_dump() if default_value else None,
            )
        
        return WidgetMapper.render_widget(
            field_name=label,
            field_type=field_type,
            constraints=constraints,
            default_value=default_value,
            description=description,
            key=key,
            required=is_required,
        )

    @staticmethod
    def validate_form_data(
        form_data: Dict[str, Any],
        model: Type[BaseModel],
    ) -> Tuple[bool, Dict[str, List[str]]]:
        """
        Validate form data against Pydantic model.
        
        Args:
            form_data: Dictionary of form field values
            model: Pydantic model class to validate against
            
        Returns:
            Tuple of (is_valid, errors) where errors is a dict mapping
            field names to lists of error messages (supports multiple errors per field)
        """
        errors: Dict[str, List[str]] = {}
        
        # First check required fields
        fields = SchemaIntrospector.get_fields(model)
        for field_name in fields:
            is_required = SchemaIntrospector.is_field_required(model, field_name)
            value = form_data.get(field_name)
            
            if is_required:
                if value is None or (isinstance(value, str) and not value.strip()):
                    if field_name not in errors:
                        errors[field_name] = []
                    errors[field_name].append(
                        ValidationErrorHandler.generate_error_message("required")
                    )
        
        # If we have required field errors, return early
        if errors:
            return False, errors
        
        # Try to instantiate the model to get validation errors
        try:
            model(**form_data)
            return True, {}
        except ValidationError as e:
            for error in e.errors():
                field_name, error_msg = ValidationErrorHandler.parse_pydantic_error(error)
                if field_name not in errors:
                    errors[field_name] = []
                errors[field_name].append(error_msg)
            return False, errors
    
    @staticmethod
    def validate_field_constraints(
        field_name: str,
        value: Any,
        model: Type[BaseModel],
    ) -> List[str]:
        """
        Validate a single field's value against its constraints.
        
        Args:
            field_name: Name of the field to validate
            value: Value to validate
            model: Pydantic model class
            
        Returns:
            List of error messages (empty if valid)
        """
        errors = []
        constraints = SchemaIntrospector.get_field_constraints(model, field_name)
        # field_type is available for future type-specific validation
        _ = SchemaIntrospector.get_field_type(model, field_name)
        
        # Check numeric constraints
        if isinstance(value, (int, float)):
            if "gt" in constraints and value <= constraints["gt"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("gt", constraints["gt"])
                )
            if "ge" in constraints and value < constraints["ge"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("ge", constraints["ge"])
                )
            if "lt" in constraints and value >= constraints["lt"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("lt", constraints["lt"])
                )
            if "le" in constraints and value > constraints["le"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("le", constraints["le"])
                )
        
        # Check string constraints
        if isinstance(value, str):
            if "min_length" in constraints and len(value) < constraints["min_length"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("min_length", constraints["min_length"])
                )
            if "max_length" in constraints and len(value) > constraints["max_length"]:
                errors.append(
                    ValidationErrorHandler.generate_error_message("max_length", constraints["max_length"])
                )
            if "pattern" in constraints:
                import re
                if not re.match(constraints["pattern"], value):
                    errors.append(
                        ValidationErrorHandler.generate_error_message("pattern", constraints["pattern"])
                    )
        
        return errors

    @staticmethod
    def render_form_with_validation(
        model: Type[BaseModel],
        key: str = None,
        exclude_fields: List[str] = None,
        field_order: List[str] = None,
        custom_labels: Dict[str, str] = None,
        default_values: Dict[str, Any] = None,
        submit_label: str = "Submit",
        on_submit: Callable[[BaseModel], None] = None,
    ) -> Optional[BaseModel]:
        """
        Render a form with validation and optional submit handling.
        
        This method:
        - Displays validation errors when form data is invalid
        - Prevents form submission when errors exist
        - Clears errors when they are corrected
        - Supports multiple errors per field
        
        Args:
            model: Pydantic model class
            key: Streamlit key prefix for form state
            exclude_fields: Fields to exclude from form
            field_order: Custom field ordering
            custom_labels: Custom labels for fields
            default_values: Default values to pre-populate fields
            submit_label: Label for submit button
            on_submit: Callback function when form is successfully submitted
            
        Returns:
            Validated model instance if submitted successfully, None otherwise
        """
        form_key = key or f"form_{model.__name__}"
        error_key = f"{form_key}_errors"
        
        # Initialize error state in session state if not present
        if error_key not in st.session_state:
            st.session_state[error_key] = {}
        
        with st.form(key=form_key):
            form_data = FormInputRenderer.render_form_input(
                model=model,
                key=f"{form_key}_input",
                exclude_fields=exclude_fields,
                field_order=field_order,
                custom_labels=custom_labels,
                default_values=default_values,
            )
            
            submitted = st.form_submit_button(submit_label)
            
            if submitted:
                is_valid, errors = FormInputRenderer.validate_form_data(form_data, model)
                
                if not is_valid:
                    # Store errors in session state
                    st.session_state[error_key] = errors
                    # Display all errors
                    FormInputRenderer.display_validation_errors(errors)
                    return None
                
                try:
                    instance = model(**form_data)
                    # Clear errors on successful validation
                    st.session_state[error_key] = {}
                    if on_submit:
                        on_submit(instance)
                    return instance
                except ValidationError as e:
                    # Parse and display Pydantic validation errors
                    errors = {}
                    for error in e.errors():
                        field_name, error_msg = ValidationErrorHandler.parse_pydantic_error(error)
                        if field_name not in errors:
                            errors[field_name] = []
                        errors[field_name].append(error_msg)
                    st.session_state[error_key] = errors
                    FormInputRenderer.display_validation_errors(errors)
                    return None
        
        # Display any existing errors from previous submission
        if st.session_state.get(error_key):
            FormInputRenderer.display_validation_errors(st.session_state[error_key])
        
        return None

    @staticmethod
    def display_validation_errors(errors: Dict[str, List[str]]) -> None:
        """
        Display validation errors in the UI.
        
        Supports displaying multiple errors per field and formats
        field names for readability.
        
        Args:
            errors: Dictionary mapping field names to lists of error messages
        """
        if not errors:
            return
        
        # Count total errors for summary
        total_errors = sum(len(msgs) for msgs in errors.values())
        
        # Display error summary
        if total_errors > 1:
            st.error(f"⚠️ {total_errors} validation errors found. Please correct them before submitting.")
        
        # Display individual field errors
        for field_name, error_messages in errors.items():
            formatted_name = ValidationErrorHandler.format_field_name(field_name)
            for error_msg in error_messages:
                st.error(f"**{formatted_name}**: {error_msg}")
    
    @staticmethod
    def clear_validation_errors(form_key: str) -> None:
        """
        Clear validation errors for a form.
        
        Args:
            form_key: The form key used when rendering the form
        """
        error_key = f"{form_key}_errors"
        if error_key in st.session_state:
            st.session_state[error_key] = {}
    
    @staticmethod
    def has_validation_errors(form_key: str) -> bool:
        """
        Check if a form has validation errors.
        
        Args:
            form_key: The form key used when rendering the form
            
        Returns:
            True if the form has errors, False otherwise
        """
        error_key = f"{form_key}_errors"
        return bool(st.session_state.get(error_key, {}))
    
    @staticmethod
    def get_validation_errors(form_key: str) -> Dict[str, List[str]]:
        """
        Get validation errors for a form.
        
        Args:
            form_key: The form key used when rendering the form
            
        Returns:
            Dictionary mapping field names to lists of error messages
        """
        error_key = f"{form_key}_errors"
        return st.session_state.get(error_key, {})
