"""
Tests for Dynamic Model Adaptation.

This module tests that UI components automatically adapt when Pydantic models change,
verifying:
- Adding new fields automatically includes them in forms
- Removing fields automatically excludes them from forms
- Changing field types automatically updates widget selection
- Modifying constraints automatically updates widget parameters
- Adding validators automatically applies them
- Schema introspection is used for dynamic behavior

Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6
"""

import datetime
from typing import Optional, List, Literal
from enum import Enum

import pytest
from pydantic import BaseModel, Field, field_validator

from src.ui.schema_introspector import SchemaIntrospector
from src.ui.widget_mapper import WidgetMapper
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer


# =============================================================================
# Dynamic Test Models - These models simulate model evolution
# =============================================================================

class BaseProduct(BaseModel):
    """Base product model with minimal fields."""
    id: str = Field(..., description="Product ID")
    name: str = Field(..., min_length=1, description="Product name")


class ProductWithNewField(BaseModel):
    """Product model with an additional field (simulates field addition)."""
    id: str = Field(..., description="Product ID")
    name: str = Field(..., min_length=1, description="Product name")
    price: float = Field(..., gt=0, description="Product price")


class ProductWithRemovedField(BaseModel):
    """Product model with a field removed (simulates field removal)."""
    id: str = Field(..., description="Product ID")
    # name field removed


class ProductWithChangedType(BaseModel):
    """Product model with changed field type (simulates type change)."""
    id: str = Field(..., description="Product ID")
    name: str = Field(..., min_length=1, description="Product name")
    quantity: int = Field(..., gt=0, description="Quantity")  # Was float, now int


class ProductWithChangedConstraints(BaseModel):
    """Product model with modified constraints."""
    id: str = Field(..., description="Product ID")
    name: str = Field(..., min_length=3, max_length=100, description="Product name")  # Changed constraints


class ProductWithValidator(BaseModel):
    """Product model with custom validator."""
    id: str = Field(..., description="Product ID")
    name: str = Field(..., min_length=1, description="Product name")
    sku: str = Field(..., description="Stock Keeping Unit")
    
    @field_validator("sku")
    @classmethod
    def validate_sku(cls, v: str) -> str:
        """Validate SKU format: must start with 'SKU-'."""
        if not v.startswith("SKU-"):
            raise ValueError("SKU must start with 'SKU-'")
        return v


# =============================================================================
# Tests for Property 34: Dynamic Field Addition
# =============================================================================

class TestDynamicFieldAddition:
    """Tests that adding new fields to models automatically includes them in forms."""

    def test_new_field_appears_in_schema_introspection(self):
        """Test that a new field is detected by schema introspection."""
        base_fields = SchemaIntrospector.get_fields(BaseProduct)
        extended_fields = SchemaIntrospector.get_fields(ProductWithNewField)
        
        assert "price" not in base_fields
        assert "price" in extended_fields

    def test_new_field_type_is_extractable(self):
        """Test that the type of a new field can be extracted."""
        field_type = SchemaIntrospector.get_field_type(ProductWithNewField, "price")
        assert field_type == float

    def test_new_field_constraints_are_extractable(self):
        """Test that constraints of a new field can be extracted."""
        constraints = SchemaIntrospector.get_field_constraints(ProductWithNewField, "price")
        assert "gt" in constraints
        assert constraints["gt"] == 0

    def test_new_field_widget_is_selected(self):
        """Test that appropriate widget is selected for new field."""
        field_type = SchemaIntrospector.get_field_type(ProductWithNewField, "price")
        widget_type = WidgetMapper.get_widget_type(field_type)
        assert widget_type == "number_input"

    def test_new_field_appears_in_display_data(self):
        """Test that new field appears in form output display data."""
        instance = ProductWithNewField(id="P001", name="Test Product", price=19.99)
        data = FormOutputRenderer.get_display_data(instance)
        
        assert "Price" in data
        assert "19.99" in data["Price"]

    def test_new_field_validation_works(self):
        """Test that validation works for new field."""
        # Valid data
        valid_data = {"id": "P001", "name": "Test", "price": 10.0}
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ProductWithNewField)
        assert is_valid is True
        
        # Invalid data (price <= 0)
        invalid_data = {"id": "P001", "name": "Test", "price": 0}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ProductWithNewField)
        assert is_valid is False
        assert "price" in errors


