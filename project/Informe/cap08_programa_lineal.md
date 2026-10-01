# Capítulo 8. El problema de asignación como programa lineal entero

En los capítulos anteriores definimos el problema como una
asignación de recursos bajo restricciones (capítulo 4), fijamos
las entidades y reglas del dominio (capítulo 5) y mostramos cómo
se organizan los datos y el sistema (capítulos 6 y 7). En este
capítulo presentamos cómo se resuelve efectivamente el problema:
lo modelamos como un programa lineal entero, explicamos cómo se
diagnostica cuando no tiene solución y cómo se le comunica el
resultado al usuario. En el cuerpo damos el modelo con la
profundidad necesaria para seguir el argumento; las derivaciones
completas, las formulaciones alternativas descartadas y los
análisis de complejidad están en el **Anexo B, Desarrollo formal
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
   Cuando el usuario no definió si un horario es de teoría o de
   laboratorio, lo resuelve el modelo.
3. **Una redistribución de la matrícula esperada entre las
   comisiones de un mismo dictado**, si el usuario la habilita y
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
- `P_R11`: pares de horarios consecutivos de materias distintas
  de un mismo año y cuatrimestre de una carrera, separados por
  menos tiempo que el margen fijado.

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
  sedes al grupo `g`, elegido por el usuario.
- `sede_pref(h)`: sede preferida del horario `h`, definida sólo
  si su grupo está en modo BLANDO.
- `pin(h)`: aula fijada manualmente por el usuario para `h`, si
  la hay.
- Pesos y tolerancias del objetivo: `λ_sobre`, `λ_sub`,
  `λ_sede_pref`, `tol_sobre`, `tol_sub`, ajustables por el
  usuario.

### 8.2.3 Variables de decisión

- `x[h, a] ∈ {0, 1}`: vale 1 si el horario `h` se asigna al aula
  `a`. Sólo existen para pares compatibles; los horarios de `H_∅`
  no tienen variables `x`.
- `t[h] ∈ {0, 1}`: para los horarios con `tipo(h) = ⊥`, vale 1 si
  se resuelven como laboratorio y 0 si se resuelven como teoría.
- `y[c, s] ∈ {0, 1}`: vale 1 si la comisión `c` se dicta en la
  sede `s`. Sólo se usa cuando se exige una única sede por
  comisión (R12).
- `sobre[h], sub[h] ≥ 0`: sobreocupación y subocupación del
  horario `h`.
- `α[k] ∈ [0, 1]`: proporción de la matrícula del dictado que
  corresponde a la comisión `k`. Sólo se usa cuando el usuario
  habilita la redistribución (R7).

### 8.2.4 Función objetivo

Minimizar

$$
\lambda_{\text{sobre}} \sum_{h} \text{sobre}[h]
\;+\;
\lambda_{\text{sub}} \sum_{h} \text{sub}[h]
\;+\;
\lambda_{\text{sede\_pref}} \sum_{h \in H_{\text{BLANDO}}}
\sum_{\substack{a \in A \\ \text{sede}(a) \neq \text{sede\_pref}(h)}}
x[h, a]
$$

donde `H_BLANDO` son los horarios cuyo grupo está en modo BLANDO
y tienen sede preferida.

Los pesos por defecto son `λ_sobre = 10`, `λ_sub = 1` y
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

**R2. Compatibilidad entre tipo de aula y tipo de clase.** Las
clases teóricas van a aulas teóricas o anfiteatros; los
laboratorios, a laboratorios compatibles con la materia. Se
cumple por construcción: las variables `x[h, a]` de pares
incompatibles directamente no existen.

**R3. Sin superposición en un aula.** Dos horarios que se
superponen en el tiempo no comparten aula. En lugar de escribirla
par por par, se formula por grupos maximales de simultaneidad:
para cada grupo `S ∈ Sim` y cada aula `a`,

$$\sum_{h \in S} x[h, a] \le 1$$

Las ventajas de esta formulación se explican en §8.3.3.

**R4. Reparto entre teoría y laboratorio.** En cada comisión con
horas de teoría y de laboratorio, la suma de las duraciones de
sus horarios de cada tipo debe coincidir con las horas de la
materia. Los horarios virtuales cuentan para este balance aunque
no ocupen aula.

