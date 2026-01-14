"""Tests for Solution Domain Entities."""

import pytest
from datetime import date
from pydantic import ValidationError

from src.domain.solution import (
    Inscripcion,
    Asistencia,
    AsignacionAula,
)


class TestInscripcion:
    """Tests for Inscripcion entity."""
    
    def test_valid_inscripcion(self):
        """Test creating a valid Inscripcion."""
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=date(2025, 3, 1),
            activa=True
        )
        assert inscripcion.id == "INS-001"
        assert inscripcion.alumno_legajo == "A-12345"
        assert inscripcion.comision_id == "COM-001"
        assert inscripcion.fecha_inscripcion == date(2025, 3, 1)
        assert inscripcion.activa is True
    
    def test_inscripcion_default_activa(self):
        """Test that activa defaults to True."""
        inscripcion = Inscripcion(
            id="INS-001",
            alumno_legajo="A-12345",
            comision_id="COM-001",
            fecha_inscripcion=date(2025, 3, 1)
        )
        assert inscripcion.activa is True
    
    def test_invalid_empty_id(self):
        """Test that empty id is rejected."""
        with pytest.raises(ValidationError):
            Inscripcion(
                id="",
                alumno_legajo="A-12345",
                comision_id="COM-001",
                fecha_inscripcion=date(2025, 3, 1)
            )
    
    def test_invalid_empty_alumno_legajo(self):
        """Test that empty alumno_legajo is rejected."""
        with pytest.raises(ValidationError):
            Inscripcion(
                id="INS-001",
                alumno_legajo="",
                comision_id="COM-001",
                fecha_inscripcion=date(2025, 3, 1)
            )
    
    def test_invalid_empty_comision_id(self):
        """Test that empty comision_id is rejected."""
        with pytest.raises(ValidationError):
            Inscripcion(
                id="INS-001",
                alumno_legajo="A-12345",
                comision_id="",
                fecha_inscripcion=date(2025, 3, 1)
            )


class TestAsistencia:
    """Tests for Asistencia entity."""
    
    def test_valid_asistencia_presente(self):
        """Test creating a valid Asistencia with presente=True."""
        asistencia = Asistencia(
            id="ASI-001",
            alumno_legajo="A-12345",
            clase_id="CLS-001",
            fecha=date(2025, 3, 15),
            presente=True
        )
        assert asistencia.id == "ASI-001"
        assert asistencia.alumno_legajo == "A-12345"
        assert asistencia.clase_id == "CLS-001"
        assert asistencia.fecha == date(2025, 3, 15)
        assert asistencia.presente is True
    
    def test_valid_asistencia_ausente(self):
        """Test creating a valid Asistencia with presente=False."""
        asistencia = Asistencia(
            id="ASI-002",
            alumno_legajo="A-12345",
            clase_id="CLS-001",
            fecha=date(2025, 3, 15),
            presente=False
        )
        assert asistencia.presente is False
    
    def test_invalid_empty_id(self):
        """Test that empty id is rejected."""
        with pytest.raises(ValidationError):
            Asistencia(
                id="",
                alumno_legajo="A-12345",
                clase_id="CLS-001",
                fecha=date(2025, 3, 15),
                presente=True
            )
    
    def test_invalid_empty_alumno_legajo(self):
        """Test that empty alumno_legajo is rejected."""
        with pytest.raises(ValidationError):
            Asistencia(
                id="ASI-001",
                alumno_legajo="",
                clase_id="CLS-001",
                fecha=date(2025, 3, 15),
                presente=True
            )
    
    def test_invalid_empty_clase_id(self):
        """Test that empty clase_id is rejected."""
        with pytest.raises(ValidationError):
            Asistencia(
                id="ASI-001",
                alumno_legajo="A-12345",
                clase_id="",
                fecha=date(2025, 3, 15),
                presente=True
            )


class TestAsignacionAula:
    """Tests for AsignacionAula entity."""
    
    def test_valid_asignacion(self):
        """Test creating a valid AsignacionAula."""
        asignacion = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
            aula_id="AULA-101",
            ciclo_id="2024-1C",
            fecha_asignacion=date(2025, 2, 15),
            vigente=True
        )
        assert asignacion.id == "ASG-001"
        assert asignacion.clase_id == "CLS-001"
        assert asignacion.aula_id == "AULA-101"
        assert asignacion.ciclo_id == "2024-1C"
        assert asignacion.fecha_asignacion == date(2025, 2, 15)
        assert asignacion.vigente is True
    
    def test_asignacion_default_vigente(self):
        """Test that vigente defaults to True."""
        asignacion = AsignacionAula(
            id="ASG-001",
            clase_id="CLS-001",
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
                clase_id="CLS-001",
                aula_id="AULA-101",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_clase_id(self):
        """Test that empty clase_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                clase_id="",
                aula_id="AULA-101",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_aula_codigo(self):
        """Test that empty aula_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                clase_id="CLS-001",
                aula_id="",
                ciclo_id="2024-1C",
                fecha_asignacion=date(2025, 2, 15)
            )
    
    def test_invalid_empty_ciclo_id(self):
        """Test that empty ciclo_id is rejected."""
        with pytest.raises(ValidationError):
            AsignacionAula(
                id="ASG-001",
                clase_id="CLS-001",
                aula_id="AULA-101",
                ciclo_id="",
                fecha_asignacion=date(2025, 2, 15)
            )
