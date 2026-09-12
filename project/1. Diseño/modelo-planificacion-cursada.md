# Modelo de planificación de cursada

> **Estado**: implementado y estable.
> **Última actualización**: 2026-09-12.
>
> Este documento describe el modelo de datos activo para la gestión
> de ciclos académicos, planificación de cursada y asignación de
> aulas. Está organizado como referencia por entidades: qué guarda
> cada tabla, qué invariantes preserva y cómo interactúa con las
> demás. Para el detalle exhaustivo columna por columna, ver
> [`../Informe/anexos/Anexo_Base_de_Datos.md`](../Informe/anexos/Anexo_Base_de_Datos.md).
> Para la vista UML con políticas de borrado, ver
> [`diagrama-entidades.md`](diagrama-entidades.md).
>
> Vínculos:
> - Planteo formal del programa lineal: [`asignacion-aulas-LP.md`](asignacion-aulas-LP.md)
> - Implementación y operatoria del asignador: [`../2. Desarrollo/asignador.md`](../2.%20Desarrollo/asignador.md)
> - Ciclos, dictados y virtualidad: [`../2. Desarrollo/CICLOS_Y_DICTADOS.md`](../2.%20Desarrollo/CICLOS_Y_DICTADOS.md)
> - Comisiones como entidad de primera clase: [`../2. Desarrollo/sesiones/COMISIONES_POR_CARRERA.md`](../2.%20Desarrollo/sesiones/COMISIONES_POR_CARRERA.md)

---

## 0. Historia y contexto

Este documento fue creciendo a medida que evolucionó el modelo.
Los grandes cambios estructurales, en orden cronológico:

1. **2026-03**. Diseño inicial: versionado de planes (`PlanCarreraVersion`),
   ciclos, dictados, cronogramas, comisiones y clases.
2. **2026-06**. `SedeDB` como entidad, `AulaDB.sede_id` reemplaza al
   string libre, `HorarioDB.aula_id` como objetivo del asignador
   (antes iba directo a `ClaseDB`).
3. **2026-07**. Virtualidad jerárquica en tres niveles
   (`Horario > Dictado > Materia`), recursado jerárquico en dos
   niveles (`Materia > Carrera`), `ComisionDB` como entidad de
   primera clase con anclaje XOR cronograma/plan, edición manual
   de aula del patrón por `HorarioDB.aula_asignada_manualmente`.
4. **2026-07-07**. Deprecación de clases puntuales. La UI ya no
   expone la edición manual de `ClaseDB` por fecha. La tabla
   `ClaseDB` queda como caché técnico unidireccional del patrón.
5. **2026-06-30**. Eliminación de `DictadoDB.activo` y
   `activo_override_manual`. Nueva semántica: **existencia =
   activación** (si la fila del dictado existe, se dicta este
   ciclo; para desactivar hay que borrar la fila).
6. **2026-08**. `ClaseDB.aula_asignada_manualmente` deprecado; el
   flag vive en `HorarioDB.aula_asignada_manualmente`.
7. **2026-09**. **Grupos de Materias** reemplazan a `CarreraSedeDB`
   como fuente de verdad para la resolución de sedes admisibles
   (R10) y preferidas (R12) del LP. Cada materia pertenece a
   exactamente un grupo (partición estricta), y cada grupo declara
   dos configuraciones simultáneas de sedes (set duro + lista
   blanda). `CarreraSedeDB` y `MateriaDB.es_default_comunes`
   quedan como columnas legacy.
8. **2026-09**. `ComisionDB.carrera_asignada` sobrevive como
   etiqueta visual sin efecto en el LP: la resolución de sedes va
   exclusivamente por el grupo de la materia.
9. **2026-09**. R13 extendida al eje alumno (pares intersede de
   materias distintas del mismo grupo curricular). Chequeo
   pre-solve **R13-camino** para asegurar que exista al menos una
   combinación de comisiones viable por grupo curricular. Toggle
   **R14** (`forzar_misma_sede_por_comision`). Veredicto
   estructurado por corrida persistido en `LPRunDB.details_json`.
10. **2026-09**. Excepciones de conflicto ignoradas
    (`IgnoredConflictDB`) con auto-limpieza cuando cambia la
    coexistencia curricular. Alcance de la excepción: sólo
    solapamiento horario, no intersede.

