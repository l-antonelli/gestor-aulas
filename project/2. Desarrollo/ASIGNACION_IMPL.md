# Implementación del LP de asignación de aulas

> **Última actualización**: 2026-09-11.
> **Estado**: Fases 1 a 8 completas, más las extensiones posteriores
> descriptas en este documento (Grupos de materias, R13-alumno,
> R13-camino, IIS combinado, saneamiento de virtuales, veredicto
> estructurado, panel de calidad).
>
> **Ver también**:
> - Planteo formal: [`../1. Diseño/asignacion-aulas-LP.md`](../1.%20Diseño/asignacion-aulas-LP.md).
> - Guía operativa del asignador: [`RESTRICCIONES_LP.md`](RESTRICCIONES_LP.md).
> - Plan de retiro de `ClaseDB`: [`DEPRECACION_CLASEDB.md`](DEPRECACION_CLASEDB.md).
> - Workflow general del sistema: [`WORKFLOW.md`](WORKFLOW.md) § 9.

Este documento describe **cómo está implementado el LP**: qué
archivos participan, qué contratos exponen, cómo se orquesta el
flujo end-to-end y qué decisiones de ingeniería subyacen a cada
parte. El planteo matemático de las restricciones se documenta en
el Doc 1 (planteo formal); la operatoria desde la UI, en la guía
operativa. Este documento se pisa con ambos sólo en lo mínimo
necesario para que el lector pueda ir del código al modelo sin
perderse.

---

## 1. Visión general

Cerrada la grilla horaria del cuatrimestre, el asignador decide,
por cada `HorarioDB` presencial del plan, a qué `AulaDB` va, y de
qué **tipo** es (teoría o laboratorio) cuando el cronograma no lo
predeterminó. La decisión se toma resolviendo un programa lineal
entero con CBC vía PuLP.

Cuatro decisiones de diseño rigen toda la implementación:

1. **Fuente de verdad al nivel patrón semanal**. La asignación se
   guarda en `HorarioDB.aula_id`. `ClaseDB.aula_id` sobrevive como
   *cache* técnico deprecado (§ 10) al que se le propaga desde el
   patrón por compatibilidad con validación por-fecha, pero ninguna
   vista de la UI lo lee ni permite editarlo.
2. **El LP corre sobre el patrón semanal**. El conjunto `H` del
   modelo son los `HorarioDB` del plan (docenas a cientos), no las
   `ClaseDB` (miles). Trabajar sobre el patrón mantiene el modelo
   chico.
3. **Re-run incremental**. Cada corrida tiene un parámetro
   `fecha_desde` que acota la propagación al *cache*. Las clases
   con fecha anterior quedan intactas. El toggle "respetar
   ediciones manuales" traduce los pins del usuario a R11 (dura).
4. **Auditoría completa por corrida**. Cada ejecución persiste un
   `LPRunDB` con la config completa, status, métricas top-line y
   un `details_json` con el resultado por horario, el veredicto
   humano-legible, el diagnóstico y el IIS si corrió.

---

## 2. Arquitectura del servicio

El LP vive principalmente en tres archivos:

- `src/services/asignacion_aulas_service.py` — Orquestación con la
  base de datos: carga de inputs, construcción y resolución del
  modelo, aplicación de la solución, persistencia, diagnóstico
  post-solve.
- `src/services/asignacion_aulas_helpers.py` — Funciones puras sin
  Session: cálculo de grupos de simultaneidad, matriz de
  compatibilidad, pares intersede en riesgo, heatmaps y diagnóstico
  estructural.
- `src/services/factibilidad_service.py` — Chequeo estructural
  pre-solve. Consolida bloqueos por regla y produce el
  `ReporteFactibilidad` que consume el veredicto.

Servicios auxiliares:

- `src/services/grupo_materia_service.py` — Resolución de sedes
  admisibles por materia (partición estricta materia → grupo) y
  chequeo de consistencia por grupo.
- `src/services/plan_generation_service.py` — Forecast de
  inscriptos por comisión (`get_inscriptos_esperados_por_comision`).
- `src/services/resolucion_jerarquica.py` — `resolve_virtual` (3
  niveles: `HorarioDB.virtual > DictadoDB.virtual > MateriaDB.virtual`).

### 2.1 `asignacion_aulas_helpers` (sin DB)

Funciones puras, testeables sin `Session`, que no consultan la
base de datos:

- **`HorarioSlot`, `AulaSlot`**. *Dataclasses* planos con la vista
  mínima del horario y del aula que el LP necesita. Permiten
  aislar el resto del código de los modelos ORM.
- **`compute_simultaneidad_groups(horarios)`**. Barrido de eventos
  `O(N log N)` por día que devuelve los **grupos maximales de
  simultaneidad** `Sim` para R4. Cada grupo es un `set[str]` de
  IDs de horarios que comparten al menos un instante activo. La
  formulación por grupos maximales domina a la formulación por
  pares en cantidad de restricciones y en fuerza de la relajación
  lineal (ver § 5.3 del Doc 1).
