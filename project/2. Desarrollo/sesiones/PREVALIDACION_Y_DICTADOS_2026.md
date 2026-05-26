# Prevalidación y Dictados — Refactor 2026-05

> **Sesión**: 2026-05-21 → 2026-05-26
> **Alcance**: Revolución del flujo de "materias esperadas" + reorganización
> de la pestaña Dictados como editor central + on-the-fly editing desde
> prevalidación.
> **Estado**: implementado y commiteado.

Este documento condensa los cambios de modelo, servicios y UI que afectan
el flujo Cronograma → Prevalidación → Plan de Cursada. Si venís de leer
`CONSOLIDACION_PAGINA_PLANES.md` o `EDITOR_PLANES_DICTADOS_VALIDACIONES.md`
y notás divergencias, **este documento gana** sobre los anteriores.

---

## 1. Motivación

Hasta este refactor, las "materias esperadas" en la prevalidación se
calculaban directamente desde el JOIN `MateriaDB ⨝ PlanEstudioDB ⨝
PlanCarreraVersionDB ⨝ CicloPlanVersionDB`. Toda materia del plan se
consideraba "esperada", sin pasar por una capa de "qué se va a dictar
realmente este cuatrimestre".

Problemas que esto traía:

1. Si una carrera no va a dictar una materia este cuatri, no había forma
   de excluirla de la prevalidación más allá de la heurística rígida de
   `dicta_recursado` por carrera.
2. La pestaña "Dictados" existía (con `DictadoDB`, botón "Crear Dictados",
   toggle activo/virtual) pero **no influía** en la prevalidación. Eran
   dos mundos paralelos.
3. No había manera de hacer overrides puntuales por materia.

**Objetivo**: que `DictadoDB` (los activos linkeados a un ciclo) pase a ser
**la fuente de verdad de "materias esperadas"** para la prevalidación.

---

## 2. Cambios de modelo

### 2.1 `MateriaDB.dicta_recursado: Optional[bool]`

Nuevo campo en `MateriaDB` (`src/database/models.py:178`). Override que
gana sobre `CarreraDB.dicta_recursado`:

- `None` (default) → usar el flag de la carrera.
- `True` → la materia se ofrece (activo=True) siempre, sin importar carrera.
- `False` → la materia no se ofrece si su cuatri del plan es opuesto al ciclo.

Migración en `src/database/connection.py`:
```sql
ALTER TABLE materias ADD COLUMN dicta_recursado BOOLEAN DEFAULT NULL
```

### 2.2 `ScheduleValidationDB.dictado_count_at_validation: int`

Snapshot del set de dictados activos al momento de validar. Se usa para
detectar staleness: si los dictados cambian sin que cambie el cronograma,
la validación queda desactualizada.

### 2.3 Sin nuevas tablas

No se introdujeron tablas nuevas. El refactor reutiliza el modelo existente.

---

## 3. Cambios de servicio

### 3.1 `dictado_service.py` — nuevos helpers

| Función | Qué hace |
|---------|----------|
| `get_materias_esperadas_from_dictados(session, ciclo_id)` | Devuelve `{materia_codigo: nombre}` de dictados con `activo=True` linkeados al ciclo. **Es la fuente de verdad para prevalidación.** |
| `get_dictado_codigos_for_ciclo(session, ciclo_id, only_active)` | Devuelve `{materia_codigo: dictado_codigo}` para mostrar en faltantes |
| `count_active_dictados_for_ciclo(session, ciclo_id)` | Para el snapshot de staleness |
| `has_dictados_for_ciclo(session, ciclo_id)` | Pre-check: la prevalidación falla si no hay dictados creados |
| `recompute_activo_for_ciclo(session, ciclo_id, apply)` | Recalcula `activo` según reglas vigentes. Devuelve `RecomputeResult` con diff. `apply=False` solo preview, `apply=True` persiste |
| `set_activo_for_materias_in_ciclo(session, ciclo_id, materia_codigos, activo)` | Bulk update por código de materia. Si `activo=True` y no hay dictado, lo crea on-the-fly |
| `swap_plan_version_for_ciclo(session, ciclo_id, carrera_codigo, new_pv_id)` | Cambia la versión del plan asignada a una carrera para un ciclo. No toca dictados (queda para "Recalcular") |
| `get_drift_summary(session, ciclo_id)` | Diagnóstico completo: recompute pendiente, materias sin dictado, dictados huérfanos. Powers el indicador "⚠️ Cambios pendientes" |

