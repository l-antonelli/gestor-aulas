# Capítulo 5. El modelo conceptual

En los capítulos 3 y 4 la operatoria y el problema quedaron descritos
al nivel de "qué se hace y qué hay que decidir". Este capítulo da el
paso siguiente: identificar las entidades del dominio, sus relaciones
y las reglas de negocio que las gobiernan. Es el primer eslabón de la
cadena introducida en §2.5.1, el **modelo conceptual del dominio**; su
traducción a un esquema de datos queda para el capítulo 6, y su uso
como piezas del programa lineal, para el capítulo 8.

El objetivo es doble. Por un lado, fijar un **lenguaje ubicuo** en el
sentido de Evans [3] (§2.2): los términos de este capítulo son los
mismos que aparecen en la interfaz del sistema y en el resto del
informe. Por otro, hacer explícitas las **reglas de negocio** que la
FCEIA aplica en la práctica y que hoy viven mayormente en el criterio
de las personas.

## 5.1 Enfoque metodológico: modelado en capas

Una facultad tiene muchas entidades (alumnos, profesores,
inscripciones, exámenes, aulas, materias, comisiones), pero no todas
son relevantes para asignar aulas. Modelizar sin filtrar produce
diagramas grandes y poco informativos; filtrar sin justificar impide
reconstruir por qué ciertas entidades quedaron dentro y otras afuera.
Por eso organizamos el modelo en **tres capas** (Figura 3).

<!-- figura: Enfoque de modelado en tres capas -->
```mermaid
flowchart LR
    C1["<b>Dominio del problema<br/>(completo)</b><br/><br/>Todas las entidades reales<br/>que existen en la FCEIA"]
    C2["<b>Dominio del problema<br/>(delimitado)</b><br/><br/>Entidades directamente<br/>relevantes para la<br/>asignación de aulas"]
    C3["<b>Dominio de la solución</b><br/><br/>Entidades adicionales<br/>que introducimos para<br/>modelizar la solución"]

    C1 -->|"delimitación<br/>del alcance"| C2
    C2 -->|"derivación<br/>de abstracciones"| C3

    classDef body fill:#fffbe6,stroke:#c9a227,color:#000
    class C1,C2,C3 body
```

La primera capa reúne todo lo que existe en la vida de la facultad.
La segunda es el subconjunto mínimo con el que se puede describir el
problema sin recortarlo. La tercera agrega entidades que no existen
en la FCEIA como objetos independientes, pero que introducimos porque
simplifican la solución; típicamente, convierten una relación
muchos-a-muchos entre dos entidades del dominio en dos relaciones
uno-a-muchos a través de una entidad intermedia.

## 5.2 Entidades del dominio del problema

Del inventario completo de la facultad, el problema de asignación
definido en el capítulo 4 sólo necesita una parte. Quedan **fuera del
alcance**:

- **Alumno** e **inscripción**: la asignación decide sobre horarios y
  aulas, no sobre personas; del alumnado sólo importa la cantidad
  esperada por comisión.
- **Profesor**: no afecta la capacidad ni la disponibilidad de las
  aulas, y la asignación de docentes es un problema distinto que no
  abordamos.
- **Asistencia**: es una consecuencia observable del dictado, no una
  entrada del proceso.

Quedan **dentro del alcance** la carrera, el plan de estudios y la
materia (qué se dicta y con qué requerimientos); la comisión (los
grupos de dictado); el aula y la sede (los recursos que se asignan);
el ciclo lectivo (el marco temporal); el cronograma (la entrada del
proceso) y la clase (cada encuentro concreto en el calendario).

## 5.3 Las entidades del modelo

Presentamos las entidades agrupadas según el papel que cumplen. Para
cada una indicamos qué representa y para qué sirve; los atributos y
su codificación se tratan en el capítulo 6 y en el anexo A.

### 5.3.1 La oferta académica

La **carrera** es un programa de grado o tecnicatura que ofrece la
facultad. Su contenido se describe en un **plan de estudios**, que
modelamos como entidad propia porque una misma carrera puede tener
varias versiones vigentes a la vez (por ejemplo, un plan anterior
para alumnos avanzados y uno nuevo para los ingresantes).

La **materia** es una asignatura del catálogo de la facultad,
independiente de la carrera: una misma materia puede figurar en los
planes de varias carreras. Lo que la caracteriza para la asignación
es su carga horaria semanal, dividida en horas de teoría y de
laboratorio, y si se dicta en forma cuatrimestral o anual.