# =============================================================================
# Tests for Property 35: Dynamic Field Removal
# =============================================================================

class TestDynamicFieldRemoval:
    """Tests that removing fields from models automatically excludes them from forms."""

    def test_removed_field_not_in_schema_introspection(self):
        """Test that a removed field is not detected by schema introspection."""
        base_fields = SchemaIntrospector.get_fields(BaseProduct)
        reduced_fields = SchemaIntrospector.get_fields(ProductWithRemovedField)
        
        assert "name" in base_fields
        assert "name" not in reduced_fields

    def test_removed_field_not_in_display_data(self):
        """Test that removed field does not appear in form output display data."""
        instance = ProductWithRemovedField(id="P001")
        data = FormOutputRenderer.get_display_data(instance)
        
        assert "Name" not in data
        assert "Id" in data

    def test_validation_works_without_removed_field(self):
        """Test that validation works correctly without the removed field."""
        valid_data = {"id": "P001"}
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ProductWithRemovedField)
        assert is_valid is True

    def test_field_count_reflects_removal(self):
        """Test that field count reflects the removal."""
        base_fields = SchemaIntrospector.get_fields(BaseProduct)
        reduced_fields = SchemaIntrospector.get_fields(ProductWithRemovedField)
        
        assert len(base_fields) == 2
        assert len(reduced_fields) == 1


# =============================================================================
# Tests for Property 36: Dynamic Constraint Updates
# =============================================================================

class TestDynamicConstraintUpdates:
    """Tests that modifying constraints automatically updates widget parameters."""

    def test_changed_min_length_constraint(self):
        """Test that changed min_length constraint is detected."""
        base_constraints = SchemaIntrospector.get_field_constraints(BaseProduct, "name")
        changed_constraints = SchemaIntrospector.get_field_constraints(ProductWithChangedConstraints, "name")
        
        assert base_constraints.get("min_length") == 1
        assert changed_constraints.get("min_length") == 3

    def test_new_max_length_constraint(self):
        """Test that new max_length constraint is detected."""
        base_constraints = SchemaIntrospector.get_field_constraints(BaseProduct, "name")
        changed_constraints = SchemaIntrospector.get_field_constraints(ProductWithChangedConstraints, "name")
        
        assert "max_length" not in base_constraints
        assert changed_constraints.get("max_length") == 100

    def test_widget_params_reflect_constraint_changes(self):
        """Test that widget parameters reflect constraint changes."""
        changed_constraints = SchemaIntrospector.get_field_constraints(ProductWithChangedConstraints, "name")
        widget_params = WidgetMapper.apply_constraints_to_widget("text_input", changed_constraints)
        
        assert widget_params.get("max_chars") == 100

    def test_validation_uses_updated_constraints(self):
        """Test that validation uses updated constraints."""
        # Name too short (min_length=3)
        invalid_data = {"id": "P001", "name": "AB"}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ProductWithChangedConstraints)
        assert is_valid is False
        assert "name" in errors
        
        # Name valid (length >= 3)
        valid_data = {"id": "P001", "name": "ABC"}
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ProductWithChangedConstraints)
        assert is_valid is True


# =============================================================================
# Tests for Property 37: Dynamic Type Changes
# =============================================================================