- **`compute_compat(horario, aula, materia_lab_map)`**. Aplica R3
  (compatibilidad por tipo). No mira sedes — R10 se aplica encima
  en `build_inputs`.
- **`compute_pares_intersede_riesgo(horarios, comision_de_horario,
  margen_min, grupos_curriculares_por_horario)`**. Detecta pares
  `(h1, h2, gap)` de horarios contiguos el mismo día con gap menor
  al margen. Cubre dos ejes:
  - **Traslado del docente**: pares de la misma comisión.
  - **Traslado del alumno**: pares de materias distintas del mismo
    grupo curricular `(carrera, año, cuatri)`, si el caller
    proveyó el mapping.
- **`compute_heatmap_por_sede(...)`**. Computa la demanda por
  celda `(sede × día × franja × categoría)` con **cuatro vistas**:
  dura, preferida, máxima y total-sin-sede. Cada celda expone
  además la oferta agregada y — para labs — la oferta compatible
  (`oferta_compat`) que permite detectar pigeonhole y Hall por
  materia.
- **`check_lab_compatibilidad_en_celda(...)`**. Detecta pigeonhole
  y Hall en la asignación de labs por celda. Reporta la unión de
  labs compatibles vs demanda y, cuando `unión ≥ demanda` pero
  falla Hall, el subconjunto testigo.
- **`diagnose_infeasibility(...)`**. Diagnóstico estructural
  clásico pre-solve. Cubre 5 familias: horarios sin aula
  compatible (R1+R3+R10), franjas saturadas (pigeonhole global),
  saturación por tipo (refinamiento por pools disjuntos), Hall
  violators (matching bipartito), partición teoría/lab (R5). Ver
  § 4.1.

### 2.2 `factibilidad_service` (con DB)

Consolida el chequeo estructural pre-solve en una API única:

- **`check_factibilidad_estructural(session, plan_id, config)`**.
  Corre todos los chequeos y devuelve un `ReporteFactibilidad`
  con la lista de `Bloqueo`s, cada uno con `codigo_regla`,
  `severidad`, `titulo`, `detalle` y `entidades_a_revisar`.
- **`check_camino_cursada(session, plan_id, margen_min)`**. Chequeo
  R13-camino: para cada terna `(carrera, año, cuatri)` verifica
  que exista al menos una combinación de comisiones que un alumno
  pueda cursar sin conflictos horarios ni traslados imposibles.
  Backtracking DFS con cache por par `(cid_a, cid_b)`. Cap
  `MAX_COMBINACIONES_CAMINO = 10 000` para evitar explosión.

`_add_bloqueos_camino_cursada` es el helper interno que integra el
chequeo con `check_factibilidad_estructural`. Consulta
`IgnoredConflictDB` para saltar excepciones explícitas de
solapamiento (no de intersede — el traslado es físico y no depende
de qué alumnos cursen qué).

### 2.3 `asignacion_aulas_service` (con DB)

Orquesta el flujo completo. Los puntos de entrada públicos son:

```
run_lp(session, plan_id, config)
    ├── check_factibilidad_estructural(...)      ← corre siempre
    │       Si hay bloqueos → skip solver.
    ├── build_inputs(session, plan_id, config)
    ├── diagnose(inputs)                          ← siempre corre
    ├── build_model(inputs, config)
    ├── solve(model, timeout)
    ├── Si infeasible y sin bloqueos → _run_iis_relajacion(...)
    ├── apply_solution(session, plan_id, solution,
    │                  fecha_desde, respetar_manuales,
    │                  no_ocupa_aula_ids)
    └── persist_run(session, plan_id, config, inputs, solution,
                    fecha_desde, apply_result, diagnosis, iis,
                    reporte_estructural)
```

Cada uno de esos pasos se detalla abajo.

#### `build_inputs(session, plan_id, config, *, relax_r10=False)`

Arma el `LPInputs` del modelo desde la base:

1. Carga `AulaDB`, `MateriaLaboratorioDB`, `MateriaDB` y las
   comisiones + horarios del plan.
2. Filtra los horarios virtuales (`resolve_virtual`) y decide qué
   hacer con ellos según `strict_r5`:
   - Si `strict_r5=True` (default): entran al conjunto `H`
     marcados en `no_ocupa_aula_ids`. Participan de R5 pero se
     excluyen de R1/R3/R4/R7/R10/R11/R12/R13/R14.
   - Si `strict_r5=False` (legacy): se filtran completamente.
3. Resuelve `insc[h]` desde el forecast por comisión.
4. Resuelve sedes admisibles y preferidas por horario consultando
   `resolver_sedes_admisibles_por_materia` del servicio de grupos.
5. Computa `compat[(h, a)]` aplicando R3 + R10. Con `relax_r10=True`,
   se salta el filtro R10 completamente (usado por IIS).
6. Computa los grupos de simultaneidad sobre la grilla semanal.
7. Computa los pares intersede en riesgo (R13), incluyendo
   traslado del docente (misma comisión) y traslado del alumno
   (materias distintas del mismo grupo curricular).
