"""
Validaciones de factibilidad para el sistema de asignacion de aulas.

Este modulo contiene las validaciones que aseguran que los datos cargados
son correctos y factibles para el problema de asignacion.
"""

from dataclasses import dataclass
from typing import Optional
from sqlmodel import Session, select, col
from src.database.models import (
    MateriaDB, CarreraDB, HorarioDB,
    PlanEstudioDB, ComisionDB, ClaseDB,
    CicloPlanVersionDB, PlanCarreraVersionDB,
    DictadoDB, DictadoCicloDB, PlanificacionCursadaDB,
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


@dataclass
class ConflictoHorario:
    """Conflicto de horario entre dos materias dentro de un grupo curricular.

    Estructurado para que la UI pueda agrupar por (carrera, año, cuatri) y
    mostrar tabla resumen + detalle.
    """
    carrera_codigo: str
    anio_plan: int
    cuatrimestre_plan: str  # "1C" | "2C" | "Anual"
    materia_a: str
    materia_b: str
    dia: str
    hora_inicio_a: str  # "HH:MM"
    hora_fin_a: str
    hora_inicio_b: str
    hora_fin_b: str


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
    cuatrimestre: str,
    plan_version_id: Optional[str] = None,
) -> ValidationResult:
    """
    Verifica que los horarios de las materias de una carrera/anio/cuatrimestre
    no se superpongan, permitiendo que un alumno asista a todas.
    Opcionalmente filtra por version de plan.
    """
    # Get materias for this carrera/anio/cuatrimestre
    statement = (
        select(MateriaDB)
        .join(PlanEstudioDB)
        .where(PlanEstudioDB.carrera_codigo == carrera_codigo)
        .where(PlanEstudioDB.anio_plan == anio)
        .where(PlanEstudioDB.cuatrimestre_plan == cuatrimestre)
    )
    if plan_version_id:
        statement = statement.where(PlanEstudioDB.plan_version_id == plan_version_id)

    materias = session.exec(statement).all()

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

def validar_conflictos_aula_plan(session: Session, plan_cursada_id: str) -> ValidationResult:
    """
    Verifica que no haya dos clases asignadas a la misma aula con tiempos
    superpuestos en la misma fecha dentro de un plan de cursada.
    """
    from src.database.models import PlanificacionCursadaDB

    plan = session.get(PlanificacionCursadaDB, plan_cursada_id)
    if plan is None:
        return ValidationResult(
            valid=True,
            message=f"Plan '{plan_cursada_id}' no encontrado"
        )

    # Get all clases with aula assigned
    clases = session.exec(
        select(ClaseDB)
        .where(ClaseDB.plan_cursada_id == plan_cursada_id)
        .where(ClaseDB.aula_id != None)
    ).all()

    if not clases:
        return ValidationResult(
            valid=True,
            message="No hay clases con aula asignada en este plan"
        )

    # Group by (aula_id, fecha)
    by_aula_fecha: dict[tuple[str, str], list[ClaseDB]] = {}
    for clase in clases:
        key = (clase.aula_id, str(clase.fecha))
        by_aula_fecha.setdefault(key, []).append(clase)

    conflictos = []
    for (aula_id, fecha), clases_grupo in by_aula_fecha.items():
        for i, c1 in enumerate(clases_grupo):
            for c2 in clases_grupo[i+1:]:
                # Check time overlap
                overlap = not (c1.hora_fin <= c2.hora_inicio or c2.hora_fin <= c1.hora_inicio)
                if overlap:
                    conflictos.append(
                        f"Aula {aula_id} el {fecha}: "
                        f"{c1.comision_id} ({c1.hora_inicio.strftime('%H:%M')}-{c1.hora_fin.strftime('%H:%M')}) vs "
                        f"{c2.comision_id} ({c2.hora_inicio.strftime('%H:%M')}-{c2.hora_fin.strftime('%H:%M')})"
                    )

    if conflictos:
        return ValidationResult(
            valid=False,
            message=f"{len(conflictos)} conflicto(s) de aula en plan",
            details=conflictos
        )

    return ValidationResult(
        valid=True,
        message="Sin conflictos de aula en el plan"
    )


# =============================================================================
# Validacion 4: Conflictos de horarios dentro de un plan (BLOCKER)
# =============================================================================

def _comisiones_son_compatibles(
    horarios_a: list[HorarioDB],
    horarios_b: list[HorarioDB],
) -> bool:
    """True si ningún par de horarios entre dos comisiones se superpone."""
    for h1 in horarios_a:
        for h2 in horarios_b:
            if horarios_se_superponen(h1, h2):
                return False
    return True


