"""Service for creating and managing Schedules from uploaded files."""

import uuid
from dataclasses import dataclass, field
from datetime import date, time
from typing import Optional

from sqlmodel import Session, select, col

from src.database.models import (
    ComisionDB,
    MateriaDB,
    ScheduleDB,
    ScheduleEntryDB,
)
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
    """Un bloque en la grilla de un cronograma (entry directo, sin comisiones).

    `comision_id` es la FK a ``ComisionDB``. `comision_numero` es el
    número display de esa comisión (o None si el entry no tiene
    comisión asignada) — se mantiene para las UIs legacy que muestran
    `C1`, `C2`, etc.

    Campos opcionales para la Grilla Horaria del plan:
    - ``aula_label``: etiqueta corta del aula del patrón ("Sede ·
      Aula"). Sólo aplica cuando el block se arma sobre HorarioDB
      (plan de cursada), no sobre entries de cronograma.
    - ``virtual``: si el horario está resuelto como virtual, para
      mostrar un indicador visual en vez de un aula.
    - ``tipo_clase``: 'teorica' | 'laboratorio' | None.
    """
    entry_id: str
    materia_codigo: str
    materia_nombre: str
    hora_inicio: time
    hora_fin: time
    comision_id: str | None = None
    comision_numero: int | None = None
    comision_nombre: str | None = None
    aula_label: str | None = None
    virtual: bool = False
    tipo_clase: str | None = None
    # Etiqueta compacta con la lista de carreras donde la materia
    # figura en PlanEstudioDB. Para materias exclusivas viene el
    # código de carrera solo; para comunes viene 'Común (A, E, M)'.
    # Sólo se puebla desde blocks del plan; los blocks de cronograma
    # (pre-plan) lo dejan en None.
    carreras_label: str | None = None

    # Alias de compatibilidad hacia atrás: código viejo pedía `.comision`
    # como int. Devuelve el numero de la comisión referenciada.
    @property
    def comision(self) -> int | None:  # noqa: D401
        return self.comision_numero


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
    sheet_name: str | None = None,
) -> ScheduleCreationResult:
    """Crear un cronograma sin requerir ciclo.

    Si ciclo_id se provee, valida que exista.  Si no, crea el schedule sin
    asociacion a ciclo.

    Si el archivo es Excel con múltiples hojas y ``sheet_name`` es
    ``None``, se aplica el fallback tradicional del parser (hoja
    ``Horarios`` si existe; sino la primera visible).
    """
    result = ScheduleCreationResult()

    if ciclo_id:
        ciclo = ciclo_crud.get(session, ciclo_id)
        if ciclo is None:
            result.errors.append(f"Ciclo '{ciclo_id}' no encontrado")
            return result

    # Chequeo previo barato: si el archivo no tiene nada usable, no
    # crear el schedule. El pipeline del importador (abajo) hace la
    # validación fina y vuelve a parsear.
    entries, parse_errors = parse_horarios_file(file, sheet_name=sheet_name)
    if not entries:
        result.errors.extend(parse_errors)
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

    # 2026-09-23: se delega en el pipeline del importador
    # (`preview_import` + `commit_import`) en vez de crear las entries
    # a mano. Antes este flujo legacy descartaba la comisión, el tipo
    # de clase y el flag virtual del archivo — un cronograma creado
    # desde la plantilla nueva perdía la mitad de los datos. Como el
    # cronograma recién nace, todas las materias caen en "sin datos
    # previos" y se agregan tal cual.
    from src.services.cronograma_import_service import (
        commit_import as _commit_import,
        preview_import as _preview_import,
    )
    try:
        file.seek(0)
    except Exception:  # noqa: BLE001
        pass
    preview = _preview_import(
        session, schedule_id, file, sheet_name=sheet_name,
    )
    if preview.tiene_errores_bloqueantes:
        session.delete(schedule)
        session.commit()
        result.errors.extend(preview.parse_errors)
        return result
    result.warnings.extend(preview.warnings)
    for _cod, _fila in preview.materias_no_resueltas:
        result.errors.append(
            f"Fila ~{_fila}: Materia '{_cod}' no existe"
        )
    _commit_res = _commit_import(session, preview, {})
    result.errors.extend(_commit_res.errors)
    result.entries_created = _commit_res.entries_creados

    session.commit()
    session.refresh(schedule)
    result.schedule = schedule
    return result


