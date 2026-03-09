# Sesion: Implementacion del Modelo de Planificacion de Cursada

**Fecha**: 2026-03-09
**Branch**: `refactor/jerarquia-entidades-ui`

---

## Resumen

Se implemento el modelo completo de planificacion de cursada segun el diseño en `project/1. Diseño/modelo-planificacion-cursada.md`. El trabajo se dividio en 11 tareas ejecutadas secuencialmente.

## Tareas completadas

### T1: Campo `active` en Materia
- Archivos: `models.py`, `materia.py`, `converters.py`
- Se agrego `active: bool = True` a MateriaDB y Materia domain model
- Se actualizo conversiones to_db/to_domain

### T2: Nuevos modelos DB
- Archivos: `models.py`, `crud.py`, `__init__.py`
- Nuevas entidades: `DictadoCicloDB`, `ScheduleDB`, `ScheduleEntryDB`, `PlanificacionCursadaDB`, `ClaseDB`
- Se rediseno `DictadoDB`: quito ciclo_id FK directa, ahora via bridge DictadoCicloDB
- Se agrego `dictado_codigo`, `inicio_dictado`, `fin_dictado` a DictadoDB
- Se agrego `plan_cursada_id`, `comision_key` a ComisionDB (anticipado de T3)
- Nuevas instancias CRUD para todas las entidades

### T3: Modificar ComisionDB
- Archivos: `comision.py`, `converters.py`
- Se agrego `plan_cursada_id` y `comision_key` al domain model Comision
- Se actualizo converters para incluir nuevos campos

### T4: dictado_service (nuevo)
- Archivos: `src/services/dictado_service.py`, `tests/test_dictado_service.py`
- `create_dictados_for_ciclo()`: crea dictados para materias activas
  - Cuatrimestrales: nuevo dictado + link
  - Anuales 1C: nuevo dictado con fin_dictado=None
  - Anuales 2C: busca y vincula dictado existente de 1C
  - Idempotente: no duplica existentes
- `get_dictados_for_ciclo()`: consulta via bridge table
- 7 tests

### T5: schedule_service (nuevo)
- Archivos: `src/services/schedule_service.py`, `tests/test_schedule_service.py`
- `create_schedule_from_file()`: parsea archivo CSV/Excel, crea ScheduleDB + ScheduleEntryDB
  - Reutiliza `parse_horarios_file()` y `_resolve_materia_code()`
  - Resuelve codigos guarani, reporta errores de materias no encontradas
- `get_schedules_for_ciclo()`, `get_schedule_entries()`
- 5 tests

### T6: plan_generation_service (nuevo)
- Archivos: `src/services/plan_generation_service.py`, `tests/test_plan_generation_service.py`
- `generate_plan_from_schedule()`: genera PlanificacionCursadaDB desde Schedule
  - Agrupa entries por materia
  - Deriva comisiones con `derive_comision_count()`
  - Crea ComisionDB con plan_cursada_id y comision_key
  - Crea HorarioDB copiados de ScheduleEntryDB
- `activate_plan()`: activa un plan y desactiva otros del mismo ciclo
- 6 tests

### T7: clase_generation_service (nuevo)
- Archivos: `src/services/clase_generation_service.py`, `tests/test_clase_generation_service.py`
- `generate_clases_for_plan()`: genera ClaseDB desde horarios del plan
  - Expande fechas del ciclo que coincidan con el dia del horario
  - Crea ClaseDB por cada fecha (executed=False, aula_id=None)
- `_expand_dates()`: funcion auxiliar para expandir fechas por dia de semana
- 8 tests

### T8: Eliminar AsignacionAula
- Se elimino `AsignacionAulaDB` de models.py, crud.py, __init__.py
- Se elimino `src/domain/solution/asignacion_aula.py`
- Se limpio converters.py (quitar AsignacionAula de conversiones)
- Se limpio relationship_definitions.py (quitar relacion Horario->AsignacionAula)
- Se limpio cascading_operations.py (quitar de mapeos)
- Se refactoreo validations.py: `validar_conflictos_aula_ciclo` -> `validar_conflictos_aula_plan` (usa ClaseDB)
- Se limpio crud_form_renderer.py y relationship_selector.py
- Se elimino `assignment_validation.py` y su test
- Se limpiaron 7 archivos de test que referenciaban AsignacionAula

### T9: UI - Pagina de Ciclos
- Archivo: `app/pages/6_📆_Ciclos.py`
- Reescrita con 4 tabs:
  1. **Ciclos**: CRUD de ciclos lectivos
  2. **Dictados**: crear dictados para un ciclo seleccionado
  3. **Schedules**: cargar archivos de horarios, ver entries
  4. **Planes**: generar planes desde schedules, activar/desactivar

### T10: UI - Comisiones y Horarios
- `app/pages/3_👥_Comisiones.py`: reescrita para agrupar por plan_cursada_id y materia, con edicion de cupo
- `app/pages/4_📅_Horarios.py`: se agrego nota sobre flujo recomendado via Ciclos

### T11: Actualizar tests + load_initial_data
- Tests: 692 pasando (bajaron de 715 por tests eliminados de AsignacionAula)
- `scripts/load_initial_data.py`: funciona sin cambios (legacy flow compatible)

## Servicios creados

| Servicio | Reutiliza de | Funcionalidad principal |
|----------|-------------|------------------------|
| `dictado_service` | `materia_crud`, `ciclo_crud` | Crear/consultar dictados por ciclo |
| `schedule_service` | `horario_file_parser`, `horario_loading_service._resolve_materia_code` | Cargar schedules desde archivos |
| `plan_generation_service` | `horario_loading_service.derive_comision_count` | Generar planes con comisiones y horarios |
| `clase_generation_service` | `planificacion_crud`, `ciclo_crud` | Generar clases individuales con fecha |

## Tests nuevos

| Archivo | Tests |
|---------|-------|
| `test_dictado_service.py` | 7 |
| `test_schedule_service.py` | 5 |
| `test_plan_generation_service.py` | 6 |
| `test_clase_generation_service.py` | 8 |
| **Total nuevos** | **26** |

## Notas tecnicas

- `ComisionDB.dictado_id` se mantiene como campo opcional para backward compatibility con datos legacy cargados via `load_initial_data.py`
- El flujo legacy (pagina Horarios, load_initial_data.py) sigue funcionando, crea comisiones sin plan_cursada_id
- El flujo nuevo (Ciclos -> Schedule -> Plan) crea comisiones con plan_cursada_id y comision_key
- La tabla `asignaciones_aula` puede quedar en la DB existente pero no se usa mas en el codigo

## Sesion siguiente

Ver `PLAN_VERSIONING_IMPLEMENTATION.md`: se implemento versionado de planes de estudio por carrera, reemplazando `Materia.active` como mecanismo para determinar dictados.
