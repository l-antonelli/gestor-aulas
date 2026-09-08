# Capítulo 3. La organización y su operatoria

El capítulo anterior fijó las herramientas conceptuales del trabajo.
Este capítulo las aplica por primera vez, sobre un objeto concreto:
la Facultad de Ciencias Exactas, Ingeniería y Agrimensura de la
Universidad Nacional de Rosario, y en particular el proceso por el
cual cada cuatrimestre se decide qué clase se dicta en qué aula.

El propósito del capítulo es doble. Por un lado, dejar caracterizada
a la organización con el nivel de detalle necesario para que las
decisiones de modelización de los capítulos siguientes tengan una
base concreta. Por otro, describir el proceso actual de asignación
(cómo se hace hoy, con qué información y con qué resultados) para
que el diagnóstico de sus problemas quede fundado y no dependa de
la intuición del lector. El instrumental que se usa acá viene del
análisis de sistemas y del modelado de procesos, presentados en
§2.1.1; los diagnósticos organizacionales se apoyan en las
tipologías de §2.1.2 y §2.1.3 sin repetirlas.

## 3.1 FCEIA en detalle

### 3.1.1 Misión, escala y contexto institucional

La Facultad de Ciencias Exactas, Ingeniería y Agrimensura (en
adelante, FCEIA) es una de las doce facultades de la Universidad
Nacional de Rosario (UNR). Su actividad primaria es la formación
universitaria de grado y de posgrado en disciplinas de la
ingeniería, las ciencias exactas y la agrimensura. La escala de la
facultad (decenas de carreras activas, cientos de materias, miles
de alumnos regulares por cuatrimestre) hace que la coordinación de
su operatoria académica no sea reducible a la de una unidad
pequeña: cualquier proceso que la involucre se enfrenta con la
combinatoria propia de una organización mediana.

La actividad académica se ordena en **ciclos lectivos**, cada uno
compuesto por dos **cuatrimestres**. Cada cuatrimestre inaugura un
nuevo escenario de planificación: qué materias se dictan, con qué
comisiones, en qué horarios y en qué aulas. Este documento se ocupa
específicamente de la última pregunta, aunque en varios momentos
tendrá que apoyarse en las tres anteriores para dar contexto.

### 3.1.2 Sedes: Pellegrini y Siberia

La FCEIA opera físicamente en dos sedes:

- **Sede Pellegrini** (edificio central, calle Pellegrini): concentra
  la mayor parte del dictado. En ella coexisten actividades académicas
  de distintas carreras, que comparten el edificio y sus aulas.
- **Sede Siberia**: sede complementaria en la que se dictan algunas
  materias específicas, típicamente ligadas a laboratorios o
  espacios de práctica que sólo existen allí.

Ambas sedes están bajo gestión centralizada de la facultad y sus
aulas son de uso exclusivo de FCEIA. La distinción entre sedes es
relevante para el problema de asignación por dos motivos: primero,
porque un alumno que cursa dos materias correlativas el mismo día no
puede trasladarse instantáneamente de una sede a la otra, y por lo
tanto ciertos pares de horarios que en un edificio único serían
válidos en dos sedes distintas no lo son; segundo, porque hay
laboratorios que existen solamente en una de las dos sedes, con lo
cual el tipo de aula requerida por una materia puede restringir la
sede donde se dicta.

### 3.1.3 Tipología de aulas

Las aulas de la FCEIA se clasifican, para los efectos de la
asignación, en tres grandes tipos:

- **Aulas teóricas**: destinadas al dictado expositivo, con bancos
  fijos o móviles. Capacidades típicas que van desde una veintena
  hasta un centenar y medio de alumnos. Dentro de esta familia se
  distinguen aulas comunes y **anfiteatros**, que son aulas
  teóricas con capacidad especialmente alta.
- **Laboratorios**: aulas con equipamiento específico según la
  disciplina (química, electrónica, informática, ensayo de
  materiales, entre otros). No son intercambiables: un laboratorio
  de química no sirve para una clase de electrónica y viceversa.
  Formalmente, cada materia con contenido de laboratorio declara
  cuáles laboratorios son compatibles con ella.
