# Programa Lineal de Asignación de Aulas

> **Estado**: planteo formal cerrado, implementación en curso. Esta versión documenta el modelo en su variante actual: el programa lineal asigna aulas al **patrón semanal** y las clases puntuales heredan automáticamente.
> **Última actualización**: 2026-06-12.

## Glosario inicial

Antes de entrar al planteo, fijamos los términos técnicos que aparecen a lo largo del documento. La idea es que un lector que no sea especialista pueda seguirlo sin tener que adivinar significados.

| Término | Definición |
|---|---|
| **Programación lineal entera** (PLE) | Familia de problemas de optimización en los que se busca maximizar o minimizar una función lineal (objetivo) sujeta a restricciones lineales, donde algunas o todas las variables están obligadas a tomar valores enteros (típicamente 0 o 1). En el ámbito anglosajón se la llama *Integer Linear Programming* (ILP); usamos PLE como abreviatura en castellano. |
| **Programa lineal** | Cada instancia concreta de un problema de programación lineal entera. En este documento se usa indistintamente "programa lineal", "modelo" o "problema". |
| **Resolutor** | Programa informático que recibe un programa lineal entero y devuelve la solución óptima (o un certificado de infactibilidad). En la literatura anglosajona se lo llama *solver*. Ejemplos: CBC (libre), Gurobi, CPLEX (comerciales). |
| **Variable de decisión** | Las incógnitas del modelo cuyos valores el resolutor decide. En este planteo son binarias (0 o 1) y continuas (reales no negativas). |
| **Función objetivo** | La expresión lineal que el resolutor minimiza (o maximiza). |
| **Restricción** | Igualdad o desigualdad lineal que toda solución factible debe satisfacer. |
| **Factible** | Cualquier asignación de valores a las variables que cumple **todas** las restricciones. |
| **Óptimo** | La solución factible que minimiza (o maximiza) la función objetivo. |
| **Infactible** | Estado del modelo cuando no existe ninguna asignación que cumpla todas las restricciones simultáneamente. |
| **Relajación lineal** | Versión "ablandada" del programa lineal entero en la que las variables binarias se reemplazan por variables continuas en `[0, 1]`. La resuelve el resolutor internamente para obtener cotas y guiar la búsqueda. |
| **Ramificación y acotación** | Algoritmo estándar para resolver programas lineales enteros. Recursivamente parte el problema en subproblemas (ramifica) y descarta los que no pueden contener al óptimo (acota). En la literatura anglosajona se lo llama *branch-and-bound*. |
| **Patrón semanal** | El conjunto de horarios (materia / comisión / día / hora de inicio / hora de fin) que se repite todas las semanas del cuatrimestre. Es el sujeto sobre el que decide el programa lineal. |
| **Clase puntual** | Una instancia concreta del patrón en una fecha específica (por ejemplo, "lunes 22 de marzo, 14 a 18 hs"). Hereda el aula del patrón salvo override manual del operador. |
| **Sobre-ocupación** | Cantidad de inscriptos esperados que excede la capacidad efectiva del aula asignada. |
| **Sub-ocupación** | Cantidad de lugares vacíos en el aula asignada respecto a un umbral mínimo de aprovechamiento. |
| **Ventana operativa** | Rango horario en el que la facultad opera (por ejemplo, de 8 a 23 hs). Ningún horario puede caer fuera de ella. |
| **Doble asignación** | Situación prohibida en la que un mismo aula recibe dos horarios que se dictan al mismo tiempo. En la literatura anglosajona se la suele llamar *double booking*. |
| **Modalidad virtual** | Horario que se dicta en forma remota o asincrónica. No consume aula y se excluye del modelo. |
| **Restricción dura** y **restricción blanda** | Una restricción dura no admite violación: o se cumple o el modelo es infactible. Una restricción blanda admite violación pero la castiga con un peso en la función objetivo. En este modelo, capacidad es blanda (vía sobre/sub-ocupación). |

## Resumen ejecutivo

Una vez cerrada la grilla horaria de un cuatrimestre (qué materia/comisión se da qué día y a qué hora), queda un problema combinatorio: **a qué aula va cada uno de esos horarios semanales**. Lo modelamos como un **programa lineal entero (PLE)** y lo resolvemos con un resolutor clásico (CBC, accedido desde Python a través de la biblioteca PuLP).

El programa lineal decide tres cosas:

1. **El aula de cada horario** (variables `x[h, a] ∈ {0, 1}`, una por cada par horario-aula compatible).
2. **El tipo de cada horario** cuando no viene predeterminado (variables `t[h] ∈ {0, 1}`: 1 = laboratorio, 0 = teoría).
3. **Cómo se reparten los inscriptos esperados entre las comisiones de un mismo dictado** (variables `α[k] ∈ [0, 1]`, opcional según una opción configurable por el usuario).

El **objetivo** es lineal y asimétrico: minimizar la sobre-ocupación con un peso `λ_over` (valor por defecto 10) y la sub-ocupación con un peso `λ_under` (valor por defecto 1). Las **restricciones** garantizan asignación única, no doble asignación, compatibilidad de tipo aula↔clase, partición teoría/laboratorio coherente con la materia, y consistencia de los coeficientes cuando la opción de redistribución está activa.

## 1. Contexto y motivación

### 1.1 De qué problema estamos hablando

En una facultad mediana hay típicamente **algunos cientos de horarios semanales** (cada combinación materia-comisión-día-franja es uno) y **algunas decenas de aulas**, repartidas entre teóricas, anfiteatros y laboratorios de distintos tipos. Cada cuatrimestre alguien tiene que decidir, para cada horario, qué aula le toca.

A simple vista parece un problema de "encajar piezas". Pero cuando se mira con detalle aparecen tres complicaciones que lo vuelven no trivial:

- **Conflictos temporales**. Dos horarios que se dictan a la misma hora del mismo día no pueden compartir aula. Cuando son muchos en simultáneo (típico en franjas horarias populares como las 18 a 20), aparece un cuello de botella.
- **Tipo de aula vs tipo de clase**. Una clase de laboratorio no puede dictarse en cualquier aula: depende del laboratorio compatible con esa materia (el de Química requiere mecheros, el de Electrónica requiere instrumental, etcétera). Esto recorta drásticamente las opciones.
- **Capacidad vs cantidad de inscriptos**. Si una comisión tiene 80 inscriptos esperados y se la manda a un aula de 30, hay sobre-ocupación; al revés, si va al anfiteatro de 200, hay sub-utilización.

A esto se suma un grado de libertad adicional: hay materias donde el plan declara **horas de teoría y horas de laboratorio** por separado, pero los horarios cargados por el cronograma no siempre tienen esa partición resuelta. El programa lineal decide simultáneamente qué horarios son teoría, cuáles son laboratorio, y a qué aula van — todo de manera consistente.

### 1.2 Por qué un único modelo en lugar de un encadenamiento de etapas

La tentación natural es resolverlo en pasos: "primero decido el tipo de cada horario, después le busco aula". Eso falla por una razón simple: el tipo y el aula están **acoplados**. Si decidimos teoría/laboratorio de antemano y después no hay laboratorios disponibles en cierta franja, llegamos a infactibilidad evitable. Un único modelo combinado encuentra el óptimo del problema acoplado o demuestra que no hay solución.

### 1.3 Patrón semanal vs clases puntuales

El sistema distingue dos niveles:

- **Patrón semanal** (un horario): la franja que se repite todas las semanas del cuatrimestre. Por ejemplo: "Análisis Matemático I, Comisión A, lunes de 14 a 18 hs".
- **Clase puntual**: una instancia concreta del patrón en una fecha. Por ejemplo: "lunes 22 de marzo, 14 a 18 hs".

El **programa lineal trabaja exclusivamente sobre el patrón**: asigna un aula a cada horario semanal. Las clases puntuales heredan automáticamente esa aula. Cuando, después de correr el programa lineal, alguien necesita hacer una excepción puntual (cambiar de aula una clase un día específico, por ejemplo), eso queda como un override manual sobre la clase puntual y no afecta al patrón ni al programa lineal.

Esta separación es importante por dos motivos. Primero, **el programa lineal queda mucho más chico**: un cuatrimestre típico tiene ~600 horarios pero ~10000 clases puntuales (16 semanas × 600 = 9600). Resolver por patrón es un orden de magnitud menos. Segundo, separa con claridad qué decide la herramienta automática (el patrón) de qué decide el operador humano (las excepciones).

## 2. Alcance

### 2.1 Qué decide el programa lineal

- A qué **aula** va cada horario del cuatrimestre.
- De qué **tipo** es cada horario cuando el cronograma no lo predetermina.
- Cómo se **distribuyen los inscriptos esperados** entre comisiones de un mismo dictado (sólo si el usuario activa la opción "permitir reasignar pesos").

