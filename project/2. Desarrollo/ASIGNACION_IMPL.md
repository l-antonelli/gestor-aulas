# Implementación del LP de asignación de aulas

> **Última actualización**: 2026-06-04
> **Estado**: Fases 1 a 8 implementadas (incluye toggle α de
> redistribución de pesos).
>
> **Ver también**:
> - Planteo formal: [`asignacion-aulas-LP.md`](../1.%20Diseño/asignacion-aulas-LP.md)
> - Workflow general: [`WORKFLOW.md`](WORKFLOW.md) § 9

## 1. Visión general

El planteo matemático del LP está cerrado en
`project/1. Diseño/asignacion-aulas-LP.md` (variables `x[h, a]`, `t[h]`,
`α[k]`, restricciones R1–R9, formulación por grupos de simultaneidad
para R4). Este documento describe **la implementación** y la operatoria
para el usuario.

Decisiones de diseño que rigen toda la implementación:

1. **Storage único**: la asignación de aula se guarda exclusivamente en
   `ClaseDB.aula_id`. No existe un campo `HorarioDB.aula_id` ni una
   tabla intermedia. La "semana modelo" se deriva agrupando `ClaseDB`
   por `horario_id`.
2. **El LP corre sobre la semana modelo, no sobre cada `ClaseDB`**: el
   conjunto `C` del LP son los `HorarioDB` del plan. Después de
   resolver, la solución se propaga a todas las `ClaseDB` con
   `fecha ≥ fecha_desde` y `executed = False`. Esto reduce el modelo
   a docenas/cientos de variables binarias en lugar de miles.
3. **Re-run incremental**: cada corrida tiene un `fecha_desde` y NO
   toca las clases anteriores ni las ya ejecutadas. Por default
   respeta también las clases con `aula_asignada_manualmente=True`,
   pero ese toggle se puede desactivar.
4. **Auditoría completa**: cada corrida genera un `LPRunDB` con su
   configuración, status, métricas top-line y un `details_json` con
   el detalle por horario y el diagnóstico estructural.

## 2. Arquitectura del servicio

### 2.1 `asignacion_aulas_helpers` (sin DB)

`src/services/asignacion_aulas_helpers.py` contiene funciones puras
testeables sin Session:

- **`HorarioSlot`**, **`AulaSlot`**: dataclasses planos con la vista
  mínima del horario y del aula que el LP necesita.
- **`compute_simultaneidad_groups(horarios)`**: barrido de eventos
  `O(N log N)` por día que devuelve los grupos maximales `Sim` de
  R4. Cada grupo es un set de IDs de horarios que comparten al menos
  un instante.
- **`compute_compat(horario, aula, materia_lab_aulas)`**: aplica R3
  (compatibilidad por tipo).
- **`compute_heatmap_carga(horarios)`**: matriz día × franja de 30 min
  con clases simultáneas, desglosada por tipo declarado en el
  cronograma. Sirve para el panel de diagnóstico.
- **`diagnose_infeasibility(horarios, aulas, materia_lab_map, sim_groups)`**:
  detecta causas estructurales de infactibilidad **antes** de armar
  el LP. Tres tipos de causa:
  1. Horarios sin ninguna aula compatible (R3 sin opciones).
  2. Franjas saturadas: en un grupo de simultaneidad de N horarios,
     la unión de aulas compatibles tiene cardinalidad < N (pigeonhole
     conservador).
  3. Pre-validación de partición teoría/lab por comisión
     (`validar_particion_factible`): subset-sum sobre las duraciones
     respetando los tipos fijados en el cronograma.

### 2.2 `asignacion_aulas_service` (con DB)

`src/services/asignacion_aulas_service.py` orquesta el flujo completo:

```
build_inputs(session, plan_id, config)
    └── carga aulas, comisiones, horarios, MateriaLaboratorioDB,
        forecast por comisión, computa compat y sim_groups.
    → LPInputs

diagnose(inputs)
    → InfeasibilityDiagnosis (puede tener problemas aunque el LP
      después resuelva si las cotas son conservadoras)

build_model(inputs, config)
    └── R1: Σ x[h, a] = 1 ∀ h
    └── R3: variables x[h, a] sólo para pares compatibles
    └── R4: para cada grupo de simultaneidad y cada aula, Σ ≤ 1
    └── R5: Σ_{h∈k} dur[h]·t[h] = hlab(materia(k))
    └── R6: si t[h]=0 → aula teórica; si t[h]=1 → A_lab(materia)
    └── R7: over[h] ≥ insc[h] − Σ x[h,a]·cap[a]·(1+tol_over);
            under[h] ≥ Σ x[h,a]·cap[a]·(1−tol_under) − insc[h]
    → (pulp.LpProblem, vars_dict)

solve(prob, vars_dict, config)
    └── PuLP + CBC con timeLimit
    → LPSolution con x_assignments, tipo_resuelto, over, under

apply_solution(session, plan_id, solution, fecha_desde, respetar_manuales)
    └── propaga aula_id a ClaseDB filtrando fecha ≥ fecha_desde,
        executed=False, y opcionalmente aula_asignada_manualmente=False.
    └── propaga tipo_clase resuelto si el horario lo tenía None.
    → ApplyResult

persist_run(session, plan_id, config, inputs, solution, fecha_desde,
            apply_result, diagnosis)
    └── inserta una fila en LPRunDB con la corrida y su detalle.
    → LPRunDB

run_lp(session, plan_id, config)
    └── wrapper end-to-end de los anteriores.
```

### 2.3 Datos de entrada

| Input | Origen |
|---|---|
| Aulas (`A`, `cap[a]`, `tipo[a]`) | `AulaDB` |
| `A_lab(m)` | `MateriaLaboratorioDB` (M:N materia↔aula tipo lab) |
| Horarios del plan | `HorarioDB` filtrando por `comision_id` de las comisiones del plan; se excluyen los de materias virtuales |
| `dur[h]` | `hora_fin − hora_inicio` del `HorarioDB` |
| `insc[h]` | `total_esperado(materia(h)) × coef_asignacion(comision(h))`, computado por `plan_generation_service.get_inscriptos_esperados_por_comision` |
| `hteo[m]`, `hlab[m]` | `MateriaDB.horas_teoria` y `horas_laboratorio` |
| `fija_lab(h)` | `HorarioDB.tipo_clase` (`None` deja la decisión al LP) |
| Sim groups | `compute_simultaneidad_groups(horarios)` |
| Tolerancias y pesos | `LPConfig` (UI) |
| `open_h, close_h` | `ConfiguracionHoraria` (R8 defensivo, no entra al LP) |

### 2.4 Output persistido

- **`ClaseDB.aula_id`**: aula resuelta para cada clase de la semana
  modelo, propagada a todas las fechas correspondientes en el rango.
- **`ClaseDB.tipo_clase`**: si el `HorarioDB` lo tenía en `None` y R5+R6
  lo decidieron, se setea en la clase.
- **`ClaseDB.aula_asignada_manualmente`**: `False` para las pisadas por
  el LP. Sólo se pone en `True` desde la UI de edición manual.
- **`LPRunDB`**: una fila por corrida. Histórico para auditar y
  comparar configuraciones.

## 3. Política de re-run

### 3.1 `fecha_desde`

Configurable en la UI (default: hoy). El LP siempre se modela y resuelve
sobre la **semana modelo completa** (todos los `HorarioDB` del plan),
pero la propagación de la solución a `ClaseDB` filtra por
`fecha ≥ fecha_desde`. Las clases anteriores quedan exactamente como
estaban.

### 3.2 Toggle "respetar ediciones manuales"

- **ON (default)**: las `ClaseDB` con `aula_asignada_manualmente=True`
  no se pisan. Quedan con su aula previa intacta. Aparecen en
  `LPRunDB.n_ediciones_manuales_respetadas`.
- **OFF**: el LP retoma el control absoluto. Las clases manuales se
  pisan y el flag se baja a `False`.

### 3.3 Casos especiales

- **Clases ya `executed=True`**: nunca se tocan, sin importar la
  configuración.
- **Materias virtuales** (`MateriaDB.virtual=True`): sus horarios no
  entran al LP en absoluto y sus `ClaseDB` nunca tienen aula.
