# Hallazgos de la auditoría — bugs, discrepancias y deuda técnica

> Fecha de la auditoría: 2026-07-30.
> Origen: 5 agentes en paralelo revisaron el catálogo maestro,
> ciclos+cronogramas, planes+asignación de aulas, inscriptos+historial y
> flujos globales. El detalle exhaustivo está en
> `project/3. Manual de Usuario/_auditoria/*.md`.
> **Ninguno de estos hallazgos fue arreglado**: sirven de backlog para
> sesiones futuras.

Convenciones:

- **Prioridad**: 🔴 alta (bug funcional que corrompe datos o rompe una
  operación central), 🟠 media (bug funcional acotado o UX
  engañoso), 🟡 baja (deuda técnica, dead code, textos desfasados).
- **Categoría**: `bug`, `ui-engañosa`, `dead-code`, `doc-desfasada`,
  `dx-hueco` (deuda de developer experience, ej. duplicación).
- Cada hallazgo referencia archivo + línea. Se agregó un TL;DR arriba
  de todo para triaje rápido.

---

## TL;DR — Ranking rápido

| # | Prioridad | Categoría | Descripción corta |
|---|---|---|---|
| ~~H01~~ | ✅ | bug | ~~Guardar en Inscriptos "Con datos" con filtro por cuatri borra silenciosamente el otro cuatri~~ **Resuelto 2026-07-30** — nuevo `inscripcion_service.guardar_registros_materia` con UPSERT y scope restringido a cuatris visibles. |
| H02 | 🔴 | bug | `apply_horario_edits` no limpia `HorarioDB.aula_id` al mover el slot: patrón queda con aula colgada |
| H03 | 🔴 | bug | Borrar un `ScheduleDB` no borra sus comisiones template ni el plan derivado: FK dangling |
| H04 | 🔴 | bug | Crear una `CarreraDB` desde la UI no crea la `PlanCarreraVersionDB`: la carrera queda inútil hasta que se detecta |
| H05 | 🔴 | bug | `clonar_ciclo_para_demo.py` no clona `HorarioDB.virtual`: los horarios clonados pierden el override |
| H06 | 🔴 | bug | Import de cronograma ignora la columna `comision` del archivo: se pierde asociación de horarios a comisiones al importar |
| H07 | 🟠 | bug | Historial "últimos N días" aplicado después del limit: si hay >500 eventos recientes, quedan cortados |
| H08 | 🟠 | bug | "Activar" en tab Vista General de Planes no genera `ClaseDB` (solo flippea flag); el "Activar plan" del panel de validación sí |
| H09 | 🟠 | ui-engañosa | Toggle "Respetar ediciones manuales" del asignador no hace nada visible: `aula_asignada_manualmente` está huérfano post-deprecación de clases puntuales |
| H10 | 🟠 | bug | Borrar un `AulaDB` no verifica horarios de patrón ni `MateriaLaboratorioDB`, solo `ClaseDB` |
| H11 | 🟠 | bug | Borrar una `MateriaDB` no verifica dependencias antes: cascada rota o `IntegrityError` de SQL |
| H12 | 🟠 | ui-engañosa | Botón "🗑️ Cancelar (borra el plan)" del wizard borra sin confirmación intermedia |
| H13 | 🟠 | ui-engañosa | Botón "Eliminar" del tab Vista General borra el plan sin confirmación intermedia |
| H14 | 🟠 | bug | `MateriaForecastConfigDB.valor_override` no queda en historial: cambia el forecast (y el asignador) sin trazabilidad |
| H15 | 🟠 | bug | `parse_horarios_file` no persiste `comision_id` aunque el schema lee la columna: la columna es una promesa incumplida |
| H16 | 🟠 | ui-engañosa | Página real es "🏛️ Aulas y Sedes" y "📈 Inscriptos" pero `WORKFLOW.md` la nombra distinto y el mapa no lista Historial |
| H17 | 🟠 | bug | Cambiar tipo de `AulaDB` de/a `laboratorio` no borra `MateriaLaboratorioDB` colgadas |
| H18 | 🟡 | dead-code | Tab "🔍 Buscar" de Materias duplica el filtro del tab "📋 Lista" con menos features |
| H19 | 🟡 | dead-code | `ORIGIN_LABEL` del historial mapea `"ui:materias"` y `"ui:carreras"` pero ningún flujo los emite |
| H20 | 🟡 | dead-code | `MateriaDB.active` en whitelist de auditoría pero la UI no lo edita |
| H21 | 🟡 | dead-code | `codigo_guarani` se carga del Excel pero no se ve ni se edita en la UI |
| H22 | 🟡 | dx-hueco | Vista General duplica `delete_plan_cascade` inline en lugar de usar la función del service |
| H23 | 🟡 | doc-desfasada | `WORKFLOW.md § 3.3` menciona el toggle "Pisar ediciones manuales" y campo `activo_override_manual` ya eliminados |
| H24 | 🟡 | doc-desfasada | `WORKFLOW.md § 6.2` habla de 5 métricas del plan (real: 4). `§ 6.3` afirma que el cupo no se edita en UI (real: sí). `§ 10` lista tab "Clases" inexistente |
| H25 | 🟡 | doc-desfasada | `ASIGNACION_IMPL.md § 4.2/4.3` describe `_render_heatmap_demanda_oferta` y `_render_impacto_r10` reemplazados por `_render_heatmap_por_sede` |
| H26 | 🟡 | doc-desfasada | `requerimientos.md` RF-LP-13/14 apuntan a funciones ya no usadas; RF-PLAN-01 describe "por dictado" pero el schema actual no lo obliga |
| H27 | 🟡 | ui-engañosa | Autoderivación del `codigo_aula` deja el nombre de la sede pegado como string: si la sede se renombra o fusiona, queda desincronizado |
| H28 | 🟡 | ui-engañosa | Fila "Sólo manuales ✋" del cronograma por aula queda siempre vacía (no hay flujo que setee el flag) |
| H29 | 🟡 | doc-desfasada | Cutoff del selectbox de cuatrimestre incluye "Anual" en Inscriptos, pero el filtro superior no |
| H30 | 🟡 | dx-hueco | La comisión del `data_editor` de "Carrera asignada" muestra `["—"] + [codigos]`. Si la carrera no existe en la base, el valor previo se pierde silenciosamente al re-render |
| H31 | 🟡 | bug | Change log usa `datetime.utcnow()` sin zona horaria: usuarios en Rosario (GMT-3) ven fechas absolutas desfasadas 3 h |
| H32 | 🟡 | dx-hueco | `emit_event` explícito para `HorarioDB.virtual` y `ComisionDB.carrera_asignada` cubre 3 líneas del código, otras ediciones equivalentes en distintos widgets quedan sin auditoría |
| H33 | 🟡 | ui-engañosa | Snapshots de validación pueden quedar stale (`is_validation_stale`) pero la UI no siempre lo indica claro |
| H34 | 🟡 | ui-engañosa | El historial "Por entidad" tiene el limit hardcodeado a 50 sin indicador de "hay más" |
| H35 | 🟡 | bug | Inscriptos: la sección "Asociar" del panel "Sin matchear" suma silenciosamente al valor previo del destino sin warning |
| H36 | 🟡 | dx-hueco | Comisiones template quedan vivas con `schedule_id` a un ID inexistente si el cronograma se borra (no aparecen en listados pero siguen en la DB) |

