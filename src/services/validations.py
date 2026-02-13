"""
Validaciones de factibilidad para el sistema de asignacion de aulas.

Este modulo contiene las validaciones que aseguran que los datos cargados
son correctos y factibles para el problema de asignacion.
"""

from dataclasses import dataclass
from sqlmodel import Session, select
from src.database.models import (
    MateriaDB, CarreraDB, HorarioDB, AsignacionAulaDB,
    PlanEstudioDB, ComisionDB
)


@dataclass
class ValidationResult:
    """Resultado de una validacion."""
    valid: bool
    message: str
    details: list[str] = None

    def __post_init__(self):
        if self.details is None:
            self.details = []


# =============================================================================
# Validacion 1: Toda materia debe pertenecer a al menos una carrera
# =============================================================================

def validar_materias_tienen_carrera(session: Session) -> ValidationResult:
    """
    Verifica que todas las materias esten asociadas a al menos una carrera.
    """
    # Get all materias
    materias = session.exec(select(MateriaDB)).all()

    # Get all links
    links = session.exec(select(PlanEstudioDB)).all()
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
# Validacion 2: Horarios no superpuestos para materias del mismo anio/cuatrimestre
# =============================================================================

def horarios_se_superponen(h1: HorarioDB, h2: HorarioDB) -> bool:
    """Verifica si dos horarios se superponen (mismo dia y horas solapadas)."""
    if h1.dia != h2.dia:
        return False

    # Check time overlap
    return not (h1.hora_fin <= h2.hora_inicio or h2.hora_fin <= h1.hora_inicio)


def validar_factibilidad_horarios_carrera(
    session: Session,
    carrera_codigo: str,
    anio: int,
    cuatrimestre: str
) -> ValidationResult:
    """
    Verifica que los horarios de las materias de una carrera/anio/cuatrimestre
    no se superpongan, permitiendo que un alumno asista a todas.
    """
    # Get materias for this carrera/anio/cuatrimestre
    materias = session.exec(
        select(MateriaDB)
        .join(PlanEstudioDB)
        .where(PlanEstudioDB.carrera_codigo == carrera_codigo)
        .where(PlanEstudioDB.anio_plan == anio)
        .where(PlanEstudioDB.cuatrimestre_plan == cuatrimestre)
    ).all()

    if not materias:
        return ValidationResult(
            valid=True,
            message=f"No hay materias para {carrera_codigo} anio {anio} cuatri {cuatrimestre}"
        )

    # Get all horarios for these materias (Comision -> Horario)
    horarios_por_materia: dict[str, list[HorarioDB]] = {}

    for materia in materias:
        comisiones = session.exec(
            select(ComisionDB).where(ComisionDB.materia_codigo == materia.codigo)
        ).all()

        materia_horarios = []
        for comision in comisiones:
            horarios = session.exec(
                select(HorarioDB).where(HorarioDB.comision_id == comision.id)
            ).all()
            materia_horarios.extend(horarios)

        if materia_horarios:
            horarios_por_materia[materia.codigo] = materia_horarios

    # Check for overlaps between different materias
    conflictos = []
    materias_codigos = list(horarios_por_materia.keys())

    for i, mat1 in enumerate(materias_codigos):
        for mat2 in materias_codigos[i+1:]:
            for h1 in horarios_por_materia[mat1]:
                for h2 in horarios_por_materia[mat2]:
                    if horarios_se_superponen(h1, h2):
                        conflictos.append(
                            f"{mat1} vs {mat2}: {h1.dia} "
                            f"{h1.hora_inicio.strftime('%H:%M')}-{h1.hora_fin.strftime('%H:%M')}"
                        )

    if conflictos:
        return ValidationResult(
            valid=False,
            message=f"{len(conflictos)} conflicto(s) de horario en {carrera_codigo} anio {anio} cuatri {cuatrimestre}",
            details=conflictos
        )

    return ValidationResult(
        valid=True,
        message=f"Sin conflictos de horario para {carrera_codigo} anio {anio} cuatri {cuatrimestre}"
    )


def validar_factibilidad_horarios_todas_carreras(session: Session) -> list[ValidationResult]:
    """Ejecuta la validacion de horarios para todas las combinaciones carrera/anio/cuatri."""
    results = []

    carreras = session.exec(select(CarreraDB)).all()

    for carrera in carreras:
        for anio in range(1, carrera.duracion_anios + 1):
            for cuatri in ["1C", "2C"]:
                result = validar_factibilidad_horarios_carrera(
                    session, carrera.codigo, anio, cuatri
                )
                if not result.valid:
                    results.append(result)

    return results


# =============================================================================
# Validacion 3: Un aula no puede estar asignada a dos horarios en el mismo tiempo/ciclo
# =============================================================================

def validar_conflictos_aula_ciclo(session: Session, ciclo_id: str) -> ValidationResult:
    """
    Verifica que no haya dos horarios asignados a la misma aula con tiempos
    superpuestos dentro de un ciclo.
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
        # Get horarios for each assignment
        horarios_asig = []
        for asig in asigs:
            horario = session.get(HorarioDB, asig.horario_id)
            if horario:
                horarios_asig.append((horario, asig))

        # Check for overlaps within same aula
        for i, (h1, _) in enumerate(horarios_asig):
            for h2, _ in horarios_asig[i+1:]:
                if horarios_se_superponen(h1, h2):
                    conflictos.append(
                        f"Aula {aula_id}: {h1.comision_id} vs {h2.comision_id} "
                        f"en {h1.dia} {h1.hora_inicio.strftime('%H:%M')}"
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

    # Validacion 1: Materias con carrera
    results["materias_carrera"] = validar_materias_tienen_carrera(session)

    # Validacion 2: Horarios por carrera
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

    # Validacion 3: Conflictos de aula (si se especifica ciclo)
    if ciclo_id:
        results["conflictos_aula"] = validar_conflictos_aula_ciclo(session, ciclo_id)

    return results
