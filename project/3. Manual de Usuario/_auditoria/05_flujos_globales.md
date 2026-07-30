# Auditoría — Flujos globales end-to-end

> Fecha de auditoría: 2026-07-30
> Fuente única de verdad: código fuente en `src/`, `app/pages/` y
> `scripts/`. Los documentos operativos (`WORKFLOW.md`,
> `ASIGNACION_IMPL.md`, `CARGA_DATOS_INICIALES.md`,
> `COMISIONES_POR_CARRERA.md`, `modelo-planificacion-cursada.md`,
> `requerimientos.md`) se contrastan al final.
> Alcance: cómo se conectan las páginas Streamlit y los scripts CLI en
> un uso real de punta a punta.
> Complementa las auditorías previas de módulos específicos
> (`02_ciclos_cronogramas.md`, `03_planes_asignacion.md`).

---

## 1. Flujos maestros identificados

De la lectura transversal se desprenden **ocho flujos** que un usuario
tiene que poder ejecutar. No son mutuamente exclusivos: cada
cuatrimestre en producción encadena varios de ellos.

### F1 — Setup inicial de la base (bootstrap)

**Cuándo usarlo**: primera instalación del sistema en una máquina
nueva, después de un cambio grande de plan de estudios (nueva versión
maestra) o cuando la DB quedó irrecuperable y hay que rearrancar.

**Estado previo esperado**:
- Repositorio clonado, dependencias instaladas
  (`uv sync` / `pip install -e .`).
- Excels maestros en `data/input/`:
  - `aulas/aulas.xlsx`
  - `Carreras/Maestro materias.xlsx`
  - `Carreras/Maestro planes.xlsx`
  - `Carreras/carreras_metadata.json` (opcional pero recomendado)
  - `inscriptos/final_df.xlsx` (opcional, para forecast)

**Pasos ordenados**:

1. **Reset y carga de catálogo** (CLI):
   `python -m scripts.load_initial_data --reset`.
   Borra `data/database.db`, recrea el schema y carga aulas, materias,
   carreras, versiones de plan y `PlanEstudioDB`. Aplica
   `carreras_metadata.json` para completar nombres, títulos, duración,
   `cantidad_materias`, `dicta_recursado`.
2. *(Opcional)* **Carga de inscriptos históricos**:
   `python -m scripts.load_inscriptos` — alimenta el forecast del
   plan.
3. **Arrancar la aplicación**: `streamlit run app/main.py`. La página
   Home (`app/main.py`) llama a `init_db()`, que corre las migraciones
   idempotentes (`_run_migrations` en `src/database/connection.py`,
   ~200 sentencias `ALTER TABLE`). Es normal que la primera carga
   tarde unos segundos.
4. **Ajustes de catálogo desde la UI**:
   - `📚 Materias`: revisar `horas_teoria` / `horas_laboratorio`
     (los Excel sólo traen `horas_semanales` total).
     Marcar virtuales de catálogo si corresponde.
     Asociar laboratorios compatibles vía `MateriaLaboratorioDB`.
   - `🏛️ Aulas y Sedes`: crear sedes adicionales (Siberia, etc.),
     dar de alta aulas fuera de Pellegrini, ajustar tipos
     (`teorica` / `practica` / `laboratorio` / `anfiteatro`),
     marcar `es_default_comunes` en una única sede.
   - `🎓 Carreras`: editar nombres reales (el script deja
     placeholders = código si falta el JSON), setear
     `dicta_recursado`, definir sedes habilitadas por carrera
     (M:N `CarreraSedeDB`).

**Verificación final**: en la landing (`app/main.py`) los métricos
"Materias", "Aulas", "Comisiones", "Horarios" muestran valores
esperados. Comisiones y Horarios en cero es correcto — todavía no
hay cronogramas ni planes.

**Rollback**: `python -m scripts.load_initial_data --reset` de nuevo.
Toda la información operativa se pierde; los Excel maestros son
inmutables.

**Puntos de fricción**:
- El reset **borra ciclos, cronogramas y planes** — no sólo el
  catálogo. Es literal: `unlink()` sobre `data/database.db`.
- Después del reset hay que **recrear todo lo posterior al catálogo**:
  ciclos, dictados, cronogramas, planes, asignación de aulas.
- La sede default `Pellegrini` se crea automáticamente; otras sedes
  requieren alta manual antes de crear las aulas.

---

### F2 — Armar un cuatrimestre nuevo de cero

**Cuándo usarlo**: cada arranque de cuatrimestre (1C o 2C), cuando ya
existe el catálogo cargado y el usuario tiene el Excel de horarios que
llega desde la facultad.

**Estado previo esperado**:
- Catálogo estable (materias, carreras, aulas, planes de estudio).
- Excel de horarios del cuatrimestre disponible (columnas
  `materia | día | inicio | fin | comisión`).

**Pasos ordenados**:

1. **Crear el ciclo** (`📆 Ciclos → ➕ Crear`): id como `2026-1C`,
   año, número (1 ó 2), `fecha_inicio` y `fecha_fin`.