---

## H01 — Inscriptos "Con datos" borra silenciosamente el otro cuatri ✅ RESUELTO

**Categoría**: `bug` funcional que **destruye datos del usuario sin
aviso**.

**Archivo**: `app/pages/7_📈_Inscriptos.py`, función
`_render_materia_expander`, líneas ~180–196.

**Descripción**: al guardar cambios en la sección "Materias con datos"
teniendo el filtro superior de "Cuatrimestre" seteado en `1C` (o `2C`),
la operación de guardado ejecuta un `DELETE WHERE materia_codigo = X`
**sin condición por cuatrimestre** y luego reinserta lo que hay en el
editor. Como el editor sólo muestra las filas del cuatri filtrado,
**todas las filas del cuatri opuesto se pierden**.

**Escenario de reproducción**:
1. Materia `FIS 1.1` tiene registros en `1C` (años 2021-2025) y en
   `2C` (años 2021-2025).
2. Usuario setea filtro "Cuatrimestre = 1C" en el sidebar.
3. Abre el expander de `FIS 1.1`, corrige un valor de 2024/1C.
4. Aprieta "Guardar".

**Resultado real**: los 5 registros de `2C` desaparecen. La UI muestra
sólo los de `1C` así que el usuario no ve la pérdida hasta que
saque el filtro.

**Resultado esperado**: guardar sólo lo que se editó, respetando los
otros cuatrimestres.

**Fix aplicado** (2026-07-30):

Se creó `src/services/inscripcion_service.py` con la función
`guardar_registros_materia(session, codigo, registros, *,
cuatris_visibles)` que reemplaza el `DELETE + INSERT` monolítico por
un diff explícito:

1. Trae las filas existentes de la materia **restringidas a los
   `cuatris_visibles`**.
2. Aplica UPDATE / INSERT según coincidencia por PK
   `(materia_codigo, anio, cuatrimestre)`.
3. Borra las filas visibles que ya no están en el editor (el usuario
   las eliminó).
4. **Las filas fuera de `cuatris_visibles` quedan intactas**.

Además valida defensivamente que ninguna fila del editor tenga un
cuatrimestre fuera del scope visible (bug en la UI).

Test suite dedicada: `tests/test_inscripcion_service.py` (9 tests
cubriendo el bug original, el flujo "Todos", eliminación de filas,
inserción de filas nuevas, y validaciones defensivas).

