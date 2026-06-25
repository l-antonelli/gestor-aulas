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

    Se computa sobre los inputs antes de correr el solver. Las causas
    que detecta cubren las situaciones más comunes en que el modelo es
    infactible aunque el solver no dé pistas:

    1. **Horarios sin aula compatible** (R1 + R3): un horario que no
       tiene NI UNA sola aula que pueda recibirlo. Causa típica: lab
       sin entradas en `MateriaLaboratorioDB` para esa materia.
    2. **Franjas saturadas** (R4 + R3, cota pigeonhole sobre la unión):
       grupo de simultaneidad donde la unión de aulas compatibles tiene
       menos elementos que el grupo. Necesaria pero no suficiente.
    3. **Saturación por tipo dentro de una franja** (R3 + R4 + R6):
       refinamiento de (2). Mira por separado teóricas vs laboratorios:
       si las clases del grupo que NECESITAN aula teórica son más que
       el inventario de teóricas/anfiteatros, infactible. Para labs,
       chequea por materia (cada materia tiene su pool propio).
       Las clases con `tipo_clase=None` se manejan optimistamente
       (sólo cuentan como teóricas si NO admiten ir a lab; sólo cuentan
       como lab si NO admiten ir a teórica) para evitar falsos
       positivos.
    4. **Hall violators** (R3 + R4 vía matching bipartito): test
       suficiente y necesario sobre cada grupo. Para cada subconjunto
       S del grupo, verifica `|N(S)| >= |S|` donde N(S) es la unión
       de aulas compatibles de S. Si falla, identifica el subconjunto
       más chico donde falla (testigo concreto). Cubre casos que las
       cotas (2) y (3) NO detectan, ej. `{h1,h2,h3}` con aulas
       compatibles `{A→{a,b}, B→{a}, C→{a}}`: |union|=2 < 3 falla
       pigeonhole, pero `|N({B,C})|=1 < 2` también falla Hall y es
       más informativo. Para grupos chicos (≤8) por enumeración de
       subconjuntos; para más grandes, matching bipartito clásico.
    5. **Partición teoría/lab infactible** (R5): comisión cuya suma
       de horas no admite una bipartición que cumpla `hteo + hlab`.

    Las tolerancias del penalty (λ_over, λ_under, tol_*) NO pueden
    hacer infactible al modelo porque R7 es de desigualdad con
    `over, under ≥ 0`.
    """
    # (1) Horarios sin ninguna aula compatible.
    horarios_sin_aula_compatible: list[dict] = field(default_factory=list)
    # (2) Cota pigeonhole sobre la unión.
    franjas_saturadas: list[dict] = field(default_factory=list)
    # (3) Saturación por tipo (refina pigeonhole).
    saturacion_por_tipo: list[dict] = field(default_factory=list)
    # (4) Hall violators.
    hall_violators: list[dict] = field(default_factory=list)
    # Inventario de aulas por tipo (contexto global).
    inventario_aulas: dict = field(default_factory=dict)
    # (5) Comisiones cuya partición teoría/lab es infactible.
    particion_problemas: list[dict] = field(default_factory=list)

    def is_infeasible(self) -> bool:
        return bool(
            self.horarios_sin_aula_compatible
            or self.franjas_saturadas
            or self.saturacion_por_tipo
            or self.hall_violators
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
        for item in self.saturacion_por_tipo:
            msgs.append(
                f"❌ Saturación de aulas {item['tipo']} en "
                f"{item['dia']} {item['solapan_inicio']}–"
                f"{item['solapan_fin']}: {item['n_necesarias']} "
                f"clases requieren aula {item['tipo']} pero hay "
                f"{item['n_disponibles']} disponibles. "
                f"Materias: {', '.join(item['materias'])}."
            )
        for item in self.hall_violators:
            msgs.append(
                f"❌ Hall: {item['n_horarios']} horarios sólo pueden "
                f"ir a {item['n_aulas']} aula(s) en común "
                f"(día {item['dia']}). "
                f"Horarios: {', '.join(item['materias'])}; "
                f"Aulas: {', '.join(item['aulas'])}."
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
    compat_override: dict[tuple[str, str], bool] | None = None,
) -> InfeasibilityDiagnosis:
    """Detecta causas estructurales de infactibilidad antes del solve.

    Args:
        horarios: lista de horarios del plan.
        aulas: lista completa de aulas.
        materia_lab_map: para cada materia, el set de IDs de aulas
            compatibles para laboratorio.
        sim_groups: grupos de simultaneidad maximales.
        compat_override: si se pasa, este dict (computado por
            ``build_inputs`` y que YA incluye filtros adicionales como
            R10 — restricción de sede) se usa en lugar de
            ``compute_compat``. Permite que el diagnóstico reporte
            causas reales del problema posterior al filtrado.

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

    def _es_compat(h: HorarioSlot, a: AulaSlot) -> bool:
        if compat_override is not None:
            return bool(compat_override.get((h.id, a.id), False))
        return compute_compat(h, a, materia_lab_map.get(h.materia_codigo, set()))

    # 1. Horarios sin ninguna aula compatible (R1 + R3 estructural; +R10
    #    si compat_override viene).
    for h in horarios:
        lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
        compat_count = sum(1 for a in aulas if _es_compat(h, a))
        if compat_count == 0:
            # ¿Sería compatible si no fuera por R10? Si sin override
            # también queda en 0, es la causa "clásica" R1+R3.
            compat_sin_r10 = sum(
                1 for a in aulas if compute_compat(h, a, lab_aulas_m)
            )
            es_r10 = compat_override is not None and compat_sin_r10 > 0

            if es_r10:
                razon = (
                    "ningún aula admisible por R10 (restricción de "
                    "sede por carrera/materia). Revisá las sedes "
                    "habilitadas para la carrera o la sede default "
                    f"para materias comunes ({h.materia_codigo})."
                )
            elif h.tipo_clase == "laboratorio":
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

    # 3. Saturación por tipo dentro de cada franja (refina pigeonhole).
    diag.saturacion_por_tipo = _diagnose_saturacion_por_tipo(
        sim_groups, horarios_map, aulas, materia_lab_map,
    )

    # 4. Hall violators: matching bipartito por grupo. Más fuerte que
    #    pigeonhole (es necesario y suficiente para que haya solución).
    diag.hall_violators = _diagnose_hall(
        sim_groups, horarios_map, aulas, materia_lab_map,
    )

    return diag