### 2.2 Qué NO toca el programa lineal

- **No crea ni elimina comisiones**. Las comisiones llegan ya definidas desde el panel de planificación. Si el resultado es malo o infactible, el usuario ajusta comisiones (sumar más, redistribuir pesos, mover horarios) y vuelve a correr.
- **No reescribe horarios**. Los días, horas y duraciones son datos de entrada fijos.
- **No asigna aulas a horarios virtuales** (modalidad a distancia o asincrónica). Esos horarios se filtran antes de armar el modelo: no consumen aula.
- **No decide reservas puntuales de laboratorio**. Si un día puntual una clase teórica necesita ir a un laboratorio (porque tienen una práctica especial), eso es una excepción ad-hoc posterior al programa lineal, no parte del planteo inicial.
- **No considera horarios ya ejecutados**. Si la corrida del programa lineal es a mitad del cuatrimestre, las clases que ya pasaron quedan intactas.

### 2.3 Supuestos modelados

1. **Inscriptos constantes por comisión**: el número de inscriptos esperados es el mismo para todos los horarios de una comisión (teóricas y laboratorios). Esto refleja que la matrícula es por comisión, no por franja.
2. **Aulas siempre disponibles**: cada aula está disponible toda la ventana operativa de la facultad (por ejemplo, de 8 a 23 hs). No se modelan indisponibilidades por exámenes, eventos, refacciones, etc.: queda como extensión futura.
3. **Una corrida por ciclo (cuatrimestre)**: dos cuatrimestres distintos se resuelven en corridas separadas, aun cuando hayan materias anuales que abarquen ambos.

## 3. Planteo matemático formal

### 3.1 Conjuntos

| Símbolo | Definición |
|---|---|
| `H` | Conjunto de **horarios semanales** del plan (no virtuales, no ejecutados). Cada `h ∈ H` representa una franja recurrente: una materia, una comisión, un día de la semana, una hora de inicio y una de fin. |
| `A` | Conjunto de **aulas** disponibles. |
| `A_t ⊆ A` | Aulas aptas para clase teórica (incluye anfiteatros). |
| `A_lab(m) ⊆ A` | Aulas aptas para clase de laboratorio de la materia `m`. Cada materia tiene su propia lista (los laboratorios son específicos por equipamiento). |
| `K` | Conjunto de **comisiones** del plan. Cada horario pertenece a una única comisión. |
| `D` | Conjunto de **dictados**. Un dictado agrupa todas las comisiones de una misma materia en el cuatrimestre. |
| `Sim` | Conjunto de **grupos de simultaneidad**. Cada `S ∈ Sim` es un subconjunto maximal de horarios que se dictan en simultáneo en algún instante de la semana (mismo día, intervalos solapados). |

### 3.2 Parámetros

| Símbolo | Tipo | Significado |
|---|---|---|
| `cap[a]` | entero positivo | Capacidad del aula `a`. |
| `total_esp[m]` | real positivo | Inscriptos esperados de la materia `m` en el cuatrimestre, según el módulo de pronóstico de inscripción. |
| `coef[k]` | real en `[0, 1]` | Coeficiente de asignación de la comisión `k` (qué fracción del total de la materia le corresponde). |
| `insc[h]` | real positivo | Inscriptos esperados en el horario `h`. Cuando la opción de redistribución está apagada: `insc[h] = total_esp[materia(h)] · coef[comision(h)]`. Cuando está encendida pasa a depender de las variables `α[k]`. |
| `dur[h]` | real positivo | Duración de la franja semanal en horas. |
| `hteo[m]`, `hlab[m]` | reales | Horas semanales de teoría y de laboratorio que la materia declara en su plan de estudios. |
| `fija_lab(h)` | `True` / `False` / `None` | Indicador que viene del cronograma: `True` si el horario está fijado como laboratorio, `False` si está fijado como teórico, `None` si la decisión la hace el programa lineal. |
| `compat[h, a]` | `0` / `1` | Pre-computado: vale 1 si el aula `a` puede recibir al horario `h` (ver § 3.5 R3). |
| `λ_over`, `λ_under` | reales positivos | Pesos de los penalizadores de sobre y sub-ocupación. Valores por defecto: 10 y 1. |
| `tol_over`, `tol_under` | reales en `[0, 1]` | Tolerancias relativas (un `tol_under = 0.20` permite 20% de sub-ocupación gratis). Valores por defecto: 0 y 0.20. |
| `activar_α` | `0` / `1` | Opción del usuario para permitir redistribución de pesos. Apagada por defecto. |

### 3.3 Variables de decisión

| Variable | Tipo | Cuándo existe | Significado |
|---|---|---|---|
| `x[h, a]` | binaria | para cada `(h, a)` con `compat[h, a] = 1` | Vale 1 si al horario `h` le asignamos el aula `a`. |
| `t[h]` | binaria | para cada `h` con `fija_lab(h) = None` | Vale 1 si el programa lineal decide que `h` es laboratorio, 0 si es teoría. Cuando `fija_lab(h)` viene fijado, `t[h]` es constante. |
| `α[k]` | continua en `[0, 1]` | para cada `k ∈ K`, sólo si `activar_α = 1` | Coeficiente nuevo de la comisión `k`. |
| `over[h]` | continua, `≥ 0` | para cada `h ∈ H` | Sobre-ocupación del horario respecto a la capacidad efectiva del aula asignada. |
| `under[h]` | continua, `≥ 0` | para cada `h ∈ H` | Sub-ocupación. |

### 3.4 Función objetivo

> **Cómo leer las fórmulas que vienen abajo**. Conviene fijar la notación antes de seguir, porque las restricciones siguientes la usan intensivamente.
>
> | Símbolo | Cómo se lee | Ejemplo |
> |---|---|---|
> | `Σ_a expr(a)` | "Suma de `expr(a)` para cada aula `a` del conjunto `A`" | `Σ_a x[h, a]` = `x[h, a₁] + x[h, a₂] + … + x[h, a_n]` |
> | `Σ_{a ∈ A_t} expr(a)` | "Suma de `expr(a)` sólo para las aulas `a` que pertenecen al subconjunto `A_t` (aulas teóricas)" | si `A_t = {a₁, a₂}`: `x[h, a₁] + x[h, a₂]` |
> | `Σ_{h ∈ S} expr(h)` | "Suma de `expr(h)` para cada horario `h` del grupo `S`" | si `S = {h₁, h₂, h₃}`: `x[h₁, a] + x[h₂, a] + x[h₃, a]` |
> | `∀ h ∈ H` | "Para todo horario `h` del conjunto `H`" — la igualdad o desigualdad se replica una vez por cada `h` | una restricción por horario |
> | `x[h, a]` | "La variable de decisión que vale 1 si al horario `h` le asignamos el aula `a`, y 0 si no" | binaria |
> | `t[h]` | "La variable que vale 1 si el horario `h` es laboratorio, 0 si es teórica" | binaria |
> | `dur[h]`, `cap[a]`, `insc[h]`, etc. | parámetros pre-computados, ver § 3.2 | reales |

```
min   λ_over · Σ_h over[h]   +   λ_under · Σ_h under[h]
```

**Cómo se lee**: "Minimizar la suma ponderada de dos sumatorias: la suma sobre todos los horarios de la sobre-ocupación, multiplicada por su peso `λ_over`, más la suma sobre todos los horarios de la sub-ocupación, multiplicada por su peso `λ_under`". En criollo: penalizar lugares de menos (mucho) y lugares de más (poco).

Con los valores por defecto (`λ_over = 10`, `λ_under = 1`) la sobre-ocupación se castiga **diez veces más** que la sub-ocupación. Esa asimetría refleja una preferencia operativa concreta: es mucho peor que entren 80 alumnos a un aula de 60 (alguien queda sin lugar) que dejar 30 lugares vacíos en un aula de 80.

### 3.5 Restricciones

#### R1 — Cada horario tiene exactamente un aula

```
Σ_a x[h, a] = 1     ∀ h ∈ H
```

**Cómo se lee**: "Para cada horario `h` del plan, la suma de `x[h, a]` sobre todas las aulas `a` debe ser exactamente 1". Como `x[h, a]` es una variable binaria que vale 1 cuando le asignamos el aula `a` a ese horario y 0 en caso contrario, sumarlas y exigir que dé 1 equivale a decir: "exactamente una de esas variables vale 1, y el resto valen 0". Es decir, **a cada horario le toca exactamente un aula**, ni dos ni cero.

#### R2 — Los horarios virtuales no consumen aula

