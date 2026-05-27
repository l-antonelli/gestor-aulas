"""Service for generating a PlanificacionCursada from a Schedule."""

import math
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import time, timedelta, datetime

from sqlmodel import Session, select, func

from typing import Optional
from sqlmodel import col

from src.database.models import (
    ScheduleEntryDB, PlanificacionCursadaDB, ComisionDB, HorarioDB,
    MateriaDB, ScheduleDB, ConfiguracionHoraria,
    PlanEstudioDB, CicloPlanVersionDB,
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


# =============================================================================
# Preview: analyze schedule entries before generating a plan
# =============================================================================

@dataclass
class EntryPreview:
    """A single schedule entry in the preview."""
    entry_id: str
    dia: str
    hora_inicio: time
    hora_fin: time
    comision_asignada: int  # 1-based comision number
    tipo_clase: Optional[str] = None  # "teorica", "laboratorio" o None (sin determinar)


@dataclass
class MateriaPreview:
    """Preview of how a materia would be split into comisiones."""
    materia_codigo: str
    materia_nombre: str
    horas_semanales: Optional[float]
    total_horas_schedule: float
    n_comisiones: int
    max_clases_paralelas: int  # max entries in the same time slot
    flag: str  # "exact", "duplicates", "uncertain", "no_data", "needs_more_comisiones"
    flag_detail: str  # human-readable explanation
    entries: list[EntryPreview] = field(default_factory=list)


@dataclass
class SchedulePreviewResult:
    """Full preview of plan generation from a schedule."""
    materias: list[MateriaPreview] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


def _calc_entry_hours(hora_inicio: time, hora_fin: time) -> float:
    """Calculate hours between two times, handling midnight crossover."""
    start_min = hora_inicio.hour * 60 + hora_inicio.minute
    end_min = hora_fin.hour * 60 + hora_fin.minute
    if end_min <= start_min:
        # Midnight crossover: e.g., 21:00 - 00:00
        end_min += 24 * 60
    return (end_min - start_min) / 60


def _count_carreras_for_materia(session: Session, materia_codigo: str) -> int:
    """Count how many distinct carreras a materia belongs to."""
    from src.database.models import PlanEstudioDB as PE
    result = session.exec(
        select(func.count(func.distinct(PE.carrera_codigo)))
        .where(PE.materia_codigo == materia_codigo)
    ).one()
    return result or 0


def _derive_comisiones(
    entries: list[ScheduleEntryDB],
    horas_semanales: Optional[float],
    optativa: bool,
    n_carreras: int,
) -> tuple[int, int, str, str]:
    """Derive comision count using simplified rules.

    Rules:
    0. Pre-assigned: if entries already have comision values from DB,
       use max(comision) as floor for n_comisiones.
    1. Optativa -> always 1 (unless pre-assigned > 1)
    2. Exclusive to 1 carrera -> always 1 (unless pre-assigned > 1)
    3. Shared (>1 carrera) -> total_hours / horas_semanales ONLY if exact integer >= 1.
       Otherwise flag for correction.
    4. CONSTRAINT: if max_clases_paralelas > n_comisiones, force n_comisiones =
       max_clases_paralelas with flag "needs_more_comisiones".

    Returns: (n_comisiones, max_clases_paralelas, flag, flag_detail)
    """
    slot_counts = Counter(
        (e.dia, e.hora_inicio, e.hora_fin) for e in entries
    )
    max_paralelas = max(slot_counts.values()) if slot_counts else 1
    total_hours = sum(_calc_entry_hours(e.hora_inicio, e.hora_fin) for e in entries)

    # Rule 0: check pre-assigned comision values from the schedule
    pre_assigned_vals = [e.comision for e in entries if e.comision is not None and e.comision >= 1]
    pre_assigned_max = max(pre_assigned_vals) if pre_assigned_vals else 0
    all_pre_assigned = len(pre_assigned_vals) == len(entries) and pre_assigned_max > 0

    if all_pre_assigned:
        # All entries have explicit comision — trust the user's assignment
        n_comisiones = pre_assigned_max
        flag = "exact"
        flag_detail = (
            f"Comisiones pre-asignadas en el cronograma: "
            f"{n_comisiones} comision(es) detectada(s)."
        )
        # Still check parallel constraint
        if max_paralelas > n_comisiones:
            flag = "needs_more_comisiones"
            flag_detail = (
                f"{max_paralelas} clases paralelas en el mismo horario requieren "
                f"al menos {max_paralelas} comisiones (pre-asignadas: {n_comisiones}). "
                f"Forzando n_comisiones={max_paralelas}."
            )
            n_comisiones = max_paralelas
        return n_comisiones, max_paralelas, flag, flag_detail

    # Rule 1: optativa
    if optativa:
        n_comisiones = 1
        flag, flag_detail = "exact", "Materia optativa: 1 comision por defecto."

    # Rule 2: exclusive to 1 carrera
    elif n_carreras <= 1:
        n_comisiones = 1
        flag, flag_detail = "exact", "Materia exclusiva de 1 carrera: 1 comision por defecto."

    # Rule 3: shared across multiple carreras
    elif not horas_semanales or horas_semanales <= 0:
        n_comisiones = 1
        flag = "no_data"
        flag_detail = (
            f"Materia compartida ({n_carreras} carreras) sin horas_semanales. "
            f"Asumiendo 1 comision. Corregir horas_semanales para derivar correctamente."
        )
    else:
        ratio = total_hours / horas_semanales
        if ratio >= 1 and abs(ratio - round(ratio)) < 0.01:
            n_comisiones = round(ratio)
            flag = "exact"
            flag_detail = (
                f"Materia compartida ({n_carreras} carreras): "
                f"{total_hours:g}h / {horas_semanales}h = {n_comisiones} comision(es)."
            )
        else:
            n_comisiones = 1
            flag = "uncertain"
            flag_detail = (
                f"Materia compartida ({n_carreras} carreras): "
                f"{total_hours:g}h / {horas_semanales}h = {ratio:.2f} (no es entero). "
                f"Asumiendo 1 comision. Verificar horas_semanales."
            )

    # Ensure pre-assigned floor is respected (partial pre-assignment)
    if pre_assigned_max > n_comisiones:
        n_comisiones = pre_assigned_max
        flag_detail += (
            f" Ajustado a {pre_assigned_max} por comisiones pre-asignadas en el cronograma."
        )

    # Rule 4: constraint — parallel classes require at least that many comisiones
    if max_paralelas > n_comisiones:
        flag = "needs_more_comisiones"
        flag_detail = (
            f"{max_paralelas} clases paralelas en el mismo horario requieren "
            f"al menos {max_paralelas} comisiones (se derivaron {n_comisiones}). "
            f"Forzando n_comisiones={max_paralelas}."
        )
        n_comisiones = max_paralelas

    return n_comisiones, max_paralelas, flag, flag_detail


def _assign_entries_to_comisiones(
    entries: list[ScheduleEntryDB],
    n_comisiones: int,
) -> list[EntryPreview]:
    """Distribute entries among comisiones balancing by total hours.

    If entries already have a comision value from the DB, use it.
    For entries with comision=None, assign using hours-balanced algorithm
    that ensures each comision gets roughly equal total hours.
    """
    dia_order = {"Lunes": 0, "Martes": 1, "Miércoles": 2,
                 "Jueves": 3, "Viernes": 4, "Sábado": 5, "Domingo": 6}
    sorted_entries = sorted(
        entries,
        key=lambda e: (dia_order.get(e.dia, 9), e.hora_inicio, e.hora_fin)
    )

    # Separate entries with and without pre-assigned comision
    pre_assigned: dict[str, int] = {}
    needs_assignment: list[ScheduleEntryDB] = []
    com_hours: dict[int, float] = {c: 0.0 for c in range(1, n_comisiones + 1)}

    for e in sorted_entries:
        if e.comision is not None and 1 <= e.comision <= n_comisiones:
            pre_assigned[e.id] = e.comision
            com_hours[e.comision] += _calc_entry_hours(e.hora_inicio, e.hora_fin)
        else:
            needs_assignment.append(e)

    # Assign remaining entries balanced by accumulated hours
    if needs_assignment:
        slot_groups: dict[tuple, list[ScheduleEntryDB]] = {}
        for e in needs_assignment:
            key = (e.dia, e.hora_inicio, e.hora_fin)
            slot_groups.setdefault(key, []).append(e)

        for slot_key in sorted(
            slot_groups.keys(),
            key=lambda k: (dia_order.get(k[0], 9), k[1], k[2]),
        ):
            group = slot_groups[slot_key]
            dur = _calc_entry_hours(group[0].hora_inicio, group[0].hora_fin)
            if len(group) > 1:
                # Parallel entries: assign each to a different comision,
                # preferring those with fewest accumulated hours.
                available = sorted(
                    range(1, n_comisiones + 1),
                    key=lambda c: com_hours[c],
                )
                for i, entry in enumerate(group):
                    com_num = available[i % len(available)]
                    pre_assigned[entry.id] = com_num
                    com_hours[com_num] += dur
            else:
                com_num = min(
                    range(1, n_comisiones + 1),
                    key=lambda c: com_hours[c],
                )
                pre_assigned[group[0].id] = com_num
                com_hours[com_num] += dur

    return [
        EntryPreview(
            entry_id=e.id,
            dia=e.dia,
            hora_inicio=e.hora_inicio,
            hora_fin=e.hora_fin,
            comision_asignada=pre_assigned.get(e.id, 1),
            tipo_clase=e.tipo_clase,
        )
        for e in sorted_entries
    ]


def preview_plan_from_schedule(
    session: Session,
    schedule_id: str,
) -> SchedulePreviewResult:
    """Preview how a plan would be generated from a schedule, without creating anything.

    Returns analysis per materia: proposed comision count, flags, entry assignments.
    """
    result = SchedulePreviewResult()

    schedule = schedule_crud.get(session, schedule_id)
    if schedule is None:
        result.errors.append(f"Schedule '{schedule_id}' no encontrado")
        return result

    entries = session.exec(
        select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == schedule_id)
    ).all()

    if not entries:
        result.errors.append("El schedule no tiene entries")
        return result

    # Group by materia
    materia_entries: dict[str, list[ScheduleEntryDB]] = {}
    for entry in entries:
        materia_entries.setdefault(entry.codigo_materia, []).append(entry)

    for materia_codigo, mat_entries in materia_entries.items():
        materia = materia_crud.get(session, materia_codigo)
        mat_nombre = materia.nombre if materia else materia_codigo
        h_sem = materia.horas_semanales if materia else None
        optativa = materia.optativa if materia else False
        n_carreras = _count_carreras_for_materia(session, materia_codigo)

        total_hours = sum(_calc_entry_hours(e.hora_inicio, e.hora_fin) for e in mat_entries)

        n_comisiones, max_paralelas, flag, flag_detail = _derive_comisiones(
            mat_entries, h_sem, optativa, n_carreras
        )

        entry_previews = _assign_entries_to_comisiones(mat_entries, n_comisiones)

        preview = MateriaPreview(
            materia_codigo=materia_codigo,
            materia_nombre=mat_nombre,
            horas_semanales=h_sem,
            total_horas_schedule=total_hours,
            n_comisiones=n_comisiones,
            max_clases_paralelas=max_paralelas,
            flag=flag,
            flag_detail=flag_detail,
            entries=entry_previews,
        )
        result.materias.append(preview)

    # Sort: flagged first (uncertain > no_data > duplicates > exact)
    flag_order = {"uncertain": 0, "no_data": 1, "duplicates": 2, "exact": 3}
    result.materias.sort(key=lambda m: (flag_order.get(m.flag, 9), m.materia_codigo))

    return result


