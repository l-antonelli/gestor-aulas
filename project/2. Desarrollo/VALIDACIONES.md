# Validaciones del sistema

Este documento describe **todas** las validaciones que ejecuta gestor-aulas
para garantizar la consistencia del cronograma, los planes de cursada y
la asignación final de aulas. Está organizado por capa (servicio,
agregador, UI inline) y por entidad sobre la que opera.

> **Convención de severity**: `BLOCKER` impide avanzar al próximo paso
> (p. ej. activar un plan). `WARNING` advierte pero no bloquea. `INFO`
> es puramente informativo.

---

## 1. Validaciones a nivel servicio (`src/services/validations.py`)

Funciones unitarias que devuelven `ValidationResult(valid, message, details)`.
Pueden invocarse independientemente; algunas se agrupan dentro de los
servicios agregadores (`cronograma_validation_service`,
`plan_validation_service`).

### 1.1. `validar_materias_tienen_carrera`

- **Qué verifica**: que toda fila de `MateriaDB` aparezca en al menos un
  `PlanEstudioDB` (i.e. esté asociada a una carrera/plan).
- **Severity**: BLOCKER — una materia sin carrera no puede entrar en
  ningún plan.
- **Details**: lista `cod: nombre` de materias sin asociación.
- **Cuándo correrla**: durante seeding/load inicial. La UI no la expone
  con un botón explícito; es un guard del proceso de carga.

### 1.2. `validar_factibilidad_horarios_carrera(carrera, año, cuatri, plan_version_id?)`

- **Qué verifica**: para una tupla `(carrera, año, cuatri)` (opcionalmente
  acotada a una `plan_version_id`), que los horarios de las materias del
  grupo curricular **no se superpongan**, asumiendo un alumno tipo que
  cursa todo el grupo.
- **Lógica interna**: cruza `PlanEstudioDB → MateriaDB → ComisionDB →
  HorarioDB` y aplica `horarios_se_superponen` por par.
- **Severity**: WARNING — un alumno real solo cursaría un subset, pero
  un solapamiento total entre dos materias del mismo grupo es
  estructuralmente problemático.
- **Hermana**: `validar_factibilidad_horarios_todas_carreras` itera sobre
  todas las combinaciones `(carrera, año, cuatri)`.
- **Cuándo correrla**: durante exploración inicial. No la expone hoy
  ningún botón de la UI nueva; sobrevive como herramienta de debug.

### 1.3. `validar_conflictos_aula_plan(plan_id)`

- **Qué verifica**: para un plan ya **asignado** (con `ClaseDB.aula_id`
  poblado), que no haya dos clases en la misma `(aula, fecha)` con
  rangos horarios superpuestos.
- **Severity**: BLOCKER post-asignación — significaría doble booking
  físico de un aula.
- **Cuándo correrla**: después de la asignación de aulas. Hoy no se
  invoca desde el panel de validación unificado (ese opera pre-asignación).

### 1.4. `validar_conflictos_horarios_plan(plan_id, ignored_pairs=None)`

- **Qué verifica**: dentro de un plan, para cada `(carrera, año, cuatri)`
  derivado de `PlanEstudioDB` del ciclo, que **al menos un par de
  comisiones sea compatible** entre cada par de materias del grupo. Si
  para algún par no existe ningún emparejamiento de comisiones sin
  superposición → conflicto real.
- **Lógica clave**:
  1. Filtra a grupos del **cuatri del ciclo + Anuales del mismo
     carrera/año** (descarta el cuatri opuesto).
  2. Para cada par de materias del grupo, busca pairwise compatibility
     entre sus comisiones via `_comisiones_son_compatibles`.
  3. Si `ignored_pairs` contiene `(mat_a, mat_b)` lexicográficamente
     ordenado, salta el chequeo (el usuario marcó el conflicto como
     ignorado en `IgnoredConflictDB`).