2. **Asignar versiones de plan al ciclo**
   (`📆 Ciclos → Versiones de plan`): para cada carrera, elegir la
   `PlanCarreraVersionDB` vigente. Sin esto no se pueden crear
   dictados.
3. **Crear los dictados**
   (`📆 Ciclos → 📚 Dictados → botón "Crear dictados"`):
   `create_dictados_for_ciclo` recorre las materias del plan y crea
   una fila `DictadoDB` por cada una que la regla de recursado no
   descarte (semántica "existencia = activación").
4. **Ajustar el panel de divergencias** si aparece: cada fila con
   discrepancia se resuelve con `[✅ Crear]`, `[🗑️ Borrar]`,
   `[⬆️ Promover a regla]` o `[⏭️ Omitir en regla]`. Revisar toggles
   `Virtual` para materias que se dictan por Zoom en este ciclo.
5. **Cargar el cronograma** (`📅 Cronogramas → 📤 Cargar`):
   subir el Excel. Se crea un `ScheduleDB` con sus `ScheduleEntryDB`.
   Elegir el ciclo al que corresponde.
6. **Editar y validar el cronograma**
   (`📅 Cronogramas → ✏️ Editar` y `✅ Validar`):
   - Resolver conflictos, agregar/mover entries.
   - En `Validar`, mirar cobertura contra los dictados del ciclo,
     particiones teoría/lab, materias faltantes vs no-esperadas.
   - Para materias que aparecen en el cronograma pero no tienen
     dictado activo: usar los botones bulk `🟢 Activar` o
     `🌐 Activar y marcar virtual`.
7. **Generar el plan de cursada**
   (`📊 Planes → 📥 Generar Plan`, wizard de 2 pasos):
   - Paso 1: seleccionar ciclo, cronograma, nombre, descripción,
     método de forecast default.
   - Paso 2: preview del plan en edición previa; ajustar comisiones
     antes de salir del wizard. El plan se crea como borrador
     (`activo=False`).
8. **Editar el plan en detalle** (`📊 Planes → 🔍 Detalle`):
   - Metadata (nombre, descripción, forecast default).
   - Por materia: horarios, comisiones, pesos, inscriptos esperados
     manuales (override), 10 chequeos inline.
9. **Validar el plan** (panel unificado dentro del detalle):
   - Resolver conflictos o marcarlos ignorados
     (`IgnoredConflictDB`).
   - Confirmar cobertura con dictados y particiones factibles.
10. **Activar el plan**: sólo se habilita el botón si no hay
    conflictos no-ignorados. `activate_plan` desactiva los demás
    planes del ciclo (uno activo por ciclo), genera `ClaseDB` (cache
    técnico) por cada `HorarioDB` × fecha del ciclo.
11. **Asignar aulas** (`📊 Planes → 🏛️ Aulas`):
    - Configurar `LPConfig` (fecha_desde, λ_over, λ_under,
      tolerancias, timeout).
    - Correr el LP.
    - Si es infactible: leer diagnóstico estructural, revisar
      heatmaps de carga y demanda-vs-oferta, actuar sobre la causa
      (agregar aulas, marcar virtual, ampliar
      `MateriaLaboratorioDB`, revisar sedes admisibles).
    - Si es óptimo: revisar tabla de resultados coloreada por
      gap vs tolerancias, candidatas a partir comisiones,
      cronograma por aula.

**Verificación final**:
- Plan `[ACTIVO]` en `📊 Planes`.
- Todos los `HorarioDB` no virtuales tienen `aula_id` asignada.
- El `LPRunDB` más reciente está en `optimal` o `feasible`.
- La tabla del panel de resultado no muestra rojos que preocupen
  (gaps intolerables).

**Rollback**:
- Antes de activar: borrar el plan (borra en cascada comisiones,
  horarios). El cronograma sobrevive.
- Después de activar: desactivar el plan (marcar `activo=False` desde
  la lista). Las `ClaseDB` quedan pero pasan a estado "borrador".
- Se puede activar otro plan del mismo ciclo: `activate_plan`
  desactiva los otros automáticamente.

**Puntos de fricción**:
- El **paso 2 (asignar versión de plan)** es fácil de olvidar y sin
  él los dictados no se pueden crear.
- La regla de recursado + toggle virtual + panel de divergencias es
  un tridente denso: manejar el "estado inicial correcto" del ciclo
  requiere entender la semántica jerárquica.
- El wizard de generación del plan reusa el editor de detalle
  embebido — visualmente parece "lo mismo" que después.
- El LP puede tardar (timeout configurable); si es infactible, el
  diagnóstico estructural es útil pero necesita interpretación.

---

### F3 — Clonar un ciclo previo como base

**Cuándo usarlo**: preservar un escenario problemático (ej. una
corrida infactible del LP con un heatmap saturado) como caso ejemplo
no editable, sin bloquear el trabajo sobre el original.

**Estado previo esperado**: existe un ciclo con plan generado (y
opcionalmente asignación de aulas ya corrida).

**Pasos ordenados**:

1. **Correr el script CLI**:
   `python -m scripts.clonar_ciclo_para_demo --ciclo-id 2026-1C`
   (opcional `--sufijo` o `--dry-run`).