def generate_plan_from_preview(
    session: Session,
    schedule_id: str,
    nombre: str,
    ciclo_id: str,
    materia_previews: list[MateriaPreview],
    descripcion: str = "",
    forecast_metodo_default: str = "media_movil",
) -> PlanGenerationResult:
    """Generate a plan using the (possibly user-corrected) preview data.

    Args:
        session: Database session.
        schedule_id: Source schedule ID.
        nombre: Name for the plan.
        ciclo_id: Ciclo this plan belongs to.
        materia_previews: List of MateriaPreview with comision assignments.
        descripcion: Descripcion opcional del plan.
        forecast_metodo_default: metodo de forecast aplicado por defecto a las
            materias del plan ("media_movil" | "drift" | "ses"). Editable
            despues por materia con override en MateriaForecastConfigDB.
    """
    result = PlanGenerationResult()

    plan_id = str(uuid.uuid4())
    plan = PlanificacionCursadaDB(
        id=plan_id,
        nombre=nombre,
        descripcion=descripcion,
        ciclo_id=ciclo_id,
        activo=False,
        schedule_id=schedule_id,
        forecast_metodo_default=forecast_metodo_default,
    )
    session.add(plan)
    session.flush()

    for mp in materia_previews:
        materia = materia_crud.get(session, mp.materia_codigo)
        cupo = (materia.cupo or 0) if materia else 0

        # Group entries by comision number
        com_entries: dict[int, list[EntryPreview]] = {}
        for ep in mp.entries:
            com_entries.setdefault(ep.comision_asignada, []).append(ep)

        # Coeficiente uniforme: 1/n para n comisiones de esta materia.
        # El usuario puede ajustarlo despues desde Planes -> Detalle.
        n_comisiones = len(com_entries) or 1
        coef_uniforme = 1.0 / n_comisiones

        for com_num in sorted(com_entries.keys()):
            comision_id = str(uuid.uuid4())
            comision_key = f"{mp.materia_codigo}-{com_num:03d}"

            comision = ComisionDB(
                id=comision_id,
                materia_codigo=mp.materia_codigo,
                plan_cursada_id=plan_id,
                comision_key=comision_key,
                nombre=f"Comision {com_num}",
                numero=com_num,
                cupo=cupo,
                coef_asignacion=coef_uniforme,
            )
            session.add(comision)
            session.flush()
            result.comisiones_created += 1

            for ep in com_entries[com_num]:
                horario = HorarioDB(
                    id=str(uuid.uuid4()),
                    comision_id=comision_id,
                    codigo_materia=mp.materia_codigo,
                    dia=ep.dia,
                    hora_inicio=ep.hora_inicio,
                    hora_fin=ep.hora_fin,
                    tipo_clase=getattr(ep, "tipo_clase", None),
                )
                session.add(horario)
                result.horarios_created += 1

        if mp.flag in ("uncertain", "no_data"):
            result.comision_flags.append(f"{mp.materia_codigo}: {mp.flag_detail}")

    session.commit()
    session.refresh(plan)
    result.plan = plan
    return result


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

        # Coef de asignacion uniforme: 1/n para n comisiones de esta materia
        coef_uniforme = 1.0 / max(len(groups), 1)

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
                coef_asignacion=coef_uniforme,
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
                    tipo_clase=getattr(entry, "tipo_clase", None),
                )
                session.add(horario)
                result.horarios_created += 1

    session.commit()
    session.refresh(plan)
    result.plan = plan
    return result