- **Espacios específicos**: aulas con requerimientos particulares
  que no encuadran en las categorías anteriores. Se los menciona
  para completitud pero, dentro del alcance de este trabajo, se los
  trata como una variante de aula teórica o de laboratorio según
  corresponda.

Las aulas tienen, además, dos atributos operativamente relevantes:
**capacidad** (cantidad máxima de alumnos que pueden cursar en ella
en condiciones adecuadas) y **disponibilidad horaria** (franjas de
la semana en las que el aula está habilitada para dictado). Sobre
capacidades, la facultad opera con un rango amplio (aulas chicas
para comisiones reducidas, aulas grandes para materias masivas,
anfiteatros para clases plenarias); sobre disponibilidades, la
convención asumida es que las aulas están disponibles durante toda
la ventana operativa de la facultad, salvo excepciones puntuales
que quedan fuera del alcance de este trabajo.

## 3.2 El proceso actual de asignación de aulas

Con la organización ya caracterizada, corresponde describir el
proceso concreto por el cual hoy se decide qué clase se dicta en qué
aula. Antes de la descripción propiamente dicha conviene una nota
sobre el instrumento de modelado.

### 3.2.1 Análisis y modelado de procesos como instrumento

Cuando un ingeniero necesita entender un proceso operativo, uno de
los recursos de su caja de herramientas es el **modelado de
procesos**: representar el flujo de actividades (quién hace qué,
cuándo, con qué insumos y con qué salidas) en una notación
suficientemente formal como para que la representación pueda
discutirse, revisarse y mejorarse. Este recurso ya fue introducido
en §2.1.1 como parte del instrumental de análisis de sistemas de la
ingeniería industrial.

Existen varias notaciones estandarizadas para modelar procesos: los
diagramas de flujo elementales, los cursogramas, la notación
**BPMN** (*Business Process Model and Notation*, un estándar de la
Object Management Group) y los diagramas SIPOC. Cada notación
enfatiza aspectos distintos: BPMN es fuerte para explicitar roles y
puntos de decisión; los cursogramas son fuertes para documentar
formularios y responsables administrativos; SIPOC es útil para
enfocar entradas y salidas. En este capítulo se opta por una
notación de flujo simplificada, suficiente para comunicar la
estructura del proceso actual sin recargar al lector con
convenciones específicas.

### 3.2.2 Actores intervinientes

En el proceso actual de asignación intervienen los siguientes
actores:

- **Coordinación estudiantil**. Área administrativa a cargo del
  proceso. Su responsable, a quien nos referimos genéricamente
  como *la coordinadora estudiantil*, es quien materializa las
  decisiones de asignación de aulas, recibe los requerimientos de
  las cátedras, resuelve conflictos y publica el resultado.
- **Cátedras**. Cada materia está a cargo de una cátedra que fija
  su modalidad de dictado (cantidad de comisiones, horarios,
  necesidad de laboratorio, contenidos por bloque) dentro de las
  restricciones que le imponen el plan de estudios y el
  cronograma general de la facultad.
- **Autoridades académicas**. Definen políticas generales:
  calendario, ciclos, planes de estudio, sedes habilitadas para
  cada carrera, cupos globales.
- **Alumnos**. Consumen el resultado del proceso: se inscriben a
  comisiones y asisten a las clases en las aulas asignadas.
- **Sistema SIU Guaraní**. Sistema de gestión académica que
  administra la información de alumnos, inscripciones y
  comisiones. Detallado en §3.4.

Se destaca que **la coordinadora estudiantil es el único punto del
sistema donde se toman decisiones de asignación de aulas**. El
resto de los actores aporta información, restricciones o
requerimientos, pero la asignación final es una decisión
centralizada.

### 3.2.3 Momentos y modalidad del proceso

El proceso tiene dos momentos operativos distintos:

