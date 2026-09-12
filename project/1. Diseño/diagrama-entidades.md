# Diagrama de Entidades y Políticas de Borrado

**Última actualización**: 2026-09-11.

Este documento refleja el estado actual de las entidades
implementadas en `src/database/models.py`, sus relaciones y las
políticas de borrado aplicadas en la capa de servicios. Para la
descripción detallada de cada tabla (columnas, invariantes,
operaciones) ver `Informe/anexos/Anexo_Base_de_Datos.md`.

---

## 1. Diagrama de clases UML

```mermaid
classDiagram
    direction TB

    %% ========================================================================
    %% Catálogo (dominio del problema)
    %% ========================================================================

    class CarreraDB {
        +str codigo PK
        +str nombre
        +str titulo_otorgado
        +int duracion_anios
        +int cantidad_materias
        +Optional~bool~ dicta_recursado
    }

    class MateriaDB {
        +str codigo PK
        +str nombre
        +str codigo_guarani
        +int cupo
        +float horas_teoria
        +float horas_laboratorio
        +str periodo
        +bool active
        +bool virtual
        +Optional~bool~ dicta_recursado
        +str grupo_id FK
    }

    class SedeDB {
        +str id PK
        +str nombre
        +bool es_default_comunes «deprecated»
    }

    class AulaDB {
        +str id PK
        +str sede_id FK
        +str codigo_aula
        +str nombre
        +int capacidad
        +str tipo
        +str descripcion
    }

    class MateriaLaboratorioDB {
        +str materia_codigo PK FK
        +str aula_id PK FK
    }

    %% ========================================================================
    %% Grupos de Materias (R10/R12)
    %% ========================================================================

    class GrupoMateriaDB {
        +str id PK
        +str nombre
        +str descripcion
        +bool es_sin_clasificar
        +bool chequear_pertenencia_asociadas
        +bool chequear_exclusividad_no_asociadas
        +bool chequear_completitud
    }

    class GrupoMateriaSedeDB {
        +str grupo_id PK FK
        +str sede_id PK FK
        +str tipo PK  «DURO|BLANDO»
        +int orden
    }

    class GrupoMateriaCarreraDB {
        +str grupo_id PK FK
        +str carrera_codigo PK FK
    }

    class CarreraSedeDB {
        <<deprecated>>
        +str carrera_codigo PK FK
        +str sede_id PK FK
    }

    %% ========================================================================
    %% Plan de Estudio (versionado)
    %% ========================================================================

    class PlanCarreraVersionDB {
        +str id PK
        +str carrera_codigo FK
        +str nombre
        +str descripcion
        +date fecha_creacion
        +bool activo
    }

    class PlanEstudioDB {
        +str id PK
        +str plan_version_id FK
        +str materia_codigo FK
        +str carrera_codigo FK
        +int anio_plan
        +str cuatrimestre_plan
    }

    class CorrelativaDB {
        +str carrera_codigo PK FK
        +str materia_codigo PK FK
        +str materia_correlativa_codigo PK FK
    }

    %% ========================================================================
    %% Ciclo y Dictados
    %% ========================================================================

    class CicloDB {
        +str id PK
        +int anio
        +int numero
        +date fecha_inicio
        +date fecha_fin
        +str descripcion
    }

    class CicloPlanVersionDB {
        +str ciclo_id PK FK
        +str plan_version_id PK FK
    }

    class DictadoDB {
        +str id PK
        +str materia_codigo FK
        +str dictado_codigo
        +date inicio_dictado
        +date fin_dictado
        +Optional~bool~ virtual
    }

    class DictadoCicloDB {
        +str dictado_id PK FK
        +str ciclo_id PK FK
    }

    %% ========================================================================
    %% Cronogramas (fuente crudo de horarios)
    %% ========================================================================

    class ScheduleDB {
        +str id PK
        +str ciclo_id FK
        +str nombre
        +date fecha_upload
        +str source_filename
    }

    class ScheduleEntryDB {
        +str id PK
        +str schedule_id FK
        +str codigo_materia FK
        +str dia
        +time hora_inicio
        +time hora_fin
        +Optional~str~ comision_id FK
        +Optional~str~ tipo_clase
        +Optional~bool~ virtual
    }

    class ScheduleValidationDB {
        +str id PK
        +str schedule_id FK
        +str ciclo_id FK
        +datetime validated_at
        +str details_json
    }

    %% ========================================================================
    %% Plan de Cursada (generado desde un cronograma)
    %% ========================================================================

    class PlanificacionCursadaDB {
        +str id PK
        +str nombre
        +str descripcion
        +str ciclo_id FK
        +Optional~str~ schedule_id FK
        +str forecast_metodo_default
    }

    class ComisionDB {
        +str id PK
        +str materia_codigo FK
        +Optional~str~ dictado_id FK
        +Optional~str~ plan_cursada_id FK
        +Optional~str~ schedule_id FK
        +str comision_key
        +str nombre
        +int numero
        +int cupo
        +Optional~str~ carrera_asignada FK «etiqueta visual»
        +float coef_asignacion
    }

    class HorarioDB {
        +str id PK
        +str comision_id FK
        +str codigo_materia FK
        +str dia
        +time hora_inicio
        +time hora_fin
        +Optional~str~ tipo_clase
        +Optional~str~ aula_id FK
        +bool aula_asignada_manualmente
        +Optional~bool~ virtual
    }

    class ClaseDB {
        <<deprecated cache>>
        +str id PK
        +str horario_id FK
        +str comision_id FK
        +str plan_cursada_id FK
        +Optional~str~ dictado_id FK
        +date fecha
        +time hora_inicio
        +time hora_fin
        +bool executed
        +Optional~str~ aula_id FK
    }

    %% ========================================================================
    %% Excepciones, auditorías y snapshots
    %% ========================================================================

    class IgnoredConflictDB {
        +str plan_cursada_id PK FK
        +str materia_a PK
        +str materia_b PK
        +str razon
        +datetime fecha_creacion
    }

    class PlanValidationDB {
        +str id PK
        +str plan_cursada_id FK
        +datetime validated_at
        +str details_json
    }

    class LPRunDB {
        +str id PK
        +str plan_cursada_id FK
        +datetime run_at
        +date fecha_desde
        +float lambda_over
        +float lambda_under
        +str status
        +Optional~float~ objective_value
        +int n_horarios_asignados
        +Optional~float~ solver_seconds
        +str details_json
    }

    class ChangeLogDB {
        +str id PK
        +datetime created_at
        +str entity_type
        +str entity_id
        +str action
        +str origin
        +str details_json
    }

    class InscripcionHistoricaDB {
        +str id PK
        +str materia_codigo FK
        +int anio
        +int cuatrimestre
        +int inscriptos
    }

    class MateriaForecastConfigDB {
        +str plan_cursada_id PK FK
        +str materia_codigo PK FK
        +str cuatrimestre PK
        +Optional~str~ metodo
        +Optional~float~ valor_override
    }

    class ConfiguracionHoraria {
        +int id PK
        +int granularidad_minutos
        +time hora_inicio_operativo
        +time hora_fin_operativo
        +str dias_operativos
    }

    %% ========================================================================
    %% Relaciones
    %% ========================================================================

    %% Grupos de Materias
    GrupoMateriaDB "1" *-- "0..*" GrupoMateriaSedeDB : cascade
    GrupoMateriaDB "1" *-- "0..*" GrupoMateriaCarreraDB : cascade
    SedeDB "1" --o "0..*" GrupoMateriaSedeDB : restrict
    CarreraDB "1" --o "0..*" GrupoMateriaCarreraDB : restrict
    MateriaDB "0..*" --> "1" GrupoMateriaDB : partición estricta

    %% Sedes y Aulas
    SedeDB "1" --o "0..*" AulaDB : restrict
    MateriaDB "0..*" --o "0..*" AulaDB : via MateriaLaboratorioDB

    %% Legacy deprecado
    CarreraDB "0..*" --o "0..*" CarreraSedeDB : « deprecated »
    SedeDB "0..*" --o "0..*" CarreraSedeDB : « deprecated »

    %% Plan de estudio
    CarreraDB "1" --o "0..*" PlanCarreraVersionDB : restrict
    PlanCarreraVersionDB "1" --o "0..*" PlanEstudioDB : cascade
    MateriaDB "1" --o "0..*" PlanEstudioDB : restrict
    CarreraDB "1" *-- "0..*" CorrelativaDB : cascade

    %% Ciclo ↔ Plan version (M:N bridge)
    CicloDB "1" --o "0..*" CicloPlanVersionDB
    PlanCarreraVersionDB "1" --o "0..*" CicloPlanVersionDB

    %% Dictados
    MateriaDB "1" --o "0..*" DictadoDB
    CicloDB "0..*" --o "0..*" DictadoDB
    DictadoDB "1" --o "0..*" DictadoCicloDB : bridge M:N

    %% Cronogramas
    CicloDB "1" --o "0..*" ScheduleDB : cascade
    ScheduleDB "1" *-- "0..*" ScheduleEntryDB : cascade
    ScheduleDB "1" --o "0..*" ScheduleValidationDB : snapshot

    %% Plan de cursada
    CicloDB "1" --o "0..*" PlanificacionCursadaDB
    ScheduleDB "1" --o "0..*" PlanificacionCursadaDB : referencia
    PlanificacionCursadaDB "1" *-- "0..*" ComisionDB : cascade
    ComisionDB "1" *-- "0..*" HorarioDB : cascade
    PlanificacionCursadaDB "1" *-- "0..*" ClaseDB : cascade

    %% Referencias de Comision, Horario, Clase
    MateriaDB "1" --o "0..*" ComisionDB
    DictadoDB "1" --o "0..*" ComisionDB
    CarreraDB "0..1" --o "0..*" ComisionDB : carrera_asignada
    ComisionDB "1" --o "0..*" ClaseDB
    HorarioDB "1" --o "0..*" ClaseDB
    AulaDB "1" --o "0..*" HorarioDB : aula del patrón
    AulaDB "1" --o "0..*" ClaseDB : cache técnico

    %% Excepciones y snapshots
    PlanificacionCursadaDB "1" *-- "0..*" IgnoredConflictDB : cascade
    PlanificacionCursadaDB "1" --o "0..*" PlanValidationDB : snapshot
    PlanificacionCursadaDB "1" --o "0..*" LPRunDB : snapshot

    %% Forecast e histórico
    MateriaDB "1" --o "0..*" InscripcionHistoricaDB
    PlanificacionCursadaDB "1" --o "0..*" MateriaForecastConfigDB : cascade
    MateriaDB "1" --o "0..*" MateriaForecastConfigDB
```