Para el detalle histórico completo hay documentos en
`../2. Desarrollo/sesiones/`. Este archivo se enfoca en el estado
actual del modelo.

---

## 1. Objetivos del modelo

El modelo de planificación de cursada permite:

1. **Registrar** las materias que se ofrecen en cada ciclo vía
   `Dictado`, aplicando la regla de recursado jerárquica.
2. **Cargar** cronogramas de horarios desde archivos Excel
   (`Schedule` + `ScheduleEntry`) con validación previa contra los
   dictados del ciclo.
3. **Prevalidar** un cronograma contra los dictados del ciclo:
   cobertura, faltantes, no-esperadas, partición teoría/lab,
   conflictos horarios.
4. **Generar** planes de cursada con comisiones y horarios
   (`PlanificacionCursada`) clonando desde un cronograma.
5. **Asignar aulas** al patrón semanal (`HorarioDB.aula_id`) vía
   programa lineal.
6. **Propagar** la asignación a las instancias puntuales
   (`ClaseDB`) como caché técnico.
7. **Comparar** diferentes planes (distintas configuraciones de
   comisiones, horarios, asignaciones de aula).
8. **Auditar** cada corrida del asignador y cada validación con
   snapshots persistidos (`LPRunDB`, `PlanValidationDB`,
   `ScheduleValidationDB`) y un log global de mutaciones
   (`ChangeLogDB`).

---

## 2. Catálogo de entidades

Las entidades se agrupan por zona funcional. La fuente de verdad
del esquema exacto es siempre `src/database/models.py`; este
documento resume propósito y decisiones.

### 2.1 Zona: catálogo maestro

#### `MateriaDB`

Catálogo estático de asignaturas. Persiste entre ciclos.

| Campo | Tipo | Notas |
|-------|------|-------|
| `codigo` | `str` PK | Código del plan de estudio (ej. `MAT101`). |
| `nombre` | `str` | Nombre de la asignatura. |
| `codigo_guarani` | `Optional[str]` | Alternativo, usado en SIU Guaraní. |
| `cupo` | `Optional[int]` | Cupo default heredable a comisiones. |
| `horas_semanales` | `Optional[float]` | Total de horas por semana. |
| `horas_teoria` | `Optional[float]` | Subset de teoría. |
| `horas_laboratorio` | `Optional[float]` | Subset de laboratorio. |
| `periodo` | `str` | `"anual"` o `"cuatrimestral"`. |
| `active` | `bool` | Informativo, no controla creación de dictados. |
| `virtual` | `bool` | Default heredado por `DictadoDB.virtual`. Ver §4.1. |
| `optativa` | `bool` | Si la materia es opcional en el plan. |
| `dicta_recursado` | `Optional[bool]` | Override sobre `CarreraDB.dicta_recursado`. `None` = usar el de la carrera. Ver §4.2. |
| `grupo_id` | `str` FK NOT NULL | Grupo de materias al que pertenece (partición estricta). Alimenta R10/R12 del LP. |

**Invariantes**:

- Cada materia pertenece a **exactamente un** `GrupoMateriaDB`
  (`grupo_id NOT NULL`, enforzado por schema).
- `horas_teoria + horas_laboratorio ≤ horas_semanales` cuando los
  tres están definidos (chequeado en validación, no en schema).

#### `CarreraDB`

Programa académico.

| Campo | Tipo | Notas |
|-------|------|-------|
| `codigo` | `str` PK | Código único (ej. `IC`, `IS`). |
| `nombre` | `str` | Nombre completo. |
| `titulo_otorgado` | `str` | Título. |
| `duracion_anios` | `int` | Cantidad de años. |
| `cantidad_materias` | `Optional[int]` | Total esperado. |
| `dicta_recursado` | `bool` | Si la carrera ofrece recursado. Default `True`. Editable global desde Ciclos → Dictados. Sobreescribible por `MateriaDB.dicta_recursado`. |

#### `SedeDB`

Sede física donde viven las aulas.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | `str` PK UUID | Identificador opaco. |
| `nombre` | `str` unique | Ej. `"Pellegrini"`. |
| `es_default_comunes` | `bool` | **Deprecado (2026-09)**. Reemplazado por Grupos. Legacy. |

#### `AulaDB`