def validar_conflictos_horarios_plan(
    session: Session,
    plan_id: str,
) -> ValidationResult:
    """
    Verifica que no haya conflictos de horarios dentro de un plan de cursada.

    Para cada combinacion carrera+año+cuatrimestre en las plan versions del ciclo:
    - Obtiene las materias que corresponden a ese grupo
    - Obtiene los horarios de comisiones dentro del plan
    - Para 2C: incluye anuales (cuatrimestre_plan == "Anual")
    - Para cada par de materias, verifica si EXISTE al menos un par
      de comisiones compatible (una de cada materia). Si no existe
      ningún par compatible → conflicto real.

    Severity: BLOCKER — debe resolverse antes de activar el plan.
    """
    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        return ValidationResult(
            valid=True,
            message=f"Plan '{plan_id}' no encontrado"
        )

    # Get plan versions for the ciclo
    plan_version_ids = session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == plan.ciclo_id)
    ).all()

    if not plan_version_ids:
        return ValidationResult(
            valid=True,
            message="El ciclo no tiene versiones de plan asignadas"
        )

    # Get all comisiones in this plan, indexed by materia_codigo
    comisiones = session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all()
    comision_ids = [c.id for c in comisiones]
    comision_map = {c.id: c for c in comisiones}

    if not comision_ids:
        return ValidationResult(
            valid=True,
            message="El plan no tiene comisiones"
        )

    # Load all horarios for the plan's comisiones
    all_horarios = session.exec(
        select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
    ).all()

    # Index horarios by comision_id
    horarios_por_comision: dict[str, list[HorarioDB]] = {}
    for h in all_horarios:
        horarios_por_comision.setdefault(h.comision_id, []).append(h)

    # Index comisiones by materia_codigo
    comisiones_por_materia: dict[str, list[str]] = {}
    for c in comisiones:
        comisiones_por_materia.setdefault(c.materia_codigo, []).append(c.id)

    # Get all distinct (carrera, anio, cuatrimestre) groups
    plan_entries = session.exec(
        select(PlanEstudioDB)
        .where(PlanEstudioDB.plan_version_id.in_(plan_version_ids))
    ).all()

    # Build groups: (carrera_codigo, anio_plan, cuatrimestre_plan) → set of materia_codigos
    groups: dict[tuple[str, int, str], set[str]] = {}
    for pe in plan_entries:
        if pe.anio_plan is None or pe.cuatrimestre_plan is None:
            continue
        key = (pe.carrera_codigo, pe.anio_plan, pe.cuatrimestre_plan)
        groups.setdefault(key, set()).add(pe.materia_codigo)

    # For each cuatrimestre group, also include anuales from the same carrera+year
    enriched_groups: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mat_codes in groups.items():
        enriched = set(mat_codes)
        if cuatri in ("1C", "2C"):
            # Include anuales from same carrera+year
            anual_key = (carrera, anio, "Anual")
            if anual_key in groups:
                enriched |= groups[anual_key]
        enriched_groups[(carrera, anio, cuatri)] = enriched

    # Check for conflicts within each group using pairwise comision compatibility
    conflictos = []
    for (carrera, anio, cuatri), mat_codes in enriched_groups.items():
        # Only check materias that have comisiones with horarios in this plan
        relevant = [
            mc for mc in mat_codes
            if mc in comisiones_por_materia
            and any(cid in horarios_por_comision for cid in comisiones_por_materia[mc])
        ]

        for i, mat1 in enumerate(relevant):
            for mat2 in relevant[i + 1:]:
                # Check if at least one pair of comisiones is compatible
                com_ids_1 = [
                    cid for cid in comisiones_por_materia[mat1]
                    if cid in horarios_por_comision
                ]
                com_ids_2 = [
                    cid for cid in comisiones_por_materia[mat2]
                    if cid in horarios_por_comision
                ]

                found_compatible = False
                for cid1 in com_ids_1:
                    for cid2 in com_ids_2:
                        if _comisiones_son_compatibles(
                            horarios_por_comision[cid1],
                            horarios_por_comision[cid2],
                        ):
                            found_compatible = True
                            break
                    if found_compatible:
                        break

                if not found_compatible:
                    # Build detail: list overlapping slots from first conflicting pair
                    sample_h1 = horarios_por_comision[com_ids_1[0]]
                    sample_h2 = horarios_por_comision[com_ids_2[0]]
                    for h1 in sample_h1:
                        for h2 in sample_h2:
                            if horarios_se_superponen(h1, h2):
                                conflictos.append(
                                    f"{carrera} Año {anio} {cuatri}: "
                                    f"{mat1} vs {mat2} — {h1.dia} "
                                    f"{h1.hora_inicio.strftime('%H:%M')}-"
                                    f"{h1.hora_fin.strftime('%H:%M')}"
                                )

    if conflictos:
        return ValidationResult(
            valid=False,
            message=f"{len(conflictos)} conflicto(s) de horario en el plan",
            details=conflictos,
        )

    return ValidationResult(
        valid=True,
        message="Sin conflictos de horario en el plan",
    )


