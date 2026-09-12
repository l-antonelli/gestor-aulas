# Capítulo 8. El problema de asignación como programa lineal entero

Este es el capítulo técnico central del informe. Los cuatro
capítulos anteriores prepararon el terreno: el capítulo 4 dejó
formalizada la definición del problema como un problema de
asignación de recursos bajo restricciones; el capítulo 5 fijó las
entidades y reglas del dominio; el capítulo 6 las materializó en
un esquema de datos; el capítulo 7 explicó cómo se organiza el
código. Ahora corresponde entrar en el corazón del sistema y
mostrar cómo se resuelve efectivamente el problema.

La estrategia expositiva del capítulo sigue el patrón *cuerpo
resumido con anexo exhaustivo* fijado en la estructura del informe
(§2 de `estructura.md`): en el cuerpo se presenta el modelo
completo con la profundidad suficiente para que la línea
argumental cierre por sí misma. Los detalles exhaustivos, las
demostraciones, las alternativas de formulación descartadas y los
análisis finos de complejidad se remiten al **Anexo E, Desarrollo
formal del programa lineal**.

## 8.1 De la operatoria al modelo

El problema de asignación de aulas quedó definido en el capítulo 4
en dos formas complementarias: en su forma coloquial (la
Secretaría Técnica tiene que decidir, para cada clase, en qué aula
se dicta) y en su forma formal (un problema de asignación de
recursos bajo restricciones, con costo ajustable). Este capítulo
da el paso siguiente: **modelar ese problema como un programa
lineal entero** que un resolutor pueda resolver de manera
sistemática.

### 8.1.1 Por qué programación lineal entera

En §2.3 introdujimos la programación lineal entera como
herramienta canónica de la investigación operativa para modelizar
problemas de asignación combinatoria con restricciones
estructuradas. Ese instrumental encaja con nuestro problema por
tres razones que conviene explicitar antes de meternos en la
formulación:

- **Las decisiones son binarias.** Un horario semanal se asigna a
  un aula (variable 1) o no se asigna (variable 0). No hay
  fracciones ni matices. La variable binaria es la representación
  natural.
- **Las restricciones son lineales.** Todas las reglas del
  capítulo 5 se pueden expresar como sumas y desigualdades entre
  variables binarias, sin recurrir a funciones no lineales.
- **El objetivo es cuantificable y lineal.** El costo asociado a
  una asignación (sobre-ocupación, sub-ocupación, incumplimiento
  de la preferencia de sede) se cuantifica horario por horario y
  se agrega linealmente.

Estos tres puntos son los que permiten instanciar el problema
como un programa lineal entero, delegarlo al resolutor y recibir
o bien la solución óptima o bien un certificado de infactibilidad.

### 8.1.2 Qué decide el programa lineal y qué queda fuera

El programa lineal decide, simultáneamente, tres cosas:

1. **El aula asignada a cada horario semanal presencial.** Es la
   decisión central: para cada horario `h` que se dicta
   presencialmente en el ciclo, elegir un aula `a` en la que se
   dicta.
