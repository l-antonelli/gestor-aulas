"""Servicio del LP de asignación de aulas.

Implementa la Fase 1 del plan: backend mínimo del LP con R1 (asignación
única), R4 (no solapamiento por aula vía grupos de simultaneidad) y R7
(penalty de capacidad lineal asimétrico).

NO incluye todavía:
- t[h] / R5 / R6 (lab/teoría split): se agregan en Fase 5.
- α[k] / R9 (toggle redistribución de pesos): se agrega en Fase 8.
- apply_solution / persistencia (LPRunDB): se agrega en Fase 2.

Funciones públicas:
- ``build_inputs(session, plan_id, config)``: arma los conjuntos del LP
  desde la base.
- ``build_model(inputs, config)``: instancia el LpProblem de PuLP.
- ``solve(model, timeout)``: corre CBC.
- ``run_lp_dry(session, plan_id, config)``: wrapper end-to-end que
  devuelve la solución sin tocar la DB. Útil para tests y CLI.

El planteo matemático completo está en
``project/1. Diseño/asignacion-aulas-LP.md``.
"""

from __future__ import annotations

import json
import time as _time_mod
from dataclasses import dataclass, field
from datetime import date
from typing import Optional

import pulp
from sqlmodel import Session, select

from src.database.models import (
    AulaDB,
    ClaseDB,
    ComisionDB,
    DictadoDB,
    HorarioDB,
    LPRunDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanificacionCursadaDB,
)
from src.services.asignacion_aulas_helpers import (
    AulaSlot,
    HorarioSlot,
    InfeasibilityDiagnosis,
    ValidationResult,
    compute_compat,
    compute_simultaneidad_groups,
    diagnose_infeasibility,
    validar_particion_factible,
)
from src.services.plan_generation_service import (
    get_inscriptos_esperados_por_comision,
)


# =============================================================================
# Configuración
# =============================================================================

@dataclass
class LPConfig:
    """Parámetros que configuran la corrida del LP.

    Defaults alineados con § 3.4 y § 4 del documento de diseño.
    """
    lambda_over: float = 10.0
    lambda_under: float = 1.0
    tol_over: float = 0.0
    tol_under: float = 0.20
    activar_alpha: bool = False  # Fase 8 (no implementado todavía)
    timeout_seconds: int = 300
    # Política de re-run respecto a clases con aula_asignada_manualmente=True.
    # True (default): el LP no toca esas clases.
    # False: el LP las pisa como cualquier otra.
    respetar_ediciones_manuales: bool = True
    # Rango de aplicación: el resultado se propaga a ClaseDB con
    # fecha >= fecha_desde y executed=False. None = aplicar desde la
    # fecha más antigua del plan.
    fecha_desde: Optional[date] = None


# =============================================================================
# Inputs del modelo
# =============================================================================

@dataclass
class LPInputs:
    """Conjuntos y parámetros precomputados para construir el LP."""
    horarios: list[HorarioSlot]
    aulas: list[AulaSlot]
    insc: dict[str, float]              # horario_id -> inscriptos esperados
    dur: dict[str, float]               # horario_id -> duración en horas
    materia_de_horario: dict[str, str]  # horario_id -> codigo materia
    comision_de_horario: dict[str, str] # horario_id -> comision_id
    compat: dict[tuple[str, str], bool] # (horario_id, aula_id) -> True/False
    sim_groups: list[set[str]]          # grupos maximales de simultaneidad
    # Map materia_codigo -> set[aula_id] de labs compatibles. Necesario
    # para diagnosticar infactibilidad después.
    materia_lab_map: dict[str, set[str]] = field(default_factory=dict)
    # Horas de teoría / laboratorio por materia (para R5).
    hteo: dict[str, float] = field(default_factory=dict)
    hlab: dict[str, float] = field(default_factory=dict)
    # Total esperado de inscriptos por materia (para R9 cuando alpha está
    # activo: insc[h] se reemplaza por total_esp[m] * alpha[k]).
    total_esp: dict[str, float] = field(default_factory=dict)
    # Comisiones del plan: comision_id -> dictado_id (para agrupar α
    # por dictado en R9) y comision_id -> coef actual (para diff).
    dictado_de_comision: dict[str, Optional[str]] = field(default_factory=dict)
    coef_actual: dict[str, float] = field(default_factory=dict)
    # Errores no fatales detectados durante build_inputs (materias sin
    # forecast, virtuales filtradas, etc.). El caller decide si abortar.
    warnings: list[str] = field(default_factory=list)


def build_inputs(
    session: Session,
    plan_id: str,
    config: LPConfig,
) -> LPInputs:
    """Arma los inputs del LP a partir del plan de cursada.

    Pasos:
    1. Carga aulas y materia_lab map.
    2. Carga comisiones y horarios del plan, filtrando los de materias
       virtuales.
    3. Resuelve forecast por comisión (vía
       ``get_inscriptos_esperados_por_comision``).
    4. Computa compat[h, a] aplicando R3.
    5. Computa los grupos de simultaneidad sobre la grilla semanal.
    """
    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        raise ValueError(f"Plan '{plan_id}' no encontrado")

    aulas_db = list(session.exec(select(AulaDB)).all())
    aulas = [
        AulaSlot(id=a.id, tipo=a.tipo, capacidad=a.capacidad)
        for a in aulas_db
    ]
    aula_sede_id: dict[str, str] = {a.id: a.sede_id for a in aulas_db}

    # Map materia_codigo -> set[aula_id] desde MateriaLaboratorioDB.
    matlab_pairs = list(session.exec(select(MateriaLaboratorioDB)).all())
    materia_lab_map: dict[str, set[str]] = {}
    for ml in matlab_pairs:
        materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

    # Materias del plan (para filtrar virtuales y para R5).
    materias_db = list(session.exec(select(MateriaDB)).all())
    # materia_codigo -> bool: virtualidad DECLARADA en la materia (raiz
    # de la cadena de resolucion jerarquica).
    materia_virtual: dict[str, bool] = {m.codigo: m.virtual for m in materias_db}
    hteo: dict[str, float] = {
        m.codigo: float(m.horas_teoria or 0.0) for m in materias_db
    }
    hlab: dict[str, float] = {
        m.codigo: float(m.horas_laboratorio or 0.0) for m in materias_db
    }

    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    comision_ids = {c.id for c in comisiones}
    # Mapeos para R9: cada comisión a su dictado y a su coef actual.
    dictado_de_comision: dict[str, Optional[str]] = {
        c.id: c.dictado_id for c in comisiones
    }
    coef_actual: dict[str, float] = {
        c.id: float(c.coef_asignacion) for c in comisiones
    }

    # Dictados del ciclo: leemos el flag `virtual` de cada dictado
    # (Optional[bool]) para poder resolver la virtualidad efectiva de
    # cada horario via `resolve_virtual` (regla "nivel mas especifico
    # manda": horario > dictado > materia). Permite marcar como
    # "virtual solo en este ciclo" a recursados u ofertas excepcionales
    # sin tocar el catalogo `MateriaDB.virtual`.
    #
    # Nota: ComisionDB.dictado_id no esta siempre poblado (las
    # comisiones generadas desde plan generation suelen quedar con
    # None), asi que resolvemos via (materia_codigo, ciclo_id) usando
    # DictadoCicloDB.
    from src.database.models import DictadoCicloDB
    from src.services.resolucion_jerarquica import resolve_virtual
    materia_dictado_virtual: dict[str, bool | None] = {}
    if plan.ciclo_id is not None:
        rows = session.exec(
            select(DictadoDB.materia_codigo, DictadoDB.virtual)
            .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)  # type: ignore[arg-type]
            .where(DictadoCicloDB.ciclo_id == plan.ciclo_id)
        ).all()
        for materia_codigo, es_virtual in rows:
            materia_dictado_virtual[materia_codigo] = es_virtual

    horarios_db = list(session.exec(
        select(HorarioDB).where(HorarioDB.comision_id.in_(comision_ids))  # type: ignore[attr-defined]
    ).all()) if comision_ids else []

    warnings: list[str] = []

    horarios: list[HorarioSlot] = []
    materia_de_horario: dict[str, str] = {}
    comision_de_horario: dict[str, str] = {}
    dur: dict[str, float] = {}
    # Override de carrera para la restriccion de sede (R10). Se llena
    # solo con horarios cuya comisión tiene `carrera_asignada != None`.
    # Se usa mas abajo para decidir sedes admisibles por horario en vez
    # de por materia. Ver RF-LP-15.
    #
    # El override vive a nivel COMISIÓN (no a nivel horario individual)
    # porque semanticamente "la comisión está organizada para una
    # carrera puntual" — todos los horarios de la comisión heredan la
    # restricción de sede correspondiente.
    carrera_asignada_por_comision: dict[str, str | None] = {
        c.id: c.carrera_asignada for c in comisiones
    }
    carrera_asignada_de_horario: dict[str, str] = {}

    for h in horarios_db:
        # Resolver virtualidad con jerarquia horario > dictado > materia.
        # Los tres niveles pueden ser None (heredar del padre) excepto
        # materia, que es bool concreto (raiz).
        es_virtual = resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dictado_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        )
        if es_virtual:
            warnings.append(
                f"Horario {h.id} excluido: virtual "
                f"(materia {h.codigo_materia})"
            )
            continue
        _car = carrera_asignada_por_comision.get(h.comision_id)
        if _car:
            carrera_asignada_de_horario[h.id] = _car
        # Red de seguridad: si el horario tiene tipo_clase=None pero la
        # materia declara una sola modalidad (hteo>0 y hlab=0, o
        # viceversa), inferimos el tipo en memoria. No persistimos: si
        # el operador quiere ver el cambio reflejado en la DB, debe
        # correr la acción "Auto-completar tipos" en el panel del plan.
        # Esto evita variables binarias t[h] redundantes en el LP.
        tipo_efectivo = h.tipo_clase
        if tipo_efectivo is None:
            mat_hteo = hteo.get(h.codigo_materia, 0.0)
            mat_hlab = hlab.get(h.codigo_materia, 0.0)
            if mat_hteo > 0 and mat_hlab == 0:
                tipo_efectivo = "teorica"
            elif mat_hlab > 0 and mat_hteo == 0:
                tipo_efectivo = "laboratorio"
        horarios.append(HorarioSlot(
            id=h.id,
            dia=h.dia,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            materia_codigo=h.codigo_materia,
            tipo_clase=tipo_efectivo,
        ))
        materia_de_horario[h.id] = h.codigo_materia
        comision_de_horario[h.id] = h.comision_id
        # Duración en horas (fracciones permitidas).
        hi = h.hora_inicio
        hf = h.hora_fin
        dur[h.id] = (
            (hf.hour + hf.minute / 60 + hf.second / 3600)
            - (hi.hour + hi.minute / 60 + hi.second / 3600)
        )

    # Forecast por comisión, multiplicar por duración para tener
    # esperados por horario (en realidad es lo mismo: insc[h] = total ×
    # coef_asignacion del comisión, no depende de la duración del horario).
    insc_por_comision = get_inscriptos_esperados_por_comision(session, plan_id)

    insc: dict[str, float] = {}
    for h in horarios:
        cid = comision_de_horario[h.id]
        if cid in insc_por_comision:
            insc[h.id] = insc_por_comision[cid]
        else:
            warnings.append(
                f"Sin forecast para comisión {cid} (horario {h.id}); "
                f"asumiendo 0 esperados"
            )
            insc[h.id] = 0.0

    # total_esp por materia (para R9 con α activo). Reusa la misma
    # lógica de get_inscriptos_esperados_por_comision pero antes del
    # producto por coef.
    from src.database.models import CicloDB
    from src.services.forecast_service import get_forecast_for_materia
    plan_obj = session.get(PlanificacionCursadaDB, plan_id)
    ciclo_obj = session.get(CicloDB, plan_obj.ciclo_id) if plan_obj and plan_obj.ciclo_id else None
    total_esp: dict[str, float] = {}
    if ciclo_obj is not None:
        cuatri_lbl = f"{ciclo_obj.numero}C"
        materias_unicas = sorted({h.materia_codigo for h in horarios})
        for mc in materias_unicas:
            f_anual = get_forecast_for_materia(session, plan_id, mc, "Anual")
            f_cuatri = get_forecast_for_materia(session, plan_id, mc, cuatri_lbl)
            if f_anual is not None:
                total_esp[mc] = float(f_anual.valor)
            elif f_cuatri is not None:
                total_esp[mc] = float(f_cuatri.valor)

    # Compatibilidad pre-computada (R3 sin sede).
    compat: dict[tuple[str, str], bool] = {}
    for h in horarios:
        lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas:
            compat[(h.id, a.id)] = compute_compat(h, a, lab_aulas_m)

    # R10 — Restriccion de sede por carrera. Se aplica como filtro
    # adicional sobre `compat`: si el aula no esta en una sede admisible
    # para el horario, se descarta el par.
    #
    # La sede admisible se resuelve por HORARIO (no solo por materia)
    # para soportar el override `ComisionDB.carrera_asignada` — usado
    # cuando una comision de una materia comun se organiza pensada
    # para alumnos de una carrera de otra sede (ej. Fisica III comision
    # electronica en Siberia). Si la comisión del horario tiene el
    # override, la sede se resuelve via esa carrera; si no, via la
    # materia (regla habitual).
    #
    # Excepcion: cuando el aula esta en MateriaLaboratorioDB para la
    # materia, prevalece la compatibilidad de laboratorio sobre la
    # restriccion de sede (un lab compatible se puede usar aunque no
    # este en la sede default de la carrera/comunes).
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_carrera,
        sedes_admisibles_para_materia,
    )
    materias_unicas_sede = sorted({h.materia_codigo for h in horarios})
    sedes_admisibles_por_materia: dict[str, set[str] | None] = {
        mc: sedes_admisibles_para_materia(session, mc)
        for mc in materias_unicas_sede
    }
    carreras_override_unicas = sorted(set(carrera_asignada_de_horario.values()))
    sedes_admisibles_por_carrera_override: dict[str, set[str] | None] = {
        cc: sedes_admisibles_para_carrera(session, cc)
        for cc in carreras_override_unicas
    }
    for h in horarios:
        carrera_override = carrera_asignada_de_horario.get(h.id)
        if carrera_override:
            admisibles = sedes_admisibles_por_carrera_override.get(
                carrera_override
            )
        else:
            admisibles = sedes_admisibles_por_materia.get(h.materia_codigo)
        if admisibles is None:
            # Sin restriccion de sede para este horario (fallback "todas").
            continue
        lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas:
            if not compat[(h.id, a.id)]:
                continue
            if a.id in lab_aulas_m:
                # Lab compatible prevalece sobre restriccion de sede.
                continue
            if aula_sede_id.get(a.id) not in admisibles:
                compat[(h.id, a.id)] = False

    sim_groups = compute_simultaneidad_groups(horarios)

    return LPInputs(
        horarios=horarios,
        aulas=aulas,
        insc=insc,
        dur=dur,
        materia_de_horario=materia_de_horario,
        comision_de_horario=comision_de_horario,
        compat=compat,
        sim_groups=sim_groups,
        materia_lab_map=materia_lab_map,
        hteo=hteo,
        hlab=hlab,
        total_esp=total_esp,
        dictado_de_comision=dictado_de_comision,
        coef_actual=coef_actual,
        warnings=warnings,
    )