Integración en `app/pages/7_📈_Inscriptos.py:_render_materia_expander`:
la lógica del botón "Guardar" ahora arma `RegistroInscripcion`s desde
el editor y delega al service, pasando `cuatris_visibles` derivado del
filtro superior del sidebar.

---

## H02 — `apply_horario_edits` no limpia `HorarioDB.aula_id` al mover slot 🔴

**Categoría**: `bug` funcional. Deja el modelo inconsistente.

**Archivo**: `src/services/plan_generation_service.py`,
`apply_horario_edits` línea ~629.

**Descripción**: al mover un `HorarioDB` a otro día/franja (drag en el
calendario, edición manual del editor por materia, edición en la
Grilla Horaria), el `aula_id` viejo queda pegado a la fila. Puede
generar dos horarios apuntando a la misma aula en la misma franja sin
que nadie lo señale hasta la próxima corrida del LP (que va a decir
`infeasible` o pisar la asignación).

**Servicio disponible pero no invocado**: `clear_aula_horario` existe
pero `apply_horario_edits` no lo llama automáticamente.

**Escenario de reproducción**:
1. LP corrido, `HorarioDB h1` tiene `aula_id = A5`, día Lu 14–16.
2. Usuario arrastra `h1` al Ma 10–12.
3. `HorarioDB h1` queda con `dia=Ma`, `hora=10–12`, **`aula_id=A5`**
   pero el aula A5 en Ma 10–12 ya está ocupada por otra clase.
4. El panel de "Cronograma por aula" muestra choques.
5. Recién en la próxima corrida del LP se detecta y se reasigna.

**Fix propuesto**: `apply_horario_edits` debe llamar a
`clear_aula_horario` cuando `dia/hora_inicio/hora_fin` cambia respecto
del estado previo.

**Riesgo si no se arregla**: reportes visuales inconsistentes,
sensación de "el sistema quedó desincronizado" hasta la próxima
corrida.

---

## H03 — Borrar cronograma con plan derivado deja comisiones template y FK dangling 🔴

**Categoría**: `bug` funcional. Corrompe el modelo relacional.

**Archivo**: `src/services/schedule_service.py` función
`delete_schedule`. Modelo:
`ComisionDB.schedule_id` en `src/database/models.py`.

**Descripción**: `delete_schedule` borra `ScheduleEntryDB` y
`ScheduleDB` pero **no** las `ComisionDB` con `schedule_id` igual.
Además no toca a `PlanificacionCursadaDB` que hereda `schedule_id`
como referencia histórica — el plan queda apuntando a un schedule
inexistente. Como el `comision_service` filtra por `schedule_id`
seteado, las comisiones template huérfanas no aparecen en ningún
listado — sólo se pueden ver con un query directo.

**Escenario de reproducción**:
1. Se creó cronograma `sched_2026_1C_v1` con 12 comisiones template.
2. Se generó plan `plan_2026_1C_borrador` a partir de él (crea las
   comisiones del plan por clonado).
3. Usuario borra `sched_2026_1C_v1` desde el tab Lista.
4. Comisiones template quedan en `comisiones` con `schedule_id`
   apuntando a un ID inexistente.
5. `plan_2026_1C_borrador.schedule_id` sigue apuntando a un ID
   inexistente. El plan queda navegable pero sin ancla.

**Fix propuesto**: `delete_schedule` debe:
1. Verificar si hay planes derivados y bloquear con error, o
2. Borrar las comisiones template en cascada, o
3. Nullificar `plan_cursada.schedule_id` como decisión explícita.

Además, `plan_generation_service` debería usar
`plan.schedule_id` sólo para trazabilidad y no romper si es NULL.

**Riesgo si no se arregla**: crecimiento de basura en la tabla
`comisiones` con `schedule_id` inexistente; potenciales `IntegrityError`
en operaciones que no filtren bien.

---

## H04 — Crear una carrera desde la UI no crea `PlanCarreraVersionDB` 🔴

**Categoría**: `bug` funcional (comportamiento inesperado).

**Archivo**: `app/pages/3_🎓_Carreras.py` tab "➕ Crear".

**Descripción**: al crear una `CarreraDB` desde la UI, no se crea
automáticamente una `PlanCarreraVersionDB`. El script
`load_initial_data` sí la crea (`"Plan Original"`), pero la UI no.
Consecuencia: la carrera nueva aparece pero **no se le pueden asociar
materias** — el editor de "Materias por carrera" tira "No se encontró
plan de estudios para la carrera 'X'".

**Escenario de reproducción**:
1. Usuario crea carrera nueva `LEE` (Lic. en Estadística Educativa)
   desde `🎓 Carreras → ➕ Crear`.
2. Va a `📚 Materias → ➕ Crear` y quiere asociarla a materias.
3. Ve error "No se encontro plan de estudios para la carrera 'LEE'".
4. El usuario no técnico no sabe que hay que crear una "versión de
   plan" primero.

**Fix propuesto**: al crear la carrera, crear también una versión
inicial `PlanCarreraVersionDB(nombre="Plan Original", ...)` en la
misma transacción.

