# Programa Lineal de Asignación de Aulas

> **Estado**: Planteo formal cerrado. Implementación pendiente.
> **Última actualización**: 2026-06-03
> **Sesiones siguientes**: codear `src/services/asignacion_aulas_service.py` (PuLP+CBC), tab UI "Asignar Aulas" en `5_📊_Planes.py`, fixtures de test, visualización de resultado.
>
> **Vínculos**:
> - Decisión de "un único LP": [modelo-planificacion-cursada.md § 9](modelo-planificacion-cursada.md)
> - Forecasting (insumo del parámetro `insc[c]`): [plan-de-cursada.md § 5.5](../0.%20Planteo/plan-de-cursada.md)
> - Workflow general: [WORKFLOW.md § 13](../2.%20Desarrollo/WORKFLOW.md)
> - Planteo simplificado del compañero ICR (cuadrático con ventanas): `~/Downloads/planteo programa lineal.docx`

## TL;DR

Una vez generadas todas las `ClaseDB` de un plan activado (instancias concretas con fecha), queda decidir a qué `AulaDB` va cada una. Esa decisión se modela como un **programa lineal entero (ILP)** con tres familias de variables:

1. `x[c, a] ∈ {0,1}`: la clase `c` se asigna al aula `a`.
2. `t[c] ∈ {0,1}`: la clase `c` es de laboratorio (`1`) o de teoría (`0`). Constante cuando viene fijado desde el cronograma; variable cuando no.
3. `α[k] ∈ [0,1]` (opcional, toggle del usuario): coeficiente de asignación de la comisión `k` dentro de su dictado.

El **objetivo** es lineal y asimétrico: minimizar la sobre-ocupación con peso `λ_over` (default `10`) y la sub-ocupación con peso `λ_under` (default `1`). Las **restricciones** garantizan asignación única, no doble booking, compatibilidad de tipo aula↔clase, partición teoría/lab por comisión y consistencia de los coeficientes cuando el toggle está activo.

## 1. Contexto y motivación

### 1.1 Qué decisión cubre el LP

Tras activar un plan se generan las clases concretas (`ClaseDB`) del cuatrimestre, una por cada combinación `(HorarioDB, fecha)` válida. El LP decide:

- **A qué aula va cada clase** no virtual (`ClaseDB.aula_id`).
- **De qué tipo es cada clase** cuando el cronograma no lo predetermina (`ClaseDB.tipo_clase`, vía la variable `t[c]`).
- **Cómo se reparten los inscriptos esperados** entre comisiones del mismo dictado, **opcionalmente**, si el usuario activa el toggle "permitir reasignar pesos" (`ComisionDB.coef_asignacion`, vía la variable `α[k]`).

### 1.2 Por qué un único LP, no un pipeline secuencial

La justificación completa está en [`modelo-planificacion-cursada.md` § 9](modelo-planificacion-cursada.md). En síntesis: el tipo de aula que admite cada clase depende de su `tipo_clase`, y el `tipo_clase` (cuando no está fijado) afecta qué pool de aulas es elegible. Resolver primero el tipo y después el aula garantiza factibilidad local pero no optimalidad global, y puede arrojar infactibilidad evitable cuando los labs están saturados en una franja específica. Un único modelo combinado encuentra el óptimo del problema acoplado o demuestra infactibilidad de manera definitiva.

## 2. Alcance

### 2.1 Lo que el LP decide

- `x[c, a]`: una variable binaria por cada par `(clase, aula)` compatible.
- `t[c]`: una variable binaria por clase cuyo `HorarioDB.tipo_clase` sea `None`. Si el horario fija el tipo, `t[c]` se reduce a constante.
- `α[k]`: una variable continua por comisión, sólo si el toggle "permitir reasignar pesos" está activo. Default OFF.

### 2.2 Lo que el LP NO toca

- **No crea ni elimina comisiones**. Toma el plan tal cual viene de **Planes → Detalle**. Si el resultado es infactible o malo, el usuario ajusta comisiones desde la UI (subir `n_comisiones`, mover horarios, redistribuir pesos) y vuelve a correr el LP.
- **No reescribe horarios** (`HorarioDB`).
- **Excluye clases virtuales**: si `MateriaDB.virtual = True` o `DictadoDB.virtual = True`, la clase no consume aula y se filtra del conjunto `C` antes de armar el modelo.
- **Excluye reservas ad-hoc de laboratorio**: las materias con `horas_laboratorio = 0` que tienen labs compatibles (`MateriaLaboratorioDB`) reciben aula teórica como cualquier otra clase. La reserva puntual de un lab para una clase específica es una operación del flujo de implementación, no del plan inicial.
- **Excluye clases ya `executed`**: una clase con `executed = True` representa una sesión que ya ocurrió y no se re-asigna.

### 2.3 Supuestos

1. **Inscriptos constantes por comisión**: `insc[c]` es el mismo para todas las clases (teoría y laboratorio) de la comisión a la que pertenece `c`. Esto refleja el modelo actual donde el `coef_asignacion` reparte el total de inscriptos esperados de la materia entre comisiones.
2. **Disponibilidad horaria full**: cada aula está disponible durante toda la ventana operativa global (`ConfiguracionHoraria`). No se modelan reservas externas (exámenes, eventos) — queda como extensión futura (`AulaIndisponibleDB`).
3. **Una corrida por ciclo**: el LP no resuelve cross-ciclo. Si hay dos ciclos activos (ej. 1C y 2C en simultáneo para anuales), cada uno tiene su corrida independiente.

## 3. Planteo matemático formal

### 3.1 Índices y conjuntos