def apply_horario_edits(
    session: Session,
    plan_id: str,
    materia_codigo: str,
    edited_rows: list[dict],
) -> tuple[int, int, int]:
    """Aplica ediciones bulk a horarios de una materia dentro de un plan.

    Args:
        session: Database session.
        plan_id: ID del plan de cursada.
        materia_codigo: Codigo de la materia cuyos horarios se editan.
        edited_rows: Lista de dicts con keys:
            horario_id, comision_numero, dia, hora_inicio, hora_fin.

    Returns:
        (updated, created, deleted) — cantidad de cada operacion.

    Logica:
    - horario_id existente → update si hay cambios
    - horario_id empieza con "new_" → crear nuevo HorarioDB
    - horario_id en DB pero no en edited_rows → eliminar
    """
    # Get comisiones for this materia in the plan
    comisiones = session.exec(
        select(ComisionDB)
        .where(ComisionDB.plan_cursada_id == plan_id)
        .where(ComisionDB.materia_codigo == materia_codigo)
    ).all()
    com_by_numero = {c.numero: c for c in comisiones}
    com_ids = [c.id for c in comisiones]

    if not com_ids:
        return 0, 0, 0

    # Load existing horarios for these comisiones
    existing_horarios = session.exec(
        select(HorarioDB).where(col(HorarioDB.comision_id).in_(com_ids))
    ).all()
    existing_map = {h.id: h for h in existing_horarios}

    edited_ids = set()
    updated = 0
    created = 0

    for row in edited_rows:
        hid = row["horario_id"]
        com_num = row["comision_numero"]
        target_com = com_by_numero.get(com_num)
        if target_com is None:
            continue

        _row_tipo = row.get("tipo_clase") or None

        if isinstance(hid, str) and hid.startswith("new_"):
            # Create new horario
            new_h = HorarioDB(
                id=str(uuid.uuid4()),
                comision_id=target_com.id,
                codigo_materia=materia_codigo,
                dia=row["dia"],
                hora_inicio=row["hora_inicio"],
                hora_fin=row["hora_fin"],
                tipo_clase=_row_tipo,
            )
            session.add(new_h)
            created += 1
        elif hid in existing_map:
            edited_ids.add(hid)
            h = existing_map[hid]
            changed = (
                h.dia != row["dia"]
                or h.hora_inicio != row["hora_inicio"]
                or h.hora_fin != row["hora_fin"]
                or h.comision_id != target_com.id
                or h.tipo_clase != _row_tipo
            )
            if changed:
                h.dia = row["dia"]
                h.hora_inicio = row["hora_inicio"]
                h.hora_fin = row["hora_fin"]
                h.comision_id = target_com.id
                h.tipo_clase = _row_tipo
                session.add(h)
                updated += 1

    # Delete horarios removed from the edited list
    deleted = 0
    for hid, h in existing_map.items():
        if hid not in edited_ids:
            session.delete(h)
            deleted += 1

    session.commit()
    return updated, created, deleted


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