---

## 2. Convenciones de notación

| Símbolo | Relación | Significado |
|---------|----------|-------------|
| `*--` | Composición | El hijo no existe sin el padre. Borrado en cascada. |
| `--o` | Agregación / referencia | El hijo puede existir independientemente. |
| `restrict` | | No se puede borrar el padre si tiene hijos. |
| `cascade` | | Borrar el padre borra todos los hijos. |
| `referencia` | | FK opcional, no se borra en cascada. |
| `« deprecated »` | | Entidad o relación conservada por compatibilidad, no la lee ni el LP ni la UI. |

---

## 3. Políticas de borrado

### 3.1 Entidades raíz

| Entidad | Se puede borrar si... |
|---------|----------------------|
| `CarreraDB` | No tiene `PlanCarreraVersionDB` (restrict). |
| `MateriaDB` | Cascadea comisiones + horarios vía `relationship_definitions`. Verifica primero que no rompa la partición estricta de grupos. |
| `SedeDB` | No tiene `AulaDB` ni referencias en `GrupoMateriaSedeDB` (restrict). |
| `AulaDB` | Libre (referenciada opcionalmente por `HorarioDB.aula_id`, `ClaseDB.aula_id` y `MateriaLaboratorioDB`). El servicio pone en `None` las referencias débiles al borrar. |
| `CicloDB` | Restrict actualmente si tiene planes o cronogramas. |