def diagnose(inputs: LPInputs) -> InfeasibilityDiagnosis:
    """Wrapper sobre ``diagnose_infeasibility`` + pre-validación de
    partición teoría/lab. Toma un LPInputs y devuelve un Diagnóstico
    con todas las causas estructurales detectables sin correr el LP."""
    diag = diagnose_infeasibility(
        horarios=inputs.horarios,
        aulas=inputs.aulas,
        materia_lab_map=inputs.materia_lab_map,
        sim_groups=inputs.sim_groups,
        compat_override=inputs.compat,
    )
    # Pre-validación R5 (partición factible).
    horarios_por_comision: dict[str, list[tuple[str, float, str | None]]] = {}
    for h in inputs.horarios:
        cid = inputs.comision_de_horario[h.id]
        horarios_por_comision.setdefault(cid, []).append(
            (h.id, inputs.dur[h.id], h.tipo_clase)
        )
    materia_de_comision: dict[str, str] = {}
    for cid, lista in horarios_por_comision.items():
        if lista:
            materia_de_comision[cid] = inputs.materia_de_horario[lista[0][0]]
    problemas_particion = validar_particion_factible(
        horarios_por_comision=horarios_por_comision,
        hteo=inputs.hteo,
        hlab=inputs.hlab,
        materia_de_comision=materia_de_comision,
    )
    diag.particion_problemas = problemas_particion  # type: ignore[attr-defined]
    return diag


# =============================================================================
# Modelo PuLP
# =============================================================================

@dataclass
class LPSolution:
    """Resultado de resolver el LP."""
    status: str  # "optimal" | "infeasible" | "timeout" | "error"
    objective: Optional[float]
    # horario_id -> aula_id elegida (sólo horarios con asignación).
    x_assignments: dict[str, str]
    # horario_id -> tipo_clase resuelto ("teorica"|"laboratorio"). Sólo
    # entrega las claves para horarios que tenían tipo_clase=None y el
    # LP les puso un valor (R5/R6). Para los que tenían tipo fijado, no
    # aparecen acá (su tipo no cambió).
    tipo_resuelto: dict[str, str]
    over: dict[str, float]   # horario_id -> over[h]
    under: dict[str, float]  # horario_id -> under[h]
    # comision_id -> α* propuesto (sólo si activar_alpha=True). Vacío
    # cuando el toggle estaba apagado.
    alpha_resuelto: dict[str, float] = field(default_factory=dict)
    solver_seconds: float = 0.0
    error_message: str = ""


def build_model(
    inputs: LPInputs,
    config: LPConfig,
    *,
    relax: Optional[set[str]] = None,
) -> tuple[pulp.LpProblem, dict]:
    """Instancia el modelo PuLP con R1, R3 (compatibilidad), R4 (no
    doble booking), R5 (partición teoría/lab), R6 (consistencia
    tipo↔aula), R7 (penalty de capacidad).

    Args:
        inputs: conjuntos y parámetros precomputados.
        config: configuración del LP (lambdas, tolerancias, alpha).
        relax: conjunto opcional de IDs de restricciones a OMITIR del
            modelo. Valores soportados: ``"R4"``, ``"R5"``, ``"R6"``.
            Útil para diagnóstico IIS por relajación selectiva: cuando
            el modelo completo es infactible y las cotas estructurales
            no detectan causas, se prueba relajar cada Ri por separado
            para identificar la culpable. Default: ``None`` (sin
            relajación, todas las restricciones activas).

    Returns:
        (problem, vars_dict) donde vars_dict tiene las variables x, t,
        over, under indexadas para que ``solve`` las pueda leer.
    """
    relax_set = relax or set()
    prob = pulp.LpProblem("asignacion_aulas", pulp.LpMinimize)

    # Variables x[h, a] solo para pares compatibles (R3 pre-computada).
    # tuplado (hid, aid) -> variable binaria. Si un par no es compatible, no hay variable y el modelo no puede asignar esa aula a ese horario.
    # o sea basicamente la variable x se lee como "x[h,a] existe y es 1" <=> "h se asigna a a", y si el par no es compatible, x[h,a] no existe y por lo tanto h no puede asignarse a a.
    x: dict[tuple[str, str], pulp.LpVariable] = {}
    #     horario_id, aula_id , valor de x (var. de asignacion)
    for (hid, aid), is_compat in inputs.compat.items():
        if not is_compat:
            continue
        x[(hid, aid)] = pulp.LpVariable(
            f"x_{hid}_{aid}", cat=pulp.LpBinary,
        )

    # Variables t[h]: 1 = laboratorio, 0 = teoría. Sólo se crean para
    # horarios con tipo_clase=None (los demás son constantes en el
    # modelo: 0 si "teorica", 1 si "laboratorio").
    horarios_map = {h.id: h for h in inputs.horarios}
    t: dict[str, pulp.LpVariable] = {}
    t_const: dict[str, int] = {}
    for h in inputs.horarios:
        if h.tipo_clase == "teorica":
            t_const[h.id] = 0
        elif h.tipo_clase == "laboratorio":
            t_const[h.id] = 1
        else:
            t[h.id] = pulp.LpVariable(f"t_{h.id}", cat=pulp.LpBinary)

    # Variables α[k]: una por comisión, sólo cuando el toggle está
    # activo. R9: Σ α[k] = 1 por dictado. Si toggle OFF, alpha queda
    # vacío y se usa coef_asignacion de la base como constante en R7.
    alpha: dict[str, pulp.LpVariable] = {}
    if config.activar_alpha:
        comision_ids_unicos = {
            inputs.comision_de_horario[h.id] for h in inputs.horarios
        }
        for cid in comision_ids_unicos:
            alpha[cid] = pulp.LpVariable(
                f"a_{cid}", lowBound=0, upBound=1, cat=pulp.LpContinuous,
            )
        # R9: Σ α por dictado = 1.
        por_dictado: dict[str, list[str]] = {}
        for cid in comision_ids_unicos:
            did = inputs.dictado_de_comision.get(cid)
            if did is None:
                # Comisión sin dictado: forzamos α=1 (peso completo de
                # su materia, no hay con quién compartir).
                continue
            por_dictado.setdefault(did, []).append(cid)
        for did, cids in por_dictado.items():
            prob += (
                pulp.lpSum(alpha[c] for c in cids) == 1,
                f"R9_{did}",
            )
        # Comisiones sin dictado: α=1 forzado.
        for cid in comision_ids_unicos:
            if inputs.dictado_de_comision.get(cid) is None:
                prob += alpha[cid] == 1, f"R9_solo_{cid}"

    # Variables over[h], under[h].
    over_vars: dict[str, pulp.LpVariable] = {}
    under_vars: dict[str, pulp.LpVariable] = {}
    for h in inputs.horarios:
        over_vars[h.id] = pulp.LpVariable(
            f"over_{h.id}", lowBound=0, cat=pulp.LpContinuous,
        )
        under_vars[h.id] = pulp.LpVariable(
            f"under_{h.id}", lowBound=0, cat=pulp.LpContinuous,
        )

    # Función objetivo.
    prob += (
        config.lambda_over * pulp.lpSum(over_vars.values())
        + config.lambda_under * pulp.lpSum(under_vars.values())
    ), "objetivo"

    # R1: asignación única.
    aulas_por_horario: dict[str, list[str]] = {}
    for (hid, aid), _ in x.items():
        aulas_por_horario.setdefault(hid, []).append(aid)

    for h in inputs.horarios:
        compat_aulas = aulas_por_horario.get(h.id, [])
        if not compat_aulas:
            # Horario sin ninguna aula compatible → infactible por
            # construcción. Lo marcamos via una restricción imposible
            # para que el solver lo reporte limpio.
            prob += pulp.lpSum([]) == 1, f"R1_sin_aulas_compat_{h.id}"
            continue
        prob += (
            pulp.lpSum(x[(h.id, aid)] for aid in compat_aulas) == 1,
            f"R1_{h.id}",
        )

    # R4: para cada (aula, grupo de simultaneidad), suma de x ≤ 1.
    if "R4" not in relax_set:
        for gi, grupo in enumerate(inputs.sim_groups):
            for a in inputs.aulas:
                terms = [
                    x[(hid, a.id)]
                    for hid in grupo
                    if (hid, a.id) in x
                ]
                if len(terms) >= 2:
                    prob += (
                        pulp.lpSum(terms) <= 1,
                        f"R4_g{gi}_{a.id}",
                    )

    # R5: Partición teoría/lab por comisión.
    # Σ_{h ∈ k} dur[h] · t[h] = hlab[materia(k)]
    # (la ecuación de teoría es redundante con la suma total y se omite).
    horarios_por_comision: dict[str, list[str]] = {}
    for hid, cid in inputs.comision_de_horario.items():
        horarios_por_comision.setdefault(cid, []).append(hid)

    if "R5" not in relax_set:
        for cid, hids in horarios_por_comision.items():
            # Materia de la comisión: la sacamos de cualquier horario.
            if not hids:
                continue
            m = inputs.materia_de_horario[hids[0]]
            hl = inputs.hlab.get(m, 0.0)
            # Si la comisión no tiene horarios con tipo_clase=None y la
            # suma fijada ya iguala hlab, no hay nada que el LP decida.
            # Esa restricción la chequeamos como pre-condición en
            # validar_particion_factible; acá la agregamos siempre como
            # restricción para que el LP arroje infactibilidad si los
            # números no cuadran.
            terms = []
            for hid in hids:
                d = inputs.dur[hid]
                if hid in t:
                    terms.append(d * t[hid])
                else:
                    terms.append(d * t_const[hid])
            prob += (
                pulp.lpSum(terms) == hl,
                f"R5_lab_{cid}",
            )

    # R6: Pool de aulas para tipo decidido (sólo aplica cuando
    # tipo_clase=None y por lo tanto t[h] es variable).
    if "R6" not in relax_set:
        aulas_teoricas = {a.id for a in inputs.aulas if a.tipo == "teorica"}
        for h in inputs.horarios:
            if h.id not in t:
                continue  # tipo fijado, R3 lo cubre
            lab_aulas_m = inputs.materia_lab_map.get(h.materia_codigo, set())
            # R6a: si t[h] = 0 (teórica), x[h, a]=0 para a ∉ A_t.
            # Equivalente: Σ_{a ∈ A_t} x[h, a] ≥ 1 - t[h].
            terms_teo = [
                x[(h.id, aid)] for aid in aulas_teoricas
                if (h.id, aid) in x
            ]
            if terms_teo:
                prob += (
                    pulp.lpSum(terms_teo) >= 1 - t[h.id],
                    f"R6teo_{h.id}",
                )
            else:
                # No hay aulas teóricas: t[h] DEBE ser 1.
                prob += t[h.id] == 1, f"R6teo_forzado_{h.id}"
            # R6b: si t[h] = 1 (laboratorio), x[h, a]=0 para a ∉ A_lab(m).
            terms_lab = [
                x[(h.id, aid)] for aid in lab_aulas_m
                if (h.id, aid) in x
            ]
            if terms_lab:
                prob += (
                    pulp.lpSum(terms_lab) >= t[h.id],
                    f"R6lab_{h.id}",
                )
            else:
                # No hay labs compatibles: t[h] DEBE ser 0.
                prob += t[h.id] == 0, f"R6lab_forzado_{h.id}"

    # R7: linealización del penalty de capacidad.
    # Cuando α está activo, insc[h] no es una constante sino la
    # expresión lineal `total_esp[materia(h)] · α[comision(h)]`.
    cap_por_aula = {a.id: a.capacidad for a in inputs.aulas}
    for h in inputs.horarios:
        compat_aulas = aulas_por_horario.get(h.id, [])
        if config.activar_alpha:
            cid = inputs.comision_de_horario[h.id]
            mat = inputs.materia_de_horario[h.id]
            total_m = inputs.total_esp.get(mat, 0.0)
            insc_expr = total_m * alpha[cid]
        else:
            insc_expr = inputs.insc[h.id]
        # over[h] >= insc - sum(x[h,a] * cap[a] * (1 + tol_over))
        prob += (
            over_vars[h.id]
            >= insc_expr
            - pulp.lpSum(
                x[(h.id, aid)] * cap_por_aula[aid] * (1 + config.tol_over)
                for aid in compat_aulas
            ),
            f"R7over_{h.id}",
        )
        # under[h] >= sum(x[h,a] * cap[a] * (1 - tol_under)) - insc
        prob += (
            under_vars[h.id]
            >= pulp.lpSum(
                x[(h.id, aid)] * cap_por_aula[aid] * (1 - config.tol_under)
                for aid in compat_aulas
            )
            - insc_expr,
            f"R7under_{h.id}",
        )

    return prob, {
        "x": x, "t": t, "alpha": alpha,
        "over": over_vars, "under": under_vars,
    }


