# Capítulo 4. Definición del problema

El capítulo 3 describió la operatoria actual de asignación de aulas
en la FCEIA en su forma coloquial: quién decide, cuándo, con qué
información y con qué resultado. Este capítulo cierra el arco de la
Parte II del informe: retoma esa descripción y la traduce a una
formulación formal, con vocabulario preciso, en el marco de la
investigación de operaciones fijado en §2.3.

El objetivo es que a la salida del capítulo el problema quede
enunciado con un nivel de precisión que permita, en la Parte IV,
modelarlo como un programa lineal entero sin que aparezcan
sorpresas. Interesa saber **qué tenemos**, **qué decidimos**, **qué
restricciones respeta la decisión** y **según qué criterio se
compara una asignación con otra**. Cada uno de estos cuatro puntos
tiene su sección.

## 4.1 Formulación coloquial

Antes de sumergirnos en la formulación formal, conviene enunciar el
problema en la lengua en la que se plantea todos los cuatrimestres
entre las Escuelas, la Secretaría Académica y la Secretaría Técnica
de la facultad. Este enunciado nos va a servir de referencia para
verificar, más adelante, que la formulación formal no pierda
ninguna pieza del original.

> Al comienzo de cada cuatrimestre, la Secretaría Técnica de la
> facultad dispone de una lista de **clases** que hay que dictar en
> cada franja horaria de la semana (grilla horaria ya consolidada
> por la Secretaría Académica a partir de las propuestas de las
> Escuelas), y una lista de **aulas** de distintos tipos y
> capacidades. Tiene que decidir, para cada clase, en qué aula se
> va a dictar, respetando las reglas: que dos clases al mismo
> tiempo no compartan aula, que el tipo de aula sea compatible con
> el tipo de clase, que la capacidad del aula sea razonable
> respecto de la cantidad de alumnos, que se cumpla la carga de
> teoría y de laboratorio declarada por cada materia, y que la
> asignación respete las sedes admisibles para cada carrera. Entre
> todas las asignaciones que cumplen las reglas, quiere elegir una
> que aproveche bien las aulas: sin dejar afuera alumnos por falta
> de capacidad, y sin desperdiciar aulas grandes en clases chicas.

Esta descripción es informal pero identifica ya todos los elementos
del problema: hay entidades (clases, aulas), hay una decisión (la
asignación), hay restricciones que la decisión debe respetar y hay
un criterio para comparar dos decisiones válidas entre sí. Las
próximas secciones van dando nombre y contorno preciso a cada uno
de estos elementos.

## 4.2 Encuadre: el problema como asignación de recursos bajo restricciones

### 4.2.1 Qué es un problema de asignación de recursos

En la caja de herramientas de la investigación de operaciones,
existe una familia de problemas, los **problemas de asignación de
recursos bajo restricciones**, que sirve de marco general para
situaciones como la que acabamos de describir coloquialmente. Antes
de aplicar el marco a nuestro caso, conviene decir qué caracteriza
a esta familia, en coherencia con la directiva metodológica del
capítulo 2 (introducir toda técnica primero como recurso del
instrumental profesional antes de pasar a su definición formal).

Un problema de asignación de recursos se caracteriza por:

- Un conjunto de **entidades demandantes** que requieren consumir
  recursos para poder llevarse a cabo (tareas a ejecutar, personas
  a alojar, mercadería a almacenar, clases a dictar).
- Un conjunto de **recursos disponibles**, típicamente escasos, que
  las entidades demandantes pueden consumir (máquinas, salas,
  camiones, aulas).
- Un conjunto de **reglas de compatibilidad y restricción** que
  determinan qué asignaciones son admisibles y cuáles no (esta
  máquina no puede procesar esta pieza, esta persona no puede estar
  en dos salas a la vez, este aula no es apta para química).
- Uno o más **criterios de calidad** que permiten comparar dos
  asignaciones admisibles y decidir cuál es mejor (menor costo,
  mejor aprovechamiento, mayor cobertura).

Este esquema (demanda, recursos, restricciones, criterio) es tan
general que abarca situaciones tan distintas como la asignación de
turnos hospitalarios, la planificación de mantenimiento de flotas o
la programación de la producción en una planta. Todas comparten la
misma estructura lógica; lo que cambia son las entidades concretas
y las reglas específicas.

