# Auditoría — Catálogo Maestro (Materias, Aulas, Carreras)

Fuente de verdad: código en `app/pages/`, `src/services/`, `src/ui/`,
`src/database/models.py`. Fecha del relevamiento: 2026-07-30.

Este documento describe **qué hace REALMENTE la aplicación**, tab por tab,
para las tres entidades base del catálogo. Después se van a comparar los
hallazgos con la documentación existente y usar como insumo para el manual
de usuario.

---

## 1. Walkthrough real de cada módulo

### 1.1 Página `📚 Materias` (`app/pages/1_📚_Materias.py`)

**Propósito**. Gestionar el catálogo de asignaturas académicas. Es donde
se dan de alta las materias del maestro, se define su carga horaria y su
período (anual/cuatrimestral), se asocian a los planes de estudio de
distintas carreras y se marcan qué laboratorios son compatibles con cada
una.

**Entidades que maneja**:

- `MateriaDB` (tabla `materias`, PK = `codigo`).
- `PlanEstudioDB` (tabla `plan_estudio`) — link M:N Materia ↔ Carrera,
  ubicado dentro de una `PlanCarreraVersionDB`, con año y cuatrimestre.
- `MateriaLaboratorioDB` (tabla `materia_laboratorio`) — link M:N Materia
  ↔ Aula de tipo laboratorio.

**Estructura de la página**.

Al abrir la página, arriba de todo hay un expander (`collapsed=False` al
inicio) titulado **"📊 Estado de Completitud de Carreras"** que muestra:

- Cuatro métricas globales: Total Carreras, Completas, Incompletas, Sin
  Cantidad Definida (con % debajo).
- Un panel de advertencias listando carreras sin `cantidad_materias`
  definida y carreras incompletas (con barra de progreso individual).
- Este widget aparece acá porque cargar materias es lo que "completa" una
  carrera; sirve como recordatorio contextual.

Luego, tres tabs.

#### Tab `📋 Lista`

- Muestra un `text_input` para filtrar por código o nombre (case-insensitive,
  substring).
- Lista **todas** las materias (`limit=10000`, en la práctica no pagina).
- Cada materia se muestra en un expander con:
  - Columna izquierda: Código, Nombre, Período, Horas/Semana, Hs Teoría
    y Hs Laboratorio (si hay alguna cargada).
  - Columna derecha: Cupo, Virtual (Sí/No), Optativa (Sí/No), lista de
    Carreras asociadas (deduplicadas across versiones) y cantidad de
    Laboratorios compatibles.
  - Dos botones: **Editar** y **Eliminar**.

**Modo Edición** (cuando se apretó "Editar"):

- Sub-tabs: `Datos Básicos`, `Carreras`, `Laboratorios`.
- **Datos Básicos**: formulario con Código (disabled, no se cambia),
  Nombre, Período, Cupo, Hs/Sem, Hs Teoría, Hs Laboratorio, Virtual,
  Optativa. Además un `selectbox` de tres estados "Recursado (excepción
  para esta materia)" con opciones "Según Carrera" / "Sí (forzar)" /
  "No (forzar)", que edita `MateriaDB.dicta_recursado` (override respecto
  del flag de la carrera).
- **Carreras**: `data_editor` con las asociaciones actuales (columnas:
  Carrera, Nombre Carrera, Plan, Año, Cuatrimestre). Solo Año y
  Cuatrimestre son editables inline. Un botón "Guardar Cambios" persiste
  los cambios de año/cuatri. Debajo hay un multiselect "Desasociar
  Carrera" (por par carrera + plan) y un form "Asociar Nueva Carrera"
  (selectbox de carrera disponible + año + cuatri; usa la versión de
  plan más reciente de esa carrera). Si la materia es **anual**, el
  cuatri se fuerza a `"anual"` y el campo aparece disabled.
- **Laboratorios**: multiselect de aulas de tipo `laboratorio` (mostradas
  como `codigo_aula — nombre (sede)`). Cuenta las diferencias contra el
  estado actual y muestra "N para agregar, M para quitar" con un botón
  "Guardar" que aplica las altas y bajas en `MateriaLaboratorioDB`. Si
  no hay laboratorios cargados, muestra un `st.info` explicando que hay
  que crear aulas de tipo `laboratorio` primero.
- Al pie: botón "Volver a la lista".

**Modo Eliminación** (cuando se apretó "Eliminar"):

- Pantalla de confirmación con `st.warning("Esta accion no se puede
  deshacer.")`.
- Dos botones: **Confirmar** y **Cancelar**.
- No hay chequeo de dependencias antes de borrar (a diferencia de
  Carreras). Si la materia tiene planes de estudio, dictados, comisiones,
  etc. el borrado puede fallar por foreign keys de SQL o dejar registros
  huérfanos. **Ver Gotchas**.

