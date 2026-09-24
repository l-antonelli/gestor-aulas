# Requerimientos del sistema gestor-aulas

Este documento centraliza los requerimientos funcionales (RF) y no
funcionales (RNF) del sistema, en cumplimiento de la regla 10 de
`CLAUDE.md`. La intención es que actúe como índice maestro: cada
requerimiento describe brevemente el "qué" y referencia el documento
canónico donde está desarrollado el "cómo" (planteo, diseño o
implementación).

**Mantenimiento**: cada cambio relevante de la aplicación debe revisar
este archivo. Si introduce una capacidad nueva, agregar un RF; si
modifica una existente, actualizar la entrada correspondiente y, si
cambia el estado de implementación, ajustar la matriz de cobertura.

## Reglas de redacción

- **No usar em-dashes (`—`)**: suenan a texto generado por IA y no
  reflejan el registro rioplatense natural que buscamos para el
  informe y para la documentación en general. Reemplazarlos según
  el sentido de la oración: por comas cuando enmarcan una aclaración
  breve, por paréntesis cuando es un inciso lateral, por dos puntos
  cuando introducen una explicación, por punto seguido cuando
  separan ideas independientes, o simplemente reformulando la
  oración. Esta regla aplica tanto al informe (`project/Informe/**`)
  como al resto de la documentación del proyecto.

## Convenciones

- **Estados**: ✅ Implementado · 🟡 Parcial · ⏳ Pendiente.
- **Prefijos por área**: CAT (catálogo), CICLO (ciclos y dictados),
  PLAN (plan de cursada), LP (asignación de aulas), ADHOC (gestión
  manual), DIAG (diagnóstico/validación), UI (interfaz), DOC
  (documentación).
- Los IDs son estables: una vez asignado, no se reusa ni reordena.

## RF — Requerimientos funcionales

### RF-CAT — Catálogo (carreras, materias, planes, aulas, sedes)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-CAT-01 | CRUD de carreras (alta, edición, baja, atributos académicos como `dicta_recursado`). | ✅ | `1. Diseño/modelo-planificacion-cursada.md` |
| RF-CAT-02 | CRUD de materias con horas de teoría/laboratorio, virtual, marca de recursado por materia. | ✅ | `1. Diseño/modelo-planificacion-cursada.md` |
| RF-CAT-03 | Carga inicial desde Excel (`scripts/load_initial_data.py`). | ✅ | `2. Desarrollo/CARGA_DATOS_INICIALES.md` |
| RF-CAT-04 | CRUD de aulas asociadas a sede, con tipo (teorica/practica/laboratorio/anfiteatro) y capacidad. | ✅ | `app/pages/2_🏛️_Aulas.py` |
| RF-CAT-05 | CRUD de sedes (renombrar, fusionar, borrar si no tiene aulas). | ✅ | `app/pages/2_🏛️_Aulas.py` |
| RF-CAT-06 | Compatibilidad M:N materia ↔ laboratorio (`MateriaLaboratorioDB`). | ✅ | `1. Diseño/modelo-planificacion-cursada.md` |
| RF-CAT-07 | Versionado de planes de estudio por carrera (`PlanCarreraVersionDB`). | ✅ | `1. Diseño/modelo-planificacion-cursada.md` |
| RF-CAT-08 | Ubicación curricular materia↔carrera (`PlanEstudioDB`) con año, cuatrimestre, optativa. | ✅ | `1. Diseño/modelo-planificacion-cursada.md` |
| RF-CAT-09 | Correlativas materia ↔ materia por carrera. | ✅ | modelo |
| RF-CAT-10 | **Grupos de Materias (2026-09)**. Cada `MateriaDB` pertenece a exactamente un `GrupoMateriaDB` (partición estricta, `grupo_id NOT NULL`). Cada grupo declara **dos configuraciones simultáneas** de sedes: set duro (R10) y lista blanda ordenada (R12). El bootstrap crea automáticamente los grupos `Sin clasificar`, `FB`, `F`, `FI`, `CE` y `Específicas de <Carrera>` por cada carrera. La UI de Materias tiene una pestaña "📦 Grupos de materias" para editar el modo, las sedes, y reasignar materias entre grupos (con filtro "Sólo sin clasificar" para atacar el backlog). | ✅ | `src/services/grupo_materia_service.py`, `1. Diseño/modelo-planificacion-cursada.md` § 0.1.9 |
| RF-CAT-11 | **Chequeo de consistencia por grupo** (2026-09). Cada `GrupoMateriaDB` puede asociarse a 0..N carreras (`GrupoMateriaCarreraDB`) y expone tres flags configurables (pertenencia, exclusividad, completitud) que gobiernan el chequeo de consistencia (`chequear_consistencia_grupo`). Reporta `faltantes` (materias que corresponderían al grupo pero están en otro) y `ajenas` (materias en el grupo que violan los ejes activos). Herramienta de curación; no afecta al LP. | ✅ | `src/services/grupo_materia_service.py:chequear_consistencia_grupo`, `src/ui/grupo_materia_editor.py` |

