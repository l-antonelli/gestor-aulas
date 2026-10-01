# Capítulo 8. El problema de asignación como programa lineal entero

En los capítulos anteriores definimos el problema como una
asignación de recursos bajo restricciones (capítulo 4), fijamos
las entidades y reglas del dominio (capítulo 5) y mostramos cómo
se organizan los datos y el sistema (capítulos 6 y 7). En este
capítulo presentamos cómo se resuelve efectivamente el problema:
lo modelamos como un programa lineal entero, explicamos cómo se
diagnostica cuando no tiene solución y cómo se le comunica el
resultado al operador. En el cuerpo damos el modelo con la
profundidad necesaria para seguir el argumento; las derivaciones
completas, las formulaciones alternativas descartadas y los
análisis de complejidad están en el **Anexo E, Desarrollo formal
del programa lineal**.

## 8.1 De la operatoria al modelo

En el capítulo 4 el problema quedó planteado de dos maneras
complementarias: en forma coloquial (la Secretaría Técnica tiene
que decidir, para cada clase, en qué aula se dicta) y en forma
formal (una asignación de recursos bajo restricciones, con costo
ajustable). El paso siguiente es expresarlo como un **programa
lineal entero** que un *resolutor* pueda tratar de manera
sistemática.

### 8.1.1 Por qué programación lineal entera

En §2.3 presentamos la programación lineal entera como la
herramienta clásica de la investigación operativa para problemas
de asignación combinatoria con restricciones estructuradas. Encaja
con nuestro problema por tres razones:

- **Las decisiones son binarias.** Un horario semanal se asigna a
  un aula (variable 1) o no (variable 0); no hay fracciones.
- **Las restricciones son lineales.** Todas las reglas del
  capítulo 5 se expresan como sumas y desigualdades entre
  variables binarias.
- **El objetivo es lineal.** El costo de una asignación
  (sobreocupación, subocupación, alejamiento de la sede preferida)
  se mide horario por horario y se suma.

Con estas tres condiciones, el resolutor devuelve o bien la
solución óptima o bien la constancia de que no existe ninguna
solución factible.

### 8.1.2 Qué decide el programa lineal y qué queda fuera

El programa lineal decide, simultáneamente:

1. **El aula de cada horario semanal presencial.** Es la decisión
   central.
2. **El tipo de los horarios que el cronograma dejó abierto.**
   Cuando el operador no definió si un horario es de teoría o de
   laboratorio, lo resuelve el modelo.
3. **Una redistribución de la matrícula esperada entre las
   comisiones de un mismo dictado**, si el operador la habilita y
   si mejora el aprovechamiento de las aulas.

Todo lo demás queda **fuera**: el modelo no decide qué comisiones
se abren ni en qué horarios se dictan (eso lo trae el
cronograma), no trata excepciones puntuales por fecha ni
indisponibilidades transitorias de aulas y no incorpora
preferencias personales de los docentes. Estos límites son
deliberados: un modelo acotado se resuelve con garantías y en
tiempos razonables.

### 8.1.3 De vuelta al planteo del capítulo 4

En §4.2 identificamos los cuatro ingredientes de un problema de
asignación de recursos bajo restricciones. En el programa lineal
se traducen así:

- **Recursos**: las aulas, con sus tipos y capacidades.
- **Demanda**: los horarios presenciales del plan, con su
  materia, comisión, inscriptos esperados y tipo declarado.
- **Restricciones**: las reglas del capítulo 5, escritas como
  desigualdades lineales.
- **Criterio**: una función objetivo que combina sobreocupación,
  subocupación y alejamiento de la sede preferida, con pesos
  ajustables.

## 8.2 Formulación matemática resumida

Presentamos el programa lineal en su forma habitual: conjuntos,
parámetros, variables, función objetivo y restricciones. La
notación sigue los nombres del dominio del capítulo 5 y la
convención usual de la investigación operativa.

### 8.2.1 Conjuntos

- `H`: horarios del plan que participan del modelo. Se distinguen
  los presenciales y el subconjunto `H_∅` de horarios virtuales,
  que cuentan para el balance entre teoría y laboratorio pero no
  ocupan aula.
- `A`: aulas, con los subconjuntos `A_teo` (aulas teóricas y
  anfiteatros) y `A_lab(m)` (laboratorios compatibles con la
  materia `m`).
