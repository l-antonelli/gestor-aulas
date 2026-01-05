"""Tests for cascading operations module."""

import pytest
from datetime import date

from src.services.cascading_operations import CascadingOperations
from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_metadata import RelationshipMetadata
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision


class TestCascadingOperations:
    """Test cascading operations functionality."""
    
    def test_apply_cascading_defaults(self):
        """Test that cascading defaults are applied correctly."""
        # Create a parent materia
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        # Apply cascading defaults
        defaults = {
            "nombre": "Comisión Única",
            "numero": 1,
            "cupo": 30,
        }
        
        comision = CascadingOperations.apply_cascading_defaults(
            parent_instance=materia,
            child_model=Comision,
            defaults=defaults,
            foreign_key_field="materia_codigo",
        )
        
        # Verify the child has correct values
        assert comision.materia_codigo == "MAT101"
        assert comision.nombre == "Comisión Única"
        assert comision.numero == 1
        assert comision.cupo == 30
        assert comision.id == "MAT101-C1"  # Generated ID
    
    def test_get_primary_key_value_with_codigo(self):
        """Test extracting primary key from model with 'codigo' field."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        pk = CascadingOperations._get_primary_key_value(materia)
        assert pk == "MAT101"
    
    def test_get_primary_key_value_with_id(self):
        """Test extracting primary key from model with 'id' field."""
        comision = Comision(
            id="COM-001",
            materia_codigo="MAT101",
            nombre="Comisión A",
            numero=1,
            cupo=30,
        )
        
        pk = CascadingOperations._get_primary_key_value(comision)
        assert pk == "COM-001"
    
    def test_generate_child_id_with_numero(self):
        """Test ID generation for child with numero field."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        child_data = {
            "nombre": "Comisión Única",
            "numero": 2,
        }
        
        child_id = CascadingOperations._generate_child_id(
            parent_instance=materia,
            child_model=Comision,
            child_data=child_data,
        )
        
        assert child_id == "MAT101-C2"
    
    def test_generate_child_id_with_nombre(self):
        """Test ID generation for child with nombre field."""
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4
        )
        
        child_data = {
            "nombre": "Especial",
        }
        
        child_id = CascadingOperations._generate_child_id(
            parent_instance=materia,
            child_model=Comision,
            child_data=child_data,
        )
        
        assert child_id == "MAT101-ESP"
    
    def test_get_crud_func_for_model(self):
        """Test getting CRUD function for a model."""
        crud_func = CascadingOperations._get_crud_func_for_model(Materia)
        assert crud_func is not None
        
        crud_func = CascadingOperations._get_crud_func_for_model(Comision)
        assert crud_func is not None