Entre plan y materia hay una relación muchos-a-muchos que resolvemos
con una entidad del dominio de la solución, la **entrada de plan de
estudios**: indica en qué año y cuatrimestre del plan se ubica cada
materia. Las **correlativas**, a su vez, expresan qué materias deben
haberse cursado antes que otras dentro de una carrera; no intervienen
en la asignación de aulas, pero sirven para verificar que el
cronograma sea cursable por un alumno tipo.

### 5.3.2 Los recursos físicos

La **sede** es un edificio de la facultad que agrupa aulas. El
**aula** es el espacio físico donde se dicta, pertenece a una única
sede y se caracteriza por su capacidad y su tipo (teórica,
laboratorio, anfiteatro, práctica).

No todo laboratorio sirve para cualquier materia: una materia de
electrónica necesita un laboratorio con instrumental de electrónica.
La **compatibilidad materia-laboratorio** registra qué laboratorios
son técnicamente aptos para la parte práctica de cada materia; una
materia puede tener varios laboratorios compatibles y un laboratorio
puede servir a varias materias.

### 5.3.3 La planificación del cuatrimestre

El **ciclo lectivo** es cada cuatrimestre de operación académica y
contextualiza todo lo demás: en él están vigentes ciertas versiones
de los planes de estudio, se carga el cronograma y se arma la
planificación.

El **dictado** representa la oferta efectiva de una materia en un
ciclo. Existe como entidad porque "la materia dictándose en un ciclo"
tiene características propias que ni la materia ni el ciclo aportan
por separado: si se ofrece o no, sus fechas de inicio y fin, y si ese
cuatrimestre se dicta en forma virtual.

El **cronograma** es el conjunto de horarios que entrega la
coordinación cada cuatrimestre, normalmente como planilla de cálculo.
Es el material de partida del que se derivan las comisiones y sus
horarios.

El **plan de cursada** es un escenario concreto de planificación para
un ciclo: reúne todas las comisiones que se van a abrir, sus horarios
y, una vez resuelto el problema, las aulas asignadas. Un ciclo puede
tener varios planes de cursada para comparar alternativas, pero sólo
uno activo.

La **comisión** es un grupo de estudiantes que cursa una materia con
un mismo esquema semanal; una materia puede abrir varias comisiones.
Cada comisión se compone de **horarios semanales**: franjas
recurrentes con día, hora de inicio, hora de fin y tipo de clase
(teoría o laboratorio). El horario semanal es la unidad sobre la que
se decide el aula, según se justificó en §4.3.1. Finalmente, la
**clase** es cada encuentro concreto en una fecha del calendario; se
obtiene repitiendo el horario semanal a lo largo del ciclo y hereda
su aula.

### 5.3.4 El grupo de materias

La pregunta "¿en qué sedes puede dictarse esta materia?" no se
responde materia por materia, sino por bloques: las materias del
ciclo básico de las ingenierías comparten un criterio, las del bloque
troncal de ingeniería otro, las comunes a licenciaturas y
profesorados otro, y las específicas de cada carrera el suyo. El
**grupo de materias** captura ese criterio. Cada materia pertenece a
exactamente un grupo, y cada grupo declara dos configuraciones de
sedes:

- un **conjunto duro**: las únicas sedes admisibles cuando el grupo
  se resuelve con criterio estricto;
- una **lista blanda ordenada**: las sedes preferidas cuando el
  grupo se resuelve con criterio flexible; la primera no tiene costo
  y las demás se aceptan con una penalización.

El criterio con que se resuelve cada grupo se elige en cada corrida
del asignador. Esto permite, por ejemplo, resolver un mismo plan una
vez con criterio estricto, para verificar su factibilidad, y otra con
criterio flexible, para reducir traslados. Las materias que todavía
no se clasificaron caen en un grupo *sin clasificar*, cuya presencia
el sistema señala como advertencia. El grupo de materias interviene
en las restricciones R8 y R10 del programa lineal (capítulo 8).

## 5.4 Relaciones y multiplicidades

La mayoría de las relaciones del modelo son simples, de uno a muchos:
una sede tiene muchas aulas, un ciclo tiene varios cronogramas y
planes de cursada, una comisión tiene varios horarios semanales y
cada horario genera muchas clases. Pero, como anticipamos en §2.4.1 y
en el diagnóstico de §3.4, en la asignación de aulas las relaciones
muchos-a-muchos son la norma más que la excepción. Cada una se
resuelve con una entidad intermedia del dominio de la solución
(Tabla 3).

<!-- tabla: Relaciones muchos a muchos y sus entidades intermedias -->
| Relación conceptual | Entidad intermedia | Qué aporta la intermedia |
| --- | --- | --- |
| Materia con carrera | Entrada de plan de estudios | Año y cuatrimestre dentro de una versión del plan |
| Materia con laboratorio | Compatibilidad materia-laboratorio | Sólo la afirmación de compatibilidad |
| Grupo de materias con sede | Sede del grupo | Tipo de configuración (dura o blanda) y orden de preferencia |
| Materia con ciclo lectivo | Dictado | Fechas efectivas y virtualidad del ciclo |