class TestDynamicTypeChanges:
    """Tests that changing field types automatically updates widget selection."""

    def test_type_change_detected(self):
        """Test that type change is detected by schema introspection."""
        # Create models with different types for same conceptual field
        class ModelWithFloat(BaseModel):
            value: float = Field(..., description="A value")
        
        class ModelWithInt(BaseModel):
            value: int = Field(..., description="A value")
        
        float_type = SchemaIntrospector.get_field_type(ModelWithFloat, "value")
        int_type = SchemaIntrospector.get_field_type(ModelWithInt, "value")
        
        assert float_type == float
        assert int_type == int

    def test_widget_changes_with_type(self):
        """Test that widget selection changes with type."""
        # Different types should get appropriate widgets
        class ModelWithStr(BaseModel):
            field: str
        
        class ModelWithBool(BaseModel):
            field: bool
        
        class ModelWithDate(BaseModel):
            field: datetime.date
        
        str_type = SchemaIntrospector.get_field_type(ModelWithStr, "field")
        bool_type = SchemaIntrospector.get_field_type(ModelWithBool, "field")
        date_type = SchemaIntrospector.get_field_type(ModelWithDate, "field")
        
        assert WidgetMapper.get_widget_type(str_type) == "text_input"
        assert WidgetMapper.get_widget_type(bool_type) == "checkbox"
        assert WidgetMapper.get_widget_type(date_type) == "date_input"

    def test_literal_type_gets_selectbox(self):
        """Test that Literal type gets selectbox widget."""
        class ModelWithLiteral(BaseModel):
            status: Literal["active", "inactive", "pending"]
        
        field_type = SchemaIntrospector.get_field_type(ModelWithLiteral, "status")
        widget_type = WidgetMapper.get_widget_type(field_type)
        
        assert widget_type == "selectbox"

    def test_enum_type_gets_selectbox(self):
        """Test that Enum type gets selectbox widget."""
        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"
        
        class ModelWithEnum(BaseModel):
            status: Status
        
        field_type = SchemaIntrospector.get_field_type(ModelWithEnum, "status")
        widget_type = WidgetMapper.get_widget_type(field_type)
        
        assert widget_type == "selectbox"

    def test_list_type_gets_multiselect(self):
        """Test that List type gets multiselect widget."""
        class ModelWithList(BaseModel):
            tags: List[str]
        
        field_type = SchemaIntrospector.get_field_type(ModelWithList, "tags")
        widget_type = WidgetMapper.get_widget_type(field_type)
        
        assert widget_type == "multiselect"

    def test_optional_type_unwrapped_correctly(self):
        """Test that Optional types are unwrapped to get correct widget."""
        class ModelWithOptional(BaseModel):
            optional_int: Optional[int] = None
            optional_str: Optional[str] = None
            optional_bool: Optional[bool] = None
        
        int_type = SchemaIntrospector.get_field_type(ModelWithOptional, "optional_int")
        str_type = SchemaIntrospector.get_field_type(ModelWithOptional, "optional_str")
        bool_type = SchemaIntrospector.get_field_type(ModelWithOptional, "optional_bool")
        
        assert WidgetMapper.get_widget_type(int_type) == "number_input"
        assert WidgetMapper.get_widget_type(str_type) == "text_input"
        assert WidgetMapper.get_widget_type(bool_type) == "checkbox"


# =============================================================================
# Tests for Property 38: Dynamic Validator Application
# =============================================================================

class TestDynamicValidatorApplication:
    """Tests that adding validators automatically applies them."""

    def test_custom_validator_is_applied(self):
        """Test that custom validator is applied during validation."""
        # Invalid SKU (doesn't start with 'SKU-')
        invalid_data = {"id": "P001", "name": "Test", "sku": "INVALID"}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, ProductWithValidator)
        
        assert is_valid is False
        assert "sku" in errors

    def test_valid_data_passes_custom_validator(self):
        """Test that valid data passes custom validator."""
        valid_data = {"id": "P001", "name": "Test", "sku": "SKU-12345"}
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ProductWithValidator)
        
        assert is_valid is True
        assert errors == {}

    def test_multiple_validators_applied(self):
        """Test that multiple validators are all applied."""
        class ModelWithMultipleValidators(BaseModel):
            code: str = Field(..., description="Code")
            value: int = Field(..., gt=0, description="Value")
            
            @field_validator("code")
            @classmethod
            def validate_code_format(cls, v: str) -> str:
                if not v.startswith("CODE-"):
                    raise ValueError("Code must start with 'CODE-'")
                return v
            
            @field_validator("code")
            @classmethod
            def validate_code_length(cls, v: str) -> str:
                if len(v) < 8:
                    raise ValueError("Code must be at least 8 characters")
                return v
        
        # Invalid code format
        invalid_format = {"code": "INVALID", "value": 10}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_format, ModelWithMultipleValidators)
        assert is_valid is False
        assert "code" in errors
        
        # Valid data
        valid_data = {"code": "CODE-123", "value": 10}
        is_valid, errors = FormInputRenderer.validate_form_data(valid_data, ModelWithMultipleValidators)
        assert is_valid is True