8. Carga los pins manuales cuando `respetar_ediciones_manuales=True`
   (para R11).

Devuelve un `LPInputs` con todos los conjuntos y parámetros
pre-computados, más `warnings` no fatales (materias sin forecast,
virtuales filtradas, etc.).

#### `build_model(inputs, config, *, relax=None)`

Instancia el `pulp.LpProblem` y agrega restricciones en el orden
canónico:

- **R1** (asignación única): `Σ_a x[h, a] = 1 ∀ h ∈ H \ H_∅`.
- **R3** (compatibilidad tipo aula ↔ tipo clase): pre-aplicada en
  `compat`, se instancian variables sólo para pares compatibles.
- **R4** (no doble asignación): `Σ_{h ∈ S} x[h, a] ≤ 1` por cada
  `S ∈ Sim` y cada `a ∈ A`. Los virtuales quedan fuera.
- **R5** (partición teoría / lab): `Σ dur · t + Σ dur · t_const =
  hlab(m)` por comisión. Con `strict_r5=True`, también `Σ dur ·
  (1 - t) + Σ dur · (1 - t_const) = hteo(m)`. Los virtuales
  contribuyen al balance con su duración pero no toman `x`.
- **R6** (consistencia tipo ↔ pool) para horarios con `tipo_clase =
  None`: `Σ_{a ∈ A_teo} x[h, a] = 1 - t[h]` y
  `Σ_{a ∈ A_lab(m)} x[h, a] = t[h]`.
- **R7** (definición lineal de over/under en función de la
  capacidad).
- **R9** (redistribución α opcional): sólo si `activar_alpha=True`.
- **R11** (pins manuales): `x[h, aula_manual] = 1` para cada
  horario con pin, si `respetar_ediciones_manuales=True`. Si el
  pin apunta a un par no compatible, se emite una restricción
  imposible con nombre parlante (`R11_pin_incompat_<hid>`).
- **R12** (preferencia blanda de sede): añade `λ_sede_pref · x[h, a]`
  al objetivo cuando `sede(a) ≠ sede_pref(h)` y el grupo del
  horario corre en modo BLANDO con lista blanda no vacía.
- **R13** (continuidad de sede en pares en riesgo):
  `Σ_{a ∈ aulas(s1)} x[h1, a] + Σ_{a ∈ aulas(s2)} x[h2, a] ≤ 1`
  para cada par de sedes distintas `(s1, s2)` y cada par en riesgo.
- **R14** (misma sede por comisión, opcional): sólo cuando el
  toggle está On. Introduce `y[c, s] ∈ {0, 1}` con
  `Σ_s y[c, s] = 1` y `x[h, a] ≤ y[c, sede(a)]`.

El objetivo agrega los términos de over, under y sede_pref (§ 3.4
del Doc 1).

El parámetro `relax: set[str] | None` permite construir el modelo
saltando restricciones específicas — se usa desde el diagnóstico
IIS para probar cuál relajación rescata la solución.

#### `solve(model, timeout)`

Corre CBC vía PuLP con `timeLimit=timeout`. Devuelve un
`LPSolution` con:

- `status`: `optimal`, `infeasible`, `timeout`, `error`.
- `x_assignments`: `dict[horario_id → aula_id]` con la asignación.
- `tipo_resuelto`: `dict[horario_id → "teoria" | "laboratorio"]`
  para horarios con `tipo_clase = None`.
- `over`, `under`: `dict[horario_id → float]`.
- `alpha_resuelto`: `dict[comision_id → float]` si α estaba activo.
- `objective_value`, `solver_seconds`, `error_message`.

#### `apply_solution(...)`

Escribe la solución al patrón y propaga a las clases puntuales
del plan:

1. Para cada `(h, a) ∈ x_assignments`:
   - Setea `HorarioDB.aula_id = a`.
   - Preserva `aula_asignada_manualmente=True` si el horario tenía
     pin y `respetar_manuales=True` (la escritura es idempotente
     por R11). Si no, baja el flag.
   - Persiste `HorarioDB.tipo_clase` si `t[h]` resolvió el tipo y
     estaba en `None`.
   - Propaga a las `ClaseDB` no ejecutadas con `fecha ≥ fecha_desde`.

2. **Saneamiento de virtuales stale**. Los horarios en
   `no_ocupa_aula_ids` no producen entrada en `x_assignments`.
   Si arrastraban `aula_id` de una corrida vieja (cuando eran
   presenciales), la asignación quedaría stale. `apply_solution`
   la libera activamente:
   `HorarioDB.aula_id = None`,
   `aula_asignada_manualmente = False`,
   propagando al *cache* técnico. Preserva el pin si el usuario lo
   había fijado explícitamente y el toggle lo pide.

3. Devuelve un `ApplyResult` con contadores de horarios
   reasignados, clases actualizadas, ediciones manuales
   respetadas, y la lista de reasignaciones por horario.

#### `persist_run(...)`

Inserta un `LPRunDB` con:

- Referencia al plan, `run_at`, `fecha_desde`.
- Copia completa de los parámetros de la config.
- Resultado agregado: `status`, `objective_value`, contadores de
  horarios y clases, `solver_seconds`, `error_message`.
- **`details_json`** con:
  - `horarios`: detalle por horario (aula, tipo, insc, cap, over,
    under, estado ok/sobre/sub).
  - `heatmap_por_sede`: cuatro vistas (dura, preferida, máxima,
    total-sin-sede) precomputadas para la UI.
  - `veredicto`: bloque humano-legible con `status`, `resumen`,
    `causa_infactibilidad`, `bloqueos_diagnosticados`,
    `horarios_sin_asignar`, `restricciones_activas` (dump completo
    de `LPConfig` incluyendo `modos_por_grupo`).
  - `infeasibility_diagnosis`: cuando aplica.
  - `iis`: cuando corrió (§ 4.2).
  - `alpha_propuestos`: cuando α estaba activo.

#### `run_lp(session, plan_id, config)`

Wrapper end-to-end que ata todo lo anterior. Antes de instanciar
el modelo corre `check_factibilidad_estructural`. Si el reporte
tiene bloqueos, se saltea el solver, se persiste una corrida
`infeasible_estructural` con los bloqueos en el veredicto y se
devuelve al UI. Esto evita gastar hasta 5 min de timeout inútil
en planes estructuralmente rotos.

`apply_solution` se envuelve en `change_context(skip_hooks=True)`
para silenciar los hooks del change log durante la mutación
bulk. Si la corrida reasigna al menos un horario, se emite **un
solo** evento agregado en `ChangeLogDB` con
`entity_type=LPRunDB, origin='lp:run'` y la lista de
reasignaciones en `new_value`. Las corridas idempotentes (misma
asignación que la vez anterior) no emiten evento.

---

## 3. Datos de entrada y contratos

| Input | Origen | Notas |
|---|---|---|
| `A`, `cap[a]`, `tipo[a]`, `sede[a]` | `AulaDB` | Sin filtro. |
| `A_lab(m)` | `MateriaLaboratorioDB` | M:N materia ↔ aula. |
| Horarios del plan | `HorarioDB` filtrado por `comision_id ∈ comisiones(plan)` | Virtualidad resuelta con `resolve_virtual` (H > D > M). |
| `dur[h]` | `hora_fin - hora_inicio` | En horas. |
| `insc[h]` | `get_inscriptos_esperados_por_comision` | Forecast × coef comisión. Con α activo se reemplaza por `total_esp · α`. |
| `hteo[m]`, `hlab[m]` | `MateriaDB.horas_teoria` y `horas_laboratorio` | Alimentan R5. |
| `tipo(h)` fijado | `HorarioDB.tipo_clase` | `None` deja la decisión al LP (R6). |
| Sedes admisibles y preferida por horario | `resolver_sedes_admisibles_por_materia` (servicio de grupos) | Depende del grupo de la materia y del modo elegido en la corrida (`modos_por_grupo`). |
| Sim groups | `compute_simultaneidad_groups(horarios)` | Excluye virtuales. |
| Pares intersede en riesgo | `compute_pares_intersede_riesgo(...)` | Docente + alumno. Vacío si `margen_min = 0`. |
| Grupos curriculares por horario | Derivado de `PlanEstudioDB` + materia | Alimenta el eje "alumno" de R13. |
| Pins manuales | `HorarioDB.aula_id` con `aula_asignada_manualmente=True` | Sólo si `respetar_ediciones_manuales=True`. |

---

## 4. Diagnóstico y IIS

El asignador combina **dos capas** de diagnóstico:

- **Pre-solve estructural** (§ 4.1). Corre siempre antes del solver.
  Detecta situaciones que garantizan infactibilidad sin necesidad
  de encender CBC.
- **Post-solve por relajación selectiva (IIS)** (§ 4.2). Sólo corre
  cuando el solver dio `infeasible` y el pre-solve no detectó
  bloqueos. Identifica la restricción culpable o combinaciones de
  restricciones cuando ninguna regla individual explica el problema.

Ambas capas persisten su resultado en `LPRunDB.details_json` para
que la UI pueda reconstruir el diagnóstico sin re-correr.

### 4.1 Chequeo estructural pre-solve

Consolidado en `factibilidad_service.check_factibilidad_estructural`.
Cada familia produce cero, uno o más `Bloqueo`s con
`codigo_regla` y detalles. La UI los renderiza en el panel del
asignador debajo del semáforo de factibilidad.

Familias implementadas:

1. **R1** — Horarios sin aula compatible. Distingue causas:
   R1+R3 clásica (sin lab compatible o tipo desalineado) y R10
   (sedes vacías después del filtro).
2. **R3+R4** — Saturación por tipo dentro de una franja
   (refinamiento del *pigeonhole* clásico por pools disjuntos
   teóricas / labs).
3. **R5** — Partición teoría / lab infactible: la suma de
   duraciones no cierra con `hteo + hlab`, o alguna partición
   necesaria por materia no existe (subset-sum).