2. El script clona en profundidad: `CicloDB` (con id sufijado como
   `2026-1C-demo-saturacion`), `DictadoDB`, `DictadoCicloDB`,
   `PlanificacionCursadaDB` (con `activo=False` y descripción marcada
   como caso ejemplo), `ComisionDB`, `HorarioDB`, `ClaseDB`, `LPRunDB`
   (con `details_json` reescrito para preservar los IDs de horario del
   clon), `MateriaForecastConfigDB`, `IgnoredConflictDB`.
3. **No** se clonan: catálogos (materias, aulas, sedes, carreras,
   plan_estudio, carrera_sede), snapshots de validación
   (`PlanValidationDB`), ni el cronograma (`ScheduleDB` — el plan clon
   preserva el FK original).

**Verificación final**: aparece el ciclo nuevo en `📆 Ciclos` con la
marca "[CASO EJEMPLO DE SATURACION — ...]" en la descripción. El plan
correspondiente aparece en `📊 Planes` como borrador. Los heatmaps y
detalles del `LPRunDB` clonado son navegables sin re-correr el solver.

**Rollback**: `_delete_ciclo_cascade(session, "2026-1C-demo-...")`
desde la UI de Ciclos (botón borrar con confirmación) o directamente
en la DB.

**Puntos de fricción**:
- El plan clon depende del `ScheduleDB` original — si se borra el
  cronograma se rompe la referencia (aunque el plan siga siendo
  navegable a nivel comisiones/horarios).
- Sin UI: hoy es puramente CLI. Un usuario "normal" del manual no
  necesita saber que este flujo existe salvo que el equipo lo use
  para preservar casos didácticos.

---

### F4 — Reasignar aulas tras cambios en el plan

**Cuándo usarlo**: se editó el plan después de una asignación LP
previa (se agregó/movió un horario, se ajustó una comisión, se marcó
una materia como virtual del ciclo, se cambió una carrera asignada
de comisión, se ajustaron sedes admisibles).

**Estado previo esperado**: plan activo con `LPRunDB` previo.

**Pasos ordenados**:

1. **Aplicar los cambios estructurales** al patrón:
   - `📊 Planes → 🔍 Detalle` para editar horarios/comisiones de una
     materia.
   - `📊 Planes → 📋 Grilla Horaria` para ediciones globales
     tipo drag/resize.
   - `📆 Ciclos → 📚 Dictados` para toggle virtual, borrar/crear
     dictados.
   - `🏛️ Aulas y Sedes` o `🎓 Carreras` si cambió la disponibilidad
     de aulas o las sedes habilitadas por carrera.
2. **Volver a `📊 Planes → 🏛️ Aulas`** y revisar la configuración
   del LP:
   - `fecha_desde` decide qué `ClaseDB` se pisan (las anteriores
     quedan intactas).
   - Toggle "respetar ediciones manuales" existe pero hoy no hay UI
     que setee `ClaseDB.aula_asignada_manualmente=True`, así que en
     la práctica no cambia nada.
   - Toggle α opcional si se desea que el LP redistribuya pesos.
3. **Correr LP**. Revisar diff del resultado en la tabla y en la
   vista cronograma por aula.
4. **Aplicar α** si se activó y el usuario acepta la propuesta
   (botón "Aplicar nuevos pesos" del panel de resultado).

**Verificación final**: `LPRunDB` más reciente en estado óptimo o
feasible. `HorarioDB.aula_id` refleja los nuevos asignados. Los
patrones del cronograma por aula (`aula_cronograma_view`) muestran
la asignación consistente.

**Rollback**: los `LPRunDB` son inmutables y quedan como histórico.
Para "volver atrás" hay que re-correr el LP con la config previa o
editar aulas manualmente vía `cambiar_aula_horario`.

**Puntos de fricción**:
- No hay "modo comparación" entre dos `LPRunDB` (feature diferida).
- Las clases anteriores a `fecha_desde` quedan con la asignación
  vieja: mezcla temporal deliberada.

---

### F5 — Alta o baja de una comisión con clases ya generadas

**Cuándo usarlo**: post-activación del plan hay que abrir una comisión
nueva (más inscriptos de lo previsto), cerrarla, o cambiarle
carrera_asignada / cupo / nombre.

**Estado previo esperado**: plan activo con `ClaseDB` ya generadas.

**Pasos ordenados**:

1. **Alta** de comisión:
   - `📊 Planes → 🔍 Detalle → 🎓 Comisiones` (o desde la tabla de
     comisiones del plan) → crear.
   - Agregarle horarios (día, hora, tipo).
   - Al agregar `HorarioDB`, las clases todavía no existen para ese
     patrón: hay que re-correr `generate_clases_for_plan` (se
     dispara automáticamente al activar; si el plan ya está activo,
     hay que forzarlo desde el flujo del plan — hoy la UI dispara la
     generación al modificar horarios en la mayoría de casos).
2. **Baja** de comisión:
   - `delete_comision` está bloqueado si tiene horarios activos
     (guardián por integridad). Primero hay que borrar los
     `HorarioDB` de la comisión.
   - Al borrar los horarios, sus `ClaseDB` en cascada se borran o
     quedan huérfanas según implementación.
