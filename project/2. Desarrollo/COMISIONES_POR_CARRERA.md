# Comisiones como entidad y override de sede por carrera

## Motivación

Las materias comunes (las que aparecen en ≥2 carreras) por default se
asignan a la sede marcada como `SedeDB.es_default_comunes` — en el
setup actual, **Pellegrini**. Esta regla resuelve la mayoría de los
casos, pero deja fuera un escenario real:

> Física III es una materia común entre Ingeniería en Informática,
> Electrónica, Eléctrica, Licenciatura en Física, etc. Se dictan
> muchas comisiones y en principio cualquier alumno se anota a la
> que quiera. Sin embargo, algunas comisiones se organizan pensadas
> para alumnos de una carrera puntual, para que puedan cursar
> cómodamente (misma sede que el resto de sus materias). Una
> comisión "para alumnos de Electrónica" debería dictarse en
> **Siberia**, no en Pellegrini — aunque la materia sea común.

## Modelo — comisiones como entidad

Antes del refactor, `ScheduleEntryDB.comision` era un `int` que
funcionaba de identificador de facto de "una comisión de esa materia
en ese cronograma", pero no existía como entidad. Eso obligaba a:

- Editar la carrera asignada horario por horario en vez de a nivel
  comisión (que es donde vive semánticamente).
- No poder editar nombre, cupo o descripción de una comisión antes
  de generar el plan.
- Crear comisiones "por número" sin metadatos, siempre las mismas.

**Después del refactor:**

- `ComisionDB` puede pertenecer a un cronograma (`schedule_id`
  seteado) **o** a un plan de cursada (`plan_cursada_id` seteado),
  pero no a ambos a la vez. El XOR se valida a nivel service.
- `ScheduleEntryDB.comision_id` es FK a `ComisionDB` (reemplaza al
  viejo campo `comision: int`).
- `HorarioDB.comision_id` sigue apuntando a `ComisionDB`, pero ahora
  las comisiones del plan **se clonan** de las comisiones del
  cronograma template al generar el plan.
- `ComisionDB.carrera_asignada: Optional[str]` (FK a
  `carreras.codigo`) es el override — vive a nivel comisión, no a
  nivel horario.

**Regla de resolución de sede (R10, actualizada):**

- Si `comision.carrera_asignada` está seteado → sede admisible se
  resuelve vía `sedes_admisibles_para_carrera(carrera_asignada)`.
- Sino, se cae al comportamiento habitual por materia (RF-LP-11).

La compatibilidad de laboratorio (`MateriaLaboratorioDB`) sigue
prevaleciendo sobre esta restricción.

## Cascada Cronograma → Plan

Al generar un plan desde un cronograma:

1. Para cada comisión template del cronograma
   (`ComisionDB.schedule_id != None`), se **clona** con
   `plan_cursada_id` seteado y `schedule_id=None` (nuevo ID).
2. Los atributos se preservan: `numero, nombre, cupo, descripcion,
   coef_asignacion, carrera_asignada`.
3. Los `HorarioDB` del plan apuntan a las **comisiones clon**.
4. El ciclo de vida del plan es independiente: editar la comisión
   del plan **no** afecta a la del cronograma template.

Ver `src/services/comision_service.py:clone_comisiones_for_plan` y
la lógica de `generate_plan_from_preview` en
`plan_generation_service.py`.

## UI

**Cronogramas** (`app/pages/6_📅_Cronogramas.py`):

- **Tabla de entries** por materia:
  - Columna "Comisión" pasa a ser un `SelectboxColumn` con las
    comisiones existentes (`{N° · nombre}`), opción "— sin comisión —"
    y opción "➕ Crear nueva comisión…" que abre un form inline
    (nombre, cupo, carrera asignada, descripción).
- **Tabla de comisiones** (nueva, siempre visible cuando se ve una
  materia):
  - Columnas: N° · Nombre · Cupo · Carrera asignada · Descripción.
  - Editable inline. `Carrera asignada` es `SelectboxColumn` con
    todas las carreras + "—".
  - Borrar bloqueado si tiene entries asociadas (guardián en
    `delete_comision`).
- **Diálogo "Editar entrada"** del calendario:
  - El `number_input` de "Comisión" fue reemplazado por un
    `selectbox` de comisiones existentes + "➕ Crear nueva…" (mismo
    form inline).

**Planes** (`src/ui/plan_grilla_editor.py`):

- **Grid de horarios**: la columna "Carrera asignada" fue removida.
- **Tabla de comisiones del plan** (nueva) debajo del grid:
  - Columnas: N° · Nombre · Cupo · Coef · Carrera asignada · Descripción.
  - Editable inline; cambios en `carrera_asignada` emiten evento en
    el change log (`entity_type=ComisionDB`, `origin=ui:planes`).

## Audit log

En la grilla del plan, un cambio explícito de `carrera_asignada` en
la tabla de comisiones emite un evento `ChangeLogDB` con:

- `entity_type = "ComisionDB"`
- `field = "carrera_asignada"`
- `old_value` / `new_value` con los códigos previos y nuevos.
- `origin = "ui:planes"`
- `reason = "Edición inline en grilla del plan {plan_id}"`