#### Tab `➕ Crear`

- Formulario Streamlit (`st.form`) con todos los campos de `Materia`:
  Código, Nombre, Período, Cupo, Hs/Sem, Hs Teoría, Hs Laboratorio,
  Virtual, Optativa, Recursado.
- Sección "Asignación de Carreras": **obligatoria — al menos una**. Se
  usa un `st.data_editor` con filas dinámicas (`num_rows="dynamic"`) y
  columnas Carrera (selectbox `CODIGO - Nombre`), Año (1–6), Cuatrimestre
  (1C/2C — si la materia es anual queda fijo en "Anual" y disabled) y
  Plan (selectbox con los nombres de planes de estudio disponibles;
  default = plan más reciente).
- El botón **Crear Materia** dispara la validación:
  - Si no hay carreras seleccionadas → error "Debe asignar al menos una
    carrera".
  - Si `Hs Teoría + Hs Lab ≠ Hs/Sem` (y `Hs/Sem` está seteado) → warning
    y no crea la materia.
  - Si la validación pasa, crea la `MateriaDB` y para cada fila del
    data_editor resuelve el `plan_version_id` (por `carrera_codigo +
    plan_nombre`, ordenado por fecha desc) y crea la `PlanEstudioDB`
    correspondiente.

#### Tab `🔍 Buscar`

- Un `text_input` "Buscar por código o nombre".
- Muestra resultados como texto plano `📚 codigo - nombre`. **No hay**
  botones de acción. Es una vista de solo lectura, prácticamente
  redundante con el filtro del tab Lista.

**Validaciones y reglas**.

- `codigo` no puede ser vacío (validador Pydantic).
- `nombre` mínimo 1 carácter.
- `cupo > 0` si se define; `horas_semanales > 0`; `horas_teoria ≥ 0`,
  `horas_laboratorio ≥ 0`.
- `periodo` restringido a `"anual"` o `"cuatrimestral"`.
- Al crear con carreras, mínimo 1 carrera obligatoria.
- Validación soft (warning, no bloqueante en edición, sí bloqueante en
  creación): `hteo + hlab == hsem` si se cargan las tres.
- No hay validación de duplicidad de nombre (solo el `codigo` es único).

**Relaciones con otros módulos**.

- Cambios en `MateriaDB` alimentan **Ciclos → Dictados**, **Cronogramas**
  (via `ScheduleEntryDB.codigo_materia`), **Planes** y el LP de
  asignación de aulas.
- El flag `virtual` en la materia se hereda a `DictadoDB` y `HorarioDB`
  como default (jerarquía en 3 niveles con override — ver
  `RECURSADO_Y_VIRTUAL.md`).
- El flag `optativa` afecta la validación de cobertura (toggles "excluir
  optativas") y el conteo de `cantidad_materias` de una carrera (solo se
  cuentan las obligatorias).
- El flag `dicta_recursado` (override) modifica la generación de
  dictados en la página de Ciclos.
- La asociación con laboratorios (`MateriaLaboratorioDB`) es consumida
  por el LP de asignación cuando el `tipo_clase` del horario es
  `"laboratorio"`.

**Audit log**. `MateriaDB` está en `TRACKED_ENTITIES` de
`change_log_service` — se auditan altas/bajas y cambios de los campos
`virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`,
`horas_laboratorio`. Se pueden ver en la página **📜 Historial**.

**Carga inicial**. Vía `python -m scripts.load_initial_data --reset`.
Lee `data/input/Carreras/Maestro materias.xlsx` con columnas
`codigo_plan`, `nombre`, `horas`, `codigo_guarani`, `periodo`, `electiva`.
Genera `MateriaDB` con `cupo=None`, `horas_teoria=None`,
`horas_laboratorio=None` (sólo se carga `horas_semanales`). El
`codigo_guarani` es un campo persistido en el modelo pero **no editable
desde la UI**.

---

### 1.2 Página `🏛️ Aulas y Sedes` (`app/pages/2_🏛️_Aulas.py`)

**Propósito**. CRUD de aulas y de sedes en la misma página. Las sedes son
una entidad transversal referenciada tanto por las aulas (cada aula
pertenece a una sede) como por las carreras (una carrera puede tener
sedes habilitadas — R10 del LP).

**Entidades que maneja**:

- `AulaDB` (tabla `aulas`, PK = UUID `id`, código display en `codigo_aula`).
- `SedeDB` (tabla `sedes`, PK = UUID `id`, nombre único).
- `MateriaLaboratorioDB` (M:N con Materias) — cuando el aula es un
  laboratorio.

**Estructura**. Cuatro tabs.

#### Tab `📋 Listado`

