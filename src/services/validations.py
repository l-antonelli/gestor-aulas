"""
Validaciones de factibilidad para el sistema de asignación de aulas.

Este módulo contiene las validaciones que aseguran que los datos cargados
son correctos y factibles para el problema de asignación.
"""

from dataclasses import dataclass
from sqlmodel import Session, select
from src.database.models import (
    MateriaDB, CarreraDB, ClaseDB, AsignacionAulaDB,
    HorarioCronogramaDB, MateriaCarreraLink, ComisionDB
)


@dataclass
class ValidationResult:
    """Resultado de una validación."""
    valid: bool
    message: str
    details: list[str] = None
    
    def __post_init__(self):
        if self.details is None:
            self.details = []


# =============================================================================
# Validación 1: Toda materia debe pertenecer a al menos una carrera
# =============================================================================

def validar_materias_tienen_carrera(session: Session) -> ValidationResult:
    """
    Verifica que todas las materias estén asociadas a al menos una carrera.
    """
    # Get all materias
    materias = session.exec(select(MateriaDB)).all()
    
    # Get all links
    links = session.exec(select(MateriaCarreraLink)).all()
    materias_con_carrera = {link.materia_codigo for link in links}
    
    # Find materias without carrera
    materias_sin_carrera = [m for m in materias if m.codigo not in materias_con_carrera]
    
    if materias_sin_carrera:
        return ValidationResult(
            valid=False,
            message=f"{len(materias_sin_carrera)} materia(s) sin carrera asignada",
            details=[f"{m.codigo}: {m.nombre}" for m in materias_sin_carrera]
        )
    
    return ValidationResult(
        valid=True,
        message=f"Todas las {len(materias)} materias tienen carrera asignada"
    )


# =============================================================================
# Validación 2: Horarios no superpuestos para materias del mismo año/cuatrimestre
# =============================================================================

def horarios_se_superponen(h1: HorarioCronogramaDB, h2: HorarioCronogramaDB) -> bool:
    """Verifica si dos horarios se superponen (mismo día y horas solapadas)."""
    if h1.dia_semana != h2.dia_semana:
        return False
    
    # Check time overlap
    return not (h1.hora_fin <= h2.hora_inicio or h2.hora_fin <= h1.hora_inicio)


def validar_factibilidad_horarios_carrera(
    session: Session,
    carrera_codigo: str,
    anio: int,
    cuatrimestre: int
) -> ValidationResult:
    """
    Verifica que los horarios de las materias de una carrera/año/cuatrimestre
    no se superpongan, permitiendo que un alumno asista a todas.
    """
    # Get materias for this carrera/año/cuatrimestre
    materias = session.exec(
        select(MateriaDB)
        .join(MateriaCarreraLink)
        .where(MateriaCarreraLink.carrera_codigo == carrera_codigo)
        .where(MateriaDB.anio_carrera == anio)
        .where(MateriaDB.cuatrimestre_carrera == cuatrimestre)
    ).all()
    
    if not materias:
        return ValidationResult(
            valid=True,
            message=f"No hay materias para {carrera_codigo} año {anio} cuatri {cuatrimestre}"
        )
    
    # Get all clases for these materias
    clases_por_materia: dict[str, list[tuple[ClaseDB, HorarioCronogramaDB]]] = {}
    
    for materia in materias:
        comisiones = session.exec(
            select(ComisionDB).where(ComisionDB.materia_codigo == materia.codigo)
        ).all()
        
        clases_horarios = []
        for comision in comisiones:
            clases = session.exec(
                select(ClaseDB).where(ClaseDB.comision_id == comision.id)
            ).all()
            for clase in clases:
                horario = session.get(HorarioCronogramaDB, clase.horario_id)
                if horario:
                    clases_horarios.append((clase, horario))
        
        if clases_horarios:
            clases_por_materia[materia.codigo] = clases_horarios
    
    # Check for overlaps between different materias
    conflictos = []
    materias_codigos = list(clases_por_materia.keys())
    
    for i, mat1 in enumerate(materias_codigos):
        for mat2 in materias_codigos[i+1:]:
            for _, h1 in clases_por_materia[mat1]:
                for _, h2 in clases_por_materia[mat2]:
                    if horarios_se_superponen(h1, h2):
                        conflictos.append(
                            f"{mat1} vs {mat2}: {h1.dia_semana} "
                            f"{h1.hora_inicio.strftime('%H:%M')}-{h1.hora_fin.strftime('%H:%M')}"
                        )
    
    if conflictos:
        return ValidationResult(
            valid=False,
            message=f"{len(conflictos)} conflicto(s) de horario en {carrera_codigo} año {anio} cuatri {cuatrimestre}",
            details=conflictos
        )
    
    return ValidationResult(
        valid=True,
        message=f"Sin conflictos de horario para {carrera_codigo} año {anio} cuatri {cuatrimestre}"
    )


