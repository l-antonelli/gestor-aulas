# Programa Lineal de Asignación de Aulas

> **Estado**: modelo formalizado y en producción. Este documento es la **referencia técnica** del planteo matemático — cubre conjuntos, variables, función objetivo, restricciones, chequeo estructural pre-solve y diagnóstico por relajación selectiva. Para la **guía operativa** (cómo se usa desde la UI, qué significan los parámetros, cómo interpretar cada mensaje del veredicto), ver `project/2. Desarrollo/asignador_guia_operativa.md`.
>
> **Última actualización**: 2026-09-11.

## Glosario

Antes de entrar al planteo, fijamos los términos técnicos que aparecen a lo largo del documento. La idea es que un lector que no sea especialista pueda seguirlo sin adivinar significados. Los términos que originalmente vienen en inglés se introducen en castellano con el original entre paréntesis la primera vez.

| Término | Definición |
|---|---|
| **Programación lineal entera** (*integer linear programming*, PLE) | Familia de problemas de optimización donde se busca minimizar (o maximizar) una función lineal sujeta a restricciones lineales, con algunas o todas las variables obligadas a tomar valores enteros. Es una de las herramientas más antiguas y estudiadas de la investigación operativa; existen resolutores libres y comerciales altamente optimizados. |
| **Programa lineal** | Cada instancia concreta de un problema de programación lineal entera. En este documento se usa indistintamente "programa lineal", "modelo" o "problema". |
| **Resolutor** (*solver*) | Programa informático que recibe un programa lineal y devuelve la solución óptima o un certificado de infactibilidad. Ejemplos: CBC (libre, la que usa este proyecto), Gurobi y CPLEX (comerciales). |
| **Variable de decisión** | Las incógnitas del modelo cuyos valores el resolutor decide. En este planteo son binarias (0 o 1) y continuas (reales no negativas). |
| **Función objetivo** | La expresión lineal que el resolutor minimiza. |
| **Restricción** | Igualdad o desigualdad lineal que toda solución factible debe satisfacer. |
| **Factible** | Cualquier asignación de valores a las variables que cumple **todas** las restricciones. |
| **Óptimo** | La solución factible que minimiza la función objetivo. |
| **Infactible** | Estado del modelo cuando no existe ninguna asignación que cumpla todas las restricciones simultáneamente. |
| **Relajación lineal** | Versión "ablandada" del programa lineal entero en la que las variables binarias se reemplazan por variables continuas en `[0, 1]`. La resuelve el resolutor internamente para obtener cotas y guiar la búsqueda. |
| **Ramificación y acotación** (*branch-and-bound*) | Algoritmo estándar para resolver programas lineales enteros. Recursivamente parte el problema en subproblemas (ramifica) y descarta los que no pueden contener al óptimo (acota). |
| **Patrón semanal** | El conjunto de horarios (materia / comisión / día / hora de inicio / hora de fin) que se repite todas las semanas del cuatrimestre. Es el sujeto sobre el que decide el programa lineal. Cada patrón corresponde a un registro `HorarioDB`. |
| **Clase puntual** | Una instancia concreta del patrón en una fecha específica (por ejemplo, "lunes 22 de marzo, 14 a 18 hs"). Hereda el aula del patrón salvo *override* manual del operador. En el schema es un registro `ClaseDB`. |
| **Sobre-ocupación** | Cantidad de inscriptos esperados que excede la capacidad efectiva del aula asignada. |
| **Sub-ocupación** | Cantidad de lugares vacíos en el aula asignada respecto a un umbral mínimo de aprovechamiento. |
| **Ventana operativa** | Rango horario en el que la facultad opera. Por defecto de 7 a 23 hs, configurable en `ConfiguracionHoraria`. Ningún horario puede caer fuera. |
| **Doble asignación** (*double booking*) | Situación prohibida en la que un mismo aula recibe dos horarios que se dictan al mismo tiempo. |
| **Modalidad virtual** | Horario que se dicta en forma remota o asincrónica. No consume aula. Cuando la restricción R5 está en modo estricto, entra al modelo pero sin ocupar aula (contribuye al balance de horas teoría/lab); cuando no, se filtra completamente. |
| **Restricción dura** vs **restricción blanda** | Una restricción dura no admite violación: o se cumple o el modelo es infactible. Una restricción blanda admite violación pero la castiga con un peso en la función objetivo. En este modelo, capacidad (sobre-ocupación y sub-ocupación) es blanda; el resto son duras salvo que se indique. |
| **Grupo de materias** | Entidad del dominio (`GrupoMateriaDB`) que agrupa materias que comparten el mismo criterio de sedes admisibles. Cada materia pertenece a exactamente un grupo (partición estricta). Cada grupo declara dos configuraciones simultáneas: un **set duro** de sedes admisibles cuando corre en modo DURO, y una **lista blanda ordenada** de sedes preferidas cuando corre en modo BLANDO. El modo se elige por-grupo al momento de correr el asignador. |
| **Camino de cursada** | Chequeo estructural que verifica que, para cada terna `(carrera, año, cuatrimestre)`, exista al menos una combinación de comisiones — una por materia obligatoria — que un alumno pueda cursar sin conflictos horarios ni de traslado entre sedes. |
| **Grupo de simultaneidad** | Conjunto maximal de horarios activos en un mismo instante del cuatrimestre. Se calcula analizando la grilla semanal y sirve para modelar la restricción de doble asignación de aula (R4) sin necesidad de comparar todos los pares de horarios. |
| **Sedes admisibles por horario** | Conjunto de sedes en las que un horario particular puede ser asignado. Se resuelve consultando el grupo de la materia del horario y el modo elegido en la corrida (DURO o BLANDO). En modo BLANDO todas las sedes son admisibles pero la primera de la lista es preferida (paga cero al objetivo); las alternativas suman un costo `λ_sede_pref` por cada horario que caiga en ellas. En modo DURO sólo las sedes del set duro son admisibles; la lista vacía se interpreta como *fallback* permisivo. |
| **Excepción de conflicto ignorado** | Registro en `IgnoredConflictDB` que marca un par de materias como no bloqueante para el chequeo de camino de cursada. Se usa cuando en la práctica una comisión de la materia A y una de la materia B nunca son cursadas por el mismo alumno (por ejemplo, materias homónimas de distintos años del plan). |
| **IIS** (*Irreducible Infeasible Subsystem*) | Subconjunto mínimo de restricciones cuya interacción produce la infactibilidad. En este proyecto no computamos el IIS teórico exacto sino un **diagnóstico por relajación selectiva**: se relaja cada restricción "candidata" por separado y se re-corre el modelo para ver cuál rescata la solución. Cuando ninguna funciona, se prueban combinaciones de a pares. |

## Resumen ejecutivo

Una vez cerrada la grilla horaria de un cuatrimestre —es decir, definidos los `HorarioDB` que se van a dictar y a qué comisión pertenecen—, queda un problema combinatorio: **a qué aula va cada uno de esos horarios semanales**. Lo modelamos como un programa lineal entero y lo resolvemos con CBC accedido desde Python a través de la biblioteca PuLP.

El programa lineal decide tres cosas simultáneamente:

1. **El aula de cada horario presencial** (variables `x[h, a] ∈ {0, 1}`, una por cada par horario-aula compatible).
2. **El tipo de cada horario** cuando el cronograma no lo predetermina (variables `t[h] ∈ {0, 1}`: 1 = laboratorio, 0 = teoría).
3. **Cómo se reparten los inscriptos esperados entre las comisiones de un mismo dictado**, opcionalmente (variables `α[k] ∈ [0, 1]` sólo activas si el usuario tilda "redistribuir pesos entre comisiones").

El **objetivo** es lineal y asimétrico: minimizar la sobre-ocupación con peso `λ_over` (default 10), la sub-ocupación con peso `λ_under` (default 1) y la asignación a una sede alternativa —cuando el grupo corre en modo BLANDO— con peso `λ_sede_pref` (default 5). Todos los pesos son configurables desde la UI.

