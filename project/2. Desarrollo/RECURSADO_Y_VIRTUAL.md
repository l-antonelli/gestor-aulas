# Recursado, virtualidad y auditoría de cambios

Documenta el refactor completado en la Etapa 1 + Fases 2 y 3 del
trabajo sobre dictados. Los tres cambios se pensaron y ejecutaron
juntos porque comparten un mismo objetivo: **hacer explícito y
auditable el contrato entre las reglas del catálogo y el estado de
cada ciclo lectivo**.

Estado: **implementado y en uso**. La DB fue migrada de forma
destructiva (318 dictados con `activo=False` borrados; 280 clases
huérfanas quedaron con `dictado_id=NULL`).

---

## 1. Semántica "existencia = activación"

**Antes**: `DictadoDB` tenía un campo `activo: bool` (default `True`) y
un override manual `activo_override_manual`. Existía la posibilidad de
que un dictado estuviera creado en un ciclo pero marcado como inactivo
— lo cual generaba dos preguntas conceptualmente distintas ("¿existe?"
y "¿está activo?") que en la práctica eran redundantes y difíciles de
mantener sincronizadas.

**Ahora**: un dictado **existe ↔ se dicta en ese ciclo**. Punto. No
hay flag `activo`. Para "desactivar" hay que borrar la fila con
`borrar_dictado_de_ciclo` (que también nullifica `ClaseDB.dictado_id`
en las clases huérfanas para que sobrevivan). Para "reactivar" hay que
volver a crear el dictado.

**Implicancias**:
- `create_dictados_for_ciclo` ya **no crea** dictados que la regla de
  recursado dice omitir; antes los creaba con `activo=False`.
- La sincronización de dictados vs el plan es explícita
  (`sync_dictados_para_ciclo`) y siempre en modo preview + apply, sin
  auto-borrado.
- Las 3 secciones del panel de divergencias son ortogonales y
  autoexplicativas.

**Campos eliminados de `DictadoDB`**: `activo`, `activo_override_manual`.
También el parámetro `activo` del helper `update_dictado`.

### 1.1 Independencia entre ciclos

De la semántica "existencia = activación" se deriva un corolario que
conviene explicitar: **cada ciclo es una unidad operativa autónoma**.
Crear el ciclo 1C no crea ni pre-declara nada del 2C, y viceversa.
Cada corrida de `create_dictados_for_ciclo` opera sobre las materias
del plan asignado al ciclo actual y aplica la regla de recursado
sólo a ese ciclo. Los dictados **cuatrimestrales** viven cada uno
linkeado a un único ciclo; no hay propagación entre ciclos ni
efectos cruzados.

La única entidad que se comparte entre dos ciclos es el `DictadoDB`
de una materia **anual**, que se materializa como una fila única
con dos filas de `DictadoCicloDB` (una por ciclo del año lectivo).
Al crear el 1C, un dictado anual nace con `fin_dictado=None`;
cuando después se crea el 2C del mismo año, `_link_anual_dictado_2c`
reutiliza ese dictado, le agrega el bridge al 2C y completa
`fin_dictado`. Si el 2C se crea sin que exista todavía el 1C
previo, se crea un dictado anual fresco (con las dos filas de
`DictadoCicloDB` aún por completarse cuando aparezca el 1C
correspondiente).

Ninguna otra información se propaga entre ciclos: horarios,
comisiones, planes de cursada, asignaciones de aula y validaciones
son estrictamente por ciclo. Formalizado como RN19 en
`modelo-planificacion-cursada.md`.

### 1.2 Las tres puertas de decisión de un dictado

Cuando uno se pregunta "¿esta materia se dicta este ciclo? y si sí,
¿cómo?", en realidad está atravesando **tres puertas de decisión
distintas**, cada una con su propio mecanismo y su propia jerarquía.
Confundirlas es fuente de errores frecuente cuando se carga un
ciclo por primera vez, así que conviene tenerlas explícitas.