Espacio físico.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | `str` PK UUID | Autogenerado. |
| `sede_id` | `str` FK | Referencia a `SedeDB`. |
| `codigo_aula` | `str` unique | Display editable, autoderivable como `{sede}-{nombre}`. |
| `nombre` | `str` | |
| `capacidad` | `int > 0` | |
| `tipo` | `str` | `"teorica"`, `"anfiteatro"`, `"laboratorio"`. |
| `descripcion` | `str` | |

#### `MateriaLaboratorioDB`

M:N entre materias y aulas de tipo laboratorio compatibles.

| Campo | Tipo |
|-------|------|
| `materia_codigo` | PK, FK `materias.codigo` |
| `aula_id` | PK, FK `aulas.id` |

Alimenta R3 del LP (una clase de laboratorio sólo va a un lab
compatible con su materia). Además habilita la **excepción de
lab** de R10 (§5.5.3).

#### `CorrelativaDB`

Precedencia entre materias por carrera.

| Campo | Tipo |
|-------|------|
| `carrera_codigo` | PK, FK |
| `materia_codigo` | PK, FK |
| `materia_correlativa_codigo` | PK, FK |

### 2.2 Zona: grupos de materias

Reemplazo (2026-09) de `CarreraSedeDB` como fuente de verdad de
la resolución R10/R12 del LP.

#### `GrupoMateriaDB`

Agrupa materias que comparten criterio de sedes.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | `str` PK UUID | |
| `nombre` | `str` unique | Ej. `FB`, `F`, `FI`, `CE`, `Específicas de Ing. Electrónica`, `Sin clasificar`. |
| `descripcion` | `str` | |
| `es_sin_clasificar` | `bool` | Marca el fallback. **A lo sumo uno con `True`**. |
| `chequear_pertenencia_asociadas` | `bool` | Flag del chequeo de consistencia (default `True`). |
| `chequear_exclusividad_no_asociadas` | `bool` | Idem, default `True`. |
| `chequear_completitud` | `bool` | Idem, default `True`. |

**Dos configuraciones simultáneas de sedes**:

- **Set duro** (`tipo=DURO` en `GrupoMateriaSedeDB`): sedes
  admisibles cuando el grupo corre en modo DURO. R10 filtra a
  esas sedes. Lista vacía = fallback permisivo (todas admisibles).
- **Lista blanda ordenada** (`tipo=BLANDO`): sedes cuando el grupo
  corre en modo BLANDO. La primera es la preferida (paga cero al
  objetivo); el resto son alternativas con costo `λ_sede_pref`
  por horario asignado (R12).

El modo por-grupo se elige por corrida desde
`LPConfig.modos_por_grupo` en el panel del asignador.

**Bootstrap idempotente** (`_migrate_grupos_materia` en
`connection.py`) al inicializar la base:

| Grupo | Modo default | Set duro | Prefijo de materia | Motivación |
|---|---|---|---|---|
| `Sin clasificar` | DURO | todas las sedes activas (fallback permisivo) | ninguno | Fallback. |
| `FB` | DURO | Pellegrini | `FB*` | Ciclo básico de ingenierías. |
| `F` | DURO | Siberia | `F*` (excluye `FB*`, `FI*`) | Troncal de ingenierías. |
| `FI` | DURO | Pellegrini | `FI*` | Inglés. |
| `CE` | DURO | Pellegrini | `CE*` | Comunes de licenciaturas y profesorados. |
| `Específicas de <Carrera>` | DURO | según `CarreraSedeDB` original | ninguno | Una por carrera. Se llena con materias exclusivas de esa carrera. |

**Invariantes**:

- Toda materia tiene grupo (`MateriaDB.grupo_id NOT NULL`).
- No se puede borrar un grupo con materias asignadas (rechazo
  explícito en `grupo_materia_service.delete_grupo`).

#### `GrupoMateriaSedeDB`

M:N ordenada con tipo DURO/BLANDO en la PK.

| Campo | Tipo | Notas |
|-------|------|-------|
| `grupo_id` | PK, FK | |
| `sede_id` | PK, FK | |
| `tipo` | PK, `str` | `"DURO"` o `"BLANDO"`. Permite que la misma sede aparezca en ambos sets. |
| `orden` | `int ≥ 0` | 0 = primera. Semántico sólo en BLANDO (0 = preferida). En DURO sólo estabilidad visual. |