- `C`: comisiones activas del plan; `H(c)` son los horarios de la
  comisión `c`.
- `M`: materias del plan.
- `S`: sedes; `sede(a)` es la sede del aula `a`.
- `G`: grupos de materias; cada materia `m` pertenece a un único
  grupo `grupo(m)`.
- `Sim`: *grupos maximales de simultaneidad*, es decir, conjuntos
  de horarios que se dictan al mismo tiempo el mismo día (§8.3.3).
- `P_R13`: pares de horarios consecutivos separados por menos
  tiempo que el margen fijado. Se consideran dos casos: horarios
  de la misma comisión (traslado del docente) y horarios de
  materias distintas de un mismo año y cuatrimestre de una
  carrera (traslado del alumno).

### 8.2.2 Parámetros

- `dur(h)`: duración en horas del horario `h`.
- `cap(a)`: capacidad del aula `a`.
- `tipo(h)`: tipo declarado del horario, o `⊥` si el cronograma
  dejó la decisión al modelo.
- `tipo(a)`: tipo del aula.
- `insc(h)`: inscriptos esperados en el horario, según el
  pronóstico de matrícula.
- `hteo(m)`, `hlab(m)`: horas de teoría y de laboratorio de la
  materia.
- `S_D(g)`, `S_B(g)`: conjunto obligatorio de sedes y lista
  ordenada de sedes preferidas del grupo `g`.
- `modo(g) ∈ {DURO, BLANDO}`: modo en que se aplica la regla de
  sedes al grupo `g`, elegido por el operador.
- `sede_pref(h)`: sede preferida del horario `h`, definida sólo
  si su grupo está en modo BLANDO.
- `pin(h)`: aula fijada manualmente por el operador para `h`, si
  la hay.
- Pesos y tolerancias del objetivo: `λ_over`, `λ_under`,
  `λ_sede_pref`, `tol_over`, `tol_under`, ajustables por el
  operador.

### 8.2.3 Variables de decisión

- `x[h, a] ∈ {0, 1}`: vale 1 si el horario `h` se asigna al aula
  `a`. Sólo existen para pares compatibles; los horarios de `H_∅`
  no tienen variables `x`.
- `t[h] ∈ {0, 1}`: para los horarios con `tipo(h) = ⊥`, vale 1 si
  se resuelven como laboratorio y 0 si se resuelven como teoría.
- `y[c, s] ∈ {0, 1}`: vale 1 si la comisión `c` se dicta en la
  sede `s`. Sólo se usa cuando se exige una única sede por
  comisión (R14).
- `over[h], under[h] ≥ 0`: sobreocupación y subocupación del
  horario `h`.
- `α[k] ∈ [0, 1]`: proporción de la matrícula del dictado que
  corresponde a la comisión `k`. Sólo se usa cuando el operador
  habilita la redistribución (R9).

### 8.2.4 Función objetivo

Minimizar

$$
\lambda_{\text{over}} \sum_{h} \text{over}[h]
\;+\;
\lambda_{\text{under}} \sum_{h} \text{under}[h]
\;+\;
\lambda_{\text{sede\_pref}} \sum_{h \in H_{\text{BLANDO}}}
\sum_{\substack{a \in A \\ \text{sede}(a) \neq \text{sede\_pref}(h)}}
x[h, a]
$$

donde `H_BLANDO` son los horarios cuyo grupo está en modo BLANDO
y tienen sede preferida.

Los pesos por defecto son `λ_over = 10`, `λ_under = 1` y
`λ_sede_pref = 5`. La asimetría entre los dos primeros expresa
que la sobreocupación (los alumnos no entran en el aula) es un
problema físico más grave que la subocupación (un aula grande
desaprovechada), que es un problema económico.

### 8.2.5 Restricciones

Cada restricción traduce una regla del capítulo 5. Las numeramos
R*n* y las presentamos en el orden en que se incorporan al
modelo.

**R1. Asignación única.** Cada horario presencial se asigna a
exactamente un aula.

$$\sum_{a \in A} x[h, a] = 1 \qquad \forall h \in H \setminus H_\emptyset$$

**R3. Compatibilidad entre tipo de aula y tipo de clase.** Las
clases teóricas van a aulas teóricas o anfiteatros; los
laboratorios, a laboratorios compatibles con la materia. Se
cumple por construcción: las variables `x[h, a]` de pares
incompatibles directamente no existen.