### 3.2 Grupos de Materias

```
GrupoMateriaDB ──cascade──> GrupoMateriaSedeDB
GrupoMateriaDB ──cascade──> GrupoMateriaCarreraDB
```

- **`grupo_materia_service.delete_grupo`** rechaza el borrado si el
  grupo tiene materias asignadas (invariante de partición estricta:
  no puede quedar `MateriaDB.grupo_id` colgado).
- Cada `MateriaDB` referencia **exactamente un** `GrupoMateriaDB`
  (partición estricta, `grupo_id NOT NULL` enforzado en la
  migración). Reasignar una materia entre grupos se hace vía
  `asignar_materia_a_grupo`.
- Sólo puede existir **un** grupo con `es_sin_clasificar=True` a la
  vez (invariante en service layer).
- `GrupoMateriaSedeDB` tiene PK compuesta `(grupo_id, sede_id, tipo)`
  para permitir que una sede aparezca en ambos sets del mismo grupo
  (DURO y BLANDO son independientes).

### 3.3 Árbol de Plan de Estudio

```
CarreraDB ──restrict──> PlanCarreraVersionDB ──cascade──> PlanEstudioDB
CarreraDB ──cascade──> CorrelativaDB
```

- No se puede borrar una carrera con versiones de plan.
- Borrar una versión borra sus entradas de plan de estudio.

