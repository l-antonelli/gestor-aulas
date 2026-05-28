"""Service para validar cronogramas (ScheduleDB) contra ciclos.

Encapsula la logica que antes estaba inline en `app/pages/5_📊_Planes.py`:

- Computa el resumen completo de validacion: cobertura, faltantes por
  carrera, extras, breakdown de laboratorios, factibilidad de particion.
- Persiste cada validacion como un `ScheduleValidationDB` (snapshot
  historico) con `details_json` para reconstruccion sin recomputar.
- Provee helpers para leer la ultima validacion y detectar staleness.

La UI (Cronogramas) consume este servicio: setear schedule + ciclo,
ejecutar `validar_cronograma()`, persistir con `persist_validation()`,
y luego recuperar con `get_latest_validation()` para mostrar el badge.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select, col, func

from src.database.models import (
    CarreraDB,
    CicloPlanVersionDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    ScheduleEntryDB,
    ScheduleValidationDB,
)
from src.database.crud import ciclo_crud
from src.services.dictado_service import (
    count_active_dictados_for_ciclo,
    get_dictado_codigos_for_ciclo,
    get_materias_esperadas_from_dictados,
    has_dictados_for_ciclo,
)
from src.services.validations import (
    validar_conflictos_horarios_cronograma,
    validar_factibilidad_particion_horas,
    ConflictoHorario,
)


# =============================================================================
# Resumen
# =============================================================================

@dataclass
class CronogramaValidationSummary:
    """Resumen completo de una validacion de cronograma contra un ciclo.

    Se construye via `validar_cronograma()` y se persiste como
    `ScheduleValidationDB` via `persist_validation()`.
    """
    schedule_id: str
    ciclo_id: str
    validated_at: datetime = field(default_factory=datetime.utcnow)

    # Snapshot del cronograma
    entry_count_at_validation: int = 0
    # Snapshot del set de dictados activos (para detectar staleness por cambios
    # en la pestaña Dictados aunque el cronograma no haya cambiado).
    dictado_count_at_validation: int = 0

    # Error pre-computo: si el ciclo no tiene dictados creados, la prevalidacion
    # se aborta y este campo describe la condicion. La UI debe renderear el
    # mensaje y omitir el resto del summary.
    error: Optional[str] = None

    # Resumen general
    n_materias: int = 0
    n_clases: int = 0
    total_horas: float = 0.0

    # Cobertura vs ciclo
    n_esperadas: int = 0
    n_cubiertas: int = 0
    n_faltantes: int = 0
    n_extra: int = 0

    # Resumen de laboratorios
    n_con_lab_asignado: int = 0
    n_lab_fijo: int = 0
    n_lab_reserva: int = 0
    n_lab_pendiente: int = 0

    # Particion teoria/lab
    particion_valid: bool = True
    particion_n_infactibles: int = 0
    particion_message: str = ""

    # Conflictos de horarios (con comisiones auto-derivadas)
    n_conflictos_horarios: int = 0

    # Config aplicada (toggle "excluir optativas"). Las virtuales SI se
    # validan (estructuralmente deben ser consistentes); solo las optativas
    # se descartan del set esperado cuando el toggle esta ON.
    # `excluir_virtuales_optativas` queda como alias retro-compatible.
    excluir_optativas: bool = False
    excluir_virtuales_optativas: bool = False  # legacy

    # Detalle (para reconstruir la UI sin recomputar)
    faltantes_por_carrera: list[dict] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)
    particion_details: list[str] = field(default_factory=list)
    conflictos_horarios: list[dict] = field(default_factory=list)
    esperadas: dict[str, str] = field(default_factory=dict)
    mat_map: dict[str, str] = field(default_factory=dict)

    def to_details_json(self) -> str:
        """Serializa los campos de detalle a JSON para persistir."""
        return json.dumps({
            "faltantes_por_carrera": self.faltantes_por_carrera,
            "extras": self.extras,
            "particion_details": self.particion_details,
            "conflictos_horarios": self.conflictos_horarios,
            "esperadas": self.esperadas,
            "mat_map": self.mat_map,
            "particion_message": self.particion_message,
        })


# =============================================================================
# Helpers (originalmente en 5_📊_Planes.py)
# =============================================================================

def _get_faltantes_por_carrera(
    session: Session,
    ciclo_id: str,
    esperadas: dict[str, str],
    materias_en_schedule: set[str],
    dictado_codigos: dict[str, str],
) -> list[dict]:
    """Return faltantes agrupados por carrera con info de plan y razon.

    El conjunto de "faltantes" se calcula contra las materias esperadas
    (provistas via `esperadas`, que vienen de DictadoDB activo). El detalle
    por carrera se enriquece via PlanEstudioDB para mostrar contexto
    (anio/cuatri/optativa) — pero la razón se construye en función del
    dictado: "Dictado activo {dictado_codigo} sin horarios cargados".
    """
    ciclo = ciclo_crud.get(session, ciclo_id)
    if not ciclo:
        return []

    faltantes_set = set(esperadas.keys()) - materias_en_schedule
    if not faltantes_set:
        return []

    cpv_rows = session.exec(
        select(CicloPlanVersionDB).where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all()

    result = []
    for cpv in cpv_rows:
        pv = session.get(PlanCarreraVersionDB, cpv.plan_version_id)
        if not pv:
            continue
        carrera = session.get(CarreraDB, pv.carrera_codigo)
        if not carrera:
            continue

        pe_rows = session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.plan_version_id == pv.id)
            .order_by(PlanEstudioDB.anio_plan, PlanEstudioDB.cuatrimestre_plan)
        ).all()

        faltantes_pe = [
            pe for pe in pe_rows if pe.materia_codigo in faltantes_set
        ]
        if not faltantes_pe:
            continue

        falt_codigos = list({pe.materia_codigo for pe in faltantes_pe})
        mats_db = session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(falt_codigos))
        ).all()
        mat_map = {m.codigo: m for m in mats_db}

        materias_faltantes = []
        for pe in faltantes_pe:
            mat = mat_map.get(pe.materia_codigo)
            if not mat:
                continue

            dic_cod = dictado_codigos.get(mat.codigo, "?")
            razon = f"Dictado activo {dic_cod} sin horarios cargados"

            materias_faltantes.append({
                "codigo": mat.codigo,
                "nombre": mat.nombre,
                "anio_plan": pe.anio_plan,
                "cuatrimestre_plan": pe.cuatrimestre_plan,
                "optativa": pe.optativa,
                "periodo": mat.periodo,
                "horas_semanales": mat.horas_semanales,
                "virtual": mat.virtual,
                "dictado_codigo": dic_cod,
                "razon": razon,
            })

        if materias_faltantes:
            result.append({
                "carrera_codigo": carrera.codigo,
                "carrera_nombre": carrera.nombre,
                "plan_version_nombre": pv.nombre,
                "dicta_recursado": carrera.dicta_recursado,
                "materias": materias_faltantes,
            })

    result.sort(key=lambda x: x["carrera_codigo"])
    return result


def _compute_lab_breakdown(
    session: Session, materia_codigos: list[str],
) -> tuple[int, int, int, int]:
    """Cuenta materias del cronograma segun su modo lab.

    Returns:
        (n_con_lab_asignado, n_lab_fijo, n_lab_reserva, n_lab_pendiente)

    - n_con_lab_asignado: materias con al menos un MateriaLaboratorioDB
    - n_lab_fijo: subset con horas_laboratorio > 0 (entran al LP)
    - n_lab_reserva: subset con horas_laboratorio == 0 (reserva ad-hoc)
    - n_lab_pendiente: subset con horas_laboratorio is None (sin definir)
    """
    if not materia_codigos:
        return (0, 0, 0, 0)

    # Materias con lab asignado
    con_lab_rows = session.exec(
        select(MateriaLaboratorioDB.materia_codigo)
        .where(col(MateriaLaboratorioDB.materia_codigo).in_(materia_codigos))
        .distinct()
    ).all()
    con_lab_set = set(con_lab_rows)

    if not con_lab_set:
        return (0, 0, 0, 0)

    # Para esas materias, leer horas_laboratorio
    mats = session.exec(
        select(MateriaDB.codigo, MateriaDB.horas_laboratorio)
        .where(col(MateriaDB.codigo).in_(list(con_lab_set)))
    ).all()

    n_lab_fijo = 0
    n_lab_reserva = 0
    n_lab_pendiente = 0
    for _cod, hl in mats:
        if hl is None:
            n_lab_pendiente += 1
        elif hl > 0:
            n_lab_fijo += 1
        else:  # hl == 0
            n_lab_reserva += 1

    return (len(con_lab_set), n_lab_fijo, n_lab_reserva, n_lab_pendiente)


# =============================================================================
# Validacion principal
# =============================================================================

def validar_cronograma(
    session: Session, schedule_id: str, ciclo_id: str,
    exclude_optativas: bool = False,
) -> CronogramaValidationSummary:
    """Computa el resumen completo de validacion de un cronograma vs un ciclo.

    Args:
        exclude_optativas: si True, el set de "esperadas" descarta materias
            optativas del computo de cobertura/faltantes/extras. Las
            virtuales SI cuentan (no necesitan aula pero estructuralmente
            deben ser consistentes). Es config de la validacion: cambiar
            el toggle invalida el snapshot.

    No persiste el resultado (usar `persist_validation()` para eso).
    """
    summary = CronogramaValidationSummary(
        schedule_id=schedule_id, ciclo_id=ciclo_id,
        excluir_optativas=exclude_optativas,
        excluir_virtuales_optativas=exclude_optativas,  # legacy mirror
    )

    # Pre-check: el ciclo debe tener dictados creados. Sin esto la prevalidacion
    # no tiene contra que comparar las materias del cronograma.
    if not has_dictados_for_ciclo(session, ciclo_id):
        summary.error = (
            "Este ciclo no tiene dictados creados. "
            "Ir a Ciclos → 📚 Dictados y apretar 'Crear Dictados' antes de prevalidar."
        )
        return summary

    summary.dictado_count_at_validation = count_active_dictados_for_ciclo(
        session, ciclo_id,
    )

    # Entries del schedule
    entries = list(session.exec(
        select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == schedule_id)
    ).all())

    summary.entry_count_at_validation = len(entries)
    summary.n_clases = len(entries)

    # Materias presentes
    materias_en_sched = {e.codigo_materia for e in entries}
    summary.n_materias = len(materias_en_sched)

    # Total horas
    total_horas = 0.0
    for e in entries:
        mins = (
            e.hora_fin.hour * 60 + e.hora_fin.minute
            - e.hora_inicio.hour * 60 - e.hora_inicio.minute
        )
        total_horas += max(0, mins) / 60
    summary.total_horas = total_horas

    # Materia name map (para mostrar en extras)
    if materias_en_sched:
        mat_rows = session.exec(
            select(MateriaDB.codigo, MateriaDB.nombre)
            .where(col(MateriaDB.codigo).in_(list(materias_en_sched)))
        ).all()
        summary.mat_map = {cod: nombre for cod, nombre in mat_rows}

    # Cobertura — esperadas = dictados ACTIVOS linkeados al ciclo.
    esperadas = get_materias_esperadas_from_dictados(session, ciclo_id)
    if exclude_optativas and esperadas:
        # Filtro: descartar SOLO materias optativas. Las virtuales se
        # mantienen porque sus horarios y comisiones tambien deben ser
        # consistentes (pero no van a precisar aula al asignar).
        _esp_codes = list(esperadas.keys())
        from src.database.models import PlanEstudioDB as _PE
        _opt_rows = list(session.exec(
            select(_PE.materia_codigo)
            .where(col(_PE.materia_codigo).in_(_esp_codes))
            .where(_PE.optativa == True)  # noqa: E712
            .distinct()
        ).all())
        _optativas = set(_opt_rows)
        esperadas = {
            mc: nom for mc, nom in esperadas.items()
            if mc not in _optativas
        }
    summary.esperadas = esperadas
    cubiertas = materias_en_sched & set(esperadas.keys())
    faltantes_set = set(esperadas.keys()) - materias_en_sched
    extra_set = materias_en_sched - set(esperadas.keys())

    summary.n_esperadas = len(esperadas)
    summary.n_cubiertas = len(cubiertas)
    summary.n_faltantes = len(faltantes_set)
    summary.n_extra = len(extra_set)

    # Faltantes por carrera (detalle) — usa el dictado_codigo en la razon.
    dictado_codigos = get_dictado_codigos_for_ciclo(
        session, ciclo_id, only_active=True,
    )
    summary.faltantes_por_carrera = _get_faltantes_por_carrera(
        session, ciclo_id, esperadas, materias_en_sched, dictado_codigos,
    )

    # Extras (detalle)
    summary.extras = [
        {"codigo": cod, "nombre": summary.mat_map.get(cod, "?")}
        for cod in sorted(extra_set)
    ]

    # Lab breakdown
    (
        summary.n_con_lab_asignado,
        summary.n_lab_fijo,
        summary.n_lab_reserva,
        summary.n_lab_pendiente,
    ) = _compute_lab_breakdown(session, list(materias_en_sched))

    # Particion teoria/lab
    part_result = validar_factibilidad_particion_horas(
        session, schedule_id=schedule_id,
    )
    summary.particion_valid = part_result.valid
    summary.particion_message = part_result.message
    summary.particion_details = list(part_result.details or [])
    summary.particion_n_infactibles = (
        len(summary.particion_details) if not part_result.valid else 0
    )

    # Conflictos de horarios (con comisiones auto-derivadas del cronograma)
    conflictos = validar_conflictos_horarios_cronograma(
        session, schedule_id, ciclo_id,
    )
    summary.n_conflictos_horarios = len(conflictos)
    summary.conflictos_horarios = [
        {
            "carrera_codigo": c.carrera_codigo,
            "anio_plan": c.anio_plan,
            "cuatrimestre_plan": c.cuatrimestre_plan,
            "materia_a": c.materia_a,
            "materia_b": c.materia_b,
            "dia": c.dia,
            "hora_inicio_a": c.hora_inicio_a,
            "hora_fin_a": c.hora_fin_a,
            "hora_inicio_b": c.hora_inicio_b,
            "hora_fin_b": c.hora_fin_b,
        }
        for c in conflictos
    ]

    return summary


# =============================================================================
# Persistencia
# =============================================================================

def persist_validation(
    session: Session, summary: CronogramaValidationSummary,
) -> ScheduleValidationDB:
    """Inserta un nuevo `ScheduleValidationDB` con los datos del summary."""
    record = ScheduleValidationDB(
        schedule_id=summary.schedule_id,
        ciclo_id=summary.ciclo_id,
        validated_at=summary.validated_at,
        entry_count_at_validation=summary.entry_count_at_validation,
        dictado_count_at_validation=summary.dictado_count_at_validation,
        n_materias=summary.n_materias,
        n_clases=summary.n_clases,
        total_horas=summary.total_horas,
        n_esperadas=summary.n_esperadas,
        n_cubiertas=summary.n_cubiertas,
        n_faltantes=summary.n_faltantes,
        n_extra=summary.n_extra,
        n_con_lab_asignado=summary.n_con_lab_asignado,
        n_lab_fijo=summary.n_lab_fijo,
        n_lab_reserva=summary.n_lab_reserva,
        n_lab_pendiente=summary.n_lab_pendiente,
        particion_valid=summary.particion_valid,
        particion_n_infactibles=summary.particion_n_infactibles,
        n_conflictos_horarios=summary.n_conflictos_horarios,
        excluir_optativas=summary.excluir_optativas,
        excluir_virtuales_optativas=summary.excluir_virtuales_optativas,
        details_json=summary.to_details_json(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_latest_validation(
    session: Session, schedule_id: str, ciclo_id: Optional[str] = None,
) -> Optional[ScheduleValidationDB]:
    """Devuelve la validacion mas reciente para un schedule (opcionalmente acotada por ciclo)."""
    stmt = (
        select(ScheduleValidationDB)
        .where(ScheduleValidationDB.schedule_id == schedule_id)
    )
    if ciclo_id:
        stmt = stmt.where(ScheduleValidationDB.ciclo_id == ciclo_id)
    stmt = stmt.order_by(ScheduleValidationDB.validated_at.desc()).limit(1)  # type: ignore[attr-defined]
    return session.exec(stmt).first()


def get_validation_history(
    session: Session, schedule_id: str, ciclo_id: Optional[str] = None,
    limit: int = 50,
) -> list[ScheduleValidationDB]:
    """Devuelve el historial de validaciones (mas reciente primero)."""
    stmt = (
        select(ScheduleValidationDB)
        .where(ScheduleValidationDB.schedule_id == schedule_id)
    )
    if ciclo_id:
        stmt = stmt.where(ScheduleValidationDB.ciclo_id == ciclo_id)
    stmt = stmt.order_by(ScheduleValidationDB.validated_at.desc()).limit(limit)  # type: ignore[attr-defined]
    return list(session.exec(stmt).all())


def is_validation_stale(
    session: Session, validation: ScheduleValidationDB,
) -> bool:
    """True si cambio el cronograma O el set de dictados activos del ciclo
    desde que se persistio la validacion.
    """
    current_entries = session.exec(
        select(func.count(ScheduleEntryDB.id))
        .where(ScheduleEntryDB.schedule_id == validation.schedule_id)
    ).one()
    if current_entries != validation.entry_count_at_validation:
        return True

    current_dictados = count_active_dictados_for_ciclo(
        session, validation.ciclo_id,
    )
    if current_dictados != validation.dictado_count_at_validation:
        return True

    return False


def parse_details_json(details_json: str) -> dict:
    """Deserializa el details_json. Devuelve dict vacio si falla."""
    try:
        return json.loads(details_json) if details_json else {}
    except json.JSONDecodeError:
        return {}
