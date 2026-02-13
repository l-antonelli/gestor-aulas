"""Tests for Solution Domain Entities."""

import pytest
from datetime import date
from pydantic import ValidationError

from src.domain.solution import (
    AsignacionAula,
)


class TestAsignacionAula:
    """Tests for AsignacionAula entity."""
    
    def test_valid_asignacion(self):
        """Test creating a valid AsignacionAula."""
        asignacion = AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 2, 15),
            vigente=True
        )
        assert asignacion.id == "ASG-001"
        assert asignacion.horario_id == "HOR-001"
        assert asignacion.aula_id == "AULA-101"
        assert asignacion.ciclo_id == "2024-1C"
        assert asignacion.fecha_asignacion == date(2025, 2, 15)
        assert asignacion.vigente is True
    
    def test_asignacion_default_vigente(self):
        """Test that vigente defaults to True."""
        asignacion = AsignacionAula(
            id="ASG-001",
            horario_id="HOR-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 2, 15)
        )
        assert asignacion.vigente is True
    
    def test_invalid_empty_id(self):
        """Test that empty id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="",
                horario_id="HOR-001",
                aula_id="AULA-101",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_horario_id(self):
        """Test that empty horario_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                horario_id="",
                aula_id="AULA-101",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_aula_codigo(self):
        """Test that empty aula_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                horario_id="HOR-001",
                aula_id="",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_ciclo_id(self):
        """Test that empty ciclo_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                horario_id="HOR-001",
                aula_id="AULA-101",
                ciclo_id="",
                fecha_asignacion=date(2025, 2, 15)
            )
