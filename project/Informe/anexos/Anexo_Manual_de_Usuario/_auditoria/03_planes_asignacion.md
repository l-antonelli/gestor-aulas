# Auditoría — Planes de Cursada + Asignación de Aulas (LP)

> Fecha de auditoría: 2026-07-30
> Fuente única de verdad: código fuente en `src/` y `app/`. Los documentos
> del proyecto (`WORKFLOW.md`, `ASIGNACION_IMPL.md`, `requerimientos.md`,
> `asignacion-aulas-LP.md`) se contrastan al final.
> Alcance: página `app/pages/5_📊_Planes.py` y todo el aparato que la
> alimenta (planificaciones, comisiones, horarios, solver LP y
> diagnóstico).

---

## 1. Modelo mental

La página `5_📊_Planes` es la boca de un flujo de datos con cinco capas
que hay que entender antes de poder describir cualquier operación de
usuario.

### 1.1 Cadena Cronograma → Plan → Comisiones → Horarios → Aulas

```
ScheduleDB (cronograma)
    ├── ScheduleEntryDB (una fila por bloque día/hora en el archivo)
    │       └── comision_id ─────→ ComisionDB (schedule_id, "template")
    │
    └── (al generar el plan)
              │  preview_plan_from_schedule  +  generate_plan_from_preview
              ▼
PlanificacionCursadaDB (plan de cursada, activo=False por default)
    ├── ComisionDB (plan_cursada_id, clones de las templates)
    │       └── HorarioDB (día, hora_inicio, hora_fin, tipo_clase,
    │                       virtual, aula_id)   ← ítem que asigna el LP
    │
    └── (al activar el plan)
              │  generate_clases_for_plan
              ▼
ClaseDB (una instancia por HorarioDB × cada fecha del ciclo)
```

Fuentes: `PlanificacionCursadaDB`, `ComisionDB`, `HorarioDB`, `ClaseDB`
en `src/database/models.py`. Servicio en
`src/services/plan_generation_service.py`.

### 1.2 XOR de comisión: cronograma vs. plan

`ComisionDB` tiene dos FKs opcionales excluyentes:

- `schedule_id != None, plan_cursada_id == None` → comisión "template" de
  un cronograma. Define atributos (nombre, cupo, `carrera_asignada`,
  descripción) que las entries del cronograma referencian.
- `schedule_id == None, plan_cursada_id != None` → comisión viva de un
  plan de cursada. Es la que apunta cada `HorarioDB`.

El XOR **no** es un constraint de la base de datos (SQLite no soporta
`CHECK` con `OR` bien): lo valida el service layer
(`src/services/comision_service.py`, docstring del modelo).

Al generar el plan, `clone_comisiones_for_plan` (o el path equivalente
dentro de `generate_plan_from_preview`) **duplica** las comisiones
template: nuevos IDs, `plan_cursada_id` seteado, `schedule_id=None`,
preservando `nombre`, `cupo`, `coef_asignacion`, `descripcion` y —
importante— `carrera_asignada`. **Ciclo de vida independiente**:
modificar una comisión del plan no toca la del cronograma origen.
Requerimiento formal: `RF-COMISION-01/02`.

### 1.3 Virtualidad jerárquica (regla "nivel más específico manda")

Tres niveles opcionales resueltos vía `resolve_virtual` en
`src/services/resolucion_jerarquica.py`:

1. `HorarioDB.virtual` (Optional[bool])
2. `DictadoDB.virtual` (Optional[bool]) — resuelto por
   `(materia_codigo, ciclo_id)` vía `DictadoCicloDB`
3. `MateriaDB.virtual` (bool concreto, raíz)

`None` en cualquier nivel = heredar del padre; `True`/`False` fuerzan.
El LP y todos los diagnósticos usan esta resolución para **excluir**
horarios virtuales del modelo. Consecuencia práctica: marcar virtual un
horario individual desde el inspector de franja descomprime esa franja
sin mover el horario.

### 1.4 "Patrón semanal" vs. "cache técnico"

- **Patrón** (`HorarioDB.aula_id`): fuente de verdad de la asignación
  del LP. El LP escribe acá y también, si el `tipo_clase` estaba en
  `None`, lo persiste.
- **Cache** (`ClaseDB.aula_id`, `ClaseDB.tipo_clase`,
  `ClaseDB.aula_asignada_manualmente`): heredan del patrón vía
  `apply_solution`. Filtra `fecha >= fecha_desde` y `executed=False`;
  respeta `aula_asignada_manualmente=True` cuando el toggle está prendido.

**Desde 2026-07-07 (deprecación de clases puntuales)** el usuario no
edita `ClaseDB` en la UI: no hay tab "Clases", no hay dialog que setee
el flag manual. Sin embargo el flag y la lógica de "respetar manuales"
siguen vivos en el modelo y en el LP — quedan como capacidad latente
por si se reintroduce en el futuro (`RF-LP-05`, marcado 🚫 Sin UI).

### 1.5 Restricciones de sede (R10) y override por comisión

`build_inputs` (líneas 318–367 de
`src/services/asignacion_aulas_service.py`) filtra pares
`compat[(h, a)]` por sede admisible:

1. Si la comisión del horario tiene `carrera_asignada` seteado →
   `sedes_admisibles_para_carrera(carrera_asignada)`.
2. Si no → `sedes_admisibles_para_materia(materia_codigo)`, que decide
   por regla habitual (materia exclusiva ⇒ sedes de la carrera dueña;
   materia común ⇒ sede default de comunes).