# =============================================================================
# Saturación por tipo (cota refinada de pigeonhole)
# =============================================================================

def _diagnose_saturacion_por_tipo(
    sim_groups: list[set[str]],
    horarios_map: dict[str, HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]],
) -> list[dict]:
    """Para cada grupo de simultaneidad, verifica saturación POR TIPO.

    Refina la cota global de pigeonhole (que mira la unión total) con
    pools separados por tipo:

    - **Teóricas**: clases que ESTRICTAMENTE requieren aula teórica
      (tipo_clase="teorica") más aquellas con `tipo_clase=None` que
      no admiten ir a lab (sin lab compatible para su materia). Estas
      últimas son las que el LP forzosamente mandará a teórica via R6,
      por lo que cuentan contra la pool teórica.
    - **Laboratorios**: por materia. Cada materia tiene su pool propio
      `materia_lab_map[m]`. Las clases con `tipo_clase=None` que no
      admiten ir a teórica (sin aulas teóricas/anfiteatros del sistema,
      caso raro) cuentan contra el pool de su materia.

    El manejo OPTIMISTA de las `None` evita falsos positivos: una
    clase con `tipo_clase=None` y materia con lab disponible no se
    cuenta contra teórica porque el LP puede mandarla a lab via R5.

    Args:
        sim_groups: grupos maximales de simultaneidad.
        horarios_map: horario_id -> HorarioSlot.
        aulas: inventario completo de aulas.
        materia_lab_map: por materia, set de aula_id de labs compatibles.

    Returns:
        Lista de items con la saturación detectada. Cada item:
        {tipo, dia, solapan_inicio/fin, ventana_inicio/fin,
         n_necesarias, n_disponibles, materias, horario_ids,
         materia (sólo para tipo=lab)}.
    """
    aulas_teoricas = {a.id for a in aulas if a.tipo in ("teorica", "anfiteatro")}
    n_teoricas = len(aulas_teoricas)

    items: list[dict] = []

    for grupo in sim_groups:
        hs_grupo = [horarios_map[hid] for hid in grupo if hid in horarios_map]
        if len(hs_grupo) < 2:
            continue

        # Clases que necesitan teórica: tipo="teorica" + las None sin lab
        # disponible (R6 las fuerza a teoría).
        n_teorica_forzadas = []
        for h in hs_grupo:
            if h.tipo_clase == "teorica":
                n_teorica_forzadas.append(h)
            elif h.tipo_clase is None:
                lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
                if not lab_aulas_m:
                    # No hay labs compatibles: R6 fuerza t[h]=0 (teórica).
                    n_teorica_forzadas.append(h)

        if len(n_teorica_forzadas) > n_teoricas:
            solapan_inicio = max(h.hora_inicio for h in hs_grupo)
            solapan_fin = min(h.hora_fin for h in hs_grupo)
            ventana_inicio = min(h.hora_inicio for h in hs_grupo)
            ventana_fin = max(h.hora_fin for h in hs_grupo)
            items.append({
                "tipo": "teórica",
                "dia": hs_grupo[0].dia,
                "solapan_inicio": solapan_inicio.strftime("%H:%M"),
                "solapan_fin": solapan_fin.strftime("%H:%M"),
                "ventana_inicio": ventana_inicio.strftime("%H:%M"),
                "ventana_fin": ventana_fin.strftime("%H:%M"),
                "n_necesarias": len(n_teorica_forzadas),
                "n_disponibles": n_teoricas,
                "materias": sorted({
                    h.materia_codigo for h in n_teorica_forzadas
                }),
                "horario_ids": sorted([h.id for h in n_teorica_forzadas]),
            })

        # Saturación de labs POR MATERIA. Si una materia tiene N clases
        # de lab simultáneas pero su pool tiene < N aulas, falla.
        # Las None sin teóricas disponibles cuentan también contra lab,
        # pero en la práctica si no hay teóricas n_teoricas==0 y eso
        # sería una infeasibility independiente; no enmascaramos.
        por_materia_lab: dict[str, list[HorarioSlot]] = {}
        for h in hs_grupo:
            if h.tipo_clase == "laboratorio":
                por_materia_lab.setdefault(h.materia_codigo, []).append(h)
            elif h.tipo_clase is None and n_teoricas == 0:
                # Forzosamente lab via R6 (no hay aulas teóricas).
                lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
                if lab_aulas_m:
                    por_materia_lab.setdefault(h.materia_codigo, []).append(h)

        for materia, hs_lab in por_materia_lab.items():
            pool = materia_lab_map.get(materia, set())
            if len(hs_lab) > len(pool):
                solapan_inicio = max(h.hora_inicio for h in hs_lab)
                solapan_fin = min(h.hora_fin for h in hs_lab)
                ventana_inicio = min(h.hora_inicio for h in hs_lab)
                ventana_fin = max(h.hora_fin for h in hs_lab)
                items.append({
                    "tipo": "laboratorio",
                    "materia": materia,
                    "dia": hs_lab[0].dia,
                    "solapan_inicio": solapan_inicio.strftime("%H:%M"),
                    "solapan_fin": solapan_fin.strftime("%H:%M"),
                    "ventana_inicio": ventana_inicio.strftime("%H:%M"),
                    "ventana_fin": ventana_fin.strftime("%H:%M"),
                    "n_necesarias": len(hs_lab),
                    "n_disponibles": len(pool),
                    "materias": [materia],
                    "horario_ids": sorted([h.id for h in hs_lab]),
                })

    return items


