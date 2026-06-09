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
    compute_heatmap_carga,
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

    # Map materia_codigo -> set[aula_id] desde MateriaLaboratorioDB.
    matlab_pairs = list(session.exec(select(MateriaLaboratorioDB)).all())
    materia_lab_map: dict[str, set[str]] = {}
    for ml in matlab_pairs:
        materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

    # Materias del plan (para filtrar virtuales y para R5).
    materias_db = list(session.exec(select(MateriaDB)).all())
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

    horarios_db = list(session.exec(
        select(HorarioDB).where(HorarioDB.comision_id.in_(comision_ids))  # type: ignore[attr-defined]
    ).all()) if comision_ids else []

    warnings: list[str] = []

    horarios: list[HorarioSlot] = []
    materia_de_horario: dict[str, str] = {}
    comision_de_horario: dict[str, str] = {}
    dur: dict[str, float] = {}

    for h in horarios_db:
        if materia_virtual.get(h.codigo_materia, False):
            warnings.append(
                f"Horario {h.id} excluido: materia {h.codigo_materia} es virtual"
            )
            continue
        horarios.append(HorarioSlot(
            id=h.id,
            dia=h.dia,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            materia_codigo=h.codigo_materia,
            tipo_clase=h.tipo_clase,
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

    # Compatibilidad pre-computada.
    compat: dict[tuple[str, str], bool] = {}
    for h in horarios:
        lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas:
            compat[(h.id, a.id)] = compute_compat(h, a, lab_aulas_m)

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
) -> tuple[pulp.LpProblem, dict]:
    """Instancia el modelo PuLP con R1, R3 (compatibilidad), R4 (no
    doble booking), R5 (partición teoría/lab), R6 (consistencia
    tipo↔aula), R7 (penalty de capacidad).

    Returns:
        (problem, vars_dict) donde vars_dict tiene las variables x, t,
        over, under indexadas para que ``solve`` las pueda leer.
    """
    prob = pulp.LpProblem("asignacion_aulas", pulp.LpMinimize)

    # Variables x[h, a] solo para pares compatibles (R3 pre-computada).
    x: dict[tuple[str, str], pulp.LpVariable] = {}
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
    """Propaga la asignación de la semana modelo a las ClaseDB del plan.

    Para cada (horario_id, aula_id) en ``solution.x_assignments``:
    selecciona las ClaseDB con ``horario_id`` igual, ``fecha >= fecha_desde``,
    ``executed = False``. Si ``respetar_manuales=True`` además filtra
    ``aula_asignada_manualmente = False``.

    A las clases seleccionadas se les setea ``aula_id`` y se deja el flag
    ``aula_asignada_manualmente = False`` (porque viene del LP, no del
    usuario). Si el flag estaba en True y respetar_manuales=False, se
    resetea a False (el LP toma el control).
    """
    if solution.status != "optimal":
        return ApplyResult()

    apply_result = ApplyResult()

    for horario_id, aula_id in solution.x_assignments.items():
        query = select(ClaseDB).where(
            ClaseDB.horario_id == horario_id,
            ClaseDB.fecha >= fecha_desde,
            ClaseDB.executed == False,  # noqa: E712
            ClaseDB.plan_cursada_id == plan_id,
        )
        clases = list(session.exec(query).all())
        tipo_nuevo = solution.tipo_resuelto.get(horario_id)
        for c in clases:
            if respetar_manuales and c.aula_asignada_manualmente:
                apply_result.n_ediciones_manuales_respetadas += 1
                continue
            c.aula_id = aula_id
            c.aula_asignada_manualmente = False
            # Propagar tipo_clase si el LP lo decidió (sólo para los que
            # tenían None en el horario).
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
    heatmap = compute_heatmap_carga(inputs.horarios)
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
        "heatmap_carga": heatmap,
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
) -> LPRunDB:
    """Inserta una fila en LPRunDB con la corrida y su resumen.

    Si ``solution.status != 'optimal'`` y se pasa un ``diagnosis``, el
    detalle estructural se persiste en details_json y se incorpora a
    ``error_message`` un resumen humano.
    """
    details = _build_details_json(inputs, solution, config)
    n_sobre = details["n_sobreocupados"]
    n_sub = details["n_subutilizados"]

    error_message = solution.error_message
    if diagnosis is not None:
        details["infeasibility_diagnosis"] = {
            "horarios_sin_aula_compatible":
                diagnosis.horarios_sin_aula_compatible,
            "franjas_saturadas": diagnosis.franjas_saturadas,
            "inventario_aulas": diagnosis.inventario_aulas,
            "particion_problemas": diagnosis.particion_problemas,
        }
        if diagnosis.is_infeasible():
            msgs = diagnosis.to_messages()
            # Anteponer el resumen estructural al mensaje del solver.
            error_message = (
                "Infactibilidad estructural detectada:\n"
                + "\n".join(msgs[:5])
                + (f"\n(+ {len(msgs) - 5} más)" if len(msgs) > 5 else "")
                + (f"\n— Solver: {solution.error_message}"
                   if solution.error_message else "")
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
    """
    cfg = config or LPConfig()
    inputs = build_inputs(session, plan_id, cfg)

    # Diagnóstico estructural — se computa siempre (incluso si el LP
    # resuelve OK, queda como warning informativo en el snapshot).
    diagnosis = diagnose(inputs)

    prob, vars_dict = build_model(inputs, cfg)
    solution = solve(prob, vars_dict, cfg)

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
        apply_result, diagnosis=diagnosis,
    )


# =============================================================================
# Edición manual de aula sobre ClaseDB (Fase 7)
# =============================================================================

def clases_del_rango(
    session: Session,
    clase_referencia_id: str,
    *,
    fecha_desde: Optional[date] = None,
    fecha_hasta: Optional[date] = None,
) -> list[ClaseDB]:
    """Devuelve las clases de la misma comisión y mismo (día, hora) que
    la clase de referencia, en el rango de fechas dado.

    Si ``fecha_desde`` o ``fecha_hasta`` son None, no se aplican esos
    bordes (se toman todas las del ciclo en esa dirección). Filtra
    siempre ``executed=False``.
    """
    ref = session.get(ClaseDB, clase_referencia_id)
    if ref is None:
        return []
    query = select(ClaseDB).where(
        ClaseDB.plan_cursada_id == ref.plan_cursada_id,
        ClaseDB.comision_id == ref.comision_id,
        ClaseDB.hora_inicio == ref.hora_inicio,
        ClaseDB.hora_fin == ref.hora_fin,
        ClaseDB.executed == False,  # noqa: E712
    )
    if fecha_desde is not None:
        query = query.where(ClaseDB.fecha >= fecha_desde)
    if fecha_hasta is not None:
        query = query.where(ClaseDB.fecha <= fecha_hasta)
    candidatas = list(session.exec(query).all())
    # Filtrar por mismo día de la semana (la query ya filtra hora pero
    # podría haber clases en otro día con misma hora).
    return [c for c in candidatas if c.fecha.weekday() == ref.fecha.weekday()]


def get_aulas_disponibles(
    session: Session,
    plan_id: str,
    clase_ids: list[str],
    *,
    excluir_ediciones_manuales_propias: bool = True,
) -> list[AulaDB]:
    """Para un conjunto de ClaseDB que se quieren editar simultáneamente,
    devuelve las aulas que están libres en TODAS sus fechas y franjas, y
    son compatibles por tipo con el ``tipo_clase`` de las clases.

    Args:
        session: SQLAlchemy session.
        plan_id: ID del plan (para limitar el contexto de búsqueda de
            colisiones).
        clase_ids: las clases que estamos por editar. Sus aulas actuales
            se ignoran (no se cuentan como ocupando aula, porque el
            usuario las está liberando para reasignar).
        excluir_ediciones_manuales_propias: si True, no filtra por
            choques con las propias clases de ``clase_ids``.

    Returns:
        Lista de AulaDB candidatas, ordenadas por capacidad ascendente.
    """
    if not clase_ids:
        return []
    clases = list(session.exec(
        select(ClaseDB).where(ClaseDB.id.in_(clase_ids))  # type: ignore[attr-defined]
    ).all())
    if not clases:
        return []
    # Tipo de clase requerido. Si las clases no tienen el mismo tipo,
    # algo raro pasa — devolvemos vacío para no asignar mal.
    tipos = {c.tipo_clase for c in clases}
    if len(tipos) > 1:
        return []
    tipo_clase = tipos.pop()

    # Materia (necesaria para A_lab si tipo=lab).
    com_ids = {c.comision_id for c in clases}
    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())
    materias = {c.materia_codigo for c in comisiones}
    if len(materias) > 1:
        return []
    materia_codigo = materias.pop() if materias else None

    aulas_db = list(session.exec(
        select(AulaDB).order_by(AulaDB.capacidad)  # type: ignore[attr-defined]
    ).all())

    # Aulas compatibles por tipo.
    compat_aulas: list[AulaDB] = []
    if tipo_clase == "laboratorio":
        if materia_codigo:
            lab_ids = {
                ml.aula_id for ml in session.exec(
                    select(MateriaLaboratorioDB).where(
                        MateriaLaboratorioDB.materia_codigo == materia_codigo
                    )
                ).all()
            }
            compat_aulas = [a for a in aulas_db if a.id in lab_ids]
    elif tipo_clase == "teorica":
        compat_aulas = [
            a for a in aulas_db if a.tipo in ("teorica", "anfiteatro")
        ]
    else:
        # Sin determinar: cualquier aula es candidata
        compat_aulas = list(aulas_db)

    # Para cada aula candidata, chequear que no esté ocupada en NINGUNA
    # de las (fecha, hora_inicio, hora_fin) de las clases a editar, por
    # otra clase distinta de las que estamos editando.
    clase_ids_set = set(clase_ids)
    fechas_franjas = [(c.fecha, c.hora_inicio, c.hora_fin) for c in clases]
    disponibles: list[AulaDB] = []
    for aula in compat_aulas:
        ocupada = False
        for fecha, hi, hf in fechas_franjas:
            choque = session.exec(
                select(ClaseDB).where(
                    ClaseDB.aula_id == aula.id,
                    ClaseDB.fecha == fecha,
                    ClaseDB.hora_inicio < hf,
                    ClaseDB.hora_fin > hi,
                    ClaseDB.id.notin_(clase_ids_set),  # type: ignore[attr-defined]
                ).limit(1)
            ).first()
            if choque is not None:
                ocupada = True
                break
        if not ocupada:
            disponibles.append(aula)
    return disponibles


def validar_edicion_manual(
    session: Session,
    clase_ids: list[str],
    aula_nueva_id: str,
) -> ValidationResult:
    """Valida que cambiar el aula de las clases ``clase_ids`` a
    ``aula_nueva_id`` no rompa restricciones del modelo.

    Chequeos:
    - R3 / R6: tipo del aula compatible con tipo_clase de las clases.
    - R4: ninguna otra ClaseDB del plan choca temporalmente con las
      editadas en la misma aula.
    - R7 (warning, no bloquea): capacidad del aula >= esperados de la
      clase.
    """
    res = ValidationResult(ok=True)
    if not clase_ids:
        res.ok = False
        res.errores.append("No hay clases para editar.")
        return res
    aula = session.get(AulaDB, aula_nueva_id)
    if aula is None:
        res.ok = False
        res.errores.append(f"Aula '{aula_nueva_id}' no encontrada.")
        return res
    clases = list(session.exec(
        select(ClaseDB).where(ClaseDB.id.in_(clase_ids))  # type: ignore[attr-defined]
    ).all())
    if not clases:
        res.ok = False
        res.errores.append("No se encontraron las clases especificadas.")
        return res

    # Validación de tipo: todas las clases deben tener el mismo tipo
    # (la edición de rango se construye así). Y el aula debe ser
    # compatible.
    tipos = {c.tipo_clase for c in clases}
    if len(tipos) > 1:
        res.ok = False
        res.errores.append(
            "Las clases del rango tienen distinto tipo_clase, no se "
            "puede editar en bloque."
        )
        return res
    tipo_clase = tipos.pop()
    if tipo_clase == "laboratorio":
        com = clases[0].comision_id
        comision_db = session.get(ComisionDB, com)
        if comision_db is None:
            res.ok = False
            res.errores.append("Comisión no encontrada.")
            return res
        compat_set = {
            ml.aula_id for ml in session.exec(
                select(MateriaLaboratorioDB).where(
                    MateriaLaboratorioDB.materia_codigo
                    == comision_db.materia_codigo
                )
            ).all()
        }
        if aula.id not in compat_set:
            res.ok = False
            res.errores.append(
                f"El aula '{aula.nombre}' no es laboratorio compatible "
                f"con la materia {comision_db.materia_codigo}."
            )
            return res
    elif tipo_clase == "teorica":
        if aula.tipo not in ("teorica", "anfiteatro"):
            res.ok = False
            res.errores.append(
                f"El aula '{aula.nombre}' es de tipo '{aula.tipo}' y la "
                f"clase es teórica."
            )
            return res

    # No doble booking.
    clase_ids_set = set(clase_ids)
    for c in clases:
        choque = session.exec(
            select(ClaseDB).where(
                ClaseDB.aula_id == aula.id,
                ClaseDB.fecha == c.fecha,
                ClaseDB.hora_inicio < c.hora_fin,
                ClaseDB.hora_fin > c.hora_inicio,
                ClaseDB.id.notin_(clase_ids_set),  # type: ignore[attr-defined]
            ).limit(1)
        ).first()
        if choque is not None:
            res.ok = False
            res.errores.append(
                f"El aula '{aula.nombre}' está ocupada el "
                f"{c.fecha.isoformat()} de "
                f"{c.hora_inicio.strftime('%H:%M')} a "
                f"{c.hora_fin.strftime('%H:%M')} por otra clase."
            )
            return res

    # Warning de capacidad (no bloquea).
    com = clases[0].comision_id
    insc_por_com = get_inscriptos_esperados_por_comision(
        session, clases[0].plan_cursada_id,
    )
    esperados = insc_por_com.get(com)
    if esperados is not None and aula.capacidad < esperados:
        res.warnings.append(
            f"⚠️ Capacidad ({aula.capacidad}) menor que esperados "
            f"({esperados:.0f}). La asignación es válida pero generará "
            f"sobre-ocupación."
        )

    return res


def aplicar_edicion_manual(
    session: Session,
    clase_ids: list[str],
    aula_nueva_id: str,
) -> int:
    """Aplica la edición a las ClaseDB y marca el flag manual. Asume que
    ``validar_edicion_manual`` fue invocado y devolvió ok=True.

    Returns: cantidad de clases efectivamente actualizadas.
    """
    n = 0
    clases = list(session.exec(
        select(ClaseDB).where(ClaseDB.id.in_(clase_ids))  # type: ignore[attr-defined]
    ).all())
    for c in clases:
        c.aula_id = aula_nueva_id
        c.aula_asignada_manualmente = True
        session.add(c)
        n += 1
    session.commit()
    return n


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