Las **restricciones duras** garantizan asignación única, ausencia de doble asignación, compatibilidad del tipo del aula con la clase, balance correcto entre horas de teoría y de laboratorio declaradas por la materia, filtro por sedes admisibles según el grupo de la materia (R10), continuidad de sede para pares de horarios contiguos en riesgo intersede (R13), y opcionalmente misma sede para todos los horarios de una comisión (R14).

Antes de correr el resolutor se ejecuta un **chequeo estructural pre-solve** que detecta situaciones que garantizan infactibilidad sin necesidad de encender el modelo entero. Si el solver da infactible pese al chequeo, se corre un **diagnóstico por relajación selectiva** que identifica qué restricciones son las culpables. Ambos mecanismos están descriptos en detalle en las secciones §7 y §8.

## 1. Contexto y motivación

### 1.1 De qué problema estamos hablando

En una facultad mediana hay típicamente **algunos cientos de horarios semanales** (cada combinación materia-comisión-día-franja es uno) y **algunas decenas de aulas**, repartidas entre teóricas, anfiteatros y laboratorios de distintos tipos. Cada cuatrimestre alguien tiene que decidir, para cada horario, qué aula le toca.

A simple vista parece un problema de "encajar piezas". Pero cuando se mira con detalle aparecen varias complicaciones que lo vuelven no trivial:

- **Conflictos temporales**. Dos horarios que se dictan a la misma hora del mismo día no pueden compartir aula.
- **Tipo de aula vs tipo de clase**. Una clase de laboratorio no puede dictarse en cualquier aula: depende del laboratorio compatible con esa materia (el de Química requiere mecheros, el de Electrónica requiere instrumental, etcétera).
- **Capacidad vs cantidad de inscriptos**. Si una comisión tiene 80 inscriptos esperados y se la manda a un aula de 30, hay sobre-ocupación; al revés, si va al anfiteatro de 200, hay sub-utilización.
- **Distribución en sedes**. FCEIA-UNR opera en más de una sede (Pellegrini, Siberia, etc.), pero no todas las materias pueden dictarse en todas las sedes: hay preferencias curriculares y compatibilidades de laboratorio. Además, los alumnos y los profesores no pueden trasladarse instantáneamente entre sedes.
- **Balance teoría/laboratorio**. Hay materias donde el plan declara horas de teoría y horas de laboratorio por separado, pero los horarios cargados por el cronograma no siempre tienen esa partición resuelta. El asignador debe decidir simultáneamente qué horarios son teoría, cuáles son laboratorio y a qué aula van.
- **Camino de cursada**. Aunque una comisión individual sea factible, un alumno concreto de una carrera-año-cuatrimestre necesita que exista al menos una combinación de comisiones (una por materia obligatoria) que le permita cursar todo sin solapamientos horarios ni traslados imposibles.

### 1.2 Por qué programación lineal entera

La programación lineal entera es una de las herramientas canónicas de la investigación operativa (ver Winston [1], Hillier & Lieberman [2]) para modelizar problemas de asignación combinatoria con restricciones estructuradas. Su atractivo para este proyecto es doble:

- **Expresividad**. Restricciones como "un aula no puede recibir dos clases simultáneas" o "las horas de laboratorio de una materia deben cerrar exactamente con las declaradas" son lineales con variables binarias. No necesitamos salir del marco lineal.
- **Herramientas maduras**. Existen resolutores libres (CBC, GLPK, HiGHS) capaces de resolver instancias de este tamaño en segundos. Delegar la búsqueda combinatoria a un resolutor bien optimizado permite concentrar el esfuerzo en el planteo del modelo, no en el algoritmo.

Alternativas consideradas y descartadas:

- **Programación por restricciones** (*constraint programming*). Más flexible para restricciones no lineales, pero acá no las necesitamos y perderíamos el ecosistema maduro de resolutores enteros.
- **Metaheurísticas** (búsqueda local, algoritmos genéticos). Escalan mejor a instancias enormes, pero no garantizan óptimo ni certifican infactibilidad. Para el tamaño de FCEIA-UNR, el óptimo exacto es alcanzable.
- **Encadenamiento de etapas** ("primero decido el tipo, después le busco aula"). Falla porque tipo y aula están acoplados: si decidimos teoría/laboratorio de antemano y después no hay laboratorios disponibles en cierta franja, llegamos a infactibilidad evitable.

### 1.3 Trabajo exclusivamente sobre el patrón semanal

El programa lineal trabaja exclusivamente sobre el **patrón semanal**: la franja que se repite todas las semanas del cuatrimestre. Por ejemplo: "Análisis Matemático I, Comisión A, lunes de 14 a 18 hs". Asigna un aula a cada patrón; esa asignación aplica a todas las instancias del ciclo.

En versiones tempranas del sistema el usuario podía además editar excepciones a nivel de "clase puntual" (`ClaseDB`): un día específico podía cambiar de aula sin afectar al patrón. Esa capacidad se deprecó porque agregaba complejidad sin uso operativo real. Hoy el usuario solo edita el patrón semanal; `ClaseDB` sigue existiendo en el modelo como *cache* técnico que las clases heredan al aplicar la solución.

Trabajar sobre el patrón mantiene el programa lineal chico: un cuatrimestre típico tiene ~600 horarios pero ~10000 clases puntuales; resolver por patrón es un orden de magnitud menos.

## 2. Alcance

### 2.1 Qué decide el programa lineal

- A qué **aula** va cada horario presencial del cuatrimestre.
- De qué **tipo** es cada horario cuando el cronograma no lo predetermina (con restricción R5 estricta activa, que es el default).
- Cómo se **distribuyen los inscriptos esperados** entre comisiones de un mismo dictado (sólo si el usuario activa la opción "permitir reasignar pesos").

### 2.2 Qué NO toca el programa lineal

- **No crea ni elimina comisiones**. Las comisiones llegan ya definidas desde el panel de planificación.
- **No reescribe horarios**. Los días, horas y duraciones son datos de entrada fijos.
- **No asigna aulas a horarios virtuales**. Los horarios que resuelven a virtuales por la cadena `horario > dictado > materia` se filtran del modelo o entran con la marca `no_ocupa_aula`, según el modo de R5.
- **No decide reservas puntuales de laboratorio**. La reserva se hace a nivel patrón: si un horario semanal debe dictarse en un laboratorio, se marca su `tipo_clase` y el programa lineal le asigna un aula de laboratorio.
- **No considera horarios ya ejecutados**. Si la corrida es a mitad del cuatrimestre, las clases con `fecha < fecha_desde` quedan intactas.

### 2.3 Supuestos modelados

1. **Inscriptos constantes por comisión**: el número de inscriptos esperados es el mismo para todos los horarios de una comisión. Refleja que la matrícula es por comisión, no por franja.
2. **Aulas siempre disponibles**: cada aula está disponible toda la ventana operativa. No se modelan indisponibilidades por exámenes, eventos, refacciones, etc.
3. **Una corrida por ciclo**: dos cuatrimestres distintos se resuelven en corridas separadas, aun cuando haya materias anuales que abarquen ambos.
4. **Excepción de laboratorio prevalece sobre restricción de sede**: si un aula está en la lista de laboratorios compatibles de una materia (`MateriaLaboratorioDB`), se acepta para esa materia aunque no esté en el set de sedes admisibles del grupo. Refleja que la compatibilidad física del laboratorio es más restrictiva que la preferencia curricular.

## 3. Planteo matemático formal

### 3.1 Conjuntos

Todos los conjuntos se computan una sola vez al inicio de la corrida, dentro de `build_inputs` en `src/services/asignacion_aulas_service.py`.