- Filtro por sede (`Todas` + una entrada por sede existente).
- Tabla (`st.dataframe`) con columnas: Código, Sede, Nombre, Capacidad,
  Tipo.
- Contador de aulas al pie.
- Sin acciones en la tabla — es solo lectura.

#### Tab `➕ Crear`

Campos:

- Nombre del aula (obligatorio).
- Sede (selectbox obligatorio; si no hay ninguna sede muestra warning
  "Creá al menos una sede en la pestaña '📍 Sedes'").
- Código (display, opcional). Si el usuario lo deja vacío, se autoderiva
  como `{sede_nombre}-{nombre}` con espacios reemplazados por guiones. El
  placeholder muestra en tiempo real cómo quedaría.
- Capacidad (mínimo 1, default 30).
- Tipo: selectbox con opciones `teorica`, `practica`, `laboratorio`,
  `anfiteatro` (default `teorica`).
- Descripción (textarea opcional).

Al apretar **Crear aula** valida unicidad global de `codigo_aula`. Si
choca con uno existente, muestra error y no crea.

#### Tab `👁️ Ver detalle`

- Selectbox para elegir un aula (formato
  `codigo_aula — nombre (sede_nombre)`).
- Formulario de edición inline con las mismas columnas del alta:
  Nombre, Sede, Código (editable), Capacidad, Tipo, Descripción.
- Detecta si hubo cambios y muestra "Sin cambios" si no. El botón
  "Guardar cambios" recalcula la unicidad del código si cambió.
- Cambiar de/a tipo `laboratorio` **no borra** las relaciones
  `MateriaLaboratorioDB` — el aviso lo dice explícitamente.

Debajo del formulario, un expander `🗑️ Borrar aula`:

- Si el aula tiene clases asignadas (`ClaseDB.aula_id == aula.id`),
  bloquea con error "No se puede borrar: el aula tiene clases asignadas.
  Reasignalas primero." No hay verificación de horarios de patrón
  semanal ni de `MateriaLaboratorioDB`, sólo `ClaseDB`.
- Si no tiene clases, borra la fila directamente.

**Si el aula es tipo `laboratorio`** aparece una sección adicional
"Materias que usan este laboratorio" con el mismo widget de multiselect
que en la página de Materias, pero al revés (elegir qué materias usan
este lab).

#### Tab `📍 Sedes`

- Tabla `st.dataframe` con: Sede, Aulas (conteo), Default comunes (icono
  🏛️ Sí / — ).
- Expander **"🏛️ Sede por defecto para materias comunes"** (colapsado
  por default). Permite elegir una sola sede como "default de comunes"
  o desactivarlo con `— ninguna —`. Sólo puede haber una a la vez —
  el service `set_sede_default_comunes` desactiva automáticamente la
  anterior.
- Expander **"➕ Crear sede"**: nombre único obligatorio. Si ya existe
  otra sede con el mismo nombre, error.
- Expander **"✏️ Renombrar / borrar sede"**: elegir sede + input de
  nuevo nombre. Dos acciones:
  - **Renombrar**: valida colisión de nombre.
  - **Borrar**: deshabilitado si la sede tiene aulas asociadas (muestra
    tooltip "No se puede borrar: tiene N aula(s) asociada(s)."). Si no
    tiene aulas, la borra. Adicionalmente, el service `SedeService.delete`
    hace la misma verificación en el back — si por alguna razón el
    front no lo bloquea, el servicio tira `ValueError`.
- Expander **"🔗 Fusionar sedes"**: elegir sede origen y sede destino
  (necesita ≥ 2 sedes). Reasigna todas las aulas de origen a destino y
  borra la origen. Útil cuando se creó una sede con el nombre mal
  escrito y hay que consolidarla.

**Validaciones y reglas**.

- `codigo_aula` único globalmente (validado en creación y en edición).
- `capacidad > 0`.
- `sede_id` obligatorio.
- `nombre` mínimo 1 carácter.
- `tipo` restringido a los cuatro valores enumerados.
- `SedeDB.nombre` único (validado en alta y renombre).
- Borrado de sede: bloqueado si tiene aulas (validación en front + back).
- Borrado de aula: bloqueado si tiene clases (`ClaseDB.aula_id`).
- Fusión: origen y destino distintos.

**Relaciones con otros módulos**.

- Aulas son el "recurso" que el LP de asignación asigna a los `HorarioDB`
  del patrón semanal. Un cambio de capacidad o tipo altera qué
  asignaciones son factibles.
- Sedes gobiernan la restricción R10 del LP:
  - Materias **exclusivas** (una sola carrera) → sólo aulas de las
    sedes habilitadas para esa carrera (`CarreraSedeDB`). Si la carrera
    no tiene sedes configuradas, se asume "todas las sedes" (fallback).
  - Materias **comunes** (≥ 2 carreras) → sólo la sede marcada como
    `es_default_comunes=True`. Si no hay ninguna sede default, "todas las
    sedes".
  - Excepción: si una comisión tiene `carrera_asignada` seteado
    (RF-LP-15), la restricción se resuelve por esa carrera puntual en
    lugar de por la materia.