**Riesgo si no se arregla**: onboarding roto para nuevas carreras.

---

## H05 — Clon de ciclo para demo no clona `HorarioDB.virtual` 🔴

**Categoría**: `bug` funcional. Pierde configuración.

**Archivo**: `scripts/clonar_ciclo_para_demo.py`, paso 6 (clonación de
`HorarioDB`).

**Descripción**: el script crea las filas clonadas **sin pasar el
campo `virtual`**. Con el refactor RF-DICT-09/10, `HorarioDB.virtual`
es `Optional[bool]` y es semánticamente relevante. Al clonar, los
horarios nuevos quedan con `virtual=None` (heredan del dictado),
aunque el original tuviera `virtual=True` o `virtual=False` forzados.

**Escenario de reproducción**:
1. Un ciclo `2026-1C` tiene comisiones con horarios individuales
   marcados como virtuales (por Zoom).
2. Se clona con
   `python -m scripts.clonar_ciclo_para_demo --ciclo-id 2026-1C
   --sufijo demo`.
3. En el ciclo clonado, esos horarios pierden el `virtual=True` y
   pasan a resolver el flag por el dictado padre.
4. La corrida del LP sobre el clon puede volverse infactible o
   asignar aulas a horarios que en el original no las requerían.

**Fix propuesto**: en el paso 6, pasar `virtual=orig.virtual` al
constructor de `HorarioDB`.

**Riesgo si no se arregla**: casos ejemplo (demos, escenarios de
saturación) no reproducen fielmente el estado original.

---

## H06 — Import de cronograma ignora la columna `comision` 🔴

**Categoría**: `bug` funcional (promesa del schema incumplida).

**Archivo**: `src/services/horario_file_parser.py` +
`src/services/schedule_service.py` funciones
`create_schedule_from_file` / `create_schedule_standalone`.

**Descripción**: `parse_horarios_file` lee la columna `comision` (o
alias) del Excel y la asigna a `HorarioInput.comision_nombre`. Pero
`create_schedule_standalone` **no la usa** al crear los
`ScheduleEntryDB` — sólo persiste `codigo_materia/dia/hora_inicio/hora_fin`.
El número de comisión del archivo original **se pierde**.

**Escenario de reproducción**:
1. Excel con 4 columnas: `materia | dia | inicio | fin | comision`.
2. Usuario sube el archivo desde `📅 Cronogramas → 📤 Cargar`.
3. El toast dice "Cronograma creado con N entradas" — todas quedan
   con `comision_id = NULL`.
4. Usuario tiene que asignar comisiones manualmente desde el tab
   Editar.

**Fix propuesto**: usar
`get_or_create_comision_by_numero(schedule_id, codigo_materia,
comision_nombre)` durante la creación de entries y setear
`comision_id`.

**Riesgo si no se arregla**: para cualquier facultad que ya trae
Excels con comisión asignada, la importación se pierde y hay que
re-hacer manualmente. UX terrible para un caso frecuente.

---

## H07 — Historial: cutoff "N días" aplicado después del limit 🟠

**Categoría**: `bug` de UX.

**Archivo**: `src/ui/historial_widget.py`, función `render_historial`
línea ~166–171.

**Descripción**: la query trae hasta `limit` eventos ordenados por
`when DESC` y **luego** filtra por antigüedad. Si en las últimas 24 h
hubo >500 eventos, el filtro "últimos 30 días" no traerá los eventos
del día 25 — se cortan por el limit.

**Fix propuesto**: filtrar por `when >= now - N días` en la query SQL
y **luego** aplicar `LIMIT`.

**Riesgo**: pérdida de visibilidad en investigaciones históricas.

---

## H08 — "Activar" en Vista General ≠ "Activar plan" en el panel de validación 🟠

**Categoría**: `ui-engañosa` / inconsistencia semántica.

**Archivos**:
- `app/pages/5_📊_Planes.py` tab Vista General, botón "Activar"
  (llama `plan_generation_service.activate_plan`).
- Panel de validación del tab Detalle, botón "Activar plan"
  (llama `activate_plan` + `generate_clases_for_plan`).

**Descripción**: hay dos botones con label parecido y semántica
distinta. Uno flippea el flag `activo=True`. El otro flippea el flag
**y** genera `ClaseDB`. Si el usuario activa desde Vista General, el
plan queda "activo" pero sin clases materializadas — un estado
intermedio confuso.

**Fix propuesto**: unificar el comportamiento (Vista General llama al
mismo flujo que el panel de validación), o renombrar los botones para
que la diferencia sea clara ("Activar (rápido, sin generar clases)"
vs "Activar y generar clases").

---

## H09 — Toggle "Respetar ediciones manuales" no hace nada visible 🟠

**Categoría**: `ui-engañosa` post-deprecación.

**Archivos**:
- `src/services/asignacion_aulas_service.py`
  `LPConfig.respetar_ediciones_manuales`.
- `src/ui/asignacion_panel.py` _render_config_form.