| Símbolo | Descripción | Origen |
|---|---|---|
| `H` | Conjunto de horarios semanales activos del plan de cursada. Se excluyen los virtuales cuando R5 no es estricta; con R5 estricta los virtuales entran a `H` pero se marcan en `H_∅ ⊆ H` como *no ocupan aula*. | `HorarioDB` filtrado por `PlanificacionCursadaDB.id` y resuelto vía `resolve_virtual`. |
| `H_∅` | Subconjunto de `H` que no ocupa aula física (horarios virtuales bajo R5 estricta). Participa en R5 pero se excluye de R1, R3, R4, R7, R10, R12, R13, R14. | Se calcula al iterar `HorarioDB` en `build_inputs`. |
| `A` | Conjunto de aulas del catálogo. Cada aula tiene tipo (`teorica`, `anfiteatro`, `laboratorio`), capacidad y sede. | `AulaDB`. |
| `A_teo ⊆ A` | Aulas de tipo `teorica` o `anfiteatro`. | Derivado. |
| `A_lab ⊆ A` | Aulas de tipo `laboratorio`. | Derivado. |
| `A_lab(m) ⊆ A_lab` | Laboratorios compatibles con la materia `m`. La lista la mantiene manualmente el operador. | `MateriaLaboratorioDB`. |
| `C` | Conjunto de comisiones activas en el plan. | `ComisionDB` filtrado por `plan_cursada_id`. |
| `H(c) ⊆ H` | Horarios de la comisión `c`. | Derivado. |
| `M` | Conjunto de materias que aparecen en el plan. | Derivado de `HorarioDB.codigo_materia`. |
| `S` | Conjunto de sedes. | `SedeDB`. |
| `sede(a) ∈ S` | Sede física del aula `a`. | `AulaDB.sede_id`. |
| `G` | Conjunto de grupos de materias. | `GrupoMateriaDB`. |
| `grupo(m) ∈ G` | Grupo al que pertenece la materia `m` (partición estricta). | `MateriaDB.grupo_id`. |
| `S_D(g) ⊆ S` | Set duro de sedes del grupo `g`: las únicas admisibles cuando el grupo corre en modo DURO. | `GrupoMateriaSedeDB` con `tipo=DURO`. |
| `S_B(g)` (lista ordenada) | Lista blanda ordenada de sedes preferidas del grupo `g`. La primera es la preferida (paga cero al objetivo); el resto son alternativas con costo `λ_sede_pref`. | `GrupoMateriaSedeDB` con `tipo=BLANDO` ordenado por `orden`. |
| `modo(g) ∈ {DURO, BLANDO}` | Modo con el que se corre el grupo `g` en esta corrida. Se elige en el panel del asignador. | `LPConfig.modos_por_grupo` (default DURO). |
| `Sim` | Conjunto de **grupos de simultaneidad maximales**: subconjuntos `S ⊆ H \ H_∅` tales que existe un instante de la semana en el que todos los horarios de `S` están activos y no puede agregarse ningún horario más manteniendo esa propiedad. | Computado por `compute_simultaneidad_groups` sobre la grilla semanal. |
| `P_R13` | Conjunto de pares `(h1, h2)` de horarios contiguos el mismo día con gap menor a `margen_min_intersede_minutos`. Incluye pares de la misma comisión (traslado del docente) y pares de distintas materias del mismo grupo curricular `(carrera, año, cuatri)` (traslado del alumno). | Computado por `compute_pares_intersede_riesgo`. |
| `K` | Conjunto de dictados que agrupan más de una comisión (con `α` activo). | Derivado de `ComisionDB.dictado_id`. |

### 3.2 Parámetros

| Símbolo | Descripción | Fuente |
|---|---|---|
| `dur(h)` | Duración del horario `h` en horas. | `HorarioDB.hora_fin - HorarioDB.hora_inicio`. |
| `cap(a)` | Capacidad del aula `a`. | `AulaDB.capacidad`. |
| `tipo(h) ∈ {teorica, laboratorio, ⊥}` | Tipo declarado del horario `h`. `⊥` significa que el cronograma no lo predeterminó y el modelo lo decide vía R6. | `HorarioDB.tipo_clase`. |
| `tipo(a) ∈ {teorica, anfiteatro, laboratorio}` | Tipo del aula. | `AulaDB.tipo`. |
| `insc(h)` | Inscriptos esperados en `h`. Se propaga desde el forecast de la comisión (con o sin `α[k]`). | `get_inscriptos_esperados_por_comision`. |
| `hteo(m)` | Horas semanales de teoría declaradas por la materia `m`. | `MateriaDB.horas_teoria`. |
| `hlab(m)` | Horas semanales de laboratorio declaradas por la materia `m`. | `MateriaDB.horas_laboratorio`. |
| `sedes_adm(h) ⊆ S` | Conjunto efectivo de sedes admisibles para el horario `h`, resuelto por `grupo(materia(h))` y `modo(grupo)`. **En modo DURO**: `S_D(g)` si no está vacío, todas las sedes si lo está (*fallback* permisivo). **En modo BLANDO**: todas las sedes son admisibles (sin filtro por R10; el sesgo hacia la preferida vive en R12). | Ver §5.2. |
| `sede_pref(h) ∈ S ∪ {⊥}` | Sede preferida para `h`. En modo BLANDO con `S_B(g)` no vacía, es la primera de la lista. En cualquier otro caso, `⊥` (no aplica R12). | `sede_preferida_por_horario` en `build_inputs`. |
| `pin(h) ∈ A ∪ {⊥}` | Aula fijada manualmente por el operador si `HorarioDB.aula_asignada_manualmente=True`. `⊥` si no hay pin. Sólo se propaga a R11 cuando `respetar_ediciones_manuales=True`. | `HorarioDB.aula_id`, `aula_asignada_manualmente`. |
| `tol_over ∈ [0, 1]` | Fracción de la capacidad que la sobre-ocupación puede exceder sin penalidad. Default 0. | `LPConfig.tol_over`. |
| `tol_under ∈ [0, 1]` | Fracción de la capacidad que la sub-ocupación puede tener sin penalidad. Default 0.20. | `LPConfig.tol_under`. |
| `λ_over` | Peso de la sobre-ocupación en el objetivo. Default 10. | `LPConfig.lambda_over`. |
| `λ_under` | Peso de la sub-ocupación en el objetivo. Default 1. | `LPConfig.lambda_under`. |
| `λ_sede_pref` | Peso del término blando de preferencia de sede (R12). Aplica sólo a horarios cuyo grupo corre en modo BLANDO. Default 5. | `LPConfig.lambda_sede_pref`. |
| `λ_intersede` | Peso del término blando de intersede (variante blanda de R13, hoy no activa por default). Default 0. | `LPConfig.lambda_intersede`. |
| `margen_min_intersede_minutos` | Umbral en minutos para considerar dos horarios contiguos "en riesgo" de traslado imposible. Default 30. Con 0 se desactiva R13. | `LPConfig.margen_min_intersede_minutos`. |
| `forzar_misma_sede_por_comision ∈ {False, True}` | Toggle que activa R14 (todos los horarios de una comisión en la misma sede). | `LPConfig.forzar_misma_sede_por_comision`. |
| `strict_r5 ∈ {False, True}` | Modo de R5. Con `True` (default) valida horas de teoría y de laboratorio y admite virtuales al modelo con marca `no_ocupa_aula`. Con `False` (legacy) sólo valida laboratorio y filtra virtuales. | `LPConfig.strict_r5`. |
| `respetar_ediciones_manuales ∈ {False, True}` | Si `True`, los pins manuales se aplican como restricciones duras R11. Default `True`. | `LPConfig.respetar_ediciones_manuales`. |
| `activar_alpha ∈ {False, True}` | Si `True`, se agregan las variables `α[k]` que redistribuyen inscriptos entre comisiones del mismo dictado. Default `False`. | `LPConfig.activar_alpha`. |

### 3.3 Variables de decisión