def solve(
    prob: pulp.LpProblem,
    vars_dict: dict,
    config: LPConfig,
) -> LPSolution:
    """Corre el solver y extrae la solución."""
    solver = pulp.PULP_CBC_CMD(
        msg=False,
        timeLimit=config.timeout_seconds,
    )

    t0 = _time_mod.time()
    try:
        status_code = prob.solve(solver)
    except Exception as exc:
        return LPSolution(
            status="error",
            objective=None,
            x_assignments={},
            tipo_resuelto={},
            over={},
            under={},
            alpha_resuelto={},
            solver_seconds=_time_mod.time() - t0,
            error_message=f"Solver error: {exc}",
        )
    elapsed = _time_mod.time() - t0

    status_str = pulp.LpStatus[status_code].lower()

    # PuLP status codes: 1 = Optimal, 0 = Not Solved, -1 = Infeasible,
    # -2 = Unbounded, -3 = Undefined.
    if status_code != 1:
        return LPSolution(
            status="infeasible" if status_str == "infeasible" else status_str,
            objective=None,
            x_assignments={},
            tipo_resuelto={},
            over={},
            under={},
            alpha_resuelto={},
            solver_seconds=elapsed,
            error_message=f"Solver no encontró solución óptima: {status_str}",
        )

    # Extraer asignaciones.
    x = vars_dict["x"]
    t_vars = vars_dict["t"]
    alpha_vars = vars_dict.get("alpha", {})
    over_vars = vars_dict["over"]
    under_vars = vars_dict["under"]

    x_assignments: dict[str, str] = {}
    for (hid, aid), var in x.items():
        v = var.value()
        if v is not None and v > 0.5:
            x_assignments[hid] = aid

    tipo_resuelto: dict[str, str] = {}
    for hid, var in t_vars.items():
        v = var.value()
        if v is None:
            continue
        tipo_resuelto[hid] = "laboratorio" if v > 0.5 else "teorica"

    alpha_resuelto: dict[str, float] = {}
    for cid, var in alpha_vars.items():
        v = var.value()
        if v is not None:
            alpha_resuelto[cid] = float(v)

    over = {hid: (var.value() or 0.0) for hid, var in over_vars.items()}
    under = {hid: (var.value() or 0.0) for hid, var in under_vars.items()}

    return LPSolution(
        status="optimal",
        objective=pulp.value(prob.objective),
        x_assignments=x_assignments,
        tipo_resuelto=tipo_resuelto,
        over=over,
        under=under,
        alpha_resuelto=alpha_resuelto,
        solver_seconds=elapsed,
    )


# =============================================================================
# Wrapper end-to-end (sin persistencia)
# =============================================================================

def run_lp_dry(
    session: Session,
    plan_id: str,
    config: Optional[LPConfig] = None,
) -> tuple[LPInputs, LPSolution]:
    """Construye y resuelve el LP, sin tocar la DB.

    Útil para tests y para una corrida exploratoria que sólo reporta
    sin persistir. La aplicación a ``ClaseDB`` y la persistencia en
    ``LPRunDB`` viven en ``run_lp``.
    """
    cfg = config or LPConfig()
    inputs = build_inputs(session, plan_id, cfg)
    prob, vars_dict = build_model(inputs, cfg)
    solution = solve(prob, vars_dict, cfg)
    return inputs, solution


# =============================================================================
# Aplicación a ClaseDB y persistencia (Fase 2)
# =============================================================================

@dataclass
class ApplyResult:
    """Resultado de propagar la solución del LP a las ClaseDB."""
    n_clases_actualizadas: int = 0
    n_ediciones_manuales_respetadas: int = 0


def apply_solution(
    session: Session,
    plan_id: str,
    solution: LPSolution,
    fecha_desde: date,
    respetar_manuales: bool = True,
) -> ApplyResult:
    """Aplica la solución del asignador al PATRÓN (``HorarioDB``).

    Para cada ``(horario_id, aula_id)`` en ``solution.x_assignments``:

    1. Si ``respetar_manuales=True`` y el horario tiene
       ``aula_asignada_manualmente=True``, **NO se toca** (la aula la
       eligió el usuario a mano y quiere que se respete).
    2. Si no, setea ``HorarioDB.aula_id = aula_id`` y baja el flag
       (queda como asignada por el asignador). Si el asignador
       resolvió el ``tipo_clase`` y el horario lo tenía en None,
       también lo persiste.
    3. Propaga el aula a las ``ClaseDB`` no ejecutadas del plan (con
       ``fecha >= fecha_desde``) como cache técnico.

    ``ClaseDB.aula_asignada_manualmente`` está deprecado (se usaba en
    la era de clases puntuales); acá lo bajamos siempre para mantener
    consistencia.
    """
    if solution.status != "optimal":
        return ApplyResult()

    apply_result = ApplyResult()

    for horario_id, aula_id in solution.x_assignments.items():
        # 1) Chequear si el patrón está protegido como manual.
        horario = session.get(HorarioDB, horario_id)
        if horario is None:
            continue

        if respetar_manuales and horario.aula_asignada_manualmente:
            # Patrón blindado. NO tocamos el patrón pero SÍ propagamos
            # el aula del patrón a las ClaseDB no ejecutadas (por si
            # las clases se generaron antes de que el patrón se marcara
            # manual y quedaron con otra aula).
            apply_result.n_ediciones_manuales_respetadas += 1
            if horario.aula_id is not None:
                # Traer todas las clases del horario y filtrar en Python
                # (evita el problema de NULL != <valor> en SQL, que
                # devuelve NULL en lugar de TRUE).
                clases_todas = list(session.exec(
                    select(ClaseDB).where(
                        ClaseDB.horario_id == horario_id,
                        ClaseDB.fecha >= fecha_desde,
                        ClaseDB.executed == False,  # noqa: E712
                        ClaseDB.plan_cursada_id == plan_id,
                    )
                ).all())
                for c in clases_todas:
                    if c.aula_id != horario.aula_id:
                        c.aula_id = horario.aula_id
                        session.add(c)
            continue

        # 2) Escribir al patrón.
        tipo_nuevo = solution.tipo_resuelto.get(horario_id)
        horario.aula_id = aula_id
        horario.aula_asignada_manualmente = False
        if tipo_nuevo is not None and horario.tipo_clase is None:
            horario.tipo_clase = tipo_nuevo
        session.add(horario)

        # 3) Propagar a clases (cache técnico).
        query = select(ClaseDB).where(
            ClaseDB.horario_id == horario_id,
            ClaseDB.fecha >= fecha_desde,
            ClaseDB.executed == False,  # noqa: E712
            ClaseDB.plan_cursada_id == plan_id,
        )
        clases = list(session.exec(query).all())
        for c in clases:
            c.aula_id = aula_id
            c.aula_asignada_manualmente = False
            if tipo_nuevo is not None and c.tipo_clase is None:
                c.tipo_clase = tipo_nuevo
            session.add(c)
            apply_result.n_clases_actualizadas += 1

    session.commit()
    return apply_result


def _build_details_json(
    inputs: LPInputs,
    solution: LPSolution,
    config: LPConfig,
    session: Session,
) -> dict:
    """Arma el dict que se serializa en LPRunDB.details_json."""
    cap_por_aula = {a.id: a.capacidad for a in inputs.aulas}
    detalle_horarios = []
    n_sobre = 0
    n_sub = 0
    for h in inputs.horarios:
        aula_id = solution.x_assignments.get(h.id)
        cap = cap_por_aula.get(aula_id, 0) if aula_id else 0
        insc = inputs.insc.get(h.id, 0.0)
        delta = cap - insc
        over = solution.over.get(h.id, 0.0)
        under = solution.under.get(h.id, 0.0)
        if over > 1e-6:
            estado = "sobre"
            n_sobre += 1
        elif under > cap * config.tol_under + 1e-6 and aula_id is not None:
            estado = "sub"
            n_sub += 1
        else:
            estado = "ok"
        detalle_horarios.append({
            "horario_id": h.id,
            "aula_id": aula_id,
            "tipo_clase": h.tipo_clase,
            "insc": insc,
            "cap": cap,
            "delta": delta,
            "over": over,
            "under": under,
            "estado": estado,
        })
    # Heatmap PARTICIONADO POR SEDE — la herramienta principal para
    # ver exactamente en qué sede × franja × tipo de aula falta capacidad
    # (la restricción de sedes R10 puede generar saturación).
    # El heatmap de carga global (día × franja, sin discriminar sede
    # ni tipo) se deprecó porque no aportaba nada útil sobre este.
    from src.services.asignacion_aulas_helpers import (
        compute_heatmap_por_sede,
    )
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_materia,
    )
    from src.database.models import AulaDB as _AulaDB
    from src.database.models import SedeDB as _SedeDB
    from sqlmodel import select as _select
    # Pre-cargas necesarias para el heatmap por sede.
    materias_unicas_sede = sorted({h.materia_codigo for h in inputs.horarios})
    sedes_admis_por_mat: dict[str, set[str] | None] = {
        mc: sedes_admisibles_para_materia(session, mc)
        for mc in materias_unicas_sede
    }
    aulas_db = list(session.exec(_select(_AulaDB)).all())
    aula_sede_id_map: dict[str, str] = {a.id: a.sede_id for a in aulas_db}
    sedes_db = list(session.exec(_select(_SedeDB)).all())
    sede_nombre_map: dict[str, str] = {s.id: s.nombre for s in sedes_db}
    heatmap_por_sede = compute_heatmap_por_sede(
        inputs.horarios, inputs.aulas, inputs.materia_lab_map,
        sedes_admis_por_mat, aula_sede_id_map, sede_nombre_map,
    )
    # Si hubo redistribución de α, registramos la propuesta junto con
    # el coef actual para que la UI pueda mostrar el diff sin re-correr
    # el LP.
    alpha_diff = []
    if solution.alpha_resuelto:
        for cid, alpha_new in solution.alpha_resuelto.items():
            alpha_old = inputs.coef_actual.get(cid, 0.0)
            alpha_diff.append({
                "comision_id": cid,
                "alpha_actual": alpha_old,
                "alpha_propuesto": alpha_new,
                "delta": alpha_new - alpha_old,
            })
    return {
        "horarios": detalle_horarios,
        "n_sobreocupados": n_sobre,
        "n_subutilizados": n_sub,
        "heatmap_por_sede": heatmap_por_sede,
        "alpha_propuestos": alpha_diff,
    }


def persist_run(
    session: Session,
    plan_id: str,
    config: LPConfig,
    inputs: LPInputs,
    solution: LPSolution,
    fecha_desde: date,
    apply_result: ApplyResult,
    diagnosis: Optional[InfeasibilityDiagnosis] = None,
    iis: Optional[dict] = None,
) -> LPRunDB:
    """Inserta una fila en LPRunDB con la corrida y su resumen.

    Si ``solution.status != 'optimal'`` y se pasa un ``diagnosis``, el
    detalle estructural se persiste en details_json y se incorpora a
    ``error_message`` un resumen humano.

    Args:
        iis: opcional. Resultado de ``_run_iis_relajacion`` cuando se
            ejecutó (sólo cuando el solver dio infactible Y el
            diagnóstico estructural quedó vacío). Estructura
            documentada en esa función.
    """
    details = _build_details_json(inputs, solution, config, session)
    n_sobre = details["n_sobreocupados"]
    n_sub = details["n_subutilizados"]
    if iis is not None:
        details["iis"] = iis

    error_message = solution.error_message
    if diagnosis is not None:
        details["infeasibility_diagnosis"] = {
            "horarios_sin_aula_compatible":
                diagnosis.horarios_sin_aula_compatible,
            "franjas_saturadas": diagnosis.franjas_saturadas,
            "saturacion_por_tipo": diagnosis.saturacion_por_tipo,
            "hall_violators": diagnosis.hall_violators,
            "inventario_aulas": diagnosis.inventario_aulas,
            "particion_problemas": diagnosis.particion_problemas,
        }
        # Solo anteponer resumen estructural al error si el solver
        # NO encontró solución óptima. Si el solver resolvió `optimal`,
        # el modelo era factible y no corresponde mostrar "infactible
        # estructural" en el summary (ni siquiera si el diagnóstico
        # detectó saturaciones — el LP las toleró vía slack).
        # Además, solo generamos el mensaje si `to_messages()` produce
        # items: `particion_problemas` cuenta para `is_infeasible()`
        # pero no se serializa en messages, y quedaba un header vacío.
        if solution.status != "optimal" and diagnosis.is_infeasible():
            msgs = diagnosis.to_messages()
            if msgs:
                error_message = (
                    "Infactibilidad estructural detectada:\n"
                    + "\n".join(msgs[:5])
                    + (f"\n(+ {len(msgs) - 5} más)" if len(msgs) > 5 else "")
                    + (f"\n— Solver: {solution.error_message}"
                       if solution.error_message else "")
                )

    # Si se ejecutó IIS, anteponer un resumen humano al error_message.
    # Usamos `principal` (filtrado de falsos positivos) en vez de
    # listar todas las restricciones que arreglaron al relajarse —
    # eso confunde al usuario cuando el problema real es solo R4 y
    # R5/R6 aparecen por libertad extra (efecto secundario).
    if iis is not None:
        principal = iis.get("principal")
        descripciones_cortas = {
            "R4": "más clases simultáneas que aulas disponibles",
            "R5": "horas declaradas vs horarios cargados (teoría/lab)",
            "R6": "horarios sin tipo determinado sin aula compatible",
        }
        if principal:
            desc = descripciones_cortas.get(principal, principal)
            _iis_resumen = (
                f"🔍 Causa probable: {desc}. "
                "Mirá la sección 'Diagnóstico cruzado' abajo para "
                "detalles y acciones específicas."
            )
        else:
            _iis_resumen = (
                "🔍 No se pudo identificar una causa única. La "
                "infactibilidad combina varias condiciones del modelo. "
                "Mirá el detalle abajo."
            )
        error_message = (
            (error_message + "\n\n" if error_message else "")
            + _iis_resumen
        )

    run = LPRunDB(
        plan_cursada_id=plan_id,
        fecha_desde=fecha_desde,
        lambda_over=config.lambda_over,
        lambda_under=config.lambda_under,
        tol_over=config.tol_over,
        tol_under=config.tol_under,
        activar_alpha=config.activar_alpha,
        respetar_ediciones_manuales=config.respetar_ediciones_manuales,
        timeout_seconds=config.timeout_seconds,
        status=solution.status,
        objective_value=solution.objective,
        n_horarios_total=len(inputs.horarios),
        n_horarios_asignados=len(solution.x_assignments),
        n_clases_actualizadas=apply_result.n_clases_actualizadas,
        n_clases_sobreocupadas=n_sobre,
        n_clases_subutilizadas=n_sub,
        n_ediciones_manuales_respetadas=apply_result.n_ediciones_manuales_respetadas,
        solver_seconds=solution.solver_seconds,
        error_message=error_message,
        details_json=json.dumps(details, default=str),
    )
    session.add(run)
    session.commit()
    session.refresh(run)
    return run