### 3.2 Lógica nueva: `create_dictados_for_ciclo` ya no skipea

Antes: cuando la regla de recursado decía "no crear", la materia quedaba
**sin dictado** ("skipped_recursado"). Esto generaba un estado intermedio
("materia del plan sin dictado") que confundía la UX.

Ahora: **siempre se crea el dictado**. Si la regla dice "no dictar", se
crea con `activo=False`. El campo `created_inactive` del `DictadoCreationResult`
cuenta el subset.

Beneficio: simetría con el toggle del usuario. Activar y desactivar son
operaciones equivalentes (un toggle de `activo`), no implican creación/
borrado de filas.

### 3.3 `cronograma_validation_service.py`

- `_get_materias_esperadas` (privado, viejo) → reemplazado por
  `get_materias_esperadas_from_dictados` (delega).
- `_get_faltantes_por_carrera` ahora recibe `dictado_codigos` y la razón
  de cada faltante incluye el `dictado_codigo`.
- `validar_cronograma` aborta con `summary.error` si el ciclo no tiene
  dictados.
- `is_validation_stale` también detecta cambios en `dictado_count_at_validation`.

---

## 4. Cambios de UI

### 4.1 Pestaña Dictados (`app/pages/4_📆_Ciclos.py` → tab Dictados)

**Antes**: lista plana de dictados agrupados por carrera, con toggles
`activo`/`virtual` y un panel separado de "Materias sin dictado".

**Ahora**:

- **Mini-stats arriba**: 5 métricas (Carreras / Planes / Materias /
  Optativas / Override recursado).
- **Botones lado a lado**: ➕ Crear Dictados · 🔄 Recalcular según reglas.
- **Indicador de drift al lado del Recalcular**:
  - ✅ Si todo está alineado.
  - ⚠️ Si hay cambios: `🔄 N a recalcular · ➕ M sin dictado · 🗑️ K huérfano(s)`
    + popover "Ver detalle" con listas + botón "🗑️ Eliminar huérfanos".
- **Filtros**: buscador, estado (Activo/Inactivo), modalidad (Presencial/
  Virtual), año del plan, cuatri del plan, optativas (Incluir/Solo/Excluir).
- **Abrir/Cerrar todos** (botones).
- **Expander por carrera** con:
  - **⚙️ Configuración** (al inicio, en `st.container(border=True)`):
    - Toggle "Carrera dicta recursado" — edita `CarreraDB.dicta_recursado`
      globalmente. Toast + rerun.
    - Selectbox "Plan asignado al ciclo" — si hay >1 versión, permite
      swap. Llama a `swap_plan_version_for_ciclo`. Caption si hay 1 sola.
  - **Materias separadas en obligatorias / optativas** dentro del expander.
  - **Cada item de materia** tiene una columna "Recursado" con selectbox
    de 3 estados (`Según Carrera` / `Sí` / `No`) que persiste
    `MateriaDB.dicta_recursado` on-the-fly.
  - Toggles `Activo` y `Virtual` por dictado, batch-saved.

### 4.2 Pestaña Cronogramas → Validar (`src/ui/validacion_cronograma_tab.py`)

**Antes**: el resumen de cobertura listaba faltantes por carrera y "no
esperadas" como un bloque aparte al final.

**Ahora**:

- **Pre-check de dictados**: si el ciclo no tiene dictados creados, se
  muestra `st.error` rojo pidiendo ir a Ciclos → Dictados.
- **Toggle "Excluir virtuales y optativas del cómputo"** arriba del resumen
  → recalcula Esperadas/Cubiertas/Faltantes ignorando esas materias (con
  delta `−N virt/opt` para mostrar cuánto se quitó).
- **Faltantes y extras integradas por carrera**: el viejo bloque de
  "Materias no esperadas" desapareció. Cada expander de carrera muestra
  `📭 N faltantes · 📥 M no esperadas` y dentro tiene **dos tablas**
  (faltantes y extras) con columnas detalle (Optativa / Virtual / Anual /
  Dictado).