**Descripción**: el toggle está en el form de configuración del
asignador (default ON). Su efecto es respetar `ClaseDB.aula_asignada_manualmente=True`.
Pero desde la deprecación de clases puntuales (2026-07-07), **ningún
flujo de UI setea ese flag en True**. Consecuencia: la métrica
"Manuales respetadas" da siempre 0, y el toggle no cambia el
comportamiento visible.

**Fix propuesto** (dos opciones):
- Ocultar el toggle en la UI hasta que vuelva la edición puntual
  (`RF-LP-05`).
- O documentarlo como "capacidad latente" con un caption "no hace
  efecto en el flujo actual".

**Riesgo**: usuario ajusta el toggle esperando cambios de
comportamiento y no ve ninguno.

---

## H10 — Borrar `AulaDB` no verifica horarios de patrón ni `MateriaLaboratorioDB` 🟠

**Categoría**: `bug` funcional.

**Archivo**: `app/pages/2_🏛️_Aulas.py` tab "👁️ Ver detalle", expander
"🗑️ Borrar aula".

**Descripción**: la validación pre-borrado sólo mira
`ClaseDB.aula_id == aula.id`. Pero un aula puede estar referenciada
también por:
- `HorarioDB.aula_id` (patrón semanal, output del LP).
- `MateriaLaboratorioDB` (compatibilidades lab).

Si se borra sin verificar, el `HorarioDB` queda con `aula_id`
apuntando a un ID inexistente y las relaciones lab también.

**Fix propuesto**: extender la verificación a las tres tablas.
Idealmente usar el enfoque de "fusionar aulas" para reasignar antes
de borrar.

---

## H11 — Borrar `MateriaDB` no verifica dependencias 🟠

**Categoría**: `bug` funcional (falta de guardián).

**Archivo**: `app/pages/1_📚_Materias.py`, botón "Eliminar" del tab
Lista.

**Descripción**: a diferencia de `CarreraDB` (verifica planes
asociados) y `SedeDB` (verifica aulas), la eliminación de materias
va directo al `DELETE`. Si la materia tiene `PlanEstudioDB`,
`MateriaLaboratorioDB`, `DictadoDB`, `ComisionDB`, `HorarioDB` o
`InscripcionHistoricaDB`, la operación falla con `IntegrityError`
crudo de SQLAlchemy visible en la UI como "FOREIGN KEY constraint
failed" — feo y confuso.

**Fix propuesto**: agregar chequeo de dependencias antes del delete,
con mensaje claro tipo "No se puede eliminar: la materia está
asignada a N carreras / tiene M dictados / etc."

---

## H12 — Wizard "Cancelar" borra sin confirmación intermedia 🟠

**Categoría**: `ui-engañosa`. Riesgo de pérdida accidental.

**Archivo**: `app/pages/5_📊_Planes.py` líneas ~649–664.

**Descripción**: el botón **"🗑️ Cancelar (borra el plan)"** del Paso 2
del wizard llama a `delete_plan_cascade` en cascada (borra clases,
horarios, comisiones, plan). No hay diálogo intermedio. El caption
dice "No se puede deshacer" pero técnicamente no hay confirmación
explícita — un click accidental destruye todo.

**Fix propuesto**: 2-step confirm (primer click cambia el label a
"¿Estás seguro? Volvé a hacer click para confirmar" durante N
segundos).

---

## H13 — "Eliminar" en Vista General también borra sin confirmación 🟠

Igual que H12 pero para el botón "Eliminar" del contenedor de cada
plan en el tab Vista General. Además duplica la cascada inline en
lugar de reutilizar `delete_plan_cascade` (ver H22).

---

## H14 — `MateriaForecastConfigDB.valor_override` no queda en historial 🟠

**Categoría**: `bug` de trazabilidad.

**Archivo**: `src/database/models.py` `MateriaForecastConfigDB`. No
está en `TRACKED_ENTITIES` de `change_log_service`.

**Descripción**: el `valor_override` (Total esperado (manual)) es
probablemente el override **más consecuente** en el sistema porque
pisa el forecast que alimenta al asignador. Un cambio de este valor
puede transformar un plan de "factible" a "infactible". No hay
rastro en el historial de quién lo cambió, cuándo ni por qué.

**Fix propuesto**: agregar `MateriaForecastConfigDB` a
`TRACKED_ENTITIES` y envolver los cambios en `change_context` con
`origin="ui:planes"`.

---

## H15 — Parser lee `comision` pero no la usa 🟠

Ver H06. Es la contracara del bug: el parser aloja el campo, el
service no lo consume.

---

## H16 — Nombres/íconos de páginas desalineados con `WORKFLOW.md` 🟠

- Página real: `🏛️ Aulas y Sedes` — `WORKFLOW.md` la nombra
  "Aulas" a secas y no menciona el CRUD de sedes.
- Página real: `📈 Inscriptos` — `WORKFLOW.md` dice `📝 Inscriptos`.
- Página real: `📜 Historial` (página 8) — no aparece en el mapa de
  páginas de `WORKFLOW.md`.