- **Clases sin forecast** (materia sin serie histórica ni override):
  se asignan con `insc=0`, lo cual hace que el LP las ponga en el aula
  más chica disponible. Se reporta como warning en `LPRunDB`.

## 4. Diagnóstico de infactibilidad

Cuando el solver devuelve `infeasible`, **sin diagnóstico estructural el
mensaje es inútil**. El servicio computa `diagnose_infeasibility` siempre
(no sólo cuando el LP falla) y persiste el resultado en
`LPRunDB.details_json`. El diagnóstico aplica cinco técnicas en orden
de informatividad creciente — la lectura de cada item del reporte está
ordenada para que el usuario vea primero las causas más concretas y
accionables.

> **Documento de diseño**: `project/1. Diseño/asignacion-aulas-LP.md`
> § 4ter detalla el planteo formal y las cotas matemáticas de cada
> técnica. Este documento describe la implementación.

La UI muestra:

1. **Inventario de aulas**: total y desglose por tipo
   (`teorica`, `laboratorio`, `anfiteatro`).
2. **Heatmap de carga**: matriz día × franja de 30 min con clases
   simultáneas. Filtrable por `tipo_clase` declarado: Todas, Teórica
   fijada, Laboratorio fijado, Sin determinar. Renderizado con Altair
   (escala lineal blanco→rojo). Las celdas en cero quedan transparentes
   y los huecos entre clases consecutivas no solapadas se ven
   claramente.
3. **Comisiones con partición infactible** (R5): tabla con materia,
   `hteo`, `hlab`, sumas fijadas, sumas totales, y razón concreta
   (suma no coincide / lab fijado excede / subset-sum infactible).
