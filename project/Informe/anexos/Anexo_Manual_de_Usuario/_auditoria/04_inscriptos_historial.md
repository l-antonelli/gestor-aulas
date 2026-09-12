# Auditoría — Inscriptos + Historial

> Fuente exclusiva: código en `app/pages/`, `src/services/`, `src/database/`,
> `scripts/`. Este documento describe qué hacen los módulos **hoy**, no lo
> que debieran hacer. Toda referencia a comportamiento está anclada a
> archivos + líneas.

---

## 1. Inscriptos

### 1.1 Propósito

La página `app/pages/7_📈_Inscriptos.py` (título en la UI: **📈 Inscriptos
Históricos**) es un **editor CRUD** sobre la tabla
`InscripcionHistoricaDB` (`src/database/models.py:597-604`).

Cada fila representa: **(materia, año, cuatrimestre) → cantidad de
inscriptos**. PK compuesta: `materia_codigo` (FK a `materias.codigo`) +
`anio` (int) + `cuatrimestre` (`"1C" | "2C" | "Anual"`). Único campo de
datos: `inscriptos: int (ge=0)`.

No es un módulo de "proyección" en sí — la proyección la calcula
`src/services/forecast_service.py` a partir de estos datos. Esta página
sirve para:

1. Ver la serie histórica que alimenta al forecast.
2. Editar / corregir / cargar a mano registros faltantes.
3. Comparar los tres métodos de forecast (`media_movil`, `drift`, `ses`)
   como referencia. La elección del método aplicado a la asignación se
   configura desde `📊 Planes → Detalle`, no acá (caption línea 271-276).
4. Asociar códigos del Excel de inscriptos que no matchearon
   automáticamente contra la DB.

### 1.2 Origen de los datos — carga inicial

**Fuente**: `data/input/inscriptos/final_df.xlsx` (columnas `codigo`,
`actividad`, `year`, `period`, `cant._inscriptos`).

**Script**: `scripts/load_inscriptos.py` — se corre desde CLI:

```bash
python -m scripts.load_inscriptos [--reset]
```

- `--reset` vacía `inscripciones_historicas` antes de insertar
  (`load_inscriptos:172-176`).
- Sin `--reset` hace upsert por PK: si existe, pisa `inscriptos`; si no,
  inserta (`load_inscriptos:186-198`).
- Es un script **manual** — no hay atajo desde la UI. La página tampoco
  ofrece "cargar Excel", solo consume el archivo si sigue existiendo en
  `data/input/inscriptos/final_df.xlsx` para armar la sección "sin
  matchear".

**Matcheo código-inscripto → código-materia** (`load_inscriptos:55-139`):

Estrategia en 3 capas, sin fallback entre carreras distintas:

1. **Match directo** por `codigo` idéntico.
2. **Normalización por formato** de código, con reglas hardcodeadas por
   carrera (`_normalize_code:55-85`):
   - TUIA: `IA11 → IA 1.1`
   - Prof. Física: `PF14 → PF1.4`
   - Lic. Física: `F1801 → LF1`
   - Lic. Matemática: `L1801 → LM1`
   - Prof. Matemática: `P1801 → PM1`
3. **Match por nombre dentro de misma carrera**: LCC `T10xx → R-xxx` y
   curso de ingreso `CI24xx → CE` (usa `_build_name_map`).
4. **Tabla hardcodeada** `_HARDCODED_MAP` (`load_inscriptos:41-52`) para
   typos ("Algebra" vs "Álgebra", "del Software" vs "de Software", etc.).

Antes de insertar, se agrega por `(db_codigo, year, period)` sumando
`cant._inscriptos` — cubre el caso donde varios códigos del Excel
mapean a la misma materia (`load_inscriptos:160-167`).

### 1.3 Carga manual desde la UI

Además del script CLI, la página permite editar/agregar datos in-place
en tres flujos:

#### 1.3.1 Editar materias con datos