# =============================================================================
# Tests for Property 39: Schema Introspection Usage
# =============================================================================

class TestSchemaIntrospectionUsage:
    """Tests that schema introspection is used for dynamic UI generation."""

    def test_introspection_returns_current_fields(self):
        """Test that introspection always returns current model fields."""
        # Create a model dynamically
        class DynamicModel(BaseModel):
            field_a: str
            field_b: int
            field_c: bool
        
        fields = SchemaIntrospector.get_fields(DynamicModel)
        
        assert "field_a" in fields
        assert "field_b" in fields
        assert "field_c" in fields
        assert len(fields) == 3

    def test_introspection_reflects_inheritance(self):
        """Test that introspection reflects inherited fields."""
        class ParentModel(BaseModel):
            parent_field: str
        
        class ChildModel(ParentModel):
            child_field: int
        
        parent_fields = SchemaIntrospector.get_fields(ParentModel)
        child_fields = SchemaIntrospector.get_fields(ChildModel)
        
        assert "parent_field" in parent_fields
        assert "child_field" not in parent_fields
        
        assert "parent_field" in child_fields
        assert "child_field" in child_fields

    def test_introspection_handles_complex_types(self):
        """Test that introspection handles complex field types."""
        class ComplexModel(BaseModel):
            simple_str: str
            optional_int: Optional[int] = None
            literal_choice: Literal["a", "b", "c"]
            list_of_str: List[str] = []
            date_field: datetime.date
            time_field: datetime.time
        
        fields = SchemaIntrospector.get_fields(ComplexModel)
        
        assert len(fields) == 6
        
        # Verify types are extractable
        for field_name in fields:
            field_type = SchemaIntrospector.get_field_type(ComplexModel, field_name)
            assert field_type is not None

    def test_display_data_uses_introspection(self):
        """Test that display data generation uses schema introspection."""
        class TestModel(BaseModel):
            field_one: str = Field(..., description="First field")
            field_two: int = Field(..., description="Second field")
        
        instance = TestModel(field_one="value1", field_two=42)
        data = FormOutputRenderer.get_display_data(instance)
        
        # Labels should be derived from field names via introspection
        assert "Field One" in data
        assert "Field Two" in data

    def test_validation_uses_introspection(self):
        """Test that validation uses schema introspection."""
        class TestModel(BaseModel):
            required_field: str
            optional_field: str = "default"
        
        # Missing required field
        invalid_data = {"optional_field": "value"}
        is_valid, errors = FormInputRenderer.validate_form_data(invalid_data, TestModel)
        
        assert is_valid is False
        assert "required_field" in errors

    def test_widget_selection_uses_introspection(self):
        """Test that widget selection uses schema introspection."""
        class TestModel(BaseModel):
            text_field: str
            number_field: int
            bool_field: bool
            date_field: datetime.date
        
        for field_name in ["text_field", "number_field", "bool_field", "date_field"]:
            field_type = SchemaIntrospector.get_field_type(TestModel, field_name)
            widget_type = WidgetMapper.get_widget_type(field_type)
            
            # Widget type should be determined based on introspected type
            assert widget_type is not None
            assert isinstance(widget_type, str)


# =============================================================================
# Tests for Model Evolution Scenarios
# =============================================================================

