"""
Converters between SQLModel (DB) and Pydantic (Domain) models.

This module provides bidirectional conversion functions to maintain
separation between persistence layer and domain logic.

Usage:
    # Load from DB, convert to domain for processing
    with get_session() as session:
        aulas_db = aula_crud.get_all(session)
    aulas = [to_domain(a) for a in aulas_db]
    
    # Process with optimization algorithm...
    
    # Convert result back to DB model for persistence
    asignacion_db = to_db(asignacion_domain)
"""

from typing import TypeVar, Union, overload

# Domain models
from src.domain.problem.alumno import Alumno
from src.domain.problem.aula import Aula
from src.domain.problem.materia import Materia
from src.domain.problem.comision import Comision
from src.domain.problem.horario_cronograma import HorarioCronograma
from src.domain.problem.clase import Clase
from src.domain.solution.inscripcion import Inscripcion
from src.domain.solution.asistencia import Asistencia
from src.domain.solution.asignacion_aula import AsignacionAula

# DB models
from src.database.models import (
    AlumnoDB,
    AulaDB,
    MateriaDB,
    ComisionDB,
    HorarioCronogramaDB,
    ClaseDB,
    InscripcionDB,
    AsistenciaDB,
    AsignacionAulaDB,
)

# Type aliases for clarity
DomainModel = Union[Alumno, Aula, Materia, Comision, HorarioCronograma, Clase, Inscripcion, Asistencia, AsignacionAula]
DBModel = Union[AlumnoDB, AulaDB, MateriaDB, ComisionDB, HorarioCronogramaDB, ClaseDB, InscripcionDB, AsistenciaDB, AsignacionAulaDB]


# =============================================================================
# Domain → DB Converters
# =============================================================================

@overload
def to_db(domain: Alumno) -> AlumnoDB: ...
@overload
def to_db(domain: Aula) -> AulaDB: ...
@overload
def to_db(domain: Materia) -> MateriaDB: ...
@overload
def to_db(domain: Comision) -> ComisionDB: ...
@overload
def to_db(domain: HorarioCronograma) -> HorarioCronogramaDB: ...
@overload
def to_db(domain: Clase) -> ClaseDB: ...
@overload
def to_db(domain: Inscripcion) -> InscripcionDB: ...
@overload
def to_db(domain: Asistencia) -> AsistenciaDB: ...
@overload
def to_db(domain: AsignacionAula) -> AsignacionAulaDB: ...

def to_db(domain: DomainModel) -> DBModel:
    """Convert a domain model to its DB equivalent."""
    
    if isinstance(domain, Alumno):
        return AlumnoDB(
            legajo=domain.legajo,
            email=domain.email,
            nombre=domain.nombre,
            dni=domain.dni,
        )
    
    if isinstance(domain, Aula):
        return AulaDB(
            codigo=domain.codigo,
            capacidad=domain.capacidad,
            tipo=domain.tipo,
        )
    
    if isinstance(domain, Materia):
        return MateriaDB(
            codigo=domain.codigo,
            nombre=domain.nombre,
            cupo=domain.cupo,
            horas_semanales=domain.horas_semanales,
        )
    
    if isinstance(domain, Comision):
        return ComisionDB(
            id=domain.id,
            materia_codigo=domain.materia_codigo,
            nombre=domain.nombre,
            numero=domain.numero,
            cupo=domain.cupo,
        )
    
    if isinstance(domain, HorarioCronograma):
        return HorarioCronogramaDB(
            id=domain.id,
            dia_semana=domain.dia_semana,
            hora_inicio=domain.hora_inicio,
            hora_fin=domain.hora_fin,
        )
    
    if isinstance(domain, Clase):
        return ClaseDB(
            id=domain.id,
            comision_id=domain.comision_id,
            horario_id=domain.horario_id,
            dia=domain.dia,
        )
    
    if isinstance(domain, Inscripcion):
        return InscripcionDB(
            id=domain.id,
            alumno_legajo=domain.alumno_legajo,
            comision_id=domain.comision_id,
            fecha_inscripcion=domain.fecha_inscripcion,
            activa=domain.activa,
        )
    
    if isinstance(domain, Asistencia):
        return AsistenciaDB(
            id=domain.id,
            alumno_legajo=domain.alumno_legajo,
            clase_id=domain.clase_id,
            fecha=domain.fecha,
            presente=domain.presente,
        )
    
    if isinstance(domain, AsignacionAula):
        return AsignacionAulaDB(
            id=domain.id,
            clase_id=domain.clase_id,
            aula_codigo=domain.aula_codigo,
            fecha_asignacion=domain.fecha_asignacion,
            vigente=domain.vigente,
        )
    
    raise TypeError(f"Unknown domain model type: {type(domain)}")


# =============================================================================
# DB → Domain Converters
# =============================================================================

@overload
def to_domain(db: AlumnoDB) -> Alumno: ...
@overload
def to_domain(db: AulaDB) -> Aula: ...
@overload
def to_domain(db: MateriaDB) -> Materia: ...
@overload
def to_domain(db: ComisionDB) -> Comision: ...
@overload
def to_domain(db: HorarioCronogramaDB) -> HorarioCronograma: ...
@overload
def to_domain(db: ClaseDB) -> Clase: ...
@overload
def to_domain(db: InscripcionDB) -> Inscripcion: ...
@overload
def to_domain(db: AsistenciaDB) -> Asistencia: ...
@overload
def to_domain(db: AsignacionAulaDB) -> AsignacionAula: ...

def to_domain(db: DBModel) -> DomainModel:
    """Convert a DB model to its domain equivalent."""
    
    if isinstance(db, AlumnoDB):
        return Alumno(
            legajo=db.legajo,
            email=db.email,
            nombre=db.nombre,
            dni=db.dni,
        )
    
    if isinstance(db, AulaDB):
        return Aula(
            codigo=db.codigo,
            capacidad=db.capacidad,
            tipo=db.tipo,
        )
    
    if isinstance(db, MateriaDB):
        return Materia(
            codigo=db.codigo,
            nombre=db.nombre,
            cupo=db.cupo,
            horas_semanales=db.horas_semanales,
        )
    
    if isinstance(db, ComisionDB):
        return Comision(
            id=db.id,
            materia_codigo=db.materia_codigo,
            nombre=db.nombre,
            numero=db.numero,
            cupo=db.cupo,
        )
    
    if isinstance(db, HorarioCronogramaDB):
        return HorarioCronograma(
            id=db.id,
            dia_semana=db.dia_semana,
            hora_inicio=db.hora_inicio,
            hora_fin=db.hora_fin,
        )
    
    if isinstance(db, ClaseDB):
        return Clase(
            id=db.id,
            comision_id=db.comision_id,
            horario_id=db.horario_id,
            dia=db.dia,
        )
    
    if isinstance(db, InscripcionDB):
        return Inscripcion(
            id=db.id,
            alumno_legajo=db.alumno_legajo,
            comision_id=db.comision_id,
            fecha_inscripcion=db.fecha_inscripcion,
            activa=db.activa,
        )
    
    if isinstance(db, AsistenciaDB):
        return Asistencia(
            id=db.id,
            alumno_legajo=db.alumno_legajo,
            clase_id=db.clase_id,
            fecha=db.fecha,
            presente=db.presente,
        )
    
    if isinstance(db, AsignacionAulaDB):
        return AsignacionAula(
            id=db.id,
            clase_id=db.clase_id,
            aula_codigo=db.aula_codigo,
            fecha_asignacion=db.fecha_asignacion,
            vigente=db.vigente,
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