| Variable | Dominio | Semántica |
|---|---|---|
| `x[h, a]` | `{0, 1}`, para cada `h ∈ H \ H_∅` y `a ∈ A` con `compat(h, a) = 1` | Toma valor 1 si el horario `h` se asigna al aula `a`. La compatibilidad `compat` se pre-computa aplicando R3 y R10 antes de instanciar las variables (así se reduce el tamaño del modelo). |
| `t[h]` | `{0, 1}`, para cada `h ∈ H` con `tipo(h) = ⊥` | Toma valor 1 si `h` se resuelve como laboratorio, 0 si se resuelve como teoría. Sólo se instancia para horarios con tipo indefinido. Si `tipo(h) ≠ ⊥`, `t[h]` se fija por R6. |
| `y[c, s]` | `{0, 1}`, para cada `c ∈ C` con más de un horario y `s ∈ S`, sólo si `forzar_misma_sede_por_comision=True` | Toma valor 1 si la comisión `c` cae en la sede `s`. Se usa para R14. |
| `over[h]` | `ℝ_{≥0}`, para cada `h ∈ H \ H_∅` | Sobre-ocupación del horario `h`: unidades de inscriptos que exceden `cap(aula(h)) · (1 + tol_over)`. |
| `under[h]` | `ℝ_{≥0}`, para cada `h ∈ H \ H_∅` | Sub-ocupación del horario `h`: unidades de asientos vacíos respecto al umbral `cap(aula(h)) · (1 − tol_under)`. |
| `α[k]` | `ℝ ∈ [0, 1]`, para cada `k ∈ K` con `activar_alpha=True` | Fracción de inscriptos del dictado que va a la comisión `k`. |

### 3.4 Función objetivo

$$
\min_{x, t, y, over, under, \alpha} \quad
\lambda_{\text{over}} \sum_{h \in H \setminus H_\emptyset} \text{over}[h]
\;+\;
\lambda_{\text{under}} \sum_{h \in H \setminus H_\emptyset} \text{under}[h]
\;+\;
\lambda_{\text{sede\_pref}} \sum_{h \in H_{\text{BLANDO}}}
\sum_{\substack{a \in A \\ \text{sede}(a) \neq \text{sede\_pref}(h)}}
x[h, a]
$$

donde `H_BLANDO = {h ∈ H \ H_∅ : sede_pref(h) ≠ ⊥}` son los horarios cuyo grupo corre en modo BLANDO con lista blanda no vacía.

El término asimétrico entre `λ_over` y `λ_under` refleja que sobre-ocupación es un problema físico (los alumnos no entran al aula) mientras que sub-ocupación es un problema económico (aula grande desaprovechada). Los defaults `λ_over = 10 · λ_under` codifican esa jerarquía.

El término de preferencia de sede sólo tiene efecto cuando el grupo del horario corre en modo BLANDO. En modo DURO no aparece porque la restricción R10 hace que sólo las sedes del set duro sean admisibles, y todas se consideran equivalentes al objetivo.

### 3.5 Salida del programa lineal

- **Asignación de aulas**: `x_assignments[h] = a` para cada `h ∈ H \ H_∅` (excluye virtuales).
- **Resolución de tipo**: `tipo_resuelto[h] = teorica | laboratorio` para cada `h ∈ H` con `tipo(h) = ⊥`.
- **Diagnóstico de sobre/sub-ocupación**: `over[h]`, `under[h]` para cada horario asignado.
- **Redistribución de coeficientes** (opcional): `α[k]` para cada `k ∈ K`.
- **Status**: `optimal`, `infeasible`, `timeout` o `error`. En caso de `infeasible`, se dispara el diagnóstico por relajación selectiva descripto en §8.

## 4. Restricciones

Cada restricción se identifica con un código (R1, R3, ..., R14, R13-camino). Se describen a continuación en orden de aplicación. Cada una lleva:

- **Motivación** en un párrafo.
- **Formulación matemática** rigurosa.
- **Detalles de implementación** (dónde vive en el código, cómo se puede relajar en el IIS).

### R1 — Asignación única

**Motivación.** Cada horario presencial que participa del modelo tiene que recibir exactamente un aula. No se admite dejar un horario sin aula (eso sería infactibilidad) ni asignarle dos aulas (contradiría la estructura de la solución).

**Formulación.**

$$
\sum_{a \in A} x[h, a] = 1 \qquad \forall\, h \in H \setminus H_\emptyset
$$

Los horarios en `H_∅` (virtuales bajo R5 estricta) no reciben aula: se saltan de esta restricción.

**Implementación.** `build_model:820`. No se puede relajar en el IIS: es constitutiva del problema.

### R3 — Compatibilidad tipo aula ↔ tipo clase

**Motivación.** Una clase teórica no puede darse en un aula de laboratorio y una clase de laboratorio no puede darse en un aula teórica común. Cuando la clase es de laboratorio, además, tiene que ser un laboratorio compatible con la materia (por instrumental, mesada de trabajo, etc.).

**Implementación.** R3 se aplica **antes** de instanciar las variables `x[h, a]`: se computa la matriz `compat(h, a)` y sólo se crean variables para pares con `compat(h, a) = 1`. Esto reduce dramáticamente el tamaño del modelo.

**Formulación (equivalente, si expresáramos R3 con variables completas).**

$$
\begin{aligned}
x[h, a] &= 0 \quad \text{si } \text{tipo}(h) = \text{teorica} \text{ y } \text{tipo}(a) \notin \{\text{teorica}, \text{anfiteatro}\} \\
x[h, a] &= 0 \quad \text{si } \text{tipo}(h) = \text{laboratorio} \text{ y } a \notin A_{\text{lab}}(\text{materia}(h)) \\
x[h, a] &= 0 \quad \text{si } \text{tipo}(h) = \bot \text{ y } a \notin A_{\text{teo}} \cup A_{\text{lab}}(\text{materia}(h))
\end{aligned}
$$

**Interacción con R6.** Cuando `tipo(h) = ⊥`, la restricción R6 obliga a que el tipo resuelto sea consistente con la aula asignada (ver R6). Esto significa que las clases sin tipo definido pueden ir a cualquier aula teórica o a cualquier laboratorio compatible con su materia; R6 fuerza la coherencia entre `t[h]` y `tipo(a)`.

### R4 — No doble asignación (grupos de simultaneidad)

**Motivación.** Dos horarios que se dictan a la misma hora del mismo día no pueden compartir aula. La formulación por grupos de simultaneidad maximales es preferible a la formulación por pares por dos motivos: genera menos restricciones (una por grupo × aula en lugar de una por par × aula) y tiene una relajación lineal más fuerte (ver §5.3).

**Formulación.**

$$
\sum_{h \in S} x[h, a] \le 1 \qquad \forall\, S \in Sim,\ \forall\, a \in A
$$

**Implementación.** `build_model:970`. Los horarios en `H_∅` se excluyen de `Sim` porque no compiten por aula. Se puede relajar en el IIS (permitir sobre-asignación aula por aula) para diagnosticar saturación.

### R5 — Partición teoría/laboratorio por materia

**Motivación.** Muchas materias declaran cuántas horas semanales corresponden a teoría (`hteo(m)`) y cuántas a laboratorio (`hlab(m)`). El asignador debe respetar esa partición sumando las duraciones de los horarios asignados a cada tipo.

**Formulación con `strict_r5 = True` (default).**

$$
\begin{aligned}
\sum_{h \in H(c),\, \text{tipo}(h)=\text{teorica}} \text{dur}(h)
+ \sum_{h \in H(c),\, \text{tipo}(h)=\bot} (1 - t[h]) \cdot \text{dur}(h)
&= \text{hteo}(\text{materia}(c)) \\
\sum_{h \in H(c),\, \text{tipo}(h)=\text{laboratorio}} \text{dur}(h)
+ \sum_{h \in H(c),\, \text{tipo}(h)=\bot} t[h] \cdot \text{dur}(h)
&= \text{hlab}(\text{materia}(c))
\end{aligned}
$$

por cada comisión `c ∈ C` cuya materia declara `hteo` o `hlab` positivos. Los horarios en `H_∅` **cuentan** para el balance aunque no ocupen aula: reflejan horas dictadas de manera virtual.

**Formulación con `strict_r5 = False` (legacy).** Sólo valida el balance de laboratorio; los horarios en `H_∅` se filtran completamente. Se conserva por compatibilidad con planes cargados antes de la Fase 8.1; el default en la UI es `True`.

**Implementación.** `build_model:850`. Se puede relajar en el IIS para diagnosticar desalineaciones entre las horas declaradas y las cargadas en el cronograma.

### R6 — Consistencia tipo ↔ pool de aulas (cuando el tipo es indefinido)

