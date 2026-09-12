# Guía operativa del asignador de aulas

> **Estado**: guía viva, actualizada a medida que evoluciona la
> interfaz del asignador. Este documento es la **referencia
> operativa** del programa lineal: cómo se corre, cómo se configura,
> cómo se interpretan sus resultados y cómo se diagnostican los
> casos que no cierran. Para el **planteo formal** (conjuntos,
> variables, restricciones, función objetivo, chequeo estructural,
> IIS) ver `project/1. Diseño/asignacion-aulas-LP.md`. El presente
> documento asume conocido ese planteo y remite a él cuando la
> discusión requiere la formulación matemática.
>
> **Última actualización**: 2026-09-11.

---

## Índice

1. [Qué hace el asignador en criollo](#1-qué-hace-el-asignador-en-criollo)
2. [Parámetros del panel del asignador](#2-parámetros-del-panel-del-asignador)
3. [Grupos de materias: modos DURO y BLANDO](#3-grupos-de-materias-modos-duro-y-blando)
4. [Veredicto de la corrida y sus estados](#4-veredicto-de-la-corrida-y-sus-estados)
5. [Diagnóstico y recomendaciones ante infactibilidad](#5-diagnóstico-y-recomendaciones-ante-infactibilidad)
6. [Ediciones manuales y consistencia con el LP](#6-ediciones-manuales-y-consistencia-con-el-lp)
7. [Excepciones de conflicto ignorado](#7-excepciones-de-conflicto-ignorado)
8. [Panel de resultado: cómo se lee](#8-panel-de-resultado-cómo-se-lee)
9. [Persistencia de corridas y multi-pestaña](#9-persistencia-de-corridas-y-multi-pestaña)
10. [Troubleshooting común](#10-troubleshooting-común)

---

## 1. Qué hace el asignador en criollo

Cerrada la grilla horaria del cuatrimestre — es decir, definidos
los `HorarioDB` que van a dictarse y a qué comisión pertenecen — el
asignador decide **a qué aula va cada horario semanal presencial**.
Adicionalmente, cuando el cronograma no predetermina si un horario
es teoría o laboratorio, el asignador también lo resuelve, y si el
operador lo pide puede redistribuir los inscriptos esperados entre
comisiones de un mismo dictado. Todo esto se decide en simultáneo
resolviendo un **programa lineal entero** con el resolutor CBC.

### 1.1 Lo que decide

- **El aula de cada horario presencial**. Un aula por horario, ni
  más ni menos.
- **El tipo de cada horario** (teoría o laboratorio) cuando el
  cronograma no lo predeterminó.
- **La distribución de inscriptos entre comisiones** de un mismo
  dictado (opcional, apagado por defecto).

### 1.2 Lo que no decide

- **No crea ni elimina comisiones** ni horarios. Esos son datos de
  entrada.
- **No asigna aulas a horarios virtuales**. Los virtuales no ocupan
  aula por diseño; cuentan sólo para el balance de horas teoría / lab.
- **No decide reservas o bloqueos puntuales de aula**. No hay
  manera hoy de bloquear un aula para una fecha específica desde
  el LP.
- **No considera preferencias horarias de docentes**. Los horarios
  vienen fijos.

### 1.3 Cómo se corre en la UI

El asignador vive en **Planes → seleccionar plan → Aulas**. La
página tiene tres componentes principales:

- **Panel de asignación** (§ 2). Donde se configura la corrida y se
  aprieta el botón para lanzar el solver.
- **Panel de resultado** (§ 8). Aparece después de correr o al abrir
  un plan que ya tiene corridas persistidas.
- **Mapa de saturación** por sede. Vista analítica independiente
  del LP; se puede consultar antes o después de correr.

El flujo típico es:

1. Ajustar parámetros del panel (o dejar los defaults / la última
   corrida).
2. Apretar **"🚦 Chequear factibilidad"** para descartar bloqueos
   estructurales antes de gastar tiempo del solver.
3. Apretar **"⚙ Correr asignador"**.
4. Leer el **veredicto** (§ 4).
5. Si es `optimal`, revisar la solución en el panel de resultado.
   Si es infactible, seguir el **diagnóstico** (§ 5).

### 1.4 Qué mira para decidir, en orden de prioridad

1. **Compatibilidad tipo aula ↔ tipo clase**. Teóricas van a aulas
   teóricas o anfiteatros; laboratorios van a laboratorios
   compatibles con la materia (definidos en
   `MateriaLaboratorioDB`).
2. **Sedes admisibles** según el **grupo de la materia** (§ 3).
3. **No solapamiento por aula**. Dos clases simultáneas nunca
   comparten aula.
4. **Balance teoría / laboratorio** declarado por la materia.
5. **Ediciones manuales**, si el toggle "respetar ediciones
   manuales" está activo (§ 6).
6. **Continuidad de sede intersede** (R13) para pares de horarios
   contiguos en riesgo — profesor de la misma comisión o alumno de
   materias distintas del mismo grupo curricular.
7. **Preferencia de sede** (grupos en modo BLANDO — § 3).
8. **Ajuste de capacidad al forecast** de inscriptos. Penaliza
   fuerte quedarse corto (sobrecupo, `λ_over`) y penaliza suave
   quedarse con mucho sobrante (subutilización, `λ_under`).

---

## 2. Parámetros del panel del asignador

El panel de asignación está organizado en **cuatro contenedores** que
agrupan los parámetros por temática. Cada parámetro se persiste al
correr y se prefill desde la última corrida al reabrir la página
(§ 9).

### 2.1 Alcance temporal

| Parámetro | Default | Efecto |
|---|---|---|
| **Fecha desde** | primer día del ciclo | Fecha a partir de la cual se propaga la solución a las clases puntuales. Las clases anteriores quedan intactas. Útil para reasignar mitad del cuatrimestre sin pisar lo dictado. |
| **Timeout del solver (segundos)** | 300 | Cota máxima de tiempo que el solver puede tardar. Si vence sin resolver, el veredicto queda en `timeout`. |

### 2.2 Ajuste de capacidad

| Parámetro | Default | Efecto |
|---|---|---|
| **Peso de sobre-ocupación (`λ_over`)** | 10 | Multiplicador del término `over[h]` en el objetivo. Cuanto más alto, más castiga cada inscripto que excede la capacidad del aula. |
| **Peso de sub-utilización (`λ_under`)** | 1 | Multiplicador del término `under[h]`. Cuanto más alto, más castiga cada asiento vacío respecto al umbral. |
| **Tolerancia de sobre-ocupación (`tol_over`)** | 0 | Fracción de la capacidad que se admite exceder sin penalidad. Con 0, cualquier exceso cuenta. Con 0.1, se admite un 10 % sin castigo. |
| **Tolerancia de sub-utilización (`tol_under`)** | 0.20 | Fracción de la capacidad que se admite dejar vacía sin penalidad. Con 0.20 (default) se acepta perder hasta un 20 % de asientos sin castigo. |

**Regla mnemotécnica**: `λ_over = 10 · λ_under` codifica que
sobrecupo es un problema físico (los alumnos no entran al aula)
mientras que subutilización es un problema económico (aula grande
desaprovechada). Bajar `λ_over` o subir `tol_over` afloja la
prioridad — a usar con criterio.

### 2.3 Preferencia de sede

| Parámetro | Default | Efecto |
|---|---|---|
| **Peso de preferencia de sede (`λ_sede_pref`)** | 5 | Multiplicador del término R12. Aplica sólo a horarios cuyo grupo corre en modo BLANDO. Cuanto más alto, más fuerte la preferencia por la primera sede de la lista blanda; con 0 se desactiva completamente. |
| **Margen mínimo intersede (minutos)** | 30 | Umbral para detectar pares de horarios contiguos "en riesgo" que no dan tiempo para un traslado. Se aplica a R13 (pares de la misma comisión y pares de alumno del mismo grupo curricular). Con 0 se desactiva. |
| **Forzar misma sede por comisión** | Off | Toggle que activa R14: todos los horarios de una misma comisión deben caer en la misma sede. Utíl cuando el docente no viaja entre sedes a mitad de semana. |
| **Modos por grupo (DURO/BLANDO)** | Todos DURO | Sección desplegable donde por cada grupo de materias se elige el modo con el que corre en esta corrida. Se detalla en § 3. |

### 2.4 Configuración avanzada

| Parámetro | Default | Efecto |
|---|---|---|
| **Estricto R5 (`strict_r5`)** | On | Valida horas de teoría y horas de laboratorio por separado (ver R5 en el planteo). Con Off, sólo valida laboratorio (modo legacy). |
| **Respetar ediciones manuales** | On | Fija como restricción dura las aulas marcadas manualmente. Con Off, el LP reasigna libremente incluso las aulas con pin manual (§ 6). |
| **Redistribuir inscriptos entre comisiones (`activar_alpha`)** | Off | Activa R9: variables `α[k]` que reasignan la matrícula entre comisiones del mismo dictado. Experimental. |
| **Peso intersede blanda (`λ_intersede`)** | 0 | Cableado en el modelo pero no activo hoy. Reservado para una variante blanda de R13. |

### 2.5 Botones

- **🚦 Chequear factibilidad**. Corre el chequeo estructural
  pre-solve (§ 7 del Doc 1) sin encender el solver. Devuelve un
  semáforo (verde / rojo) con detalle por bloqueo. Recomendado
  antes de cada corrida.
- **⚙ Correr asignador**. Lanza la corrida completa: chequeo
  pre-solve + solver + diagnóstico si aplica + persistencia.

---

## 3. Grupos de materias: modos DURO y BLANDO

La preferencia y admisibilidad de sedes se modela a través de la
entidad **`GrupoMateriaDB`**, definida en el módulo Materias. Cada
materia pertenece a exactamente un grupo (partición estricta), y
cada grupo declara **dos configuraciones simultáneas** de sedes:
un set duro y una lista blanda ordenada. El modo con el que corre
un grupo se elige por corrida desde el panel del asignador.

### 3.1 Estructura de un grupo

Cada grupo tiene:

- **Nombre** (`FB`, `F`, `FI`, `CE`, `Específicas de <Carrera>`,
  `Sin clasificar`, o custom).
- **Set duro de sedes** (`S_D(g)`): las únicas admisibles cuando el
  grupo corre en modo DURO.
- **Lista blanda ordenada de sedes** (`S_B(g)`): la primera es la
  preferida (paga cero al objetivo); el resto son alternativas
  con costo `λ_sede_pref` por horario asignado a ellas.

Ambas configuraciones se editan en **Materias → 📦 Grupos de
materias**. Una misma sede puede aparecer con ambos tipos: son
listas independientes.

### 3.2 Modo DURO

- Las sedes del set duro son las **únicas** admisibles para las
  materias del grupo. R10 filtra las variables `x[h, a]` a esas
  sedes antes de instanciar el modelo.
- El orden no tiene efecto: todas las sedes del set son
  equivalentes a nivel objetivo.
- **Excepción de laboratorio compatible**: un aula listada en
  `MateriaLaboratorioDB` para la materia se acepta aunque su sede
  no esté en el set duro. Refleja que la compatibilidad física del
  laboratorio es más restrictiva que la preferencia curricular.
- **Set duro vacío = fallback permisivo**: todas las sedes se
  consideran admisibles. Se usa en el grupo "Sin clasificar" y
  emite un warning en la UI para que se cure.

### 3.3 Modo BLANDO

- **Todas** las sedes son admisibles (R10 no filtra).
- La primera sede de la lista blanda es la preferida: cero costo
  al objetivo.
- El resto son alternativas: cada horario asignado a una de ellas
  suma `λ_sede_pref` al objetivo. La penalidad es **plana**: da lo
  mismo la segunda que la quinta.
- Con `S_B(g) = ∅`, todas las sedes son admisibles y no hay sede
  preferida (el modo se comporta como "cualquier sede vale sin
  costo").

### 3.4 Cómo se eligen los modos por corrida

En el panel del asignador, dentro del contenedor "Preferencia de
sede", hay una sección desplegable **"Modos por grupo"** que lista
todos los grupos activos con un radio DURO / BLANDO por grupo.
Debajo de cada radio se muestra el efecto textual:

- **DURO**: "Sólo se aceptan aulas en las sedes `S_D(g)`."
- **BLANDO**: "Todas las sedes son admisibles. Preferida:
  `S_B(g)[0]`. Alternativas con costo `λ_sede_pref` por horario."

Al correr, cada radio se persiste en `LPConfig.modos_por_grupo` y
se guarda con la corrida en `LPRunDB.details_json`. La próxima vez
que se abra el panel, los modos vuelven a hidratarse desde la
última corrida (§ 9).

### 3.5 Grupos bootstrapeados al inicializar la base

La primera vez que se carga la base, la migración crea
automáticamente los siguientes grupos y les asigna materias por
prefijo de código:

| Grupo | Modo default | Set duro | Prefijo | Motivación |
|---|---|---|---|---|
| `Sin clasificar` | DURO | todas las sedes activas (fallback permisivo) | ninguno | Recibe las materias que la migración no logró clasificar. Se muestra con warning. |
| `FB` | DURO | Pellegrini | `FB*` | Ciclo básico de ingenierías. |
| `F` | DURO | Siberia | `F*` (excluye `FB*` y `FI*`) | Troncal de ingenierías. |
| `FI` | DURO | Pellegrini | `FI*` | Inglés, todas las ingenierías. |
| `CE` | DURO | Pellegrini | `CE*` | Comunes de licenciaturas y profesorados. |
| `Específicas de <Carrera>` | DURO | según `CarreraSedeDB` original | ninguno | Uno por carrera. Recibe materias que aparecen sólo en el plan de esa carrera. |

Después de la migración inicial se puede editar libremente: agregar
sedes, cambiar el modo default de un grupo, reasignar materias
entre grupos, crear grupos nuevos, etcétera.

### 3.6 Chequeo de consistencia (opcional, no bloquea el LP)

Cada grupo puede asociarse a 0..N carreras (`GrupoMateriaCarreraDB`).
Esa asociación sirve para el **chequeo de consistencia**, que
compara qué materias hay en el grupo contra qué materias aparecen
en el plan vigente de las carreras asociadas. El chequeo tiene tres
flags configurables por-grupo:

- **Pertenencia a asociadas** (default On). Toda materia del grupo
  debe aparecer en el plan de al menos una carrera asociada.
- **Exclusividad frente a no asociadas** (default On). Ninguna
  materia del grupo puede aparecer en el plan de carreras no
  asociadas.
- **Completitud (faltantes)** (default On). Busca materias que
  corresponderían al grupo pero están en otro.

Estos flags no afectan al LP. Son una herramienta de curación para
mantener la partición estricta materia ↔ grupo alineada con los
planes de estudio vigentes. La UI del editor de grupos reporta las
inconsistencias en dos listas (`faltantes`, `ajenas`) y permite
reasignar materias con un clic.

### 3.7 Ejemplo: A5 (Informática Aplicada, Electrónica)

- A5 pertenece al grupo `Específicas de Ing. Electrónica`.
- Grupo en modo DURO con `S_D = {Siberia}`.
- A5 tiene laboratorios compatibles en Pellegrini
  (`MateriaLaboratorioDB`).

Resultado: R10 admite aulas de Siberia + los labs compatibles en
Pellegrini (por la excepción de laboratorio). El LP puede usar
cualquiera.

Si se quisiera empujar toda A5 a Pellegrini como preferida, se
pasaría el grupo a modo BLANDO con `S_B = [Pellegrini, Siberia]`:
Pellegrini gratis, Siberia suma `λ_sede_pref`. El LP elegiría
Pellegrini salvo que se sature.

---

## 4. Veredicto de la corrida y sus estados

Después de correr, el panel de resultado muestra un contenedor
**"📋 Veredicto de la corrida"** con el estado final. Son cuatro
estados posibles:

### 4.1 ✅ `optimal`

El solver encontró la solución óptima. Todos los horarios
presenciales recibieron aula. Los horarios virtuales quedan sin
aula por diseño (no ocupan aula pero cuentan hacia las horas
declaradas de la materia por R5 estricta).

**Qué mirar después**:

- **Panel de calidad** en Planes → Detalle (métricas de cobertura,
  ajuste al forecast, uso del catálogo, estado del LP).
- **Horarios fuera de sede preferida**: expander dentro del
  veredicto que lista los horarios asignados a una sede alternativa
  (aplica sólo a grupos BLANDO).
- **Mapa de saturación** para chequear si alguna sede quedó al
  borde.

### 4.2 ❌ `infeasible_estructural`

El **chequeo pre-solve** detectó bloqueos antes de encender el
solver. No se gastó tiempo de CBC. El veredicto enumera cada
bloqueo con su regla (R1, R3+R4, R5, R11, R13, R13-camino,
compat-pigeonhole, compat-hall) y las entidades involucradas.

**Acción**: corregir los datos según el detalle del bloqueo. Ver
§ 10.4 para causas típicas y § 7 del Doc 1 para la lista completa
de chequeos pre-solve.

### 4.3 ❌ `infeasible`

El solver corrió pero no encontró solución. El chequeo pre-solve
no había detectado bloqueos, pero alguna combinación de
restricciones vuelve el problema imposible. Se dispara
automáticamente el **diagnóstico por relajación selectiva** (§ 5)
que identifica qué restricción o combinación de restricciones es
la culpable.

**Acción**: leer la sección "Diagnóstico cruzado" del veredicto y
aplicar la recomendación accionable.

### 4.4 ⏱ `timeout`

El solver alcanzó el timeout sin resolver ni certificar
infactibilidad. Suele significar que el modelo es muy grande o que
hay ambigüedades costosas de resolver.

**Acción**:

- Subir `timeout_seconds` en la configuración avanzada.
- Revisar si hay bloqueos estructurales ocultos (correr chequeo
  pre-solve).
- Simplificar la config (menos grupos BLANDO, R14 apagado, margen
  intersede más bajo).

### 4.5 Restricciones activas — expander de auditoría

El veredicto siempre incluye un expander **"🔧 Restricciones
activas"** con los valores concretos que se usaron en la corrida:
`λ_over`, `λ_under`, `λ_sede_pref`, `margen_min_intersede_minutos`,
`strict_r5`, `respetar_ediciones_manuales`, `activar_alpha`,
`forzar_misma_sede_por_comision` y los modos por grupo. Esto es
crítico para:

- **Reproducir** una corrida vieja con la misma config.
- **Comparar** dos corridas con configs distintas.
- **Auditar** qué se estaba usando cuando algo falló.

---

## 5. Diagnóstico y recomendaciones ante infactibilidad

Cuando el veredicto es `infeasible` (no `infeasible_estructural`),
el asignador ejecuta automáticamente un **diagnóstico por
relajación selectiva** — descripto formalmente en § 8 del Doc 1.
Esta sección explica cómo interpretarlo desde la UI y qué acciones
tomar.

### 5.1 Diagnóstico cruzado — lectura general

El panel muestra tres bloques:

1. **Restricciones que rescatan al modelo** cuando se las relaja
   individualmente. Cada una viene con `feasible_relajado = true`.
2. **Causa principal**. La restricción con mayor prioridad
   accionable, elegida con el orden `R10 → R14 → R13 → R4 → R5 → R6`.
   Es la que la UI recomienda revisar primero.
3. **Falsos positivos filtrados**. Las restricciones que rescatan
   al modelo pero por un artefacto conocido (típicamente R5 y R6
   se marcan como culpables espurias cuando la causa real es R4).

### 5.2 Recomendaciones específicas por regla

- **R10 (filtro DURO de sedes)** — Cuando R10 es la principal, el
  diagnóstico refina el análisis probando **cada grupo DURO a
  BLANDO por separado** (`_iss_r10_grupos_rescate`) y lista los que
  rescatan al modelo individualmente. Cada uno viene con:
  - Nombre del grupo.
  - Cantidad de materias del grupo que tienen comisiones en el plan.
  - Modo actual (DURO) y modo propuesto (BLANDO).
  
  La recomendación de la UI es del estilo "pasá el grupo *X* a modo
  BLANDO". El usuario elige cuál pasar (típicamente el de menor
  cantidad de materias — menos invasivo).

- **R14 (forzar misma sede por comisión)** — Si estaba On, la
  recomendación es apagarlo. La UI lo señaliza con un botón directo
  en el diagnóstico.

- **R13 (margen intersede)** — Recomendación: bajar
  `margen_min_intersede_minutos` (por ejemplo de 30 a 15 o 0). El
  diagnóstico indica cuántos pares están efectivamente en riesgo
  con el margen actual.

- **R4 (doble asignación)** — Es la más difícil de accionar porque
  requiere agregar aulas al catálogo o mover horarios del
  cronograma. El diagnóstico apunta a la franja saturada y a la
  cantidad de aulas del tipo requerido en la unión de sedes
  admisibles.

- **R5 (partición teoría / lab)** — Cuando la causa es real (no
  falso positivo), indica que las horas declaradas por la materia
  no cierran con las duraciones de los horarios cargados en el
  cronograma. Se arregla en Materias → editar → horas de teoría /
  laboratorio o ajustando los horarios.

- **R6 (consistencia tipo ↔ pool)** — Cuando la causa es real,
  indica que un horario con `tipo_clase = ⊥` no tiene ni aula
  teórica ni laboratorio compatible disponible. Se arregla
  agregando laboratorios compatibles a la materia.

### 5.3 Combinaciones de rescate

Cuando ninguna regla individual rescata al modelo, la UI muestra
"⚠️ No se pudo identificar una causa única" y por debajo aparece
un bloque **"Combinaciones que rescatan"**. Se probaron pares de
relajaciones:

- Cada grupo DURO → BLANDO **combinado con** desactivar R14.
- Cada grupo DURO → BLANDO **combinado con** poner margen intersede
  en 0.

Cada combinación viene ordenada por menor impacto (el grupo con
menos materias en el plan primero) para facilitar la elección. El
costo del análisis está acotado por `CAP_PRUEBAS = 40`
combinaciones.

**Cuándo ocurre esto**: típicamente cuando el problema es
saturación combinada entre un grupo DURO estricto y un margen
intersede alto, o entre un grupo DURO y R14 activo. Rara vez
requiere relajar tres o más restricciones simultáneamente.

### 5.4 Flujo recomendado ante `infeasible`

1. Leer la **causa principal** que reporta el veredicto.
2. Si es R10, mirar los **grupos de rescate** y pasar el que menos
   materias afecte a BLANDO.
3. Si es R14, apagar el toggle.
4. Si es R13, bajar el margen.
5. Si no hay causa individual, mirar las **combinaciones** y
   aplicar la de menor impacto.
6. Re-correr. Si el veredicto sigue siendo `infeasible`, iterar
   con la segunda opción o combinar dos relajaciones.

**Regla práctica**: relajar de a una a la vez. Cambiar varios
parámetros simultáneamente hace que sea difícil identificar cuál
fue el que resolvió.

---

## 6. Ediciones manuales y consistencia con el LP

El operador puede fijar manualmente el aula de un horario desde
distintos puntos de la UI (Cronogramas, Detalle del plan, Aulas
por sede). Cuando lo hace, el horario queda marcado con
`HorarioDB.aula_asignada_manualmente = True` — R11 en el planteo.

### 6.1 Toggle "Respetar ediciones manuales"

En el panel del asignador está el toggle **"Respetar ediciones
manuales"** (default On). Con On, las aulas manuales quedan fijas
como restricción dura R11. Con Off, el LP las reasigna libremente y
borra el flag manual.

El flujo típico es dejarlo On: las decisiones manuales del operador
son fuente de verdad para el LP. Se pasa a Off sólo cuando se
quiere que el LP haga una reasignación completa desde cero (por
ejemplo, después de cambios grandes en el catálogo o en el
cronograma).

### 6.2 Colisiones de aula al editar un horario

Cuando el operador cambia el aula de un horario manualmente y esa
aula ya está ocupada por otro horario en la misma franja, la UI
detecta la colisión y ofrece un panel para resolverla:

- **Ver quién ocupa el aula** con el otro horario en conflicto.
- **Liberar el otro horario** (poner `aula_id = None`) con un botón
  directo, dejando que el LP lo reasigne en la próxima corrida.
- **Cancelar la edición** y buscar otra aula.

Este panel aparece en tres lugares:

- Detalle del plan → editar horario del grilla → preview de impacto.
- Detalle del plan → editar horario desde materia.
- Aulas por sede → cronograma del aula → editar horario.

Todas comparten el mismo componente (`horario_edit_shared.py`) para
mantener el flujo idéntico.

### 6.3 Badge "manual" en el detalle del plan

Los horarios con `aula_asignada_manualmente = True` aparecen con un
badge visual "manual" en el expander correspondiente. Esto sirve
para distinguirlos rápidamente de los horarios que el LP resolvió
automáticamente.

### 6.4 Pin apunta a un aula incompatible

Si el aula pinneada dejó de ser compatible con el horario (cambió
el tipo del aula, la sede quedó fuera de las admisibles del grupo
en modo DURO, etc.), la corrida devuelve infactibilidad estructural
en R11. La UI reporta el pin problemático y sugiere dos acciones:

- **Editar el horario** para elegir un aula compatible.
- **Desmarcar el pin** (bajar el flag `aula_asignada_manualmente`)
  y dejar que el LP asigne libremente.

### 6.5 Saneamiento de horarios virtuales stale

Cuando un horario era presencial en una corrida previa y se cambia
a virtual antes de la siguiente corrida, el LP no lo incluye en su
modelo (los virtuales no participan de las variables `x[h, a]`).
Sin saneamiento activo, el `aula_id` viejo quedaría stale y
generaría falsas colisiones en las vistas de aula.

`apply_solution` recibe el conjunto `no_ocupa_aula_ids` de los
horarios que dejaron de ocupar aula y libera activamente su
`aula_id` (lo pone en `None` y baja `aula_asignada_manualmente`).
Esto se propaga a las clases puntuales del plan. El operador no
tiene que hacer nada — se hace en cada corrida.

---

## 7. Excepciones de conflicto ignorado

`IgnoredConflictDB` es una tabla que registra pares de materias que
la validación del plan **ignora** para el chequeo de solapamiento
horario. Se usa cuando en la práctica una comisión de la materia A
y una de la materia B nunca son cursadas por el mismo alumno — por
ejemplo, materias homónimas de distintos años del plan.

### 7.1 Cuándo agregar una excepción

Sólo cuando el conflicto es formalmente reportado por la
validación pero **operativamente falso**. Un caso típico: dos
materias con nombres similares que aparecen en dos años distintos
del plan y comparten franja horaria en las comisiones actuales.
Los alumnos que cursan una no cursan la otra porque están en
momentos distintos del plan.

**Cuándo NO agregar una excepción**: si el conflicto es entre
materias que un alumno podría cursar simultáneamente (por ejemplo
recursando), la excepción esconde un problema real. Preferir mover
comisiones o ajustar horarios.

### 7.2 Alcance de la excepción

Las excepciones **sólo se aplican al chequeo de solapamiento**. El
chequeo de intersede (R13, R13-camino) las **ignora**: el traslado
físico entre sedes es un problema independiente de qué alumnos
cursen qué. Un alumno que teóricamente no cursa las dos materias
igual puede necesitar el traslado, por lo que la excepción no
aplica.

### 7.3 Cómo se gestionan

Las excepciones se agregan y quitan desde el panel de validación
del plan, en la sección de conflictos detectados. Cada conflicto
tiene un botón "Ignorar este par" que crea el registro; los
ignorados aparecen en una lista separada con un botón para quitar
la excepción.

### 7.4 Auto-limpieza de excepciones stale

Cuando el plan de estudio cambia y una materia deja de coexistir
con la otra en algún grupo curricular `(carrera, año, cuatri)`, la
excepción registrada queda huérfana. `cleanup_stale_ignored_pairs`
la limpia automáticamente en la próxima validación del plan
(`validate_plan`) y reporta la limpieza al usuario en el summary,
así el operador sabe qué pares dejaron de aplicar.

---

## 8. Panel de resultado: cómo se lee

El panel de resultado del asignador vive en Planes → Aulas debajo
del panel de configuración. Se compone de varios bloques que
aparecen según el estado de la corrida.

### 8.1 📋 Veredicto de la corrida

Ya descripto en § 4. Es el primer bloque que aparece. En el
expander "Restricciones activas" se ve la config completa.

### 8.2 Diagnóstico cruzado (sólo `infeasible`)

Descripto en § 5. Aparece sólo cuando el veredicto es `infeasible`
(no `infeasible_estructural`). Lista la causa principal, los grupos
de rescate (si R10 es la culpable) y las combinaciones de rescate
(si ninguna regla individual funciona).

### 8.3 Bloqueos estructurales (sólo `infeasible_estructural`)

Aparece cuando el chequeo pre-solve detectó bloqueos. Cada bloqueo
viene con:

- **Regla** (R1, R3+R4, R5, R11, R13, R13-camino, compat-pigeonhole,
  compat-hall).
- **Descripción** en lenguaje natural.
- **Entidades involucradas** (horarios, materias, aulas, franjas).
- **Sugerencia de acción** concreta.

### 8.4 Horarios asignados

Tabla con todos los horarios asignados en la corrida. Columnas:

- Materia, comisión, día, hora inicio y fin.
- Aula asignada (con badge "manual" si aplica).
- Sede.
- Tipo resuelto (`teoria` / `laboratorio` / `⊥`).
- Inscriptos esperados vs capacidad.
- Sobrecupo (`over`) y subutilización (`under`).
- Flag "sede alternativa" si el grupo corría en BLANDO y el aula
  quedó en una sede distinta de la preferida.

### 8.5 Horarios fuera de sede preferida

Expander que lista los horarios cuyo grupo corría en BLANDO y
terminaron en una sede alternativa. Cada uno muestra la sede
preferida, la sede efectiva y una razón hipotética (típicamente
capacidad o combinación con R14). Sirve para auditar rápido el
impacto de la preferencia blanda.

### 8.6 Mapa de saturación

Independiente de la corrida del LP. Puede mirarse antes de correr
para prevenir infactibilidades, o después para comparar la
solución contra la demanda estructural.

Cada celda del mapa (sede × día × franja × categoría teoría / lab)
tiene **cuatro vistas** seleccionables desde un radio button:

- **Dura**. Horarios cuya única sede admisible es ésta. Si `dura >
  oferta`, es infactibilidad segura — configurable en Materias →
  Grupos de materias.
- **Preferida**. Horarios cuya sede preferida es ésta (primera del
  grupo BLANDO o única del DURO). Si `preferida > oferta`, el LP
  desplaza a alternativas.
- **Máxima**. Horarios que **podrían** caer aquí (unión de
  admisibles). Muestra el margen del LP.
- **Total sin sede**. Cota inferior global. Si supera oferta
  agregada, el plan no cabe.

Además, para las celdas de laboratorio hay un sub-control **Oferta
de labs a considerar** con dos opciones:

- **Todo el catálogo** (default). Compara demanda contra todas las
  aulas de laboratorio de la sede.
- **Sólo compatibles**. Compara demanda contra las aulas
  compatibles con las materias con demanda en la celda. Detecta
  pigeonhole y Hall — las celdas Hall-violadoras se marcan con ⚠️.

### 8.7 Panel de calidad (en Planes → Detalle)

Vive en la página Detalle del plan (no en Aulas). Muestra 4
familias de métricas de la última corrida:

- **Cobertura**: asignados / totales, sede preferida / alternativa,
  comisiones completas.
- **Ajuste al forecast**: sobrecupo total, subutilización total,
  ratio promedio / mediana / P90, peor caso.
- **Uso del catálogo**: aulas usadas / ociosas, concentración por
  sede.
- **Estado del LP**: valor de la función objetivo, tiempo del
  solver, ediciones manuales respetadas, traslados intersede.

Se computa a partir de `HorarioDB.aula_id` + forecast al momento
de abrir la vista, por lo que refleja el estado vigente aunque no
se haya corrido el LP recientemente.

---

## 9. Persistencia de corridas y multi-pestaña

### 9.1 `LPRunDB` como registro completo

Cada corrida se persiste como un registro `LPRunDB` con:

- Referencia al plan (`plan_cursada_id`), fecha de corrida
  (`run_at`), fecha desde propagación (`fecha_desde`).
- Copia de todos los parámetros de la config (`lambda_over`,
  `lambda_under`, `tol_over`, `tol_under`, `timeout_seconds`,
  `respetar_ediciones_manuales`, `activar_alpha`, `lambda_sede_pref`,
  `margen_min_intersede_minutos`, `strict_r5`,
  `forzar_misma_sede_por_comision`).
- Resultado agregado: `status`, `objective_value`, cantidad de
  horarios asignados / reasignados, `solver_seconds`,
  `error_message`.
- **`details_json`** con la solución completa: lista de horarios
  asignados con aula y tipo resuelto, diagnóstico estructural, IIS
  si corrió, veredicto humano-legible, modos por grupo, y las
  restricciones activas de la corrida.

### 9.2 Prefill del panel con la última corrida

Al abrir Planes → Aulas, el panel del asignador se **prefill** con
los parámetros de la última corrida del plan. Esto permite iterar
sobre una misma configuración sin re-configurar todo cada vez.

El prefill es **idempotente por-plan**: se apoya en un
*fingerprint* calculado desde la última corrida en la base. Si el
usuario cambia parámetros en la UI y no corre, los cambios se
persisten en `session_state`. Al volver a apretar el botón, la
corrida usa los valores del panel (no los del prefill).

### 9.3 Advertencia sobre pestañas múltiples

Cuando el operador tiene varias pestañas abiertas del mismo plan
(por ejemplo, una en el panel de asignación y otra en Materias),
cada pestaña mantiene su propio `session_state`. Al apretar botones
en una, la otra puede estar mostrando estado desactualizado.

El prefill del panel se re-hidrata desde la base al recargar la
página. Es decir: si en otra pestaña se agregó una corrida nueva,
al refrescar la pestaña actual el panel se hidrata con los últimos
parámetros de la base.

**Recomendación operativa**: cerrar pestañas viejas antes de
trabajar sobre el plan. Si aparecen inconsistencias entre lo que
muestra la UI y lo que hay en la base, refrescar la página fuerza
la re-hidratación.

### 9.4 Historial de corridas

El panel de asignación muestra siempre la corrida más reciente,
pero se pueden consultar corridas anteriores (a modo de auditoría)
desde el panel de historial que lista todas las `LPRunDB` del
plan con su fecha y su status. Es útil para:

- Reproducir una corrida vieja: leer sus parámetros y volver a
  correr con esa config.
- Comparar dos corridas: ver cómo cambió el objetivo o la
  distribución de sedes al ajustar parámetros.
- Auditar la evolución de la infactibilidad a medida que se
  corregían datos.

---

## 10. Troubleshooting común

### 10.1 El LP dice `infeasible_estructural`, ¿qué reviso?

Leer los bloqueos que reporta el veredicto en orden de aparición.
Cada bloqueo tiene una regla y una descripción concreta. Las causas
típicas:

- **R1 con "sin aula compatible por R10"**: la materia del horario
  tiene un grupo con set duro vacío o con sedes donde no hay aulas
  del tipo requerido. Revisar en Materias → Grupos de materias.
- **R1 con "sin aula compatible por tipo"**: la materia declara
  laboratorio pero no tiene ninguna aula en `MateriaLaboratorioDB`.
  Revisar en Aulas → laboratorio → "Materias que usan este
  laboratorio".
- **R5 con "particion imposible"**: las horas declaradas por la
  materia no cierran con las duraciones de los horarios cargados
  en el cronograma. Revisar Materias → editar → horas de teoría y
  laboratorio, o el cronograma.
- **R11 con "pin incompatible"**: un horario tiene aula manual que
  ya no cumple las restricciones. Desmarcar o reasignar.
- **R13 con "pares intersede"**: dos horarios contiguos de la misma
  comisión sin sede común factible. Bajar margen o cambiar
  cronograma.
- **R13-camino con "sin combinación viable"**: no existe
  combinación de comisiones que un alumno de la carrera-año-cuatri
  pueda cursar sin conflictos. Revisar horarios de las materias
  involucradas.

### 10.2 El LP dice `infeasible` sin bloqueos estructurales, ¿qué hago?

Leer el diagnóstico cruzado (§ 5). La UI recomienda una acción
concreta. Regla general: aplicar la recomendación **menos
invasiva** primero (grupo con menos materias a BLANDO, apagar R14,
bajar margen).

### 10.3 El LP resolvió pero muchos horarios quedaron en sede alternativa

Revisar el mapa de saturación en vista **preferida** y **máxima**:

- Si la sede preferida está muy saturada, es un problema de
  capacidad — hay que sumar aulas o mover horarios.
- Si la máxima no está saturada, es que otras restricciones (R13,
  R14) empujaron a alternativas. Revisar si conviene relajarlas.

También revisar el expander **"Horarios fuera de sede preferida"**
del panel de resultado. Lista uno por uno con razón hipotética.

### 10.4 El LP tarda mucho

- Subir `timeout_seconds` en la configuración avanzada.
- Bajar cantidad de grupos BLANDO (menos flexibilidad = menos
  búsqueda).
- Apagar R14.
- Bajar `margen_min_intersede_minutos`.
- Revisar si hay bloqueos estructurales que estén generando
  búsqueda inútil (correr chequeo pre-solve primero).

### 10.5 Cambié algo en Materias / Aulas y el panel no refleja el cambio

El panel toma los parámetros de la última corrida al abrir la
página. Los cambios en Materias, Aulas o grupos afectan a la
**próxima** corrida, no a la última corrida cacheada. Basta con
volver a apretar "Correr asignador" para que el LP use los datos
actualizados.

### 10.6 El detalle del plan muestra "Sin aula" pero yo ya asigné

Si el aula fue asignada manualmente y no se corrió el LP después,
la asignación ya está en `HorarioDB.aula_id`. Si aparece "Sin
aula" en la vista, chequear:

- Que el horario no esté en modalidad virtual (`resolve_virtual`).
  Los virtuales aparecen sin aula por diseño.
- Que el filtro de la vista no esté ocultando la fila.
- Que la última corrida del LP no haya sobrescrito la asignación
  (revisar el badge "manual" en el expander).

### 10.7 Aparecen colisiones fantasma en el cronograma de un aula

Si el operador cambió un horario a virtual sin correr el LP
después, el `aula_id` viejo queda stale. En la próxima corrida el
saneamiento automático (§ 6.5) los libera. Alternativa manual:
editar el horario y limpiar la asignación.

### 10.8 Cambié el forecast de inscriptos y la solución no refleja el cambio

Los cambios de forecast recién impactan al correr de nuevo el
asignador. El forecast entra al LP como parámetro `insc(h)` — no
se recalcula automáticamente. Volver a apretar "Correr asignador".

### 10.9 El chequeo dice verde pero el LP da infactible

Es raro pero puede pasar por combinaciones inusuales que el chequeo
estructural no captura (por ejemplo, saturación combinada entre R13
y R10 muy específica). El diagnóstico cruzado post-solve va a
identificar la causa. Si aparece "combinaciones que rescatan", la
recomendación de menor impacto es la que hay que probar primero.

### 10.10 Quiero comparar dos configuraciones sin perder la corrida anterior

Cada corrida se persiste como `LPRunDB` con snapshot completo de
parámetros. Para comparar:

1. Correr con la config A. Anotar mentalmente el objetivo y las
   métricas de calidad.
2. Cambiar parámetros. Correr con la config B.
3. Consultar el historial de corridas (§ 9.4) para ver ambos
   registros lado a lado.

No hace falta guardar nada manualmente. Los `LPRunDB` viejos no se
borran salvo que el operador los elimine explícitamente.

---

## Referencias cruzadas

- **Planteo formal completo**: `project/1. Diseño/asignacion-aulas-LP.md`.
- **Validaciones del plan y camino de cursada**: `project/2.
  Desarrollo/VALIDACIONES.md`.
- **Recursado y modalidad virtual**: `project/2. Desarrollo/RECURSADO_Y_VIRTUAL.md`.
- **Implementación por servicio**: `project/2. Desarrollo/ASIGNACION_IMPL.md`.
- **Métricas de calidad y catálogo de indicadores**: § 8.7 y el
  documento de diseño del panel de calidad.