| Símbolo | Definición |
|---|---|
| `C` | Conjunto de clases no virtuales y no ejecutadas del plan. Cada `c ∈ C` se obtiene de `ClaseDB`. |
| `A` | Conjunto de aulas (`AulaDB`). |
| `A_t ⊆ A` | Aulas con `tipo = "teorica"` (incluye anfiteatros y similares). |
| `A_lab(m) ⊆ A` | Aulas listadas en `MateriaLaboratorioDB` para la materia `m`. |
| `K` | Conjunto de comisiones del plan (`ComisionDB`). |
| `D` | Conjunto de dictados del ciclo (`DictadoDB`). Cada `k ∈ K` pertenece a exactamente un `d ∈ D`. |
| `comision(c)`, `materia(c)`, `dictado(c)` | Funciones derivadas de la denormalización de `ClaseDB`. |
| `fija_lab(c) ∈ {True, False, None}` | `HorarioDB.tipo_clase` de la clase. `True` = laboratorio fijado, `False` = teoría fijada, `None` = sin determinar. |
| `Sim` | Conjunto de **grupos de simultaneidad**. Cada `S ∈ Sim` es un subconjunto maximal de clases `S ⊆ C` que comparten al menos un instante en común (todas dictándose a la vez en algún momento). Se obtiene barriendo los eventos de `hora_inicio` y `hora_fin` por fecha (ver § 3.5 R4). |

### 3.2 Parámetros

| Símbolo | Tipo | Significado |
|---|---|---|
| `cap[a]` | `ℤ⁺` | Capacidad del aula `a`. |
| `total_esp[m]` | `ℝ⁺` | Inscriptos esperados de la materia `m`. Se obtiene del `forecast_service` (override manual o forecast histórico). |
| `coef[k]` | `[0,1]` | `ComisionDB.coef_asignacion`. Input del modelo cuando `activar_α = 0`. |
| `insc[c]` | `ℝ⁺` | Inscriptos esperados de la clase `c`. Cuando `activar_α = 0`: `insc[c] = total_esp[materia(c)] · coef[comision(c)]`. Cuando `activar_α = 1`: pasa a expresión lineal en `α[k]` (ver R9). |
| `dur[c]` | `ℝ⁺` | Duración de la clase en horas: `c.hora_fin − c.hora_inicio`. |
| `hteo[m]`, `hlab[m]` | `ℝ⁺` | Horas semanales de teoría y de laboratorio de la materia (`MateriaDB.horas_teoria`, `horas_laboratorio`). |
| `compat[c, a]` | `{0,1}` | Pre-computado: `1` si el aula `a` puede recibir a la clase `c` dado su tipo. Ver § 3.5 (R3). |
| `open_h`, `close_h` | `time` | Ventana operativa global (`ConfiguracionHoraria.hora_inicio_operativo`, `hora_fin_operativo`). |
| `λ_over` | `ℝ⁺` | Peso del penalty por sobre-ocupación. **Default = 10**. |
| `λ_under` | `ℝ⁺` | Peso del penalty por sub-ocupación. **Default = 1**. |
| `tol_over` | `[0,1]` | Tolerancia relativa de sobre-ocupación sin penalty. **Default = 0**. |
| `tol_under` | `[0,1]` | Tolerancia relativa de sub-ocupación sin penalty. **Default = 0.20**. |
| `activar_α` | `{0,1}` | Toggle del usuario para permitir que el LP redistribuya `coef_asignacion`. **Default = 0**. |

### 3.3 Variables de decisión

| Variable | Tipo | Cuándo existe | Significado |
|---|---|---|---|
| `x[c, a]` | binaria | `∀(c, a)` con `compat[c, a] = 1` | `1` si la clase `c` se asigna al aula `a`. |
| `t[c]` | binaria | `∀c` con `fija_lab(c) = None` | `1` si la clase es laboratorio, `0` si es teoría. Cuando `fija_lab(c)` está fijado, `t[c]` es la constante correspondiente. |
| `α[k]` | continua en `[α_min, α_max]` | `∀k ∈ K` si `activar_α = 1` | Coeficiente de asignación de la comisión. **Default `α_min = 0`, `α_max = 1`**. |
| `over[c]` | continua, `≥ 0` | `∀c ∈ C` | Sobre-ocupación de la clase respecto a la capacidad efectiva del aula asignada. |
| `under[c]` | continua, `≥ 0` | `∀c ∈ C` | Sub-ocupación de la clase. |

### 3.4 Función objetivo

```
min   λ_over · Σ_c over[c]   +   λ_under · Σ_c under[c]
```

El default `(λ_over = 10, λ_under = 1)` modela una preferencia asimétrica: la sobre-ocupación (alumnos sin lugar) se penaliza diez veces más que la sub-ocupación (lugares vacíos). Ambos pesos son configurables por el usuario.

> **Nota de diseño**: el planteo del compañero (`~/Downloads/planteo programa lineal.docx`) propone `Σ (cap − insc)²`, una forma cuadrática simétrica que requiere un solver MIQP (Gurobi, OR-Tools CP-SAT con linealización piecewise) y no admite tolerancias asimétricas naturalmente. El planteo lineal asimétrico cubre el mismo intento práctico (clases grandes → aulas grandes) y se resuelve con CBC vía PuLP. Queda como extensión la versión cuadrática.

### 3.5 Restricciones

#### R1 — Asignación única

Cada clase no virtual recibe exactamente un aula:

```
Σ_a x[c, a] = 1     ∀ c ∈ C
```

Las clases virtuales se filtran de `C` antes de construir el modelo (no aparecen en R1 ni en ninguna otra restricción).

#### R2 — Virtuales no consumen aula

Si una clase `c` proviene de un dictado virtual, se excluye de `C`. Equivale a:

```
x[c, a] = 0     ∀ a ∈ A,  ∀ c con virtual(c) = 1
```

En la práctica el filtro se aplica al construir el conjunto `C`, no como restricción explícita del LP.

#### R3 — Compatibilidad pre-computada

Para cada par `(c, a)` se calcula `compat[c, a] ∈ {0, 1}` antes de construir el modelo. Las variables `x[c, a]` con `compat = 0` no se crean (equivalente a fijarlas en cero).

```
compat[c, a] = 1   sii   alguno de:
   (a)  fija_lab(c) = False  ∧  tipo[a] ∈ {teorica}
   (b)  fija_lab(c) = True   ∧  a ∈ A_lab(materia(c))
   (c)  fija_lab(c) = None
```

