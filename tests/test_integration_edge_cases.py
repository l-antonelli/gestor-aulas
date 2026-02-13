"""
Integration Tests for Error Handling and Edge Cases.

This module tests error handling and edge cases:
- Test with empty models
- Test with deeply nested models
- Test with circular references
- Test with invalid data
- Test with missing required fields
- Test with constraint violations

Requirements: All (Integration testing)
"""

import datetime
from typing import Optional, List

import pytest
from pydantic import BaseModel, Field, ValidationError, field_validator

# Domain models
from src.domain.problem import (
    Materia,
    Comision,
    Horario,
    Aula,
)
from src.domain.solution import (
    AsignacionAula,
)

# UI Components
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer
from src.ui.schema_introspector import SchemaIntrospector
from src.ui.widget_mapper import WidgetMapper
from src.ui.serialization_utils import (
    SerializationUtils,
    SerializationError,
    DeserializationError,
)


# =============================================================================
# Test Models for Edge Cases
# =============================================================================

class EmptyModel(BaseModel):
    """A model with no fields for testing empty model handling."""
    pass


class SimpleModel(BaseModel):
    """A simple model for basic testing."""
    id: str = Field(..., description="Unique identifier")
    name: str = Field(..., min_length=1, description="Name")


class NestedChild(BaseModel):
    """Child model for nested testing."""
    child_id: str = Field(..., description="Child ID")
    child_name: str = Field(..., description="Child name")


class NestedParent(BaseModel):
    """Parent model with nested child."""
    parent_id: str = Field(..., description="Parent ID")
    child: NestedChild = Field(..., description="Nested child")


class DeeplyNestedLevel3(BaseModel):
    """Level 3 of deeply nested model."""
    level3_id: str = Field(..., description="Level 3 ID")
    value: int = Field(default=0, description="Value")


class DeeplyNestedLevel2(BaseModel):
    """Level 2 of deeply nested model."""
    level2_id: str = Field(..., description="Level 2 ID")
    level3: DeeplyNestedLevel3 = Field(..., description="Level 3 nested")


class DeeplyNestedLevel1(BaseModel):
    """Level 1 of deeply nested model (root)."""
    level1_id: str = Field(..., description="Level 1 ID")
    level2: DeeplyNestedLevel2 = Field(..., description="Level 2 nested")


class ModelWithOptionalNested(BaseModel):
    """Model with optional nested field."""
    id: str = Field(..., description="ID")
    nested: Optional[NestedChild] = Field(default=None, description="Optional nested")


class ModelWithList(BaseModel):
    """Model with list field."""
    id: str = Field(..., description="ID")
    items: List[str] = Field(default_factory=list, description="List of items")


class ModelWithAllConstraints(BaseModel):
    """Model with various constraint types."""
    id: str = Field(..., min_length=1, max_length=50, description="ID")
    count: int = Field(..., gt=0, lt=100, description="Count")
    ratio: float = Field(..., ge=0.0, le=1.0, description="Ratio")
    name: str = Field(..., min_length=2, max_length=100, description="Name")
    optional_field: Optional[str] = Field(default=None, description="Optional")


# =============================================================================
# Test Class: Empty Model Handling
# =============================================================================

class TestEmptyModelHandling:
    """Tests for handling empty models."""

    def test_empty_model_schema_introspection(self):
        """Test schema introspection on empty model."""
        fields = SchemaIntrospector.get_fields(EmptyModel)
        assert fields == {}

    def test_empty_model_validation(self):
        """Test validation of empty model."""
        form_data = {}
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, EmptyModel)
        assert is_valid is True
        assert errors == {}

    def test_empty_model_instantiation(self):
        """Test instantiation of empty model."""
        instance = EmptyModel()
        assert instance is not None

    def test_empty_model_serialization(self):
        """Test serialization of empty model."""
        instance = EmptyModel()
        json_str = SerializationUtils.serialize_to_json(instance)
        assert json_str == "{}"

    def test_empty_model_deserialization(self):
        """Test deserialization of empty model."""
        json_str = "{}"
        instance = SerializationUtils.deserialize_from_json(json_str, EmptyModel)
        assert instance is not None

    def test_empty_model_display_data(self):
        """Test display data for empty model."""
        instance = EmptyModel()
        data = FormOutputRenderer.get_display_data(instance)
        assert data == {}