Sección **"Materias con datos"** (`7_📈_Inscriptos.py:454-475`). Cada
materia aparece como expander (`_render_materia_expander:126`) con un
`st.data_editor` de columnas `Año / Cuatrimestre / Inscriptos`.

Guardado (`:180-196`): **borra TODAS las filas** de la materia y las
reescribe con lo del editor. Es idempotente contra edición pero no
preserva filas invisibles por filtro de cuatri — filtrar por `1C` y
guardar no borra las `2C` porque los `records` que se pasan son sin
filtrar (`_render_materia_expander` recibe `records` completo y filtra
solo para display).

**Gotcha**: la columna `Cuatrimestre` es un selectbox con opciones
`["1C", "2C", "Anual"]` pero el filtro superior solo ofrece
`["Todos", "1C", "2C"]` — no hay filtro directo para ver "solo Anuales".

#### 1.3.2 Materias sin datos

Sección **"Materias sin datos de inscriptos"** (`:481-538`). Lista las
materias de `MateriaDB` que no tienen ninguna fila en
`InscripcionHistoricaDB`. Muestra un editor vacío para agregar registros
nuevos. Botón "Guardar" hace `INSERT` de las filas no nulas.

#### 1.3.3 Sin matchear

Sección **"Sin matchear"** (`:544-628`). Lista códigos del Excel
`final_df.xlsx` que **no** pudieron asociarse contra `MateriaDB` cuando
la página se abre. Recomputa el matcheo en vivo (`:79-120`) usando las
mismas 3 capas que el script.

Para cada código unmatched muestra:
- Tabla agregada (año / cuatri / inscriptos).
- Gráfico de línea (`:582-591`).
- Selector "Materia destino" + botón "Asociar" — insertA los registros
  bajo el `db_codigo` elegido, sumando a lo existente si ya había datos
  para esa (materia, año, cuatri) (`:596-628`).

Se calcula solo si `final_df.xlsx` existe (`:79-84`). Si el archivo no
está, esta sección queda vacía silenciosamente.

### 1.4 Filtros y visualizaciones

Filtros (`:282-343`):

- **Buscar** (código o nombre, sustring).
- **Cuatrimestre**: `Todos | 1C | 2C` (**no incluye Anual explícitamente**).
- **Año target del forecast**: hasta qué año se extienden las líneas de
  forecast en el gráfico (default 2026).
- **Carrera**: multiselect. Filtra por `PlanEstudioDB.carrera_codigo`.
  Materias huérfanas (sin plan) aparecen solo si el filtro incluye TODAS
  las carreras (`_materia_pasa_filtros:381-384`).
- **Año del plan**: filtro por `PlanEstudioDB.anio_plan`.
- **Optativas**: `Incluir | Solo | Excluir` (usa `PlanEstudioDB.optativa`
  agregado por materia).
- **Período**: `cuatrimestral | anual` (filtro por `MateriaDB.periodo`).
- **Modalidad**: `Presencial | Virtual` (filtro por `MateriaDB.virtual`
  — NO usa el override de dictado).

Toggles de visibilidad (`:344-363`) para las 3 secciones: con datos, sin
datos, sin matchear.

**Gráfico por materia** (`:200-269`):

Es un `st.line_chart` con múltiples series superpuestas:

- Una serie **histórica** por cuatrimestre: `"{cuatri} histórico"`.
- Tres series de **forecast** por cuatrimestre, una por método:
  `"{cuatri} Media móvil"`, `"{cuatri} Drift (lineal)"`,
  `"{cuatri} SES (α auto)"` (labels en `METODO_LABELS` de
  `forecast_service.py:33-38`).

La línea de forecast se traza entre el último punto histórico y el año
target (`_render_materia_expander:230-235`).

Debajo del gráfico se muestran **métricas** de cada método con:
- Valor proyectado.
- Parámetro relevante (α para SES, slope para drift, window para media
  móvil).
- SSE in-sample como tooltip.