Cuando `fija_lab(c) = None` la decisión queda librada a `t[c]`, y se usa R6 para forzar la consistencia entre `t[c]` y el aula elegida.

#### R4 — Un aula recibe a lo sumo una clase en cada instante

Para cada aula y cada **grupo de simultaneidad** (conjunto maximal de clases que se dictan a la vez en algún momento), a lo sumo una de ellas puede asignarse al aula:

```
Σ_{c ∈ S} x[c, a] ≤ 1     ∀ a ∈ A,  ∀ S ∈ Sim
```

**Qué es un grupo de simultaneidad**. Si tres clases `c1, c2, c3` están todas activas a las 18:30 de un mismo lunes (porque sus intervalos `[hora_inicio, hora_fin)` cubren ese instante), forman un grupo de simultaneidad. La restricción para un aula `a` dada dice: "de esas tres clases, a lo sumo una puede usar `a`". El conjunto `Sim` es la unión de todos esos grupos a lo largo del ciclo.

**Cómputo de `Sim`** (barrido de eventos por fecha):

```
para cada fecha f del ciclo:
    eventos = sorted unión de (c.hora_inicio, c.hora_fin) sobre clases de f
    activas = {}
    para cada instante e en eventos:
        antes de procesar e:
            si activas no está vacía y no es subconjunto de un grupo ya emitido:
                emitir grupo S = activas (es maximal en este intervalo)
        si e es un hora_inicio: activas.add(c)
        si e es un hora_fin:    activas.remove(c)
```

Esta formulación (un grupo de simultaneidad por aula) en lugar de la pairwise (un par solapado por aula) es **más compacta** y **más fuerte en la relajación LP** del solver. La justificación detallada está en § 4.5.

> **Equivalencia con la versión pairwise**: cualquier par `(c1, c2)` de clases que se solapan pertenece a algún grupo `S` (porque comparten al menos un instante), por lo que la pairwise queda implicada. La diferencia es de eficiencia computacional, no de semántica.

#### R5 — Partición teoría/lab por comisión

Para cada comisión `k`, la suma de duraciones de sus clases de laboratorio debe igualar `hlab[materia(k)]`, y la suma de las teóricas debe igualar `hteo[materia(k)]`:

```
Σ_{c ∈ k} dur[c] · t[c]       = hlab[materia(k)]    ∀ k ∈ K
Σ_{c ∈ k} dur[c] · (1 − t[c]) = hteo[materia(k)]    ∀ k ∈ K
```

Equivalentemente, basta con una de las dos ecuaciones más la suma total: `Σ_c dur[c] = hteo + hlab` por construcción del cronograma.

> **Pre-validación previa al LP**: antes de correr el modelo se verifica que existe al menos una partición factible de las clases de cada comisión cuyas duraciones sumen `hteo` y `hlab` (subset-sum). Si no existe, el LP es infactible por R5 y el usuario lo ve antes de gastar tiempo de solver.

#### R6 — Pool de aulas para tipo decidido

Cuando `fija_lab(c) = None`, el aula elegida tiene que ser consistente con el valor de `t[c]`:

```
Σ_{a ∈ A_t}            x[c, a] ≥ 1 − t[c]    si  fija_lab(c) = None
Σ_{a ∈ A_lab(materia(c))} x[c, a] ≥ t[c]      si  fija_lab(c) = None
```

Junto con R1 (`Σ_a x[c, a] = 1`), esto fuerza que cuando `t[c] = 0` la clase vaya a un aula teórica, y cuando `t[c] = 1` vaya a un lab compatible.

#### R7 — Penalty de capacidad (linealización del objetivo)

```
over[c]  ≥ insc[c] − Σ_a x[c, a] · cap[a] · (1 + tol_over)        ∀ c ∈ C
under[c] ≥ Σ_a x[c, a] · cap[a] · (1 − tol_under) − insc[c]       ∀ c ∈ C
over[c],  under[c] ≥ 0
```

No hay restricción dura `cap[a] ≥ insc[c]`: la sobre-ocupación se castiga vía `λ_over`. Si el usuario quiere capacidad como hard constraint, basta con setear `λ_over = ∞` (o un número muy grande relativo al rango de under).

#### R8 — Ventana operativa global (defensiva)

```
hora_inicio(c) ≥ open_h   ∧   hora_fin(c) ≤ close_h     ∀ c ∈ C
```

Esta restricción se chequea como **pre-condición** antes de armar el LP. Si alguna clase cae fuera de la ventana, el LP se aborta con un error explícito y el usuario tiene que corregir el cronograma o ampliar `ConfiguracionHoraria`. No se modela como restricción del LP porque el cronograma ya fue validado en pasos previos.

> **Extensión futura**: ventanas por sede (`SedeDB.hora_apertura`, `hora_cierre`) o ventanas por aula. Hoy todas las aulas comparten la misma ventana global.

#### R9 — Coef de asignación (sólo si `activar_α = 1`)

```
Σ_{k ∈ d} α[k] = 1               ∀ d ∈ D
α_min ≤ α[k] ≤ α_max              ∀ k ∈ K
insc[c] = total_esp[materia(k)] · α[k]     ∀ c con comision(c) = k
```

`insc[c]` deja de ser parámetro y pasa a ser una expresión lineal en `α[k]`. Las restricciones R7 se reescriben sustituyendo. El producto `α[k] · cap[a]` no aparece en el modelo (R7 multiplica `cap[a]` por `x[c, a]`, no por `α[k]`), por lo que la formulación se mantiene lineal.

### 3.6 Datos de entrada (inputs del solver)

Se obtienen de la base antes de instanciar el modelo:

| Input | Origen |
|---|---|
| Conjunto `C` | `ClaseDB` filtrando `executed=False`, `dictado.virtual=False`, `materia.virtual=False`. |
| Conjunto `A` | `AulaDB`. |
| `cap[a]`, `tipo[a]` | `AulaDB.capacidad`, `AulaDB.tipo`. |
| `A_lab(m)` | `MateriaLaboratorioDB.aula_id` por `materia_codigo`. |
| Conjunto `K`, `D` | `ComisionDB`, `DictadoDB`. |
| `total_esp[m]` | `forecast_service.get_forecast_for_materia(plan_id, materia, cuatri).valor`. Resuelve override manual y forecast histórico. |
| `coef[k]` | `ComisionDB.coef_asignacion`. |
| `dur[c]` | Calculado de `ClaseDB.hora_inicio`, `hora_fin`. |
| `hteo[m]`, `hlab[m]` | `MateriaDB.horas_teoria`, `horas_laboratorio`. |
| `fija_lab(c)` | `HorarioDB.tipo_clase` de la clase (vía `ClaseDB.horario_id`). |
| `Sim` | Calculado offline agrupando clases por `(plan_id, fecha)` y barriendo eventos `hora_inicio` / `hora_fin`. Cada grupo de simultaneidad maximal genera una restricción R4 por aula. |
| `compat[c, a]` | Calculado offline aplicando R3. |
| `open_h`, `close_h` | `ConfiguracionHoraria.hora_inicio_operativo`, `hora_fin_operativo`. |
| `λ_over`, `λ_under`, `tol_over`, `tol_under`, `activar_α` | UI de configuración del LP. Persistido en `LPConfiguracionDB` (a definir) o extendiendo `ConfiguracionHoraria`. |

### 3.7 Output

Persiste en la base:

| Campo | Origen LP |
|---|---|
| `ClaseDB.aula_id` | `x[c, a]* = 1` ⇒ `aula_id = a` |
| `ClaseDB.tipo_clase` | `t[c]*` cuando `fija_lab(c) = None` (`0 → "teorica"`, `1 → "laboratorio"`). Si `fija_lab(c) ≠ None`, no se modifica. |
| `ComisionDB.coef_asignacion` | `α[k]*` sólo si `activar_α = 1` y el usuario confirma persistir. |

No se persisten (recomputables a partir de la asignación):

- `over[c]`, `under[c]` por clase.
- Métrica `gap[c] = cap[a] − insc[c]` con `a` la aula asignada.
- Buckets verde / amarillo / rojo según `gap` y `tol_*`.

## 4. Casos particulares de la función objetivo

| Configuración | Comportamiento |
|---|---|
| `λ_over = +∞`, `λ_under = 0` | Capacidad como hard constraint. Si no hay solución factible, infactibilidad reportada. |
| `λ_over = λ_under`, `tol_over = tol_under = 0` | Penalty simétrico tipo `\|cap − insc\|`. |
| `λ_over = 10`, `λ_under = 1`, `tol_under = 0.2` (default) | Asimétrico: castigo fuerte a sobre-ocupación, sub-ocupación tolerada hasta 20%. |
| `λ_under = 0`, `tol_under = 1.0` | Sólo importa no sobre-asignar (cualquier sub-ocupación es gratis). |

## 4.5 Análisis: por qué la formulación por grupos de simultaneidad mejora sobre la pairwise

Esta sección expande el comentario que aparece junto a R4 en § 3.5. La elección de cómo escribir la restricción de no doble booking es una decisión de diseño no obvia y con impacto directo en la performance del solver, así que vale la pena desarrollarla.

### 4.5.1 Las dos formulaciones equivalentes

**Formulación pairwise** (la primera que uno tiende a escribir): para cada par `(c1, c2)` de clases que se solapan temporalmente, una restricción por aula:

```
x[c1, a] + x[c2, a] ≤ 1     ∀ a ∈ A,  ∀ (c1, c2) ∈ Conf
```

**Formulación por grupos de simultaneidad** (la elegida): para cada grupo maximal `S` de clases que están todas activas en algún instante común, una sola restricción por aula:

```
Σ_{c ∈ S} x[c, a] ≤ 1     ∀ a ∈ A,  ∀ S ∈ Sim
```

Sobre variables enteras `x ∈ {0, 1}`, ambas describen exactamente el mismo conjunto factible: en ningún caso un aula puede dictar dos clases simultáneas. La diferencia se ve en otro lado.

### 4.5.2 Diferencia conceptual: cantidad de restricciones

Sea `S` un grupo de tamaño `n` (n clases activas a la vez). La pairwise genera C(n, 2) = n(n−1)/2 restricciones para ese grupo (una por cada par). La formulación por grupos genera **una sola**.

En horarios universitarios reales, donde varias clases tienden a coincidir en franjas como "lunes de 18 a 20" o "miércoles de 8 a 10", esos grupos pueden tener fácilmente 10 a 30 clases simultáneas. Con `n = 20`, la pairwise produce 190 restricciones por aula contra 1 de la formulación por grupos. Multiplicado por la cantidad de aulas y de grupos a lo largo del ciclo, la diferencia en tamaño del modelo es sustancial.

### 4.5.3 Diferencia clave: fuerza de la relajación lineal

Este es el punto central, y el que justifica el cambio aún más allá del ahorro en cantidad de restricciones.

Los solvers de programación entera mixta (CBC, Gurobi, CPLEX) resuelven internamente una sucesión de **relajaciones lineales**, en las que las variables `x[c, a] ∈ {0, 1}` se reemplazan por `x[c, a] ∈ [0, 1]`. La relajación devuelve una cota inferior del óptimo entero; cuanto más ajustada la cota, más rápido converge el branch-and-bound porque hay que explorar menos sub-problemas.

Una formulación es **más fuerte** que otra cuando su poliedro de soluciones fraccionarias está estrictamente contenido en el de la otra. Las soluciones enteras coinciden, pero la formulación más fuerte recorta puntos fraccionarios que la otra admite.

**Ejemplo con tres clases simultáneas**. Sean `c1, c2, c3` activas todas en un mismo instante (forman un grupo de tamaño 3) y consideremos una sola aula `a`:

- **Pairwise**: tres restricciones, `x[c1, a] + x[c2, a] ≤ 1`, `x[c1, a] + x[c3, a] ≤ 1`, `x[c2, a] + x[c3, a] ≤ 1`. La solución fraccionaria `x[c1, a] = x[c2, a] = x[c3, a] = 1/2` satisface las tres (cada par suma 1) y es factible para la relajación.
- **Por grupos**: una sola restricción, `x[c1, a] + x[c2, a] + x[c3, a] ≤ 1`. La misma solución fraccionaria suma `3/2 > 1` y queda **excluida** de la relajación.

Esa solución fraccionaria de la pairwise representa "asignar media clase a cada una", que sobre enteros corresponde a "elegir una de las tres con probabilidad uniforme". El solver, al pasar por relajaciones que la admiten, gasta esfuerzo de branching para descartarla. La formulación por grupos corta ese punto antes de que el branch-and-bound tenga que recorrerlo.

En el caso general con `n` clases en un grupo, la pairwise admite la solución fraccionaria `x[c, a] = 1/(n−1)` para cada `c` (cada par suma `2/(n−1) ≤ 1`), mientras que la formulación por grupos la rechaza apenas `n ≥ 2`. El gap entre la relajación y el óptimo entero crece con `n`, y la formulación por grupos lo cierra de un saque.

### 4.5.4 Conexión con la teoría de poliedros enteros

Las restricciones del tipo "a lo sumo una de un conjunto de variables binarias vale 1" se llaman **restricciones de set packing**. Cuando el conjunto corresponde a un grupo maximal de clases simultáneas, la desigualdad es una **faceta** del poliedro entero asociado (ver Nemhauser & Wolsey, *Integer and Combinatorial Optimization*, capítulo III.6, "Polyhedra of the Set Packing Problem"). Las facetas son las desigualdades más fuertes posibles para describir el poliedro entero: no se las puede ajustar más sin recortar soluciones enteras válidas.

Las desigualdades pairwise, en cambio, son **dominadas** por las desigualdades por grupos cuando varias se combinan. Sumando las `n(n−1)/2` desigualdades pairwise se obtiene `(n−1) · Σ x_c ≤ n(n−1)/2`, equivalente a `Σ x_c ≤ n/2`, que es estrictamente más débil que `Σ x_c ≤ 1` para `n ≥ 3`.

Esta es la razón teórica por la cual los modelos de scheduling con conflictos sobre un recurso compartido (aulas, máquinas, frecuencias) usan formulaciones por grupos siempre que sea razonable enumerarlos.

### 4.5.5 Costo de obtener los grupos

La objeción natural es: "obtener grupos maximales en un grafo arbitrario es NP-hard". Es cierto en general, pero en nuestro caso el grafo es **de intervalos** (cada clase es un intervalo en una recta de tiempo por fecha), y los grafos de intervalos tienen una estructura especial: los grupos maximales se obtienen en tiempo lineal con un barrido de eventos `hora_inicio` y `hora_fin`. Cada vez que se abre un nuevo intervalo, las clases activas en ese momento forman un grupo maximal candidato; cada vez que se cierra, se reevalúa.

El algoritmo concreto está en el cuerpo de R4 (§ 3.5). Su complejidad es O(N log N) por fecha (dominada por el sort de eventos), donde `N` es la cantidad de clases de esa fecha. Para un ciclo típico con decenas de clases por día, el cómputo total se mide en milisegundos.

### 4.5.6 Resumen del beneficio

| Aspecto | Pairwise | Por grupos de simultaneidad |
|---|---|---|
| Cantidad de restricciones para un grupo de `n` clases | `n(n−1)/2` por aula | `1` por aula |
| Soluciones fraccionarias `x = 1/(n−1)` admitidas | sí | no (rechazadas para `n ≥ 2`) |
| Cota inferior de la relajación | más floja | más ajustada |
| Branching del solver | más costoso | más liviano |
| Status teórico | desigualdades dominadas | facetas del poliedro de set packing |
| Costo de cómputo offline | trivial (enumerar pares solapados) | O(N log N) por fecha (sweep de eventos) |
| Costo a runtime del LP | mayor (modelo más grande, relajación más débil) | menor |

La conclusión: la formulación por grupos de simultaneidad no es una optimización menor; es la formulación canónica del problema de scheduling con conflictos sobre un recurso compartido. Para un informe técnico o una defensa académica, el contraste entre ambas formulaciones ilustra concretamente la diferencia entre **modelar correctamente** (la pairwise lo hace) y **modelar para que el solver pueda aprovecharlo** (la formulación por grupos).

## 4.6 El LP en limpio

Esta sección compila la formulación final en una sola vista, con conteo explícito de cuántas restricciones y variables genera cada bloque sobre el modelo real. El propósito es doble: dejar el modelo legible de un vistazo y dimensionar el problema antes de pasarlo al solver.

### 4.6.1 Tamaños de los conjuntos (notación)

Para contar restricciones necesitamos nombres cortos para los tamaños:

| Símbolo | Significado |
|---|---|
| `\|C\|` | cantidad de clases no virtuales y no ejecutadas |
| `\|A\|` | cantidad de aulas |
| `\|K\|` | cantidad de comisiones del plan |
| `\|D\|` | cantidad de dictados del ciclo |
| `\|Sim\|` | cantidad de grupos de simultaneidad maximales |
| `\|C_∅\|` | cantidad de clases con `fija_lab(c) = None` |
| `\|C_∅(k)\|` | cantidad de clases de la comisión `k` con `fija_lab(c) = None` |
| `\|compat\|` | cantidad total de pares `(c, a)` con `compat[c, a] = 1` |

### 4.6.2 Variables del modelo

| Variable | Tipo | Cantidad | Notas |
|---|---|---|---|
| `x[c, a]` | binaria | `\|compat\|` | Una por cada par `(c, a)` que pasa el filtro de compatibilidad de § 3.5 R3. Las que no pasan no se crean (equivalente a `x = 0`). |
| `t[c]` | binaria | `\|C_∅\|` | Una por cada clase con tipo no fijado en el cronograma. Si `fija_lab(c) ∈ {True, False}`, `t[c]` es constante y no entra al modelo. |
| `α[k]` | continua en `[0, 1]` | `\|K\|` (sólo si `activar_α = 1`) | Una por comisión. Cuando el toggle está OFF, `α[k] = coef[k]` (constante). |
| `over[c]` | continua, `≥ 0` | `\|C\|` | Una por clase. |
| `under[c]` | continua, `≥ 0` | `\|C\|` | Una por clase. |

