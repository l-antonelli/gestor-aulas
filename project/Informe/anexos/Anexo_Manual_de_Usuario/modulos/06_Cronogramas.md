# Cronogramas

## ¿Para qué sirve?

El módulo de **Cronogramas** es donde cargás y editás la grilla
horaria del cuatrimestre: qué día y a qué hora se dicta cada
materia, y con qué comisión. Es la representación digital de la
planilla de horarios que llega desde la facultad al inicio de cada
cuatrimestre.

Un cronograma no es un plan de cursada todavía — es la materia
prima. A partir de un cronograma se genera después el plan concreto
que se termina asignando a aulas.

## ¿Cuándo vas a usar este módulo?

- **Al inicio de cada cuatrimestre**, después de crear el ciclo y
  los dictados: subís el Excel de horarios que llega desde la
  facultad.
- **Cuando hay que arrancar sin un archivo**: creás un cronograma
  vacío y lo vas cargando a mano.
- **Cuando hay cambios de última hora**: se movió un horario,
  cambió una comisión, agregaron una materia que no estaba.
- **Antes de generar el plan de cursada**: para validar que el
  cronograma cubre todos los dictados esperados del ciclo.

## Cómo se relaciona con el resto

El orden lógico de trabajo es:

```
Ciclos (con dictados creados)
        │
        ▼
   Cronogramas  ──►  Planes de Cursada  ──►  Asignación de Aulas
```

- **Antes de Cronogramas**: el ciclo tiene que existir y tener sus
  dictados creados. Si no, la validación del cronograma no puede
  correr (no tiene contra qué comparar).
- **Después de Cronogramas viene Planes de Cursada**: un plan se
  genera a partir de un cronograma. Las comisiones y los horarios
  que declaraste acá se clonan al plan.

Un ciclo puede tener **varios cronogramas** (por ejemplo, un
borrador inicial, una versión revisada y una final). El sistema no
te obliga a tener uno solo, pero cuando generás el plan de cursada
elegís cuál usar.

## Modelo mental

Antes de meterte a cargar horarios conviene tener claros estos tres
conceptos.

### Un cronograma es un conjunto de filas

Cada **fila del cronograma** representa un horario concreto: día
de la semana, hora de inicio, hora de fin, materia, y opcionalmente
la comisión y el tipo de clase (teoría o laboratorio). Es lo más
parecido a una fila del Excel original.

Un cronograma completo agrupa todas las filas del cuatrimestre.

### La comisión es una entidad separada

En este sistema, **la comisión es una entidad de primera clase**.
No es sólo un número al lado de la materia: es un objeto con
nombre, cupo, carrera asignada (opcional) y descripción.

Adentro de un cronograma podés tener varias comisiones para la
misma materia (por ejemplo, Análisis I comisión 1, 2 y 3), y cada
fila del cronograma se asocia a **una** comisión.

Cuando el cronograma después se transforma en plan de cursada, las
comisiones se **clonan**: la comisión del cronograma queda como
"modelo" y la del plan es la que efectivamente se asigna a aulas y
alumnos.

### La modalidad virtual se puede fijar por fila

Cada fila del cronograma puede tener su modalidad forzada
(virtual o presencial), o dejarla en "Heredar" (que es el default y
significa: usar lo que diga el dictado o la materia). Esto es útil
cuando dentro de la misma comisión la teoría es virtual pero el
laboratorio es presencial.

## Recorrido rápido de la página

La página se llama **📅 Cronogramas** y tiene cinco pestañas:

### Pestaña "📋 Lista"

Vista general de todos los cronogramas cargados. Cada cronograma se
muestra como un expander con:

- Su nombre, cantidad de filas, ciclo asociado (o "sin ciclo") y
  fecha de subida.
- Un **badge de estado de validación**:
  - **⚪ sin validar**: nunca se validó.
  - **🟡 validado pero modificado**: se validó, pero después
    cambió algo del cronograma o de los dictados del ciclo.
  - **🔴 con issues**: la última validación encontró problemas
    (materias faltantes, particiones infactibles).
  - **🟢 validado**: la última validación pasó limpia.
- Adentro del expander podés **renombrar**, **duplicar** o
  **eliminar** el cronograma. También ves el resumen de la última
  validación.