#### `GrupoMateriaCarreraDB`

M:N grupo ↔ carrera para el chequeo de consistencia. No afecta al
LP.

| Campo | Tipo |
|-------|------|
| `grupo_id` | PK, FK |
| `carrera_codigo` | PK, FK |

#### `CarreraSedeDB` (DEPRECADA)

M:N legacy entre carreras y sedes habilitadas. Reemplazada por
`GrupoMateriaSedeDB` con el grupo `Específicas de <Carrera>`.
Sobrevive en el schema para no romper migraciones viejas pero
ningún flujo la lee.

### 2.3 Zona: estructura curricular

#### `PlanCarreraVersionDB`

Versión fechada del plan de estudios de una carrera. Permite
mantener múltiples versiones vivas (Plan 2015, Plan 2023, etc.)
sin perder trazabilidad de cohortes anteriores.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `carrera_codigo` | FK | |
| `nombre` | `str` | Ej. `"Plan Original"`, `"Plan 2025"`. |
| `descripcion` | `str` | |
| `fecha_creacion` | `date` | |

#### `PlanEstudioDB`

Materia dentro de una versión de plan.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `plan_version_id` | FK | |
| `materia_codigo` | FK, index | |
| `carrera_codigo` | FK, index | Denormalizado desde la versión. |
| `anio_plan` | `Optional[int]` | Año sugerido (1-6). |
| `cuatrimestre_plan` | `Optional[str]` | `"1C"`, `"2C"`, `"Anual"`. |
| `optativa` | `bool` | Si es opcional. |
| `correlativas` | `str` | Texto crudo (para display, no computable). |

#### `CicloPlanVersionDB` (bridge)

Vincula versiones de plan con ciclos. Define qué materias se
ofrecen en cada ciclo.

| Campo | Tipo |
|-------|------|
| `ciclo_id` | PK, FK |
| `plan_version_id` | PK, FK |

### 2.4 Zona: ciclo lectivo

#### `CicloDB`

Cuatrimestre lectivo concreto.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | `str` PK | `"2026-1C"`, `"2026-2C"`. |
| `nombre` | `str` | |
| `fecha_inicio` | `date` | |
| `fecha_fin` | `date` | |
| `descripcion` | `str` | |

Cada ciclo es una **unidad operativa autónoma** (ver §4.3). Crear
el 1C no crea ni pre-declara nada del 2C, y viceversa.

#### `DictadoDB`

Oferta de una materia en un período. Existe **si y sólo si** la
materia se dicta en el ciclo correspondiente. Los dictados
cuatrimestrales se linkean a un único ciclo; los anuales a dos
ciclos del mismo año lectivo vía `DictadoCicloDB`.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `dictado_codigo` | unique | Display: `"MAT101-2026-1C"` o `"MAT101-2026"` (anual). |
| `materia_codigo` | FK | |
| `inicio_dictado` | `date` | Heredado del primer ciclo vinculado. |
| `fin_dictado` | `Optional[date]` | Anuales: `None` al 1C, se completa al 2C. |
| `virtual` | `Optional[bool]` | Override de virtualidad para este ciclo. `None` = heredar de `MateriaDB.virtual`. |

**Semántica "existencia = activación"** (2026-06-30). Si la fila
existe, la materia se ofrece este ciclo. Para desactivar hay que
borrar la fila (`borrar_dictado_de_ciclo`, que además nulifica
las `ClaseDB.dictado_id` huérfanas para preservarlas). Ver
[`../2. Desarrollo/CICLOS_Y_DICTADOS.md`](../2.%20Desarrollo/CICLOS_Y_DICTADOS.md).

#### `DictadoCicloDB` (bridge)

Vincula dictados con ciclos.

| Campo | Tipo |
|-------|------|
| `dictado_id` | PK, FK |
| `ciclo_id` | PK, FK |

Cuatrimestrales: 1 fila. Anuales: 2 filas (una por ciclo del año).

### 2.5 Zona: cronogramas

#### `ScheduleDB`

Carga validada de horarios desde un archivo.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `ciclo_id` | `Optional[str]` FK | |
| `nombre` | `str` | |
| `fecha_upload` | `datetime` | |
| `source_filename` | `str` | |

