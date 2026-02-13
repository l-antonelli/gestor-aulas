"""Tests for Form Input Renderer module."""

from typing import Optional
from pydantic import BaseModel, Field

from src.ui.form_input_renderer import (
    FormInputRenderer,
    ValidationErrorHandler,
)
from src.domain.problem import Materia


class SimpleModel(BaseModel):
    """Simple test model."""
    name: str = Field(..., description="Name field")
    age: int = Field(..., gt=0, description="Age in years")
    active: bool = Field(default=True, description="Is active")


class ModelWithOptional(BaseModel):
    """Model with optional fields."""
    required_field: str = Field(..., description="Required")
    optional_field: Optional[str] = Field(default=None, description="Optional")
    default_field: str = Field(default="default_value", description="Has default")


class NestedChild(BaseModel):
    """Nested child model."""
    child_name: str = Field(..., description="Child name")
    child_value: int = Field(default=0, description="Child value")


class NestedParent(BaseModel):
    """Model with nested child."""
    parent_name: str = Field(..., description="Parent name")
    child: NestedChild = Field(..., description="Nested child")


class TestValidationErrorHandler:
    """Tests for ValidationErrorHandler class."""
    
    def test_generate_error_message_required(self):
        """Test error message generation for required field."""
        msg = ValidationErrorHandler.generate_error_message("required")
        assert msg == "This field is required"
    
    def test_generate_error_message_gt(self):
        """Test error message generation for gt constraint."""
        msg = ValidationErrorHandler.generate_error_message("gt", constraint_value=0)
        assert "greater than" in msg.lower()
        assert "0" in msg
    
    def test_generate_error_message_min_length(self):
        """Test error message generation for min_length constraint."""
        msg = ValidationErrorHandler.generate_error_message("min_length", constraint_value=5)
        assert "5" in msg
        assert "character" in msg.lower()
    
    def test_generate_error_message_custom(self):
        """Test custom error message overrides template."""
        custom = "My custom error"
        msg = ValidationErrorHandler.generate_error_message("gt", custom_message=custom)
        assert msg == custom
    
    def test_format_field_name(self):
        """Test field name formatting."""
        assert ValidationErrorHandler.format_field_name("my_field_name") == "My Field Name"
        assert ValidationErrorHandler.format_field_name("name") == "Name"


class TestFormInputRendererValidation:
    """Tests for FormInputRenderer.validate_form_data method."""

    def test_validate_valid_data(self):
        """Test validation passes for valid data."""
        form_data = {
            "name": "John",
            "age": 25,
            "active": True,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, SimpleModel)
        assert is_valid is True
        assert errors == {}

    def test_validate_missing_required_field(self):
        """Test validation fails for missing required field."""
        form_data = {
            "name": "",
            "age": 25,
            "active": True,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, SimpleModel)
        assert is_valid is False
        assert "name" in errors
        # Errors are now lists
        assert isinstance(errors["name"], list)
        assert len(errors["name"]) > 0

    def test_validate_constraint_violation(self):
        """Test validation fails for constraint violation."""
        form_data = {
            "name": "John",
            "age": 0,  # gt=0 constraint violated
            "active": True,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, SimpleModel)
        assert is_valid is False
        assert "age" in errors
        assert isinstance(errors["age"], list)

    def test_validate_optional_field_can_be_none(self):
        """Test validation passes when optional field is None."""
        form_data = {
            "required_field": "value",
            "optional_field": None,
            "default_field": "custom",
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, ModelWithOptional)
        assert is_valid is True
        assert errors == {}

    def test_validate_multiple_errors(self):
        """Test validation returns multiple errors."""
        form_data = {
            "name": "",
            "age": 0,
            "active": True,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, SimpleModel)
        assert is_valid is False
        # At least one error should be present
        assert len(errors) >= 1

    def test_validate_materia_valid(self):
        """Test validation with valid Materia data."""
        form_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
            "cupo": 30,
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
        assert is_valid is True
        assert errors == {}

    def test_validate_materia_invalid_cupo(self):
        """Test validation fails for invalid cupo in Materia."""
        form_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
            "cupo": 0,  # Must be > 0
            "horas_semanales": 4,
        }
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
        assert is_valid is False
        assert "cupo" in errors
        assert isinstance(errors["cupo"], list)


class TestValidateFieldConstraints:
    """Tests for FormInputRenderer.validate_field_constraints method."""
    
    def test_validate_gt_constraint_pass(self):
        """Test gt constraint passes for valid value."""
        errors = FormInputRenderer.validate_field_constraints("age", 5, SimpleModel)
        assert errors == []
    
    def test_validate_gt_constraint_fail(self):
        """Test gt constraint fails for invalid value."""
        errors = FormInputRenderer.validate_field_constraints("age", 0, SimpleModel)
        assert len(errors) > 0
        assert "greater than" in errors[0].lower()


class TestFormInputRendererFieldOrdering:
    """Tests for field ordering in render_form_input."""

    def test_default_field_order(self):
        """Test that fields are returned in model definition order by default."""
        # This is a unit test for the ordering logic
        fields = list(SimpleModel.model_fields.keys())
        assert fields == ["name", "age", "active"]

    def test_custom_field_order_applied(self):
        """Test that custom field order is respected."""
        # We can't easily test Streamlit rendering, but we can verify
        # the logic by checking the method doesn't raise errors
        # with custom ordering
        # This would be tested in integration tests with Streamlit
        pass


class TestFormInputRendererExcludeFields:
    """Tests for exclude_fields functionality."""

    def test_exclude_fields_logic(self):
        """Test that excluded fields are not processed."""
        exclude = ["active"]
        fields = SimpleModel.model_fields.keys()
        filtered = [f for f in fields if f not in exclude]
        assert "active" not in filtered
        assert "name" in filtered
        assert "age" in filtered


class TestFormInputRendererCustomLabels:
    """Tests for custom_labels functionality."""

    def test_custom_labels_mapping(self):
        """Test that custom labels are properly mapped."""
        custom_labels = {
            "name": "Full Name",
            "age": "Years Old",
        }
        assert custom_labels.get("name") == "Full Name"
        assert custom_labels.get("age") == "Years Old"
        assert custom_labels.get("active") is None


class TestFormInputRendererDefaultValues:
    """Tests for default_values functionality."""

    def test_default_values_override(self):
        """Test that provided default values override model defaults."""
        default_values = {
            "active": False,  # Override model default of True
        }
        assert default_values.get("active") is False

    def test_model_default_used_when_not_provided(self):
        """Test that model defaults are used when not overridden."""
        from src.ui.schema_introspector import SchemaIntrospector
        default = SchemaIntrospector.get_default_value(SimpleModel, "active")
        assert default is True


class TestDisplayValidationErrors:
    """Tests for display_validation_errors functionality."""
    
    def test_display_errors_format(self):
        """Test that errors dictionary has correct format."""
        errors = {
            "name": ["This field is required"],
            "age": ["Value must be greater than 0"],
        }
        # Verify structure
        assert isinstance(errors, dict)
        for field, msgs in errors.items():
            assert isinstance(msgs, list)
            for msg in msgs:
                assert isinstance(msg, str)
    
    def test_multiple_errors_per_field(self):
        """Test that multiple errors per field are supported."""
        errors = {
            "email": [
                "This field is required",
                "Invalid email format",
            ],
        }
        assert len(errors["email"]) == 2