- **Planificación inicial**: al comienzo de cada cuatrimestre, antes
  del inicio de clases y, típicamente, antes de conocer la cantidad
  final de inscriptos, se define el esquema completo de asignación.
  Se toma como punto de partida el esquema del cuatrimestre
  anterior y se lo ajusta según los cambios reportados por las
  cátedras y las autoridades.
- **Ajustes dinámicos**: iniciadas las clases, el esquema inicial
  suele requerir ajustes: por incorporación tardía de inscriptos,
  por materias que resultaron más numerosas de lo esperado, por
  cambios de última hora en la disponibilidad de docentes o aulas,
  por conflictos que se descubren en la práctica. Los ajustes se
  resuelven caso por caso.

La modalidad, en ambos momentos, es fundamentalmente **manual**. La
coordinadora trabaja con planillas (Excel y documentos derivados),
comunicaciones informales con cátedras (correo electrónico,
mensajería) y con las autoridades. No existe un sistema de
información integrado que centralice restricciones, disponibilidades
y decisiones; la información se organiza en documentos separados
que la coordinadora integra mentalmente al momento de decidir.

### 3.2.4 Diagrama del proceso actual

El diagrama siguiente resume el flujo operativo. Es una
representación simplificada, elaborada para servir de referencia en
las secciones que siguen; su fidelidad al detalle administrativo
concreto no es total pero sí suficiente para el análisis.

```mermaid
flowchart TB
    A[Cierre del cuatrimestre anterior] --> B[Recepción de novedades<br/>de cátedras y autoridades]
    B --> C[Toma del esquema anterior<br/>como punto de partida]
    C --> D[Aplicación manual de ajustes:<br/>cambios de horarios, nuevas comisiones,<br/>materias que se abren o cierran]
    D --> E{¿Conflictos detectados?}
    E -->|Sí| F[Resolución manual:<br/>reasignación caso por caso,<br/>consulta a cátedras]
    F --> E
    E -->|No| G[Publicación del esquema inicial]
    G --> H[Inicio de clases]
    H --> I{¿Novedad operativa<br/>durante el cuatrimestre?}
    I -->|Aula superpoblada,<br/>cambio de comisión,<br/>indisponibilidad puntual| J[Ajuste dinámico caso por caso]
    J --> I
    I -->|Fin del cuatrimestre| K[Cierre]

    classDef proc fill:#fffbe6,stroke:#c9a227,color:#000
    classDef dec fill:#e6f0ff,stroke:#4a6fa5,color:#000
    class A,B,C,D,F,G,H,J,K proc
    class E,I dec
```

## 3.3 Problemas operativos observados

La descripción del proceso permite ahora enumerar los problemas
operativos que motivan este trabajo. La lista se construye a partir
de la observación del funcionamiento actual y de las comunicaciones
recogidas con la coordinación estudiantil.

### 3.3.1 Problemas visibles al alumnado

Estos son los problemas cuya manifestación es directamente
perceptible en el aula:

- **Alumnos que pierden clases por falta de capacidad.** En materias
  masivas o en fechas de examen, la asistencia excede la capacidad
  del aula asignada; parte del alumnado queda sin lugar y no puede
  cursar esa clase concreta.
- **Alta densidad de alumnos.** Aun sin superar formalmente la
  capacidad del aula, la densidad efectiva (alumnos por metro
  cuadrado, disponibilidad de bancos) puede degradar sensiblemente
  la calidad del dictado.
- **Movimiento de bancos entre aulas.** Como corolario de lo
  anterior, alumnos y bedelería trasladan bancos entre aulas para
  compensar diferencias, entorpeciendo el paso en los pasillos y
  generando condiciones ergonómicas pobres.
- **Demoras en el inicio de las clases.** Cuando el aula asignada
  resulta inadecuada o no está disponible, la reasignación
  improvisada retrasa el inicio, con impacto acumulado sobre el
  dictado.

### 3.3.2 Problemas del proceso administrativo

Estos son los problemas ligados a cómo se lleva adelante la
asignación:

- **Alto costo de tiempo humano.** La coordinadora dedica una
  proporción significativa de su tiempo a la asignación inicial y,
  sobre todo, a los ajustes dinámicos, en detrimento de otras
  tareas de coordinación.
