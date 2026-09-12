# Materias

## ¿Para qué sirve?

La página **📚 Materias** es el catálogo maestro de asignaturas del sistema.
Es donde se cargan las materias con su código, nombre, carga horaria y
período (anual o cuatrimestral), se las asocia a los planes de estudio de
las carreras correspondientes, y se define qué laboratorios son
compatibles con cada una.

Todo lo que después se ofrece en un ciclo (dictados), aparece en un
cronograma o se planifica en una comisión, arranca desde acá.

## ¿Cuándo vas a usar este módulo?

- **Setup inicial**: después de la primera carga masiva desde los Excel
  maestros, para revisar horas de teoría y laboratorio (los Excel sólo
  traen el total semanal), marcar materias virtuales del catálogo y
  asociar laboratorios compatibles.
- **Cambio de plan de estudios**: cuando una carrera incorpora una
  materia nueva o reemplaza una vieja.
- **Al abrir una carrera nueva**: darle de alta al catálogo las materias
  que la componen (si no venían del Excel maestro).
- **Cuatrimestre nuevo con materias extra**: agregar asignaturas
  optativas o especiales que este ciclo se van a dictar por primera vez.
- **Corrección de datos**: ajustar horas semanales, cupos, período o
  cambiar el flag de virtual/optativa de una materia existente.
- **Mantenimiento**: dar de baja materias que ya no se dictan, mover
  una materia de año/cuatrimestre en un plan puntual.

## Cómo se relaciona con el resto

- **Depende de Carreras**: una materia siempre pertenece a al menos una
  carrera, dentro de una versión de plan de estudios. Sin carreras
  cargadas no se pueden dar de alta materias nuevas.
- **Depende de Aulas y Sedes**: para asociar laboratorios compatibles a
  una materia, tienen que existir aulas de tipo laboratorio.
- **Alimenta Ciclos**: cuando un ciclo se pone en marcha, las materias
  del plan asignado se convierten en dictados (una fila por materia).
- **Alimenta Cronogramas**: las filas del cronograma referencian
  materias por su código.
- **Alimenta Planes**: las comisiones y los patrones semanales del plan
  de cursada se arman a partir de materias.
- **Alimenta el asignador de aulas**: los laboratorios compatibles y el
  flag de "virtual" pesan al momento de asignar aulas.

## Recorrido rápido de la página

Arriba de todo, un panel plegable **📊 Estado de Completitud de
Carreras** muestra cuántas carreras están completas y cuáles todavía
tienen materias pendientes de asignar. Está ahí porque justamente cargar
materias es lo que "completa" una carrera.

Después vienen tres solapas:

- **📋 Lista**: es la vista principal. Se ven todas las materias, se
  puede filtrar por código o nombre, y desde acá se entra al modo de
  edición o eliminación de una materia puntual.
- **➕ Crear**: formulario para dar de alta una materia nueva desde cero,
  con la asignación de carreras incluida en el mismo paso.
- **🔍 Buscar**: una vista de solo lectura para localizar materias por
  código o nombre. Es prácticamente redundante con el filtro de la
  solapa Lista y no ofrece acciones — en la práctica conviene usar
  Lista para todo.

## Tareas comunes

### Cargar una materia nueva