Nota: `ComisionDB` no está en `TRACKED_ENTITIES` del hook automático
(evitamos ruido al clonar comisiones masivamente en la generación
de planes). Los eventos se emiten explícitamente para los cambios
que impactan al LP.

## Migración de datos

`src/database/connection.py:_migrate_schedule_entries_a_comision_id`
corre una sola vez y hace:

1. Detecta que `schedule_entries.comision` (int) existe.
2. Por cada tupla `(schedule_id, codigo_materia, comision_num)`
   distinta con `comision > 0`, crea una `ComisionDB` con
   `schedule_id`, `numero=comision_num`, defaults del catálogo.
3. Setea `schedule_entries.comision_id` a la comisión matching.
4. Entries con `comision = 0` o `NULL` quedan con `comision_id=NULL`
   (huérfanos — el usuario los reasigna manualmente).
5. Recrea `schedule_entries` sin la columna `comision`.

Además, `_migrate_horario_entries_drop_carrera_asignada` migra los
valores de `carrera_asignada` que hubieran quedado en `horarios` o
`schedule_entries` de un intento previo del refactor, mudándolos a
`ComisionDB.carrera_asignada` de la comisión referenciada. Después
recrea las tablas sin esa columna.

Ambas migraciones son idempotentes.

## Puntos de código

| Responsabilidad | Ubicación |
|---|---|
| Modelo `ComisionDB` (schedule_id, carrera_asignada) | `src/database/models.py` |
| Modelo `ScheduleEntryDB.comision_id` (FK) | `src/database/models.py` |
| Migración one-shot | `src/database/connection.py:_migrate_schedule_entries_a_comision_id`, `_migrate_horario_entries_drop_carrera_asignada` |
| CRUD dedicado | `src/services/comision_service.py` |
| Clone template → plan | `src/services/comision_service.py:clone_comisiones_for_plan` |
| Resolución de sede por carrera | `src/services/carrera_sede_service.py:sedes_admisibles_para_carrera` |
| Aplicación en LP | `src/services/asignacion_aulas_service.py:build_inputs` (R10) |
| UI edición manual del patrón | `src/services/asignacion_aulas_service.py:get_aulas_disponibles_para_horario` |
| Cascada cronograma → plan | `src/services/plan_generation_service.py:generate_plan_from_preview` |
| CRUD schedule entry (usa comision_id) | `src/services/schedule_service.py:add_schedule_entry` / `update_schedule_entry` |
| UI cronogramas (tabla + selectbox + dialog) | `app/pages/6_📅_Cronogramas.py`, `src/ui/schedule_materia_editor.py` |
| UI plan (tabla de comisiones) | `src/ui/plan_grilla_editor.py` |
| Change log (emit_event ComisionDB) | `src/services/change_log_service.py` |

## Tests

- `tests/test_comision_service.py`: 15 tests que cubren creación
  (schedule/plan), get_or_create por número, update (regenera
  `comision_key`), delete bloqueado por entries/horarios, listado y
  clonado.
- `tests/test_carrera_sede_service.py::TestSedesAdmisiblesParaCarrera`:
  el helper `sedes_admisibles_para_carrera` bajo distintas
  configuraciones.
- `tests/test_asignacion_aulas_service.py::TestCarreraAsignadaOverride`:
  el LP respeta el override (leído desde la comisión), `None`
  mantiene el comportamiento previo, carrera sin sedes hace fallback
  "todas", y `get_aulas_disponibles_para_horario` respeta el override.

## Ejemplos de uso

**Caso 1 — Comisión de Física III para Electrónica en el cronograma:**

1. En cronogramas, seleccionar Física III → agregar entrada
   Miércoles 18:00-22:00.
2. En el selectbox "Comisión" del data editor (o del diálogo del
   calendario), elegir "➕ Crear nueva comisión…". Se abre el form
   inline.
3. Nombre = "Comisión 5 - Electrónica", cupo = 40, carrera asignada
   = "ELECTRONICA". Confirmar.
4. La `ComisionDB` queda persistida con `schedule_id` del cronograma
   y `carrera_asignada="ELECTRONICA"`.
5. Al generar el plan, la comisión se clona (nuevo id,
   `plan_cursada_id` seteado) preservando `carrera_asignada`.
6. El LP asignará aulas de Siberia para esa comisión.

**Caso 2 — Override tardío desde la grilla del plan:**

1. El plan ya está generado con la sede default.
2. El operador nota que la comisión 5 debería ser para Electrónica.
3. En la tabla de comisiones del plan, cambia "Carrera asignada" a
   "ELECTRONICA".
4. Se emite un evento en el change log (`entity_type=ComisionDB`,
   `origin=ui:planes`, `field=carrera_asignada`).
5. Al re-correr el LP, se asignan aulas de Siberia.

**Caso 3 — Editar cupo o nombre de una comisión:**

- Antes: no había forma. Los "objetos comisión" recién existían al
  generar el plan.
- Ahora: en la tabla de comisiones del cronograma editás
  directamente cualquier campo, y el cambio se propaga al plan al
  regenerar (o queda en el plan si ya está generado).
