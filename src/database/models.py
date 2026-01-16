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
    
    id: int = Field(default=1, primary_key=True)
    granularidad_minutos: int = Field(default=15, ge=5, le=60)
    hora_inicio_operativo: time = Field(default=time(7, 0))
    hora_fin_operativo: time = Field(default=time(23, 0))
    dias_operativos: str = Field(default="Lunes,Martes,Miércoles,Jueves,Viernes,Sábado")


# =============================================================================
# Link Tables (for M:M relationships)
# =============================================================================

class MateriaCarreraLink(SQLModel, table=True):
    """Relación M:M entre Materia y Carrera con ubicación curricular."""
    __tablename__ = "materia_carrera"
    
    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    carrera_codigo: str = Field(foreign_key="carreras.codigo", primary_key=True)
    anio_carrera: int = Field(default=1, ge=1, le=6)  # Año en el plan de estudios
    cuatrimestre_carrera: int = Field(default=0, ge=0, le=2)  # 0=anual, 1=1C, 2=2C


class ComisionProfesorLink(SQLModel, table=True):
    """Relación M:M entre Comision y Profesor."""
    __tablename__ = "comision_profesor"
    
    comision_id: str = Field(foreign_key="comisiones.id", primary_key=True)
    profesor_id: str = Field(foreign_key="profesores.id", primary_key=True)
    es_titular: bool = Field(default=False)


# =============================================================================
# Solution Domain Models - Temporal
# =============================================================================

class CicloDB(SQLModel, table=True):
    """
    Período lectivo (cuatrimestre).
    Ejemplo: 2024-1C, 2024-2C
    """
    __tablename__ = "ciclos"
    
    id: str = Field(primary_key=True)  # Ej: "2024-1C", "2024-2C"
    anio: int = Field(ge=2020, le=2100)
    numero: int = Field(ge=1, le=2)  # 1 = primer cuatri, 2 = segundo cuatri
    fecha_inicio: date
    fecha_fin: date
    descripcion: str = Field(default="")
    
    # Relationships
    dictados: list["DictadoDB"] = Relationship(back_populates="ciclo")


class DictadoDB(SQLModel, table=True):
    """
    Instancia de una materia en un ciclo específico.
    Una materia anual tendrá 2 dictados (uno por cuatrimestre).
    """
    __tablename__ = "dictados"
    
    id: str = Field(primary_key=True)  # Ej: "MAT101-2024-1C"
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    ciclo_id: str = Field(foreign_key="ciclos.id", index=True)
    tipo: str = Field(default="normal")  # normal, recursado, intensivo, etc.
    activo: bool = Field(default=True)
    
    # Relationships
    materia: Optional["MateriaDB"] = Relationship(back_populates="dictados")
    ciclo: Optional[CicloDB] = Relationship(back_populates="dictados")
    comisiones: list["ComisionDB"] = Relationship(back_populates="dictado")


# =============================================================================
# Problem Domain Models
# =============================================================================

class CarreraDB(SQLModel, table=True):
    """Carrera universitaria."""
    __tablename__ = "carreras"
    
    codigo: str = Field(primary_key=True, min_length=1)
    nombre: str = Field(min_length=1)
    titulo_otorgado: str = Field(default="")
    duracion_anios: int = Field(default=5, ge=1)
    cantidad_materias: Optional[int] = Field(default=None, ge=1)
    
    # Relationships
    materias: list["MateriaDB"] = Relationship(
        back_populates="carreras",
        link_model=MateriaCarreraLink
    )


class ProfesorDB(SQLModel, table=True):
    """Docente de la facultad."""
    __tablename__ = "profesores"
    
    id: str = Field(primary_key=True, min_length=1)
    nombre: str = Field(min_length=1)
    email: str = Field(default="")
    dni: str = Field(default="")
    
    # Relationships
    comisiones: list["ComisionDB"] = Relationship(
        back_populates="profesores",
        link_model=ComisionProfesorLink
    )
    clases: list["ClaseDB"] = Relationship(back_populates="profesor")


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
    periodo: str = Field(default="cuatrimestral")  # "anual" o "cuatrimestral"
    
    # Relationships
    comisiones: list["ComisionDB"] = Relationship(back_populates="materia")
    carreras: list[CarreraDB] = Relationship(
        back_populates="materias",
        link_model=MateriaCarreraLink
    )
    dictados: list[DictadoDB] = Relationship(back_populates="materia")


class ComisionDB(SQLModel, table=True):
    """División de una materia para distribuir alumnos en un dictado específico."""
    __tablename__ = "comisiones"
    
    id: str = Field(primary_key=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", index=True)
    dictado_id: Optional[str] = Field(default=None, foreign_key="dictados.id", index=True)
    nombre: str = Field(default="Comisión Única")
    numero: int = Field(ge=1, default=1)
    cupo: int = Field(gt=0)
    descripcion: str = Field(default="")
    
    # Relationships
    materia: Optional[MateriaDB] = Relationship(back_populates="comisiones")
    dictado: Optional[DictadoDB] = Relationship(back_populates="comisiones")
    clases: list["ClaseDB"] = Relationship(back_populates="comision")
    inscripciones: list["InscripcionDB"] = Relationship(back_populates="comision")
    profesores: list[ProfesorDB] = Relationship(
        back_populates="comisiones",
        link_model=ComisionProfesorLink
    )


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
    profesor_id: Optional[str] = Field(default=None, foreign_key="profesores.id", index=True)
    dia: str
    
    # Relationships
    comision: Optional[ComisionDB] = Relationship(back_populates="clases")
    horario: Optional[HorarioCronogramaDB] = Relationship(back_populates="clases")
    profesor: Optional[ProfesorDB] = Relationship(back_populates="clases")
    asistencias: list["AsistenciaDB"] = Relationship(back_populates="clase")
    asignacion: Optional["AsignacionAulaDB"] = Relationship(back_populates="clase")


# =============================================================================
# Solution Domain Models - Gestión
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
    """Asignación de un aula a una clase en un ciclo (resuelve M:M Clase-Aula)."""
    __tablename__ = "asignaciones_aula"
    
    id: str = Field(primary_key=True)
    clase_id: str = Field(foreign_key="clases.id", index=True)
    aula_id: str = Field(foreign_key="aulas.id", index=True)
    ciclo_id: str = Field(foreign_key="ciclos.id", index=True)  # Agregado para validar por ciclo
    fecha_asignacion: date
    vigente: bool = Field(default=True)
    
    # Relationships
    clase: Optional[ClaseDB] = Relationship(back_populates="asignacion")
    aula: Optional[AulaDB] = Relationship(back_populates="asignaciones")