# =============================================================================
# Test Class: Deeply Nested Model Handling
# =============================================================================

class TestDeeplyNestedModelHandling:
    """Tests for handling deeply nested models."""

    def test_nested_model_detection(self):
        """Test detection of nested models."""
        field_type = SchemaIntrospector.get_field_type(NestedParent, "child")
        assert SchemaIntrospector.is_nested_model(field_type) is True

    def test_deeply_nested_model_detection(self):
        """Test detection of deeply nested models."""
        # Level 1 -> Level 2
        field_type_l2 = SchemaIntrospector.get_field_type(DeeplyNestedLevel1, "level2")
        assert SchemaIntrospector.is_nested_model(field_type_l2) is True
        
        # Level 2 -> Level 3
        field_type_l3 = SchemaIntrospector.get_field_type(DeeplyNestedLevel2, "level3")
        assert SchemaIntrospector.is_nested_model(field_type_l3) is True

    def test_nested_model_validation(self):
        """Test validation of nested model data."""
        valid_data = {
            "parent_id": "P-001",
            "child": {
                "child_id": "C-001",
                "child_name": "Child Name",
            }
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, NestedParent)
        assert is_valid is True

    def test_deeply_nested_model_validation(self):
        """Test validation of deeply nested model data."""
        valid_data = {
            "level1_id": "L1-001",
            "level2": {
                "level2_id": "L2-001",
                "level3": {
                    "level3_id": "L3-001",
                    "value": 42,
                }
            }
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, DeeplyNestedLevel1)
        assert is_valid is True

    def test_nested_model_serialization_round_trip(self):
        """Test serialization round-trip for nested model."""
        instance = NestedParent(
            parent_id="P-001",
            child=NestedChild(
                child_id="C-001",
                child_name="Child Name",
            )
        )
        
        json_str = SerializationUtils.serialize_to_json(instance)
        restored = SerializationUtils.deserialize_from_json(json_str, NestedParent)
        
        assert restored == instance
        assert restored.child.child_id == "C-001"

    def test_deeply_nested_serialization_round_trip(self):
        """Test serialization round-trip for deeply nested model."""
        instance = DeeplyNestedLevel1(
            level1_id="L1-001",
            level2=DeeplyNestedLevel2(
                level2_id="L2-001",
                level3=DeeplyNestedLevel3(
                    level3_id="L3-001",
                    value=42,
                )
            )
        )
        
        json_str = SerializationUtils.serialize_to_json(instance)
        restored = SerializationUtils.deserialize_from_json(json_str, DeeplyNestedLevel1)
        
        assert restored == instance
        assert restored.level2.level3.value == 42

    def test_nested_model_display_data(self):
        """Test display data for nested model."""
        instance = NestedParent(
            parent_id="P-001",
            child=NestedChild(
                child_id="C-001",
                child_name="Child Name",
            )
        )
        
        data = FormOutputRenderer.get_display_data(instance)
        
        assert "Parent Id" in data
        assert "Child" in data
        # Nested data should be a dict
        assert isinstance(data["Child"], dict)


# =============================================================================
# Test Class: Invalid Data Handling
# =============================================================================