4. **Horarios sin aula compatible**: tabla con materia, día, franja,
   tipo y razón concreta (ej. "sin laboratorios en
   `MateriaLaboratorioDB` para QUI"). Acción sugerida: cargar labs
   compatibles, marcar el horario como teoría, agregar aulas.
5. **Saturación por tipo dentro de una franja**: refina la cota
   pigeonhole global mirando por separado teóricas y labs. Por cada
   franja saturada por tipo, la tabla muestra día, franja, tipo
   problemático (`teórica` o `laboratorio` con la materia indicada),
   `n_necesarias / n_disponibles` y materias afectadas. Manejo
   **optimista** de `tipo_clase = None`: una clase sin tipo
   determinado sólo se cuenta contra el pool teórico si NO admite
   ir a lab (`materia_lab_map[m]` vacío); análogamente para lab.
   Esto evita falsos positivos. Acción sugerida: marcar virtual algún
   dictado de recursado, agregar aulas del tipo correcto, ampliar
   `MateriaLaboratorioDB`.
6. **Hall violators**: matching bipartito por grupo. Para grupos
   chicos (≤8) enumeración exacta de subconjuntos por tamaño
   creciente; para grupos más grandes, augmenting paths clásicos
   O(V·E). Reporta el subconjunto Hall-violador más chico (testigo
   minimal), incluyendo las aulas exactas a las que ese subconjunto
   está restringido. Detecta casos que pigeonhole no ve, ej.
   `{h1,h2,h3}` con `h1→{a,b,c}, h2→{a}, h3→{a}`: |union|=3 ✓ pero
   `{h2,h3}→{a}` viola Hall.
7. **Franjas saturadas (pigeonhole)**: tabla con día, franja exacta
   de intersección, ventana total, cantidad de clases simultáneas,
   cantidad de aulas compatibles, desglose por tipo (`T:23 L:6`).
   Cota más débil que (5) y (6) pero útil cuando ambas pasan y igual
   hay saturación residual.
8. **IIS por relajación selectiva** (sólo cuando 1-7 vienen vacías y
   el solver tiró infactible): el sistema relaja R4, R5 y R6 por
   separado y vuelve a resolver. La relajación que arregla el modelo
   identifica la restricción culpable. Implementado en
   `_run_iis_relajacion`; agrega el parámetro `relax: set[str]` a
   `build_model` para omitir las constraints correspondientes. Para
   R5 además identifica las **materias específicas** problemáticas
   comparando `Σ dur·t[h]` resuelto vs `hlab[m]` declarado.
   Costo: hasta 3× tiempo de solver extra. Trigger automático
   (no opt-in): sólo se ejecuta cuando hace falta. Si ninguna
   relajación arregla, la infactibilidad es combinada y se reporta
   como "no concluyente".

### 4.1 Pendientes documentados

Las técnicas (1)-(8) cubren las causas estructurales atómicas, de
fronteras y combinadas. Queda pendiente para iteración futura:

- **Pico de simultaneidad por tipo siempre visible**: incluso si el
  LP da factible, mostrar la franja con mayor presión por tipo para
  anticipar problemas si se agregan dictados.

## 5. Edición manual de aula

### 5.1 Tres modos

- **Esta clase puntual**: edita exactamente una `ClaseDB`.
- **Rango de fechas**: edita las `ClaseDB` con misma `(comision_id,
  día_de_la_semana, hora_inicio, hora_fin)` dentro del rango. Es decir,
  agarra "el mismo slot semanal" repetido a lo largo del cuatrimestre.
- **De hoy en adelante**: equivalente a rango con `fecha_desde=hoy` y
  `fecha_hasta=ciclo.fecha_fin`.

### 5.2 Validaciones pre-confirmación

- **Tipo aula compatible** con `tipo_clase` (R3/R6): teóricas a aulas
  teorica/anfiteatro; labs sólo a aulas en `MateriaLaboratorioDB` para
  esa materia.
- **No doble booking** (R4): el aula nueva no puede estar ocupada por
  ninguna otra `ClaseDB` del plan en ninguna de las fechas/franjas
  involucradas.
- **Capacidad** (warning, no bloquea): si `cap[a] < esperados[c]`, se
  muestra advertencia pero la edición sigue siendo válida.

### 5.3 Helpers

- **`get_aulas_disponibles(session, plan_id, clase_ids)`**: filtra el
  selector del dialog a sólo aulas factibles para todas las
  fechas/franjas elegidas + tipo compatible.
- **`validar_edicion_manual(session, clase_ids, aula_nueva_id)`**:
  re-corre las 3 validaciones y devuelve `ValidationResult` con
  errores/warnings.
- **`aplicar_edicion_manual(session, clase_ids, aula_nueva_id)`**:
  setea `aula_id` y `aula_asignada_manualmente=True` en todas las
  clases del rango.
- **`clases_del_rango(session, clase_ref_id, fecha_desde, fecha_hasta)`**:
  devuelve las `ClaseDB` del mismo slot semanal en el rango.

## 6. Vistas operativas

### 6.1 Tab "🏛️ Aulas" en Planes

`app/pages/5_📊_Planes.py` agrega un tab nuevo. Selector de ciclo + plan
+ panel de asignación.

### 6.2 Panel de asignación (`asignacion_panel.py`)

- Form de configuración: `fecha_desde`, `λ_over`, `λ_under`, `tol_over`,
  `tol_under`, toggles, timeout.
- Botón "Correr LP" con spinner.
- Summary del último run: status, métricas top-line, configuración
  aplicada en expander.
- Detalle del resultado o diagnóstico de infactibilidad
  (`asignacion_resultado_ui.render_resultado`).
- Vista cronograma por aula en expander aparte
  (`aula_cronograma_view.render_aula_cronograma`).

### 6.3 Detalle del resultado (`asignacion_resultado_ui.py`)

- Heatmap de carga (siempre, expandido cuando el LP falla).
- Si el run no es óptimo: diagnóstico estructural arriba.
- Si el run es óptimo:
  - **Métricas agregadas** (5–6).
  - **Tabla por horario** con `Materia | Comisión | Día | Horario |
    Aula | Cap | Esperados | Δ | Estado` coloreada (verde/amarillo/
    rojo según gap vs tolerancias).
  - **Candidatas a partir comisión**: materias con horarios
    sobre-ocupados, ordenadas por exceso total de alumnos.

### 6.4 Cronograma por aula (`aula_cronograma_view.py`)

- Selector de aula (sólo las que tienen al menos una clase asignada).
- Indicador "horarios uniformes vs divergentes": cuenta cuántos
  `HorarioDB` tienen el aula igual en TODAS las semanas del ciclo y
  cuántos tienen al menos una semana con otra aula (típicamente por
  ediciones manuales puntuales).
- Selector de semana (lunes a domingo del ciclo).
- Calendar read-only de FullCalendar con las clases de esa aula en
  esa semana.
- **Listado debajo del calendar** con botón "Editar" por cada clase
  → abre el dialog de edición manual.

## 7. Tests

`tests/test_asignacion_aulas_helpers.py` cubre los helpers puros:
grupos de simultaneidad (5 casos), compatibilidad (4 casos), diagnóstico
de infactibilidad (5 casos), partición teoría/lab (5 casos).

`tests/test_asignacion_aulas_service.py` cubre el servicio con DB:
build_inputs (2 casos), `run_lp_dry` con fixtures mínimas (3 casos),
persistencia y `LPRunDB` (3 casos), fecha_desde y respetar_manuales
(3 casos), lab/teoría split (1 caso e2e), edición manual (5 casos).

Total: **38 tests verdes** al cierre de Fase 7.

## 7bis. Toggle α (redistribución de pesos)

Cuando los pesos manuales (`ComisionDB.coef_asignacion`) no calzan con
la capacidad disponible, el toggle "Redistribuir pesos α (avanzado)" en
el panel permite que el LP los **proponga de cero** sujeto a
`Σ_{k ∈ dictado} α[k] = 1` (R9). El flujo es:

1. Usuario activa el toggle, corre el LP.
2. El LP usa variables continuas `α[k] ∈ [0, 1]` y reemplaza
   `insc[h]` por `total_esperado[m] · α[k]` en R7. La formulación
   sigue siendo lineal porque `cap[a]` se multiplica por `x[h, a]`,
   no por `α[k]`.
3. La solución incluye `alpha_resuelto: dict[comision_id → α*]`. Las
   aulas asignadas en esta corrida **asumen los pesos propuestos**.
4. **No se persiste automáticamente**: la modificación de
   `coef_asignacion` requiere confirmación del usuario.
5. La UI de resultado muestra una tabla "Pesos propuestos" con diff
   coloreado (verde = sube, rojo = baja) y dos botones: "Aplicar
   nuevos pesos" llama a ``aplicar_alpha_propuesto`` y persiste;
   "Descartar" deja los pesos viejos pero advierte que las aulas
   asignadas ya no son consistentes con esos pesos viejos (conviene
   re-correr con α OFF).

Servicios:

- **``aplicar_alpha_propuesto(session, plan_id, alpha_dict)``**:
  persiste `coef_asignacion` para las comisiones del plan que están
  en el dict.

`LPRunDB.activar_alpha` y `details_json["alpha_propuestos"]` guardan
la propuesta para que la UI pueda mostrarla sin re-correr el solver.

Caso clásico de prueba (en `tests/test_asignacion_aulas_service.py
::TestToggleAlpha`): 2 comisiones del mismo dictado con
`coef=[1.0, 0.0]`, total=120, dos aulas iguales `cap=60`. Con α
**OFF** queda `over=60`. Con α **ON**, `α* = [0.5, 0.5]` y
`over+under = 0`.

## 8. Cuestiones abiertas y extensiones

- **Cota exacta para franjas saturadas**: hoy la pre-validación R4
  usa una cota conservadora (unión de aulas compatibles). Para
  detección exacta haría falta matching bipartito (Hopcroft–Karp). En
  la práctica la cota es suficiente.
- **Disponibilidad parcial de aulas** (exámenes que toman aula): no
  modelado. Se podría agregar una tabla `AulaIndisponibleDB` con
  `(aula_id, fecha, hora_inicio, hora_fin)`.
- **Ventanas operativas por sede**: hoy `ConfiguracionHoraria` es
  global. Si se abren sedes con horarios distintos, agregar
  `hora_apertura/cierre` a `SedeDB`.
- **Estabilidad entre re-corridas**: el LP no penaliza cambios
  respecto a la corrida previa. Si dos re-runs con configuración
  parecida dan asignaciones distintas, sería deseable un término
  `λ_estabilidad · |x_actual − x_previa|`. Por ahora el toggle
  "respetar ediciones manuales" cubre el caso de las ediciones
  intencionales.