def generate_time_slots(config: ConfiguracionHoraria) -> list[tuple[time, time]]:
    """Generate time slot ranges based on scheduling configuration.

    Each slot covers `config.granularidad_minutos` minutes, starting from
    `config.hora_inicio_operativo`. The field `hora_fin_operativo` represents
    the start of the last time slot (not the end of operations), so a slot
    starting at that time is always included. This allows covering the
    23:00-00:00 range.

    Returns:
        List of (start_time, end_time) tuples for each slot.
    """
    slots: list[tuple[time, time]] = []
    granularidad = timedelta(minutes=config.granularidad_minutos)

    # Use datetime for arithmetic, then extract time
    base_date = datetime(2000, 1, 1)
    current = datetime.combine(base_date, config.hora_inicio_operativo)
    ultima_franja = datetime.combine(base_date, config.hora_fin_operativo)

    while current <= ultima_franja:
        slot_start = current.time()
        slot_end = (current + granularidad).time()
        slots.append((slot_start, slot_end))
        current += granularidad

    return slots


@dataclass
class TimetableBlock:
    """A block in the timetable grid representing a horario entry."""
    materia_codigo: str
    materia_nombre: str
    comision_nombre: str
    hora_inicio: time
    hora_fin: time
    virtual: bool
    en_periodo: Optional[bool] = None  # True=en su cuatrimestre planificado, False=fuera, None=indeterminado


