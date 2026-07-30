# Carreras

## ¿Para qué sirve?

La página **🎓 Carreras** es el catálogo maestro de carreras
universitarias del sistema. Es donde se dan de alta las carreras (con
su código, nombre, título otorgado y duración), se gestionan las
versiones de su plan de estudios (qué materias componen la carrera en
qué año y cuatrimestre) y se configuran las sedes habilitadas en las
que se puede dictar cada una.

Es una de las tres entradas del catálogo maestro, junto con Materias y
Aulas.

## ¿Cuándo vas a usar este módulo?

- **Setup inicial**: después de la carga masiva, para completar los
  nombres reales de las carreras (los Excel maestros dejan el código
  como placeholder si el archivo de metadata no está actualizado),
  ajustar duración, cantidad de materias esperadas, y configurar las
  sedes habilitadas de cada una.
- **Apertura de una carrera nueva**: cuando la facultad lanza una
  carrera que no existía y hay que darla de alta.
- **Actualización de un plan de estudios**: cuando cambia oficialmente
  el plan (por ejemplo, se aprueba un plan 2027 que reemplaza al 2020),
  se crea una versión nueva del plan y se le asocian las materias.
- **Cambio de regla de recursado**: cuando una carrera pasa a dictar
  o dejar de dictar materias como recursado.
- **Habilitación de sedes**: cuando una carrera empieza a dictar en un
  edificio nuevo o deja de hacerlo en uno viejo.
- **Baja de una carrera**: cuando la facultad cierra un plan y hay que
  archivarlo.

## Cómo se relaciona con el resto

- **Alimenta Materias**: las materias del catálogo se asocian a una o
  varias carreras dentro de una versión de plan de estudios. Sin
  carreras cargadas no se pueden dar de alta materias nuevas desde la
  otra página.
- **Alimenta Ciclos**: cada ciclo asocia una versión de plan de cada
  carrera para saber qué materias ofrecer.
- **Alimenta Planes de cursada**: los planes se arman a partir de las
  materias que la versión de plan asociada al ciclo tenga.
- **Interactúa con Aulas y Sedes**: cada carrera puede tener una lista
  de sedes habilitadas. El asignador de aulas respeta esta lista para
  las materias exclusivas de la carrera.
- **Depende de Aulas y Sedes**: para configurar sedes habilitadas, las
  sedes tienen que existir antes.

## Recorrido rápido de la página

Tres solapas:

- **📋 Lista**: vista principal, con todas las carreras cargadas. Se
  puede editar, eliminar y configurar las sedes habilitadas de cada
  una. También muestra la barra de completitud (cuánto le falta a la
  carrera para tener todas sus materias asignadas).
- **➕ Crear**: formulario para dar de alta una carrera nueva.
- **📚 Materias por Carrera** (planes de estudio): el editor del plan
  de estudios. Se elige carrera + versión de plan + año, y se puede
  asociar / desasociar materias en las columnas de Anuales, 1er
  Cuatrimestre y 2do Cuatrimestre. También se crean nuevas versiones
  del plan.

## Tareas comunes

### Crear una carrera nueva

1. Andá a la solapa **➕ Crear**.
2. Completá los datos:
   - **Código**: identificador único de la carrera (por ejemplo, "IE",
     "LCC", "IM"). No puede repetirse y no se puede cambiar después.
   - **Nombre**: nombre completo de la carrera (por ejemplo,
     "Ingeniería Electrónica").
   - **Título Otorgado**: título académico que se obtiene al completar
     la carrera.
   - **Duración (años)**: mínimo 1. Cantidad de años teóricos que dura
     el plan.
   - **Cantidad de Materias** (opcional): cantidad total esperada de
     materias obligatorias. Sirve para calcular la barra de
     completitud. Si lo dejás vacío, la carrera va a mostrar
     "Cantidad no definida" hasta que lo completes.
   - **Dicta recursado**: tildá si la carrera dicta las materias como
     recursado en el cuatrimestre opuesto. Se puede sobrescribir a
     nivel materia con una excepción puntual.
3. Apretá **Crear Carrera**.
4. Verificación: la carrera aparece en la solapa **📋 Lista** con los
   datos que le cargaste.