La familia se estudia sistemáticamente desde la investigación de
operaciones y admite formulaciones matemáticas estándar, en
particular como programas lineales enteros, tal como se anticipó en
§2.3. Encuadrar la asignación de aulas dentro de esta familia
tiene una consecuencia práctica inmediata: podemos aprovechar el
aparato teórico y algorítmico ya desarrollado en lugar de tener que
inventar métodos desde cero.

### 4.2.2 Ubicación del problema de asignación de aulas dentro de la familia

Con el marco fijado, la ubicación es directa:

| Elemento del marco | Instancia en nuestro problema |
| --- | --- |
| Entidades demandantes | **Horarios semanales de clase**: cada franja recurrente de dictado (materia, comisión, día de la semana, hora de inicio, hora de fin) es una entidad que necesita un aula. |
| Recursos disponibles | **Aulas** de FCEIA, en sus tres tipologías (teóricas, laboratorios, espacios específicos), con sus capacidades y sedes. |
| Restricciones | Compatibilidad tipo-de-aula con tipo-de-clase; no simultaneidad en la misma aula; sede admisible por carrera y materia; carga horaria de teoría y de laboratorio declarada por la materia; ventana operativa de la facultad. |
| Criterio de calidad | Balance entre **no dejar alumnos afuera** (evitar sobre-ocupación) y **no desperdiciar capacidad** (evitar sub-ocupación), con las prioridades explicitadas más adelante. |

El resto del capítulo desarrolla cada uno de estos elementos con
más detalle. La formulación matemática concreta (qué variables se
definen, cómo se escriben las restricciones, cuál es la función
objetivo exacta) queda para el capítulo 8, una vez presentada la
arquitectura de la solución y el modelo de datos que la soporta.

## 4.3 Elementos del problema

### 4.3.1 La entidad demandante: el horario semanal

La primera decisión de modelización, que anticipamos acá y
formalizamos en el capítulo 5, es que la unidad sobre la cual se
decide una asignación no es la clase individual (una fecha concreta
del calendario) sino el **horario semanal**: la franja recurrente
que se dicta todas las semanas del cuatrimestre en el mismo día y
en el mismo rango horario.

Un horario semanal está caracterizado por:

- La **materia** a la que corresponde.
- La **comisión** de esa materia dentro de la cual se ubica.
- El **día de la semana** en que se dicta.
- La **hora de inicio** y la **hora de fin**.
- Su **tipo** (clase teórica o clase de laboratorio), que puede
  venir determinado desde el cronograma o quedar por decidir.

La elección de trabajar sobre el horario semanal (y no sobre cada
clase concreta con fecha) responde a una economía descriptiva: en
un cuatrimestre típico hay del orden de cientos de horarios
semanales pero varios miles de clases concretas si se las cuenta
por fecha. Como el patrón semanal se repite, salvo excepciones que
quedan fuera del alcance, resolver una vez por horario es
equivalente a resolver una vez por clase, con un modelo
sustancialmente más chico.

Vale notar la relación entre esta unidad de decisión y la
**grilla horaria oficial** de la facultad presentada en §3.1.4.
La grilla organiza el día en tres turnos y bloques de 45 minutos;
en la práctica, sin embargo, las Escuelas no siempre encajan sus
horarios en esos bloques. Por eso el modelo no adopta el bloque de
45 minutos como unidad y sí adopta el horario semanal declarado por
la cátedra, con sus horas de inicio y de fin efectivas. La grilla
oficial queda como marco de referencia pero no como restricción
dura del modelo.

### 4.3.2 El recurso: el aula

Un **aula** es el recurso que se asigna. Un aula está caracterizada
por:

- Un **identificador** único dentro de la facultad.
- Su **sede** (Pellegrini o Centro Universitario Rosario, en el
  caso FCEIA).
- Su **tipo** dentro de la tipología definida en §3.1.3 (aula
  teórica, laboratorio específico, anfiteatro).
- Su **capacidad**: la cantidad máxima de alumnos que puede
  albergar en condiciones adecuadas.

En este trabajo se asume que **las aulas están disponibles durante
toda la ventana operativa de la facultad**. La ventana operativa es
una franja global, típicamente de 8 a 23 hs, que acota los horarios
en los que la facultad opera. No se modelan indisponibilidades por
exámenes, eventos institucionales, refacciones ni reservas
externas; se dejan explícitamente por fuera del alcance, como se
detalla en §4.6.