**Motivación.** Los horarios con `tipo(h) = ⊥` tienen una variable `t[h]` que decide si son teoría o laboratorio. Esa decisión debe ser consistente con el tipo del aula asignada: si `t[h] = 0` (teoría), el aula tiene que ser teórica; si `t[h] = 1` (laboratorio), el aula tiene que ser laboratorio compatible.

**Formulación.**

$$
\begin{aligned}
\sum_{a \in A_{\text{teo}}} x[h, a] &= 1 - t[h] \\
\sum_{a \in A_{\text{lab}}(\text{materia}(h))} x[h, a] &= t[h]
\end{aligned}
\qquad \forall\, h \in H \setminus H_\emptyset \text{ con } \text{tipo}(h) = \bot
$$

**Implementación.** `build_model:920`. Se puede relajar en el IIS.

### R7 — Sobre-ocupación y sub-ocupación (definiciones lineales)

**Motivación.** No es una restricción "clásica" sino la definición lineal de las variables `over[h]` y `under[h]` en función de la capacidad del aula asignada y de los inscriptos esperados. Aparece como restricción porque de otra manera las variables serían libres.

**Formulación.**

$$
\begin{aligned}
\text{over}[h] &\ge \text{insc}[h] - (1 + \text{tol\_over}) \cdot \sum_{a \in A} \text{cap}(a) \cdot x[h, a] \\
\text{under}[h] &\ge (1 - \text{tol\_under}) \cdot \sum_{a \in A} \text{cap}(a) \cdot x[h, a] - \text{insc}[h] \\
\text{over}[h], \text{under}[h] &\ge 0
\end{aligned}
\qquad \forall\, h \in H \setminus H_\emptyset
$$

Como el objetivo minimiza `over` y `under`, en la solución óptima ambas quedan al valor exacto del exceso o del hueco, según corresponda.

**Implementación.** `build_model:1000`.

### R9 — Redistribución de coeficientes (opcional, off por default)

**Motivación.** Cuando un dictado tiene varias comisiones, la matrícula esperada puede distribuirse desigualmente. El toggle `activar_alpha` permite al asignador redistribuir esos pesos si eso mejora la sobre/sub-ocupación agregada. Con `α` desactivado, cada comisión conserva su `coef_asignacion` original.

**Formulación con `activar_alpha = True`.** Para cada dictado `k` con `|comisiones(k)| > 1`:

$$
\sum_{c \in \text{comisiones}(k)} \alpha[c] = 1 \qquad
\text{insc}[h] = \text{total\_esp}(\text{materia}(k)) \cdot \alpha[\text{comisión}(h)] \quad \forall h \in H(c)
$$

Con `activar_alpha = False`, `insc[h]` es constante y `α` no aparece.

**Implementación.** `build_model:1050`.

### R10 — Sedes admisibles por horario (vía grupo de materias)

**Motivación.** No todas las materias pueden dictarse en todas las sedes. La restricción se modela por-grupo: cada `GrupoMateriaDB` declara dos configuraciones simultáneas (set duro y lista blanda ordenada), y en cada corrida el usuario elige el modo por-grupo (`modo(g) ∈ {DURO, BLANDO}`). La restricción dura R10 sólo se activa en modo DURO.

**Formulación.**

$$
x[h, a] = 0 \qquad \forall\, h \in H \setminus H_\emptyset,\ \forall\, a \in A
$$

cuando se cumple lo siguiente:

- `modo(grupo(materia(h))) = DURO`,
- `S_D(grupo(materia(h)))` no vacío,
- `sede(a) ∉ S_D(grupo(materia(h)))`,
- **excepción de laboratorio**: `a ∉ A_lab(materia(h))`.

Es decir, se prohíbe la asignación al aula `a` para el horario `h` a menos que la aula sea un laboratorio compatible con la materia (donde la compatibilidad física prevalece sobre la preferencia curricular).

**Implementación.** Se aplica **antes** de instanciar las variables: `build_inputs:475` recorre cada horario y anula `compat[(h, a)]` para las aulas prohibidas. En modo BLANDO no se aplica R10 y todas las sedes son admisibles; el sesgo hacia la sede preferida vive en R12.

**Fallback permisivo.** Si `S_D(g) = ∅` para un grupo en modo DURO, R10 no filtra (todas las sedes son admisibles). Se usa para el grupo "Sin clasificar" durante la transición inicial y se emite un warning en la UI.

**IIS**. R10 se relaja reconstruyendo `build_inputs` con el flag `relax_r10=True`, que salta el filtro de sede completamente.

### R11 — Pins de ediciones manuales

**Motivación.** Cuando el operador fija manualmente el aula de un horario y marca la asignación como manual (`HorarioDB.aula_asignada_manualmente = True`), el asignador debe respetar esa elección. Es una restricción dura sólo cuando `respetar_ediciones_manuales = True`.

**Formulación.**

$$
x[h, a] = 1 \qquad \forall\, h \in H \setminus H_\emptyset : \text{pin}(h) = a,\ \text{respetar\_ediciones\_manuales}
$$

Si `respetar_ediciones_manuales = False`, R11 no se activa y el LP reasigna libremente.

**Implementación.** `build_model:830`.

### R12 — Preferencia blanda de sede (grupos BLANDO)

**Motivación.** Cuando un grupo corre en modo BLANDO, todas las sedes son admisibles (R10 no aplica) pero la primera de la lista blanda es la preferida. El LP asigna cero costo si el aula elegida está en esa sede y suma `λ_sede_pref` por cada horario que caiga en otra sede admisible.

**Formulación.** Aparece en el objetivo (ver §3.4), no como restricción. En términos de variables:

$$
\text{costo\_sede}[h] = \sum_{a \in A : \text{sede}(a) \neq \text{sede\_pref}(h)} x[h, a]
$$

Se acumula al objetivo multiplicado por `λ_sede_pref`.

**Implementación.** `build_model:780`.

### R13 — Continuidad de sede en pares en riesgo

**Motivación.** Cuando dos horarios contiguos el mismo día tienen un gap menor al margen mínimo intersede, no dan tiempo para un traslado entre sedes. Se detectan dos tipos de riesgo:

- **Traslado del docente**: pares de horarios de la **misma comisión** (el mismo profesor debe estar en los dos).
- **Traslado del alumno**: pares de horarios de **distintas materias** del mismo grupo curricular `(carrera, año, cuatri)` (un alumno inscripto en las dos materias tiene que hacer el traslado).

R13 impone que, para cada par en riesgo, los dos horarios caigan en la misma sede o al menos en sedes compatibles.

**Formulación.** Para cada par `(h1, h2) ∈ P_R13` y cada par de sedes distintas `(s1, s2) ∈ S²` con `s1 ≠ s2`:

$$
\sum_{a \in A : \text{sede}(a) = s_1} x[h_1, a]
+
\sum_{a \in A : \text{sede}(a) = s_2} x[h_2, a]
\le 1
$$

Dado que R1 fuerza `Σ_a x[h, a] = 1` para todo horario, la restricción equivale a "si `h1` cae en `s1`, entonces `h2` no puede caer en `s2`".

**Detección de pares (`compute_pares_intersede_riesgo`).** Toma como entrada la lista de horarios, el mapa `comision(h)` y el mapa opcional `grupos_curriculares(h)` (conjuntos `(carrera, año, cuatri)` en los que aparece la materia del horario). Devuelve la lista de pares `(h1, h2, gap)` con `0 ≤ gap < margen_min_intersede_minutos` y `mismo_dia(h1, h2)`, agrupados en:

- Pares de la misma comisión (siempre).
- Pares de materias distintas del mismo grupo curricular (sólo si se provee el mapping).

**Implementación.** `build_model:995`. Se puede relajar en el IIS. Se desactiva completamente si `margen_min_intersede_minutos = 0`.

### R14 — Forzar misma sede por comisión (opcional)

**Motivación.** Cuando el toggle `forzar_misma_sede_por_comision` está activo, todos los horarios de una misma comisión deben caer en la misma sede. Refleja que el docente no cambia de sede a mitad de semana y que fragmentar una comisión entre sedes es operativamente indeseable, aunque sea técnicamente posible.