- Página `🏛️ Aulas y Sedes` incluye default de comunes, fusión,
  renombre — nada de esto está documentado.

**Fix propuesto**: alinear el mapa de páginas de `WORKFLOW.md` con el
código, o (mejor) generarlo automáticamente.

---

## H17 — Cambiar tipo de aula no limpia `MateriaLaboratorioDB` 🟠

**Categoría**: `bug` (dead relations).

**Archivo**: `app/pages/2_🏛️_Aulas.py` tab "👁️ Ver detalle".

**Descripción**: al cambiar el tipo de un aula de `laboratorio` a
otro tipo (o viceversa), las filas `MateriaLaboratorioDB` **no se
limpian**. Aparece un caption que lo dice, pero la relación queda
colgando: aulas que ya no son labs siguen mencionadas como
compatibles.

**Efecto real**: se mitiga porque los queries filtran por
`tipo=="laboratorio"` antes de mostrar. Pero al re-cambiar el aula a
laboratorio, las relaciones antiguas vuelven a estar activas sin
aviso.

**Fix propuesto**: al cambiar tipo, borrar (o desactivar) las
relaciones `MateriaLaboratorioDB` de ese aula.

---

## H18 — Tab "🔍 Buscar" de Materias es redundante 🟡

**Categoría**: `dead-code` / duplicación de UI.

**Archivo**: `app/pages/1_📚_Materias.py` tab "🔍 Buscar".

**Descripción**: es una vista de sólo lectura que muestra "📚 codigo
- nombre" sin acciones. El tab "📋 Lista" ofrece el mismo filtro con
Editar/Eliminar. Es redundante.

**Fix propuesto**: eliminar el tab. Guardar la lógica de búsqueda como
utility si acaso.

---

## H19 — `ORIGIN_LABEL` incluye labels sin uso real 🟡

**Categoría**: `dead-code`.

**Archivo**: `src/ui/historial_widget.py` líneas ~40–48.

**Descripción**: el mapa incluye `"ui:materias"` y `"ui:carreras"`
como orígenes esperados, pero **ningún** `change_context` los emite
hoy. Los cambios desde `1_📚_Materias.py` y `3_🎓_Carreras.py` quedan
con `origin="auto"` (hook automático sin contexto).

**Fix propuesto** (dos opciones):
1. Cubrir las páginas 1 y 3 con `change_context(origin="ui:materias")`
   y `change_context(origin="ui:carreras")` en los flujos relevantes.
2. Eliminar los labels no usados del mapa.

Opción (1) es preferible porque completa la traza.

---

## H20 — `MateriaDB.active` trackeado pero no editable 🟡

**Categoría**: `dead-code` / feature latente.

**Archivo**: `MateriaDB.active` en `src/database/models.py` +
whitelist en `change_log_service.py`.

**Descripción**: la columna `active` existe con default `True`. Un
script antiguo (`mark_optativas_virtual.py`) la puede tocar. Pero la
UI de Materias no la expone como toggle. Puede generar eventos por
script y confundir al lector del historial.

**Fix propuesto**:
- Si es feature latente para soft-delete: documentarlo y ofrecer un
  toggle "activo".
- Si es dead-code: sacar la columna o al menos sacarla de la whitelist.

---

## H21 — `codigo_guarani` fantasma 🟡

**Categoría**: `dead-code` / campo silencioso.

**Archivo**: `MateriaDB.codigo_guarani` en `src/database/models.py` +
`scripts/load_initial_data.py`.

**Descripción**: se carga del Excel maestro pero **no se edita ni se
muestra en la UI** en ningún lado. Probablemente pensado para
integración futura con SIU-Guaraní. Hoy es data huérfana.

**Fix propuesto**: documentarlo como "reservado para integración
futura", exponer un input read-only en la vista de detalle de
materia (para que sea evidente que existe), o sacarlo.

---

## H22 — Vista General duplica `delete_plan_cascade` inline 🟡

**Categoría**: `dx-hueco`.

**Archivo**: `app/pages/5_📊_Planes.py` líneas ~775–800.

**Descripción**: el borrado del plan en el tab Vista General
implementa la cascada manualmente (clases → horarios → comisiones →
plan). El wizard usa `delete_plan_cascade` del service. Es el mismo
código duplicado.

**Fix propuesto**: reemplazar el bloque inline por una llamada a
`delete_plan_cascade`.

---

## H23 — `WORKFLOW.md § 3.3` menciona features eliminadas 🟡

**Categoría**: `doc-desfasada` (contradicción interna).

**Descripción**: la sección 3.3 sigue mencionando el toggle "Pisar
también las ediciones manuales" y el campo `activo_override_manual`.
Ambos fueron eliminados en el refactor de junio 2026 (marcado en la
nota 1 del header del propio documento). Contradicción entre header
y cuerpo.