**R4. Sin superposición en un aula.** Dos horarios que se
superponen en el tiempo no comparten aula. En lugar de escribirla
par por par, se formula por grupos maximales de simultaneidad:
para cada grupo `S ∈ Sim` y cada aula `a`,

$$\sum_{h \in S} x[h, a] \le 1$$

Las ventajas de esta formulación se explican en §8.3.3.

**R5. Reparto entre teoría y laboratorio.** En cada comisión con
horas de teoría y de laboratorio, la suma de las duraciones de
sus horarios de cada tipo debe coincidir con las horas de la
materia. Los horarios virtuales cuentan para este balance aunque
no ocupen aula.

**R6. Coherencia de tipo en horarios abiertos.** Si `t[h]` decide
que un horario sin tipo es de teoría, el aula asignada debe ser
teórica; si decide laboratorio, debe ser un laboratorio
compatible con la materia. El vínculo se expresa con
desigualdades lineales entre `t[h]` y las variables `x`.

**R7. Sobreocupación y subocupación.** Las variables `over[h]` y
`under[h]` miden el exceso o el faltante de capacidad del aula
asignada frente a los inscriptos esperados, con tolerancias:

$$
\text{over}[h] \ge \text{insc}(h) - (1 + \text{tol\_over}) \sum_{a} \text{cap}(a) \cdot x[h, a]
$$

y análogamente para `under[h]`. Como el objetivo las minimiza, en
el óptimo toman exactamente el valor del exceso o del faltante.

**R9. Redistribución de la matrícula.** Cuando está habilitada,
los inscriptos esperados de cada comisión dejan de ser un dato y
pasan a ser el total del dictado multiplicado por `α[k]`; las
proporciones de cada dictado deben sumar 1.

**R10. Sedes admitidas por grupo de materias (modo duro).** Si el
grupo de la materia está en modo DURO, sólo se admiten aulas de
las sedes de su conjunto obligatorio:

$$x[h, a] = 0 \quad \text{si} \quad \text{sede}(a) \notin S_D(\text{grupo}(m(h)))$$

siempre que el conjunto no esté vacío. La excepción son los
laboratorios declarados compatibles con la materia, que se
admiten aunque estén en otra sede.

**R11. Aulas fijadas manualmente.** Si el operador fijó el aula
de un horario y pidió respetar esas decisiones, se impone
`x[h, pin(h)] = 1`.

**R12. Preferencia de sede (modo blando).** Si el grupo está en
modo BLANDO, todas las sedes son admisibles (R10 no se aplica),
pero cada horario asignado fuera de la sede preferida suma
`λ_sede_pref` al objetivo (§8.2.4).

**R13. Continuidad de sede entre horarios consecutivos.** Para
cada par `(h₁, h₂) ∈ P_R13` y cada par de sedes distintas
`(s₁, s₂)`,

$$
\sum_{a \in A: \text{sede}(a) = s_1} x[h_1, a] +
\sum_{a \in A: \text{sede}(a) = s_2} x[h_2, a] \le 1
$$

Junto con R1, equivale a "si `h₁` se dicta en `s₁`, `h₂` no
puede dictarse en `s₂`". Se aplica tanto a los traslados del
docente como a los del alumno.

**R14. Misma sede por comisión.** Cuando el operador lo exige,
las variables `y[c, s]` obligan a que todos los horarios de una
comisión se dicten en la misma sede.

## 8.3 Herramientas conceptuales para el diagnóstico

Los resultados matemáticos presentados en el capítulo 2 se usan
para diagnosticar el modelo: antes de resolverlo, durante la
resolución y después de ella.

### 8.3.1 Principio del palomar

El *principio del palomar* (§2.4.2) dice que si se reparten
`n + 1` objetos en `n` cajas, alguna recibe al menos dos. En el
asignador funciona como prueba rápida de infactibilidad: si en un
mismo momento de la semana hay `k` horarios simultáneos y sólo
`k − 1` aulas compatibles, el problema no tiene solución, y no
hace falta resolverlo para saberlo. La prueba se hace primero con
todas las aulas y luego por tipo (teóricas por un lado,
laboratorios compatibles por otro), como parte de la verificación
previa (§8.4).

### 8.3.2 Teorema de Hall y apareamiento bipartito