**Formulación.** Se introducen variables auxiliares `y[c, s] ∈ {0, 1}` para cada comisión `c` con más de un horario y cada sede `s ∈ S`. Las restricciones son:

$$
\begin{aligned}
\sum_{s \in S} y[c, s] &= 1 \\
x[h, a] &\le y[c, \text{sede}(a)] \qquad \forall\, h \in H(c),\ \forall\, a \in A \text{ con } (h, a) \in x
\end{aligned}
$$

La primera obliga a que cada comisión con más de un horario caiga en exactamente una sede. La segunda es el vínculo entre `x` y `y`: si `h` se asigna al aula `a` en sede `s`, entonces `y[c, s] = 1`.

**Implementación.** `build_model:1070`. Sólo se activa cuando el toggle está prendido. Se puede relajar en el IIS.

### R13-camino — Chequeo estructural de camino de cursada

R13-camino no es una restricción del modelo LP: es un **chequeo pre-solve** que se ejecuta antes de armar el modelo y aborta la corrida si detecta que no hay solución posible desde el punto de vista de un alumno. Se describe en detalle en §7.5. Se menciona acá para la numeración canónica de restricciones.

## 5. Semántica de sedes y grupos de materias

### 5.1 Modelo de grupos

Cada `GrupoMateriaDB` declara **dos configuraciones simultáneas** de sedes:

- **Set duro** (`S_D(g) ⊆ S`): sedes admisibles cuando el grupo corre en modo DURO.
- **Lista blanda ordenada** (`S_B(g)`): lista de sedes preferidas cuando el grupo corre en modo BLANDO. El orden es semántico: la primera es la preferida (paga cero al objetivo); el resto son alternativas con costo `λ_sede_pref` por horario que caiga ahí.

Ambas configuraciones se declaran en la UI del editor de grupos y se persisten en `GrupoMateriaSedeDB` con `tipo ∈ {DURO, BLANDO}`. Una misma sede puede aparecer con ambos tipos: son independientes.

### 5.2 Resolución de sedes admisibles por horario

Dado un horario `h`, la resolución de sedes admisibles procede así:

1. Obtener `g = grupo(materia(h))` (partición estricta).
2. Obtener `modo(g)` desde `LPConfig.modos_por_grupo`. Si no aparece, default DURO.
3. Si `modo(g) = DURO`:
   - Si `S_D(g) ≠ ∅`: `sedes_adm(h) = S_D(g)`, sede preferida `⊥`.
   - Si `S_D(g) = ∅`: `sedes_adm(h) = S` (fallback permisivo), sede preferida `⊥`.
4. Si `modo(g) = BLANDO`:
   - `sedes_adm(h) = S` (todas admisibles, no aplica R10).
   - Si `S_B(g) ≠ ∅`: sede preferida `= primera de S_B(g)`.
   - Si `S_B(g) = ∅`: sede preferida `⊥` (no aplica R12).

**Excepción de laboratorio compatible.** Si `a ∈ A_lab(materia(h))`, entonces `a` es admisible para `h` aunque `sede(a) ∉ sedes_adm(h)`. Refleja que la compatibilidad física del laboratorio es más restrictiva que la preferencia curricular.

Esta resolución la implementa `resolver_config_sedes_por_materia` en `grupo_materia_service.py` y la consume `build_inputs` para armar la matriz `compat`.

### 5.3 Grupos de simultaneidad — motivación de la formulación

R4 se formula por grupos de simultaneidad maximales y no por pares de horarios. Las dos formulaciones son equivalentes en cuanto al conjunto factible, pero difieren en dos aspectos importantes:

- **Cantidad de restricciones**. Un grupo de simultaneidad con `n` horarios genera **una sola** restricción R4 por aula (`Σ_{h ∈ S} x[h, a] ≤ 1`), mientras que la formulación por pares genera `n(n−1)/2` restricciones por aula (una por cada par). Para franjas populares con `n = 20`, la diferencia es de 1 vs 190 restricciones por aula.
- **Fuerza de la relajación lineal**. La restricción por grupo tiene una relajación lineal más ajustada que las restricciones por pares equivalentes. En la práctica esto se traduce en menos nodos explorados durante el *branch and bound* y tiempos de resolución menores.

La construcción de `Sim` (`compute_simultaneidad_groups`) recorre la grilla semanal detectando maximalidad: en cada instante activo se registra qué horarios están corriendo, y se emite un grupo cuando el conjunto activo cambia (algún horario terminó o algún horario nuevo comenzó).

## 6. Función objetivo — resumen de parámetros

La función objetivo agrega tres términos con pesos distintos:

| Término | Parámetro | Default | Cuándo aparece |
|---|---|---|---|
| Sobre-ocupación | `λ_over` | 10 | Siempre. |
| Sub-ocupación | `λ_under` | 1 | Siempre. |
| Preferencia de sede | `λ_sede_pref` | 5 | Sólo para horarios cuyo grupo corre en modo BLANDO y tiene sede preferida definida. |

La asimetría `λ_over = 10 · λ_under` codifica que sobre-ocupación es más grave que sub-ocupación. La razón operativa es que sobre-ocupación es un problema físico (alumnos no entran al aula) mientras que sub-ocupación es un problema económico (aula desaprovechada).

El término blando de intersede (`λ_intersede`) está cableado en el código pero no se activa por default: con `λ_intersede = 0` no aparece en el objetivo. Se dejó como preparación para una posible variante blanda de R13.

## 7. Chequeo estructural pre-solve

Antes de armar el modelo LP, se ejecuta un conjunto de chequeos que detectan situaciones que garantizan infactibilidad. Si alguno detecta un problema, la corrida aborta y reporta el bloqueo sin gastar tiempo del resolutor. La UI muestra el resultado bajo el título "Chequeo de factibilidad estructural".

Los chequeos se implementan en `factibilidad_service.py` y son los siguientes.

### 7.1 R1 — Horarios sin aula compatible

Para cada horario `h ∈ H \ H_∅`, verifica que exista al menos un aula `a` con `compat(h, a) = 1`. Si no, el horario es infactible por sí mismo: el LP no tiene dónde asignarlo. El chequeo distingue dos causas:

- **R1+R3 clásica**: sin `compat_override`, no hay aula compatible por tipo o por lab.
- **R10**: sin filtro de sede sí habría aula compatible, pero al aplicar R10 el conjunto queda vacío.

### 7.2 Saturación por tipo dentro de una franja

Para cada grupo de simultaneidad `S ∈ Sim`, cuenta cuántos horarios de `S` necesitan **estrictamente** un aula teórica y cuántos aulas de laboratorio de una materia específica. Si en alguna franja la demanda de un tipo supera la oferta, la infactibilidad es estructural.

Este chequeo es una **refinación** del *pigeonhole* clásico: no cuenta contra la unión total de aulas de la franja sino contra los pools disjuntos por tipo. Detecta casos como "en la franja del lunes 18 hs hay 5 clases de laboratorio de Química pero sólo 3 laboratorios de Química", que la cota global de pigeonhole no ve.

### 7.3 Test de Hall (apareamiento bipartito)

Para cada grupo de simultaneidad `S ∈ Sim`, construye el grafo bipartito `(S, A)` con arista `(h, a)` si `compat(h, a) = 1` y verifica que exista un apareamiento perfecto que asigne un aula distinta a cada horario de `S`. Por el teorema de Hall, existe apareamiento perfecto si y sólo si para todo subconjunto `T ⊆ S`, el conjunto de vecinos `N(T)` cumple `|N(T)| ≥ |T|`.

En la práctica:

- Para `|S| ≤ 8` se enumera exactamente cada subconjunto y se reporta el testigo Hall-violador más chico.
- Para `|S| > 8` se corre un matching bipartito con búsqueda de caminos aumentantes; si el matching máximo es `< |S|`, se reporta el lado izquierdo no matcheado.

Hall es una condición necesaria y suficiente para la existencia de una asignación válida en cada franja: es la cota más fuerte del chequeo estructural.

### 7.4 Partición teoría/laboratorio infactible