**R5. Coherencia de tipo en horarios abiertos.** Si `t[h]` decide
que un horario sin tipo es de teoría, el aula asignada debe ser
teórica; si decide laboratorio, debe ser un laboratorio
compatible con la materia. El vínculo se expresa con
desigualdades lineales entre `t[h]` y las variables `x`.

**R6. Sobreocupación y subocupación.** Las variables `sobre[h]` y
`sub[h]` miden el exceso o el faltante de capacidad del aula
asignada frente a los inscriptos esperados, con tolerancias:

$$
\text{sobre}[h] \ge \text{insc}(h) - (1 + \text{tol\_sobre}) \sum_{a} \text{cap}(a) \cdot x[h, a]
$$

y análogamente para `sub[h]`. Como el objetivo las minimiza, en
el óptimo toman exactamente el valor del exceso o del faltante.

**R7. Redistribución de la matrícula.** Cuando está habilitada,
los inscriptos esperados de cada comisión dejan de ser un dato y
pasan a ser el total del dictado multiplicado por `α[k]`; las
proporciones de cada dictado deben sumar 1.

**R8. Sedes admitidas por grupo de materias (modo duro).** Si el
grupo de la materia está en modo DURO, sólo se admiten aulas de
las sedes de su conjunto obligatorio:

$$x[h, a] = 0 \quad \text{si} \quad \text{sede}(a) \notin S_D(\text{grupo}(m(h)))$$

siempre que el conjunto no esté vacío. La excepción son los
laboratorios declarados compatibles con la materia, que se
admiten aunque estén en otra sede.

**R9. Aulas fijadas manualmente.** Si el usuario fijó el aula
de un horario y pidió respetar esas decisiones, se impone
`x[h, pin(h)] = 1`.

**R10. Preferencia de sede (modo blando).** Si el grupo está en
modo BLANDO, todas las sedes son admisibles (R8 no se aplica),
pero cada horario asignado fuera de la sede preferida suma
`λ_sede_pref` al objetivo (§8.2.4).

**R11. Continuidad de sede entre horarios consecutivos.** Para
cada par `(h₁, h₂) ∈ P_R11` y cada par de sedes distintas
`(s₁, s₂)`,

$$
\sum_{a \in A: \text{sede}(a) = s_1} x[h_1, a] +
\sum_{a \in A: \text{sede}(a) = s_2} x[h_2, a] \le 1
$$

Junto con R1, equivale a "si `h₁` se dicta en `s₁`, `h₂` no
puede dictarse en `s₂`": el alumno que sale de una clase llega a
tiempo a la siguiente.

Aparte de este caso, el mismo margen se aplica a un caso puntual:
dos horarios consecutivos de una misma comisión en el mismo día,
algo que rara vez ocurre. Si se exige R12, ese caso ya queda
cubierto.

**R12. Misma sede por comisión.** Es la regla que mira al
docente. Cuando el usuario la exige, las variables `y[c, s]`
obligan a que todos los horarios de una comisión se dicten en la
misma sede.

### 8.2.6 Un ejemplo pequeño

Para ver cómo queda escrito el programa, tomamos un caso mínimo:
cuatro horarios del lunes por la mañana y tres aulas de una misma
sede. Las Tablas @tab:ej-horarios y @tab:ej-aulas resumen los datos, y la
Figura @fig:ej-lp los muestra sobre la línea de tiempo.

