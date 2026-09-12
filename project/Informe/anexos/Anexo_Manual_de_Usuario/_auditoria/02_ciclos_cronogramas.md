# Auditoría 02 — Ciclos, Cronogramas y Dictados

Alcance: pilar temporal del sistema (páginas `📆 Ciclos` y
`📅 Cronogramas`, más los servicios de `dictado`, `schedule` y
`cronograma_validation`). Fuente de verdad: código en `main` al
2026-07-30.

---

## 1. Modelo mental

### 1.1 Cadena de entidades

```
CicloDB (id="2026-1C")
  ├─ N:M ─ PlanCarreraVersionDB   via CicloPlanVersionDB
  │         └─ N ─ PlanEstudioDB (materia_codigo, anio_plan, cuatri_plan, optativa)
  │
  ├─ N:M ─ DictadoDB              via DictadoCicloDB
  │         └─ FK ─ MateriaDB
  │
  ├─ 1:N ─ ScheduleDB (cronograma)
  │         ├─ 1:N ─ ScheduleEntryDB
  │         │        ├─ FK ─ MateriaDB (codigo_materia)
  │         │        └─ FK opcional ─ ComisionDB (comision_id, schedule_id seteado)
  │         └─ 1:N ─ ComisionDB (template, schedule_id seteado, plan_cursada_id=NULL)
  │
  └─ 1:N ─ PlanificacionCursadaDB
            ├─ 1:N ─ ComisionDB (schedule_id=NULL, plan_cursada_id seteado)
            │         └─ 1:N ─ HorarioDB
            │                   └─ 1:N ─ ClaseDB
            └─ FK opcional ─ ScheduleDB (schedule origen)
```

### 1.2 Reglas de referencia clave

- `CicloDB.id` es una string estable con formato `"{anio}-{numero}C"`
  (ej. `"2026-1C"`). Se usa como natural key en todas las FK
  (`ScheduleDB.ciclo_id`, `PlanificacionCursadaDB.ciclo_id`, etc.).
- `DictadoDB` **no** tiene FK a ciclo; el link es via
  `DictadoCicloDB(dictado_id, ciclo_id)`. Es M:N porque un mismo
  dictado anual aparece linkeado al 1C y al 2C del mismo año
  (`_link_anual_dictado_2c`).
- `ScheduleDB.ciclo_id` es **opcional**: se pueden crear cronogramas
  "standalone" sin ciclo (útil para importar borradores). En la UI de
  Ciclos → Dictados sólo se validan cronogramas ya asociados a un
  ciclo.
- `ComisionDB` tiene **XOR** entre `schedule_id` y `plan_cursada_id`.
  No es constraint de DB (SQLite no lo soporta con OR); el
  `comision_service` lo valida en runtime al crear/actualizar.
  Semántica:
  - `schedule_id` seteado → "template" del cronograma. Los
    `ScheduleEntryDB.comision_id` apuntan acá.
  - `plan_cursada_id` seteado → entidad viva del plan. Los
    `HorarioDB.comision_id` apuntan acá. Al generar un plan desde un
    cronograma, las comisiones template se **clonan** (nuevos UUIDs)
    vía `clone_comisiones_for_plan`.
- `ScheduleEntryDB.comision_id` reemplaza al viejo `comision:int`. Es
  FK a `ComisionDB` (con `schedule_id` igual al del entry). Puede ser
  `NULL` — entry huérfano de comisión.
- `ScheduleEntryDB.virtual` es `Optional[bool]` de 3 estados
  (`None`/`True`/`False`). Al generar el plan se propaga a
  `HorarioDB.virtual` con la misma semántica de 3 estados.