- **Severity**: BLOCKER — un plan con conflictos no se puede activar.
- **Versión estructurada**: `validar_conflictos_horarios_plan_estructurados`
  devuelve `list[ConflictoHorario]` (rico: incluye `carrera_codigo`,
  `anio_plan`, `cuatrimestre_plan`, `materia_a`, `materia_b`, `dia`,
  `hora_inicio_a/b`, `hora_fin_a/b`) para que la UI agrupe por carrera y
  arme tabla resumen + detalle.

### 1.5. `validar_cobertura_plan(plan_id, ciclo_id)`

- **Qué verifica**: que toda materia con dictado activo en el ciclo
  tenga al menos una `ComisionDB` con horarios cargados en el plan.
- **Severity**: WARNING — informa materias del ciclo no cubiertas, pero
  no bloquea (puede ser intencional excluirlas).
- **Nota**: el panel unificado reusa esta lógica indirectamente vía
  `validar_plan` (que computa esperadas/cubiertas/faltantes a partir
  del set de dictados activos).

### 1.6. `identificar_virtuales_plan(plan_id)`

- **Qué verifica**: lista materias virtuales (`MateriaDB.virtual=True`)
  con horarios cargados en el plan. Solo informa que **no necesitan
  aula** al asignar.
- **Severity**: INFO.

### 1.7. `validar_factibilidad_particion_horas(schedule_id?, plan_cursada_id?)`

- **Qué verifica**: para cada comisión de una materia con
  `horas_laboratorio > 0`, que las duraciones de sus clases puedan
  **particionarse** en dos subconjuntos cuyas sumas sean `horas_teoria`
  y `horas_laboratorio` respectivamente.
- **Lógica**:
  1. Toma materias con `horas_laboratorio > 0` (ignora `None` o `0`).
  2. Agrupa entries/horarios por `(materia, comision)`.
  3. Si hay clases con `tipo_clase` predeterminado (`teorica` /
     `laboratorio`), valida que las sumas predeterminadas no excedan
     `horas_teoria` / `horas_laboratorio`.
  4. Resuelve un **subset-sum** sobre las duraciones para verificar
     existencia de partición válida.
- **Severity**: BLOCKER — sin partición factible, el LP de asignación
  no puede separar slots de teoría y laboratorio.
- **Source dual**: opera tanto sobre `schedule_id` (cronograma crudo)
  como sobre `plan_cursada_id` (plan estructurado).

### 1.8. `validar_conflictos_horarios_cronograma(schedule_id, ciclo_id)`

- **Qué verifica**: espejo de `validar_conflictos_horarios_plan_estructurados`
  pero sobre `ScheduleEntryDB`. Las "comisiones" se derivan
  automáticamente del campo `ScheduleEntryDB.comision` (int) por materia.
- **Severity**: BLOCKER (en el panel del cronograma).
- **Output**: `list[ConflictoHorario]`.

---

## 2. Validaciones agregadas (servicios de prevalidación)

Estos servicios ejecutan **un grupo coherente** de validaciones contra
una entidad y devuelven un `ValidationSummary` que la UI consume.
Cada validación se persiste en una tabla de snapshot
(`ScheduleValidationDB`, `PlanValidationDB`) para auditoría y staleness.

### 2.1. `validar_cronograma(schedule_id, ciclo_id, exclude_optativas=False)`
→ `CronogramaValidationSummary`

Compone el siguiente resumen contra un cronograma + ciclo:

1. **Pre-check**: que el ciclo tenga **dictados creados**
   (`has_dictados_for_ciclo`). Si no, `summary.error` se pobla y se
   aborta.
2. **Snapshot del cronograma**: `entry_count_at_validation`,
   `dictado_count_at_validation` (para detectar staleness en el futuro).
3. **Cobertura**: `n_esperadas`, `n_cubiertas`, `n_faltantes`, `n_extra`
   contra el set de dictados activos del ciclo. Si
   `exclude_optativas=True`, las optativas se descartan **del set
   esperado y del set de extras** (filtro simétrico).
4. **Faltantes por carrera**: detalle agrupado con código de dictado
   de cada faltante (vía `_get_faltantes_por_carrera`).