### 3.4 Árbol de Cronograma

```
ScheduleDB ──cascade──> ScheduleEntryDB
ScheduleDB ──snapshot──> ScheduleValidationDB (histórico)
```

- Borrar un cronograma borra todas sus entradas.
- Las validaciones históricas del cronograma se conservan mientras
  exista el schedule; se limpian al borrarlo (cascade).

### 3.5 Árbol de Plan de Cursada

```
PlanificacionCursadaDB ──cascade──> ComisionDB ──cascade──> HorarioDB
PlanificacionCursadaDB ──cascade──> ClaseDB (cache técnico)
PlanificacionCursadaDB ──cascade──> IgnoredConflictDB
PlanificacionCursadaDB ──snapshot──> PlanValidationDB, LPRunDB
```

- Borrar un plan cascadea: comisiones (y sus horarios), clases
  cache, excepciones ignoradas.
- Los snapshots (`PlanValidationDB`, `LPRunDB`) NO se cascadean por
  default: se conservan para auditoría. Un `truncate_plan` explícito
  los limpia si se necesita.
- Orden interno de borrado: `ClaseDB → HorarioDB → ComisionDB →
  IgnoredConflictDB → PlanificacionCursadaDB`.

### 3.6 Excepciones ignoradas

`IgnoredConflictDB` se cascadea con el plan. Además, la validación
del plan corre `cleanup_stale_ignored_pairs` para limpiar
excepciones que quedaron huérfanas cuando cambia la coexistencia
curricular de las materias involucradas. El evento de limpieza se
reporta al usuario en el summary de `validate_plan`.

---

## 4. Legacy y deprecaciones activas

- **`CarreraSedeDB`**. Reemplazada por
  `GrupoMateriaDB + GrupoMateriaSedeDB`. La tabla y sus columnas
  siguen en el schema para no romper migraciones de bases viejas,
  pero ningún flujo la lee.
- **`SedeDB.es_default_comunes`**. Reemplazado por los grupos
  transversales (`FB`, `FI`, `CE`, `F`) que declaran sus propias
  sedes. Conservado como columna legacy.
- **`ClaseDB`**. Cache técnico deprecado (2026-08). El modelo activo
  trabaja sobre `HorarioDB.aula_id`. `ClaseDB.aula_id` se propaga
  desde el patrón por `apply_solution` pero ninguna vista lo
  renderiza. Plan de retiro en `2. Desarrollo/sesiones/DEPRECACION_CLASEDB.md`.
- **`ClaseDB.aula_asignada_manualmente`**. Deprecado. El flag vive
  ahora en `HorarioDB.aula_asignada_manualmente`.
- **`DictadoDB.activo`**. Eliminada (2026-06-30). Semántica actual:
  "existencia = activación" — si el dictado existe en el ciclo, se
  ofrece; para desactivar hay que borrar la fila.
- **`ComisionDB.carrera_asignada`**. Sobrevive como etiqueta visual
  sin efecto en el LP: la resolución de sedes va exclusivamente por
  el grupo de la materia.
