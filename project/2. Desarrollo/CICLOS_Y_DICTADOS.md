# Ciclos y dictados

> Guía técnica y operativa para configurar un ciclo lectivo en
> gestor-aulas: modelo mental, semántica de dictados y virtualidad,
> operatoria de carga desde cero, sincronización con reglas,
> auditoría de cambios y escenarios recurrentes.
>
> **Última actualización**: 2026-09-12 (consolida el runbook operativo
> con las notas conceptuales del refactor `activo` → `existencia`, la
> virtualidad jerárquica y el change log).
>
> **Referencias cruzadas**:
> - Modelo de datos: [`../1. Diseño/modelo-planificacion-cursada.md`](../1.%20Diseño/modelo-planificacion-cursada.md).
> - Validaciones del sistema: [`VALIDACIONES.md`](VALIDACIONES.md).
> - Flujo end-to-end (con asignación de aulas): [`WORKFLOW.md`](WORKFLOW.md).

---

## Índice

1. [Modelo mental](#1-modelo-mental)
2. [Semántica de dictados y las tres puertas de decisión](#2-semántica-de-dictados-y-las-tres-puertas-de-decisión)
3. [Virtualidad jerárquica y recursado jerárquico](#3-virtualidad-jerárquica-y-recursado-jerárquico)
4. [Sincronización de dictados y panel de divergencias](#4-sincronización-de-dictados-y-panel-de-divergencias)
5. [Auditoría — change log](#5-auditoría--change-log)
6. [Runbook: crear un ciclo desde cero](#6-runbook-crear-un-ciclo-desde-cero)
7. [Checklist previo al asignador de aulas](#7-checklist-previo-al-asignador-de-aulas)
8. [Escenarios recurrentes](#8-escenarios-recurrentes)
9. [Archivos y símbolos relevantes](#9-archivos-y-símbolos-relevantes)

---

## 1. Modelo mental

Un **ciclo lectivo** es un cuatrimestre concreto (por ejemplo,
`2026-1C` o `2026-2C`). Cada ciclo se configura de forma
**independiente** de los demás: crear el 1C no crea nada del 2C, y
viceversa. La única entidad que se comparte entre dos ciclos es
el `DictadoDB` de una materia **anual**, que se materializa como
una fila única linkeada a ambos ciclos del año lectivo vía dos
filas de `DictadoCicloDB` (regla RN19 del modelo).

La configuración de un ciclo se compone de tres capas apiladas:

```text
┌──────────────────────────────────────────────────────────────┐
│ 3. Cronograma cargado (horarios semanales por comisión)       │
│    ScheduleDB + ScheduleEntryDB                               │
├──────────────────────────────────────────────────────────────┤
│ 2. Dictados del ciclo (qué materias se dictan y cómo)         │
│    DictadoDB + DictadoCicloDB                                 │
├──────────────────────────────────────────────────────────────┤
│ 1. Plan versions asignadas al ciclo (qué carreras participan) │
│    CicloPlanVersionDB → PlanCarreraVersionDB                  │
└──────────────────────────────────────────────────────────────┘
                    ↓ alimenta ↓
┌──────────────────────────────────────────────────────────────┐
│ Plan de cursada + Programa lineal de asignación de aulas      │
└──────────────────────────────────────────────────────────────┘
```

Cada capa filtra o transforma lo que llega desde arriba. Las
decisiones de una capa se validan contra las anteriores (por
ejemplo, el cronograma se prevalida contra los dictados creados).

---

## 2. Semántica de dictados y las tres puertas de decisión

### 2.1 "Existencia = activación"

**Antes** (previo al refactor de 2026-06-30): `DictadoDB` tenía
un campo `activo: bool` (default `True`) y un override manual
`activo_override_manual`. Podía existir un dictado creado en un
ciclo pero marcado como inactivo, lo cual generaba dos preguntas
conceptualmente distintas ("¿existe?" y "¿está activo?") que en la
práctica eran redundantes y difíciles de mantener sincronizadas.

**Ahora**: un dictado **existe ↔ se dicta en ese ciclo**. No hay
flag `activo`. Para "desactivar" hay que borrar la fila con
`borrar_dictado_de_ciclo` (que nullifica `ClaseDB.dictado_id` en
las clases huérfanas para preservarlas). Para "reactivar" hay que
volver a crear el dictado.

Consecuencias:

- `create_dictados_for_ciclo` ya **no crea** dictados que la regla
  de recursado dice omitir; antes los creaba con `activo=False`.
- La sincronización de dictados vs plan es explícita
  (`sync_dictados_para_ciclo`) y siempre en modo preview + apply,
  sin auto-borrado.
- Las 3 secciones del panel de divergencias son ortogonales y
  autoexplicativas (ver §4).

**Campos eliminados de `DictadoDB`**: `activo`,
`activo_override_manual`. También el parámetro `activo` del
helper `update_dictado`.

### 2.2 Las tres puertas

Cuando uno se pregunta "¿esta materia se dicta este ciclo? y si sí,
¿cómo?", en realidad atraviesa **tres puertas de decisión
distintas**, cada una con su propio mecanismo y su propia jerarquía.
Confundirlas es fuente de errores frecuente cuando se carga un
ciclo por primera vez.

#### Puerta 1: pertenencia estructural

*¿La materia está en el ciclo?*

La materia tiene que estar declarada en alguna versión de plan de
estudios que esté asignada al ciclo:

```text
MateriaDB → PlanEstudioDB → PlanCarreraVersionDB
                                    ↑
                            CicloPlanVersionDB
                                    ↓
                                 CicloDB
```

Si la materia no aparece en ningún `PlanEstudioDB` cuya
`plan_version_id` esté enganchada al ciclo vía
`CicloPlanVersionDB`, el ciclo ni siquiera la considera.
`create_dictados_for_ciclo` directamente no la ve.

En la práctica, **la configuración inicial más importante de un
ciclo es qué versiones de plan le asignás**. Error habitual:
asignar la versión del plan de una carrera y olvidarse de otra,
con lo cual las materias exclusivas de esa segunda carrera quedan
fuera del ciclo sin previo aviso.

#### Puerta 2: regla de recursado

*¿Esta materia se dicta al recursado?*

Aplica **sólo a materias cuatrimestrales cuyo cuatrimestre en el
plan es opuesto al del ciclo** (por ejemplo, una materia declarada
como "2C" en el plan cuando estamos creando un ciclo "1C"). Para
esas materias, la pregunta operativa es: "¿la facultad quiere
ofrecerla como recursado en el cuatrimestre opuesto?".

La resolución es **jerárquica materia > carrera**, implementada
en `resolve_dicta_recursado`:

- `MateriaDB.dicta_recursado` es `Optional[bool]`:
  - `None` (default) → heredar de la carrera.
  - `True` → forzar recursado, ignorando la carrera.
  - `False` → forzar NO recursado, ignorando la carrera.
- `CarreraDB.dicta_recursado` es `bool` (default `True`).

Si el valor resuelto es `True`, la materia queda en el ciclo. Si
es `False`, `_should_skip_for_recursado` la excluye y el dictado
no se crea.

**Matiz — materias compartidas por múltiples carreras**: si una
materia aparece en `PlanEstudioDB` con más de un `carrera_codigo`,
`_should_skip_for_recursado` **nunca la skippea**, porque no hay
una "carrera dueña" única de la cual heredar el flag. Se dicta en
ambos cuatrimestres siempre. Es intencional (las materias
compartidas suelen ser de primer año y tienen alta demanda).

**Materias anuales**: la regla de recursado **no se aplica** a
las anuales. Se dictan siempre y en ambos ciclos del año lectivo.

#### Puerta 3: modalidad virtual

*¿Los horarios consumen aula?*

La modalidad virtual no decide si la materia se dicta o no.
Decide si los horarios de la materia **participan del LP de
asignación de aulas**. Si un horario es virtual efectivo, se
filtra antes de armar el modelo (no consume aula) pero el dictado
sigue existiendo y la validación del cronograma lo cuenta como
cubierto.

La resolución es **jerárquica horario > dictado > materia**,
implementada en `resolve_virtual` (ver §3).

#### Cómo se combinan las tres puertas

Ante una configuración concreta, el orden lógico de resolución es:

```text
1. ¿La materia está en algún plan asignado al ciclo?
      ├── No → la materia queda fuera del ciclo (ni dictado se
      │       intenta crear).
      └── Sí → seguir.

2. ¿Es cuatrimestral del cuatrimestre opuesto al ciclo?
      ├── No (anual, o cuatrimestral del mismo cuatri) →
      │       se crea el dictado.
      └── Sí → resolver dicta_recursado (jerárquico materia >
              carrera). ¿Compartida por múltiples carreras?
              ├── Sí → se crea el dictado (nunca se skippea).
              └── No, y dicta_recursado resuelto es:
                  ├── True  → se crea el dictado.
                  └── False → NO se crea el dictado (skipped).

3. Para cada horario del dictado creado, al correr el LP:
      ¿es virtual efectivo? (jerárquico horario > dictado > materia)
      ├── Sí → se filtra del LP (no consume aula, pero el dictado
      │       existe y cubre el cronograma).
      └── No → participa del LP normalmente.
```

Las puertas 1 y 2 se evalúan **al crear el ciclo** (o al correr
`sync_dictados_para_ciclo`), y su resultado se materializa como
"existe o no existe la fila de `DictadoDB` + `DictadoCicloDB`".
La puerta 3 se evalúa **al correr el LP de asignación**, sobre
los horarios ya cargados, y su resultado es "el horario entra al
modelo o se filtra".

### 2.3 Independencia entre ciclos

De la semántica "existencia = activación" se deriva un corolario
importante: **cada ciclo es una unidad operativa autónoma**.
Crear el ciclo 1C no crea ni pre-declara nada del 2C, y
viceversa. Cada corrida de `create_dictados_for_ciclo` opera
sobre las materias del plan asignado al ciclo actual y aplica la
regla de recursado sólo a ese ciclo. Los dictados
**cuatrimestrales** viven cada uno linkeado a un único ciclo; no
hay propagación entre ciclos ni efectos cruzados.

La única entidad que se comparte entre dos ciclos es el
`DictadoDB` de una materia **anual**, que se materializa como
una fila única con dos filas de `DictadoCicloDB` (una por ciclo
del año lectivo). Al crear el 1C, un dictado anual nace con
`fin_dictado=None`; cuando después se crea el 2C del mismo año,
`_link_anual_dictado_2c` reutiliza ese dictado, le agrega el
bridge al 2C y completa `fin_dictado`. Si el 2C se crea sin que
exista todavía el 1C previo, se crea un dictado anual fresco
(con las dos filas de `DictadoCicloDB` aún por completarse
cuando aparezca el 1C correspondiente).

Ninguna otra información se propaga entre ciclos: horarios,
comisiones, planes de cursada, asignaciones de aula y
validaciones son estrictamente por ciclo. Formalizado como RN19
en `../1. Diseño/modelo-planificacion-cursada.md`.

---

## 3. Virtualidad jerárquica y recursado jerárquico

### 3.1 Virtualidad — regla "el nivel más específico manda"

Un horario efectivamente virtual se resuelve en cascada:

```
HorarioDB.virtual  >  DictadoDB.virtual  >  MateriaDB.virtual
   (Optional[bool])     (Optional[bool])       (bool, raíz)
```

- `None` = heredar del padre.
- `True/False` = forzar el valor, ignorando padres.

El helper `resolve_virtual(horario, dictado, materia) -> bool`
centraliza la resolución. Los cuatro consumidores importantes
(LP `build_inputs`, generación de bloques del plan, inspector
de franja, validación de cronograma) ya lo usan.

**Uso típico**:

| Ubicación del override | Alcance | Caso de uso |
|---|---|---|
| `MateriaDB.virtual=True` | Todos los dictados y horarios de la materia, en todos los ciclos | Materia virtual por diseño en el plan (ej. asincrónicas del ciclo superior). |
| `DictadoDB.virtual=True` | Todos los horarios de una materia en un ciclo puntual | Recursado por Zoom, o modalidad puntual del ciclo sin tocar el catálogo. |
| `HorarioDB.virtual=True` | Un horario específico de una comisión | Comisión híbrida (algunas franjas presenciales, otras virtuales). |

### 3.2 Recursado — regla análoga con dos niveles

`MateriaDB.dicta_recursado` (Optional[bool]) prevalece sobre
`CarreraDB.dicta_recursado` (bool). Se resuelve con
`resolve_dicta_recursado(materia, carrera) -> bool`. Es el mismo
patrón con sólo 2 niveles.

---

## 4. Sincronización de dictados y panel de divergencias

### 4.1 La API — `sync_dictados_para_ciclo`

Compara el set de dictados existentes en un ciclo contra las
materias del plan y las reglas vigentes, y devuelve un
`SyncResult` con 3 listas:

- **`to_create`**: materias del plan sin dictado y la regla NO
  dice skippear. Deberían existir.
- **`to_delete`**: dictados existentes cuya materia ya no está
  en el plan del ciclo (huérfanos, típicamente aparecen tras
  cambiar la versión de plan asignada).
- **`rule_says_skip_but_exists`**: dictados existentes que la
  regla actual dice que no deberían existir. **Nunca se borran
  automáticamente** — el usuario decide si los borra o si
  promueve la decisión a regla general.

Con `apply=False` (default) sólo devuelve el diff. Con
`apply=True` aplica `to_create` y `to_delete`;
`rule_says_skip_but_exists` queda siempre para revisión manual.

### 4.2 El panel — `src/ui/divergencias_panel.py`

Componente reutilizable que renderiza el `SyncResult` en tres
secciones colapsables, con acciones por fila:

- **Sección `to_create`**:
  - `[✅ Crear]`: crea el dictado en el ciclo.
  - `[⏭️ Omitir en regla]`: setea
    `MateriaDB.dicta_recursado=False` para que ciclos futuros
    omitan la materia (no crea nada en el ciclo actual).
  - `[⏭️ Omitir TODAS en regla (N)]`: bulk con confirmación en 2
    pasos.

- **Sección `to_delete`**:
  - `[🗑️ Borrar]`: borra el dictado y nullifica clases huérfanas.

- **Sección `rule_says_skip_but_exists`**:
  - `[🗑️ Borrar]`.
  - `[⬆️ Promover a regla]`: setea
    `MateriaDB.dicta_recursado=True` para que en ciclos futuros
    ya no sea divergencia.
  - `[⬆️ Promover TODAS a regla (N)]`: bulk con confirmación.

- Botón masivo global `[⚡ Aplicar todo]` que ejecuta
  `sync_dictados_para_ciclo(apply=True)` (respeta la sección
  `rule_says_skip_but_exists`, nunca borra masivamente).

### 4.3 Promoción a regla — `promover_a_regla`

Cambia `MateriaDB.dicta_recursado` según la acción:

- `"crear-en-regla"` → `True` (la materia pasa a ser esperada
  por defecto).
- `"omitir-en-regla"` → `False` (la materia pasa a ser omitida
  por defecto en ciclos donde el cuatrimestre no coincide).

**No modifica** dictados existentes; sólo el catálogo. El usuario
tiene que aplicar la sincronización explícitamente después si
quiere que el ciclo actual se ajuste.

---

## 5. Auditoría — change log

### 5.1 Modelo `ChangeLogDB`

Registra cada mutación relevante con:

- `entity_type` + `entity_id` + `entity_label` (label preservado
  aunque la entidad se borre).
- `action`: `created` / `updated` / `deleted`.
- `field`, `old_value`, `new_value` (para updates; JSON
  serializado).
- `reason` (texto libre) + `origin` (`ui:ciclos`,
  `ui:validacion`, `script:xxx`, `auto`).
- `when` con índice para queries por rango temporal.

### 5.2 Entidades trackeadas

Whitelist explícita en `TRACKED_ENTITIES` de
`change_log_service.py`:

| Entidad | Campos trackeados | Modo |
|---|---|---|
| `MateriaDB` | `virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`, `horas_laboratorio`, `grupo_id` | create/update/delete |
| `CarreraDB` | `dicta_recursado` | create/update/delete |
| `DictadoDB` | `virtual` | create/update/delete |
| `DictadoCicloDB` | (bridge, sin campos) | create/delete solamente |
| `SedeDB` | — (el flag legado `es_default_comunes` está deprecado) | create/update/delete |
| `GrupoMateriaDB` | flags de consistencia + alta/baja | create/update/delete |
| `GrupoMateriaSedeDB` | alta/baja de sedes por grupo | create/delete |

Las entidades de operación (`HorarioDB`, `ComisionDB`, `ClaseDB`,
etc.) **no se auditan**. Son datos de operación, no política; su
volumen generaría ruido sin valor.

### 5.3 Hooks vs eventos explícitos

- **Hooks automáticos**: capturan cualquier cambio a las
  entidades trackeadas (sin importar quién lo dispare). Corren
  en el `after_insert/update/delete` de SQLAlchemy e insertan la
  fila del log usando `connection.execute` (no la session, porque
  el flush ya está en curso).
- **Eventos explícitos**: los servicios pueden llamar
  `emit_event(...)` para agregar filas con `reason` contextualizada.
  Además existe `change_context(origin, reason)` como context
  manager que propaga la información a los hooks automáticos:

  ```python
  with change_context(
      origin="ui:ciclos",
      reason="Promoción a regla desde panel de divergencias del ciclo X",
  ):
      promover_a_regla(session, "MAT101", ciclo_id, accion="crear-en-regla")
  ```

  La mutación de `MateriaDB.dicta_recursado` queda registrada con
  esa razón sin necesidad de emitir el evento manualmente.

### 5.4 UI — página **📜 Historial**

Dos modos:

- **Feed global**: mutaciones recientes de todas las entidades
  trackeadas, con filtros por tipo y origen. Timestamp relativo
  ("hace 3 min", "hace 2 días").
- **Por entidad**: seleccionás una Materia / Carrera / Dictado /
  Sede y ves su historial completo.

El widget está en `src/ui/historial_widget.py` y se puede reutilizar
como pestaña dentro de páginas individuales.

---

## 6. Runbook: crear un ciclo desde cero

### 6.1 Prerrequisitos

Antes de crear un ciclo hay que asegurar el estado del catálogo:

- **Carreras** cargadas (`📚 Carreras`) con su flag
  `dicta_recursado` puesto en el valor correcto. Default `True`
  (la carrera acepta recursado); ponerlo en `False` si la
  carrera nunca ofrece materias del cuatrimestre opuesto.
- **Materias** cargadas (`📚 Materias`) con:
  - `periodo`: `"cuatrimestral"` o `"anual"`.
  - `horas_teoria` y `horas_laboratorio` correctas (impactan
    directamente al asignador vía R5).
  - `virtual`: `True` sólo si la materia se dicta virtual **por
    diseño en el plan** (no para casos puntuales de un ciclo).
  - `dicta_recursado`: `None` por defecto (heredar de la
    carrera); poner `True` o `False` sólo como override explícito.
  - `grupo_id`: cada materia pertenece a un grupo (partición
    estricta). Ver `asignador_implementacion.md § 5`.
- **Planes de estudio versionados** (`PlanCarreraVersionDB`) para
  cada carrera que va a participar del ciclo, con sus
  `PlanEstudioDB` cargados (materia + carrera + año +
  cuatrimestre).

### 6.2 Crear el ciclo

En `📆 Ciclos → 📋 Ciclos`:

1. Botón **"Crear ciclo nuevo"**.
2. Completar:
   - **Año**: por ejemplo `2026`.
   - **Cuatrimestre**: `1` o `2`.
   - **Fecha inicio / Fecha fin**: el rango calendario del cuatri.
   - **Descripción** (opcional).
   - **Versiones de plan a asignar**: seleccionar la versión de
     plan vigente de cada carrera que va a participar del ciclo.
     Por default se pre-selecciona la versión activa de cada
     carrera (o la más reciente si no hay activa).
3. **Guardar**. Se crea la fila en `CicloDB` con id
   `"{año}-{numero}C"` (por ejemplo `2026-2C`) más las filas de
   `CicloPlanVersionDB` correspondientes.

> Regla operativa clave: **asegurate de incluir todas las carreras
> relevantes**. Si olvidás una carrera, las materias exclusivas
> de esa carrera van a quedar fuera del ciclo sin ninguna
> advertencia. Es el error más común al configurar un ciclo por
> primera vez.

### 6.3 Crear los dictados

En `📆 Ciclos → 📚 Dictados`, seleccionar el ciclo recién creado
y tocar **"Crear dictados"**. Esto llama a
`create_dictados_for_ciclo`, que recorre las materias de los
planes asignados y aplica las tres puertas de decisión (§2.2):

1. Filtra las materias que están en algún `PlanEstudioDB` de las
   versiones asignadas al ciclo.
2. Para cada materia:
   - Si es **anual**, crea un `DictadoDB` con `dictado_codigo` =
     `"{materia}-{año}"` y `fin_dictado=None`. Si estamos
     creando el 2C y ya existe un dictado anual del 1C del mismo
     año, en lugar de crear uno nuevo se linkea el existente al
     2C y se completa `fin_dictado`.
   - Si es **cuatrimestral del mismo cuatrimestre que el ciclo**,
     crea un `DictadoDB` con `dictado_codigo` =
     `"{materia}-{año}-{N}C"`.
   - Si es **cuatrimestral del cuatrimestre opuesto**, aplica la
     regla de recursado:
     - Si la materia está en **múltiples carreras**, se crea igual
       (nunca se skippea).
     - Si la materia es **exclusiva de una carrera** y
       `resolve_dicta_recursado(materia, carrera)` da `False`,
       se omite (`skipped_recursado` en el resultado).
     - Si da `True`, se crea normalmente.

El resultado devuelve conteos: creados, linkeados (anuales 2C),
omitidos por recursado, saltados (ya existían), errores.

### 6.4 Revisar divergencias

Después de "Crear dictados", el panel de la tab **📚 Dictados**
muestra el listado de dictados existentes y expone dos operaciones
adicionales:

- **🔄 Sincronizar según reglas** (§4): compara el estado actual
  del ciclo contra lo que las reglas dicen hoy y muestra las tres
  secciones de divergencia con acciones fila-a-fila.
- **Toggle Virtual por dictado**: marca el dictado como virtual
  sólo en este ciclo (`DictadoDB.virtual=True`, override del
  catálogo). Sus horarios se filtran del LP pero cuentan como
  cubiertos en la validación del cronograma.

> El panel de sincronización es la herramienta para curar
> excepciones puntuales sin ensuciar el catálogo. Recomendado
> correrlo al final de la carga del ciclo para chequear que el
> estado esté alineado con las reglas vigentes.

### 6.5 Cargar el cronograma

En `📅 Cronogramas → 📤 Cargar`:

1. Seleccionar el ciclo.
2. Cargar el archivo Excel/CSV con los horarios.
3. La prevalidación contrasta el cronograma contra los dictados
   creados en el paso 6.3 y reporta:
   - **Materias esperadas cubiertas** (dictado existe y hay
     horarios en el cronograma). ✅
   - **Materias esperadas no cubiertas** (dictado existe pero no
     hay horarios cargados). ⚠️
   - **Horarios no esperados** (hay horarios cargados para una
     materia sin dictado, o materia inexistente en el ciclo). ❌
4. Resolver issues en el editor in-place o volver al panel de
   dictados si faltan crear dictados.

Las materias marcadas como virtuales (por cualquiera de los tres
niveles) cuentan como cubiertas aunque no tengan horarios: es
consistente con el hecho de que no consumen aula.

### 6.6 Generar plan, validar, activar, asignar aulas

Este tramo del flujo lo cubre `WORKFLOW.md` a partir de la § 4.
En resumen:

1. `📊 Planes → Generar plan`: deriva comisiones y horarios
   estructurados desde el cronograma.
2. `📊 Planes → Detalle`: ajustes finos por materia (comisiones,
   pesos, override de inscriptos esperados).
3. Validar el plan: cobertura de dictados, no-superposición por
   carrera-año-cuatri, partición teoría/lab consistente, camino
   de cursada intersede.
4. Correr el asignador de aulas (`🎯 Asignación`).

---

## 7. Checklist previo al asignador de aulas

Del mapa de las tres puertas se deriva un checklist operativo
antes de correr el LP:

- [ ] **Versiones de plan asignadas al ciclo**. ¿Están todas las
      carreras que deberían participar? ¿La versión de cada
      carrera es la vigente para este cuatrimestre?
- [ ] **Flags `dicta_recursado` de carreras**. ¿Los defaults
      reflejan la política actual de cada carrera?
- [ ] **Overrides `MateriaDB.dicta_recursado`**. ¿Alguno
      arrastrado de decisiones viejas? Correr
      `🔄 Sincronizar según reglas` para hacer el diff visible.
- [ ] **Modalidad virtual del catálogo (`MateriaDB.virtual`)**.
      ¿Sólo las materias efectivamente virtuales por diseño?
- [ ] **Modalidad virtual del ciclo (`DictadoDB.virtual`)**.
      ¿Algún dictado marcado virtual por un caso puntual del
      ciclo anterior que se copió sin querer? Revisar en el
      panel de dictados.
- [ ] **Cronograma cargado y prevalidado**. Todos los dictados
      no virtuales tienen horarios cargados. La prevalidación
      no reporta "no esperadas".
- [ ] **Grupos de materias configurados** (para R10 y R12 del
      LP). Ver `asignador_implementacion.md § 5`.

---

## 8. Escenarios recurrentes

### 8.1 Materia del 1C que se ofrece también al recursado en el 2C

Se maneja con la puerta 2 (regla de recursado). Dos formas:

- **Regla amplia**: la carrera tiene `dicta_recursado=True`
  (default). Al crear el ciclo 2C, `create_dictados_for_ciclo`
  crea el dictado de esa materia automáticamente.
- **Override puntual**: la carrera tiene `dicta_recursado=False`
  en general, pero para esta materia se quiere ofrecer
  recursado. Setear `MateriaDB.dicta_recursado=True` como
  override del catálogo.

### 8.2 Materia declarada anual pero que solo se dicta un cuatrimestre

No es lo habitual y la herramienta no tiene una noción de "anual
que se corta en el 1C". Si esto pasa, la vía correcta es cambiar
`MateriaDB.periodo` a `"cuatrimestral"` (probablemente el plan
de estudio ya lo indica así). Como alternativa temporaria,
borrar el `DictadoCicloDB` del 2C.

### 8.3 Recursado por Zoom (virtual sólo en un ciclo)

Setear `DictadoDB.virtual=True` desde el panel de dictados del
ciclo. Los horarios de ese dictado se filtran del LP pero
cuentan como cubiertos en el cronograma. El catálogo
(`MateriaDB.virtual`) sigue en `False`.

### 8.4 Comisión híbrida (algunos horarios presenciales, otros virtuales)

Setear `HorarioDB.virtual=True` en los horarios específicos que
son virtuales, desde el editor inline de la grilla del plan. El
resto del dictado sigue presencial.

### 8.5 Materia que se saca del plan de estudio (nueva versión)

Crear una nueva `PlanCarreraVersionDB` sin esa materia. Asignar
la nueva versión al próximo ciclo vía `CicloPlanVersionDB`. Los
ciclos existentes que siguen apuntando a la versión anterior no
se ven afectados. En el nuevo ciclo,
`create_dictados_for_ciclo` directamente no considera la materia.

### 8.6 Reset y recrear todo un ciclo

Borrar el ciclo con `borrar_ciclo` (previo backup si hace falta)
y recrearlo desde cero. El borrado en cascada limpia
`CicloPlanVersionDB`, `DictadoCicloDB` (los dictados anuales
que quedan huérfanos sólo del 1C no se borran, se mantienen),
el cronograma, el plan de cursada y las clases del ciclo.

---

## 9. Archivos y símbolos relevantes

**Modelo**:

- `src/database/models.py`: `MateriaDB.dicta_recursado`,
  `CarreraDB.dicta_recursado`, `DictadoDB.virtual`,
  `HorarioDB.virtual`, `ChangeLogDB`.

**Servicios**:

- `src/services/resolucion_jerarquica.py`: helpers puros
  `resolve_virtual`, `resolve_dicta_recursado`.
- `src/services/dictado_service.py`:
  - `create_dictados_for_ciclo`: crea dictados iniciales.
  - `sync_dictados_para_ciclo`: diff regla vs estado.
  - `_link_anual_dictado_2c`: reutilización de anuales.
  - `_should_skip_for_recursado`: aplicación de la puerta 2.
  - `borrar_dictado_de_ciclo`: baja individual.
  - `promover_a_regla`: propaga decisión del ciclo al catálogo.
- `src/services/change_log_service.py`: `emit_event`,
  `change_context`, `get_log_for_entity`, `get_recent_log`,
  `TRACKED_ENTITIES`.

**UI**:

- `app/pages/4_📆_Ciclos.py`: tab Ciclos + tab Dictados +
  integración del panel de divergencias.
- `app/pages/8_📜_Historial.py`: página del historial.
- `src/ui/divergencias_panel.py`: componente reutilizable.
- `src/ui/historial_widget.py`: componente reutilizable.

**Tests**:

- `tests/test_resolucion_jerarquica.py` (17 casos).
- `tests/test_dictado_service.py` (35 casos, incluyendo Sync,
  Promover, Borrar).
- `tests/test_change_log_service.py` (15 casos).

**Requerimientos**: `../requerimientos.md`, secciones `RF-CICLO`
y `RF-DICT`.