# =============================================================================
# Validacion 5: Cobertura del plan (WARNING)
# =============================================================================

def validar_cobertura_plan(
    session: Session,
    plan_id: str,
    ciclo_id: str,
) -> ValidationResult:
    """
    Verifica que toda materia con dictado activo tenga al menos una comisión
    con horarios en el plan.

    Severity: WARNING — informativo, no bloquea activación.
    """
    # Get active dictados for this ciclo
    dictados_activos = session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
        .where(DictadoDB.activo == True)  # noqa: E712
    ).all()

    if not dictados_activos:
        return ValidationResult(
            valid=True,
            message="No hay dictados activos para este ciclo",
        )

    # Get comisiones in the plan that have at least one horario
    comisiones_con_horario = session.exec(
        select(ComisionDB.materia_codigo)
        .where(ComisionDB.plan_cursada_id == plan_id)
        .join(HorarioDB, HorarioDB.comision_id == ComisionDB.id)
        .distinct()
    ).all()
    materias_cubiertas = set(comisiones_con_horario)

    # Find dictados without coverage
    sin_cobertura = []
    for d in dictados_activos:
        if d.materia_codigo not in materias_cubiertas:
            sin_cobertura.append(
                f"{d.dictado_codigo} ({d.materia_codigo})"
            )

    if sin_cobertura:
        return ValidationResult(
            valid=False,
            message=f"{len(sin_cobertura)} materia(s) con dictado activo sin comisión/horarios en el plan",
            details=sin_cobertura,
        )

    return ValidationResult(
        valid=True,
        message=f"Todas las {len(dictados_activos)} materias con dictado activo tienen cobertura en el plan",
    )


# =============================================================================
# Validacion 6: Identificar materias virtuales en el plan (INFO)
# =============================================================================

def identificar_virtuales_plan(
    session: Session,
    plan_id: str,
) -> ValidationResult:
    """
    Identifica materias virtuales que tienen horarios en el plan.
    Estas materias no necesitan aula física.

    Severity: INFO — puramente informativo.
    """
    # Get comisiones in the plan
    comisiones = session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all()

    if not comisiones:
        return ValidationResult(
            valid=True,
            message="El plan no tiene comisiones",
        )

    # Get unique materia codes
    mat_codes = list({c.materia_codigo for c in comisiones})
    materias = session.exec(
        select(MateriaDB).where(col(MateriaDB.codigo).in_(mat_codes))
    ).all()
    virtual_materias = {m.codigo: m.nombre for m in materias if m.virtual}

    if not virtual_materias:
        return ValidationResult(
            valid=True,
            message="No hay materias virtuales en el plan",
        )

    # Check which virtual materias have horarios
    virtuales_con_horario = []
    comision_ids = [c.id for c in comisiones if c.materia_codigo in virtual_materias]
    if comision_ids:
        horarios = session.exec(
            select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
        ).all()

        # Which materias have horarios
        mat_con_horario = set()
        com_map = {c.id: c.materia_codigo for c in comisiones}
        for h in horarios:
            mc = com_map.get(h.comision_id)
            if mc and mc in virtual_materias:
                mat_con_horario.add(mc)

        for mc in sorted(mat_con_horario):
            virtuales_con_horario.append(
                f"{mc}: {virtual_materias[mc]} (no necesita aula)"
            )

    if virtuales_con_horario:
        return ValidationResult(
            valid=True,
            message=f"{len(virtuales_con_horario)} materia(s) virtual(es) con horarios (no necesitan aula)",
            details=virtuales_con_horario,
        )

    return ValidationResult(
        valid=True,
        message=f"{len(virtual_materias)} materia(s) virtual(es) en el plan, sin horarios asignados",
    )


# =============================================================================
# =============================================================================
# Prevalidación: factibilidad de partición teoría/laboratorio
# =============================================================================

