# Workflow End-to-End del sistema (referencia técnica interna)

> **Última actualización**: 2026-09-23.
>
> ⚙️ **Este documento es la referencia técnica interna**: usa nombres
> de tablas, servicios y detalles de implementación. Es útil para el
> equipo de desarrollo o para redactar el informe académico.
>
> Para uso operativo por usuarios finales no técnicos, consultar el
> **manual de usuario** en `project/Informe/anexos/Anexo_Manual_de_Usuario/`, que cubre
> los mismos flujos en lenguaje coloquial y con foco en tareas.
>
> **Cambios clave a tener en cuenta al leer este documento**:
>
> 1. **`DictadoDB.activo` eliminado** (2026-06-30). La semántica
>    actual es "existencia = activación": si el dictado existe en el
>    ciclo, se ofrece; si no existe, no se ofrece. `activo_override_manual`
>    tampoco existe. Cualquier referencia a "toggle Activo" o
>    "activo/inactivo" de dictados que quede abajo se refiere ahora
>    a **crear / borrar la fila del dictado**. Ver
>    `CICLOS_Y_DICTADOS.md` y `RF-DICT-03`.
> 2. **Clases puntuales deprecadas** (2026-07-07). El tab "📅 Clases"
>    y toda la edición manual de `ClaseDB` (aula puntual, tipo puntual,
>    rangos) fueron removidos. El asignador de aulas y la UI trabajan
>    sólo sobre el patrón semanal (`HorarioDB.aula_id`). Cualquier
>    mención al tab de clases o a la edición por fecha en las secciones
>    5-8 refleja el estado anterior; hoy se trabaja únicamente con el
>    patrón semanal.
> 3. **Comisiones como entidad de primera clase** (2026-07). Antes
>    `ScheduleEntry.comision` era un `int` sin entidad. Ahora
>    `ComisionDB` puede pertenecer a un cronograma o a un plan y se
>    edita como fila (nombre, cupo, carrera asignada, descripción).
>    Al generar el plan desde un cronograma, las comisiones template
>    se **clonan** al plan. Ver [sesiones/COMISIONES_POR_CARRERA.md](sesiones/COMISIONES_POR_CARRERA.md).
> 4. **Grupos de Materias reemplazan `CarreraSedeDB`** (2026-09). La
>    resolución de sedes admisibles del LP (R10) y la preferencia
>    blanda (R12) van exclusivamente por el grupo de la materia.
>    Cada grupo declara set duro + lista blanda ordenada; el modo
>    por-grupo se elige por corrida (`LPConfig.modos_por_grupo`).
>    `CarreraSedeDB` y `SedeDB.es_default_comunes` quedan deprecados.
>    `ComisionDB.carrera_asignada` sobrevive como etiqueta visual sin
>    efecto en el LP. Ver `asignador_implementacion.md` § 5.
> 5. **R13 extendida y R13-camino** (2026-09). R13 detecta pares
>    intersede en riesgo tanto por traslado del docente (misma
>    comisión) como por traslado del alumno (materias distintas del
>    mismo grupo curricular). Un chequeo pre-solve **R13-camino**
>    verifica que para cada `(carrera, año, cuatri)` exista al menos
>    una combinación de comisiones viable. Ver `VALIDACIONES.md` § 2.5.
> 6. **Toggle R14 y veredicto estructurado** (2026-09). Nuevo toggle
>    `forzar_misma_sede_por_comision` en el panel del asignador.
>    Cada corrida persiste un veredicto humano-legible en
>    `LPRunDB.details_json` con status, causa, bloqueos y config
>    completa. Ver `asignador_guia_operativa.md` § 4.
> 7. **Excepciones ignoradas con auto-limpieza** (2026-09).
>    `IgnoredConflictDB` marca pares de materias que la validación de
>    solapamiento debe saltar. La auto-limpieza en `validate_plan`
>    quita excepciones que ya no aplican. No afectan al chequeo de
>    intersede.
> 8. **Colisiones de aula al editar horario** (2026-09). La edición
>    manual de aula detecta colisiones con otros horarios y ofrece
>    liberar el ocupante desde la UI compartida
>    `horario_edit_shared.py`. `apply_solution` sanea horarios
>    virtuales stale para preservar la invariante "virtual → sin
>    aula".
>
> Vínculos:
> - Modelo de datos: [modelo-planificacion-cursada.md](../1.%20Diseño/modelo-planificacion-cursada.md)
> - Asignación de aulas (planteo formal): [asignacion-aulas-LP.md](../1.%20Diseño/asignacion-aulas-LP.md)
> - Asignación de aulas (implementación): [asignador_implementacion.md](asignador_implementacion.md)
> - Recursado y virtualidad: [CICLOS_Y_DICTADOS.md](CICLOS_Y_DICTADOS.md)
> - Comisiones y sede por carrera: [sesiones/COMISIONES_POR_CARRERA.md](sesiones/COMISIONES_POR_CARRERA.md)
> - Validaciones: [VALIDACIONES.md](VALIDACIONES.md)
> - Concepto de plan de cursada: [plan-de-cursada.md](../0.%20Planteo/plan-de-cursada.md)

---

## 0. Vista panorámica

El sistema tiene **un único flujo lineal** que arranca con la carga
de datos del catálogo y termina con un plan de cursada activado, listo
para que el solver de aulas lo procese.

```
┌─────────────────────┐
│  0. Carga inicial   │  Excel → MateriaDB, CarreraDB, PlanEstudio,
│  (script CLI)       │       MateriaLaboratorioDB, AulaDB
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  1. Ciclo + Plan    │  Crear CicloDB → asignar PlanCarreraVersion
│  Versions           │       → ahora el ciclo "sabe" qué se dicta
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Dictados del    │  Crear DictadoDB para cada materia del ciclo.
│  ciclo              │       Semántica "existencia = activación":
│                     │       la fila existe ↔ la materia se dicta
│                     │       este cuatri.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. Cronograma      │  Cargar Excel con horarios del cuatri;
│                     │       valida contra dictados activos del ciclo;
│                     │       editor in-place para resolver issues.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. Generar Plan    │  Wizard de 2 pasos: del cronograma derivar
│                     │       comisiones + horarios estructurados.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  5. Detalle del     │  Por materia: editar horarios/comisiones,
│     Plan            │       peso, override manual de inscriptos
│                     │       esperados, calendario editable.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  6. Validar Plan    │  Cobertura, conflictos, partición teoría/lab,
│                     │       ignorar conflictos puntuales. Snapshot
│                     │       persistido en PlanValidationDB.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  7. Activar Plan    │  Sólo si no hay conflictos NO ignorados;
│                     │       genera ClaseDB (instancias concretas
│                     │       con fecha) para todo el cuatri.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  8. Asignar Aulas   │  Programa lineal que decide el aula de cada
│                     │       HorarioDB (patrón semanal) respetando
│                     │       capacidad, virtuales, partición
│                     │       teoría/lab, sedes admisibles y no
│                     │       doble booking. Las ClaseDB heredan
│                     │       el aula del patrón.
└─────────────────────┘
```

---

## 1. Carga inicial (CLI)

```bash
python -m scripts.load_initial_data --reset
```

Resetea la DB y carga desde `data/input/`:

- `aulas.xlsx` → `SedeDB("Pellegrini")` (default) + `AulaDB` con
  `sede_id` apuntando a Pellegrini, `codigo_aula` derivado como
  `Pellegrini-AULA-01` y tipo default `"teorica"`. Aulas de otras
  sedes se cargan desde la página `🏛️ Aulas y Sedes` en la UI.
- `materias.xlsx` → `MateriaDB` (código, nombre, hsem, hteo, hlab,
  período, virtual, optativa).
- `materias_carreras.xlsx` → `CarreraDB` + `PlanEstudioDB` (qué
  materia pertenece a qué carrera, año y cuatrimestre).
- `materias_laboratorios.xlsx` → `MateriaLaboratorioDB` (qué
  laboratorios son compatibles con qué materia).

Detalle completo: [CARGA_DATOS_INICIALES.md](CARGA_DATOS_INICIALES.md).

> Tras reset, **se debe recrear** desde la UI: nombres de carrera,
> ciclos, dictados, cronogramas y planes de cursada (no se persisten
> en los Excel de entrada).

---

## 2. Ciclo + Plan Versions (📆 Ciclos)

### 2.1 Crear el ciclo

`📆 Ciclos → Lista → Crear ciclo nuevo`. Atributos:

- `id` (ej. `2026-1C`)
- `anio`, `numero` (1 ó 2)
- `fecha_inicio`, `fecha_fin` (rango del cuatri)

### 2.2 Asignar versiones de plan

Cada carrera tiene una o más `PlanCarreraVersionDB` (planes de
estudio versionados). Para que un ciclo "sepa" qué materias se
ofrecen, hay que crear `CicloPlanVersionDB` (uno por carrera que
participa).

Esto se gestiona desde `📆 Ciclos → Versiones de plan` y permite:
- Cambiar la plan version asignada a una carrera para un ciclo
  puntual (`swap_plan_version_for_ciclo`).
- Que distintas carreras del mismo ciclo apunten a distintas
  versiones.

---

## 3. Dictados del ciclo (📆 Ciclos → 📚 Dictados)

Los `DictadoDB` representan **qué materia se dicta y cómo en este
ciclo concreto**. Crear dictados es necesario antes de cargar
cronogramas y planes — sin dictados no hay set de "materias
esperadas" contra el cual validar.

### 3.0 Los ciclos son unidades operativas independientes

Vale explicitar el modelo mental antes de entrar en el detalle:
**cada ciclo se crea y opera de manera autónoma**. Crear el 1C **no**
crea ni pre-declara nada del 2C, y viceversa. Los dictados
cuatrimestrales del 1C viven linkeados sólo al 1C, y los del 2C
sólo al 2C; no se propagan horarios, comisiones ni planes de
cursada entre ciclos.

La única entidad que se comparte entre dos ciclos es el `DictadoDB`
de una materia **anual**: se materializa como una única fila
linkeada a ambos ciclos del año lectivo vía dos filas de
`DictadoCicloDB`. Al crear el 1C, un dictado anual nace con
`fin_dictado=None`; al crear después el 2C del mismo año,
`_link_anual_dictado_2c` reutiliza ese dictado, le agrega el bridge
al 2C y completa `fin_dictado`. Si el 2C se crea sin que exista
todavía el 1C previo, se crea un dictado anual fresco. Formalizado
como RN19 en `modelo-planificacion-cursada.md`.

Para la guía operativa completa (crear un ciclo desde cero, cargar
horarios, checklist previo al asignador, escenarios recurrentes),
ver el runbook **[CICLOS_Y_DICTADOS.md](CICLOS_Y_DICTADOS.md)**.
Para la semántica formal de las tres puertas de decisión de un
dictado (pertenencia, recursado, virtualidad),
[`CICLOS_Y_DICTADOS.md § 1`](CICLOS_Y_DICTADOS.md).

### 3.1 Crear los dictados

Botón **"Crear dictados"**: para cada materia del plan asignado al
ciclo crea un `DictadoDB` con:

- `dictado_codigo` (`{materia}-{ciclo.anio}-{numero}C` para
  cuatrimestral; `{materia}-{ciclo.anio}` para anual).
- Si la regla de recursado dice omitir la materia (por
  `MateriaDB.dicta_recursado=False`, override, o
  `CarreraDB.dicta_recursado=False`), el dictado **no se crea**
  (aparece como omitido con la razón en el resumen). Semántica
  "existencia = activación": la fila del dictado sólo existe si
  la materia se dicta.

### 3.2 Existencia del dictado (crear / borrar), no toggle activo

**No hay más toggle "activo/inactivo"** (2026-06-30). La regla
actual es "existencia = activación":

- **Crear el dictado** ↔ la materia es esperada este cuatri.
- **Borrar el dictado** ↔ la materia NO se considera para
  validaciones de cobertura.

Para borrar un dictado existente se usa
`borrar_dictado_de_ciclo(session, ciclo_id, dictado_id)`, que
también pone en NULL las `ClaseDB.dictado_id` huérfanas para que
sobrevivan (por si se necesita el historial). Para "reactivar" hay
que volver a crear la fila (`create_dictado_for_materia` o rerunning
`create_dictados_for_ciclo`).

**Panel de divergencias**: cuando la regla vigente y los dictados
del ciclo no coinciden, la página de Ciclos ofrece un panel de
sincronización que reporta:

- Materias del plan sin dictado creado (`to_create`).
- Dictados sin materia en el plan (`to_delete`, típicamente por
  cambio de versión de plan).
- Dictados existentes que la regla actual diría omitir
  (`rule_says_skip_but_exists`). **No se borran automáticamente**;
  el usuario decide caso por caso: borrar o **promover a regla**
  (setear `MateriaDB.dicta_recursado`) para que en ciclos futuros
  no aparezca como divergencia.

Detalle completo del flujo en `CICLOS_Y_DICTADOS.md`.

> **Materias compartidas y separación visual**: una misma materia
> (ej. "Cálculo I") puede aparecer en varios planes de carrera. La
> UI las separa en dos buckets para evitar widgets duplicados:
>
> - Los **expanders por carrera** muestran sólo materias **exclusivas**
>   a esa carrera (las que aparecen en un único plan del ciclo).
> - Un **expander adicional "🔗 Comunes"** al final lista las
>   materias **compartidas** (en 2+ carreras) una sola vez por
>   materia, con su propio set de filtros — incluye un filtro extra
>   por carrera con lógica O: si elegís "Industrial" + "Mecánica",
>   se muestran todas las comunes que pertenecen a *cualquiera* de
>   las dos.
>
> Cada `DictadoDB` se renderea una única vez por run (sin importar
> cuántas carreras compartan la materia). Los toggles Activo,
> Virtual y Recursado de las comunes afectan a todas las carreras
> donde aparece la materia (los flags viven en `DictadoDB` /
> `MateriaDB`, no por carrera). Esto elimina las race conditions
> que existían cuando se renderizaba la misma materia en cada
> carrera con keys de widget distintas pero apuntando al mismo
> dictado.

### 3.3 Recalcular según reglas

Botón que aplica las reglas de `dicta_recursado` (más los flags
overrideables por carrera y por materia) a todos los dictados
existentes y reporta los cambios pendientes sin aplicarlos hasta que
el usuario confirme.