### RF-CICLO — Ciclos académicos y dictados

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-CICLO-01 | Definición de ciclos lectivos (año + número 1C/2C, fecha inicio/fin). | ✅ | `2. Desarrollo/WORKFLOW.md` |
| RF-CICLO-02 | Asociación de planes de estudio a un ciclo (`CicloPlanVersionDB`). | ✅ | modelo |
| RF-DICT-01 | Generación automática de dictados a partir de las materias de los planes asociados al ciclo. Semántica "existencia = activación": si la regla de recursado dice omitir, el dictado NO se crea (aparece como skipped). | ✅ | `src/services/dictado_service.py:create_dictados_for_ciclo` |
| RF-DICT-02 | Regla de recursado jerárquica: `MateriaDB.dicta_recursado` (Optional[bool], override) prevalece sobre `CarreraDB.dicta_recursado`. Se resuelve con `resolve_dicta_recursado`. | ✅ | `src/services/resolucion_jerarquica.py`, `src/services/dictado_service.py:_should_skip_for_recursado` |
| RF-DICT-03 | Un dictado existe ↔ se dicta en ese ciclo. Para "desactivar" hay que borrar la fila (`borrar_dictado_de_ciclo`). Semántica reemplaza al viejo flag `DictadoDB.activo` que fue eliminado. | ✅ | `2. Desarrollo/CICLOS_Y_DICTADOS.md` |
| RF-DICT-04 | Virtualidad jerárquica en 3 niveles: `HorarioDB.virtual > DictadoDB.virtual > MateriaDB.virtual`. Los dos primeros son `Optional[bool]` (None = heredar). El nivel más específico manda. Se resuelve con `resolve_virtual`. | ✅ | `src/services/resolucion_jerarquica.py`, `2. Desarrollo/CICLOS_Y_DICTADOS.md` |
| RF-DICT-05 | Bridge `DictadoCicloDB` para soportar dictados anuales que cubren dos ciclos. | ✅ | modelo |
| RF-DICT-06 | Sincronización dictados ↔ regla vigente (`sync_dictados_para_ciclo`): diff con `to_create` (faltantes), `to_delete` (huérfanos) y `rule_says_skip_but_exists` (existen pero la regla dice que no; no se borran automáticamente). Modo preview + apply. | ✅ | `src/services/dictado_service.py:sync_dictados_para_ciclo` |
| RF-DICT-07 | Panel de divergencias con acciones fila-a-fila (`[✅ Crear]` / `[🗑️ Borrar]` / `[⬆️ Promover a regla]` / `[⏭️ Omitir en regla]`) + bulk masivos con confirmación en 2 pasos. | ✅ | `src/ui/divergencias_panel.py`, `2. Desarrollo/CICLOS_Y_DICTADOS.md` |
| RF-DICT-08 | Promover una decisión del ciclo a regla general en `MateriaDB.dicta_recursado` (`promover_a_regla`): setea True (crear-en-regla) o False (omitir-en-regla). Sólo modifica el catálogo, no toca dictados existentes. | ✅ | `src/services/dictado_service.py:promover_a_regla` |
| RF-DICT-09 | Virtualidad por horario individual en cronogramas: columna "Virtual" en los data editors de entries. Desde 2026-09-23 es un **casillero booleano** (antes era un selector de 3 estados Heredar / Sí / No, opaco para el usuario): destildado = presencial, tildado = virtual. Se persiste en `ScheduleEntryDB.virtual` y se propaga a `HorarioDB.virtual` al generar el plan; a nivel modelo el campo sigue siendo `Optional[bool]` y un `None` heredado de datos viejos se interpreta como el flag de catálogo de la materia al renderizar (`build_schedule_grid`). Permite mezclar modalidades dentro de un dictado (ej. teoría virtual + laboratorio presencial). | ✅ | `app/pages/6_📅_Cronogramas.py`, `src/services/plan_generation_service.py` |
| RF-DICT-10 | Edición inline de `HorarioDB.virtual` en la grilla del plan (`plan_grilla_editor`), con misma UX de 3 estados. Cambios explícitos al flag emiten evento al change log con `origin=ui:planes` (HorarioDB no está en TRACKED_ENTITIES para evitar ruido al generar planes masivos). | ✅ | `src/ui/plan_grilla_editor.py` |

### RF-PLAN — Plan de cursada (cronograma + comisiones)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-PLAN-01 | Generación de comisiones por dictado con coeficientes de asignación. | ✅ | `src/services/comision_service.py` |
| RF-PLAN-02 | Generación de horarios por comisión a partir del cronograma cargado. | ✅ | `src/services/plan_generation_service.py` |
| RF-PLAN-03 | *(Deprecado)* Materialización de `HorarioDB` a `ClaseDB` por cada fecha del ciclo. La generación de clases puntuales quedó fuera del alcance operativo: el LP y la UI trabajan exclusivamente sobre el patrón semanal (`HorarioDB`). `ClaseDB` permanece en el modelo como cache técnico del LP pero no se materializa desde la UI. | 🚫 Deprecado | — |
| RF-PLAN-04 | Validación de cobertura (faltantes, no esperadas, conflictos por carrera/año/cuatri). | ✅ | `src/ui/validation_ui.py`, `2. Desarrollo/VALIDACIONES.md` |
| RF-PLAN-05 | Detección de materias virtuales tanto a nivel catálogo como dictado. | ✅ | `src/ui/validation_ui.py` |
| RF-PLAN-06 | Estimación de inscriptos esperados por comisión a partir de series históricas y forecast configurable. | ✅ | `src/services/forecast_service.py` |
| RF-PLAN-07 | *(Deprecado)* Las `ClaseDB` heredan `aula_id` y `tipo_clase` del patrón. Ver RF-PLAN-03. La propagación patrón→clase sigue viva en `apply_solution` como cache, pero no se expone en la UI. | 🚫 Deprecado | — |
| RF-PLAN-08 | **Excepciones de conflicto ignorado** (`IgnoredConflictDB`). Permite marcar un par de materias como "ignorado" para el chequeo de solapamiento del plan (`validar_conflictos_horarios_plan`). Sirve para modelar casos como materias homónimas de años distintos que en la práctica cursan alumnos distintos. Se registra con `plan_cursada_id + (materia_a < materia_b)`. **No aplica** al chequeo de intersede (R13, R13-camino) — el traslado físico es independiente de qué alumnos cursen qué. | ✅ | `src/database/models.py:IgnoredConflictDB`, `src/services/plan_validation_service.py` |
| RF-PLAN-09 | **Auto-limpieza de excepciones stale**. `cleanup_stale_ignored_pairs` corre en cada `validate_plan` y elimina pares cuyas materias ya no coexisten en ningún grupo curricular `(carrera, año, cuatri)` del plan. Reporta la limpieza en `summary.excepciones_stale_removidas`. | ✅ | `src/services/plan_validation_service.py:cleanup_stale_ignored_pairs` |
| RF-PLAN-10 | **Preview de impacto al editar horario** (2026-09). `preview_cambio_horario` computa el impacto de mover un horario a un nuevo slot: horarios afectados, cambios de tipo, `colisiones_aula` (otros horarios que ocupan la misma aula en la franja destino). El componente compartido `render_preview_impacto_edicion` en `horario_edit_shared.py` unifica la UX en Detalle del plan (grilla y por materia) y Aulas por sede. Ofrece un botón para liberar el aula del ocupante y dejar que el LP la reasigne. | ✅ | `src/services/plan_actions_service.py:preview_cambio_horario`, `src/ui/horario_edit_shared.py` |