def _build_periodo_map(
    session: Session, ciclo_id: str, mat_codigos: list[str],
) -> dict[str, Optional[bool]]:
    """Determine if each materia is in its planned cuatrimestre for a ciclo.

    Returns dict materia_codigo -> True (en periodo), False (fuera), None (indeterminado).
    """
    from src.database.models import CicloDB

    ciclo = session.get(CicloDB, ciclo_id)
    if not ciclo:
        return {c: None for c in mat_codigos}

    # "1C" or "2C"
    ciclo_cuatri = f"{ciclo.numero}C"

    # Get plan version ids for this ciclo
    pv_ids = session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    if not pv_ids:
        return {c: None for c in mat_codigos}

    # Get cuatrimestre_plan for each materia in the plan versions
    rows = session.exec(
        select(PlanEstudioDB.materia_codigo, PlanEstudioDB.cuatrimestre_plan)
        .where(PlanEstudioDB.plan_version_id.in_(pv_ids))
        .where(col(PlanEstudioDB.materia_codigo).in_(mat_codigos))
    ).all()

    # Group cuatrimestres by materia (may appear in multiple carreras)
    mat_cuatris: dict[str, set[str]] = {}
    for mat_cod, cuatri in rows:
        if cuatri:
            mat_cuatris.setdefault(mat_cod, set()).add(cuatri)

    result: dict[str, Optional[bool]] = {}
    for cod in mat_codigos:
        cuatris = mat_cuatris.get(cod)
        if not cuatris:
            result[cod] = None  # No info de cuatrimestre en el plan
        elif "Anual" in cuatris or "anual" in cuatris:
            result[cod] = True  # Anuales siempre estan en periodo
        elif ciclo_cuatri in cuatris:
            result[cod] = True
        else:
            result[cod] = False

    return result