def validar_factibilidad_particion_horas(
    session: Session,
    schedule_id: str | None = None,
    plan_cursada_id: str | None = None,
) -> ValidationResult:
    """Valida que para cada comisión con horas_laboratorio > 0, las clases
    puedan particionarse en subconjuntos que sumen horas_teoria y horas_laboratorio.

    Trabaja a nivel de schedule entries (agrupadas por materia+comision) o de
    horarios de un plan existente.

    Reglas:
    - Si materia.horas_laboratorio is None o == 0: skip (no requiere lab fijo).
    - Las duraciones de clases de la comision deben poder particionarse en
      dos subconjuntos: uno que sume horas_teoria y otro que sume horas_laboratorio.
    - Si hay tipos predeterminados (!= None), las duraciones predeterminadas como
      'laboratorio' deben sumar <= horas_laboratorio y las predeterminadas como
      'teorica' deben sumar <= horas_teoria.
    """
    from src.database.models import ScheduleEntryDB
    from itertools import combinations

    errors: list[str] = []

    # Collect materias with horas_laboratorio > 0
    materias = list(session.exec(
        select(MateriaDB).where(
            MateriaDB.horas_laboratorio != None,  # noqa: E711
            MateriaDB.horas_laboratorio > 0,
        )
    ).all())

    if not materias:
        return ValidationResult(
            valid=True,
            message="No hay materias con horas de laboratorio fijas definidas.",
        )

    mat_map = {m.codigo: m for m in materias}

    if schedule_id:
        entries = list(session.exec(
            select(ScheduleEntryDB)
            .where(ScheduleEntryDB.schedule_id == schedule_id)
            .where(ScheduleEntryDB.codigo_materia.in_(list(mat_map.keys())))
        ).all())

        # Group by (materia, comision). Skip entries sin comision asignada
        # (la Phase 2 valida con comisiones del preview).
        from collections import defaultdict
        groups: dict[tuple[str, int], list] = defaultdict(list)
        for e in entries:
            if e.comision is None:
                continue
            groups[(e.codigo_materia, e.comision)].append(e)

        for (mat_code, com_num), group_entries in sorted(groups.items()):
            mat = mat_map[mat_code]
            ht = mat.horas_teoria or 0
            hl = mat.horas_laboratorio or 0

            durations = []
            pre_lab_sum = 0.0
            pre_teo_sum = 0.0
            for e in group_entries:
                h_ini = e.hora_inicio
                h_fin = e.hora_fin
                dur = (h_fin.hour * 60 + h_fin.minute - h_ini.hour * 60 - h_ini.minute) / 60.0
                durations.append(dur)
                if e.tipo_clase == "laboratorio":
                    pre_lab_sum += dur
                elif e.tipo_clase == "teorica":
                    pre_teo_sum += dur

            # Check predetermined consistency
            if pre_lab_sum > hl + 0.01:
                errors.append(
                    f"{mat_code} C{com_num}: horas predeterminadas como lab "
                    f"({pre_lab_sum:.1f}) > horas_laboratorio ({hl:.1f})"
                )
                continue
            if pre_teo_sum > ht + 0.01:
                errors.append(
                    f"{mat_code} C{com_num}: horas predeterminadas como teoría "
                    f"({pre_teo_sum:.1f}) > horas_teoria ({ht:.1f})"
                )
                continue

            # Check if a partition exists (subset-sum on lab hours)
            total = sum(durations)
            expected_total = ht + hl
            if abs(total - expected_total) > 0.01:
                errors.append(
                    f"{mat_code} C{com_num}: duracion total ({total:.1f}h) "
                    f"≠ horas_teoria + horas_laboratorio ({expected_total:.1f}h)"
                )
                continue

            # Subset-sum: find a subset of durations summing to hl
            if not _subset_sum_exists(durations, hl):
                errors.append(
                    f"{mat_code} C{com_num}: no existe partición de clases "
                    f"({[f'{d:.1f}' for d in durations]}) que sume "
                    f"horas_laboratorio={hl:.1f}"
                )

    elif plan_cursada_id:
        horarios = list(session.exec(
            select(HorarioDB)
            .join(ComisionDB, HorarioDB.comision_id == ComisionDB.id)
            .where(ComisionDB.plan_cursada_id == plan_cursada_id)
            .where(HorarioDB.codigo_materia.in_(list(mat_map.keys())))
        ).all())

        from collections import defaultdict
        groups_h: dict[tuple[str, str], list] = defaultdict(list)
        for h in horarios:
            groups_h[(h.codigo_materia, h.comision_id)].append(h)

        for (mat_code, com_id), group_hs in sorted(groups_h.items()):
            mat = mat_map[mat_code]
            ht = mat.horas_teoria or 0
            hl = mat.horas_laboratorio or 0

            durations = []
            pre_lab_sum = 0.0
            pre_teo_sum = 0.0
            for h in group_hs:
                dur = (h.hora_fin.hour * 60 + h.hora_fin.minute - h.hora_inicio.hour * 60 - h.hora_inicio.minute) / 60.0
                durations.append(dur)
                if h.tipo_clase == "laboratorio":
                    pre_lab_sum += dur
                elif h.tipo_clase == "teorica":
                    pre_teo_sum += dur

            if pre_lab_sum > hl + 0.01:
                errors.append(
                    f"{mat_code} (comision {com_id[:8]}): predeterminadas lab "
                    f"({pre_lab_sum:.1f}) > horas_laboratorio ({hl:.1f})"
                )
                continue
            if pre_teo_sum > ht + 0.01:
                errors.append(
                    f"{mat_code} (comision {com_id[:8]}): predeterminadas teoría "
                    f"({pre_teo_sum:.1f}) > horas_teoria ({ht:.1f})"
                )
                continue

            total = sum(durations)
            expected_total = ht + hl
            if abs(total - expected_total) > 0.01:
                errors.append(
                    f"{mat_code} (comision {com_id[:8]}): duracion total ({total:.1f}h) "
                    f"≠ ht+hl ({expected_total:.1f}h)"
                )
                continue

            if not _subset_sum_exists(durations, hl):
                errors.append(
                    f"{mat_code} (comision {com_id[:8]}): no existe partición "
                    f"que sume horas_laboratorio={hl:.1f}"
                )

    if errors:
        return ValidationResult(
            valid=False,
            message=f"{len(errors)} comisión(es) con partición de horas infactible",
            details=errors,
        )
    return ValidationResult(
        valid=True,
        message="Todas las comisiones con lab fijo tienen partición factible.",
    )


