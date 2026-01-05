"""
Tests for Domain Model Compatibility with UI Components.

This module tests that FormInputRenderer and FormOutputRenderer work correctly
with all domain models in the system, verifying:
- Complete field coverage for all models
- Custom validators are respected
- Relationship entity selection mechanisms work
- Database layer compatibility

Requirements: 6.1, 6.2, 6.3, 6.4
"""

import datetime
from typing import List, Optional, Callable, Dict, Any

import pytest
from pydantic import BaseModel, Field, ValidationError

# Domain models - Problem domain
from src.domain.problem import (
    Alumno,
    Materia,
    Comision,
    Clase,
    Aula,
    HorarioCronograma,
)

# Domain models - Solution domain
from src.domain.solution import (
    Inscripcion,
    Asistencia,
    AsignacionAula,
)

# UI Components
from src.ui.form_input_renderer import FormInputRenderer
from src.ui.form_output_renderer import FormOutputRenderer
from src.ui.schema_introspector import SchemaIntrospector


# =============================================================================
# Test Data Factories
# =============================================================================

def create_valid_alumno() -> Alumno:
    """Create a valid Alumno instance for testing."""
    return Alumno(
        legajo="A-12345",
        email="test@example.com",
        nombre="Juan Pérez",
        dni="12345678",
    )


def create_valid_materia() -> Materia:
    """Create a valid Materia instance for testing."""
    return Materia(
        codigo="MAT101",
        nombre="Matemáticas I",
        cupo=30,
        horas_semanales=4,
    )


def create_valid_comision() -> Comision:
    """Create a valid Comision instance for testing."""
    return Comision(
        id="COM-001",
        materia_codigo="MAT101",
        nombre="Comisión A",
        numero=1,
        cupo=25,
    )


def create_valid_clase() -> Clase:
    """Create a valid Clase instance for testing."""
    return Clase(
        id="CLS-001",
        comision_id="COM-001",
        horario_id="HOR-001",
        dia="Lunes",
    )


def create_valid_aula() -> Aula:
    """Create a valid Aula instance for testing."""
    return Aula(
        id="AULA-001",
        sede="Campus Central",
        nombre="Aula 101",
        capacidad=40,
        tipo="teorica",
        descripcion="Aula de teoría",
    )


def create_valid_horario() -> HorarioCronograma:
    """Create a valid HorarioCronograma instance for testing."""
    return HorarioCronograma(
        id="HOR-001",
        dia_semana="Lunes",
        hora_inicio=datetime.time(8, 0),
        hora_fin=datetime.time(10, 0),
    )


def create_valid_inscripcion() -> Inscripcion:
    """Create a valid Inscripcion instance for testing."""
    return Inscripcion(
        id="INS-001",
        alumno_legajo="A-12345",
        comision_id="COM-001",
        fecha_inscripcion=datetime.date(2024, 3, 1),
        activa=True,
    )


def create_valid_asistencia() -> Asistencia:
    """Create a valid Asistencia instance for testing."""
    return Asistencia(
        id="ASI-001",
        alumno_legajo="A-12345",
        clase_id="CLS-001",
        fecha=datetime.date(2024, 3, 15),
        presente=True,
    )


def create_valid_asignacion() -> AsignacionAula:
    """Create a valid AsignacionAula instance for testing."""
    return AsignacionAula(
        id="ASG-001",
        clase_id="CLS-001",
        aula_id="AULA-001",
        fecha_asignacion=datetime.date(2024, 3, 1),
        vigente=True,
    )


# All domain models with their factory functions
DOMAIN_MODELS = [
    (Alumno, create_valid_alumno),
    (Materia, create_valid_materia),
    (Comision, create_valid_comision),
    (Clase, create_valid_clase),
    (Aula, create_valid_aula),
    (HorarioCronograma, create_valid_horario),
    (Inscripcion, create_valid_inscripcion),
    (Asistencia, create_valid_asistencia),
    (AsignacionAula, create_valid_asignacion),
]


# =============================================================================
# Tests for Property 24: Compatibility with All Domain Models
# =============================================================================