Con series de <2 puntos, `get_all_forecasts` (`forecast_service.py:237-253`)
solo devuelve `media_movil` — las otras se omiten.

### 1.5 Cómo se conectan con la asignación

**No hay uso directo del `inscriptos` crudo en el asignador**. La cadena
es:

1. `InscripcionHistoricaDB` es la serie histórica.
2. `forecast_service.get_forecast_for_materia` (`:389-415`) computa el
   valor esperado para (plan, materia, cuatri):
   - Si hay `MateriaForecastConfigDB.valor_override` para ese trío,
     devuelve un `ForecastResult(valor=override, metodo="manual")` —
     **el histórico se ignora**.
   - Sino, computa con el método resuelto: override por materia
     (`MateriaForecastConfigDB.metodo`) o default del plan
     (`PlanificacionCursadaDB.forecast_metodo_default`).
   - Si no hay serie histórica → devuelve `None`.
3. `plan_generation_service.get_inscriptos_esperados_por_comision`
   (`:1077-1127`) multiplica el forecast de la materia por
   `ComisionDB.coef_asignacion` para obtener esperados por comisión.
   Prioriza serie `"Anual"` sobre la del cuatri del ciclo.
4. `asignacion_aulas_service.build_inputs` (`:278-309`) consume el
   forecast por comisión (para el penalty asimétrico del LP) y el
   total por materia (para R9 con α activo).

**Consecuencia práctica**: cambios en la página de Inscriptos afectan
al LP solo cuando (a) el plan usa forecast automático (sin
`valor_override`) y (b) no se está pisando el método. Si el usuario
seteó "Total esperado (manual)" desde `📊 Planes → Detalle`, los
cambios acá **no se propagan**.

### 1.6 Gotchas

1. **Guardar borra y reinserta**: la sección "Con datos" hace
   `DELETE WHERE materia_codigo = X` y reinserta. Si otro proceso agregó
   datos entre la lectura y el save, se pierden — no hay optimistic
   locking.
2. **El filtro por cuatri no restringe el save**: guardar con
   `Cuatrimestre="1C"` filtrado sí guarda solo lo del editor (porque el
   editor no muestra las otras filas), y el DELETE borra TODO lo de la
   materia. **Filtrar por 1C y editar tiene el efecto de borrar las
   filas del 2C sin querer** (validar cuidadosamente en el código:
   `_render_materia_expander:181-194` — el `records` completo se
   filtra a `filtered_records` para display, pero el `df` que va al
   editor arranca de `filtered_records`; el DELETE borra por
   `materia_codigo` sin condición de cuatri). Este es un **bug latente
   que la documentación no menciona**.
3. **"Asociar" suma, no reemplaza**: en la sección "Sin matchear", si el
   destino ya tenía datos para (año, cuatri), la asociación **suma** los
   inscriptos existentes al valor asociado (`:614-618`). No hay warning
   antes de sumar.
4. **`final_df.xlsx` es opcional pero silencioso**: si el archivo no
   existe, la sección "Sin matchear" queda vacía y aparece la sección
   con count 0. No hay mensaje explicando que falta el Excel.
5. **La UI no permite cargar un Excel nuevo**: la carga bulk sigue
   siendo por CLI. Reemplazar el Excel + correr script es la única forma
   de refrescar la vista de unmatched.
6. **La opción "Anual" existe en el selectbox** de cuatrimestre del
   editor pero **el filtro superior no la incluye** — solo `1C / 2C /
   Todos`.
7. **Sin caché**: cada rerun consulta toda la tabla + todos los
   `MateriaDB` + `PlanEstudioDB` + `CarreraDB`. En DBs chicas irrelevante;
   con crecimiento sostenido podría afectar el TTI.

### 1.7 Errores / warnings expuestos al usuario

