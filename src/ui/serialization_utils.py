"""
Serialization utilities for Pydantic models.

This module provides utilities for serializing and deserializing Pydantic
model instances to/from JSON format, with validation and error handling.
"""

import json
from typing import Type, TypeVar, Tuple, Any

from pydantic import BaseModel, ValidationError


T = TypeVar("T", bound=BaseModel)


class SerializationError(Exception):
    """Exception raised when serialization fails."""
    pass


class DeserializationError(Exception):
    """Exception raised when deserialization fails."""
    pass


class SerializationUtils:
    """Utilities for serializing and deserializing form data."""

    @staticmethod
    def serialize_to_json(instance: BaseModel) -> str:
        """
        Serialize a Pydantic model instance to JSON string.

        Args:
            instance: Pydantic model instance to serialize

        Returns:
            JSON string representation of the model

        Raises:
            SerializationError: If serialization fails
        """
        if instance is None:
            raise SerializationError("Cannot serialize None")
        
        if not isinstance(instance, BaseModel):
            raise SerializationError(
                f"Expected BaseModel instance, got {type(instance).__name__}"
            )
        
        try:
            return instance.model_dump_json()
        except Exception as e:
            raise SerializationError(f"Failed to serialize model: {str(e)}") from e

    @staticmethod
    def deserialize_from_json(json_str: str, model: Type[T]) -> T:
        """
        Deserialize JSON string to a Pydantic model instance.

        Args:
            json_str: JSON string to deserialize
            model: Pydantic model class to deserialize into

        Returns:
            Pydantic model instance

        Raises:
            DeserializationError: If deserialization fails
        """
        if not json_str:
            raise DeserializationError("Cannot deserialize empty string")
        
        if not isinstance(json_str, str):
            raise DeserializationError(
                f"Expected string, got {type(json_str).__name__}"
            )
        
        try:
            return model.model_validate_json(json_str)
        except json.JSONDecodeError as e:
            raise DeserializationError(f"Invalid JSON format: {str(e)}") from e
        except ValidationError as e:
            errors = e.errors()
            # Check if this is a JSON parsing error (type=json_invalid)
            for err in errors:
                if err.get("type") == "json_invalid":
                    raise DeserializationError(
                        f"Invalid JSON format: {err.get('msg', 'JSON parsing error')}"
                    ) from e
            # Otherwise it's a validation error
            error_messages = [
                f"{err['loc'][0] if err['loc'] else 'field'}: {err['msg']}"
                for err in errors
            ]
            raise DeserializationError(
                f"Validation failed: {'; '.join(error_messages)}"
            ) from e
        except Exception as e:
            raise DeserializationError(f"Failed to deserialize: {str(e)}") from e

    @staticmethod
    def pretty_print_json(json_str: str) -> str:
        """
        Format JSON string for human-readable output.

        Args:
            json_str: JSON string to format

        Returns:
            Pretty-printed JSON string with indentation

        Raises:
            SerializationError: If the input is not valid JSON
        """
        if not json_str:
            raise SerializationError("Cannot format empty string")
        
        try:
            parsed = json.loads(json_str)
            return json.dumps(parsed, indent=2, ensure_ascii=False, sort_keys=True)
        except json.JSONDecodeError as e:
            raise SerializationError(f"Invalid JSON format: {str(e)}") from e

    @staticmethod
    def validate_serialized_data(
        json_str: str, model: Type[BaseModel]
    ) -> Tuple[bool, str]:
        """
        Validate serialized data against a Pydantic model.

        Args:
            json_str: JSON string to validate
            model: Pydantic model class to validate against

        Returns:
            Tuple of (is_valid, error_message)
            - is_valid: True if data is valid, False otherwise
            - error_message: Empty string if valid, error description if invalid
        """
        if not json_str:
            return False, "Cannot validate empty string"
        
        try:
            model.model_validate_json(json_str)
            return True, ""
        except json.JSONDecodeError as e:
            return False, f"Invalid JSON format: {str(e)}"
        except ValidationError as e:
            errors = e.errors()
            # Check if this is a JSON parsing error (type=json_invalid)
            for err in errors:
                if err.get("type") == "json_invalid":
                    return False, f"Invalid JSON format: {err.get('msg', 'JSON parsing error')}"
            # Otherwise it's a validation error
            error_messages = [
                f"{err['loc'][0] if err['loc'] else 'field'}: {err['msg']}"
                for err in errors
            ]
            return False, f"Validation failed: {'; '.join(error_messages)}"
        except Exception as e:
            return False, f"Validation error: {str(e)}"

    @staticmethod
    def serialize_instance_pretty(instance: BaseModel) -> str:
        """
        Serialize a Pydantic model instance to pretty-printed JSON.

        Convenience method that combines serialize_to_json and pretty_print_json.

        Args:
            instance: Pydantic model instance to serialize

        Returns:
            Pretty-printed JSON string

        Raises:
            SerializationError: If serialization fails
        """
        json_str = SerializationUtils.serialize_to_json(instance)
        return SerializationUtils.pretty_print_json(json_str)