# =============================================================================
# Hall violators (matching bipartito)
# =============================================================================

# Umbral para enumeración exacta de subconjuntos. Por encima de esto
# usamos matching bipartito clásico (Hopcroft-Karp simplificado, augmenting
# paths con búsqueda DFS). 8 da 256 subconjuntos por grupo, manejable.
_HALL_ENUM_LIMIT = 8


def _diagnose_hall(
    sim_groups: list[set[str]],
    horarios_map: dict[str, HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]],
) -> list[dict]:
    """Para cada grupo, verifica el teorema de Hall.

    Para cada subconjunto S del grupo, debe cumplirse |N(S)| >= |S|,
    donde N(S) es la unión de aulas compatibles de los elementos de S.
    Si NO se cumple, el grupo no admite emparejamiento perfecto y el
    LP es infactible.

    Estrategia:
    - Grupos con |grupo| <= _HALL_ENUM_LIMIT: enumeración exacta de
      subconjuntos. Reportamos el subconjunto Hall-violador más chico
      (testigo más informativo).
    - Grupos más grandes: matching bipartito por augmenting paths. Si
      el matching máximo es < |grupo|, hay infactibilidad. Reportamos
      el lado izquierdo no matcheado como subconjunto violador
      (subóptimo en tamaño pero correcto).

    Items reportados con:
    - dia, n_horarios, materias (lista de códigos)
    - n_aulas, aulas (lista de IDs de aulas en N(S))
    - horario_ids del subconjunto

    Returns:
        Lista de violaciones detectadas. Vacía si todos los grupos
        admiten matching.
    """
    items: list[dict] = []

    for grupo in sim_groups:
        hs_grupo = [horarios_map[hid] for hid in grupo if hid in horarios_map]
        if len(hs_grupo) < 2:
            continue

        # Build adjacency: horario_idx -> set[aula_id]
        adj: list[set[str]] = []
        for h in hs_grupo:
            lab_aulas_m = materia_lab_map.get(h.materia_codigo, set())
            compat_aulas = {
                a.id for a in aulas if compute_compat(h, a, lab_aulas_m)
            }
            adj.append(compat_aulas)

        n = len(hs_grupo)
        if n <= _HALL_ENUM_LIMIT:
            violator = _hall_smallest_violator_enum(adj)
        else:
            violator = _hall_violator_via_matching(adj)

        if violator is None:
            continue

        # `violator` es un set[int] con índices de hs_grupo.
        sub_hs = [hs_grupo[i] for i in violator]
        sub_aulas: set[str] = set()
        for i in violator:
            sub_aulas |= adj[i]
        items.append({
            "dia": hs_grupo[0].dia,
            "n_horarios": len(violator),
            "n_aulas": len(sub_aulas),
            "materias": sorted({h.materia_codigo for h in sub_hs}),
            "aulas": sorted(sub_aulas),
            "horario_ids": sorted([h.id for h in sub_hs]),
        })

    return items