Cuando el palomar no detecta nada pero el problema igualmente es
infactible, recurrimos al *teorema de Hall* (§2.4.3). Se arma un
grafo bipartito con los horarios de un lado, las aulas del otro y
una arista por cada par compatible. Existe una asignación que le
da un aula distinta a cada horario si y sólo si todo subconjunto
de horarios tiene, en conjunto, al menos tantas aulas vecinas
como horarios.

Cuando la condición falla, el sistema informa el subconjunto de
horarios que la viola junto con sus aulas vecinas. La lectura es
directa: "estas materias compiten por estas aulas y no alcanzan".
La verificación se hace por momento de simultaneidad y por sede.

### 8.3.3 Grupos de simultaneidad

Un grupo maximal de simultaneidad es un conjunto de horarios que
están activos en un mismo momento y que no se puede agrandar sin
incluir un horario que no se superponga con los demás. Formular
R4 por grupos, en lugar de por pares de horarios, es equivalente
pero mejor: genera menos restricciones y su relajación lineal es
más ajustada, lo que reduce el trabajo de ramificación y acotación
del resolutor (§2.3.3). El Anexo E compara ambas formulaciones
sobre casos de prueba.

## 8.4 Verificación estructural previa

Antes de llamar al resolutor, el sistema hace una **verificación
estructural previa** que detecta situaciones que hacen imposible
cualquier asignación. Si encuentra al menos un bloqueo, la
corrida se detiene y se informa el detalle, sin gastar tiempo en
resolver un problema que ya sabemos que no tiene solución. Las
situaciones que verifica son:

1. **R1. Horarios sin aula posible**, por tipo, por compatibilidad
   de laboratorio o por sede admitida.
2. **R3+R4. Falta de aulas de un tipo en una franja.** Versión del
   principio del palomar por tipo de aula: no basta con que
   alcancen las aulas en total; tienen que alcanzar las del tipo
   requerido.
3. **R5. Reparto imposible entre teoría y laboratorio**, cuando
   las duraciones de los horarios de una comisión no pueden
   cerrar con las horas de la materia.
4. **R11. Aula fijada que ya no es válida**, porque cambió de
   tipo o su sede quedó fuera de las admitidas para el grupo.
5. **R13. Horarios consecutivos sin sede común posible.**
6. **R13 a nivel de recorrido.** Ninguna combinación de comisiones
   le permite a un alumno de un año y cuatrimestre dados cursar
   sin traslados imposibles.
7. **Palomar por sede**, aplicado a cada franja y sede.
8. **Hall por sede**, sobre la oferta de laboratorios
   compatibles.

Cada bloqueo se informa con la regla involucrada, su gravedad,
una descripción y las materias, comisiones o aulas afectadas,
junto con una acción sugerida para resolverlo. Sin esta
verificación, un plan con problemas estructurales podía ocupar al
resolutor varios minutos y terminar en un "infactible" sin
ninguna pista sobre la causa.

## 8.5 Construcción dinámica del programa lineal

El programa lineal no es fijo: en cada corrida se arma desde cero
con los datos vigentes y las opciones que eligió el operador. Los
pasos son:

1. **Reunir los datos** de horarios, aulas, comisiones,
   laboratorios compatibles, grupos de materias y pronósticos de
   matrícula, y determinar qué horarios son virtuales según la
   regla jerárquica del capítulo 5.
2. **Separar los horarios virtuales** en `H_∅`: cuentan para R5
   pero no ocupan aula.
3. **Calcular la compatibilidad** de cada par horario-aula por
   tipo y por sede admitida. Los pares incompatibles no generan
   variables, con lo que R3 y R10 se cumplen de antemano.
4. **Calcular los grupos de simultaneidad** recorriendo la grilla
   semanal en orden cronológico.
5. **Detectar los pares de horarios consecutivos en riesgo** de
   traslado, del docente y del alumno.
6. **Plantear el modelo**: variables, las restricciones que
   correspondan según las opciones elegidas y la función
   objetivo.
7. **Resolver**: el resolutor aplica ramificación y acotación
   (§2.3.3) y devuelve la solución óptima, la constancia de
   infactibilidad o el aviso de que se agotó el tiempo máximo.

## 8.6 Aplicación de la solución

