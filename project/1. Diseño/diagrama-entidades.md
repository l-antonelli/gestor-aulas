# Diagrama de Entidades y Politicas de Borrado

**Ultima actualizacion**: 2026-03-10

Este documento refleja el estado actual de las entidades implementadas en `src/database/models.py`,
sus relaciones y las politicas de borrado aplicadas en la capa de servicios.

---

## Diagrama de Clases UML

```mermaid
classDiagram
    direction TB

    %% ========================================================================
    %% Entidades independientes (dominio del problema)
    %% ========================================================================

    class CarreraDB {
        +str codigo PK
        +str nombre
        +str titulo_otorgado
        +int duracion_anios
        +int cantidad_materias
    }

    class MateriaDB {
        +str codigo PK
        +str nombre
        +str codigo_guarani
        +int cupo
        +int horas_semanales
        +str periodo
        +bool active
    }

    class AulaDB {
        +str id PK
        +str sede
        +str nombre
        +int capacidad
        +str tipo
        +str descripcion
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
    }

    class PlanEstudioDB {
        +str id PK
        +str plan_version_id FK
        +str materia_codigo FK
        +str carrera_codigo FK
        +int anio_plan
        +str cuatrimestre_plan
        +str correlativas
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
        +bool activo
    }

    class DictadoCicloDB {
        +str dictado_id PK FK
        +str ciclo_id PK FK
    }

    %% ========================================================================
    %% Cronogramas (datos crudos de horarios)
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
    }

    %% ========================================================================
    %% Plan de Cursada (generado desde un cronograma)
    %% ========================================================================

    class PlanificacionCursadaDB {
        +str id PK
        +str nombre
        +str descripcion
        +str ciclo_id FK
        +bool activo
        +str schedule_id FK
    }

    class ComisionDB {
        +str id PK
        +str materia_codigo FK
        +str dictado_id FK
        +str plan_cursada_id FK
        +str comision_key
        +str nombre
        +int numero
        +int cupo
        +str descripcion
    }

    class HorarioDB {
        +str id PK
        +str comision_id FK
        +str codigo_materia FK
        +str dia
        +time hora_inicio
        +time hora_fin
    }

    class ClaseDB {
        +str id PK
        +str horario_id FK
        +str comision_id FK
        +str plan_cursada_id FK
        +str dictado_id FK
        +date fecha
        +time hora_inicio
        +time hora_fin
        +bool executed
        +str aula_id FK
    }

    %% ========================================================================
    %% Configuracion
    %% ========================================================================

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

    %% Plan de estudio
    CarreraDB "1" --o "0..*" PlanCarreraVersionDB : restrict
    PlanCarreraVersionDB "1" --o "0..*" PlanEstudioDB : cascade
    MateriaDB "1" --o "0..*" PlanEstudioDB : restrict

    %% Ciclo ↔ Plan version (M:N bridge)
    CicloDB "1" --o "0..*" CicloPlanVersionDB
    PlanCarreraVersionDB "1" --o "0..*" CicloPlanVersionDB

    %% Dictados
    MateriaDB "1" --o "0..*" DictadoDB
    CicloDB "0..*" --o "0..*" DictadoDB
    note for DictadoCicloDB "Bridge M:N\n(anuales vinculan 2 ciclos)"

    %% Cronogramas
    CicloDB "1" --o "0..*" ScheduleDB : cascade
    ScheduleDB "1" *-- "0..*" ScheduleEntryDB : cascade

    %% Plan de cursada (composition)
    CicloDB "1" --o "0..*" PlanificacionCursadaDB
    ScheduleDB "1" --o "0..*" PlanificacionCursadaDB : referencia
    PlanificacionCursadaDB "1" *-- "0..*" ComisionDB : cascade
    ComisionDB "1" *-- "0..*" HorarioDB : cascade
    PlanificacionCursadaDB "1" *-- "0..*" ClaseDB : cascade

    %% Referencias de Comision y Clase
    MateriaDB "1" --o "0..*" ComisionDB
    ComisionDB "1" --o "0..*" ClaseDB
    HorarioDB "1" --o "0..*" ClaseDB
    AulaDB "1" --o "0..*" ClaseDB : asignacion futura
```

---

## Politicas de Borrado

### Notacion

| Simbolo | Relacion | Significado |
|---------|----------|-------------|
| `*--` | Composicion | El hijo no existe sin el padre. Borrado en cascada. |
| `--o` | Agregacion / Referencia | El hijo puede existir independientemente. |
| `restrict` | | No se puede borrar el padre si tiene hijos. |
| `cascade` | | Borrar el padre borra todos los hijos. |
| `referencia` | | FK opcional, no se borra en cascada. |

### Detalle por entidad

#### Entidades independientes (raiz)
| Entidad | Se puede borrar si... |
|---------|----------------------|
| `CarreraDB` | No tiene `PlanCarreraVersionDB` (restrict) |
| `MateriaDB` | Cascadea comisiones + horarios via relationship_definitions |
| `AulaDB` | Libre (solo referenciada opcionalmente por ClaseDB.aula_id) |
| `CicloDB` | Libre actualmente (deberia restringirse si tiene planes/schedules) |

#### Arbol de Plan de Estudio
```
CarreraDB ──restrict──> PlanCarreraVersionDB ──cascade──> PlanEstudioDB
```
- No se puede borrar una carrera que tiene versiones de plan.
- Borrar una version borra sus entradas de plan de estudio.

#### Arbol de Cronograma
```
ScheduleDB ──cascade──> ScheduleEntryDB
```
- Borrar un cronograma borra todas sus entradas.
- Implementado inline en la UI (Planes > tab Cronogramas).

#### Arbol de Plan de Cursada (composition)
```
PlanificacionCursadaDB ──cascade──> ClaseDB
                       ──cascade──> ComisionDB ──cascade──> HorarioDB
```
- Borrar un plan borra: clases, horarios (via comision), comisiones.
- Orden de borrado en la UI: ClaseDB → HorarioDB → ComisionDB → PlanificacionCursadaDB.
- Las comisiones y horarios son **componentes** del plan (composition, no existen fuera de uno).

#### Notas
- `PlanificacionCursadaDB.schedule_id` es una referencia (FK opcional). Borrar un schedule NO borra los planes generados desde el (los planes ya tienen sus propias comisiones/horarios copiados).
- `ClaseDB.aula_id` es FK opcional para la futura asignacion de aulas.
- `DictadoCicloDB` es bridge M:N porque materias anuales vinculan un dictado a 2 ciclos.