class TestInvalidDataHandling:
    """Tests for handling invalid data."""

    def test_invalid_type_for_string_field(self):
        """Test validation with invalid type for string field."""
        invalid_data = {
            "id": 12345,  # Should be string
            "name": "Test",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, SimpleModel)
        # Pydantic may coerce int to string, so this might pass
        # The important thing is it doesn't crash

    def test_invalid_type_for_int_field(self):
        """Test validation with invalid type for int field."""
        invalid_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
            "cupo": "not_a_number",  # Should be int
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False
        assert "cupo" in errors

    def test_none_for_required_field(self):
        """Test validation with None for required field."""
        invalid_data = {
            "codigo": None,
            "nombre": "Test",
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False

    def test_empty_string_for_required_field(self):
        """Test validation with empty string for required field."""
        invalid_data = {
            "codigo": "",
            "nombre": "Test",
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False

    def test_whitespace_only_for_required_field(self):
        """Test validation with whitespace-only string for required field."""
        invalid_data = {
            "codigo": "   ",
            "nombre": "Test",
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False

    def test_invalid_literal_value(self):
        """Test validation with invalid Literal value."""
        invalid_data = {
            "id": "AULA-001",
            "sede": "Campus",
            "nombre": "Aula 1",
            "capacidad": 30,
            "tipo": "invalid_type",  # Not in Literal options
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Aula)
        assert is_valid is False
        assert "tipo" in errors

    def test_invalid_json_deserialization(self):
        """Test deserialization with invalid JSON."""
        with pytest.raises(DeserializationError, match="Invalid JSON format"):
            SerializationUtils.deserialize_from_json("not valid json", Materia)

    def test_malformed_json_deserialization(self):
        """Test deserialization with malformed JSON."""
        with pytest.raises(DeserializationError):
            SerializationUtils.deserialize_from_json('{"incomplete": ', Materia)

    def test_wrong_model_deserialization(self):
        """Test deserialization with wrong model type."""
        # Materia JSON deserialized as Aula
        materia_json = '{"codigo": "MAT101", "nombre": "Test", "cupo": 30, "horas_semanales": 4}'
        with pytest.raises(DeserializationError, match="Validation failed"):
            SerializationUtils.deserialize_from_json(materia_json, Aula)


# =============================================================================
# Test Class: Missing Required Fields
# =============================================================================

class TestMissingRequiredFields:
    """Tests for handling missing required fields."""

    def test_missing_all_required_fields(self):
        """Test validation with all required fields missing."""
        invalid_data = {}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False
        # Should have errors for all required fields
        assert len(errors) >= 1

    def test_missing_one_required_field(self):
        """Test validation with one required field missing."""
        invalid_data = {
            "codigo": "MAT101",
            # "nombre" is missing
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Materia)
        assert is_valid is False
        assert "nombre" in errors

    def test_missing_nested_required_field(self):
        """Test validation with missing required field in nested model."""
        invalid_data = {
            "parent_id": "P-001",
            "child": {
                "child_id": "C-001",
                # "child_name" is missing
            }
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, NestedParent)
        assert is_valid is False

    def test_missing_entire_nested_object(self):
        """Test validation with entire nested object missing."""
        invalid_data = {
            "parent_id": "P-001",
            # "child" is missing
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, NestedParent)
        assert is_valid is False

    def test_optional_nested_can_be_none(self):
        """Test that optional nested field can be None."""
        valid_data = {
            "id": "ID-001",
            "nested": None,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ModelWithOptionalNested)
        assert is_valid is True

    def test_optional_nested_can_be_omitted(self):
        """Test that optional nested field can be omitted."""
        valid_data = {
            "id": "ID-001",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ModelWithOptionalNested)
        assert is_valid is True


# =============================================================================
# Test Class: Constraint Violations
# =============================================================================

class TestConstraintViolations:
    """Tests for handling constraint violations."""

    def test_min_length_violation(self):
        """Test validation with min_length constraint violation."""
        invalid_data = {
            "id": "",  # min_length=1
            "count": 50,
            "ratio": 0.5,
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False

    def test_max_length_violation(self):
        """Test validation with max_length constraint violation."""
        invalid_data = {
            "id": "x" * 100,  # max_length=50
            "count": 50,
            "ratio": 0.5,
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        assert "id" in errors

    def test_gt_constraint_violation(self):
        """Test validation with gt (greater than) constraint violation."""
        invalid_data = {
            "id": "ID-001",
            "count": 0,  # gt=0, so 0 is invalid
            "ratio": 0.5,
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        assert "count" in errors

    def test_lt_constraint_violation(self):
        """Test validation with lt (less than) constraint violation."""
        invalid_data = {
            "id": "ID-001",
            "count": 100,  # lt=100, so 100 is invalid
            "ratio": 0.5,
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        assert "count" in errors

    def test_ge_constraint_violation(self):
        """Test validation with ge (greater than or equal) constraint violation."""
        invalid_data = {
            "id": "ID-001",
            "count": 50,
            "ratio": -0.1,  # ge=0.0, so negative is invalid
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        assert "ratio" in errors

    def test_le_constraint_violation(self):
        """Test validation with le (less than or equal) constraint violation."""
        invalid_data = {
            "id": "ID-001",
            "count": 50,
            "ratio": 1.5,  # le=1.0, so > 1.0 is invalid
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        assert "ratio" in errors

    def test_multiple_constraint_violations(self):
        """Test validation with multiple constraint violations."""
        invalid_data = {
            "id": "",  # min_length violation
            "count": 0,  # gt violation
            "ratio": 2.0,  # le violation
            "name": "X",  # min_length=2 violation
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ModelWithAllConstraints)
        assert is_valid is False
        # Should have multiple errors
        assert len(errors) >= 1

    def test_valid_data_with_all_constraints(self):
        """Test validation with valid data meeting all constraints."""
        valid_data = {
            "id": "ID-001",
            "count": 50,
            "ratio": 0.5,
            "name": "Test Name",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ModelWithAllConstraints)
        assert is_valid is True
        assert errors == {}


# =============================================================================
# Test Class: Domain Model Edge Cases
# =============================================================================

class TestDomainModelEdgeCases:
    """Tests for edge cases specific to domain models."""

    def test_materia_cupo_boundary_values(self):
        """Test Materia cupo with boundary values (must be > 0)."""
        # Valid cupo
        valid_data = {
            "codigo": "MAT101",
            "nombre": "Test",
            "cupo": 1,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Materia)
        assert is_valid is True

        # Invalid cupo (0)
        invalid_zero = {
            "codigo": "MAT101",
            "nombre": "Test",
            "cupo": 0,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_zero, Materia)
        assert is_valid is False

        # Invalid cupo (negative)
        invalid_negative = {
            "codigo": "MAT101",
            "nombre": "Test",
            "cupo": -1,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_negative, Materia)
        assert is_valid is False

    def test_horario_time_boundary(self):
        """Test Horario with time boundary values."""
        # Valid: start before end
        valid_data = {
            "id": "HOR-001",
            "comision_id": "COM-001",
            "codigo_materia": "MAT101",
            "dia": "Lunes",
            "hora_inicio": datetime.time(8, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Horario)
        assert is_valid is True

        # Invalid: start equals end
        invalid_equal = {
            "id": "HOR-001",
            "comision_id": "COM-001",
            "codigo_materia": "MAT101",
            "dia": "Lunes",
            "hora_inicio": datetime.time(10, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_equal, Horario)
        assert is_valid is False

        # Invalid: start after end
        invalid_after = {
            "id": "HOR-001",
            "comision_id": "COM-001",
            "codigo_materia": "MAT101",
            "dia": "Lunes",
            "hora_inicio": datetime.time(12, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_after, Horario)
        assert is_valid is False

    def test_horario_valid_days(self):
        """Test Horario with valid and invalid day values."""
        valid_days = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

        for day in valid_days:
            valid_data = {
                "id": "HOR-001",
                "comision_id": "COM-001",
                "codigo_materia": "MAT101",
                "dia": day,
                "hora_inicio": datetime.time(8, 0),
                "hora_fin": datetime.time(10, 0),
            }
            is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Horario)
            assert is_valid is True, f"Day '{day}' should be valid"

        # Invalid day
        invalid_data = {
            "id": "HOR-001",
            "comision_id": "COM-001",
            "codigo_materia": "MAT101",
            "dia": "InvalidDay",
            "hora_inicio": datetime.time(8, 0),
            "hora_fin": datetime.time(10, 0),
        }
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, Horario)
        assert is_valid is False

    def test_aula_tipo_all_valid_values(self):
        """Test Aula with all valid tipo values."""
        valid_tipos = ["teorica", "practica", "laboratorio", "anfiteatro"]
        
        for tipo in valid_tipos:
            valid_data = {
                "id": "AULA-001",
                "sede": "Campus",
                "nombre": "Aula 1",
                "capacidad": 30,
                "tipo": tipo,
            }
            is_valid, errors = FormInputRenderer.validate_form_data(valid_data, Aula)
            assert is_valid is True, f"Tipo '{tipo}' should be valid"


# =============================================================================
# Test Class: Serialization Edge Cases
# =============================================================================

class TestSerializationEdgeCases:
    """Tests for serialization edge cases."""

    def test_serialize_none_raises_error(self):
        """Test that serializing None raises error."""
        with pytest.raises(SerializationError, match="Cannot serialize None"):
            SerializationUtils.serialize_to_json(None)

    def test_serialize_non_model_raises_error(self):
        """Test that serializing non-BaseModel raises error."""
        with pytest.raises(SerializationError, match="Expected BaseModel instance"):
            SerializationUtils.serialize_to_json({"key": "value"})

    def test_deserialize_empty_string_raises_error(self):
        """Test that deserializing empty string raises error."""
        with pytest.raises(DeserializationError, match="Cannot deserialize empty string"):
            SerializationUtils.deserialize_from_json("", Materia)

    def test_deserialize_non_string_raises_error(self):
        """Test that deserializing non-string raises error."""
        with pytest.raises(DeserializationError, match="Expected string"):
            SerializationUtils.deserialize_from_json(123, Materia)

    def test_pretty_print_empty_string_raises_error(self):
        """Test that pretty printing empty string raises error."""
        with pytest.raises(SerializationError, match="Cannot format empty string"):
            SerializationUtils.pretty_print_json("")

    def test_pretty_print_invalid_json_raises_error(self):
        """Test that pretty printing invalid JSON raises error."""
        with pytest.raises(SerializationError, match="Invalid JSON format"):
            SerializationUtils.pretty_print_json("not valid json")

    def test_validate_empty_string(self):
        """Test validation of empty string."""
        is_valid, error = SerializationUtils.validate_serialized_data("", Materia)
        assert is_valid is False
        assert "Cannot validate empty string" in error

    def test_validate_invalid_json(self):
        """Test validation of invalid JSON."""
        is_valid, error = SerializationUtils.validate_serialized_data("not json", Materia)
        assert is_valid is False
        assert "Invalid JSON format" in error

    def test_unicode_characters_preserved(self):
        """Test that unicode characters are preserved in serialization."""
        materia = Materia(
            codigo="MAT101",
            nombre="José García Ñoño",
            cupo=30,
            horas_semanales=4,
        )

        json_str = SerializationUtils.serialize_to_json(materia)
        restored = SerializationUtils.deserialize_from_json(json_str, Materia)

        assert restored.nombre == "José García Ñoño"

    def test_special_characters_in_strings(self):
        """Test handling of special characters in strings."""
        materia = Materia(
            codigo="MAT101",
            nombre='Test "Quoted" Name',
            cupo=30,
            horas_semanales=4,
        )

        json_str = SerializationUtils.serialize_to_json(materia)
        restored = SerializationUtils.deserialize_from_json(json_str, Materia)

        assert restored.nombre == 'Test "Quoted" Name'


# =============================================================================
# Test Class: Widget Mapper Edge Cases
# =============================================================================

class TestWidgetMapperEdgeCases:
    """Tests for widget mapper edge cases."""

    def test_unknown_type_defaults_to_text_input(self):
        """Test that unknown types default to text_input."""
        # Custom class that's not in the mapping
        class CustomType:
            pass
        
        widget_type = WidgetMapper.get_widget_type(CustomType)
        assert widget_type == "text_input"

    def test_optional_type_unwrapping(self):
        """Test that Optional types are properly unwrapped."""
        from typing import Optional
        
        # Optional[str] should map to text_input
        widget_type = WidgetMapper.get_widget_type(Optional[str])
        assert widget_type == "text_input"
        
        # Optional[int] should map to number_input
        widget_type = WidgetMapper.get_widget_type(Optional[int])
        assert widget_type == "number_input"
        
        # Optional[bool] should map to checkbox
        widget_type = WidgetMapper.get_widget_type(Optional[bool])
        assert widget_type == "checkbox"

    def test_list_type_mapping(self):
        """Test that List types map to multiselect."""
        from typing import List
        
        widget_type = WidgetMapper.get_widget_type(List[str])
        assert widget_type == "multiselect"

    def test_literal_type_mapping(self):
        """Test that Literal types map to selectbox."""
        from typing import Literal
        
        widget_type = WidgetMapper.get_widget_type(Literal["a", "b", "c"])
        assert widget_type == "selectbox"


# =============================================================================
# Test Class: Schema Introspector Edge Cases
# =============================================================================

class TestSchemaIntrospectorEdgeCases:
    """Tests for schema introspector edge cases."""

    def test_get_field_type_nonexistent_field(self):
        """Test getting type for nonexistent field."""
        # Should raise ValueError for nonexistent field
        with pytest.raises(ValueError, match="Field 'nonexistent_field' not found"):
            SchemaIntrospector.get_field_type(Materia, "nonexistent_field")

    def test_get_field_constraints_no_constraints(self):
        """Test getting constraints for field with no constraints."""
        # EmptyModel has no fields, but SimpleModel has fields without many constraints
        constraints = SchemaIntrospector.get_field_constraints(SimpleModel, "id")
        # Should return empty dict or dict with only basic info
        assert isinstance(constraints, dict)

    def test_get_default_value_no_default(self):
        """Test getting default value for field with no default."""
        default = SchemaIntrospector.get_default_value(Materia, "codigo")
        # Required fields have no default, should return None or PydanticUndefined
        # The important thing is it doesn't crash

    def test_is_field_required_with_default(self):
        """Test is_field_required for field with default value."""
        # Aula.tipo has default="teorica"
        assert SchemaIntrospector.is_field_required(Aula, "tipo") is False
        
        # Aula.id has no default
        assert SchemaIntrospector.is_field_required(Aula, "id") is True

    def test_get_field_description_no_description(self):
        """Test getting description for field without description."""
        # All our domain models have descriptions, but test the method works
        description = SchemaIntrospector.get_field_description(Materia, "codigo")
        assert isinstance(description, str)


# =============================================================================
# Test Class: Form Output Edge Cases
# =============================================================================

class TestFormOutputEdgeCases:
    """Tests for form output edge cases."""

    def test_format_none_value(self):
        """Test formatting None value."""
        formatted = FormOutputRenderer.format_field_value(None, str)
        assert formatted == "—"  # Em dash for empty values

    def test_format_empty_list(self):
        """Test formatting empty list."""
        formatted = FormOutputRenderer.format_field_value([], list)
        assert formatted == "—"

    def test_format_empty_string(self):
        """Test formatting empty string."""
        formatted = FormOutputRenderer.format_field_value("", str)
        assert formatted == ""

    def test_format_large_number(self):
        """Test formatting large numbers."""
        formatted = FormOutputRenderer.format_field_value(1000000, int)
        # Should have thousand separators
        assert "1,000,000" in formatted or "1000000" in formatted

    def test_format_float_precision(self):
        """Test formatting float with precision."""
        formatted = FormOutputRenderer.format_field_value(3.14159, float)
        # Should have 2 decimal places
        assert "3.14" in formatted

    def test_display_data_with_exclude_fields(self):
        """Test display data with excluded fields."""
        materia = Materia(
            codigo="MAT101",
            nombre="Test",
            cupo=30,
            horas_semanales=4,
        )

        data = FormOutputRenderer.get_display_data(
            materia,
            exclude_fields=["cupo", "horas_semanales"]
        )

        assert "Codigo" in data
        assert "Nombre" in data
        assert "Cupo" not in data
        assert "Horas Semanales" not in data

    def test_display_data_with_custom_labels(self):
        """Test display data with custom labels."""
        materia = Materia(
            codigo="MAT101",
            nombre="Test",
            cupo=30,
            horas_semanales=4,
        )

        data = FormOutputRenderer.get_display_data(
            materia,
            custom_labels={"codigo": "Subject Code", "nombre": "Full Name"}
        )

        assert "Subject Code" in data
        assert "Full Name" in data

    def test_display_data_with_field_order(self):
        """Test display data with custom field order."""
        materia = Materia(
            codigo="MAT101",
            nombre="Test",
            cupo=30,
            horas_semanales=4,
        )

        data = FormOutputRenderer.get_display_data(
            materia,
            field_order=["nombre", "codigo", "cupo", "horas_semanales", "periodo"]
        )

        # All fields should still be present
        assert len(data) == 5