**Fix propuesto**: reescribir § 3.3 usando el modelo actual
(`sync_dictados_para_ciclo` con 3 secciones:
`to_create` / `to_delete` / `rule_says_skip_but_exists`).

---

## H24 — `WORKFLOW.md § 6.2 / 6.3 / 10` desalineados con el código 🟡

**Categoría**: `doc-desfasada`.

**Descripción**:
- § 6.2 dice "5 métricas": Materias, Comisiones, Horarios, Clases,
  Con Aula. Realidad: 4 métricas (sin "Clases").
- § 6.3 afirma que el cupo por comisión no se edita en UI. Realidad:
  se edita desde el `data_editor` de comisiones en la Grilla
  Horaria.
- § 10 lista un tab "Clases" que fue removido en la deprecación de
  clases puntuales.

**Fix propuesto**: reemplazar la sección de tabs con la lista real
(Generar Plan, Vista General, Detalle, Grilla Horaria, Aulas,
Configuración).

---

## H25 — `ASIGNACION_IMPL.md § 4.2 / 4.3` describe funciones ya no usadas 🟡

**Categoría**: `doc-desfasada`.

**Descripción**: la doc habla de `_render_heatmap_demanda_oferta` y
`_render_impacto_r10`. Ambas fueron reemplazadas por
`_render_heatmap_por_sede` que unifica funcionalidades particionando
por sede.

**Fix propuesto**: actualizar la sección al estado actual del
`asignacion_resultado_ui.py`.

---

## H26 — `requerimientos.md` con RFs desactualizados 🟡

**Categoría**: `doc-desfasada`.

**Descripción**:
- RF-LP-13 / RF-LP-14 apuntan al heatmap demanda/oferta e impacto R10
  con nombres viejos. Reemplazados (ver H25).
- RF-PLAN-01 describe "por dictado con coeficientes de asignación",
  pero el schema actual permite `ComisionDB.dictado_id = None` para
  las comisiones del plan y `build_inputs` lo maneja explícitamente.

**Fix propuesto**: reescribir los RFs afectados.

---

## H27 — `codigo_aula` autoderivado se desincroniza al renombrar sede 🟡

**Categoría**: `ui-engañosa`.

**Descripción**: la autoderivación del código
(`{sede_nombre}-{aula_nombre}` con guiones) genera un string que
persiste **como texto crudo**, no como referencia. Si después la sede
se renombra o se fusiona con otra, el código del aula queda con el
nombre viejo pegado.

Ejemplo: `Pellegrini-AULA-01` sigue siendo así aunque la sede se
renombre a "Sede Central".

**Fix propuesto** (dos opciones):
- Ofrecer un botón "Regenerar código" cuando la sede se renombra.
- Regenerar automáticamente si el usuario no lo customizó.

---

## H28 — "Sólo manuales ✋" siempre vacío 🟡

**Categoría**: `ui-engañosa` post-deprecación.

**Archivo**: `src/ui/aula_cronograma_view.py`, filtro "Sólo manuales".

**Descripción**: el filtro busca `HorarioDB` cuyo `aula_id` fue
seteado manualmente. Antes de la deprecación de clases puntuales,
había flags `aula_asignada_manualmente` que hacían efecto. Hoy nadie
setea ese flag desde la UI — el filtro siempre da vacío.

**Fix propuesto**: ocultar el filtro hasta que vuelva la edición
manual, o marcar `HorarioDB` cuando se cambie desde el dialog de
cambio de aula.

---

## H29 — Filtro de cuatri en Inscriptos inconsistente 🟡

**Categoría**: `ui-engañosa`.

**Archivo**: `app/pages/7_📈_Inscriptos.py`.

**Descripción**: la columna Cuatrimestre del editor tiene opciones
`["1C", "2C", "Anual"]` (permite editar `"Anual"`), pero el filtro
superior sólo ofrece `["Todos", "1C", "2C"]` — no hay filtro directo
para ver "sólo Anuales". Si el usuario carga registros anuales, no
puede aislarlos con el filtro.

**Fix propuesto**: agregar `"Anual"` al selectbox del filtro.

---

## H30 — `data_editor` de carrera asignada pierde valor si carrera no existe 🟡

**Categoría**: `dx-hueco` / bug latente.

**Archivo**: `src/ui/plan_grilla_editor.py` línea ~1191.

**Descripción**: la columna "Carrera asignada" del `data_editor` de
comisiones tiene opciones `["—"] + [codigos_actuales]`. Si por algún
motivo (típicamente porque se borró la carrera después de que la
comisión la tenía asignada) el valor previo no está en la lista, el
`data_editor` lo **descarta silenciosamente** en el próximo render.

**Fix propuesto**: incluir el valor previo en las opciones aunque la
carrera ya no exista, o mostrar un warning al detectar la
inconsistencia.

---

## H31 — Change log usa `utcnow()` sin zona horaria 🟡

**Categoría**: `bug` de presentación.

**Archivo**: `src/services/change_log_service.py` `_fmt_when` y
`src/ui/historial_widget.py`.

