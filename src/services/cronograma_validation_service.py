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

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, select, col, func

from src.database.models import (
    CarreraDB,
    CicloPlanVersionDB,
    DictadoCicloDB,
    DictadoDB,
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

    # Bloqueos de camino de cursada (Fase B). Cuenta grupos
    # (carrera, año, cuatri) donde no hay combinación libre de
    # solapamientos + advertencias por cap excedido.
    n_camino_bloqueos: int = 0

    # Horarios que no respetan la config global (Fase H.1 del
    # rediseño 2026-09-15): día no operativo, fuera del rango
    # operativo, o no múltiplo de la granularidad. Detalle en
    # `details_json["horarios_fuera_config"]`.
    n_horarios_fuera_config: int = 0

    # Config aplicada (toggle "excluir optativas"). Las virtuales SI se
    # validan (estructuralmente deben ser consistentes); solo las optativas
    # se descartan del set esperado cuando el toggle esta ON.
    # `excluir_virtuales_optativas` queda como alias retro-compatible.
    excluir_optativas: bool = False
    excluir_virtuales_optativas: bool = False  # legacy

    # Hash de contenido del snapshot (Fase A). Cubre entries, dictados
    # activos, PlanEstudioDB del ciclo, MateriaLaboratorioDB, campos de
    # MateriaDB que afectan cobertura/particion, y el toggle. Se computa
    # via `compute_content_hash()` antes de persistir.
    content_hash: str = ""

    # Detalle (para reconstruir la UI sin recomputar)
    faltantes_por_carrera: list[dict] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)
    particion_details: list[str] = field(default_factory=list)
    conflictos_horarios: list[dict] = field(default_factory=list)
    camino_bloqueos: list[dict] = field(default_factory=list)
    horarios_fuera_config: list[dict] = field(default_factory=list)
    esperadas: dict[str, str] = field(default_factory=dict)
    mat_map: dict[str, str] = field(default_factory=dict)

    def to_details_json(self) -> str:
        """Serializa los campos de detalle a JSON para persistir."""
        return json.dumps({
            "faltantes_por_carrera": self.faltantes_por_carrera,
            "extras": self.extras,
            "particion_details": self.particion_details,
            "conflictos_horarios": self.conflictos_horarios,
            "camino_bloqueos": self.camino_bloqueos,
            "horarios_fuera_config": self.horarios_fuera_config,
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


def _compute_content_hash(
    session: Session, schedule_id: str, ciclo_id: str, exclude_optativas: bool,
) -> str:
    """Hash SHA-256 del contenido del cronograma + inputs del ciclo.

    Detecta cambios que la staleness por counts se pierde: mover una
    clase de lunes a martes, cambiar `PlanEstudioDB.optativa`, editar
    `MateriaLaboratorioDB`, agregar sedes admisibles, cambiar el toggle.

    Compuesto por:
    - Entries del schedule: (dia, hora_inicio, hora_fin, codigo_materia,
      comision_id, tipo_clase, virtual) ordenado deterministicamente.
    - Dictados activos del ciclo con su `virtual`.
    - `PlanEstudioDB.optativa` de cada materia (afecta el filtro
      exclude_optativas y las cuentas de faltantes por carrera).
    - `MateriaLaboratorioDB` de cada materia con lab (afecta el
      breakdown y la particion teoria/lab).
    - `MateriaDB.horas_teoria`, `horas_laboratorio`, `virtual`,
      `optativa` (afectan la particion y la clasificacion).
    - Toggle `exclude_optativas`.

    Retorna hex string SHA-256.
    """
    parts: list[str] = [f"toggle:{'1' if exclude_optativas else '0'}"]

    # Config horaria global (Fase H.1). Si cambia la granularidad,
    # los días operativos o el rango, los horarios que antes pasaban
    # la validación pueden empezar a fallar → la staleness debe
    # detectar ese cambio.
    from src.database.models import ConfiguracionHoraria
    config = session.exec(
        select(ConfiguracionHoraria).limit(1)
    ).first()
    if config is not None:
        # Bugfix (2026-09-22, task #356): normalizamos
        # `dias_operativos` antes de sumarlo al hash porque su
        # representación es un string CSV; un mismo conjunto de
        # días guardado con distinto orden o espacios extra
        # producía hashes distintos y disparaba staleness falso
        # positivo (ej. "Lunes,Martes" vs "Martes, Lunes").
        _dias_norm = ",".join(sorted({
            d.strip() for d in (config.dias_operativos or "").split(",")
            if d.strip()
        }))
        parts.append(
            f"config:{config.granularidad_minutos}"
            f"|{config.hora_inicio_operativo.isoformat()}"
            f"|{config.hora_fin_operativo.isoformat()}"
            f"|{_dias_norm}"
        )
    else:
        parts.append("config:none")

    # 1) Entries del schedule
    entries = list(session.exec(
        select(ScheduleEntryDB)
        .where(ScheduleEntryDB.schedule_id == schedule_id)
    ).all())
    entry_tuples = sorted(
        (
            e.codigo_materia or "",
            e.dia or "",
            e.hora_inicio.isoformat() if e.hora_inicio else "",
            e.hora_fin.isoformat() if e.hora_fin else "",
            e.comision_id or "",
            e.tipo_clase or "",
            "1" if e.virtual is True else ("0" if e.virtual is False else "-"),
        )
        for e in entries
    )
    parts.append("entries:" + "|".join(
        ";".join(t) for t in entry_tuples
    ))

    # 2) Dictados activos del ciclo (materia_codigo + virtual). El link
    # es M:N via DictadoCicloDB (un dictado anual atraviesa 2 ciclos).
    dictados = list(session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoCicloDB.dictado_id == DictadoDB.id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all())
    dictado_tuples = sorted(
        (
            d.materia_codigo or "",
            "1" if d.virtual is True else ("0" if d.virtual is False else "-"),
        )
        for d in dictados
    )
    parts.append("dictados:" + "|".join(
        ";".join(t) for t in dictado_tuples
    ))

    # Universo de materias relevantes: las del schedule + las esperadas
    materia_codes: set[str] = {e.codigo_materia for e in entries if e.codigo_materia}
    materia_codes.update(d.materia_codigo for d in dictados if d.materia_codigo)

    if materia_codes:
        # 3) MateriaDB (horas_teoria, horas_laboratorio, virtual, optativa)
        mat_rows = list(session.exec(
            select(MateriaDB)
            .where(col(MateriaDB.codigo).in_(list(materia_codes)))
        ).all())
        mat_tuples = sorted(
            (
                m.codigo or "",
                str(m.horas_teoria if m.horas_teoria is not None else "-"),
                str(m.horas_laboratorio if m.horas_laboratorio is not None else "-"),
                "1" if m.virtual else "0",
                "1" if m.optativa else "0",
            )
            for m in mat_rows
        )
        parts.append("materias:" + "|".join(
            ";".join(t) for t in mat_tuples
        ))

        # 4) PlanEstudioDB.optativa por (materia, plan_version)
        pe_rows = list(session.exec(
            select(PlanEstudioDB)
            .where(col(PlanEstudioDB.materia_codigo).in_(list(materia_codes)))
        ).all())
        pe_tuples = sorted(
            (
                pe.materia_codigo or "",
                pe.plan_version_id or "",
                str(pe.anio_plan if pe.anio_plan is not None else "-"),
                pe.cuatrimestre_plan or "",
                "1" if pe.optativa else "0",
            )
            for pe in pe_rows
        )
        parts.append("plan_estudio:" + "|".join(
            ";".join(t) for t in pe_tuples
        ))

        # 5) MateriaLaboratorioDB (afecta breakdown y particion)
        lab_rows = list(session.exec(
            select(MateriaLaboratorioDB)
            .where(col(MateriaLaboratorioDB.materia_codigo).in_(list(materia_codes)))
        ).all())
        lab_tuples = sorted(
            (ml.materia_codigo or "", ml.aula_id or "")
            for ml in lab_rows
        )
        parts.append("labs:" + "|".join(
            ";".join(t) for t in lab_tuples
        ))

    payload = "\n".join(parts).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
    # Si exclude_optativas=True, las optativas salen tanto del set
    # esperado como del set de extras (simetria: el toggle dice "no me
    # importan las optativas", aplica a ambos lados).
    esperadas = get_materias_esperadas_from_dictados(session, ciclo_id)
    optativas_excluidas: set[str] = set()
    if exclude_optativas:
        from src.database.models import PlanEstudioDB as _PE
        _univ = list(set(esperadas.keys()) | materias_en_sched)
        if _univ:
            _opt_rows = list(session.exec(
                select(_PE.materia_codigo)
                .where(col(_PE.materia_codigo).in_(_univ))
                .where(_PE.optativa == True)  # noqa: E712
                .distinct()
            ).all())
            optativas_excluidas = set(_opt_rows)
        if optativas_excluidas:
            esperadas = {
                mc: nom for mc, nom in esperadas.items()
                if mc not in optativas_excluidas
            }
    summary.esperadas = esperadas

    materias_en_sched_filt = materias_en_sched - optativas_excluidas
    cubiertas = materias_en_sched_filt & set(esperadas.keys())
    faltantes_set = set(esperadas.keys()) - materias_en_sched_filt
    extra_set = materias_en_sched_filt - set(esperadas.keys())

    summary.n_esperadas = len(esperadas)
    summary.n_cubiertas = len(cubiertas)
    summary.n_faltantes = len(faltantes_set)
    summary.n_extra = len(extra_set)

    # Faltantes por carrera (detalle) — usa el dictado_codigo en la razon.
    dictado_codigos = get_dictado_codigos_for_ciclo(
        session, ciclo_id,
    )
    summary.faltantes_por_carrera = _get_faltantes_por_carrera(
        session, ciclo_id, esperadas, materias_en_sched_filt, dictado_codigos,
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

    # Camino de cursada (Fase B). Detecta grupos (carrera, año, cuatri)
    # donde ninguna combinación de comisiones evita solapamientos entre
    # materias obligatorias. Antes ese chequeo sólo se ejecutaba al
    # generar el plan, así que las inconsistencias del cronograma no
    # eran visibles hasta ese momento.
    from src.services.factibilidad_service import check_camino_cursada_cronograma
    bloqueos_camino = check_camino_cursada_cronograma(
        session, schedule_id, ciclo_id,
    )
    summary.n_camino_bloqueos = len(bloqueos_camino)
    summary.camino_bloqueos = [
        {
            "codigo_regla": b.codigo_regla,
            "severidad": b.severidad,
            "titulo": b.titulo,
            "detalle": b.detalle,
            "entidades_a_revisar": list(b.entidades_a_revisar or []),
            "contexto": dict(b.contexto or {}),
        }
        for b in bloqueos_camino
    ]

    # Horarios fuera de config (Fase H.1): entries que no respetan
    # `ConfiguracionHoraria` (día, rango operativo, granularidad).
    # Warning, no bloqueante — el cronograma puede convivir con
    # horarios rotos hasta que el usuario los corrija.
    from src.services.validations import validar_horarios_vs_config
    fuera_config = validar_horarios_vs_config(session, schedule_id)
    summary.n_horarios_fuera_config = len(fuera_config)
    summary.horarios_fuera_config = [
        {
            "entry_id": h.entry_id,
            "codigo_materia": h.codigo_materia,
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "razones": list(h.razones),
        }
        for h in fuera_config
    ]

    # Hash de contenido — Fase A. Se computa al final para que refleje
    # exactamente el estado que dio origen al summary.
    summary.content_hash = _compute_content_hash(
        session, schedule_id, ciclo_id, exclude_optativas,
    )

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
        n_camino_bloqueos=summary.n_camino_bloqueos,
        n_horarios_fuera_config=summary.n_horarios_fuera_config,
        excluir_optativas=summary.excluir_optativas,
        excluir_virtuales_optativas=summary.excluir_virtuales_optativas,
        content_hash=summary.content_hash,
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
    """True si el contenido relevante cambio desde que se persistio la validacion.

    Estrategia (Fase A del rediseño 2026-09-15):
    - Si el snapshot tiene `content_hash` no vacio, se recomputa el hash
      del estado actual con la misma config del toggle y se compara. Esto
      detecta cambios que la comparacion por counts se pierde (mover una
      clase de dia con mismo count, editar `PlanEstudioDB.optativa`, etc).
    - Si el snapshot es historico (`content_hash == ""`), se cae al
      comportamiento previo: comparar `entry_count` y `dictado_count`.
      Esto preserva la semantica de snapshots viejos hasta que el usuario
      corra una validacion nueva.
    """
    if validation.content_hash:
        current_hash = _compute_content_hash(
            session,
            validation.schedule_id,
            validation.ciclo_id,
            validation.excluir_optativas,
        )
        return current_hash != validation.content_hash

    # Fallback backward-compat: snapshots sin hash usan comparacion de counts.
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


# =============================================================================
# Politica unificada: badge de estado y "listo para plan"
# =============================================================================

@dataclass
class ValidationStatus:
    """Estado consolidado de la ultima validacion de un cronograma.

    Unifica la lectura de badge y la politica de "listo para generar plan".
    Antes cada consumidor computaba su propia version — el badge en la
    Lista de Cronogramas ignoraba `n_conflictos_horarios` y `n_extra`, y
    el wizard del Plan ignoraba todo excepto staleness. Ahora hay una
    fuente unica.

    Campos:
    - `validation`: el ScheduleValidationDB mas reciente (None si nunca).
    - `stale`: si el contenido cambio desde que se persistio.
    - `problemas`: lista de mensajes cortos de problemas detectados
      (faltantes, particion, conflictos, extras, error de pre-check).
    - `listo_para_plan`: True solo si no hay problemas y no esta stale.
    - `badge`: string con emoji + descripcion resumida para la UI.
    """
    validation: Optional[ScheduleValidationDB]
    stale: bool
    problemas: list[str]
    listo_para_plan: bool
    badge: str


def _describir_problemas(val: ScheduleValidationDB) -> list[str]:
    """Enumera problemas concretos de una validacion.

    Un cronograma es "listo para plan" solo si esta lista esta vacia
    (y ademas el snapshot no esta stale). Se contempla:
    - Pre-check fallado (no hay dictados en el ciclo).
    - Materias faltantes vs dictados esperados.
    - Particion teoria/lab infactible.
    - Conflictos de horario intra-grupo.
    - Materias extras (no tienen dictado en el ciclo).
    - Bloqueos de camino de cursada (Fase B).
    """
    problemas: list[str] = []

    # Nota: el snapshot no persiste el `error` de pre-check literal, pero
    # si el pre-check falla el summary no se persiste (early return en
    # validar_cronograma). Aca alcanza con las metricas del snapshot.

    if val.n_faltantes > 0:
        problemas.append(f"{val.n_faltantes} materias faltantes")
    if not val.particion_valid:
        problemas.append(
            f"{val.particion_n_infactibles} particiones teoria/lab sin cupo"
        )
    if val.n_conflictos_horarios > 0:
        problemas.append(
            f"{val.n_conflictos_horarios} conflictos de horario intra-grupo"
        )
    if val.n_extra > 0:
        problemas.append(
            f"{val.n_extra} materias sin dictado en el ciclo"
        )
    if val.n_camino_bloqueos > 0:
        problemas.append(
            f"{val.n_camino_bloqueos} bloqueos de camino de cursada"
        )
    # Bugfix (2026-09-22, task #342): `n_horarios_fuera_config` NO se
    # incluye acá porque, por decisión de la Fase H.1 del rediseño
    # 2026-09-21, es un *warning* (no bloqueante) del cronograma. La
    # UI lo sigue mostrando en la sección de config horaria con su
    # propio botón "Ajustar automáticamente"; pero no debe impedir
    # que `listo_para_plan` sea True. Antes esto contradecía la doc.

    return problemas


def compute_validation_status(
    session: Session,
    schedule_id: str,
    ciclo_id: Optional[str] = None,
) -> ValidationStatus:
    """Devuelve el estado consolidado de la ultima validacion.

    Consumido tanto por la Lista de Cronogramas como por el wizard del
    Plan. Reemplaza la logica inline que existia en ambos lugares
    (ver docstring de `ValidationStatus`).
    """
    val = get_latest_validation(session, schedule_id, ciclo_id)

    if val is None:
        return ValidationStatus(
            validation=None,
            stale=False,
            problemas=[],
            listo_para_plan=False,
            badge="⚪ sin validar",
        )

    stale = is_validation_stale(session, val)
    problemas = _describir_problemas(val)

    ciclo_lbl = val.ciclo_id
    if stale:
        listo = False
        badge = f"🟡 validado vs {ciclo_lbl}, con cambios posteriores"
    elif problemas:
        listo = False
        badge = (
            f"🔴 con problemas vs {ciclo_lbl} "
            f"({', '.join(problemas)})"
        )
    else:
        listo = True
        badge = f"🟢 validado vs {ciclo_lbl}"

    return ValidationStatus(
        validation=val,
        stale=stale,
        problemas=problemas,
        listo_para_plan=listo,
        badge=badge,
    )


def esta_listo_para_plan(
    session: Session, schedule_id: str, ciclo_id: Optional[str] = None,
) -> bool:
    """Shortcut booleano de `compute_validation_status(...).listo_para_plan`."""
    return compute_validation_status(session, schedule_id, ciclo_id).listo_para_plan


def parse_details_json(details_json: str) -> dict:
    """Deserializa el details_json. Devuelve dict vacio si falla."""
    try:
        return json.loads(details_json) if details_json else {}
    except json.JSONDecodeError:
        return {}
