"""
Tests for Relationship Entity Selector module.

This module tests the relationship entity selection mechanisms
that enable dropdown selection for foreign key fields.

Requirements: 6.3
"""

import pytest
from pydantic import BaseModel, Field

from src.ui.relationship_selector import (
    RelationshipSelector,
    RELATIONSHIP_REGISTRY,
    register_domain_relationships,
)

# Domain models
from src.domain.problem import (
    Materia, Comision, Horario, Aula,
)
from src.domain.solution import (
    AsignacionAula,
)


class TestRelationshipRegistry:
    """Tests for relationship registration."""

    def test_register_relationship(self):
        """Test that relationships can be registered."""
        class SourceModel(BaseModel):
            target_id: str = Field(..., description="Reference to target")
        
        class TargetModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        RelationshipSelector.register_relationship(
            source_model=SourceModel,
            field_name="target_id",
            target_model=TargetModel,
            display_field="name",
            id_field="id",
        )
        
        key = ("SourceModel", "target_id")
        assert key in RELATIONSHIP_REGISTRY
        
        info = RELATIONSHIP_REGISTRY[key]
        assert info[0] == TargetModel
        assert info[1] == "name"
        assert info[2] == "id"

    def test_get_relationship_info(self):
        """Test getting relationship info."""
        class TestSource(BaseModel):
            ref_id: str = Field(..., description="Reference")
        
        class TestTarget(BaseModel):
            id: str = Field(..., description="ID")
            label: str = Field(..., description="Label")
        
        RelationshipSelector.register_relationship(
            source_model=TestSource,
            field_name="ref_id",
            target_model=TestTarget,
            display_field="label",
            id_field="id",
        )
        
        info = RelationshipSelector.get_relationship_info(TestSource, "ref_id")
        
        assert info is not None
        assert info[0] == TestTarget
        assert info[1] == "label"
        assert info[2] == "id"

    def test_get_relationship_info_not_found(self):
        """Test getting relationship info for unregistered field."""
        class UnregisteredModel(BaseModel):
            some_field: str = Field(..., description="Some field")
        
        info = RelationshipSelector.get_relationship_info(UnregisteredModel, "some_field")
        
        assert info is None

    def test_is_relationship_field(self):
        """Test checking if field is a relationship."""
        class CheckSource(BaseModel):
            related_id: str = Field(..., description="Related ID")
            normal_field: str = Field(..., description="Normal field")
        
        class CheckTarget(BaseModel):
            id: str = Field(..., description="ID")
        
        RelationshipSelector.register_relationship(
            source_model=CheckSource,
            field_name="related_id",
            target_model=CheckTarget,
            display_field="id",
            id_field="id",
        )
        
        assert RelationshipSelector.is_relationship_field(CheckSource, "related_id") is True
        assert RelationshipSelector.is_relationship_field(CheckSource, "normal_field") is False


class TestDomainRelationshipRegistration:
    """Tests for domain model relationship registration."""

    def test_comision_materia_relationship_registered(self):
        """Test that Comision -> Materia relationship is registered."""
        info = RelationshipSelector.get_relationship_info(Comision, "materia_codigo")
        
        assert info is not None
        assert info[0] == Materia
        assert info[1] == "nombre"
        assert info[2] == "codigo"

    def test_horario_comision_relationship_registered(self):
        """Test that Horario -> Comision relationship is registered."""
        info = RelationshipSelector.get_relationship_info(Horario, "comision_id")

        assert info is not None
        assert info[0] == Comision
        assert info[1] == "nombre"
        assert info[2] == "id"

    def test_asignacion_horario_relationship_registered(self):
        """Test that AsignacionAula -> Horario relationship is registered."""
        info = RelationshipSelector.get_relationship_info(AsignacionAula, "horario_id")

        assert info is not None
        assert info[0] == Horario
        assert info[1] == "id"
        assert info[2] == "id"

    def test_asignacion_aula_relationship_registered(self):
        """Test that AsignacionAula -> Aula relationship is registered."""
        info = RelationshipSelector.get_relationship_info(AsignacionAula, "aula_id")
        
        assert info is not None
        assert info[0] == Aula
        assert info[1] == "nombre"
        assert info[2] == "id"