Se filtran del conjunto `H` antes de instanciar el modelo: simplemente no aparecen.

#### R3 — Compatibilidad pre-computada

Para cada par `(h, a)` el sistema calcula previamente, fuera del programa lineal, si esa combinación es admisible:

```
compat[h, a] = 1   sii   alguno de:
  (a)  fija_lab(h) = False  ∧  a ∈ A_t
  (b)  fija_lab(h) = True   ∧  a ∈ A_lab(materia(h))
  (c)  fija_lab(h) = None
```

**Cómo se lee**: "El par `(h, a)` es compatible (vale 1) si y sólo si se cumple alguna de estas tres condiciones: **(a)** el horario está fijado como teórica (`fija_lab(h) = False`) y el aula pertenece al conjunto de aulas teóricas; **(b)** el horario está fijado como laboratorio (`fija_lab(h) = True`) y el aula está en la lista de laboratorios compatibles con la materia de ese horario; **(c)** el tipo del horario no está determinado todavía". El símbolo `∧` significa "y" lógico; `sii` se lee "si y sólo si".

Cuando el tipo está sin determinar (caso c), la compatibilidad real la termina de aportar R6 más adelante (porque allí se vincula `t[h]` con el aula elegida). Las variables `x[h, a]` con `compat = 0` directamente no se crean — equivale a fijarlas en cero pero achica el modelo de manera dramática.

#### R4 — No doble asignación en simultáneo

Para cada aula y cada grupo de horarios que se dictan en simultáneo, a lo sumo uno usa esa aula:

```
Σ_{h ∈ S} x[h, a] ≤ 1     ∀ a ∈ A,  ∀ S ∈ Sim
```

**Cómo se lee**: "Para cada aula `a` y cada grupo de simultaneidad `S` (un conjunto de horarios que comparten algún instante), la suma de las variables `x[h, a]` sobre los horarios de ese grupo es a lo sumo 1". Es decir: si tres horarios se solapan en un instante y miramos un aula concreta, **como mucho uno de esos tres horarios** puede tener esa aula asignada (`x = 1`); los demás tienen que estar en otras aulas (`x = 0`). Notá que es "≤ 1" y no "= 1": ninguno podría usar esa aula, lo importante es que no se pisen.

**Qué es un grupo de simultaneidad**. Si tres horarios `h₁, h₂, h₃` están todos activos a las 18:30 de un mismo lunes (porque sus intervalos `[hora_inicio, hora_fin)` cubren ese instante), forman un grupo de simultaneidad. La restricción para un aula `a` dice: "de esos tres horarios, a lo sumo uno puede usar `a`". El conjunto `Sim` es la unión de todos esos grupos a lo largo de la semana.

**Cómo se computa `Sim`** (barrido de eventos por día):

```
para cada día de la semana:
    eventos = lista ordenada de (hora_inicio, hora_fin) sobre los horarios de ese día
    activos = ∅
    para cada evento e en orden:
        antes de procesar e:
            si activos no está vacío y todavía no se emitió este conjunto:
                emitir grupo S = activos (es maximal en este intervalo)
        si e es un hora_inicio: activos.add(h)
        si e es un hora_fin:    activos.remove(h)
```

La justificación detallada de por qué se usa esta formulación (en lugar de la alternativa "una restricción por cada par solapado") está en § 4.5.

#### R5 — Coherencia entre teoría y laboratorio por comisión

Para cada comisión `k`, la suma de duraciones de sus horarios marcados como laboratorio tiene que coincidir con `hlab[materia(k)]` declarado en el plan de estudios:

```
Σ_{h ∈ k} dur[h] · t[h]       = hlab[materia(k)]    ∀ k ∈ K
Σ_{h ∈ k} dur[h] · (1 − t[h]) = hteo[materia(k)]    ∀ k ∈ K
```

**Cómo se leen**:

- **Primera línea** (laboratorio): "Para cada comisión `k`, la suma sobre los horarios de esa comisión del producto `dur[h] · t[h]` debe igualar las horas de laboratorio declaradas en la materia". Como `t[h]` vale 1 cuando el horario es laboratorio y 0 cuando es teórica, ese producto **'enciende' la duración sólo si el horario es laboratorio**. Sumar esos productos da las horas semanales totales de laboratorio de la comisión, y se exige que igualen lo que dice el plan de estudios.
- **Segunda línea** (teoría): análogo, pero con `(1 − t[h])`, que vale 1 cuando el horario **no** es laboratorio (o sea, es teórica). La suma da las horas totales de teoría y debe igualar `hteo[materia(k)]`.

Las dos ecuaciones son redundantes (una sale de la otra más la suma total `Σ dur = hteo + hlab`), pero conviene escribir ambas: hace la formulación más explícita y le da más estructura al resolutor para podar.

#### R6 — Conjunto de aulas según el tipo decidido

Cuando `fija_lab(h) = None`, el aula elegida tiene que ser consistente con el valor de `t[h]`:

```
Σ_{a ∈ A_t}            x[h, a] ≥ 1 − t[h]   si  fija_lab(h) = None
Σ_{a ∈ A_lab(materia(h))} x[h, a] ≥ t[h]    si  fija_lab(h) = None
```

**Cómo se leen**:

- **Primera línea**: "La suma de `x[h, a]` sobre las aulas teóricas debe ser al menos `1 − t[h]`". Si el programa lineal decide `t[h] = 0` (el horario es teórico), el lado derecho es `1`, así que **alguna** de las aulas teóricas tiene que tener `x[h, a] = 1`. Si decide `t[h] = 1` (laboratorio), el lado derecho es `0` y la restricción no exige nada (queda inactiva).
- **Segunda línea**: análogamente, "la suma de `x[h, a]` sobre las aulas que son laboratorios compatibles con la materia del horario debe ser al menos `t[h]`". Si `t[h] = 1`, alguna aula de ese conjunto tiene que estar elegida; si `t[h] = 0`, no se exige nada.

Junto con R1 (que dice "exactamente una aula"), esto garantiza: si `t[h] = 0`, el horario va a aula teórica; si `t[h] = 1`, va a un laboratorio compatible con su materia.

#### R7 — Sobre y sub-ocupación lineal

```
over[h]  ≥ insc[h] − Σ_a x[h, a] · cap[a] · (1 + tol_over)        ∀ h ∈ H
under[h] ≥ Σ_a x[h, a] · cap[a] · (1 − tol_under) − insc[h]       ∀ h ∈ H
over[h], under[h] ≥ 0
```

**Cómo se leen**: la expresión `Σ_a x[h, a] · cap[a]` es un truco lineal estándar: como exactamente una `x[h, a]` vale 1 (por R1), la suma colapsa a la **capacidad del aula efectivamente asignada al horario `h`**. La llamamos `cap_asignada(h)`. Con eso:

- **Primera línea**: `over[h] ≥ insc[h] − cap_asignada(h) · (1 + tol_over)`. Es decir, "la sobre-ocupación es al menos la diferencia entre inscriptos esperados y la capacidad efectiva tolerada". Si los inscriptos no superan la capacidad tolerada, el lado derecho da negativo y la restricción se satisface trivialmente con `over[h] = 0` (porque también exigimos `over[h] ≥ 0`). Si la superan, `over[h]` queda forzado al exceso. Como en el objetivo se **minimiza** `over`, el programa lineal la deja siempre lo más chica posible.
- **Segunda línea**: análogamente, "la sub-ocupación es al menos la diferencia entre la capacidad mínima tolerada y los inscriptos". `under[h]` mide cuánto se desperdicia respecto al umbral inferior `cap · (1 − tol_under)`.

No hay restricción dura "capacidad ≥ inscriptos": la sobre-ocupación se castiga con peso `λ_over` (es una **restricción blanda** linealizada). Si alguien quiere capacidad como restricción dura, basta con poner `λ_over` muy grande.

#### R8 — Ventana operativa global (defensiva)

```
hora_inicio(h) ≥ open_h   ∧   hora_fin(h) ≤ close_h     ∀ h ∈ H
```

Esto se chequea **antes** de armar el programa lineal, no como restricción del modelo. Si algún horario cae fuera de la ventana operativa de la facultad (por ejemplo, a las 23:30 con cierre a las 23:00), el sistema aborta con un mensaje claro y el operador corrige el cronograma o amplía la ventana.

#### R9 — Coeficientes de comisión (sólo si la opción está prendida)

```
Σ_{k ∈ d} α[k] = 1                          ∀ d ∈ D
α_min ≤ α[k] ≤ α_max                         ∀ k ∈ K
insc[h] = total_esp[materia(k)] · α[k]      ∀ h con comision(h) = k
```

**Cómo se leen**:

- **Primera línea**: "Para cada dictado `d` (un dictado agrupa todas las comisiones de una misma materia en el cuatrimestre), la suma de los coeficientes `α[k]` sobre las comisiones de ese dictado debe ser exactamente 1". En criollo: los porcentajes de inscriptos repartidos entre comisiones de la misma materia tienen que sumar el 100%.
- **Segunda línea**: cota inferior y superior para cada `α[k]`. Por defecto `α_min = 0` y `α_max = 1`, así que cada coeficiente queda en el intervalo `[0, 1]`.
- **Tercera línea**: "Para cada horario `h` cuya comisión es `k`, los inscriptos esperados se calculan como el total estimado de la materia multiplicado por el coeficiente de la comisión". Acá `insc[h]` deja de ser un parámetro pre-calculado y pasa a ser una **expresión lineal** que depende de las variables `α[k]`. Por eso R7 (que usa `insc[h]`) se reescribe por sustitución cuando la opción está prendida.

Cuando la opción está apagada, `insc[h]` es un parámetro fijo. Cuando está prendida, pasa a ser una expresión lineal en `α[k]`, y las restricciones R7 se reescriben por sustitución. El producto `α[k] · cap[a]` no aparece (R7 multiplica capacidad por `x[h, a]`, no por `α[k]`), así que la formulación se mantiene lineal.

#### R10 — Restricción de sede por carrera y materia

Cada materia tiene un conjunto de sedes admisibles `Sed(m) ⊆ Sedes` que el LP respeta:

```
x[h, a] = 0     ∀ h ∈ H,  ∀ a ∈ A   tal que
                aula_sede(a) ∉ Sed(materia(h))   y   a ∉ A_lab(materia(h))
```

**Cómo se lee**: "Para cada horario `h` y cada aula `a`, si la sede del aula no pertenece al conjunto de sedes admisibles de la materia y el aula tampoco es un laboratorio compatible con esa materia, entonces la asignación se prohíbe (`x[h, a] = 0`)".

**Cómo se calcula `Sed(m)`**:

- **Materia común** (pertenece a ≥2 carreras): `Sed(m) = {sede_default_comunes}`. Si no hay sede default configurada, `Sed(m) = Sedes` (sin restricción).
- **Materia exclusiva** (pertenece a 1 carrera): `Sed(m) = sedes habilitadas para esa carrera` (vía la tabla M:N carrera↔sede). Si la carrera no tiene sedes configuradas, `Sed(m) = Sedes` (sin restricción).
- **Excepción de laboratorio**: si `a ∈ A_lab(m)`, la restricción de sede no aplica (la compatibilidad de laboratorio prevalece).

**Implementación**: en lugar de generar restricciones explícitas en el LP, R10 se aplica como **filtro adicional al cómputo de `compat[h, a]`** (las variables `x[h, a]` con sede inadmisible directamente no se crean). Equivale matemáticamente a la formulación `x[h, a] = 0` pero achica el modelo dramáticamente.

### 3.6 Salida del programa lineal

Una vez resuelto, el programa lineal devuelve, para cada horario:

- el aula asignada (donde `x[h, a]* = 1`);
- el tipo decidido cuando antes no estaba fijado (`t[h]*`);
- los coeficientes `α[k]*` reasignados, si la opción estaba prendida y el operador acepta persistirlos.

Esa decisión queda como **patrón semanal**: todas las clases puntuales del cuatrimestre la heredan al generarse o cuando el operador re-corre la generación de clases. Las excepciones puntuales por fecha quedan fuera del alcance del programa lineal.

## 4. Casos particulares de la función objetivo

| Configuración | Comportamiento |
|---|---|
| `λ_over` muy grande, `λ_under = 0` | Capacidad como restricción dura. Si no hay solución factible, infactibilidad. |
| `λ_over = λ_under`, `tol_over = tol_under = 0` | Penalización simétrica: `\|capacidad − inscriptos\|`. |
| `λ_over = 10`, `λ_under = 1`, `tol_under = 0.2` (defecto) | Asimétrico: castiga fuerte sobre-ocupación, tolera hasta 20% de sub-ocupación gratis. |
| `λ_under = 0`, `tol_under = 1.0` | Sólo importa no sobre-asignar; cualquier sub-utilización es gratis. |

## 4.5 Por qué la formulación por grupos de simultaneidad es mejor que la formulación por pares

Esta sección desarrolla la elección de cómo escribir R4. Es una decisión de diseño no obvia y con impacto directo en el tiempo del resolutor, así que vale la pena justificarla en detalle.

### 4.5.1 Las dos formulaciones equivalentes

**Formulación por pares** (la primera que uno tiende a escribir): para cada par `(h₁, h₂)` de horarios que se solapan, una restricción por aula:

```
x[h₁, a] + x[h₂, a] ≤ 1     ∀ a ∈ A,  ∀ (h₁, h₂) ∈ Conf
```

**Formulación por grupos de simultaneidad** (la elegida): para cada grupo maximal `S` de horarios que están todos activos en algún instante común, una sola restricción por aula:

```
Σ_{h ∈ S} x[h, a] ≤ 1     ∀ a ∈ A,  ∀ S ∈ Sim
```

Sobre variables enteras `x ∈ {0, 1}` ambas describen exactamente el mismo conjunto factible. La diferencia se ve en otro lado.

### 4.5.2 Diferencia conceptual: cantidad de restricciones

Sea `S` un grupo de tamaño `n`. La formulación por pares genera `n(n−1)/2` restricciones para ese grupo (una por par). La formulación por grupos genera **una sola**.

En horarios universitarios reales los grupos en franjas populares (lunes 18 a 20, miércoles 8 a 10) pueden tener fácilmente entre 10 y 30 horarios simultáneos. Con `n = 20`, la formulación por pares produce 190 restricciones por aula contra 1 de la formulación por grupos. Multiplicado por la cantidad de aulas y de grupos a lo largo de la semana, la diferencia en tamaño del modelo es sustancial.

### 4.5.3 Diferencia clave: fuerza de la relajación lineal

Este es el punto central. Los resolutores de programación entera mixta (CBC, Gurobi, CPLEX) resuelven internamente una sucesión de **relajaciones lineales**, donde las variables `x[h, a] ∈ {0, 1}` se reemplazan por `x[h, a] ∈ [0, 1]`. Cuanto más ajustada sea la cota inferior que devuelve la relajación, más rápido converge la **ramificación y acotación**, porque hay menos puntos fraccionarios que descartar.

Una formulación es **más fuerte** que otra cuando su poliedro de soluciones fraccionarias está estrictamente contenido en el de la otra. Las soluciones enteras coinciden, pero la formulación más fuerte recorta puntos fraccionarios que la otra admite.

**Ejemplo con tres horarios simultáneos**. Sean `h₁, h₂, h₃` activos al mismo instante (forman un grupo de tamaño 3) y consideremos una sola aula `a`:

- **Por pares**: tres restricciones, `x[h₁,a] + x[h₂,a] ≤ 1`, `x[h₁,a] + x[h₃,a] ≤ 1`, `x[h₂,a] + x[h₃,a] ≤ 1`. La solución fraccionaria `x[h₁,a] = x[h₂,a] = x[h₃,a] = 1/2` satisface las tres (cada par suma 1) y es factible para la relajación.
- **Por grupos**: una sola restricción, `x[h₁,a] + x[h₂,a] + x[h₃,a] ≤ 1`. Esa misma solución suma `3/2 > 1` y queda **excluida** de la relajación.

En el caso general con `n` horarios en un grupo, la formulación por pares admite la solución fraccionaria `x[h, a] = 1/(n−1)` para cada `h` (cada par suma `2/(n−1) ≤ 1`), mientras que la por grupos la rechaza apenas `n ≥ 2`. La brecha entre la relajación y el óptimo entero crece con `n`, y la formulación por grupos la cierra de un saque.

### 4.5.4 Conexión con la teoría

Las restricciones del tipo "a lo sumo una de un conjunto de variables binarias vale 1" se llaman **restricciones de empaquetamiento de conjunto** (en la literatura, *set packing*). Cuando el conjunto corresponde a un grupo maximal de simultáneos, la desigualdad es una **faceta** del poliedro entero asociado (Nemhauser & Wolsey, *Integer and Combinatorial Optimization*, capítulo III.6, "Polyhedra of the Set Packing Problem"). Las facetas son las desigualdades más fuertes posibles: no se las puede ajustar más sin recortar soluciones enteras válidas.

Las desigualdades por pares, en cambio, son **dominadas** por las desigualdades por grupos: sumando las `n(n−1)/2` desigualdades por pares se obtiene `(n−1) · Σ x_h ≤ n(n−1)/2`, equivalente a `Σ x_h ≤ n/2`, estrictamente más débil que `Σ x_h ≤ 1` para `n ≥ 3`.