#### Puerta 1: pertenencia estructural (¿la materia está en el ciclo?)

La materia tiene que estar declarada en alguna versión de plan de
estudios que esté asignada al ciclo. Concretamente:

```text
MateriaDB → PlanEstudioDB → PlanCarreraVersionDB
                                    ↑
                            CicloPlanVersionDB
                                    ↓
                                 CicloDB
```

Si la materia no aparece en ningún `PlanEstudioDB` cuya
`plan_version_id` esté enganchada al ciclo vía `CicloPlanVersionDB`,
el ciclo ni siquiera la considera. `create_dictados_for_ciclo`
directamente no la ve.

En la práctica esto significa que **la configuración inicial más
importante de un ciclo es qué versiones de plan le asignás**. Un
error habitual: asignar la versión del plan de una carrera y
olvidarse de otra, con lo cual las materias exclusivas de esa
segunda carrera quedan fuera del ciclo sin previo aviso.

#### Puerta 2: regla de recursado (¿esta materia se dicta al recursado?)

Aplica **solo a materias cuatrimestrales cuyo cuatrimestre en el
plan es opuesto al del ciclo** (por ejemplo, una materia declarada
como "2C" en el plan cuando estamos creando un ciclo "1C"). Para
esas materias, la pregunta operativa es: "¿la facultad quiere
ofrecerla como recursado en el cuatrimestre opuesto?".

La resolución es **jerárquica materia > carrera**, implementada en
`resolve_dicta_recursado`:

- `MateriaDB.dicta_recursado` es `Optional[bool]`:
  - `None` (default) → heredar de la carrera.
  - `True` → forzar recursado, ignorando la carrera.
  - `False` → forzar NO recursado, ignorando la carrera.
- `CarreraDB.dicta_recursado` es `bool` (default `True`).

Si el valor resuelto es `True`, la materia queda en el ciclo. Si es
`False`, `_should_skip_for_recursado` la excluye y el dictado
no se crea.

**Matiz importante — materias compartidas por múltiples carreras**:
si una materia aparece en `PlanEstudioDB` con más de un
`carrera_codigo`, `_should_skip_for_recursado` **nunca la
skippea**, porque no hay una "carrera dueña" única de la cual
heredar el flag. Se dicta en ambos cuatrimestres siempre. Este
comportamiento es intencional (las materias compartidas suelen ser
de primer año y son las de mayor demanda) pero conviene saberlo
para no sorprenderse.

**Materias anuales**: la regla de recursado **no se aplica** a las
anuales. Se dictan siempre y en ambos ciclos del año lectivo.

#### Puerta 3: modalidad virtual (¿los horarios consumen aula?)

La modalidad virtual no decide si la materia se dicta o no. Decide
si los horarios de la materia **participan del LP de asignación de
aulas**. Si un horario es virtual efectivo, se filtra antes de
armar el modelo (no consume aula) pero el dictado sigue existiendo
y la validación del cronograma lo cuenta como cubierto.

La resolución es **jerárquica horario > dictado > materia**,
implementada en `resolve_virtual`:

- `HorarioDB.virtual` es `Optional[bool]` (default `None` = heredar).
- `DictadoDB.virtual` es `Optional[bool]` (default `None` = heredar).
- `MateriaDB.virtual` es `bool` (default `False`, raíz de la cadena).

Casos típicos de uso:

| Ubicación del override | Alcance | Caso de uso |
|---|---|---|
| `MateriaDB.virtual=True` | Todos los dictados y horarios de esa materia, en todos los ciclos | Materia declarada virtual por diseño en el plan (ej. asincrónicas del ciclo superior). |
| `DictadoDB.virtual=True` | Todos los horarios de una materia en un ciclo puntual | Recursado por Zoom, o modalidad puntual del ciclo sin tocar el catálogo. |
| `HorarioDB.virtual=True` | Un horario específico de una comisión | Comisión híbrida (algunas franjas presenciales, otras virtuales). |

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
La puerta 3 se evalúa **al correr el LP de asignación**, sobre los
horarios ya cargados, y su resultado es "el horario entra al modelo
o se filtra".