3. **Edición** (nombre / cupo / `carrera_asignada`):
   - Tabla de comisiones del plan (`plan_grilla_editor`).
   - Los cambios de `carrera_asignada` emiten evento en el change
     log (`ChangeLogDB` con `origin=ui:planes`).
4. **Re-correr LP** para reflejar los cambios en las aulas.

**Verificación final**: la lista de comisiones muestra el estado
esperado; los horarios apuntan a las comisiones correctas; el LP
vuelve a estado óptimo.

**Rollback**: manual — no hay undo. Si la baja rompió algo, hay que
recrear la comisión y sus horarios.

**Puntos de fricción**:
- La guarda de `delete_comision` obliga a mover horarios primero;
  puede ser tedioso.
- Un cambio de `carrera_asignada` afecta a **todos** los horarios de
  la comisión (por diseño): no se puede tener una comisión con
  algunos horarios en Pellegrini y otros en Siberia.

---

### F6 — Cambio de aula puntual manual

**Cuándo usarlo**: la asignación del LP es correcta en general pero
una comisión requiere un aula específica por razones no modeladas
(preferencia docente, proximidad, aula amoblada).

**Estado previo esperado**: LP ya corrido, `HorarioDB.aula_id`
asignada.

**Pasos ordenados**:

1. **Ir al panel de aulas** (`📊 Planes → 🏛️ Aulas`).
2. **Filtrar** por materia/comisión/día en el panel de filtros
   (`aula_cronograma_view`).
3. **Fila del horario** → botón "Editar" → dialog
   `_dialog_cambiar_aula_horario`:
   - Selector de aula (filtrado por compatibilidad de tipo + choques
     temporales contra otros `HorarioDB` del mismo plan).
   - Opcional: cambiar tipo (`teorica` ↔ `laboratorio`).
   - Confirmar.
4. El servicio `cambiar_aula_horario` valida y persiste
   `HorarioDB.aula_id` (y opcionalmente `tipo_clase`). Propaga a las
   `ClaseDB` que **no** tienen `aula_asignada_manualmente=True`
   (hoy siempre `False` porque la UI de clases puntuales se
   deprecó).

**Verificación final**: la tabla del panel muestra el aula nueva.
El cronograma por aula del aula nueva incluye el horario. Si se re-
corre el LP con toggle "respetar manuales" (hoy sin efecto real, no
hay marca), el cambio queda o se pisa según el toggle.

**Rollback**: repetir el flujo eligiendo el aula vieja, o re-correr
el LP para volver a la asignación algorítmica.

**Puntos de fricción**:
- La deprecación de clases puntuales (2026-07-07) hizo desaparecer
  la posibilidad de "cambiar aula sólo para el 15 de septiembre".
  Sólo se puede cambiar el patrón semanal completo.
- No hay marca visual persistente de "aula editada manualmente" a
  nivel patrón: el usuario tiene que acordarse.

---

### F7 — Verificación pre-inicio de cuatrimestre

**Cuándo usarlo**: días antes del inicio del cuatri, para dar por
cerrado el plan y comunicar la asignación oficial.

**Estado previo esperado**: plan activo, LP corrido en óptimo.

**Checklist recomendado** (ver también sección 4 abajo):

1. `📊 Planes → 🔍 Detalle → ✅ Validaciones`:
   - Cobertura contra dictados: 0 materias faltantes reales,
     0 no-esperadas sin decidir.
   - Partición teoría/lab factible por comisión.
   - Sin conflictos horarios no-ignorados por grupo curricular.
2. `📊 Planes → 🏛️ Aulas`:
   - `LPRunDB` en `optimal`.
   - Métricas de over/under bajas.
   - Diagnóstico estructural vacío (o entendido si tiene warnings).
   - Cronograma por aula sin choques.
3. `📆 Ciclos → 📚 Dictados`:
   - Panel de divergencias vacío (o con divergencias justificadas).
   - Toggles `Virtual` consistentes con la modalidad real.
4. `📊 Planes → 📋 Grilla Horaria`:
   - Barrido visual buscando huecos raros o solapamientos.
5. `📜 Historial`: revisar el feed reciente para detectar cambios
   inesperados desde otras sesiones.

**Verificación final**: cada ítem OK. Se puede tomar screenshot del
panel de resultado del LP y del cronograma por aula como registro
oficial.

**Rollback**: cualquier corrección envía de vuelta a F4/F5/F6.

**Puntos de fricción**:
- No hay un "botón único" de verificación consolidada — hay que
  recorrer varias páginas.
- Los snapshots (`PlanValidationDB`) pueden quedar stale y el badge
  no lo refleja hasta forzar revalidación.

---

### F8 — Consulta histórica en el change log

**Cuándo usarlo**: alguien pregunta "quién cambió esto y cuándo",
o hay que investigar por qué una regla ahora dice X.

**Estado previo esperado**: hooks del `ChangeLogDB` activos (default),
y el evento en cuestión ocurrió después de la instalación del hook.

**Pasos ordenados**:

1. **Página `📜 Historial`**:
   - Tab **🌐 Feed global**: últimos N días de mutaciones (default
     30), filtrable por tipo de entidad y origen (`ui:planes`,
     `ui:ciclos`, `system`, etc.).
   - Tab **🔎 Por entidad**: elegir Materia / Carrera / Dictado /
     Sede específica y ver su historial completo.
2. **Interpretar el evento**: el evento tiene `entity_type`, `field`,
   `old_value` / `new_value`, `origin`, `reason`, `timestamp`.

**Verificación final**: cada cambio relevante tiene su fila con
razón y origen.

**Rollback**: el historial es sólo lectura. Para "revertir" hay que
editar manualmente el campo actual al valor anterior.

**Puntos de fricción**:
- Sólo se auditan **catálogo y política**: `MateriaDB`, `CarreraDB`,
  `DictadoDB`, `DictadoCicloDB`, `SedeDB`. No se auditan
  `HorarioDB`, `ComisionDB` (excepto emisión explícita por
  `carrera_asignada`), `ClaseDB`, `LPRunDB`.
- Un cambio hecho por script SQL directo no queda registrado.
- El campo tiene que estar en la whitelist (`TRACKED_ENTITIES`).

---

## 2. Auditoría de `WORKFLOW.md`

### 2.1 Actualización general

`WORKFLOW.md` lleva la etiqueta "Última actualización: 2026-07-12". A
2026-07-30, el documento **está bastante actualizado en los aspectos
mayores**:

- Menciona explícitamente los tres refactors clave en el header:
  eliminación de `DictadoDB.activo`, deprecación de clases puntuales,
  y `ComisionDB` como entidad de primera clase.
- La sección 2 (Ciclos + Plan Versions) refleja el estado actual.
- La sección 3 (Dictados) describe correctamente la semántica
  "existencia = activación" y el panel de divergencias.
- La sección 8 (Activación) explica que `ClaseDB` es cache técnico y
  no se edita.
- La sección 9 (Estado actual) menciona correctamente el LP fases
  1–8 y sus features (α, diagnóstico, edición manual del patrón).
- La sección 13 apunta bien a los documentos canónicos del LP.

### 2.2 Cobertura de los flujos maestros

| Flujo | Cobertura en WORKFLOW.md |
|---|---|
| F1 Setup inicial | § 1 lo trata en 5 líneas (referencia a `CARGA_DATOS_INICIALES.md`). Falta explicitar que hay que ajustar catálogo desde la UI antes de crear ciclos. |
| F2 Cuatrimestre nuevo | § 2 a § 8: cubierto en profundidad, es el flujo troncal del documento. |
| F3 Clonar ciclo | **No mencionado**. El script `clonar_ciclo_para_demo.py` no aparece en el documento. |
| F4 Reasignar aulas | § 9 lo menciona genéricamente (re-run incremental, α); no lo presenta como flujo distinto. |
| F5 Alta/baja comisión | § 6.5 (comisiones dentro del detalle) lo cubre parcialmente, pero no explica cascada a `ClaseDB` ni el guardián de borrado. |
| F6 Cambio aula puntual | § 9 lo menciona ("edición manual de aula con dialog"). La deprecación de clases puntuales queda clara en la nota 2 del header. |
| F7 Pre-inicio de cuatri | **No hay checklist consolidado**. Cada validación está descripta en su sección propia pero no hay una vista "pre-cierre". |
| F8 Consulta histórica | **No mencionado**. La página `📜 Historial` no aparece en el mapa de páginas (§ 10). |

### 2.3 Features deprecadas todavía mencionadas

Todas las menciones deprecadas están **explícitamente marcadas como
tales**, no hay ruido:

- Clases puntuales / tab "📅 Clases": nota 2 del header aclara que
  cualquier mención en secciones 5-8 es histórica.
- `DictadoDB.activo` / `activo_override_manual`: nota 1 del header.
- Sin embargo, **la sección 3.3 sigue mencionando el toggle "Pisar
  también las ediciones manuales"** en el contexto de recompute — eso
  se refiere al `activo_override_manual` que **fue eliminado** según
  la propia nota 1. Hay contradicción con el header.
- La **sección 12.3** menciona `MateriaForecastConfigDB.valor_override`
  correctamente; consistente con el código.
- El **mapa de páginas (§ 10)** no lista `📜 Historial` (página 8)
  y todavía usa el ícono `📝` para Inscriptos (la página real es
  `📈`).

### 2.4 Detalles críticos que faltan o son incompletos

1. **Flujo end-to-end explícito de F2**: hay un diagrama en la
   sección 0, pero no una lista secuencial con checkboxes o números
   claros de "primero X, después Y". Un usuario nuevo tiene que
   construírsela mentalmente desde 8 secciones.
2. **Bulk activate desde el panel de validación del plan (§ 6.3)**:
   se explica bien, pero el "marcar virtual" cascadea al toggle
   `DictadoDB.virtual` que ya está descrito en § 3.4 con otras
   palabras. Redundancia parcial.
3. **Sedes y CarreraSede (R10)**: se mencionan de pasada en la
   sección 13, pero no hay un flujo explícito de "cómo configurar
   sedes por carrera" antes de correr el LP por primera vez.