def get_latest_run(session: Session, plan_id: str) -> Optional[LPRunDB]:
    """Devuelve el último LPRunDB del plan, o None si no hay ninguno."""
    return session.exec(
        select(LPRunDB)
        .where(LPRunDB.plan_cursada_id == plan_id)
        .order_by(LPRunDB.run_at.desc())  # type: ignore[attr-defined]
    ).first()


def _run_iis_relajacion(
    inputs: LPInputs,
    config: LPConfig,
) -> dict:
    """Diagnóstico cruzado por relajación selectiva (IIS).

    Cuando el solver da `infeasible` y las cotas estructurales no
    detectan ninguna causa, relajamos cada restricción "blanda" (R4,
    R5, R6) por separado y re-corremos el modelo. Para cada
    relajación que hace al modelo factible, la marcamos como
    *candidata* a culpable.

    **Filtro de falsos positivos**: la relajación independiente
    sufre de un problema conocido — cuando hay una restricción
    fuertemente saturadora (típicamente R4: muchas clases
    simultáneas vs pocas aulas), relajar R5 o R6 también arregla,
    porque eso le da al solver más libertad y la restricción real
    deja de morder. Para evitar reportar R5/R6 como culpables
    espurios:

    - **R5** se descarta como culpable si NO hay materias con
      `hlab_declarado > 0` cuyo `lab_resuelto` haya quedado en otro
      valor. Es decir: si todas las materias afectadas tienen
      `hlab=0` y el LP les puso lab solo porque le sirvió, no es
      problema de catálogo, es libertad recién obtenida.
    - **R6** se descarta como culpable si todos los horarios con
      `tipo_clase=None` admiten al menos una alternativa válida (al
      menos un aula teórica O al menos un lab compatible).
      Comprobado a priori con `materia_lab_map` y el inventario de
      teóricas.
    - **R4** se considera causa principal cuando aparece junto con
      R5/R6 falsos positivos (los otros sólo "ayudan" porque le
      dan al solver libertad extra que oculta el problema real).

    Args:
        inputs: los mismos `LPInputs` del run principal.
        config: misma config (lambdas, etc) — el toggle alpha se
            preserva.

    Returns:
        dict con estructura::

            {
                "ran": True,
                "culpables": ["R4", ...],
                "principal": "R4" | None,
                "detalles": {
                    "R4": {"feasible_relajado": bool,
                           "es_falso_positivo": False,
                           "explicacion": str},
                    "R5": {"feasible_relajado": bool,
                           "es_falso_positivo": bool,
                           "explicacion": str,
                           "materias_problema": [...]},
                    "R6": {"feasible_relajado": bool,
                           "es_falso_positivo": bool,
                           "explicacion": str},
                },
            }

        - ``culpables`` lista las restricciones que arreglaron Y NO
          fueron filtradas como falso positivo.
        - ``principal`` es la causa probable: R4 si aparece, sino la
          primera de la lista. None si no hay culpables.
        - ``detalles[Ri]["es_falso_positivo"]`` indica que la
          relajación arregló pero descartamos esa Ri como causa
          real por el filtro descrito arriba.
    """
    detalles: dict[str, dict] = {}

    # Mensajes accionables en castellano "criollo", sin terminología
    # técnica (no doble booking, pigeonhole, partición, etc).
    explicaciones = {
        "R4": (
            "Hay franjas horarias con **más clases simultáneas que "
            "aulas disponibles** para recibirlas. Acciones que suelen "
            "resolver:\n"
            "- **Marcar virtual** algún dictado de recursado u optativa "
            "que no necesite aula presencial este cuatri (desde "
            "Ciclos → Dictados o desde el panel de no esperadas).\n"
            "- **Agregar aulas** a la sede correspondiente (página "
            "Aulas).\n"
            "- **Mover horarios** a franjas menos cargadas en el "
            "cronograma."
        ),
        "R5": (
            "Las **horas declaradas de teoría / laboratorio** de "
            "alguna materia no cuadran con los horarios cargados en "
            "el cronograma. La materia dice 'tengo X horas de lab' "
            "pero los horarios fijados como lab no suman X (o "
            "viceversa con teoría). Acciones:\n"
            "- **Ajustar las horas declaradas** de la materia desde "
            "la página Materias (campos `horas_teoria` / "
            "`horas_laboratorio`).\n"
            "- **Cambiar el tipo (teoría / lab)** de algún horario "
            "en el cronograma para que la suma cuadre."
        ),
        "R6": (
            "Hay horarios sin tipo determinado (sin marcar como "
            "teoría ni como laboratorio en el cronograma) que **no "
            "encuentran un aula compatible** ni como teóricos ni "
            "como labs. Acciones:\n"
            "- **Fijar el tipo** (teoría o laboratorio) del horario "
            "en el cronograma, así el LP sabe a qué pool de aulas "
            "asignarlo.\n"
            "- **Cargar más laboratorios compatibles** para esa "
            "materia (página Materias → laboratorios)."
        ),
    }

    # Pre-checks para detectar falsos positivos a priori.
    # 1) ¿Hay horarios `tipo_clase=None` que no tengan ninguna
    #    alternativa? Si todos tienen alternativa, R6 individual no
    #    debería ser causa.
    aulas_teoricas_existen = any(
        a.tipo in ("teorica", "anfiteatro") for a in inputs.aulas
    )
    horarios_sin_tipo = [
        h for h in inputs.horarios if h.tipo_clase is None
    ]
    todos_los_none_tienen_alternativa = all(
        (
            aulas_teoricas_existen
            or bool(inputs.materia_lab_map.get(h.materia_codigo))
        )
        for h in horarios_sin_tipo
    )

    for ri in ("R4", "R5", "R6"):
        prob_r, vars_r = build_model(inputs, config, relax={ri})
        sol_r = solve(prob_r, vars_r, config)
        feas = sol_r.status == "optimal"
        item: dict = {
            "feasible_relajado": feas,
            "es_falso_positivo": False,
            "explicacion": (
                explicaciones[ri] if feas else
                f"Sin esta regla el modelo sigue infactible — no es la "
                f"causa por sí sola."
            ),
        }
        if feas:
            if ri == "R5":
                # Identificar las comisiones cuya partición está mal.
                horarios_por_comision: dict[str, list[str]] = {}
                for hid, cid in inputs.comision_de_horario.items():
                    horarios_por_comision.setdefault(cid, []).append(hid)
                materias_problema: list[dict] = []
                for cid, hids in horarios_por_comision.items():
                    if not hids:
                        continue
                    m = inputs.materia_de_horario[hids[0]]
                    hlab_decl = inputs.hlab.get(m, 0.0)
                    suma_lab = 0.0
                    for hid in hids:
                        d = inputs.dur[hid]
                        if hid in vars_r["t"]:
                            v = vars_r["t"][hid].value()
                            t_val = 1.0 if (v is not None and v > 0.5) else 0.0
                        else:
                            _h_obj = next(
                                (hh for hh in inputs.horarios if hh.id == hid),
                                None,
                            )
                            if (
                                _h_obj is not None
                                and _h_obj.tipo_clase == "laboratorio"
                            ):
                                t_val = 1.0
                            else:
                                t_val = 0.0
                        suma_lab += d * t_val
                    if abs(suma_lab - hlab_decl) > 1e-3:
                        materias_problema.append({
                            "comision_id": cid,
                            "materia_codigo": m,
                            "hlab_declarado": hlab_decl,
                            "lab_resuelto": round(suma_lab, 2),
                            "delta": round(suma_lab - hlab_decl, 2),
                        })
                # Dedupe por materia.
                vistas: set[str] = set()
                materias_problema_unicas: list[dict] = []
                for mp in materias_problema:
                    if mp["materia_codigo"] in vistas:
                        continue
                    vistas.add(mp["materia_codigo"])
                    materias_problema_unicas.append(mp)
                item["materias_problema"] = materias_problema_unicas

                # FILTRO DE FALSO POSITIVO PARA R5:
                # R5 es causa real solo si hay materias con
                # `hlab_declarado > 0` cuyo `lab_resuelto` quedó
                # distinto. Si todas las afectadas tienen
                # `hlab_declarado=0`, el LP les puso lab solo porque
                # ganó libertad al relajar R5 — no es problema de
                # catálogo, es ruido.
                materias_con_hlab_real = [
                    mp for mp in materias_problema_unicas
                    if mp["hlab_declarado"] > 0
                ]
                if not materias_con_hlab_real:
                    item["es_falso_positivo"] = True
                    item["explicacion"] = (
                        "Esta regla aparece como 'arreglable' al "
                        "relajarla, pero **probablemente no es la "
                        "causa real**: ninguna materia con horas "
                        "de lab declaradas quedó con números "
                        "incoherentes. Cuando el modelo está "
                        "infactible por falta de aulas (R4), "
                        "relajar las horas teoría/lab también "
                        "ayuda al solver, pero como efecto "
                        "secundario, no como causa directa. Si "
                        "querés revisarlo igual: la lista de "
                        "abajo muestra materias donde el LP usó "
                        "horas de lab que no estaban declaradas, "
                        "lo cual es esperable cuando hay libertad "
                        "extra."
                    )
                else:
                    # Filtrar a sólo las que tienen hlab declarado
                    # para que el usuario vea las relevantes primero.
                    item["materias_problema"] = materias_con_hlab_real

            elif ri == "R6":
                # FILTRO DE FALSO POSITIVO PARA R6:
                # Si todos los horarios sin tipo determinado tienen
                # al menos un aula teórica disponible globalmente o
                # al menos un lab compatible para su materia, R6
                # individualmente no es la causa.
                if todos_los_none_tienen_alternativa:
                    item["es_falso_positivo"] = True
                    item["explicacion"] = (
                        "Esta regla aparece como 'arreglable' al "
                        "relajarla, pero **probablemente no es la "
                        "causa real**: todos los horarios sin tipo "
                        "determinado tienen al menos un aula "
                        "compatible (teórica o laboratorio), así "
                        "que el LP siempre puede decidir un tipo "
                        "consistente. Cuando el modelo está "
                        "infactible por falta de aulas (R4), "
                        "permitir que un horario teórico vaya a un "
                        "lab también ayuda al solver, pero como "
                        "efecto secundario, no como causa directa."
                    )

        detalles[ri] = item

    # Construir la lista de culpables reales (excluyendo falsos
    # positivos) y elegir la principal.
    culpables = [
        ri for ri in ("R4", "R5", "R6")
        if detalles[ri]["feasible_relajado"]
        and not detalles[ri]["es_falso_positivo"]
    ]
    # Prioridad: R4 prevalece sobre R5/R6 cuando aparece. Sino, la
    # primera en orden R5 → R6.
    principal: Optional[str]
    if "R4" in culpables:
        principal = "R4"
    elif culpables:
        principal = culpables[0]
    else:
        principal = None

    return {
        "ran": True,
        "culpables": culpables,
        "principal": principal,
        "detalles": detalles,
    }