### Pestaña "📤 Cargar"

Se usa para **crear un cronograma nuevo**, ya sea vacío o
importándolo desde un archivo Excel o CSV.

### Pestaña "👁 Visualizar"

Vista de sólo lectura del cronograma en formato calendario. Podés
filtrar **por grupo curricular** (carrera + año + cuatri) o **por
materia** (una a la vez, con colores distintos por comisión).

### Pestaña "✏️ Editar"

La pestaña más pesada del módulo. El calendario acá es interactivo:
podés mover filas, cambiar horarios, agregar nuevas y borrar. Se
apoya en dos modos:

- **Por grupo**: filtrás por carrera + año + cuatri y editás las
  materias de ese grupo curricular en pantalla.
- **Por materia**: elegís una materia puntual y ves todas sus
  filas y comisiones abajo del calendario, en tablas editables.

### Pestaña "✅ Validar"

Corre la validación del cronograma contra los dictados del ciclo:
verifica cobertura (que todas las materias esperadas estén),
detecta materias no esperadas (que están en el cronograma pero no
tienen dictado), calcula la partición teoría/laboratorio, y detecta
conflictos horarios.

## Tareas comunes

### Cargar un cronograma nuevo desde archivo

**Cuándo hacerlo**: cuando ya tenés el Excel de horarios del
cuatrimestre y querés subirlo al sistema.

**Prerequisito**: idealmente el ciclo ya existe y tiene los
dictados creados. Aunque el sistema te permite subir un cronograma
sin asociarlo a ningún ciclo, la validación después necesita esa
asociación.

**Formato esperado del archivo**:

El sistema acepta archivos `.csv`, `.xlsx` o `.xls`. Las columnas
esperadas (con aliases aceptados) son:

| Columna del archivo | Aliases aceptados | Contenido |
|---|---|---|
| `codigo_materia` | `codigo_plan`, `materia`, `cod_materia` | Código de la materia |
| `dia` | `dia_semana` | Día de la semana |
| `hora_inicio` | `hora_ingreso`, `inicio` | Hora de inicio |
| `hora_fin` | `hora_egreso`, `fin` | Hora de fin |
| `comision` | `codigo_comision`, `comision_nombre`, `cod_comision` | Número o nombre de comisión (opcional) |

> ⚠️ **Atención — la columna `comision` del archivo no se asocia
> automáticamente**
>
> El sistema **lee** la columna de comisión del archivo pero
> **no la persiste** al momento de crear el cronograma: las filas
> quedan sin comisión asignada. Vas a tener que asociar las
> comisiones **manualmente** desde la pestaña Editar después de la
> importación.
>
> Si tenés un cronograma grande con comisiones ya definidas en el
> Excel, este paso puede ser tedioso. Es una limitación conocida
> del importador que se resuelve en el editor.

**Paso a paso**:

1. Andá a la pestaña **📤 Cargar**.
2. Elegí la opción **Cargar desde archivo**.
3. Escribí un **nombre** para el cronograma. Es obligatorio y
   conviene que sea descriptivo (por ejemplo, `2026-1C - v1`).
4. Elegí el **ciclo** al que corresponde. Si todavía no tenés
   ciclo, podés dejarlo en `(ninguno)` — pero después no vas a
   poder validar hasta asociarlo.
5. Subí el archivo con el uploader.
6. Apretá **Crear cronograma**.
7. El sistema procesa el archivo y muestra:
   - Un cartel verde con `Cronograma '{nombre}' creado con N
     entradas.` en el happy path.
   - Errores fila por fila si algo no se pudo resolver (materia
     inexistente, columna faltante, formato de hora inválido).
   - Warnings si tuvo que resolver el código de la materia con
     un fallback (por ejemplo, si vino con código externo de la
     facultad en lugar del código interno del sistema).

**Verificación**: andá a la pestaña **📋 Lista**. El cronograma
recién creado aparece con el badge **⚪ sin validar**.

**Notas importantes**:

- El archivo se procesa fila por fila. Si una fila tiene error, se
  saltea; las demás se cargan igual. Revisá el resumen de errores.
