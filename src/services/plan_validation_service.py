"""Service para validar planes de cursada.

Espejo de `cronograma_validation_service` pero opera sobre
`PlanificacionCursadaDB` y sus comisiones reales (no auto-derivadas).

Adicionales sobre el cronograma:
- Soporta `IgnoredConflictDB` (pares de materias cuyo conflicto el usuario
  decidio ignorar manualmente).
- Snapshot persistido en `PlanValidationDB` para auditoria + staleness.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from sqlmodel import Session, col, func, select

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    ComisionDB,
    HorarioDB,
    IgnoredConflictDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    PlanificacionCursadaDB,
    PlanValidationDB,
)
from src.services.dictado_service import (
    count_active_dictados_for_ciclo,
    get_dictado_codigos_for_ciclo,
    get_materias_esperadas_from_dictados,
    has_dictados_for_ciclo,
)
from src.services.validations import (
    ConflictoHorario,
    validar_conflictos_horarios_plan_estructurados,
    validar_factibilidad_particion_horas,
)


# =============================================================================
# Resumen
# =============================================================================

@dataclass
class PlanValidationSummary:
    plan_cursada_id: str
    validated_at: datetime = field(default_factory=datetime.utcnow)

    # Snapshots para staleness
    comision_count_at_validation: int = 0
    horario_count_at_validation: int = 0
    dictado_count_at_validation: int = 0

    # Config aplicada
    excluir_virtuales_optativas: bool = False

    # Error pre-computo (ej. plan sin comisiones, ciclo sin dictados)
    error: Optional[str] = None

    # Resumen general
    n_materias: int = 0
    n_clases: int = 0
    total_horas: float = 0.0

    # Cobertura
    n_esperadas: int = 0
    n_cubiertas: int = 0
    n_faltantes: int = 0
    n_extra: int = 0

    # Particion teoria/lab
    particion_valid: bool = True
    particion_n_infactibles: int = 0
    particion_message: str = ""

    # Conflictos
    n_conflictos_horarios: int = 0
    n_conflictos_ignorados: int = 0

    # Detalle (para reconstruccion sin recomputar)
    faltantes_por_carrera: list[dict] = field(default_factory=list)
    extras: list[dict] = field(default_factory=list)
    particion_details: list[str] = field(default_factory=list)
    conflictos_horarios: list[dict] = field(default_factory=list)
    conflictos_ignorados: list[dict] = field(default_factory=list)
    esperadas: dict[str, str] = field(default_factory=dict)
    mat_map: dict[str, str] = field(default_factory=dict)

    def to_details_json(self) -> str:
        return json.dumps({
            "faltantes_por_carrera": self.faltantes_por_carrera,
            "extras": self.extras,
            "particion_details": self.particion_details,
            "conflictos_horarios": self.conflictos_horarios,
            "conflictos_ignorados": self.conflictos_ignorados,
            "esperadas": self.esperadas,
            "mat_map": self.mat_map,
            "particion_message": self.particion_message,
        })


# =============================================================================
# Helpers
# =============================================================================

def _faltantes_por_carrera(
    session: Session,
    plan: PlanificacionCursadaDB,
    esperadas: dict[str, str],
    materias_en_plan: set[str],
    dictado_codigos: dict[str, str],
) -> list[dict]:
    """Espejo de cronograma_validation_service._get_faltantes_por_carrera
    pero sobre el plan: faltantes = materias esperadas (con dictado activo)
    que NO tienen comisiones en el plan.
    """
    if not plan.ciclo_id:
        return []

    faltantes_set = set(esperadas.keys()) - materias_en_plan
    if not faltantes_set:
        return []

    cpv_rows = list(session.exec(
        select(CicloPlanVersionDB)
        .where(CicloPlanVersionDB.ciclo_id == plan.ciclo_id)
    ).all())

    result = []
    for cpv in cpv_rows:
        pv = session.get(PlanCarreraVersionDB, cpv.plan_version_id)
        if not pv:
            continue
        carrera = session.get(CarreraDB, pv.carrera_codigo)
        if not carrera:
            continue

        pe_rows = list(session.exec(
            select(PlanEstudioDB)
            .where(PlanEstudioDB.plan_version_id == pv.id)
            .order_by(PlanEstudioDB.anio_plan, PlanEstudioDB.cuatrimestre_plan)
        ).all())

        faltantes_pe = [pe for pe in pe_rows if pe.materia_codigo in faltantes_set]
        if not faltantes_pe:
            continue

        falt_codigos = list({pe.materia_codigo for pe in faltantes_pe})
        mats_db = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(falt_codigos))
        ).all())
        mat_map = {m.codigo: m for m in mats_db}

        materias_faltantes = []
        for pe in faltantes_pe:
            mat = mat_map.get(pe.materia_codigo)
            if not mat:
                continue
            dic_cod = dictado_codigos.get(mat.codigo, "?")
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
                "razon": (
                    f"Dictado activo {dic_cod} sin comisiones en el plan"
                ),
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


def _extras_por_carrera(
    session: Session,
    plan: PlanificacionCursadaDB,
    extra_set: set[str],
    mat_map: dict[str, str],
) -> list[dict]:
    """Materias en el plan (con comisiones) pero sin dictado activo en ciclo."""
    if not extra_set or not plan.ciclo_id:
        return []

    _ext_mats = list(session.exec(
        select(MateriaDB).where(col(MateriaDB.codigo).in_(list(extra_set)))
    ).all())
    _ext_mat_map = {m.codigo: m for m in _ext_mats}

    _ext_pe = list(session.exec(
        select(PlanEstudioDB)
        .join(PlanCarreraVersionDB,
              PlanEstudioDB.plan_version_id == PlanCarreraVersionDB.id)
        .join(CicloPlanVersionDB,
              PlanCarreraVersionDB.id == CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == plan.ciclo_id)
        .where(col(PlanEstudioDB.materia_codigo).in_(list(extra_set)))
    ).all())

    _by_carr: dict[str, list[dict]] = {}
    _seen: set[tuple[str, str]] = set()
    for _pe in _ext_pe:
        _key = (_pe.carrera_codigo, _pe.materia_codigo)
        if _key in _seen:
            continue
        _seen.add(_key)
        _m_obj = _ext_mat_map.get(_pe.materia_codigo)
        _by_carr.setdefault(_pe.carrera_codigo, []).append({
            "codigo": _pe.materia_codigo,
            "nombre": _m_obj.nombre if _m_obj else "?",
            "anio_plan": _pe.anio_plan,
            "cuatrimestre_plan": _pe.cuatrimestre_plan,
            "optativa": bool(_pe.optativa),
            "virtual": bool(_m_obj.virtual) if _m_obj else False,
            "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
        })

    _no_plan_extras = set(extra_set) - {
        m["codigo"] for ms in _by_carr.values() for m in ms
    }

    result: list[dict] = []
    for _cc, _mlist in _by_carr.items():
        _carr = session.get(CarreraDB, _cc)
        result.append({
            "carrera_codigo": _cc,
            "carrera_nombre": _carr.nombre if _carr else _cc,
            "materias": _mlist,
        })

    if _no_plan_extras:
        _np_list = []
        for _mc in sorted(_no_plan_extras):
            _m_obj = _ext_mat_map.get(_mc)
            _np_list.append({
                "codigo": _mc,
                "nombre": _m_obj.nombre if _m_obj else "?",
                "anio_plan": None,
                "cuatrimestre_plan": None,
                "optativa": False,
                "virtual": bool(_m_obj.virtual) if _m_obj else False,
                "periodo": _m_obj.periodo if _m_obj else "cuatrimestral",
            })
        result.append({
            "carrera_codigo": "—",
            "carrera_nombre": "Sin carrera asignada",
            "materias": _np_list,
        })
    result.sort(key=lambda x: x["carrera_codigo"])
    return result


# =============================================================================
# Validacion principal
# =============================================================================

def validar_plan(
    session: Session, plan_id: str, exclude_virt_opt: bool = False,
) -> PlanValidationSummary:
    """Computa el resumen completo de validacion de un plan."""
    summary = PlanValidationSummary(
        plan_cursada_id=plan_id,
        excluir_virtuales_optativas=exclude_virt_opt,
    )

    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        summary.error = f"Plan '{plan_id}' no encontrado."
        return summary

    if not plan.ciclo_id:
        summary.error = "El plan no tiene ciclo asignado."
        return summary

    if not has_dictados_for_ciclo(session, plan.ciclo_id):
        summary.error = (
            "El ciclo del plan no tiene dictados creados. "
            "Ir a Ciclos → 📚 Dictados."
        )
        return summary

    summary.dictado_count_at_validation = count_active_dictados_for_ciclo(
        session, plan.ciclo_id,
    )

    # Snapshot: comisiones + horarios del plan
    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    summary.comision_count_at_validation = len(comisiones)
    if not comisiones:
        summary.error = (
            "El plan no tiene comisiones. Cargar comisiones desde el editor."
        )
        return summary

    com_ids = [c.id for c in comisiones]
    horarios = list(session.exec(
        select(HorarioDB).where(col(HorarioDB.comision_id).in_(com_ids))
    ).all())
    summary.horario_count_at_validation = len(horarios)
    summary.n_clases = len(horarios)

    # Total horas (suma de duraciones de todos los horarios)
    total_h = 0.0
    for h in horarios:
        mins = (
            h.hora_fin.hour * 60 + h.hora_fin.minute
            - h.hora_inicio.hour * 60 - h.hora_inicio.minute
        )
        total_h += max(0, mins) / 60
    summary.total_horas = total_h

    # Materias del plan
    materias_en_plan = {c.materia_codigo for c in comisiones}
    summary.n_materias = len(materias_en_plan)

    if materias_en_plan:
        mat_rows = list(session.exec(
            select(MateriaDB.codigo, MateriaDB.nombre)
            .where(col(MateriaDB.codigo).in_(list(materias_en_plan)))
        ).all())
        summary.mat_map = {cod: nombre for cod, nombre in mat_rows}

    # Cobertura — esperadas = dictados activos del ciclo (con filtro virt/opt)
    esperadas = get_materias_esperadas_from_dictados(session, plan.ciclo_id)
    if exclude_virt_opt and esperadas:
        _esp_codes = list(esperadas.keys())
        _mats_full = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(_esp_codes))
        ).all())
        _virtuales = {m.codigo for m in _mats_full if m.virtual}
        _opt_rows = list(session.exec(
            select(PlanEstudioDB.materia_codigo)
            .where(col(PlanEstudioDB.materia_codigo).in_(_esp_codes))
            .where(PlanEstudioDB.optativa == True)  # noqa: E712
            .distinct()
        ).all())
        _optativas = set(_opt_rows)
        _excluir = _virtuales | _optativas
        esperadas = {
            mc: nom for mc, nom in esperadas.items()
            if mc not in _excluir
        }
    summary.esperadas = esperadas

    cubiertas = materias_en_plan & set(esperadas.keys())
    faltantes_set = set(esperadas.keys()) - materias_en_plan
    extra_set = materias_en_plan - set(esperadas.keys())

    summary.n_esperadas = len(esperadas)
    summary.n_cubiertas = len(cubiertas)
    summary.n_faltantes = len(faltantes_set)
    summary.n_extra = len(extra_set)

    # Detalle faltantes/extras por carrera
    dictado_codigos = get_dictado_codigos_for_ciclo(
        session, plan.ciclo_id, only_active=True,
    )
    summary.faltantes_por_carrera = _faltantes_por_carrera(
        session, plan, esperadas, materias_en_plan, dictado_codigos,
    )
    summary.extras = [
        {"codigo": cod, "nombre": summary.mat_map.get(cod, "?")}
        for cod in sorted(extra_set)
    ]
    # Tambien armamos extras_por_carrera-style para la UI unificada
    summary.conflictos_ignorados = []  # se llena despues

    # Particion teoria/lab
    part_result = validar_factibilidad_particion_horas(
        session, plan_cursada_id=plan_id,
    )
    summary.particion_valid = part_result.valid
    summary.particion_message = part_result.message
    summary.particion_details = list(part_result.details or [])
    summary.particion_n_infactibles = (
        len(summary.particion_details) if not part_result.valid else 0
    )

    # Conflictos de horarios (con ignorados aplicados)
    ignored_pairs = get_ignored_pairs(session, plan_id)
    conflictos = validar_conflictos_horarios_plan_estructurados(
        session, plan_id, ignored_pairs=ignored_pairs,
    )
    summary.n_conflictos_horarios = len(conflictos)
    summary.conflictos_horarios = [_conflicto_to_dict(c) for c in conflictos]

    # Recolectar tambien los conflictos ignorados (para listarlos en UI)
    if ignored_pairs:
        all_conflicts = validar_conflictos_horarios_plan_estructurados(
            session, plan_id, ignored_pairs=set(),
        )
        ignored_list = [
            c for c in all_conflicts
            if (c.materia_a, c.materia_b) in ignored_pairs
            or (c.materia_b, c.materia_a) in ignored_pairs
        ]
        summary.conflictos_ignorados = [_conflicto_to_dict(c) for c in ignored_list]
        summary.n_conflictos_ignorados = len(ignored_pairs)

    return summary


def _conflicto_to_dict(c: ConflictoHorario) -> dict:
    return {
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


# =============================================================================
# Persistencia
# =============================================================================

def persist_validation(
    session: Session, summary: PlanValidationSummary,
) -> PlanValidationDB:
    record = PlanValidationDB(
        plan_cursada_id=summary.plan_cursada_id,
        validated_at=summary.validated_at,
        comision_count_at_validation=summary.comision_count_at_validation,
        horario_count_at_validation=summary.horario_count_at_validation,
        dictado_count_at_validation=summary.dictado_count_at_validation,
        excluir_virtuales_optativas=summary.excluir_virtuales_optativas,
        n_materias=summary.n_materias,
        n_clases=summary.n_clases,
        total_horas=summary.total_horas,
        n_esperadas=summary.n_esperadas,
        n_cubiertas=summary.n_cubiertas,
        n_faltantes=summary.n_faltantes,
        n_extra=summary.n_extra,
        particion_valid=summary.particion_valid,
        particion_n_infactibles=summary.particion_n_infactibles,
        n_conflictos_horarios=summary.n_conflictos_horarios,
        n_conflictos_ignorados=summary.n_conflictos_ignorados,
        details_json=summary.to_details_json(),
    )
    session.add(record)
    session.commit()
    session.refresh(record)
    return record


def get_latest_validation(
    session: Session, plan_id: str,
) -> Optional[PlanValidationDB]:
    stmt = (
        select(PlanValidationDB)
        .where(PlanValidationDB.plan_cursada_id == plan_id)
        .order_by(PlanValidationDB.validated_at.desc())  # type: ignore[attr-defined]
        .limit(1)
    )
    return session.exec(stmt).first()


def is_validation_stale(
    session: Session, validation: PlanValidationDB,
    current_exclude_virt_opt: Optional[bool] = None,
) -> bool:
    """True si el plan, sus dictados o el toggle aplicado cambiaron desde
    que se persistio la validacion.

    Args:
        current_exclude_virt_opt: si se provee, compara contra el toggle
            persistido. None = ignorar este check.
    """
    plan = session.get(PlanificacionCursadaDB, validation.plan_cursada_id)
    if plan is None:
        return True

    n_com = session.exec(
        select(func.count(ComisionDB.id))
        .where(ComisionDB.plan_cursada_id == validation.plan_cursada_id)
    ).one()
    if n_com != validation.comision_count_at_validation:
        return True

    com_ids_subq = select(ComisionDB.id).where(
        ComisionDB.plan_cursada_id == validation.plan_cursada_id
    )
    n_h = session.exec(
        select(func.count(HorarioDB.id))
        .where(col(HorarioDB.comision_id).in_(com_ids_subq))
    ).one()
    if n_h != validation.horario_count_at_validation:
        return True

    if plan.ciclo_id:
        n_dict = count_active_dictados_for_ciclo(session, plan.ciclo_id)
        if n_dict != validation.dictado_count_at_validation:
            return True

    if (
        current_exclude_virt_opt is not None
        and current_exclude_virt_opt != validation.excluir_virtuales_optativas
    ):
        return True

    return False


def parse_details_json(details_json: str) -> dict:
    try:
        return json.loads(details_json) if details_json else {}
    except json.JSONDecodeError:
        return {}


# =============================================================================
# Conflictos ignorados
# =============================================================================

def get_ignored_pairs(
    session: Session, plan_id: str,
) -> set[tuple[str, str]]:
    """Devuelve set de tuplas (materia_a, materia_b) ordenadas
    lexicograficamente para el plan."""
    rows = list(session.exec(
        select(IgnoredConflictDB)
        .where(IgnoredConflictDB.plan_cursada_id == plan_id)
    ).all())
    return {(r.materia_a, r.materia_b) for r in rows}


def add_ignored_pair(
    session: Session, plan_id: str, mat_a: str, mat_b: str, razon: str = "",
) -> IgnoredConflictDB:
    """Agrega un par ignorado. mat_a y mat_b se ordenan lexicograficamente."""
    a, b = (mat_a, mat_b) if mat_a < mat_b else (mat_b, mat_a)
    existing = session.get(IgnoredConflictDB, (plan_id, a, b))
    if existing is not None:
        if razon and razon != existing.razon:
            existing.razon = razon
            session.add(existing)
            session.commit()
            session.refresh(existing)
        return existing
    rec = IgnoredConflictDB(
        plan_cursada_id=plan_id,
        materia_a=a, materia_b=b, razon=razon,
    )
    session.add(rec)
    session.commit()
    session.refresh(rec)
    return rec


def remove_ignored_pair(
    session: Session, plan_id: str, mat_a: str, mat_b: str,
) -> bool:
    """Elimina un par ignorado. True si existia."""
    a, b = (mat_a, mat_b) if mat_a < mat_b else (mat_b, mat_a)
    existing = session.get(IgnoredConflictDB, (plan_id, a, b))
    if existing is None:
        return False
    session.delete(existing)
    session.commit()
    return True