Para cada comisión `c ∈ C` cuya materia declara horas de teoría y de laboratorio, verifica que la suma total de duraciones de los horarios de `c` sea compatible con `hteo(m) + hlab(m)`, y que exista al menos una partición de los horarios de tipo indefinido que respete R5. Si la partición no cierra —por ejemplo, la materia declara 3 horas de lab pero los horarios cargados sólo suman 2— la infactibilidad es estructural y se reporta antes del solve.

### 7.5 R13-camino — Camino de cursada factible

Para cada terna `(carrera, año, cuatri)` del ciclo del plan, verifica que exista al menos una combinación de comisiones (una por materia obligatoria) que un alumno pueda cursar sin conflictos. El chequeo cubre dos ejes:

- **Solapamiento horario**: si dos horarios de dos comisiones distintas se pisan el mismo día, el alumno no puede cursar ambas simultáneamente.
- **Traslado intersede**: si dos horarios de comisiones distintas tienen gap menor al margen mínimo y las sedes admisibles de sus grupos son disjuntas, no hay traslado factible.

**Algoritmo.** Se agrupan las comisiones del plan por `(carrera, año, cuatri)` obligatorias, se enriquece cada grupo con las materias anuales de la misma `carrera × año`, y se corre backtracking DFS probando combinaciones. Para cada par `(cid_a, cid_b)` de comisiones candidatas se cachea el resultado de compatibilidad (`_par_es_compatible`) para no re-computar. Si el DFS encuentra al menos una combinación viable, el grupo se declara factible. Si no encuentra ninguna, se emite bloqueo.

**Cap de exploración.** El backtracking se detiene si el producto de comisiones por materia supera `MAX_COMBINACIONES_CAMINO = 10 000`, y en ese caso se emite advertencia en lugar de bloqueo.

**Excepciones ignoradas.** Los pares `(materia_a, materia_b)` registrados en `IgnoredConflictDB` para el plan se **saltan** del chequeo de solapamiento. Sirven para modelar casos como "materias homónimas de distintos años del plan que en la práctica cursan alumnos distintos". El chequeo de intersede **no** consulta las excepciones: el traslado es un problema físico independiente de qué alumnos cursen qué.

**Auto-limpieza.** Cuando el plan de estudio cambia y una materia deja de coexistir con la otra en algún grupo curricular, la excepción registrada en `IgnoredConflictDB` queda huérfana y se limpia automáticamente en la próxima validación del plan (`cleanup_stale_ignored_pairs`). Se reporta la limpieza al usuario para que sepa qué pares dejaron de aplicar.

## 8. Diagnóstico por relajación selectiva (IIS)

Cuando el solver reporta `infeasible` y el chequeo estructural pre-solve no detectó ninguna causa conocida (o las causas detectadas son insuficientes), se dispara un diagnóstico por relajación selectiva. El objetivo es identificar qué restricciones son las responsables de la infactibilidad y proponer acciones concretas.

Se implementa en `_run_iis_relajacion` en `asignacion_aulas_service.py`.

### 8.1 Relajación individual por regla

Se prueban las siguientes restricciones, una a la vez, y se re-corre el modelo:

- **R4**: doble asignación.
- **R5**: partición teoría/lab.
- **R6**: consistencia tipo ↔ pool.
- **R10**: filtro de sede DURO (se reconstruye `build_inputs` con `relax_r10=True`).
- **R13**: margen intersede.
- **R14**: forzar misma sede por comisión (sólo si estaba activo).

Para cada regla que arregla el modelo al relajarse, se registra `feasible_relajado = True`.

### 8.2 Filtros de falsos positivos

La relajación selectiva sufre de un artefacto conocido: cuando la causa real es una restricción fuertemente saturadora (típicamente R4), relajar otras reglas también arregla porque le da al solver más libertad y la restricción real deja de morder. Para evitar reportar culpables espurios:

- **R5** se descarta como culpable si ninguna materia con `hlab_declarado > 0` quedó con desalineación. Es decir: si sólo materias sin lab declarado aparecen con `t[h]` cambiado al relajar R5, el "arreglo" es un efecto secundario de la libertad extra.
- **R6** se descarta como culpable si todos los horarios con `tipo(h) = ⊥` admiten al menos una alternativa válida (aula teórica o lab compatible). Si todos tienen alternativa, el problema es de saturación (R4) y no de tipo.
- **R4** se prioriza como causa principal cuando aparece junto con R5/R6 falsos positivos.

### 8.3 Priorización de la causa principal

Cuando hay varios culpables reales, se elige el "principal" con un orden de prioridad accionable:

```
R10 → R14 → R13 → R4 → R5 → R6
```

Las restricciones "de sede" (R10, R14, R13) se priorizan porque son las que el usuario controla directamente desde el panel del asignador. R4 (saturación global) es más difícil de accionar porque requiere agregar aulas o mover horarios. R5/R6 son las menos frecuentes como causa real.

### 8.4 Análisis refinado cuando R10 es la culpable

Cuando R10 rescata el modelo al relajarse por completo, se ejecuta un análisis adicional en `_iss_r10_grupos_rescate`: se prueba pasar **cada grupo DURO a BLANDO por separado** y se registra cuáles rescatan el modelo individualmente. Esto permite dar recomendaciones accionables del tipo "pasá el grupo *X* a modo BLANDO" en lugar del genérico "R10 es la culpable".

Los grupos candidatos se filtran por:

- Estar en modo DURO en la corrida actual.
- Tener lista blanda no vacía (pasarlo a BLANDO tiene efecto real).
- Tener al menos una materia con comisiones en el plan.

### 8.5 Análisis de combinaciones cuando ninguna regla individual rescata

Cuando el IIS no encuentra ninguna causa individual, es porque la infactibilidad es combinada: relajar sólo una restricción no alcanza, hay que relajar dos o más juntas. Se ejecuta `_iss_combinaciones_rescate`, que prueba combinaciones de a pares:

- Cada grupo DURO → BLANDO **combinado con** desactivar R14 (si estaba activo).
- Cada grupo DURO → BLANDO **combinado con** poner margen intersede en 0 (si era > 0).

Se registra cada combinación que rescata el modelo. El costo es acotado por `CAP_PRUEBAS = 40` combinaciones. La UI presenta las combinaciones ordenadas por menor impacto (grupos con menos materias en el plan primero) para que el usuario elija la menos invasiva.

### 8.6 Estructura del resultado del IIS

El diagnóstico se serializa en `LPRunDB.details_json` bajo la clave `iis`:

```jsonc
{
  "ran": true,
  "culpables": ["R10", "R13"],   // reglas que rescatan y no son falsos positivos
  "principal": "R10",            // causa principal según prioridad
  "detalles": {
    "R4": {"feasible_relajado": false, "es_falso_positivo": false, "explicacion": "..."},
    "R5": {"feasible_relajado": true, "es_falso_positivo": true, "explicacion": "...", "materias_problema": [...]},
    // ...
    "R10": {
      "feasible_relajado": true,
      "es_falso_positivo": false,
      "explicacion": "...",
      "grupos_rescate": [
        {"grupo_id": "...", "grupo_nombre": "Específicas de Ing. Eléctrica",
         "n_materias_plan": 13, "modo_actual": "DURO", "modo_propuesto": "BLANDO"}
      ]
    }
  },
  "combinaciones_rescate": [
    {"grupo_id": "...", "grupo_nombre": "Específicas de Ing. Civil",
     "n_materias_plan": 8, "extra": "sin_forzar_misma_sede",
     "extra_label": "desactivar 'Forzar misma sede por comisión'"}
  ]
}
```

La UI del panel de resultado (`asignacion_resultado_ui.py`) consume esta estructura y renderea el "Diagnóstico cruzado" con las recomendaciones accionables.

## 9. Aplicación de la solución al plan

Cuando el solver devuelve `optimal`, la función `apply_solution` (en `asignacion_aulas_service.py`) escribe la asignación al patrón semanal y propaga a las clases puntuales del plan.

### 9.1 Escritura al patrón

Para cada `(h, a) ∈ x_assignments`:

- Si `respetar_ediciones_manuales = True` y `HorarioDB.aula_asignada_manualmente = True`, la solución del LP ya vino con `x[h, a] = 1` fijado por R11, la escritura es idempotente y el flag de manual se preserva.
- Si no, `HorarioDB.aula_id = a` y se baja el flag manual.
- Si `t[h]` está definido y `HorarioDB.tipo_clase` era `⊥`, se persiste el tipo resuelto.

### 9.2 Propagación a clases puntuales

Para cada `ClaseDB` del plan con `fecha ≥ fecha_desde` y `executed = False`, se propaga el nuevo `aula_id` desde el patrón. Es un *cache* técnico que preserva compatibilidad con la validación por-fecha; ninguna vista de la UI depende de leer directamente de `ClaseDB`.

### 9.3 Saneamiento de virtuales stale

Los horarios en `H_∅` (virtuales bajo R5 estricta) no producen entrada en `x_assignments` porque no participan del modelo. Si arrastraban una `aula_id` de una corrida anterior en la que eran presenciales, quedaría stale. `apply_solution` recibe `no_ocupa_aula_ids` como parámetro y libera esas aulas: `HorarioDB.aula_id = None`, `aula_asignada_manualmente = False`, propagando el cambio a las clases puntuales correspondientes.

Este saneamiento fue agregado tras detectar que corridas viejas dejaban aulas asignadas a horarios que después se marcaban como virtuales, generando falsas colisiones en las vistas de aulas.

## 10. Persistencia de corridas

Cada ejecución del asignador se persiste como un registro `LPRunDB`. La UI puede reconstruir la vista completa de la corrida (heatmap, tabla por horario, diagnóstico) desde el registro sin volver a correr el LP.

Campos principales:

- `plan_cursada_id`, `run_at`, `fecha_desde`.
- Copia de parámetros de la config: `lambda_over`, `lambda_under`, `tol_over`, `tol_under`, `timeout_seconds`, `respetar_ediciones_manuales`, `activar_alpha`.
- Resultado: `status`, `objective_value`, `n_horarios_total`, `n_horarios_asignados`, `n_horarios_reasignados`, `solver_seconds`, `error_message`.
- `details_json`: dict serializado con la lista completa de horarios asignados, el diagnóstico estructural, el IIS (si corrió) y el veredicto humano.

El panel del asignador lee siempre la corrida más reciente del plan y presenta la última al abrirla. Los parámetros del panel se **prefill** con los de la última corrida, lo que permite iterar sin re-configurar todo cada vez (persistencia de parámetros descripta en la guía operativa).

## 11. Decisiones de diseño

Esta sección documenta las principales elecciones estructurales del modelo. Se agrupan por tema.

### 11.1 Por qué grupos de materias en lugar de sedes por carrera

Versiones tempranas del sistema modelaban la restricción de sede vía `CarreraSedeDB` — una tabla M:N entre carreras y sedes habilitadas. El problema: una materia común a varias carreras heredaba la unión de sus sedes, lo que en la práctica generaba conflictos entre carreras con criterios distintos. Además, `MateriaDB.es_default_comunes` no soportaba modelizar "materias del ciclo básico" (comunes a varias ingenierías pero con criterio distinto que "una sede para todas las comunes").

Los **grupos de materias** invirtieron la relación: cada materia pertenece a exactamente un grupo, y cada grupo declara sus propias sedes. Esto permite:

- Distintos criterios por familia curricular: FB (ciclo básico Pellegrini), F (troncal Siberia), CE (comunes lics/profs Pellegrini), FI (Inglés Pellegrini), y Específicas de cada carrera.
- Bootstrap por prefijo del código de materia (`FB*`, `FI*`, `CE*`, `F*`) + fallback por carrera única.
- Curación asistida vía chequeo de consistencia (`chequear_consistencia_grupo`) que reporta materias faltantes y ajenas por grupo.

`CarreraSedeDB` queda como legacy trackeado; no la leen ni el LP ni la UI.

### 11.2 Por qué dos configuraciones simultáneas (DURO/BLANDO) por grupo

Cada grupo declara set duro y lista blanda al mismo tiempo, y el modo se elige por-grupo en cada corrida. Esta decisión permite:

- **Iterar sin re-configurar los grupos**. El usuario puede probar la misma corrida en modo DURO (más estricto) o BLANDO (más flexible) sin tocar la config de sedes.
- **Modelizar preferencia sin rigidez**. En BLANDO la primera sede es preferida pero no obligatoria. El LP paga costo por asignar alternativas pero puede hacerlo si mejora el objetivo global (o resuelve una infactibilidad local).
- **Facilitar el diagnóstico**. Cuando el IIS detecta que R10 es la causa, propone pasar grupos específicos de DURO a BLANDO — una acción directa del usuario, sin necesidad de tocar la lista de sedes.

### 11.3 Por qué R13 aplica al alumno además del profesor

En el planteo original, la restricción de continuidad de sede (R13) sólo consideraba pares de horarios de la **misma comisión** — modelaba el traslado del docente entre dos clases suyas contiguas. Al analizar casos reales aparecieron infactibilidades desde el punto de vista del alumno: una comisión de FB12 en Pellegrini y una de A6 en Siberia con gap 0 min hacen imposible el traslado, aunque cada comisión aislada sea factible.

La extensión de R13 a pares intercomisión del mismo grupo curricular refleja que **cada alumno concreto** debe poder cursar sin traslados imposibles. El LP ahora bloquea también estos pares y el chequeo pre-solve R13-camino lo verifica antes de correr el modelo.

### 11.4 Por qué R13-camino como chequeo pre-solve y no como restricción del modelo

El chequeo de camino de cursada verifica **existencia** de una combinación viable, no la fuerza. En modelo LP, forzarlo requeriría variables adicionales por alumno hipotético — algo que aumentaría dramáticamente el tamaño del modelo sin beneficio directo: si existe al menos una combinación viable, cualquier alumno concreto podrá elegirla al inscribirse. El LP mismo no elige comisiones por alumno.

Por eso R13-camino se implementa como **pre-check estructural**: si no existe combinación viable, se aborta antes del solve. Si existe, el LP asigna aulas libremente y cada alumno elige su combinación de manera independiente.

### 11.5 Por qué IIS con análisis combinado

Cuando ninguna regla individual rescata el modelo, el diagnóstico simple ("no hay causa única") deja al usuario sin acción concreta. La extensión a combinaciones de a pares refleja la observación empírica de que los casos combinados típicos son: **algún grupo DURO** + **R14 activo** o **margen intersede alto**. Probar todas las combinaciones de tres o más restricciones sería explosivo; con pares se cubren los casos frecuentes sin costo prohibitivo.

### 11.6 Por qué `apply_solution` sanea virtuales stale

En el planteo estricto, `apply_solution` sólo escribe lo que el LP resolvió. Los horarios no incluidos en `x_assignments` (virtuales) quedaban con su `aula_id` previo, generando falsas colisiones si eran presenciales antes. La decisión de sanear activamente refleja la invariante deseada del sistema: **un horario virtual no debe tener aula asignada**. La alternativa (validar en cada consulta) diluye la responsabilidad y produce el problema observado de "colisiones fantasma".

### 11.7 Por qué configuración persistida por-corrida

Cada `LPRunDB` guarda snapshot completo de sus parámetros. Permite:

- Reproducir cualquier corrida vieja con la misma config.
- Prefill del panel con los valores de la última corrida (persistencia entre sesiones de Streamlit y entre reinicios).
- Análisis comparativo entre corridas con distintas configs.

El costo es marginal (unos cientos de bytes de JSON por run) y la trazabilidad ganada es significativa para debugging y para el informe académico.

## 12. Referencias

[1] Winston, W. L. *Operations Research: Applications and Algorithms*. Cengage Learning.

[2] Hillier, F. S. y Lieberman, G. J. *Introduction to Operations Research*. McGraw-Hill.

[3] Nemhauser, G. L. y Wolsey, L. A. *Integer and Combinatorial Optimization*. Wiley-Interscience.

[4] Wolsey, L. A. *Integer Programming*. Wiley-Interscience.

[5] Chinneck, J. W. *Feasibility and Infeasibility in Optimization*. Springer. (Referencia principal para el diagnóstico por relajación selectiva y el concepto de IIS.)