El **detalle del preview** muestra para cada cambio:
- Materia (código + nombre completo).
- Carrera (o "Compartida" cuando aplica).
- Año/cuatrimestre del plan donde figura.
- Estado actual → estado nuevo.
- **Razón** legible del cambio (ej. "Carrera FBA no dicta recursado
  y la materia es del 2C; este ciclo es 1C → inactiva").

**Tres secciones en el preview**: 🟢 Pasarán a Activo, ⚪ Pasarán a
Inactivo, ✋ Editados a mano (respetados) — estos últimos son los
que el modo default no toca porque tienen
`activo_override_manual` seteado.

**Toggle "Pisar también las ediciones manuales"** (default OFF):
cuando está activo, las ediciones manuales se descartan y la regla
se aplica a todo. Útil cuando se acumularon muchas ediciones
obsoletas y se quiere limpiar el estado del ciclo.

### 3.4 Toggle Virtual (modalidad puntual del ciclo)

Cada fila tiene además una columna **Virtual**. Marca el dictado
como **virtual sólo en este ciclo** (modalidad puntual), sin
modificar el catálogo `MateriaDB.virtual`.

**Qué cambia cuando un dictado está marcado virtual**:

- El **LP de asignación de aulas** ignora todos los horarios de la
  materia: no consume aula, no entra en grupos de simultaneidad ni
  contribuye al penalty de capacidad.
- El **cronograma del plan** los muestra con el ícono `🌐 virtual`
  para que sea visible.
- La **prevalidación de cobertura** los considera **cubiertos**
  (presentes), no como faltantes ni como extras: están en la oferta
  oficial, sólo que no son presenciales este cuatri.
- La generación de `ClaseDB` los crea normalmente con `aula_id=None`
  (igual que las virtuales del catálogo).

**Cuándo conviene usarlo**:

- Recursados que se dictan por Zoom este cuatrimestre.
- Materias del 2C que aparecen en el cronograma del 1C como
  recursado virtual: en lugar de dejar el dictado **inactivo** (que
  marcaría todo como faltante en validaciones) o tener que marcar
  cada horario uno por uno, basta con activar el dictado y
  marcarlo virtual. Esto **alinea** los datos del ciclo con los
  del plan y el cronograma sin generar ruido.

> **Persistencia**: el flag vive en `DictadoDB.virtual` (a nivel
> ciclo). Al regenerar el plan desde el cronograma, la marca se
> mantiene. Al crear un nuevo ciclo, los dictados nuevos heredan
> `virtual=False` (presencial) por default, salvo que la materia
> sea virtual de catálogo, en cuyo caso heredan True.

> **Modo batch**: igual que el toggle Activo y el selector
> Recursado, los cambios al toggle Virtual NO se aplican al
> instante. Se acumulan en la sección **⏳ Cambios pendientes** y
> se persisten todos juntos al apretar **💾 Aplicar cambios**.
> Esto evita la pérdida de cambios cuando se hacen clicks rápidos
> consecutivos.

---

## 4. Cronograma (📅 Cronogramas)

El cronograma es el **input principal de horarios**: una snapshot
del Excel que llega desde la facultad con la oferta horaria del
cuatri. Múltiples cronogramas por ciclo (versiones de borrador,
copias para experimentar).

### 4.1 📤 Cargar

Sube un Excel `.xlsx` con columnas: `materia | día | inicio | fin |
comisión (opcional)`. Se valida la estructura y se persiste como un
`ScheduleDB` con `ScheduleEntryDB` por fila.

**Modos disponibles** (radio del tope de la tab):

- **Crear vacío** — cronograma sin entradas.
- **Crear desde archivo** — cronograma nuevo poblado con un CSV/Excel.
- **Importar en cronograma existente** — flujo Fase C2, agrega/
  reemplaza horarios sobre un cronograma existente con preview y
  decisión de merge por materia.
- **Copiar desde plan** (Fase F del rediseño 2026-09-15) — crea un
  cronograma nuevo con el estado consolidado de un plan de cursada.
  Uso típico: después de varias iteraciones de validación y edición
  sobre un plan, se quiere "archivar" ese estado como cronograma
  reutilizable (ej. para replicar la configuración firme del ciclo
  anterior en el nuevo ciclo). Delega en
  `src/services/schedule_service.py::clonar_plan_a_cronograma`,
  que copia `ComisionDB` + `HorarioDB` como `ScheduleEntryDB` con
  nuevos UUIDs preservando nombre/número/cupo/coef/carrera_asignada
  a nivel comisión y día/horas/tipo_clase/virtual a nivel horario.
  **No** copia `aula_id` (las entries del cronograma no tienen
  aula asignada; el LP la resuelve al armar el plan siguiente) ni
  `dictado_id` (se re-resuelve contra el ciclo destino).

**Plantilla descargable con listas desplegables** (Fase C1 del
rediseño 2026-09-15; rediseñada 2026-09-23). Antes de subir, el
usuario puede descargar una plantilla Excel armada dinámicamente por
`src/services/template_export_service.py::generar_plantilla_cronograma_excel`.
El archivo trae:

- Hoja `Instrucciones` con guía en castellano sobre cómo completar
  cada columna y las reglas que valida la aplicación al importar.
- Hoja `Horarios` con 9 columnas (`nombre_materia` primero — pedido
  2026-09-24 —, `codigo_materia`, `codigo_comision`,
  `nombre_comision`, `dia`, `hora_inicio`, `hora_fin`, `tipo_clase`,
  `virtual`), headers estilizados, freeze pane y **sin fila de
  ejemplo** (la fila de ejemplo pre-cargada se importaba como dato
  real si el usuario no la borraba — fix auditoría 2026-09-23; el
  ejemplo vive ahora en Instrucciones).
- Hoja **visible** `Materias` (2026-09-24: **protegida**, sólo
  consulta) con el contexto completo de cada materia con dictado
  activo en el ciclo: nombre y código primero (los referencian los
  rangos de la hoja Horarios), atributos del catálogo (Guaraní,
  período, horas, cupo, optativa, virtual, regla de recursado), en
  qué **planes de carrera** aparece y en qué momento (carrera, año,
  cuatrimestre, optativa por plan) y cómo quedó configurado el
  **dictado del ciclo** (código de dictado, modalidad resuelta con
  la jerarquía dictado > catálogo, y si es un dictado de recursado
  — todas sus apariciones en los planes del ciclo son del
  cuatrimestre opuesto). Fuente:
  `template_export_service.obtener_contexto_materias_del_ciclo`.
- La materia se ingresa **sólo por código** (desplegable en
  `codigo_materia`; quien carga debe conocer el código correcto).
  `nombre_materia` es la **primera columna** de Horarios (pedido
  2026-09-24) y viene pre-cargada (filas 2–1001) con una fórmula
  `=IFERROR(INDEX(...);MATCH(...))` que **muestra el nombre al
  elegir el código**, como verificación visual: la hoja está
  **protegida sin contraseña** con esa columna bloqueada (las de
  carga están desbloqueadas celda a celda), así que el nombre no se
  puede editar ni elegir a mano y no puede haber código y nombre
  que no se correspondan. La protección permite expresamente
  ordenar, filtrar, insertar/eliminar filas y ajustar anchos; sin
  contraseña, se quita en un clic (Revisar → Desproteger hoja).
- El área de datos es una **tabla de Excel** (`TablaHorarios`,
  `A1:I1001`): filtros por columna y bandeado de filas.
- Hojas ocultas `_dias`, `_tipos`, `_virtual` con las listas
  cerradas restantes. `_virtual` contiene los **booleanos reales**
  de Excel (se muestran VERDADERO/FALSO): elegir del desplegable
  deja un `bool` en la celda — con textos tipo "SI"/"NO" la celda
  no se alineaba con la semántica booleana de la columna. En Excel
  365 la columna puede convertirse en casillas de verificación
  nativas (seleccionar la columna → Insertar → Casilla); openpyxl
  todavía no puede generarlas, así que la plantilla trae el
  desplegable booleano y la sugerencia queda en Instrucciones. La
  lista de materias válidas sale de los dictados activos del ciclo
  elegido (misma fuente que `validar_cronograma`) — por eso el
  botón queda deshabilitado hasta que se elija ciclo.
- `openpyxl.DataValidation` en cada columna crítica: listas
  desplegables para código de materia (referencia la hoja
  `Materias`), día, tipo y virtual; entero ≥ 1 para
  `codigo_comision`; validación tipográfica de hora en formato
  `HH:MM`. `nombre_materia` (fórmula de sólo lectura) y
  `nombre_comision` (texto libre) no llevan validación. Las listas
  de **tipo y virtual son dependientes entre sí** (2026-09-24): la
  fuente de cada una es una fórmula `IF` por fila, así con tipo
  `laboratorio` la lista de virtual sólo ofrece FALSO y con virtual
  VERDADERO la de tipo sólo ofrece `teorica` — Excel mismo impide
  la combinación laboratorio + virtual (pegar valores saltea
  cualquier validación de Excel; para eso queda la guardia del
  parser).
- `fullCalcOnLoad` activado para que las fórmulas se recalculen al
  abrir el archivo (openpyxl no guarda valores cacheados).

La plantilla no ejecuta reglas de negocio (unicidad de comisión, gap
horario, etc.): esas se corren en el importer en Fase C2. Acá sólo
se blindan errores tipográficos y datos fuera del catálogo.

**Validaciones de entrada del parser** (2026-09-23).
`horario_file_parser.parse_horarios_file` rechaza por fila (sin
frenar el resto del archivo):

- `hora_inicio >= hora_fin` (antes la fila invertida entraba y
  recién rompía en las validaciones del cronograma).
- `tipo_clase = laboratorio` marcado `virtual` — un laboratorio
  requiere aula física.
- `codigo_comision` no numérico o menor a 1.
- Correspondencia código ↔ nombre de comisión **no unívoca** dentro
  de una materia (2026-09-24): si se declara nombre, un mismo código
  no puede aparecer con dos nombres distintos ni un mismo nombre con
  dos códigos. Las filas que no declaran nombre (queda el default
  `C{código}`) no participan del chequeo, y al agrupar en la vista
  previa gana el nombre declarado sobre el default.
- Fila que declara `codigo_materia` **y** `nombre_materia` que no se
  corresponden en el catálogo (esta guardia corre en el preview del
  importador, que es quien tiene acceso al catálogo): tipear un
  código pisa la fórmula de autopoblación, así que el Excel solo no
  alcanza para impedir la mezcla.

Además: la columna `virtual` es un **booleano** — vacío o NaN se
interpreta `False` (presencial); `tipo_clase` puede quedar vacío
(= "sin determinar", lo resuelve la asignación automática por
programación lineal); las filas totalmente vacías (típico: filas de
la plantilla que sólo traen la fórmula de auto-población) se
saltean en silencio; y si `codigo_materia` viene vacío pero hay
`nombre_materia`, el importador resuelve la materia por nombre
(match exacto case-insensitive, sólo si es único — orden de
resolución: código de plan > código Guaraní > nombre).

**Selector de hoja del Excel** (Fase I.4 del rediseño, 2026-09-23).
Los archivos que llegan de las cátedras suelen traer una hoja por
cuatrimestre (`1C`, `2C`, `Verano`) dentro del mismo libro, y el
fallback automático del parser — preferir la hoja `Horarios`, y si no
existe la primera visible — elige mal en ese escenario. Por eso, en
cuanto se sube un archivo, la tab Cargar lista las hojas candidatas
con `horario_file_parser.listar_hojas_visibles` (openpyxl en modo
read-only: se descartan `Instrucciones`, las hojas de sistema con
prefijo `_` y las marcadas ocultas en el workbook) y, si hay más de
una, ofrece un selector **"Hoja del Excel a importar"** que arranca
pre-seleccionado en la hoja preferida del parser
(`hoja_default(sheets)`). Con una sola hoja visible el selector no se
muestra pero la hoja se fija igual, de modo que el parser no pueda
caer en una hoja oculta. La elección se propaga como `sheet_name` a
`parse_horarios_file`, `preview_import`, `crear_shadow_import`,
`regenerar_materia_en_shadow` y `create_schedule_standalone`; con
`None` se conserva el fallback tradicional. Para CSV no aplica. La
página **📈 Inscriptos** tiene el selector análogo, con la hoja
`Inscriptos` como preferida — el caso típico ahí es un libro con una
hoja por año lectivo.

**Importer con preview + merge por materia** (Fase C2 del rediseño
2026-09-15). La tab Cargar tiene tres modos:

- **Crear vacío**: como antes, arranca sin entradas.
- **Crear desde archivo**: flujo legacy, crea cronograma + carga en
  un solo paso (sin preview). Sirve para migración rápida cuando el
  cronograma es nuevo y no hay riesgo de merge.
- **Importar en cronograma existente** (nuevo): pipeline de dos pasos
  a través de `src/services/cronograma_import_service.py`:

  1. `preview_import(session, schedule_id, file, sheet_name=None) →
     ImportPreview`: parsea el archivo — la hoja que indique
     `sheet_name`, o el fallback tradicional si viene en `None` —,
     resuelve códigos contra el catálogo (con fallback via
     ``codigo_guarani``), agrupa por `(materia, comisión)` y detecta
     qué materias ya tienen horarios en el cronograma destino. La UI
     muestra cuatro métricas (horarios del archivo, materias
     detectadas, materias que requieren decisión y horarios totales
     del estado hipotético) y, por cada materia con datos previos,
     un radio **"reemplazar / agregar / ignorar"** con `reemplazar`
     como opción por default.
  2. `commit_import(session, preview, decisiones) → ImportResult`:
     aplica las decisiones en una sola transacción. Con `agregar`,
     la comisión del archivo se rechaza si el nombre choca (unicidad
     case-insensitive dentro de la misma materia) y el error se
     acumula en `result.errors`. Con `reemplazar`, borra entries +
     comisiones previas antes de crear las nuevas, **preservando los
     atributos manuales de las comisiones homónimas** (cupo,
     descripción, coeficiente de asignación, carrera asignada — el
     archivo de horarios no trae esos campos y no puede reponerlos;
     fix auditoría 2026-09-23). Con `ignorar`, la materia queda
     intacta. Si el archivo trae el mismo dictado bajo dos códigos
     que resuelven a la misma materia (código de plan + Guaraní), el
     borrado del `reemplazar` se hace una sola vez y el segundo
     grupo se suma con chequeo de colisión.

**Identidad de las comisiones** (2026-09-23). Las comisiones del
cronograma son entidades (`ComisionDB`) con **código numérico**
(`numero`, el identificador estable que declara la cátedra en la
columna `codigo_comision` de la plantilla) y **nombre** opcional
(`nombre_comision`; si falta se autogenera `C{código}`). En los
calendarios de cronograma se visualiza el código (`[C2]`); el
nombre aparece en la leyenda por comisión y en los editores. Si la
fila declara código, los horarios se agrupan por código y la
colisión en `agregar` se chequea tanto por número como por nombre
canónico. La columna histórica `comision` (texto libre: `"1"`,
`"A"`, `"Mañana"`) se sigue aceptando por compatibilidad: se
interpreta como nombre, se deduplica sobre la forma canónica
`strip().lower()` y el `numero` se autoderiva.

El importer no ejecuta las validaciones estructurales completas del
cronograma (cobertura, conflictos, camino de cursada) — esas siguen
a cargo de `validar_cronograma` en la tab Validar. El preview sólo
hace las validaciones tipográficas mínimas que evitan un import roto.

**Preview per-materia con calendarios Antes / Después** (Fase G del
rediseño 2026-09-15; rediseñado 2026-09-23). Al apretar "Ver preview
del archivo" se crea un **shadow schedule**
(`ScheduleDB.es_shadow_import=True`, `shadow_target_schedule_id`
apuntando al destino) que aplica las entries del archivo sobre una
copia del destino. La decisión de merge por default es **"reemplazar"**
para materias con datos previos y **"agregar"** para materias nuevas.

La UI del preview es un loop de expanders — una tarjeta por cada
materia que aparece en el archivo. El título de cada tarjeta lleva el
ícono y el estado estructural de la materia, más los tags "con datos
previos" / "nueva", "🚫 se ignora" cuando la decisión activa es
ignorar, y "⚠️ con errores" cuando la última regeneración no se pudo
aplicar por completo. Adentro de cada expander, en orden:

- **✏️ Ajustes manuales** (expander anidado, colapsado): un
  `data_editor` precargado con las entries del shadow para esa
  materia (Día / Inicio / Fin / Comisión / Tipo, filas dinámicas).
  "Aplicar ajustes al preview" persiste **al shadow** (no al destino)
  con la misma maquinaria del editor por materia (`_persist_edits` →
  `sync_preview_edits_to_schedule`) y refresca el Después, los
  chequeos y las métricas globales. Borrar una fila = esa entrada no
  se importa. La key del editor lleva un fingerprint de las entries:
  cuando la decisión del radio regenera la materia, el editor se
  resetea solo con los datos frescos (los ajustes manuales de esa
  materia se pierden — semántica documentada y deliberada).
- **Radio de decisión**: `reemplazar` / `agregar` / `ignorar` para
  materias con datos previos; `agregar` / `ignorar` para materias
  nuevas (2026-09-23 — el usuario puede excluir del import una
  materia cuyo archivo vino mal, sin comprometerse a subirla, y
  corregirla en el Excel de origen o con los ajustes manuales).
  Cambiar la decisión llama a `regenerar_materia_en_shadow` y
  recomputa la vista Después; los errores del resultado
  (`ImportResult.errors`) se persisten y se muestran dentro de la
  tarjeta. La decisión se guarda sólo si la regeneración salió bien.
- **Columna Antes**: calendario read-only con los horarios de esa
  materia en el destino (estado actual).
- **Columna Después**: calendario read-only con los horarios en el
  shadow (estado hipotético después de aplicar la decisión y los
  ajustes manuales).
- **Chequeos estructurales** de la materia
  (`compute_materia_checks_from_db`), los mismos once que muestra el
  panel Validar → Detalle por materia. Cada tarjeta abre por default
  si el estado no es OK o si hay errores de regeneración pendientes.

Debajo del listado, un container con **métricas globales** del
cronograma hipotético (`validar_cronograma` sobre el shadow —
faltantes, conflictos horarios, bloqueos de camino, partición y
horarios fuera de config) + los botones **Confirmar** y **Descartar**.

Al confirmar (`finalizar_shadow_import`), el destino se pisa con el
shadow y el toast reporta las métricas honestas por diff de
fingerprints (materia + comisión-por-nombre + día + horario + tipo +
virtual): `entries_agregadas`, `entries_eliminadas`,
`entries_sin_cambio`. Re-importar los mismos datos reporta "sin
diferencias".

Si el usuario cierra el navegador con un preview abierto, el shadow
queda huérfano en la DB. Al reabrir la tab Cargar se muestra un
banner amarillo listando los huérfanos con un botón "Descartar" por
cada uno. Los shadows nunca aparecen en `get_all_schedules` ni en el
wizard del plan (filtrados por default en `schedule_service`).

Servicio: `src/services/cronograma_import_service.py::crear_shadow_import`,
`finalizar_shadow_import`, `descartar_shadow_import`,
`list_shadows_huerfanos`.

### 4.2 📋 Lista

Lista todos los cronogramas con:
- Badge de validación (sin validar / validado / con issues / stale).
- Acciones: duplicar, eliminar, abrir en editar/validar.

### 4.3 👁 Ver / Editar

Fase F del rediseño 2026-09-21: las pestañas antiguas "Visualizar"
(read-only) y "Editar" (drag/click/select) se unificaron en una sola,
con un toggle "Solo lectura" que alterna entre ambos modos sin
cambiar de tab. La razón fue simplificar la navegación: la mayoría
de las veces el usuario alterna entre mirar y editar la misma vista.

Editor full-featured (drag/click/select) sobre `ScheduleEntryDB`:

- **Toggle "Solo lectura"**: al estar activo, el calendario queda
  read-only (sin drag, resize, ni edición de celdas) y las tablas
  `data_editor` pasan a modo lectura. Sirve para revisar el estado
  sin riesgo de cambios accidentales, en particular después de un
  merge por shadow.
- **Modo "Por grupo"**: filtros Carrera/Año/Cuatri/Tipo de materia
  (Ciclo Básico/Específicas) + checkbox "Excluir comunes" +
  multiselect de materias a mostrar.
- **Modo "Por materia"**: búsqueda de materia + calendario filtrado
  + tabla `data_editor` con auto-save de Día/Inicio/Fin/Comisión/
  Tipo (sin determinar / teorica / laboratorio) + resumen por
  comisión.
- **Calendario editable** (sólo con "Solo lectura" apagado): drag →
  mover, resize → cambiar duración, click → editar (dialog con
  materia/día/inicio/fin/comisión/tipo + Eliminar/Cancelar), drag
  sobre celdas vacías → agregar entrada (requiere materia activa).
- **Chequeos estructurales inline** (Fase I.3 del rediseño,
  2026-09-23): debajo del calendario aparecen los mismos once
  chequeos del panel "Validar → Detalle por materia" (h/sem ×
  comisiones, horas divisibles entre comisiones, comisiones
  equilibradas, clases paralelas ≤ comisiones, sin comisiones
  vacías, h/sem definidas, teoría + lab = h/sem, modo lab,
  predeterminados consistentes, partición teoría/lab factible y
  horarios dentro de la configuración horaria), más el chequeo
  `entries_sin_comision` cuando hay horarios sin comisión asignada,
  con badge de estado por materia. En modo "Por materia" muestra un
  único bloque; en modo "Por grupo" muestra una tarjeta por cada
  materia del filtro **que ya tenga horarios cargados** — las que no
  tienen ninguna entrada no generan tarjeta acá (su condición de
  faltante se reporta en el panel Validar, que es el que cruza
  contra los dictados del ciclo). Los estados de la tarjeta (`OK` /
  `Revisión` / `Sin horarios` / `Sin datos`) son un subconjunto de
  los del panel Validar — acá no se cruzan con el summary del ciclo,
  así que los estados que dependen del ciclo (`Conflictiva`,
  `No esperada`, `Faltante`) siguen viviendo sólo en Validar.
  Helper `compute_materia_checks_from_db` en
  `src/ui/schedule_materia_editor.py`.

### 4.4 ✅ Validar (panel unificado)

Esta es la pestaña central del cronograma. Reusa el módulo
`validation_ui.render_validation(source='schedule', ...)` que también
sirve al panel del plan.

#### Estructura

1. **Toggle "Excluir optativas"** + **toggle "Auto-revalidar al
   cambiar"** + **botón "Validar cronograma"**.
2. **Toggle "Guardar cambios como copia del cronograma"** (opcional):
   cuando está activo, cualquier edición desde el panel se aplica a
   una copia del cronograma en lugar del original.
3. **Resumen de cobertura**: 6 métricas (Materias, Clases, Horas,
   Esperadas, Cubiertas, Faltantes).
4. **Lab breakdown**: 4 métricas (Con lab asignado, Lab fijo,
   Reserva ad-hoc, Pendiente).
5. **Partición teoría/lab**: success/error global.
6. **Detalle por carrera** (expander):
   - Tabla resumen con totales (Faltantes / No esperadas /
     Conflictos / Ignorados — este último solo plan).
   - Sub-expanders por carrera con discrepancias de dictado y
     conflictos de horarios; bulk-action de activar/desactivar
     dictados desde aquí mismo.
7. **Detalle por materia** (expander):
   - Filtros: búsqueda, Carrera (multiselect, soporta materias
     comunes), Año, Cuatri, Estado (OK/Faltante/No esperada/
     Conflictiva/Sin datos), Tipo (carreras: Comunes/Exclusivas),
     Atributos (Optativa/Virtual/Anual/Con lab/etc), toggle "Solo
     con alertas".
   - Tabla resumen por carrera (sobre el set filtrado) con counts
     por estado.
   - Tabla compacta de materias.
   - **Loop paginado de expanders** (10/página) — cada materia con
     ícono dinámico según su worst-status, header con sufijo de
     modo lab (🧪 fijo / ℹ️ reserva / ⚠️ pendiente). Botones
     "Abrir todas / Cerrar todas" sobre la página actual.
   - Cada expander rendea el `schedule_materia_editor` completo:
     calendario editable filtrado a la materia, controles de
     hsem/hteo/hlab, selector de comisiones + reasignar, data_editor
     con todos los entries, **10 chequeos estructurados** con tildes
     y, cuando aplica, el check `materia_faltante` (cuando la
     materia tiene dictado activo pero 0 entries — alineado con el
     badge 📭 de la tabla).

> Para el detalle completo de los 10 checks ver
> [VALIDACIONES.md](VALIDACIONES.md#4-validaciones-inline-del-editor-por-materia-cronograma).

#### Completitud desagregada (Fase D del rediseño 2026-09-15)

Después del resumen por carrera, el panel Validar muestra dos tablas
de completitud desagregada:

- **Por grupo de materias**: cada `GrupoMateriaDB` (F, FB, CE,
  Específicas, etc.) con `n_cubiertas / n_esperadas` y un accordion
  con las materias faltantes del grupo.
- **Por (carrera, año, cuatri)**: cada grupo curricular del ciclo
  con la misma métrica y accordion.

Ambas vistas se computan on-the-fly con
`src/services/cronograma_completitud_service.py` (no persisten en el
snapshot). Respetan el toggle **"Excluir optativas del cómputo"**,
que en Fase D pasó a estar **encendido por default** — la definición
operativa "cronograma listo" no debería depender de las optativas
para la mayoría de los flujos.

#### Horarios fuera de configuración (Fase H.1 del rediseño 2026-09-21)

Sección propia dentro del panel Validar que resume las entries que
no cumplen con la `ConfiguracionHoraria` global (día no operativo,
rango fuera del operativo, granularidad no múltiplo). Es warning, no
bloquea `listo_para_plan`. Botón "Ajustar automáticamente" dispara
`ajustar_horarios_a_config` que redondea/desplaza las entries en
masa (ver VALIDACIONES.md § 1.9 y 1.10).

---

## 4.5 Inscriptos históricos (📈 Inscriptos)

Página dedicada a la serie histórica de inscriptos por
`(materia, año, cuatri)`, que alimenta el forecast que consume el
LP. Datos en `InscripcionHistoricaDB` (PK compuesta).

### Carga

- **Manual**: data editor por materia con filtro de cuatri visible.
  El service `guardar_registros_materia` respeta el scope del filtro
  para no borrar registros ocultos (`H01` del auditoría —
  fix histórico).
- **Masivo desde Excel** (Fase E1 del rediseño 2026-09-15): expander
  "📥 Cargar masivo desde plantilla Excel" en el tope de la página.
  Flujo de dos pasos:

  1. **Paso 1**: descargar plantilla generada por
     `template_export_service.generar_plantilla_inscriptos_excel`.
     Trae dropdowns de códigos activos del catálogo, cuatri
     (1C/2C/Anual), rango de año y validación de inscriptos >= 0.
  2. **Paso 2**: subir el archivo completado y ver el preview
     armado por `inscripcion_import_service.preview_import`. La UI
     muestra métricas (nuevos / pisan valor / con errores),
     warnings (duplicados en archivo, resolución vía
     `codigo_guarani`), errores por fila, y una tabla con el
     efecto por fila (`valor previo` vs `valor nuevo`). Al
     confirmar se ejecuta `commit_import` con semántica overwrite
     (última fila del archivo gana).

  El importer respeta el fix del bug histórico "cuatri Anual
  omitido del filtro de la UI" (Fase E1): el selectbox de
  cuatri ahora incluye "Anual".

### Auditoría mínima y alias persistentes (Fase E2)

- `InscripcionHistoricaDB` incluye `updated_at` (datetime UTC) y
  `origen` (`"manual"` | `"importado"` | `"override"`). Cada
  INSERT/UPDATE de los services los popula: `guardar_registros_materia`
  usa `"manual"` por default (parámetro configurable),
  `inscripcion_import_service.commit_import` usa `"importado"`, y la
  UI de "Sin matchear" usa `"override"`.
- `CodigoAliasDB(codigo_externo, materia_codigo, updated_at,
  origen, nota)` persiste los matches manuales del flow "Sin
  matchear": cuando el usuario asocia un código externo a una
  materia del catálogo, se guarda el alias y `preview_import` de la
  próxima importación lo resuelve automáticamente sin volver a
  ofrecerlo como "sin matchear".
- Orden de resolución del importer: (1) match directo por
  `codigo`, (2) alias persistido, (3) `codigo_guarani` con
  match único, (4) error.

### Filtros y forecast

Filtros combinables (búsqueda, cuatri, carrera, año dentro del plan,
optativa, período, modalidad). El forecast se muestra como
referencia visual en 3 métodos superpuestos (media móvil, drift,
SES); la elección del método real vive en el
`PlanificacionCursadaDB` (default) y en `MateriaForecastConfigDB`
(override por materia + plan). Ver también `asignador_implementacion.md`
para cómo el asignador consume el forecast.

---

## 5. Generar Plan (📊 Planes → Generar plan)

Wizard de 2 pasos para producir un `PlanificacionCursadaDB` a partir
de un cronograma validado.

### 5.1 Paso 1 — Selección

- Ciclo + Cronograma + nombre/descripción del plan.
- Método de forecast default (media móvil / drift / SES).
- El plan se crea inmediatamente como **borrador** (`activo=False`),
  con todas las comisiones y horarios derivados del cronograma.

### 5.2 Paso 2 — Edición previa

Embebe el editor del tab "Detalle del Plan" (sección 6) para que el
usuario haga los ajustes que quiera antes de salir del wizard.
Cancelar = borra el plan en cascada. Confirmar = sale del modo
wizard y deja el plan como borrador.

---

## 6. Detalle del Plan (📊 Planes → Detalle)

Editor central del plan. Selector de plan (uno o varios por ciclo)
+ las siguientes secciones por plan:

### 6.1 Metadata

Nombre, descripción y método de forecast default. Auto-save.

### 6.2 Estadísticas

5 métricas: Materias, Comisiones, Horarios, Clases, Con Aula.

### 6.3 Validaciones (panel unificado)

Mismo módulo `validation_ui.render_validation(source='plan', ...)`
con todas las features del cronograma + extras del plan:

- **Conflictos de horarios** del plan (sobre comisiones reales,
  vía `validar_conflictos_horarios_plan_estructurados`).
- **Ignorar conflictos** puntuales (`IgnoredConflictDB`): un par
  ignorado no bloquea la activación. Se persiste por (plan, par
  lex-ordenado) y sobrevive aunque cambien los horarios.
- **Snapshot persistido** en `PlanValidationDB` con detalle JSON
  para reconstrucción sin recomputar; staleness automático cuando
  cambia algo (entries, comisiones, horarios, dictados, toggle).
- **Activación gate**: botón "Activar plan" deshabilitado si hay
  conflictos no ignorados; al activar genera `ClaseDB` para todo
  el cuatri.
- **Bulk activate sobre "no esperadas"**: cada lista de materias
  no esperadas (las que aparecen en el cronograma del plan pero
  no tienen dictado activo) ofrece dos botones:
  - **🟢 Activar**: marca el dictado como esperado y presencial.
  - **🌐 Activar y marcar virtual**: marca el dictado como
    esperado pero **virtual sólo en este ciclo** (modalidad
    puntual). El LP de asignación lo ignora; queda alineado con
    el cronograma sin meter presión sobre las aulas. Caso típico:
    materias del 2C que aparecen como recursado por Zoom en el
    cronograma del 1C. Internamente: `set_activo_for_materias_in_ciclo`
    con `marcar_virtual=True` setea ambos flags en bulk.
- **Filtro Virtual del detalle por materia**: la lista de materias
  filtrable del panel de validación combina **dos vías** de
  virtualidad: virtuales de catálogo (`MateriaDB.virtual=True`) y
  con dictado virtual del ciclo (`DictadoDB.virtual=True`). Una
  materia matchea el filtro **Virtual** si cualquiera de las dos
  es True. La columna **Virtual** de la tabla resumen distingue
  visualmente cuál de las dos aplica: `Sí (catálogo)` vs
  `Sí (dictado)`. Esto refleja la misma semántica que el LP, que
  ignora horarios virtuales por cualquiera de los dos motivos.

#### Detalle por materia → editor inline (`plan_materia_editor`)

Cada expander del loop paginado abre el editor completo de la
materia, con esta estructura:

1. **📚 Catálogo de horas**: hsem / hteo / hlab editables con
   auto-save y validación cruzada (`hteo + hlab == hsem`).
   Período read-only.
2. **🗓️ Calendario editable**: drag/click/select sobre los
   `HorarioDB` de la materia, con dialogs adaptados (selector de
   comisión existente o `➕ Nueva comisión` que se crea al vuelo;
   selector de tipo de clase).
3. **✏️ Edición masiva de horarios** (`data_editor`): tabla con
   todos los horarios + Día/Inicio/Fin/Comisión/Tipo, auto-save al
   cambiar.
4. **👥 Inscriptos esperados**:
   - **Peso total** (suma de `coef_asignacion` de las comisiones,
     debe ser ≈1.0) + botón "Normalizar" que reparte 1/n.
   - **Total esperado (manual)**: input numérico para forzar el
     valor de inscriptos esperados de la materia, sobreescribiendo
     el forecast histórico. Persiste en
     `MateriaForecastConfigDB.valor_override`. Botón "Quitar
     manual" para volver al forecast.
   - **Forecast (automático)**: muestra el valor calculado desde
     la serie histórica + método (`Default plan` o override
     puntual). El selector de método override solo aparece cuando
     no hay valor manual seteado.
5. **🎓 Comisiones** (loop, una por expander):
   - Header del expander: `nombre · #N · peso X · esperados Y · ⚠️ partición infactible (si aplica)`.
   - Cuerpo: nombre / **peso** (antes "Coef") / esperados
     (read-only, calculado como `total_esperado × peso`) +
     listado de horarios con borrar inline + popover "Agregar
     horario" + botón "Eliminar comisión".
6. **✅ Validaciones**: los 10 chequeos estructurados (mismos
   `_compute_checks` que el editor del cronograma).

> El **cupo** del modelo se mantiene en DB con default 30 (o el
> cupo de catálogo de la materia) pero **no se edita más en el
> UI** — ya no era usado funcionalmente.

---

## 7. Grilla horaria del plan (📊 Planes → Grilla horaria)

Editor del plan a nivel global, espejo de Cronogramas → Editar pero
sobre `ComisionDB` + `HorarioDB`:

- Modo "Por grupo" (filtros Carrera/Año/Cuatri/Tipo + Excluir
  comunes + Materias a mostrar).
- Modo "Por materia" (búsqueda + calendario + data_editor).
- Calendario editable con drag/resize/click/select.
- Dialogs con selector de comisión (existente o nueva) + tipo.

Útil para detectar y resolver conflictos del mismo cuatri/carrera
en una sola vista.

---

## 8. Activación

Cuando el plan no tiene conflictos no-ignorados y el usuario aprieta
**"Activar plan"** desde el panel de validación:

1. Se invoca `activate_plan(session, plan_id)`.
2. Se desactivan los demás planes del mismo ciclo (sólo un plan
   activo por ciclo).
3. Se genera `ClaseDB` como **cache técnico** de instancias
   concretas para cada `HorarioDB` × cada fecha del ciclo donde
   aplique (`generate_clases_for_plan`):
   - Para cada `HorarioDB(comision=C, dia=Lunes, 8-10)` y cada
     fecha del ciclo cuyo `weekday()` coincida con "Lunes", se
     crea una `ClaseDB(comision_id=C.id, fecha=…, hora_inicio=8,
     hora_fin=10, aula_id=HorarioDB.aula_id)` — hereda el aula del
     patrón semanal.
   - Materias anuales heredan ambas mitades (1C + 2C).
   - Las virtuales **se generan también** con `aula_id=None`. Una
     clase es virtual si la materia es virtual de catálogo, si su
     dictado del ciclo está marcado virtual, o si el horario
     puntual está marcado virtual (jerarquía en 3 niveles, ver
     `CICLOS_Y_DICTADOS.md`). El toggle a nivel dictado vive en
     `📆 Ciclos → 📚 Dictados`, columna **Virtual**.

El plan queda con `activo=True` y aparece como `[ACTIVO]` en la
lista.

> **Nota**: desde la deprecación de clases puntuales (2026-07-07)
> el usuario **no edita `ClaseDB` desde la UI**. Las clases se
> generan como cache del asignador de aulas y no hay tab de edición
> por fecha. La única fuente de verdad editable es el patrón
> semanal (`HorarioDB`).
>
> **Actualización 2026-08-28**: `ClaseDB` quedó formalmente marcado
> como deprecado. El cache sigue vivo por compatibilidad
> (`generate_clases_for_plan`, `apply_solution`, cascadas de borrado)
> pero no se debe usar para features nuevas. Ver
> [`sesiones/DEPRECACION_CLASEDB.md`](sesiones/DEPRECACION_CLASEDB.md).

---

## 9. Estado actual (qué está implementado)

✅ Pasos 0 a 8 + **LP de asignación de aulas (fases 1 a 8)**.

El LP corre sobre la "semana modelo" (variables por `HorarioDB`,
propagación a `ClaseDB` con `fecha ≥ fecha_desde`) y cubre:

- R1 asignación única, R3 compatibilidad por tipo, R4 no doble
  booking vía grupos de simultaneidad, R5 partición teoría/lab,
  R6 consistencia tipo↔aula, R7 penalty lineal asimétrico.
- Re-run incremental con flag `aula_asignada_manualmente` y toggle
  "respetar ediciones manuales" / "sobreescribir todo".
- Diagnóstico estructural de infactibilidad antes y después del
  solve (horarios sin aula compatible, franjas saturadas,
  particiones teoría/lab infactibles) + heatmap día×franja.
- Detalle del resultado coloreado + candidatas a partir comisión.
- Vista cronograma por aula con selector de semana.
- Edición manual de aula con dialog de tres modos (puntual /
  rango / desde hoy) y validación pre-confirmación.
- Toggle α opcional para que el LP redistribuya
  `coef_asignacion` entre comisiones del mismo dictado (R9), con
  diff visual y persistencia bajo confirmación.

Detalle completo de la implementación:
[`asignador_implementacion.md`](asignador_implementacion.md).

---

## 10. Mapa de páginas Streamlit

| Página | Tabs principales |
|---|---|
| `main.py` | Landing |
| `1_📚_Materias.py` | CRUD Materias / Laboratorios |
| `2_🏛️_Aulas.py` | CRUD Aulas |
| `3_🎓_Carreras.py` | CRUD Carreras + plan versions |
| `4_📆_Ciclos.py` | Lista, Crear, Plan versions, **📚 Dictados** |
| `5_📊_Planes.py` | **Generar plan**, **Detalle**, **Grilla horaria**, Clases, **🏛️ Aulas** (LP), Config |
| `6_📅_Cronogramas.py` | Lista, **Cargar** (selector de hoja + preview per-materia), **Ver / Editar** (toggle "Solo lectura" + chequeos inline), **Validar** |
| `7_📈_Inscriptos.py` | Carga histórica por materia/cuatri (manual) + **importer masivo desde plantilla Excel** con selector de hoja |
| `8_📜_Historial.py` | Auditoría de cambios (feed global + vista por entidad) |

---

## 11. Convenciones de UI

- **Toggle "Auto-revalidar al cambiar"**: activo por default en
  los paneles de validación. Cualquier acción del panel (dialogs,
  bulk-actions, calendario editable, data_editor) marca un flag
  pending; al final del render se compara fingerprint vivo (DB) vs
  snapshot del summary cacheado y, si difieren, se dispara
  `validar_*` automáticamente con un toast.
- **Estado por materia (badges)**: ✅ OK, 📭 Faltante, 📥 No
  esperada, ⚠️ Conflictiva, ❓ Sin datos. La columna `Carrera`
  muestra `(+N)` cuando la materia es común a varias.
- **Filtro de carrera**: una materia común matchea si pertenece a
  cualquiera de las carreras seleccionadas (intersección no-vacía
  con su `carreras_set`).
- **Worst-status del expander**: el icono del header de cada
  materia refleja el peor de los 10 checks del editor (priority:
  faltante > error > warn > info > ok), cacheado en session_state
  y refrescado tras cada edición.

---

## 12. Decisiones operativas relevantes

1. **Fuente de verdad de horarios**: el `cronograma` es el
   "boceto" que llega de la facultad; el `plan` es el "plano
   ejecutivo" editable. Los conflictos del cronograma se resuelven
   editando el cronograma (o haciendo una copia); los conflictos
   del plan se pueden ignorar puntualmente.
2. **Multi-carrera y comunes**: una materia compartida entre
   varias carreras existe como un único `MateriaDB`, pero aparece
   en varios `PlanEstudioDB`. La UI respeta esto en filtros y
   counts (cada materia común suma en cada carrera donde
   pertenece).
3. **Override manual de inscriptos esperados**: cuando no hay
   serie histórica o el usuario tiene info externa
   (preinscripción), puede forzar el valor en
   `MateriaForecastConfigDB.valor_override`. Se persiste por
   (plan, materia, cuatri).
4. **Período de la materia (anual/cuatrimestral)**: las anuales
   se dictan en 1C y 2C; los `DictadoDB` anuales se crean en 1C y
   se linkean en 2C (un único dictado, dos `DictadoCicloDB`).

---

## 13. Asignación de aulas (implementado)

El planteo formal y la implementación del programa lineal de
asignación de aulas están en documentos dedicados:

- **Planteo formal** (variables, restricciones R1–R10, función
  objetivo, ejemplos): `1. Diseño/asignacion-aulas-LP.md`.
- **Implementación** (servicios, flujo, diagnóstico de
  infactibilidad, panel operativo, edición manual del patrón):
  `2. Desarrollo/asignador_implementacion.md`.

El diseño final asigna aulas al **patrón semanal**
(`HorarioDB.aula_id`) en vez de a cada `ClaseDB` — un orden de
magnitud menos variables. Las `ClaseDB` heredan el aula del patrón
al generarse. La UI del panel de asignación vive en la pestaña
"🏛️ Aulas" de la página de Planes.