def run_lp(
    session: Session,
    plan_id: str,
    config: Optional[LPConfig] = None,
) -> LPRunDB:
    """Wrapper end-to-end: build_inputs → diagnose → build_model → solve → apply → persist.

    Devuelve el ``LPRunDB`` recién insertado. Si la corrida resulta
    infeasible o falla, igual se persiste con el status correspondiente
    (sin tocar las ClaseDB), incluyendo el diagnóstico estructural en
    ``details_json``.

    Si el solver tira `infeasible` y `diagnose` no detecta ninguna
    causa estructural (todas las cotas pigeonhole/Hall/saturación/
    partición vienen vacías), se ejecuta ``_run_iis_relajacion``
    automáticamente para identificar qué restricción es la culpable.
    El resultado se persiste en ``details_json["iis"]`` y se renderea
    en la UI del panel de resultado.
    """
    cfg = config or LPConfig()
    inputs = build_inputs(session, plan_id, cfg)

    # Diagnóstico estructural — se computa siempre (incluso si el LP
    # resuelve OK, queda como warning informativo en el snapshot).
    diagnosis = diagnose(inputs)

    prob, vars_dict = build_model(inputs, cfg)
    solution = solve(prob, vars_dict, cfg)

    # IIS automático: solo cuando el solver dice infeasible Y las
    # cotas estructurales no detectaron causas. Si las cotas detectan
    # algo, ya hay diagnóstico accionable y no vale la pena gastar
    # 3× tiempo extra de solver.
    iis_result: Optional[dict] = None
    if (
        solution.status == "infeasible"
        and not diagnosis.is_infeasible()
    ):
        iis_result = _run_iis_relajacion(inputs, cfg)

    # Resolver fecha_desde: explícita > fecha más antigua del plan > hoy.
    if cfg.fecha_desde is not None:
        fecha_desde = cfg.fecha_desde
    else:
        plan = session.get(PlanificacionCursadaDB, plan_id)
        if plan is not None:
            from src.database.models import CicloDB
            ciclo = session.get(CicloDB, plan.ciclo_id)
            fecha_desde = ciclo.fecha_inicio if ciclo else date.today()
        else:
            fecha_desde = date.today()

    if solution.status == "optimal":
        apply_result = apply_solution(
            session, plan_id, solution, fecha_desde,
            respetar_manuales=cfg.respetar_ediciones_manuales,
        )
    else:
        apply_result = ApplyResult()

    return persist_run(
        session, plan_id, cfg, inputs, solution, fecha_desde,
        apply_result, diagnosis=diagnosis, iis=iis_result,
    )


def aplicar_alpha_propuesto(
    session: Session,
    plan_id: str,
    alpha_dict: dict[str, float],
) -> int:
    """Persiste los α* propuestos por el LP en
    ``ComisionDB.coef_asignacion`` para las comisiones del plan.

    Args:
        session: SQLAlchemy session.
        plan_id: ID del plan al que pertenecen las comisiones.
        alpha_dict: comision_id -> α* nuevo.

    Returns:
        Cantidad de comisiones actualizadas.
    """
    n = 0
    if not alpha_dict:
        return 0
    comisiones = list(session.exec(
        select(ComisionDB).where(
            ComisionDB.plan_cursada_id == plan_id,
            ComisionDB.id.in_(alpha_dict.keys()),  # type: ignore[attr-defined]
        )
    ).all())
    for com in comisiones:
        nuevo = alpha_dict.get(com.id)
        if nuevo is None:
            continue
        com.coef_asignacion = float(nuevo)
        session.add(com)
        n += 1
    session.commit()
    return n


# =============================================================================
# Edición del PATRÓN (HorarioDB.aula_id)
# =============================================================================


def _validar_aula_para_horario(
    session: Session,
    horario: HorarioDB,
    aula: AulaDB,
    *,
    tipo_objetivo: Optional[str] = None,
) -> ValidationResult:
    """Valida que ``aula`` sea compatible con ``horario`` (tipo_clase) y
    no tenga choque temporal con OTROS horarios del mismo plan en la
    misma franja semanal.

    Si ``tipo_objetivo`` se especifica, valida contra ese tipo en vez
    del actual del horario (útil cuando se cambia el tipo del patrón
    en simultáneo).
    """
    res = ValidationResult(ok=True)
    tipo_clase = tipo_objetivo if tipo_objetivo is not None else horario.tipo_clase

    # Compatibilidad tipo<->aula.
    if tipo_clase == "laboratorio":
        comision = session.get(ComisionDB, horario.comision_id)
        if comision is None:
            res.ok = False
            res.errores.append("Comisión del horario no encontrada.")
            return res
        compat_set = {
            ml.aula_id for ml in session.exec(
                select(MateriaLaboratorioDB).where(
                    MateriaLaboratorioDB.materia_codigo
                    == comision.materia_codigo
                )
            ).all()
        }
        if aula.id not in compat_set:
            res.ok = False
            res.errores.append(
                f"El aula '{aula.nombre}' no es laboratorio compatible "
                f"con la materia {comision.materia_codigo}."
            )
            return res
    elif tipo_clase == "teorica":
        if aula.tipo not in ("teorica", "anfiteatro"):
            res.ok = False
            res.errores.append(
                f"El aula '{aula.nombre}' es de tipo '{aula.tipo}' y "
                "no admite clase teórica."
            )
            return res

    # No doble booking a nivel patrón: ningún OTRO horario del mismo
    # plan (vía las comisiones del plan) puede tener este aula en una
    # franja superpuesta el mismo día.
    comision = session.get(ComisionDB, horario.comision_id)
    plan_id = comision.plan_cursada_id if comision else None
    if plan_id is None:
        return res
    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids_plan:
        return res
    choque = session.exec(
        select(HorarioDB).where(
            HorarioDB.aula_id == aula.id,
            HorarioDB.dia == horario.dia,
            HorarioDB.hora_inicio < horario.hora_fin,
            HorarioDB.hora_fin > horario.hora_inicio,
            HorarioDB.id != horario.id,
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
        ).limit(1)
    ).first()
    if choque is not None:
        res.ok = False
        res.errores.append(
            f"El aula '{aula.nombre}' ya está asignada a otro horario "
            f"del plan ({horario.dia} "
            f"{choque.hora_inicio.strftime('%H:%M')}–"
            f"{choque.hora_fin.strftime('%H:%M')})."
        )
    return res


def cambiar_aula_horario(
    session: Session,
    horario_id: str,
    aula_id: Optional[str],
    *,
    nuevo_tipo: Optional[str] = None,
    propagar_a_clases: bool = True,
    marcar_manual: Optional[bool] = None,
) -> ValidationResult:
    """Cambia el aula del PATRÓN (``HorarioDB.aula_id``) y propaga a
    las ``ClaseDB`` como cache técnico.

    Args:
        horario_id: id del HorarioDB a modificar.
        aula_id: aula nueva. Si ``None``, deja el patrón sin asignar.
        nuevo_tipo: si se especifica, también modifica el ``tipo_clase``
          del patrón antes de validar.
        propagar_a_clases: si True (default), propaga el cambio a las
          ClaseDB no ejecutadas del horario.
        marcar_manual: si True, marca el horario con
          ``aula_asignada_manualmente=True`` (el asignador lo va a
          respetar en futuras corridas). Si False, lo desmarca. Si
          ``None``, no toca el flag (preserva su valor actual).

    Returns:
        ValidationResult con ``ok=True`` si el cambio se aplicó. Si
        falla, no persiste nada y devuelve ``errores``.
    """
    res = ValidationResult(ok=True)
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        res.ok = False
        res.errores.append(f"Horario '{horario_id}' no encontrado.")
        return res

    if aula_id is None:
        # Limpiar el patrón.
        horario.aula_id = None
        if nuevo_tipo is not None:
            horario.tipo_clase = nuevo_tipo
        if marcar_manual is not None:
            horario.aula_asignada_manualmente = marcar_manual
        else:
            # Sin aula no tiene sentido el flag "manual" — lo apagamos.
            horario.aula_asignada_manualmente = False
        session.add(horario)
        if propagar_a_clases:
            clases = list(session.exec(
                select(ClaseDB).where(
                    ClaseDB.horario_id == horario_id,
                    ClaseDB.executed == False,  # noqa: E712
                )
            ).all())
            for c in clases:
                c.aula_id = None
                if nuevo_tipo is not None:
                    c.tipo_clase = nuevo_tipo
                session.add(c)
        session.commit()
        return res

    aula = session.get(AulaDB, aula_id)
    if aula is None:
        res.ok = False
        res.errores.append(f"Aula '{aula_id}' no encontrada.")
        return res

    val = _validar_aula_para_horario(
        session, horario, aula, tipo_objetivo=nuevo_tipo,
    )
    if not val.ok:
        return val

    horario.aula_id = aula.id
    if nuevo_tipo is not None:
        horario.tipo_clase = nuevo_tipo
    if marcar_manual is not None:
        horario.aula_asignada_manualmente = marcar_manual
    session.add(horario)

    if propagar_a_clases:
        clases = list(session.exec(
            select(ClaseDB).where(
                ClaseDB.horario_id == horario_id,
                ClaseDB.executed == False,  # noqa: E712
            )
        ).all())
        for c in clases:
            c.aula_id = aula.id
            if nuevo_tipo is not None:
                c.tipo_clase = nuevo_tipo
            session.add(c)
    session.commit()
    return res


def get_aulas_disponibles_para_horario(
    session: Session,
    plan_id: str,
    horario_id: str,
    *,
    tipo_objetivo: Optional[str] = None,
) -> list[AulaDB]:
    """Aulas candidatas para asignar al PATRÓN ``horario_id`` del plan.

    Filtra:
      - Compatibilidad tipo<->aula contra ``tipo_objetivo`` (si dado)
        o el ``HorarioDB.tipo_clase`` actual.
      - Sin choque con OTROS HorarioDB del mismo plan en la misma
        franja (mismo día y solapamiento horario).
      - Restriccion de sede (R10): si ``horario.carrera_asignada`` esta
        seteado, solo aulas de sedes admisibles para esa carrera;
        sino, sedes admisibles segun la materia (comun/exclusiva).
        Excepcion: labs compatibles con la materia siempre pasan
        (misma logica que en ``build_inputs``).

    Devuelve aulas ordenadas por capacidad ascendente.
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return []
    tipo_clase = (
        tipo_objetivo if tipo_objetivo is not None else horario.tipo_clase
    )
    comision = session.get(ComisionDB, horario.comision_id)
    materia_codigo = comision.materia_codigo if comision else None

    aulas_db = list(session.exec(
        select(AulaDB).order_by(AulaDB.capacidad)  # type: ignore[attr-defined]
    ).all())

    # Filtrado por tipo.
    compat: list[AulaDB] = []
    lab_ids: set[str] = set()
    if materia_codigo:
        lab_ids = {
            ml.aula_id for ml in session.exec(
                select(MateriaLaboratorioDB).where(
                    MateriaLaboratorioDB.materia_codigo == materia_codigo
                )
            ).all()
        }
    if tipo_clase == "laboratorio":
        if materia_codigo:
            compat = [a for a in aulas_db if a.id in lab_ids]
    elif tipo_clase == "teorica":
        compat = [a for a in aulas_db if a.tipo in ("teorica", "anfiteatro")]
    else:
        compat = list(aulas_db)

    # Filtrado por sede (R10). El override vive en la comisión.
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_carrera,
        sedes_admisibles_para_materia,
    )
    _com_override = comision.carrera_asignada if comision else None
    if _com_override:
        admisibles = sedes_admisibles_para_carrera(session, _com_override)
    elif materia_codigo:
        admisibles = sedes_admisibles_para_materia(session, materia_codigo)
    else:
        admisibles = None
    if admisibles is not None:
        compat = [
            a for a in compat
            if a.id in lab_ids or a.sede_id in admisibles
        ]

    # Filtrado por choque con otros HorarioDB del plan en la misma franja.
    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids_plan:
        return compat
    horarios_otros = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.id != horario_id,
            HorarioDB.dia == horario.dia,
            HorarioDB.hora_inicio < horario.hora_fin,
            HorarioDB.hora_fin > horario.hora_inicio,
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
            HorarioDB.aula_id.is_not(None),  # type: ignore[union-attr]
        )
    ).all())
    aulas_ocupadas = {h.aula_id for h in horarios_otros if h.aula_id}
    return [a for a in compat if a.id not in aulas_ocupadas]


def clear_aula_horario(session: Session, horario_id: str) -> bool:
    """Limpia el ``aula_id`` del patrón. Útil cuando se edita el slot
    (día/hora) del horario y la asignación del LP queda inválida.

    Devuelve True si limpió algo, False si el horario no existía o ya
    estaba en None.
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None or horario.aula_id is None:
        return False
    cambiar_aula_horario(
        session, horario_id, aula_id=None, propagar_a_clases=True,
    )
    return True


# =============================================================================
# Reasignación con desplazamiento (edición manual)
# =============================================================================
#
# Feature: al editar el aula de un horario, el usuario puede elegir un
# aula que ya está ocupada por otro horario del plan y resolver el
# conflicto entre ambos en un solo paso (swap, reasignar el desplazado
# a una libre, o dejarlo sin aula).
#
# Acciones válidas para ``reasignar_con_desplazamiento``:
#   - "libre":     asigna un aula libre al horario editado. Equivalente
#                  a ``cambiar_aula_horario``.
#   - "swap":      el aula elegida está ocupada por un horario con
#                  franja idéntica. El editado toma esa aula y el
#                  desplazado recibe el aula original del editado.
#   - "reassign":  el editado toma el aula ocupada; el desplazado se
#                  reasigna a un aula libre pasada en
#                  ``aula_para_desplazado``.
#   - "unassign":  el editado toma el aula ocupada; el desplazado queda
#                  sin aula (aula_id=None).
#
# Restricción: sólo swap directo con franjas idénticas. Si el ocupante
# tiene franja parcial vs. el horario editado, se lo trata como "no
# hay ocupante" a efectos del swap simple. La UI se encarga de mostrar
# el aula como "ocupada" en el desplegable pero deshabilitar la opción
# swap si la franja no coincide.


@dataclass
class AulaCandidata:
    """Aula candidata a ser asignada a un horario, con metadata sobre
    ocupación en la franja del horario editado.

    Devuelto por ``get_aulas_todas_para_horario`` para poblar el
    desplegable del diálogo de edición manual.

    Los campos ``ocupante`` y ``ocupante_franja_identica`` mantienen la
    API "un ocupante" para compatibilidad con el flujo de reasignación
    simple (swap/reassign/unassign). Para el flujo de cascada usar
    ``ocupantes`` que trae **todos** los horarios que solapan.
    """
    aula: AulaDB
    libre_en_franja: bool
    ocupante: Optional[HorarioDB]
    # True si el ocupante tiene EXACTAMENTE la misma franja (día,
    # hora_inicio, hora_fin) que el horario editado. Sólo cuando esto
    # es True, la UI puede ofrecer la acción "swap".
    ocupante_franja_identica: bool
    # TODOS los horarios del plan que solapan con la franja del horario
    # editado (usando esta aula). Puede tener 0, 1 o N elementos. La UI
    # de cascada la usa para armar el árbol de decisiones.
    ocupantes: list[HorarioDB] = field(default_factory=list)


