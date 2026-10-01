# Capítulo 4. Definición del problema

El capítulo 3 describió cómo se asignan hoy las aulas en la FCEIA:
quién decide, cuándo, con qué información y con qué resultado. Este
capítulo traduce esa descripción a un enunciado preciso, en el marco
de la investigación de operaciones presentado en §2.3, de modo que
más adelante pueda modelarse como un programa lineal entero sin
sorpresas. Para eso fijamos qué datos tenemos, qué decidimos, qué
reglas debe respetar la decisión y con qué criterio se compara una
asignación con otra.

## 4.1 Formulación coloquial

::: revisar
<!-- Sección a cargo de Pablo Galliano (comentario @maguitopg en la revisión del 2026-09-30): se deja tal cual, resaltada para revisar. -->

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
:::

## 4.2 Encuadre: el problema como asignación de recursos bajo restricciones

### 4.2.1 Qué es un problema de asignación de recursos

La investigación de operaciones estudia una familia de problemas,
los **problemas de asignación de recursos bajo restricciones**, que
sirve de marco general para situaciones como la descripta. Es una
herramienta habitual del ingeniero porque permite formalizar con un
mismo esquema problemas en apariencia muy distintos: turnos
hospitalarios, mantenimiento de flotas, programación de la
producción. Todos se caracterizan por:

- Un conjunto de **entidades demandantes** que necesitan consumir
  recursos (tareas, personas, mercadería, clases).
- Un conjunto de **recursos disponibles**, típicamente escasos
  (máquinas, salas, camiones, aulas).
- **Reglas de compatibilidad y restricción** que determinan qué
  asignaciones son admisibles (esta persona no puede estar en dos
  salas a la vez, esta aula no es apta para química).
- Uno o más **criterios de calidad** que permiten decidir cuál de
  dos asignaciones admisibles es mejor (menor costo, mejor
  aprovechamiento, mayor cobertura).

Lo que cambia de un caso a otro son las entidades concretas y las
reglas específicas; la estructura lógica es la misma. Esta familia
admite formulaciones matemáticas estándar, en particular como
programas lineales enteros (§2.3), de modo que encuadrar en ella la
asignación de aulas nos permite aprovechar métodos ya desarrollados
en lugar de inventarlos desde cero.

### 4.2.2 Ubicación del problema de asignación de aulas dentro de la familia

La Tabla @tab:familia muestra cómo se instancia cada elemento del marco en
nuestro problema.