#### `ScheduleEntryDB`

Filas individuales del cronograma normalizadas.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `schedule_id` | FK | |
| `codigo_materia` | FK | Ya resuelto a código del plan (no guaraní). |
| `dia` | `str` | |
| `hora_inicio` | `time` | |
| `hora_fin` | `time` | |
| `comision_id` | `Optional[str]` FK | Referencia a la `ComisionDB` template del mismo `schedule_id`. Reemplazo (2026-07) del viejo `comision: int`. |
| `tipo_clase` | `Optional[str]` | `"teorica"` / `"laboratorio"` / `None`. |
| `virtual` | `Optional[bool]` | Override de virtualidad. Se propaga a `HorarioDB.virtual` al generar el plan. |

#### `ScheduleValidationDB`

Snapshot histórico de una validación de cronograma contra un
ciclo. Cada corrida agrega una fila. Ver
[`../2. Desarrollo/VALIDACIONES.md`](../2.%20Desarrollo/VALIDACIONES.md)
§2.1.

### 2.6 Zona: plan de cursada

#### `PlanificacionCursadaDB`

Escenario de planificación para un ciclo.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `nombre` | `str` | |
| `descripcion` | `str` | |
| `ciclo_id` | FK | |
| `schedule_id` | `Optional[str]` FK | Cronograma origen. |
| `forecast_metodo_default` | `str` | Método de forecast default (`"media_movil"`, `"drift"`, `"ses"`). |

Nota: el flag `activo` fue **eliminado** en migración
`_migrate_planificacion_cursada_drop_activo`. Puede haber
múltiples planes por ciclo; la interfaz muestra el último editado.

#### `ComisionDB`

Grupo de estudiantes (**entidad de primera clase** desde 2026-07).

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `materia_codigo` | FK | Denormalizado. |
| `dictado_id` | `Optional[str]` FK | |
| `plan_cursada_id` | `Optional[str]` FK | XOR con `schedule_id`. |
| `schedule_id` | `Optional[str]` FK | XOR con `plan_cursada_id`. |
| `comision_key` | `str` | Clave plan-agnóstica: `{materia_codigo}-{numero:03d}` o `{dictado_codigo}-{numero:03d}`. |
| `nombre` | `str` | Ej. `"Comisión 1"`, `"A-Turno Mañana"`. |
| `numero` | `int` | Secuencial dentro de la materia. |
| `cupo` | `int` | Heredable desde `MateriaDB.cupo`. |
| `descripcion` | `str` | |
| `carrera_asignada` | `Optional[str]` FK | **Sólo etiqueta visual (2026-09)**. No interviene en el LP. |
| `coef_asignacion` | `float ∈ [0, 1]` | Fracción de la demanda del dictado que va a esta comisión. Suma 1 dentro del dictado. |

**Invariante XOR** (INV-COM-XOR): exactamente uno de `schedule_id`
o `plan_cursada_id` está seteado. Validado en la capa de servicios.

**Clonado cronograma → plan**: al generar un plan desde un
cronograma, las comisiones template se **clonan** (nuevos
identificadores, `plan_cursada_id` seteado, `schedule_id=None`)
preservando todos los atributos. Editar la comisión del plan no
afecta a la del cronograma. Ver
`comision_service.clone_comisiones_for_plan`.

#### `HorarioDB`

Patrón semanal de una comisión.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK | |
| `comision_id` | FK, index | |
| `codigo_materia` | FK, index | Denormalizado. |
| `dia` | `str`, index | |
| `hora_inicio` | `time` | |
| `hora_fin` | `time` | |
| `tipo_clase` | `Optional[str]` | `"teorica"` / `"laboratorio"` / `None` (LP decide). |
| `aula_id` | `Optional[str]` FK, index | **Objetivo del asignador**. |
| `aula_asignada_manualmente` | `bool` | Pin manual (R11 del LP). |
| `virtual` | `Optional[bool]` | Override de virtualidad. Ver §4.1. |

#### `ClaseDB` (DEPRECADA — caché técnico)

Instancia puntual de una clase con fecha, expandida desde un
`HorarioDB`. Deprecada desde 2026-08. Ninguna vista de la UI la
renderiza y ninguna operación la edita. La propagación desde
`HorarioDB` sigue viva vía `apply_solution` como caché.

