# Sesion: Versionado de Planes de Estudio por Carrera

**Fecha**: 2026-03-09
**Branch**: `refactor/jerarquia-entidades-ui`
**Commit**: `6566cba`

---

## Resumen

Se implemento el versionado de planes de estudio por carrera. Antes, `PlanEstudioDB` era una tabla puente plana `(materia_codigo, carrera_codigo)` sin versionado, y los dictados se creaban basandose en `MateriaDB.active == True`. Ahora los planes de estudio tienen versiones explicitas por carrera, se asignan a ciclos, y determinan que dictados se crean.

## Motivacion

- Los planes de estudio cambian con el tiempo (nuevas materias, reorganizacion curricular)
- Diferentes ciclos pueden operar bajo diferentes versiones del plan
- `Materia.active` era un proxy inadecuado: no distinguia entre carreras ni versiones
- Se necesitaba trazabilidad: que plan se uso para que ciclo

## Tareas completadas

### T1: Nuevos modelos DB + modificar PlanEstudioDB
- Archivos: `src/database/models.py`, `src/database/crud.py`, `src/database/__init__.py`
- Nuevas entidades:
  - `PlanCarreraVersionDB`: version de un plan (id UUID, carrera_codigo FK, nombre, descripcion, fecha_creacion)
  - `CicloPlanVersionDB`: bridge ciclo <-> version de plan (ciclo_id PK+FK, plan_version_id PK+FK)
- Modificaciones a `PlanEstudioDB`:
  - Quitar composite PK `(materia_codigo, carrera_codigo)`
  - Agregar `id: str` UUID PK (auto-generado)
  - Agregar `plan_version_id: str` FK -> plan_carrera_version
  - `carrera_codigo` se mantiene denormalizado (index)
- Relaciones:
  - `CarreraDB.plan_versions` -> `PlanCarreraVersionDB`
  - `CicloDB.plan_versions` -> `PlanCarreraVersionDB` via `CicloPlanVersionDB`
- Nuevas instancias CRUD: `plan_carrera_version_crud`, `ciclo_plan_version_crud`

### T2: Actualizar load_initial_data.py
- Archivo: `scripts/load_initial_data.py`
- Al cargar carreras, crea un `PlanCarreraVersionDB` ("Plan Original") por cada carrera
- Al crear `PlanEstudioDB`, asigna `plan_version_id` de la version correspondiente
- Resultado: 30 carreras -> 30 versiones -> 584 planes de estudio

### T3: Actualizar crud_services.py + materia_carrera_editor.py
- Archivos: `src/services/crud_services.py`, `src/ui/materia_carrera_editor.py`
- **CarreraService** (metodos nuevos):
  - `get_plan_versions(session, carrera_codigo)`: listar versiones
  - `get_latest_plan_version(session, carrera_codigo)`: ultima version
  - `create_plan_version(session, carrera_codigo, nombre, copy_from_version_id=None)`: crear version, opcionalmente copiando materias
  - `update_plan_version(session, plan_version_id, nombre=None, descripcion=None)`: editar metadata
- **CarreraService** (metodos modificados):
  - `get_materias()`: acepta `plan_version_id` opcional (sin filtro = dedup across versions)
  - `add_materia()`: requiere `plan_version_id`
  - `remove_materia()`: requiere `plan_version_id`
  - `get_children_count()`: acepta `plan_version_id` opcional
  - `get_materias_by_year_and_semester()`: acepta `plan_version_id` opcional
- **MateriaService** (metodos modificados):
  - `get_carreras()`: retorna dedup across versions (sin cambio de firma)
  - `set_carreras()`: requiere `plan_version_id`
  - `add_carrera()`: requiere `plan_version_id`
  - `remove_carrera()`: requiere `plan_version_id`
- **MateriaCarreraEditor**:
  - `render_associations_editor()`: requiere `plan_version_id`
  - `_get_associations()`: filtra por version, retorna `plan_estudio_id` para edicion
  - `_save_changes()`: usa `session.get(PlanEstudioDB, id)` en vez de busqueda por composite key
  - `_render_add_association()`: recibe `plan_version_id`

### T4: Actualizar Carreras page UI
- Archivo: `app/pages/5_Carreras.py`
- Tab 3 "Planes de Estudio":
  - Selector de version (dropdown con versiones de la carrera)
  - Boton "Nueva Version" con formulario (nombre, descripcion, opcion de copiar)
  - Expander para editar nombre/descripcion de la version
  - Todas las operaciones (add/remove/view materias) pasan `plan_version_id`
  - Refactor: helper `_render_period_column()` elimina duplicacion de columnas

### T5: Actualizar dictado_service + Ciclos UI
- Archivos: `src/services/dictado_service.py`, `app/pages/6_Ciclos.py`
- **dictado_service.py**:
  - `create_dictados_for_ciclo()` ahora obtiene materias desde `CicloPlanVersionDB -> PlanEstudioDB` (distinct)
  - Retorna error si el ciclo no tiene versiones de plan asignadas
  - `Materia.active` ya no se consulta