- Cadena de resolución de `virtual` (regla "nivel más específico
  manda", en `resolucion_jerarquica.resolve_virtual`):
  `HorarioDB.virtual` → `DictadoDB.virtual` → `MateriaDB.virtual`
  (raíz, `bool` no-optional). `ScheduleEntryDB.virtual` se comporta
  como override a nivel `HorarioDB` cuando se genera el plan.
- Cadena de resolución de `dicta_recursado` (2 niveles):
  `MateriaDB.dicta_recursado` (Optional[bool]) →
  `CarreraDB.dicta_recursado` (bool raíz).

### 1.3 Semántica "existencia = activación"

Refactor documentado en `RECURSADO_Y_VIRTUAL.md`. `DictadoDB` **ya no
tiene** flag `activo`; la existencia de la fila (con su link
`DictadoCicloDB`) **es** la afirmación "esta materia se dicta en este
ciclo". Consecuencias:
- `create_dictados_for_ciclo` NO crea dictados que la regla de
  recursado dice omitir (antes los creaba con `activo=False`).
- Para "desactivar" un dictado hay que **borrarlo** con
  `borrar_dictado_de_ciclo`, que además nullifica
  `ClaseDB.dictado_id` para las clases huérfanas.
- Para "reactivar" hay que volver a crear la fila
  (`create_dictado_for_materia` o rerun de `create_dictados_for_ciclo`).

---

## 2. Walkthrough por página

### 2.1 📆 Ciclos — `app/pages/4_📆_Ciclos.py`

Dos tabs: **📋 Ciclos** y **📚 Dictados**. Selector de ciclo
compartido.

#### Tab "📋 Ciclos"

- **Sección "Ciclos Registrados"**: `st.dataframe` con ID, Año,
  Cuatrimestre, Inicio, Fin, Descripción; total al pie. Si no hay
  ciclos → `st.info("No hay ciclos registrados. Crea uno abajo.")`.
- **Sección "Eliminar Ciclo"**: selectbox de ciclos + botón
  "Eliminar" (type secondary). Ejecuta `_delete_ciclo_cascade` en
  cascada:
  1. `PlanificacionCursadaDB` → `ClaseDB` → `ComisionDB` +
     `HorarioDB` → plan.
  2. `ScheduleDB` → `ScheduleEntryDB` → schedule.
  3. `DictadoCicloDB` (bridges, no borra el `DictadoDB`).
  4. `CicloPlanVersionDB` (bridges).
  5. El `CicloDB`.

  Muestra `st.error(f"Error al eliminar: {e}")` si algo falla y
  `st.success(f"Ciclo {ciclo_delete} eliminado")` en el happy path.
- **Sección "Nuevo Ciclo"**: form con Año (2020-2100), Cuatrimestre
  (1C/2C), fecha inicio, fecha fin, descripción libre, y un
  **multiselect obligatorio** de "Versiones de plan a asignar" (por
  default marca la última versión de cada carrera). El ID del ciclo se
  autoderiva como `f"{anio}-{numero}C"`. Validaciones antes de
  guardar:
  - `fecha_fin <= fecha_inicio` → `st.error("La fecha de fin debe ser
    posterior a la de inicio")`.
  - `not selected_versions` → `st.error("Debe seleccionar al menos
    una version de plan")`.
  - Excepción al crear → `st.error(f"Error al crear ciclo: {e}")`.
  - Success → `st.success(f"Ciclo '{ciclo_id}' creado con
    {len(selected_versions)} version(es) de plan")`.

#### Tab "📚 Dictados"

Es la página más densa del sistema. Selector de ciclo
(`sel_ciclo_dictados`). Si el ciclo no tiene versiones de plan
asignadas → `st.warning("Este ciclo no tiene versiones de plan
asignadas. Los dictados no se pueden crear sin versiones
asignadas.")` + `st.stop()`.

Componentes en orden vertical:

1. **Métricas de configuración** (`Carreras`, `Planes`, `Materias`,
   `Optativas`, `Recursado fijado a mano`). Caption con warnings de
   carreras `no dicta recursado`, materias archivadas, etc.
2. **Botones de operación**:
   - `➕ Crear Dictados`: dispara `create_dictados_for_ciclo`.
   - `🔄 Sincronizar según reglas`: dispara
     `sync_dictados_para_ciclo(apply=False)` y guarda preview en
     `session_state["dict_sync_preview"]`.
   - Al lado, un mini-status:
     `✅ Dictados al día` o
     `⚠️ Divergencias: ➕ N sin dictado · 🗑️ N huérfano(s) · ⚠️ N
     existen pero la regla dice que no · Panel de gestión abajo ↓`.
   - **Guard**: si hay `dict_pending_count > 0` en session_state
     (toggles Virtual/Recursado sin aplicar), ambos botones se
     bloquean con `st.error("Tenés cambios pendientes sin aplicar...")`.
3. **Panel de divergencias** (`render_panel_divergencias`) — ver §3.4.
4. **Preview de sincronización** (si el usuario apretó Sincronizar):
   3 expanders (materias a crear, huérfanas a borrar, "existen pero la
   regla dice que no"), botón "Aplicar sincronización" (con guard
   `_n_changes == 0`) + "Cancelar".
5. **Métricas top** (`Dictados existentes`, `Virtuales (override)`,
   `Optativas`) + caption explicativa de la semántica nueva.
6. **Expander de ayuda "ℹ️ Cómo funciona esta página"**.
7. **Sección "Cambios pendientes"** (visible sólo si detecta diff en
   session_state) — ver §3.7.
8. **Filtros**: búsqueda por código/nombre, Estado (Con dictado / Sin
   dictado), Modalidad (Presencial / Virtual), Año del plan
   (multiselect), Cuatri del plan, Optativas (Incluir/Solo/Excluir).
9. **Botones "Abrir todos" / "Cerrar todos"** — settean
   `dict_force_open`.
10. **Expanders por carrera** — uno por cada carrera con materias
    **exclusivas** en el ciclo. Header:
    `🎓 {codigo} · {nombre} — N materia(s) (🟢 X con dictado · 🔘 Y
    sin dictado)`. Adentro:
    - Sub-container "⚙️ Configuración" (toggle
      `Carrera dicta recursado` + selector `Plan asignado al ciclo`
      si hay más de una versión disponible → dispara
      `swap_plan_version_for_ciclo`).
    - Split entre "Obligatorias" y "Optativas".
    - Cada fila renderea `_render_item`:
      `[info+badge][meta año/cuatri/h-sem][selector Recursado 3
      estados][🗑️ Borrar / ✅ Crear][selector Virtual 3 estados]`.
11. **Expander "🔗 Comunes"** — una única entrada por materia
    compartida entre 2+ carreras. Trae su propio multiselect de
    carreras (lógica O). Detalle en §4.2.

### 2.2 📅 Cronogramas — `app/pages/6_📅_Cronogramas.py`

Cinco tabs: **📋 Lista**, **📤 Cargar**, **👁 Visualizar**,
**✏️ Editar**, **✅ Validar**.

#### Tab "📋 Lista"

Un expander por cronograma con header:
`{nombre} — N entradas — ciclo upload: {ciclo_id|sin ciclo} —
{fecha_upload} — {badge}`.

Badges de validación (comparan contra `ScheduleValidationDB` más
reciente):
- `⚪ sin validar`.
- `🟡 validado vs {ciclo_id} pero modificado` (staleness — cambió el
  cronograma o el set de dictados del ciclo).
- `🔴 con issues vs {ciclo_id} (N faltantes, N part. infactibles)`.
- `🟢 validado vs {ciclo_id}`.

Adentro del expander:
- Text input para renombrar (Enter para guardar).
- `st.info`/`st.warning` con el resumen de la última validación
  (fecha, cobertura, breakdown de labs, partición).
- Duplicar: text input con nombre "(copia)" + botón `Duplicar` →
  `duplicate_schedule` (clona entries + comisiones del schedule).
- Eliminar: warning "Esta accion es irreversible." + botón `Eliminar`
  (type primary) → `delete_schedule` (borra entries y schedule, **no**
  toca comisiones).

#### Tab "📤 Cargar"

- Radio `Crear vacío` / `Cargar desde archivo`.
- Text input `Nombre del cronograma` (obligatorio).
- Selectbox `Ciclo (opcional)` con `(ninguno)` como default.
- Si "Cargar desde archivo": file uploader (CSV/XLSX/XLS) + botón
  `Crear cronograma` (deshabilitado sin nombre y sin archivo).
- Si "Crear vacío": info "Se creará un cronograma sin entradas..." +
  botón `Crear cronograma vacío` (deshabilitado sin nombre).

Errores/warnings de parseo se muestran fila por fila con `st.error` /
`st.warning`. Success: `st.success(f"Cronograma '{...}' creado con
N entradas.")`.

#### Tab "👁 Visualizar"

- Selectbox de cronogramas.
- Radio `Por grupo` / `Por materia`.
- **Por grupo**: 3 filtros obligatorios (Carrera, Año, Cuatrimestre)
  + filtros de "Tipo de materia" (Todas / Ciclo Básico F-FB /
  Específicas de carrera) + checkbox "Excluir materias comunes
  (multi-carrera)" + multiselect de materias. Renderea calendario
  read-only vía `render_schedule_calendar`.
- **Por materia**: buscador por código/nombre + selectbox +
  calendario filtrado a esa materia (`color_by_comision=True`).

#### Tab "✏️ Editar"

Muy similar al de Visualizar pero con calendario editable
(`render_editable_schedule_calendar`) que emite acciones `move` /
`click` / `select`:

- `move` (drag/resize) → `update_schedule_entry` con dia/hora nueva.
- `click` → abre `_dialog_edit_entry`: dialog con Materia (búsqueda +
  select), Día, Inicio, Fin, Comisión (con opción "➕ Crear nueva
  comisión…"), Tipo de clase (sin determinar / teorica /
  laboratorio), Virtual (Heredar / Sí / No). Botones Guardar /
  Eliminar / Cancelar.
- `select` (drag sobre vacío) → abre `_dialog_confirm_add`: dialog
  con materia+día+horas prefijados + input de Comisión numérica (0 =
  sin asignar) + Confirmar/Cancelar. Al confirmar con comisión ≠ 0
  llama a `get_or_create_comision_by_numero` (crea comisión template
  si no existe con ese número para la materia en ese cronograma).

**Modo "Por materia"** además tiene abajo del calendario:
- `st.data_editor` de todas las entries de la materia
  (autoguarda vía `on_change`), con columnas Día / Inicio / Fin /
  Comisión / Tipo / Virtual. Elegir "➕ Crear nueva comisión…" en la
  columna Comisión levanta un mini-form inline para completar los
  datos.
- `st.data_editor` de las comisiones template de la materia (N°,
  Nombre, Cupo, Carrera asignada, Descripción). Borrar una comisión
  está bloqueado si tiene entries u horarios asociados (`st.warning`
  al fondo con el motivo).
- Tabla resumen "Comisión / Clases / Horarios" por comisión.

#### Tab "✅ Validar"

Delega a `src/ui/validacion_cronograma_tab.py::render_tab` que:
1. Selectbox de ciclo + cronograma (persiste selección con
   `_persist_planes_ciclo_crono` / `_persist_planes_cronograma`).
2. Expander explicativo "¿Qué significa validar?".
3. Llama a `validation_ui.render_validation(source="schedule", ...)`.

El renderer unificado maneja:
- Toggle "Excluir optativas" + toggle "Auto-revalidar al cambiar" +
  botón "Validar cronograma".
- Toggle "Guardar cambios como copia del cronograma" (aplica edits del
  panel a una copia en lugar del original).
- 6 métricas de cobertura, breakdown de labs, partición teoría/lab.
- Expanders "Detalle por carrera" y "Detalle por materia" (con
  editor inline por materia, 10 checks estructurados y bulk actions
  de aceptar extras como dictados nuevos).

---

## 3. Operaciones importantes

### 3.1 Crear un ciclo nuevo

Ciclos → tab "Ciclos" → form "Nuevo Ciclo". No hay operación de clon
desde la UI — se hace por CLI (`scripts/clonar_ciclo_para_demo.py`).
El `id` del ciclo es la natural key derivada de año + cuatri;
**no se puede editar** después. Si ya existe uno con ese id, el
`ciclo_crud.create` va a fallar (excepción capturada como
`st.error`).

### 3.2 Activar/desactivar el dictado de una materia (semántica nueva)

- **Activar**: existencia = activación. Se crea el dictado con
  cualquiera de estos caminos:
  1. Botón `➕ Crear Dictados` a nivel ciclo (bulk):
     `create_dictados_for_ciclo` crea dictados para todas las
     materias del plan que la regla de recursado autoriza.
     Idempotente (skippea las que ya están).
  2. Panel de divergencias → fila "materia del plan sin dictado" →
     `✅ Crear`: `create_dictado_for_materia` (NO aplica el skip de
     recursado — decisión explícita del usuario).
  3. Botón `✅ Crear` inline en filas "Sin dictado" en la grilla de
     carrera. Registra la operación en el change log con
     `origin="ui:ciclos"` y razón que menciona "excepcional".
  4. Desde el panel de validación de cronograma: bulk action
     `🟢 Activar` sobre extras → `aceptar_materias_en_ciclo`. Opción
     `🌐 Activar y marcar virtual` setea también
     `DictadoDB.virtual=True`.
- **Desactivar**: `🗑️ Borrar` en la fila del dictado →
  `borrar_dictado_de_ciclo`. Efectos:
  - Borra el bridge `DictadoCicloDB` para ese ciclo.
  - Si no queda ningún bridge en otros ciclos (materia
    cuatrimestral típica), borra la fila `DictadoDB`.
  - Setea `ClaseDB.dictado_id=NULL` para las clases del plan que
    apuntaban al dictado (no las borra — permite trazabilidad).
  - Idempotente: si no hay bridge para el ciclo, devuelve
    `False`.

### 3.3 Crear un cronograma, importar horarios, editarlos

- **Crear vacío**: `create_empty_schedule(nombre, ciclo_id)`. El
  cronograma queda con 0 entries y 0 comisiones. Todo se agrega desde
  la tab Editar.
- **Cargar desde archivo**: `create_schedule_standalone` acepta
  CSV/XLSX/XLS. Usa `parse_horarios_file` que espera columnas
  (con aliases):
  - `codigo_materia` (o `codigo_plan`, `materia`, `cod_materia`).
  - `dia` (o `dia_semana`).
  - `hora_inicio` (o `hora_ingreso`, `inicio`).
  - `hora_fin` (o `hora_egreso`, `fin`).
  - `comision` (o `codigo_comision`, `comision_nombre`,
    `cod_comision`) — opcional, y **actualmente ignorado** al crear
    entries (mira solo `codigo_materia/dia/inicio/fin`, no persiste
    `comision_id`). Ver §7.
  - Resolución de código de materia vía `_resolve_materia_code` con
    fallback a `codigo_guarani` (emite warning por fila).
- **Editar**: cada acción del calendario dispara una mutación
  atómica en DB. El `data_editor` autoguarda `on_change`. Los toasts
  aparecen en el próximo run.

### 3.4 Panel de divergencias

Componente en `src/ui/divergencias_panel.py`. Aparece **siempre** en
Ciclos → Dictados (dentro de un container con borde); si no hay
divergencias muestra el banner verde
"✅ No hay divergencias: los dictados del ciclo están alineados con
las reglas vigentes.".

Cuando sí hay divergencias, arriba muestra el header
`⚠️ Divergencias: N a crear · N a borrar · N existen pero la regla
dice que no` y un botón `⚡ Aplicar todo (N cambios)` que ejecuta
`sync_dictados_para_ciclo(apply=True)` (NO toca la sección
`rule_says_skip_but_exists`).

Tres secciones en expanders:

- **➕ Materias del plan sin dictado**: la materia está en el plan y
  la regla dice que debería tener dictado, pero no lo tiene.
  Acciones fila:
  - `✅ Crear`: `create_dictado_for_materia`.
  - `⏭️ Omitir en regla`: `promover_a_regla(accion="omitir-en-regla")`
    (setea `MateriaDB.dicta_recursado=False` — afecta ciclos
    futuros, NO crea nada en el actual).
  - Bulk: `⏭️ Omitir TODAS en regla (N)` con confirmación en 2
    pasos.
- **🗑️ Dictados huérfanos**: el dictado existe pero la materia ya no
  está en el plan del ciclo (típico tras un `swap_plan_version_for_ciclo`).
  Acción única: `🗑️ Borrar` → `borrar_dictado_de_ciclo`.
- **⚠️ Existen pero la regla dice que no**: el dictado existe pero
  las reglas actuales dicen que no debería. **No se borra
  automáticamente** — decisión explícita del usuario:
  - `🗑️ Borrar` (si fue error).
  - `⬆️ Promover a regla`: `promover_a_regla(accion="crear-en-regla")`
    (setea `MateriaDB.dicta_recursado=True`).
  - Bulk: `⬆️ Promover TODAS a regla (N)`.

Todas las acciones envuelven en `change_context(origin="ui:ciclos",
reason=...)` para dejar el rastro en el change log.

### 3.5 Validación del cronograma

`cronograma_validation_service.validar_cronograma(schedule_id,
ciclo_id, exclude_optativas)`:

- **Pre-check**: si el ciclo no tiene ningún dictado
  (`has_dictados_for_ciclo`) →
  `summary.error = "Este ciclo no tiene dictados creados..."` y
  return.
- **Set de "materias esperadas"** =
  `get_materias_esperadas_from_dictados(session, ciclo_id)` (todos
  los dictados linkeados al ciclo). Si `exclude_optativas=True`, se
  descartan las optativas del set esperado **y** del set de extras
  (simetría).
- **Métricas computadas**:
  - `n_materias`, `n_clases`, `total_horas` (suma de `hora_fin −
    hora_inicio` en horas).
  - `n_esperadas`, `n_cubiertas`, `n_faltantes`, `n_extra`.
  - `n_con_lab_asignado`, `n_lab_fijo`, `n_lab_reserva`,
    `n_lab_pendiente` (via `_compute_lab_breakdown` con
    `MateriaLaboratorioDB`).
  - `particion_valid`, `particion_n_infactibles`,
    `particion_message`, `particion_details` (via
    `validar_factibilidad_particion_horas`).
  - `n_conflictos_horarios` (via
    `validar_conflictos_horarios_cronograma`).
  - Detalles: `faltantes_por_carrera` (agrupado por carrera/plan,
    con año/cuatri/optativa/período/horas/virtual/dictado_codigo/
    razón textual "Dictado activo X sin horarios cargados"),
    `extras`, `esperadas`, `mat_map`.

Persistencia: `persist_validation` inserta un
`ScheduleValidationDB` (snapshot histórico). Cada validación es
inmutable — la staleness se detecta comparando conteos de entries y
dictados al momento de validar contra los actuales
(`is_validation_stale`).

**Qué se puede "ignorar"**: a nivel cronograma solamente se pueden
aceptar extras como dictados nuevos (bulk action `🟢 Activar` /
`🌐 Activar y marcar virtual` desde el panel). Los faltantes no se
ignoran — se corrigen agregando entries o borrando dictados. La
funcionalidad de "ignorar conflictos" existe pero es sólo del panel
de plan (`IgnoredConflictDB`), no del cronograma.

### 3.6 Marcar virtual (jerarquía RF-DICT-09/10)

Tres puntos de override, aplicando "nivel más específico manda":

1. **Nivel materia** (raíz): `MateriaDB.virtual: bool` (default
   `False`). Se edita desde la página de Materias.
2. **Nivel dictado** (override por ciclo): `DictadoDB.virtual:
   Optional[bool]` (default `None` = heredar). Se edita desde Ciclos
   → Dictados → selector "Virtual" de 3 estados (`Heredar` /
   `Virtual` / `Presencial`). Los cambios entran al batch "Cambios
   pendientes" — se aplican con "💾 Aplicar cambios".
3. **Nivel horario** (override por slot):
   - En un cronograma: `ScheduleEntryDB.virtual: Optional[bool]` —
     editable desde el dialog de editar entry o desde el
     `data_editor` de "Por materia".
   - En un plan generado: `HorarioDB.virtual: Optional[bool]` —
     editable desde el editor de horarios del plan
     (`schedule_materia_editor`).

Resolución final: `resolve_virtual(horario, dictado, materia) -> bool`.
El primer no-`None` de la cadena manda.

**Efectos**: cuando el horario resuelto es virtual, el LP de
asignación de aulas lo ignora (no consume aula, no entra en grupos
de simultaneidad), el cronograma lo marca con `🌐 virtual`, y la
prevalidación lo cuenta como cubierto.

### 3.7 Batch "Cambios pendientes" (Virtual + Recursado)

Los selectores `Virtual` y `Recursado` en la grilla de Dictados
**no commitean al instante**: escriben a `session_state[
f"virtual_{ns}_{carrera}_{dictado_id}"]` y `session_state[
f"rec_mat_{ns}_{carrera}_{materia_codigo}"]`.

`_detectar_pendientes()` compara session_state vs DB en cada render y
levanta el bloque "⏳ Cambios pendientes (N)":
- Tabla con Materia, Atributo (Recursado / Virtual), Actual, Nuevo.
- Botón `💾 Aplicar N cambio(s)` → actualiza todo en una sola
  session, marca `dict_resync_pending=True`.
- Botón `🚫 Descartar cambios` → limpia las keys de session_state.

**Guard**: mientras haya pendientes, los botones `➕ Crear Dictados`
y `🔄 Sincronizar según reglas` quedan bloqueados con `st.error`.

Racional del batch: Streamlit interrumpe reruns cuando el usuario
hace clicks rápidos consecutivos, lo que cancelaba commits
intermedios y "perdía" cambios. El batch garantiza una única
transacción determinística.

**Resync de session_state tras bulk ops**: `dict_resync_pending`
levantado por operaciones bulk (Recalcular, Crear Dictados, aceptar
extras desde Validación) invalida el session_state de los toggles
para que el próximo render lea de DB (evita "stuck values" en toggles
después de bulk ops).

### 3.8 Clonar ciclo para demo

Script CLI: `python -m scripts.clonar_ciclo_para_demo --ciclo-id
2026-1C [--sufijo demo-saturacion] [--dry-run]`.

Genera un `CicloDB` con id `{ciclo}-{sufijo}` que clona:
- `CicloDB` (fechas iguales, descripción marcada `[CASO EJEMPLO DE
  SATURACION — clonado ...]`).
- `DictadoDB` (nuevos UUIDs, mismo `materia_codigo`, preserva
  `virtual` actual).
- `DictadoCicloDB` bridges apuntando al nuevo ciclo.
- `PlanificacionCursadaDB` (nuevo UUID, `activo=False`, nombre
  `(demo)`; conserva FK al `schedule_id` original).
- `ComisionDB` del plan → rewire de `plan_cursada_id` y
  `dictado_id`.
- `HorarioDB` (con sufijo en el id para trazabilidad) → rewire de
  `comision_id`. Preserva `aula_id` del patrón y `tipo_clase`.
  **NO** clona `virtual` — ver §6 (discrepancia).
- `ClaseDB` → rewire completo, preserva `aula_id`,
  `aula_asignada_manualmente`, `executed`.
- `LPRunDB` → rewire de `plan_cursada_id` + reescritura del
  `details_json` para que los `horario_id` apunten a los clonados.
- `MateriaForecastConfigDB` e `IgnoredConflictDB` → rewire.

**No clona**: `PlanValidationDB`, `ScheduleDB` /
`ScheduleEntryDB` / `ScheduleValidationDB`, catálogos
(`MateriaDB`, `CarreraDB`, `AulaDB`, `SedeDB`, `PlanEstudioDB`,
`CarreraSedeDB`, `PlanCarreraVersionDB`, `CicloPlanVersionDB`,
`MateriaLaboratorioDB`, `InscripcionHistoricaDB`).

Precondiciones: `--sufijo` no debe colisionar (chequea que el nuevo
id no exista, si no error). Al terminar, `engine.dispose()` para
que sesiones cacheadas vean el ciclo nuevo.

### 3.9 Swap de versión de plan por carrera dentro del ciclo

Botón `Plan asignado al ciclo` dentro del expander de cada carrera
(sólo si `len(_avail) > 1`). Ejecuta
`swap_plan_version_for_ciclo(session, ciclo_id, carrera, new_pv)`:
- Valida que la nueva PV pertenezca a la carrera indicada.
- Borra los `CicloPlanVersionDB` de la carrera para ese ciclo.
- Crea un nuevo bridge apuntando a la nueva PV.
- **No toca dictados existentes** — el usuario tiene que apretar
  "🔄 Sincronizar según reglas" para alinear (los que ya no están en
  el plan nuevo aparecerán como `to_delete` = huérfanos).

Emite un `st.toast("Plan de {carrera} cambiado. Apretá 🔄
Recalcular arriba.")`.

---

## 4. Gotchas y cosas no obvias

### 4.1 Borrar un cronograma que ya tiene plan derivado

`delete_schedule` borra `ScheduleEntryDB` y `ScheduleDB` **pero no
las comisiones template** con `schedule_id` igual. Tampoco toca al
`PlanificacionCursadaDB` que hereda `schedule_id` como referencia
histórica — el plan queda apuntando a un schedule inexistente
(dangling FK). No hay validación previa: si borrás un schedule con
plan derivado, el plan sigue vivo pero pierde su ancla.

Adicionalmente, las comisiones template quedan huérfanas (con
`schedule_id` apuntando a un id inexistente). Como el
`comision_service` filtra por `schedule_id` seteado, no aparecen en
ningún listado — sólo con un query directo.

### 4.2 Materias compartidas — un solo DictadoDB, un solo widget

Cada `DictadoDB` se renderea **una única vez por run**, aunque la
materia aparezca en 2+ carreras del ciclo. Las exclusivas van en el
expander de su carrera; las compartidas van al expander "🔗 Comunes"
al final. Los toggles Virtual y Recursado en Comunes afectan a
todas las carreras donde la materia aparece (los flags viven en
`DictadoDB`/`MateriaDB`, no por carrera).

Racional: antes se renderizaba la misma materia en cada carrera con
keys distintas apuntando al mismo dictado — race conditions y
"cambios perdidos" al autoguardar.

### 4.3 Editar una `ScheduleEntry` y su comisión

- `update_schedule_entry` acepta cambios en `codigo_materia`, `dia`,
  `hora_inicio`, `hora_fin`, `comision_id`, `tipo_clase`, `virtual`.
- Si cambiás la comisión de un entry, la comisión anterior queda
  vacía (sin entries) pero sigue viva como template. El
  `data_editor` de comisiones permite borrarla explícitamente si no
  tiene entries ni horarios.
- Si borrás una comisión que tiene entries u horarios,
  `delete_comision` devuelve `ok=False` con mensaje en `.errores`.
  El data_editor no revierte el borrado (queda inconsistente en la
  UI hasta el siguiente rerun), pero el warning aparece al fondo con
  `st.warning`.

### 4.4 Promoción a regla — sólo cambia catálogo

`promover_a_regla` **NO** modifica el estado actual de ningún
dictado: sólo cambia `MateriaDB.dicta_recursado`. La sincronización
del ciclo actual sigue siendo decisión explícita del usuario (apretar
Sincronizar y aplicar).

Además, `promover_a_regla` termina con `engine.dispose()` para
invalidar el pool. Sin esto, otras sesiones abiertas (el próximo
render de Streamlit típicamente) leían `dicta_recursado` stale y el
selectbox detectaba un falso "cambio pendiente".

### 4.5 Efectos del audit log

- Cada mutación de las entidades trackeadas (`TRACKED_ENTITIES`
  incluye `MateriaDB`, `CarreraDB`, `DictadoDB`, `DictadoCicloDB`,
  `SedeDB`) inserta una fila en `ChangeLogDB` via hooks
  `after_insert/update/delete` de SQLAlchemy.
- `change_context(origin, reason)` es un context manager que
  propaga origen/razón a los hooks. Las UI de ciclo usan
  `origin="ui:ciclos"`; las bulk actions de validación,
  `"ui:validacion"`.
- Entidades **no trackeadas**: `HorarioDB`, `ComisionDB`, `ClaseDB`,
  `ScheduleEntryDB`. Son datos de operación, no política.

### 4.6 Override de sede por comisión

`ComisionDB.carrera_asignada: Optional[str]` sobrescribe la
restricción de sede del LP a nivel comisión. Uso típico: una
comisión de una materia común que se organiza para alumnos de una
carrera puntual (ej. una comisión de "Análisis I" para alumnos de
Electrónica que se dicta en la sede de Electrónica). Se edita:
- Al crear la comisión (dialog "➕ Crear nueva comisión…" o
  `create_comision_for_schedule(..., carrera_asignada=...)`).
- Desde el `data_editor` de comisiones en el tab Editar (columna
  "Carrera asignada").

Comportamiento del LP: si `carrera_asignada` es no-`None`, restringe
la sede del aula asignada a las sedes de esa carrera (vía
`CarreraSedeDB`), aunque la materia sea común y por default iría a
la sede default de comunes (`SedeDB.es_default_comunes=True`).

### 4.7 Sincronizar según reglas — modo preview + apply

`sync_dictados_para_ciclo(apply=False)` es un preview puro; devuelve
`SyncResult` con las 3 listas. La UI de Sincronizar guarda el
preview en `session_state["dict_sync_preview"]` y muestra un botón
`Aplicar sincronización` que corre `sync_dictados_para_ciclo(apply=True)`.
El botón `⚡ Aplicar todo` del panel de divergencias hace lo mismo
en un solo paso.

`sync(apply=True)` **crea** `to_create` y **borra** `to_delete`
(bridge + fila si es el único ciclo, nullificando clases). NUNCA
toca `rule_says_skip_but_exists`.

### 4.8 Anuales — mismo DictadoDB en 1C y 2C

Una materia con `periodo="anual"` genera **un solo `DictadoDB`**
(`dictado_codigo = f"{materia}-{anio}"`) que se linkea al ciclo 1C
con `fin_dictado=None` y luego al ciclo 2C setándole `fin_dictado`.
`create_dictados_for_ciclo` sobre el 2C busca el dictado anual del
mismo año y linkea sin duplicar. Si no encuentra el del 1C (raro),
crea uno fresh para el 2C.

Al borrar el dictado desde 2C, el bridge del 2C se borra pero el
bridge del 1C queda vivo (por eso `borrar_dictado_de_ciclo` sólo
borra la fila `DictadoDB` "si no queda ningún bridge en otros
ciclos").

---

## 5. Errores y warnings visibles al usuario

### 5.1 Página Ciclos

- `st.info("No hay ciclos registrados. Crea uno abajo.")`
- `st.warning("No hay versiones de plan disponibles. Cree planes de
  estudio primero.")`
- `st.error("La fecha de fin debe ser posterior a la de inicio")`
- `st.error("Debe seleccionar al menos una version de plan")`
- `st.success("Ciclo '{ciclo_id}' creado con N version(es) de plan")`
- `st.error("Error al crear ciclo: {e}")`
- `st.success("Ciclo {ciclo_delete} eliminado")`
- `st.error("Error al eliminar: {e}")`
- `st.info("Crea un ciclo primero en la pestana 'Ciclos'.")`
- `st.warning("Este ciclo no tiene versiones de plan asignadas. Los
  dictados no se pueden crear sin versiones asignadas.")`
- `st.success("✅ Dictados al día con la configuración.")`
- `st.warning("⚠️ Divergencias: ... · Panel de gestión abajo ↓")`
- `st.error("Tenés cambios pendientes sin aplicar. Apretá 💾 Aplicar
  cambios abajo o 🚫 Descartar antes de crear/sincronizar
  dictados.")`
- `st.success("Dictados: N creados, N vinculados (anuales), N ya
  existentes, N omitidos por recursado")`
- `st.info("Los dictados del ciclo ya están alineados.")`
- `st.info("Asigne versiones de plan al ciclo para gestionar
  dictados.")`
- `st.info("Las versiones de plan asignadas a este ciclo no tienen
  materias cargadas. Cargá los planes de estudio primero.")`
- `st.error("No se pudo crear el dictado. Verificá que la materia
  esté en el plan asignado al ciclo.")`
- Toasts: `🗑️ Dictado borrado: {codigo}`,
  `✅ Dictado creado: {codigo}`, `✅ N cambio(s) aplicados.`,
  `Cambios descartados.`, `{codigo}: dicta_recursado = Sí/No`,
  `Plan de {carrera} cambiado. Apretá 🔄 Recalcular arriba.`.
- Panel de divergencias: `st.success("✅ No hay divergencias...")`,
  `st.warning("⚠️ Vas a modificar la regla de recursado de N
  materia(s) del catálogo. Esto **afecta todos los ciclos
  futuros**...")`.

### 5.2 Página Cronogramas

- `st.info("No hay cronogramas cargados. Usa la pestana 'Cargar'
  para subir uno.")`
- `st.info("No hay cronogramas para visualizar.")` / `"...para
  editar."`.
- `st.info("Se creará un cronograma sin entradas. Podés agregar
  horarios desde la pestaña Editar.")`
- `st.error("Ciclo '{ciclo_id}' no encontrado")`
- `st.error("No se encontraron horarios validos en el archivo")`
- `st.error("Formato no soportado: {name}. Use CSV o Excel
  (.xlsx)")`
- `st.error("Error leyendo archivo: {e}")`
- `st.error("Columnas faltantes: ...")`
- `st.error("Fila {N}: codigo_materia vacio")`
- `st.error("Fila {N}: Materia '{codigo}' no existe")`
- `st.warning("Fila {N}: Codigo '{original}' resuelto via
  codigo_guarani -> '{resolved}'")`
- `st.success("Cronograma '{nombre}' creado con N entradas.")`
- `st.success("Cronograma duplicado como '{nombre}'")`
- `st.success("Cronograma eliminado")`
- `st.warning("Esta accion es irreversible.")` (delete)
- `st.warning("No se encontraron materias para '{busqueda}'")`
- `st.info("No hay materias disponibles con los filtros actuales.")`
- Toasts de edición: "{mat} movida a {dia} HH:MM-HH:MM",
  "{mat} agregada: ...", "{mat} actualizada: ...", "{mat} eliminada
  ({dia} HH:MM-HH:MM)", "Sin cambios", "N modificada(s), N
  agregada(s), N eliminada(s)", "N comisión(es) actualizada(s), N
  borrada(s)".
- Warnings al borrar comisión: "No se puede borrar: la comisión
  tiene entries asociadas en el cronograma. Reasignalos o borrá las
  entries primero." / "...horarios asociados en el plan..."

### 5.3 Validación de cronograma

- `st.error("Este ciclo no tiene dictados creados. Ir a Ciclos →
  📚 Dictados y apretar 'Crear Dictados' antes de prevalidar.")`
- `st.info("Apretá **Validar cronograma** para correr la validación
  completa (cobertura, conflictos, partición teoría/lab).")`
- `st.warning("El cronograma, sus dictados o el toggle cambiaron
  desde la última validación. Apretá **Validar cronograma** para
  actualizar.")`
- `st.success(particion_message or "Partición teoría/lab OK.")`
- `st.error(particion_message or "Partición teoría/lab inválida.")`
- `st.info("No hay ciclos registrados. Crear uno en la pagina de
  Ciclos antes de validar cronogramas.")`
- `st.info("No hay cronogramas cargados para este ciclo.")`

---

## 6. Discrepancias con docs

Comparación con `project/2. Desarrollo/WORKFLOW.md` y
`project/2. Desarrollo/RECURSADO_Y_VIRTUAL.md`.

### 6.1 "Toggle Activo" — texto legacy en WORKFLOW.md §3.3

WORKFLOW.md §3.3 "Recalcular según reglas" describe todavía **tres
secciones del preview**: `🟢 Pasarán a Activo`, `⚪ Pasarán a
Inactivo`, `✋ Editados a mano (respetados)`, y un toggle "Pisar
también las ediciones manuales". Nada de esto existe hoy en el
código. El preview real (`sync_dictados_para_ciclo`) muestra
`to_create` (crear), `to_delete` (borrar huérfanos) y
`rule_says_skip_but_exists` (nunca se toca).

También §3.4 dice que los dictados nuevos "heredan `virtual=False`
(presencial) por default, salvo que la materia sea virtual de
catálogo, en cuyo caso heredan True". El código actual siempre
setea `virtual=None` en `_create_cuatrimestral_dictado`,
`_create_anual_dictado_1c` y `_link_anual_dictado_2c`, que **hereda**
de la materia via `resolve_virtual`. No se persiste `True` en el
catálogo virtual — se deja `None` y se resuelve dinámicamente.

### 6.2 Botón "🌐 Activar y marcar virtual" en Ciclos

WORKFLOW.md §3.4 sugiere que la marca virtual se hace toggleando
desde Ciclos. En la práctica también se hace desde el panel de
validación de cronograma con bulk action `🌐 Activar y marcar
virtual`; esto usa `aceptar_materias_en_ciclo(marcar_virtual=True)`.
No hay doc explícita del path completo.

### 6.3 Cronograma sin ciclo (`ciclo_id=None`)

`ScheduleDB.ciclo_id` es opcional (`Optional[str]`). El código lo
soporta explícitamente (`create_empty_schedule` y
`create_schedule_standalone` aceptan `ciclo_id=None`). WORKFLOW.md
§4 no menciona este modo standalone — asume que todo cronograma
pertenece a un ciclo. La tab Validar sólo funciona con cronogramas
asociados a un ciclo (el selector en `validacion_cronograma_tab`
filtra por `get_schedules_for_ciclo`).

### 6.4 Import de horarios — columna `comision` ignorada

`parse_horarios_file` acepta la columna `comision`, pero
`create_schedule_from_file` y `create_schedule_standalone` **no la
usan** al crear `ScheduleEntryDB` — sólo persisten
`codigo_materia/dia/hora_inicio/hora_fin`. Es decir, el número de
comisión del archivo original **no se preserva**. Para asociar
entries a comisiones hay que hacerlo manualmente desde la tab
Editar. Discrepancia con la promesa implícita del schema.

### 6.5 Clon de ciclo no clona `virtual` de horarios

`scripts/clonar_ciclo_para_demo.py` en el paso 6 (HorarioDB) crea
las filas clonadas **sin pasar el campo `virtual`**. Con la
refactor RF-DICT-09/10, `HorarioDB.virtual` existe como Optional[bool]
y es semánticamente relevante. Al clonar, los horarios nuevos
quedan con `virtual=None` (default), aunque el original tuviera
`virtual=True/False`. Similar comentario para `ScheduleEntryDB` (que
el script no clona en absoluto — deja apuntando al schedule
original). Ver también §7.

### 6.6 "Toggle Activo" en helper `_render_item`

El código de `_render_item` menciona `col_activo` como "columna que
se re-usa como acción `🗑️ Borrar dictado`" (comentario). El nombre
del identificador es legacy y confunde: no es un toggle de activar,
es un botón de borrar. Similar `col_virtual` que es el selectbox.

### 6.7 WORKFLOW.md §3.3 menciona `activo_override_manual`

`RECURSADO_Y_VIRTUAL.md` §1 explicita que `activo_override_manual`
fue eliminado. Pero WORKFLOW.md §3.3 sigue mencionándolo. Los dos
docs no están sincronizados entre sí.

---

## 7. Preguntas abiertas

1. **Comisiones huérfanas tras `delete_schedule`**: si borrás un
   cronograma con comisiones template, esas quedan vivas con FK
   dangling. ¿Se limpian por algún cron? ¿Se hace validación al
   crear el próximo cronograma? No aparece cleanup explícito.

2. **`ScheduleEntry.virtual` en clon de ciclo**: el script de clon
   no toca cronogramas (deja apuntando al `schedule_id` original).
   Los planes clonados heredan referencia al schedule viejo. ¿Es
   deseado? El script dice "cronogramas son inmutables" pero la
   práctica es que se editan.

3. **Import desde archivo — parseo de `comision`**: hay `has_comision =
   "comision" in df.columns` en el parser, se lee la columna, se
   asigna a `HorarioInput.comision_nombre`… pero luego
   `create_schedule_standalone` ignora ese campo. ¿Es intencional?
   ¿O falta el wiring para persistir la comisión?

4. **Formato de fecha en el ID del ciclo**: si querés crear un
   ciclo `2026-3C` (cuatrimestre 3), el schema no lo permite
   (`numero: int = Field(ge=1, le=2)`). ¿Cómo se modelaría un
   trimestre o un cursillo especial? Actualmente sólo 1C/2C.

5. **`fecha_inicio` / `fecha_fin` del ciclo vs `inicio_dictado` /
   `fin_dictado` del dictado**: al crear el dictado, se copian las
   fechas del ciclo. Si después se editan las fechas del ciclo, los
   dictados quedan con las fechas viejas. ¿Se propaga? El código
   no hace propagación explícita.

6. **`get_or_create_comision_by_numero`**: se usa en el
   `_dialog_confirm_add` cuando se agrega una entry con número de
   comisión ≠ 0. Si ya existe una comisión con ese número para la
   materia en ese cronograma, la reusa; si no, crea una nueva con
   defaults (cupo 30, nombre auto). ¿El usuario sabe que este
   dialog puede crear comisiones de silente?

7. **Race condition en swap de plan version**: `swap_plan_version_for_ciclo`
   borra los bridges y crea uno nuevo, pero no está en una
   transacción explícita (usa el `.commit()` del session). Si dos
   sesiones lo corren simultáneamente para la misma
   (ciclo, carrera), ¿queda consistente?

8. **Validación de partición teoría/lab**: se usa
   `validar_factibilidad_particion_horas` — no auditamos su lógica
   acá. Es potencialmente confusa para el usuario (`particion_message`
   es texto libre desde el service).

9. **`ScheduleValidationDB.excluir_virtuales_optativas` vs
   `excluir_optativas`**: el modelo tiene ambas columnas.
   `excluir_virtuales_optativas` es "legacy" según el comentario;
   se guarda como mirror del nuevo `excluir_optativas`. ¿Por qué no
   se dropeó de una? Los snapshots históricos anteriores al refactor
   quedan con el viejo formato pero al leerse, ¿se prioriza cuál?