5. **Lab breakdown**: para las materias presentes en el cronograma con
   `MateriaLaboratorioDB`, cuenta:
   - `n_con_lab_asignado`: total con lab compatible asignado.
   - `n_lab_fijo`: subset con `horas_laboratorio > 0`.
   - `n_lab_reserva`: subset con `horas_laboratorio == 0` (reserva
     ad-hoc, lo decide el docente fuera del LP).
   - `n_lab_pendiente`: subset con `horas_laboratorio is None` (falta
     definir; bloqueante para el siguiente paso).
6. **Partición teoría/lab**: invoca
   `validar_factibilidad_particion_horas(schedule_id=...)`.
7. **Conflictos de horarios**: invoca
   `validar_conflictos_horarios_cronograma`. Lista estructurada por
   carrera/año/cuatri.
8. **Config aplicada**: `excluir_optativas` queda persistido en el
   snapshot. Si el toggle cambia entre runs, el snapshot está stale.

**Persistencia**: `persist_validation` inserta una fila en
`ScheduleValidationDB` con detalle JSON (`details_json`) para
reconstruir la UI sin recomputar.

**Staleness** (`is_validation_stale`): True si cambió alguno de:
- `entry_count_at_validation` (se editaron entries del cronograma).
- `dictado_count_at_validation` (cambiaron los dictados activos del
  ciclo).
- `excluir_optativas` (toggle aplicado).

### 2.2. `validar_plan(plan_id, exclude_optativas=False)`
→ `PlanValidationSummary`

Espejo del cronograma sobre `PlanificacionCursadaDB`. Diferencias:

- **Pre-checks adicionales**:
  - Plan existe y tiene ciclo asignado.
  - Plan tiene comisiones (sino `summary.error`).
- **Conflictos**: invoca `validar_conflictos_horarios_plan_estructurados`
  pasando `ignored_pairs` desde `IgnoredConflictDB`.
- **Conflictos ignorados**: además del set activo, calcula la lista
  completa con `ignored_pairs=set()` y filtra los que coinciden con los
  pares ignorados. Eso permite mostrarlos en una tabla aparte.
- **No tiene lab breakdown** (los labs viven a nivel cronograma).

**Persistencia**: `PlanValidationDB`.

**Staleness**: cambia `comision_count_at_validation`,
`horario_count_at_validation`, `dictado_count_at_validation` o
`excluir_optativas`.

### 2.3. Tabla `IgnoredConflictDB`

PK compuesta `(plan_cursada_id, materia_a, materia_b)` con `materia_a <
materia_b` lexicográficamente.

- **Granularidad**: por par de materias, no por slot horario. Si los
  horarios cambian, el par sigue ignorado.
- **CRUD**: `add_ignored_pair(plan_id, mat_a, mat_b, razon)`,
  `remove_ignored_pair(...)`, `get_ignored_pairs(plan_id) -> set`.

---

## 3. Validaciones inline en la UI

### 3.1. Panel de validación unificado (`src/ui/validation_ui.py::render_validation`)

Punto de entrada: `render_validation(source, schedule_id?, ciclo_id?,
plan_id?, key_ns)`. `source ∈ {'plan', 'schedule'}` decide qué servicio
agregador llamar y qué bloques mostrar. La estructura común es:

1. **Toggle "Excluir optativas"** + **toggle "Auto-revalidar al cambiar"**
   + **botón "Validar"** (en una sola fila).
2. **Resumen de cobertura**: 6 métricas (Materias, Clases, Horas,
   Esperadas, Cubiertas, Faltantes).
3. **Lab breakdown** (solo cronograma): 4 métricas (Con lab asignado,
   Lab fijo, Reserva ad-hoc, Pendiente).
4. **Partición teoría/lab**: success/error según el resultado de
   `validar_factibilidad_particion_horas`.
5. **Detalle por carrera** (expander principal con tabla resumen de
   issues + sub-expanders por carrera con):
   - Discrepancias de dictado (faltantes + no esperadas) con tabla,
     selector multi y botones bulk Activar/Desactivar dictado.
   - Conflictos de horarios con tabla resumen, detalle, botón "Resolver
     conflicto" (solo plan: muestra calendario read-only del par y
     shortcut "Editar A" / "Editar B" al editor inline) y "Ignorar
     conflicto" (solo plan: agrega a `IgnoredConflictDB`).
   - Conflictos ignorados (solo plan): tabla + botón "Dejar de ignorar".
