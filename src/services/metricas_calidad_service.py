"""Métricas de calidad del resultado del asignador (Fase 6).

Consolida en un único servicio las métricas dispersas para que el
operador pueda evaluar a simple vista la calidad de una corrida del
LP y compararla contra otras configuraciones.

Cuatro familias de métricas:

- **Cobertura global (A)**: horarios asignados / total, horarios sin
  aula, horarios en sede preferida vs alternativa.
- **Sobre/sub ocupación (B)**: conteos, totales agregados en asientos
  faltantes/ociosos, ratios promedios y P50/P90, peor caso.
- **Distribución de aulas (C)**: aulas usadas / total, aulas nunca
  usadas, aulas con carga alta, concentración de ocupación por sede.
- **Estabilidad del LP (D)**: valor de objetivo, tiempo de solve,
  ediciones manuales respetadas, sedes distintas por comisión / día.

La función principal `compute_metricas_calidad` lee del estado
actual (`HorarioDB.aula_id` + forecast). Devuelve un dict tipado
para que la UI arme el panel sin re-computar nada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from typing import Any, Optional

from sqlmodel import Session, select

from src.database.models import (
    AulaDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    LPRunDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_helpers import (
    sede_preferida_desde_sets,
)
from src.services.grupo_materia_service import (
    sedes_admisibles_set_por_materia,
)
from src.services.plan_generation_service import (
    get_inscriptos_esperados_por_comision,
)
from src.services.resolucion_jerarquica import resolve_virtual


# =============================================================================
# Dataclasses de salida
# =============================================================================


@dataclass
class MetricasCobertura:
    """Familia A: cobertura global."""
    n_horarios_total: int = 0
    n_horarios_asignados: int = 0
    n_horarios_sin_aula: int = 0
    n_horarios_en_sede_preferida: int = 0
    n_horarios_en_sede_alternativa: int = 0
    n_horarios_sin_sede_preferida: int = 0
    n_comisiones_total: int = 0
    n_comisiones_completas: int = 0


@dataclass
class MetricasOcupacion:
    """Familia B: sobre y sub ocupación."""
    n_sobreocupados: int = 0
    n_subutilizados: int = 0
    n_ok: int = 0
    sobrecupo_total_asientos: int = 0
    subutilizacion_total_asientos: int = 0
    ratio_promedio: float = 0.0
    ratio_p50: float = 0.0
    ratio_p90: float = 0.0
    peor_sobreocupado: Optional[dict] = None
    peor_subutilizado: Optional[dict] = None


@dataclass
class MetricasAulas:
    """Familia C: distribución de aulas."""
    n_aulas_catalogo: int = 0
    n_aulas_usadas: int = 0
    n_aulas_ociosas: int = 0
    aulas_ociosas: list[dict] = field(default_factory=list)
    n_aulas_carga_alta: int = 0
    umbral_carga_alta: float = 0.7
    concentracion_por_sede: list[dict] = field(default_factory=list)


@dataclass
class MetricasLP:
    """Familia D: estabilidad del LP y traslados."""
    objetivo: Optional[float] = None
    tiempo_solve_segundos: Optional[float] = None
    n_ediciones_manuales_respetadas: Optional[int] = None
    n_comisiones_con_traslado_intersede: int = 0
    detalle_traslados: list[dict] = field(default_factory=list)
    fecha_ultima_corrida: Optional[str] = None
    status_ultima_corrida: Optional[str] = None


@dataclass
class MetricasCalidad:
    """Contenedor de las 4 familias + metadata para debug."""
    cobertura: MetricasCobertura = field(default_factory=MetricasCobertura)
    ocupacion: MetricasOcupacion = field(default_factory=MetricasOcupacion)
    aulas: MetricasAulas = field(default_factory=MetricasAulas)
    lp: MetricasLP = field(default_factory=MetricasLP)


# =============================================================================
# Cálculo
# =============================================================================


def compute_metricas_calidad(
    session: Session,
    plan_id: str,
    *,
    umbral_carga_alta: float = 0.7,
    umbral_traslado_minutos: int = 30,
) -> MetricasCalidad:
    """Computa el panel de métricas de calidad del plan.

    Todo se computa contra el estado actual de la DB (no del
    LPRunDB.details_json). Cuando existe un LPRun reciente, algunas
    métricas D se leen de ahí (objetivo, tiempo, ediciones respetadas).

    Args:
        session: sesión de SQLModel.
        plan_id: id del plan a analizar.
        umbral_carga_alta: fracción de franjas del catálogo que un aula
            debe tener ocupadas para considerarse "carga alta".
            0.7 = 70% del catálogo.
        umbral_traslado_minutos: gap máximo (min) entre dos horarios de
            la misma comisión para considerar el par como "traslado
            intersede" cuando quedan en sedes distintas. Debería
            coincidir con `LPConfig.margen_min_intersede_minutos`.

    Returns:
        ``MetricasCalidad`` con las 4 familias pobladas.
    """
    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        return MetricasCalidad()

    metricas = MetricasCalidad()
    metricas.aulas.umbral_carga_alta = umbral_carga_alta

    # -------------------------------------------------------------------------
    # Datos base
    # -------------------------------------------------------------------------
    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    com_ids = [c.id for c in comisiones]
    metricas.cobertura.n_comisiones_total = len(comisiones)
    carrera_asignada_por_comision: dict[str, Optional[str]] = {
        c.id: c.carrera_asignada for c in comisiones
    }

    if not com_ids:
        return metricas

    horarios_db = list(session.exec(
        select(HorarioDB).where(HorarioDB.comision_id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())

    # Filtrar horarios virtuales (misma lógica que build_inputs).
    mat_codes = sorted({h.codigo_materia for h in horarios_db})
    materias = list(session.exec(
        select(MateriaDB).where(MateriaDB.codigo.in_(mat_codes))  # type: ignore[attr-defined]
    ).all()) if mat_codes else []
    materia_virtual = {m.codigo: m.virtual for m in materias}
    materia_dict_virtual: dict[str, Optional[bool]] = {}
    if plan.ciclo_id:
        for mc, v in session.exec(
            select(DictadoDB.materia_codigo, DictadoDB.virtual)
            .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)  # type: ignore[arg-type]
            .where(DictadoCicloDB.ciclo_id == plan.ciclo_id)
        ).all():
            materia_dict_virtual[mc] = v

    horarios = [
        h for h in horarios_db
        if not resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dict_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        )
    ]
    metricas.cobertura.n_horarios_total = len(horarios)

    # Aulas y sedes.
    aulas_db = list(session.exec(select(AulaDB)).all())
    aula_sede_id: dict[str, str] = {a.id: a.sede_id for a in aulas_db}
    aula_nombre: dict[str, str] = {a.id: a.codigo_aula for a in aulas_db}
    aula_capacidad: dict[str, int] = {a.id: a.capacidad for a in aulas_db}
    aula_tipo: dict[str, str] = {a.id: a.tipo for a in aulas_db}

    sedes = list(session.exec(select(SedeDB)).all())
    sede_nombre: dict[str, str] = {s.id: s.nombre for s in sedes}

    # Labs por materia.
    lab_pairs = list(session.exec(select(MateriaLaboratorioDB)).all())
    materia_lab_map: dict[str, set[str]] = {}
    for ml in lab_pairs:
        materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

    # Sedes admisibles resueltas por HORARIO vía Grupo de Materias.
    # ``ComisionDB.carrera_asignada`` quedó como etiqueta visual y no
    # interviene en la resolución (el LP tampoco la usa — ver
    # `asignacion_aulas_service.build_inputs`, sección R10). Todo se
    # resuelve por la materia y su grupo.
    #
    # Nota: acá pasamos ``modos_por_grupo={}`` porque las métricas se
    # calculan sobre una corrida ya persistida y no conocemos el modo
    # con el que corrió el LP. Asumir DURO como default es coherente
    # con el fallback del LP cuando no hay override por-grupo, y
    # devuelve el filtro más restrictivo — coincide con lo que el
    # inspector de la corrida muestra como "sedes duras".
    sedes_admis_por_materia: dict[str, Optional[set[str]]] = {
        mc: sedes_admisibles_set_por_materia(session, mc)
        for mc in mat_codes
    }

    def _sedes_admisibles_del_horario(h: HorarioDB) -> Optional[set[str]]:
        return sedes_admis_por_materia.get(h.codigo_materia)

    # Forecast por comisión.
    forecast_por_com = get_inscriptos_esperados_por_comision(session, plan_id)

    # -------------------------------------------------------------------------
    # Familia A: cobertura global
    # -------------------------------------------------------------------------
    comisiones_completas: set[str] = set(com_ids)  # empieza como todas; sale la que tenga un horario sin aula
    for h in horarios:
        if not h.aula_id:
            metricas.cobertura.n_horarios_sin_aula += 1
            comisiones_completas.discard(h.comision_id)
            continue
        metricas.cobertura.n_horarios_asignados += 1
        # ¿Está en sede preferida?
        admis = _sedes_admisibles_del_horario(h)
        labs = materia_lab_map.get(h.codigo_materia, set())
        sede_pref = sede_preferida_desde_sets(
            labs_de_materia=labs,
            sedes_admisibles=admis,
            aula_sede_id=aula_sede_id,
        )
        sede_asignada = aula_sede_id.get(h.aula_id)
        if sede_pref is None:
            metricas.cobertura.n_horarios_sin_sede_preferida += 1
        elif sede_asignada == sede_pref:
            metricas.cobertura.n_horarios_en_sede_preferida += 1
        else:
            metricas.cobertura.n_horarios_en_sede_alternativa += 1
    metricas.cobertura.n_comisiones_completas = len(comisiones_completas)

    # -------------------------------------------------------------------------
    # Familia B: sobre/sub ocupación
    # -------------------------------------------------------------------------
    tol_under_default = 0.20  # coherente con LPConfig default
    ratios: list[float] = []
    peor_sobre = None
    peor_sub = None
    for h in horarios:
        if not h.aula_id:
            continue
        cap = aula_capacidad.get(h.aula_id, 0)
        insc = forecast_por_com.get(h.comision_id, 0.0)
        if cap <= 0:
            continue
        ratio = insc / cap
        ratios.append(ratio)
        materia_info = next((m for m in materias if m.codigo == h.codigo_materia), None)
        mat_nombre = materia_info.nombre if materia_info else h.codigo_materia
        comision = next((c for c in comisiones if c.id == h.comision_id), None)
        com_nombre = comision.nombre if comision else "?"
        if insc > cap:
            metricas.ocupacion.n_sobreocupados += 1
            metricas.ocupacion.sobrecupo_total_asientos += int(insc - cap)
            item = {
                "materia": h.codigo_materia,
                "materia_nombre": mat_nombre,
                "comision": com_nombre,
                "dia": h.dia,
                "hora_inicio": h.hora_inicio.strftime("%H:%M"),
                "hora_fin": h.hora_fin.strftime("%H:%M"),
                "aula": aula_nombre.get(h.aula_id, "?"),
                "capacidad": cap,
                "inscriptos_esperados": int(insc),
                "faltantes": int(insc - cap),
            }
            if peor_sobre is None or item["faltantes"] > peor_sobre["faltantes"]:
                peor_sobre = item
        elif insc < cap * (1 - tol_under_default):
            metricas.ocupacion.n_subutilizados += 1
            asientos_ociosos = int(cap - insc)
            metricas.ocupacion.subutilizacion_total_asientos += asientos_ociosos
            item = {
                "materia": h.codigo_materia,
                "materia_nombre": mat_nombre,
                "comision": com_nombre,
                "dia": h.dia,
                "hora_inicio": h.hora_inicio.strftime("%H:%M"),
                "hora_fin": h.hora_fin.strftime("%H:%M"),
                "aula": aula_nombre.get(h.aula_id, "?"),
                "capacidad": cap,
                "inscriptos_esperados": int(insc),
                "ociosos": asientos_ociosos,
            }
            if peor_sub is None or item["ociosos"] > peor_sub["ociosos"]:
                peor_sub = item
        else:
            metricas.ocupacion.n_ok += 1

    if ratios:
        ratios_sorted = sorted(ratios)
        n = len(ratios_sorted)
        metricas.ocupacion.ratio_promedio = sum(ratios_sorted) / n
        metricas.ocupacion.ratio_p50 = ratios_sorted[n // 2]
        p90_idx = min(n - 1, int(n * 0.9))
        metricas.ocupacion.ratio_p90 = ratios_sorted[p90_idx]
    metricas.ocupacion.peor_sobreocupado = peor_sobre
    metricas.ocupacion.peor_subutilizado = peor_sub

    # -------------------------------------------------------------------------
    # Familia C: distribución de aulas
    # -------------------------------------------------------------------------
    metricas.aulas.n_aulas_catalogo = len(aulas_db)
    aulas_usadas: dict[str, int] = {}  # aula_id -> cantidad de horarios activos
    for h in horarios:
        if h.aula_id:
            aulas_usadas[h.aula_id] = aulas_usadas.get(h.aula_id, 0) + 1
    metricas.aulas.n_aulas_usadas = len(aulas_usadas)
    metricas.aulas.n_aulas_ociosas = (
        len(aulas_db) - len(aulas_usadas)
    )
    # Detalle de aulas ociosas.
    for a in aulas_db:
        if a.id not in aulas_usadas:
            metricas.aulas.aulas_ociosas.append({
                "aula_id": a.id,
                "aula_nombre": a.codigo_aula,
                "sede": sede_nombre.get(a.sede_id, "?"),
                "tipo": a.tipo,
                "capacidad": a.capacidad,
            })
    metricas.aulas.aulas_ociosas.sort(
        key=lambda x: (x["sede"], x["aula_nombre"]),
    )

    # Aulas con carga alta: aula con >= umbral * (n_franjas_totales_del_plan).
    # Aproximamos "franjas del plan" como el número total de horarios
    # activos / n_aulas_usadas (uso promedio). Alternativa más simple:
    # n_horarios_del_aula / max(1, uso_promedio) ≥ umbral.
    if aulas_usadas:
        uso_promedio = sum(aulas_usadas.values()) / len(aulas_usadas)
        metricas.aulas.n_aulas_carga_alta = sum(
            1 for n in aulas_usadas.values()
            if n >= uso_promedio * (1 + umbral_carga_alta)
        )

    # Concentración por sede.
    ocupacion_por_sede: dict[str, int] = {}
    for a_id, n in aulas_usadas.items():
        sede = aula_sede_id.get(a_id)
        if sede is None:
            continue
        ocupacion_por_sede[sede] = ocupacion_por_sede.get(sede, 0) + n
    total_ocupacion = sum(ocupacion_por_sede.values()) or 1
    for sede, ocup in sorted(
        ocupacion_por_sede.items(), key=lambda x: -x[1],
    ):
        metricas.aulas.concentracion_por_sede.append({
            "sede_id": sede,
            "sede_nombre": sede_nombre.get(sede, "?"),
            "n_horarios": ocup,
            "porcentaje": 100.0 * ocup / total_ocupacion,
        })

    # -------------------------------------------------------------------------
    # Familia D: estabilidad del LP + traslados intersede
    # -------------------------------------------------------------------------
    # Último LPRun para leer metadata.
    ultimo_run = session.exec(
        select(LPRunDB)
        .where(LPRunDB.plan_cursada_id == plan_id)
        .order_by(LPRunDB.run_at.desc())  # type: ignore[attr-defined]
    ).first()
    if ultimo_run is not None:
        metricas.lp.objetivo = ultimo_run.objective_value
        metricas.lp.tiempo_solve_segundos = ultimo_run.solver_seconds
        metricas.lp.fecha_ultima_corrida = ultimo_run.run_at.strftime(
            "%Y-%m-%d %H:%M"
        )
        metricas.lp.status_ultima_corrida = ultimo_run.status
        metricas.lp.n_ediciones_manuales_respetadas = (
            ultimo_run.n_ediciones_manuales_respetadas
        )

    # Traslados intersede: pares (h1, h2) de la misma comisión, mismo
    # día, con gap < umbral y asignados a sedes distintas.
    def _min(t: time) -> int:
        return t.hour * 60 + t.minute

    horarios_por_com_dia: dict[tuple[str, str], list[HorarioDB]] = {}
    for h in horarios:
        if not h.aula_id:
            continue
        horarios_por_com_dia.setdefault(
            (h.comision_id, h.dia), [],
        ).append(h)

    traslados: dict[str, list[dict]] = {}  # comision_id -> lista de traslados
    for (cid, dia), hs in horarios_por_com_dia.items():
        hs_sorted = sorted(hs, key=lambda h: (h.hora_inicio, h.hora_fin))
        for i in range(len(hs_sorted)):
            for j in range(i + 1, len(hs_sorted)):
                h1, h2 = hs_sorted[i], hs_sorted[j]
                gap = _min(h2.hora_inicio) - _min(h1.hora_fin)
                if gap < 0 or gap >= umbral_traslado_minutos:
                    if gap >= umbral_traslado_minutos:
                        break
                    continue
                s1 = aula_sede_id.get(h1.aula_id) if h1.aula_id else None
                s2 = aula_sede_id.get(h2.aula_id) if h2.aula_id else None
                if s1 and s2 and s1 != s2:
                    traslados.setdefault(cid, []).append({
                        "materia": h1.codigo_materia,
                        "dia": dia,
                        "hora_fin_1": h1.hora_fin.strftime("%H:%M"),
                        "hora_inicio_2": h2.hora_inicio.strftime("%H:%M"),
                        "gap_minutos": gap,
                        "sede_1": sede_nombre.get(s1, "?"),
                        "sede_2": sede_nombre.get(s2, "?"),
                        "aula_1": aula_nombre.get(h1.aula_id, "?"),
                        "aula_2": aula_nombre.get(h2.aula_id, "?"),
                    })
    metricas.lp.n_comisiones_con_traslado_intersede = len(traslados)
    for cid, items in traslados.items():
        comision = next((c for c in comisiones if c.id == cid), None)
        com_lbl = comision.nombre if comision else cid[:8]
        for it in items:
            it["comision"] = com_lbl
            metricas.lp.detalle_traslados.append(it)

    return metricas