4. **R11** — Pin manual apunta a un aula ya no compatible.
5. **R13** — Par de horarios en riesgo sin sede común factible.
6. **R13-camino** — No existe combinación de comisiones viable
   para algún grupo curricular (§ 2.2, `check_camino_cursada`).
7. **compat-pigeonhole** — Pigeonhole por celda del mapa
   (unión de labs compatibles < demanda simultánea).
8. **compat-hall** — Hall violator por celda: existe subconjunto
   `T` de materias del que sólo alcanzan `|N(T)| < |T|` labs.

La familia 1 usa `diagnose_infeasibility` de los helpers puros;
las demás se computan directamente en `factibilidad_service`. El
`ReporteFactibilidad` expone `factible: bool`, `bloqueos: list[Bloqueo]`
y `resumen_por_regla: dict[str, int]`.

### 4.2 IIS por relajación selectiva

Cuando el solver reporta `infeasible` y el pre-solve no detectó
bloqueos que expliquen la causa, se dispara `_run_iis_relajacion`.

**Relajación individual** — Se prueba, una a la vez, saltar cada
una de las restricciones candidatas: R4, R5, R6, R10, R13, R14.
R10 se relaja reconstruyendo `build_inputs` con `relax_r10=True`
(el filtro se aplica en la matriz `compat`, no en el modelo); el
resto se saltea vía `build_model(relax={"Rk"})`. La restricción
que rescata la solución es la culpable candidata.

**Filtros de falsos positivos** — Cuando la causa real es una
restricción saturadora (típicamente R4), relajar otras también
funciona porque le da libertad extra al solver. Para evitar
culpables espurios:

- **R5**. Se descarta si al relajar no aparece ninguna materia
  con `hlab_declarado > 0` desalineada. Si sólo materias sin lab
  declarado quedan con `t[h]` cambiado, el "arreglo" es efecto
  secundario.
- **R6**. Se descarta si todos los horarios con `tipo(h) = ⊥`
  tienen alternativa válida (aula teórica o lab compatible). Si
  todos tienen alternativa, la causa real es saturación (R4).
- **R4** se prioriza sobre R5/R6 cuando aparecen juntos como
  candidatos.

**Priorización de la causa principal** — Cuando quedan varios
culpables reales, se elige con el orden accionable
`R10 → R14 → R13 → R4 → R5 → R6`. Las restricciones "de sede"
(R10, R14, R13) tienen prioridad porque el usuario las controla
directamente desde el panel.

**Refinamiento cuando R10 es la principal**
(`_iss_r10_grupos_rescate`) — Se prueba pasar **cada grupo DURO a
BLANDO por separado** y se registra cuáles rescatan
individualmente. Se filtran grupos que:

- Están en modo DURO en la corrida actual.
- Tienen lista blanda no vacía (BLANDO tendría efecto real).
- Tienen al menos una materia con comisiones en el plan.

La UI puede así recomendar "pasá el grupo *X* a modo BLANDO" en
vez del genérico "R10 es la causa".

**Análisis combinado** — Cuando ninguna regla individual rescata,
la infactibilidad es combinada. `_iss_combinaciones_rescate` prueba
combinaciones de a pares:

- Cada grupo DURO → BLANDO **combinado con** desactivar R14 (si
  estaba On).
- Cada grupo DURO → BLANDO **combinado con** poner
  `margen_min_intersede = 0` (si era > 0).

Cap `CAP_PRUEBAS = 40` combinaciones. Se registra cada
combinación que rescata el modelo. La UI las ordena por menor
impacto (grupos con menos materias primero).

**Estructura del resultado** (en `details_json.iis`):

```jsonc
{
  "ran": true,
  "culpables": ["R10", "R13"],
  "principal": "R10",
  "detalles": {
    "R4": {"feasible_relajado": false, "es_falso_positivo": false, ...},
    "R5": {"feasible_relajado": true, "es_falso_positivo": true, ...},
    "R10": {
      "feasible_relajado": true,
      "grupos_rescate": [
        {"grupo_id": "...", "grupo_nombre": "Específicas de Ing. Eléctrica",
         "n_materias_plan": 13, "modo_actual": "DURO", "modo_propuesto": "BLANDO"}
      ]
    }
  },
  "combinaciones_rescate": [
    {"grupo_id": "...", "grupo_nombre": "Específicas de Ing. Civil",
     "n_materias_plan": 8, "extra": "sin_forzar_misma_sede",
     "extra_label": "desactivar 'Forzar misma sede por comisión'"}
  ]
}
```

---

## 5. Grupos de materias — implementación

La entidad `GrupoMateriaDB` define el criterio de sedes admisibles
por grupo curricular. Cada `MateriaDB` pertenece a exactamente un
grupo (partición estricta enforzada por `grupo_id NOT NULL`).

### 5.1 Schema

- `GrupoMateriaDB` — Identificador, nombre, flag `es_sin_clasificar`
  y los tres flags de chequeo de consistencia
  (`chequear_pertenencia_asociadas`,
  `chequear_exclusividad_no_asociadas`, `chequear_completitud`).
