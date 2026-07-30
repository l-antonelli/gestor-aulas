# Inscriptos

## ¿Para qué sirve?

La página **📈 Inscriptos Históricos** te permite ver y mantener la serie
histórica de inscriptos por materia. Cada fila representa un dato del
tipo *"en la materia X, en el año Y, cuatrimestre Z, hubo N inscriptos"*.

A partir de esos datos, el sistema calcula una **estimación** de cuántos
alumnos se van a inscribir en cada materia del próximo cuatrimestre. Ese
número alimenta después al asignador de aulas para elegir salones con
capacidad adecuada.

En resumen, este módulo te sirve para:

- Consultar cuántos alumnos tuvo históricamente cada materia.
- Corregir o completar datos que faltan o son incorrectos.
- Comparar tres métodos distintos de estimación para el próximo
  cuatrimestre.
- Asociar códigos del Excel de inscriptos que no matchearon
  automáticamente con las materias del sistema.

> Importante: esta página no ejecuta la estimación por sí sola ni la
> aplica al asignador. Sólo administra los datos históricos y muestra las
> proyecciones a modo informativo. La estimación efectiva que usa el
> asignador se elige desde **📊 Planes → Detalle** de cada plan.

---

## ¿Cuándo vas a usar este módulo?

Vas a entrar a **Inscriptos** en estos momentos típicos:

- **Después de reinstalar el sistema o resetear la base**: para volver a
  cargar la serie histórica desde el Excel maestro corriendo el script
  correspondiente.
- **Al iniciar un nuevo cuatrimestre**, para verificar que la serie
  histórica esté al día antes de generar el plan de cursada.
- **Cuando el asignador reporta capacidades raras**: si una materia
  aparece con esperados extraños, capaz que hay un dato viejo mal
  cargado o falta un año.
- **Cuando hay materias nuevas** que no tienen serie histórica y querés
  cargarles datos manualmente para que la estimación tenga base.
- **Para revisar códigos "sin matchear"**: cuando el Excel de la
  facultad usa un código que el sistema no reconoce y hay que asociarlo
  a una materia existente.

No es una página que uses todos los días. Es más bien un módulo de
mantenimiento: se toca al principio de cada cuatrimestre y después queda
tranquilo, salvo correcciones puntuales.

---

## Cómo se relaciona con el resto

Los datos de esta página alimentan la estimación de inscriptos que usa
el asignador de aulas. La cadena de dependencias es la siguiente:

1. **Vos cargás** la serie histórica acá (por script o a mano).
2. El sistema calcula, para cada materia del plan, un **valor esperado
   de inscriptos** basado en esa historia.
3. Ese valor se **reparte entre las comisiones** de la materia según el
   peso de cada una.
4. El asignador usa esos esperados por comisión para elegir aulas con
   capacidad adecuada.

> **Atajo importante**: si en la página **📊 Planes → Detalle** de una
> materia setés un "Total esperado (manual)", ese valor **le gana a la
> estimación calculada desde acá**. Es decir: si viste que el forecast
> automático da un número raro, podés pisarlo desde el plan, y los
> cambios que hagas después en Inscriptos no se van a propagar hasta
> que saques ese override manual desde el plan.

---

## Modelo mental

### La serie histórica

Pensá a la **serie histórica** como una tabla de tres columnas:
`materia → año → cuatrimestre → cantidad de inscriptos`. Cada combinación
(materia, año, cuatri) es única: no puede haber dos filas para la misma
materia en el mismo cuatri del mismo año. El sistema tiene tres
cuatrimestres válidos: `1C`, `2C` y `Anual` (para las materias que se
dictan durante todo el año).

### La estimación (forecast)

A partir de la serie, el sistema calcula una **estimación** para años
futuros. Se ofrecen **tres métodos** distintos, cada uno con su propia
lógica:

- **Media móvil**: promedia los últimos años para estimar el próximo. Es
  el método más conservador. Sirve bien cuando la matrícula es estable
  año contra año.
- **Drift (lineal)**: ajusta una tendencia lineal a los datos. Si la
  materia viene creciendo o cayendo, este método captura esa pendiente.
- **SES (suavizado exponencial simple)**: le da más peso a los años
  recientes que a los viejos. Sirve cuando la matrícula está cambiando
  y querés seguir la tendencia reciente sin ser demasiado volátil.

En el gráfico de cada materia vas a ver los tres métodos superpuestos.
Debajo del gráfico aparecen las **métricas** de cada método: el valor
proyectado, el parámetro relevante (peso de suavizado para SES,
pendiente para drift, ventana para media móvil) y el error interno.

> Si la materia tiene menos de dos puntos en la historia, sólo se
> muestra la media móvil. Los otros métodos necesitan al menos dos años
> para tener sentido.