class TestModelEvolutionScenarios:
    """Tests for realistic model evolution scenarios."""

    def test_adding_optional_field_with_default(self):
        """Test adding an optional field with default value."""
        class V1Model(BaseModel):
            id: str
            name: str
        
        class V2Model(BaseModel):
            id: str
            name: str
            description: str = ""  # New optional field
        
        v1_fields = SchemaIntrospector.get_fields(V1Model)
        v2_fields = SchemaIntrospector.get_fields(V2Model)
        
        assert "description" not in v1_fields
        assert "description" in v2_fields
        assert not SchemaIntrospector.is_field_required(V2Model, "description")

    def test_making_field_required(self):
        """Test changing a field from optional to required."""
        class OptionalModel(BaseModel):
            id: str
            status: str = "pending"
        
        class RequiredModel(BaseModel):
            id: str
            status: str  # Now required
        
        assert not SchemaIntrospector.is_field_required(OptionalModel, "status")
        assert SchemaIntrospector.is_field_required(RequiredModel, "status")

    def test_changing_field_type_from_str_to_enum(self):
        """Test changing field type from str to Enum."""
        class Status(Enum):
            ACTIVE = "active"
            INACTIVE = "inactive"
        
        class StrModel(BaseModel):
            status: str
        
        class EnumModel(BaseModel):
            status: Status
        
        str_type = SchemaIntrospector.get_field_type(StrModel, "status")
        enum_type = SchemaIntrospector.get_field_type(EnumModel, "status")
        
        assert WidgetMapper.get_widget_type(str_type) == "text_input"
        assert WidgetMapper.get_widget_type(enum_type) == "selectbox"

    def test_adding_constraints_to_existing_field(self):
        """Test adding constraints to an existing field."""
        class UnconstrainedModel(BaseModel):
            value: int
        
        class ConstrainedModel(BaseModel):
            value: int = Field(..., gt=0, le=100)
        
        unconstrained = SchemaIntrospector.get_field_constraints(UnconstrainedModel, "value")
        constrained = SchemaIntrospector.get_field_constraints(ConstrainedModel, "value")
        
        assert "gt" not in unconstrained
        assert "le" not in unconstrained
        assert constrained.get("gt") == 0
        assert constrained.get("le") == 100

    def test_renaming_field_via_alias(self):
        """Test that field aliases are handled correctly."""
        class ModelWithAlias(BaseModel):
            internal_name: str = Field(..., alias="externalName")
        
        fields = SchemaIntrospector.get_fields(ModelWithAlias)
        
        # The field should be accessible by its Python name
        assert "internal_name" in fields

    def test_nested_model_field_addition(self):
        """Test adding a nested model field."""
        class Address(BaseModel):
            street: str
            city: str
        
        class PersonV1(BaseModel):
            name: str
        
        class PersonV2(BaseModel):
            name: str
            address: Address  # New nested field
        
        v1_fields = SchemaIntrospector.get_fields(PersonV1)
        v2_fields = SchemaIntrospector.get_fields(PersonV2)
        
        assert "address" not in v1_fields
        assert "address" in v2_fields
        
        address_type = SchemaIntrospector.get_field_type(PersonV2, "address")
        assert SchemaIntrospector.is_nested_model(address_type)


# =============================================================================
# Tests for Edge Cases
# =============================================================================

class TestDynamicAdaptationEdgeCases:
    """Tests for edge cases in dynamic model adaptation."""

    def test_empty_model(self):
        """Test handling of model with no fields."""
        class EmptyModel(BaseModel):
            pass
        
        fields = SchemaIntrospector.get_fields(EmptyModel)
        assert len(fields) == 0

    def test_model_with_only_optional_fields(self):
        """Test model with only optional fields."""
        class AllOptionalModel(BaseModel):
            field_a: str = "default_a"
            field_b: int = 0
            field_c: bool = False
        
        fields = SchemaIntrospector.get_fields(AllOptionalModel)
        
        for field_name in fields:
            assert not SchemaIntrospector.is_field_required(AllOptionalModel, field_name)

    def test_model_with_complex_default_factory(self):
        """Test model with default_factory for complex defaults."""
        class ModelWithFactory(BaseModel):
            items: List[str] = Field(default_factory=list)
            created_at: datetime.date = Field(default_factory=datetime.date.today)
        
        fields = SchemaIntrospector.get_fields(ModelWithFactory)
        
        assert "items" in fields
        assert "created_at" in fields
        assert not SchemaIntrospector.is_field_required(ModelWithFactory, "items")
        assert not SchemaIntrospector.is_field_required(ModelWithFactory, "created_at")

    def test_deeply_nested_model(self):
        """Test handling of deeply nested models."""
        class Level3(BaseModel):
            value: str
        
        class Level2(BaseModel):
            level3: Level3
        
        class Level1(BaseModel):
            level2: Level2
        
        level2_type = SchemaIntrospector.get_field_type(Level1, "level2")
        assert SchemaIntrospector.is_nested_model(level2_type)
        
        level3_type = SchemaIntrospector.get_field_type(Level2, "level3")
        assert SchemaIntrospector.is_nested_model(level3_type)