- `GrupoMateriaSedeDB` — M:N ordenada entre grupo y sede, con
  `tipo ∈ {DURO, BLANDO}` y `orden`. Una misma sede puede
  aparecer en ambos tipos: son listas independientes.
- `GrupoMateriaCarreraDB` — Asociación grupo ↔ carrera para el
  chequeo de consistencia (opcional, no afecta al LP).
- `MateriaDB.grupo_id` — FK a `GrupoMateriaDB`, NOT NULL.

### 5.2 Resolución en el LP

`grupo_materia_service.resolver_sedes_admisibles_por_materia(session,
materia_codigo)` devuelve `(sedes_ordenadas: list[str], modo:
Literal["DURO", "BLANDO"])`:

- Con `modo="DURO"`:
  - `sedes_ordenadas` es el set duro del grupo.
  - Lista vacía = fallback permisivo (todas admisibles).
- Con `modo="BLANDO"`:
  - `sedes_ordenadas` es la lista blanda del grupo.
  - Primera sede = preferida (paga cero al objetivo).
  - Resto = alternativas con costo `λ_sede_pref`.

El modo con el que corre cada grupo se elige por corrida desde
`LPConfig.modos_por_grupo`. Si un grupo no aparece en el dict, se
asume DURO (default seguro).

`build_inputs` consume la resolución para:

- Alimentar la matriz `compat` con R10 (modo DURO con lista no
  vacía → filtro; modo BLANDO → sin filtro, todas admisibles).
- Alimentar `sede_preferida_por_horario` (modo BLANDO con lista
  no vacía → primera sede; en otro caso `None`, no aplica R12).

**Excepción de laboratorio compatible**: si el aula está en
`MateriaLaboratorioDB` para la materia, se acepta aunque su sede
no esté en el set duro. La compatibilidad física del laboratorio
prevalece sobre la preferencia curricular.

### 5.3 Bootstrap

`connection.py._migrate_grupos_materia` crea idempotentemente al
inicializar la base:

- `Sin clasificar` (DURO, todas las sedes, fallback permisivo).
- `FB`, `FI`, `CE` (DURO Pellegrini) y `F` (DURO Siberia) por
  prefijo del código de materia.
- `Específicas de <Carrera>` por cada carrera, DURO con las sedes
  que la carrera tenía en el modelo viejo (`CarreraSedeDB`).

Las materias se asignan al grupo que corresponda por prefijo o
por "materia exclusiva de una sola carrera". El resto cae en
`Sin clasificar` y aparece con warning en la UI para que se cure.

### 5.4 Legacy deprecado

`CarreraSedeDB` y `MateriaDB.es_default_comunes` **ya no son
leídos por el LP ni por la UI**. La tabla y el flag sobreviven
por un release para no romper migraciones de bases viejas, pero
no participan de ningún flujo. La resolución de sedes va
exclusivamente por grupo. `ComisionDB.carrera_asignada` sigue
siendo una etiqueta visual sin efecto en el LP.

---

## 6. Ediciones manuales y colisiones de aula

La edición manual del aula de un horario se hace desde varios
puntos de la UI (Cronogramas, Detalle del plan, Aulas por sede).
Todas comparten la lógica de servicio.

### 6.1 `cambiar_aula_horario`

Signatura:

```python
cambiar_aula_horario(
    session, horario_id, aula_id,
    *, nuevo_tipo=None, propagar_a_clases=True,
) -> ValidationResult
```

- Setea `HorarioDB.aula_id` (admite `None` para liberar).
- Si `nuevo_tipo` se especifica, también modifica
  `HorarioDB.tipo_clase`.
- Valida vía `_validar_aula_para_horario`: compatibilidad
  tipo ↔ aula y choque temporal contra OTROS `HorarioDB` del
  mismo plan en la misma franja.
- Con `propagar_a_clases=True` (default), propaga al *cache*
  técnico. Preserva las clases con
  `aula_asignada_manualmente=True`.
- Devuelve `ValidationResult`. Si falla, no persiste.

### 6.2 Preview de impacto y colisiones

`plan_actions_service.preview_cambio_horario(session, horario_id,
nuevo_slot)` computa el impacto de mover un horario a un nuevo
slot y devuelve, entre otros datos:

- `colisiones_aula`: lista de otros horarios que ocupan la misma
  aula en la franja destino. Cada uno viene con su materia,
  comisión, día y horario para que el usuario pueda ver quién es
  el ocupante.

Cuando hay colisiones, el componente compartido
`horario_edit_shared.render_preview_impacto_edicion` muestra:

- Un banner de colisión con la lista de ocupantes.
- Un botón "Liberar aula del otro horario" que llama a
  `liberar_aula_horario(...)` para poner `aula_id=None` y bajar el
  flag manual, dejando que el LP lo reasigne en la próxima
  corrida.
- Un botón "Cancelar edición".

Este flujo se dispara en:

- Detalle del plan → editor de grilla (`plan_grilla_editor.py`).
- Detalle del plan → editor por materia (`plan_materia_editor.py`).
- Aulas por sede → cronograma del aula (`aula_cronograma_view.py`).