- **Sensibilidad a la información no consolidada.** Como los datos
  viven en documentos separados, cualquier cambio en un documento
  fuente puede pasar inadvertido y contaminar decisiones
  subsiguientes; la ausencia de una vista unificada favorece los
  errores de omisión.
- **Efecto cascada al re-planificar.** Una modificación local
  (cambio de horario de una materia, apertura de una comisión
  nueva) puede invalidar varias asignaciones aparentemente
  independientes. Sin una herramienta que evalúe el impacto de un
  cambio, cada re-planificación es exploratoria y consume tiempo
  desproporcionado al tamaño del cambio.
- **Falta de trazabilidad de las decisiones.** No queda registro
  sistemático de por qué se asignó cada aula a cada clase, con lo
  cual es difícil auditar decisiones pasadas o replicar buenas
  soluciones en cuatrimestres siguientes.

### 3.3.3 Problemas estructurales

Finalmente, hay problemas que no son fallas del proceso sino
características estructurales que el proceso no puede abordar:

- **Naturaleza combinatoria del problema.** Cientos de horarios
  semanales, decenas de aulas de tipos distintos, restricciones de
  tipo, sede, capacidad y no simultaneidad; el espacio de
  asignaciones posibles crece de manera explosiva y es
  prácticamente inabarcable para una decisión manual óptima.
- **Falta de un modelo formal de las restricciones.** Las reglas de
  la asignación (qué aula puede recibir qué clase, qué
  compatibilidades existen entre materias y laboratorios, cuáles
  son las sedes admisibles por carrera) son de conocimiento común
  pero no están explicitadas en ningún documento único. Cada
  decisión se toma con base en el criterio personal de la
  coordinadora, alimentado por experiencia acumulada.
- **Ausencia de indicadores cuantitativos.** No hay métricas
  sostenidas de ocupación, capacidad excedida, aulas subutilizadas,
  tiempo insumido por reasignaciones. Sin ellas, cualquier
  discusión sobre "cómo funciona la asignación" queda anclada en
  impresiones antes que en datos.

Es importante señalar, para no exagerar el diagnóstico, que el
proceso actual **funciona**: cada cuatrimestre se logra publicar un
esquema de asignación y las clases se dictan. La motivación del
trabajo no es que el proceso esté fallando sino que **funciona a un
costo alto y con resultados subóptimos**, y que ambas cosas son
susceptibles de mejora con las herramientas adecuadas.

## 3.4 Datos y silos: cómo viven hoy los datos

Los problemas del proceso descriptos arriba no son ajenos a cómo
viven los datos que el proceso consume. Esta sección describe el
estado actual del ecosistema de datos de FCEIA en relación con la
asignación de aulas, y hace explícita la dispersión que motiva
varias de las decisiones de modelización del capítulo siguiente.

### 3.4.1 Las tres fuentes principales

En la práctica, la coordinadora trabaja con información que proviene
de tres fuentes distintas:

- **Planes de estudio de las carreras.** Cada carrera publica su
  plan de estudios: la lista de materias que la componen, su
  ubicación curricular (año, cuatrimestre), su carga horaria y sus
  correlativas. Estos planes viven en documentos institucionales
  (resoluciones del Consejo Directivo, publicaciones en la web de
  la facultad) y usualmente emplean **códigos internos propios de
  cada carrera** para identificar sus materias.
- **SIU Guaraní.** Sistema informático de gestión académica común a
  las universidades nacionales argentinas. Administra la
  información de alumnos, inscripciones a materias y comisiones,
  actas de examen y trámites conexos. Sus **códigos son propios del
  sistema** y no coinciden con los códigos internos de los planes
  de estudio.
- **Horarios y cronogramas publicados.** Cada cuatrimestre las
  cátedras y la coordinación publican los horarios de cursada en
  planillas y en la web. En estas publicaciones, una misma materia
  puede aparecer con **nombres distintos** según la carrera desde
  la cual se la mira (la misma materia de matemática puede
  llamarse *Análisis Matemático* en una carrera y *Cálculo* en
  otra, sin que ambos nombres se declaren como equivalentes en
  ningún documento común).