class TestFormInputRendererDomainCompatibility:
    """Tests that FormInputRenderer works with all domain models."""

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_validate_form_data_with_valid_data(self, model_class, factory):
        """Test that valid form data passes validation for all domain models."""
        instance = factory()
        form_data = instance.model_dump()
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, model_class)
        
        assert is_valid is True, f"Validation failed for {model_class.__name__}: {errors}"
        assert errors == {}

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_schema_introspection_returns_all_fields(self, model_class, factory):
        """Test that schema introspection returns all fields for all domain models."""
        fields = SchemaIntrospector.get_fields(model_class)
        model_fields = model_class.model_fields
        
        assert set(fields.keys()) == set(model_fields.keys()), \
            f"Field mismatch for {model_class.__name__}"

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_field_types_are_extractable(self, model_class, factory):
        """Test that field types can be extracted for all domain models."""
        fields = SchemaIntrospector.get_fields(model_class)
        
        for field_name in fields:
            # Should not raise an exception
            field_type = SchemaIntrospector.get_field_type(model_class, field_name)
            assert field_type is not None, \
                f"Could not get type for {model_class.__name__}.{field_name}"

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_field_constraints_are_extractable(self, model_class, factory):
        """Test that field constraints can be extracted for all domain models."""
        fields = SchemaIntrospector.get_fields(model_class)
        
        for field_name in fields:
            # Should not raise an exception
            constraints = SchemaIntrospector.get_field_constraints(model_class, field_name)
            assert isinstance(constraints, dict), \
                f"Constraints should be dict for {model_class.__name__}.{field_name}"


class TestFormOutputRendererDomainCompatibility:
    """Tests that FormOutputRenderer works with all domain models."""

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_get_display_data_returns_all_fields(self, model_class, factory):
        """Test that get_display_data returns all fields for all domain models."""
        instance = factory()
        data = FormOutputRenderer.get_display_data(instance)
        
        model_fields = model_class.model_fields
        expected_labels = {f.replace("_", " ").title() for f in model_fields.keys()}
        
        assert set(data.keys()) == expected_labels, \
            f"Display data field mismatch for {model_class.__name__}"

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_format_field_value_handles_all_types(self, model_class, factory):
        """Test that format_field_value handles all field types in domain models."""
        instance = factory()
        
        for field_name in model_class.model_fields:
            field_value = getattr(instance, field_name)
            field_type = SchemaIntrospector.get_field_type(model_class, field_name)
            
            # Should not raise an exception
            formatted = FormOutputRenderer.format_field_value(field_value, field_type)
            assert isinstance(formatted, str), \
                f"Formatted value should be string for {model_class.__name__}.{field_name}"

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_display_data_values_are_strings(self, model_class, factory):
        """Test that all display data values are strings (read-only format)."""
        instance = factory()
        data = FormOutputRenderer.get_display_data(instance)
        
        for key, value in data.items():
            assert isinstance(value, (str, dict)), \
                f"Value for {key} in {model_class.__name__} should be string or dict"


# =============================================================================
# Tests for Property 25: Custom Validator Respect
# =============================================================================