### RF-LP — Asignación de aulas (programación lineal)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-LP-01 | Modelo LP completo R1–R7 (cobertura, asignación única, tipo compatible, no doble booking, partición teoría/lab, capacidad blanda). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-02 | Restricción opcional R9 (penalización por sobre-utilización ponderada por λ). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-03 | Toggle α: redistribución de coeficientes de comisión cuando hay desbalance. | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-04 | Re-ejecución incremental desde `fecha_desde`: clases anteriores quedan intactas. | ✅ | `2. Desarrollo/asignador_implementacion.md` |
| RF-LP-09 | El LP asigna aulas al **patrón** (`HorarioDB.aula_id`), no directamente a clases. Esto separa "asignación del esquema semanal" (responsabilidad del LP) de "excepciones puntuales por fecha" (responsabilidad del usuario). | ✅ | `src/services/asignacion_aulas_service.py:apply_solution` |
| RF-LP-10 | Edición del patrón post-LP vía `cambiar_aula_horario`: cambia `HorarioDB.aula_id`. La propagación al cache `ClaseDB` se mantiene por si en el futuro se re-habilita alguna vista por fecha, pero el usuario no la ve. | ✅ | `src/services/asignacion_aulas_service.py:cambiar_aula_horario` |
| RF-LP-05 | *(Legacy)* Toggle "respetar ediciones manuales" del LP: preserva `ClaseDB.aula_asignada_manualmente=True`. Se conserva como capacidad del solver por si vuelven las clases puntuales; hoy no hay UI que setee el flag. | 🚫 Sin UI | `2. Desarrollo/asignador_implementacion.md` |
| RF-LP-06 | Persistencia de `LPRunDB` con snapshot completo (config, status, métricas, detalles). | ✅ | `src/database/models.py` |
| RF-LP-07 | Resolución con CBC y timeout configurable. | ✅ | `LPConfig.timeout_seconds` |
| RF-LP-08 | Filtrado de horarios virtuales (catálogo y dictado) en el armado de inputs. | ✅ | `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-11 | **R10 — Sedes admisibles por Grupo de Materias** (redefinido 2026-09). Cada `MateriaDB` pertenece a exactamente un `GrupoMateriaDB` (partición estricta). El grupo declara dos configuraciones simultáneas: un set duro (sedes admisibles en modo DURO, R10) y una lista blanda ordenada (sedes preferidas en modo BLANDO, R12). El modo por-grupo se elige por corrida desde `LPConfig.modos_por_grupo`. En modo DURO, `x[h, a] = 0` si `sede(a)` no está en el set duro del grupo. Fallback: set duro vacío = todas admisibles (permisivo). La compatibilidad de laboratorio (`MateriaLaboratorioDB`) prevalece: un aula listada como lab compatible es admisible aunque su sede no esté en el set duro. `CarreraSedeDB` y `SedeDB.es_default_comunes` quedan deprecados. | ✅ | `src/services/grupo_materia_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-12 | **Auto-completar tipo de horario por horas declaradas**. Cuando una materia tiene `hlab=0` y `hteo>0` (o viceversa), el tipo de cada horario queda determinado de antemano. La acción `aplicar_auto_completar_tipos` persiste ese tipo en `HorarioDB.tipo_clase` para el plan. Adicionalmente, `build_inputs` aplica el override en memoria como red de seguridad: si el operador no corrió la acción, el LP arranca igual con menos variables `t[h]` redundantes. | ✅ | `src/services/plan_actions_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-13 | **Heatmap demanda vs oferta**. Mapa día × franja con la peor saturación por celda (cantidad de horarios simultáneos sobre cantidad de aulas admisibles tras R3 + R10), categorizado por tipo (teórica / laboratorio-por-materia / sin determinar). Identifica el cuello de botella concreto cuando el LP es infactible. | ✅ | `src/services/asignacion_aulas_helpers.py:compute_heatmap_demanda_oferta`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-14 | **Reporte de impacto de R10**. Tabla por materia con cuántas aulas admisibles tenía sólo por R3 (tipo + lab) y cuántas le quedan tras R10 (sede). Permite responder "¿la infactibilidad la causa la configuración de sedes o el inventario?". | ✅ | `src/services/asignacion_aulas_helpers.py:compute_impacto_r10`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-15 | **`ComisionDB.carrera_asignada` como etiqueta visual** (redefinido 2026-09). El campo sobrevive como etiqueta informativa a nivel comisión ("esta comisión está pensada para alumnos de X"), pero **ya no interviene** en la resolución de sedes admisibles del LP. La resolución va exclusivamente por el grupo de la materia (RF-LP-11) y el modo por-grupo. La razón: modelar la preferencia por-comisión como override introducía divergencias entre lo que veía el operador y lo que resolvía el LP; el modelo de grupos permite el mismo efecto de manera unificada moviendo la materia al grupo correcto o dividiendo el grupo. Los cambios de `carrera_asignada` siguen emitiéndose al `ChangeLogDB`. | ✅ | `src/database/models.py:ComisionDB`, UI de edición de comisión |
| RF-LP-16 | **R12 — Preferencia blanda de sede por Grupo BLANDO** (2026-09). Cuando el grupo de la materia corre en modo BLANDO, todas las sedes son admisibles (R10 no filtra) pero la primera de la lista blanda es la preferida (paga cero al objetivo). Las alternativas suman `λ_sede_pref` al objetivo por cada horario asignado a ellas. Penalidad plana: da igual la segunda que la quinta. `λ_sede_pref` es configurable en el panel; con 0 se desactiva el término. | ✅ | `src/services/asignacion_aulas_service.py:build_model`, `src/services/grupo_materia_service.py` |
| RF-LP-17 | **R13 — Continuidad de sede en pares en riesgo (docente y alumno)** (2026-09). Para cada par de horarios contiguos el mismo día con gap menor a `margen_min_intersede_minutos`, el LP prohíbe asignarlos a sedes distintas. Se detectan dos ejes: (a) **traslado del docente** para pares de la misma comisión, (b) **traslado del alumno** para pares de materias distintas del mismo grupo curricular `(carrera, año, cuatri)`. Con `margen_min_intersede = 0` la restricción se desactiva. Configurable en el panel del asignador. | ✅ | `src/services/asignacion_aulas_helpers.py:compute_pares_intersede_riesgo`, `src/services/asignacion_aulas_service.py:build_model` |
| RF-LP-18 | **R13-camino — Camino de cursada intersede factible (pre-check estructural)** (2026-09). Antes de correr el LP, `check_camino_cursada` verifica que para cada terna `(carrera, año, cuatri)` exista al menos una combinación de comisiones (una por materia obligatoria) que un alumno pueda cursar sin conflictos horarios ni traslados imposibles entre sedes. Backtracking DFS con cache por par. Cap `MAX_COMBINACIONES_CAMINO = 10 000`. Ignora `IgnoredConflictDB` para el chequeo de intersede (el traslado es físico, independiente de qué alumnos cursen qué). Aparece como bloqueo `R13-camino` en el semáforo pre-solve. | ✅ | `src/services/factibilidad_service.py:check_camino_cursada` |
| RF-LP-19 | **R14 — Forzar misma sede por comisión (opcional)** (2026-09). Toggle `LPConfig.forzar_misma_sede_por_comision` que introduce variables auxiliares `y[c, s] ∈ {0, 1}` para cada comisión × sede, con `Σ_s y[c, s] = 1` y `x[h, a] ≤ y[c, sede(a)]` para todo horario `h` de `c`. Impide fragmentar una comisión entre sedes. Default `False`. Configurable en el panel del asignador. | ✅ | `src/services/asignacion_aulas_service.py:build_model` (bloque R14) |
| RF-LP-20 | **Chequeo estructural pre-solve consolidado** (2026-09). `check_factibilidad_estructural` en `factibilidad_service.py` reúne todas las familias de bloqueo (R1 sin aula compatible, R3+R4 saturación por tipo, R5 partición, R11 pin incompatible, R13, R13-camino, compat-pigeonhole, compat-hall) y devuelve un `ReporteFactibilidad`. Se ejecuta automáticamente antes del solve; si hay bloqueos, se saltea al solver y se persiste una corrida `infeasible_estructural`. El panel del asignador expone un botón "🚦 Chequear factibilidad" que dispara el reporte aislado. | ✅ | `src/services/factibilidad_service.py` |
| RF-LP-21 | **Veredicto estructurado por corrida** (2026-09). Cada `LPRunDB.details_json` incluye un bloque `veredicto` con `status` (`optimal` / `infeasible_estructural` / `infeasible` / `timeout` / `error`), `resumen` humano-legible, `causa_infactibilidad`, `bloqueos_diagnosticados`, `horarios_sin_asignar` y `restricciones_activas` (dump completo de `LPConfig` incluyendo `modos_por_grupo`). Permite reproducir cualquier corrida vieja con exactitud. | ✅ | `src/services/asignacion_aulas_service.py:persist_run`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-22 | **Saneamiento de virtuales stale al aplicar la solución** (2026-09). `apply_solution` recibe `no_ocupa_aula_ids` (horarios excluidos del modelo por ser virtuales) y libera activamente su `aula_id` si arrastraban aula de una corrida anterior. Preserva la invariante "horario virtual ⇒ sin aula". Preserva el pin manual si el usuario lo había fijado y el toggle "respetar ediciones manuales" está activo. | ✅ | `src/services/asignacion_aulas_service.py:apply_solution` |
| RF-LP-23 | **Prefill del panel con la última corrida** (2026-09). Al abrir Planes → Aulas, el panel del asignador se prefill con los parámetros de la última corrida del plan usando un fingerprint por-plan. Los cambios no aplicados persisten en `session_state`; la corrida usa los valores del panel. Al refrescar la página se re-hidrata desde la base (útil frente a pestañas múltiples). | ✅ | `src/ui/asignacion_panel.py` |

### RF-COMISION — Gestión de comisiones como entidad

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-COMISION-01 | **Las comisiones son entidades reales** (`ComisionDB`) que pueden pertenecer a un cronograma (`schedule_id` seteado) o a un plan de cursada (`plan_cursada_id` seteado), pero no a ambos a la vez (XOR validado a nivel service). Reemplaza al viejo campo `ScheduleEntryDB.comision: int` que era identificador de facto sin entidad. `ScheduleEntryDB.comision_id` y `HorarioDB.comision_id` son ambos FK a `ComisionDB`. Los atributos de la comisión (nombre, cupo, coef_asignacion, carrera_asignada, descripción) son editables desde una tabla dedicada — antes del refactor solo existían al momento de generar el plan y no podían editarse en la etapa de cronograma. | ✅ | `src/database/models.py:ComisionDB`, `src/services/comision_service.py`, `2. Desarrollo/sesiones/COMISIONES_POR_CARRERA.md` |
| RF-COMISION-02 | **Cascada cronograma → plan por clonado**. Al generar un plan desde un cronograma, las comisiones template del cronograma se **clonan** (nuevos IDs, `plan_cursada_id` seteado, `schedule_id=None`) preservando nombre, cupo, coef_asignacion, carrera_asignada, descripción. Los `HorarioDB` del plan apuntan a las comisiones clon. Editar la comisión del plan no afecta a la del cronograma template (ciclo de vida independiente). | ✅ | `src/services/comision_service.py:clone_comisiones_for_plan`, `src/services/plan_generation_service.py:generate_plan_from_preview` |
| RF-COMISION-03 | **Borrado seguro con guarda**: `delete_comision` bloquea el borrado si la comisión tiene entries de cronograma o horarios de plan asociados. El usuario debe reasignarlos primero. Evita "huérfanos" no intencionales por borrar comisiones activas. | ✅ | `src/services/comision_service.py:delete_comision` |
| RF-COMISION-04 | **UI: selector de comisiones en cronogramas y planes**. En la tabla de entries del cronograma y en el diálogo "Editar entrada" del calendario, la columna/campo "Comisión" es un selectbox de comisiones existentes (label `{N° · nombre}`) + opción "➕ Crear nueva comisión…" que abre un form inline (nombre, cupo, carrera_asignada, descripción). No se depende más de que el usuario ingrese un número arbitrario. | ✅ | `app/pages/6_📅_Cronogramas.py`, `src/ui/schedule_materia_editor.py` |

### RF-ADHOC — Gestión ad-hoc post-LP *(deprecada)*

Todo el bloque de "clases puntuales" (RF-ADHOC-01..05, RF-ADHOC-09) fue
eliminado en la decisión operativa de trabajar solo sobre el patrón
semanal. Los servicios `aplicar_edicion_manual`,
`cambiar_tipo_clase_puntual`, `clases_del_rango`,
`validar_edicion_manual` y `get_aulas_disponibles` se borraron del
código; sus tests también. El tab "📅 Clases" de la página de Planes
y el diálogo `_dialog_cambiar_aula` de `aula_cronograma_view.py`
también se sacaron.

Las capacidades que **quedan** en producción y no eran puntuales:

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-ADHOC-06 | Filtros multi-dimensionales en panel Aulas del plan: aula, carrera, año, cuatri, tipo de clase, materia, día, sede. | ✅ | `src/ui/aula_cronograma_view.py` |
| RF-ADHOC-07 | Vista de calendario semanal por aula (a nivel patrón). | ✅ | `src/ui/aula_cronograma_view.py` |
| RF-ADHOC-08 | Activación de materia y marca virtual en bloque desde el panel de validación. | ✅ | `src/ui/validation_ui.py` |

### RF-DIAG — Diagnóstico y validación

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-DIAG-01 | Cotas estructurales de infactibilidad (pigeonhole, partición, horarios sin aula compatible, saturación por tipo, Hall, R11 pin incompatible, R13, R13-camino). | ✅ | `src/services/factibilidad_service.py` |
| RF-DIAG-02 | Diagnóstico cruzado por relajación (IIS) cuando las cotas estructurales no detectan la causa: relaja R4/R5/R6/R10/R13/R14 individualmente y reporta culpables. Filtra falsos positivos por interacción con R4 saturadora. Prioriza causa principal con orden `R10 → R14 → R13 → R4 → R5 → R6`. | ✅ | `src/services/asignacion_aulas_service.py:_run_iis_relajacion` |
| RF-DIAG-03 | Filtrado de falsos positivos en IIS y selección de causa principal. R5 se descarta si ninguna materia con `hlab>0` quedó desalineada. R6 se descarta si todos los `t[h]=⊥` tenían alternativa. | ✅ | `1. Diseño/asignacion-aulas-LP.md` § 8.2 |
| RF-DIAG-04 | Validación de cobertura por carrera/año/cuatri con clasificación de discrepancias (faltantes, no esperadas, conflictos). | ✅ | `2. Desarrollo/VALIDACIONES.md` |
| RF-DIAG-05 | **Análisis refinado cuando R10 es la culpable** (2026-09). Cuando R10 rescata al modelo, `_iss_r10_grupos_rescate` prueba pasar cada grupo DURO a BLANDO por separado y lista los que rescatan individualmente. La UI recomienda "pasá el grupo *X* a modo BLANDO" con el grupo de menor impacto (menos materias en el plan). | ✅ | `src/services/asignacion_aulas_service.py:_iss_r10_grupos_rescate` |
| RF-DIAG-06 | **Análisis combinado cuando ninguna regla individual rescata** (2026-09). `_iss_combinaciones_rescate` prueba pares de relajaciones (cada grupo DURO→BLANDO combinado con desactivar R14, y con margen intersede en 0). Cap `CAP_PRUEBAS = 40`. La UI presenta las combinaciones ordenadas por menor impacto. | ✅ | `src/services/asignacion_aulas_service.py:_iss_combinaciones_rescate` |
| RF-DIAG-07 | **Panel de calidad del plan** (2026-09). En Planes → Detalle, muestra 4 familias de métricas de la última corrida: cobertura (asignados/totales, preferida/alternativa, comisiones completas), ajuste al forecast (sobrecupo/subutilización, ratio promedio/P50/P90, peor caso), uso del catálogo (aulas usadas/ociosas, concentración por sede), estado del LP (objetivo, tiempo, ediciones manuales, traslados intersede). Se computa a partir del estado vigente, no del snapshot. | ✅ | `src/services/metricas_calidad_service.py`, panel de Detalle del plan |

### RF-AUDIT — Trazabilidad de cambios (change log)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-AUDIT-01 | Registro automático de mutaciones en entidades trackeadas (MateriaDB, CarreraDB, DictadoDB, DictadoCicloDB, SedeDB) vía hooks SQLAlchemy `after_insert/update/delete`. Solo auditamos catálogo/política; HorarioDB/ComisionDB/ClaseDB quedan afuera (datos de operación). | ✅ | `src/services/change_log_service.py` |
| RF-AUDIT-02 | Whitelist de campos por entidad (ej. MateriaDB → `virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`, `horas_laboratorio`). Cambios en campos fuera de la lista no generan ruido. | ✅ | `TRACKED_ENTITIES` en `change_log_service.py` |
| RF-AUDIT-03 | Eventos de dominio explícitos con `reason` y `origin` (`emit_event`, `change_context`) para trazar la intención detrás del cambio ("Promoción a regla desde el ciclo X", "Aceptar materia del cronograma"). | ✅ | `src/services/change_log_service.py:emit_event` |
| RF-AUDIT-04 | Página **📜 Historial** con dos vistas: feed global filtrable por tipo de entidad y origen, y vista por entidad puntual. | ✅ | `app/pages/8_📜_Historial.py`, `src/ui/historial_widget.py` |

### RF-UI — Interfaz de usuario

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-UI-01 | Aplicación Streamlit con páginas separadas por dominio (Aulas, Materias, Carreras, Ciclos, Planes). | ✅ | `app/pages/` |
| RF-UI-02 | Indicadores visuales de estado (badges 🟢⚪✋ ←override, virtual, manual). | ✅ | UI |
| RF-UI-03 | Edición inline con toggles auto-save + `st.toast` de confirmación. | ✅ | `app/pages/4_📆_Ciclos.py` |
| RF-UI-04 | Calendario semanal renderizado con `render_timetable_calendar`. | ✅ | `src/ui/calendar_render.py` |
| RF-UI-05 | *(Deprecado)* Diálogo modal de edición de aula/tipo con alcance configurable (para clases puntuales). Eliminado con la deprecación de clases puntuales. | 🚫 Deprecado | — |

### RF-DOC — Documentación operativa y conceptual

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-DOC-01 | Runbook operativo de gestión de ciclos y dictados: cómo crear un ciclo desde cero, cargar horarios, chequeos previos al asignador, escenarios recurrentes. Incluye ejemplo concreto de carga del 2C 2026 para demo. | ✅ | `2. Desarrollo/CICLOS_Y_DICTADOS.md` |
| RF-DOC-02 | Mapa conceptual de las tres puertas de decisión de un dictado (pertenencia estructural, regla de recursado, modalidad virtual) con su jerarquía de override respectiva y cómo se combinan. | ✅ | `2. Desarrollo/CICLOS_Y_DICTADOS.md § 1.2` |
| RF-DOC-03 | Regla de independencia entre ciclos (RN19): cada ciclo es unidad operativa autónoma, con excepción de dictados anuales compartidos vía `DictadoCicloDB`. | ✅ | `1. Diseño/modelo-planificacion-cursada.md § 6 (RN19)` |

### RF-IMPORT — Importer masivo de cronograma e inscriptos (rediseño 2026-09)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-IMPORT-01 | Generación de **plantilla Excel** para cargar horarios en un ciclo, con hoja `Instrucciones` en castellano rioplatense, hoja `Horarios` de 9 columnas (`nombre_materia`, `codigo_materia`, `codigo_comision`, `nombre_comision`, `dia`, `hora_inicio`, `hora_fin`, `tipo_clase`, `virtual`) con headers estilizados y freeze, definida como **tabla de Excel** (`TablaHorarios`: filtros por columna y bandeado), y hoja **visible** `Materias` (**protegida**, sólo consulta) con el contexto completo de cada materia: nombre y código primero, atributos del catálogo (Guaraní, período, horas, cupo, optativa, virtual, regla de recursado), planes de carrera en que aparece (carrera, año, cuatrimestre, optativa) y configuración del dictado del ciclo (código, modalidad resuelta, recursado) vía `obtener_contexto_materias_del_ciclo`. La materia se ingresa **sólo por código** (desplegable; quien carga debe conocer el código correcto): `nombre_materia` es la primera columna de `Horarios` y una fórmula `INDEX`/`MATCH` pre-cargada **muestra el nombre al elegir el código** como verificación visual; la hoja está **protegida sin contraseña** con esa columna bloqueada (las de carga desbloqueadas; se permiten ordenar, filtrar, insertar/eliminar filas y ajustar anchos), de modo que no puede quedar un código y un nombre que no se correspondan. Listas cerradas vía `openpyxl.DataValidation` (código de materia contra la hoja `Materias`; `_dias` según `ConfiguracionHoraria`; `_horas` discretas según granularidad; `_tipos`; `_virtual` con **booleanos reales** VERDADERO/FALSO, vacío = FALSO, convertibles a casillas de verificación nativas en Excel 365; entero ≥ 1 para `codigo_comision`). Las listas de tipo y virtual son **dependientes entre sí** (fuente `IF` por fila): con tipo laboratorio la lista de virtual sólo ofrece FALSO y con virtual VERDADERO la de tipo sólo ofrece teorica, con lo que Excel mismo impide la combinación laboratorio + virtual. `fullCalcOnLoad` activado para que las fórmulas se recalculen al abrir. Sin fila de ejemplo pre-llenada para evitar imports fantasma. Fase C1 del rediseño; rediseñada 2026-09-24. | ✅ | `src/services/template_export_service.py::generar_plantilla_cronograma_excel` |
| RF-IMPORT-02 | Preview del importer masivo (Fase G del rediseño 2026-09-15; rediseñado 2026-09-23): crea un **shadow schedule** (`ScheduleDB.es_shadow_import=True`, `shadow_target_schedule_id` apuntando al destino) que aplica el archivo sobre el destino con decisión default **"reemplazar"** por materia (preservando los atributos manuales de las comisiones homónimas). La UI del preview es un loop de expanders per-materia con: sección **✏️ Ajustes manuales** (data editor que edita el shadow antes de confirmar — corrige horarios, agrega o borra filas; se resetea si cambia la decisión), radio de decisión (reemplazar/agregar/ignorar con datos previos; **agregar/ignorar para materias nuevas**, para excluir del import un archivo que vino mal) que llama a `regenerar_materia_en_shadow` y persiste la decisión sólo si la regeneración salió bien, calendarios **Antes** (destino) y **Después** (shadow), y los mismos once chequeos estructurales del panel Validar. El título de cada tarjeta refleja el estado, la decisión "se ignora" y los errores pendientes. Debajo, métricas globales + confirmar/descartar. Al confirmar (`finalizar_shadow_import`) el destino se pisa con el shadow y el toast reporta métricas honestas por diff de fingerprints con aritmética de multiconjuntos (`entries_agregadas` / `entries_eliminadas` / `entries_sin_cambio`); re-importar los mismos datos reporta "sin diferencias". Los shadows se filtran de `get_all_schedules` y del wizard del plan. | ✅ | `src/services/cronograma_import_service.py`; `2. Desarrollo/WORKFLOW.md § 4.1` |
| RF-IMPORT-03 | Detección y limpieza de **shadows huérfanos** cuando el usuario cierra el navegador con un preview abierto. La tab Cargar muestra un banner amarillo listando cada shadow huérfano con botón "Descartar". | ✅ | `cronograma_import_service.list_shadows_huerfanos` |
| RF-IMPORT-04 | Generación de **plantilla Excel** para carga masiva de inscriptos históricos: hoja `Instrucciones`, hoja `Inscriptos` con listas desplegables cerradas (`_materias` con todo el catálogo activo, `_cuatris` `1C/2C/Anual`), validaciones tipográficas de año (2000-2100) e inscriptos (entero ≥0). Sin fila de ejemplo pre-llenada. Fase E1 del rediseño. | ✅ | `template_export_service.generar_plantilla_inscriptos_excel` |
| RF-IMPORT-05 | Preview + commit del importer de inscriptos con **resolución jerárquica** de códigos: `alias > guaraní > match directo`. Detección de duplicados intra-archivo (última fila gana), pre-carga en batch de existentes, clasificación por materia y por (año, cuatri). Si el alias apunta a un target inexistente en el catálogo, la fila se rechaza con un mensaje específico que guía a re-asignar. Fase E1/E2 del rediseño. | ✅ | `src/services/inscripcion_import_service.py::preview_import`, `commit_import` |
| RF-IMPORT-06 | Persistencia de **alias manuales** (`CodigoAliasDB`) para que un código externo resuelto una vez ("Sin matchear" → asociar) quede resuelto automáticamente en importaciones futuras. Fase E2. | ✅ | `CodigoAliasDB`; `inscripcion_import_service.registrar_alias` |
| RF-IMPORT-07 | Auditoría de la carga histórica de inscriptos: `InscripcionHistoricaDB.updated_at` + `.origen` (`manual` / `importado` / `override`) se refresca cada vez que la fila se toca (incluso cuando el importer confirma un valor que ya estaba). Fase E2. | ✅ | `InscripcionHistoricaDB`; `1. Diseño/modelo-planificacion-cursada.md § 2.8` |
| RF-IMPORT-08 | **Selector de hoja del Excel** en los dos importers masivos (cronograma e inscriptos): cuando el archivo trae más de una hoja candidata — se descartan `Instrucciones`, las hojas de sistema con prefijo `_` y las marcadas ocultas en el workbook — la UI ofrece un selectbox "Hoja del Excel a importar", pre-seleccionado en la hoja preferida del parser (`Horarios` / `Inscriptos`) para que la interfaz y el fallback no diverjan, y propaga la elección como `sheet_name` hasta el parser. Con una única hoja visible la selección se fija automáticamente. Con `sheet_name=None` se conserva el fallback histórico. No aplica a CSV. La lista de hojas se resuelve con openpyxl en modo read-only (sólo nombres, sin materializar el workbook) y se cachea por archivo. Fase I.4. | ✅ | `horario_file_parser.listar_hojas_visibles` + `hoja_default`; `WORKFLOW.md § 4.1` |
| RF-IMPORT-09 | **Validaciones de entrada del parser de horarios** (2026-09-23): se rechazan por fila (sin frenar el resto del archivo) `hora_inicio >= hora_fin`, `tipo_clase = laboratorio` marcado virtual (el laboratorio requiere aula física) y `codigo_comision` no numérico o < 1. La columna `virtual` es un **booleano**: vacío/NaN se interpreta `False` (presencial). `tipo_clase` puede quedar vacío (= "sin determinar"; lo resuelve la asignación automática por LP). Las filas totalmente vacías (típico: filas de la plantilla que sólo traen la fórmula de auto-población) se saltean en silencio. Si `codigo_materia` viene vacío pero hay `nombre_materia`, la materia se resuelve por nombre (match exacto case-insensitive, sólo si es único; orden: código de plan > Guaraní > nombre). Si se declara nombre de comisión, la correspondencia código ↔ nombre debe ser **unívoca dentro de la materia** (2026-09-24): un mismo código con dos nombres, o un mismo nombre con dos códigos, rechaza las filas; las filas sin nombre declarado no participan y al agrupar gana el nombre declarado sobre el default `C{código}`. Si la fila declara código Y nombre de materia que no se corresponden en el catálogo, la vista previa del importador la rechaza como error bloqueante (la plantilla sola no puede impedir la mezcla porque tipear el código pisa la fórmula). Las mismas reglas de coherencia (inicio < fin, laboratorio ≠ virtual) se aplican en los data editors de la UI antes de persistir (`_validar_filas_editor`). | ✅ | `horario_file_parser.parse_horarios_file`; `horario_loading_service._resolve_materia_code`; `tests/test_horario_parser_validaciones.py` |
| RF-IMPORT-10 | **Comisiones con código declarado desde la plantilla** (2026-09-23): la columna `codigo_comision` (entero ≥ 1, recomendada) es el identificador estable de la comisión dentro de la materia y se persiste como `ComisionDB.numero`; `nombre_comision` es opcional (default `C{código}`). Los horarios del archivo se agrupan por código cuando está declarado, y la colisión en la decisión `agregar` se chequea por número **y** por nombre canónico. En los calendarios de cronograma se visualiza el código (`[C2]`); el nombre aparece en la leyenda por comisión y en los editores. La columna histórica `comision` (texto libre) se sigue aceptando: se interpreta como nombre y el número se autoderiva. | ✅ | `cronograma_import_service` (agrupación + `_agregar_comisiones_nuevas`); `src/ui/calendar_render.py` |

### RF-CONFIG — Configuración horaria global (Fase H del rediseño 2026-09)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-CONFIG-01 | Entidad `ConfiguracionHoraria` (fila única) con: granularidad en minutos, hora de inicio/fin operativo, días operativos (CSV). Sirve como fuente única de verdad para todas las UIs de calendario, dropdowns de plantillas y validaciones. | ✅ | `ConfiguracionHoraria` (modelo) |
| RF-CONFIG-02 | Validación `validar_horarios_vs_config`: reporta las `ScheduleEntryDB` que rompen la config (día no operativo, rango fuera del operativo, granularidad no múltiplo). Es **warning**, no bloqueante — no impide `listo_para_plan`. Fase H.1. | ✅ | `src/services/validations.py`; `VALIDACIONES.md § 1.9` |
| RF-CONFIG-03 | Acción **"Ajustar automáticamente"** (`ajustar_horarios_a_config`): redondea las entries al slot más cercano dentro del rango operativo. Salvaguarda contra duración cero: si al ajustar quedaría `hora_fin ≤ hora_inicio` empuja `hora_inicio` un slot atrás; si eso llevaría por debajo de `hora_inicio_operativo`, skippea y reporta como "requiere corrección manual". Fase I.1. | ✅ | `validations.py::ajustar_horarios_a_config`; `VALIDACIONES.md § 1.10` |

### RF-CRONO — Panel de cronograma unificado (rediseño 2026-09)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-CRONO-01 | Tab **"Ver / Editar"** unificado en `app/pages/6_📅_Cronogramas.py` (reemplaza las tabs separadas "Visualizar" y "Editar"). Toggle **"Solo lectura"** que alterna entre modo lectura (calendario + tablas deshabilitados) y modo edición (drag/click/resize + `data_editor` con auto-save). Fase F del rediseño. | ✅ | `2. Desarrollo/WORKFLOW.md § 4.3` |
| RF-CRONO-02 | Estado por materia extendido con `Revisión`: la tabla "Detalle por materia" del panel Validar diferencia `OK` (sin warnings) de `Revisión` (con al menos un chequeo estructural en `warn` — h/sem×com no divisible, distribución desequilibrada, `hsem × com ≠ total`). El filtro "Estado" del panel es multi-select de 6 estados. Fase F. | ✅ | `VALIDACIONES.md § 3.2` |
| RF-CRONO-03 | Completitud desagregada del cronograma en el panel Validar: tabla "Por grupo de materias" (`GrupoMateriaDB`) y tabla "Por (carrera, año, cuatri)" con `n_cubiertas / n_esperadas` y accordions con faltantes. Toggle **"Excluir optativas del cómputo"** encendido por default. Fase D del rediseño. | ✅ | `src/services/cronograma_completitud_service.py`; `WORKFLOW.md § 4.4` |
| RF-CRONO-04 | Clonar un plan de cursada a un cronograma nuevo (flujo inverso "plan consolidado → cronograma reutilizable"): `clonar_plan_a_cronograma(plan_id, nombre, ciclo_id_override?)` genera un `ScheduleDB` con las `ComisionDB` del plan clonadas como comisiones del schedule y los `HorarioDB` como `ScheduleEntryDB`. No se copia `aula_id` ni `dictado_id`. Fase F. | ✅ | `src/services/schedule_service.py::clonar_plan_a_cronograma`; `1. Diseño/modelo-planificacion-cursada.md § 5.2` |
| RF-CRONO-05 | **Chequeos estructurales inline en el tab Ver / Editar** (Fase I.3, 2026-09-23): debajo del calendario aparecen los mismos once chequeos del editor por-materia y del panel Validar (más `entries_sin_comision` cuando hay horarios sin comisión asignada), con badge de estado (OK / Revisión / Sin horarios / Sin datos). En modo "Por materia" cubre la materia seleccionada; en modo "Por grupo" cubre las materias del filtro activo que tengan horarios cargados. La lógica se reusa vía `compute_materia_checks_from_db` para que los tres consumidores (editor por-materia, panel Validar y Ver/Editar) queden alineados sin duplicar código. La cantidad de comisiones se deriva de las `ComisionDB` reales del cronograma (no del máximo número, que con numeración con huecos inventaba comisiones inexistentes — fix auditoría 2026-09-23). Los estados que dependen del summary del ciclo (Conflictiva, No esperada, Faltante) siguen viviendo sólo en el panel Validar. | ✅ | `src/ui/schedule_materia_editor.py::compute_materia_checks_from_db`; `WORKFLOW.md § 4.3` |

## RNF — Requerimientos no funcionales

| ID | Descripción | Estado |
|---|---|---|
| RNF-01 | Toda la UI y la documentación se redactan en castellano rioplatense; nada de inglés en la interfaz. | ✅ |
| RNF-02 | Solver CBC con timeout configurable; el sistema debe responder en menos de 60 s para planes típicos. | ✅ |
| RNF-03 | Suite de tests pasa al merge; cada función nueva tiene test asociado (CLAUDE.md regla 4). | ✅ |
| RNF-04 | La documentación del directorio `project/` se mantiene sincronizada después de cada commit con cambios de código (CLAUDE.md regla 7). | ✅ |
| RNF-05 | TDD: bug-fix empieza por test que reproduzca el bug (CLAUDE.md regla 4). | ✅ |
| RNF-06 | Cambios mayores a 3 archivos se descomponen en subtareas (CLAUDE.md regla 2). | ✅ |
| RNF-07 | Persistencia: SQLite local con migraciones aditivas (`ALTER TABLE`) en `src/database/connection.py`. | ✅ |
| RNF-08 | Trazabilidad: cada corrida del LP queda registrada en `LPRunDB` con todos los parámetros y resultados. | ✅ |

## Matriz de cobertura por módulo

| Módulo | RFs cubiertos | Tests |
|---|---|---|
| `src/services/asignacion_aulas_service.py` | RF-LP-01..15 | `tests/test_asignacion_aulas_service.py` |
| `src/services/asignacion_aulas_helpers.py` | RF-DIAG-01..03 | `tests/test_asignacion_aulas_helpers.py` |
| `src/services/dictado_service.py` | RF-DICT-01..08 | `tests/test_dictado_service.py` |
| `src/services/resolucion_jerarquica.py` | RF-DICT-02, RF-DICT-04 | `tests/test_resolucion_jerarquica.py` |
| `src/services/change_log_service.py` | RF-AUDIT-01..03 | `tests/test_change_log_service.py` |
| `src/ui/divergencias_panel.py` | RF-DICT-07 | (UI) |
| `src/ui/historial_widget.py` | RF-AUDIT-04 | (UI) |
| `src/services/forecast_service.py` | RF-PLAN-06 | `tests/test_forecast_service.py` |
| `src/services/plan_generation_service.py` | RF-PLAN-02 | `tests/test_plan_generation_service.py` |
| `src/services/clase_generation_service.py` | *(deprecado)* — RF-PLAN-03 fuera de scope operativo | `tests/test_clase_generation_service.py` (retenidos) |
| `src/services/comision_service.py` | RF-PLAN-01 | `tests/test_comision_service.py` |
| `src/services/template_export_service.py` | RF-IMPORT-01, RF-IMPORT-04 | `tests/test_template_export_service.py` |
| `src/services/horario_file_parser.py` | RF-IMPORT-08, RF-IMPORT-09 | `tests/test_horario_parser_validaciones.py`, `tests/test_multi_sheet_import.py` |
| `src/services/cronograma_import_service.py` | RF-IMPORT-02, RF-IMPORT-03, RF-IMPORT-10 | `tests/test_cronograma_import_service.py`, `tests/test_horario_parser_validaciones.py` |
| `src/services/inscripcion_import_service.py` | RF-IMPORT-05, RF-IMPORT-06, RF-IMPORT-07 | `tests/test_inscripcion_import_service.py` |
| `src/ui/validation_ui.py` | RF-PLAN-04..05, RF-ADHOC-08 | (UI, sin tests directos) |
| `src/ui/aula_cronograma_view.py` | RF-ADHOC-06..07, RF-UI-04 | (UI, helpers cubiertos en service tests) |
| `app/pages/4_📆_Ciclos.py` | RF-CICLO-01..02, RF-DICT-* | (UI) |
| `app/pages/2_🏛️_Aulas.py` | RF-CAT-04..05 | (UI) |

## Decisiones cerradas

- **2026-07-07 (deprecación clases puntuales)**: se decidió eliminar
  del sistema el concepto de "clase puntual" (`ClaseDB` como unidad
  editable). El LP trabaja exclusivamente sobre el patrón semanal
  (`HorarioDB.aula_id`) y las clases materializadas quedan como
  cache técnico (opción C del análisis previo). Se removió: (a) tab
  "📅 Clases" de la página Planes; (b) diálogo
  `_dialog_cambiar_aula`; (c) funciones service
  `aplicar_edicion_manual`, `cambiar_tipo_clase_puntual`,
  `clases_del_rango`, `validar_edicion_manual`,
  `get_aulas_disponibles`; (d) los tests asociados. Se conservó
  `ClaseDB.aula_id`, `aula_asignada_manualmente`, `tipo_clase` y el
  toggle `respetar_ediciones_manuales` del LP como capacidad latente
  del solver (no expuesta en UI).

## Pendientes y backlog
- **RF-LP-09** (constraint de mismo edificio para clases consecutivas
  de la misma carrera/año): mencionado en discusiones pero no
  formalizado.
- **RF-UI-06** (exportar a CSV/Excel los listados filtrados del
  panel Aulas): conveniencia para auditoría externa.
- **RF-UI-07** (métricas de ocupación a nivel aula y a nivel ciclo):
  porcentaje de franjas usadas, total de horas semanales, ranking
  de aulas más cargadas. Diferido a iteración futura.