- **6_Ciclos.py**:
  - Tab 1 (crear ciclo): multi-select de versiones de plan. Default: ultima version por carrera
  - Tab 2 (dictados): muestra versiones asignadas antes del boton "Crear Dictados"

### T6: Actualizar validations
- Archivo: `src/services/validations.py`
- `validar_factibilidad_horarios_carrera()`: acepta param opcional `plan_version_id`

### T7: Actualizar tests
- Archivos: `tests/test_dictado_service.py`, `tests/test_carrera_materia_relationship.py`
- Fixtures actualizados: crean `CarreraDB`, `PlanCarreraVersionDB`, `PlanEstudioDB`, `CicloPlanVersionDB`
- Tests nuevos:
  - `test_ciclo_without_plan_versions_errors`: ciclo sin versiones retorna error
  - `test_create_plan_version`: crear version vacia
  - `test_create_plan_version_with_copy`: crear version copiando materias
  - `test_materia_not_in_plan_skipped`: materias fuera del plan no obtienen dictado
- Todos los tests existentes adaptados a usar `plan_version_id`
- Total: 694 tests pasan

### T8: Tambien se corrigio
- `app/pages/1_Materias.py`: agregar selector de version para `MateriaCarreraEditor`

## Flujo de datos (antes vs despues)

### Antes
```
Crear Ciclo -> Crear Dictados -> SELECT * FROM materias WHERE active = True
```

### Despues
```
Crear Ciclo (con versiones de plan asignadas)
  -> Crear Dictados
    -> SELECT plan_version_ids FROM ciclo_plan_version WHERE ciclo_id = ?
    -> SELECT DISTINCT materias FROM plan_estudio WHERE plan_version_id IN (?)
```

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `src/database/models.py` | +PlanCarreraVersionDB, +CicloPlanVersionDB, mod PlanEstudioDB |
| `src/database/crud.py` | +plan_carrera_version_crud, +ciclo_plan_version_crud |
| `src/database/__init__.py` | Exports nuevos modelos |
| `src/services/crud_services.py` | CarreraService y MateriaService con plan_version_id |
| `src/services/dictado_service.py` | Materias desde plan versions en vez de active |
| `src/services/validations.py` | +plan_version_id opcional |
| `src/ui/materia_carrera_editor.py` | Version-aware editor |
| `scripts/load_initial_data.py` | Crea "Plan Original" por carrera |
| `app/pages/1_Materias.py` | Version selector para editor |
| `app/pages/5_Carreras.py` | Version selector, crear/editar versiones |
| `app/pages/6_Ciclos.py` | Multi-select versiones, mostrar asignadas |
| `tests/test_dictado_service.py` | Fixtures con versiones |
| `tests/test_carrera_materia_relationship.py` | Fixtures y tests con versiones |

## Follow-up: Fix M:M delete checks + proteccion de borrado en CarreraService

**Commit**: `804859b`

### Problema

La verificacion de `delete_behavior="restrict"` en `BaseCRUDService.delete_with_cascading()` no funcionaba para relaciones M:N. Para la relacion Carrera->Materia (M:M via `plan_estudio`), el codigo hacia:

```python
select(MateriaDB).where(MateriaDB.codigo == carrera_id)
```

Esto nunca encontraba resultados porque `MateriaDB.codigo` es la PK de la materia, no un FK a carrera. El restrict era un no-op.

Ademas, `CarreraService.delete()` no verificaba la existencia de `PlanCarreraVersionDB` records (que no estan en el relationship registry por ser DB-only).

### Solucion

**`cascading_operations.py`**:
- `_get_children()` ahora distingue 1:N vs M:N. Para M:N, consulta la link table (`PlanEstudioDB`) usando `parent_link_field` en vez de la child table.
- Nuevo helper `_get_db_model_for_link_table()` mapea nombres de link tables a DB model classes.

**`crud_services.py`**:
- `delete_with_cascading()` delega a `CascadingOperations._get_children()` en vez de inlinear la query. Usa `self.delete()` al final (en vez de `self.crud.delete()`) para que los overrides de subclases apliquen.
- `CarreraService.delete()` override: bloquea borrado si existen `PlanCarreraVersionDB` asociadas.

**Tests nuevos** (4):
- `test_delete_with_cascading_restricts_when_plan_entries_exist`
- `test_delete_with_cascading_succeeds_when_no_plan_entries`
- `test_delete_blocked_by_plan_versions`
- `test_delete_succeeds_after_removing_plan_versions`

Total: 698 tests pasan.

## Consideraciones de migracion

- Ciclos existentes (creados antes de este cambio) no tendran `CicloPlanVersionDB` records. `create_dictados_for_ciclo` retornara error. Deben recrearse o asignarseles versiones manualmente.
- `Materia.active` sigue existiendo como campo informativo pero no tiene efecto funcional.
- El script `load_initial_data.py` es idempotente: si ya existen versiones "Plan Original", las reutiliza.