def build_timetable_grid(
    session: Session,
    plan_id: str,
    config: ConfiguracionHoraria,
    filtered_materia_codigos: Optional[set[str]] = None,
    ciclo_id: Optional[str] = None,
) -> dict[str, list[TimetableBlock]]:
    """Build a timetable grid data structure for visualization.

    Args:
        session: Database session.
        plan_id: Plan to build the grid for.
        config: Scheduling configuration (for days).
        filtered_materia_codigos: If provided, only include these materias.
        ciclo_id: If provided, calculates en_periodo for each block.

    Returns:
        Dict mapping day name -> list of TimetableBlock sorted by hora_inicio.
    """
    # Get comisiones for this plan
    comisiones = session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all()

    if not comisiones:
        return {}

    # Filter by materia if needed
    if filtered_materia_codigos is not None:
        comisiones = [c for c in comisiones if c.materia_codigo in filtered_materia_codigos]

    comision_ids = [c.id for c in comisiones]
    comision_map = {c.id: c for c in comisiones}

    # Materia info
    mat_codigos = list({c.materia_codigo for c in comisiones})
    materias_db = session.exec(
        select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codigos))
    ).all()
    mat_info = {m.codigo: m for m in materias_db}

    # Build periodo map if ciclo provided
    periodo_map: dict[str, Optional[bool]] = {}
    if ciclo_id:
        periodo_map = _build_periodo_map(session, ciclo_id, mat_codigos)

    # Get horarios
    horarios = session.exec(
        select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
    ).all()

    # Build blocks grouped by day
    grid: dict[str, list[TimetableBlock]] = {}
    for h in horarios:
        com = comision_map.get(h.comision_id)
        if com is None:
            continue
        materia = mat_info.get(com.materia_codigo)
        mat_nombre = materia.nombre if materia else com.materia_codigo
        is_virtual = materia.virtual if materia else False

        block = TimetableBlock(
            materia_codigo=com.materia_codigo,
            materia_nombre=mat_nombre,
            comision_nombre=com.nombre,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            virtual=is_virtual,
            en_periodo=periodo_map.get(com.materia_codigo),
        )
        grid.setdefault(h.dia, []).append(block)

    # Sort blocks within each day
    for day in grid:
        grid[day].sort(key=lambda b: b.hora_inicio)

    return grid


# =============================================================================
# Coeficientes de asignacion (inscriptos por comision)
# =============================================================================

def _comisiones_de_materia_en_plan(
    session: Session, plan_cursada_id: str, materia_codigo: str,
) -> list[ComisionDB]:
    return list(session.exec(
        select(ComisionDB)
        .where(ComisionDB.plan_cursada_id == plan_cursada_id)
        .where(ComisionDB.materia_codigo == materia_codigo)
        .order_by(ComisionDB.numero)
    ).all())


def normalize_coef_asignacion(
    session: Session, plan_cursada_id: str, materia_codigo: str,
) -> int:
    """Reasigna coef_asignacion uniformemente (1/n) entre las comisiones de
    la materia en el plan. Devuelve la cantidad de comisiones afectadas.
    """
    comisiones = _comisiones_de_materia_en_plan(
        session, plan_cursada_id, materia_codigo,
    )
    n = len(comisiones)
    if n == 0:
        return 0
    coef = 1.0 / n
    for c in comisiones:
        c.coef_asignacion = coef
        session.add(c)
    session.commit()
    return n