def clonar_plan_a_cronograma(
    session: Session,
    plan_id: str,
    nombre: str,
    ciclo_id_override: Optional[str] = None,
) -> ScheduleDB:
    """Crea un cronograma nuevo a partir del estado consolidado de un plan.

    Fase F del rediseño 2026-09-15. Uso típico: después de varias
    iteraciones de validación y edición sobre un plan, se quiere
    "guardar" el estado actual como un cronograma reutilizable — por
    ejemplo, para archivar la versión consolidada del ciclo o para
    usarla como base de un ciclo siguiente.

    Qué se clona:
    - ``ComisionDB`` del plan → ``ComisionDB`` del schedule (nuevos
      UUIDs), preservando: ``nombre``, ``numero``, ``cupo``,
      ``descripcion``, ``coef_asignacion``, ``carrera_asignada``.
      **No** se copia ``dictado_id`` — los dictados pertenecen al
      ciclo; al generar un plan nuevo desde este cronograma se
      re-resuelven contra el ciclo destino.
    - ``HorarioDB`` de cada comisión del plan → ``ScheduleEntryDB``
      del schedule (nuevos UUIDs, ``comision_id`` apuntando a la
      comisión clonada), preservando: ``codigo_materia``, ``dia``,
      ``hora_inicio``, ``hora_fin``, ``tipo_clase``, ``virtual``.
      **No** se copia ``aula_id`` — las entries del cronograma son
      "sin aula asignada"; el aula la resuelve el LP al armar el
      plan nuevo.

    Qué NO se clona (fuera de scope del cronograma):
    - Snapshots de validación (``PlanValidationDB``).
    - Excepciones de conflicto ignoradas (``IgnoredConflictDB``).
    - Config del asignador, corridas del LP, etc.

    Args:
        session: sesión activa.
        plan_id: plan de cursada de origen.
        nombre: nombre para el cronograma nuevo.
        ciclo_id_override: si se especifica, el cronograma queda
            asociado a este ciclo en lugar del ``ciclo_id`` del plan.
            Útil para clonar un plan del ciclo N como plantilla del
            ciclo N+1.

    Returns:
        ``ScheduleDB`` recién creado (ya committeado).

    Raises:
        ValueError si el plan no existe o el ciclo de override no existe.
    """
    from src.database.models import (
        ComisionDB as _Com,
        HorarioDB as _Hor,
        PlanificacionCursadaDB as _Plan,
    )

    plan = session.get(_Plan, plan_id)
    if plan is None:
        raise ValueError(f"Plan '{plan_id}' no existe.")

    ciclo_id_final = ciclo_id_override if ciclo_id_override is not None else plan.ciclo_id
    if ciclo_id_final is not None:
        if ciclo_crud.get(session, ciclo_id_final) is None:
            raise ValueError(f"Ciclo '{ciclo_id_final}' no existe.")

    schedule = ScheduleDB(
        id=str(uuid.uuid4()),
        ciclo_id=ciclo_id_final,
        nombre=nombre,
        fecha_upload=date.today(),
        source_filename=f"clon:plan:{plan_id}",
    )
    session.add(schedule)
    session.flush()

    # Clonar comisiones del plan → comisiones del schedule.
    comisiones_plan = list(session.exec(
        select(_Com).where(_Com.plan_cursada_id == plan_id)
    ).all())
    # Mapa plan_com_id → schedule_com_id, para linkear los horarios.
    com_id_map: dict[str, str] = {}
    for c in comisiones_plan:
        new_id = str(uuid.uuid4())
        com_id_map[c.id] = new_id
        session.add(_Com(
            id=new_id,
            materia_codigo=c.materia_codigo,
            dictado_id=None,  # dictados son del ciclo, se re-resuelven
            plan_cursada_id=None,
            schedule_id=schedule.id,
            comision_key=c.comision_key,
            nombre=c.nombre,
            numero=c.numero,
            cupo=c.cupo,
            descripcion=c.descripcion,
            coef_asignacion=c.coef_asignacion,
            carrera_asignada=c.carrera_asignada,
        ))
    session.flush()

    # Clonar horarios del plan → entries del schedule.
    if com_id_map:
        horarios_plan = list(session.exec(
            select(_Hor).where(col(_Hor.comision_id).in_(list(com_id_map.keys())))
        ).all())
        for h in horarios_plan:
            new_com_id = com_id_map.get(h.comision_id)
            if new_com_id is None:
                continue
            session.add(ScheduleEntryDB(
                id=str(uuid.uuid4()),
                schedule_id=schedule.id,
                codigo_materia=h.codigo_materia,
                dia=h.dia,
                hora_inicio=h.hora_inicio,
                hora_fin=h.hora_fin,
                comision_id=new_com_id,
                tipo_clase=h.tipo_clase,
                virtual=h.virtual,
                # Nota: NO se copia aula_id — el cronograma no tiene
                # concepto de aula asignada; el LP resuelve eso al
                # generar el plan siguiente.
            ))

    session.commit()
    session.refresh(schedule)
    return schedule


