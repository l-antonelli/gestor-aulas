# Deprecación de `ClaseDB`

**Fecha de deprecación formal**: 2026-08-28
**Estado**: DEPRECADO — cache técnico latente. NO agregar features nuevas encima.
**Retiro completo**: pendiente (tarea trackeada, sin fecha compromiso).

## Contexto

El diseño original modelaba dos capas:

1. **Patrón semanal** (`HorarioDB`): franja repetitiva de una comisión en
   una materia (día, hora inicio/fin, aula, tipo).
2. **Instancias puntuales** (`ClaseDB`): expansión concreta de un
   `HorarioDB` en cada fecha del ciclo. Se usaba para permitir
   ediciones puntuales por fecha (ej. "esta clase del 12/09 la damos
   en otra aula").

En 2026-07-07 se **eliminó del sistema la edición manual por fecha**
(`aplicar_edicion_manual`, `validar_edicion_manual`, el diálogo de
edición puntual y los helpers asociados). Desde entonces, todo el
flujo de asignación de aulas trabaja sólo sobre el patrón semanal
(`HorarioDB`) y el LP escribe únicamente ahí. `ClaseDB` quedó como
un cache técnico que ninguna vista de la UI renderiza y ninguna
lógica de dominio necesita leer.

En 2026-08-28 se completó la migración del flag
`aula_asignada_manualmente` de `ClaseDB` a `HorarioDB` (ver commit
`10651f3`), cerrando el último "vestigio activo" del modelo puntual.

## Por qué no se elimina todavía

Retirar `ClaseDB` completamente toca ~15 archivos (servicios,
validaciones, UI cascades, tests, migración SQL). Se posterga hasta
que exista una razón concreta (ej. simplificar un servicio nuevo,
resolver un bug de sincronización, aliviar carga de tests). Mientras
el cache no aparezca en la UI ni en features nuevas, la sobrecarga
de mantenerlo es baja.

## Qué NO hacer (regla de mantenimiento)

- NO leer `ClaseDB.aula_id`, `ClaseDB.tipo_clase` ni
  `ClaseDB.aula_asignada_manualmente` para renderizar en la UI.
- NO agregar validaciones nuevas que dependan de `ClaseDB`.
- NO propagar cambios de dominio nuevos a `ClaseDB` — trabajar sólo
  sobre `HorarioDB`.
- NO exponer el flag `ClaseDB.aula_asignada_manualmente` en ningún
  lado; el equivalente vivo es `HorarioDB.aula_asignada_manualmente`.

## Superficie viva que sigue tocando `ClaseDB`

Documentado como referencia para el retiro futuro:

### Servicios

- `src/services/clase_generation_service.py::generate_clases_for_plan`
  — crea `ClaseDB` al activar un plan.
- `src/services/asignacion_aulas_service.py::apply_solution`
  — propaga `HorarioDB.aula_id` y `tipo_clase` a `ClaseDB` como
  cache (bloque final del loop principal, líneas ~877–890 y bloque
  de "respetar manuales", líneas ~854–866).
- `src/services/asignacion_aulas_service.py::cambiar_aula_horario`
  — mismo pattern de propagación (líneas ~1619–1664).
- `src/services/validations.py::validar_conflictos_aula_plan`
  — lee `ClaseDB` con `aula_id != None` para detectar solapamientos
  por fecha.

### UI (borrado en cascada)

- `app/pages/2_🏛️_Aulas.py` línea ~371 — impide borrar un aula si
  tiene `ClaseDB` asociada.
- `app/pages/4_📆_Ciclos.py` línea ~40 — al borrar ciclo, elimina
  `ClaseDB` de todos sus planes.
- `app/pages/5_📊_Planes.py` línea ~768 — al borrar plan, elimina
  sus `ClaseDB`.

### Tests

- `tests/test_clase_generation_service.py` — suite completa.
- `tests/test_asignacion_aulas_service.py` — helper
  `_seed_plan_con_clases` y assertions de propagación.
- `tests/test_dictado_service.py` — seeds puntuales.
- `tests/test_clonan_ciclo_para_demo.py` — feature clon.

### Migración

- `src/database/connection.py` línea ~76 — `ALTER TABLE clases ADD
  COLUMN aula_asignada_manualmente` (columna que ya está muerta).

## Plan de retiro (para cuando se decida encararlo)

Cada fase en su propio commit, con la suite verde al final de cada
uno:

1. **Reemplazar `validar_conflictos_aula_plan`** por una versión que
   trabaje sobre `HorarioDB` expandido on-the-fly por ciclo.
2. **Sacar propagación a `ClaseDB`** en `apply_solution` y
   `cambiar_aula_horario`.
3. **Deprecar `generate_clases_for_plan`** — el "activar plan" deja
   de expandir instancias puntuales.
4. **Limpiar cascadas UI** — remover queries a `ClaseDB` en las
   páginas de borrado.
5. **Migración SQL**: `DROP TABLE clases`. Sacar el modelo y sus
   imports/exports (`models.py`, `__init__.py`, `crud.py`).
6. **Reponer tests** — borrar `test_clase_generation_service.py`,
   simplificar seeds de otros tests que hoy pasan por `ClaseDB`.

## Regla para el asistente

Si el usuario pide una feature o bugfix relacionado con "clases
concretas por fecha", primero confirmar si se puede resolver a
nivel `HorarioDB`. Si la única solución razonable requiere
`ClaseDB`, avisar que es tocar código deprecado y sugerir revisitar
el plan de retiro antes de invertir en la solución.