### 3.4.2 El problema de la codificación no estandarizada

Las tres fuentes anteriores no comparten un identificador estable
para las entidades comunes. Una misma materia puede tener tres o más
nombres distintos (el del plan de la carrera A, el del plan de la
carrera B, el de SIU Guaraní, el del cronograma publicado) sin que
exista un mapeo formal entre ellos. Este fenómeno es especialmente
frecuente en las **materias comunes**: asignaturas que forman parte
de varias carreras a la vez (típicamente las de los primeros años,
como matemáticas o físicas).

La consecuencia práctica es que integrar información de las tres
fuentes es una tarea de reconciliación manual. Saber cuántos
alumnos de una carrera van a cursar una materia común implica
identificar la equivalencia entre el código de plan y el código de
SIU; saber en qué aula estaba dictándose el año pasado implica
identificar la equivalencia entre el nombre del cronograma y el
código de plan. Cada una de estas reconciliaciones se hace de
memoria o consultando documentos accesorios; ninguna está
sistematizada.

### 3.4.3 Conceptos coloquialmente definidos

Un fenómeno estrechamente relacionado, y que ya se mencionó en la
introducción como una de las motivaciones del diseño guiado por el
dominio, es que muchos de los conceptos que estructuran el proceso
tienen definiciones coloquiales pero no formales. Todos los actores
saben, en términos generales, qué es una **clase**, una **comisión**,
un **dictado**, un **plan de cursada**; pero al examinar el detalle
aparecen discrepancias sutiles. Un docente puede considerar que dos
clases de la misma materia en el mismo día constituyen "una clase" o
"dos clases" según qué esté enfatizando; una comisión puede
entenderse como una lista de alumnos, como un grupo de horarios, o
como ambas cosas al mismo tiempo. Mientras estas discrepancias no
se hacen visibles el trabajo puede continuar, pero cualquier intento
de sistematizar información las expone: dos personas discutiendo
sobre "cuántas clases se dictan por semana" pueden estar contando
cosas distintas sin saberlo.

Esta dispersión conceptual es la contracara de la dispersión de los
datos y motiva el trabajo de modelización del dominio que se aborda
en el capítulo 5. Fijar un **lenguaje ubicuo** (en el sentido de
Evans, ver §2.2) sobre estas entidades no es meramente un ejercicio
de higiene técnica: es una condición necesaria para que la
asignación deje de depender de reconciliaciones informales.

## 3.5 Recapitulación

Este capítulo dejó caracterizada a la FCEIA como organización y a su
proceso actual de asignación de aulas. Los puntos que se retoman en
los capítulos siguientes son cuatro:

1. **La FCEIA es una organización compleja** con dos sedes,
   múltiples carreras y una tipología heterogénea de aulas. Cualquier
   modelo del problema tiene que representar sedes, tipos de aula y
   compatibilidades específicas.
2. **El proceso de asignación es hoy manual y no soportado por
   herramientas de decisión.** Su output se logra a costa de un
   costo humano elevado, con dificultad para replanificar y sin
   trazabilidad sistemática de las decisiones.
3. **Los problemas observados son de tres tipos**: los que percibe
   el alumnado en el aula, los que sufren los actores del proceso
   administrativo, y los que son estructurales al problema
   subyacente. Los dos primeros pueden mitigarse con un sistema
   adecuado; el tercero exige un modelo formal explícito.
4. **Los datos viven en silos con codificaciones no estandarizadas**,
   y varios conceptos operativos carecen de definiciones formales
   compartidas. Este diagnóstico motiva el trabajo de modelización
   del dominio que aparece en los próximos capítulos: definir con
   precisión las entidades del problema es una condición previa a
   cualquier automatización, no un lujo académico.

Con este cuadro, el capítulo siguiente formaliza el problema:
recoge la operatoria descripta acá y la traduce al vocabulario de
la investigación de operaciones fijado en §2.3, para que la
solución pueda diseñarse con las herramientas apropiadas.