def validar_factibilidad_horarios_todas_carreras(session: Session) -> list[ValidationResult]:
    """Ejecuta la validación de horarios para todas las combinaciones carrera/año/cuatri."""
    results = []
    
    carreras = session.exec(select(CarreraDB)).all()
    
    for carrera in carreras:
        for anio in range(1, carrera.duracion_anios + 1):
            for cuatri in [1, 2]:
                result = validar_factibilidad_horarios_carrera(
                    session, carrera.codigo, anio, cuatri
                )
                if not result.valid:
                    results.append(result)
    
    return results


# =============================================================================
# Validación 3: Un aula no puede estar asignada a dos clases en el mismo horario/ciclo
# =============================================================================

def validar_conflictos_aula_ciclo(session: Session, ciclo_id: str) -> ValidationResult:
    """
    Verifica que no haya dos clases asignadas a la misma aula en el mismo
    horario dentro de un ciclo.
    """
    # Get all active assignments for this ciclo
    asignaciones = session.exec(
        select(AsignacionAulaDB)
        .where(AsignacionAulaDB.ciclo_id == ciclo_id)
        .where(AsignacionAulaDB.vigente)
    ).all()
    
    if not asignaciones:
        return ValidationResult(
            valid=True,
            message=f"No hay asignaciones en el ciclo {ciclo_id}"
        )
    
    # Group by aula
    asignaciones_por_aula: dict[str, list[AsignacionAulaDB]] = {}
    for asig in asignaciones:
        if asig.aula_id not in asignaciones_por_aula:
            asignaciones_por_aula[asig.aula_id] = []
        asignaciones_por_aula[asig.aula_id].append(asig)
    
    conflictos = []
    
    for aula_id, asigs in asignaciones_por_aula.items():
        # Get horarios for each clase
        clases_horarios = []
        for asig in asigs:
            clase = session.get(ClaseDB, asig.clase_id)
            if clase:
                horario = session.get(HorarioCronogramaDB, clase.horario_id)
                if horario:
                    clases_horarios.append((clase, horario, asig))
        
        # Check for overlaps within same aula
        for i, (c1, h1, _) in enumerate(clases_horarios):
            for c2, h2, _ in clases_horarios[i+1:]:
                if horarios_se_superponen(h1, h2):
                    conflictos.append(
                        f"Aula {aula_id}: {c1.comision_id} vs {c2.comision_id} "
                        f"en {h1.dia_semana} {h1.hora_inicio.strftime('%H:%M')}"
                    )
    
    if conflictos:
        return ValidationResult(
            valid=False,
            message=f"{len(conflictos)} conflicto(s) de aula en ciclo {ciclo_id}",
            details=conflictos
        )
    
    return ValidationResult(
        valid=True,
        message=f"Sin conflictos de aula en ciclo {ciclo_id}"
    )


# =============================================================================
# Ejecutar todas las validaciones
# =============================================================================

def ejecutar_todas_validaciones(session: Session, ciclo_id: str = None) -> dict[str, ValidationResult]:
    """
    Ejecuta todas las validaciones y retorna un diccionario con los resultados.
    """
    results = {}
    
    # Validación 1: Materias con carrera
    results["materias_carrera"] = validar_materias_tienen_carrera(session)
    
    # Validación 2: Horarios por carrera
    horarios_results = validar_factibilidad_horarios_todas_carreras(session)
    if horarios_results:
        # Combine all failures
        all_details = []
        for r in horarios_results:
            all_details.extend(r.details)
        results["horarios_carrera"] = ValidationResult(
            valid=False,
            message=f"{len(horarios_results)} carrera(s) con conflictos de horario",
            details=all_details
        )
    else:
        results["horarios_carrera"] = ValidationResult(
            valid=True,
            message="Sin conflictos de horario en ninguna carrera"
        )
    
    # Validación 3: Conflictos de aula (si se especifica ciclo)
    if ciclo_id:
        results["conflictos_aula"] = validar_conflictos_aula_ciclo(session, ciclo_id)
    
    return results