### 4.3.3 La decisión: la asignación

La decisión a tomar es una **asignación** que empareja a cada
horario semanal del cuatrimestre con exactamente una aula. En
términos del marco de §4.2.1: cada entidad demandante consume un
recurso, y consume exactamente uno.

Vale la pena notar dos rasgos de esta decisión antes de seguir. El
primero es que la asignación no es una decisión aislada: como el
mismo aula puede recibir varios horarios distintos (siempre que no
sean simultáneos), las decisiones sobre distintos horarios están
acopladas entre sí. No se puede decidir aula por aula ni horario
por horario en forma independiente: el problema es **combinatorio y
acoplado**. El segundo es que la asignación es una decisión
**discreta**: cada par (horario, aula) está o no está, no admite
gradaciones. Este rasgo la ubica de lleno en el terreno de la
programación lineal entera que introdujimos en §2.3.

## 4.4 Restricciones

Las restricciones son las reglas que toda asignación tiene que
respetar para ser aceptable. Recordamos que en §2.3.5 introdujimos
la distinción entre restricciones **duras** (cuyo incumplimiento
descarta la solución) y **blandas** (cuyo incumplimiento se tolera
pero se penaliza en el criterio de comparación). En este capítulo
enumeramos las restricciones del problema en términos de negocio;
la clasificación dura/blanda y su expresión matemática se dejan
para el capítulo 8.

### 4.4.1 Restricciones estructurales

Son las que reflejan la naturaleza física y organizacional del
problema. Su incumplimiento no admite negociación:

- **Cada horario semanal debe tener asignada exactamente una aula.**
  No puede quedar sin aula (la clase no puede dictarse) ni tener
  asignadas dos aulas (una clase no puede estar en dos lugares al
  mismo tiempo).
- **No hay doble asignación en simultáneo.** Si dos horarios se
  dictan en algún instante común de la semana, no pueden compartir
  el aula. Ésta es la restricción que hace acoplado al problema.
- **Compatibilidad de tipo entre aula y clase.** Una clase teórica
  sólo puede dictarse en un aula teórica o en un anfiteatro; una
  clase de laboratorio sólo puede dictarse en un laboratorio
  compatible con la materia correspondiente. Esta compatibilidad
  materia-laboratorio la declara la propia cátedra y refleja
  requerimientos de equipamiento (mecheros, instrumental, puestos
  de trabajo).
- **Ventana operativa.** Ningún horario puede caer fuera de la
  franja horaria en que la facultad opera. Es una restricción
  defensiva: si un horario cargado por error cae fuera de la
  ventana, el sistema debe rechazarlo antes de intentar
  asignarlo.

### 4.4.2 Restricciones de política institucional

Estas restricciones no son físicas sino que reflejan decisiones
institucionales de la facultad:

- **Sedes admisibles por familia de materias.** No todas las
  materias pueden dictarse en cualquier sede. La política de la
  facultad agrupa a las materias en familias que comparten un
  criterio común: las del ciclo básico de las ingenierías se
  dictan en una sede; las del bloque troncal de ingeniería, en
  otra; las comunes de licenciaturas y profesorados, en una
  tercera; las específicas de cada carrera, donde esa carrera
  tenga sus recursos concentrados. El modelo agrupa las materias
  en **grupos** y para cada grupo declara qué sedes son admisibles
  y con qué criterio. Las excepciones (típicamente laboratorios
  que existen sólo en una sede específica) se manejan con reglas
  puntuales que desarrollamos en el capítulo 5.
- **Carga horaria declarada por la materia.** Cada materia declara
  en su plan de estudios cuántas horas semanales son de teoría y
  cuántas de laboratorio. La suma de duraciones de horarios teóricos
  de una comisión debe coincidir con las horas de teoría declaradas
  por la materia; análogamente con laboratorio.
- **Protección de trayectorias académicas.** Dos materias del mismo
  año y carrera que un alumno tipo cursaría en paralelo no pueden
  tener horarios superpuestos, para no bloquear el progreso
  académico. La restricción se aplica a nivel del par (año, carrera,
  cuatrimestre) y admite el matiz de que un alumno cursa una única
  comisión por materia: alcanza con que exista al menos un par
  compatible de comisiones para cada par de materias del grupo
  curricular.