class TestRelationshipFieldIdentification:
    """Tests for identifying relationship fields in domain models."""

    def test_comision_relationship_fields(self):
        """Test identifying relationship fields in Comision."""
        assert RelationshipSelector.is_relationship_field(Comision, "materia_codigo") is True
        assert RelationshipSelector.is_relationship_field(Comision, "id") is False
        assert RelationshipSelector.is_relationship_field(Comision, "nombre") is False

    def test_horario_relationship_fields(self):
        """Test identifying relationship fields in Horario."""
        assert RelationshipSelector.is_relationship_field(Horario, "comision_id") is True
        assert RelationshipSelector.is_relationship_field(Horario, "id") is False
        assert RelationshipSelector.is_relationship_field(Horario, "dia") is False

    def test_asignacion_relationship_fields(self):
        """Test identifying relationship fields in AsignacionAula."""
        assert RelationshipSelector.is_relationship_field(AsignacionAula, "horario_id") is True
        assert RelationshipSelector.is_relationship_field(AsignacionAula, "aula_id") is True
        assert RelationshipSelector.is_relationship_field(AsignacionAula, "id") is False
        assert RelationshipSelector.is_relationship_field(AsignacionAula, "fecha_asignacion") is False


class TestNonRelationshipModels:
    """Tests for models without relationship fields."""

    def test_materia_has_no_relationships(self):
        """Test that Materia has no registered relationship fields."""
        for field_name in Materia.model_fields:
            assert RelationshipSelector.is_relationship_field(Materia, field_name) is False

    def test_aula_has_no_relationships(self):
        """Test that Aula has no registered relationship fields."""
        for field_name in Aula.model_fields:
            assert RelationshipSelector.is_relationship_field(Aula, field_name) is False


class TestRelationshipTargetModels:
    """Tests for relationship target model information."""

    def test_materia_is_target_for_comision(self):
        """Test that Materia is the target model for Comision.materia_codigo."""
        info = RelationshipSelector.get_relationship_info(Comision, "materia_codigo")
        assert info[0] == Materia

    def test_comision_is_target_for_horario(self):
        """Test that Comision is the target model for Horario.comision_id."""
        info = RelationshipSelector.get_relationship_info(Horario, "comision_id")
        assert info[0] == Comision

    def test_aula_is_target_for_asignacion(self):
        """Test that Aula is the target model for AsignacionAula.aula_id."""
        info = RelationshipSelector.get_relationship_info(AsignacionAula, "aula_id")
        assert info[0] == Aula


class TestRelationshipDisplayFields:
    """Tests for relationship display field configuration."""

    def test_materia_display_field_is_nombre(self):
        """Test that Materia display field is 'nombre'."""
        info = RelationshipSelector.get_relationship_info(Comision, "materia_codigo")
        assert info[1] == "nombre"

    def test_comision_display_field_is_nombre(self):
        """Test that Comision display field is 'nombre'."""
        info = RelationshipSelector.get_relationship_info(Horario, "comision_id")
        assert info[1] == "nombre"

    def test_aula_display_field_is_nombre(self):
        """Test that Aula display field is 'nombre'."""
        info = RelationshipSelector.get_relationship_info(AsignacionAula, "aula_id")
        assert info[1] == "nombre"


class TestRelationshipIdFields:
    """Tests for relationship ID field configuration."""

    def test_materia_id_field_is_codigo(self):
        """Test that Materia ID field is 'codigo'."""
        info = RelationshipSelector.get_relationship_info(Comision, "materia_codigo")
        assert info[2] == "codigo"

    def test_comision_id_field_is_id(self):
        """Test that Comision ID field is 'id'."""
        info = RelationshipSelector.get_relationship_info(Horario, "comision_id")
        assert info[2] == "id"

    def test_aula_id_field_is_id(self):
        """Test that Aula ID field is 'id'."""
        info = RelationshipSelector.get_relationship_info(AsignacionAula, "aula_id")
        assert info[2] == "id"