- Toast al guardar: `"{code}: {N} registros guardados/creados."`.
- Toast al asociar: `"Asociado: {codigo_excel} → {codigo_db}"`.
- Caption "Sin datos para graficar" si `chart_data` está vacío.
- Info `"Selecciona al menos una categoría para mostrar"` si los 3
  toggles están apagados.

No hay error handling explícito para fallos de DB en el save — cualquier
excepción interrumpe el rerun y muestra el traceback de Streamlit.

---

## 2. Historial

### 2.1 Qué se registra

**Modelo**: `ChangeLogDB` (`src/database/models.py:700-741`). Campos:

| Campo | Tipo | Semántica |
|---|---|---|
| `id` | uuid4 | PK |
| `entity_type` | str (indexed) | Nombre de la clase, ej. `"MateriaDB"` |
| `entity_id` | str (indexed) | PK de la entidad (compuestas → `"a+b"`) |
| `entity_label` | str | Etiqueta humana preservada (sobrevive al delete) |
| `action` | str | `"created" | "updated" | "deleted"` |
| `field` | Optional[str] | Solo para `updated`; None para create/delete |
| `old_value` | Optional[str] | JSON serializado |
| `new_value` | Optional[str] | JSON serializado |
| `reason` | str | Texto libre (vacío para hooks sin `change_context`) |
| `when` | datetime (indexed) | `utcnow()` — **UTC**, no zona local |
| `origin` | str (indexed) | `"auto" | "ui:ciclos" | "ui:validacion" | "ui:planes" | ...` |

### 2.2 Entidades trackeadas por hooks automáticos

Whitelist en `TRACKED_ENTITIES` (`change_log_service.py:66-92`):

| Entidad | Campos con `updated` | `created` / `deleted` |
|---|---|---|
| `MateriaDB` | `virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`, `horas_laboratorio` | Sí |
| `CarreraDB` | `dicta_recursado` | Sí |
| `DictadoDB` | `virtual` | Sí |
| `DictadoCicloDB` | — (bridge) | Sí (alta/baja del dictado en un ciclo) |
| `SedeDB` | `es_default_comunes` | Sí |

Los hooks son SQLAlchemy `after_insert / after_update / after_delete`
registrados en `_register_hooks()` (`change_log_service.py:305-317`), que
se ejecuta al importar el módulo. `connection.init_db` importa
`change_log_service` (`src/database/connection.py`), por lo que la
inicialización de la app garantiza que los hooks estén activos.

Campos **no listados** en la whitelist no generan eventos aunque cambien
(ej. `MateriaDB.nombre` no queda en el historial).

**Entidades que NO se auditan por hook**: `HorarioDB`, `ComisionDB`,
`ClaseDB`, `PlanificacionCursadaDB`, `CicloDB`, `AulaDB`,
`ScheduleDB` / `ScheduleEntryDB`, `InscripcionHistoricaDB`,
`MateriaForecastConfigDB`, `LPRunDB`, `PlanEstudioDB`,
`PlanCarreraVersionDB`, `CicloPlanVersionDB`, `MateriaLaboratorioDB`,
`IgnoredConflictDB`, `PlanValidationDB`.

### 2.3 Eventos explícitos via `emit_event`

Cinco puntos del código emiten eventos manualmente (`grep emit_event`):

1. **`src/ui/plan_grilla_editor.py:958-978`** — cuando se edita el flag
   `virtual` de un `HorarioDB` desde la grilla del plan. `HorarioDB` NO
   está en `TRACKED_ENTITIES` (evita ruido cuando se generan cientos
   de filas), pero este cambio puntual **sí** se registra con:
   - `entity_type="HorarioDB"`, `entity_label=f"{materia} · {dia} {hora}"`
   - `field="virtual"`, `origin="ui:planes"`.
   - `reason=f"Edición inline en grilla del plan {plan_id}"`.