4. **Wizard de generación (§ 5)**: dice "wizard de 2 pasos", pero no
   explicita que el paso 2 embebe el editor de detalle del plan y
   que "cancelar" borra el plan.
5. **La sección "Ciclos → Recalcular según reglas" (§ 3.3)** menciona
   el toggle "Pisar también las ediciones manuales" que ya no
   existe (era para `activo_override_manual`, eliminado en
   2026-06-30). Contradicción interna con el header del documento.
6. **`📜 Historial`** completamente ausente del mapa de páginas.

### 2.5 Jerga técnica que un manual debería suavizar

- "LP", "solver", "CBC", "pigeonhole", "IIS", "Hall violators",
  "matching bipartito", "α[k]", "R1–R10": jerga formal
  matemática/optimización. Un manual de usuario debería reservarlas
  para un glosario final y usar "el asignador de aulas" en el
  cuerpo.
- "`build_inputs`", "`apply_solution`", "`_run_iis_relajacion`":
  nombres de funciones internas que no le sirven al usuario final.
- "XOR validado a nivel service": jerga de implementación.
- "fingerprint vivo (DB) vs snapshot del summary cacheado" en § 11:
  se puede reescribir como "el sistema detecta cambios recientes y
  revalida solo si hace falta".

**Diagnóstico general**: `WORKFLOW.md` es un buen documento **de
referencia técnica interna** pero **no un manual de usuario**. Sirve
como fuente para redactar el manual, no como sustituto.

---

## 3. Cadena de dependencias entre módulos

### 3.1 Orden estricto de creación

```
[F1 — Bootstrap]
  Sede (default: Pellegrini)  ──►  Aula
  Materia
  Carrera
  PlanCarreraVersion  ──►  PlanEstudio  ──►  (materia ↔ carrera + año/cuatri)
  MateriaLaboratorio (M:N materia ↔ aula lab)
  CarreraSede (M:N carrera ↔ sede)

[F2 — Cuatrimestre]
  Ciclo
      └─►  CicloPlanVersion (bridge ciclo ↔ versión de plan)
              └─►  Dictado (uno por materia del plan filtrada por
                           regla de recursado; existencia = activación)
                      └─►  DictadoCiclo (bridge; anuales: 2 filas)

  Schedule (cronograma)
      └─►  ScheduleEntry (una fila por día/hora del Excel)
              └─►  Comision (schedule_id seteado, "template")

  PlanificacionCursada (borrador)
      ├─►  Comision (plan_cursada_id seteado — clon del template)
      │       └─►  Horario  ← ítem que asigna el LP
      │
      └─►  (al activar)
              └─►  Clase (una por Horario × fecha del ciclo)

  LPRun (post-asignación de aulas)
```

### 3.2 Operaciones que ocurren en cascada automáticamente

- **Creación de dictados** al crear dictados en un ciclo: recorre
  materias de la versión de plan asignada, filtra por recursado.
- **Clonado cronograma → plan**: al generar el plan,
  `clone_comisiones_for_plan` duplica las comisiones template a la
  planificación (nuevos IDs, `plan_cursada_id` seteado).
- **Generación de `ClaseDB`**: al activar un plan,
  `generate_clases_for_plan` crea una `ClaseDB` por `HorarioDB` ×
  cada fecha del ciclo cuyo `weekday()` coincida.
- **Propagación de aula desde patrón a `ClaseDB`**: `apply_solution`
  propaga `HorarioDB.aula_id` a las `ClaseDB` con
  `fecha ≥ fecha_desde` (y sin `aula_asignada_manualmente=True`).
- **Desactivación de otros planes**: `activate_plan` marca
  `activo=False` en los demás planes del mismo ciclo.
- **Borrado en cascada de ciclos**: `_delete_ciclo_cascade` borra
  clases → horarios → comisiones → planes → schedules → dictado-ciclo
  links → ciclo-plan-version links → ciclo.
- **Migraciones idempotentes** al arrancar la app: `_run_migrations`
  aplica ~200 `ALTER TABLE` que agregan columnas faltantes en
  DBs viejas.
- **Change log automático** vía hooks SQLAlchemy sobre las entidades
  trackeadas (`MateriaDB`, `CarreraDB`, `DictadoDB`, `DictadoCicloDB`,
  `SedeDB`).

### 3.3 Operaciones que NO cascadean (hay que hacerlas a mano)

- **Regeneración de `ClaseDB` post-edición de horarios**: el usuario
  tiene que confiar en que ediciones al plan disparen la regeneración;
  no hay botón explícito documentado.
- **Re-correr el LP**: cambios estructurales (agregar aula, marcar
  virtual, cambiar sede admisible) requieren re-correr manualmente.
- **Revalidación del plan**: hay auto-revalidación pero el usuario
  puede desactivarla; entonces hay que forzarla con el botón.
- **Baja de comisión**: hay que borrar horarios primero (guardián).
- **Sede default de comunes**: hay que marcar `es_default_comunes=True`
  en una sede; no hay default automático.
- **`CarreraSedeDB`** (M:N carrera ↔ sedes habilitadas): sin
  configurar, el fallback es "todas las sedes" — hay que setearlo
  explícitamente carrera por carrera.