def _hall_smallest_violator_enum(adj: list[set[str]]) -> set[int] | None:
    """Para |grupo| <= _HALL_ENUM_LIMIT: enumera todos los subconjuntos
    y devuelve el más chico que viola Hall.

    Hall: para todo S, |∪{adj[i] : i ∈ S}| >= |S|.
    Devuelve None si todos los subconjuntos cumplen.

    Más chico = más informativo para el usuario. Empezamos enumerando
    por tamaño creciente para encontrar rápido.
    """
    n = len(adj)
    indices = list(range(n))
    # Probar tamaños de 1 a n. Tamaño 1 sólo viola si algún horario
    # no tiene ninguna aula compatible (caso ya cubierto por
    # `horarios_sin_aula_compatible`, lo dejamos pasar para no
    # duplicar mensaje).
    for size in range(2, n + 1):
        for combo in _combinations(indices, size):
            union: set[str] = set()
            for i in combo:
                union |= adj[i]
            if len(union) < size:
                return set(combo)
    return None


def _combinations(items: list[int], r: int):
    """Wrapper de itertools.combinations sin importar al top-level."""
    from itertools import combinations
    return combinations(items, r)


def _hall_violator_via_matching(adj: list[set[str]]) -> set[int] | None:
    """Para grupos grandes: matching bipartito vía DFS augmenting paths.

    Si el matching máximo es M < |adj|, entonces hay (al menos) un
    subconjunto violador. Reportamos los nodos NO emparejados del lado
    izquierdo (horarios) como aproximación: ese conjunto S tiene
    |N(S)| <= |adj| - (M de S) que es < |S| en algún caso (no
    necesariamente el subconjunto Hall-violador más chico, pero
    suficiente para señalar la infactibilidad).

    Implementación clásica O(V·E), más que suficiente para los
    tamaños del problema (grupos típicamente ≤ 20).
    """
    n_left = len(adj)
    # Mapping aula_id -> int (canonical idx).
    aula_ids: list[str] = sorted({a for s in adj for a in s})
    aula_idx = {a: i for i, a in enumerate(aula_ids)}
    adj_idx: list[set[int]] = [
        {aula_idx[a] for a in s} for s in adj
    ]

    match_l: list[int] = [-1] * n_left
    match_r: dict[int, int] = {}

    def dfs(u: int, visited: set[int]) -> bool:
        for v in adj_idx[u]:
            if v in visited:
                continue
            visited.add(v)
            if v not in match_r or dfs(match_r[v], visited):
                match_l[u] = v
                match_r[v] = u
                return True
        return False

    matched = 0
    for u in range(n_left):
        if dfs(u, set()):
            matched += 1

    if matched == n_left:
        return None  # Matching perfecto.
    # Reportar los no matcheados.
    no_match = {u for u in range(n_left) if match_l[u] == -1}
    return no_match if no_match else None


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
# Heatmap demanda vs oferta (cuello de botella por franja)
# =============================================================================