Esta es la razón teórica por la cual los modelos de planificación con conflictos sobre un recurso compartido (aulas, máquinas, frecuencias) usan formulaciones por grupos siempre que sea razonable enumerarlos.

### 4.5.5 Costo de obtener los grupos

La objeción natural: "obtener grupos maximales en un grafo arbitrario es **NP-difícil**" (clase de problemas para los cuales no se conoce un algoritmo eficiente; informalmente, "muy difíciles de resolver en general"). Es cierto en general, pero acá el grafo es **de intervalos** (cada horario es un intervalo en una recta de tiempo por día), y los grafos de intervalos tienen estructura especial: los grupos maximales se obtienen en tiempo lineal con un barrido de eventos. Cada vez que se abre un nuevo intervalo, los activos en ese momento forman un grupo maximal candidato; cada vez que se cierra, se reevalúa.

El costo total: `O(N log N)` por día (dominado por el ordenamiento de eventos), donde `N` es la cantidad de horarios de ese día. Para una facultad típica con decenas de horarios por día, son milisegundos.

### 4.5.6 Resumen del beneficio

| Aspecto | Por pares | Por grupos de simultaneidad |
|---|---|---|
| Restricciones para un grupo de `n` | `n(n−1)/2` por aula | `1` por aula |
| Soluciones fraccionarias `x = 1/(n−1)` | admitidas | rechazadas para `n ≥ 2` |
| Cota inferior de la relajación | más floja | más ajustada |
| Ramificación del resolutor | más costosa | más liviana |
| Estatus teórico | desigualdades dominadas | facetas del poliedro de empaquetamiento |
| Costo de cómputo previo | trivial (enumerar pares) | `O(N log N)` por día (barrido) |
| Costo durante la corrida del programa lineal | mayor | menor |

La conclusión: la formulación por grupos no es una optimización menor, es la formulación canónica del problema. Para una defensa académica el contraste entre ambas formulaciones ilustra la diferencia entre **modelar correctamente** (la formulación por pares lo hace) y **modelar para que el resolutor pueda aprovecharlo** (la formulación por grupos).

## 4.6 El programa lineal en limpio

### 4.6.1 Notación de tamaños

| Símbolo | Significado |
|---|---|
| `\|H\|` | cantidad de horarios |
| `\|A\|` | cantidad de aulas |
| `\|K\|` | cantidad de comisiones |
| `\|D\|` | cantidad de dictados |
| `\|Sim\|` | cantidad de grupos de simultaneidad maximales |
| `\|H_∅\|` | cantidad de horarios con `fija_lab(h) = None` |
| `\|compat\|` | cantidad total de pares `(h, a)` con `compat[h, a] = 1` |

### 4.6.2 Variables del modelo

| Variable | Tipo | Cantidad |
|---|---|---|
| `x[h, a]` | binaria | `\|compat\|` |
| `t[h]` | binaria | `\|H_∅\|` |
| `α[k]` | continua en `[0, 1]` | `\|K\|` (sólo si la opción de redistribución está activa) |
| `over[h]` | continua, `≥ 0` | `\|H\|` |
| `under[h]` | continua, `≥ 0` | `\|H\|` |

**Total con la opción de redistribución apagada**: `\|compat\| + \|H_∅\| + 2·\|H\|` variables, de las cuales `\|compat\| + \|H_∅\|` son binarias.

### 4.6.3 Restricciones (vista compacta con conteo)

| ID | Forma | Cantidad | Para qué sirve |
|---|---|---|---|
| R1 | `Σ_a x[h, a] = 1` para cada `h` | `\|H\|` | Cada horario tiene un aula |
| R4 | `Σ_{h ∈ S} x[h, a] ≤ 1` para cada `a, S` | `\|A\| · \|Sim\|` | Un aula no recibe dos horarios simultáneos |
| R5a | `Σ_{h ∈ k} dur[h] · t[h] = hlab[materia(k)]` | `\|K\|` | Suma de horas de laboratorio por comisión |
| R5b | `Σ_{h ∈ k} dur[h] · (1 − t[h]) = hteo[materia(k)]` | `\|K\|` | Análogo para teoría |
| R6a | `Σ_{a ∈ A_t} x[h, a] ≥ 1 − t[h]` para cada `h` con tipo libre | `\|H_∅\|` | Si `t[h] = 0`, el aula es teórica |
| R6b | `Σ_{a ∈ A_lab(materia(h))} x[h, a] ≥ t[h]` para cada `h` con tipo libre | `\|H_∅\|` | Si `t[h] = 1`, el aula es laboratorio compatible |
| R7a | `over[h] ≥ insc[h] − Σ_a x[h,a] · cap[a] · (1 + tol_over)` | `\|H\|` | Lineariza la sobre-ocupación |
| R7b | `under[h] ≥ Σ_a x[h,a] · cap[a] · (1 − tol_under) − insc[h]` | `\|H\|` | Lineariza la sub-ocupación |
| R9a | `Σ_{k ∈ d} α[k] = 1` (sólo si la opción está activa) | `\|D\|` o 0 | Suma de coeficientes por dictado |
| R10 | `x[h, a] = 0` cuando `aula_sede(a) ∉ Sed(materia(h))` y `a ∉ A_lab(materia(h))` | 0 (filtro pre-LP, no genera filas) | Materias exclusivas sólo en sedes de su carrera; comunes sólo en sede default |

**Total** (opción de redistribución apagada): `\|H\| + \|A\| · \|Sim\| + 2·\|K\| + 2·\|H_∅\| + 2·\|H\|`. El término dominante es `\|A\| · \|Sim\|`.

### 4.6.4 El programa lineal en una sola vista

```
Variables:
    x[h, a] ∈ {0, 1}        ∀ (h, a) con compat[h, a] = 1
    t[h]    ∈ {0, 1}        ∀ h ∈ H con fija_lab(h) = None
    α[k]    ∈ [0, 1]        ∀ k ∈ K          (si redistribución activa)
    over[h]  ≥ 0             ∀ h ∈ H
    under[h] ≥ 0             ∀ h ∈ H

Objetivo:
    minimizar  λ_over · Σ_h over[h]  +  λ_under · Σ_h under[h]

Sujeto a:
    R1   Σ_a x[h, a] = 1                                          ∀ h ∈ H
    R4   Σ_{h ∈ S} x[h, a] ≤ 1                                     ∀ a ∈ A, ∀ S ∈ Sim
    R5a  Σ_{h ∈ k} dur[h] · t[h]       = hlab[materia(k)]          ∀ k ∈ K
    R5b  Σ_{h ∈ k} dur[h] · (1 − t[h]) = hteo[materia(k)]          ∀ k ∈ K
    R6a  Σ_{a ∈ A_t} x[h, a]            ≥ 1 − t[h]                 ∀ h con fija_lab(h) = None
    R6b  Σ_{a ∈ A_lab(materia(h))} x[h, a] ≥ t[h]                  ∀ h con fija_lab(h) = None
    R7a  over[h]  ≥ insc[h] − Σ_a x[h,a] · cap[a] · (1 + tol_over) ∀ h ∈ H
    R7b  under[h] ≥ Σ_a x[h,a] · cap[a] · (1 − tol_under) − insc[h]∀ h ∈ H
    R9   Σ_{k ∈ d} α[k] = 1   y   insc[h] = total_esp[materia(k)] · α[k]   (si redistribución activa)
    R10  x[h, a] = 0   ∀ (h, a)   con   aula_sede(a) ∉ Sed(materia(h))   y   a ∉ A_lab(materia(h))

Pre-condiciones (verificadas antes de armar el programa lineal):
    - factibilidad de partición teoría/laboratorio por comisión (suma de subconjunto)
    - hora_inicio(h) ≥ open_h ∧ hora_fin(h) ≤ close_h               ∀ h ∈ H   (R8)
```

## 5. Ejemplo en miniatura

> Esta sección desarrolla el programa lineal completo sobre un caso pequeño como uno lo escribiría en papel o en LINDO. Sirve para concretar el modelo y mostrar cómo se traducen las restricciones generales a un problema chico.

### 5.1 Instancia

Imaginá una facultad con **un solo día** (digamos lunes) y los siguientes datos.

**Horarios** (`H`):

| Horario | Comisión | Materia | Día | De | Hasta | Tipo fijado | Inscriptos esperados |
|---|---|---|---|---|---|---|---|
| h₁ | A1 | Análisis | Lun | 14:00 | 16:00 | teórico | 80 |
| h₂ | B1 | Programación | Lun | 14:00 | 16:00 | teórico | 30 |
| h₃ | C1 | Química | Lun | 15:00 | 17:00 | laboratorio | 25 |
| h₄ | A1 | Análisis | Lun | 16:00 | 18:00 | sin determinar | 80 |

