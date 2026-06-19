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
| RF-DICT-01 | Generación automática de dictados a partir de las materias de los planes asociados al ciclo. | ✅ | `src/services/dictado_service.py` |
| RF-DICT-02 | Cálculo automático del flag `activo` por materia según reglas de recursado por carrera y cuatrimestre. | ✅ | `src/services/dictado_service.py:_should_skip_for_recursado` |
| RF-DICT-03 | Override manual de `activo` con flag `activo_override_manual` que sobrevive al recálculo. | ✅ | `2. Desarrollo/WORKFLOW.md` |
| RF-DICT-04 | Modalidad virtual a nivel `DictadoDB` (puntual del ciclo, distinto al catálogo). | ✅ | `2. Desarrollo/WORKFLOW.md` |
| RF-DICT-05 | Bridge `DictadoCicloDB` para soportar dictados anuales que cubren dos ciclos. | ✅ | modelo |

### RF-PLAN — Plan de cursada (cronograma + comisiones)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-PLAN-01 | Generación de comisiones por dictado con coeficientes de asignación. | ✅ | `src/services/comision_service.py` |
| RF-PLAN-02 | Generación de horarios por comisión a partir del cronograma cargado. | ✅ | `src/services/plan_generation_service.py` |
| RF-PLAN-03 | Materialización de `HorarioDB` a `ClaseDB` por cada fecha del ciclo. | ✅ | `src/services/clase_generation_service.py` |
| RF-PLAN-04 | Validación de cobertura (faltantes, no esperadas, conflictos por carrera/año/cuatri). | ✅ | `src/ui/validation_ui.py`, `2. Desarrollo/VALIDACIONES.md` |
| RF-PLAN-05 | Detección de materias virtuales tanto a nivel catálogo como dictado. | ✅ | `src/ui/validation_ui.py` |
| RF-PLAN-06 | Estimación de inscriptos esperados por comisión a partir de series históricas y forecast configurable. | ✅ | `src/services/forecast_service.py` |
| RF-PLAN-07 | Las `ClaseDB` heredan `aula_id` y `tipo_clase` del patrón (`HorarioDB`) al generarse. Esto garantiza que el aula asignada por el LP al patrón se propague automáticamente a todas las instancias del ciclo. | ✅ | `src/services/clase_generation_service.py` |

### RF-LP — Asignación de aulas (programación lineal)

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-LP-01 | Modelo LP completo R1–R7 (cobertura, asignación única, tipo compatible, no doble booking, partición teoría/lab, capacidad blanda). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-02 | Restricción opcional R9 (penalización por sobre-utilización ponderada por λ). | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-03 | Toggle α: redistribución de coeficientes de comisión cuando hay desbalance. | ✅ | `1. Diseño/asignacion-aulas-LP.md` |
| RF-LP-04 | Re-ejecución incremental desde `fecha_desde`: clases anteriores quedan intactas. | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` |
| RF-LP-09 | El LP asigna aulas al **patrón** (`HorarioDB.aula_id`), no directamente a clases. Esto separa "asignación del esquema semanal" (responsabilidad del LP) de "excepciones puntuales por fecha" (responsabilidad del usuario). | ✅ | `src/services/asignacion_aulas_service.py:apply_solution` |
| RF-LP-10 | Edición del patrón post-LP vía `cambiar_aula_horario`: cambia `HorarioDB.aula_id` y propaga a las `ClaseDB` que heredan, respetando excepciones manuales. | ✅ | `src/services/asignacion_aulas_service.py:cambiar_aula_horario` |
| RF-LP-05 | Toggle "respetar ediciones manuales": preserva clases con `aula_asignada_manualmente=True`. | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` |
| RF-LP-06 | Persistencia de `LPRunDB` con snapshot completo (config, status, métricas, detalles). | ✅ | `src/database/models.py` |
| RF-LP-07 | Resolución con CBC y timeout configurable. | ✅ | `LPConfig.timeout_seconds` |
| RF-LP-08 | Filtrado de horarios virtuales (catálogo y dictado) en el armado de inputs. | ✅ | `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-11 | **R10 — Restricción de sede por carrera/materia**. Las materias exclusivas de una carrera sólo se asignan a aulas de las sedes habilitadas para esa carrera (M:N vía `CarreraSedeDB`). Las materias comunes (pertenecen a ≥2 carreras) sólo se asignan a la sede marcada como `SedeDB.es_default_comunes`. La compatibilidad de laboratorio (`MateriaLaboratorioDB`) prevalece sobre la restricción de sede. Si una carrera no tiene sedes configuradas o no hay sede default de comunes, el LP asume "todas las sedes" como fallback. | ✅ | `src/services/carrera_sede_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-12 | **Auto-completar tipo de horario por horas declaradas**. Cuando una materia tiene `hlab=0` y `hteo>0` (o viceversa), el tipo de cada horario queda determinado de antemano. La acción `aplicar_auto_completar_tipos` persiste ese tipo en `HorarioDB.tipo_clase` para el plan. Adicionalmente, `build_inputs` aplica el override en memoria como red de seguridad: si el operador no corrió la acción, el LP arranca igual con menos variables `t[h]` redundantes. | ✅ | `src/services/plan_actions_service.py`, `src/services/asignacion_aulas_service.py:build_inputs` |
| RF-LP-13 | **Heatmap demanda vs oferta**. Mapa día × franja con la peor saturación por celda (cantidad de horarios simultáneos sobre cantidad de aulas admisibles tras R3 + R10), categorizado por tipo (teórica / laboratorio-por-materia / sin determinar). Identifica el cuello de botella concreto cuando el LP es infactible. | ✅ | `src/services/asignacion_aulas_helpers.py:compute_heatmap_demanda_oferta`, `src/ui/asignacion_resultado_ui.py` |
| RF-LP-14 | **Reporte de impacto de R10**. Tabla por materia con cuántas aulas admisibles tenía sólo por R3 (tipo + lab) y cuántas le quedan tras R10 (sede). Permite responder "¿la infactibilidad la causa la configuración de sedes o el inventario?". | ✅ | `src/services/asignacion_aulas_helpers.py:compute_impacto_r10`, `src/ui/asignacion_resultado_ui.py` |