def compute_heatmap_demanda_oferta(
    horarios: list[HorarioSlot],
    aulas: list[AulaSlot],
    compat: dict[tuple[str, str], bool],
    *,
    granularidad_minutos: int = 30,
    hora_inicio: int = 7,
    hora_fin: int = 23,
    horarios_filtrados: list[HorarioSlot] | None = None,
) -> dict:
    """Para cada celda (día × franja) calcula la **peor saturación** entre
    los horarios activos en esa celda y las aulas que admiten cada uno.

    Definiciones:

    - ``demanda(celda, tipo)``: cuántos horarios del tipo (teorica /
      laboratorio_de_materia_m / sin_determinar) están activos en la celda.
    - ``oferta(celda, tipo)``: cuántas aulas del catalogo son admisibles
      (segun ``compat``) para algún horario de ese tipo en la celda.
    - ``ratio = demanda / oferta``. ratio > 1 ⇒ saturación segura
      (más horarios que aulas), ratio = 1 ⇒ frontera, ratio < 1 ⇒ holgura.

    El ``compat`` se asume ya filtrado por R10 (sede), R3 (tipo) y lab
    compatible. Si el caller pasa un compat sin esos filtros, el heatmap
    seguirá funcionando pero con cobertura distinta.

    Args:
        horarios: TODOS los horarios del plan (para detectar conflicto con
            la oferta global).
        aulas: catalogo de aulas.
        compat: ``compat[(h_id, a_id)] = True/False`` ya filtrado.
        horarios_filtrados: si se pasa, sólo estos horarios se cuentan
            como demanda. La oferta sigue mirando todos. Util para
            mostrar "saturacion para los horarios que matchean los filtros
            del panel".

    Devuelve un dict con:

    - ``slots``: ["07:00-07:30", ...].
    - ``dias``: ["Lunes", ...].
    - ``ratio``: matriz [slot][dia] -> float. peor saturacion en la celda
      (max sobre las "categorias" de tipo: teorica, laboratorio_m, sin_det).
    - ``demanda``: matriz [slot][dia] -> int. count del peor caso.
    - ``oferta``: matriz [slot][dia] -> int. aulas disponibles para el peor caso.
    - ``categoria``: matriz [slot][dia] -> str. cual fue el peor caso
      (e.g. "teorica", "laboratorio:MIX", "sin_determinar").
    - ``detalle``: matriz [slot][dia] -> dict con materias_demandantes,
      aulas_disponibles_ids para drill-down.
    """
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]

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

    n_slots = len(slot_bounds)
    n_dias = len(DIAS)
    dia_idx = {d: i for i, d in enumerate(DIAS)}

    def _zeros_f() -> list[list[float]]:
        return [[0.0] * n_dias for _ in range(n_slots)]

    def _zeros_i() -> list[list[int]]:
        return [[0] * n_dias for _ in range(n_slots)]

    def _empty_str() -> list[list[str]]:
        return [[""] * n_dias for _ in range(n_slots)]

    def _empty_dict() -> list[list[dict]]:
        return [[{} for _ in range(n_dias)] for _ in range(n_slots)]

    ratio = _zeros_f()
    demanda = _zeros_i()
    oferta = _zeros_i()
    categoria = _empty_str()
    detalle = _empty_dict()

    # Pre-computo, para cada horario, en qué celdas está activo.
    def _celdas_de_horario(h: HorarioSlot) -> list[tuple[int, int]]:
        di = dia_idx.get(h.dia)
        if di is None:
            return []
        h_start = h.hora_inicio.hour * 60 + h.hora_inicio.minute
        h_end = h.hora_fin.hour * 60 + h.hora_fin.minute
        out = []
        for si, (a, b) in enumerate(slot_bounds):
            if h_start < b and h_end > a:
                out.append((si, di))
        return out

    horarios_demanda = horarios_filtrados if horarios_filtrados is not None else horarios

    # Para cada celda, agrupo horarios por categoria y mido demanda/oferta.
    # Estructura: por (si, di) -> {categoria -> {"horarios": [h_ids],
    # "materias": set[str]}}
    por_celda: dict[tuple[int, int], dict[str, dict]] = {}
    for h in horarios_demanda:
        if h.tipo_clase == "teorica":
            cat = "teorica"
        elif h.tipo_clase == "laboratorio":
            cat = f"laboratorio:{h.materia_codigo}"
        else:
            cat = "sin_determinar"
        for si, di in _celdas_de_horario(h):
            celda = por_celda.setdefault((si, di), {})
            grupo = celda.setdefault(cat, {
                "horario_ids": [],
                "materias": set(),
            })
            grupo["horario_ids"].append(h.id)
            grupo["materias"].add(h.materia_codigo)

    # Para la oferta: por categoria, qué aulas son admisibles.
    # - "teorica": aulas tipo {teorica, anfiteatro} — pero la oferta
    #   real es la cardinalidad del set de aulas a las que algún
    #   horario de la celda se podría asignar (segun compat). Tomamos
    #   la union de aulas admisibles para horarios de esa categoria
    #   en la celda.
    # - "laboratorio:m": aulas en materia_lab_map[m] que ademas pasan
    #   el filtro de compat con esos horarios.
    # - "sin_determinar": union de aulas admisibles para los horarios
    #   sin tipo (R6 deja la decision al LP, pero acotamos por compat).

    aula_ids = [a.id for a in aulas]

    def _oferta_para_grupo(horario_ids: list[str]) -> set[str]:
        """Aulas que admiten al menos uno de los horarios del grupo.

        Para una cota de saturacion, lo correcto seria calcular un
        matching: pero la cota |union| >= |grupo| es la pigeonhole
        clasica y alcanza para detectar 'mas demanda que oferta total'.
        """
        out: set[str] = set()
        for h_id in horario_ids:
            for a_id in aula_ids:
                if compat.get((h_id, a_id), False):
                    out.add(a_id)
        return out

    for (si, di), grupos in por_celda.items():
        peor_ratio = 0.0
        peor_demanda = 0
        peor_oferta = 0
        peor_cat = ""
        peor_materias: set[str] = set()
        peor_aulas: set[str] = set()
        for cat, datos in grupos.items():
            d = len(datos["horario_ids"])
            o = len(_oferta_para_grupo(datos["horario_ids"]))
            r = (d / o) if o > 0 else (float("inf") if d > 0 else 0.0)
            if r > peor_ratio or (
                r == peor_ratio and d > peor_demanda
            ):
                peor_ratio = r
                peor_demanda = d
                peor_oferta = o
                peor_cat = cat
                peor_materias = datos["materias"]
                peor_aulas = _oferta_para_grupo(datos["horario_ids"])
        ratio[si][di] = peor_ratio if peor_ratio != float("inf") else 999.0
        demanda[si][di] = peor_demanda
        oferta[si][di] = peor_oferta
        categoria[si][di] = peor_cat
        detalle[si][di] = {
            "materias": sorted(peor_materias),
            "aulas_disponibles_ids": sorted(peor_aulas),
            "horarios_simultaneos": peor_demanda,
            "categoria": peor_cat,
        }

    return {
        "slots": slots_label,
        "dias": DIAS,
        "ratio": ratio,
        "demanda": demanda,
        "oferta": oferta,
        "categoria": categoria,
        "detalle": detalle,
    }


# =============================================================================
# Impacto de R10 (restriccion de sede por carrera)
# =============================================================================