Todos los horarios son de la única comisión por materia. La materia "Análisis" declara `hteo = 4`, `hlab = 0`. Como `h₁` ya está fijado como teórico (2 horas), el programa lineal tiene que decidir el tipo de `h₄` (las otras 2 horas) cumpliendo R5: la suma de horas teóricas de A1 tiene que ser 4 y de laboratorio 0, por lo tanto `t[h₄] = 0` (teórica). Es decir, en este ejemplo `h₄` queda forzado a teórica por R5: el tipo se decide indirectamente.

**Aulas** (`A`):

| Aula | Tipo | Capacidad |
|---|---|---|
| a₁ | teórica | 100 |
| a₂ | teórica | 40 |
| a₃ | laboratorio (compatible con Química) | 30 |

**Parámetros del objetivo**: `λ_over = 10`, `λ_under = 1`, `tol_over = 0`, `tol_under = 0.20`.

### 5.2 Compatibilidades

Aplicando R3 horario por horario:

- `h₁`, `h₂`, `h₄` son teóricos → compatibles con `{a₁, a₂}`.
- `h₃` es laboratorio de Química → compatible con `{a₃}` (única laboratorio compatible).

Variables `x[h, a]` que se crean:

```
x[h₁, a₁]   x[h₁, a₂]
x[h₂, a₁]   x[h₂, a₂]
x[h₃, a₃]
x[h₄, a₁]   x[h₄, a₂]
```

(Variables `x[h₁, a₃]`, `x[h₂, a₃]`, `x[h₃, a₁]`, `x[h₃, a₂]`, `x[h₄, a₃]` no se crean — equivalen a 0.)

Variables `t[h]`: sólo `t[h₄]`, las demás están fijadas.

Variables `over[h]` y `under[h]`: una por cada horario.

### 5.3 Grupos de simultaneidad

Hacemos el barrido de eventos del lunes:

```
14:00  inicio h₁ → activos = {h₁}
14:00  inicio h₂ → activos = {h₁, h₂}                ← grupo S₁ candidato
15:00  inicio h₃ → activos = {h₁, h₂, h₃}             ← grupo S₂ candidato
16:00  fin h₁    → activos = {h₂, h₃}
16:00  fin h₂    → activos = {h₃}
16:00  inicio h₄ → activos = {h₃, h₄}                 ← grupo S₃ candidato
17:00  fin h₃    → activos = {h₄}
18:00  fin h₄    → activos = ∅
```

Filtrando subconjuntos no maximales (S₁ ⊆ S₂ así que S₁ se descarta), quedan los grupos:

```
S₂ = {h₁, h₂, h₃}    (de 15 a 16)
S₃ = {h₃, h₄}         (de 16 a 17)
```

### 5.4 Modelo escrito en limpio

**Función objetivo**:

```
min   10·(over[h₁] + over[h₂] + over[h₃] + over[h₄])
      +  1·(under[h₁] + under[h₂] + under[h₃] + under[h₄])
```

**R1 — un aula por horario**:

```
x[h₁, a₁] + x[h₁, a₂] = 1
x[h₂, a₁] + x[h₂, a₂] = 1
x[h₃, a₃] = 1
x[h₄, a₁] + x[h₄, a₂] = 1
```

(R1 para h₃ se reduce trivialmente: el programa lineal fuerza `x[h₃, a₃] = 1`.)

**R4 — no doble asignación sobre los grupos S₂ y S₃, por aula**:

Para `S₂ = {h₁, h₂, h₃}`:

```
x[h₁, a₁] + x[h₂, a₁] + 0           ≤ 1     (h₃ no puede ir a a₁)
x[h₁, a₂] + x[h₂, a₂] + 0           ≤ 1
0         + 0         + x[h₃, a₃]   ≤ 1     (trivial: equivale a R1 de h₃)
```

Para `S₃ = {h₃, h₄}`:

```
0           + x[h₄, a₁] ≤ 1
0           + x[h₄, a₂] ≤ 1
x[h₃, a₃]   + 0         ≤ 1
```

(Las que tienen sólo un término no aportan nada nuevo en este ejemplo, pero el modelo general las emite. En código se podrían filtrar.)

**R5 — partición teoría/laboratorio por comisión**:

Para A1 (`hteo = 4`, `hlab = 0`, horarios `{h₁, h₄}`, duraciones 2 y 2):

```
2·t[h₄]              = 0       (la parte de h₁ es 2·0 = 0 porque está fijada teórica)
2·1 + 2·(1 − t[h₄])  = 4
```

De la primera, `t[h₄] = 0`. La segunda queda satisfecha. (En la práctica, conviene escribir las dos para que el resolutor las explote, aunque sean redundantes.)

Para B1 (`hteo = 2`, `hlab = 0`, horario `{h₂}` de duración 2):

```
2·0 = 0     (trivial, h₂ está fijada teórica)
2·1 = 2     ✓
```

Para C1 (`hteo = 0`, `hlab = 2`, horario `{h₃}` de duración 2):

```
2·1 = 2     ✓
2·0 = 0     ✓
```

**R6 — conjunto de aulas para horario con tipo libre**:

Sólo aplica a `h₄`:

```
x[h₄, a₁] + x[h₄, a₂]  ≥  1 − t[h₄]
0                       ≥  t[h₄]
```

(La segunda — sumatoria sobre `A_lab(Análisis)` — es 0 porque Análisis no tiene laboratorios compatibles. Esto fuerza `t[h₄] ≤ 0`, es decir `t[h₄] = 0`.)

**R7 — sobre y sub-ocupación lineal**:

Capacidades efectivas con `tol_over = 0`, `tol_under = 0.20`:

```
cap_efectiva_over(a)  = cap[a]
cap_efectiva_under(a) = cap[a] · 0.8
```

Para `h₁` (insc = 80):

```
over[h₁]  ≥ 80 − (100·x[h₁,a₁] + 40·x[h₁,a₂])
under[h₁] ≥ (80·x[h₁,a₁] + 32·x[h₁,a₂]) − 80
```

Para `h₂` (insc = 30):

```
over[h₂]  ≥ 30 − (100·x[h₂,a₁] + 40·x[h₂,a₂])
under[h₂] ≥ (80·x[h₂,a₁] + 32·x[h₂,a₂]) − 30
```

Para `h₃` (insc = 25, sólo va a a₃ con cap = 30):

```
over[h₃]  ≥ 25 − 30·x[h₃,a₃] = 25 − 30 = −5  →  over[h₃] = 0
under[h₃] ≥ 24·x[h₃,a₃] − 25 = 24 − 25 = −1  →  under[h₃] = 0
```

(Las dos quedan en 0 porque la capacidad de a₃ está cómoda para 25 inscriptos con la tolerancia de 20%.)

Para `h₄` (insc = 80, idéntico planteo que `h₁`).

### 5.5 Resolución manual

R1 ya forzó `x[h₃, a₃] = 1`. R5 forzó `t[h₄] = 0`. Quedan `h₁`, `h₂`, `h₄` distribuidos entre `a₁` (cap 100) y `a₂` (cap 40), con la restricción R4: a las 15:00 simultanean `h₁` y `h₂` (no pueden compartir aula), y a las 16:00 simultanean `h₃` y `h₄` (`h₃` está en `a₃`, así que no compite con `h₄` por `a₁/a₂`).

Las opciones para `(h₁, h₂)` son:

| `h₁` | `h₂` | over[h₁] | under[h₁] | over[h₂] | under[h₂] | Costo parcial |
|---|---|---|---|---|---|---|
| `a₁` (cap 100) | `a₂` (cap 40) | 0 | 0 | 0 | 2 (32 − 30) | `0·10 + 2·1 = 2` |
| `a₂` (cap 40) | `a₁` (cap 100) | 40 | 0 | 0 | 50 (80 − 30) | `40·10 + 50·1 = 450` |

Claramente la primera opción es la buena: `h₁ → a₁`, `h₂ → a₂`. Costo parcial: 2.

Para `h₄` (insc 80), las opciones son `a₁` o `a₂` (idéntico análisis que `h₁`):

| `h₄` | over[h₄] | under[h₄] | Costo |
|---|---|---|---|
| `a₁` (cap 100) | 0 | 0 | 0 |
| `a₂` (cap 40) | 40 | 0 | 400 |

`h₄ → a₁`. Sumando: costo total = 2 + 0 = **2**.

### 5.6 Solución