### Override manual del esperado

Hay una tercera forma de decidir el esperado de una materia: **pisar la
estimación con un valor fijo**. Eso se hace desde **📊 Planes → Detalle**
(no desde acá) y **le gana a los tres métodos**. Cuando hay override
manual, el sistema muestra "Total esperado (manual)" en el detalle del
plan, y los cambios que hagas en la serie histórica quedan sin efecto
hasta que saques el override.

---

## Recorrido rápido de la página

La página se divide en tres bloques principales, todos gobernados por
los filtros del sidebar.

**Sidebar (filtros)**:

- **Buscar**: por código o nombre de materia.
- **Cuatrimestre**: `Todos`, `1C` o `2C`. **Cuidado**: no incluye
  "Anual"; si necesitás filtrar sólo las anuales, dejalo en `Todos` y
  usá la búsqueda por nombre.
- **Año target del forecast**: hasta qué año se extienden las líneas de
  estimación en el gráfico (default: 2026).
- **Carrera**: multiselect para filtrar materias por carrera.
- **Año del plan**: filtro por el año en el plan de estudios.
- **Optativas**: `Incluir`, `Solo` o `Excluir`.
- **Período**: `cuatrimestral` o `anual`.
- **Modalidad**: `Presencial` o `Virtual` (según el catálogo de
  materia).

**Toggles de visibilidad**: te permiten mostrar u ocultar cada una de
las tres secciones.

**Sección 1 — Materias con datos**: lista las materias que ya tienen
serie histórica cargada. Cada materia aparece como un desplegable
(expander) con la tabla editable de años/cuatris/inscriptos y el
gráfico con las tres estimaciones.

**Sección 2 — Materias sin datos**: lista las materias del catálogo que
todavía no tienen ninguna fila cargada. Podés agregar filas a mano acá.

**Sección 3 — Sin matchear**: lista códigos del Excel de la facultad
que el sistema no pudo asociar automáticamente a ninguna materia. Para
cada código sin matchear te ofrece un selector para elegir la materia
destino y un botón para asociar.

---

## ⚠️ Advertencia importante — pérdida de datos al filtrar por cuatri

> **Cuidado**: por un problema conocido, si tenés filtrado el
> cuatrimestre (por ejemplo, "1C") y guardás cambios en una materia de
> la sección **"Materias con datos"**, los datos del otro cuatri
> (`2C` y `Anual`) de esa materia **se van a perder sin aviso**.

Esto pasa porque el guardado borra todo lo que tenía esa materia y
reescribe únicamente lo visible en el editor. Como el filtro esconde
las filas del otro cuatri, esas filas se pierden.

**Como precaución, siempre trabajá con el filtro "Cuatrimestre" puesto
en "Todos" antes de guardar cambios en una materia.**

Si necesitás concentrarte visualmente en un cuatri, usá la búsqueda por
código/nombre y dejá el cuatri en `Todos`.

---

## Tareas comunes

### Cargar la serie histórica desde el Excel maestro

La carga inicial (o la reinicialización) se hace desde la línea de
comandos, no desde la UI. Los pasos son:

1. Asegurate de que el Excel maestro esté en su ruta esperada:
   `data/input/inscriptos/final_df.xlsx`. El archivo debe tener las
   columnas `codigo`, `actividad`, `year`, `period` y `cant._inscriptos`.
2. Desde una terminal, en la raíz del proyecto, correr:

   ```bash
   python -m scripts.load_inscriptos
   ```

3. Si querés vaciar la serie previa antes de cargar, usá:

   ```bash
   python -m scripts.load_inscriptos --reset
   ```

   > Ojo: `--reset` borra **toda** la tabla de inscriptos históricos.
   > Sin `--reset` el script hace *upsert*: si ya existía la
   > combinación (materia, año, cuatri), pisa el valor; si no, la crea.

4. Cuando termine, entrá a la página de Inscriptos y verificá que las
   materias muestren datos.

El script tiene un mecanismo de matcheo por capas para relacionar los
códigos del Excel con las materias del sistema:

- Match directo por código idéntico.
- Normalización por formato según reglas hardcodeadas por carrera (por
  ejemplo, `IA11 → IA 1.1` para TUIA, `PF14 → PF1.4` para Profesorado
  de Física, etc.).
- Match por nombre dentro de la misma carrera.
- Tabla de correcciones manuales para tipos de nombre (por ejemplo,
  "Algebra" ↔ "Álgebra", "del Software" ↔ "de Software").

Los códigos que no matchean por ninguna de esas capas quedan disponibles
en la sección "Sin matchear" de la UI para que los asocies a mano.

### Ver la proyección de inscriptos para una materia

