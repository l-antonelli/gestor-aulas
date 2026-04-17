"""Service for generating individual Clase records from a PlanificacionCursada."""

import uuid
from dataclasses import dataclass, field
from datetime import date, timedelta

from sqlmodel import Session, select

from src.database.models import (
    PlanificacionCursadaDB, ComisionDB, HorarioDB, ClaseDB, DictadoDB,
    DictadoCicloDB,
)
from src.database.crud import planificacion_crud, ciclo_crud

# Map day names to Python weekday numbers (Monday=0)
_DIA_TO_WEEKDAY = {
    "Lunes": 0,
    "Martes": 1,
    "Miércoles": 2,
    "Jueves": 3,
    "Viernes": 4,
    "Sábado": 5,
}


@dataclass
class ClaseGenerationResult:
    """Result of generating clases for a plan."""
    clases_created: int = 0
    errors: list[str] = field(default_factory=list)


def _expand_dates(fecha_inicio: date, fecha_fin: date, dia_semana: str) -> list[date]:
    """
    Generate all dates between fecha_inicio and fecha_fin (inclusive)
    that fall on the given day of the week.
    """
    weekday = _DIA_TO_WEEKDAY.get(dia_semana)
    if weekday is None:
        return []

    dates = []
    # Find the first occurrence of the weekday on or after fecha_inicio
    current = fecha_inicio
    days_ahead = weekday - current.weekday()
    if days_ahead < 0:
        days_ahead += 7
    current = current + timedelta(days=days_ahead)

    while current <= fecha_fin:
        dates.append(current)
        current += timedelta(days=7)

    return dates


def _find_dictado_for_comision(
    session: Session,
    materia_codigo: str,
    ciclo_id: str,
) -> str | None:
    """Find the dictado ID for a materia in a ciclo."""
    result = session.exec(
        select(DictadoDB.id)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.materia_codigo == materia_codigo)
    ).first()
    return result


def generate_clases_for_plan(
    session: Session,
    plan_cursada_id: str,
) -> ClaseGenerationResult:
    """
    Generate ClaseDB records from the Horarios of a plan + ciclo dates.

    For each Horario in the plan's comisiones, expands dates within
    the ciclo's date range that match the horario's day of the week,
    and creates a ClaseDB for each.
    """
    result = ClaseGenerationResult()

    plan = planificacion_crud.get(session, plan_cursada_id)
    if plan is None:
        result.errors.append(f"Plan '{plan_cursada_id}' no encontrado")
        return result

    ciclo = ciclo_crud.get(session, plan.ciclo_id)
    if ciclo is None:
        result.errors.append(f"Ciclo '{plan.ciclo_id}' no encontrado")
        return result

    # Get all comisiones for this plan
    comisiones = session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_cursada_id)
    ).all()

    for comision in comisiones:
        # Find dictado for this materia+ciclo
        dictado_id = _find_dictado_for_comision(
            session, comision.materia_codigo, plan.ciclo_id
        )

        # Get horarios for this comision
        horarios = session.exec(
            select(HorarioDB).where(HorarioDB.comision_id == comision.id)
        ).all()

        for horario in horarios:
            dates = _expand_dates(ciclo.fecha_inicio, ciclo.fecha_fin, horario.dia)

            for fecha in dates:
                clase = ClaseDB(
                    id=str(uuid.uuid4()),
                    horario_id=horario.id,
                    comision_id=comision.id,
                    plan_cursada_id=plan_cursada_id,
                    dictado_id=dictado_id,
                    fecha=fecha,
                    hora_inicio=horario.hora_inicio,
                    hora_fin=horario.hora_fin,
                    executed=False,
                    aula_id=None,
                )
                session.add(clase)
                result.clases_created += 1

    session.commit()
    return result