- Cambiar el flag `es_default_comunes` está trackeado en el audit log
  (`SedeDB` en `TRACKED_ENTITIES`).

**Carga inicial**. `load_aulas` crea una sede `"Pellegrini"` por default
(si no existe) y carga las aulas del Excel `data/input/aulas/aulas.xlsx`
con `sede_id` apuntando a Pellegrini y `tipo="teorica"`. El
`codigo_aula` se autoderiva. Aulas de otras sedes (Zeballos, Beltrán, etc.)
se cargan a mano desde la UI. Las sedes también se crean desde la UI.

**Audit log**. Sólo `SedeDB.es_default_comunes` se trackea. Cambios en
`AulaDB` **no están en `TRACKED_ENTITIES`** (no aparecen en el
Historial).

---

### 1.3 Página `🎓 Carreras` (`app/pages/3_🎓_Carreras.py`)

**Propósito**. Definir las carreras universitarias del maestro y su
plan de estudios (qué materias las componen, en qué año/cuatri).

**Entidades que maneja**:

- `CarreraDB` (tabla `carreras`, PK = `codigo`).
- `PlanCarreraVersionDB` (tabla `plan_carrera_version`) — versiones del
  plan de estudios de una carrera.
- `PlanEstudioDB` (M:N Materia ↔ Carrera dentro de una versión).
- `CarreraSedeDB` (M:N Carrera ↔ Sede — sedes habilitadas).

**Estructura**. Tres tabs.

#### Tab `📋 Lista`

- Lista de carreras, cada una en un expander `🎓 codigo - nombre`.
- Muestra Código, Nombre, Título Otorgado, Duración (años), Cantidad de
  Materias, Dicta recursado (Sí/No) y un widget de completitud (barra
  de progreso `materias asignadas / cantidad_esperada`).
- Sección **"🏛️ Sedes habilitadas"**: multiselect con las sedes
  disponibles. Estas son las sedes admisibles para las **materias
  exclusivas** de la carrera (R10 del LP). Si no se selecciona ninguna,
  el sistema asume "todas las sedes". Aparece un botón "💾 Guardar
  sedes" cuando hay diferencias respecto del estado actual.
- Dos botones: **✏️ Editar** y **🗑️ Eliminar**.

**Modo Edición**: formulario con Nombre, Título Otorgado, Duración
(años), Cantidad de Materias, Dicta recursado. Código queda disabled.