1. Entrá a la página **📈 Inscriptos Históricos**.
2. Buscá la materia por código o nombre.
3. Expandí el desplegable de la materia.
4. Vas a ver:
   - La **tabla histórica** con año, cuatri e inscriptos.
   - El **gráfico** con la serie histórica y las tres estimaciones
     superpuestas hasta el año target elegido en el sidebar.
   - Las **métricas** debajo del gráfico, una por método, con el valor
     proyectado y el parámetro relevante.

### Ver los tres métodos de forecast comparados

Cada expander de materia con datos muestra en su gráfico tres líneas de
proyección superpuestas (una por método): media móvil, drift lineal y
SES. Debajo del gráfico, tres cajitas con el valor proyectado de cada
método, para que puedas compararlos rápidamente.

Los tres métodos se calculan siempre. La elección de **cuál se usa en
la asignación** se hace más adelante, desde **📊 Planes → Detalle** del
plan del ciclo que corresponda.

### Editar o corregir un dato histórico

1. En **"Materias con datos"**, expandí la materia.
2. Editá el valor de inscriptos directamente en la tabla del editor.
3. Podés cambiar el año, el cuatri o la cantidad.
4. Apretá **Guardar**.

> Recordatorio: antes de guardar, **dejá el filtro de cuatrimestre en
> "Todos"** para no perder datos del otro cuatri (ver advertencia
> arriba).

### Agregar datos manualmente a una materia sin serie histórica

1. En la sección **"Materias sin datos de inscriptos"**, buscá la
   materia.
2. En el editor vacío, agregá una o más filas con año, cuatri e
   inscriptos.
3. Apretá **Guardar**. La materia va a pasar automáticamente a la
   sección "Materias con datos" en el próximo refresco.

### Asociar un código del Excel que no matcheó automáticamente

Cuando un código del Excel de inscriptos no matchea con ninguna materia
del sistema, aparece en la sección **"Sin matchear"** con su propia
tabla de datos y su gráfico.

1. Verificá los datos del código sin matchear en su tabla y gráfico.
2. Elegí la **materia destino** en el selector "Materia destino".
3. Apretá **Asociar**.

Los registros del código se insertan bajo el código de la materia
elegida.

> **Advertencia**: si la materia destino ya tenía datos para (año,
> cuatri), el asociador **suma** los nuevos inscriptos a los
> existentes, no reemplaza. Verificá antes de asociar que no haya
> superposición, o el número final va a quedar inflado sin que el
> sistema te avise.

### Filtrar por carrera / año / cuatri / modalidad

Todos los filtros están en el sidebar izquierdo:

- **Buscar**: por código o parte del nombre.
- **Cuatrimestre**: `Todos`, `1C` o `2C`.
- **Carrera**: multiselect. Materias que no pertenecen a ningún plan
  ("huérfanas") sólo aparecen si el filtro incluye todas las carreras.
- **Año del plan**: filtra materias por año en el plan de estudios.
- **Optativas**: `Incluir`, `Solo` o `Excluir`.
- **Período**: `cuatrimestral` o `anual` (del catálogo de la materia).
- **Modalidad**: `Presencial` o `Virtual` (del catálogo, no del dictado
  del ciclo).

Los filtros se aplican en cascada: primero se filtran las materias
visibles, después las tres secciones se recalculan sobre ese subconjunto.

---

## Errores frecuentes y qué hacer

### Guardé cambios y ahora faltan filas del otro cuatri

Es el problema descripto en la advertencia arriba: guardaste con el
filtro de cuatri activo y las filas del otro cuatri se borraron. La
única forma de recuperarlas es:

- Si hiciste backup reciente de `data/database.db`, restaurá desde el
  backup.
- Si tenés el Excel maestro, correr `python -m scripts.load_inscriptos`
  (sin `--reset`) para reinsertar los valores del Excel (el upsert
  respeta las filas que quedaron).
- Si no hay backup ni Excel, tenés que cargar los datos a mano.

**Prevención**: siempre poné el filtro de cuatrimestre en "Todos" antes
de guardar.

### Asocié un código y el número quedó duplicado

Si asociaste un código del Excel a una materia que ya tenía datos para
esos (año, cuatri), los valores se sumaron. No hay undo automático:

1. Editá manualmente las filas duplicadas en la sección "Materias con
   datos" de la materia destino.
2. Restá los valores del código asociado.
3. Guardá (con el filtro de cuatrimestre en "Todos").

### La sección "Sin matchear" aparece vacía

Puede ser porque:

- **Todos los códigos del Excel matchearon**: caso ideal.
- **El Excel `final_df.xlsx` no existe** en `data/input/inscriptos/`: la
  sección queda vacía silenciosamente. Verificá que el archivo esté en
  la ruta correcta.