2. **`src/ui/plan_grilla_editor.py:1126-1145`** — cambio de
   `ComisionDB.carrera_asignada` desde la tabla de comisiones de la
   grilla del plan. `ComisionDB` tampoco está en `TRACKED_ENTITIES`,
   pero este campo **sí** se registra por afectar al LP:
   - `entity_type="ComisionDB"`, `origin="ui:planes"`.

3. **`src/ui/plan_materia_editor.py:1355-1377`** — mismo caso que (2)
   pero desde el editor por materia del plan.

### 2.4 Eventos por `change_context` (hooks con razón)

`change_context` (`change_log_service.py:103-127`) es un context manager
que setea `origin` + `reason` en `ContextVar`s, que los hooks automáticos
leen al insertar la fila (`:286-287`).

Puntos de uso:

| Archivo | Línea | Operación | `origin` | `reason` (patrón) |
|---|---|---|---|---|
| `src/ui/divergencias_panel.py` | 104 | Aplicar todo (bulk sync) | `ui:ciclos` | `"Sincronización masiva del ciclo {ciclo_id}..."` |
| " | 255 | Bulk promover a regla | `ui:ciclos` | `"Bulk promover: {accion} en {n} materia(s)..."` |
| " | 301 | Crear dictado (fila to_create) | `ui:ciclos` | `"Crear dictado ({materia}) desde panel..."` |
| " | 326 | Omitir en regla (fila to_create) | `ui:ciclos` | `"Promoción a regla (omitir)..."` |
| " | 367 | Borrar huérfano (to_delete) | `ui:ciclos` | `"Borrar huérfano ({materia})..."` |
| " | 403 | Borrar (rule_says_skip) | `ui:ciclos` | `"Borrar dictado ({materia})... regla decía skippear"` |
| " | 427 | Promover a regla (crear) | `ui:ciclos` | `"Promoción a regla (crear)..."` |
| `src/ui/validation_ui.py` | 904 | Aceptar materia(s) del cronograma | `ui:validacion` | `"Aceptar materia(s) del cronograma como {presencial|virtual}..."` |
| " | 943 | Bulk desactivar/borrar | `ui:validacion` | `"Bulk desactivar (borrar) desde validación..."` |
| `app/pages/4_📆_Ciclos.py` | 1339 | Crear dictado excepcional | `ui:ciclos` | `"Crear dictado excepcional ({materia})..."` |

Todos los `origin` posibles observados (más los que aparecen en
`ORIGIN_LABEL` del widget): `auto`, `ui:ciclos`, `ui:validacion`,
`ui:planes`, `ui:materias`, `ui:carreras`, `script`.

**Observación**: `ui:materias` y `ui:carreras` aparecen en el mapa de
labels del widget (`historial_widget.py:40-48`) pero **no hay ningún
`change_context` con esos origen en el código**. Es decir: cualquier
cambio a `MateriaDB` desde `1_📚_Materias.py` queda con `origin="auto"`
(y sin `reason`), no como `"ui:materias"`. La misma observación aplica
a `CarreraDB`.

### 2.5 Estructura de un evento (ejemplo)

Cambio típico registrado al marcar un dictado como virtual desde la
página de Ciclos:

```
id:            "b3a91..."
entity_type:   "DictadoDB"
entity_id:     "12"
entity_label:  "IA1.1-2026-1C"
action:        "updated"
field:         "virtual"
old_value:     "false"
new_value:     "true"
reason:        ""                  # Ciclos no usa change_context para esto
when:          "2026-07-30T14:23:11.482Z"
origin:        "auto"              # hook automático, sin contexto
```

Cambio con contexto rico (bulk promover desde panel de divergencias):

```
entity_type:   "MateriaDB"
entity_id:     "IA 2.3"
entity_label:  "IA 2.3 - Bases de Datos"
action:        "updated"
field:         "dicta_recursado"
old_value:     "false"
new_value:     "true"
reason:        "Bulk promover: crear-en-regla en 4 materia(s) desde el panel de divergencias del ciclo 2026-1C"
origin:        "ui:ciclos"
```