def update_comision_coef(
    session: Session, comision_id: str, new_coef: float,
) -> Optional[ComisionDB]:
    """Setea el coef_asignacion de una comision puntual (clamp [0, 1]).

    NO normaliza el resto. La UI muestra la suma por dictado y el usuario
    decide si ajusta o aprieta "Normalizar".
    """
    coef = max(0.0, min(1.0, float(new_coef)))
    comision = session.get(ComisionDB, comision_id)
    if comision is None:
        return None
    comision.coef_asignacion = coef
    session.add(comision)
    session.commit()
    session.refresh(comision)
    return comision


def get_coef_sum_por_materia(
    session: Session, plan_cursada_id: str,
) -> dict[str, float]:
    """Devuelve {materia_codigo: suma de coef_asignacion} para todas las
    materias del plan. Para validar que cada suma sea ~1.0.
    """
    rows = list(session.exec(
        select(
            ComisionDB.materia_codigo,
            func.sum(ComisionDB.coef_asignacion),
        )
        .where(ComisionDB.plan_cursada_id == plan_cursada_id)
        .group_by(ComisionDB.materia_codigo)
    ).all())
    return {mc: float(s or 0.0) for mc, s in rows}


def delete_plan_cascade(session: Session, plan_cursada_id: str) -> bool:
    """Borra un plan y todas sus dependencias en orden FK seguro:
    clases -> horarios -> comisiones -> plan.

    Devuelve True si el plan existia y se borro. False si no existia.
    """
    plan = session.get(PlanificacionCursadaDB, plan_cursada_id)
    if plan is None:
        return False

    # Clases (depende de horario, comision, plan)
    clases = list(session.exec(
        select(ClaseDB).where(ClaseDB.plan_cursada_id == plan_cursada_id)
    ).all())
    for c in clases:
        session.delete(c)

    # Horarios -> comisiones
    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_cursada_id)
    ).all())
    for com in comisiones:
        horarios = list(session.exec(
            select(HorarioDB).where(HorarioDB.comision_id == com.id)
        ).all())
        for h in horarios:
            session.delete(h)
        session.delete(com)

    session.delete(plan)
    session.commit()
    return True


def get_inscriptos_esperados_por_comision(
    session: Session, plan_cursada_id: str,
) -> dict[str, float]:
    """Para cada comision del plan, calcula `forecast(materia, cuatri) × coef_asignacion`.

    Usa el cuatrimestre del ciclo del plan. Para materias anuales (que
    tienen serie con cuatri='Anual') prioriza esa serie sobre la del cuatri
    del ciclo.

    El metodo de forecast se resuelve via `forecast_service.resolve_metodo`
    (override por materia > default del plan). El valor se computa al vuelo,
    no se persiste.

    Si la materia no tiene serie historica, se omite del resultado.
    """
    from src.services.forecast_service import get_forecast_for_materia

    plan = session.get(PlanificacionCursadaDB, plan_cursada_id)
    if plan is None or plan.ciclo_id is None:
        return {}

    from src.database.models import CicloDB
    ciclo = session.get(CicloDB, plan.ciclo_id)
    if ciclo is None:
        return {}
    cuatri = f"{ciclo.numero}C"

    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_cursada_id)
    ).all())
    if not comisiones:
        return {}

    # Forecasts por materia: probar "Anual" primero (para materias anuales),
    # sino el del cuatri del ciclo.
    materias = sorted({c.materia_codigo for c in comisiones})
    forecasts: dict[str, float] = {}
    for mc in materias:
        f_anual = get_forecast_for_materia(session, plan_cursada_id, mc, "Anual")
        f_cuatri = get_forecast_for_materia(session, plan_cursada_id, mc, cuatri)
        if f_anual is not None:
            forecasts[mc] = f_anual.valor
        elif f_cuatri is not None:
            forecasts[mc] = f_cuatri.valor

    result: dict[str, float] = {}
    for c in comisiones:
        if c.materia_codigo not in forecasts:
            continue
        result[c.id] = forecasts[c.materia_codigo] * c.coef_asignacion
    return result