### 6.3 Toggle "respetar ediciones manuales"

- **On (default)**. Los horarios con
  `aula_asignada_manualmente=True` entran como R11 (dura) al
  modelo. La solución del solver ya trae `x[h, a_pin] = 1` y
  `apply_solution` preserva el flag. La lista de pins se muestra
  en un expander del panel con botón para liberar cualquiera.
- **Off**. Los pins se ignoran al construir el modelo (no se
  emite R11) y el flag se baja a `False` para cada horario que
  el LP reasigna.

Si un pin apunta a un aula ya no compatible (cambió el tipo, la
sede quedó fuera de las admisibles del grupo en modo DURO, etc.),
el LP reporta infactibilidad estructural en R11 y la UI ofrece
liberar el pin o reasignar manualmente.

### 6.4 Badge visual "manual"

Los horarios con `aula_asignada_manualmente=True` aparecen con un
badge "manual" en el expander correspondiente del detalle del
plan. Permite distinguir rápido las asignaciones fijadas por el
operador de las resueltas por el LP.

---

## 7. Toggle α (redistribución de coeficientes)

Cuando los pesos manuales (`ComisionDB.coef_asignacion`) no calzan
con la capacidad disponible, el toggle "Redistribuir pesos α
(avanzado)" en el panel permite que el LP los proponga sujeto a
`Σ_{k ∈ dictado} α[k] = 1` (R9).

Flujo:

1. El usuario activa el toggle y corre el LP.
2. El LP usa variables continuas `α[k] ∈ [0, 1]` y reemplaza
   `insc[h]` por `total_esperado[m] · α[k]` en R7. La formulación
   sigue siendo lineal porque `cap[a]` se multiplica por `x[h, a]`,
   no por `α[k]`.
3. La solución incluye `alpha_resuelto: dict[comision_id → α*]`.
   Las aulas asignadas en esa corrida asumen los pesos propuestos.
4. **No se persiste automáticamente**. La modificación de
   `coef_asignacion` requiere confirmación del usuario.
5. La UI muestra una tabla "Pesos propuestos" con diff coloreado
   y dos botones: "Aplicar nuevos pesos" (llama a
   `aplicar_alpha_propuesto` y persiste) y "Descartar" (deja los
   pesos viejos, pero advierte que las aulas ya no son
   consistentes; conviene re-correr con α Off).

`LPRunDB.activar_alpha` y `details_json["alpha_propuestos"]`
guardan la propuesta para que la UI pueda mostrarla sin re-correr
el solver.

**Caso de prueba canónico**: 2 comisiones del mismo dictado con
`coef=[1.0, 0.0]`, total=120, dos aulas iguales `cap=60`. Con α
Off queda `over=60`. Con α On, `α* = [0.5, 0.5]` y
`over + under = 0`.

---

## 8. Excepciones ignoradas (`IgnoredConflictDB`)

`IgnoredConflictDB` registra pares de materias que el chequeo de
solapamiento horario debe ignorar. Se usa cuando en la práctica
una comisión de la materia A y una de la materia B nunca son
cursadas por el mismo alumno (materias homónimas en años
distintos del plan, por ejemplo).

Alcance de la excepción:

- **Solapamiento horario**: la excepción salta el chequeo.
- **Intersede (R13, R13-camino)**: la excepción NO aplica. El
  traslado físico es independiente de qué alumnos cursen qué.

### 8.1 Auto-limpieza de excepciones stale

Cuando el plan cambia y una materia deja de coexistir con la
otra en algún grupo curricular, la excepción queda huérfana.
`plan_validation_service.cleanup_stale_ignored_pairs` la limpia
automáticamente en la próxima ejecución de `validate_plan` y
reporta la limpieza al usuario en el summary (`excepciones_stale_removidas`).

---

## 9. UI — panel de resultado

El panel de resultado (`asignacion_resultado_ui.py`) se compone
de varios bloques que aparecen según el estado de la corrida:

- **📋 Veredicto de la corrida** (siempre). Status, resumen humano,
  causa de infactibilidad si aplica, y expander con las
  restricciones activas.
- **Bloqueos estructurales** (`infeasible_estructural`). Lista los
  bloqueos por regla con sus entidades y sugerencia de acción.
- **Diagnóstico cruzado** (`infeasible`). Muestra el resultado del
  IIS: causa principal, grupos de rescate (§ 4.2), combinaciones
  de rescate cuando ninguna regla individual explica.
- **Tabla de horarios asignados**. Recomputada en vivo desde
  `HorarioDB` para reflejar cambios manuales posteriores a la
  corrida. Umbrales de tol_over / tol_under se toman del run
  vigente para consistencia.
- **Horarios fuera de sede preferida**. Expander que lista los
  horarios cuyo grupo corría en BLANDO y terminaron en una sede
  alternativa. Sirve para auditar el impacto de R12.
- **Mapa de saturación por sede**. Cuatro vistas seleccionables
  (dura, preferida, máxima, total-sin-sede) con sub-control de
  oferta de labs (todo el catálogo / sólo compatibles). Las
  celdas Hall-violadoras se marcan con ⚠️ y tooltip con el
  subconjunto testigo.