| Campo | Tipo | Notas |
|-------|------|-------|
| `id` | PK UUID | |
| `horario_id` | FK | |
| `comision_id` | FK | Denormalizado. |
| `plan_cursada_id` | FK | Denormalizado. |
| `dictado_id` | FK | Para queries cross-plan. |
| `fecha` | `date` | |
| `hora_inicio` | `time` | Copiado del horario. |
| `hora_fin` | `time` | Copiado del horario. |
| `executed` | `bool` | Marca permanente: `True` cuando la clase ocurrió. |
| `aula_id` | `Optional[str]` FK | Heredado del patrón. |
| `tipo_clase` | `Optional[str]` | Heredado del patrón. |
| `aula_asignada_manualmente` | `bool` | Deprecado; el flag activo vive en `HorarioDB`. |

Ver [`../2. Desarrollo/sesiones/DEPRECACION_CLASEDB.md`](../2.%20Desarrollo/sesiones/DEPRECACION_CLASEDB.md)
para el plan de retiro.

### 2.7 Zona: excepciones, snapshots y auditoría

#### `IgnoredConflictDB`

Par de materias cuyo conflicto de horarios el usuario decidió
ignorar en el chequeo de solapamiento del plan.

| Campo | Tipo | Notas |
|-------|------|-------|
| `plan_cursada_id` | PK, FK | Cascade al borrar el plan. |
| `materia_a` | PK | Menor lexicográficamente. |
| `materia_b` | PK | Mayor lexicográficamente. |
| `razon` | `str` | Justificación textual del usuario. |
| `fecha_creacion` | `datetime` | |

**Alcance**: sólo aplica al chequeo de **solapamiento horario**.
El chequeo de **intersede** (R13, R13-camino) las ignora.

**Auto-limpieza**:
`plan_validation_service.cleanup_stale_ignored_pairs` corre en
cada `validate_plan` y elimina pares cuyas materias ya no
coexisten en ningún grupo curricular `(carrera, año, cuatri)` del
plan. Reporta la limpieza en `summary.excepciones_stale_removidas`.

#### `PlanValidationDB`

Snapshot histórico de una validación de un plan.

#### `LPRunDB`

Snapshot histórico de una corrida del asignador. Persiste config
completa, status, contadores y un `details_json` con la
asignación por horario, el diagnóstico, el veredicto humano y las
restricciones activas.

Ver
[`../Informe/anexos/Anexo_Base_de_Datos.md`](../Informe/anexos/Anexo_Base_de_Datos.md)
§ 11 para la ficha completa.

#### `ChangeLogDB`

Log global de mutaciones sobre entidades trackeadas (materias,
carreras, dictados, sedes, grupos). Fuente de la vista Historial.

### 2.8 Zona: forecast e inscripciones

#### `InscripcionHistoricaDB`

Historial de inscriptos por `(materia, año, cuatrimestre)`.
Alimenta el forecast.

#### `MateriaForecastConfigDB`

Override de config de forecast por `(plan, materia, cuatri)`:
método (`"media_movil"`, `"drift"`, `"ses"`) o valor forzado.

### 2.9 Zona: configuración global

#### `ConfiguracionHoraria`

Parámetros globales de la grilla: granularidad, hora de apertura,
hora de cierre, días operativos.

---

## 3. Relaciones y multiplicidades

Para el UML completo con políticas de borrado ver
[`diagrama-entidades.md`](diagrama-entidades.md). Este resumen
apunta a los patrones de composición.

### 3.1 Cascadas de composición

```
CicloDB ──cascade──> PlanificacionCursadaDB ──cascade──> ComisionDB ──cascade──> HorarioDB
                                              ──cascade──> ClaseDB (caché)
                                              ──cascade──> IgnoredConflictDB
CicloDB ──cascade──> ScheduleDB ──cascade──> ScheduleEntryDB
CicloDB ──cascade──> DictadoCicloDB
GrupoMateriaDB ──cascade──> GrupoMateriaSedeDB
GrupoMateriaDB ──cascade──> GrupoMateriaCarreraDB
```

### 3.2 Restricciones de borrado (restrict)

- `CarreraDB` no se puede borrar si tiene `PlanCarreraVersionDB`.
- `SedeDB` no se puede borrar si tiene `AulaDB` o referencias en
  `GrupoMateriaSedeDB`.