def compute_heatmap_por_sede(
    horarios: list[HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]],
    sedes_admisibles_por_materia: dict[str, set[str] | None],
    aula_sede_id: dict[str, str],
    sede_nombre: dict[str, str],
    *,
    granularidad_minutos: int = 30,
    hora_inicio: int = 7,
    hora_fin: int = 23,
) -> dict:
    """Mapa de saturación particionado por SEDE.

    Para cada combinación (sede × día × franja × tipo), computa:

    - **demanda**: cuántos horarios activos en esa franja **necesitan**
      una aula de esa sede. Un horario "necesita" una sede si esa sede
      es admisible para él (según R10 o por ser lab compatible).
    - **oferta**: cuántas aulas de la sede son del tipo necesario y
      admiten al menos uno de esos horarios.
    - **ratio**: demanda / oferta. Verde ≤0.8, amarillo 0.8–1, rojo >1.

    Las categorías son: ``teorica``, ``laboratorio:<materia>``, y
    ``sin_determinar``. Para evitar saturar la pantalla, el caller
    decide qué categorías mostrar (filtro UI).

    Args:
        horarios: horarios del plan (no virtuales).
        aulas: catálogo de aulas.
        materia_lab_map: aulas compatibles para lab por materia.
        sedes_admisibles_por_materia: por cada materia, set de
            sede_ids admisibles según R10. Si la materia no está en el
            dict o el valor es None, se asume que admite todas las sedes.
        aula_sede_id: mapping aula_id → sede_id.
        sede_nombre: mapping sede_id → nombre legible.
        granularidad_minutos, hora_inicio, hora_fin: idem otros heatmaps.

    Returns:
        ``{
            "sedes": [{"sede_id", "sede_nombre", "n_aulas_teoricas",
                       "n_aulas_laboratorio", "tiene_demanda"}, ...],
            "dias": [...],
            "slots": [...],
            "data": {
                sede_id: {
                    "teorica":    {"ratio": [[float]], "demanda": [[int]],
                                   "oferta": [[int]]},
                    "laboratorio": {... idem ...},
                    "peor":        {... peor caso entre las categorías ...},
                }, ...
            }
        }``
    """
    DIAS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"]
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
    n_slots = len(slot_bounds)
    n_dias = len(DIAS)
    dia_idx = {d: i for i, d in enumerate(DIAS)}

    # Aulas por sede, separadas por tipo.
    aulas_por_sede: dict[str, dict[str, list[AulaSlot]]] = {}
    for a in aulas:
        sede = aula_sede_id.get(a.id)
        if sede is None:
            continue
        bucket = aulas_por_sede.setdefault(
            sede, {"teorica": [], "laboratorio": []},
        )
        if a.tipo in ("teorica", "anfiteatro"):
            bucket["teorica"].append(a)
        elif a.tipo == "laboratorio":
            bucket["laboratorio"].append(a)

    # Pre-computo: en qué celdas está activo cada horario.
    def _celdas_de_horario(h: HorarioSlot) -> list[tuple[int, int]]:
        di = dia_idx.get(h.dia)
        if di is None:
            return []
        h_s = h.hora_inicio.hour * 60 + h.hora_inicio.minute
        h_e = h.hora_fin.hour * 60 + h.hora_fin.minute
        out_c = []
        for si, (a, b) in enumerate(slot_bounds):
            if h_s < b and h_e > a:
                out_c.append((si, di))
        return out_c

    def _zeros_f() -> list[list[float]]:
        return [[0.0] * n_dias for _ in range(n_slots)]

    def _zeros_i() -> list[list[int]]:
        return [[0] * n_dias for _ in range(n_slots)]

    def _empty_categoria() -> dict:
        return {
            "ratio": _zeros_f(),
            "demanda": _zeros_i(),
            "oferta": _zeros_i(),
        }

    # Inicializo data por sede.
    data: dict[str, dict[str, dict]] = {}
    sedes_con_aulas = list(aulas_por_sede.keys())
    for sede in sedes_con_aulas:
        data[sede] = {
            "teorica": _empty_categoria(),
            "laboratorio": _empty_categoria(),
            "peor": _empty_categoria(),
        }

    # Para cada celda × sede, agrupar horarios por categoría.
    # Estructura: por_celda_sede[(si,di,sede)][cat] = {"horarios":[ids],
    # "materias":set}
    por_celda_sede: dict[tuple[int, int, str], dict[str, dict]] = {}
    for h in horarios:
        admis = sedes_admisibles_por_materia.get(h.materia_codigo)
        # Lab compatible: su sede siempre cuenta como admisible.
        labs = materia_lab_map.get(h.materia_codigo, set())
        for si, di in _celdas_de_horario(h):
            for sede in sedes_con_aulas:
                # ¿Esta sede es admisible para este horario?
                tiene_lab_en_sede = any(
                    aula_sede_id.get(a_id) == sede for a_id in labs
                )
                if admis is None:
                    sede_admisible = True
                else:
                    sede_admisible = (sede in admis) or tiene_lab_en_sede
                if not sede_admisible:
                    continue
                # Categoría según tipo del horario.
                if h.tipo_clase == "teorica":
                    cat = "teorica"
                elif h.tipo_clase == "laboratorio":
                    # Sólo cuenta si la sede tiene labs compatibles
                    # con esta materia. Si no, no aporta a esta sede.
                    if not tiene_lab_en_sede:
                        continue
                    cat = "laboratorio"
                else:
                    # tipo_clase=None: lo contamos como teorica
                    # (decisión del LP es lo más probable). Si la
                    # materia tiene lab y sede tiene lab compatible,
                    # también podría ir a lab — caso optimista
                    # ignorado por simplicidad.
                    cat = "teorica"
                key = (si, di, sede)
                grupo = por_celda_sede.setdefault(key, {}).setdefault(
                    cat, {"horarios": [], "materias": set()},
                )
                grupo["horarios"].append(h.id)
                grupo["materias"].add(h.materia_codigo)

    # Computar oferta por (sede, categoría): es la cantidad de aulas
    # del tipo. Para lab, idealmente se mide por materia (cada materia
    # tiene su pool propio), pero acá agregamos todas las labs de la
    # sede. Como cota la usamos como referencia.
    oferta_estatica: dict[tuple[str, str], int] = {}
    for sede in sedes_con_aulas:
        oferta_estatica[(sede, "teorica")] = len(
            aulas_por_sede[sede]["teorica"]
        )
        oferta_estatica[(sede, "laboratorio")] = len(
            aulas_por_sede[sede]["laboratorio"]
        )

    # Llenar data.
    for (si, di, sede), grupos in por_celda_sede.items():
        peor_ratio_cell = 0.0
        peor_dem_cell = 0
        peor_of_cell = 0
        for cat, datos in grupos.items():
            d = len(datos["horarios"])
            o = oferta_estatica.get((sede, cat), 0)
            r = (d / o) if o > 0 else (float("inf") if d > 0 else 0.0)
            r_safe = r if r != float("inf") else 999.0
            data[sede][cat]["demanda"][si][di] = d
            data[sede][cat]["oferta"][si][di] = o
            data[sede][cat]["ratio"][si][di] = r_safe
            if r_safe > peor_ratio_cell or (
                r_safe == peor_ratio_cell and d > peor_dem_cell
            ):
                peor_ratio_cell = r_safe
                peor_dem_cell = d
                peor_of_cell = o
        data[sede]["peor"]["demanda"][si][di] = peor_dem_cell
        data[sede]["peor"]["oferta"][si][di] = peor_of_cell
        data[sede]["peor"]["ratio"][si][di] = peor_ratio_cell

    # Metadata de sedes.
    sedes_meta = []
    for sede in sedes_con_aulas:
        nombre = sede_nombre.get(sede, sede)
        n_teo = len(aulas_por_sede[sede]["teorica"])
        n_lab = len(aulas_por_sede[sede]["laboratorio"])
        # ¿Hay alguna celda con demanda > 0 para esta sede?
        tiene_demanda = any(
            data[sede]["peor"]["demanda"][si][di] > 0
            for si in range(n_slots)
            for di in range(n_dias)
        )
        sedes_meta.append({
            "sede_id": sede,
            "sede_nombre": nombre,
            "n_aulas_teoricas": n_teo,
            "n_aulas_laboratorio": n_lab,
            "tiene_demanda": tiene_demanda,
        })
    # Orden alfabético.
    sedes_meta.sort(key=lambda s: s["sede_nombre"])

    return {
        "sedes": sedes_meta,
        "dias": DIAS,
        "slots": slots_label,
        "data": data,
    }


