"""Helpers para el LP de asignación de aulas.

Funciones puras (sin DB) que se usan al construir el modelo:

- ``compute_simultaneidad_groups``: a partir de un conjunto de horarios
  semanales, devuelve los grupos maximales de simultaneidad (clases que
  comparten al menos un instante). Cada grupo genera una restricción R4
  por aula en el LP. Algoritmo de barrido de eventos en O(N log N) por día.

- ``compute_compat``: aplica la regla de compatibilidad R3 entre un horario
  y un aula, con `tipo_clase` fijado en el horario.

- ``diagnose_infeasibility``: detecta causas estructurales de
  infactibilidad antes de correr el solver, para reportarlas al usuario
  con mensajes accionables.

Ver `project/1. Diseño/asignacion-aulas-LP.md` § 3.5 R3 y R4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time


# =============================================================================
# Datos mínimos requeridos para el cálculo
# =============================================================================

@dataclass(frozen=True)
class HorarioSlot:
    """Vista mínima de un HorarioDB para los cálculos del LP.

    Se mantiene como dataclass plano (no SQLModel) para que los helpers
    sean testeables sin DB.
    """
    id: str
    dia: str
    hora_inicio: time
    hora_fin: time
    materia_codigo: str
    tipo_clase: str | None  # "teorica" | "laboratorio" | None


@dataclass(frozen=True)
class AulaSlot:
    """Vista mínima de un AulaDB para los cálculos del LP."""
    id: str
    tipo: str  # "teorica" | "laboratorio" | "anfiteatro"
    capacidad: int


# =============================================================================
# Grupos de simultaneidad (R4)
# =============================================================================

def compute_simultaneidad_groups(
    horarios: list[HorarioSlot],
) -> list[set[str]]:
    """Calcula los grupos maximales de horarios que se solapan en el tiempo.

    Para cada día de la semana, hace un barrido de eventos (hora_inicio /
    hora_fin) y emite el conjunto de horarios activos cada vez que el set
    de activos cambia y no es subconjunto de un grupo previamente emitido.

    Cada grupo retornado es un ``set[str]`` de IDs de horarios. Dos grupos
    distintos no son comparables por inclusión (son maximales).

    Implementa el algoritmo descripto en R4 del documento de diseño § 3.5.

    Args:
        horarios: lista de HorarioSlot (puede ser de varios días).

    Returns:
        Lista de grupos maximales. Cada grupo tiene >= 2 horarios (los
        grupos triviales de tamaño 1 se filtran porque no aportan
        restricciones útiles para R4).
    """
    grupos: list[set[str]] = []

    # Agrupar por día (los horarios de días distintos no pueden solaparse).
    por_dia: dict[str, list[HorarioSlot]] = {}
    for h in horarios:
        por_dia.setdefault(h.dia, []).append(h)

    for _dia, hs in por_dia.items():
        # Eventos: (instante, tipo_orden, horario_id) donde tipo_orden hace
        # que en el mismo instante los `end` se procesen antes que los `start`.
        # Si una clase termina exactamente cuando otra empieza, NO se solapan,
        # así que la que termina debe salir del set antes de que entre la nueva.
        eventos: list[tuple[time, int, str, int]] = []
        for h in hs:
            eventos.append((h.hora_inicio, 1, h.id, 0))   # tipo 0 = start
            eventos.append((h.hora_fin, 0, h.id, 1))      # tipo 1 = end
        # Ordenamos: instante asc; en mismo instante, end (1) antes que
        # start (0). Como invertimos el orden con (1 - tipo) → 0 = end
        # primero, 1 = start después.
        eventos.sort(key=lambda e: (e[0], e[1]))

        activas: set[str] = set()
        for _instante, _orden_tag, hid, tipo in eventos:
            if tipo == 1:  # end
                activas.discard(hid)
            else:  # start
                activas.add(hid)
                # Después de cada start, las activas forman un grupo de
                # simultaneidad candidato. Lo agregamos sólo si es maximal
                # (no subconjunto de uno previo) y de tamaño >= 2.
                if len(activas) >= 2:
                    _add_if_maximal(grupos, set(activas))

    return grupos


def _add_if_maximal(grupos: list[set[str]], nuevo: set[str]) -> None:
    """Agrega `nuevo` a `grupos` si no es subconjunto de ninguno previo,
    y elimina previos que sean subconjuntos de `nuevo`."""
    if not nuevo:
        return
    # ¿Es subset de uno existente? Si sí, no agregar.
    for g in grupos:
        if nuevo <= g:
            return
    # Eliminar subsets previos que estén contenidos en `nuevo`.
    grupos[:] = [g for g in grupos if not g < nuevo]
    # Agregar el nuevo.
    grupos.append(nuevo)


# =============================================================================
# Compatibilidad (R3)
# =============================================================================

def compute_compat(
    horario: HorarioSlot,
    aula: AulaSlot,
    materia_lab_aulas: set[str],
) -> bool:
    """Devuelve True si el horario puede dictarse en el aula.

    Aplica R3 del documento de diseño:

    - Si ``horario.tipo_clase == "teorica"``: el aula debe ser
      ``tipo ∈ {teorica, anfiteatro}``.
    - Si ``horario.tipo_clase == "laboratorio"``: el aula debe estar en
      ``materia_lab_aulas`` (lista de aulas compatibles para la materia,
      derivada de MateriaLaboratorioDB).
    - Si ``horario.tipo_clase`` es ``None``: cualquier aula es compatible
      en principio (la compatibilidad se decide vía la variable t[h] en
      el LP, junto con R6).

    Args:
        horario: el horario semanal.
        aula: el aula candidata.
        materia_lab_aulas: set de IDs de aulas compatibles para la materia
            del horario (vía MateriaLaboratorioDB).

    Returns:
        True si el aula puede recibir al horario, False si no.
    """
    if horario.tipo_clase == "teorica":
        return aula.tipo in ("teorica", "anfiteatro")
    if horario.tipo_clase == "laboratorio":
        return aula.id in materia_lab_aulas
    # tipo_clase = None → cualquier aula compatible en principio. La
    # consistencia con t[h] se fuerza vía R6 en el LP.
    return True


# =============================================================================
# Diagnóstico de infactibilidad
# =============================================================================

@dataclass
class InfeasibilityDiagnosis:
    """Detalle estructural de por qué un LP es (o podría ser) infactible.

    Se computa sobre los inputs antes de correr el solver. Las causas que
    detecta son las únicas dos que pueden hacer el problema infactible
    en este modelo (R1 + R3 + R4 — las tolerancias del penalty NO pueden
    hacer infactible al modelo porque R7 es de desigualdad con `over, under
    ≥ 0`).
    """
    # Horarios que no tienen ninguna aula compatible (causa R1 + R3).
    horarios_sin_aula_compatible: list[dict] = field(default_factory=list)
    # Franjas donde hay más clases simultáneas que aulas compatibles
    # (causa R4 + R3). Cada item describe el grupo y la cuenta de aulas
    # compatibles para cada uno de sus horarios.
    franjas_saturadas: list[dict] = field(default_factory=list)
    # Inventario de aulas por tipo (contexto global).
    inventario_aulas: dict = field(default_factory=dict)
    # Comisiones cuya partición teoría/lab es infactible (causa R5).
    particion_problemas: list[dict] = field(default_factory=list)

    def is_infeasible(self) -> bool:
        return bool(
            self.horarios_sin_aula_compatible
            or self.franjas_saturadas
            or self.particion_problemas
        )

    def to_messages(self) -> list[str]:
        """Mensajes legibles, accionables para el usuario."""
        msgs: list[str] = []
        for item in self.horarios_sin_aula_compatible:
            msgs.append(
                f"❌ Horario sin aula compatible: materia "
                f"{item['materia_codigo']}, {item['dia']} "
                f"{item['hora_inicio']}–{item['hora_fin']} "
                f"(tipo={item['tipo_clase']}). "
                f"Razón: {item['razon']}"
            )
        for item in self.franjas_saturadas:
            msgs.append(
                f"❌ Franja saturada {item['dia']} "
                f"{item['solapan_inicio']}–{item['solapan_fin']} "
                f"(intersección de {item['n_clases']} horarios): "
                f"{item['n_clases']} clases simultáneas pero sólo "
                f"{item['n_aulas_compatibles']} aulas compatibles. "
                f"Materias: {', '.join(item['materias'])}."
            )
        return msgs


def diagnose_infeasibility(
    horarios: list[HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]],
    sim_groups: list[set[str]],
) -> InfeasibilityDiagnosis:
    """Detecta causas estructurales de infactibilidad antes del solve.

    Args:
        horarios: lista de horarios del plan.
        aulas: lista completa de aulas.
        materia_lab_map: para cada materia, el set de IDs de aulas
            compatibles para laboratorio.
        sim_groups: grupos de simultaneidad maximales.

    Returns:
        InfeasibilityDiagnosis con las causas detectadas (si las hay).
    """
    diag = InfeasibilityDiagnosis()
    horarios_map = {h.id: h for h in horarios}

    # Inventario global de aulas (contexto para el usuario).
    inv: dict[str, int] = {}
    for a in aulas:
        inv[a.tipo] = inv.get(a.tipo, 0) + 1
    diag.inventario_aulas = {
        "total": len(aulas),
        "por_tipo": inv,
    }

    # 1. Horarios sin ninguna aula compatible (R1 + R3 estructural).
    for h in horarios:
        lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
        compat_count = sum(
            1 for a in aulas if compute_compat(h, a, lab_aulas_m)
        )
        if compat_count == 0:
            if h.tipo_clase == "laboratorio":
                razon = (
                    f"sin laboratorios en MateriaLaboratorioDB para "
                    f"{h.materia_codigo}"
                )
            elif h.tipo_clase == "teorica":
                razon = "sin aulas teóricas/anfiteatros disponibles"
            else:
                razon = "sin ninguna aula registrada"
            diag.horarios_sin_aula_compatible.append({
                "horario_id": h.id,
                "materia_codigo": h.materia_codigo,
                "dia": h.dia,
                "hora_inicio": h.hora_inicio.strftime("%H:%M"),
                "hora_fin": h.hora_fin.strftime("%H:%M"),
                "tipo_clase": h.tipo_clase or "sin determinar",
                "razon": razon,
            })

    # 2. Franjas saturadas: para cada grupo de simultaneidad, contar
    #    cuántas aulas pueden recibir simultáneamente a las clases del
    #    grupo. Como la pregunta exacta (matching bipartito) requeriría
    #    flujo, usamos una cota inferior conservadora: para cada horario
    #    del grupo, su pool individual de aulas. Si la unión de pools es
    #    menor que el tamaño del grupo, el problema es infactible.
    for grupo in sim_groups:
        hs_grupo = [horarios_map[hid] for hid in grupo if hid in horarios_map]
        if len(hs_grupo) < 2:
            continue
        # Aulas compatibles con AL MENOS UN horario del grupo.
        union_aulas: set[str] = set()
        for h in hs_grupo:
            lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
            for a in aulas:
                if compute_compat(h, a, lab_aulas_m):
                    union_aulas.add(a.id)
        if len(union_aulas) < len(hs_grupo):
            # Pigeonhole: imposible asignar una aula distinta a cada uno.
            # La intersección (max start, min end) es la franja donde
            # las N clases coinciden simultáneamente — más informativa
            # para el usuario que la unión.
            solapan_inicio = max(h.hora_inicio for h in hs_grupo)
            solapan_fin = min(h.hora_fin for h in hs_grupo)
            # Unión sólo para contexto adicional.
            ventana_inicio = min(h.hora_inicio for h in hs_grupo)
            ventana_fin = max(h.hora_fin for h in hs_grupo)
            # Desglose por tipo de aula requerida.
            n_teorica = sum(1 for h in hs_grupo if h.tipo_clase == "teorica")
            n_lab = sum(1 for h in hs_grupo if h.tipo_clase == "laboratorio")
            n_sin_det = sum(1 for h in hs_grupo if h.tipo_clase is None)
            diag.franjas_saturadas.append({
                "dia": hs_grupo[0].dia,
                "solapan_inicio": solapan_inicio.strftime("%H:%M"),
                "solapan_fin": solapan_fin.strftime("%H:%M"),
                "ventana_inicio": ventana_inicio.strftime("%H:%M"),
                "ventana_fin": ventana_fin.strftime("%H:%M"),
                "n_clases": len(hs_grupo),
                "n_teorica": n_teorica,
                "n_laboratorio": n_lab,
                "n_sin_determinar": n_sin_det,
                "n_aulas_compatibles": len(union_aulas),
                "n_aulas_total": len(aulas),
                "materias": sorted({h.materia_codigo for h in hs_grupo}),
                "horario_ids": sorted([h.id for h in hs_grupo]),
            })

    return diag


# =============================================================================
# Heatmap día × franja (vista de carga del cronograma)
# =============================================================================

def compute_heatmap_carga(
    horarios: list[HorarioSlot],
    *,
    granularidad_minutos: int = 30,
    hora_inicio: int = 7,
    hora_fin: int = 23,
) -> dict:
    """Cuenta cuántas clases están activas en cada slot (día × franja).

    Devuelve un dict con:

    - ``slots``: lista de strings "HH:MM-HH:MM" para las filas (franjas).
    - ``dias``: lista de días para las columnas.
    - ``total``: matriz [slot][dia] -> int (clases activas en ese slot,
      cualquier tipo).
    - ``teorica``: matriz [slot][dia] -> int (sólo tipo_clase="teorica").
    - ``laboratorio``: matriz [slot][dia] -> int (tipo_clase="laboratorio").
    - ``sin_determinar``: matriz [slot][dia] -> int (tipo_clase=None).

    Una clase se considera "activa" en un slot si su intervalo
    [hora_inicio, hora_fin) intersecta el slot. Las clases virtuales no
    deberían estar en ``horarios`` (se filtran antes en build_inputs).
    """
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

    # Generar slots como pares (start_minutos, end_minutos).
    start = hora_inicio * 60
    end = hora_fin * 60
    slot_bounds: list[tuple[int, int]] = []
    s = start
    while s + granularidad_minutos <= end:
        slot_bounds.append((s, s + granularidad_minutos))
        s += granularidad_minutos
    slots_label = [
        f"{a // 60:02d}:{a % 60:02d}-{b // 60:02d}:{b % 60:02d}"
        for a, b in slot_bounds
    ]

    def _zeros() -> list[list[int]]:
        return [[0] * len(DIAS) for _ in slot_bounds]

    total = _zeros()
    teorica = _zeros()
    lab = _zeros()
    sin_det = _zeros()

    dia_idx = {d: i for i, d in enumerate(DIAS)}

    for h in horarios:
        di = dia_idx.get(h.dia)
        if di is None:
            continue
        h_start = h.hora_inicio.hour * 60 + h.hora_inicio.minute
        h_end = h.hora_fin.hour * 60 + h.hora_fin.minute
        for si, (a, b) in enumerate(slot_bounds):
            if h_start < b and h_end > a:  # intersección no vacía
                total[si][di] += 1
                if h.tipo_clase == "teorica":
                    teorica[si][di] += 1
                elif h.tipo_clase == "laboratorio":
                    lab[si][di] += 1
                else:
                    sin_det[si][di] += 1

    return {
        "slots": slots_label,
        "dias": DIAS,
        "total": total,
        "teorica": teorica,
        "laboratorio": lab,
        "sin_determinar": sin_det,
    }


# =============================================================================
# Pre-validación de partición teoría/lab por comisión (Fase 5)
# =============================================================================

def _subset_sum_factible(
    duraciones: list[float], objetivo: float, *, eps: float = 1e-3,
) -> bool:
    """Existe un subconjunto de ``duraciones`` que sume exactamente
    ``objetivo`` (con tolerancia ``eps``). Trabaja en escala entera con
    cuartos de hora para evitar problemas de coma flotante."""
    if abs(objetivo) < eps:
        return True
    # Convertir a unidades de 0.25h (15 min) para hacer subset-sum entero.
    UNIT = 0.25
    target = round(objetivo / UNIT)
    items = [round(d / UNIT) for d in duraciones if d > eps]
    if target < 0:
        return False
    if sum(items) < target:
        return False
    # DP estándar de subset-sum.
    reachable = {0}
    for it in items:
        reachable = reachable | {r + it for r in reachable if r + it <= target}
        if target in reachable:
            return True
    return target in reachable


# =============================================================================
# Edición manual de aula sobre ClaseDB (Fase 7)
# =============================================================================
# Estos helpers operan a nivel de servicio (necesitan Session). Los dejo
# acá porque son auxiliares específicos del flujo del LP de aulas y no
# encajan bien en otros services pre-existentes.

@dataclass
class ValidationResult:
    """Resultado de pre-validar una edición manual de aula."""
    ok: bool
    errores: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def validar_particion_factible(
    horarios_por_comision: dict[str, list[tuple[str, float, str | None]]],
    hteo: dict[str, float],
    hlab: dict[str, float],
    materia_de_comision: dict[str, str],
) -> list[dict]:
    """Verifica que cada comisión admita una partición teoría/lab válida.

    Para cada comisión ``k`` con materia ``m``, los horarios del plan
    deben poder dividirse en dos subconjuntos cuyas duraciones sumen
    exactamente ``hteo[m]`` y ``hlab[m]`` respectivamente. Los horarios
    con ``tipo_clase`` fijado restringen la partición; los `None` son
    libres de ir a cualquiera.

    Args:
        horarios_por_comision: comision_id -> lista de
            (horario_id, duracion_horas, tipo_clase fijado o None).
        hteo: codigo_materia -> horas de teoría declaradas.
        hlab: codigo_materia -> horas de laboratorio declaradas.
        materia_de_comision: comision_id -> codigo_materia.

    Returns:
        Lista de problemas detectados; vacía si todas las comisiones son
        factibles. Cada item: {comision_id, materia, hteo, hlab,
        suma_total, suma_lab_fijado, suma_teorica_fijada, razon}.
    """
    problemas: list[dict] = []
    for cid, lista in horarios_por_comision.items():
        m = materia_de_comision.get(cid)
        if m is None:
            continue
        ht = hteo.get(m, 0.0)
        hl = hlab.get(m, 0.0)
        suma_total = sum(d for _, d, _ in lista)
        suma_teo_fija = sum(d for _, d, t in lista if t == "teorica")
        suma_lab_fija = sum(d for _, d, t in lista if t == "laboratorio")
        suma_libre = suma_total - suma_teo_fija - suma_lab_fija
        # Sanity 1: la suma total debe igualar hteo + hlab (con tolerancia).
        eps = 1e-3
        if abs(suma_total - (ht + hl)) > eps:
            problemas.append({
                "comision_id": cid, "materia": m, "hteo": ht, "hlab": hl,
                "suma_total": suma_total,
                "suma_lab_fijado": suma_lab_fija,
                "suma_teorica_fijada": suma_teo_fija,
                "razon": (
                    f"La suma de duraciones de los horarios ({suma_total:.2f}h) "
                    f"no coincide con hteo+hlab declarado ({ht + hl:.2f}h)."
                ),
            })
            continue
        # Sanity 2: lo fijado como lab no puede exceder hlab; idem teoría.
        if suma_lab_fija - hl > eps:
            problemas.append({
                "comision_id": cid, "materia": m, "hteo": ht, "hlab": hl,
                "suma_total": suma_total,
                "suma_lab_fijado": suma_lab_fija,
                "suma_teorica_fijada": suma_teo_fija,
                "razon": (
                    f"Hay {suma_lab_fija:.2f}h fijadas como laboratorio "
                    f"pero la materia declara hlab={hl:.2f}h."
                ),
            })
            continue
        if suma_teo_fija - ht > eps:
            problemas.append({
                "comision_id": cid, "materia": m, "hteo": ht, "hlab": hl,
                "suma_total": suma_total,
                "suma_lab_fijado": suma_lab_fija,
                "suma_teorica_fijada": suma_teo_fija,
                "razon": (
                    f"Hay {suma_teo_fija:.2f}h fijadas como teoría "
                    f"pero la materia declara hteo={ht:.2f}h."
                ),
            })
            continue
        # Sanity 3: subset-sum sobre los horarios libres para ver si
        # existe una asignación de los `None` que complete las horas
        # restantes. La cantidad de horas libres a asignar a lab es
        # hl - suma_lab_fija; el resto va a teoría.
        lab_restante = hl - suma_lab_fija
        libres_durs = [d for _, d, t in lista if t is None]
        if not _subset_sum_factible(libres_durs, lab_restante):
            problemas.append({
                "comision_id": cid, "materia": m, "hteo": ht, "hlab": hl,
                "suma_total": suma_total,
                "suma_lab_fijado": suma_lab_fija,
                "suma_teorica_fijada": suma_teo_fija,
                "razon": (
                    f"No existe combinación de los horarios sin tipo "
                    f"determinado que sume {lab_restante:.2f}h de "
                    f"laboratorio (hlab={hl:.2f}h, ya fijadas "
                    f"{suma_lab_fija:.2f}h)."
                ),
            })
    return problemas