- `GrupoMateriaDB` no se puede borrar si tiene materias asignadas.

### 3.3 Snapshots (no se cascadean automáticamente)

Los snapshots (`ScheduleValidationDB`, `PlanValidationDB`,
`LPRunDB`) se conservan para auditoría cuando se borra la entidad
principal, salvo que el operador dispare un `truncate` explícito.

### 3.4 Campos denormalizados intencionalmente

| Entidad | Campo | Derivable de | Motivación |
|---|---|---|---|
| `PlanEstudioDB` | `carrera_codigo` | `plan_version.carrera_codigo` | Query directa por carrera. |
| `ComisionDB` | `materia_codigo` | `comision.dictado.materia` | Query "comisiones de MAT101" sin joins. |
| `HorarioDB` | `codigo_materia` | `horario.comision.materia` | Historia del modelo. |
| `ClaseDB` | `comision_id`, `plan_cursada_id`, `dictado_id` | `clase.horario.comision.*` | Queries cross-plan por materia/ciclo. |

---

## 4. Reglas jerárquicas del dominio

### 4.1 Virtualidad jerárquica en tres niveles

`HorarioDB.virtual > DictadoDB.virtual > MateriaDB.virtual`. Los
dos primeros son `Optional[bool]` (`None` = heredar). El helper
`resolve_virtual(horario, dictado, materia) -> bool` camina la
jerarquía y devuelve el primer valor no nulo.

**Consecuencia operativa**: un horario efectivamente virtual **no
ocupa aula**. El asignador lo excluye del modelo salvo bajo R5
estricto, donde participa del balance teoría/lab sin variable de
aula.

Casos de uso: recursado por Zoom que no debe alterar el catálogo,
teoría virtual + laboratorio presencial dentro del mismo dictado,
comisión híbrida.

### 4.2 Recursado jerárquico en dos niveles

`MateriaDB.dicta_recursado > CarreraDB.dicta_recursado`. El helper
`resolve_dicta_recursado(materia, carrera) -> bool` resuelve el
valor efectivo. Al generar dictados para un ciclo, el servicio
`create_dictados_for_ciclo` aplica la regla: si el efectivo es
`False` y el cuatrimestre del plan es opuesto al ciclo, el dictado
no se crea.

### 4.3 Independencia entre ciclos

Cada `CicloDB` es una unidad operativa autónoma. Crear el 1C no
crea ni pre-declara nada del 2C, y viceversa. La única entidad que
se comparte entre dos ciclos es el `DictadoDB` de una materia
**anual**, que existe como fila única con dos vínculos en
`DictadoCicloDB` (uno por ciclo del año). Al crear el 1C se
instancia con `fin_dictado=None`; cuando se crea el 2C del mismo
año, `_link_anual_dictado_2c` reutiliza el dictado y completa
`fin_dictado`. Ninguna otra información se propaga entre ciclos:
horarios, comisiones, planes y asignaciones son estrictamente por
ciclo.

### 4.4 Partición estricta materia → grupo

Cada `MateriaDB` referencia un único `GrupoMateriaDB` vía
`grupo_id` NOT NULL. Las materias sin grupo específico caen al
grupo `Sin clasificar`, que se muestra con warning en la UI para
forzar curación.

### 4.5 Anclaje XOR de comisión (cronograma vs plan)

Cada `ComisionDB` pertenece a **o bien** un cronograma
(`schedule_id`) **o bien** un plan (`plan_cursada_id`), pero no a
ambos. Validado en `comision_service`. Ver §2.6.

### 4.6 Auto-limpieza de excepciones ignoradas

`IgnoredConflictDB` se limpia automáticamente cuando cambia la
coexistencia curricular de las materias del par. Ver §2.7.

---

## 5. Flujo operativo por ciclo

El flujo completo de trabajo desde la carga inicial hasta la
asignación de aulas está documentado en
[`../2. Desarrollo/WORKFLOW.md`](../2.%20Desarrollo/WORKFLOW.md).
Este resumen apunta a los hitos clave.

