"""
Schema Introspection Module.

Provides utilities for extracting field information from Pydantic models
to enable dynamic UI component generation.
"""

from typing import Any, Dict, Type, get_args, get_origin, Union
from pydantic import BaseModel
from pydantic.fields import FieldInfo


class SchemaIntrospector:
    """Introspects Pydantic model schemas to extract field information."""

    @staticmethod
    def get_fields(model: Type[BaseModel]) -> Dict[str, FieldInfo]:
        """
        Extract all fields from a Pydantic model.
        
        Args:
            model: Pydantic model class
            
        Returns:
            Dictionary mapping field names to FieldInfo objects
        """
        return model.model_fields

    @staticmethod
    def get_field_type(model: Type[BaseModel], field_name: str) -> Type:
        """
        Get the Python type of a field.
        
        Args:
            model: Pydantic model class
            field_name: Name of the field
            
        Returns:
            The Python type of the field
        """
        field_info = model.model_fields.get(field_name)
        if field_info is None:
            raise ValueError(f"Field '{field_name}' not found in model {model.__name__}")
        
        annotation = model.model_fields[field_name].annotation
        
        # Handle Optional types (Union[X, None])
        origin = get_origin(annotation)
        if origin is Union:
            args = get_args(annotation)
            # Filter out NoneType
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                return non_none_args[0]
        
        return annotation

    @staticmethod
    def get_field_constraints(model: Type[BaseModel], field_name: str) -> Dict[str, Any]:
        """
        Extract validation constraints from a field.
        
        Args:
            model: Pydantic model class
            field_name: Name of the field
            
        Returns:
            Dictionary of constraints (min_length, max_length, gt, lt, ge, le, regex, etc.)
        """
        field_info = model.model_fields.get(field_name)
        if field_info is None:
            raise ValueError(f"Field '{field_name}' not found in model {model.__name__}")
        
        constraints = {}
        
        # Extract metadata constraints
        if field_info.metadata:
            for meta in field_info.metadata:
                # Handle Pydantic constraint objects
                if hasattr(meta, 'gt'):
                    constraints['gt'] = meta.gt
                if hasattr(meta, 'ge'):
                    constraints['ge'] = meta.ge
                if hasattr(meta, 'lt'):
                    constraints['lt'] = meta.lt
                if hasattr(meta, 'le'):
                    constraints['le'] = meta.le
                if hasattr(meta, 'min_length'):
                    constraints['min_length'] = meta.min_length
                if hasattr(meta, 'max_length'):
                    constraints['max_length'] = meta.max_length
                if hasattr(meta, 'pattern'):
                    constraints['pattern'] = meta.pattern
        
        # Also check direct field_info attributes for Pydantic v2
        json_schema_extra = field_info.json_schema_extra
        if json_schema_extra and isinstance(json_schema_extra, dict):
            constraints.update(json_schema_extra)
        
        return constraints

    @staticmethod
    def is_field_required(model: Type[BaseModel], field_name: str) -> bool:
        """
        Determine if a field is required (no default value).
        
        Args:
            model: Pydantic model class
            field_name: Name of the field
            
        Returns:
            True if field is required, False otherwise
        """
        field_info = model.model_fields.get(field_name)
        if field_info is None:
            raise ValueError(f"Field '{field_name}' not found in model {model.__name__}")
        
        return field_info.is_required()

    @staticmethod
    def get_field_description(model: Type[BaseModel], field_name: str) -> str:
        """
        Get the description of a field from Field definition.
        
        Args:
            model: Pydantic model class
            field_name: Name of the field
            
        Returns:
            Field description or empty string if not defined
        """
        field_info = model.model_fields.get(field_name)
        if field_info is None:
            raise ValueError(f"Field '{field_name}' not found in model {model.__name__}")
        
        return field_info.description or ""

    @staticmethod
    def get_default_value(model: Type[BaseModel], field_name: str) -> Any:
        """
        Get the default value of a field if it exists.
        
        Args:
            model: Pydantic model class
            field_name: Name of the field
            
        Returns:
            Default value or None if no default
        """
        field_info = model.model_fields.get(field_name)
        if field_info is None:
            raise ValueError(f"Field '{field_name}' not found in model {model.__name__}")
        
        if field_info.is_required():
            return None
        
        return field_info.default

    @staticmethod
    def is_nested_model(field_type: Type) -> bool:
        """
        Check if a field type is a nested Pydantic model.
        
        Args:
            field_type: The type to check
            
        Returns:
            True if the type is a Pydantic BaseModel subclass
        """
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
        
        try:
            return isinstance(field_type, type) and issubclass(field_type, BaseModel)
        except TypeError:
            return False

    @staticmethod
    def get_nested_model(field_type: Type) -> Type[BaseModel]:
        """
        Get the nested Pydantic model if field is a nested model.
        
        Args:
            field_type: The type to extract nested model from
            
        Returns:
            The nested Pydantic model class
            
        Raises:
            ValueError: If the type is not a nested Pydantic model
        """
        # Handle Optional types
        origin = get_origin(field_type)
        if origin is Union:
            args = get_args(field_type)
            non_none_args = [arg for arg in args if arg is not type(None)]
            if len(non_none_args) == 1:
                field_type = non_none_args[0]
        
        if SchemaIntrospector.is_nested_model(field_type):
            return field_type
        
        raise ValueError(f"Type {field_type} is not a nested Pydantic model")