**Paso siguiente crítico** (no se hace automáticamente): antes de
poder asociar materias a esta carrera, tenés que crear la **primera
versión del plan de estudios**. Andá a la solapa **📚 Materias por
Carrera**, elegí la carrera nueva y usá el botón **"Nueva Version"**
para crear una versión con nombre (por ejemplo, "Plan 2020"). Sin esto,
cualquier intento de asociarle materias va a fallar con "No se encontró
plan de estudios para la carrera 'X'".

### Editar los datos de una carrera

1. En la solapa **📋 Lista**, desplegá la carrera y apretá **✏️ Editar**.
2. Modificá los campos que necesites: Nombre, Título Otorgado, Duración,
   Cantidad de Materias o Dicta recursado. El código queda deshabilitado
   y no se puede cambiar.
3. Guardá los cambios.
4. Verificación: al volver a la lista, los datos se refrescan.

**Nota**: solo el cambio del flag "Dicta recursado" queda registrado
en el Historial. Cambios en nombre, título o duración no se auditan.

### Configurar las sedes habilitadas de una carrera

Esta es la lista de sedes en las que el asignador puede colocar las
materias exclusivas de esta carrera.

1. En la solapa **📋 Lista**, desplegá la carrera.
2. En la sección **"🏛️ Sedes habilitadas"** vas a ver un multiselect
   con todas las sedes cargadas en el sistema.
3. Marcá las sedes en las que esta carrera efectivamente dicta sus
   materias exclusivas.
4. Cuando hagas cambios respecto del estado guardado, va a aparecer un
   botón **"💾 Guardar sedes"**. Apretalo para confirmar.
5. Verificación: al recargar la carrera, las sedes seleccionadas siguen
   marcadas.

**Regla clave**: si no seleccionás ninguna sede (multiselect vacío), el
sistema asume **"todas las sedes"**, no "ninguna sede". Puede sorprender,
pero es así: sin configuración explícita, el asignador tiene libertad
total. La restricción de sedes recién se activa cuando marcás al menos
una.

**Materias comunes vs exclusivas**: esta configuración solo aplica a
las materias exclusivas de la carrera. Las materias comunes (que
aparecen en dos o más carreras) se asignan a la sede "default de
comunes" configurada globalmente en la página de Aulas y Sedes.

### Crear una nueva versión del plan de estudios

Sirve para preservar el plan viejo mientras armás uno nuevo, o para
tener plan histórico + plan vigente conviviendo.

1. Andá a la solapa **📚 Materias por Carrera** y elegí la carrera.
2. En el selector de versión de plan, apretá **"Nueva Version"**.
3. Se abre un formulario:
   - **Nombre**: por ejemplo, "Plan 2027" o "Plan 2020 reformado".
   - **Descripción**: opcional, notas sobre el plan.
   - **Copiar materias de la versión actual**: por default tildado. Si
     lo dejás así, la versión nueva arranca con las mismas materias
     asociadas que la versión actual (mismos año, cuatrimestre y flag
     de optativa). Es útil para partir de una base y modificar.
4. Confirmá.
5. Verificación: la versión nueva aparece en el selector, con las
   materias copiadas si tildaste la opción.

**Efecto colateral**: cuando cambiás de versión en el selector, todas
las asociaciones que edites (agregar/desasociar materias) se hacen
sobre esa versión. Los ciclos que estén apuntando a otra versión no
se ven afectados.

### Editar el nombre o descripción de una versión existente

1. En la solapa **📚 Materias por Carrera**, elegí la carrera y la
   versión.
2. Desplegá el expander **"Editar version"**.
3. Modificá nombre o descripción.
4. Guardá.

**Limitación**: solo se puede editar el nombre y la descripción. Hoy
no hay una opción en la interfaz para borrar una versión completa —
eso se hace desde el equipo técnico si hace falta.

### Asociar una materia a un plan de estudios

1. En la solapa **📚 Materias por Carrera**, elegí la carrera y la
   versión del plan.
2. Elegí el **año del plan** (1 a 6) al que la querés asociar.
3. Vas a ver tres columnas: **Anuales**, **1er Cuatrimestre** y **2do
   Cuatrimestre**.
