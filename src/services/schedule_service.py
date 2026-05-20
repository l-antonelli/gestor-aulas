"""Service for creating and managing Schedules from uploaded files."""

import uuid
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from sqlmodel import Session, select, col

from src.database.models import ScheduleDB, ScheduleEntryDB, MateriaDB
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


@dataclass
class ScheduleBlock:
    """Un bloque en la grilla de un cronograma (entry directo, sin comisiones)."""
    entry_id: str
    materia_codigo: str
    materia_nombre: str
    hora_inicio: time
    hora_fin: time
    comision: int | None = None


# =============================================================================
# Creation
# =============================================================================

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


def create_empty_schedule(
    session: Session,
    nombre: str,
    ciclo_id: Optional[str] = None,
) -> ScheduleDB:
    """Crear un cronograma vacio (sin entries) para luego agregar entradas manualmente."""
    if ciclo_id:
        ciclo = ciclo_crud.get(session, ciclo_id)
        if ciclo is None:
            raise ValueError(f"Ciclo '{ciclo_id}' no encontrado")

    schedule = ScheduleDB(
        id=str(uuid.uuid4()),
        ciclo_id=ciclo_id,
        nombre=nombre,
        fecha_upload=date.today(),
        source_filename="",
    )
    session.add(schedule)
    session.commit()
    session.refresh(schedule)
    return schedule