**Total de variables (toggle α OFF, caso por defecto)**: `\|compat\| + \|C_∅\| + 2·\|C\|` variables, de las cuales `\|compat\| + \|C_∅\|` son binarias.

### 4.6.3 Función objetivo

```
minimizar    λ_over · Σ_{c ∈ C} over[c]   +   λ_under · Σ_{c ∈ C} under[c]
```

Defaults: `λ_over = 10`, `λ_under = 1`, `tol_over = 0`, `tol_under = 0.20`.

### 4.6.4 Restricciones (vista compacta con conteo)

| ID | Forma | Cantidad de líneas en el LP | Para qué sirve |
|---|---|---|---|
| R1 | `Σ_{a : compat[c,a]=1} x[c, a] = 1` para cada `c ∈ C` | `\|C\|` | Cada clase no virtual recibe exactamente un aula. |
| R3' | (no se materializa como restricción explícita) | `0` | La compatibilidad se aplica filtrando el dominio de `x` antes de instanciar el modelo. |
| R4 | `Σ_{c ∈ S} x[c, a] ≤ 1` para cada `a ∈ A` y cada `S ∈ Sim` | `\|A\| · \|Sim\|` | Un aula no puede dictar dos clases al mismo tiempo. **Una restricción por cada aula y cada grupo de simultaneidad** — sí, exactamente como dijiste: por cada aula, una línea por cada grupo de clases que se solapan en algún instante. |
| R5a | `Σ_{c ∈ k} dur[c] · t[c] = hlab[materia(k)]` para cada `k ∈ K` | `\|K\|` | La suma de horas de laboratorio de la comisión iguala lo declarado en la materia. |
| R5b | `Σ_{c ∈ k} dur[c] · (1 − t[c]) = hteo[materia(k)]` para cada `k ∈ K` | `\|K\|` | Análogo para teoría. (Redundante con R5a + suma total, pero explícito para claridad del solver.) |
| R6a | `Σ_{a ∈ A_t} x[c, a] ≥ 1 − t[c]` para cada `c` con `fija_lab(c) = None` | `\|C_∅\|` | Si `t[c] = 0`, la clase va a aula teórica. |
| R6b | `Σ_{a ∈ A_lab(materia(c))} x[c, a] ≥ t[c]` para cada `c` con `fija_lab(c) = None` | `\|C_∅\|` | Si `t[c] = 1`, la clase va a un lab compatible. |
| R7a | `over[c] ≥ insc[c] − Σ_{a} x[c, a] · cap[a] · (1 + tol_over)` para cada `c ∈ C` | `\|C\|` | Linealiza la sobre-ocupación. |
| R7b | `under[c] ≥ Σ_{a} x[c, a] · cap[a] · (1 − tol_under) − insc[c]` para cada `c ∈ C` | `\|C\|` | Linealiza la sub-ocupación. |
| R8 | (pre-condición, no parte del LP) | `0` | Se verifica antes de armar el modelo; aborta si falla. |
| R9a | `Σ_{k ∈ d} α[k] = 1` para cada `d ∈ D` (sólo si `activar_α = 1`) | `\|D\|` (toggle ON) o `0` (toggle OFF) | Suma de pesos por dictado. |

**Total de restricciones (toggle α OFF, caso por defecto)**:

```
\|C\|              (R1)
+ \|A\| · \|Sim\|   (R4)         ← término dominante
+ 2 · \|K\|        (R5a + R5b)
+ 2 · \|C_∅\|      (R6a + R6b)
+ 2 · \|C\|        (R7a + R7b)
```

`\|A\| · \|Sim\|` suele ser el término que más pesa. Para dimensionar: con `\|A\| ~ 50` aulas y `\|Sim\| ~ 200` grupos de simultaneidad por ciclo, R4 aporta del orden de 10.000 restricciones (a comparar con ~700.000 que daría la formulación pairwise sobre los mismos grupos si tuvieran tamaño promedio 10 — ver § 4.5.2).

### 4.6.5 El LP en una sola vista

Reuniendo todo:

```
Variables:
    x[c, a] ∈ {0, 1}        ∀ (c, a) con compat[c, a] = 1
    t[c]    ∈ {0, 1}        ∀ c ∈ C con fija_lab(c) = None
    α[k]    ∈ [0, 1]        ∀ k ∈ K   (sólo si activar_α = 1)
    over[c]  ≥ 0            ∀ c ∈ C
    under[c] ≥ 0            ∀ c ∈ C

Objetivo:
    minimizar
        λ_over · Σ_{c ∈ C} over[c]
      + λ_under · Σ_{c ∈ C} under[c]

Sujeto a:
    R1   Σ_{a} x[c, a] = 1                                     ∀ c ∈ C

    R4   Σ_{c ∈ S} x[c, a] ≤ 1                                  ∀ a ∈ A, ∀ S ∈ Sim

    R5a  Σ_{c ∈ k} dur[c] · t[c]       = hlab[materia(k)]       ∀ k ∈ K
    R5b  Σ_{c ∈ k} dur[c] · (1 − t[c]) = hteo[materia(k)]       ∀ k ∈ K

    R6a  Σ_{a ∈ A_t}            x[c, a] ≥ 1 − t[c]              ∀ c con fija_lab(c) = None
    R6b  Σ_{a ∈ A_lab(materia(c))} x[c, a] ≥ t[c]               ∀ c con fija_lab(c) = None

    R7a  over[c]  ≥ insc[c] − Σ_{a} x[c, a] · cap[a] · (1 + tol_over)     ∀ c ∈ C
    R7b  under[c] ≥ Σ_{a} x[c, a] · cap[a] · (1 − tol_under) − insc[c]    ∀ c ∈ C

    R9   Σ_{k ∈ d} α[k] = 1                                     ∀ d ∈ D     (si activar_α = 1)
         insc[c] = total_esp[materia(k)] · α[k]                 ∀ c con comision(c) = k

Pre-condiciones (verificadas antes de instanciar el LP):
    - factibilidad de partición teoría/lab por comisión (subset-sum)
    - hora_inicio(c) ≥ open_h ∧ hora_fin(c) ≤ close_h           ∀ c ∈ C    (R8)
```