class TestCustomValidatorRespect:
    """Tests that custom validators defined in domain models are respected."""

    def test_alumno_email_validator(self):
        """Test that Alumno email validator is respected."""
        form_data = {
            "legajo": "A-12345",
            "email": "invalid-email",  # Missing @
            "nombre": "Juan Pérez",
            "dni": "12345678",
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Alumno)
        
        assert is_valid is False
        assert "email" in errors

    def test_alumno_dni_validator(self):
        """Test that Alumno DNI validator is respected."""
        form_data = {
            "legajo": "A-12345",
            "email": "test@example.com",
            "nombre": "Juan Pérez",
            "dni": "123",  # Too short (must be 7-8 digits)
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Alumno)
        
        assert is_valid is False
        assert "dni" in errors

    def test_alumno_legajo_validator(self):
        """Test that Alumno legajo validator is respected."""
        form_data = {
            "legajo": "",  # Empty
            "email": "test@example.com",
            "nombre": "Juan Pérez",
            "dni": "12345678",
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Alumno)
        
        assert is_valid is False
        assert "legajo" in errors

    def test_materia_cupo_constraint(self):
        """Test that Materia cupo constraint (gt=0) is respected."""
        form_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
            "cupo": 0,  # Must be > 0
            "horas_semanales": 4,
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
        
        assert is_valid is False
        assert "cupo" in errors

    def test_materia_horas_semanales_constraint(self):
        """Test that Materia horas_semanales constraint (gt=0) is respected."""
        form_data = {
            "codigo": "MAT101",
            "nombre": "Matemáticas",
            "cupo": 30,
            "horas_semanales": 0,  # Must be > 0
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Materia)
        
        assert is_valid is False
        assert "horas_semanales" in errors

    def test_comision_numero_constraint(self):
        """Test that Comision numero constraint (ge=1) is respected."""
        form_data = {
            "id": "COM-001",
            "materia_codigo": "MAT101",
            "nombre": "Comisión A",
            "numero": 0,  # Must be >= 1
            "cupo": 25,
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Comision)
        
        assert is_valid is False
        assert "numero" in errors

    def test_aula_capacidad_constraint(self):
        """Test that Aula capacidad constraint (gt=0) is respected."""
        form_data = {
            "id": "AULA-001",
            "sede": "Campus Central",
            "nombre": "Aula 101",
            "capacidad": 0,  # Must be > 0
            "tipo": "teorica",
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Aula)
        
        assert is_valid is False
        assert "capacidad" in errors

    def test_clase_dia_validator(self):
        """Test that Clase dia validator is respected."""
        form_data = {
            "id": "CLS-001",
            "comision_id": "COM-001",
            "horario_id": "HOR-001",
            "dia": "InvalidDay",  # Not a valid day
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, Clase)
        
        assert is_valid is False
        assert "dia" in errors

    def test_horario_time_range_validator(self):
        """Test that HorarioCronograma time range validator is respected."""
        form_data = {
            "id": "HOR-001",
            "dia_semana": "Lunes",
            "hora_inicio": datetime.time(10, 0),
            "hora_fin": datetime.time(8, 0),  # End before start
        }
        
        is_valid, errors = FormInputRenderer.validate_form_data(form_data, HorarioCronograma)
        
        assert is_valid is False
        # The error might be on the model level, not a specific field
        assert len(errors) > 0


# =============================================================================
# Tests for Property 26: Relationship Entity Selection
# =============================================================================

class TestRelationshipEntitySelection:
    """Tests for relationship entity selection mechanisms."""

    def test_comision_has_materia_reference(self):
        """Test that Comision has materia_codigo field for relationship."""
        fields = SchemaIntrospector.get_fields(Comision)
        assert "materia_codigo" in fields

    def test_clase_has_comision_reference(self):
        """Test that Clase has comision_id field for relationship."""
        fields = SchemaIntrospector.get_fields(Clase)
        assert "comision_id" in fields

    def test_clase_has_horario_reference(self):
        """Test that Clase has horario_id field for relationship."""
        fields = SchemaIntrospector.get_fields(Clase)
        assert "horario_id" in fields

    def test_inscripcion_has_alumno_reference(self):
        """Test that Inscripcion has alumno_legajo field for relationship."""
        fields = SchemaIntrospector.get_fields(Inscripcion)
        assert "alumno_legajo" in fields

    def test_inscripcion_has_comision_reference(self):
        """Test that Inscripcion has comision_id field for relationship."""
        fields = SchemaIntrospector.get_fields(Inscripcion)
        assert "comision_id" in fields

    def test_asistencia_has_alumno_reference(self):
        """Test that Asistencia has alumno_legajo field for relationship."""
        fields = SchemaIntrospector.get_fields(Asistencia)
        assert "alumno_legajo" in fields

    def test_asistencia_has_clase_reference(self):
        """Test that Asistencia has clase_id field for relationship."""
        fields = SchemaIntrospector.get_fields(Asistencia)
        assert "clase_id" in fields

    def test_asignacion_has_clase_reference(self):
        """Test that AsignacionAula has clase_id field for relationship."""
        fields = SchemaIntrospector.get_fields(AsignacionAula)
        assert "clase_id" in fields

    def test_asignacion_has_aula_reference(self):
        """Test that AsignacionAula has aula_id field for relationship."""
        fields = SchemaIntrospector.get_fields(AsignacionAula)
        assert "aula_id" in fields


# =============================================================================
# Tests for Literal Type Handling (TipoAula)
# =============================================================================

class TestLiteralTypeHandling:
    """Tests for handling Literal types like TipoAula."""

    def test_aula_tipo_is_literal(self):
        """Test that Aula tipo field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Aula, "tipo")
        widget_type = WidgetMapper.get_widget_type(field_type)
        
        # Literal types should use selectbox
        assert widget_type == "selectbox"

    def test_aula_tipo_options(self):
        """Test that Aula tipo has correct options."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Aula, "tipo")
        options = WidgetMapper._get_selectbox_options(field_type)
        
        expected_options = ["teorica", "practica", "laboratorio", "anfiteatro"]
        assert set(options) == set(expected_options)