3. **Excepción**: si el aula está en `MateriaLaboratorioDB` para la
   materia, el aula pasa aunque no esté en sedes admisibles (lab
   compatible prevalece).
4. **Fallback**: si `sedes_admisibles_*` devuelve `None`, no hay
   restricción de sede para ese horario.

### 1.6 Entidad `LPRunDB` (snapshot histórico)

Cada corrida del LP inserta una fila en `LPRunDB` con:

- Config aplicada (`lambda_over`, `lambda_under`, `tol_over`,
  `tol_under`, `activar_alpha`, `respetar_ediciones_manuales`,
  `timeout_seconds`, `fecha_desde`).
- Resultado (`status`, `objective_value`, contadores).
- `details_json` con detalle por horario, heatmap de carga, heatmap por
  sede, α propuestos, diagnóstico de infactibilidad estructural, y —
  cuando corresponde — resultado del IIS por relajación.

La UI muestra por default el último run (`get_latest_run`) pero conserva
todos para auditoría.

---

## 2. Walkthrough por tab de la página `5_📊_Planes`

Definidos en `app/pages/5_📊_Planes.py` (líneas 74–81). En orden de
aparición:

### 2.1 📥 Generar Plan (wizard de 2 pasos)

**Propósito**: crear un `PlanificacionCursadaDB` a partir de un
cronograma **validado y vigente**. Emite `activo=False` (borrador).

**Paso 1 — Selección** (líneas 488–633):

- Selector de ciclo.
- Selector de cronograma filtrado por estado: sólo aparecen los con
  badge **🟢 Validado y vigente** (`get_latest_validation` sin
  `is_validation_stale`). Los "⚪ Sin validar" y "🟡 Validado pero
  desactualizado" quedan listados en un expander pero no se pueden
  elegir.
- Nombre del plan (default: `"Plan {ciclo_id} ({sched.nombre})"`).
- Descripción opcional.
- Método de forecast default (`media_movil` | `drift` | `ses`).
- Botón **"Crear borrador y continuar →"** llama
  `preview_plan_from_schedule` + `generate_plan_from_preview` en la
  misma transacción; el plan queda persistido y se pasa a Paso 2.

**Paso 2 — Edición** (líneas 636–702):

Embebe el editor de "Detalle del Plan" (mismo `_render_plan_editor`)
con `key_ns="wizard"` para evitar colisiones de session_state con el
tab Detalle. Botones:

- **🗑️ Cancelar (borra el plan)**: `delete_plan_cascade`
  (clases → horarios → comisiones → plan). No hay confirmación
  intermedia.
- **✅ Confirmar y salir del wizard**: pre-selecciona el plan en el tab
  Detalle vía `st.session_state["planes_sel_plan"] = _wizard_plan_id`
  y limpia keys del wizard.

Si el usuario cierra la pestaña sin apretar nada, el borrador queda
persistido y aparece en Vista General.

### 2.2 📋 Vista General

**Propósito**: listar todos los planes del ciclo seleccionado (activo o
borrador).

Por cada plan (loop en líneas 726–800), un contenedor con:

- **Info**: nombre, badge (🟢 ACTIVO / ⚪ inactivo), descripción,
  nombre del cronograma origen.
- **Métricas**: Materias distintas, Comisiones, Horarios (via `count`
  sobre `ComisionDB` + `HorarioDB`).
- **Acciones**:
  - **Activar** (si `activo=False`): llama `activate_plan` — desactiva
    los otros planes del ciclo y activa este. **Nota**: la activación
    real que **genera `ClaseDB`** ocurre desde el panel de validación
    del tab Detalle (WORKFLOW.md § 8), no desde acá. `activate_plan`
    en `plan_generation_service` solo cambia el flag `activo`.
  - **Eliminar**: hace cascada manual inline (clases → horarios →
    comisiones → plan). No usa `delete_plan_cascade` (código
    duplicado; ver Sección 8).

### 2.3 🔍 Detalle del Plan

**Propósito**: editor central del plan. Selector de ciclo → plan,
después renderiza `_render_plan_editor(sel_plan_id, ...)`.

El editor (`_render_plan_editor`, líneas 188–301) muestra:

1. **Metadata** (form): nombre, descripción, método de forecast default.
2. **Estadísticas**: 4 métricas (Materias, Comisiones, Horarios,
   Horarios con aula).
3. **🔧 Acciones del plan** (`_render_acciones_del_plan`):
   - "Auto-completar tipo de horarios por materia" (expander). Preview
     live que dice cuántos horarios cambiarían de `None` a
     `teorica` o `laboratorio` según las horas declaradas de la
     materia (`hteo>0, hlab=0` → teórica; recíproco). Botón "Aplicar"
     confirma. Nota: `build_inputs` del LP aplica el mismo override en
     memoria como red de seguridad — no es bloqueante, sólo
     recomendado para que otras vistas muestren bien el tipo.
4. **Validaciones** (`validation_ui.render_validation(source='plan',
   plan_id=...)`): panel unificado que incluye cobertura, conflictos
   de horario, editor inline por materia (`plan_materia_editor`),
   forecasts, particiones teoría/lab, activación gate. Es el bloque
   más pesado de la página; su detalle exhaustivo queda para otra
   auditoría.

### 2.4 📋 Grilla Horaria

**Propósito**: espejo del editor de "Cronogramas → Editar" pero sobre
`ComisionDB` + `HorarioDB` del plan. Renderizado por
`plan_grilla_editor.render_plan_grilla_editor`.