- Podés subir **varios cronogramas al mismo ciclo** (por ejemplo,
  un borrador y una versión final). Después elegís cuál usar para
  generar el plan.
- La columna comisión se ignora al importar (ver advertencia
  arriba).

### Crear un cronograma vacío

**Cuándo hacerlo**: cuando no tenés archivo y vas a cargar los
horarios uno por uno desde el editor. También sirve para arrancar
un cronograma nuevo copiándolo desde otro existente y ajustándolo.

**Paso a paso**:

1. Andá a la pestaña **📤 Cargar**.
2. Elegí la opción **Crear vacío**.
3. Escribí el nombre y elegí el ciclo (mismo criterio que la carga
   por archivo).
4. Apretá **Crear cronograma vacío**.
5. El sistema crea un cronograma con cero filas.

**Verificación**: aparece en **📋 Lista** con 0 entradas y
**⚪ sin validar**.

**Siguiente paso**: andá a **✏️ Editar** y empezá a agregar filas.

### Editar horarios (mover, agregar, borrar)

**Cuándo hacerlo**: en cualquier momento después de crear el
cronograma. Es la pestaña donde más tiempo vas a pasar.

**Paso a paso — vista general**:

1. Andá a la pestaña **✏️ Editar**.
2. Elegí el cronograma del selector.
3. Elegí el modo:
   - **Por grupo**: filtrás por carrera, año, cuatri y opcionalmente
     tipo de materia y materias puntuales. Vas a ver el calendario
     de ese grupo curricular.
   - **Por materia**: elegís una materia y ves todos sus horarios
     en un calendario acotado a esa materia.

**Paso a paso — mover una fila (drag & drop)**:

1. Con el modo elegido, en el calendario, hacé click y arrastrá el
   bloque de una materia hacia otro día u horario.
2. El sistema guarda el cambio en el momento y muestra un toast:
   `{materia} movida a {dia} HH:MM-HH:MM`.

**Paso a paso — agregar una fila nueva**:

1. En el calendario, arrastrá con el mouse sobre un espacio vacío
   marcando el día y el rango horario.
2. Se abre un dialog con la materia, día y horas prefijados.
3. Cargá el **número de comisión**. Poné 0 si querés dejarla sin
   asignar por ahora.
4. Apretá **Confirmar**.
5. Si el número de comisión no existe todavía para esa materia en
   este cronograma, el sistema la crea automáticamente con valores
   por default (cupo 30, nombre auto-generado).

**Paso a paso — editar una fila existente**:

1. Hacé click sobre el bloque de la fila en el calendario.
2. Se abre un dialog más grande con todos los datos de la fila:
   - **Materia** (con buscador).
   - **Día** de la semana.
   - **Inicio** y **Fin**.
   - **Comisión** (con opción **➕ Crear nueva comisión…**).
   - **Tipo de clase**: `sin determinar`, `teorica`, `laboratorio`.
   - **Virtual**: `Heredar`, `Sí`, `No`.
3. Modificá lo que necesites.
4. Apretá **Guardar**, **Eliminar** o **Cancelar**.

**Paso a paso — modo "Por materia"**:

En el modo Por materia, además del calendario tenés tres tablas
abajo:

- **Tabla de horarios de la materia**: filas editables directas.
  Cambiar cualquier celda autoguarda al confirmar el cambio.
- **Tabla de comisiones**: podés editar nombre, cupo, carrera
  asignada, descripción. Borrar una comisión desde acá **está
  bloqueado** si tiene filas u horarios asociados; hay que
  reasignar o borrar primero.
- **Tabla resumen** de cuántas clases y horarios tiene cada
  comisión.

**Verificación**: los cambios aparecen reflejados en el calendario
y en las tablas. Además, en la pestaña **📋 Lista** el badge de
validación pasa a **🟡 validado pero modificado** (si estaba
validado) porque los cambios invalidan la última validación.

**Notas importantes**:

- El editor **autoguarda** cada cambio individual. No hay un botón
  de "guardar todo" — cada acción se persiste al momento.
- Si dos operadores editan el mismo cronograma en paralelo, los
  cambios se van pisando. Coordinen entre ustedes cuál está
  editando qué en cada momento.

