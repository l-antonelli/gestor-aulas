"""Tests for Form Output Renderer module."""

import datetime
from enum import Enum
from typing import Optional, List

from pydantic import BaseModel, Field

from src.ui.form_output_renderer import FormOutputRenderer
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


class StatusEnum(Enum):
    """Status enumeration."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    PENDING = "pending"


class ModelWithEnum(BaseModel):
    """Model with enum field."""
    name: str = Field(..., description="Name")
    status: StatusEnum = Field(..., description="Status")


class ModelWithDates(BaseModel):
    """Model with date/time fields."""
    name: str = Field(..., description="Name")
    birth_date: datetime.date = Field(..., description="Birth date")
    created_at: datetime.datetime = Field(..., description="Created timestamp")
    start_time: datetime.time = Field(..., description="Start time")


class ModelWithList(BaseModel):
    """Model with list field."""
    name: str = Field(..., description="Name")
    tags: List[str] = Field(default_factory=list, description="Tags")


class TestFormatFieldValue:
    """Tests for FormOutputRenderer.format_field_value method."""

    def test_format_none_value(self):
        """Test formatting None value."""
        result = FormOutputRenderer.format_field_value(None, str)
        assert result == "—"

    def test_format_string_value(self):
        """Test formatting string value."""
        result = FormOutputRenderer.format_field_value("Hello World", str)
        assert result == "Hello World"

    def test_format_integer_value(self):
        """Test formatting integer value with thousands separator."""
        result = FormOutputRenderer.format_field_value(1234567, int)
        assert result == "1,234,567"

    def test_format_float_value(self):
        """Test formatting float value with decimal places."""
        result = FormOutputRenderer.format_field_value(1234.567, float)
        assert result == "1,234.57"

    def test_format_boolean_true(self):
        """Test formatting True boolean."""
        result = FormOutputRenderer.format_field_value(True, bool)
        assert result == "✓ Sí"

    def test_format_boolean_false(self):
        """Test formatting False boolean."""
        result = FormOutputRenderer.format_field_value(False, bool)
        assert result == "✗ No"

    def test_format_date_value(self):
        """Test formatting date value."""
        date_val = datetime.date(2024, 6, 15)
        result = FormOutputRenderer.format_field_value(date_val, datetime.date)
        assert result == "2024-06-15"

    def test_format_datetime_value(self):
        """Test formatting datetime value."""
        dt_val = datetime.datetime(2024, 6, 15, 14, 30, 45)
        result = FormOutputRenderer.format_field_value(dt_val, datetime.datetime)
        assert result == "2024-06-15 14:30:45"

    def test_format_time_value(self):
        """Test formatting time value."""
        time_val = datetime.time(14, 30, 45)
        result = FormOutputRenderer.format_field_value(time_val, datetime.time)
        assert result == "14:30:45"

    def test_format_enum_value(self):
        """Test formatting enum value."""
        result = FormOutputRenderer.format_field_value(StatusEnum.ACTIVE, StatusEnum)
        assert result == "active"

    def test_format_list_value(self):
        """Test formatting list value."""
        result = FormOutputRenderer.format_field_value(["a", "b", "c"], list)
        assert result == "a, b, c"

    def test_format_empty_list(self):
        """Test formatting empty list."""
        result = FormOutputRenderer.format_field_value([], list)
        assert result == "—"

    def test_format_set_value(self):
        """Test formatting set value."""
        result = FormOutputRenderer.format_field_value({"x", "y"}, set)
        # Sets are unordered, so check both items are present
        assert "x" in result
        assert "y" in result


class TestGetDisplayData:
    """Tests for FormOutputRenderer.get_display_data method."""

    def test_get_display_data_simple_model(self):
        """Test getting display data from simple model."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance)
        
        assert "Name" in data
        assert "Age" in data
        assert "Active" in data
        assert data["Name"] == "John"
        assert data["Age"] == "25"
        assert data["Active"] == "✓ Sí"

    def test_get_display_data_with_exclude_fields(self):
        """Test excluding fields from display data."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance, exclude_fields=["active"])
        
        assert "Name" in data
        assert "Age" in data
        assert "Active" not in data

    def test_get_display_data_with_custom_labels(self):
        """Test custom labels in display data."""
        instance = SimpleModel(name="John", age=25, active=True)
        custom_labels = {"name": "Full Name", "age": "Years Old"}
        data = FormOutputRenderer.get_display_data(instance, custom_labels=custom_labels)
        
        assert "Full Name" in data
        assert "Years Old" in data
        assert data["Full Name"] == "John"

    def test_get_display_data_with_field_order(self):
        """Test custom field ordering in display data."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance, field_order=["age", "name", "active"])
        
        # Check all fields are present
        assert "Name" in data
        assert "Age" in data
        assert "Active" in data
        
        # Check order by converting to list
        keys = list(data.keys())
        assert keys.index("Age") < keys.index("Name")

    def test_get_display_data_with_optional_none(self):
        """Test display data with None optional field."""
        instance = ModelWithOptional(required_field="value", optional_field=None)
        data = FormOutputRenderer.get_display_data(instance)
        
        assert data["Optional Field"] == "—"

    def test_get_display_data_nested_model(self):
        """Test display data with nested model."""
        child = NestedChild(child_name="Child", child_value=10)
        parent = NestedParent(parent_name="Parent", child=child)
        data = FormOutputRenderer.get_display_data(parent)
        
        assert "Parent Name" in data
        assert "Child" in data
        # Nested model should return a dict
        assert isinstance(data["Child"], dict)
        assert "Child Name" in data["Child"]
        assert data["Child"]["Child Name"] == "Child"

    def test_get_display_data_with_domain_model_materia(self):
        """Test display data with Materia domain model."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        data = FormOutputRenderer.get_display_data(materia)
        
        assert "Codigo" in data
        assert "Nombre" in data
        assert "Cupo" in data
        assert "Horas Semanales" in data
        assert data["Cupo"] == "30"

    def test_get_display_data_with_enum(self):
        """Test display data with enum field."""
        instance = ModelWithEnum(name="Test", status=StatusEnum.ACTIVE)
        data = FormOutputRenderer.get_display_data(instance)
        
        assert data["Status"] == "active"

    def test_get_display_data_with_dates(self):
        """Test display data with date/time fields."""
        instance = ModelWithDates(
            name="Test",
            birth_date=datetime.date(1990, 5, 15),
            created_at=datetime.datetime(2024, 1, 1, 12, 0, 0),
            start_time=datetime.time(9, 30, 0)
        )
        data = FormOutputRenderer.get_display_data(instance)
        
        assert data["Birth Date"] == "1990-05-15"
        assert data["Created At"] == "2024-01-01 12:00:00"
        assert data["Start Time"] == "09:30:00"


class TestCompleteOutputDisplay:
    """Tests for Property 7: Complete Output Display."""

    def test_all_fields_displayed(self):
        """Test that all entity attributes are included in output."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance)
        
        model_fields = set(SimpleModel.model_fields.keys())
        # Convert field names to title case for comparison
        expected_labels = {f.replace("_", " ").title() for f in model_fields}
        
        assert set(data.keys()) == expected_labels

    def test_all_domain_model_fields_displayed(self):
        """Test all fields displayed for domain models."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemáticas",
            cupo=30,
            horas_semanales=4
        )
        data = FormOutputRenderer.get_display_data(materia)

        model_fields = set(Materia.model_fields.keys())
        expected_labels = {f.replace("_", " ").title() for f in model_fields}

        assert set(data.keys()) == expected_labels


class TestReadOnlyDisplay:
    """Tests for Property 10: Read-Only Output Display."""

    def test_get_display_data_returns_strings(self):
        """Test that display data returns formatted strings, not editable values."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance)
        
        # All values should be strings (formatted for display)
        for key, value in data.items():
            assert isinstance(value, (str, dict)), f"Value for {key} should be string or dict"

    def test_display_data_is_immutable_copy(self):
        """Test that modifying display data doesn't affect original instance."""
        instance = SimpleModel(name="John", age=25, active=True)
        data = FormOutputRenderer.get_display_data(instance)
        
        # Modify the display data
        data["Name"] = "Modified"
        
        # Original instance should be unchanged
        assert instance.name == "John"