### 1.3 Configuraciones a revisar antes de correr el asignador

Del mapa anterior se deriva un checklist operativo. Antes de correr
el LP sobre un ciclo, conviene verificar:

1. **Versiones de plan asignadas al ciclo (`CicloPlanVersionDB`)**.
   ¿Están todas las carreras que deberían participar? ¿La versión
   asignada de cada carrera es la vigente para ese cuatrimestre?
2. **Flags `dicta_recursado` de carreras**. ¿Alguna carrera
   configurada por defecto en `True` corresponde en realidad a
   una carrera que no ofrece recursado? (o viceversa).
3. **Overrides `MateriaDB.dicta_recursado`**. ¿Alguna materia
   marcada explícitamente como `True` o `False` refleja aún la
   política actual? Suelen ser overrides puntuales que envejecen.
4. **Modalidad virtual del catálogo (`MateriaDB.virtual`)**. ¿Están
   marcadas como virtuales solo las materias que efectivamente lo
   son en el plan?
5. **Modalidad virtual del ciclo (`DictadoDB.virtual`)**. ¿Hay
   dictados marcados como virtuales de un ciclo previo que se
   arrastraron sin querer? (Los dictados nuevos heredan de la
   materia, pero uno editado a mano en un ciclo previo puede
   confundir al lector si busca por ese lado.)
6. **Cronograma cargado del ciclo**. El cronograma debe cubrir
   todos los dictados no virtuales. La prevalidación del cronograma
   contrasta contra los dictados del ciclo (`RN15`).

El detalle operativo paso-a-paso, con ejemplo concreto de carga
del 2C 2026 para demo, vive en `CICLOS_Y_DICTADOS.md`.

---

## 2. Virtualidad jerárquica (regla "el nivel más específico manda")

Un horario efectivamente virtual se resuelve en cascada:

```
HorarioDB.virtual  >  DictadoDB.virtual  >  MateriaDB.virtual
   (Optional[bool])     (Optional[bool])       (bool, raíz)
```

- `None` = heredar del padre.
- `True/False` = forzar el valor, ignorando padres.

El helper `resolve_virtual(horario, dictado, materia) -> bool` centraliza
la resolución. Los cuatro consumidores importantes (LP `build_inputs`,
generación de bloques del plan, inspector de franja, validación de
cronograma) ya lo usan.

**Uso típico**:
- Una materia catalogada como virtual (`MateriaDB.virtual=True`) → todos
  sus dictados y horarios son virtuales por default.
- Un ciclo puntual donde la materia se dicta por Zoom
  → `DictadoDB.virtual=True` (override para ese ciclo únicamente).
- Un horario específico dentro de un dictado presencial que se dicta
  virtual (ej. clase invertida un día por semana)
  → `HorarioDB.virtual=True`.

**Regla análoga para recursado**: `MateriaDB.dicta_recursado` (Optional[bool])
prevalece sobre `CarreraDB.dicta_recursado` (bool). Se resuelve con
`resolve_dicta_recursado(materia, carrera) -> bool`. Es el mismo patrón
con sólo 2 niveles.

---

## 3. Sincronización con reglas + panel de divergencias

### 3.1 La API — `sync_dictados_para_ciclo`

Compara el set de dictados existentes en un ciclo contra las materias
del plan + reglas vigentes, y devuelve un `SyncResult` con 3 listas:

- **`to_create`**: materias del plan sin dictado y la regla NO dice
  skippear. Deberían existir.
- **`to_delete`**: dictados existentes cuya materia ya no está en el
  plan del ciclo (huérfanos, típicamente aparecen tras cambiar la
  versión de plan asignada).
- **`rule_says_skip_but_exists`**: dictados existentes que la regla
  actual dice que no deberían existir. **Nunca se borran
  automáticamente** — el usuario decide si los borra o si promueve la
  decisión a regla general.