El panel de calidad (en Planes → Detalle, no en Aulas) muestra 4
familias de métricas de la última corrida:

- **Cobertura**: asignados / totales, sede preferida / alternativa,
  comisiones completas.
- **Ajuste al forecast**: sobrecupo total, subutilización total,
  ratio promedio / mediana / P90, peor caso.
- **Uso del catálogo**: aulas usadas / ociosas, concentración por
  sede.
- **Estado del LP**: valor de la función objetivo, tiempo del
  solver, ediciones manuales respetadas, traslados intersede.

Se computa vía `metricas_calidad_service.compute_metricas_calidad`
a partir del estado vigente de la base, no del snapshot del último
`LPRunDB`.

---

## 10. Deprecaciones activas

- **`ClaseDB` como fuente de verdad de asignación**. Deprecado
  desde 2026-08-28. El LP y toda la UI trabajan sobre
  `HorarioDB.aula_id`. `ClaseDB.aula_id` se mantiene como *cache*
  con propagación desde el patrón por compatibilidad con
  validación por-fecha, pero ninguna vista lo lee ni permite
  editarlo. Plan de retiro en [`DEPRECACION_CLASEDB.md`](DEPRECACION_CLASEDB.md).
- **`ClaseDB.aula_asignada_manualmente`**. El flag vive en
  `HorarioDB.aula_asignada_manualmente`. La columna en `ClaseDB`
  existe por compatibilidad de esquema, pero no la consulta ni
  la escribe ningún flujo.
- **`CarreraSedeDB` y `MateriaDB.es_default_comunes`**. Deprecados
  desde 2026-09. La resolución de sedes va exclusivamente por
  `GrupoMateriaDB`. Sobreviven en el schema por un release para
  no romper migraciones viejas.
- **Edición manual de `ClaseDB` por fecha** (2026-07-07). Toda la
  batería (`aplicar_edicion_manual`, `cambiar_tipo_clase_puntual`,
  `clases_del_rango`, `validar_edicion_manual`,
  `get_aulas_disponibles`, diálogo `_dialog_cambiar_aula`, tab
  "📅 Clases") fue removida. Sólo queda la edición del patrón
  (`cambiar_aula_horario`).

---

## 11. Tests

Cobertura principal:

- **`tests/test_asignacion_aulas_helpers.py`** — Grupos de
  simultaneidad, matriz de compatibilidad, diagnóstico de
  infactibilidad, partición teoría/lab, heatmap por sede y sus
  cuatro vistas, `sede_preferida_para_horario`,
  `compute_pares_intersede_riesgo` (docente + alumno),
  `check_lab_compatibilidad_en_celda` (pigeonhole y Hall).
- **`tests/test_asignacion_aulas_service.py`** — `build_inputs`,
  `run_lp_dry` con fixtures mínimas, persistencia y `LPRunDB`,
  fecha_desde y respetar_manuales, lab/teoría split, edición
  manual, toggle α, R13 pares en riesgo, saneamiento de virtuales
  stale, integración con `strict_r5=True`.
- **`tests/test_factibilidad_service.py`** —
  `check_factibilidad_estructural`, `check_camino_cursada`,
  integración de todas las familias de bloqueo, cap de
  `MAX_COMBINACIONES_CAMINO`.
- **`tests/test_grupo_materia_service.py`** — CRUD de grupos,
  partición estricta, resolución de sedes por materia, chequeo
  de consistencia con sus tres flags.
- **`tests/test_plan_validation_service.py`** —
  `cleanup_stale_ignored_pairs`, integración con `validate_plan`.

Todos los tests corren con `pytest tests/` sin dependencias
externas (moto / mocks / DB en memoria).

---

## 12. Cuestiones abiertas y extensiones

- **Estabilidad entre re-corridas**. El LP no penaliza cambios
  respecto de la corrida previa. Si dos re-runs con configuración
  parecida dan asignaciones distintas, sería deseable un término
  `λ_estabilidad · |x_actual − x_previa|` en el objetivo. Por
  ahora el toggle "respetar ediciones manuales" cubre las
  ediciones intencionales.
- **Disponibilidad parcial de aulas** (exámenes, refacciones,
  eventos). No modelado. Se podría agregar
  `AulaIndisponibleDB(aula_id, fecha, hora_inicio, hora_fin)`.
- **Ventanas operativas por sede**. Hoy `ConfiguracionHoraria` es
  global. Si se abren sedes con horarios distintos, agregar
  `hora_apertura / cierre` a `SedeDB`.
- **R13 blanda**. `lambda_intersede` está cableado en el modelo
  pero no activo (default 0). Reservado para una variante blanda
  de R13 que penalice cambios de sede pero no los prohíba.
- **Combinaciones IIS de a tres o más**. Hoy sólo se prueban
  pares (grupo DURO → BLANDO + R14 / margen). Combinaciones de
  tres serían explosivas; se dejó fuera del alcance.