# =============================================================================
# Queries
# =============================================================================

def get_all_schedules(
    session: Session, *, incluir_shadows: bool = False,
) -> list[ScheduleDB]:
    """Listar todos los cronogramas.

    Los shadow schedules del importer (Fase G) se ocultan por default:
    son artefactos temporales del preview que no deberían aparecer en
    la Lista, en el wizard de plan, ni en los selectores de import
    destino.
    """
    statement = select(ScheduleDB).order_by(ScheduleDB.fecha_upload.desc())  # type: ignore[attr-defined]
    if not incluir_shadows:
        statement = statement.where(ScheduleDB.es_shadow_import == False)  # noqa: E712
    return list(session.exec(statement).all())


def get_schedules_for_ciclo(
    session: Session, ciclo_id: str, *, incluir_shadows: bool = False,
) -> list[ScheduleDB]:
    """Get all schedules for a ciclo (excluye shadows del importer por default)."""
    statement = select(ScheduleDB).where(ScheduleDB.ciclo_id == ciclo_id)
    if not incluir_shadows:
        statement = statement.where(ScheduleDB.es_shadow_import == False)  # noqa: E712
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

    # Clonar primero las comisiones del schedule original y armar un
    # mapa old_comision_id -> new_comision_id.
    from src.services.comision_service import list_comisiones_for_schedule
    comisiones_origen = list_comisiones_for_schedule(session, schedule_id)
    com_id_map: dict[str, str] = {}
    for c in comisiones_origen:
        clon_c = ComisionDB(
            id=str(uuid.uuid4()),
            materia_codigo=c.materia_codigo,
            schedule_id=new_id,
            plan_cursada_id=None,
            comision_key=c.comision_key,
            nombre=c.nombre,
            numero=c.numero,
            cupo=c.cupo,
            descripcion=c.descripcion,
            coef_asignacion=c.coef_asignacion,
            carrera_asignada=c.carrera_asignada,
        )
        session.add(clon_c)
        com_id_map[c.id] = clon_c.id
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
            comision_id=com_id_map.get(e.comision_id) if e.comision_id else None,
            tipo_clase=e.tipo_clase,
            virtual=e.virtual,
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
    comision_id: str | None = None,
    tipo_clase: str | None = None,
    virtual: bool | None = None,
) -> ScheduleEntryDB:
    """Agregar una entrada a un cronograma existente.

    `comision_id` es FK a ``ComisionDB``. Si es None, el entry queda
    huérfano (sin comisión asignada).

    `virtual` es Optional[bool]: None=heredar (default), True=virtual,
    False=presencial. Se propaga a HorarioDB.virtual al generar el plan.

    Nota: el override de carrera de sede (``carrera_asignada``) vive
    ahora a nivel ``ComisionDB``, no a nivel entry.
    """
    entry = ScheduleEntryDB(
        id=str(uuid.uuid4()),
        schedule_id=schedule_id,
        codigo_materia=codigo_materia,
        dia=dia,
        hora_inicio=hora_inicio,
        hora_fin=hora_fin,
        comision_id=comision_id,
        tipo_clase=tipo_clase,
        virtual=virtual,
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

    allowed = {
        "dia", "hora_inicio", "hora_fin", "codigo_materia",
        "comision_id", "tipo_clase", "virtual",
    }
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
        ed_comision_id = ed.get("comision_id")
        ed_tipo = ed.get("tipo_clase") or None
        ed_virtual = ed.get("virtual")

        if isinstance(eid, str) and eid.startswith("new_"):
            # New entry
            add_schedule_entry(
                session, schedule_id, materia_codigo,
                ed["dia"], ed["hora_inicio"], ed["hora_fin"],
                comision_id=ed_comision_id,
                tipo_clase=ed_tipo,
                virtual=ed_virtual,
            )
            created += 1
        elif eid in current_map:
            edited_ids.add(eid)
            existing = current_map[eid]
            changed = (
                existing.dia != ed["dia"]
                or existing.hora_inicio != ed["hora_inicio"]
                or existing.hora_fin != ed["hora_fin"]
                or existing.comision_id != ed_comision_id
                or existing.tipo_clase != ed_tipo
                or existing.virtual != ed_virtual
            )
            if changed:
                update_schedule_entry(
                    session, eid,
                    dia=ed["dia"],
                    hora_inicio=ed["hora_inicio"],
                    hora_fin=ed["hora_fin"],
                    comision_id=ed_comision_id,
                    tipo_clase=ed_tipo,
                    virtual=ed_virtual,
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
    mat_virtual = {m.codigo: bool(m.virtual) for m in materias}

    # Resolver comisiones referenciadas
    com_ids = {e.comision_id for e in entries if e.comision_id}
    comisiones_map: dict[str, ComisionDB] = {}
    if com_ids:
        comisiones_map = {
            c.id: c for c in session.exec(
                select(ComisionDB).where(col(ComisionDB.id).in_(list(com_ids)))
            ).all()
        }

    grid: dict[str, list[ScheduleBlock]] = {}
    for e in entries:
        com = comisiones_map.get(e.comision_id) if e.comision_id else None
        # Bugfix (2026-09-23): `block.virtual` no se populaba nunca —
        # quedaba en el default False y las entradas marcadas virtual
        # no se veían en ninguna vista de cronograma. Resolución:
        # el override de la entry manda; con None (heredar) cae al
        # flag de catálogo de la materia.
        _virt = (
            e.virtual
            if e.virtual is not None
            else mat_virtual.get(e.codigo_materia, False)
        )
        block = ScheduleBlock(
            entry_id=e.id,
            materia_codigo=e.codigo_materia,
            materia_nombre=mat_names.get(e.codigo_materia, e.codigo_materia),
            hora_inicio=e.hora_inicio,
            hora_fin=e.hora_fin,
            comision_id=e.comision_id,
            comision_numero=com.numero if com else None,
            comision_nombre=com.nombre if com else None,
            virtual=_virt,
        )
        grid.setdefault(e.dia, []).append(block)

    # Ordenar cada dia por hora_inicio
    for dia in grid:
        grid[dia].sort(key=lambda b: b.hora_inicio)

    return grid