### 2.6 UI — página `📜 Historial`

Dos tabs (`app/pages/8_📜_Historial.py`):

#### Tab 1: 🌐 Feed global

Controles (`:41-53`):
- **Últimos N días**: cutoff temporal (default 30, min 1, max 365).
- **Máx. eventos**: cap de resultados (default 100, min 10, max 500).

**Orden del cutoff y del limit** (`historial_widget.py:166-171`): primero
se traen `limit` eventos ordenados por `when DESC`, y luego se filtran
por antigüedad. **Consecuencia**: si en las últimas 24h hubo >500
eventos, el filtro "últimos 30 días" no traerá los eventos del día 25 —
quedan cortados por el `limit`. Es un gotcha real.

Filtros in-widget adicionales (`:180-198`):
- **Tipo de entidad**: multiselect sobre los tipos presentes en la
  ventana.
- **Origen**: multiselect sobre los orígenes presentes en la ventana.

Cada evento se renderea como fila timeline con:
- Emoji de acción (`➕ / ✏️ / 🗑️`).
- Detalle (`campo: viejo → nuevo` para updates; `**creada**` /
  `**borrada**` para otros).
- Timestamp relativo (`_fmt_when:60-71`): "hace unos segundos", "hace 5
  min", "hace 3 h", "hace 4 días", o fecha `YYYY-MM-DD` si es >30 días.
- Origen (con label humano).
- `entity_label` (si existe).
- `reason` en cursiva (si existe).

**Nota**: el timestamp se compara `datetime.utcnow() - when`. Si el
servidor no está en UTC, la resta funciona porque `when` también se
guarda como `utcnow()`. Pero al mostrar fecha absoluta (`>30 días`) se
muestra la fecha UTC, no la local — puede confundir en zonas GMT-3.

#### Tab 2: 🔎 Por entidad

Selector de tipo (`:56-67`): `Materia | Carrera | Dictado | Sede` (no
incluye `DictadoCicloDB` ni `HorarioDB`/`ComisionDB` aunque tengan
eventos).

Selector de entidad puntual, luego llama a `render_historial_entidad`
(`historial_widget.py:126-150`) que:
- Consulta con `get_log_for_entity` (`change_log_service.py:324-339`).
- Trae hasta `limit=50` eventos ordenados por `when DESC`.
- Renderea la misma fila timeline.

**Gotcha**: si la entidad tiene más de 50 eventos, los más viejos quedan
truncados sin indicador de "hay más". El limit no es configurable desde
la UI (hardcoded a 50).

### 2.7 Casos de uso concretos

- **"¿Quién marcó virtual esta comisión?"** — solo funciona parcialmente:
  el cambio de `ComisionDB.carrera_asignada` sí se loggea (con
  `origin="ui:planes"`); otros campos de comisión (`cupo`, `nombre`,
  `coef_asignacion`) **no se auditan**. `ComisionDB` no está en
  `TRACKED_ENTITIES`.
- **"¿Cuándo se marcó virtual este dictado?"** — sí, hay evento
  `DictadoDB updated field=virtual`. Tab "Por entidad" → Dictado → seleccionar.
- **"¿Por qué se creó este dictado en el ciclo 2026-1C?"** — si se creó
  desde el panel de divergencias o desde validación, el `reason` explica
  el flujo. Si se creó por bulk `create_dictados_for_ciclo` sin
  `change_context`, `reason` está vacío y `origin="auto"`.
- **"¿Quién editó las horas de esta materia?"** — sí, hay evento
  `MateriaDB updated field=horas_teoria`. No hay dato de usuario (el
  sistema no tiene login), pero sí de origin (`auto` si vino de
  `1_📚_Materias.py`, ya que esa página **no** envuelve en
  `change_context`).

### 2.8 Exportar / deshacer / retention

- **No hay exportación**: no existe botón "exportar CSV" ni acceso
  programático desde la UI. La única vía es query directa a la DB.