### 4.6.6 Lectura rápida del LP

- **R1**: una línea por clase. "Cada clase tiene una sola aula".
- **R4**: una línea por par (aula, grupo de simultaneidad). "Un aula, un grupo, a lo sumo una clase ahí".
- **R5**: dos líneas por comisión. "Las horas de teoría y de laboratorio de la materia se distribuyen entre las clases de la comisión".
- **R6**: dos líneas por clase con tipo no fijado. "Si decidiste que la clase es teoría, va a aula teórica; si decidiste que es lab, a lab compatible".
- **R7**: dos líneas por clase. "Penalizá la sobre-ocupación y la sub-ocupación según las tolerancias".
- **R9** (opcional): una línea por dictado más una sustitución por clase. "Si te dejo redistribuir pesos, que sumen 1 dentro de cada dictado".



### Idea general

Un objetivo natural sería minimizar la cantidad de veces que una comisión cambia de aula entre clases consecutivas, por ejemplo entre las clases del lunes y del miércoles de la misma comisión. La forma estándar de modelarlo es con una variable binaria adicional `swap[k, i] ∈ {0, 1}` que vale `1` cuando la `i`-ésima y la `(i+1)`-ésima clase de la comisión `k` (ordenadas por fecha) están en aulas distintas, linealizada como:

```
x[c_i, a]      − x[c_{i+1}, a]      ≤ swap[k, i]    ∀ a, ∀ k, ∀ i
x[c_{i+1}, a]  − x[c_i, a]          ≤ swap[k, i]    ∀ a, ∀ k, ∀ i
```

Y agregar `λ_swap · Σ_k Σ_i swap[k, i]` al objetivo.

### Por qué NO se implementa

El término asume que cada comisión es una **cohorte estable**: un grupo de alumnos que se mueve junto entre sus diferentes materias. Esa hipótesis se cumple razonablemente para comisiones de **materias específicas de carrera** en años avanzados (por ejemplo, los alumnos de cuarto año primer cuatrimestre de una orientación tienden a cursar todo en bloque).

Sin embargo, en el **ciclo básico** las comisiones agrupan estudiantes que después se dispersan a comisiones distintas en sus otras materias. Una comisión de Análisis Matemático I no es una cohorte: es una sub-población heterogénea de alumnos de varias carreras y orientaciones. Forzar al optimizador a "minimizar movimiento" para esa comisión privilegia arbitrariamente a una sub-cohorte de sus estudiantes a costa del resto.

### En qué caso se justificaría incorporarlo

Si el modelo de datos incorporara explícitamente el concepto de **itinerario de alumno** o **comisión-cohorte** (un grupo identificable que cursa varias materias juntas), tendría sentido reactivar este término del objetivo aplicado sólo a esas comisiones-cohorte. Hoy ese concepto no existe en la base, por lo que el término queda registrado como extensión potencial y fuera del alcance de la implementación.

## 5. Sección específica de implementación

### 5.1 Stack

| Componente | Decisión |
|---|---|
| Solver | **PuLP + CBC** (default del sistema, suficiente para problemas de cientos a pocos miles de variables binarias). OR-Tools como alternativa si CBC no escala. |
| Servicio | `src/services/asignacion_aulas_service.py` (a crear). |
| Persistencia de configuración | Extender `ConfiguracionHoraria` con campos del LP, o crear `LPConfiguracionDB` por plan. Decisión menor, se cierra en la sesión de implementación. |
| Integración UI | Tab nuevo "Asignar Aulas" en `app/pages/5_📊_Planes.py`. |

### 5.2 Mapeo de entidades a elementos del modelo

| Entidad de la base | Rol en el LP |
|---|---|
| `ClaseDB` (no virtual, no executed) | Cada fila es un `c ∈ C`. |
| `AulaDB` | Cada fila es un `a ∈ A`. Aporta `cap[a]`, `tipo[a]`. |
| `MateriaLaboratorioDB` | Define `A_lab(m)` para cada materia. |
| `HorarioDB.tipo_clase` | `fija_lab(c)` de la clase. |
| `ComisionDB` | Cada fila es un `k ∈ K`. Aporta `coef[k]` (input o variable según toggle). |
| `DictadoDB` | Define `D`; agrupa comisiones para R9. |
| `MateriaDB.horas_teoria`, `horas_laboratorio`, `virtual` | Aporta `hteo[m]`, `hlab[m]`; `virtual=True` filtra clases de `C`. |
| `forecast_service.get_forecast_for_materia` | Resuelve `total_esp[m]` (override manual o forecast histórico). |
| `MateriaDB.optativa` | **No afecta al LP**: se asigna como cualquier otra materia. |
| `ConfiguracionHoraria` | `open_h`, `close_h` para R8 (defensivo). |

### 5.3 Pipeline de ejecución

