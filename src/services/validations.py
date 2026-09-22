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


def build_grupos_curriculares_del_ciclo(
    session: Session, ciclo_id: str,
) -> dict[tuple[str, int, str], set[str]]:
    """Devuelve los grupos curriculares (carrera, año, cuatri) → set[materia]
    que se cursan en el ciclo dado, enriquecidos con anuales.

    Patrón compartido: se cursan en el ciclo las materias del cuatri
    del ciclo (`{ciclo.numero}C`) más las anuales del mismo (carrera,
    año). Los grupos del cuatri opuesto se descartan.

    Sólo devuelve materias **obligatorias**. Las optativas se filtran
    porque ningún alumno las cursa simultáneamente por default; incluirlas
    genera falsos positivos en camino de cursada. Si en el futuro se
    necesitase mostrar bloqueos "posibles" con optativas, se puede
    parametrizar.

    Antes este bloque estaba duplicado 4 veces (validations.py,
    plan_validation_service.py, factibilidad_service.py) casi textual.
    Ahora es una fuente única. Consumidores del plan y del cronograma
    resuelven el mismo grafo curricular por acá.
    """
    from src.database.models import CicloDB

    ciclo = session.get(CicloDB, ciclo_id)
    if ciclo is None:
        return {}
    cuatri_ciclo = f"{ciclo.numero}C"

    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == ciclo_id)
    ).all())
    if not plan_version_ids:
        return {}

    plan_entries = list(session.exec(
        select(PlanEstudioDB)
        .where(col(PlanEstudioDB.plan_version_id).in_(plan_version_ids))
    ).all())

    grupos: dict[tuple[str, int, str], set[str]] = {}
    for pe in plan_entries:
        if pe.anio_plan is None or pe.cuatrimestre_plan is None:
            continue
        if pe.optativa:
            continue
        key = (pe.carrera_codigo, pe.anio_plan, pe.cuatrimestre_plan)
        grupos.setdefault(key, set()).add(pe.materia_codigo)

    enriquecidos: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mats in grupos.items():
        if cuatri != cuatri_ciclo:
            continue
        s = set(mats)
        anual_key = (carrera, anio, "Anual")
        if anual_key in grupos:
            s |= grupos[anual_key]
        enriquecidos[(carrera, anio, cuatri)] = s

    return enriquecidos


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
    ignored_pairs: Optional[set[tuple[str, str]]] = None,
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

    Args:
        ignored_pairs: set de tuplas (materia_a, materia_b) ordenadas
            lexicograficamente que se descartan (no se reportan como
            conflicto). Provistas por la UI desde IgnoredConflictDB.
    """
    ignored_pairs = ignored_pairs or set()
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

    # Solo nos interesan grupos del cuatri del ciclo + Anual: las materias
    # del cuatri opuesto no se cursan en este ciclo.
    from src.database.models import CicloDB
    ciclo = session.get(CicloDB, plan.ciclo_id)
    if ciclo is None:
        return ValidationResult(
            valid=True, message="Ciclo del plan no encontrado",
        )
    cuatri_ciclo = f"{ciclo.numero}C"

    # Build groups: (carrera_codigo, anio_plan, cuatrimestre_plan) → set of materia_codigos
    groups: dict[tuple[str, int, str], set[str]] = {}
    for pe in plan_entries:
        if pe.anio_plan is None or pe.cuatrimestre_plan is None:
            continue
        key = (pe.carrera_codigo, pe.anio_plan, pe.cuatrimestre_plan)
        groups.setdefault(key, set()).add(pe.materia_codigo)

    # Enrich: solo grupos del cuatri del ciclo (incluyen anuales del mismo
    # carrera+año). Los grupos del cuatri opuesto se descartan.
    enriched_groups: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mat_codes in groups.items():
        if cuatri != cuatri_ciclo:
            continue
        enriched = set(mat_codes)
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
                # Skip si el par esta ignorado (ordenamos lexicograficamente)
                _pair = (mat1, mat2) if mat1 < mat2 else (mat2, mat1)
                if _pair in ignored_pairs:
                    continue
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


def validar_conflictos_horarios_plan_estructurados(
    session: Session,
    plan_id: str,
    ignored_pairs: Optional[set[tuple[str, str]]] = None,
) -> list[ConflictoHorario]:
    """Espejo de `validar_conflictos_horarios_cronograma` pero sobre las
    comisiones REALES del plan (no auto-derivadas).

    Devuelve list[ConflictoHorario] estructurado para que la UI agrupe
    por (carrera, año, cuatri) y muestre tabla resumen + detalle. Los
    pares ignorados se descartan.
    """
    ignored_pairs = ignored_pairs or set()

    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        return []

    plan_version_ids = list(session.exec(
        select(CicloPlanVersionDB.plan_version_id)
        .where(CicloPlanVersionDB.ciclo_id == plan.ciclo_id)
    ).all())
    if not plan_version_ids:
        return []

    from src.database.models import CicloDB
    ciclo = session.get(CicloDB, plan.ciclo_id)
    if ciclo is None:
        return []
    cuatri_ciclo = f"{ciclo.numero}C"

    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    comision_ids = [c.id for c in comisiones]
    if not comision_ids:
        return []

    all_horarios = list(session.exec(
        select(HorarioDB).where(col(HorarioDB.comision_id).in_(comision_ids))
    ).all())
    horarios_por_comision: dict[str, list[HorarioDB]] = {}
    for h in all_horarios:
        horarios_por_comision.setdefault(h.comision_id, []).append(h)

    comisiones_por_materia: dict[str, list[str]] = {}
    for c in comisiones:
        comisiones_por_materia.setdefault(c.materia_codigo, []).append(c.id)

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

    enriched: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mats in groups.items():
        if cuatri != cuatri_ciclo:
            continue
        s = set(mats)
        anual_k = (carrera, anio, "Anual")
        if anual_k in groups:
            s |= groups[anual_k]
        enriched[(carrera, anio, cuatri)] = s

    conflictos: list[ConflictoHorario] = []
    seen: set[tuple[str, int, str, str, str]] = set()

    for (carrera, anio, cuatri), mats in enriched.items():
        relevant = [
            m for m in mats
            if m in comisiones_por_materia
            and any(cid in horarios_por_comision for cid in comisiones_por_materia[m])
        ]
        for i, mat1 in enumerate(sorted(relevant)):
            for mat2 in sorted(relevant)[i + 1:]:
                # Skip ignorados
                _pair = (mat1, mat2) if mat1 < mat2 else (mat2, mat1)
                if _pair in ignored_pairs:
                    continue
                _seen_key = (carrera, anio, cuatri, mat1, mat2)
                if _seen_key in seen:
                    continue
                seen.add(_seen_key)

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
                if found_compatible:
                    continue

                # Reportar todos los pares (h1, h2) solapados de la primera
                # combinacion (com1=primera, com2=primera)
                first_com_1 = horarios_por_comision[com_ids_1[0]]
                first_com_2 = horarios_por_comision[com_ids_2[0]]
                for h1 in first_com_1:
                    for h2 in first_com_2:
                        if horarios_se_superponen(h1, h2):
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
    # Get dictados for this ciclo (todos existen → todos activos).
    dictados_activos = session.exec(
        select(DictadoDB)
        .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)
        .where(DictadoCicloDB.ciclo_id == ciclo_id)
    ).all()

    if not dictados_activos:
        return ValidationResult(
            valid=True,
            message="No hay dictados para este ciclo",
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

        # Group by (materia, comision_id). Skip entries sin comisión
        # asignada (huérfanos). Se muestran los numeros/nombres de las
        # comisiones en los mensajes de error.
        from collections import defaultdict
        groups: dict[tuple[str, str], list] = defaultdict(list)
        for e in entries:
            if e.comision_id is None:
                continue
            groups[(e.codigo_materia, e.comision_id)].append(e)

        # Precargar comisiones referenciadas para las etiquetas.
        com_ids_referenciados = {cid for _, cid in groups.keys()}
        comisiones_map: dict[str, ComisionDB] = {}
        if com_ids_referenciados:
            comisiones_map = {
                c.id: c for c in session.exec(
                    select(ComisionDB).where(
                        ComisionDB.id.in_(com_ids_referenciados)  # type: ignore[attr-defined]
                    )
                ).all()
            }

        def _lbl_com(com_id: str) -> str:
            c = comisiones_map.get(com_id)
            if c is None:
                return f"comision {com_id[:8]}"
            return f"C{c.numero}"

        for (mat_code, com_id), group_entries in sorted(groups.items()):
            mat = mat_map[mat_code]
            ht = mat.horas_teoria or 0
            hl = mat.horas_laboratorio or 0
            com_lbl = _lbl_com(com_id)

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
                    f"{mat_code} {com_lbl}: horas predeterminadas como lab "
                    f"({pre_lab_sum:.1f}) > horas_laboratorio ({hl:.1f})"
                )
                continue
            if pre_teo_sum > ht + 0.01:
                errors.append(
                    f"{mat_code} {com_lbl}: horas predeterminadas como teoría "
                    f"({pre_teo_sum:.1f}) > horas_teoria ({ht:.1f})"
                )
                continue

            # Check if a partition exists (subset-sum on lab hours)
            total = sum(durations)
            expected_total = ht + hl
            if abs(total - expected_total) > 0.01:
                errors.append(
                    f"{mat_code} {com_lbl}: duracion total ({total:.1f}h) "
                    f"≠ horas_teoria + horas_laboratorio ({expected_total:.1f}h)"
                )
                continue

            # Subset-sum: find a subset of durations summing to hl
            if not _subset_sum_exists(durations, hl):
                errors.append(
                    f"{mat_code} {com_lbl}: no existe partición de clases "
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
# Validacion: horarios respetan la configuracion horaria global
# =============================================================================


@dataclass
class HorarioFueraConfig:
    """Un ScheduleEntryDB que rompe alguna regla de ConfiguracionHoraria."""
    entry_id: str
    codigo_materia: str
    dia: str
    hora_inicio: str  # HH:MM
    hora_fin: str
    razones: list[str]  # ej: ["dia no operativo", "inicio no múltiplo de 15 min"]


def validar_horarios_vs_config(
    session: Session,
    schedule_id: str,
) -> list[HorarioFueraConfig]:
    """Chequea que cada entry del cronograma respete `ConfiguracionHoraria`.

    Fase H.1 del rediseño 2026-09-15. Antes no se validaba que los
    horarios cayeran en los días operativos, dentro del rango
    ``[hora_inicio_operativo, hora_fin_operativo]`` y con la
    granularidad configurada. Cargar horarios rotos pasaba
    silenciosamente y sólo se detectaba al armar el plan (o ni ahí).

    Reglas:

    - ``dia`` debe estar en ``ConfiguracionHoraria.dias_operativos``.
    - ``hora_inicio >= hora_inicio_operativo``.
    - ``hora_fin <= hora_fin_operativo`` (con `time(0, 0)` interpretado
      como "medianoche" — sólo válido si `hora_fin_operativo` es
      exactamente medianoche).
    - ``hora_inicio`` y ``hora_fin`` deben ser múltiplos de
      ``granularidad_minutos`` contados desde ``hora_inicio_operativo``.

    Devuelve la lista de entries que violan al menos una regla, con
    las razones enumeradas por entry. Vacía si todo OK.
    """
    from src.database.models import ConfiguracionHoraria, ScheduleEntryDB

    config = session.exec(
        select(ConfiguracionHoraria).limit(1)
    ).first()
    if config is None:
        # Sin config no hay reglas — no reportar nada.
        return []

    dias_operativos = {
        d.strip() for d in (config.dias_operativos or "").split(",") if d.strip()
    }
    granularidad = int(config.granularidad_minutos or 15)
    if granularidad <= 0:
        granularidad = 15

    def _mins(t) -> int:
        return t.hour * 60 + t.minute

    base_mins = _mins(config.hora_inicio_operativo)
    fin_mins = _mins(config.hora_fin_operativo)
    # Interpretar medianoche como fin del día (24:00).
    if config.hora_fin_operativo.hour == 0 and config.hora_fin_operativo.minute == 0:
        fin_mins = 24 * 60

    entries = list(session.exec(
        select(ScheduleEntryDB).where(
            ScheduleEntryDB.schedule_id == schedule_id,
        )
    ).all())

    resultado: list[HorarioFueraConfig] = []
    for e in entries:
        razones: list[str] = []

        if dias_operativos and e.dia not in dias_operativos:
            razones.append(
                f"día '{e.dia}' no está en los días operativos "
                f"({sorted(dias_operativos)})"
            )

        h_ini = _mins(e.hora_inicio)
        h_fin = _mins(e.hora_fin)
        # hora_fin == 00:00 significa "medianoche" (fin del día).
        if e.hora_fin.hour == 0 and e.hora_fin.minute == 0:
            h_fin = 24 * 60

        if h_ini < base_mins:
            razones.append(
                f"inicio {e.hora_inicio.strftime('%H:%M')} es anterior "
                f"al horario operativo ({config.hora_inicio_operativo.strftime('%H:%M')})"
            )
        if h_fin > fin_mins:
            razones.append(
                f"fin {e.hora_fin.strftime('%H:%M')} es posterior al "
                f"horario operativo ({config.hora_fin_operativo.strftime('%H:%M')})"
            )
        if h_ini >= base_mins:
            delta_ini = h_ini - base_mins
            if delta_ini % granularidad != 0:
                razones.append(
                    f"inicio {e.hora_inicio.strftime('%H:%M')} no respeta la "
                    f"granularidad de {granularidad} min "
                    f"(offset {delta_ini % granularidad} min)"
                )
        if h_fin <= fin_mins and h_fin > base_mins:
            delta_fin = h_fin - base_mins
            if delta_fin % granularidad != 0:
                razones.append(
                    f"fin {e.hora_fin.strftime('%H:%M')} no respeta la "
                    f"granularidad de {granularidad} min "
                    f"(offset {delta_fin % granularidad} min)"
                )

        if razones:
            resultado.append(HorarioFueraConfig(
                entry_id=e.id,
                codigo_materia=e.codigo_materia,
                dia=e.dia,
                hora_inicio=e.hora_inicio.strftime("%H:%M"),
                hora_fin=e.hora_fin.strftime("%H:%M"),
                razones=razones,
            ))
    return resultado


def ajustar_horarios_a_config(
    session: Session,
    schedule_id: str,
) -> tuple[int, int, list[str]]:
    """Ajusta masivamente los ``ScheduleEntryDB`` que rompen la config
    horaria: redondea ``hora_inicio`` y ``hora_fin`` al múltiplo de la
    granularidad más cercano dentro del rango operativo.

    Fase I.1 del rediseño 2026-09-21. Complementa
    ``validar_horarios_vs_config``: en vez de sólo reportar, arregla.

    Reglas de ajuste:

    - Si el día no es operativo → la entry queda **inalterada** (no
      hay redondeo posible; el usuario tiene que decidir el día
      manualmente). Se cuenta en ``skipped_dia`` y su descripción
      aparece en el listado devuelto.
    - Si ``hora_inicio < hora_inicio_operativo`` → se lleva a
      ``hora_inicio_operativo``.
    - Si ``hora_fin > hora_fin_operativo`` → se lleva a
      ``hora_fin_operativo``.
    - Redondeo al slot más cercano según ``granularidad_minutos``.
      Si empatan, redondea hacia arriba.
    - Guard: si tras el ajuste ``hora_fin <= hora_inicio``, se
      extiende ``hora_fin`` un slot (granularidad).

    Returns:
        (n_ajustadas, n_skipped, mensajes) — ``mensajes`` es un
        listado corto de los cambios aplicados y los saltos por
        día, útil para el toast/log de la UI.
    """
    from datetime import time
    from src.database.models import ConfiguracionHoraria, ScheduleEntryDB

    config = session.exec(
        select(ConfiguracionHoraria).limit(1)
    ).first()
    if config is None:
        return (0, 0, [])

    dias_ok = {
        d.strip() for d in (config.dias_operativos or "").split(",")
        if d.strip()
    }
    gran = int(config.granularidad_minutos or 15) or 15

    def _mins(t) -> int:
        return t.hour * 60 + t.minute

    def _from_mins(m: int) -> time:
        # `m == 24*60` se representa como time(0, 0) — semántica
        # medianoche del final del día.
        if m >= 24 * 60:
            return time(0, 0)
        return time((m // 60) % 24, m % 60)

    base = _mins(config.hora_inicio_operativo)
    fin_op = _mins(config.hora_fin_operativo)
    if (
        config.hora_fin_operativo.hour == 0
        and config.hora_fin_operativo.minute == 0
    ):
        fin_op = 24 * 60

    def _round_to_slot(m: int) -> int:
        """Redondea m al múltiplo de `gran` más cercano contado desde `base`."""
        if m <= base:
            return base
        if m >= fin_op:
            return fin_op
        rel = m - base
        lower = (rel // gran) * gran + base
        upper = lower + gran
        # Empate → hacia arriba.
        return upper if (m - lower) >= (upper - m) else lower

    entries = list(session.exec(
        select(ScheduleEntryDB).where(
            ScheduleEntryDB.schedule_id == schedule_id,
        )
    ).all())

    n_ajustadas = 0
    n_skipped = 0
    mensajes: list[str] = []
    for e in entries:
        # Día no operativo → skip.
        if dias_ok and e.dia not in dias_ok:
            n_skipped += 1
            mensajes.append(
                f"{e.codigo_materia} {e.dia} "
                f"{e.hora_inicio.strftime('%H:%M')}–"
                f"{e.hora_fin.strftime('%H:%M')}: día no operativo, "
                "requiere corrección manual"
            )
            continue

        hi = _mins(e.hora_inicio)
        hf = _mins(e.hora_fin)
        if e.hora_fin.hour == 0 and e.hora_fin.minute == 0:
            hf = 24 * 60

        new_hi = _round_to_slot(hi)
        new_hf = _round_to_slot(hf)
        # Guard: fin > inicio.
        if new_hf <= new_hi:
            new_hf = min(new_hi + gran, fin_op)

        if new_hi == hi and new_hf == hf:
            continue  # ya estaba OK

        e.hora_inicio = _from_mins(new_hi)
        e.hora_fin = _from_mins(new_hf)
        session.add(e)
        n_ajustadas += 1
        mensajes.append(
            f"{e.codigo_materia} {e.dia}: "
            f"{_from_mins(hi).strftime('%H:%M')}–"
            f"{_from_mins(hf).strftime('%H:%M')} → "
            f"{e.hora_inicio.strftime('%H:%M')}–"
            f"{e.hora_fin.strftime('%H:%M')}"
        )

    if n_ajustadas > 0:
        session.commit()
    return (n_ajustadas, n_skipped, mensajes)


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
    # Solo nos interesan grupos del cuatri del ciclo + Anual: las materias
    # del cuatri opuesto no se cursan en este ciclo, asi que sus posibles
    # solapamientos no son problema actual.
    from src.database.models import CicloDB
    ciclo = session.get(CicloDB, ciclo_id)
    if ciclo is None:
        return []
    cuatri_ciclo = f"{ciclo.numero}C"

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

    # Enrich: el cuatri del ciclo incluye tambien las anuales. Los grupos
    # del cuatri opuesto se descartan completamente (no se cursan en este ciclo).
    enriched: dict[tuple[str, int, str], set[str]] = {}
    for (carrera, anio, cuatri), mats in groups.items():
        if cuatri != cuatri_ciclo:
            continue
        s = set(mats)
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