<!-- tabla: Ubicación del problema dentro de la familia de problemas de asignación {#tab:familia} -->
| Elemento del marco | Instancia en nuestro problema |
| --- | --- |
| Entidades demandantes | **Horarios semanales de clase**: cada franja recurrente de dictado de una comisión, en un día y un rango horario, necesita un aula. |
| Recursos disponibles | **Aulas** de la FCEIA, en sus distintas tipologías, con sus capacidades y sedes. |
| Restricciones | Compatibilidad entre tipo de aula y tipo de clase; no simultaneidad en la misma aula; sedes admisibles; carga horaria de teoría y de laboratorio de cada materia; horario de funcionamiento de la facultad. |
| Criterio de calidad | Equilibrio entre **no dejar alumnos afuera** y **no desperdiciar capacidad**. |

La formulación matemática concreta (variables, restricciones y
función objetivo) queda para el capítulo 8.

## 4.3 Elementos del problema

### 4.3.1 La entidad demandante: el horario semanal

La unidad sobre la que se decide no es cada clase con su fecha, sino
el **horario semanal**: la franja que se repite todas las semanas
del cuatrimestre en el mismo día y rango horario. Un horario semanal
corresponde a una comisión de una materia, tiene un día, una hora de
inicio y una de fin, y es de teoría o de laboratorio (tipo que puede
venir fijado por el cronograma o quedar por decidir). El capítulo 5
formaliza esta noción.

La elección es una cuestión de economía: un cuatrimestre tiene
cientos de horarios semanales pero miles de clases con fecha. Como
el patrón se repite, resolver una vez por horario equivale a
resolver una vez por clase, con un modelo mucho más chico.

La grilla oficial de la facultad (§3.1.4) organiza el día en turnos
y bloques de 45 minutos, pero en la práctica las Escuelas no
siempre ajustan sus horarios a esos bloques. Por eso el modelo toma
las horas de inicio y fin efectivas que declara cada cátedra y deja
la grilla como referencia, no como restricción.

### 4.3.2 El recurso: el aula

El **aula** es el recurso que se asigna. Cada aula pertenece a una
**sede** (Pellegrini o Centro Universitario Rosario), tiene un
**tipo** dentro de la tipología de §3.1.3 (aula teórica,
laboratorio, anfiteatro) y una **capacidad**, es decir, la cantidad
máxima de alumnos que alberga en condiciones adecuadas.

Asumimos que las aulas están disponibles durante todo el horario de
funcionamiento de la facultad, típicamente de 8 a 23 h. Las
indisponibilidades por exámenes, actos, refacciones o reservas
externas quedan fuera del alcance (§4.6).

### 4.3.3 La decisión: la asignación

La decisión es una **asignación** que empareja cada horario semanal
del cuatrimestre con exactamente un aula. Tiene dos rasgos que
conviene destacar. Es **acoplada**: como un aula recibe varios
horarios que no se superponen, decidir sobre un horario condiciona
a los demás, y no se puede resolver horario por horario en forma
independiente. Y es **discreta**: cada horario está o no está en
cada aula, sin gradaciones. Ambos rasgos la ubican en el terreno de
la programación lineal entera (§2.3).

## 4.4 Restricciones

Las restricciones son las reglas que toda asignación debe respetar.
En §2.3.5 distinguimos las restricciones **duras**, cuyo
incumplimiento descarta la solución, de las **blandas**, que se
pueden violar a cambio de una penalización. Acá las enunciamos en
términos del dominio; su expresión matemática se desarrolla en el
capítulo 8.

### 4.4.1 Restricciones estructurales

Reflejan la naturaleza física del problema y no admiten
negociación:

- **Un aula por horario.** Cada horario semanal recibe exactamente
  un aula: ni queda sin aula ni ocupa dos.
- **Sin superposición en un aula.** Dos horarios que coinciden en
  algún momento de la semana no pueden compartir aula. Es la regla
  que acopla el problema.
- **Compatibilidad de tipo.** Una clase teórica va a un aula teórica
  o a un anfiteatro; una clase de laboratorio, a un laboratorio
  apto para esa materia, según el equipamiento que la cátedra
  declara necesario.
- **Horario de funcionamiento.** Ningún horario puede quedar fuera
  de la franja en que opera la facultad; si alguno se carga por
  error, el sistema lo rechaza antes de asignar.

### 4.4.2 Restricciones de política institucional

No responden a límites físicos sino a decisiones de la facultad:

- **Sedes admisibles.** Las materias se agrupan según un criterio
  común (ciclo básico de las ingenierías, bloque troncal de
  ingeniería, materias comunes de licenciaturas y profesorados,
  materias específicas de cada carrera) y cada grupo tiene sus
  sedes admisibles. Las excepciones, típicamente laboratorios que
  sólo existen en una sede, se tratan con reglas puntuales
  (capítulo 5).
- **Carga horaria.** Las horas semanales de teoría y de laboratorio
  de cada comisión deben coincidir con las que fija el plan de
  estudios para la materia.
- **Trayectorias académicas.** Las materias del mismo año y
  carrera, que un alumno cursaría en paralelo, no deben
  superponerse. Como cada alumno cursa una sola comisión por
  materia, alcanza con que exista al menos una combinación de
  comisiones compatible.
- **Traslados entre sedes.** Dos clases consecutivas del mismo día
  no pueden dictarse en sedes distintas si el intervalo entre ellas
  es menor a un margen (por defecto, 30 minutos), porque el
  traslado entre Pellegrini y el Centro Universitario Rosario deja
  de ser viable. La regla protege tanto al docente de una misma
  comisión como al alumno que cursa materias del mismo año.
- **Cursada posible.** Para cada carrera, año y cuatrimestre debe
  existir al menos una combinación de comisiones, una por materia
  obligatoria, que un alumno pueda cursar sin superposiciones ni
  traslados imposibles. El sistema la verifica antes de asignar.

La facultad enuncia además dos políticas que este trabajo no
incorpora como restricciones del modelo y que se retoman en §4.6:
que los ingresantes no cambien de sede dentro de un mismo día de
cursada, para facilitar su adaptación, y que durante los períodos
de exámenes se puedan generar variantes transitorias de la
asignación sin perder la de base.

### 4.4.3 Restricciones que expresan preferencias operativas

Son las reglas que la facultad prefiere ver cumplidas pero que
puede tolerar violar cuando no queda alternativa, es decir,
restricciones blandas:

- **Capacidad suficiente.** El aula debería alojar a todos los
  inscriptos esperados. Como la inscripción sigue abierta después
  del inicio de clases, ese número es una estimación, y el sistema
  debe poder asignar aun cuando algún horario quede sobreocupado.
- **Aulas no desaprovechadas.** Poner 30 alumnos en un anfiteatro
  para 200 es admisible pero indeseable: se penaliza, con menos
  peso que la sobreocupación, para reservar las aulas grandes a
  quienes las necesitan.

## 4.5 Criterio de calidad

Entre las asignaciones **admisibles**, las que respetan todas las
restricciones duras, hay que elegir la **mejor**. El criterio se
arma con dos magnitudes calculadas para cada horario:

- **Sobreocupación**: inscriptos esperados que exceden la capacidad
  del aula.
- **Subocupación**: lugares vacíos por debajo de un umbral mínimo
  de aprovechamiento.

Se busca minimizar la suma ponderada de ambas a lo largo de todos
los horarios, con una ponderación **asimétrica**: dejar alumnos
afuera es peor que dejar bancos vacíos. Los pesos son parámetros
configurables y se presentan en el capítulo 8.

Tratar la capacidad como restricción blanda es una decisión
deliberada. Si fuera dura, bastaría con una comisión mal
pronosticada para que el problema no tuviera solución; como blanda,
el sistema siempre propone una asignación, señalando la
sobreocupación, que las áreas responsables pueden ajustar luego con
información más precisa.

## 4.6 Alcance y no-alcance

### 4.6.1 Dentro del alcance

- La asignación de aulas al **patrón semanal** de cada cuatrimestre
  de la FCEIA, respetando las restricciones de §4.4 y optimizando
  el criterio de §4.5.
- El **diagnóstico previo**: detectar y comunicar cuándo el problema
  no tiene solución por razones estructurales, antes de resolverlo
  (§2.4 y capítulo 8).
- La **reasignación durante el cuatrimestre** cuando cambian las
  comisiones o los horarios, conservando las decisiones que las
  áreas responsables quieran mantener.
- El **registro de cada asignación** realizada, con sus parámetros
  y su resultado, para poder rastrearla.

### 4.6.2 Fuera del alcance

- **Cambios para una fecha puntual**, como una clase que un martes
  determinado se muda de aula sin alterar el patrón semanal.
- **Indisponibilidades temporales de aulas** por exámenes, actos,
  refacciones o uso de otras dependencias.
- **Mesas de examen**, que son un proceso distinto, con sus propias
  reglas y actores.
- **Estabilidad de sede para ingresantes**, que requiere modelar la
  cursada típica de primer año y queda como línea de continuación.
- **Otros recursos** que la facultad coordina, como proyectores,
  personal auxiliar o salas de reunión.
- **Pronóstico de inscripción** a partir del historial: el sistema
  recibe los inscriptos esperados como dato.
- **Coordinación entre cuatrimestres**: cada uno se resuelve por
  separado y las materias anuales se manejan operativamente.

## 4.7 Naturaleza combinatoria y efecto cascada

### 4.7.1 Naturaleza combinatoria

Un cuatrimestre de la FCEIA involucra varios cientos de horarios
semanales y varias decenas de aulas. Si cualquier combinación fuera
admisible, la cantidad de asignaciones posibles sería del orden de
`aulas^horarios`: un número astronómico, muchos órdenes de magnitud
mayor que la cantidad de átomos del universo observable, que vuelve
imposible cualquier enumeración exhaustiva.

Las restricciones de §4.4 descartan la mayoría de esas
combinaciones, pero lo que queda sigue siendo demasiado para
explorarlo a mano. Es el argumento cuantitativo detrás de lo
afirmado en §3.3.3: la asignación óptima manual está fuera del
alcance humano. La programación lineal entera (§2.3.2) está pensada
justamente para estos casos: la técnica de ramificación y acotación
descarta subconjuntos enteros de soluciones sin recorrerlas una por
una.

### 4.7.2 Efecto cascada

El segundo rasgo, ligado a lo observado en el capítulo 3, es el
**efecto cascada**: un cambio local puede obligar a reajustar
muchas asignaciones en apariencia independientes. Supongamos que un
aula deja de estar disponible, por ejemplo porque entra en
mantenimiento, y que el horario que tenía asignado sólo entra en
aulas que ya están ocupadas en esa franja. Para ubicarlo hay que
desplazar a otro horario, que a su vez necesita un aula libre, y así
sucesivamente, como muestra la Figura @fig:cascada. Cuanto
menos holgura de aulas libres haya en cada franja, más larga puede
ser la cadena.

![Efecto cascada: un aula en mantenimiento obliga a reacomodar tres horarios](figuras/efecto_cascada.png){#fig:cascada width=13cm}

Por eso replanificar no es sólo atender el cambio puntual: hay que
verificar que todo el resto siga siendo consistente. Un sistema con
un modelo formal recalcula la cascada completa en segundos, mientras
que una persona la resuelve por aproximaciones sucesivas y con
riesgo de inconsistencias.

## 4.8 Recapitulación

El capítulo dejó fijados cuatro puntos que se retoman más adelante:

1. **El problema es un caso de asignación de recursos bajo
   restricciones**, una familia bien estudiada por la investigación
   de operaciones (§4.2).
2. **Las entidades son horarios semanales y aulas**, y la decisión
   asigna a cada horario exactamente un aula (§4.3).
3. **Las restricciones se agrupan en tres familias**: estructurales
   (duras), de política institucional (en general duras) y de
   preferencia operativa (blandas, con penalización asimétrica entre
   sobreocupación y subocupación) (§4.4 y §4.5).
4. **El problema es combinatoriamente grande y presenta efecto
   cascada**, lo que justifica la programación lineal entera y el
   diagnóstico previo presentados en el capítulo 2 (§4.7).

Con esto el problema queda comprendido en su operatoria (capítulo 3)
y definido en su estructura (capítulo 4). La Parte III construye
sobre esta definición el modelo del dominio, base de la formulación
matemática del capítulo 8.