@dataclass
class PreviewReasignacion:
    """Efecto hipotético de una reasignación con desplazamiento.

    Devuelto por ``preview_reasignacion_con_desplazamiento`` para que
    la UI muestre el resultado antes de que el usuario confirme.
    """
    editado_ok: bool
    editado_aula_futura: Optional[str]
    # Si la operación desplaza otro horario, estos campos se completan.
    desplazado_horario_id: Optional[str] = None
    desplazado_aula_futura: Optional[str] = None
    desplazado_ok: bool = True
    errores: list[str] = field(default_factory=list)


def get_ocupante_de_aula_en_franja(
    session: Session,
    plan_id: str,
    horario_id: str,
    aula_id: str,
) -> Optional[HorarioDB]:
    """Devuelve el HorarioDB que ocupa ``aula_id`` en la misma franja
    exacta (día, hora_inicio, hora_fin) que ``horario_id``, entre los
    horarios del ``plan_id``, o ``None`` si el aula está libre en esa
    franja o el ocupante tiene franja parcial.

    Excluye al propio ``horario_id`` (no se considera su propio
    ocupante).
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return None

    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids_plan:
        return None

    # Buscar horarios con MISMA franja exacta (no solapamiento parcial).
    ocupante = session.exec(
        select(HorarioDB).where(
            HorarioDB.aula_id == aula_id,
            HorarioDB.dia == horario.dia,
            HorarioDB.hora_inicio == horario.hora_inicio,
            HorarioDB.hora_fin == horario.hora_fin,
            HorarioDB.id != horario_id,
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
        ).limit(1)
    ).first()
    return ocupante


def get_aulas_todas_para_horario(
    session: Session,
    plan_id: str,
    horario_id: str,
    *,
    tipo_objetivo: Optional[str] = None,
) -> list[AulaCandidata]:
    """Aulas candidatas al ``horario_id`` **sin filtrar por ocupación**.

    A diferencia de ``get_aulas_disponibles_para_horario`` que excluye
    aulas ocupadas por otros horarios del plan en la franja, esta
    función devuelve todas las aulas compatibles por tipo y sede, y
    marca cada una con metadata sobre ocupación en la franja del
    horario editado.

    Filtra:
      - Compatibilidad tipo<->aula.
      - Restricción de sede (R10).

    Metadata por aula candidata:
      - ``libre_en_franja``: True si ningún otro horario del plan usa
        esa aula en una franja que solape con la del ``horario_id``.
      - ``ocupante``: el HorarioDB que ocupa el aula en franja idéntica
        (si hay). None si está libre o si el ocupante tiene franja
        parcial.
      - ``ocupante_franja_identica``: si hay ocupante, si su franja
        coincide exactamente con la del horario editado. Sólo en ese
        caso la UI puede ofrecer swap directo.
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return []
    tipo_clase = (
        tipo_objetivo if tipo_objetivo is not None else horario.tipo_clase
    )
    comision = session.get(ComisionDB, horario.comision_id)
    materia_codigo = comision.materia_codigo if comision else None

    aulas_db = list(session.exec(
        select(AulaDB).order_by(AulaDB.capacidad)  # type: ignore[attr-defined]
    ).all())

    # Filtrado por tipo.
    compat: list[AulaDB] = []
    lab_ids: set[str] = set()
    if materia_codigo:
        lab_ids = {
            ml.aula_id for ml in session.exec(
                select(MateriaLaboratorioDB).where(
                    MateriaLaboratorioDB.materia_codigo == materia_codigo
                )
            ).all()
        }
    if tipo_clase == "laboratorio":
        if materia_codigo:
            compat = [a for a in aulas_db if a.id in lab_ids]
    elif tipo_clase == "teorica":
        compat = [a for a in aulas_db if a.tipo in ("teorica", "anfiteatro")]
    else:
        compat = list(aulas_db)

    # Filtrado por sede (R10).
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_carrera,
        sedes_admisibles_para_materia,
    )
    _com_override = comision.carrera_asignada if comision else None
    if _com_override:
        admisibles = sedes_admisibles_para_carrera(session, _com_override)
    elif materia_codigo:
        admisibles = sedes_admisibles_para_materia(session, materia_codigo)
    else:
        admisibles = None
    if admisibles is not None:
        compat = [
            a for a in compat
            if a.id in lab_ids or a.sede_id in admisibles
        ]

    # Traer todos los horarios del plan que solapen con la franja del
    # horario editado (excluyendo el propio horario).
    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    horarios_otros: list[HorarioDB] = []
    if com_ids_plan:
        horarios_otros = list(session.exec(
            select(HorarioDB).where(
                HorarioDB.id != horario_id,
                HorarioDB.dia == horario.dia,
                HorarioDB.hora_inicio < horario.hora_fin,
                HorarioDB.hora_fin > horario.hora_inicio,
                HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
                HorarioDB.aula_id.is_not(None),  # type: ignore[union-attr]
            )
        ).all())

    # Mapear aula_id -> lista de ocupantes que solapan.
    ocupantes_por_aula: dict[str, list[HorarioDB]] = {}
    for h in horarios_otros:
        if h.aula_id is None:
            continue
        ocupantes_por_aula.setdefault(h.aula_id, []).append(h)

    resultado: list[AulaCandidata] = []
    for a in compat:
        todos_oc = ocupantes_por_aula.get(a.id, [])
        # Buscar un ocupante con franja idéntica (preferido para swap).
        oc_identico: Optional[HorarioDB] = None
        for oc in todos_oc:
            if (
                oc.hora_inicio == horario.hora_inicio
                and oc.hora_fin == horario.hora_fin
            ):
                oc_identico = oc
                break
        franja_identica = oc_identico is not None
        # Compat con API vieja: ``ocupante`` sólo se completa si hay
        # franja idéntica.
        ocupante_out = oc_identico if franja_identica else None
        resultado.append(AulaCandidata(
            aula=a,
            libre_en_franja=not todos_oc,
            ocupante=ocupante_out,
            ocupante_franja_identica=franja_identica,
            ocupantes=list(todos_oc),
        ))
    return resultado


def get_horarios_afectados(
    session: Session,
    plan_id: str,
    horario_id: str,
    aula_id: str,
) -> list[HorarioDB]:
    """Devuelve todos los HorarioDB del plan que solapan con la franja
    del ``horario_id`` usando ``aula_id``.

    Solapan si mismo día y sus rangos [hora_inicio, hora_fin) se
    intersectan (misma franja, franja parcial, contenida o contenedora).

    Excluye al propio ``horario_id``. Devuelve lista vacía si el aula
    no tiene ningún horario del plan que solape.

    Uso: base para armar el árbol de cascada de desplazamientos.
    """
    horario = session.get(HorarioDB, horario_id)
    if horario is None:
        return []

    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids_plan:
        return []

    afectados = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.aula_id == aula_id,
            HorarioDB.dia == horario.dia,
            HorarioDB.hora_inicio < horario.hora_fin,
            HorarioDB.hora_fin > horario.hora_inicio,
            HorarioDB.id != horario_id,
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
        )
    ).all())
    return afectados


def solapamiento_franjas(
    dia_a: str, hi_a, hf_a, dia_b: str, hi_b, hf_b,
) -> Optional[tuple]:
    """Devuelve el rango de solapamiento (hi, hf) entre dos franjas, o
    None si no solapan.

    Ambas franjas son (dia, hora_inicio, hora_fin). Solapan si mismo
    día y sus rangos se intersectan.
    """
    if dia_a != dia_b:
        return None
    hi = max(hi_a, hi_b)
    hf = min(hf_a, hf_b)
    if hi >= hf:
        return None
    return (hi, hf)


def tipo_solapamiento(
    dia_a: str, hi_a, hf_a, dia_b: str, hi_b, hf_b,
) -> str:
    """Clasifica el tipo de solapamiento entre dos franjas.

    Devuelve:
        - "sin_solape" si no comparten día o rangos.
        - "identico" si mismo día e iguales hora_inicio y hora_fin.
        - "parcial" si mismo día y solapan sin ser idénticos.
    """
    if dia_a != dia_b:
        return "sin_solape"
    if hi_a == hi_b and hf_a == hf_b:
        return "identico"
    sol = solapamiento_franjas(dia_a, hi_a, hf_a, dia_b, hi_b, hf_b)
    if sol is None:
        return "sin_solape"
    return "parcial"


# =============================================================================
# Reasignación en cascada (árbol de decisiones)
# =============================================================================
#
# Modelo: cuando un usuario elige un aula ocupada para el horario que
# edita, cada horario ocupante del aula queda "desplazado" y necesita
# una decisión de qué hacer con él. Si el usuario decide reasignarlo a
# otra aula que también está ocupada, esos nuevos desplazados forman
# el nivel siguiente del árbol. Y así recursivamente.
#
# El nivel raíz (nivel 0) es el horario editado por el usuario. Los
# nodos internos son horarios desplazados. Cada nodo tiene una
# ``aula_elegida`` (o None si "dejar sin aula") y una lista de
# ``hijos``, uno por cada horario adicional que se desplaza por elegir
# esa aula.


@dataclass
class NodoCascada:
    """Nodo del árbol de decisiones de reasignación en cascada.

    Estructura:
    - Nivel 0 (raíz): el horario que el usuario editó explícitamente.
    - Nivel N>0: un horario que se desplaza por una decisión del nivel
      N-1.

    ``aula_elegida`` es None si la decisión es "dejar sin aula".

    ``hijos`` refleja los horarios adicionales que se desplazan al
    tomar esa decisión. Si ``aula_elegida`` es None o es libre, no hay
    hijos.

    ``accion`` documenta la naturaleza de la decisión:
    - "libre": el aula elegida está libre en la franja (sin hijos).
    - "swap": sólo válido en el nivel raíz — intercambia con un
      ocupante de franja idéntica.
    - "reassign": el editado toma el aula elegida y cada ocupante se
      resuelve en su propio sub-nodo hijo.
    - "unassign": raíz sin aula (nada elegido) — no común pero
      admitido para completar un ciclo.
    - "sin_aula": el nodo (desplazado) queda sin aula. Sin hijos.
    """
    horario_id: str
    aula_elegida: Optional[str]
    accion: str  # "libre" | "swap" | "reassign" | "unassign" | "sin_aula"
    hijos: list["NodoCascada"] = field(default_factory=list)
    # Si True, la asignación resultante se marca como manual
    # (`HorarioDB.aula_asignada_manualmente=True`) para que el
    # asignador la respete en futuras corridas. Default None = usar
    # el default de la UI (típicamente True cuando el usuario asigna
    # explícitamente un aula, False cuando queda sin aula).
    marcar_manual: Optional[bool] = None


_ACCIONES_NODO = ("libre", "swap", "reassign", "unassign", "sin_aula")


@dataclass
class EfectoNodo:
    """Efecto planificado sobre un horario dentro de una cascada.

    Uno por horario afectado en el árbol (raíz + descendientes).
    ``ok`` es True si el efecto no tiene errores duros (compatibilidad
    de tipo, sede, laboratorio). ``warnings`` son advertencias no
    bloqueantes.
    """
    horario_id: str
    aula_futura: Optional[str]
    ok: bool
    errores: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    nivel: int = 0
    # Rango de solapamiento con el padre (si aplica). Formato "HH:MM–HH:MM".
    solapamiento_con_padre: Optional[str] = None
    tipo_solapamiento_con_padre: Optional[str] = None  # identico | parcial | None
    # Propagado desde `NodoCascada.marcar_manual`. Si None, la
    # aplicación no toca el flag existente. Si True/False lo setea.
    marcar_manual: Optional[bool] = None


@dataclass
class PlanEjecucion:
    """Resultado de planificar una cascada de reasignación.

    ``efectos`` es la lista plana de efectos ordenada por DFS del árbol
    (raíz primero, después hijos). ``ok`` es True si TODOS los efectos
    son ok. ``errores_globales`` incluye ciclos detectados y otros
    problemas estructurales del árbol.
    """
    ok: bool
    efectos: list[EfectoNodo]
    errores_globales: list[str] = field(default_factory=list)

    @property
    def tiene_warnings(self) -> bool:
        return any(e.warnings for e in self.efectos)


def _validar_arbol_ciclos(cascada: NodoCascada) -> list[str]:
    """Detecta ciclos en el árbol de cascada.

    Un ciclo ocurre cuando un horario aparece más de una vez en la
    cadena de ancestros. Ejemplo: A→B (hijo de A), B→A (hijo de B con
    aula original de A). El usuario terminaría re-asignando A a un
    aula que luego se le vuelve a asignar por el desplazamiento
    inverso.

    Estrategia: DFS marcando ancestros en el camino desde la raíz. Si
    un nodo tiene el mismo horario_id que uno de sus ancestros, ciclo.
    """
    errores: list[str] = []

    def _dfs(nodo: NodoCascada, camino: tuple[str, ...]):
        if nodo.horario_id in camino:
            errores.append(
                f"Ciclo detectado en la cascada: el horario "
                f"'{nodo.horario_id}' aparece más de una vez en la cadena "
                f"de decisiones (camino: {' → '.join(camino)} → "
                f"{nodo.horario_id}). Elegí otra aula para cortar el ciclo."
            )
            return
        nuevo_camino = camino + (nodo.horario_id,)
        for h in nodo.hijos:
            _dfs(h, nuevo_camino)

    _dfs(cascada, tuple())
    return errores