### El gráfico dice "Sin datos para graficar"

Significa que la materia no tiene serie histórica (aunque el catálogo
la reconozca). Chequeá:

- Que hayas corrido `python -m scripts.load_inscriptos` alguna vez.
- Que el filtro superior no esté escondiendo las filas (por ejemplo,
  si la materia sólo tiene datos "Anuales" y filtraste por `1C`, no vas
  a ver nada porque el filtro no ofrece "Anual" explícitamente).

### El asignador dice esperados raros aunque cambié los datos acá

Muy probablemente hay un **override manual** activo en el plan.
Verificá en **📊 Planes → Detalle → [materia] → Total esperado
(manual)**. Si hay un número puesto ahí, el asignador lo usa y los
cambios en la serie histórica no le llegan. Sacá el override o
actualizá el valor manual.

---

## Preguntas frecuentes

### ¿Por qué la materia X no tiene datos históricos?

Puede ser por varias razones:

- La materia es **nueva** en el plan de estudios y no tenía dictados en
  años previos.
- La materia **cambió de código** entre años y el matcheo automático no
  detectó la equivalencia. Revisá la sección "Sin matchear".
- El script de carga inicial nunca se corrió: hacelo con
  `python -m scripts.load_inscriptos`.
- El Excel maestro `final_df.xlsx` no incluye esa materia.

### ¿Qué método de forecast conviene?

Depende del comportamiento de la matrícula de la materia:

- **Media móvil**: para materias con matrícula estable año contra año.
  Es el método más conservador.
- **Drift (lineal)**: para materias con tendencia clara (crecimiento o
  caída sostenido). Requiere al menos dos años de historia.
- **SES**: para materias con cambios recientes que querés capturar
  rápido. Requiere al menos dos años.

La elección efectiva del método que usa el asignador se hace desde
**📊 Planes → Detalle** del plan del ciclo, no desde acá. Podés dejar
un default por plan y sobreescribirlo por materia si hay excepciones.

### ¿Cómo hago para pisar la estimación con un valor manual?

No se hace desde esta página. El override manual (**"Total esperado
(manual)"**) se setea desde **📊 Planes → Detalle** → seleccionar la
materia → cargar el valor. Ese número le gana a los tres métodos de
estimación y le gana a lo que haya en la serie histórica.

### Cambio los datos acá y el asignador no lo refleja, ¿por qué?

Casi seguro hay un **override manual** puesto en el plan. Cuando el
plan tiene un "Total esperado (manual)" para una materia, la estimación
calculada desde esta página se ignora completamente. Sacá el override
desde **📊 Planes → Detalle** para que vuelva a mandar la serie
histórica.

### Los datos de esta página, ¿quedan en el historial?

**No**. Todas las ediciones que hagas en Inscriptos (guardar, asociar,
cargar por script) son silenciosas: no dejan rastro en la página
**📜 Historial**. Si querés tener trazabilidad de los cambios, hacé
backup periódico de `data/database.db` antes de tocar la serie
histórica.

### ¿Puedo ver sólo las materias "anuales"?

El filtro superior de cuatrimestre sólo ofrece `Todos`, `1C` y `2C`. No
tiene una opción explícita para "Anual". Como workaround, dejá el filtro
en `Todos` y usá la búsqueda por nombre o filtrá por período =
`anual`.

### ¿Puedo cargar un Excel nuevo desde la UI?

No. La carga bulk sigue siendo por línea de comandos con el script
`load_inscriptos`. Si reemplazás el archivo `final_df.xlsx` y volvés a
correr el script, la sección "Sin matchear" se actualiza automáticamente
la próxima vez que abras la página.

---

## Términos importantes de este módulo

- **Serie histórica**: la tabla de datos históricos por (materia, año,
  cuatri). Es la base de la estimación.
- **Estimación (o forecast)**: valor proyectado de inscriptos para un
  año futuro, calculado a partir de la serie histórica.
- **Método de estimación**: la fórmula usada para proyectar. Hay tres:
  media móvil, drift lineal y SES.
- **Override manual de esperados**: un valor fijo que se setea desde
  el detalle del plan y le gana a los tres métodos. Cuando está puesto,
  la serie histórica no se usa para esa materia.
- **Sin matchear**: código del Excel de la facultad que el sistema no
  pudo asociar automáticamente a ninguna materia. Requiere asociación
  manual.
- **Asociar**: acción de vincular un código sin matchear a una materia
  del sistema. Suma los inscriptos existentes si la materia destino
  ya tenía datos para ese (año, cuatri).
- **Cuatrimestre "Anual"**: valor válido en la serie histórica para
  materias que se dictan durante todo el año. El filtro superior no
  lo incluye explícitamente; dejar el filtro en "Todos" para que
  aparezcan.