4. Debajo de cada columna hay una sección **"Asociar Materia"** con un
   selector. Elegí la materia y confirmá.
5. Verificación: la materia aparece en la columna correspondiente del
   año elegido.

**Nota**: el selector solo muestra las materias que coinciden con el
período de la columna (una materia cuatrimestral no aparece en la
columna Anuales, y viceversa). Además, las materias ya asociadas al
año + período se filtran para que no las dupliques.

### Desasociar una materia de un plan

1. En la solapa **📚 Materias por Carrera**, elegí la carrera, la
   versión y el año.
2. Buscá la materia en la columna correspondiente (Anuales, 1er C o
   2do C).
3. Apretá la "X" al lado del código.
4. Verificación: la materia desaparece de la columna.

**Precaución**: si esa asociación ya está en uso por un ciclo activo
(hay dictados, comisiones o cronogramas que la referencian), desasociarla
puede dejar información inconsistente. Ideal es hacerlo antes de crear
dictados o después de haber cerrado el ciclo.

### Eliminar una carrera

1. En la solapa **📋 Lista**, desplegá la carrera y apretá **🗑️ Eliminar**.
2. Aparece una pantalla de confirmación.
3. Apretá **🗑️ Confirmar Eliminación**.
4. Verificación: la carrera desaparece de la lista.

**Restricciones**:

- Si la carrera tiene materias asociadas, el sistema muestra el error
  "No se puede eliminar: la carrera tiene N materia(s) asociada(s).
  Primero debe desasociar todas las materias de esta carrera." Tenés
  que ir a la solapa **📚 Materias por Carrera**, quitar todas las
  asociaciones año por año, y volver a intentar.
- Aún después de desasociar todas las materias, si la carrera tiene
  versiones de plan de estudios creadas, la eliminación puede fallar
  con un error del sistema. Hoy la interfaz no ofrece una opción para
  borrar versiones de plan — eso lo hace el equipo técnico manualmente.

**Nota**: la ausencia de una herramienta para desasociar en bulk todas
las materias de una carrera hace que borrarla sea un proceso tedioso.
Si necesitás archivarla en la práctica pero no borrarla, considerá
simplemente no asociarla a ciclos nuevos.

## Errores frecuentes y qué hacer

| Mensaje | ¿Qué significa? | Cómo lo resolvés |
|---|---|---|
| "No se puede eliminar: la carrera tiene N materia(s) asociada(s). Primero debe desasociar todas las materias de esta carrera." | La carrera tiene materias en su plan de estudios | Andá a Materias por Carrera y desasociá todas las materias, año por año |
| Error "N plan version(s) exist. Delete plan versions first." | La carrera no tiene materias pero sí versiones de plan de estudios | Contactá al equipo técnico para borrar las versiones (no hay opción en la interfaz) |
| "Esta carrera no tiene versiones de plan de estudio." | Elegiste una carrera en Materias por Carrera pero nunca se creó una versión | Apretá "Nueva Version" para crear la primera |
| "El nombre no puede estar vacio" | Al crear una versión nueva de plan dejaste el campo Nombre vacío | Escribí un nombre |
| "No se encontró plan de estudios para la carrera 'X'" | Al asociar una materia a esta carrera desde otra página, la carrera no tiene versión de plan | Andá a Materias por Carrera y creá una versión con "Nueva Version" |
| "Carrera con código '{codigo}' no encontrada" | La carrera que estabas editando fue borrada por otra sesión | Volvé a la lista y refrescá |
| "No se pudo actualizar la carrera" | El guardado falló silenciosamente | Reintentá; si persiste, avisale al equipo |

## Preguntas frecuentes

**¿Puedo tener dos carreras con el mismo código?**
No. El código es único a nivel sistema.

**¿Puedo cambiar el código de una carrera?**
No. Una vez creada, el código queda fijo. Si te equivocaste, hay que
crear una nueva con el código correcto y (eventualmente) mover las
materias asociadas.

**¿Qué es "Cantidad de Materias" y por qué es opcional?**
Es la cantidad total esperada de materias obligatorias de la carrera
(no cuenta optativas). Sirve para mostrar la barra de progreso en la
lista y en el panel de completitud de la página de Materias. Si lo
dejás vacío, no se muestra progreso pero la carrera funciona igual.