# =============================================================================
# Tests for Date/Time Field Handling
# =============================================================================

class TestDateTimeFieldHandling:
    """Tests for handling date and time fields in domain models."""

    def test_horario_time_fields(self):
        """Test that HorarioCronograma time fields are handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        hora_inicio_type = SchemaIntrospector.get_field_type(HorarioCronograma, "hora_inicio")
        hora_fin_type = SchemaIntrospector.get_field_type(HorarioCronograma, "hora_fin")
        
        assert WidgetMapper.get_widget_type(hora_inicio_type) == "time_input"
        assert WidgetMapper.get_widget_type(hora_fin_type) == "time_input"

    def test_inscripcion_date_field(self):
        """Test that Inscripcion fecha_inscripcion field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Inscripcion, "fecha_inscripcion")
        
        assert WidgetMapper.get_widget_type(field_type) == "date_input"

    def test_asistencia_date_field(self):
        """Test that Asistencia fecha field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Asistencia, "fecha")
        
        assert WidgetMapper.get_widget_type(field_type) == "date_input"

    def test_asignacion_date_field(self):
        """Test that AsignacionAula fecha_asignacion field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(AsignacionAula, "fecha_asignacion")
        
        assert WidgetMapper.get_widget_type(field_type) == "date_input"


# =============================================================================
# Tests for Boolean Field Handling
# =============================================================================

class TestBooleanFieldHandling:
    """Tests for handling boolean fields in domain models."""

    def test_inscripcion_activa_field(self):
        """Test that Inscripcion activa field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Inscripcion, "activa")
        
        assert WidgetMapper.get_widget_type(field_type) == "checkbox"

    def test_asistencia_presente_field(self):
        """Test that Asistencia presente field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(Asistencia, "presente")
        
        assert WidgetMapper.get_widget_type(field_type) == "checkbox"

    def test_asignacion_vigente_field(self):
        """Test that AsignacionAula vigente field is handled correctly."""
        from src.ui.widget_mapper import WidgetMapper
        
        field_type = SchemaIntrospector.get_field_type(AsignacionAula, "vigente")
        
        assert WidgetMapper.get_widget_type(field_type) == "checkbox"

    def test_boolean_display_formatting(self):
        """Test that boolean values are formatted correctly for display."""
        inscripcion = create_valid_inscripcion()
        data = FormOutputRenderer.get_display_data(inscripcion)
        
        # Active should be formatted as "✓ Sí"
        assert data["Activa"] == "✓ Sí"


# =============================================================================
# Tests for Integer Field Handling with Constraints
# =============================================================================

class TestIntegerFieldConstraints:
    """Tests for handling integer fields with constraints."""

    def test_materia_cupo_gt_constraint(self):
        """Test that Materia cupo has gt=0 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Materia, "cupo")
        assert "gt" in constraints
        assert constraints["gt"] == 0

    def test_materia_horas_semanales_gt_constraint(self):
        """Test that Materia horas_semanales has gt=0 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Materia, "horas_semanales")
        assert "gt" in constraints
        assert constraints["gt"] == 0

    def test_comision_numero_ge_constraint(self):
        """Test that Comision numero has ge=1 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Comision, "numero")
        assert "ge" in constraints
        assert constraints["ge"] == 1

    def test_aula_capacidad_gt_constraint(self):
        """Test that Aula capacidad has gt=0 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Aula, "capacidad")
        assert "gt" in constraints
        assert constraints["gt"] == 0


# =============================================================================
# Tests for String Field Handling with Constraints
# =============================================================================

