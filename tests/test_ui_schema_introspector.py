"""Tests for Schema Introspector module."""

import pytest
from typing import Optional, List
from datetime import date, time
from pydantic import BaseModel, Field

from src.ui.schema_introspector import SchemaIntrospector
from src.domain.problem import Materia, Comision, Aula


class TestSchemaIntrospector:
    """Tests for SchemaIntrospector class."""

    def test_get_fields_returns_all_fields(self):
        """Test that get_fields returns all model fields."""
        fields = SchemaIntrospector.get_fields(Materia)
        assert "codigo" in fields
        assert "nombre" in fields
        assert "cupo" in fields
        assert "horas_semanales" in fields
        assert "periodo" in fields
        assert "codigo_guarani" in fields
        assert "active" in fields
        assert len(fields) == 7

    def test_get_field_type_string(self):
        """Test get_field_type for string fields."""
        field_type = SchemaIntrospector.get_field_type(Materia, "codigo")
        # Codigo is a NewType of str
        assert field_type.__supertype__ == str or field_type == str

    def test_get_field_type_int(self):
        """Test get_field_type for integer fields."""
        field_type = SchemaIntrospector.get_field_type(Materia, "cupo")
        assert field_type == int

    def test_get_field_type_invalid_field(self):
        """Test get_field_type raises error for invalid field."""
        with pytest.raises(ValueError, match="Field 'invalid' not found"):
            SchemaIntrospector.get_field_type(Materia, "invalid")

    def test_is_field_required_true(self):
        """Test is_field_required for required fields."""
        assert SchemaIntrospector.is_field_required(Materia, "codigo") is True
        assert SchemaIntrospector.is_field_required(Materia, "nombre") is True

    def test_is_field_required_false(self):
        """Test is_field_required for optional fields."""
        # Aula has optional fields
        assert SchemaIntrospector.is_field_required(Aula, "tipo") is False
        assert SchemaIntrospector.is_field_required(Aula, "descripcion") is False

    def test_get_field_description(self):
        """Test get_field_description returns description."""
        desc = SchemaIntrospector.get_field_description(Materia, "codigo")
        assert desc == "Unique subject code (codigo_plan)"

    def test_get_field_description_empty(self):
        """Test get_field_description returns empty string when no description."""
        class SimpleModel(BaseModel):
            name: str
        
        desc = SchemaIntrospector.get_field_description(SimpleModel, "name")
        assert desc == ""

    def test_get_default_value_none_for_required(self):
        """Test get_default_value returns None for required fields."""
        default = SchemaIntrospector.get_default_value(Materia, "codigo")
        assert default is None

    def test_get_default_value_returns_default(self):
        """Test get_default_value returns actual default."""
        default = SchemaIntrospector.get_default_value(Aula, "tipo")
        assert default == "teorica"

    def test_get_field_constraints_gt(self):
        """Test get_field_constraints extracts gt constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Materia, "cupo")
        assert "gt" in constraints
        assert constraints["gt"] == 0

    def test_get_field_constraints_min_length(self):
        """Test get_field_constraints extracts min_length constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Materia, "nombre")
        assert "min_length" in constraints
        assert constraints["min_length"] == 1

    def test_is_nested_model_false(self):
        """Test is_nested_model returns False for primitive types."""
        assert SchemaIntrospector.is_nested_model(str) is False
        assert SchemaIntrospector.is_nested_model(int) is False
        assert SchemaIntrospector.is_nested_model(bool) is False

    def test_is_nested_model_true(self):
        """Test is_nested_model returns True for Pydantic models."""
        assert SchemaIntrospector.is_nested_model(Materia) is True
        assert SchemaIntrospector.is_nested_model(Comision) is True

    def test_get_nested_model(self):
        """Test get_nested_model returns the model class."""
        model = SchemaIntrospector.get_nested_model(Materia)
        assert model is Materia

    def test_get_nested_model_raises_for_non_model(self):
        """Test get_nested_model raises error for non-model types."""
        with pytest.raises(ValueError, match="is not a nested Pydantic model"):
            SchemaIntrospector.get_nested_model(str)


class TestSchemaIntrospectorWithNestedModels:
    """Tests for SchemaIntrospector with nested models."""

    def test_is_nested_model_with_optional(self):
        """Test is_nested_model handles Optional types."""
        class Parent(BaseModel):
            child: Optional[Materia] = None

        field_type = SchemaIntrospector.get_field_type(Parent, "child")
        assert SchemaIntrospector.is_nested_model(field_type) is True

    def test_get_nested_model_with_optional(self):
        """Test get_nested_model handles Optional types."""
        class Parent(BaseModel):
            child: Optional[Materia] = None

        field_type = SchemaIntrospector.get_field_type(Parent, "child")
        model = SchemaIntrospector.get_nested_model(field_type)
        assert model is Materia