### RF-ADHOC — Gestión ad-hoc post-LP

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-ADHOC-01 | Edición manual de aula puntual (1 clase). | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` § 5.1 |
| RF-ADHOC-02 | Edición manual de aula por rango de fechas (mismo horario semanal). | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` § 5.1 |
| RF-ADHOC-03 | Edición manual "de hoy en adelante" (rango = `[hoy, fin_ciclo]`). | ✅ | `2. Desarrollo/ASIGNACION_IMPL.md` § 5.1 |
| RF-ADHOC-04 | Cambio puntual y bidireccional de `tipo_clase` (teorica ↔ laboratorio) con reasignación de aula compatible y liberación del aula original. | ✅ | `src/services/asignacion_aulas_service.py:cambiar_tipo_clase_puntual` |
| RF-ADHOC-05 | Marca `aula_asignada_manualmente=True` que sobrevive a re-runs del LP. | ✅ | `src/database/models.py:ClaseDB` |
| RF-ADHOC-06 | Filtros multi-dimensionales en panel Aulas del plan: aula, carrera, año, cuatri, tipo de clase, materia, día, sede, sólo manuales. | ✅ | `src/ui/aula_cronograma_view.py` |
| RF-ADHOC-07 | Vista de calendario semanal por aula + indicador de divergencias por horario. | ✅ | `src/ui/aula_cronograma_view.py` |
| RF-ADHOC-08 | Activación de materia y marca virtual en bloque desde el panel de validación. | ✅ | `src/ui/validation_ui.py` |
| RF-ADHOC-09 | Permitir reasignación sugerida del aula liberada al hacer cambio de tipo. | ⏳ | (futuro; hoy se libera y se avisa) |

### RF-DIAG — Diagnóstico y validación

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-DIAG-01 | Cotas estructurales de infactibilidad (pigeonhole, partición, horarios sin aula compatible, etc.). | ✅ | `src/services/asignacion_aulas_helpers.py` |
| RF-DIAG-02 | Diagnóstico cruzado por relajación (IIS) cuando las cotas no detectan la causa: relaja R4/R5/R6 individualmente y reporta culpables. | ✅ | `src/services/asignacion_aulas_service.py:_run_iis_relajacion` |
| RF-DIAG-03 | Filtrado de falsos positivos en IIS y selección de causa principal. | ✅ | `1. Diseño/asignacion-aulas-LP.md` § 4ter.5 |
| RF-DIAG-04 | Validación de cobertura por carrera/año/cuatri con clasificación de discrepancias (faltantes, no esperadas, conflictos). | ✅ | `2. Desarrollo/VALIDACIONES.md` |