### Asociar horarios a comisiones

**Cuándo hacerlo**: después de importar un archivo (porque las
comisiones del Excel no se persistieron), o cuando agregaste una
comisión nueva y hay que reasignarle filas.

**Modelo mental**:

Una **comisión** en un cronograma es un objeto con nombre, cupo y
opcionalmente carrera asignada. Cada fila del cronograma se
asocia a una comisión (o queda sin asignar).

Podés tener varias comisiones para la misma materia (por ejemplo,
Análisis I comisión 1 y Análisis I comisión 2), y podés reasignar
filas entre comisiones.

**Paso a paso**:

1. Andá a **✏️ Editar → modo "Por materia"**.
2. Elegí la materia.
3. En la tabla de comisiones (abajo del calendario), verificá que
   estén todas las comisiones que necesitás. Si falta alguna,
   agregala con un nombre y cupo.
4. Volvé a la tabla de horarios de la materia.
5. Para cada fila que no tiene comisión asignada (o tiene la
   equivocada), cambiá el valor de la columna **Comisión**.
6. Los cambios se autoguardan.

**Alternativa — al hacer click en una fila del calendario**:

1. Click en la fila.
2. En el dialog, cambiá el selector de Comisión.
3. Si querés crear una comisión nueva sobre la marcha, elegí
   **➕ Crear nueva comisión…** y completá el mini-formulario que
   aparece inline.
4. Guardá.

**Notas importantes**:

- Si borrás la última fila que apuntaba a una comisión, la
  comisión queda vacía pero **sigue existiendo** en la base como
  "modelo". Podés borrarla explícitamente desde la tabla de
  comisiones si no la vas a usar más.
- La **carrera asignada** de una comisión es un campo importante
  si más adelante se activa el ajuste de sedes por carrera: le
  dice al asignador de aulas a qué sedes puede ir esa comisión.

### Validar el cronograma contra los dictados del ciclo

**Cuándo hacerlo**: después de terminar de cargar el cronograma y
antes de generar el plan de cursada. Es tu chequeo de calidad.

**Prerequisito**: el ciclo tiene que tener dictados creados (si no,
la validación te avisa que no puede correr).

**Qué hace la validación**:

Compara las filas del cronograma con los dictados del ciclo y
calcula:

- **Cobertura**: cuántos dictados están cubiertos por al menos una
  fila del cronograma, cuántos faltan (dictado existe pero no hay
  filas), cuántos "extras" hay (filas en el cronograma que no
  corresponden a ningún dictado).
- **Partición teoría/laboratorio**: verifica que las horas
  cargadas coincidan con las horas esperadas para cada tipo de
  clase de la materia.
- **Conflictos horarios**: detecta si dos filas del mismo grupo
  curricular se pisan.
- **Breakdown de laboratorios**: cuántos labs están asignados
  fijos, cuántos son reserva, cuántos quedan pendientes.

**Paso a paso**:

1. Andá a la pestaña **✅ Validar**.
2. Elegí el ciclo y el cronograma en los selectores.
3. Revisá los toggles de arriba:
   - **Excluir optativas**: ignora las materias optativas en la
     comparación (útil si el forecast no las cubre).
   - **Auto-revalidar al cambiar**: revalida sola cuando cambia el
     cronograma o los dictados.
   - **Guardar cambios como copia**: si vas a hacer ajustes desde
     el panel de validación, los aplica a una copia en lugar del
     cronograma original.
4. Apretá **Validar cronograma**.
5. El sistema muestra un resumen con:
   - Métricas de cobertura (esperadas, cubiertas, faltantes,
     extras).
   - Un cartel verde o rojo con la partición teoría/lab.
   - Cantidad de conflictos horarios.
   - Expanders con **Detalle por carrera** y **Detalle por
     materia** con los issues encontrados.

**Cómo actuar sobre los resultados**:

- **Materias faltantes**: agregá las filas que faltan desde la
  pestaña Editar, o borrá el dictado desde Ciclos si en realidad
  la materia no se dicta.
- **Materias extras** (en el cronograma pero sin dictado): tenés
  dos opciones dentro del panel de validación:
  - **🟢 Activar**: crea el dictado en el ciclo. Es equivalente al
    "excepcional Crear" desde Ciclos.
  - **🌐 Activar y marcar virtual**: crea el dictado y encima lo
    marca como virtual.