- **Continuidad de sede entre bloques consecutivos.** Dos clases
  programadas en bloques contiguos del mismo día no pueden
  dictarse en sedes distintas si el gap entre ellas es menor a un
  margen configurable (por defecto, 30 minutos), porque el
  traslado apurado entre Pellegrini y el Centro Universitario
  Rosario deja de ser viable. La regla se aplica en dos ejes: al
  **docente** (dos horarios de la misma comisión no pueden caer
  en sedes distintas si están contiguos, porque el mismo profesor
  no viaja en el intervalo) y al **alumno** (dos horarios de
  materias distintas del mismo grupo curricular tampoco pueden
  hacerlo, porque un alumno tipo que cursa las dos necesita
  atravesar el traslado).
- **Camino de cursada intersede factible.** Para cada terna
  `(carrera, año, cuatrimestre)`, debe existir al menos una
  combinación de comisiones (una por materia obligatoria) que un
  alumno pueda cursar sin conflictos horarios ni traslados
  intersede imposibles. La regla refina la protección de
  trayectorias académicas incorporando la dimensión de sedes: no
  alcanza con que no haya superposiciones horarias; debe ser
  además factible caminar de una clase a la siguiente. El sistema
  verifica esta regla como chequeo estructural antes de correr el
  asignador.

Adicionalmente, la facultad enuncia dos políticas ligadas al
funcionamiento cotidiano que este trabajo trata de manera
diferenciada:

- **Estabilidad de sede en primer año.** Los estudiantes de primer
  año de cualquier carrera no deberían trasladarse de sede dentro
  de un mismo día de cursada. La política se justifica por la
  fragilidad logística de los ingresantes y la necesidad de
  facilitar su adaptación institucional. **Su implementación
  completa queda planteada como línea de continuación** (ver §4.6),
  dado que requiere una noción operativa de "cursada del alumno
  tipo de primer año" que hoy el modelo no consolida en una
  entidad.
- **Flexibilidad ante calendarios de exámenes.** Durante los
  períodos de exámenes suele ser necesario reubicar transitoriamente
  algunas clases, tanto por demanda de aulas grandes para toma de
  exámenes como por indisponibilidad puntual de espacios. El
  sistema debe permitir generar variantes transitorias de
  asignación sin descartar la asignación de base. La versión actual
  no modela indisponibilidades por examen como restricción del
  programa lineal; queda dentro del alcance operativo de las áreas
  responsables (ver §4.6.2).

### 4.4.3 Restricciones que expresan preferencias operativas

Finalmente, hay reglas que la facultad prefiere ver satisfechas
pero que puede tolerar violar cuando no queda alternativa. En el
marco de §2.3.5 son **restricciones blandas**:

- **Capacidad razonable respecto de los inscriptos.** El aula
  asignada debería tener capacidad suficiente para todos los
  inscriptos esperados en la comisión. Pero como los inscriptos
  reales no se conocen con precisión al momento de asignar (hay
  inscripción abierta hasta después del inicio de clases), esta
  restricción no puede tratarse como dura: el sistema debe poder
  producir una asignación aun cuando en algún horario haya una
  sobre-ocupación temporaria. Ver §4.5.
- **Sub-ocupación acotada.** Colocar 30 alumnos en un anfiteatro
  para 200 es admisible pero indeseable. La sub-ocupación se
  penaliza (con menos peso que la sobre-ocupación) para que las
  aulas grandes queden libres cuando efectivamente hacen falta.

## 4.5 Criterio de calidad

Una vez definida qué es una asignación **admisible** (una que
respeta todas las restricciones duras), corresponde definir cómo se
elige, entre las asignaciones admisibles, la **mejor**. Este es el
criterio de calidad.

En nuestro problema, el criterio se construye a partir de dos
magnitudes que se calculan sobre cada horario y luego se agregan:

- **Sobre-ocupación**: cantidad de inscriptos esperados que exceden
  la capacidad del aula asignada. Un valor positivo indica que hay
  alumnos que en principio no van a entrar; un valor cero o
  negativo indica que el aula alcanza.