**Descripción**: los timestamps se guardan y muestran en UTC. Los
usuarios están en Rosario (GMT-3). Las fechas absolutas (>30 días)
muestran horas UTC sin aclararlo.

**Fix propuesto**: convertir a `America/Argentina/Buenos_Aires` en la
presentación, o agregar sufijo "UTC" al string.

---

## H32 — `emit_event` explícito cubre 3 líneas, otros equivalentes no 🟡

**Categoría**: `dx-hueco`.

**Descripción**: hay 3 `emit_event` explícitos en `plan_grilla_editor.py`
y `plan_materia_editor.py` para `HorarioDB.virtual` y
`ComisionDB.carrera_asignada`. Pero otras UIs equivalentes (el diálogo
de `_dialog_editar_horario` en el inspector de franja del panel de
aulas) hacen cambios idénticos sin emit_event. El historial queda
parcial.

**Fix propuesto**: extraer un helper `emit_horario_virtual_change` y
usarlo desde todas las UIs que tocan `HorarioDB.virtual`.

---

## H33 — Snapshots de validación stale sin indicador claro 🟡

**Categoría**: `ui-engañosa`.

**Descripción**: `is_validation_stale` compara conteos de entries y
dictados vigentes contra los que había al guardar el snapshot. Si
cambió algo, marca stale. Pero la UI no siempre lo indica claro —
en algunas vistas se muestra el badge de la validación como
"vigente" aunque el snapshot esté desactualizado.

**Fix propuesto**: revisar todos los renders del badge y mostrar
🟡 stale cuando corresponde.

---

## H34 — Historial "Por entidad" cortado en 50 sin indicador 🟡

**Categoría**: `ui-engañosa`.

**Archivo**: `src/services/change_log_service.py`
`get_log_for_entity`.

**Descripción**: limit hardcoded a 50, sin mensaje "hay más" ni
control para aumentarlo.

**Fix propuesto**: agregar un input de "cantidad a mostrar" al widget
Por entidad, o mostrar "..." con "cargar más".

---

## H35 — "Asociar" en "Sin matchear" suma silenciosamente 🟡

**Categoría**: `ui-engañosa`.

**Archivo**: `app/pages/7_📈_Inscriptos.py` sección "Sin matchear".

**Descripción**: al asociar un código no matcheado a una `MateriaDB`,
si el destino ya tenía datos para el mismo (año, cuatri), la operación
**suma** los inscriptos existentes al valor asociado. Sin warning
previo.

**Fix propuesto**: mostrar preview antes de asociar diciendo "El
destino ya tiene N inscriptos para (2024, 1C). ¿Sumar M nuevos = N+M
o reemplazar con M?"

---

## H36 — Comisiones template huérfanas quedan vivas silenciosamente 🟡

Consecuencia de H03. Se lista aparte porque es el hallazgo
"observable" (basura acumulada en la tabla `comisiones` con
`schedule_id` inexistente). Ver fix propuesto en H03.

---

## Preguntas abiertas para el equipo (no son bugs, pero requieren
decisión)

- **PQ01**: ¿debería la UI llamar `clear_aula_horario` automáticamente
  al mover un slot? Ver H02.
- **PQ02**: ¿debería `promover_a_regla` sincronizar el ciclo actual o
  se deja como decisión explícita? Hoy sólo cambia el catálogo.
- **PQ03**: ¿multi-usuario en SQLite? Si dos operadores tocan la app
  simultáneamente, ¿cómo se resuelven conflictos?
- **PQ04**: ¿retention del `ChangeLogDB`? Crece indefinidamente.
- **PQ05**: ¿cómo se maneja un cambio de plan a mitad de cuatrimestre?
  El modelo lo permite (dos planes por ciclo con `activo=False` uno);
  la UI no lo documenta.
- **PQ06**: ¿debería existir una página "🔍 Checklist de cierre" que
  agregue los ítems de verificación pre-inicio de cuatri (ver F7 de
  `_auditoria/05_flujos_globales.md`)?
- **PQ07**: ¿por qué el override de recursado en la materia es un
  selectbox de 3 estados en vez de checkbox tri-state? Es
  funcionalmente correcto pero puede confundir.

---

## Cómo se generó este documento

Este documento consolida los hallazgos de 5 agentes que auditaron el
código el 2026-07-30. Cada hallazgo referencia archivos y líneas del
código real (no de la doc). El reporte extendido de cada agente está
en:

- `project/3. Manual de Usuario/_auditoria/01_catalogo_maestro.md`
- `project/3. Manual de Usuario/_auditoria/02_ciclos_cronogramas.md`
- `project/3. Manual de Usuario/_auditoria/03_planes_asignacion.md`
- `project/3. Manual de Usuario/_auditoria/04_inscriptos_historial.md`
- `project/3. Manual de Usuario/_auditoria/05_flujos_globales.md`

Estos archivos son temporales y se pueden borrar tras redactar el
manual (contienen la parte de auditoría; los hallazgos ya están
consolidados acá).
