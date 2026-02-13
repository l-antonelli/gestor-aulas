"""
Converters between SQLModel (DB) and Pydantic (Domain) models.

This module provides bidirectional conversion functions to maintain
separation between persistence layer and domain logic.
"""

from typing import TypeVar, Union, overload

# Domain models
from src.domain.problem.aula import Aula
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario import Horario
from src.domain.problem.carrera import Carrera
from src.domain.solution.asignacion_aula import AsignacionAula

# DB models
from src.database.models import (
    AulaDB,
    MateriaDB,
    ComisionDB,
    HorarioDB,
    AsignacionAulaDB,
    CarreraDB,
)

# Type aliases for clarity
DomainModel = Union[Aula, Materia, Comision, Horario, AsignacionAula, Carrera]
DBModel = Union[AulaDB, MateriaDB, ComisionDB, HorarioDB, AsignacionAulaDB, CarreraDB]


# =============================================================================
# Domain -> DB Converters
# =============================================================================

@overload
def to_db(domain: Aula) -> AulaDB: ...
@overload
def to_db(domain: Materia) -> MateriaDB: ...
@overload
def to_db(domain: Comision) -> ComisionDB: ...
@overload
def to_db(domain: Horario) -> HorarioDB: ...
@overload
def to_db(domain: AsignacionAula) -> AsignacionAulaDB: ...
@overload
def to_db(domain: Carrera) -> CarreraDB: ...

def to_db(domain: DomainModel) -> DBModel:
    """Convert a domain model to its DB equivalent."""

    if isinstance(domain, Aula):
        return AulaDB(
            id=domain.id,
            sede=domain.sede,
            nombre=domain.nombre,
            capacidad=domain.capacidad,
            tipo=domain.tipo,
            descripcion=domain.descripcion,
        )

    if isinstance(domain, Materia):
        return MateriaDB(
            codigo=domain.codigo,
            nombre=domain.nombre,
            cupo=domain.cupo,
            horas_semanales=domain.horas_semanales,
            periodo=domain.periodo,
        )

    if isinstance(domain, Comision):
        return ComisionDB(
            id=domain.id,
            materia_codigo=domain.materia_codigo,
            nombre=domain.nombre,
            numero=domain.numero,
            cupo=domain.cupo,
        )

    if isinstance(domain, Horario):
        return HorarioDB(
            id=domain.id,
            comision_id=domain.comision_id,
            codigo_materia=domain.codigo_materia,
            dia=domain.dia,
            hora_inicio=domain.hora_inicio,
            hora_fin=domain.hora_fin,
        )

    if isinstance(domain, AsignacionAula):
        return AsignacionAulaDB(
            id=domain.id,
            horario_id=domain.horario_id,
            aula_id=domain.aula_id,
            ciclo_id=domain.ciclo_id,
            fecha_asignacion=domain.fecha_asignacion,
            vigente=domain.vigente,
        )

    if isinstance(domain, Carrera):
        return CarreraDB(
            codigo=domain.codigo,
            nombre=domain.nombre,
            titulo_otorgado=domain.titulo_otorgado,
            duracion_anios=domain.duracion_anios,
            cantidad_materias=domain.cantidad_materias,
        )

    raise TypeError(f"Unknown domain model type: {type(domain)}")


# =============================================================================
# DB -> Domain Converters
# =============================================================================

@overload
def to_domain(db: AulaDB) -> Aula: ...
@overload
def to_domain(db: MateriaDB) -> Materia: ...
@overload
def to_domain(db: ComisionDB) -> Comision: ...
@overload
def to_domain(db: HorarioDB) -> Horario: ...
@overload
def to_domain(db: AsignacionAulaDB) -> AsignacionAula: ...
@overload
def to_domain(db: CarreraDB) -> Carrera: ...

def to_domain(db: DBModel) -> DomainModel:
    """Convert a DB model to its domain equivalent."""

    if isinstance(db, AulaDB):
        return Aula(
            id=db.id,
            sede=db.sede,
            nombre=db.nombre,
            capacidad=db.capacidad,
            tipo=db.tipo,
            descripcion=db.descripcion,
        )

    if isinstance(db, MateriaDB):
        return Materia(
            codigo=db.codigo,
            nombre=db.nombre,
            cupo=db.cupo,
            horas_semanales=db.horas_semanales,
            periodo=db.periodo,
        )

    if isinstance(db, ComisionDB):
        return Comision(
            id=db.id,
            materia_codigo=db.materia_codigo,
            nombre=db.nombre,
            numero=db.numero,
            cupo=db.cupo,
        )

    if isinstance(db, HorarioDB):
        return Horario(
            id=db.id,
            comision_id=db.comision_id,
            codigo_materia=db.codigo_materia,
            dia=db.dia,
            hora_inicio=db.hora_inicio,
            hora_fin=db.hora_fin,
        )

    if isinstance(db, AsignacionAulaDB):
        return AsignacionAula(
            id=db.id,
            horario_id=db.horario_id,
            aula_id=db.aula_id,
            ciclo_id=db.ciclo_id,
            fecha_asignacion=db.fecha_asignacion,
            vigente=db.vigente,
        )

    if isinstance(db, CarreraDB):
        return Carrera(
            codigo=db.codigo,
            nombre=db.nombre,
            titulo_otorgado=db.titulo_otorgado,
            duracion_anios=db.duracion_anios,
            cantidad_materias=db.cantidad_materias,
        )

    raise TypeError(f"Unknown DB model type: {type(db)}")


# =============================================================================
# Batch Converters (convenience functions)
# =============================================================================

def to_db_list(domains: list[DomainModel]) -> list[DBModel]:
    """Convert a list of domain models to DB models."""
    return [to_db(d) for d in domains]


def to_domain_list(dbs: list[DBModel]) -> list[DomainModel]:
    """Convert a list of DB models to domain models."""
    return [to_domain(d) for d in dbs]
