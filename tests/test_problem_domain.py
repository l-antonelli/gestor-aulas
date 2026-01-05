"""Tests for Problem Domain Entities."""

import pytest
from datetime import time
from pydantic import ValidationError

from src.domain.problem import (
    Alumno,
    Materia,
    Comision,
    HorarioCronograma,
    Aula,
    Clase,
)


class TestAlumno:
    """Tests for Alumno entity."""
    
    def test_valid_alumno(self):
        """Test creating a valid Alumno."""
        alumno = Alumno(
            legajo="A-12345",
            email="test@example.com",
            nombre="Juan Pérez",
            dni="12345678"
        )
        assert alumno.legajo == "A-12345"
        assert alumno.email == "test@example.com"
        assert alumno.nombre == "Juan Pérez"
        assert alumno.dni == "12345678"
    
    def test_invalid_empty_legajo(self):
        """Test that empty legajo is rejected."""
        with pytest.raises(ValidationError):
            Alumno(legajo="", email="test@example.com", nombre="Test", dni="12345678")
    
    def test_invalid_email_no_at(self):
        """Test that email without @ is rejected."""
        with pytest.raises(ValidationError):
            Alumno(legajo="A-123", email="invalid", nombre="Test", dni="12345678")
    
    def test_invalid_dni_too_short(self):
        """Test that DNI with less than 7 digits is rejected."""
        with pytest.raises(ValidationError):
            Alumno(legajo="A-123", email="test@example.com", nombre="Test", dni="123456")
    
    def test_invalid_dni_non_numeric(self):
        """Test that DNI with non-numeric characters is rejected."""
        with pytest.raises(ValidationError):
            Alumno(legajo="A-123", email="test@example.com", nombre="Test", dni="1234567a")


class TestMateria:
    """Tests for Materia entity."""
    
    def test_valid_materia(self):
        """Test creating a valid Materia."""
        materia = Materia(
            codigo="MAT101",
            nombre="Matemática I",
            cupo=100,
            horas_semanales=6
        )
        assert materia.codigo == "MAT101"
        assert materia.nombre == "Matemática I"
        assert materia.cupo == 100
        assert materia.horas_semanales == 6
    
    def test_invalid_zero_cupo(self):
        """Test that zero cupo is rejected."""
        with pytest.raises(ValidationError):
            Materia(codigo="MAT101", nombre="Test", cupo=0, horas_semanales=6)
    
    def test_invalid_negative_horas(self):
        """Test that negative horas_semanales is rejected."""
        with pytest.raises(ValidationError):
            Materia(codigo="MAT101", nombre="Test", cupo=100, horas_semanales=-1)


class TestComision:
    """Tests for Comision entity."""
    
    def test_valid_comision(self):
        """Test creating a valid Comision."""
        comision = Comision(
            id="COM-001",
            materia_codigo="MAT101",
            nombre="Comisión A",
            numero=1,
            cupo=50
        )
        assert comision.id == "COM-001"
        assert comision.materia_codigo == "MAT101"
        assert comision.numero == 1
        assert comision.cupo == 50
    
    def test_invalid_empty_materia_codigo(self):
        """Test that empty materia_codigo is rejected."""
        with pytest.raises(ValidationError):
            Comision(id="COM-001", materia_codigo="", nombre="Test", numero=1, cupo=50)
    
    def test_invalid_zero_numero(self):
        """Test that zero numero is rejected."""
        with pytest.raises(ValidationError):
            Comision(id="COM-001", materia_codigo="MAT101", nombre="Test", numero=0, cupo=50)


class TestHorarioCronograma:
    """Tests for HorarioCronograma entity."""
    
    def test_valid_horario(self):
        """Test creating a valid HorarioCronograma."""
        horario = HorarioCronograma(
            id="HOR-001",
            dia_semana="Lunes",
            hora_inicio=time(8, 0),
            hora_fin=time(9, 20)
        )
        assert horario.id == "HOR-001"
        assert horario.dia_semana == "Lunes"
        assert horario.hora_inicio == time(8, 0)
        assert horario.hora_fin == time(9, 20)
    
    def test_invalid_dia_semana(self):
        """Test that invalid day is rejected."""
        with pytest.raises(ValidationError):
            HorarioCronograma(
                id="HOR-001",
                dia_semana="Domingo",
                hora_inicio=time(8, 0),
                hora_fin=time(9, 0)
            )
    
    def test_invalid_time_range(self):
        """Test that hora_fin <= hora_inicio is rejected."""
        with pytest.raises(ValidationError):
            HorarioCronograma(
                id="HOR-001",
                dia_semana="Lunes",
                hora_inicio=time(10, 0),
                hora_fin=time(9, 0)
            )
    
    def test_invalid_equal_times(self):
        """Test that equal start and end times are rejected."""
        with pytest.raises(ValidationError):
            HorarioCronograma(
                id="HOR-001",
                dia_semana="Lunes",
                hora_inicio=time(9, 0),
                hora_fin=time(9, 0)
            )


class TestAula:
    """Tests for Aula entity."""
    
    def test_valid_aula(self):
        """Test creating a valid Aula."""
        aula = Aula(
            id="AULA-101",
            sede="Sede Central",
            nombre="Aula 101",
            capacidad=60,
            tipo="teorica"
        )
        assert aula.id == "AULA-101"
        assert aula.sede == "Sede Central"
        assert aula.nombre == "Aula 101"
        assert aula.capacidad == 60
        assert aula.tipo == "teorica"
    
    def test_invalid_zero_capacidad(self):
        """Test that zero capacidad is rejected."""
        with pytest.raises(ValidationError):
            Aula(id="AULA-101", sede="Sede Central", nombre="Aula 101", capacidad=0, tipo="teorica")
    
    def test_invalid_tipo(self):
        """Test that invalid tipo is rejected."""
        with pytest.raises(ValidationError):
            Aula(id="AULA-101", sede="Sede Central", nombre="Aula 101", capacidad=60, tipo="invalid")


class TestClase:
    """Tests for Clase entity."""
    
    def test_valid_clase(self):
        """Test creating a valid Clase."""
        clase = Clase(
            id="CLS-001",
            comision_id="COM-001",
            horario_id="HOR-001",
            dia="Lunes"
        )
        assert clase.id == "CLS-001"
        assert clase.comision_id == "COM-001"
        assert clase.horario_id == "HOR-001"
        assert clase.dia == "Lunes"
    
    def test_invalid_empty_comision_id(self):
        """Test that empty comision_id is rejected."""
        with pytest.raises(ValidationError):
            Clase(id="CLS-001", comision_id="", horario_id="HOR-001", dia="Lunes")
    
    def test_invalid_dia(self):
        """Test that invalid dia is rejected."""
        with pytest.raises(ValidationError):
            Clase(id="CLS-001", comision_id="COM-001", horario_id="HOR-001", dia="Domingo")