class TestStringFieldConstraints:
    """Tests for handling string fields with constraints."""

    def test_alumno_nombre_min_length(self):
        """Test that Alumno nombre has min_length=1 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Alumno, "nombre")
        assert "min_length" in constraints
        assert constraints["min_length"] == 1

    def test_materia_nombre_min_length(self):
        """Test that Materia nombre has min_length=1 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Materia, "nombre")
        assert "min_length" in constraints
        assert constraints["min_length"] == 1

    def test_comision_nombre_min_length(self):
        """Test that Comision nombre has min_length=1 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Comision, "nombre")
        assert "min_length" in constraints
        assert constraints["min_length"] == 1

    def test_aula_nombre_min_length(self):
        """Test that Aula nombre has min_length=1 constraint."""
        constraints = SchemaIntrospector.get_field_constraints(Aula, "nombre")
        assert "min_length" in constraints
        assert constraints["min_length"] == 1


# =============================================================================
# Tests for Optional Field Handling
# =============================================================================

class TestOptionalFieldHandling:
    """Tests for handling optional fields with default values."""

    def test_aula_tipo_has_default(self):
        """Test that Aula tipo has default value."""
        default = SchemaIntrospector.get_default_value(Aula, "tipo")
        assert default == "teorica"

    def test_aula_descripcion_has_default(self):
        """Test that Aula descripcion has default value."""
        default = SchemaIntrospector.get_default_value(Aula, "descripcion")
        assert default == ""

    def test_inscripcion_activa_has_default(self):
        """Test that Inscripcion activa has default value."""
        default = SchemaIntrospector.get_default_value(Inscripcion, "activa")
        assert default is True

    def test_asignacion_vigente_has_default(self):
        """Test that AsignacionAula vigente has default value."""
        default = SchemaIntrospector.get_default_value(AsignacionAula, "vigente")
        assert default is True

    def test_optional_fields_not_required(self):
        """Test that fields with defaults are not required."""
        assert not SchemaIntrospector.is_field_required(Aula, "tipo")
        assert not SchemaIntrospector.is_field_required(Aula, "descripcion")
        assert not SchemaIntrospector.is_field_required(Inscripcion, "activa")
        assert not SchemaIntrospector.is_field_required(AsignacionAula, "vigente")


# =============================================================================
# Tests for Required Field Handling
# =============================================================================

class TestRequiredFieldHandling:
    """Tests for handling required fields."""

    def test_alumno_required_fields(self):
        """Test that Alumno required fields are identified correctly."""
        assert SchemaIntrospector.is_field_required(Alumno, "legajo")
        assert SchemaIntrospector.is_field_required(Alumno, "email")
        assert SchemaIntrospector.is_field_required(Alumno, "nombre")
        assert SchemaIntrospector.is_field_required(Alumno, "dni")

    def test_materia_required_fields(self):
        """Test that Materia required fields are identified correctly."""
        assert SchemaIntrospector.is_field_required(Materia, "codigo")
        assert SchemaIntrospector.is_field_required(Materia, "nombre")
        assert SchemaIntrospector.is_field_required(Materia, "cupo")
        assert SchemaIntrospector.is_field_required(Materia, "horas_semanales")

    def test_comision_required_fields(self):
        """Test that Comision required fields are identified correctly."""
        assert SchemaIntrospector.is_field_required(Comision, "id")
        assert SchemaIntrospector.is_field_required(Comision, "materia_codigo")
        assert SchemaIntrospector.is_field_required(Comision, "nombre")
        assert SchemaIntrospector.is_field_required(Comision, "numero")
        assert SchemaIntrospector.is_field_required(Comision, "cupo")


# =============================================================================
# Tests for Field Description Handling
# =============================================================================

class TestFieldDescriptionHandling:
    """Tests for handling field descriptions."""

    def test_alumno_field_descriptions(self):
        """Test that Alumno field descriptions are extracted correctly."""
        assert SchemaIntrospector.get_field_description(Alumno, "legajo") != ""
        assert SchemaIntrospector.get_field_description(Alumno, "email") != ""
        assert SchemaIntrospector.get_field_description(Alumno, "nombre") != ""
        assert SchemaIntrospector.get_field_description(Alumno, "dni") != ""

    def test_materia_field_descriptions(self):
        """Test that Materia field descriptions are extracted correctly."""
        assert SchemaIntrospector.get_field_description(Materia, "codigo") != ""
        assert SchemaIntrospector.get_field_description(Materia, "nombre") != ""
        assert SchemaIntrospector.get_field_description(Materia, "cupo") != ""
        assert SchemaIntrospector.get_field_description(Materia, "horas_semanales") != ""

    @pytest.mark.parametrize("model_class,factory", DOMAIN_MODELS)
    def test_all_fields_have_descriptions(self, model_class, factory):
        """Test that all fields in domain models have descriptions."""
        fields = SchemaIntrospector.get_fields(model_class)
        
        for field_name in fields:
            description = SchemaIntrospector.get_field_description(model_class, field_name)
            # All domain model fields should have descriptions
            assert description != "", \
                f"Field {model_class.__name__}.{field_name} should have a description"
