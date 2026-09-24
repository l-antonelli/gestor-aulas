# Sesión 2026-09-23/24 — Rediseño de la plantilla Excel y validaciones de entrada del importador

> Documento de sesión (línea de tiempo). La descripción canónica y
> vigente de la plantilla y del importador está en
> [WORKFLOW.md § 4.1](../WORKFLOW.md); los requerimientos en
> `project/requerimientos.md` (RF-IMPORT-01, RF-IMPORT-09,
> RF-IMPORT-10, RF-DICT-09); los chequeos en
> [VALIDACIONES.md § 4.13](../VALIDACIONES.md). Acá queda el
> **recorrido**: qué se pidió, qué iteraciones hubo y por qué se
> descartaron los diseños intermedios.

## Contexto

Después del cierre de la auditoría del importer (2026-09-23) y de los
ajustes manuales del preview (`c09ccd3`), el usuario levantó una serie
de pedidos sobre la carga masiva de horarios: la columna Virtual
faltaba en los data editors, quedaban términos en inglés en la UI, las
comisiones se gestionaban por texto libre sin identidad clara, la
plantilla Excel no exponía los datos de las materias, y faltaban
validaciones de entrada básicas (horas invertidas, laboratorio
virtual, semántica booleana de `virtual`).

## Lote 1 — Validaciones de entrada, comisiones con código, virtual booleano (`8e3cce3`, `95f7e26`, `a6d990c`)

- **Parser** (`horario_file_parser`): rechazo por fila de
  `hora_inicio >= hora_fin`, de laboratorio + virtual y de
  `codigo_comision` no numérico o < 1. `virtual` pasa a booleano
  (vacío = `False`; antes vacío era "heredar", opaco). Filas
  totalmente vacías se saltean en silencio.
- **Comisiones como entidad desde el archivo**: columna
  `codigo_comision` (entero ≥ 1) que se persiste como
  `ComisionDB.numero` + `nombre_comision` opcional. Los horarios se
  agrupan por código; colisión en `agregar` por número Y nombre
  canónico. El texto libre histórico (`comision`) sigue aceptado.
- **Resolución por nombre**: tercer nivel código > Guaraní > nombre
  exacto único (`_resolve_materia_code`).
- **Bugfix `build_schedule_grid`**: `ScheduleBlock.virtual` nunca se
  populaba — las clases virtuales no se veían en ninguna vista. Ahora
  el override de la entry manda y `None` cae al flag de catálogo.
- **UI**: columna Virtual (checkbox booleano) en los tres data editors
  de horarios; `_validar_filas_editor` compartida (inicio < fin,
  laboratorio ≠ virtual) antes de persistir; chequeo `lab_virtual`
  (ERROR) para datos históricos; código de comisión visible en los
  calendarios (`[C2]`), nombre en la leyenda. Castellanización de la
  UI (vista previa, lista desplegable, destino, etc. — directiva 8).

## Lote 2 — Iteraciones de la plantilla (`45f20c1` → `a887aaf`)

La plantilla pasó por cuatro diseños en respuesta a feedback directo
del usuario probándola en Excel:

1. **`45f20c1`** — hoja visible `Materias`, fórmula que autopopulaba
   el código al elegir el nombre, y virtual con booleanos reales
   (VERDADERO/FALSO — con textos, Excel coerciona lo tipeado y la
   validación de lista rechaza por tipo). Problema reportado: la
   columna del código tenía su propio desplegable, que pisaba la
   fórmula y permitía elegir código y nombre que no se corresponden.
2. **`f017124`** — desplegable en ambas columnas + columna
   `verificacion` con fórmula (nombre al elegir código, "OK" o
   advertencia de mezcla) + hoja Horarios como **tabla de Excel**.
   La bidireccionalidad literal (fórmula espejo en la celda del
   nombre) se descartó explícitamente: A y B se referenciarían
   mutuamente y Excel sólo tolera esa referencia circular con cálculo
   iterativo, un ajuste que en la práctica es de sesión (lo toma del
   primer libro abierto) — inaceptable para un archivo que circula
   por las cátedras.
3. **`50581ba`** — simplificación pedida por el usuario: la materia se
   ingresa **sólo por código** (quien carga debe conocerlo); el
   nombre se autocompleta como verificación y queda de sólo lectura
   mediante **protección de hoja sin contraseña** (columna bloqueada,
   columnas de carga desbloqueadas celda a celda; se permiten
   ordenar, filtrar, insertar/eliminar filas y ajustar anchos). La
   columna `verificacion` se eliminó por redundante.
4. **`32f6f0d`** — laboratorio + virtual bloqueado EN Excel: las
   listas de tipo y virtual son **dependientes entre sí** (la fuente
   de la validación es una fórmula `IF` por fila). Pegar valores
   saltea cualquier validación de Excel; para eso queda la guardia
   del parser.