- **Sub-ocupación**: cantidad de lugares vacíos en el aula respecto
  de un umbral mínimo de aprovechamiento. Un valor positivo indica
  que el aula quedó grande; un valor cero indica que el
  aprovechamiento es adecuado.

El criterio de calidad es la **suma ponderada** de la
sobre-ocupación total y la sub-ocupación total a lo largo de todos
los horarios. La suma se minimiza y la ponderación es
**asimétrica**: se penaliza mucho más la sobre-ocupación que la
sub-ocupación. Esta asimetría refleja una preferencia operativa
concreta: dejar alumnos afuera es peor que dejar bancos vacíos.
Los valores numéricos concretos de los pesos son parámetros
configurables de la solución y quedan documentados en el
capítulo 8.

Hay una decisión de diseño implícita en esta elección de criterio
que conviene explicitar: se optó por **codificar la capacidad como
una restricción blanda** en lugar de tratarla como dura. La razón
es la señalada en §4.4.3: la información de inscriptos al momento
de asignar es una estimación, no un dato firme, y una capacidad dura
convertiría en infactible al problema apenas apareciera una
comisión mal pronosticada. Codificarla como blanda permite obtener
siempre una asignación (eventualmente con sobre-ocupación
señalada) que las áreas responsables pueden después ajustar con
información más fresca.

## 4.6 Alcance y no-alcance

Con el problema definido, corresponde ahora hacer explícito qué
queda dentro del alcance del trabajo y qué queda fuera.

### 4.6.1 Dentro del alcance

- La asignación de aulas al **patrón semanal** de cada cuatrimestre
  de FCEIA, respetando todas las restricciones enumeradas en §4.4 y
  optimizando el criterio de §4.5.
- El **diagnóstico previo** de factibilidad estructural: identificar
  y comunicar al usuario cuándo el problema es infactible por
  razones puramente estructurales, antes de invocar al resolutor
  (capítulos 2.4 y 8).
- La **re-optimización dinámica** durante el cuatrimestre cuando
  aparecen cambios en el catálogo de comisiones o en los horarios
  cargados. El sistema permite volver a correr la asignación
  respetando decisiones ya tomadas que las áreas responsables
  quieran preservar.
- La **auditoría** de las corridas: cada ejecución del asignador
  queda registrada con sus parámetros y su resultado, para
  trazabilidad.

### 4.6.2 Fuera del alcance

El alcance definido arriba deja explícitamente afuera los siguientes
elementos, que se mencionan para acotar expectativas y para
identificar líneas de continuación del trabajo:

- **Excepciones puntuales por fecha.** El sistema decide sobre el
  patrón semanal. Cambios de aula para una fecha específica (una
  clase que un martes concreto se muda a otra aula sin afectar al
  patrón) no están soportados en la versión actual, aunque el
  modelo de datos preserva la posibilidad de reintroducirlos.
- **Indisponibilidades temporales de aulas.** Reservas externas por
  exámenes, actos, refacciones, uso por otras dependencias: no se
  modelan. La convención es que cada aula está disponible durante
  toda la ventana operativa.
- **Mesas de examen.** El calendario de exámenes es un proceso
  distinto (con sus propias reglas de superposición, capacidades
  típicas y actores) y no forma parte del alcance del asignador.
- **Otros recursos.** El sistema se concentra en aulas y
  laboratorios; no gestiona la asignación de otros recursos que la
  facultad también coordina (proyectores, personal auxiliar,
  espacios de reunión).
- **Pronóstico avanzado de inscripción.** El sistema toma como
  entrada un valor de inscriptos esperados por comisión, pero no
  incluye un módulo sofisticado de predicción de inscripción
  basado en historial. Se lo señala como línea de continuación.
- **Optimización multi-cuatrimestre.** Cada cuatrimestre se
  resuelve independientemente. La coordinación entre cuatrimestres
  (por ejemplo, materias anuales que abarcan ambos) se maneja
  operativamente pero no como parte de la optimización.

## 4.7 Naturaleza combinatoria y efecto cascada

Con el problema ya definido, corresponde caracterizar dos rasgos que
lo distinguen y que motivan la aproximación técnica del resto del
informe.

### 4.7.1 Naturaleza combinatoria