- **Partición infactible**: revisá las horas de teoría y
  laboratorio de la materia en el catálogo, o ajustá el tipo de
  clase de cada fila del cronograma.
- **Conflictos horarios**: revisá las filas involucradas y movelas
  o ajustalas.

**Verificación**: repetí la validación hasta que el badge del
cronograma pase a **🟢 validado**.

**Notas importantes**:

- Los snapshots de validación son **inmutables**: cada corrida
  queda como registro histórico.
- El badge **🟡 validado pero modificado** aparece cuando el
  snapshot está desactualizado (cambió el cronograma o los
  dictados desde la última validación).
- Los conflictos horarios detectados **no se ignoran a nivel
  cronograma**: hay que corregirlos o dejarlos pasar sabiendo que
  después van a aparecer también al validar el plan.

### Duplicar un cronograma

**Cuándo hacerlo**: cuando querés probar cambios sobre una copia
sin tocar el original. Muy útil antes de reestructurar un
cronograma existente.

**Paso a paso**:

1. Andá a **📋 Lista**.
2. Abrí el expander del cronograma que querés duplicar.
3. En el bloque de duplicar, escribí un nombre para la copia (por
   default sugiere `{nombre} (copia)`).
4. Apretá **Duplicar**.
5. El sistema clona el cronograma con todas sus filas y sus
   comisiones.

**Verificación**: aparece el nuevo cronograma en la lista con las
mismas filas y comisiones que el original.

**Notas importantes**:

- Se clonan filas y comisiones. **No se clonan** los snapshots de
  validación — la copia arranca con **⚪ sin validar**.
- Los planes de cursada derivados **no** se duplican: apuntan
  siempre al cronograma original.

### Borrar un cronograma (advertencia sobre planes derivados)

> ⚠️ **Atención — puede dejar planes en estado inconsistente**
>
> Si un cronograma ya tiene un **plan de cursada derivado** (es
> decir, ya generaste un plan a partir de este cronograma), al
> borrar el cronograma:
>
> - **El plan de cursada NO se borra** — sigue existiendo.
> - **Pero el plan queda apuntando a un cronograma que ya no
>   existe**: pierde su ancla histórica.
> - Las comisiones "modelo" del cronograma quedan huérfanas en la
>   base (sin aparecer en ningún listado).
>
> **Antes de borrar un cronograma que tiene plan derivado**,
> considerá:
> - ¿Realmente querés borrar el histórico?
> - ¿Podés en su lugar renombrarlo (por ejemplo, agregarle
>   `[obsoleto]` al nombre) y dejarlo?
> - Si sí querés borrarlo, primero borrá el plan derivado. Va a
>   quedar todo más limpio.

**Cuándo hacerlo**: cuando el cronograma es un borrador que ya no
sirve y **no tiene plan de cursada derivado**.

**Paso a paso**:

1. Andá a **📋 Lista**.
2. Abrí el expander del cronograma.
3. En el bloque de eliminar, leé el mensaje `Esta accion es
   irreversible`.
4. Apretá **Eliminar**.

**Verificación**: el cronograma desaparece de la lista.

**Qué se borra**:

- El cronograma en sí.
- Todas sus filas.

**Qué NO se borra automáticamente**:

- Las comisiones "modelo" del cronograma (quedan huérfanas).
- Los planes de cursada derivados (quedan apuntando a un
  cronograma inexistente).

## Errores frecuentes y qué hacer

### "Columnas faltantes: ..."

**Síntoma**: al subir un archivo, aparece un error rojo con la
lista de columnas faltantes.

**Causa**: el archivo no tiene alguna de las columnas requeridas o
sus aliases (`codigo_materia`, `dia`, `hora_inicio`, `hora_fin`).

**Solución**: revisá los encabezados del Excel y renombralos si
hace falta. Recordá que se aceptan varios aliases (`materia`,
`dia_semana`, `inicio`, `fin`, etc.).

### "Fila N: Materia '{codigo}' no existe"

**Síntoma**: en el resumen del import aparece este error para una
o más filas.

