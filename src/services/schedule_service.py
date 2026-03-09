"""Service for creating and managing Schedules from uploaded files."""

import uuid
from dataclasses import dataclass, field
from datetime import date

from sqlmodel import Session, select

from src.database.models import ScheduleDB, ScheduleEntryDB
from src.database.crud import ciclo_crud
from src.services.horario_loading_service import _resolve_materia_code
from src.services.horario_file_parser import parse_horarios_file


@dataclass
class ScheduleCreationResult:
    """Result of creating a schedule from a file."""
    schedule: ScheduleDB | None = None
    entries_created: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def create_schedule_from_file(
    session: Session,
    ciclo_id: str,
    nombre: str,
    file,
) -> ScheduleCreationResult:
    """
    Create a Schedule from an uploaded CSV/Excel file.

    Uses parse_horarios_file() for parsing and _resolve_materia_code() for
    resolving materia codes. Creates ScheduleDB + ScheduleEntryDB records.

    Args:
        session: Database session
        ciclo_id: The ciclo this schedule belongs to
        nombre: Human-readable name for the schedule
        file: Streamlit UploadedFile or file-like object with .name attribute

    Returns:
        ScheduleCreationResult with the created schedule and stats
    """
    result = ScheduleCreationResult()

    # Validate ciclo exists
    ciclo = ciclo_crud.get(session, ciclo_id)
    if ciclo is None:
        result.errors.append(f"Ciclo '{ciclo_id}' no encontrado")
        return result

    # Parse the file
    entries, parse_errors = parse_horarios_file(file)
    result.errors.extend(parse_errors)

    if not entries:
        if not parse_errors:
            result.errors.append("No se encontraron horarios validos en el archivo")
        return result

    # Create the schedule record
    schedule_id = str(uuid.uuid4())
    source_filename = getattr(file, "name", "unknown")

    schedule = ScheduleDB(
        id=schedule_id,
        ciclo_id=ciclo_id,
        nombre=nombre,
        fecha_upload=date.today(),
        source_filename=source_filename,
    )
    session.add(schedule)
    session.flush()

    # Process each entry
    for i, entry in enumerate(entries):
        resolution = _resolve_materia_code(session, entry.codigo_materia)

        if resolution.resolution_type == "unresolved":
            result.errors.append(
                f"Fila {i+1}: Materia '{entry.codigo_materia}' no existe"
            )
            continue

        if resolution.resolution_type == "guarani":
            result.warnings.append(
                f"Fila {i+1}: Codigo '{resolution.original_code}' resuelto via "
                f"codigo_guarani -> '{resolution.resolved_code}'"
            )

        materia_codigo = resolution.resolved_code

        entry_id = str(uuid.uuid4())
        schedule_entry = ScheduleEntryDB(
            id=entry_id,
            schedule_id=schedule_id,
            codigo_materia=materia_codigo,
            dia=entry.dia,
            hora_inicio=entry.hora_inicio,
            hora_fin=entry.hora_fin,
        )
        session.add(schedule_entry)
        result.entries_created += 1

    session.commit()
    session.refresh(schedule)
    result.schedule = schedule
    return result


def get_schedules_for_ciclo(session: Session, ciclo_id: str) -> list[ScheduleDB]:
    """Get all schedules for a ciclo."""
    statement = select(ScheduleDB).where(ScheduleDB.ciclo_id == ciclo_id)
    return list(session.exec(statement).all())


def get_schedule_entries(session: Session, schedule_id: str) -> list[ScheduleEntryDB]:
    """Get all entries for a schedule."""
    statement = select(ScheduleEntryDB).where(
        ScheduleEntryDB.schedule_id == schedule_id
    )
    return list(session.exec(statement).all())