```
x[h₁, a₁] = 1     (Análisis A1, lunes 14-16, en aula 1 — capacidad 100, 80 inscriptos)
x[h₂, a₂] = 1     (Programación B1, lunes 14-16, en aula 2 — capacidad 40, 30 inscriptos)
x[h₃, a₃] = 1     (Química C1, lunes 15-17, en laboratorio 3 — capacidad 30, 25 inscriptos)
x[h₄, a₁] = 1     (Análisis A1, lunes 16-18, en aula 1 — capacidad 100, 80 inscriptos)
t[h₄]     = 0     (h₄ es teórico, decidido por R5+R6)
over[h]   = 0     ∀h
under[h₂] = 2,    under[h₁] = under[h₃] = under[h₄] = 0
Costo total = 2
```

El óptimo coincide con la intuición operativa: las clases grandes (h₁, h₄) van al aula grande, la clase chica (h₂) va al aula chica, y el laboratorio va al laboratorio compatible. La sub-ocupación residual de 2 alumnos en a₂ con respecto a la capacidad efectiva de 32 (40 · 0.8) es inevitable y aceptable.

Este ejemplo ilustra cómo se concretan las restricciones generales sobre una instancia chica. En el caso real con cientos de horarios y decenas de aulas, el programa lineal escala pero la mecánica de cada restricción es exactamente la misma.

## 6. Diagnóstico estructural de infactibilidad

Cuando el resolutor declara el modelo **infactible** y no muestra causa, el operador queda sin acción concreta. Para evitarlo, el sistema computa **antes** de la resolución un diagnóstico estructural que identifica las causas más comunes y las reporta con mensajes accionables. Esto se ejecuta también si la corrida resulta óptima: el detalle queda persistido aunque no se muestre en la interfaz.

Las técnicas se aplican en orden de costo creciente y se reportan separadamente.

### 6.1 Horarios sin aula compatible

Para cada horario `h`, se calcula `|{a : compat[h, a] = 1}|`. Si es 0, ningún aula puede recibirlo y el modelo es infactible por R1. Casos típicos:

- Horario de laboratorio de una materia que no tiene laboratorios compatibles cargados.
- Horario teórico cuando no hay aulas teóricas/anfiteatros suficientes en el inventario.

Costo: `O(|H| × |A|)`.

### 6.2 Saturación por tipo dentro de una franja

La cota global del **principio del palomar** (clases vs aulas totales en una franja; en la literatura, *pigeonhole principle*: si hay más palomas que casilleros, alguna casilla queda con más de una paloma) es **necesaria** pero no aprovecha la información de tipos. Una franja con 5 horarios simultáneos y 6 aulas en total puede sonar OK, pero si los 5 son teóricos y sólo 4 aulas son del tipo correcto, el modelo es infactible.

Para cada grupo de simultaneidad `S` se separa el conteo:

- **Conjunto teórica**: horarios de `S` que estrictamente necesitan aula teórica (por `fija_lab = teórica`, o por `fija_lab = None` con materia sin laboratorios compatibles disponibles, que R6 mandaría a teórica).
- **Conjunto laboratorio por materia**: cada materia `m` con horarios laboratorio simultáneos en `S` requiere `|S_m| ≤ |A_lab(m)|`.

El manejo es **optimista** con los `fija_lab = None`: si tienen laboratorios disponibles para su materia, no se cuentan como teóricos forzados, porque R5+R6 podrían mandarlos a laboratorio. Eso evita falsos positivos.

Costo: `O(|Sim| · |H_grupo| · |A|)`.

### 6.3 Test de Hall (apareamiento bipartito)

> **Apareamiento bipartito**: dado un conjunto de horarios y un conjunto de aulas con sus compatibilidades, un apareamiento es una asignación uno-a-uno sin conflictos (un horario, un aula, sin repetir). Es **perfecto** si todos los horarios quedan asignados. En la literatura anglosajona se lo llama *bipartite matching*.

La cota del principio del palomar sobre la unión `|N(grupo)| ≥ |grupo|` es necesaria pero no suficiente. Ejemplo:

> Grupo `{h₁, h₂, h₃}`. h₁ admite `{a, b, c}`, h₂ admite `{a}`, h₃ admite `{a}`. La unión es `{a, b, c}` de tamaño 3 ≥ 3, pero el subconjunto `{h₂, h₃}` tiene `N = {a}` de tamaño 1 < 2: infactible.

El test correcto es el **teorema de Hall**: existe un apareamiento perfecto si y sólo si para todo subconjunto `S ⊆ grupo`, `|N(S)| ≥ |S|` (la vecindad de cualquier subconjunto tiene al menos tantos elementos como el subconjunto). Implementación:

- **Grupos chicos** (umbral configurable, ~8): enumeración exacta de los `2^|grupo|` subconjuntos por tamaño creciente. Se reporta el subconjunto Hall-violador **más chico** como testigo.
- **Grupos más grandes**: algoritmo clásico de apareamiento bipartito por **caminos de aumento** (técnica que parte de un apareamiento parcial e itera buscando trayectorias alternantes que permitan agrandarlo; en la literatura, *augmenting paths*). Costo: `O(V·E)` donde `V` y `E` son los vértices y aristas del grafo bipartito. Si el apareamiento máximo es menor que el grupo, hay infactibilidad. Como testigo se reportan los horarios no apareados (suficiente para señalar la causa).

El reporte incluye los identificadores de las aulas posibles en el lado derecho del subconjunto violador. Eso es accionable: el operador sabe que esos horarios tienen sólo esas opciones y puede ampliar el inventario de laboratorios o sumar aulas del tipo correcto.

### 6.4 Partición teoría/laboratorio infactible

Para cada comisión `k` con materia `m`, se verifica que existe una bipartición de las duraciones de los horarios de `k` que sume exactamente `hteo[m]` y `hlab[m]` respectivamente. Es un problema de **suma de subconjunto** (en la literatura, *subset-sum*: dado un conjunto de números y un objetivo, decidir si algún subconjunto suma exactamente el objetivo) sobre las duraciones de los horarios libres, respetando los fijados.

Si no existe, ningún cumplimiento de R5 es válido y el modelo es infactible. Causa típica: las horas declaradas en el plan no coinciden con la suma de duraciones cargadas, o los horarios fijados ya exceden uno de los dos.

### 6.5 Subconjunto irreducible infactible (SII) por relajación selectiva

> **Subconjunto irreducible infactible (SII)**: dado un modelo infactible, un subconjunto mínimo de restricciones que, tomadas juntas, ya son infactibles, pero que se vuelve factible si se quita cualquiera de ellas. En la literatura anglosajona se lo llama *Irreducible Infeasible Subset* (IIS). Ofrece un "núcleo del problema" mucho más útil que decir simplemente "el modelo es infactible".

Cuando las cotas anteriores vienen vacías y la pre-validación de partición tampoco detecta nada, pero el resolutor declara infactible, el sistema ejecuta automáticamente un **SII por relajación selectiva**. La idea: relajar **una sola restricción del modelo a la vez** y volver a resolver. La que al ser relajada permite que el modelo resuelva es la **culpable** (o una de las culpables, si la infactibilidad es combinada).

Las tres relajaciones que se prueban:

- **R4** (no doble asignación): si arregla, hay saturación temporal residual que las cotas del palomar / Hall no detectaron.
- **R5** (partición teoría/laboratorio): si arregla, las horas declaradas de alguna materia no admiten partición consistente con las duraciones cargadas.
- **R6** (consistencia tipo↔aula para horarios sin tipo): si arregla, hay un horario sin tipo que no admite ninguna decisión consistente.

#### Falsos positivos por libertad ganada

La relajación independiente sufre de un problema bien conocido: **cuando hay una restricción fuertemente saturadora (típicamente R4: muchos horarios simultáneos vs pocas aulas), relajar R5 o R6 también arregla el modelo** — pero no porque sean la causa real, sino porque le da al resolutor libertad extra que enmascara el problema.

Ejemplo: 50 horarios simultáneos en una franja con 42 aulas teóricas. R4 los limita a 1 por aula → infactible.

- Relajar R4: arregla (causa real).
- Relajar R5: el programa lineal gana libertad de marcar horarios como laboratorio para usar las 8 aulas laboratorio → arregla, pero los `hlab` quedan incoherentes.
- Relajar R6: el programa lineal puede meter horarios teóricos en aulas laboratorio → arregla, pero por motivos no relacionados con horarios sin tipo.

Reportar las tres como culpables confunde al operador.

#### Filtro de falsos positivos

- **R5 → falso positivo si** ninguna materia con `hlab > 0` quedó con desajuste real.
- **R6 → falso positivo si** todos los horarios con tipo libre tienen alguna alternativa válida (al menos un aula teórica o un laboratorio compatible). Si todos tienen alternativa, R6 no puede ser la causa individual.
- **R4 → siempre se considera causa real** cuando arregla.

