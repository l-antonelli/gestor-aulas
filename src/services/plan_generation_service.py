"""Service for generating a PlanificacionCursada from a Schedule."""

import uuid
from dataclasses import dataclass, field

from sqlmodel import Session, select

from src.database.models import (
    ScheduleEntryDB, PlanificacionCursadaDB, ComisionDB, HorarioDB,
    MateriaDB, ScheduleDB,
)
from src.database.crud import schedule_crud, planificacion_crud, materia_crud
from src.services.horario_loading_service import derive_comision_count


@dataclass
class PlanGenerationResult:
    """Result of generating a plan from a schedule."""
    plan: PlanificacionCursadaDB | None = None
    comisiones_created: int = 0
    horarios_created: int = 0
    errors: list[str] = field(default_factory=list)
    comision_flags: list[str] = field(default_factory=list)


def generate_plan_from_schedule(
    session: Session,
    schedule_id: str,
    nombre: str,
    ciclo_id: str,
) -> PlanGenerationResult:
    """
    Generate a PlanificacionCursada from a Schedule.

    Reads ScheduleEntries, groups by materia, derives comision counts,
    creates ComisionDB and HorarioDB records.

    Args:
        session: Database session
        schedule_id: ID of the Schedule to generate from
        nombre: Name for the plan
        ciclo_id: The ciclo this plan belongs to

    Returns:
        PlanGenerationResult with the created plan and stats
    """
    result = PlanGenerationResult()

    # Validate schedule exists
    schedule = schedule_crud.get(session, schedule_id)
    if schedule is None:
        result.errors.append(f"Schedule '{schedule_id}' no encontrado")
        return result

    # Get entries
    entries = session.exec(
        select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == schedule_id)
    ).all()

    if not entries:
        result.errors.append("El schedule no tiene entries")
        return result

    # Create plan
    plan_id = str(uuid.uuid4())
    plan = PlanificacionCursadaDB(
        id=plan_id,
        nombre=nombre,
        ciclo_id=ciclo_id,
        activo=False,
        schedule_id=schedule_id,
    )
    session.add(plan)
    session.flush()

    # Group entries by materia
    materia_entries: dict[str, list[ScheduleEntryDB]] = {}
    for entry in entries:
        materia_entries.setdefault(entry.codigo_materia, []).append(entry)

    # For each materia, derive comision count and create comisiones + horarios
    for materia_codigo, mat_entries in materia_entries.items():
        materia = materia_crud.get(session, materia_codigo)
        if materia is None:
            result.errors.append(f"Materia '{materia_codigo}' no encontrada")
            continue

        # Calculate total weekly hours from schedule entries
        total_hours = sum(
            (e.hora_fin.hour * 60 + e.hora_fin.minute -
             e.hora_inicio.hour * 60 - e.hora_inicio.minute) / 60
            for e in mat_entries
        )

        n_comisiones, flag = derive_comision_count(total_hours, materia.horas_semanales)

        # Check if rows can be evenly split
        n_rows = len(mat_entries)
        if n_comisiones > 1 and n_rows % n_comisiones != 0:
            result.comision_flags.append(
                f"{materia_codigo}: {n_comisiones} comisiones pero "
                f"{n_rows} filas no se dividen equitativamente. Usando 1."
            )
            n_comisiones = 1

        if flag in ("ceil", "no_data"):
            result.comision_flags.append(
                f"{materia_codigo}: {n_comisiones} comision(es) "
                f"(total_h={total_hours:.1f}, h_sem={materia.horas_semanales}, flag={flag})"
            )

        # Sort entries by dia + hora for consistent grouping
        dia_order = {"Lunes": 0, "Martes": 1, "Miércoles": 2,
                     "Jueves": 3, "Viernes": 4, "Sábado": 5}
        sorted_entries = sorted(
            mat_entries,
            key=lambda e: (dia_order.get(e.dia, 9), e.hora_inicio)
        )

        # Split into groups
        if n_comisiones == 1:
            groups = [sorted_entries]
        else:
            chunk_size = n_rows // n_comisiones
            groups = [
                sorted_entries[i * chunk_size:(i + 1) * chunk_size]
                for i in range(n_comisiones)
            ]

        # Create comisiones and horarios
        for com_idx, group in enumerate(groups):
            com_numero = com_idx + 1
            comision_id = str(uuid.uuid4())
            comision_key = f"{materia_codigo}-{com_numero:03d}"
            comision_nombre = f"Comision {com_numero}"

            comision = ComisionDB(
                id=comision_id,
                materia_codigo=materia_codigo,
                plan_cursada_id=plan_id,
                comision_key=comision_key,
                nombre=comision_nombre,
                numero=com_numero,
                cupo=materia.cupo or 0,
            )
            session.add(comision)
            session.flush()
            result.comisiones_created += 1

            for entry in group:
                horario_id = str(uuid.uuid4())
                horario = HorarioDB(
                    id=horario_id,
                    comision_id=comision_id,
                    codigo_materia=materia_codigo,
                    dia=entry.dia,
                    hora_inicio=entry.hora_inicio,
                    hora_fin=entry.hora_fin,
                )
                session.add(horario)
                result.horarios_created += 1

    session.commit()
    session.refresh(plan)
    result.plan = plan
    return result


def activate_plan(session: Session, plan_cursada_id: str) -> bool:
    """
    Activate a plan and deactivate all other plans for the same ciclo.

    Returns True if the plan was found and activated.
    """
    plan = planificacion_crud.get(session, plan_cursada_id)
    if plan is None:
        return False

    # Deactivate other plans for the same ciclo
    other_plans = session.exec(
        select(PlanificacionCursadaDB)
        .where(PlanificacionCursadaDB.ciclo_id == plan.ciclo_id)
        .where(PlanificacionCursadaDB.id != plan_cursada_id)
    ).all()

    for other in other_plans:
        other.activo = False
        session.add(other)

    plan.activo = True
    session.add(plan)
    session.commit()
    return True