**¿Puedo tener dos versiones de plan de estudios activas al mismo
tiempo?**
Sí. La carrera puede tener cuantas versiones históricas quieras. La
"vigente" para el asignador de aulas es la que le asignes a cada ciclo
puntual — un ciclo puede usar la versión 2020 y otro puede usar la
2027 simultáneamente.

**¿Qué pasa con las materias si borro una versión de plan?**
Las asociaciones de materia-carrera de esa versión desaparecen. Las
materias en sí (a nivel catálogo) siguen existiendo. Hoy no hay opción
en la interfaz para borrar versiones — se hace desde el equipo técnico.

**¿Qué diferencia hay entre "Dicta recursado" a nivel carrera y a nivel
materia?**
La carrera define la regla general: si tildado, todas sus materias
exclusivas se ofrecen también como recursado en el cuatrimestre opuesto
al que les toca según el plan. La materia puede sobrescribir esa regla
con su propio flag (desde la página de Materias, campo "Recursado" en
la edición). Es un mecanismo jerárquico: primero materia, después
carrera, para decidir si generar el dictado.

**¿Por qué las carreras aparecen con el nombre igual al código (por
ejemplo, "IE - IE")?**
Porque los nombres reales se cargan aparte del archivo de metadata
inicial. Si ese archivo no está actualizado o falta, el sistema deja
el código como placeholder. Podés editar cada carrera y ponerle el
nombre real desde la solapa **📋 Lista → ✏️ Editar**.

**¿Puedo asociar una materia sin haber creado un plan de estudios?**
No. La asociación materia-carrera vive dentro de una versión de plan.
Si la carrera no tiene ninguna versión, no hay dónde poner la
asociación. Crear la primera versión desde **📚 Materias por Carrera →
Nueva Version** es un paso obligatorio después de crear la carrera.

**¿Qué pasa si no configuro sedes habilitadas para una carrera?**
El sistema asume "todas las sedes" para las materias exclusivas de esa
carrera. Es decir: sin restricción. Recién configurando al menos una,
la restricción se activa.

**¿La configuración de sedes habilitadas afecta a las materias
comunes?**
No. Las materias comunes (compartidas por dos o más carreras) se
asignan a la sede "default de comunes" configurada en Aulas y Sedes,
sin importar las sedes habilitadas de las carreras que la comparten.

**¿Dónde veo el histórico de cambios de una carrera?**
En la página **📜 Historial**. Solo se auditan altas, bajas y cambios
en el flag "Dicta recursado". Nombre, título y duración no quedan en
el histórico.

## Términos importantes de este módulo

- **Carrera**: entrada del catálogo maestro con código, nombre, título
  otorgado, duración y cantidad de materias esperadas.
- **Plan de estudios (versión)**: agrupación con nombre y descripción
  de asociaciones materia-carrera. Una carrera puede tener varias
  versiones históricas.
- **Asociación materia-carrera**: una entrada que dice "esta materia
  está en el plan X de la carrera Y, en tal año y tal cuatrimestre".
- **Dicta recursado**: flag de la carrera que indica si se ofrecen sus
  materias exclusivas también como recursado en el cuatrimestre
  opuesto. Se puede sobrescribir a nivel materia.
- **Sedes habilitadas**: lista de sedes en las que la carrera puede
  dictar sus materias exclusivas. Vacío significa "todas las sedes".
- **Materia común**: materia que está asociada a dos o más carreras
  distintas. Se asigna a la sede default de comunes.
- **Materia exclusiva**: materia que está asociada a una sola carrera.
  Se asigna a las sedes habilitadas de esa carrera.
- **Barra de completitud**: indicador visual que compara cuántas
  materias obligatorias tiene asociadas la última versión del plan
  contra la cantidad esperada. Solo aparece si "Cantidad de Materias"
  está definida.
- **Placeholder de nombre**: cuando el nombre de una carrera es igual
  al código (por ejemplo, "IE - IE"), significa que la metadata inicial
  no completó el nombre real y hay que editarlo a mano.