Con `apply=False` (default) sólo devuelve el diff. Con `apply=True`
aplica `to_create` y `to_delete`; `rule_says_skip_but_exists` queda
siempre para revisión manual.

### 3.2 El panel — `src/ui/divergencias_panel.py`

Componente reutilizable que renderiza el `SyncResult` en tres secciones
colapsables, con acciones por fila:

- **Sección `to_create`**:
  - `[✅ Crear]`: crea el dictado en el ciclo.
  - `[⏭️ Omitir en regla]`: setea `MateriaDB.dicta_recursado=False`
    para que ciclos futuros omitan la materia (no crea nada en el ciclo
    actual).
  - `[⏭️ Omitir TODAS en regla (N)]`: bulk con confirmación en 2 pasos.

- **Sección `to_delete`**:
  - `[🗑️ Borrar]`: borra el dictado y nullifica clases huérfanas.

- **Sección `rule_says_skip_but_exists`**:
  - `[🗑️ Borrar]`.
  - `[⬆️ Promover a regla]`: setea `MateriaDB.dicta_recursado=True`
    para que en ciclos futuros ya no sea divergencia.
  - `[⬆️ Promover TODAS a regla (N)]`: bulk con confirmación.

- Botón masivo global `[⚡ Aplicar todo]` que ejecuta
  `sync_dictados_para_ciclo(apply=True)` (respeta la sección
  "rule_says_skip_but_exists", nunca borra masivamente).

### 3.3 Promoción a regla — `promover_a_regla`

Cambia `MateriaDB.dicta_recursado` según la acción:
- `"crear-en-regla"` → True (la materia pasa a ser esperada por defecto).
- `"omitir-en-regla"` → False (la materia pasa a ser omitida por
  defecto en ciclos donde el cuatrimestre no coincide).

**No modifica** dictados existentes; sólo el catálogo. El usuario tiene
que aplicar la sincronización explícitamente después si quiere que el
ciclo actual se ajuste.

---

## 4. Auditoría — change log

### 4.1 Modelo `ChangeLogDB`

Registra cada mutación relevante con:
- `entity_type` + `entity_id` + `entity_label` (label preservado
  aunque la entidad se borre).
- `action`: `created` / `updated` / `deleted`.
- `field`, `old_value`, `new_value` (para updates; JSON serializado).
- `reason` (texto libre) + `origin` (`ui:ciclos`, `ui:validacion`,
  `script:xxx`, `auto`).
- `when` con índice para queries por rango temporal.

### 4.2 Entidades trackeadas

Whitelist explícita en `TRACKED_ENTITIES` (`change_log_service.py`):

| Entidad | Campos trackeados | Modo |
|---|---|---|
| `MateriaDB` | `virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`, `horas_laboratorio` | create/update/delete |
| `CarreraDB` | `dicta_recursado` | create/update/delete |
| `DictadoDB` | `virtual` | create/update/delete |
| `DictadoCicloDB` | (bridge, sin campos) | create/delete solamente |
| `SedeDB` | `es_default_comunes` | create/update/delete |

Las entidades de operación (`HorarioDB`, `ComisionDB`, `ClaseDB`,
etc.) **no se auditan**. Son datos de operación, no política; su
volumen generaría ruido sin valor.

### 4.3 Hooks vs eventos explícitos

- **Hooks automáticos**: capturan cualquier cambio a las entidades
  trackeadas (sin importar quién lo dispare). Corren en el
  `after_insert/update/delete` de SQLAlchemy e insertan la fila del log
  usando `connection.execute` (no la session, porque el flush ya está
  en curso).
- **Eventos explícitos**: los servicios pueden llamar `emit_event(...)`
  para agregar filas con `reason` contextualizada (útil cuando el
  cambio mecánico es idéntico al automático pero la razón importa
  más). Además existe `change_context(origin, reason)` como context
  manager que propaga la información a los hooks automáticos:

  ```python
  with change_context(
      origin="ui:ciclos",
      reason="Promoción a regla desde panel de divergencias del ciclo X",
  ):
      promover_a_regla(session, "MAT101", ciclo_id, accion="crear-en-regla")
  ```

  La mutación de `MateriaDB.dicta_recursado` queda registrada con esa
  razón sin necesidad de emitir el evento manualmente.