def horarios_que_intersectan_rango(
    horarios: list[HorarioSlot],
    dias_seleccionados: list[str],
    slots_seleccionados: list[str],
    sedes_admisibles_por_materia: dict[str, set[str] | None],
    sede_id_inspeccionada: str,
    materia_lab_map: dict[str, set[str]],
    aula_sede_id: dict[str, str],
    *,
    incluir_no_demandantes: bool = False,
) -> dict:
    """Para el inspector de franja: devuelve los horarios que
    intersectan alguno de los días/slots seleccionados, marcando si
    cada uno demanda la sede inspeccionada (R10 + lab compatible).

    Cada horario se devuelve **completo** (de su ``hora_inicio`` a su
    ``hora_fin``), aunque el rango seleccionado sólo cubra parte.

    Args:
        horarios: todos los horarios del plan (los del LP infactible
            son los del input del LP).
        dias_seleccionados: lista de días tipo
            ``["Lunes", "Martes"]``.
        slots_seleccionados: lista de slots de 30 min en formato
            ``"HH:MM-HH:MM"`` (mismo formato que ``compute_heatmap_por_sede``).
        sedes_admisibles_por_materia: por materia, set de sede_ids
            admisibles según R10 (None = sin restricción).
        sede_id_inspeccionada: la sede que se está inspeccionando.
        materia_lab_map: aulas-lab compatibles por materia.
        aula_sede_id: mapping aula_id → sede_id.
        incluir_no_demandantes: si True, devuelve también horarios que
            intersectan el rango pero NO demandan la sede inspeccionada
            (contexto). Si False, solo los demandantes.

    Returns:
        ``{
            "horarios": [
                {
                    "horario_id", "dia", "hora_inicio", "hora_fin",
                    "materia_codigo", "tipo_clase",
                    "demanda_sede": bool,
                    "intersecta_directamente": bool,
                }, ...
            ],
            "n_demandantes": int,
            "n_contexto": int,
        }``
    """
    if not dias_seleccionados or not slots_seleccionados:
        return {"horarios": [], "n_demandantes": 0, "n_contexto": 0}

    # Convertir slots "HH:MM-HH:MM" a (start_min, end_min) y unirlos en
    # rangos contiguos para chequear intersección.
    rangos: list[tuple[int, int]] = []
    for slot in slots_seleccionados:
        try:
            inicio, fin = slot.split("-")
            h_i, m_i = inicio.split(":")
            h_f, m_f = fin.split(":")
            rangos.append((
                int(h_i) * 60 + int(m_i),
                int(h_f) * 60 + int(m_f),
            ))
        except (ValueError, IndexError):
            continue
    if not rangos:
        return {"horarios": [], "n_demandantes": 0, "n_contexto": 0}

    dias_set = set(dias_seleccionados)

    def _demanda_sede(h: HorarioSlot) -> bool:
        """¿El horario admite la sede inspeccionada (R10 + lab)?"""
        admis = sedes_admisibles_por_materia.get(h.materia_codigo)
        if admis is None:
            return True
        if sede_id_inspeccionada in admis:
            return True
        # Lab compatible en la sede prevalece.
        labs = materia_lab_map.get(h.materia_codigo, set())
        return any(
            aula_sede_id.get(a_id) == sede_id_inspeccionada
            for a_id in labs
        )

    def _intersecta(h: HorarioSlot) -> bool:
        if h.dia not in dias_set:
            return False
        h_s = h.hora_inicio.hour * 60 + h.hora_inicio.minute
        h_e = h.hora_fin.hour * 60 + h.hora_fin.minute
        for (a, b) in rangos:
            if h_s < b and h_e > a:
                return True
        return False

    out_items: list[dict] = []
    n_dem = 0
    n_ctx = 0
    for h in horarios:
        if not _intersecta(h):
            continue
        dem = _demanda_sede(h)
        if not dem and not incluir_no_demandantes:
            continue
        out_items.append({
            "horario_id": h.id,
            "dia": h.dia,
            "hora_inicio": h.hora_inicio,
            "hora_fin": h.hora_fin,
            "materia_codigo": h.materia_codigo,
            "tipo_clase": h.tipo_clase,
            "demanda_sede": dem,
            "intersecta_directamente": True,
        })
        if dem:
            n_dem += 1
        else:
            n_ctx += 1

    return {
        "horarios": out_items,
        "n_demandantes": n_dem,
        "n_contexto": n_ctx,
    }