6. **Detalle por materia** (expander principal con tabla resumen
   filtrable por carrera/año/cuatri/estado/búsqueda + selector "Materia
   activa" + calendario embebido + editor inline):
   - **Plan**: editor completo via
     `plan_materia_editor.render_plan_materia_detail`.
   - **Cronograma**: editor completo via
     `schedule_materia_editor.render_schedule_materia_detail` (pendiente
     de re-implementación — antes vivía inline en
     `validacion_cronograma_tab.py` y se borró por error en Sub-task C).
7. **Activación gate** (solo plan): botón "Activar plan" deshabilitado
   si hay conflictos no ignorados.

Cada acción del panel (activar/desactivar dictados, ignorar/dejar de
ignorar conflicto) marca un flag `_pending_revalidate_key` consumido en
el siguiente render — si "Auto-revalidar" está ON, corre `validar_plan`
/ `validar_cronograma` automáticamente y muestra un toast.

### 3.2. Estado por materia (`_estado_de_materia`)

La tabla "Detalle por materia" computa para cada materia un **estado
único** mostrado con badge:

| Estado | Trigger | Badge |
|---|---|---|
| `Faltante` | Esperada pero sin comisiones/entries | 📭 Faltante |
| `No esperada` | Tiene comisiones/entries pero sin dictado activo | 📥 No esperada |
| `Conflictiva` | Aparece como uno de los códigos en
`summary.conflictos_horarios` | ⚠️ Conflicto |
| `Sin datos` | No tiene `horas_semanales` definido | ❓ Sin datos |
| `OK` | Cubierta sin issues | ✅ OK |

El filtro "Estado" del panel acepta multi-selección de cualquiera de
los 5 valores.

---

## 4. Validaciones inline del editor por materia (cronograma)

> Estas son las validaciones del **editor por materia del cronograma**
> (`schedule_materia_editor.render_schedule_materia_detail`) que se
> ejecutan en vivo a medida que el usuario edita los entries del
> cronograma. Vivieron antes en `validacion_cronograma_tab.py` (en lo
> que internamente se llamó "Phase 2") y se rescatan como parte del
> editor inline.

Para cada materia activa del cronograma, el editor renderiza:

1. **Controles de horas** (con auto-save al cambiar):
   - `Hs/sem`: `MateriaDB.horas_semanales`.
   - `Hs teoría` y `Hs lab` (sólo si la materia tiene lab asignado o ya
     tiene los datos cargados): `MateriaDB.horas_teoria` y
     `MateriaDB.horas_laboratorio`.
2. **Selector de cantidad de comisiones** (override del derivado del
   cronograma) + **botón "Reasignar comisiones"** que redistribuye las
   clases entre las comisiones por round-robin balanceando por horas.
3. **`data_editor`** con todos los entries de la materia, columnas:
   `Día / Inicio / Fin / Comisión / Tipo / Hs`. La columna `Tipo` admite
   `sin determinar / teorica / laboratorio` (sin determinar = el LP
   decide). `Hs` se computa como `(fin − inicio)` y es read-only.
4. **Resumen** (`N clases · X horas en cronograma · M comision(es)`) +
   distribución de horas por comisión.
5. **10 chequeos estructurados** (cada uno con `status ∈ {ok, warn,
   error, info}`, `label`, `detail`) que se renderean en una grilla con
   tilde verde / signo de exclamación amarillo / círculo rojo / signo
   de pregunta gris según el `status`. Lista completa abajo.

### 4.1. `hsem_x_com` — h/sem × comisiones = total

- **OK**: `horas_semanales × n_comisiones == total_horas_cronograma`.
- **WARN**: discrepancia (`hsem × ncom ≠ total`). Sugiere que faltan
  o sobran clases en el cronograma respecto a las horas declaradas.
- **INFO**: si `horas_semanales` no está cargado.

### 4.2. `divisible` — Horas divisibles entre comisiones

- **OK** (solo aplica con `n_com > 1`): `total_horas / n_comisiones`
  cae en bloques limpios de 15 min.
- **WARN**: el reparto no cae en múltiplos de 15 min, lo que indica
  que las clases no se pueden dividir equitativamente entre comisiones.

### 4.3. `balanced` — Comisiones equilibradas

- **OK**: todas las comisiones tienen las mismas horas asignadas.
- **WARN**: distribución desigual. Detalle muestra `Cn: Xh` por comisión.

### 4.4. `paralelas` — Clases paralelas ≤ comisiones

- **OK**: el máximo de clases en paralelo (mismo día, mismo bloque
  horario) no excede el `n_comisiones`.
- **ERROR**: hay más clases simultáneas que comisiones disponibles —
  indica que la cantidad de comisiones está subdimensionada para
  cubrir el cronograma.

### 4.5. `empty_com` — Sin comisiones vacías

- **OK**: todas las comisiones tienen al menos una clase asignada.
- **WARN**: hay comisiones sin clases. Detalle lista los números.

### 4.6. `hsem_set` — Horas semanales definidas

- **OK**: `MateriaDB.horas_semanales > 0`.
- **WARN**: falta el dato. Bloquea el chequeo `hsem_x_com`.

### 4.7. `thl_sum` — Hs teórica + Hs lab = Hs semanales

- **OK**: `horas_teoria + horas_laboratorio == horas_semanales`.
- **ERROR**: la suma no coincide (con `horas_semanales > 0`). El editor
  muestra `st.warning` y **no auto-guarda** los cambios hasta que la
  suma sea consistente.
- **INFO**: `horas_semanales` no está cargado, no se puede comparar.
- **WARN**: la materia tiene lab asignado pero `Hs teoría/lab` no están
  definidos.

### 4.8. `thl_reserva` — Modo lab

Determina el modo de tratamiento del lab para la asignación posterior
(LP). Solo aplica si la materia tiene lab asignado vía
`MateriaLaboratorioDB`:

- **OK** (`lab fijo`): `horas_laboratorio > 0`. El LP usa los slots
  para fijar el laboratorio.
- **INFO** (`reserva ad-hoc`): `horas_laboratorio == 0`. El LP no fija
  laboratorio; los docentes lo reservan caso por caso durante el
  ejercicio del plan.
- **WARN** (`pendiente`): `horas_laboratorio is None`. Falta definir;
  bloqueante para asignación.

### 4.9. `thl_predet` — Predeterminados consistentes

Solo aplica si `horas_laboratorio > 0`. Suma las duraciones de las
clases marcadas explícitamente como `tipo = "laboratorio"` o
`"teorica"` por comisión y verifica que no excedan el presupuesto:

- **OK**: para toda comisión, `Σ duración(tipo=laboratorio) ≤ horas_lab`
  y `Σ duración(tipo=teorica) ≤ horas_teoria`. El detalle dice cuántas
  horas hay predeterminadas como cada tipo.
- **ERROR**: hay alguna comisión donde la suma predeterminada excede
  el presupuesto. Detalle lista los violadores como
  `Cn: lab predeterminado Xh > Hs lab Yh`.

### 4.10. `thl_partition` — Partición teoría/lab factible

Solo aplica si `horas_laboratorio > 0` y `horas_teoria` está cargado.
Para cada comisión:

1. Verifica que la suma total de duraciones sea exactamente
   `horas_teoria + horas_laboratorio`.
2. Resuelve un `subset_sum_exists(durations, horas_laboratorio)` para
   verificar que existe una partición de las clases en dos subconjuntos
   que sumen exactamente `horas_teoria` y `horas_laboratorio`.

- **OK**: cada comisión puede dividirse limpiamente en `Xh teoría +
  Yh lab`.
- **ERROR**: hay comisiones donde el total no coincide o no existe
  partición factible. Detalle lista como
  `Cn: clases [d1, d2, ...] no se pueden particionar para sumar Hs
  lab Xh`.

### Worst status (badge de la materia activa)

El editor calcula el **peor `status`** entre los 10 chequeos, con
prioridad `error > warn > info > ok`. Ese worst se muestra como **badge
arriba del editor** (antes era el icono del expander del loop):

| Worst status | Icono | Ejemplo |
|---|---|---|
| `error` | 🔺 | Paralelas > comisiones, o partición infactible |
| `warn` | ⚠️ | Discrepancia de horas, comisiones desbalanceadas |
| `info` | ❓ | Falta dato (h/sem no definido) o modo reserva ad-hoc |
| `ok` | ✅ | Todos los chequeos pasan |

> El cache `_chk_worst_<schedule_id>_<materia_codigo>` permite que el
> selector "Materia activa" muestre el badge de cada materia sin
> recomputar todo el editor — útil para ordenar por estado.

---

## 5. Validaciones a nivel base de datos (CRUD/constraints)

Estas viven como `Field(ge=0)`, `Field(gt=0)`, `Field(min_length=1)`,
`unique=True`, `foreign_key=...` en `src/database/models.py`. Garantizan
que ningún path de inserción permita estados inválidos:

- `MateriaDB.codigo` único; `nombre` no vacío; `horas_semanales >= 0`
  cuando se setea.
- `ComisionDB.cupo > 0`; `coef_asignacion ∈ [0, 1]`.
- `HorarioDB.dia` indexado; FK a `comisiones.id`.
- `IgnoredConflictDB`: PK compuesta evita duplicados; el helper
  `add_ignored_pair` además ordena lexicográficamente para que
  `(A, B) == (B, A)`.
- `ScheduleValidationDB.excluir_optativas` y
  `PlanValidationDB.excluir_optativas` con default `False` para
  compatibilidad con snapshots viejos.

---

## 6. Cómo se conecta todo

```
┌──────────────────────┐  ┌──────────────────────┐
│ Tab Cronogramas      │  │ Page Planes (Detalle)│
│ → "Validar"          │  │  _render_plan_editor │
│ render_tab()         │  │                      │
└──────────┬───────────┘  └──────────┬───────────┘
           │                         │
           v                         v
   render_validation(           render_validation(
     source='schedule',          source='plan',
     schedule_id, ciclo_id,      plan_id, key_ns)
     key_ns)                      │
           │                      │
           v                      v
   _render_schedule()       _render_plan()
           │                      │
           ├──► validar_cronograma()    ├──► validar_plan()
           │     ├─► validar_factibilidad_particion_horas
           │     └─► validar_conflictos_horarios_cronograma
           │                      │
           │                      ├─► validar_factibilidad_particion_horas
           │                      └─► validar_conflictos_horarios_plan_estructurados
           │
           ▼  (subviews compartidas)
   _build_grupos_por_carrera, _render_carrera_subexpander,
   _render_dictado_action_selector, _render_conflictos_carrera,
   _render_detalle_por_materia
                                  │
                                  ▼  (editor inline)
                          plan_materia_editor.render_plan_materia_detail
                          schedule_materia_editor.render_schedule_materia_detail
```

---

## 7. Decisiones de diseño relevantes

- **Toggle "Excluir optativas"** (no virtuales): las virtuales SÍ
  validan estructuralmente (cobertura + conflictos + partición), aunque
  al asignar aulas se descartan. Solo las optativas se descartan
  completamente del cómputo cuando el toggle está ON. Aplicación
  simétrica: optativas no aparecen como esperadas ni como "no esperadas".
- **Snapshot persistido** (`ScheduleValidationDB`, `PlanValidationDB`):
  cada validación queda en DB para auditoría y para reconstruir la UI
  sin recomputar. La UI compara contra el snapshot vivo para detectar
  staleness.
- **Conflictos del plan: ignorables vía `IgnoredConflictDB`**. Los del
  cronograma no son ignorables (las comisiones del cronograma son
  auto-derivadas; si hay conflicto, se edita el cronograma). Esto
  refleja un principio: **el cronograma es el source of truth de los
  horarios; el plan es el contrato editable**.
- **Auto-revalidar**: toggle propio en cada panel, default ON. Cualquier
  acción del panel marca un flag pendiente; si está ON, la siguiente
  rerun re-corre la validación y muestra un toast con el delta.