Un cuatrimestre típico de FCEIA involucra del orden de varios
cientos de horarios semanales (cada combinación materia, comisión,
día, franja es uno) y del orden de varias decenas de aulas
distribuidas entre las dos sedes. Si toda combinación horario-aula
fuera admisible, el espacio de asignaciones tendría una cantidad de
elementos del orden de `aulas^horarios`, es decir, un número con
tres cifras elevado a un número con tres cifras. Este espacio es
astronómico (muchos órdenes de magnitud más grande que la cantidad
de átomos en el universo observable) y hace inviable cualquier
enumeración exhaustiva.

Las restricciones enumeradas en §4.4 recortan drásticamente ese
espacio: la mayoría de las combinaciones horario-aula no son
admisibles por incompatibilidad de tipo, de sede o por
simultaneidad. Pero aun así, el espacio de asignaciones admisibles
sigue siendo demasiado grande para explorarlo a mano. Este es el
argumento cuantitativo detrás de la afirmación cualitativa hecha en
§3.3.3: la asignación óptima manual está fuera del alcance humano.

El aparato de la programación lineal entera introducido en §2.3.2
está justamente pensado para navegar espacios como éste: la
formulación combinada de restricciones y la técnica de ramificación
y acotación descartan sistemáticamente subespacios enteros de
soluciones sin visitar cada una, y aprovechan la cota de la
relajación lineal para converger al óptimo. Es la herramienta
apropiada para el tipo de espacio de búsqueda que este problema
presenta.

### 4.7.2 Efecto cascada

Un rasgo adicional del problema, directamente ligado a la
observación operativa del capítulo 3, es el **efecto cascada**: una
perturbación local en las condiciones iniciales puede requerir
reajustes de muchas asignaciones aparentemente independientes.

La explicación estructural del fenómeno es simple. Supongamos que
la comisión A de una materia teórica queda asignada al aula X. Si a
mitad de cuatrimestre se abre una comisión nueva B en la misma
franja horaria, el aula X ya no puede recibir a las dos: hay que
mover a A o a B a otra aula. Pero esa otra aula, si es la única
libre de tipo compatible en esa franja, quizás estaba ocupada por
otra comisión C en un horario contiguo; y así, la reasignación se
propaga hasta encontrar un nuevo equilibrio. Cuanto más ajustada
esté la asignación original (cuanto menos "slack" de aulas libres
haya en cada franja), más largo puede ser el efecto cascada.

Este fenómeno hace que las re-planificaciones sean cualitativamente
distintas de las planificaciones iniciales: no basta con "resolver
el nuevo requerimiento", hay que verificar globalmente que el
resto sigue siendo consistente. Es también uno de los motivos por
los que la re-optimización asistida por un modelo formal es
particularmente valiosa: un sistema puede computar la cascada
completa en segundos, mientras que un operador humano típicamente
la resuelve por aproximaciones sucesivas y con riesgo de
inconsistencias.

## 4.8 Recapitulación

Este capítulo tradujo el problema de asignación de aulas de la
descripción operativa del capítulo 3 a una definición formal, sin
haber todavía escrito el modelo matemático. Los cuatro puntos que
quedan fijados y se retoman en los capítulos siguientes son:

1. **El problema es un caso de asignación de recursos bajo
   restricciones.** Está encuadrado dentro de una familia bien
   estudiada por la investigación de operaciones, con vocabulario y
   herramientas maduras (§4.2).
2. **Las entidades del problema son horarios semanales y aulas**, y
   la decisión es un emparejamiento uno-a-uno de horarios a aulas
   (§4.3).
3. **Las restricciones se organizan en tres familias**: estructurales
   (siempre duras), de política institucional (típicamente duras) y
   de preferencia operativa (blandas, con penalización asimétrica
   sobre-ocupación / sub-ocupación) (§4.4 y §4.5).
4. **El problema es combinatoriamente grande y presenta efecto
   cascada**, dos rasgos que motivan el uso del aparato de
   programación lineal entera y de diagnóstico estructural
   presentado en el capítulo 2 (§4.7).

Con esto se cierra la Parte II del informe: el problema está
comprendido en su operatoria (capítulo 3) y definido en su
estructura formal (capítulo 4). La Parte III retoma la definición
para construir el modelo del dominio y su traducción al modelo de
datos, sobre los cuales se apoyará después la formulación
matemática del capítulo 8.