- **Cantidad de materias por carrera**: queda en NULL después de
  `load_initial_data`, hay que completarlo desde `🎓 Carreras`.
- **Nombres reales de carreras**: el script deja placeholders
  (nombre = código) si falta `carreras_metadata.json`.

---

## 4. Puntos de consistencia global a verificar

Un usuario debería auditar estos puntos antes de dar por cerrado un
cuatrimestre. Estos ítems se pueden convertir en una checklist
navegable dentro del manual.

### 4.1 Dictados

- [ ] Cada materia del plan asignado al ciclo tiene su `DictadoDB`
      correspondiente **o** justificación explícita de por qué no
      (regla de recursado + `dicta_recursado` de la materia/carrera).
- [ ] Panel de divergencias vacío o con divergencias explicadas.
- [ ] Toggle `Virtual` marcado únicamente en las materias que
      efectivamente son virtuales este cuatrimestre.
- [ ] Dictados anuales tienen bridge `DictadoCicloDB` para ambos
      cuatrimestres si ya se creó el 2C.

### 4.2 Cronograma

- [ ] El cronograma "de trabajo" del ciclo está identificado (múltiples
      cronogramas por ciclo es válido; hay que saber cuál es el vigente).
- [ ] Cobertura contra dictados: 0 materias faltantes (todas las
      materias con dictado tienen al menos 1 entry) o justificación
      caso por caso (ej. materia sólo teórica registrada en otro lado).
- [ ] 0 materias "no esperadas" sin decidir (bulk activate + virtual
      resuelto).
- [ ] Sin conflictos entre entries por grupo curricular (mismo
      año/cuatri/carrera) no ignorados.
- [ ] Cada entry tiene `tipo_clase` definido si la materia lo requiere
      (teoría + lab).

### 4.3 Plan de cursada

- [ ] Solo un plan `activo=True` por ciclo (invariante).
- [ ] Todas las comisiones del plan tienen al menos 1 `HorarioDB`.
- [ ] Todos los `HorarioDB` tienen `dia`, `hora_inicio`, `hora_fin`
      válidos.
- [ ] Los pesos de las comisiones de un mismo dictado suman ≈ 1.0
      (normalizar si no).
- [ ] Los cupos y esperados por comisión son consistentes con el
      total esperado de la materia.
- [ ] Snapshot `PlanValidationDB` no está stale.

### 4.4 Asignación de aulas

- [ ] Cada `HorarioDB` no virtual tiene `aula_id` asignada.
- [ ] Los `HorarioDB` virtuales (por catálogo, dictado u horario)
      tienen `aula_id = NULL` correctamente.
- [ ] `LPRunDB` más reciente en `optimal` o `feasible`.
- [ ] Métricas de over/under dentro de tolerancias.
- [ ] Cronograma por aula sin choques (dos comisiones distintas
      en la misma aula, día y franja horaria).
- [ ] Los tipos de aula respetan la compatibilidad con las materias
      (teóricas en aulas teóricas, labs en aulas
      `MateriaLaboratorioDB`).
- [ ] R10 (sedes) satisfecho: comisiones con `carrera_asignada`
      seteada están en sedes admisibles para esa carrera.

### 4.5 Global

- [ ] Feed del `📜 Historial` sin cambios sospechosos de las últimas
      24-48 hs desde otros usuarios.
- [ ] `data/database.db` con backup reciente.

---

## 5. Terminología unificada para el manual

Términos que aparecen en la UI o en la documentación técnica, con la
propuesta de cómo llamarlos en el manual.