def create_schedule_standalone(
    session: Session,
    nombre: str,
    file,
    ciclo_id: Optional[str] = None,
) -> ScheduleCreationResult:
    """Crear un cronograma sin requerir ciclo.

    Si ciclo_id se provee, valida que exista.  Si no, crea el schedule sin
    asociacion a ciclo.
    """
    result = ScheduleCreationResult()

    if ciclo_id:
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

        entry_id = str(uuid.uuid4())
        schedule_entry = ScheduleEntryDB(
            id=entry_id,
            schedule_id=schedule_id,
            codigo_materia=resolution.resolved_code,
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


# =============================================================================
# Queries
# =============================================================================

def get_all_schedules(session: Session) -> list[ScheduleDB]:
    """Listar todos los cronogramas."""
    statement = select(ScheduleDB).order_by(ScheduleDB.fecha_upload.desc())  # type: ignore[attr-defined]
    return list(session.exec(statement).all())


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


# =============================================================================
# Mutations
# =============================================================================

def duplicate_schedule(
    session: Session,
    schedule_id: str,
    new_name: str,
) -> ScheduleDB:
    """Clonar un schedule y todas sus entries con un nuevo nombre."""
    original = session.get(ScheduleDB, schedule_id)
    if original is None:
        raise ValueError(f"Schedule '{schedule_id}' no encontrado")

    new_id = str(uuid.uuid4())
    clone = ScheduleDB(
        id=new_id,
        ciclo_id=original.ciclo_id,
        nombre=new_name,
        fecha_upload=date.today(),
        source_filename=original.source_filename,
    )
    session.add(clone)
    session.flush()

    entries = get_schedule_entries(session, schedule_id)
    for e in entries:
        new_entry = ScheduleEntryDB(
            id=str(uuid.uuid4()),
            schedule_id=new_id,
            codigo_materia=e.codigo_materia,
            dia=e.dia,
            hora_inicio=e.hora_inicio,
            hora_fin=e.hora_fin,
            comision=e.comision,
            tipo_clase=e.tipo_clase,
        )
        session.add(new_entry)

    session.commit()
    session.refresh(clone)
    return clone


def delete_schedule(session: Session, schedule_id: str) -> None:
    """Borrar un schedule y todas sus entries."""
    entries = get_schedule_entries(session, schedule_id)
    for e in entries:
        session.delete(e)

    schedule = session.get(ScheduleDB, schedule_id)
    if schedule:
        session.delete(schedule)

    session.commit()


def add_schedule_entry(
    session: Session,
    schedule_id: str,
    codigo_materia: str,
    dia: str,
    hora_inicio: time,
    hora_fin: time,
    comision: int | None = None,
    tipo_clase: str | None = None,
) -> ScheduleEntryDB:
    """Agregar una entrada a un cronograma existente."""
    entry = ScheduleEntryDB(
        id=str(uuid.uuid4()),
        schedule_id=schedule_id,
        codigo_materia=codigo_materia,
        dia=dia,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        comision=comision,
        tipo_clase=tipo_clase,
    )
    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def update_schedule_entry(session: Session, entry_id: str, **campos) -> ScheduleEntryDB:
    """Actualizar campos individuales de una entrada de cronograma."""
    entry = session.get(ScheduleEntryDB, entry_id)
    if entry is None:
        raise ValueError(f"Entry '{entry_id}' no encontrada")

    allowed = {"dia", "hora_inicio", "hora_fin", "codigo_materia", "comision", "tipo_clase"}
    for key, value in campos.items():
        if key not in allowed:
            raise ValueError(f"Campo '{key}' no permitido")
        setattr(entry, key, value)

    session.add(entry)
    session.commit()
    session.refresh(entry)
    return entry


def delete_schedule_entry(session: Session, entry_id: str) -> None:
    """Eliminar una entrada de cronograma."""
    entry = session.get(ScheduleEntryDB, entry_id)
    if entry:
        session.delete(entry)
        session.commit()


def sync_preview_edits_to_schedule(
    session: Session,
    schedule_id: str,
    materia_codigo: str,
    edited_entries: list[dict],
) -> tuple[int, int, int]:
    """Sincroniza entries editados con la DB para una materia.

    Args:
        session: Database session.
        schedule_id: ID del schedule a sincronizar.
        materia_codigo: Codigo de la materia cuyos entries se editaron.
        edited_entries: Lista de dicts con keys: entry_id, dia, hora_inicio,
            hora_fin, comision (opcional).

    Returns:
        (updated, created, deleted) — cantidad de cada operacion.

    Logica:
    - entry_id existente en DB → update si hay cambios
    - entry_id empieza con "new_" → add_schedule_entry()
    - entry_id en DB pero no en edited_entries → delete_schedule_entry()
    """
    # Get current entries for this materia in the schedule
    current_entries = session.exec(
        select(ScheduleEntryDB)
        .where(ScheduleEntryDB.schedule_id == schedule_id)
        .where(ScheduleEntryDB.codigo_materia == materia_codigo)
    ).all()
    current_map = {e.id: e for e in current_entries}

    edited_ids = set()
    updated = 0
    created = 0

    for ed in edited_entries:
        eid = ed["entry_id"]
        ed_comision = ed.get("comision")
        ed_tipo = ed.get("tipo_clase") or None

        if isinstance(eid, str) and eid.startswith("new_"):
            # New entry
            add_schedule_entry(
                session, schedule_id, materia_codigo,
                ed["dia"], ed["hora_inicio"], ed["hora_fin"],
                comision=ed_comision,
                tipo_clase=ed_tipo,
            )
            created += 1
        elif eid in current_map:
            edited_ids.add(eid)
            existing = current_map[eid]
            changed = (
                existing.dia != ed["dia"]
                or existing.hora_inicio != ed["hora_inicio"]
                or existing.hora_fin != ed["hora_fin"]
                or existing.comision != ed_comision
                or existing.tipo_clase != ed_tipo
            )
            if changed:
                update_schedule_entry(
                    session, eid,
                    dia=ed["dia"],
                    hora_inicio=ed["hora_inicio"],
                    hora_fin=ed["hora_fin"],
                    comision=ed_comision,
                    tipo_clase=ed_tipo,
                )
                updated += 1

    # Delete entries that were removed from the edited list
    deleted = 0
    for eid, entry in current_map.items():
        if eid not in edited_ids:
            delete_schedule_entry(session, eid)
            deleted += 1

    return updated, created, deleted


# =============================================================================
# Grid builder
# =============================================================================

def build_schedule_grid(
    session: Session,
    schedule_id: str,
) -> dict[str, list[ScheduleBlock]]:
    """Construir grilla semanal directamente desde las entries de un schedule.

    Analogo a build_timetable_grid pero sin pasar por comisiones/horarios.

    Returns:
        Dict dia -> lista de ScheduleBlock ordenados por hora_inicio.
    """
    entries = get_schedule_entries(session, schedule_id)
    if not entries:
        return {}

    # Resolver nombres de materias
    mat_codigos = list({e.codigo_materia for e in entries})
    materias = session.exec(
        select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codigos))
    ).all()
    mat_names = {m.codigo: m.nombre for m in materias}

    grid: dict[str, list[ScheduleBlock]] = {}
    for e in entries:
        block = ScheduleBlock(
            entry_id=e.id,
            materia_codigo=e.codigo_materia,
            materia_nombre=mat_names.get(e.codigo_materia, e.codigo_materia),
            hora_inicio=e.hora_inicio,
            hora_fin=e.hora_fin,
            comision=e.comision,
        )
        grid.setdefault(e.dia, []).append(block)

    # Ordenar cada dia por hora_inicio
    for dia in grid:
        grid[dia].sort(key=lambda b: b.hora_inicio)

    return grid
