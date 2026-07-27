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

### RF-CICLO — Ciclos académicos y dictados

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-CICLO-01 | Definición de ciclos lectivos (año + número 1C/2C, fecha inicio/fin). | ✅ | `2. Desarrollo/WORKFLOW.md` |
| RF-CICLO-02 | Asociación de planes de estudio a un ciclo (`CicloPlanVersionDB`). | ✅ | modelo |
| RF-DICT-01 | Generación automática de dictados a partir de las materias de los planes asociados al ciclo. Semántica "existencia = activación": si la regla de recursado dice omitir, el dictado NO se crea (aparece como skipped). | ✅ | `src/services/dictado_service.py:create_dictados_for_ciclo` |
| RF-DICT-02 | Regla de recursado jerárquica: `MateriaDB.dicta_recursado` (Optional[bool], override) prevalece sobre `CarreraDB.dicta_recursado`. Se resuelve con `resolve_dicta_recursado`. | ✅ | `src/services/resolucion_jerarquica.py`, `src/services/dictado_service.py:_should_skip_for_recursado` |
| RF-DICT-03 | Un dictado existe ↔ se dicta en ese ciclo. Para "desactivar" hay que borrar la fila (`borrar_dictado_de_ciclo`). Semántica reemplaza al viejo flag `DictadoDB.activo` que fue eliminado. | ✅ | `2. Desarrollo/RECURSADO_Y_VIRTUAL.md` |
| RF-DICT-04 | Virtualidad jerárquica en 3 niveles: `HorarioDB.virtual > DictadoDB.virtual > MateriaDB.virtual`. Los dos primeros son `Optional[bool]` (None = heredar). El nivel más específico manda. Se resuelve con `resolve_virtual`. | ✅ | `src/services/resolucion_jerarquica.py`, `2. Desarrollo/RECURSADO_Y_VIRTUAL.md` |
| RF-DICT-05 | Bridge `DictadoCicloDB` para soportar dictados anuales que cubren dos ciclos. | ✅ | modelo |
| RF-DICT-06 | Sincronización dictados ↔ regla vigente (`sync_dictados_para_ciclo`): diff con `to_create` (faltantes), `to_delete` (huérfanos) y `rule_says_skip_but_exists` (existen pero la regla dice que no; no se borran automáticamente). Modo preview + apply. | ✅ | `src/services/dictado_service.py:sync_dictados_para_ciclo` |
| RF-DICT-07 | Panel de divergencias con acciones fila-a-fila (`[✅ Crear]` / `[🗑️ Borrar]` / `[⬆️ Promover a regla]` / `[⏭️ Omitir en regla]`) + bulk masivos con confirmación en 2 pasos. | ✅ | `src/ui/divergencias_panel.py`, `2. Desarrollo/RECURSADO_Y_VIRTUAL.md` |
| RF-DICT-08 | Promover una decisión del ciclo a regla general en `MateriaDB.dicta_recursado` (`promover_a_regla`): setea True (crear-en-regla) o False (omitir-en-regla). Sólo modifica el catálogo, no toca dictados existentes. | ✅ | `src/services/dictado_service.py:promover_a_regla` |
| RF-DICT-09 | Virtualidad por horario individual en cronogramas: columna "Virtual" (3 estados: Heredar / Sí / No) en el data_editor de entries. Se persiste en `ScheduleEntryDB.virtual: Optional[bool]` y se propaga a `HorarioDB.virtual` al generar el plan. Permite mezclar modalidades dentro de un dictado (ej. teoría virtual + laboratorio presencial). | ✅ | `app/pages/6_📅_Cronogramas.py`, `src/services/plan_generation_service.py` |
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