Cuando la relación tiene características propias (el año del plan, la
virtualidad del ciclo, el orden de preferencia), la entidad intermedia
es imprescindible. Cuando no las tiene, como en la compatibilidad
materia-laboratorio, la mantenemos igual por uniformidad y porque
facilita las verificaciones.

## 5.5 Reglas de negocio e invariantes

Las **reglas de negocio** son afirmaciones sobre el comportamiento de
las entidades que no se deducen de sus definiciones y que el sistema
debe garantizar. Muchas son **invariantes** en el sentido de Evans
[3] (§2.2.2): deben cumplirse en todo momento. Las agrupamos por
familia.

### 5.5.1 Reglas estructurales

- Todo horario semanal pertenece a exactamente una comisión.
- Toda comisión pertenece a exactamente una materia y a un plan de
  cursada.
- Todo dictado pertenece a una materia y se vincula con uno o dos
  ciclos (§5.5.5).
- Cada ciclo tiene a lo sumo un plan de cursada activo; los demás son
  escenarios de comparación.
- Toda aula pertenece a exactamente una sede.

### 5.5.2 Regla de virtualidad jerárquica

Un horario *virtual* se dicta a distancia y no consume aula. La
virtualidad puede declararse en tres niveles: en la **materia** (se
dicta virtual por diseño), en el **dictado** (es virtual sólo ese
cuatrimestre) o en el **horario semanal** (un encuentro puntual de
una comisión híbrida). Se resuelve en cascada: prevalece el nivel más
específico que tenga un valor definido; si el horario no lo define,
se toma el del dictado, y si tampoco, el de la materia. La invariante
asociada es que **los horarios efectivamente virtuales no participan
de la asignación**: se excluyen antes de armar el programa lineal.

### 5.5.3 Regla de sedes admisibles por grupo de materias

Cada materia tiene un conjunto de **sedes admisibles** que surge de su
grupo (§5.3.4) y del criterio con que ese grupo se resuelve:

- con criterio **estricto**, las sedes admisibles son las del
  conjunto duro del grupo; si ese conjunto está vacío (caso reservado
  al grupo sin clasificar), se admiten todas;
- con criterio **flexible**, se admiten todas las sedes, pero elegir
  otra que no sea la primera de la lista tiene un costo;
- como **excepción**, si la materia tiene un laboratorio compatible
  en una sede fuera de su grupo, esa sede también se admite: la
  aptitud física del laboratorio prevalece sobre la preferencia
  curricular.

La invariante asociada es que **toda aula asignada está en una sede
admisible para la materia del horario, o bien es un laboratorio
compatible con ella**. Este esquema reúne en un solo mecanismo dos
preocupaciones de la operatoria: las sedes propias de cada carrera
(a través del grupo de sus materias específicas) y las sedes
habituales de las materias comunes (a través de los grupos
transversales).

### 5.5.4 Regla de recursado

Algunas carreras ofrecen materias también en el cuatrimestre opuesto
al que les corresponde, para facilitar el recursado. La política se
declara en dos niveles con la misma lógica de cascada que la
virtualidad: la **carrera** indica si ofrece recursado y la
**materia** puede sobrescribir esa indicación en un sentido u otro.
La invariante asociada es que **al generar los dictados de un ciclo
sólo se crean los que la regla de recursado permite**.

### 5.5.5 Regla de materias anuales

Una materia anual se dicta durante los dos cuatrimestres del año, por
lo que su dictado se vincula con ambos ciclos y mantiene los mismos
horarios en los dos. El asignador resuelve cada cuatrimestre por
separado; la coordinación entre ambos queda a cargo de la operatoria.
La invariante es que **todo dictado se vincula con tantos ciclos como
indica la periodicidad de su materia**: uno si es cuatrimestral, los
dos del mismo año si es anual.

### 5.5.6 Regla de coherencia teoría-laboratorio

En cada comisión, la suma de las duraciones de los horarios de teoría
debe coincidir con las horas de teoría declaradas por la materia, y
lo mismo para las de laboratorio. La regla se refleja en la
restricción R4 del programa lineal (capítulo 8): si el cronograma no
permite un reparto que respete la carga declarada, el problema
resulta infactible.

### 5.5.7 Reglas de política institucional

La operatoria de la FCEIA impone además políticas ligadas a la
logística de alumnos y docentes. Las enunciamos acá como reglas del
dominio e indicamos dónde se las trata:

- **Cursada sin superposiciones.** Para cada carrera, año y
  cuatrimestre debe existir al menos una combinación de comisiones,
  una por materia obligatoria, que un alumno pueda cursar sin
  conflictos horarios ni traslados imposibles entre sedes. Se
  verifica antes de resolver el programa lineal (capítulos 8 y 9).
- **Continuidad de sede para el docente.** Dos horarios de la misma
  comisión en el mismo día, separados por menos de un margen
  configurable (30 minutos por defecto), deben dictarse en la misma
  sede (restricción R11 del capítulo 8).
- **Continuidad de sede para el alumno.** La misma condición se
  aplica a horarios consecutivos de materias distintas de una misma
  carrera, año y cuatrimestre, para que el alumno tipo pueda pasar de
  una clase a la siguiente (restricción R11).
- **Misma sede por comisión.** Opcionalmente, todos los horarios de
  una comisión deben caer en la misma sede, porque ciertos docentes
  no se trasladan entre sedes durante la semana (restricción R12).
- **Flexibilidad por calendario de exámenes.** En los períodos de
  exámenes debe poder generarse una variante transitoria de la
  asignación sin perder la de base. Queda fuera del programa lineal y
  se maneja en la operatoria (§4.6.2).

## 5.6 Diagrama UML del dominio

Las Figuras 4 y 5 resumen las entidades y sus relaciones en un
diagrama de clases UML, partido en dos para que se lea con comodidad
y sin atributos. Cada línea es una asociación y los números indican
cuántas instancias participan de cada lado (`*` significa "muchas").
La Figura 4 muestra la oferta académica y los recursos físicos; la
Figura 5, la planificación del cuatrimestre. Ambas se conectan a
través de la materia y el aula.

<!-- figura: Diagrama de clases del dominio: oferta académica y recursos -->
```mermaid
---
config:
  class:
    hideEmptyMembersBox: true
---
classDiagram
    direction TB
    class Carrera
    class PlanDeEstudios["Plan de estudios"]
    class EntradaDePlan["Entrada de plan"]
    class Materia
    class GrupoDeMaterias["Grupo de materias"]
    class Sede
    class Aula

    Carrera "1" -- "*" PlanDeEstudios
    PlanDeEstudios "1" -- "*" EntradaDePlan
    EntradaDePlan "*" -- "1" Materia
    Materia "*" -- "1" GrupoDeMaterias : pertenece a
    GrupoDeMaterias "*" -- "*" Sede : sedes admisibles
    Sede "1" -- "*" Aula
    Materia "*" -- "*" Aula : laboratorios compatibles
```

<!-- figura: Diagrama de clases del dominio: planificación del cuatrimestre -->
```mermaid
---
config:
  class:
    hideEmptyMembersBox: true
---
classDiagram
    direction TB
    class Materia
    class Dictado
    class CicloLectivo["Ciclo lectivo"]
    class Cronograma
    class PlanDeCursada["Plan de cursada"]
    class Comision["Comisión"]
    class HorarioSemanal["Horario semanal"]
    class Aula

    Materia "1" -- "*" Dictado
    Dictado "*" -- "1..2" CicloLectivo
    CicloLectivo "1" -- "*" Cronograma
    CicloLectivo "1" -- "*" PlanDeCursada
    Cronograma "1" -- "*" PlanDeCursada : origina
    PlanDeCursada "1" -- "*" Comision
    Materia "1" -- "*" Comision
    Comision "1" -- "*" HorarioSemanal
    HorarioSemanal "*" -- "0..1" Aula : se asigna
```

Las relaciones rotuladas *sedes admisibles* y *laboratorios
compatibles* se materializan con las entidades intermedias de la
Tabla 3. Para no recargar las figuras omitimos las correlativas y las
clases, que se derivan de entidades ya presentes.

## 5.7 Recapitulación

El capítulo dejó fijado el modelo conceptual del dominio:

1. **Tres capas de modelado**: dominio completo, dominio delimitado y
   dominio de la solución, con la justificación de qué entra y qué
   queda afuera.
2. **Las entidades y su papel**, en el mismo vocabulario que usan la
   interfaz y los capítulos siguientes.
3. **Las relaciones muchos-a-muchos** resueltas con entidades
   intermedias explícitas.
4. **Las reglas de negocio como invariantes**: estructurales,
   virtualidad, sedes admisibles, recursado, materias anuales,
   coherencia teoría-laboratorio y políticas institucionales; varias
   reaparecen como restricciones del programa lineal en el
   capítulo 8.

El capítulo siguiente traduce este modelo a un modelo de datos
concreto.