1. Abrí la solapa **➕ Crear**.
2. Completá los datos básicos:
   - **Código**: identificador único de la materia. No puede repetirse
     con otra materia existente y no se puede cambiar después.
   - **Nombre**: nombre completo de la materia como se muestra en la
     documentación académica.
   - **Período**: elegí "cuatrimestral" o "anual". Si es anual, en la
     asociación de carreras el cuatrimestre queda fijo en "Anual".
   - **Cupo**: opcional. Cantidad máxima de inscriptos esperada.
   - **Hs/Sem**: cantidad total de horas semanales de la materia.
   - **Hs Teoría** y **Hs Laboratorio**: desglose opcional. Si cargás
     los tres campos, la suma de Teoría + Laboratorio tiene que dar
     igual a Hs/Sem, si no el sistema no deja crear la materia.
   - **Virtual**: marcalo si la materia es siempre virtual por
     definición (no se dicta presencialmente en ningún ciclo).
   - **Optativa**: marcalo si es una materia electiva (no obligatoria
     dentro del plan).
   - **Recursado**: dejalo en "Según Carrera" salvo que quieras forzar
     una excepción para esta materia (ver "Marcar una materia como
     recursado excepcional").
3. Bajá a la sección **Asignación de Carreras** y agregá al menos una
   fila. Es obligatorio: una materia sin ninguna carrera asociada no se
   puede crear.
   - Por cada fila elegí la **carrera**, el **año** (1 a 6), el
     **cuatrimestre** (1C o 2C, o "Anual" si la materia es anual) y la
     **versión de plan de estudios** a la que la querés asociar (por
     default es la versión más reciente).
   - Podés asociar la misma materia a varias carreras en un solo paso
     agregando más filas.
4. Apretá **Crear Materia**.
5. Verificación: la materia aparece en la solapa **📋 Lista** con las
   carreras que le asociaste. El panel de completitud de arriba también
   refleja el cambio para las carreras afectadas.

**Gotcha**: si la carrera que querés asociar no tiene una versión de
plan de estudios creada, la materia no se va a poder asociar y vas a ver
el error "No se encontró plan de estudios para la carrera 'X'". En ese
caso hay que ir a la página **🎓 Carreras**, entrar al tab "Materias por
Carrera" y crear una versión con el botón "Nueva Version" antes de
volver.

### Editar una materia existente

1. En la solapa **📋 Lista**, filtrá por código o nombre si hace falta.
2. Desplegá la materia que querés editar y apretá **Editar**.
3. Se abren tres sub-solapas: **Datos Básicos**, **Carreras** y
   **Laboratorios**.
4. En **Datos Básicos** modificá los campos que necesites. El código no
   se puede cambiar (queda deshabilitado). Guardá con el botón
   correspondiente.
5. Verificación: al volver a la lista, los cambios aparecen reflejados
   en la fila de la materia.

**Ojo**: editar una materia afecta a **todas las carreras** que la
comparten. Si querés cambiar sólo el año o cuatrimestre en una carrera
puntual, hacelo desde la sub-solapa **Carreras** (ver más abajo).

### Asociar una materia a otra carrera

1. Entrá en modo edición de la materia (ver "Editar una materia
   existente").
2. Andá a la sub-solapa **Carreras**.
3. En el formulario **"Asociar Nueva Carrera"** elegí la carrera, el
   año y el cuatrimestre. La versión de plan que se usa es la más
   reciente de esa carrera.
4. Apretá el botón para asociar. La nueva asociación aparece en la
   tabla de arriba.
5. Verificación: al volver a la lista, el conteo de carreras asociadas
   aumentó y la carrera nueva aparece en el listado.

### Cambiar el año o cuatrimestre en una carrera puntual

1. Entrá en modo edición de la materia y andá a la sub-solapa
   **Carreras**.
2. En la tabla editable de asociaciones actuales, modificá directamente
   el año o el cuatrimestre en la fila correspondiente.
3. Apretá **Guardar Cambios**.
4. Verificación: la tabla se refresca con el nuevo año/cuatrimestre.

**Nota**: si la materia es anual, el campo cuatrimestre queda bloqueado
en "Anual" y no se puede editar.

### Desasociar una materia de una carrera

1. Entrá en modo edición y andá a la sub-solapa **Carreras**.
2. En el multiselect **"Desasociar Carrera"** elegí la carrera (y plan)
   de la que la querés sacar.
3. Confirmá la acción.
4. Verificación: la asociación desaparece de la tabla de arriba y el
   conteo en la lista general se ajusta.

**Precaución**: si esa asociación estaba siendo referenciada por
dictados, cronogramas o comisiones activas de un ciclo en curso,
desasociarla puede dejar información inconsistente. Antes de
desasociar, chequeá que no haya un plan de cursada activo que dependa
de esa combinación materia-carrera.

### Marcar una materia como virtual del catálogo

Existen tres niveles de "materia virtual" en el sistema, y es importante
entender la diferencia:

- **Virtual de catálogo** (`Virtual` en esta página): la materia es
  virtual siempre, por definición. Ejemplo: una materia que se dicta
  100% por Zoom en todas las carreras y todos los ciclos.
- **Virtual del ciclo** (se marca en la página de Ciclos → Dictados):
  la materia es virtual solamente para este ciclo puntual. Ejemplo: se
  vuelve virtual excepcionalmente por un cuatrimestre.
- **Virtual del horario**: aún más granular, se aplica a un patrón
  semanal específico dentro de una comisión.

El sistema aplica el orden jerárquico: si marcaste algo como virtual
en cualquiera de los tres niveles, el asignador de aulas la trata como
virtual y no le pide aula.

**Pasos para marcar virtual de catálogo**:

1. Entrá en modo edición de la materia (Datos Básicos).
2. Tildá la casilla **Virtual**.
3. Guardá los cambios.
4. Verificación: en la lista, la columna "Virtual" muestra "Sí" para
   esa materia. En cualquier ciclo futuro, esa materia va a arrancar
   como virtual por default.

### Marcar una materia como recursado excepcional

Por default, cada carrera define si dicta o no en el cuatrimestre
opuesto las materias que ya se dictaron (flag "Dicta recursado" en la
carrera). A veces hace falta una excepción para una materia puntual.

1. Entrá en modo edición → Datos Básicos.
2. En el selector **"Recursado (excepción para esta materia)"** elegí:
   - **Según Carrera**: lo default. La materia sigue la regla de la
     carrera.
   - **Sí (forzar)**: esta materia siempre se dicta como recursado, sin
     importar la carrera.
   - **No (forzar)**: esta materia nunca se dicta como recursado, sin
     importar la carrera.
3. Guardá.
4. Verificación: la próxima vez que crees dictados en un ciclo, esa
   materia aparece (o no) según lo que forzaste.

**Nota**: este override no se muestra en la vista de lista. Hay que
entrar a Editar la materia para verlo.

### Cargar laboratorios compatibles con una materia

1. Entrá en modo edición → sub-solapa **Laboratorios**.
2. Vas a ver un multiselect con todas las aulas de tipo laboratorio
   cargadas en el sistema.
3. Elegí los laboratorios que son compatibles con esta materia.
4. El sistema te muestra cuántos vas a agregar y cuántos vas a sacar
   respecto del estado actual.
5. Apretá **Guardar**.
6. Verificación: al volver a la lista, la columna "Laboratorios
   compatibles" muestra el conteo actualizado.

**Si no hay laboratorios cargados** el sistema te avisa con un mensaje
y no te deja seleccionar nada. Andá a la página **🏛️ Aulas y Sedes**
y creá al menos un aula con tipo "laboratorio" antes de volver.

**Uso**: esta lista es la que el asignador de aulas consulta cuando
tiene que asignarle aula a un patrón semanal cuyo tipo de clase es
"laboratorio".

### Eliminar una materia

1. En la solapa **📋 Lista**, desplegá la materia y apretá **Eliminar**.
2. Aparece una pantalla de confirmación con la advertencia "Esta acción
   no se puede deshacer".
3. Apretá **Confirmar** para borrar, o **Cancelar** para volver.

**Advertencia crítica**: a diferencia de otros módulos, esta pantalla
**no chequea previamente** si la materia tiene dependencias. Si la
materia está referenciada por planes de estudio, dictados de un ciclo,
comisiones o inscripciones históricas, el borrado va a fallar con un
error de tipo "FOREIGN KEY constraint failed" y la materia queda intacta.

Antes de eliminar, asegurate de:

- Desasociar la materia de todas las carreras (sub-solapa Carreras).
- Que no haya dictados activos en ningún ciclo que la mencionen.
- Que no aparezca en ningún cronograma o plan activo.

Si aún así el borrado falla, hay que rastrear qué la está referenciando
antes de poder eliminarla.

## Errores frecuentes y qué hacer

| Mensaje | ¿Qué significa? | Cómo lo resolvés |
|---|---|---|
| "Debe asignar al menos una carrera" | Al crear una materia dejaste vacía la tabla de asignación de carreras | Agregá al menos una fila con carrera + año + cuatri antes de crear |
| "Hs Teoría (X) + Hs Lab (Y) = Z ≠ Hs/Sem (W). Corregí antes de guardar." | El desglose horas de teoría + laboratorio no coincide con el total | Ajustá los tres campos para que la suma cuadre |
| "No se encontró plan de estudios para la carrera 'X'" | La carrera que querés asociar no tiene una versión de plan creada | Andá a Carreras → Materias por Carrera y creá una versión con "Nueva Version" |
| "No hay carreras disponibles. Cree una carrera primero." | El catálogo de carreras está vacío | Andá a la página Carreras y creá al menos una |
| "No hay aulas de tipo 'laboratorio' cargadas en la base de datos." | Querés asociar laboratorios pero no hay aulas de tipo laboratorio | Andá a Aulas y Sedes → Crear con tipo "laboratorio" |
| Error tipo "FOREIGN KEY constraint failed" al borrar | La materia tiene dependencias activas (planes, dictados, comisiones) | Desasociá la materia de todas las carreras y verificá que no esté en ningún ciclo activo antes de reintentar |
| "Materia '{codigo}' no encontrada" | La materia que estabas editando fue borrada por otro usuario o sesión | Volvé a la lista y refrescá |
| "No se pudo actualizar" | El guardado falló silenciosamente | Reintentá; si persiste, avisale al equipo técnico |

## Preguntas frecuentes

**¿Puedo tener dos materias con el mismo código?**
No. El código es único a nivel sistema. Si intentás crear una con un
código existente, el alta falla.

**¿Puedo tener dos materias con el mismo nombre?**
Sí. El sistema no valida duplicidad de nombres, solamente del código.
En la práctica conviene evitarlo para no confundir al equipo.

**¿Qué pasa si borro una materia que ya está en un plan activo?**
El borrado va a fallar con un error de integridad y la materia queda
intacta. Es una protección implícita, pero no está señalizada antes de
apretar Confirmar — recién ves el error al intentar. Antes de borrar,
desasociá la materia de todas las carreras y revisá que no esté en
ningún ciclo activo.

**¿Dónde veo el histórico de cambios de esta materia?**
En la página **📜 Historial**. Se auditan altas y bajas, y cambios en
los flags Virtual, Optativa, Recursado (override) y en las horas de
teoría y laboratorio. Otros campos (nombre, cupo, horas semanales) no
quedan registrados en el histórico.

**¿La misma materia puede aparecer en dos carreras con distinto año o
cuatrimestre?**
Sí, y es lo esperado. Una materia común (por ejemplo, "Análisis
Matemático I") puede estar en el primer año de una carrera y en el
segundo de otra. Se maneja desde la sub-solapa Carreras del editor.

**¿Qué diferencia hay entre "materia común" y "materia exclusiva"?**
Es una distinción implícita: una materia se considera común si aparece
en dos o más carreras distintas. No tiene un tildá en la tabla, se
calcula automáticamente. La distinción es importante para el asignador
de aulas: las comunes van a la sede "default de comunes" y las
exclusivas a las sedes habilitadas de la carrera a la que pertenecen.

**¿Puedo poner una materia como optativa y obligatoria en distintas
carreras?**
Hoy el flag "Optativa" es a nivel del catálogo maestro (afecta a todas
las carreras que la comparten). No se puede tener "optativa en la
carrera A y obligatoria en la carrera B" desde esta página.

**¿Qué pasa si cambio las horas semanales de una materia que ya está
dictándose?**
La materia queda con las horas nuevas. Los cronogramas ya cargados no
se ajustan automáticamente — si el cambio afecta el patrón semanal
esperado, tenés que revisar los cronogramas del ciclo en curso.

**¿Puedo darle "cupo" a una materia y que el sistema lo respete?**
El cupo se usa como referencia para el forecast y para las validaciones
de cobertura, pero no bloquea nada de por sí. Los cupos "duros" se
manejan a nivel de comisión, no de materia.

**¿Puedo dejar el cupo o las horas de teoría/laboratorio vacías?**
Sí. El sistema acepta que estén sin cargar (quedan en "no definido").
Si después los completás, la validación de "Hs Teoría + Hs Lab = Hs/Sem"
va a aplicar recién cuando estén los tres.

**¿Qué es el tab 🔍 Buscar?**
Es una vista de solo lectura que lista materias por código o nombre.
Es redundante con el filtro de la solapa Lista, que tiene la misma
búsqueda y además permite Editar y Eliminar. Se puede considerar como
legacy — en la práctica, usá Lista.

## Términos importantes de este módulo

- **Materia (o asignatura)**: entrada del catálogo maestro con código,
  nombre, horas semanales, período y flags. La misma materia puede
  aparecer en múltiples carreras.
- **Período**: si la materia es "cuatrimestral" (dura un semestre) o
  "anual" (dura todo el año).
- **Materia común**: aquella que aparece en dos o más carreras
  distintas. Se calcula automáticamente.
- **Materia exclusiva**: aquella que aparece en una sola carrera.
- **Materia optativa (electiva)**: no es obligatoria para completar
  la carrera. Afecta el conteo de completitud y algunas validaciones.
- **Materia virtual de catálogo**: se dicta virtualmente en todo momento
  y en todas las carreras. El asignador no le pide aula.
- **Recursado**: dictado de una materia en el cuatrimestre opuesto al
  que le tocaría según el plan, para permitir a los alumnos recuperarla.
  La carrera define si dicta recursado; la materia puede forzar una
  excepción.
- **Laboratorio compatible**: aula de tipo "laboratorio" en la que se
  puede dictar la parte práctica de esta materia. El asignador solo
  considera estas aulas para las clases de tipo laboratorio.
- **Versión de plan de estudios**: agrupación de asociaciones
  materia-carrera con un nombre y una fecha. Una carrera puede tener
  varias versiones históricas de su plan; la vigente es la más reciente.
- **Asignación materia-carrera**: entrada que dice "esta materia está en
  el plan X de la carrera Y, en tal año y tal cuatrimestre". Es lo que
  se ve en la tabla de la sub-solapa "Carreras" del editor.