### RF-LP — Asignación de aulas (programación lineal)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-LP-01 | Modelo LP completo R1–R7 (cobertura, asignación única, tipo compatible, no doble booking, partición teoría/lab, capacidad blanda). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-02 | Restricción opcional R9 (penalización por sobre-utilización ponderada por λ). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-03 | Toggle α: redistribución de coeficientes de comisión cuando hay desbalance. | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-04 | Re-ejecución incremental desde `fecha_desde`: clases anteriores quedan intactas. | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` |
| RF-LP-09 | El LP asigna aulas al **patrón** (`HorarioDB.aula_id`), no directamente a clases. Esto separa "asignación del esquema semanal" (responsabilidad del LP) de "excepciones puntuales por fecha" (responsabilidad del usuario). | ✅ | `src/services/asignacion_aulas_service.py:apply_solution` |
| RF-LP-10 | Edición del patrón post-LP vía `cambiar_aula_horario`: cambia `HorarioDB.aula_id`. La propagación al cache `ClaseDB` se mantiene por si en el futuro se re-habilita alguna vista por fecha, pero el usuario no la ve. | ✅ | `src/services/asignacion_aulas_service.py:cambiar_aula_horario` |
| RF-LP-05 | *(Legacy)* Toggle "respetar ediciones manuales" del LP: preserva `ClaseDB.aula_asignada_manualmente=True`. Se conserva como capacidad del solver por si vuelven las clases puntuales; hoy no hay UI que setee el flag. | 🚫 Sin UI | `2. Desarrollo/ASIGNACION_IMPL.md` |
| RF-LP-06 | Persistencia de `LPRunDB` con snapshot completo (config, status, métricas, detalles). | ✅ | `src/database/models.py` |
| RF-LP-07 | Resolución con CBC y timeout configurable. | ✅ | `LPConfig.timeout_seconds` |
| RF-LP-08 | Filtrado de horarios virtuales (catálogo y dictado) en el armado de inputs. | ✅ | `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-11 | **R10 — Restricción de sede por carrera/materia**. Las materias exclusivas de una carrera sólo se asignan a aulas de las sedes habilitadas para esa carrera (M:N vía `CarreraSedeDB`). Las materias comunes (pertenecen a ≥2 carreras) sólo se asignan a la sede marcada como `SedeDB.es_default_comunes`. La compatibilidad de laboratorio (`MateriaLaboratorioDB`) prevalece sobre la restricción de sede. Si una carrera no tiene sedes configuradas o no hay sede default de comunes, el LP asume "todas las sedes" como fallback. | ✅ | `src/services/carrera_sede_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-12 | **Auto-completar tipo de horario por horas declaradas**. Cuando una materia tiene `hlab=0` y `hteo>0` (o viceversa), el tipo de cada horario queda determinado de antemano. La acción `aplicar_auto_completar_tipos` persiste ese tipo en `HorarioDB.tipo_clase` para el plan. Adicionalmente, `build_inputs` aplica el override en memoria como red de seguridad: si el operador no corrió la acción, el LP arranca igual con menos variables `t[h]` redundantes. | ✅ | `src/services/plan_actions_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-13 | **Heatmap demanda vs oferta**. Mapa día × franja con la peor saturación por celda (cantidad de horarios simultáneos sobre cantidad de aulas admisibles tras R3 + R10), categorizado por tipo (teórica / laboratorio-por-materia / sin determinar). Identifica el cuello de botella concreto cuando el LP es infactible. | ✅ | `src/services/asignacion_aulas_helpers.py:compute_heatmap_demanda_oferta`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-14 | **Reporte de impacto de R10**. Tabla por materia con cuántas aulas admisibles tenía sólo por R3 (tipo + lab) y cuántas le quedan tras R10 (sede). Permite responder "¿la infactibilidad la causa la configuración de sedes o el inventario?". | ✅ | `src/services/asignacion_aulas_helpers.py:compute_impacto_r10`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-15 | **Override de sede por comisión** (`ComisionDB.carrera_asignada`). Permite modelar "comisiones orientadas a una carrera": la comisión pertenece a una materia común, pero se organiza pensada para alumnos de una carrera específica de otra sede (ej. una comisión de Física III para alumnos de Electrónica, que se dicta en Siberia en vez de la sede default de comunes, Pellegrini). El campo `ComisionDB.carrera_asignada: Optional[str]` (FK a `carreras.codigo`) sobrescribe la resolución habitual de sede para **todos los horarios de la comisión**: si tiene valor, las sedes admisibles del LP se resuelven vía `sedes_admisibles_para_carrera` con esa carrera; si es `None` (default), se usa la regla habitual por materia (RF-LP-11). El override vive a nivel comisión (no a nivel horario individual) porque semánticamente "la comisión está organizada para una carrera puntual" — todos sus horarios heredan la restricción de sede. Se edita desde la tabla de comisiones (siempre visible dentro del editor de una materia en cronogramas o planes) o al crear una comisión nueva vía dialog en cronogramas. Al generar el plan desde un cronograma, la comisión se **clona** (RF-COMISION-01) preservando el override. La compatibilidad de laboratorio (`MateriaLaboratorioDB`) sigue prevaleciendo sobre esta restricción, igual que en R10 estándar. `get_aulas_disponibles_para_horario` también respeta el override. Los cambios de `carrera_asignada` en el plan emiten evento en `ChangeLogDB` con `origin=ui:planes`. | ✅ | `src/services/carrera_sede_service.py:sedes_admisibles_para_carrera`, `src/services/asignacion_aulas_service.py:build_inputs`, `src/services/comision_service.py`, `src/ui/plan_grilla_editor.py`, `app/pages/6_📅_Cronogramas.py` |

### RF-COMISION — Gestión de comisiones como entidad

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-COMISION-01 | **Las comisiones son entidades reales** (`ComisionDB`) que pueden pertenecer a un cronograma (`schedule_id` seteado) o a un plan de cursada (`plan_cursada_id` seteado), pero no a ambos a la vez (XOR validado a nivel service). Reemplaza al viejo campo `ScheduleEntryDB.comision: int` que era identificador de facto sin entidad. `ScheduleEntryDB.comision_id` y `HorarioDB.comision_id` son ambos FK a `ComisionDB`. Los atributos de la comisión (nombre, cupo, coef_asignacion, carrera_asignada, descripción) son editables desde una tabla dedicada — antes del refactor solo existían al momento de generar el plan y no podían editarse en la etapa de cronograma. | ✅ | `src/database/models.py:ComisionDB`, `src/services/comision_service.py`, `2. Desarrollo/COMISIONES_POR_CARRERA.md` |
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
| RF-DIAG-01 | Cotas estructurales de infactibilidad (pigeonhole, partición, horarios sin aula compatible, etc.). | ✅ | `src/services/asignacion_aulas_helpers.py` |
| RF-DIAG-02 | Diagnóstico cruzado por relajación (IIS) cuando las cotas no detectan la causa: relaja R4/R5/R6 individualmente y reporta culpables. | ✅ | `src/services/asignacion_aulas_service.py:_run_iis_relajacion` |
| RF-DIAG-03 | Filtrado de falsos positivos en IIS y selección de causa principal. | ✅ | `1. Diseño/asignacion-aulas-LP.md` § 4ter.5 |
| RF-DIAG-04 | Validación de cobertura por carrera/año/cuatri con clasificación de discrepancias (faltantes, no esperadas, conflictos). | ✅ | `2. Desarrollo/VALIDACIONES.md` |

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