def _subset_sum_exists(values: list[float], target: float, tol: float = 0.01) -> bool:
    """Check if any subset of values sums to target (within tolerance).

    Uses dynamic programming on discretized values (resolution 0.25h = 15min).
    """
    if abs(target) < tol:
        return True
    if not values:
        return False

    # Discretize to quarter-hours
    scale = 4  # 4 units per hour
    target_int = round(target * scale)
    vals_int = [round(v * scale) for v in values]

    # DP: reachable sums
    reachable = {0}
    for v in vals_int:
        reachable = reachable | {s + v for s in reachable}

    return target_int in reachable


# Ejecutar todas las validaciones
# =============================================================================

def ejecutar_todas_validaciones(session: Session) -> dict[str, ValidationResult]:
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

    # Validacion 3: Conflictos de aula (placeholder - requires plan_cursada_id)
    # Use validar_conflictos_aula_plan(session, plan_cursada_id) directly when needed

    return results


# =============================================================================
# Validacion: conflictos de horarios sobre el cronograma (sin plan creado)
# =============================================================================

def validar_conflictos_horarios_cronograma(
    session: Session,
    schedule_id: str,
    ciclo_id: str,
) -> list[ConflictoHorario]:
    """Detecta conflictos de horario en un cronograma usando comisiones
    auto-derivadas (mismo flujo que `preview_plan_from_schedule`).

    Algoritmo:
    1. Corre el preview de generacion de plan -> deriva comisiones por materia
       segun reglas (optativa, exclusiva, compartida, paralelas).
    2. Convierte EntryPreview -> "horarios virtuales" agrupados por
       (materia, comision_asignada).
    3. Para cada grupo curricular (carrera, anio, cuatri) presente en los
       planes asignados al ciclo, aplica el chequeo pairwise: dos materias
       son compatibles si EXISTE al menos un par de comisiones cuyos
       horarios no se solapan.
    4. Si NO existe ningun par compatible, registra un ConflictoHorario por
       cada par (h1, h2) que se solapa.

    Devuelve la lista (vacia si no hay conflictos).
    """
    from src.services.plan_generation_service import preview_plan_from_schedule
    from src.database.models import ScheduleEntryDB

    # 1) Preview con comisiones derivadas
    preview = preview_plan_from_schedule(session, schedule_id)
    if preview.errors or not preview.materias:
        return []

    # 2) Por cada (materia, comision_asignada) armamos lista de "horarios virtuales".
    #    Reusamos HorarioDB como un struct con dia/hora_inicio/hora_fin (no se persiste).
    class _VHorario:
        __slots__ = ("dia", "hora_inicio", "hora_fin")
        def __init__(self, dia, hora_inicio, hora_fin):
            self.dia = dia
            self.hora_inicio = hora_inicio
            self.hora_fin = hora_fin

    # comisiones_por_materia: { materia: { com_num: [vhorario, ...] } }
    comisiones_por_materia: dict[str, dict[int, list[_VHorario]]] = {}
    for mp in preview.materias:
        com_dict: dict[int, list[_VHorario]] = {}
        for ep in mp.entries:
            com_dict.setdefault(ep.comision_asignada, []).append(
                _VHorario(ep.dia, ep.hora_inicio, ep.hora_fin)
            )
        comisiones_por_materia[mp.materia_codigo] = com_dict

    # 3) Grupos curriculares: (carrera, anio, cuatri) -> set[materia]
    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all())
    if not plan_version_ids:
        return []

    plan_entries = list(session.exec(
        select(PlanEstudioDB)
        .where(col(PlanEstudioDB.plan_version_id).in_(plan_version_ids))
    ).all())

    groups: dict[tuple[str, int, str], set[str]] = {}
    for pe in plan_entries:
        if pe.anio_plan is None or pe.cuatrimestre_plan is None:
            continue
        key = (pe.carrera_codigo, pe.anio_plan, pe.cuatrimestre_plan)
        groups.setdefault(key, set()).add(pe.materia_codigo)

    # Enrich: 1C/2C tambien incluyen Anual del mismo carrera/anio
    enriched: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mats in groups.items():
        s = set(mats)
        if cuatri in ("1C", "2C"):
            anual_k = (carrera, anio, "Anual")
            if anual_k in groups:
                s |= groups[anual_k]
        enriched[(carrera, anio, cuatri)] = s

    # 4) Pairwise compatibility por grupo
    def _solapa(h1: _VHorario, h2: _VHorario) -> bool:
        if h1.dia != h2.dia:
            return False
        return h1.hora_inicio < h2.hora_fin and h2.hora_inicio < h1.hora_fin

    def _coms_compatibles(hs_a: list[_VHorario], hs_b: list[_VHorario]) -> bool:
        for h1 in hs_a:
            for h2 in hs_b:
                if _solapa(h1, h2):
                    return False
        return True

    conflictos: list[ConflictoHorario] = []
    seen_pairs: set[tuple[str, int, str, str, str]] = set()

    for (carrera, anio, cuatri), mats in enriched.items():
        relevant = [m for m in mats if m in comisiones_por_materia and comisiones_por_materia[m]]
        for i, mat1 in enumerate(sorted(relevant)):
            for mat2 in sorted(relevant)[i + 1:]:
                # Dedupe: el mismo par puede aparecer en grupos enriquecidos distintos
                pair_key = (carrera, anio, cuatri, mat1, mat2)
                if pair_key in seen_pairs:
                    continue
                seen_pairs.add(pair_key)

                coms_1 = comisiones_por_materia[mat1]
                coms_2 = comisiones_por_materia[mat2]

                found_compatible = False
                for hs_a in coms_1.values():
                    for hs_b in coms_2.values():
                        if _coms_compatibles(hs_a, hs_b):
                            found_compatible = True
                            break
                    if found_compatible:
                        break

                if found_compatible:
                    continue

                # Reportar todos los pares (h1, h2) solapados de la primer
                # combinacion (com1=primera, com2=primera) — alcanza para
                # ilustrar el problema sin inflar la lista.
                first_com_1 = next(iter(coms_1.values()))
                first_com_2 = next(iter(coms_2.values()))
                for h1 in first_com_1:
                    for h2 in first_com_2:
                        if _solapa(h1, h2):
                            conflictos.append(ConflictoHorario(
                                carrera_codigo=carrera,
                                anio_plan=anio,
                                cuatrimestre_plan=cuatri,
                                materia_a=mat1,
                                materia_b=mat2,
                                dia=h1.dia,
                                hora_inicio_a=h1.hora_inicio.strftime("%H:%M"),
                                hora_fin_a=h1.hora_fin.strftime("%H:%M"),
                                hora_inicio_b=h2.hora_inicio.strftime("%H:%M"),
                                hora_fin_b=h2.hora_fin.strftime("%H:%M"),
                            ))

    return conflictos