```
1. Usuario abre Planes → Asignar Aulas (tab nuevo).

2. Pre-checks (si fallan, se aborta con mensaje claro):
   a) Existe un plan activo en el ciclo seleccionado.
   b) El plan tiene clases generadas (ClaseDB).
   c) Para cada materia del plan hay forecast resuelto (override manual o
      histórico no vacío).
   d) Para cada comisión k existe partición teoría/lab factible
      (subset-sum sobre dur[c] iguala hteo[m] + hlab[m]).
   e) Todas las clases caen dentro de la ventana operativa global (R8).

3. Usuario configura parámetros:
   - λ_over, λ_under (numeric inputs).
   - tol_over, tol_under (sliders).
   - Toggle activar_α (si ON, expone α_min / α_max).

4. Botón "Correr LP" dispara asignacion_aulas_service.run_lp(plan_id, config):
   a) Construye conjuntos y parámetros desde la DB (5.2).
   b) Pre-computa Conf y compat.
   c) Instancia el modelo PuLP.
   d) Resuelve con CBC (timeout configurable, default 5 minutos).
   e) Si infactible: reporta diagnóstico (qué restricción rompió, ejemplo
      de slot saturado) y aborta sin tocar la DB.
   f) Si óptimo o subóptimo: persiste aula_id, tipo_clase y α (si toggle).

5. UI muestra resultado:
   - Tabla por clase con Δ = cap − insc coloreada (verde / amarillo / rojo).
   - Heatmap por slot horario.
   - Resumen agregado (X clases sobre-ocupadas, Y sub-utilizadas).
   - Sugerencias de candidatas a "agregar comisión" (materias con clases
     sobre-ocupadas).

6. Si el resultado no satisface, el usuario edita comisiones desde
   Planes → Detalle y vuelve al paso 4.
```

### 5.4 Optimizaciones de tamaño

- **Pre-filtrar el dominio `compat[c, a]`**: además del filtro por tipo (R3), descartar aulas con `cap[a] · (1 + tol_over) < insc[c]` salvo que `λ_over` sea finito y chico (esos casos serían parte de las soluciones malas pero factibles). Reduce dramáticamente las binarias.
- **Particionamiento natural por slot**: R4 sólo conecta clases que se solapan temporalmente. El grafo de conflicto suele estar fragmentado por días o por franjas horarias. Si CBC no escala, partir el LP en sub-problemas independientes (un sub-problema por componente conexa de `Sim`).
- **Warm-start con heurística greedy**: una primera asignación heurística (ordenar clases por `insc[c]` decreciente y elegir el aula compatible más chica que no esté ocupada en ese slot) puede pasarse a CBC como punto inicial y acelerar la convergencia.

### 5.5 Visualización del resultado

Es **clave para iterar**. Cuando el LP devuelve un plan no ideal, el usuario necesita ver dónde está el problema para decidir si ajusta comisiones o relaja parámetros.

- **Tabla por clase** con columna `Δ` coloreada (verde / amarillo / rojo según gap vs tolerancias).
- **Heatmap por slot horario**: filas = slots `(día, franja)`, color según el peor `Δ` en ese slot.
- **Resumen agregado**: "X clases sobre-ocupadas (total +N alumnos), Y sub-utilizadas (total −M lugares)".
- **Lista de candidatas a partir comisión**: materias con clases sobre-ocupadas ordenadas por exceso, con sugerencia de subir `n_comisiones` o redistribuir `coef_asignacion`.
- **Comparación entre corridas**: persistir el snapshot del LP run (parámetros + resultado) en una tabla `LPRunDB` para auditar y comparar configuraciones.

### 5.6 Testing

Fixtures mínimas para `tests/test_asignacion_aulas_service.py`:

| Fixture | Setup | Resultado esperado |
|---|---|---|
| Mínimo | 3 clases sin solapamiento, 3 aulas de cap distinta, 1 comisión, sin labs. | Cada clase asignada al aula que minimiza `over+under`. |
| Lab fijado | 1 comisión con `hlab=2`, 2 clases. Una clase con `fija_lab=True`, un lab compatible disponible. | La clase fijada va al lab; la otra a teórica. |
| Lab decidido | Misma comisión, ambas clases con `fija_lab=None`. `hlab=2`, `hteo=2`. Cada clase dura 2 horas. | El LP elige una como lab y la otra como teoría (cualquiera de las dos); R5 se cumple. |
| Conflicto temporal | 2 clases mismo slot, 1 sola aula. | Infactible — error explícito. |
| Sobre-ocupación | 1 clase `insc=100`, aulas `cap=80` y `cap=60`. | Asigna `cap=80`; `over[c] = 20`. |
| Toggle α | 2 comisiones del mismo dictado, `total_esp=120`, aulas `cap=60` y `cap=60`. `coef=[1.0, 0.0]` inicial. Toggle ON. | `α* = [0.5, 0.5]`, `over` baja respecto a la corrida con `α* = coef`. |

## 6. Cuestiones abiertas

- **Solver definitivo**: CBC vs OR-Tools, decisión post-benchmark con datos reales.
- **Estabilidad entre re-corridas**: si el usuario cambia algo menor, ¿queremos asignaciones similares a la anterior? Considerar un término de objetivo que penalice cambios respecto a la corrida previa (warm-start sirve, pero no fuerza estabilidad).
- **Disponibilidad parcial de aulas**: hoy no se modelan reservas externas. Una tabla `AulaIndisponibleDB` con `(aula_id, fecha, hora_inicio, hora_fin)` permitiría descartar pares `(c, a)` específicos del dominio.
- **Ventanas por sede**: `ConfiguracionHoraria` es global. Si en el futuro hay sedes con ventanas distintas (ej. una sede con horario nocturno), agregar `hora_apertura`, `hora_cierre` a `SedeDB` o un modelo por aula.
- **Persistencia de configuraciones**: ¿`LPConfiguracionDB` o extensión de `ConfiguracionHoraria`? Decisión menor, se cierra en la sesión de implementación.

## 7. Referencias

- [`modelo-planificacion-cursada.md`](modelo-planificacion-cursada.md) § 9 — decisión de "un único LP" y acoplamiento entre tipo, aula y partición.
- [`plan-de-cursada.md`](../0.%20Planteo/plan-de-cursada.md) § 5.5 — forecasting y semántica de `total_esp[m]`.
- [`WORKFLOW.md`](../2.%20Desarrollo/WORKFLOW.md) § 13 — sketch original que este documento formaliza.
- Planteo cuadrático simple del compañero ICR: `~/Downloads/planteo programa lineal.docx`. Cubre asignación única, no superposición, capacidad y ventana horaria, pero no contempla tipo aula, virtuales ni partición teoría/lab.