**Causa**: el código de la materia en el archivo no matchea
ninguna materia del catálogo del sistema.

**Solución**: verificá el código en el módulo de Materias. Si
falta la materia en el catálogo, cargala primero. Si el código
está mal escrito en el Excel, corregí y volvé a subir.

### "Fila N: Codigo '{original}' resuelto por código alternativo"

**Síntoma**: warning amarillo al importar.

**Causa**: el código de la fila no matcheó directo con ninguna
materia del catálogo pero sí coincidió con un código alternativo
(típicamente el código externo de la facultad) y el sistema lo tomó
como fallback.

**Solución**: no es un error, es un aviso. Si preferís usar el
código interno, actualizá el Excel. Si el fallback te sirve,
dejalo pasar.

### "Este ciclo no tiene dictados creados"

**Síntoma**: al intentar validar, aparece un cartel rojo.

**Causa**: el ciclo del cronograma existe pero todavía no tiene
dictados creados.

**Solución**: andá a **📆 Ciclos → 📚 Dictados**, elegí el ciclo y
apretá **➕ Crear Dictados**.

### El cronograma tiene "extras" que no logro resolver

**Síntoma**: la validación muestra materias en el cronograma que
no están declaradas como dictados del ciclo.

**Causas posibles**:

1. La materia se dicta este ciclo pero olvidaste crear el dictado.
2. La materia se cargó por error en el cronograma.
3. La materia era un recursado excepcional que no está en la regla
   general.

**Solución**:

- **Caso 1 y 3**: apretá `🟢 Activar` en el panel de validación
  para crear el dictado. Si además es virtual, usá
  `🌐 Activar y marcar virtual`.
- **Caso 2**: andá a Editar y borrá las filas equivocadas.

### "No se puede borrar: la comisión tiene entries asociadas"

**Síntoma**: intentás borrar una comisión desde la tabla y no te
deja.

**Causa**: hay filas del cronograma (o horarios de un plan de
cursada) que apuntan a esa comisión.

**Solución**: primero reasigná las filas a otra comisión (o
borralas), y después intentá borrar la comisión otra vez.

### El badge pasó a "🟡 validado pero modificado" y no sé qué cambió

**Síntoma**: hiciste un cambio chico y el badge se puso amarillo.

**Causa**: cualquier modificación al cronograma o a los dictados
del ciclo invalida el snapshot de la última validación.

**Solución**: volvé a la pestaña Validar y apretá **Validar
cronograma** para refrescar el snapshot.

### Después de importar el archivo, las filas quedaron sin comisión

**Síntoma**: subiste un Excel que en el original tenía columna de
comisión, pero al abrir el cronograma en Editar todas las filas
están sin comisión asignada.

**Causa**: el importador **hoy ignora la columna comisión** del
archivo (ver advertencia en la sección de carga desde archivo).

**Solución**: asociá las comisiones manualmente desde la pestaña
Editar, ya sea en el modo Por materia (usando la columna
Comisión de la tabla) o abriendo cada fila desde el calendario.

## Preguntas frecuentes

### ¿Puedo tener varios cronogramas en el mismo ciclo?

Sí. El ciclo puede tener varios cronogramas (un borrador, una
versión con cambios, una final). Cuando generás el plan de
cursada elegís cuál usar.

### ¿Qué formato de archivo acepta el importador?

CSV (`.csv`), Excel moderno (`.xlsx`) y Excel viejo (`.xls`). Las
columnas mínimas son `codigo_materia`, `dia`, `hora_inicio`,
`hora_fin`. La columna `comision` se lee pero no se persiste — hay
que asociarla después manualmente.

### ¿Puedo importar horarios sin especificar un ciclo?

Sí, el sistema te deja subir un cronograma "standalone" sin ciclo
asociado. Sirve por ejemplo para importar borradores. Pero **no
vas a poder validarlo** hasta asociarlo a un ciclo, y el proceso
de asociación posterior no está expuesto en la interfaz — es más
práctico cargar el cronograma directamente con el ciclo elegido.

### ¿Qué pasa si dos filas se pisan en horario?