Ofrece dos modos:

- **Por grupo**: filtros Carrera/Año/Cuatri/Tipo + "Excluir comunes" +
  "Materias a mostrar". Calendario semanal editable (drag / resize /
  click / select) coloreado por comisión.
- **Por materia**: búsqueda por código o nombre → editor por materia
  con calendario + `data_editor` de horarios + `data_editor` de
  **comisiones** (líneas 1071–1214). En el segundo se editan `numero`,
  `nombre`, `cupo`, `coef_asignacion`, `carrera_asignada`,
  `descripcion` — el cambio de `carrera_asignada` emite evento de
  `ChangeLogDB` con `origin=ui:planes` (importante para el LP porque
  reordena sedes admisibles). Borrado de comisión bloquea si tiene
  horarios o entries asociados (`delete_comision` de
  `comision_service`).

Los dialogs "Editar entrada" / "Nueva entrada" permiten crear
comisiones al vuelo desde el calendario.

### 2.5 🏛️ Aulas

**Propósito**: entrada del LP de asignación de aulas.
Renderizado por `asignacion_panel.render_panel(session, plan_id, ...)`
(ver Sección 4).

### 2.6 ⚙️ Configuración

**Propósito**: parámetros globales de la grilla temporal
(`ConfiguracionHoraria`, PK=1):

- **Granularidad (minutos)**: 5–60. Define el paso de las franjas del
  heatmap y de los slot pickers.
- **Hora inicio operativo** y **Inicio última franja** (nota: es el
  inicio de la última franja, no el fin operativo, para que 23:00
  pueda cubrir 23:00-00:00).
- **Días operativos** (multiselect, default Lu–Sá).

Preview inline con la lista de todas las franjas generadas.

---

## 3. Flujo típico end-to-end

Camino "camino feliz" de cronograma a plan con aulas asignadas:

1. **Precondición**: en Cronogramas → ✅ Validar, el cronograma origen
   tiene badge **🟢 Validado y vigente** para el ciclo objetivo.

2. **📥 Generar Plan → Paso 1**:
   - Elegir ciclo, cronograma, poner nombre "Plan 2025-1C — vNN",
     dejar forecast en `media_movil`.
   - Apretar "Crear borrador y continuar →". Aparece toast tipo
     `"Borrador creado: 47 comision(es), 82 horario(s)."`

3. **📥 Generar Plan → Paso 2**: revisar validaciones, ajustar
   comisiones o coeficientes que hayan quedado raros (particularmente
   materias marcadas con flag `uncertain` o `needs_more_comisiones`
   en el preview). Apretar **"✅ Confirmar y salir del wizard"**.

4. **🔍 Detalle del Plan**: verificar el panel de validación (checks
   por materia, conflictos, particiones). Si hay horarios con
   `tipo_clase=None` en materias mono-modales, apretar
   **"🔧 Acciones del plan → ✅ Aplicar auto-completado"**.

5. **📋 Grilla Horaria** (opcional): resolver conflictos manualmente si
   quedaron. Cada movimiento persiste inmediato — no hay modo
   "preview + guardar".

6. **🏛️ Aulas**:
   - Verificar precheck: si el plan tiene al menos un horario, pasa.
   - Ajustar `LPConfig` (default: `λ_over=10`, `λ_under=1`,
     `tol_over=0`, `tol_under=0.2`, `activar_alpha=False`,
     `respetar_ediciones_manuales=True`, `timeout=300`).
   - Elegir `fecha_desde` (default hoy, o fecha_inicio del ciclo si
     hoy es anterior).
   - Apretar **"🚀 Asignar aulas"** — spinner, luego el summary del
     último run aparece con status.

7. Si sale `optimal`: revisar heatmap por sede (advertencias >80%),
   tabla por horario, candidatas a partir comisión. Si algo no
   convence, editar y volver a correr (opcionalmente con
   `respetar_ediciones_manuales=False` para pisar todo).

8. Si sale `infeasible`: leer diagnóstico estructural (Sección 5).

9. **Activación del plan** (fuera del tab Aulas): desde el panel de
   Validación del tab Detalle, botón "Activar plan" — genera
   `ClaseDB` para todo el cuatri (`generate_clases_for_plan`).

---

## 4. El asignador (LP) desde la perspectiva del usuario

Sin jerga técnica: qué hace, qué le pedís, y qué te devuelve.

### 4.1 Qué hace

Le busca un **aula del edificio de la facultad** a cada horario
semanal presencial del plan. La búsqueda minimiza dos "costos":

- **Sobre-ocupación**: alumnos esperados por encima de la capacidad del
  aula asignada. Se castiga con peso alto (`λ_over=10` por default).
- **Sub-utilización**: aula demasiado grande para los inscriptos. Se
  castiga con peso bajo (`λ_under=1` por default).

**Restricciones que se respetan siempre** (no configurables):

- Cada horario recibe **exactamente un aula** (R1).
- El aula tiene que ser del **tipo correcto**: teóricas o anfiteatros
  para clases teóricas; laboratorios compatibles con la materia para
  clases de lab (R3, R6).
- **Ningún aula se dobla** en la misma franja (R4).
- Si la materia declara horas de teoría y horas de laboratorio, la
  **suma de duraciones de los horarios** que el LP marque como lab
  tiene que coincidir con `hlab` declarado (R5).