- **No hay undo**: los eventos son puramente informativos; no revierten
  el cambio.
- **No hay cleanup / retention automático**: no hay job que borre
  eventos viejos. La tabla crece indefinidamente. No hay TTL ni
  paginación real en el feed global (solo cutoff N días desde la UI).

### 2.9 Gotchas — cambios silenciosos

Cambios que **NO quedan en historial**:

1. Cualquier edición sobre `HorarioDB` desde la UI de cronogramas
   (drag/resize/dialog). El único cambio de `HorarioDB` loggeado es el
   flag `virtual` desde la **grilla del plan**, no desde cronograma.
2. Cualquier edición sobre `ComisionDB` que no sea `carrera_asignada`
   (nombre, cupo, coef, descripción, número).
3. Toda alta/baja/edición de `PlanificacionCursadaDB` (activar plan,
   cambiar nombre, cambiar `forecast_metodo_default`, borrar plan en
   cascada).
4. `MateriaForecastConfigDB` (overrides de método y valor manual) —
   editar el "Total esperado (manual)" desde `Planes → Detalle` **no
   deja rastro**.
5. `InscripcionHistoricaDB` (todas las ediciones desde la página de
   Inscriptos son silenciosas).
6. `AulaDB`, `SedeDB` (excepto `es_default_comunes`).
7. `ScheduleDB` / `ScheduleEntryDB` (cronogramas enteros: upload, edición,
   duplicación, borrado — sin trazabilidad).
8. `LPRunDB` (corridas del asignador — sí quedan en su propia tabla como
   snapshot, pero no en el change_log).
9. `CicloDB`, `PlanEstudioDB`, `PlanCarreraVersionDB`,
   `CicloPlanVersionDB`: creación / edición de ciclos, asignación de
   versiones, cambios de plan de estudio.
10. Cambios directos vía script CLI (ej. `load_initial_data --reset`
    borra la DB entera — no queda registro).
11. Cambios a `MateriaDB.nombre`, `MateriaDB.codigo`, `MateriaDB.periodo`
    (no están en la whitelist de campos trackeados).

En resumen: **el change log audita política, no operación**. Todo el
workflow diario (cargar cronogramas, generar planes, correr el LP,
editar horarios/comisiones) es invisible al historial.

---

## 3. Discrepancias con documentación

Comparado con `project/2. Desarrollo/WORKFLOW.md` y
`RECURSADO_Y_VIRTUAL.md`:

1. **Título de la página** — `WORKFLOW.md:604` dice
   `7_📝_Inscriptos.py` con emoji "memo". El archivo real es
   `7_📈_Inscriptos.py` (emoji "chart_with_upwards_trend"). Menor pero
   confunde al buscar.
2. **Origen de datos de inscriptos** — `WORKFLOW.md` **no menciona**
   `data/input/inscriptos/final_df.xlsx` ni el script
   `load_inscriptos.py`. La sección 1 ("Carga inicial") habla de
   `aulas.xlsx`, `materias.xlsx`, `materias_carreras.xlsx`,
   `materias_laboratorios.xlsx` pero omite el Excel de inscriptos.
3. **`ORIGIN_LABEL` incluye labels sin uso real** — el widget mapea
   `"ui:materias"` y `"ui:carreras"` a labels humanos, pero ningún
   `change_context` los emite. Es dead code o intención no cumplida.
4. **`RECURSADO_Y_VIRTUAL.md:189-199` describe la UI del Historial**
   como si permitiera filtro por origen "en dos modos". El widget "Por
   entidad" **no** ofrece filtro por origen; sólo el feed global.
5. **`MateriaDB.active` está en la whitelist** de campos trackeados,
   pero `active` **no se edita desde ninguna UI relevante** hoy (el
   toggle "Activo" viejo fue removido cuando se reemplazó por
   "existencia del dictado = activación"). Es una relíquia de la fase
   anterior; puede generar eventos si se cambia por script, pero
   no aparece expuesto en la UI de Materias.