**Modo Eliminación**: pantalla de confirmación con warning. **Chequea
si la carrera tiene materias asociadas y muestra error visible** ("No
se puede eliminar: la carrera tiene N materia(s) asociada(s). Primero
debe desasociar todas las materias de esta carrera."). Además, el
service `CarreraService.delete` bloquea si existen `PlanCarreraVersionDB`
(tira `ValueError` con el mensaje "Cannot delete Carrera... N plan
version(s) exist"). El botón "🗑️ Confirmar Eliminación" está siempre
habilitado — si igual se aprieta con materias asociadas, el service
tira el error.

#### Tab `➕ Crear`

Formulario con: Código, Nombre, Título Otorgado, Duración (años),
Cantidad de Materias (opcional), Dicta recursado. Botón "Crear Carrera".

- Nótese: **crear una carrera desde acá NO le crea automáticamente una
  `PlanCarreraVersionDB`**. Sin plan version no se pueden asociar
  materias (los helpers de materia_carrera_editor buscan la versión más
  reciente y muestran error si no hay). El script de carga inicial sí
  crea la versión "Plan Original", pero la UI de creación manual no lo
  hace. **Ver Gotchas.**

#### Tab `📚 Materias por Carrera` (Planes de Estudio)

- Selectbox de carrera.
- **Selector de versión de plan** + botón "Nueva Version" que abre un
  form (nombre, descripción, checkbox "Copiar materias de la version
  actual" con default `True`).
- Un expander "Editar version" permite modificar nombre y descripción
  de la versión seleccionada.
- Widget de completitud (progress bar) para la carrera + versión.
- Selector de **año del plan** (1 a 6).
- Tres columnas paralelas, una por período: Anuales, 1er Cuatrimestre,
  2do Cuatrimestre. Cada una muestra las materias asociadas al año +
  período seleccionado, con:
  - Código y nombre de la materia.
  - Botón "X" (desasociar). Ejecuta `carrera_service.remove_materia`
    sobre esa versión de plan.
  - Debajo, sección "Asociar Materia": selectbox de materias disponibles
    (filtradas por período de la materia y excluyendo las ya
    asociadas), + botón "Asociar". Ejecuta `carrera_service.add_materia`
    con el año y cuatri correspondientes.

**Validaciones y reglas**.

- `codigo` no puede estar vacío.
- `nombre` mínimo 1 carácter.
- `duracion_anios ≥ 1`.
- `cantidad_materias ≥ 1` si se define (opcional).
- Delete bloqueado si hay `PlanCarreraVersionDB` (service) o si hay
  materias asociadas (UI check).
- Al crear una versión de plan nueva con "Copiar materias", se
  duplican los `PlanEstudioDB` del origen (mismos año, cuatri,
  correlativas, optativa).

**Relaciones con otros módulos**.

- **Materias** referencian carreras vía `PlanEstudioDB`.
- **Ciclos** consumen `PlanCarreraVersionDB` vía `CicloPlanVersionDB`
  para saber qué materias se ofrecen en el ciclo.
- **Cronogramas / Planes de cursada** derivan su set esperado de
  materias del par (ciclo, plan version por carrera).
- El flag `dicta_recursado` afecta la generación de dictados: si es
  `False`, materias exclusivas del cuatrimestre opuesto no generan
  `DictadoDB`. La materia puede sobreescribirlo con su propio
  `dicta_recursado`.
- El widget de completitud usa la última versión de plan de cada
  carrera y cuenta sólo materias obligatorias (`optativa=False`).

**Audit log**. `CarreraDB.dicta_recursado` está trackeado. Otros
campos y las versiones de plan no.

**Carga inicial**. `load_carreras_and_planes` crea `CarreraDB` con
`nombre = codigo` como placeholder (después `apply_carreras_metadata` los
completa desde `carreras_metadata.json`), crea una versión "Plan
Original" para cada una, y luego popula `PlanEstudioDB` desde
`Maestro planes.xlsx`.

---

## 2. Gotchas y cosas no obvias

1. **Diferencia crucial "Materia" vs "asociación Materia-Carrera"**.
   `MateriaDB` es el maestro (código, nombre, horas, virtual/optativa,
   etc.). La misma materia puede aparecer en múltiples carreras —
   compartida ("común") — con distinto año o cuatrimestre en cada
   plan (`PlanEstudioDB.anio_plan`, `cuatrimestre_plan`). Editar la
   materia afecta a todas las carreras que la comparten; para cambiar
   el año/cuatri hay que editarlo por asociación.

2. **"Materia común" vs "exclusiva"** es una distinción implícita:
   una materia es común si aparece en ≥ 2 carreras distintas (no hay
   flag en la tabla, se calcula on-the-fly). Esta distinción define
   qué sede admite el LP para asignarle aula (default de comunes vs
   sedes de la carrera).

3. **Cantidad de materias esperadas** en `CarreraDB.cantidad_materias`
   es opcional. Si queda en `NULL`, el widget de completitud dice
   "Cantidad no definida" y no muestra progreso. Se cuenta sólo
   materias obligatorias (`optativa=False`) en la última versión del
   plan.

4. **Al crear una carrera desde la UI no se crea automáticamente una
   `PlanCarreraVersionDB`**. Hasta que no exista al menos una versión
   de plan, no se pueden asociar materias (los formularios muestran
   error "No se encontró plan de estudios para la carrera 'X'"). Hay
   que ir al tab **📚 Materias por Carrera** y crear una versión con
   "Nueva Version". **Esto no está documentado.**

5. **Eliminar una materia no verifica dependencias** (a diferencia
   de carrera y sede). Si la materia tiene `PlanEstudioDB`,
   `MateriaLaboratorioDB`, `DictadoDB`, `ComisionDB`, `HorarioDB` o
   `InscripcionHistoricaDB`, el borrado va a fallar en SQL con un
   `IntegrityError` visible como "Error: FOREIGN KEY constraint
   failed" o similar. No hay soft-delete: existe la columna
   `MateriaDB.active` pero la UI no la expone como toggle.

6. **Eliminar una carrera** está gobernada por dos checks: la UI
   verifica materias asociadas (`PlanEstudioDB`) y el servicio
   verifica `PlanCarreraVersionDB`. La versión del plan hay que
   borrarla desde SQL directo — la UI no ofrece "borrar plan version".

7. **Eliminar una sede**: hay dos verificaciones redundantes (front
   deshabilita el botón, back tira `ValueError`). La forma correcta
   de "eliminar" una sede con aulas es **Fusionar** con otra sede,
   que reasigna las aulas al destino y borra la origen.

8. **Sede por defecto para comunes** es única globalmente. Si activás
   una nueva, la anterior se desactiva sola sin aviso. Podés dejar
   "— ninguna —" y el LP asumirá "todas las sedes" para las materias
   comunes.

9. **Sedes habilitadas por carrera vacío = "todas las sedes"**, no
   "ninguna". Esto puede sorprender: si nunca configuraste sedes,
   el LP no restringe nada; recién cuando marcás al menos una, la
   restricción se activa. Está aclarado en el caption pero es fácil
   pasarlo por alto.

10. **Cambiar el tipo de un aula de `laboratorio` a otro tipo NO borra
    las asociaciones `MateriaLaboratorioDB`**. Aparece un caption
    diciéndolo, pero la relación queda "colgando" — probablemente
    inofensiva porque los queries filtran por `tipo == "laboratorio"`
    antes de mostrar labs disponibles.

11. **Autoderivación del código del aula**: si el usuario deja vacío
    el campo Código en la creación, se genera como
    `{Sede}-{Nombre}` con espacios reemplazados por guiones. Ej:
    `Pellegrini` + `AULA 01` → `Pellegrini-AULA-01`. Si después la sede
    se renombra o se fusiona, el código del aula **no se actualiza**
    automáticamente, queda con el nombre viejo pegado en el string.

12. **Recursado por materia (override)** es un selector de tres
    estados en la edición de materia: "Según Carrera" / "Sí (forzar)" /
    "No (forzar)". Persiste como `NULL` / `True` / `False` en
    `MateriaDB.dicta_recursado`. Este override no se muestra en la
    vista de Lista — hay que entrar a Editar para verlo. Afecta la
    generación de dictados en la página de Ciclos.

13. **Plan versions y "Copiar materias"**: al crear una versión nueva
    con la opción activada (default), se duplican TODOS los
    `PlanEstudioDB` de la versión seleccionada, incluyendo
    correlativas y flag `optativa`. Es útil para hacer una variante
    del plan, pero cambia dónde apuntan las nuevas asociaciones que
    se hagan (van a la versión nueva, no a la vieja).

14. **La página de Materias tiene un tab "🔍 Buscar" que es
    prácticamente redundante** con el filtro del tab Lista. La única
    diferencia es que no ofrece Editar/Eliminar. Probablemente sea
    legacy — no tiene mucha razón de ser.

15. **Auditoría selectiva**: el audit log (`ChangeLogDB`) sólo trackea
    cambios en algunos campos de Materia, Carrera y Sede. Aula NO
    se audita en absoluto, y de Carrera sólo el flag `dicta_recursado`.
    Ver `TRACKED_ENTITIES` en `change_log_service.py`. Esto significa
    que si alguien renombra una carrera, cambia la capacidad de un
    aula o modifica el nombre de una materia, **no queda registro** en
    el Historial.

16. **`codigo_guarani` de una materia** existe en el modelo y se
    carga desde el Excel inicial pero **no se edita ni se muestra en
    la UI** de materias. Es un campo silencioso.

17. **En el editor de materia, el "override de recursado"**
    (`_rec_value`) siempre se envía al `update` como parte del
    `form_data`, incluso si el usuario no lo tocó. La lógica reconstruye
    los 3 estados desde el valor default y los aplica según el índice
    del selectbox — así que "Según Carrera" siempre setea `None`.

---

## 3. Errores/warnings que el usuario puede ver

### Página Materias

| Texto | Cuándo se dispara | Qué significa | Cómo resolverlo |
|---|---|---|---|
| "Materia '{codigo}' no encontrada" | Al abrir el editor con un código que ya no existe | Alguien borró la materia mientras estaba en edición | Volver a la lista |
| "Debe asignar al menos una carrera" | Al crear una materia sin filas en el data_editor de carreras | Regla de negocio: toda materia debe pertenecer a al menos una carrera | Agregar al menos una fila en el data_editor |
| Warning: "Hs Teoría (X) + Hs Lab (Y) = Z ≠ Hs/Sem (W). Corregí antes de guardar." | Al crear/editar una materia si la suma no cuadra | Inconsistencia en las horas | Ajustar los tres campos |
| "No se pudo actualizar" | La actualización del CRUD devolvió `None` | Fallo silencioso al hacer update | Reintentar; ver logs |
| "No se pudo eliminar" | El delete devolvió `False` | La materia no se encontró para borrar | Refrescar y reintentar |
| "Error: FOREIGN KEY constraint failed" (aprox) | Al intentar borrar una materia con dependencias | Hay planes/dictados/comisiones que la referencian | Desasociar primero (no hay una herramienta para esto en la UI) |
| "No hay carreras disponibles. Cree una carrera primero." | Al abrir Crear Materia sin carreras cargadas | El maestro está vacío | Ir a Carreras → Crear |
| "No hay aulas de tipo 'laboratorio' cargadas en la base de datos." | Al editar Laboratorios de una materia sin labs cargados | No hay aulas con `tipo="laboratorio"` | Ir a Aulas → Crear con tipo laboratorio |
| "No se encontro plan de estudios para la carrera 'X'" | Al asociar una carrera sin `PlanCarreraVersionDB` | La carrera fue creada sin plan version | Crear "Nueva Version" desde la página de Carreras |

### Página Aulas y Sedes

| Texto | Cuándo | Qué significa | Cómo resolverlo |
|---|---|---|---|
| "No hay sedes cargadas. Creá al menos una sede en la pestaña '📍 Sedes' antes de crear un aula." | Al abrir Crear Aula sin sedes | Falta la sede | Ir al tab Sedes → Crear |
| "Ya existe un aula con código '{codigo}'. Editalo manualmente para usar otro." | Al crear un aula cuyo código autogenerado ya existe | Colisión de código | Editar el campo Código manualmente |
| "Ya existe otra aula con código '{codigo}'." | Al editar un aula cambiando el código a uno ya usado | Colisión | Elegir otro código |
| "No hay sedes para asignar." | Interno; sólo si desaparecen las sedes durante la edición | Estado inconsistente | Refrescar |
| "Aula no encontrada." | Interno; el aula seleccionada se borró | Estado inconsistente | Refrescar |
| "No se puede borrar: el aula tiene clases asignadas. Reasignalas primero." | Al borrar un aula con `ClaseDB.aula_id` apuntando | Bloqueo por integridad | Reasignar clases desde el panel de asignación del plan |
| "Ya existe la sede '{nombre}'." | Al crear/renombrar sede con nombre duplicado | Colisión | Elegir otro nombre |
| "No se puede borrar la sede '...': tiene aulas asociadas. Reasignalas primero o usá 'fusionar' para moverlas a otra sede." | Al borrar sede con aulas | Bloqueo | Fusionar con otra sede |
| "La sede origen y la destino son la misma." | Al fusionar la misma sede consigo | Error de UX | Elegir sedes distintas |
| "Sede '{id}' no encontrada." | En el service, si la sede default de comunes se referencia con un id inexistente | Estado inconsistente | Refrescar |

### Página Carreras

| Texto | Cuándo | Qué significa | Cómo resolverlo |
|---|---|---|---|
| "Carrera con código '{codigo}' no encontrada" | Al editar una carrera que ya no existe | Alguien la borró | Volver a la lista |
| "No se pudo actualizar la carrera" | Update devolvió None | Fallo silencioso | Reintentar |
| "No se puede eliminar: la carrera tiene N materia(s) asociada(s). Primero debe desasociar todas las materias de esta carrera." | Al intentar borrar una carrera con materias | Bloqueo (chequeo UI) | Ir al tab Planes y desasociar todas |
| "Cannot delete Carrera 'X': N plan version(s) exist. Delete plan versions first." | Del service, si igual se aprieta Confirmar | Bloqueo (chequeo servicio) | Borrar las versiones del plan (hoy: SQL directo) |
| "Esta carrera no tiene versiones de plan de estudio." | Al abrir Planes de Estudio de una carrera sin versión | La carrera no tiene `PlanCarreraVersionDB` | Crear una con "Nueva Version" |
| "El nombre no puede estar vacio" | Al crear nueva versión sin nombre | Validación | Escribir un nombre |
| "No se encontro plan de estudios para la carrera 'X'" | En creación de materia si la carrera elegida no tiene versión | Mismo caso que arriba | Crear versión primero |

### Del sistema (excepciones traducidas por Streamlit)

Cualquier `raise ValueError` de los services (delete de sede con aulas,
merge inválido, delete de carrera con versiones) se muestra como
`st.error(str(e))`. Los errores de validación Pydantic aparecen como
"Error de validación en {model}: {mensaje}".

---

## 4. Discrepancias con la documentación

Comparación con `project/2. Desarrollo/WORKFLOW.md` (versión del
2026-07-12) y otros docs relevantes.

1. **Página de Aulas en el mapa de páginas**. `WORKFLOW.md` sección 10
   dice "CRUD Aulas" para la página 2, pero en realidad se llama
   `🏛️ Aulas y Sedes` y el CRUD de sedes es un tab de primer nivel
   con features no triviales (default de comunes, fusión, renombre).
   La sección 1 (Carga inicial) sí menciona la sede Pellegrini y
   remite a la página `🏛️ Aulas y Sedes` para el resto — hay
   inconsistencia interna en el mismo doc.

2. **Página de Materias en el mapa de páginas**. Dice "CRUD Materias /
   Laboratorios", lo cual es correcto, pero no menciona:
   - El widget de completitud de carreras que aparece arriba de todo.
   - El editor de Carreras asociadas (año, cuatri, plan version)
     dentro del edit de materia.
   - El tab "🔍 Buscar" (redundante — quizás por eso no lo mencionan).

3. **Tab de Sedes no está en el WORKFLOW.md**. Todo lo referente a
   `es_default_comunes`, `CarreraSedeDB` y la fusión de sedes queda
   sin cubrir en el workflow principal — sólo aparece de refilón en
   `asignacion-aulas-LP.md` bajo la restricción R10.

4. **`WORKFLOW.md` menciona la página `7_📝_Inscriptos.py`** pero
   el archivo real es `7_📈_Inscriptos.py` (icono diferente). No es
   una discrepancia grave pero es un error de referencia.

5. **La página 8 (`8_📜_Historial.py`) no aparece en el mapa**. El
   audit log tiene una página dedicada que WORKFLOW.md no lista.

6. **Sección 6 del WORKFLOW menciona `plan_grilla_editor`** y hace
   referencia a comisiones con `carrera_asignada` sin explicar bien
   dónde se setea. En la página de Carreras hay que configurar
   `CarreraSedeDB`, pero el `carrera_asignada` de una comisión se
   setea en otro lado (probablemente en el editor de comisiones del
   plan) — el vínculo entre ambas cosas no se explica.

7. **`WORKFLOW.md` no menciona el override `dicta_recursado` a nivel
   materia** — sí lo cubre `RECURSADO_Y_VIRTUAL.md` (referenciado
   pero no incluido en el walkthrough).

8. **`WORKFLOW.md` sección 1** dice que tras el reset "se debe
   recrear" ciclos, cronogramas, planes, etc. Pero no advierte que
   los **nombres reales** de las carreras vienen de
   `carreras_metadata.json`, así que si ese archivo está desactualizado
   o falta, las carreras quedan con `nombre = codigo` como
   placeholder. Esto se ve en la UI como "IE - IE" (ambos iguales)
   hasta que alguien las renombra a mano.

9. **La cardinalidad de `PlanEstudioDB` no está clara en la doc**.
   Al leer el código, resulta que una misma materia puede aparecer
   varias veces en la misma versión de plan si tiene varias
   asociaciones año/cuatri distintas (aunque la UI no lo facilita).
   No se documenta si esto es intencional o accidental.

10. **El campo `codigo_guarani`** no está documentado en ningún doc
    del proyecto. Sale del Excel, se persiste, no se ve.

---

## 5. Preguntas abiertas

1. ¿La materia tiene un campo `active` en el modelo (con default
   `True`) pero no se expone en la UI. ¿Está deprecado? ¿Está pensado
   para soft-delete futuro? El script `mark_optativas_virtual.py` lo
   podría tocar, pero no se ve en la UI de la página de Materias.

2. ¿El tab "🔍 Buscar" de Materias sirve para algo o es legacy que
   se puede sacar? El filtro del tab Lista ofrece la misma búsqueda
   con más funcionalidad.

3. ¿Es intencional que al crear una carrera **no** se cree
   automáticamente una `PlanCarreraVersionDB` inicial? El script de
   carga sí lo hace. Si un usuario crea una carrera desde la UI y no
   se acuerda de crear el plan, se queda mudo hasta que descubre la
   opción "Nueva Version" en el tab de Planes.

4. ¿La distinción entre `numero` y `id` en `ComisionDB` (numero es
   display-only) se refleja bien en la UI de comisiones? Fuera del
   scope de este auditoría pero relevante para el manual.

5. ¿Es un bug o feature que cambiar el tipo de un aula de/a
   `laboratorio` no ajuste las `MateriaLaboratorioDB`? El caption lo
   asume como feature pero puede generar labs "compatibles" que ya
   no son labs.

6. ¿La fusión de sedes actualiza el `codigo_aula` autoderivado de
   las aulas reasignadas? Del código pareciera que no — se limita a
   reasignar `sede_id`, el string del `codigo_aula` queda con el
   nombre de la sede vieja. ¿Es aceptable?

7. ¿Existe algún mecanismo para desasociar en bulk todas las
   materias de una carrera antes de borrarla? Hoy hay que ir una por
   una desde el tab "📚 Materias por Carrera".

8. ¿Por qué el override de recursado en la materia se implementa como
   selectbox de 3 estados en vez de un checkbox tri-state o dos
   controles separados? Es funcional pero puede confundir al usuario
   nuevo (¿qué significa "Según Carrera"?).

9. ¿Cuál es el flujo esperado para editar un `PlanCarreraVersionDB`
   completo? Hay "Editar version" que sólo edita nombre y
   descripción, y no hay una forma de borrar una versión desde la UI.

10. ¿La carga inicial y la UI comparten la lógica para
    codigo_guarani? Al menos el script lo carga; la UI no lo edita
    ni lo muestra. ¿Es para futura integración con SIU Guaraní?