- **Edición on-the-fly de dictados desde la prevalidación**:
  - Multi-select "Desactivar dictados de:" debajo de la tabla de faltantes
    + botón ⚪ → bulk toggle a inactivo.
  - Multi-select "Activar dictados de:" debajo de la tabla de extras +
    botón 🟢 → bulk toggle a activo (crea dictado si falta).
  - Al aplicar, invalida el cache de prevalidación y rerun.

### 4.3 Página Materias

- En el editor inline, debajo del form auto-generado, **selectbox de 3
  estados** "Recursado (override por materia)" → `Según Carrera` /
  `Sí (override)` / `No (override)`. Persiste `MateriaDB.dicta_recursado`.

---

## 5. Scripts auxiliares

### 5.1 `scripts/mark_optativas_virtual.py`

One-shot que marcó **229 materias** y **156 dictados** existentes a
`virtual=True` (todas las optativas del catálogo). Tiene flag `--dry-run`.

Razón: en este uso académico, las optativas son virtuales por convención.
Antes había que tildarlas una por una.

---

## 6. Tests

- `tests/test_dictado_service.py` — 28 → 33 tests. Casos nuevos:
  - `test_creates_dictado_ignoring_recursado_skip` (override on-demand)
  - `test_materia_override_recursado_true_beats_carrera_false`
  - `test_materia_override_recursado_false_beats_carrera_true`
  - `TestRecomputeActivo` (preview + apply)
  - `TestSetActivoForMaterias` (deactivate/activate/idempotente)
- `tests/test_cronograma_validation_service.py` — nuevo, 5 tests:
  - sin dictados → error
  - esperadas solo activos
  - faltantes con dictado_codigo
  - staleness por cambio de entries
  - staleness por cambio de dictados activos

---

## 7. Flujo end-to-end resumido

1. **Crear ciclo** y asignar versiones de plan → CicloPlanVersionDB.
2. **Crear Dictados** (botón) → genera `DictadoDB` para cada materia del
   plan. Las que la regla dicta no recursar quedan inactivas.
3. **Configurar** desde Ciclos → Dictados:
   - Toggle por dictado individual (activo / virtual).
   - Toggle de carrera (`dicta_recursado` global) inline.
   - Override por materia (`dicta_recursado` selectbox) inline.
   - Swap de plan asignado a la carrera para este ciclo, inline.
4. Ver el indicador de drift (⚠️ N cambios pendientes) → 🔄 Recalcular →
   preview → Aplicar.
5. **Cargar cronograma** (Schedule).
6. **Prevalidar** desde Cronogramas → Validar:
   - Si faltan dictados, ajustar desde la prevalidación misma (botones
     bulk de activar/desactivar).
   - Toggle "excluir virtuales/optativas" para el cómputo realista.
7. (Próximo paso, fuera de alcance de esta sesión) **Generar plan**
   desde el Schedule prevalidado.

---

## 8. Trade-offs / decisiones

- **Global vs por-ciclo para `Carrera.dicta_recursado`**: elegimos global.
  Si fuera por-ciclo, requeriría una tabla `CicloCarreraConfigDB`. Scope creep.
- **Crear dictados inactivos vs no crear**: elegimos crear siempre. Más
  simple para la UI (toggle simétrico) y para el modelo de drift.
- **Recompute manual vs automático**: cuando el usuario toca config, no
  recalculamos automáticamente. Mostramos un indicador de drift y dejamos
  que el usuario apriete Recalcular cuando esté listo. Más transparente.
- **Override de materia gana sobre carrera**: alternativa era una
  combinación más compleja (ej: AND), pero "override gana" es más
  predecible y matchea cómo se piensa el dominio.

---

## 9. Referencias

- Modelo de datos: `project/1. Diseño/modelo-planificacion-cursada.md`
  (RN15, RN16 + tabla Dictado actualizada)
- Validaciones: `project/0. Planteo/plan-de-cursada.md` § 4.1
- Código:
  - `src/services/dictado_service.py`
  - `src/services/cronograma_validation_service.py`
  - `src/ui/validacion_cronograma_tab.py`
  - `app/pages/4_📆_Ciclos.py` (tab Dictados)
  - `app/pages/1_📚_Materias.py` (editor)
- Tests:
  - `tests/test_dictado_service.py`
  - `tests/test_cronograma_validation_service.py`
- Script:
  - `scripts/mark_optativas_virtual.py`