def _check_compat_para_horario(
    session: Session,
    horario: HorarioDB,
    aula: AulaDB,
) -> list[str]:
    """Chequea si ``aula`` es compatible con ``horario`` en cuanto a
    tipo, sede admisible y laboratorio. Devuelve lista de errores."""
    errs: list[str] = []
    tipo = horario.tipo_clase
    if tipo == "laboratorio":
        comision = session.get(ComisionDB, horario.comision_id)
        if comision is None:
            errs.append("Comisión no encontrada.")
            return errs
        compat_set = {
            ml.aula_id for ml in session.exec(
                select(MateriaLaboratorioDB).where(
                    MateriaLaboratorioDB.materia_codigo
                    == comision.materia_codigo
                )
            ).all()
        }
        if aula.id not in compat_set:
            errs.append(
                f"El aula '{aula.nombre}' no es laboratorio compatible "
                f"con la materia {comision.materia_codigo}."
            )
    elif tipo == "teorica":
        if aula.tipo not in ("teorica", "anfiteatro"):
            errs.append(
                f"El aula '{aula.nombre}' es de tipo '{aula.tipo}' y "
                "no admite clase teórica."
            )
    # Sede admisible.
    comision = session.get(ComisionDB, horario.comision_id)
    materia_codigo = comision.materia_codigo if comision else None
    _com_override = comision.carrera_asignada if comision else None
    from src.services.carrera_sede_service import (
        sedes_admisibles_para_carrera,
        sedes_admisibles_para_materia,
    )
    if _com_override:
        admisibles = sedes_admisibles_para_carrera(session, _com_override)
    elif materia_codigo:
        admisibles = sedes_admisibles_para_materia(session, materia_codigo)
    else:
        admisibles = None
    if admisibles is not None:
        lab_ids: set[str] = set()
        if materia_codigo:
            lab_ids = {
                ml.aula_id for ml in session.exec(
                    select(MateriaLaboratorioDB).where(
                        MateriaLaboratorioDB.materia_codigo == materia_codigo
                    )
                ).all()
            }
        if aula.id not in lab_ids and aula.sede_id not in admisibles:
            errs.append(
                f"El aula '{aula.nombre}' está en una sede "
                "no admisible para la materia/carrera."
            )
    return errs


def validar_y_planificar_cascada(
    session: Session,
    plan_id: str,
    cascada: NodoCascada,
) -> PlanEjecucion:
    """Valida un árbol de decisiones de cascada sin persistir.

    Recorre el árbol en DFS y calcula, para cada nodo, cuál es su aula
    futura y qué errores/warnings genera. Detecta ciclos, verifica
    compatibilidad (tipo, sede, laboratorio) y agrega warnings cuando
    el swap involucra franjas parciales.

    NO valida choques residuales entre horarios que quedan en la
    cascada: eso lo hace el planificador cuando compone el plan
    final. La validación aquí es por horario individual.

    Args:
        plan_id: plan al que pertenece el horario editado.
        cascada: NodoCascada raíz (nivel 0).

    Returns:
        PlanEjecucion con lista de efectos y flag ok.

    Raises:
        ValueError: si ``cascada.accion`` no es válida o si hay
            inconsistencias graves en la estructura del árbol.
    """
    if cascada.accion not in _ACCIONES_NODO:
        raise ValueError(
            f"Acción raíz inválida: '{cascada.accion}'. "
            f"Válidas: {_ACCIONES_NODO}."
        )

    errores_globales = _validar_arbol_ciclos(cascada)
    if errores_globales:
        return PlanEjecucion(ok=False, efectos=[], errores_globales=errores_globales)

    efectos: list[EfectoNodo] = []

    def _dfs(nodo: NodoCascada, nivel: int, padre: Optional[NodoCascada]):
        horario = session.get(HorarioDB, nodo.horario_id)
        if horario is None:
            efectos.append(EfectoNodo(
                horario_id=nodo.horario_id,
                aula_futura=None,
                ok=False,
                errores=[f"Horario '{nodo.horario_id}' no encontrado."],
                nivel=nivel,
            ))
            return

        # Determinar aula futura según acción.
        if nodo.accion == "sin_aula":
            aula_futura = None
        elif nodo.accion == "swap":
            # Sólo válido en raíz. La aula futura del NODO SWAP es la
            # aula elegida. El swap desplaza al ocupante idéntico que
            # se resuelve como hijo con acción explícita.
            if nivel != 0:
                efectos.append(EfectoNodo(
                    horario_id=nodo.horario_id,
                    aula_futura=None,
                    ok=False,
                    errores=[
                        "La acción 'swap' sólo es válida en el nivel raíz "
                        "de la cascada. En niveles internos usá 'reassign' "
                        "o 'sin_aula'."
                    ],
                    nivel=nivel,
                ))
                return
            aula_futura = nodo.aula_elegida
        else:  # libre, reassign, unassign
            aula_futura = nodo.aula_elegida

        errs: list[str] = []
        warns: list[str] = []

        if aula_futura is not None:
            aula = session.get(AulaDB, aula_futura)
            if aula is None:
                errs.append(f"Aula '{aula_futura}' no encontrada.")
            else:
                errs.extend(_check_compat_para_horario(
                    session, horario, aula,
                ))

        # Solapamiento con padre — sólo se calcula para informar el
        # rango de solapamiento en la UI. El caso problemático (aula
        # con horarios superpuestos que se pisan) lo detecta la
        # validación cruzada `_detectar_choques_residuales`, que
        # produce mensajes más precisos.
        solape_str: Optional[str] = None
        tipo_sol: Optional[str] = None
        if padre is not None:
            padre_horario = session.get(HorarioDB, padre.horario_id)
            if padre_horario is not None:
                tipo_sol = tipo_solapamiento(
                    padre_horario.dia, padre_horario.hora_inicio,
                    padre_horario.hora_fin,
                    horario.dia, horario.hora_inicio, horario.hora_fin,
                )
                if tipo_sol == "parcial":
                    rango = solapamiento_franjas(
                        padre_horario.dia, padre_horario.hora_inicio,
                        padre_horario.hora_fin,
                        horario.dia, horario.hora_inicio, horario.hora_fin,
                    )
                    if rango:
                        solape_str = (
                            f"{rango[0].strftime('%H:%M')}"
                            f"–{rango[1].strftime('%H:%M')}"
                        )
                elif tipo_sol == "identico":
                    solape_str = "franja completa"

        efectos.append(EfectoNodo(
            horario_id=nodo.horario_id,
            aula_futura=aula_futura,
            ok=len(errs) == 0,
            errores=errs,
            warnings=warns,
            nivel=nivel,
            solapamiento_con_padre=solape_str,
            tipo_solapamiento_con_padre=tipo_sol,
            marcar_manual=nodo.marcar_manual,
        ))

        for h in nodo.hijos:
            _dfs(h, nivel + 1, nodo)

    _dfs(cascada, 0, None)

    # Validación cruzada de choques residuales:
    # después de aplicar todos los efectos, ¿algún par de horarios del
    # plan quedaría en la misma aula con franjas solapadas?
    #
    # El estado final que estamos construyendo es:
    # - Para cada horario tocado por la cascada, su ``aula_futura``.
    # - Para el resto de horarios del plan, su ``aula_id`` actual.
    _errores_choques = _detectar_choques_residuales(
        session, plan_id, efectos,
    )
    for horario_id, err in _errores_choques:
        # Adjuntar el error al efecto correspondiente y marcarlo not-ok.
        for e in efectos:
            if e.horario_id == horario_id:
                e.errores.append(err)
                e.ok = False
                break

    ok = all(e.ok for e in efectos)
    return PlanEjecucion(
        ok=ok,
        efectos=efectos,
        errores_globales=[],
    )


def _detectar_choques_residuales(
    session: Session,
    plan_id: str,
    efectos: list[EfectoNodo],
) -> list[tuple[str, str]]:
    """Detecta choques entre horarios del plan que resultarían de
    aplicar los ``efectos`` de la cascada.

    Un choque es: dos horarios distintos del plan quedan con la misma
    aula (aula_futura no None) y sus franjas se solapan.

    Devuelve lista de (horario_id, mensaje) — un par por cada efecto
    que participa en un choque. Cada choque genera 2 entradas (una por
    cada horario del par).
    """
    # 1) Construir el "estado final": aula_id → lista de (horario_id,
    # dia, hora_inicio, hora_fin). Empezamos con el estado actual del
    # plan y sobreescribimos con las asignaciones futuras de la cascada.
    tocados_por_cascada = {e.horario_id: e for e in efectos}

    # Traer todos los horarios del plan.
    com_ids_plan = list(session.exec(
        select(ComisionDB.id).where(
            ComisionDB.plan_cursada_id == plan_id,
        )
    ).all())
    if not com_ids_plan:
        return []

    horarios_plan = list(session.exec(
        select(HorarioDB).where(
            HorarioDB.comision_id.in_(com_ids_plan),  # type: ignore[attr-defined]
        )
    ).all())

    # Estado final por horario_id: (aula_id, dia, hi, hf).
    estado_final: dict[str, tuple[Optional[str], str, "object", "object"]] = {}
    for h in horarios_plan:
        aula_final = h.aula_id
        if h.id in tocados_por_cascada:
            aula_final = tocados_por_cascada[h.id].aula_futura
        estado_final[h.id] = (aula_final, h.dia, h.hora_inicio, h.hora_fin)

    # 2) Agrupar por aula → detectar solapamientos entre pares.
    por_aula: dict[str, list[tuple[str, str, "object", "object"]]] = {}
    for hid, (aula, dia, hi, hf) in estado_final.items():
        if aula is None:
            continue
        por_aula.setdefault(aula, []).append((hid, dia, hi, hf))

    # 3) Para cada aula con más de un horario, buscar pares que solapen.
    errores_por_horario: list[tuple[str, str]] = []
    for aula_id, items in por_aula.items():
        n = len(items)
        if n < 2:
            continue
        aula_nombre = None
        aula_obj = session.get(AulaDB, aula_id)
        aula_nombre = aula_obj.nombre if aula_obj else aula_id
        for i in range(n):
            hid_i, dia_i, hi_i, hf_i = items[i]
            for j in range(i + 1, n):
                hid_j, dia_j, hi_j, hf_j = items[j]
                # Sólo interesa si al menos uno de los dos fue tocado
                # por la cascada — los choques preexistentes no son
                # responsabilidad de la cascada.
                if (hid_i not in tocados_por_cascada
                        and hid_j not in tocados_por_cascada):
                    continue
                sol = solapamiento_franjas(
                    dia_i, hi_i, hf_i, dia_j, hi_j, hf_j,
                )
                if sol is None:
                    continue
                # Choque real.
                # Mensaje: enunciar quién queda en la misma aula.
                # Buscar meta legible.
                def _meta(hid: str) -> str:
                    h = session.get(HorarioDB, hid)
                    if h is None:
                        return hid
                    com = session.get(ComisionDB, h.comision_id)
                    mat_cod = com.materia_codigo if com else "?"
                    com_nombre = com.nombre if com else "?"
                    materia = session.get(MateriaDB, mat_cod) if mat_cod != "?" else None
                    mat_nombre = (
                        materia.nombre if materia else mat_cod
                    )
                    return (
                        f"**{mat_nombre}** ({mat_cod} · {com_nombre}, "
                        f"{h.dia} {h.hora_inicio.strftime('%H:%M')}"
                        f"–{h.hora_fin.strftime('%H:%M')})"
                    )
                meta_i = _meta(hid_i)
                meta_j = _meta(hid_j)
                rango_txt = (
                    f"{sol[0].strftime('%H:%M')}–{sol[1].strftime('%H:%M')}"
                )
                msg = (
                    f"El aula **{aula_nombre}** quedaría usada al mismo "
                    f"tiempo por {meta_i} y {meta_j}. Sus horarios se "
                    f"pisan de {rango_txt} — en ese tramo habría dos "
                    f"materias compartiendo el aula. "
                    f"Elegí otra aula para al menos una de las dos."
                )
                if hid_i in tocados_por_cascada:
                    errores_por_horario.append((hid_i, msg))
                if hid_j in tocados_por_cascada:
                    errores_por_horario.append((hid_j, msg))
    return errores_por_horario