<!-- tabla: Horarios del ejemplo {#tab:ej-horarios} -->
| Horario | Materia | Tipo | Lunes | Inscriptos esperados |
| :---: | --- | --- | :---: | :---: |
| `h₁` | Análisis Matemático I | teoría | 08:00 a 10:00 | 70 |
| `h₂` | Física I | teoría | 09:00 a 11:00 | 35 |
| `h₃` | Física I | laboratorio | 08:00 a 10:00 | 25 |
| `h₄` | Álgebra y Geometría | teoría | 10:00 a 12:00 | 45 |

<!-- tabla: Aulas del ejemplo {#tab:ej-aulas} -->
| Aula | Tipo | Capacidad |
| :---: | --- | :---: |
| `a₁` | teórica | 40 |
| `a₂` | teórica | 80 |
| `a₃` | laboratorio de Física | 30 |

![Ejemplo del programa lineal: horarios, grupos de simultaneidad y asignación óptima](figuras/ejemplo_lp.png){#fig:ej-lp width=15cm}

Escribimos `x_ij` en lugar de `x[h_i, a_j]`. Como las clases de teoría
sólo admiten aulas teóricas y el laboratorio sólo admite `a₃`, la
compatibilidad (R2) deja siete variables de las doce posibles:
`x₁₁, x₁₂, x₂₁, x₂₂, x₃₃, x₄₁` y `x₄₂`. Se usan los pesos por defecto
(`λ_sobre = 10`, `λ_sub = 1`), sin tolerancia para la sobreocupación
y con una tolerancia del 20 % para la subocupación: un aula recién
cuenta como subocupada cuando sobra más de una quinta parte de su
capacidad.

**Función objetivo.**

$$\min \; 10 \,(\text{sobre}_1 + \text{sobre}_2 + \text{sobre}_3 + \text{sobre}_4) \;+\; (\text{sub}_1 + \text{sub}_2 + \text{sub}_3 + \text{sub}_4)$$

**R1. Cada horario en exactamente un aula.**

$$x_{11} + x_{12} = 1, \qquad x_{21} + x_{22} = 1, \qquad x_{33} = 1, \qquad x_{41} + x_{42} = 1$$

**R3. Sin superposición.** Entre las 9 y las 10 se dictan a la vez
`h₁`, `h₂` y `h₃`; entre las 10 y las 11, `h₂` y `h₄` (`h₁` termina
justo cuando empieza `h₄`, por lo que no se superponen). Para cada
grupo y cada aula teórica:

$$x_{11} + x_{21} \le 1, \qquad x_{12} + x_{22} \le 1, \qquad x_{21} + x_{41} \le 1, \qquad x_{22} + x_{42} \le 1$$

En `a₃` sólo puede ir `h₃`, así que su restricción se cumple sola.

**R6. Sobreocupación y subocupación.** Para cada horario, el exceso
de inscriptos sobre la capacidad del aula asignada y la capacidad
sobrante más allá de la tolerancia, una fórmula por horario:

$$\text{sobre}_1 \ge 70 - 40\,x_{11} - 80\,x_{12}, \qquad \text{sub}_1 \ge 32\,x_{11} + 64\,x_{12} - 70$$

$$\text{sobre}_2 \ge 35 - 40\,x_{21} - 80\,x_{22}, \qquad \text{sub}_2 \ge 32\,x_{21} + 64\,x_{22} - 35$$

$$\text{sobre}_3 \ge 25 - 30\,x_{33}, \qquad \text{sub}_3 \ge 24\,x_{33} - 25$$

$$\text{sobre}_4 \ge 45 - 40\,x_{41} - 80\,x_{42}, \qquad \text{sub}_4 \ge 32\,x_{41} + 64\,x_{42} - 45$$

con todas las `x` binarias y `sobre`, `sub` no negativas. El resto
de las restricciones no interviene: los tipos de clase están
declarados (R4 y R5 se cumplen con los datos), hay una sola sede (R8,
R10, R11 y R12) y no hay aulas fijadas ni redistribución de
matrícula (R7 y R9).

**La solución.** Como `h₂` se superpone con `h₁` y con `h₄`, tiene
que ir a un aula distinta de la de ambos; `h₁` y `h₄` pueden
compartir aula porque no se superponen. Quedan entonces dos
alternativas:

- `h₂` en `a₁` y `h₁`, `h₄` en `a₂`. Nadie queda sin lugar; sólo `h₄`
  queda holgado (45 inscriptos en un aula de 80, `sub₄ = 64 − 45 =
  19`). Costo: **19**.
- `h₂` en `a₂` y `h₁`, `h₄` en `a₁`. Faltan 30 lugares para `h₁` y 5
  para `h₄`, y `h₂` queda holgado (`sub₂ = 29`). Costo:
  10 · (30 + 5) + 29 = **379**.

El resolutor elige la primera. El ejemplo muestra el criterio del
objetivo en pequeño: se acepta un aula grande a medio llenar antes
que dejar alumnos sin lugar. En un cuatrimestre real el razonamiento
es el mismo, pero con cientos de horarios y miles de variables.

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

R3 impide que dos horarios superpuestos compartan aula. Escribirla
par por par funciona, pero si veinte horarios coinciden a la misma
hora hay 190 pares, y cada uno suma una restricción por aula.

Hay una forma más simple: si en un instante hay varios horarios en
curso, alcanza con decir "de todos ellos, a lo sumo uno ocupa esta
aula". A ese conjunto de horarios en curso a la vez lo llamamos
*grupo de simultaneidad*, y es *maximal* cuando no está contenido en
otro más grande. En el ejemplo de §8.2.6, de 9 a 10 están en curso
`h₁`, `h₂` y `h₃`, y una sola desigualdad por aula,
`x₁ₐ + x₂ₐ + x₃ₐ ≤ 1`, reemplaza a las tres de los pares.

Las dos formas admiten las mismas asignaciones, pero la agrupada
genera muchas menos restricciones (cuando los horarios son intervalos
de tiempo, los grupos maximales son a lo sumo tantos como horarios,
según Golumbic [5]) y le da al resolutor una relajación más ajustada
(§2.3.3), así que tiene que ramificar menos. En programación lineal
entera se las conoce como *desigualdades de clique*, y Wolsey [12]
muestra que superan a las formuladas por pares. El Anexo B compara
ambas sobre casos de prueba.

## 8.4 Verificación estructural previa

Antes de llamar al resolutor, el sistema hace una **verificación
estructural previa** que detecta situaciones que hacen imposible
cualquier asignación. Si encuentra al menos un bloqueo, la
corrida se detiene y se informa el detalle, sin gastar tiempo en
resolver un problema que ya sabemos que no tiene solución. Las
situaciones que verifica son:

1. **R1. Horarios sin aula posible**, por tipo, por compatibilidad
   de laboratorio o por sede admitida.
2. **R2+R3. Falta de aulas de un tipo en una franja.** Versión del
   principio del palomar por tipo de aula: no basta con que
   alcancen las aulas en total; tienen que alcanzar las del tipo
   requerido.
3. **R4. Reparto imposible entre teoría y laboratorio**, cuando
   las duraciones de los horarios de una comisión no pueden
   cerrar con las horas de la materia.
4. **R9. Aula fijada que ya no es válida**, porque cambió de
   tipo o su sede quedó fuera de las admitidas para el grupo.
5. **R11. Horarios consecutivos sin sede común posible.**
6. **R11 a nivel de recorrido.** Ninguna combinación de comisiones
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

## 8.5 Construcción, resolución y aplicación

El programa lineal no es fijo: en cada corrida se arma desde cero
con los datos vigentes y las opciones que eligió el usuario. Los
horarios virtuales se separan (cuentan para R4 pero no ocupan aula),
sólo se crean variables para los pares horario-aula compatibles (con
lo que R2 y R8 se cumplen de antemano), se calculan los grupos de
simultaneidad y los pares de horarios consecutivos en riesgo de
traslado, y se plantean las restricciones que correspondan. El
resolutor devuelve la solución óptima, la constancia de
infactibilidad o el aviso de que se agotó el tiempo máximo.

La solución óptima se aplica de una sola vez al patrón semanal: cada
horario presencial queda con su aula y, si su tipo estaba abierto,
con el tipo que resolvió el modelo; las aulas fijadas que el usuario
pidió respetar no se tocan. La corrida queda registrada con su
configuración y sus indicadores, de modo que puede reproducirse y
compararse con otras.

## 8.6 Diagnóstico de la infactibilidad y veredicto

Cuando el resolutor declara el problema infactible y la verificación
previa no había encontrado bloqueos, el sistema busca la causa
relajando las restricciones candidatas (R3, R4, R5, R8, R11 y R12) de
a una por vez: si al quitar una el problema pasa a tener solución,
esa restricción es sospechosa. Entre varias causas posibles se
informa primero la que admite la acción más directa del usuario, como
flexibilizar la sede de un grupo de materias concreto; si ninguna
alcanza sola, se prueban combinaciones. La técnica aproxima el
*subsistema irreducible de infactibilidad*, el menor conjunto de
restricciones cuya combinación impide toda solución (Anexo B).

Toda corrida termina con un **veredicto** en lenguaje llano: el
estado final, la causa probable si la hay, los horarios que quedaron
sin aula y la configuración usada. Así, en lugar de un "infactible"
opaco, el usuario recibe una recomendación concreta con la que puede
iterar.

## 8.7 Cierre del capítulo

La asignación queda formulada como un programa lineal entero cuyas
restricciones R1 a R12 traducen las reglas del capítulo 5. La
verificación previa evita resolver problemas sin solución, y el
diagnóstico y el veredicto convierten cada corrida en información
útil para el usuario. El capítulo siguiente trata las validaciones
que garantizan que los datos que llegan al modelo cumplen lo que las
restricciones dan por supuesto.