5. **`a887aaf`** — estado final: `nombre_materia` como **primera
   columna** de Horarios; hoja `Materias` **protegida** y con el
   **contexto completo** de cada materia (atributos del catálogo,
   planes de carrera con año/cuatrimestre, y configuración del
   dictado del ciclo: modalidad resuelta con la jerarquía
   dictado > catálogo y si es dictado de recursado) vía
   `obtener_contexto_materias_del_ciclo`; y validación **1:1
   código ↔ nombre de comisión** por materia en el parser (un código
   con dos nombres o un nombre con dos códigos rechaza las filas; al
   agrupar gana el nombre declarado sobre el default `C{n}`).

## Lote 3 — Semántica de virtual e invariante en tres capas (`942af32` → `b146613`)

- **`942af32`** — bugfix reportado por el usuario probando la
  plantilla: una columna `virtual` con un solo booleano y el resto
  vacío llega al parser como float (pandas convierte bool + NaN a
  numérico; VERDADERO → `1.0`) y se rechazaba. El parser ahora
  interpreta 0/1 numéricos.
- **`8d58420`** — aclaración semántica en manuales, instructivo del
  Excel y ayudas de los editores: `virtual` en el cronograma es un
  override de **excepción** (una clase puntual virtual dentro de un
  dictado presencial); una materia que se dicta virtual completa se
  configura a nivel dictado/catálogo. Y `tipo_clase` se deja sin
  determinar salvo que sea estrictamente necesario fijarlo.
- **`b146613`** — invariante virtual/tipo pedida por el usuario
  (revierte la decisión "sin constraint de DB" de la mañana): una
  clase virtual es siempre **teórica** y un laboratorio es siempre
  **presencial explícito** (virtual=False, no None — pisa la
  herencia). Tres capas: `normalizar_tipo_virtual` en el service
  layer (con ValueError en los flujos de edición), listeners ORM
  `before_insert`/`before_update` que derivan los casos incompletos,
  y `CHECK` de tabla (`ck_*_virtual_teorica`, `ck_*_lab_presencial`)
  que rechazan hasta el SQL crudo — sólo en tablas creadas desde
  2026-09-24. Además `build_schedule_grid` propaga `tipo_clase` y el
  render simple muestra los íconos 💻/🧪/📖 en todas las vistas de
  cronograma (antes faltaban en los calendarios de la vista previa).

## Lote 4 — Espejo en Inscriptos (post-smoke exitoso del usuario)

Tras validar el flujo de cronograma en Excel real, el usuario pidió
llevar las mismas mejoras al módulo Inscriptos:

- **Plantilla espejo**: hoja visible `Materias` protegida con el
  contexto del catálogo (incluido el código Guaraní, para cruzar con
  las planillas de las cátedras) vía
  `obtener_contexto_materias_catalogo`; nombre primero de sólo
  lectura, código como única entrada, tabla `TablaInscriptos`,
  protección y salteo de filas con sólo fórmula en el parser.
- **Match forzado con asociación inline**: se eliminó la sección
  legacy "Sin matchear" (re-parseaba en cada render el Excel
  hardcodeado de la carga inicial y mostraba 41 códigos que no viven
  en la base). El preview expone `codigos_no_resueltos` y la vista
  previa ofrece asociar el código a una materia (alias persistido) y
  regenerarse con esas filas resueltas.
- **Cobertura por período**: tabla materias × períodos con ✓/— y
  conteo de huecos, filtrable, para ver qué materias no tienen datos
  para qué períodos.

## Decisiones técnicas que conviene recordar

- **Referencia circular**: la autopopulación bidireccional
  nombre ↔ código en las celdas no es viable sin cálculo iterativo
  (frágil) ni VBA (descartado). El diseño final la evita de raíz:
  una sola dirección (código → nombre) + columna protegida.
- **Booleanos en listas de Excel**: una validación de lista con
  textos "TRUE/FALSE" rechaza el valor que Excel coerciona a
  booleano al tipearlo; la hoja oculta `_virtual` contiene booleanos
  reales para que tipos y valores coincidan.
- **Casillas de verificación nativas** (Excel 365): openpyxl no puede
  generarlas (formato de archivo nuevo). Los valores ya son
  booleanos, así que la conversión manual es de dos clics
  (seleccionar columna → Insertar → Casilla) y está documentada en
  las Instrucciones de la plantilla. Si se quisieran de fábrica,
  habría que migrar el generador a XlsxWriter (≥ 3.2).
- **Protección de hoja**: los flags de `SheetProtection` en openpyxl
  significan "acción bloqueada" (por eso se setean en `False` los
  permisos). La protección desactiva la auto-extensión de tablas más
  allá de su rango: la capacidad queda en 1000 filas.
- **Fingerprints y `None ≡ False`**: al volver `virtual` booleano,
  `_fingerprint_entries` colapsa `None`/`False` para que re-importar
  los mismos datos siga reportando "sin diferencias".

## Cobertura

`tests/test_horario_parser_validaciones.py` (validaciones de entrada,
1:1 de comisiones, resolución por nombre, virtual en
`build_schedule_grid`, `_validar_filas_editor`) y
`tests/test_template_export_service.py` (estructura de la plantilla:
orden de columnas, fórmulas, protección de ambas hojas, contexto de
Materias, listas dependientes, tabla). Baseline al cierre: 1459
verdes, 18 salteados, 19 fallos históricos del LP.