### RF-UI — Interfaz de usuario

| ID | Descripción | Estado | Doc canónico |
|---|---|---|---|
| RF-UI-01 | Aplicación Streamlit con páginas separadas por dominio (Aulas, Materias, Carreras, Ciclos, Planes). | ✅ | `app/pages/` |
| RF-UI-02 | Indicadores visuales de estado (badges 🟢⚪✋ ←override, virtual, manual). | ✅ | UI |
| RF-UI-03 | Edición inline con toggles auto-save + `st.toast` de confirmación. | ✅ | `app/pages/4_📆_Ciclos.py` |
| RF-UI-04 | Calendario semanal renderizado con `render_timetable_calendar`. | ✅ | `src/ui/calendar_render.py` |
| RF-UI-05 | Diálogo modal de edición de aula/tipo con alcance configurable. | ✅ | `src/ui/aula_cronograma_view.py:_dialog_cambiar_aula` |

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
| `src/services/asignacion_aulas_service.py` | RF-LP-01..08, RF-ADHOC-01..05 | `tests/test_asignacion_aulas_service.py` |
| `src/services/asignacion_aulas_helpers.py` | RF-DIAG-01..03 | `tests/test_asignacion_aulas_helpers.py` |
| `src/services/dictado_service.py` | RF-DICT-01..05 | `tests/test_dictado_service.py` |
| `src/services/forecast_service.py` | RF-PLAN-06 | `tests/test_forecast_service.py` |
| `src/services/plan_generation_service.py` | RF-PLAN-02 | `tests/test_plan_generation_service.py` |
| `src/services/clase_generation_service.py` | RF-PLAN-03 | `tests/test_clase_generation_service.py` |
| `src/services/comision_service.py` | RF-PLAN-01 | `tests/test_comision_service.py` |
| `src/ui/validation_ui.py` | RF-PLAN-04..05, RF-ADHOC-08 | (UI, sin tests directos) |
| `src/ui/aula_cronograma_view.py` | RF-ADHOC-06..07, RF-UI-04..05 | (UI, helpers cubiertos en service tests) |
| `app/pages/4_📆_Ciclos.py` | RF-CICLO-01..02, RF-DICT-* | (UI) |
| `app/pages/2_🏛️_Aulas.py` | RF-CAT-04..05 | (UI) |

## Decisiones pendientes

- **2026-06-12 (reunión con directores)**: se planteó la posibilidad
  de **eliminar completamente el concepto de "clase puntual"** del
  sistema y trabajar exclusivamente sobre el patrón semanal
  (`HorarioDB`). El argumento es que las excepciones por fecha
  agregan complejidad sin uso operativo claro hasta el momento. La
  decisión queda **abierta**: hay que evaluar antes de codear si vale
  la pena el costo de borrar `ClaseDB.aula_id`,
  `aula_asignada_manualmente`, las funciones
  `aplicar_edicion_manual` / `cambiar_tipo_clase_puntual` /
  `clases_del_rango`, sus tests y la UI asociada (que aún no se
  implementó), o si conviene dejarlas como capacidad latente. Hay
  tres opciones evaluadas en una sesión previa: A (mantener todo,
  sólo deprecar en docs), B (limpieza fuerte: borrar todo lo puntual
  + el campo `ClaseDB.aula_id`), C (intermedio: borrar funciones y
  UI puntuales pero mantener `ClaseDB.aula_id` como caché propagado
  desde el patrón). Pendiente de cierre.

## Pendientes y backlog

- **RF-ADHOC-09** (sugerir reasignación del aula liberada): hoy al
  cambiar el tipo de una clase puntual el aula original queda con
  hueco. La UI podría sugerir qué otras clases del plan podrían
  ocupar ese hueco.
- **RF-LP-09** (constraint de mismo edificio para clases consecutivas
  de la misma carrera/año): mencionado en discusiones pero no
  formalizado.
- **RF-UI-06** (exportar a CSV/Excel los listados filtrados del
  panel Aulas): conveniencia para auditoría externa.
- **RF-UI-07** (métricas de ocupación a nivel aula y a nivel ciclo):
  porcentaje de franjas usadas, total de horas semanales, ranking
  de aulas más cargadas. Diferido a iteración futura.
