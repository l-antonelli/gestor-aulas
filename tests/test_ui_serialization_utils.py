"""Tests for SerializationUtils module."""

import pytest
import json

from src.ui.serialization_utils import (
    SerializationUtils,
    SerializationError,
    DeserializationError,
)
from src.domain.problem import Materia


class TestSerializeToJson:
    """Tests for serialize_to_json method."""

    def test_serialize_simple_model(self):
        """Test serializing a simple Pydantic model."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        result = SerializationUtils.serialize_to_json(materia)

        assert isinstance(result, str)
        parsed = json.loads(result)
        assert parsed["codigo"] == "MAT101"
        assert parsed["nombre"] == "Matemáticas"
        assert parsed["cupo"] == 30
        assert parsed["horas_semanales"] == 4

    def test_serialize_model_with_int_fields(self):
        """Test serializing a model with integer fields."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        result = SerializationUtils.serialize_to_json(materia)
        
        parsed = json.loads(result)
        assert parsed["cupo"] == 30
        assert parsed["horas_semanales"] == 4

    def test_serialize_none_raises_error(self):
        """Test that serializing None raises SerializationError."""
        with pytest.raises(SerializationError, match="Cannot serialize None"):
            SerializationUtils.serialize_to_json(None)

    def test_serialize_non_model_raises_error(self):
        """Test that serializing non-BaseModel raises SerializationError."""
        with pytest.raises(SerializationError, match="Expected BaseModel instance"):
            SerializationUtils.serialize_to_json({"key": "value"})


class TestDeserializeFromJson:
    """Tests for deserialize_from_json method."""

    def test_deserialize_simple_model(self):
        """Test deserializing a simple JSON string to model."""
        json_str = '{"codigo": "MAT101", "nombre": "Matemáticas", "cupo": 30, "horas_semanales": 4}'
        result = SerializationUtils.deserialize_from_json(json_str, Materia)

        assert isinstance(result, Materia)
        assert result.codigo == "MAT101"
        assert result.nombre == "Matemáticas"
        assert result.cupo == 30
        assert result.horas_semanales == 4

    def test_deserialize_model_with_int_fields(self):
        """Test deserializing a model with integer fields."""
        json_str = '{"codigo": "MAT101", "nombre": "Matemáticas", "cupo": 30, "horas_semanales": 4}'
        result = SerializationUtils.deserialize_from_json(json_str, Materia)
        
        assert isinstance(result, Materia)
        assert result.cupo == 30
        assert result.horas_semanales == 4

    def test_deserialize_empty_string_raises_error(self):
        """Test that deserializing empty string raises DeserializationError."""
        with pytest.raises(DeserializationError, match="Cannot deserialize empty string"):
            SerializationUtils.deserialize_from_json("", Materia)

    def test_deserialize_invalid_json_raises_error(self):
        """Test that deserializing invalid JSON raises DeserializationError."""
        with pytest.raises(DeserializationError, match="Invalid JSON format"):
            SerializationUtils.deserialize_from_json("not valid json", Materia)

    def test_deserialize_validation_error(self):
        """Test that validation errors are properly reported."""
        # Missing required field (nombre) and invalid cupo
        json_str = '{"codigo": "MAT101", "cupo": -5}'
        with pytest.raises(DeserializationError, match="Validation failed"):
            SerializationUtils.deserialize_from_json(json_str, Materia)

    def test_deserialize_non_string_raises_error(self):
        """Test that deserializing non-string raises DeserializationError."""
        with pytest.raises(DeserializationError, match="Expected string"):
            SerializationUtils.deserialize_from_json(123, Materia)


class TestPrettyPrintJson:
    """Tests for pretty_print_json method."""

    def test_pretty_print_simple_json(self):
        """Test pretty printing a simple JSON string."""
        json_str = '{"name":"test","value":123}'
        result = SerializationUtils.pretty_print_json(json_str)
        
        assert "  " in result  # Has indentation
        assert "\n" in result  # Has newlines
        parsed = json.loads(result)
        assert parsed["name"] == "test"
        assert parsed["value"] == 123

    def test_pretty_print_preserves_unicode(self):
        """Test that pretty print preserves unicode characters."""
        json_str = '{"nombre":"José García"}'
        result = SerializationUtils.pretty_print_json(json_str)
        
        assert "José García" in result

    def test_pretty_print_sorts_keys(self):
        """Test that pretty print sorts keys alphabetically."""
        json_str = '{"z":"last","a":"first","m":"middle"}'
        result = SerializationUtils.pretty_print_json(json_str)
        
        # Keys should be sorted
        a_pos = result.find('"a"')
        m_pos = result.find('"m"')
        z_pos = result.find('"z"')
        assert a_pos < m_pos < z_pos

    def test_pretty_print_empty_string_raises_error(self):
        """Test that pretty printing empty string raises SerializationError."""
        with pytest.raises(SerializationError, match="Cannot format empty string"):
            SerializationUtils.pretty_print_json("")

    def test_pretty_print_invalid_json_raises_error(self):
        """Test that pretty printing invalid JSON raises SerializationError."""
        with pytest.raises(SerializationError, match="Invalid JSON format"):
            SerializationUtils.pretty_print_json("not valid json")


class TestValidateSerializedData:
    """Tests for validate_serialized_data method."""

    def test_validate_valid_data(self):
        """Test validating valid serialized data."""
        json_str = '{"codigo": "MAT101", "nombre": "Matemáticas", "cupo": 30, "horas_semanales": 4}'
        is_valid, error = SerializationUtils.validate_serialized_data(json_str, Materia)

        assert is_valid is True
        assert error == ""

    def test_validate_empty_string(self):
        """Test validating empty string returns error."""
        is_valid, error = SerializationUtils.validate_serialized_data("", Materia)

        assert is_valid is False
        assert "Cannot validate empty string" in error

    def test_validate_invalid_json(self):
        """Test validating invalid JSON returns error."""
        is_valid, error = SerializationUtils.validate_serialized_data("not json", Materia)

        assert is_valid is False
        assert "Invalid JSON format" in error

    def test_validate_missing_required_field(self):
        """Test validating data with missing required field (nombre is required)."""
        json_str = '{"codigo": "MAT101"}'
        is_valid, error = SerializationUtils.validate_serialized_data(json_str, Materia)

        assert is_valid is False
        assert "Validation failed" in error

    def test_validate_invalid_field_value(self):
        """Test validating data with invalid field value."""
        # Invalid cupo (must be > 0)
        json_str = '{"codigo": "MAT101", "nombre": "Matemáticas", "cupo": 0, "horas_semanales": 4}'
        is_valid, error = SerializationUtils.validate_serialized_data(json_str, Materia)

        assert is_valid is False
        assert "Validation failed" in error


class TestSerializeInstancePretty:
    """Tests for serialize_instance_pretty method."""

    def test_serialize_pretty(self):
        """Test serializing to pretty-printed JSON."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        result = SerializationUtils.serialize_instance_pretty(materia)

        assert "  " in result  # Has indentation
        assert "\n" in result  # Has newlines
        parsed = json.loads(result)
        assert parsed["codigo"] == "MAT101"


class TestRoundTrip:
    """Tests for serialization/deserialization round-trip."""

    def test_round_trip_materia(self):
        """Test round-trip serialization for Materia model."""
        original = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        
        json_str = SerializationUtils.serialize_to_json(original)
        restored = SerializationUtils.deserialize_from_json(json_str, Materia)
        
        assert restored == original