def compute_impacto_r10(
    horarios: list[HorarioSlot],
    aulas: list[AulaSlot],
    materia_lab_map: dict[str, set[str]],
    compat: dict[tuple[str, str], bool],
) -> list[dict]:
    """Para cada materia presente en ``horarios``, mide cuantas aulas
    quedaron afuera por R10 (vs. el inventario que la materia podria
    usar por su tipo solamente).

    Devuelve una lista de dicts ordenada por mayor impacto (mas aulas
    perdidas), uno por materia. Cada dict tiene:

    - ``materia_codigo``
    - ``aulas_admisibles_post_r10``: cantidad de aulas que aceptan al
      menos un horario de la materia despues de R10 (segun ``compat``).
    - ``aulas_admisibles_pre_r10``: cantidad que aceptarian sin R10
      (sólo R3: tipo + lab compatible).
    - ``aulas_excluidas_por_r10``: diferencia.
    - ``ids_excluidas``: lista de aula_ids descartadas por R10.

    Materias con ``aulas_excluidas_por_r10 == 0`` igual aparecen en la
    lista (con 0) — el caller decide si las muestra.
    """
    # horarios por materia (para iterar)
    horarios_por_materia: dict[str, list[HorarioSlot]] = {}
    for h in horarios:
        horarios_por_materia.setdefault(h.materia_codigo, []).append(h)

    out: list[dict] = []
    for materia_codigo, hs in horarios_por_materia.items():
        # Pre-R10: usando compute_compat (sólo R3 + lab).
        lab_aulas_m = materia_lab_map.get(materia_codigo, set())
        ids_pre: set[str] = set()
        for h in hs:
            for a in aulas:
                if compute_compat(h, a, lab_aulas_m):
                    ids_pre.add(a.id)
        # Post-R10: usando el compat ya filtrado.
        ids_post: set[str] = set()
        for h in hs:
            for a in aulas:
                if compat.get((h.id, a.id), False):
                    ids_post.add(a.id)
        excluidas = ids_pre - ids_post
        out.append({
            "materia_codigo": materia_codigo,
            "aulas_admisibles_pre_r10": len(ids_pre),
            "aulas_admisibles_post_r10": len(ids_post),
            "aulas_excluidas_por_r10": len(excluidas),
            "ids_excluidas": sorted(excluidas),
        })

    out.sort(
        key=lambda r: (-r["aulas_excluidas_por_r10"], r["materia_codigo"]),
    )
    return out


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