| Término del manual | Concepto técnico | Contexto / notas |
|---|---|---|
| Asignador de aulas | Programa lineal (LP) / solver / CBC | En el manual siempre "el asignador"; nunca "el LP", "el solver", "CBC" |
| Corrida del asignador | `LPRunDB` | "Corrida" es más natural que "run" |
| Patrón semanal | `HorarioDB` | "El patrón semanal de la comisión". La UI ya dice "Patrón semanal de aulas" en un tab del panel de asignación |
| Clase | `ClaseDB` | Igual — pero el manual debe aclarar que las clases se generan automáticamente y no se editan una por una |
| Cronograma | `ScheduleDB` | OK como está, término consolidado |
| Fila del cronograma | `ScheduleEntryDB` | En vez de "entry" o "ScheduleEntry" |
| Comisión | `ComisionDB` | OK |
| Comisión modelo / comisión del cronograma | `ComisionDB` con `schedule_id` | En vez de "template" |
| Comisión del plan | `ComisionDB` con `plan_cursada_id` | El clon vivo, el que el LP mira |
| Plan de cursada | `PlanificacionCursadaDB` | OK, "plan" a secas también |
| Plan activo | `activo=True` | "El plan vigente / activo del ciclo" |
| Plan borrador | `activo=False` | "El borrador" o "el plan en edición" |
| Ciclo | `CicloDB` | OK. "Cuatrimestre" es sinónimo aceptable |
| Dictado | `DictadoDB` | OK. Aclarar: "una materia del catálogo se transforma en un dictado cuando el ciclo la ofrece efectivamente" |
| Versión de plan de estudios | `PlanCarreraVersionDB` | OK — evitar "plan version" en inglés |
| Regla de recursado | `dicta_recursado` (jerárquico) | "La materia se dicta como recursado si..." |
| Modalidad virtual (del ciclo) | `DictadoDB.virtual=True` | En vez de "toggle virtual" |
| Materia virtual (de catálogo) | `MateriaDB.virtual=True` | Diferenciar de la modalidad del ciclo |
| Sede default de comunes | `SedeDB.es_default_comunes` | Nombre operativo, no cambiar |
| Sedes habilitadas por carrera | `CarreraSedeDB` | "Las sedes donde una carrera puede dictar" |
| Panel de divergencias | `divergencias_panel` | OK, ya se usa en la UI |
| Snapshot de validación | `PlanValidationDB` / `ScheduleValidationDB` | Preferir "última validación guardada" |
| Peso de comisión | `ComisionDB.coef_asignacion` | "Peso" es más intuitivo que "coeficiente" |
| Redistribución de pesos (α) | Toggle α del LP | "El asignador puede reproponer pesos" |
| Inscriptos esperados | `total_esperado(materia) × peso(comision)` | OK, la UI ya lo usa así |
| Forecast | `forecast_service` | OK. Aclarar "estimación histórica" |
| Override manual de esperados | `MateriaForecastConfigDB.valor_override` | "Cuando forzás el valor manualmente" |
| Historial | `📜 Historial` / `ChangeLogDB` | OK |
| Aula asignada manualmente | `HorarioDB.aula_id` editado post-LP | El flag `ClaseDB.aula_asignada_manualmente` en el modelo no se usa desde la UI hoy |
| Grupo de simultaneidad | `Sim` en la lógica del LP | Reservar para glosario técnico; en el manual: "clases que se dictan al mismo tiempo" |
| Partición teoría/laboratorio | R5 del LP | "División teoría/lab por comisión" |
| Diagnóstico de infactibilidad | `diagnose_infeasibility` | "Diagnóstico" a secas |
| Heatmap de carga | `compute_heatmap_carga` | "Mapa de calor de simultaneidad" |
| Heatmap demanda vs oferta | `compute_heatmap_demanda_oferta` | "Mapa de demanda vs oferta de aulas" |
| Bulk-actions | | "Acciones en bloque" o "acciones masivas" |

**Términos a EVITAR en el cuerpo del manual** (dejar para glosario o
apéndice técnico): LP, ILP, CBC, PuLP, XOR, FK, PK, UUID, pigeonhole,
Hall, matching bipartito, IIS, subset-sum, hook, cascada, denormalizado,
service layer, ORM, SQLModel, Streamlit.

---

## 6. Preguntas abiertas

Estas dudas requieren aclaración antes o durante la redacción del
manual:

1. **Público objetivo**: ¿el manual apunta a un usuario administrativo
   (bedeles, secretaría académica) o a un usuario técnico del equipo
   de gestión académica? El nivel de tecnicismo aceptable cambia
   radicalmente.
2. **Estado del reset**: el flujo F1 (bootstrap) ¿debe entrar en el
   manual o queda como apéndice técnico? El reset destructivo es
   peligroso.
3. **Flujo F3 (clonar ciclo)**: hoy es CLI puro. ¿Se documenta o se
   deja fuera del alcance del manual del usuario final?
4. **F4 (reasignar aulas)**: la política sobre `fecha_desde` y las
   consecuencias temporales (clases anteriores intactas, posteriores
   pisadas) es sutil. ¿El manual la explica en detalle o presenta
   una recomendación tipo "por default, todo desde hoy en adelante"?
5. **Alta de comisión post-activación (F5)**: ¿cuál es el
   procedimiento oficial exacto? Hoy la UI lo permite pero la
   regeneración de `ClaseDB` no está claramente disparada — hay
   que rastrearlo en código para saber si es automática o no.
6. **Cambio manual de aula (F6)**: sin marca visual persistente de
   "editado manualmente" en el patrón, ¿cómo se comunica al usuario
   qué asignaciones son "del LP" y cuáles "editadas"? ¿Se agrega
   una columna al panel?
7. **Verificación pre-inicio (F7)**: ¿conviene desarrollar una
   página consolidada "🔍 Checklist de cierre" que agregue todos
   los ítems de la sección 4? Está fuera del scope de la
   documentación pero sería útil pedirlo como feature.
8. **Cambios de plan a mitad de cuatrimestre**: no aparece
   descrito en `WORKFLOW.md` § 4.3 del modelo (que lo modela
   teóricamente), pero no se documenta cómo hacerlo en la práctica
   con dos planes coexistiendo. ¿Aplica al manual?
9. **Rollback de un ciclo entero**: el borrado en cascada
   (`_delete_ciclo_cascade`) es destructivo. ¿Se recomienda hacerlo
   desde la UI o pedir backup previo?
10. **Multi-usuario / concurrencia**: la app es local en SQLite. Si
    hay más de un operador, ¿cómo se coordinan? ¿Hay política de
    "un usuario a la vez"?

---
