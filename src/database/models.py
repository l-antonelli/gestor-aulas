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

class PlanEstudioDB(SQLModel, table=True):
    """Relacion M:M entre Materia y Carrera con ubicacion curricular."""
    __tablename__ = "plan_estudio"

    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    carrera_codigo: str = Field(foreign_key="carreras.codigo", primary_key=True)
    anio_plan: int = Field(default=1, ge=1, le=6)
    cuatrimestre_plan: str = Field(default="1C")  # "1C", "2C", "anual"


class CorrelativaDB(SQLModel, table=True):
    """Correlativas: materias que deben aprobarse antes de cursar otra."""
    __tablename__ = "correlativas"

    carrera_codigo: str = Field(foreign_key="carreras.codigo", primary_key=True)
    materia_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)
    materia_correlativa_codigo: str = Field(foreign_key="materias.codigo", primary_key=True)


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
        link_model=PlanEstudioDB
    )


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
        link_model=PlanEstudioDB
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
    horarios: list["HorarioDB"] = Relationship(back_populates="comision")


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


class HorarioDB(SQLModel, table=True):
    """Horario de dictado: asocia una comisión con un día y rango horario."""
    __tablename__ = "horarios"

    id: str = Field(primary_key=True)
    comision_id: str = Field(foreign_key="comisiones.id", index=True)
    codigo_materia: str = Field(foreign_key="materias.codigo", index=True)
    dia: str = Field(index=True)
    hora_inicio: time
    hora_fin: time

    # Relationships
    comision: Optional[ComisionDB] = Relationship(back_populates="horarios")
    asignacion: Optional["AsignacionAulaDB"] = Relationship(back_populates="horario")


# =============================================================================
# Solution Domain Models - Gestión
# =============================================================================

class AsignacionAulaDB(SQLModel, table=True):
    """Asignación de un aula a un horario en un ciclo (resuelve M:M Horario-Aula)."""
    __tablename__ = "asignaciones_aula"

    id: str = Field(primary_key=True)
    horario_id: str = Field(foreign_key="horarios.id", index=True)
    aula_id: str = Field(foreign_key="aulas.id", index=True)
    ciclo_id: str = Field(foreign_key="ciclos.id", index=True)
    fecha_asignacion: date
    vigente: bool = Field(default=True)

    # Relationships
    horario: Optional[HorarioDB] = Relationship(back_populates="asignacion")
    aula: Optional[AulaDB] = Relationship(back_populates="asignaciones")