### 4.4 UI — página **📜 Historial**

Dos modos:
- **Feed global**: mutaciones recientes de todas las entidades
  trackeadas, con filtros por tipo y origen. Timestamp relativo
  ("hace 3 min", "hace 2 días").
- **Por entidad**: seleccionás una Materia/Carrera/Dictado/Sede y ves
  su historial completo.

El widget está en `src/ui/historial_widget.py` y se puede reutilizar
como pestaña dentro de páginas individuales si se necesita más adelante.

---

## 5. Flujo de trabajo típico

Un cuatrimestre nuevo:

1. **Se crea el ciclo** (`CicloDB`) y se le asignan las versiones de
   plan que aplican.
2. **Se corre `create_dictados_for_ciclo`** desde el botón de Ciclos.
   Se crean todos los dictados que la regla actual autoriza (los
   cuatrimestrales de cuatri opuesto sin recursado no se crean).
3. **Se carga el cronograma** de las materias (Excel, upload).
4. **Se corre la validación del cronograma**: aparecen extras
   (materias en el cronograma sin dictado) y faltantes (dictados sin
   horarios).
5. **Se resuelven los extras** desde el panel de validación: bulk
   `🟢 Activar` (crea el dictado como presencial) o
   `🌐 Activar y marcar virtual` (crea el dictado con
   `DictadoDB.virtual=True`). Cada acción queda en el change log con
   `origin=ui:validacion` y razón "Aceptar materia del cronograma...".
6. **Si aparecieron patrones repetidos** (ej. "la carrera X siempre
   dicta este recursado"), ir a la página de Ciclos → panel de
   divergencias → `[⬆️ Promover a regla]`. Con esto en el próximo
   ciclo ya no aparece como divergencia.

Un cambio de política a mitad de ciclo:

1. **Se edita `CarreraDB.dicta_recursado` o `MateriaDB.dicta_recursado`**
   desde la UI. El cambio queda en el change log automáticamente.
2. **Se abre el panel de Ciclos → Sincronizar**. Aparecen las
   divergencias nuevas (dictados que la regla nueva dice omitir).
3. **Se decide caso por caso**: borrar el dictado (si la política nueva
   es real) o dejarlo (si es una excepción vigente para este ciclo).

---

## 6. Archivos y símbolos relevantes

**Modelo**:
- `src/database/models.py`: `MateriaDB.dicta_recursado`,
  `CarreraDB.dicta_recursado`, `DictadoDB.virtual`,
  `HorarioDB.virtual`, `ChangeLogDB`.

**Servicios**:
- `src/services/resolucion_jerarquica.py`: helpers puros
  `resolve_virtual`, `resolve_dicta_recursado`.
- `src/services/dictado_service.py`: `create_dictados_for_ciclo`,
  `sync_dictados_para_ciclo`, `aceptar_materias_en_ciclo`,
  `borrar_dictado_de_ciclo`, `promover_a_regla`.
- `src/services/change_log_service.py`: `emit_event`,
  `change_context`, `get_log_for_entity`, `get_recent_log`,
  `TRACKED_ENTITIES`.

**UI**:
- `app/pages/4_📆_Ciclos.py`: integración del panel de divergencias.
- `app/pages/8_📜_Historial.py`: página del historial.
- `src/ui/divergencias_panel.py`: componente reutilizable.
- `src/ui/historial_widget.py`: componente reutilizable.

**Tests**:
- `tests/test_resolucion_jerarquica.py` (17 casos).
- `tests/test_dictado_service.py` (35 casos, incluyendo Sync/Promover/Borrar).
- `tests/test_change_log_service.py` (15 casos).