2. **El tipo de cada horario semanal cuando el cronograma no lo
   fijó.** Algunos horarios llegan al asignador sin `tipo_clase`
   definido (el operador dejó abierta la decisión "teórica o
   laboratorio"). El programa lineal decide.
3. **La redistribución opcional de coeficientes de asignación entre
   comisiones de un mismo dictado.** Es un mecanismo opcional (por
   defecto desactivado) que permite al resolutor proponer una
   redistribución de la matrícula esperada entre las comisiones
   de una materia si eso mejora la utilización de las aulas.

Todo lo demás queda **fuera** del programa lineal. No decide qué
comisiones se abren, no decide los horarios semanales de las
clases (eso lo trae el cronograma), no maneja excepciones puntuales
por fecha, no considera indisponibilidades transitorias de aulas y
no incorpora preferencias personales de docentes. Estos límites
son intencionales: mantener el modelo acotado permite resolverlo
con garantías y en tiempos razonables.

### 8.1.3 De vuelta al planteo del capítulo 4

En §4.2 dijimos que un problema de asignación de recursos bajo
restricciones tiene cuatro ingredientes: recursos, demanda,
restricciones y criterio de optimalidad. En términos del programa
lineal:

- **Recursos**: las aulas del catálogo, con sus tipos y
  capacidades.
- **Demanda**: los horarios presenciales del plan, con sus
  materias, comisiones, inscriptos esperados y tipos declarados.
- **Restricciones**: las reglas del capítulo 5 traducidas a
  desigualdades lineales sobre las variables binarias.
- **Criterio**: la función objetivo que combina sobre-ocupación,
  sub-ocupación y desvío de la sede preferida, con pesos
  configurables.

La formulación matemática que sigue codifica exactamente estos
cuatro ingredientes.

## 8.2 Formulación matemática resumida

Presentamos el programa lineal en su forma canónica: conjuntos,
parámetros, variables, función objetivo, restricciones. La
notación busca cercanía con la del capítulo 5 (nombres del
dominio) y con la formulación estándar de investigación
operativa. Las derivaciones completas y las decisiones puntuales
de codificación se remiten al Anexo E.

### 8.2.1 Conjuntos

- `H`: horarios del plan que participan del modelo. Se subdivide
  en `H` propiamente dicho (horarios presenciales) y `H_∅`
  (horarios virtuales que participan del balance teoría-lab pero
  no ocupan aula).
- `A`: aulas del catálogo, con sus subconjuntos `A_teo` (aulas
  teóricas y anfiteatros) y `A_lab(m)` (laboratorios compatibles
  con la materia `m`).
- `C`: comisiones activas del plan; para cada comisión `c`, `H(c)`
  son sus horarios.
- `M`: materias que aparecen en el plan.
- `S`: sedes; para cada aula `a`, `sede(a) ∈ S` es la sede donde
  vive el aula.
- `G`: grupos de materias del catálogo; para cada materia `m`,
  `grupo(m) ∈ G` es el grupo al que pertenece (partición
  estricta).
- `Sim`: grupos maximales de simultaneidad, subconjuntos de
  horarios que se dictan al mismo tiempo del mismo día. Cada
  grupo `S ∈ Sim` es candidato a compartir aula.
- `P_R13`: pares de horarios contiguos con gap menor al margen
  configurado. Se detectan dos ejes: pares de la misma comisión
  (traslado del docente) y pares de materias distintas del mismo
  grupo curricular `(carrera, año, cuatrimestre)` (traslado del
  alumno).

### 8.2.2 Parámetros

- `dur(h)`: duración en horas del horario `h`.
- `cap(a)`: capacidad del aula `a`.
- `tipo(h)`: tipo declarado del horario, o el símbolo `⊥` si
  el cronograma dejó la decisión al modelo.
- `tipo(a)`: tipo del aula.
- `insc(h)`: inscriptos esperados en el horario, calculados por
  el servicio de pronósticos.
- `hteo(m)`, `hlab(m)`: horas de teoría y laboratorio declaradas
  por la materia.
- `S_D(g)`, `S_B(g)`: set duro de sedes y lista blanda ordenada
  de sedes del grupo `g`.
- `modo(g) ∈ {DURO, BLANDO}`: modo con el que corre el grupo `g`
  en la corrida actual (configurable por el operador).
- `sede_pref(h)`: sede preferida del horario `h`, definida sólo
  si su grupo corre en modo BLANDO.
- `pin(h)`: aula fijada manualmente por el operador para el
  horario `h`, si existe.
- Pesos y tolerancias del objetivo: `λ_over`, `λ_under`,
  `λ_sede_pref`, `tol_over`, `tol_under`. Todos configurables
  desde la interfaz.

### 8.2.3 Variables de decisión

- `x[h, a] ∈ {0, 1}`: vale 1 si el horario `h` se asigna al aula
  `a`. Se instancian sólo pares compatibles (aulas cuyo tipo
  puede recibir al horario). Los horarios en `H_∅` no tienen
  variables `x`.
- `t[h] ∈ {0, 1}`: vale 1 si el horario `h` (que tenía
  `tipo(h) = ⊥`) se resuelve como laboratorio, 0 si se resuelve
  como teoría. Sólo se instancia cuando el tipo del horario
  estaba indefinido.
- `y[c, s] ∈ {0, 1}`: vale 1 si la comisión `c` cae en la sede
  `s`. Sólo se instancia cuando el operador activa el toggle
  "forzar misma sede por comisión" (restricción R14).
- `over[h], under[h] ≥ 0`: sobre-ocupación y sub-ocupación
  linealizadas del horario `h`.
- `α[k] ∈ [0, 1]`: coeficiente redistribuido de la comisión `k`
  dentro de su dictado. Sólo se instancia cuando el operador
  activa el toggle de redistribución.

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

donde `H_BLANDO` son los horarios cuyo grupo corre en modo BLANDO
con sede preferida definida.

Los pesos por defecto son `λ_over = 10`, `λ_under = 1` y
`λ_sede_pref = 5`. La asimetría `λ_over = 10 · λ_under` codifica
que la sobre-ocupación (los alumnos no entran al aula) es un
problema físico más grave que la sub-utilización (aula grande
desaprovechada), que es un problema económico.

### 8.2.5 Restricciones

El modelo tiene once restricciones canónicas. Cada una tiene
motivación en las reglas del capítulo 5. Las presentamos con su
sigla estándar (R*n*), en el orden en que se van agregando al
modelo. Las derivaciones formales y las alternativas de
formulación descartadas están en el anexo E.

**R1. Asignación única.** Cada horario presencial se asigna a
exactamente un aula.

$$\sum_{a \in A} x[h, a] = 1 \qquad \forall h \in H \setminus H_\emptyset$$

**R3. Compatibilidad tipo aula - tipo clase.** Sólo se instancian
las variables `x[h, a]` para pares compatibles: teóricas van a
aulas teóricas o anfiteatros; laboratorios van a laboratorios
compatibles con la materia. Los pares incompatibles quedan
prohibidos por construcción del modelo.

**R4. No doble asignación.** Dos horarios que se solapan en el
tiempo no comparten aula. Se formula por **grupos maximales de
simultaneidad** en vez de por pares de horarios: para cada grupo
`S ∈ Sim` y cada aula `a`,

$$\sum_{h \in S} x[h, a] \le 1$$

La motivación matemática de esta formulación (menos restricciones
generadas y relajación lineal más fuerte) está en §2.4.5 y en el
anexo E.

**R5. Partición teoría-laboratorio.** Para cada comisión con
horas de teoría y de laboratorio declaradas, la suma de duraciones
de horarios de cada tipo debe cerrar exactamente con las horas
declaradas por la materia. Los horarios virtuales cuentan a los
efectos del balance sin ocupar aula.

**R6. Consistencia tipo-pool para horarios indefinidos.** Si el
tipo del horario no vino fijado y la variable `t[h]` decide
"teoría", el aula asignada debe ser teórica; si decide
"laboratorio", debe ser un laboratorio compatible con la materia.
El vínculo entre `t[h]` y el pool de aulas se codifica con
restricciones lineales sobre las sumas de variables `x`.

**R7. Definición lineal de sobre y sub-ocupación.** Las
variables `over[h]` y `under[h]` se definen como el exceso o
faltante del aula asignada frente a los inscriptos esperados,
con tolerancias configurables:

$$
\text{over}[h] \ge \text{insc}(h) - (1 + \text{tol\_over}) \sum_{a} \text{cap}(a) \cdot x[h, a]
$$

y análogamente para `under[h]`. Como el objetivo minimiza ambas
variables, en el óptimo toman exactamente el valor del exceso o
faltante.

**R9. Redistribución opcional de coeficientes.** Cuando el toggle
`α` está activo, los inscriptos esperados dejan de ser constantes
y pasan a ser el producto de un total por dictado por el
coeficiente redistribuido `α[k]`. Las restricciones aseguran que
los coeficientes de cada dictado sumen 1.

**R10. Sedes admisibles por grupo de materias (modo duro).**
Cuando el grupo de la materia corre en modo DURO, sólo se admiten
aulas cuya sede pertenezca al set duro del grupo, salvo la
excepción de laboratorio compatible: un aula listada en la
compatibilidad materia-laboratorio se admite aunque su sede no
esté en el set. Formalmente:

$$x[h, a] = 0 \quad \text{si} \quad \text{sede}(a) \notin S_D(\text{grupo}(m(h)))$$

siempre que el grupo corra en modo DURO con set no vacío y `a`
no sea un laboratorio compatible con la materia de `h`.

**R11. Pins manuales.** Cuando el operador fija manualmente el
aula de un horario y activa el toggle "respetar ediciones
manuales", la asignación se codifica como una restricción rígida:
`x[h, pin(h)] = 1`.

**R12. Preferencia blanda de sede.** Cuando el grupo corre en modo
BLANDO, todas las sedes son admisibles (R10 no filtra), pero cada
horario que cae en una sede distinta a la preferida suma
`λ_sede_pref` al objetivo (ver §8.2.4).

**R13. Continuidad de sede en pares en riesgo.** Para cada par
`(h₁, h₂) ∈ P_R13` (con gap menor al margen configurado) y cada
par de sedes distintas `(s₁, s₂)`, se impone

$$
\sum_{a \in A: \text{sede}(a) = s_1} x[h_1, a] +
\sum_{a \in A: \text{sede}(a) = s_2} x[h_2, a] \le 1
$$

Combinado con R1, la restricción equivale a "si `h₁` cae en `s₁`,
entonces `h₂` no puede caer en `s₂`". Se aplica tanto al eje
docente (misma comisión) como al eje alumno (materias distintas
del mismo grupo curricular).

**R14. Forzar misma sede por comisión (opcional).** Cuando el
toggle correspondiente está activo, se introducen las variables
`y[c, s]` con restricciones que aseguran que todas las asignaciones
de horarios de la misma comisión caigan en la misma sede.

Las once restricciones anteriores son el núcleo del modelo. El
anexo E documenta la formulación completa restricción por
restricción, con las decisiones puntuales de codificación
(cuándo se filtra pre-modelo versus cuándo se agrega como
restricción explícita, cómo se manejan los casos degenerados,
etc.).

## 8.3 Herramientas conceptuales para el diagnóstico

Los conceptos matemáticos que el capítulo 2 introdujo como piezas
teóricas encuentran su aplicación concreta al momento de
diagnosticar el modelo. Se aplican en tres momentos: antes del
resolutor, dentro del resolutor y después de él.

### 8.3.1 Principio del palomar (pigeonhole)

El principio del palomar es la afirmación elemental de que si se
distribuyen `n + 1` objetos en `n` cajas, alguna caja recibe al
menos dos objetos (§2.4.2). En el asignador se aplica como cota
inferior de infactibilidad: si en un instante de la semana hay
`k` horarios simultáneos y sólo `k − 1` aulas compatibles con la
unión de sus tipos, el problema es infactible. No hace falta
correr el resolutor para saberlo.

Este chequeo se implementa como parte del **diagnóstico estructural
pre-solve** (§8.4). Se aplica primero de manera global (todos los
horarios simultáneos contra todas las aulas compatibles) y luego
en refinamientos por tipo (teóricas contra teóricas, laboratorios
contra laboratorios compatibles con las materias involucradas).

### 8.3.2 Teorema de Hall y apareamiento bipartito

Cuando el principio del palomar no alcanza pero igualmente hay
infactibilidad, la herramienta natural es el teorema de Hall
(§2.4.3). Se construye un grafo bipartito con horarios de un lado
y aulas del otro, con una arista por cada par compatible, y se
verifica si existe apareamiento perfecto que asigne un aula
distinta a cada horario. La existencia se caracteriza con la
condición de Hall: para todo subconjunto de horarios, sus aulas
vecinas alcanzan en cantidad.

Cuando la condición falla, el sistema reporta el **testigo Hall**:
el subconjunto mínimo de horarios y su conjunto de aulas vecinas
más chicas. La lectura del testigo es directa: "estas materias
compiten por estas aulas y no alcanzan". El chequeo se aplica en
dos escalas: por instante de simultaneidad y por celda del mapa de
saturación por sede.

### 8.3.3 Grupos de simultaneidad

La restricción R4 se podría formular por pares de horarios que se
solapan; pero la formulación por **grupos maximales de
simultaneidad** es equivalente y mejor. Un grupo maximal es un
subconjunto de horarios activos en un mismo instante que no puede
agrandarse sin dejar de estar todo simultáneo.

La formulación por grupos genera menos restricciones (una por
grupo maximal por aula en lugar de una por par) y su relajación
lineal es más ajustada, lo que se traduce en menos nodos
explorados durante la ramificación y acotación (§2.3.3). El
anexo E documenta la comparación cuantitativa entre ambas
formulaciones sobre casos de prueba.

## 8.4 Chequeo estructural pre-solve

Antes de invocar al resolutor, el sistema corre un **chequeo
estructural pre-solve** que detecta situaciones garantizadas de
infactibilidad sin necesidad de encender el motor. Si el chequeo
detecta al menos un bloqueo, la corrida aborta con status
`infeasible_estructural` y reporta el detalle; no se gasta tiempo
del resolutor en un problema que ya sabemos que no tiene solución.

Las familias de bloqueo que el chequeo cubre son:

1. **R1. Horarios sin aula compatible.** Un horario sin ninguna
   aula que pueda recibirlo por tipo o por compatibilidad de
   laboratorio o por sede admisible.
2. **R3+R4. Saturación por tipo dentro de una franja.**
   Refinamiento del principio del palomar por pool de aulas: no
   basta con que la unión de aulas alcance; deben alcanzar por
   tipo requerido.
3. **R5. Partición teoría-laboratorio infactible.** Cuando las
   duraciones de los horarios de una comisión no cierran con las
   horas declaradas por la materia.
4. **R11. Pin manual apunta a un aula ya no compatible.** Cuando
   el aula fijada manualmente dejó de ser válida (cambió de tipo,
   la sede quedó fuera del set del grupo, etcétera).
5. **R13. Par intersede sin sede común factible.** Cuando dos
   horarios contiguos con gap menor al margen no tienen ninguna
   sede común admisible.
6. **R13-camino. Camino de cursada intersede infactible.** Cuando
   no existe combinación de comisiones viable para algún grupo
   curricular. Es la versión curricular de R13: refina la regla
   asegurando que un alumno concreto pueda cursar sin traslados
   imposibles.
7. **Pigeonhole por celda.** Aplicación del principio del palomar
   sobre celdas del mapa de saturación por sede.
8. **Hall por celda.** Aplicación del teorema de Hall sobre celdas
   del mapa de saturación con oferta de laboratorios compatibles.

Cada bloqueo detectado se acompaña de un identificador de regla,
severidad, título, descripción y lista de entidades involucradas.
La interfaz los renderiza con acciones sugeridas para resolver el
problema. Documentamos con nombre propio la razón por la que hacer
este chequeo antes del solve mejora significativamente la
experiencia operativa: hasta que se sumó, correr el resolutor con
un plan estructuralmente roto podía consumir varios minutos de
tiempo de CBC antes de reportar infactibilidad sin ninguna pista
concreta.

## 8.5 Construcción dinámica del programa lineal

El programa lineal **no está hardcodeado**. Cada corrida arma el
modelo desde cero a partir del estado actual de la base de datos
y de la configuración que eligió el operador. Los pasos:

1. **Cargar los inputs**. Se leen las tablas involucradas
   (horarios, aulas, comisiones, laboratorios compatibles, grupos
   de materias, forecast) y se los normaliza en estructuras
   internas. Se resuelve la virtualidad efectiva de cada horario
   con la regla jerárquica del capítulo 5.
2. **Filtrar horarios virtuales**. Los horarios que resultan
   virtuales se marcan como pertenecientes a `H_∅`: participan
   del balance R5 pero no ocupan aula.
3. **Computar la matriz de compatibilidad**. Se calcula, para
   cada par `(h, a)`, si el aula es compatible por tipo y por
   sede admisible (aplicando el modo del grupo). Los pares
   incompatibles no generan variables `x` (implementa R3 y R10
   pre-modelo).
4. **Computar los grupos maximales de simultaneidad**. Se
   analiza la grilla semanal con un algoritmo de barrido de
   eventos para producir los subconjuntos `Sim`.
5. **Computar los pares intersede en riesgo**. Se detectan los
   pares del eje docente y del eje alumno.
6. **Instanciar el modelo**. Se declaran variables, se agregan
   restricciones R1 a R14 (las que apliquen según la
   configuración de la corrida), se define la función objetivo.
7. **Resolver con CBC**. El resolutor recibe el modelo, aplica
   ramificación y acotación (§2.3.3) y devuelve la solución
   óptima o un certificado de infactibilidad, o un timeout si el
   tiempo máximo configurado se agota.

Cada uno de estos pasos vive en el servicio
`asignacion_aulas_service`. El anexo E documenta cada función y
sus contratos con el resto del sistema.

## 8.6 Aplicación de la solución y persistencia

Una vez que el resolutor devuelve una solución óptima, el sistema
la aplica al patrón semanal:

- Cada `HorarioDB` recibe el aula asignada por el modelo. Si el
  horario tenía tipo indefinido y el modelo resolvió `t[h]`, se
  persiste también el tipo.
- Los horarios virtuales que no tomaron aula pero arrastraban un
  `aula_id` de una corrida anterior (por ejemplo, porque en la
  corrida previa eran presenciales) se sanean: se les libera el
  `aula_id` para mantener la invariante "horario virtual sin
  aula".
- Los pins manuales que el toggle preserva quedan intactos.

Todo el snapshot de la corrida se persiste como una fila
`LPRunDB` con:

- Configuración completa aplicada (pesos, tolerancias, modos por
  grupo, toggles, timeout).
- Estado final: `optimal`, `infeasible_estructural`, `infeasible`,
  `timeout`, `error`.
- Métricas agregadas: cantidad de horarios asignados, cantidad
  reasignados respecto de la corrida anterior, sobre-ocupaciones,
  sub-utilizaciones, tiempo del resolutor, valor de la función
  objetivo.
- Detalle serializado con la asignación por horario, el
  diagnóstico estructural, el veredicto humano-legible y (cuando
  aplica) el diagnóstico por relajación selectiva que se describe
  a continuación.

## 8.7 Diagnóstico por relajación selectiva

Cuando el resolutor devuelve `infeasible` y el chequeo estructural
pre-solve no había detectado bloqueos, el sistema dispara un
**diagnóstico por relajación selectiva** para identificar la
causa. La técnica es una aproximación práctica al concepto de
*subsistema irreducible de infactibilidad* (IIS, del inglés
*Irreducible Infeasible Subsystem*), que en teoría es el
subconjunto mínimo de restricciones cuya interacción produce la
infactibilidad. El anexo E documenta la técnica en detalle; en el
cuerpo del informe alcanza con la intuición operativa:

1. **Relajación individual.** Se prueba, una a la vez, saltar cada
   restricción candidata (R4, R5, R6, R10, R13, R14) y volver a
   correr el modelo. La restricción que rescata la factibilidad
   es una candidata a culpable.
2. **Filtrado de falsos positivos.** Algunas relajaciones
   funcionan por efecto colateral (dar libertad extra al
   resolutor) sin ser la causa real. El sistema aplica filtros
   heurísticos para descartar culpables espurios: por ejemplo,
   R5 sólo cuenta como causa real si al relajarla efectivamente
   aparecen materias con horas declaradas desalineadas.
3. **Priorización de la causa principal.** Cuando quedan varios
   culpables reales, se elige el que corresponde a la acción más
   directa que puede tomar el operador: primero las restricciones
   de sede (R10, R14, R13), después las estructurales (R4, R5,
   R6).
4. **Refinamiento cuando la causa es R10.** El sistema prueba
   pasar cada grupo DURO a BLANDO por separado, para poder
   recomendar al operador qué grupo específico relajar en vez
   del genérico "hay un problema de sede".
5. **Análisis de combinaciones.** Cuando ninguna relajación
   individual rescata al modelo, la infactibilidad es
   combinada. El sistema prueba pares de relajaciones (por
   ejemplo, un grupo DURO a BLANDO más desactivar R14) y reporta
   las combinaciones que funcionan.

El resultado del diagnóstico se serializa en el snapshot de la
corrida y la interfaz lo renderiza como recomendación accionable:
"la causa probable es tal; para resolverla, hacer tal cosa". Esta
capacidad de dar diagnósticos accionables es la que convierte al
sistema, de una herramienta de optimización opaca, en un asistente
operativo con el que el operador puede iterar.

## 8.8 Veredicto y transparencia

Cada corrida del asignador termina con un **veredicto
estructurado** que se persiste en el snapshot de la corrida. El
veredicto tiene siempre los mismos campos, independientemente del
resultado:

- `status`: `optimal`, `infeasible_estructural`, `infeasible`,
  `timeout` o `error`.
- `resumen`: una descripción humana del resultado en una o dos
  oraciones.
- `causa_infactibilidad`: cuando aplica, la razón identificada
  por el diagnóstico.
- `bloqueos_diagnosticados`: la lista de bloqueos estructurales
  detectados, con sus reglas asociadas.
- `horarios_sin_asignar`: los horarios que quedaron sin aula
  (en general vacío en corridas óptimas).
- `restricciones_activas`: el dump completo de la configuración
  usada en la corrida (todos los pesos, tolerancias, modos y
  toggles).

La interfaz muestra el veredicto siempre, en la cabecera del panel
de resultado, con expanders opcionales para ver el detalle. La
persistencia completa de la configuración permite reproducir
cualquier corrida vieja con exactitud y comparar dos corridas con
configuraciones distintas para entender qué cambió.

## 8.9 Cierre del capítulo

Este capítulo dejó formalizado el corazón algorítmico del sistema.
Los puntos que se retoman después:

1. **El problema de asignación de aulas se modela como un
   programa lineal entero** con variables binarias `x[h, a]` para
   la asignación, variables auxiliares `t[h]`, `y[c, s]` y `α[k]`
   para decisiones internas, y variables continuas `over[h]` y
   `under[h]` para el objetivo. La formulación es equivalente al
   problema del capítulo 4 y compatible con la operatoria del
   capítulo 3.
2. **Las once restricciones canónicas (R1-R14)** codifican las
   reglas de negocio del capítulo 5: asignación única,
   compatibilidad, no doble asignación, partición
   teoría-laboratorio, sedes admisibles, pins, preferencia
   blanda, continuidad intersede (docente y alumno), misma sede
   por comisión opcional. Cada regla del dominio tiene su
   traducción explícita.
3. **El chequeo estructural pre-solve** (§8.4) evita gastar tiempo
   del resolutor en problemas garantizados de infactibilidad y
   aplica las herramientas conceptuales de §2.4 (palomar, Hall,
   grupos de simultaneidad).
4. **El diagnóstico por relajación selectiva** (§8.7) convierte
   una respuesta "infactible" del resolutor en una recomendación
   accionable: qué relajación individual o combinada rescata al
   modelo, con priorización por accionabilidad.
5. **El veredicto estructurado** (§8.8) garantiza transparencia
   completa: toda la información de la corrida se persiste y se
   puede consultar, reproducir y comparar.

Con el modelo formalizado y las herramientas de diagnóstico
disponibles, el capítulo siguiente cubre el conjunto de
validaciones que envuelven al asignador para garantizar que los
datos que llegan al modelo cumplen los invariantes que hacen
falta para que las restricciones tengan sentido.
