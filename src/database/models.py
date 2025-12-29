"""
SQLModel database models.

These models mirror the domain entities but add database persistence.
They use SQLModel which combines Pydantic validation with SQLAlchemy ORM.
"""

from sqlmodel import SQLModel, Field, Relationship
from typing import Optional
from datetime import date, time


# =============================================================================
# Configuration Models
# =============================================================================

class ConfiguracionHoraria(SQLModel, table=True):
    """Configuración global de parámetros horarios."""
    __tablename__ = "configuracion_horaria"
    
    id: int = Field(default=1, primary_key=True)  # Singleton, siempre id=1
    
    # Granularidad de tiempo en minutos (15 = slots de 15 min)
    granularidad_minutos: int = Field(default=15, ge=5, le=60)
    
    # Horario operativo de la facultad
    hora_inicio_operativo: time = Field(default=time(7, 0))
    hora_fin_operativo: time = Field(default=time(23, 0))
    
    # Días operativos (comma-separated: "Lunes,Martes,Miércoles,Jueves,Viernes")
    dias_operativos: str = Field(default="Lunes,Martes,Miércoles,Jueves,Viernes,Sábado")


# =============================================================================
# Problem Domain Models
# =============================================================================

class AlumnoDB(SQLModel, table=True):
    """Estudiante inscripto en la facultad."""
    __tablename__ = "alumnos"
    
    legajo: str = Field(primary_key=True, min_length=1)
    email: str = Field(index=True)
    nombre: str = Field(min_length=1)
    dni: str = Field(min_length=7, max_length=8)
    
    # Relationships
    inscripciones: list["InscripcionDB"] = Relationship(back_populates="alumno")
    asistencias: list["AsistenciaDB"] = Relationship(back_populates="alumno")


class MateriaDB(SQLModel, table=True):
    """Asignatura académica."""
    __tablename__ = "materias"
    
    codigo: str = Field(primary_key=True, min_length=1)
    nombre: str = Field(min_length=1)
    cupo: int = Field(gt=0)
    horas_semanales: int = Field(gt=0)
    
    # Relationships
    comisiones: list["ComisionDB"] = Relationship(back_populates="materia")


class ComisionDB(SQLModel, table=True):
    """División de una materia para distribuir alumnos."""
    __tablename__ = "comisiones"
    
    id: str = Field(primary_key=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    nombre: str = Field(default="")
    numero: int = Field(ge=1)
    cupo: int = Field(gt=0)
    descripcion: str = Field(default="")
    
    # Relationships
    materia: Optional[MateriaDB] = Relationship(back_populates="comisiones")
    clases: list["ClaseDB"] = Relationship(back_populates="comision")
    inscripciones: list["InscripcionDB"] = Relationship(back_populates="comision")


class HorarioCronogramaDB(SQLModel, table=True):
    """Franja horaria del cronograma académico."""
    __tablename__ = "horarios_cronograma"
    
    id: str = Field(primary_key=True)
    dia_semana: str = Field(index=True)
    hora_inicio: time
    hora_fin: time
    
    # Relationships
    clases: list["ClaseDB"] = Relationship(back_populates="horario")


class AulaDB(SQLModel, table=True):
    """Espacio físico donde se dictan las clases."""
    __tablename__ = "aulas"
    
    id: str = Field(primary_key=True, min_length=1)
    sede: str = Field(index=True)
    nombre: str = Field(min_length=1)
    capacidad: int = Field(gt=0)
    tipo: str = Field(default="teorica")
    descripcion: str = Field(default="")
    
    # Relationships
    asignaciones: list["AsignacionAulaDB"] = Relationship(back_populates="aula")


class ClaseDB(SQLModel, table=True):
    """Instancia de dictado de una comisión en un horario específico."""
    __tablename__ = "clases"
    
    id: str = Field(primary_key=True)
    comision_id: str = Field(foreign_key="comisiones.id", index=True)
    horario_id: str = Field(foreign_key="horarios_cronograma.id", index=True)
    dia: str
    
    # Relationships
    comision: Optional[ComisionDB] = Relationship(back_populates="clases")
    horario: Optional[HorarioCronogramaDB] = Relationship(back_populates="clases")
    asistencias: list["AsistenciaDB"] = Relationship(back_populates="clase")
    asignacion: Optional["AsignacionAulaDB"] = Relationship(back_populates="clase")


# =============================================================================
# Solution Domain Models
# =============================================================================

class InscripcionDB(SQLModel, table=True):
    """Relación entre alumno y comisión (resuelve M:M Alumno-Materia)."""
    __tablename__ = "inscripciones"
    
    id: str = Field(primary_key=True)
    alumno_legajo: str = Field(foreign_key="alumnos.legajo", index=True)
    comision_id: str = Field(foreign_key="comisiones.id", index=True)
    fecha_inscripcion: date
    activa: bool = Field(default=True)
    
    # Relationships
    alumno: Optional[AlumnoDB] = Relationship(back_populates="inscripciones")
    comision: Optional[ComisionDB] = Relationship(back_populates="inscripciones")


class AsistenciaDB(SQLModel, table=True):
    """Registro de presencia de alumno en clase."""
    __tablename__ = "asistencias"
    
    id: str = Field(primary_key=True)
    alumno_legajo: str = Field(foreign_key="alumnos.legajo", index=True)
    clase_id: str = Field(foreign_key="clases.id", index=True)
    fecha: date
    presente: bool = Field(default=False)
    
    # Relationships
    alumno: Optional[AlumnoDB] = Relationship(back_populates="asistencias")
    clase: Optional[ClaseDB] = Relationship(back_populates="asistencias")


class AsignacionAulaDB(SQLModel, table=True):
    """Asignación de un aula a una clase (resuelve M:M Clase-Aula)."""
    __tablename__ = "asignaciones_aula"
    
    id: str = Field(primary_key=True)
    clase_id: str = Field(foreign_key="clases.id", unique=True, index=True)
    aula_id: str = Field(foreign_key="aulas.id", index=True)
    fecha_asignacion: date
    vigente: bool = Field(default=True)
    
    # Relationships
    clase: Optional[ClaseDB] = Relationship(back_populates="asignacion")
    aula: Optional[AulaDB] = Relationship(back_populates="asignaciones")