6. **`requerimientos.md` (RF-AUDIT-04)** dice que la página tiene "feed
   global filtrable por tipo de entidad y origen, y vista por entidad
   puntual". Correcto en general, pero omite que el limit "últimos N
   días" no funciona bien contra el cap de `limit` (ver 2.6).
7. **`WORKFLOW.md` no menciona explícitamente**:
   - Que el flag `virtual` de `HorarioDB` desde la grilla del plan
     genera un evento auditado.
   - Que `ComisionDB.carrera_asignada` es el **único** campo de
     comisión auditado.

---

## 4. Preguntas abiertas

1. **¿La sección "Con datos" tiene el bug latente que borra filas del
   otro cuatrimestre?** Hay que confirmar con un test de reproducción.
   La lectura del código sugiere que sí: el DELETE en
   `_render_materia_expander:181-186` no filtra por cuatri, y el editor
   solo muestra el cuatri filtrado.
2. **¿La página de Inscriptos debería registrar cambios en el historial?**
   Actualmente no lo hace. Dado que impacta forecasts que impactan al
   LP, tal vez debería.
3. **¿`MateriaForecastConfigDB.valor_override` debería auditarse?** Es
   probablemente el override más consecuente en el sistema (pisa el
   forecast) y no queda rastro.
4. **¿Cómo se maneja el crecimiento de `change_log`?** Sin retention,
   la tabla crece linealmente con el uso. ¿Debería el manual mencionar
   que hay que hacer housekeeping manual periódicamente?
5. **¿`ORIGIN_LABEL` con `"ui:materias"` / `"ui:carreras"` es
   aspiracional o dead code?** Convendría envolver los cambios de las
   páginas 1 y 3 en `change_context` para completar la traza.
6. **`_fmt_when` usa `utcnow()`** — ¿la app tiene alguna convención de
   zona horaria? Los usuarios en Rosario (GMT-3) verán las horas
   absolutas desfasadas.
7. **¿El `entity_id` de `ComisionDB` es un UUID largo?** Si es así, la
   vista "Por entidad" no ofrece `ComisionDB` — solo se pueden ver los
   eventos yendo al feed global y filtrando. Habría que agregarlo al
   selector si se considera relevante.
8. **`HorarioDB` en el filtro de tipo del tab "Por entidad"**: no
   aparece en el selector aunque haya eventos. ¿Es intencional?
9. **`DictadoCicloDB` events**: son eventos de bridge sin `field`.
   ¿Cómo se ven en la UI? El widget muestra `**creada**` / `**borrada**`
   con label `"{dictado_id} en {ciclo_id}"` — parece funcional pero
   requiere verificación visual.

---

## 5. Archivos revisados

- `app/pages/7_📈_Inscriptos.py`
- `app/pages/8_📜_Historial.py`
- `src/services/change_log_service.py`
- `src/services/forecast_service.py`
- `src/services/plan_generation_service.py` (fragmento
  `get_inscriptos_esperados_por_comision`)
- `src/services/asignacion_aulas_service.py` (fragmento `build_inputs`
  donde consume el forecast)
- `src/ui/historial_widget.py`
- `src/ui/divergencias_panel.py`
- `src/ui/plan_grilla_editor.py` (usos de `emit_event`)
- `src/ui/plan_materia_editor.py` (uso de `emit_event`)
- `src/ui/validation_ui.py` (usos de `change_context`)
- `app/pages/4_📆_Ciclos.py` (uso de `change_context`)
- `scripts/load_inscriptos.py`
- `src/database/models.py` (modelos `InscripcionHistoricaDB`,
  `ChangeLogDB`, `MateriaForecastConfigDB`)
- `project/2. Desarrollo/WORKFLOW.md`
- `project/2. Desarrollo/RECURSADO_Y_VIRTUAL.md`
- `project/requerimientos.md` (RF-AUDIT-01..04)