La validación las detecta como **conflicto horario**. Vas a verlo
en el detalle de la validación. No se puede "ignorar a nivel
cronograma"; hay que corregirlo (mover una de las dos filas o
cambiar la comisión).

### ¿Puedo tener una comisión que se dicte en varias sedes?

**No con la misma comisión**. Todas las filas de una comisión se
dictan en la misma sede (definida por la `carrera_asignada` de la
comisión). Si necesitás dos sedes para la misma materia, tenés
que crear dos comisiones distintas.

### ¿La modalidad virtual del horario pisa la del dictado?

Sí. La regla general es que **el nivel más específico manda**:
horario > dictado > materia. Si el horario dice "Presencial", eso
gana aunque el dictado esté marcado como virtual.

### ¿Cómo elimino una comisión que ya no uso?

Andá a **✏️ Editar → modo "Por materia"**, buscá la comisión en la
tabla de comisiones y borrala. Si tiene filas u horarios asociados
el sistema no te deja: primero reasignalos o borralos.

### ¿Qué es la diferencia entre "comisión del cronograma" y
"comisión del plan"?

En este sistema hay dos comisiones para la misma cosa lógica:

- La **comisión del cronograma** es la que definís acá. Funciona
  como **modelo**.
- La **comisión del plan de cursada** es un clon de la anterior,
  creada cuando se genera el plan. Es la que se asigna a alumnos
  y a aulas.

Esto permite que después puedas editar comisiones en el plan sin
alterar el cronograma histórico.

### ¿Se puede exportar el cronograma a Excel?

Hoy la aplicación **no ofrece un botón directo de exportación** desde
la pestaña Visualizar o Editar. Si necesitás sacar los datos del
cronograma en formato de planilla, hablalo con el equipo técnico —
se puede consultar la base de datos directamente. Una futura versión
puede incorporar esta funcionalidad.

### ¿Cómo veo el cronograma agrupado por comisión?

En la pestaña **👁 Visualizar → modo "Por materia"**, cada
comisión aparece con un color distinto en el calendario.

## Términos importantes de este módulo

- **Cronograma**: conjunto de filas horarias del cuatrimestre.
  Corresponde a la representación digital del Excel de horarios.
- **Fila del cronograma**: unidad mínima. Tiene día, hora de
  inicio, hora de fin, materia, comisión (opcional) y tipo de
  clase (opcional).
- **Comisión modelo (o comisión del cronograma)**: comisión
  declarada dentro del cronograma. Sirve como plantilla que se
  clona cuando se genera el plan de cursada.
- **Comisión del plan**: clon vivo de la comisión modelo, creada
  cuando se genera el plan. Es la que se asigna a alumnos y aulas.
- **Modo Por grupo**: vista del cronograma filtrada por carrera +
  año + cuatri. Sirve para pensar en cómo cursa un año concreto
  de una carrera.
- **Modo Por materia**: vista del cronograma filtrada a una
  materia. Sirve para editar sus comisiones y horarios.
- **Cobertura**: métrica de la validación. Mide qué porcentaje de
  los dictados del ciclo están cubiertos por al menos una fila
  del cronograma.
- **Materia faltante**: dictado del ciclo que no tiene ninguna
  fila en el cronograma.
- **Materia extra (no esperada)**: fila del cronograma cuya
  materia no tiene dictado en el ciclo.
- **Partición teoría/laboratorio**: chequeo de que las horas
  cargadas de cada tipo de clase coincidan con las esperadas para
  la materia.
- **Conflicto horario**: dos filas del mismo grupo curricular que
  se pisan en día y hora.
- **Snapshot de validación**: registro inmutable de una corrida
  de validación. Cada validación guarda una copia con las
  métricas del momento.
- **Badge de validación**: ícono que resume el estado del
  cronograma respecto de la última validación (⚪ 🟡 🔴 🟢).
- **Standalone**: cronograma sin ciclo asociado. Se puede crear
  pero no se puede validar hasta enlazarlo a un ciclo.
- **Duplicar**: clonar un cronograma con todas sus filas y
  comisiones. Útil para probar cambios sin tocar el original.
- **Autoguardado**: mecanismo por el cual cada cambio en el
  editor se persiste al momento, sin necesidad de un botón
  "guardar todo".