- El aula tiene que estar en una **sede admisible** para la carrera de
  la materia — con excepción de labs compatibles, que siempre pasan
  (R10).

**Horarios que el LP ignora** (expander "ℹ️ Qué horarios entran a la
asignación"):

- Materias marcadas como virtuales en el catálogo.
- Dictados del ciclo con `virtual=True`.
- Horarios individuales con `virtual=True` (jerarquía "nivel más
  específico manda", ver 1.3).

### 4.2 Cuándo lo corre

Sólo cuando el usuario aprieta **"🚀 Asignar aulas"** en el tab Aulas.
No hay corrida automática ni disparo por trigger. Cada apretón crea un
nuevo `LPRunDB`.

### 4.3 Cómo interpretar el resultado

El summary muestra un **status humano**:

- **✅ resuelta** (`optimal`): el LP encontró la mejor asignación
  posible dentro de la config elegida. Además persiste las aulas al
  patrón (`HorarioDB.aula_id`) y las propaga al cache (`ClaseDB`).
- **❌ no se pudo resolver** (`infeasible`): no existe ninguna
  asignación que cumpla todas las restricciones duras. Se muestra un
  diagnóstico. **Nada se persiste**.
- **⏱️ se agotó el tiempo** (`timeout`): pasó el `timeout_seconds` sin
  encontrar una solución óptima. Idem `infeasible` desde el punto de
  vista de persistencia.
- **⚠️ hubo un error** (`error`): excepción del solver. Se persiste el
  run con el mensaje de error.

Métricas del summary:

- **Horarios totales / Asignados**: idealmente iguales.
- **Clases actualizadas**: cantidad de `ClaseDB` que recibieron el
  aula del patrón (filtrado por `fecha >= fecha_desde`,
  `executed=False`, respetando manuales).
- **Sobre-ocupados / Sub-utilizados**: horarios cuyo aula excede o
  desperdicia capacidad — se cuentan aunque el LP haya resuelto, es
  información diagnóstica.
- **Costo total** (`objective_value`): suma ponderada de sobre y sub.
- **Tiempo de resolución (s)**.
- **Manuales respetadas**: contador del toggle "respetar ediciones
  manuales". Con la deprecación de clases puntuales este número es
  siempre 0 en la práctica (nadie edita `ClaseDB.aula_asignada_manualmente`),
  pero la métrica queda expuesta.

### 4.4 Herramientas de análisis (siempre visibles bajo el summary)

- **📊 Heatmap de carga (día × franja)** (expander, colapsado por
  default): matriz día × franja mostrando cuántas clases están activas
  simultáneamente. Filtro por tipo declarado en el cronograma
  (Todas / Teórica fijada / Laboratorio fijado / Sin determinar). Los
  huecos entre clases consecutivas se ven como 0 (no se colapsan).

- **🔥 Mapa de saturación por sede** (expander, expandido si el run
  no es óptimo o si hay saturación >100%): para cada sede con demanda,
  mini-heatmap **demanda/oferta** con escala discreta:
  - 🟢 verde ≤80%
  - 🟡 amarillo 80–100%
  - 🔴 rojo >100% (saturación segura: más horarios que aulas)
  - Categoría filtrable: "peor caso" | "solo teóricas" | "solo
    laboratorios".
  - **Live-refresh**: se recomputa contra la DB en cada rerun
    (`_recompute_heatmap_por_sede_live`), no depende del snapshot del
    LPRun. Al marcar virtual un horario desde el inspector, el
    heatmap se actualiza sin correr de nuevo el LP.

- **🔍 Inspeccionar franja** (expander, colapsado): dado una sede, un
  tipo de aula, un día y una o varias franjas de 15 min, muestra en
  un **calendario semanal coloreado por carrera** todos los horarios
  que demandan esa sede en ese rango. Cada bloque incluye botón
  **"✏️ Editar"** que abre `_dialog_editar_horario`. También indica el
  **exceso** (cuántos horarios habría que mover como mínimo para
  descomprimir). Nota: sólo mira **sedes admisibles del horario**;
  los horarios cuya carrera no usa esa sede no aparecen.

- **📅 Cronograma por aula** (expander al final del panel):
  `aula_cronograma_view.render_aula_cronograma` — vista por aula con
  selector de semana; muestra choques y divergencias de la asignación
  del patrón.

### 4.5 Configuración avanzada

Todos los inputs del form (`_render_config_form`, líneas 65–171):

| Input | Default | Efecto |
|---|---|---|
| **Aplicar desde la fecha** | Hoy (o `ciclo.fecha_inicio` si es futuro) | Las `ClaseDB` con `fecha < fecha_desde` quedan intactas; ídem las `executed=True`. |
| **Peso de sobre-ocupación** (`λ_over`) | 10.0 | Cuanto más alto, más importante evitar aulas chicas. |
| **Tolerancia de sobre-ocupación** (`tol_over`) | 0.0 | Margen relativo antes de penalizar. |
| **Peso de sub-utilización** (`λ_under`) | 1.0 | Cuanto más alto, más importante evitar aulas grandes. |
| **Tolerancia de sub-utilización** (`tol_under`) | 0.20 | 20% de vacío gratis. |
| **Respetar ediciones manuales** | ON | Preserva `ClaseDB.aula_asignada_manualmente=True`. Ver Sección 6.1. |
| **Tiempo máximo (s)** (`timeout_seconds`) | 300 | Corte del solver. |
| **Redistribuir pesos entre comisiones (avanzado)** (α) | OFF | Ver Sección 5.3. |

---

## 5. Casos comunes

### 5.1 Optimal → todo asignado

- Toast "Asignación resuelta en X.Xs. Y clases actualizadas."
- Tabla por horario (`Materia | Comisión | Día | Inicio | Fin | Aula
  | Sede | Cap | Esperados | Δ | Estado`) coloreada:
  - 🟢 verde: `ok`
  - 🟡 amarillo: `sub` (aula grande dentro de la tolerancia
    excedida)
  - 🔴 rojo: `sobre` (aula chica)
- Sección **🪓 Candidatas a partir comisión**: materias donde la suma
  de over es alta. Sugerencia: subir `n_comisiones` para repartir
  esperados en más aulas.

### 5.2 Infeasible → cómo diagnosticar y qué hacer

El resultado no persiste asignación. El panel muestra **inventario de
aulas** y hasta seis secciones en orden de utilidad:

1. **Horarios sin aula compatible**: causa atómica. Muestra materia,
   día, franja, tipo, y razón concreta. Acciones sugeridas por la
   propia UI:
   - Cargar laboratorios compatibles (página Materias).
   - Marcar el horario como teórica en el cronograma.
   - Agregar aulas del tipo correcto.

2. **Franjas con faltante de aulas de un tipo específico**: tabla con
   día, franja, tipo problemático, necesita/disponible, materias.
   Acciones:
   - Marcar virtual un dictado de recursado (Ciclos → Dictados).
   - Agregar aulas.
   - Ampliar `MateriaLaboratorioDB`.
   - Cambiar horarios a otras franjas.

3. **Hall violators**: grupos de clases simultáneas con lista chica de
   aulas compatibles compartidas. Refina pigeonhole (aunque haya
   muchas aulas totales, un subgrupo puede empatar). Muestra las
   aulas exactas del cuello de botella.

4. **Franjas saturadas (pigeonhole global)**: cota más débil que 2 y
   3 pero cubre casos residuales. Muestra desglose `T:x L:y ?:z`.

5. **Diagnóstico cruzado (IIS por relajación)**: sólo aparece cuando
   las cotas estructurales 1–4 vinieron vacías y el solver aún así
   tiró `infeasible`. Relaja R4/R5/R6 por separado y ve cuál al
   ignorarse permite resolver — esa es la causa probable
   ("**Causa probable: R4**" en rojo). Incluye filtro de **falsos
   positivos** (R5/R6 aparentan arreglar por libertad extra cuando la
   causa real es R4; se descartan).

**Herramientas complementarias** siempre visibles:

- El heatmap por sede muestra las celdas rojas exactas.
- El inspector de franja + editor de horario (dialog) permite mover
  un horario en preview (chequea saturación destino) y decidir si
  aplicar.
- Marcar virtual un horario desde el dialog es la forma más rápida de
  descomprimir sin mover nada (recursado por Zoom, típico caso).

### 5.3 Editar manual una asignación tras correr el LP

Dos caminos:

1. **📅 Cronograma por aula** (dentro del tab Aulas, expander al
   final): `aula_cronograma_view` con dialog "Cambiar aula" para
   cada horario. Persiste vía `cambiar_aula_horario` (patrón). Ver
   Sección 6.1.

2. **📋 Grilla Horaria / 🔍 Detalle → editor por materia**: se pueden
   mover, eliminar o crear horarios directamente; la asignación
   previa queda en `HorarioDB.aula_id`, pero si el slot cambia (día/
   hora) el aula sigue apuntando y podría ser inconsistente. La
   política correcta es **volver a correr el LP** después de mover
   slots.

### 5.4 Cambiar carrera asignada de una comisión

Desde 🔍 **Detalle del Plan → materia → tabla de comisiones**
(alternativamente desde 📋 Grilla → modo Por materia). Columna
"Carrera asignada": selectbox con "—" o el código de una carrera. Al
cambiar:

- Se actualiza `ComisionDB.carrera_asignada` vía `update_comision`.
- Se emite un evento en `ChangeLogDB` con `origin=ui:planes`.
- La próxima corrida del LP resolverá las sedes admisibles vía la
  carrera nueva.

Semántica: la comisión completa se orienta a esa carrera. Todos sus
horarios heredan la restricción. Caso típico documentado
(`RF-LP-15`): comisión de una materia común organizada para alumnos
de otra carrera de otra sede (ej. Física III comisión electrónica en
Siberia en vez de Pellegrini).

### 5.5 Modificar cupos

En 🔍 Detalle → editor por materia (`plan_materia_editor`) o en 📋
Grilla → tabla de comisiones. Columna "Cupo". El campo va a `ComisionDB.cupo`
directamente. **No** entra al LP: el LP usa **capacidades de aulas**
(`AulaDB.capacidad`) y **inscriptos esperados** (forecast × coef), no
el cupo de la comisión — que sólo es un contrato administrativo.

**Nota importante del WORKFLOW.md § 6.3**: el cupo por comisión "se
mantiene en DB con default 30 pero no se edita más en el UI" — pero el
código actual sí lo expone en el `data_editor` de comisiones del
plan_grilla_editor (línea 1082–1091). Discrepancia menor (ver
Sección 8).

---

## 6. Gotchas

### 6.1 "Capacidad latente" vs. funcionalidad expuesta

El sistema tiene múltiples piezas que sobreviven en el código pero **la
UI ya no las expone**:

- **`ClaseDB` como entidad editable**: deprecada 2026-07-07. El tab
  "Clases" fue removido, los dialogs `aplicar_edicion_manual`,
  `cambiar_tipo_clase_puntual` fueron eliminados. Pero `ClaseDB`
  sigue existiendo como cache técnico y `apply_solution` propaga a
  ella.
- **`ClaseDB.aula_asignada_manualmente`**: el LP lo respeta si el
  toggle está prendido. **Ningún flujo de UI actual lo setea en
  True**. Consecuencia: la métrica "Manuales respetadas" es siempre
  0 en el flujo normal, y el toggle "Respetar ediciones manuales" no
  hace nada visible hoy (pero está listo por si vuelve a habilitarse
  la edición puntual).
- **`generate_plan_from_schedule`** (path legacy, sin templates de
  comisión): sigue existiendo como función pública pero la UI usa
  `generate_plan_from_preview`. El wizard nunca llama al legacy.

### 6.2 Interacciones con override de sede a nivel comisión

- El override vive en `ComisionDB.carrera_asignada`, **no** en
  `HorarioDB`. Consecuencia: no se puede mezclar dentro de una
  misma comisión "un horario en sede A, otro en sede B".
- `_recompute_heatmap_por_sede_live` maneja overrides **mixtos por
  materia** (comisiones de la misma materia con overrides distintos)
  con un fallback conservador: usa las sedes de la materia. En ese
  caso el heatmap live puede sub-reportar demanda respecto al LP real
  (que sí aplica override por comisión). Es un compromiso conocido
  (comentado en el código, líneas 249–275).
- La UI de edición de la columna "Carrera asignada" en el
  `data_editor` (plan_grilla_editor línea 1191) sólo lista `["—"]
  + [codigos]`. Si la carrera no existe en la base, el valor previo
  se pierde silenciosamente al re-render.

### 6.3 Efectos de mover un horario (día/hora)

- `apply_horario_edits` (plan_generation_service línea 629) actualiza
  `HorarioDB.dia`, `hora_inicio`, `hora_fin`, `comision_id`,
  `tipo_clase`, `virtual`. **NO limpia `aula_id`**. Si el operador
  mueve un horario a otra franja, el `HorarioDB.aula_id` viejo queda,
  aunque ahora conflictúe con otros horarios en la nueva franja.
- El servicio `clear_aula_horario` existe para este caso pero no se
  llama automáticamente desde `apply_horario_edits`.
- Solución práctica: **re-correr el LP** después de mover slots. El
  LP volverá a asignar todo (y respetará el patrón nuevo). Si hay
  choques residuales, sale infeasible con diagnóstico claro.

### 6.4 Persistencia inmediata vs. preview

Casi todas las ediciones del plan **persisten al momento** (auto-save,
`on_change`, o form_submit sin confirmación intermedia):

- Metadata del plan → guardado con botón "Guardar" del form.
- `data_editor` de horarios y de comisiones → auto-save via
  `on_change`.
- Auto-completar tipos → preview live, aplicar con botón único.
- Eliminar plan en Vista General → **NO tiene confirmación**.
- Cancelar wizard → **NO tiene confirmación** (borra en cascada).

Excepciones con preview:

- Dialog "Editar horario" (`_dialog_editar_horario` en el inspector):
  muestra saturación destino + conflictos que se agregarían/
  resolverían **antes** del botón "Confirmar y aplicar".
- Toggle α: la corrida del LP con `activar_alpha=True` propone α*, y
  se aplica sólo si el usuario aprieta "Aplicar nuevos pesos"
  (`aplicar_alpha_propuesto`). "Descartar" deja los pesos viejos pero
  el aviso indica que las aulas asignadas no son coherentes.

### 6.5 Auto-completado de tipo — red de seguridad

Si el usuario no aplica el auto-completado, `build_inputs` del LP lo
aplica igual en memoria (líneas 249–256 de `asignacion_aulas_service`).
Consecuencia: el LP corre con menos variables `t[h]` y no falla, pero
las **otras vistas** (heatmap filtrado por tipo, editor por materia,
validaciones) siguen mostrando "sin determinar". Por eso el warning
sugerente aparece en la parte alta del panel de aulas cuando hay
horarios auto-completables.

### 6.6 `activate_plan` no genera `ClaseDB`

En el tab Vista General el botón "Activar" llama
`plan_generation_service.activate_plan`, que sólo cambia el flag
`activo=True` y desactiva otros planes del ciclo. **No genera
`ClaseDB`**. La generación de clases ocurre desde el panel de
Validación en el tab Detalle (`WORKFLOW.md § 8`) — que también tiene
un botón "Activar plan" pero con lógica distinta (revisa conflictos
como gate y llama `generate_clases_for_plan`).

**Consecuencia**: activar desde Vista General deja el plan activo
pero sin `ClaseDB` materializadas. Es probable que sea un bug de
UX (ver Sección 9, "Preguntas abiertas").

### 6.7 Wizard: cancelar sin doble confirmación borra el plan

En la línea 649–664 del wizard, el botón "🗑️ Cancelar (borra el plan)"
llama `delete_plan_cascade` directamente. Sin diálogo intermedio, sin
segundo click. La caption dice "No se puede deshacer" pero
técnicamente no hay confirmación explícita — el usuario puede darle
click accidentalmente.

### 6.8 IIS y falsos positivos

El diagnóstico cruzado (IIS por relajación) es **caro** (3× tiempo
extra de solver). Sólo se dispara cuando:

1. El solver dice `infeasible`.
2. Las cotas estructurales (secciones 1–4 del diagnóstico) están
   todas vacías.

Cuando dispara, filtra falsos positivos (R5/R6 aparentan arreglar por
libertad extra cuando la causa es R4). La "causa principal" mostrada
puede ser `None` si nada arregla al relajarse — significa
"infactibilidad combinada".

---

## 7. Errores y warnings (textos concretos)

Textos que el usuario puede ver, agrupados por origen.

### 7.1 Wizard de generación

- **"No hay ciclos registrados. Crea uno en la pagina de Ciclos."**
- **"No hay cronogramas cargados para este ciclo. Cargá uno desde
  📅 Cronogramas."**
- **"Ningún cronograma del ciclo está validado y vigente. Andá a
  📅 Cronogramas → ✅ Validar para habilitar uno."**
- Toast: **"Borrador creado: N comision(es), M horario(s)."**
- Toast: **"Plan borrador eliminado."**
- Toast: **"Plan listo. Andá a 🔍 Detalle del Plan para seguir
  editándolo."**
- Toast: **"Metadata actualizada"**
- **"El plan borrador ya no existe. Empezá de nuevo."**

### 7.2 Panel del LP (`asignacion_panel`)

- **"El plan no tiene horarios cargados. Agregá horarios desde el
  tab 📋 Grilla Horaria."** (precheck)
- **"💡 Hay N horario(s) con tipo todavía sin determinar que se
  podrían completar automáticamente..."** (warning cuando hay
  auto-completables)
- **"Asignación resuelta en X.XXs. N clases actualizadas."** (éxito)
- **"La asignación no resolvió: {msg}. {error_message}"**
  - `msg` ∈ {"no se encontró solución válida", "se agotó el tiempo
    máximo", "hubo un error inesperado"}

### 7.3 Panel de resultado (`asignacion_resultado_ui`)

- **"### ❌ Última corrida — no se pudo resolver · YYYY-MM-DD HH:MM"**
  (status humano)
- Cuando ejecutó IIS: **"🔍 Causa probable: {desc}. Mirá la sección
  'Diagnóstico cruzado' abajo..."** — antepuesto al error_message.
- **"⚠️ Algunas franjas destino ya están saturadas. Mover el horario
  podría sólo trasladar el problema."** (preview del dialog)
- **"✅ El cambio NO agrega conflictos nuevos ni duplica el día de
  la comisión."** (preview seguro)
- **"⚠️ Este cambio agregaría N conflicto(s) nuevo(s) de paralelismo
  en cohortes."**
- **"❌ Materia 'CODIGO' no encontrada"** (fallos internos del
  preview de horarios).

### 7.4 Edición de comisiones (plan_grilla_editor)

Errores desde `delete_comision` cuando hay dependencias:

- **"No se puede borrar: la comisión tiene entries asociadas en el
  cronograma. Reasignalos o borrá las entries primero."**
- **"No se puede borrar: la comisión tiene horarios asociados en el
  plan. Reasignalos o borrá los horarios primero."**

Errores desde `cambiar_aula_horario` (usado en el patrón semanal de
aulas):

- **"El aula 'X' no es laboratorio compatible con la materia MAT."**
- **"El aula 'X' es de tipo 'lab' y no admite clase teórica."**
- **"El aula 'X' ya está asignada a otro horario del plan (Lu
  14:00–16:00)."**

---

## 8. Discrepancias con docs

Documentos revisados:
`project/2. Desarrollo/WORKFLOW.md` § 5–9,
`project/2. Desarrollo/ASIGNACION_IMPL.md`,
`project/1. Diseño/asignacion-aulas-LP.md`,
`project/requerimientos.md`.

### 8.1 WORKFLOW.md § 6.2 — cantidad de estadísticas

Dice **"5 métricas: Materias, Comisiones, Horarios, Clases, Con
Aula"**. El código actual (`_render_plan_editor` línea 279) muestra
**4 métricas**: Materias, Comisiones, Horarios, Horarios con aula. No
hay "Clases".

Es coherente con la deprecación de clases puntuales (que sacó la
métrica de Clases), pero la doc quedó desactualizada.

### 8.2 WORKFLOW.md § 6.3 — cupo por comisión

Dice: **"El cupo del modelo se mantiene en DB con default 30 pero
no se edita más en el UI — ya no era usado funcionalmente."**

El código actual sí lo edita: `plan_grilla_editor.py` línea 1177 tiene
la columna Cupo en el `data_editor` de comisiones con
`min_value=0, step=1`. Aparece siempre visible en modo "Por materia".

### 8.3 WORKFLOW.md § 10 — tabs de la página Planes

Dice: **"Generar plan, Detalle, Grilla horaria, Clases, 🏛️ Aulas
(LP), Config"**. El código actual son 6 tabs: **Generar Plan, Vista
General, Detalle del Plan, Grilla Horaria, 🏛️ Aulas, ⚙️
Configuración**. No hay "Clases" y hay "Vista General" que la doc no
menciona.

### 8.4 ASIGNACION_IMPL.md § 4.2 y § 4.3 — heatmap demanda/oferta e
impacto R10

La doc dice que existen `_render_heatmap_demanda_oferta` y
`_render_impacto_r10` en `asignacion_resultado_ui.py`. El código
actual **los sustituyó por `_render_heatmap_por_sede`**, que unifica
ambas funcionalidades particionando por sede. Hay un comentario en el
propio código
(`asignacion_aulas_service._build_details_json`, líneas 909–913) que
lo dice explícitamente:

> "Heatmap PARTICIONADO POR SEDE — reemplaza al heatmap demanda/oferta
> global y al panel de impacto R10."

Sin embargo `RF-LP-13` y `RF-LP-14` en `requerimientos.md` siguen
listando ambas funcionalidades con su nombre viejo apuntando a
funciones que ya no se usan tal cual.

### 8.5 ASIGNACION_IMPL.md § 6.2 — panel de asignación

Dice **"Botón 'Correr LP'"**. El texto del botón real es **"🚀
Asignar aulas"** (línea 157 de `asignacion_panel.py`). Cosmético.

### 8.6 ASIGNACION_IMPL.md § 6.4 — cronograma por aula

Describe un panel con filtros (Aula, Sede, Sólo manuales,
Carrera/Año/Cuatri, Tipo, Día, Buscar materia) y un botón "Editar" por
fila que llama `_dialog_cambiar_aula`. Este dialog corresponde a la
edición del **patrón** (`cambiar_aula_horario`), coherente con la
sección 5 renombrada. La documentación no advierte que el filtro
"Sólo manuales ✋" hoy es siempre vacío (no hay flujo que setee
`aula_asignada_manualmente=True`).

### 8.7 ASIGNACION_IMPL.md § 7 — cantidad de tests

Dice **"38 tests verdes al cierre de Fase 7"** y menciona "cambio
puntual de tipo de clase (5 casos): bidireccionalidad teorica↔lab...".
La deprecación de 2026-07-07 removió esa funcionalidad; los tests
correspondientes probablemente ya no existan (habría que verificar
con `pytest tests/test_asignacion_aulas_service.py -k puntual`).

### 8.8 `requerimientos.md` RF-PLAN-01

Dice el requisito es cubierto por `src/services/comision_service.py`.
Es correcto tras el refactor de "comisiones como entidad de primera
clase" (`RF-COMISION-01`), pero la descripción del RF sigue hablando
de "por dictado con coeficientes de asignación" — la implementación
real ya no está atada al dictado (`ComisionDB.dictado_id` es opcional
y de hecho suele estar en `None` para comisiones del plan, según
comentarios en `build_inputs` líneas 187–190).

### 8.9 Código duplicado — Vista General vs. `delete_plan_cascade`

El tab Vista General implementa el borrado del plan inline (líneas
775–800 de `5_📊_Planes.py`) haciendo la cascada manual (clases →
horarios → comisiones → plan). El wizard usa la función
`plan_generation_service.delete_plan_cascade` que hace exactamente lo
mismo. Refactor pendiente.

---

## 9. Preguntas abiertas

1. **¿"Activar" en Vista General debería generar `ClaseDB` como el
   "Activar plan" del panel de validación?** Hoy hay dos botones con
   el mismo label ("Activar" / "Activar plan") pero comportamientos
   distintos. Uno flippea el flag, el otro flippea el flag + genera
   clases. La UX es inconsistente. La ruta correcta parece ser que
   Vista General sólo desactive/active como conveniencia rápida, y
   que la activación "completa" viva en el panel de validación —
   pero el label no lo transmite.

2. **¿El toggle "Respetar ediciones manuales" debería ocultarse hasta
   que vuelva la edición puntual?** Hoy es un flag que no cambia
   nada visible en el flujo normal (la métrica "Manuales
   respetadas" siempre da 0). Confunde al usuario porque sugiere
   que existe una capacidad de edición manual que en realidad no
   está expuesta.

3. **¿La UI debería llamar `clear_aula_horario` automáticamente al
   mover un slot?** Hoy el `HorarioDB.aula_id` puede quedar
   inconsistente después de un movimiento y el usuario tiene que
   correr el LP otra vez para reconciliar. Podría ser un save-guard.

4. **¿Debería haber una confirmación intermedia para "Cancelar
   wizard" y para "Eliminar plan"?** Ambos son destructivos y no
   tienen segundo click.

5. **`WORKFLOW.md § 10` y `ASIGNACION_IMPL.md § 4.2/4.3` están
   desactualizados**. Se deben regenerar contra el estado actual del
   código antes de escribir el manual de usuario, para no propagar
   errores.

6. **La sección "Candidatas a partir comisión" muestra sólo materias
   con `sobre`**. Si el problema es sub-utilización sistemática (aulas
   sobredimensionadas), ¿debería haber una sección análoga "Candidatas
   a fusionar comisiones"? Hoy no existe.

7. **`ComisionDB.dictado_id` está frecuentemente en `None`** para
   comisiones del plan. El toggle α (`R9`) agrupa por dictado; para
   comisiones sin dictado fuerza `α=1`. ¿Es intencional que las
   comisiones del plan típicamente estén "desconectadas" del dictado
   del ciclo? Esto se contradice con el nombre del requerimiento
   RF-PLAN-01 ("por dictado").

8. **El heatmap live vs. el LPRun snapshot pueden divergir**. El
   heatmap por sede se recomputa en cada rerun, mientras que la
   tabla por horario y el diagnóstico estructural son del snapshot.
   Cuando el usuario cambia algo entre corridas, los dos pueden
   contradecirse sutilmente. La UI ya filtra los "virtuales ahora"
   del diagnóstico (`_filtrar_diag_virtuales`), pero otros casos
   (cambiar cupo, cambiar coef, agregar aulas) no se reconcilian.
   ¿Debería la UI marcar el snapshot como "stale" y sugerir re-correr?