```
1. Ciclo + versiones de plan       ──▶  CicloDB + CicloPlanVersionDB
2. Dictados del ciclo               ──▶  DictadoDB + DictadoCicloDB (regla de recursado)
3. Cronograma                       ──▶  ScheduleDB + ScheduleEntryDB + ComisionDB template
4. Prevalidación cronograma vs ciclo──▶  ScheduleValidationDB (snapshot)
5. Generación del plan              ──▶  PlanificacionCursadaDB + ComisionDB clonadas + HorarioDB
6. Refinado del plan                ──▶  edición manual, forecast, tipo de clase
7. Validación del plan              ──▶  PlanValidationDB (snapshot) + auto-limpieza excepciones
8. Asignador de aulas               ──▶  LPRunDB (snapshot) + HorarioDB.aula_id + ClaseDB (caché)
```

Cada hito genera un snapshot persistido para auditoría (§9.4 del
capítulo del informe).

### 5.1 Estados derivados de `ClaseDB`

La única columna de estado almacenada es `executed: bool`. Los
demás estados se **derivan** en tiempo de consulta:

| Estado | Condición | Significado |
|---|---|---|
| Ejecutada | `executed = True` | La clase ocurrió. Marca permanente. |
| Planificada | `executed = False` AND `fecha ≥ hoy` | Clase futura del plan. |
| Pasada sin ejecutar | `executed = False` AND `fecha < hoy` | Ocurrió pero no se marcó ejecutada (fuera del flujo activo). |

En el modelo actual (sin plan activo vs escenarios de comparación,
depredado con `_migrate_planificacion_cursada_drop_activo`), la
distinción entre borrador y planificada desapareció: hay un único
plan operativo por ciclo.

---

## 6. Validaciones del modelo

Las reglas de negocio están enunciadas como invariantes con
identificadores estables (`INV-*`, `RN*`) en el anexo A y en el
capítulo 9 del informe. Este resumen indica dónde se aplica cada
familia.

| Familia | Dónde vive |
|---|---|
| Constraints declarativas (PK, FK, unique, ge, gt) | Schema del ORM (`src/database/models.py`). |
| Invariantes de aplicación (XOR de comisión, partición grupo, sumas de coeficientes) | Servicios (`src/services/*.py`). |
| Validaciones agregadoras (cobertura, conflictos, partición T/L, camino cursada) | `cronograma_validation_service.py`, `plan_validation_service.py`, `factibilidad_service.py`. |
| Chequeo pre-solve del LP (R1..R14 estructural) | `factibilidad_service.check_factibilidad_estructural`. |

Detalle completo:
[`../2. Desarrollo/VALIDACIONES.md`](../2.%20Desarrollo/VALIDACIONES.md).

---

## 7. Extensiones fuera de alcance

Entidades planteadas y diferidas:

| Entidad | Propósito | Cuándo |
|---|---|---|
| Alumno, Profesor, Inscripción, Asistencia | Modelo de personas | Cuando se implemente la gestión de inscripciones y de personal docente. |
| Reserva de aula | Bloqueo puntual (mantenimiento, evento) | Requiere una tabla `AulaIndisponibleDB(aula_id, fecha, hora_inicio, hora_fin)` que el LP consultaría. |
| Ventana operativa por sede | Sedes con horarios distintos | Requiere migrar `ConfiguracionHoraria` de global a por-sede. |
| R13 blanda | Costo por cambio de sede en pares en riesgo | Cableado en `LPConfig.lambda_intersede` pero no activo (default 0). Reservado para variante blanda futura. |

---

## 8. Referencias

- Planteo formal del LP: [`asignacion-aulas-LP.md`](asignacion-aulas-LP.md).
- Diagrama UML con políticas de borrado: [`diagrama-entidades.md`](diagrama-entidades.md).
- Anexo técnico exhaustivo por tabla: [`../Informe/anexos/Anexo_Base_de_Datos.md`](../Informe/anexos/Anexo_Base_de_Datos.md).
- Implementación del asignador: `../2. Desarrollo/asignador.md`.
- Ciclos, dictados y virtualidad: [`../2. Desarrollo/CICLOS_Y_DICTADOS.md`](../2.%20Desarrollo/CICLOS_Y_DICTADOS.md).
- Validaciones: [`../2. Desarrollo/VALIDACIONES.md`](../2.%20Desarrollo/VALIDACIONES.md).
- Workflow end-to-end: [`../2. Desarrollo/WORKFLOW.md`](../2.%20Desarrollo/WORKFLOW.md).