def aplicar_cascada(
    session: Session,
    plan_id: str,
    cascada: NodoCascada,
) -> ValidationResult:
    """Aplica un árbol de decisiones de cascada en transacción atómica.

    Estrategia:
    1. Llama a ``validar_y_planificar_cascada`` para verificar el árbol.
    2. Si no ok, devuelve error sin tocar nada.
    3. Si ok, aplica los efectos en orden seguro:
       a) Limpia el aula de todos los desplazados (nivel > 0) para
          liberar sus aulas y evitar choques transitorios.
       b) Asigna al editado su aula nueva.
       c) Asigna a cada desplazado su aula futura (o lo deja en None
          si acción es "sin_aula").
    4. Si algún paso falla mientras se aplica, best-effort rollback
       restaurando los aula_id originales.

    Args:
        plan_id: plan al que pertenece la cascada.
        cascada: árbol raíz.

    Returns:
        ValidationResult con ok=True si se aplicó todo, o errores.

    Raises:
        ValueError: si la cascada es inválida en forma.
    """
    plan = validar_y_planificar_cascada(session, plan_id, cascada)
    if not plan.ok:
        res = ValidationResult(ok=False)
        res.errores = list(plan.errores_globales) + [
            err for e in plan.efectos for err in e.errores
        ]
        return res

    # Snapshot de aula_id original por horario, para rollback.
    horario_ids = [e.horario_id for e in plan.efectos]
    snapshot: dict[str, Optional[str]] = {}
    for hid in horario_ids:
        h = session.get(HorarioDB, hid)
        if h is not None:
            snapshot[hid] = h.aula_id

    def _rollback():
        for hid, aula_orig in snapshot.items():
            cambiar_aula_horario(session, hid, aula_orig)

    # Paso 1: liberar aula de todos los efectos con nivel > 0.
    for efecto in plan.efectos:
        if efecto.nivel == 0:
            continue
        r = cambiar_aula_horario(session, efecto.horario_id, None)
        if not r.ok:
            _rollback()
            res = ValidationResult(ok=False)
            res.errores = [
                f"Falló liberar el horario '{efecto.horario_id}' "
                "(paso 1 de la cascada)."
            ] + list(r.errores)
            return res

    # Paso 2: asignar aula del editado (raíz).
    raiz = plan.efectos[0]
    r = cambiar_aula_horario(
        session, raiz.horario_id, raiz.aula_futura,
        marcar_manual=raiz.marcar_manual,
    )
    if not r.ok:
        _rollback()
        res = ValidationResult(ok=False)
        res.errores = [
            f"Falló asignar aula al horario raíz."
        ] + list(r.errores)
        return res

    # Paso 3: asignar aulas a los desplazados (nivel > 0).
    for efecto in plan.efectos[1:]:
        r = cambiar_aula_horario(
            session, efecto.horario_id, efecto.aula_futura,
            marcar_manual=efecto.marcar_manual,
        )
        if not r.ok:
            _rollback()
            res = ValidationResult(ok=False)
            res.errores = [
                f"Falló asignar aula al horario '{efecto.horario_id}' "
                f"(nivel {efecto.nivel})."
            ] + list(r.errores)
            return res

    return ValidationResult(ok=True)


_ACCIONES_REASIGNACION = ("libre", "swap", "reassign", "unassign")


def _validar_reasignacion(
    session: Session,
    plan_id: str,
    horario_id: str,
    aula_nueva_id: str,
    accion: str,
    aula_para_desplazado: Optional[str],
) -> tuple[HorarioDB, Optional[HorarioDB], list[str]]:
    """Validaciones de forma (previas al cómputo del efecto).

    Devuelve (horario_editado, ocupante_o_none, errores). Si `errores`
    tiene elementos, la operación no puede continuar.
    """
    errores: list[str] = []

    horario_editado = session.get(HorarioDB, horario_id)
    if horario_editado is None:
        return None, None, [f"Horario '{horario_id}' no encontrado."]  # type: ignore[return-value]

    aula_nueva = session.get(AulaDB, aula_nueva_id)
    if aula_nueva is None:
        errores.append(f"Aula '{aula_nueva_id}' no encontrada.")
        return horario_editado, None, errores

    if accion == "libre":
        return horario_editado, None, errores

    ocupante = get_ocupante_de_aula_en_franja(
        session, plan_id, horario_id, aula_nueva_id,
    )
    if ocupante is None:
        if accion == "swap":
            errores.append(
                f"No se puede hacer swap: el aula '{aula_nueva.nombre}' "
                "está libre en esta franja (no hay ocupante)."
            )
            return horario_editado, None, errores
        # reassign/unassign sin ocupante no tiene sentido tampoco
        errores.append(
            f"El aula '{aula_nueva.nombre}' está libre en esta franja. "
            "Usá acción 'libre'."
        )
        return horario_editado, None, errores

    if accion == "reassign":
        if aula_para_desplazado == horario_editado.aula_id:
            errores.append(
                f"Reasignar el desplazado al aula original del editado "
                f"es equivalente a hacer swap. Usá acción 'swap'."
            )

    return horario_editado, ocupante, errores


def preview_reasignacion_con_desplazamiento(
    session: Session,
    plan_id: str,
    horario_id: str,
    aula_nueva_id: str,
    *,
    accion: str,
    aula_para_desplazado: Optional[str] = None,
) -> PreviewReasignacion:
    """Efecto hipotético de una reasignación con desplazamiento SIN
    persistir.

    Corre ``_validar_aula_para_horario`` sobre el editado con el aula
    nueva, y (según la acción) sobre el desplazado con su aula futura.

    Args:
        plan_id: id del plan.
        horario_id: horario a editar (obtiene ``aula_nueva_id``).
        aula_nueva_id: aula destino del editado.
        accion: una de ``_ACCIONES_REASIGNACION``.
        aula_para_desplazado: sólo relevante si accion=="reassign".

    Returns:
        PreviewReasignacion con banderas ``editado_ok`` /
        ``desplazado_ok`` y la lista de errores.

    Raises:
        ValueError: si ``accion`` es inválida o si accion=="reassign"
            pero ``aula_para_desplazado`` es None.
    """
    if accion not in _ACCIONES_REASIGNACION:
        raise ValueError(
            f"accion inválida: '{accion}'. Válidas: "
            f"{_ACCIONES_REASIGNACION}."
        )
    if accion == "reassign" and aula_para_desplazado is None:
        raise ValueError(
            "aula_para_desplazado es requerido con accion='reassign'."
        )

    horario_editado, ocupante, errores_forma = _validar_reasignacion(
        session, plan_id, horario_id, aula_nueva_id, accion,
        aula_para_desplazado,
    )
    if errores_forma:
        return PreviewReasignacion(
            editado_ok=False,
            editado_aula_futura=None,
            errores=errores_forma,
        )

    aula_nueva = session.get(AulaDB, aula_nueva_id)
    assert aula_nueva is not None
    aula_original_editado = horario_editado.aula_id

    # Validar el editado tomando aula_nueva. Para esto necesitamos
    # simular sin persistir. La estrategia: hacer un "flush hipotético"
    # temporal — tocar los aula_id in-memory, correr los validators,
    # y rollback.
    prev = PreviewReasignacion(editado_ok=True, editado_aula_futura=aula_nueva_id)
    errores_all: list[str] = []

    # Para no depender del rollback (frágil con SQLModel), usamos una
    # validación manual: la lógica de _validar_aula_para_horario
    # chequea (a) compatibilidad tipo, (b) sede admisible (implícito
    # via el filtro de get_aulas_*), y (c) choque con otros horarios
    # del plan. Para simular el swap sin persistir, computamos "otros
    # aulas ocupadas en la franja" excluyendo el ocupante (que se va a
    # mover) y el propio horario editado.
    def _check_compat(horario: HorarioDB, aula: AulaDB) -> list[str]:
        errs: list[str] = []
        tipo = horario.tipo_clase
        if tipo == "laboratorio":
            comision = session.get(ComisionDB, horario.comision_id)
            if comision is None:
                errs.append("Comisión no encontrada.")
                return errs
            compat_set = {
                ml.aula_id for ml in session.exec(
                    select(MateriaLaboratorioDB).where(
                        MateriaLaboratorioDB.materia_codigo
                        == comision.materia_codigo
                    )
                ).all()
            }
            if aula.id not in compat_set:
                errs.append(
                    f"El aula '{aula.nombre}' no es laboratorio compatible "
                    f"con la materia {comision.materia_codigo}."
                )
        elif tipo == "teorica":
            if aula.tipo not in ("teorica", "anfiteatro"):
                errs.append(
                    f"El aula '{aula.nombre}' es de tipo '{aula.tipo}' y "
                    "no admite clase teórica."
                )
        # Sede admisible.
        comision = session.get(ComisionDB, horario.comision_id)
        materia_codigo = comision.materia_codigo if comision else None
        _com_override = comision.carrera_asignada if comision else None
        from src.services.carrera_sede_service import (
            sedes_admisibles_para_carrera,
            sedes_admisibles_para_materia,
        )
        if _com_override:
            admisibles = sedes_admisibles_para_carrera(session, _com_override)
        elif materia_codigo:
            admisibles = sedes_admisibles_para_materia(session, materia_codigo)
        else:
            admisibles = None
        if admisibles is not None:
            lab_ids: set[str] = set()
            if materia_codigo:
                lab_ids = {
                    ml.aula_id for ml in session.exec(
                        select(MateriaLaboratorioDB).where(
                            MateriaLaboratorioDB.materia_codigo == materia_codigo
                        )
                    ).all()
                }
            if aula.id not in lab_ids and aula.sede_id not in admisibles:
                errs.append(
                    f"El aula '{aula.nombre}' está en una sede "
                    "no admisible para la materia/carrera."
                )
        return errs

    # 1) Validar editado.
    errs_ed = _check_compat(horario_editado, aula_nueva)
    if errs_ed:
        prev.editado_ok = False
        errores_all.extend(errs_ed)

    # 2) Según acción, determinar y validar el desplazado.
    if accion == "libre":
        pass
    else:
        assert ocupante is not None
        prev.desplazado_horario_id = ocupante.id
        if accion == "swap":
            prev.desplazado_aula_futura = aula_original_editado
            if aula_original_editado is None:
                prev.desplazado_ok = False
                errores_all.append(
                    "No se puede hacer swap: el horario editado no tiene "
                    "aula asignada actualmente."
                )
            else:
                aula_para_desp = session.get(AulaDB, aula_original_editado)
                if aula_para_desp is None:
                    prev.desplazado_ok = False
                    errores_all.append(
                        f"Aula original '{aula_original_editado}' no encontrada."
                    )
                else:
                    errs_de = _check_compat(ocupante, aula_para_desp)
                    if errs_de:
                        prev.desplazado_ok = False
                        errores_all.extend(errs_de)
        elif accion == "reassign":
            assert aula_para_desplazado is not None
            prev.desplazado_aula_futura = aula_para_desplazado
            aula_desp = session.get(AulaDB, aula_para_desplazado)
            if aula_desp is None:
                prev.desplazado_ok = False
                errores_all.append(
                    f"Aula '{aula_para_desplazado}' no encontrada."
                )
            else:
                errs_de = _check_compat(ocupante, aula_desp)
                if errs_de:
                    prev.desplazado_ok = False
                    errores_all.extend(errs_de)
        elif accion == "unassign":
            prev.desplazado_aula_futura = None
            # Sin aula no hay validación de compatibilidad — siempre ok.

    prev.errores = errores_all
    return prev


def reasignar_con_desplazamiento(
    session: Session,
    plan_id: str,
    horario_id: str,
    aula_nueva_id: str,
    *,
    accion: str,
    aula_para_desplazado: Optional[str] = None,
) -> ValidationResult:
    """Aplica una reasignación con desplazamiento en una sola
    transacción atómica.

    Estrategia:
    1. Corre ``preview_reasignacion_con_desplazamiento`` para validar
       todo antes de tocar la DB.
    2. Si preview.ok, aplica en orden seguro:
       a) Deja al desplazado sin aula temporalmente (para liberar).
       b) Asigna al editado su aula nueva.
       c) Asigna al desplazado su aula futura (o lo deja sin aula
          según acción).

    Si algo falla, no persiste nada.

    Args, raises: idénticos a ``preview_reasignacion_con_desplazamiento``.

    Returns:
        ValidationResult con ok=True si se aplicó todo, o
        ``errores`` explicando por qué falló.
    """
    if accion not in _ACCIONES_REASIGNACION:
        raise ValueError(
            f"accion inválida: '{accion}'. Válidas: "
            f"{_ACCIONES_REASIGNACION}."
        )
    if accion == "reassign" and aula_para_desplazado is None:
        raise ValueError(
            "aula_para_desplazado es requerido con accion='reassign'."
        )

    # Preview primero — atrapa validaciones de forma y compatibilidad.
    prev = preview_reasignacion_con_desplazamiento(
        session, plan_id, horario_id, aula_nueva_id,
        accion=accion, aula_para_desplazado=aula_para_desplazado,
    )
    if not (prev.editado_ok and prev.desplazado_ok):
        res = ValidationResult(ok=False)
        res.errores = list(prev.errores)
        return res

    horario_editado = session.get(HorarioDB, horario_id)
    assert horario_editado is not None

    # Aplicar en orden seguro para evitar choques transitorios.
    if accion == "libre":
        return cambiar_aula_horario(
            session, horario_id, aula_nueva_id,
        )

    # accion in {swap, reassign, unassign} → hay ocupante.
    ocupante = get_ocupante_de_aula_en_franja(
        session, plan_id, horario_id, aula_nueva_id,
    )
    assert ocupante is not None

    # 1) Liberar al ocupante temporalmente.
    res1 = cambiar_aula_horario(session, ocupante.id, aula_id=None)
    if not res1.ok:
        # Muy improbable si preview pasó, pero por defensa:
        return res1

    # 2) Asignar aula nueva al editado.
    res2 = cambiar_aula_horario(session, horario_id, aula_nueva_id)
    if not res2.ok:
        # Restaurar ocupante a su aula original (best effort).
        cambiar_aula_horario(session, ocupante.id, aula_nueva_id)
        return res2

    # 3) Asignar el aula futura al desplazado.
    if accion == "swap":
        aula_para_desp = horario_editado.aula_id  # es la aula_nueva ahora
        # Pero necesitamos la aula ORIGINAL del editado, que ya no está
        # en horario_editado.aula_id (porque la sobreescribimos).
        # Usamos prev.desplazado_aula_futura que tiene el valor
        # correcto capturado antes del cambio.
        aula_para_desp = prev.desplazado_aula_futura
        assert aula_para_desp is not None
        res3 = cambiar_aula_horario(session, ocupante.id, aula_para_desp)
    elif accion == "reassign":
        assert aula_para_desplazado is not None
        res3 = cambiar_aula_horario(session, ocupante.id, aula_para_desplazado)
    else:  # unassign
        # Ya está en None, no hay nada que hacer.
        res3 = ValidationResult(ok=True)

    if not res3.ok:
        # Best effort de rollback.
        cambiar_aula_horario(session, ocupante.id, aula_nueva_id)
        cambiar_aula_horario(session, horario_id, horario_editado.aula_id)
        return res3

    return ValidationResult(ok=True)