Si tras filtrar quedan varias culpables, se elige una **causa principal** con regla de prioridad: R4 prevalece sobre R5/R6.

#### Reporte al usuario

El SII devuelve culpables genuinas, una causa principal, y por cada Ri probada un detalle con campos `factible_relajado`, `es_falso_positivo` y `explicación`. La interfaz lo presenta con cuatro niveles visuales: **causa principal** (expandida), **causa secundaria** (expandida), **falso positivo** (colapsado con explicación) y **no es problema individualmente** (colapsado).

Costo: hasta 3× tiempo extra de resolutor. Para una instancia típica de la facultad (~600 horarios, ~50 aulas) el modelo infactible se resuelve en 6-8 s, así que el SII suma ~20 s en el peor caso. Se dispara automáticamente sólo cuando el resolutor declara infactible y todas las cotas estructurales vinieron vacías.

## 7. Notas sobre la implementación

Esta sección documenta cómo el modelo abstracto se conecta con la base de datos del sistema. Es la única parte del documento que hace referencia a las entidades concretas; las secciones anteriores se mantienen abstractas a propósito.

### 7.1 Tecnologías

- **Resolutor**: PuLP + CBC. Suficiente para problemas de cientos a pocos miles de variables binarias. Si CBC no escala, OR-Tools como alternativa.
- **Servicio**: `src/services/asignacion_aulas_service.py`.
- **Integración con la interfaz**: pestaña "Aulas" en la página de Planes (`app/pages/5_📊_Planes.py`).

### 7.2 Mapeo de entidades

| Entidad de la base | Rol en el programa lineal |
|---|---|
| `HorarioDB` (no virtual, comisión del plan activo) | Cada fila es un `h ∈ H`. Su campo `aula_id` es donde el programa lineal escribe el resultado. |
| `AulaDB` | Cada fila es un `a ∈ A`. Aporta `cap[a]`, `tipo[a]`. |
| `MateriaLaboratorioDB` | Define `A_lab(m)` para cada materia. |
| `HorarioDB.tipo_clase` | Aporta `fija_lab(h)`. |
| `ComisionDB` | Cada fila es un `k ∈ K`. Aporta `coef[k]`. |
| `DictadoDB` | Define `D`; agrupa comisiones para R9. |
| `MateriaDB.horas_teoria`, `horas_laboratorio`, `virtual` | Aporta `hteo[m]`, `hlab[m]`; `virtual=True` filtra el horario de `H`. |
| Servicio de pronóstico de inscripción | Resuelve `total_esp[m]`. |
| `ConfiguracionHoraria` | `open_h`, `close_h` para R8. |

### 7.3 Flujo de ejecución

```
1. Pre-condiciones: el plan tiene horarios, hay pronóstico de inscripción
   resuelto para cada materia, la partición teoría/laboratorio es factible y
   la ventana operativa se respeta.

2. El usuario configura parámetros (λ_over, λ_under, tolerancias, opción de
   redistribución α).

3. Botón "Correr LP":
   a) Construye conjuntos y parámetros desde la base.
   b) Pre-computa Sim y compat.
   c) Instancia el modelo en PuLP.
   d) Resuelve con CBC (límite de tiempo configurable).
   e) Si resulta infactible: reporta diagnóstico estructural + SII si aplica.
   f) Si resulta óptimo o subóptimo: persiste HorarioDB.aula_id,
      HorarioDB.tipo_clase y ComisionDB.coef_asignacion (si la opción de
      redistribución está activa), y propaga a las ClaseDB que heredan del
      patrón (ver § 1.3 y RF-PLAN-07).

4. La interfaz muestra el resultado en el panel de aulas del plan.
```

### 7.4 Optimizaciones

- **Pre-filtrar `compat[h, a]`**: además del filtro por tipo (R3), se podría descartar aulas con capacidad insuficiente (`cap[a] · (1 + tol_over) < insc[h]`) cuando `λ_over` es grande. Reduce el modelo.
- **Particionamiento por componentes conexas de `Sim`**: si CBC no escala, partir en sub-problemas independientes.
- **Arranque en caliente con heurística voraz** (en la literatura, *warm start* con heurística *greedy*): una primera asignación heurística (ordenar horarios por inscriptos descendente y elegir el aula compatible más chica que no esté ocupada en esa franja) puede pasarse al resolutor como punto inicial para acelerar la convergencia.

> **Heurística voraz**: estrategia de asignación que toma decisiones locales óptimas sin reconsiderarlas. En este caso: asignar horario por horario, eligiendo en cada paso la mejor aula libre, sin volver atrás. No garantiza el óptimo global pero sí una solución factible rápida.
>
> **Arranque en caliente**: técnica que entrega al resolutor una solución factible inicial para que arranque desde ahí en lugar de construirla desde cero. Acelera la convergencia.

### 7.5 Visualización del resultado

- Tabla por horario con columna `Δ = cap − insc` coloreada (verde/amarillo/rojo según la diferencia respecto a las tolerancias).
- Mapa de calor por franja horaria.
- Resumen agregado: "X horarios sobre-ocupados (total +N alumnos), Y sub-utilizados".
- Lista de candidatos a partir comisión: materias con horarios sobre-ocupados ordenadas por exceso.
- Comparación entre corridas: instantánea de cada corrida persistida en `LPRunDB`.

> **Mapa de calor**: visualización en grilla donde cada celda corresponde a una franja (día × hora) y el color indica la magnitud de un valor (en este caso, la peor diferencia capacidad − inscriptos en esa franja). En la literatura anglosajona, *heatmap*.
>
> **Instantánea**: copia inmutable del estado de la corrida (parámetros + resultado) usada para auditoría y comparación. En la literatura, *snapshot*.

## 8. Cuestiones abiertas

- **Estabilidad entre re-corridas**: si el operador cambia algo menor, ¿se preferirían asignaciones similares a la anterior? Considerar un término del objetivo que penalice cambios respecto a la corrida previa.
- **Disponibilidad parcial de aulas**: hoy no se modelan reservas externas (exámenes, eventos). Una tabla `AulaIndisponibleDB` permitiría descartar pares `(h, a)` específicos en franjas concretas.
- **Ventanas por sede o por aula**: hoy todas las aulas comparten la ventana global. Si en el futuro hay sedes con horarios distintos (nocturnos, fin de semana), agregar atributos por sede o por aula.
- **Término de continuidad de aula entre horarios consecutivos de una comisión**: idea descartada por ahora, ver § 8.1.

### 8.1 Por qué descartamos la "continuidad de aula"

Una idea natural sería minimizar la cantidad de veces que una comisión cambia de aula entre sus horarios semanales. Se modela con una variable binaria adicional `cambio[k, i]` que vale 1 cuando el horario `i` y el `i+1` de la comisión `k` (ordenados por algún criterio) están en aulas distintas, sumando un término `λ_cambio · Σ cambio` al objetivo.

El término asume que cada comisión es una **cohorte estable**: un grupo de alumnos que se mueve junto entre sus distintas materias. Eso se cumple razonablemente para comisiones de **materias específicas de carrera** en años avanzados (cuarto año primer cuatrimestre tiende a cursar todo en bloque). Pero en el **ciclo básico** las comisiones agrupan estudiantes que después se dispersan a comisiones distintas en sus otras materias. Una comisión de Análisis Matemático I no es una cohorte: es una sub-población heterogénea de alumnos de varias carreras y orientaciones. Forzar al optimizador a "minimizar movimiento" para esa comisión privilegia arbitrariamente a una sub-cohorte a costa del resto.

Si el modelo de datos incorporara explícitamente el concepto de **itinerario de alumno** o **comisión-cohorte**, tendría sentido reactivar este término aplicado sólo a esas comisiones. Hoy ese concepto no existe en la base, por lo que el término queda registrado como extensión potencial y fuera del alcance de la implementación.

## 9. Referencias

- Documentación de modelado del dominio: `modelo-planificacion-cursada.md`.
- Pronóstico de inscripción: `../0. Planteo/plan-de-cursada.md` § 5.5.
- Flujo general del sistema: `../2. Desarrollo/WORKFLOW.md`.
- Implementación detallada con tecnologías y endpoints: `../2. Desarrollo/ASIGNACION_IMPL.md`.
- Inventario de requerimientos: `../requerimientos.md` (RF-LP-01 a RF-LP-10, RF-PLAN-07).
- Nemhauser & Wolsey, *Integer and Combinatorial Optimization*, capítulo III.6 — "Polyhedra of the Set Packing Problem".