Cuando el resolutor encuentra la solución óptima, el sistema la
aplica al patrón semanal: cada horario presencial queda con el
aula asignada y, si su tipo estaba abierto, con el tipo que
resolvió el modelo. Los horarios virtuales quedan sin aula y las
aulas fijadas manualmente que el operador pidió respetar no se
modifican.

Cada corrida queda registrada con la configuración usada, el
resultado (óptimo, infactible o tiempo agotado), los indicadores
principales (horarios asignados y reasignados respecto de la
corrida anterior, sobreocupaciones, subocupaciones, valor del
objetivo) y, si corresponde, el diagnóstico de infactibilidad.

## 8.7 Diagnóstico por relajación selectiva

Cuando el resolutor declara el problema infactible y la
verificación previa no había encontrado bloqueos, el sistema
busca la causa con un **diagnóstico por relajación selectiva**.
La técnica aproxima el concepto de *subsistema irreducible de
infactibilidad*: el menor conjunto de restricciones cuya
combinación impide toda solución. El detalle está en el Anexo E;
en criollo, el procedimiento es el siguiente:

1. **Relajar de a una.** Se quita, de a una por vez, cada
   restricción candidata (R4, R5, R6, R10, R13, R14) y se vuelve a
   resolver. Si al quitar una el problema pasa a tener solución,
   esa restricción es sospechosa.
2. **Descartar falsos culpables.** Algunas relajaciones funcionan
   sólo porque le dan holgura al resolutor, sin ser la causa real.
   Por ejemplo, R5 sólo se considera causa si al relajarla
   aparecen materias cuyas horas no cierran.
3. **Priorizar.** Si quedan varias causas, se informa primero la
   que admite la acción más directa del operador: las de sede
   (R10, R14, R13) antes que las estructurales (R4, R5, R6).
4. **Precisar el grupo cuando la causa es R10.** Se prueba pasar
   cada grupo de modo DURO a BLANDO por separado, para recomendar
   qué grupo concreto conviene flexibilizar.
5. **Probar combinaciones.** Si ninguna relajación individual
   alcanza, la infactibilidad es combinada: se prueban pares de
   relajaciones (por ejemplo, flexibilizar un grupo y dejar de
   exigir R14) y se informan los que funcionan.

El resultado se presenta como una recomendación concreta: "la
causa probable es tal; para resolverla, conviene hacer tal cosa".
Esta capacidad es la que hace del sistema, más que una
herramienta de optimización opaca, un asistente con el que el
operador puede iterar.

## 8.8 Veredicto y transparencia

Toda corrida termina con un **veredicto** de estructura fija,
cualquiera sea el resultado: el estado final, un resumen en una o
dos oraciones, la causa de infactibilidad si la hay, los bloqueos
detectados con sus reglas, los horarios que quedaron sin aula y la
configuración completa usada (pesos, tolerancias, modos y
opciones). La interfaz muestra siempre el veredicto, con la
posibilidad de desplegar el detalle. Como la configuración queda
registrada, cualquier corrida puede reproducirse con exactitud y
dos corridas pueden compararse para entender qué cambió.

## 8.9 Cierre del capítulo

En este capítulo formalizamos el núcleo del sistema:

1. **El problema se modela como un programa lineal entero**, con
   variables binarias `x[h, a]` para la asignación, variables
   auxiliares `t[h]`, `y[c, s]` y `α[k]` para decisiones internas
   y variables continuas `over[h]` y `under[h]` para el objetivo.
2. **Las restricciones R1 a R14** traducen las reglas del
   capítulo 5: asignación única, compatibilidad, ausencia de
   superposiciones, reparto entre teoría y laboratorio, sedes
   admitidas, aulas fijadas, preferencia de sede, continuidad de
   sede para docentes y alumnos y, opcionalmente, una sede por
   comisión.
3. **La verificación estructural previa** (§8.4) evita resolver
   problemas que no tienen solución, apoyándose en el principio
   del palomar, el teorema de Hall y los grupos de simultaneidad.
4. **El diagnóstico por relajación selectiva** (§8.7) convierte un
   "infactible" en una recomendación concreta.
5. **El veredicto** (§8.8) hace transparente cada corrida y
   permite reproducirla y compararla.

El capítulo siguiente trata las validaciones que rodean al
asignador y garantizan que los datos que llegan al modelo cumplen
las condiciones que las restricciones dan por supuestas.
