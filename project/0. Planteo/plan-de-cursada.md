# Plan de Cursada — Definicion Conceptual

> **Fecha**: 2026-04-19 (revisado 2026-06-03).
> **Estado**: Documento de planteo. Complementa
> [`modelo-er.md`](modelo-er.md) (modelo conceptual),
> [`1. Diseño/modelo-planificacion-cursada.md`](../1.%20Diseño/modelo-planificacion-cursada.md)
> (modelo tecnico implementado),
> [`2. Desarrollo/WORKFLOW.md`](../2.%20Desarrollo/WORKFLOW.md)
> (flujo end-to-end del usuario) y
> [`2. Desarrollo/VALIDACIONES.md`](../2.%20Desarrollo/VALIDACIONES.md)
> (validaciones del sistema en cada capa).

---

## 1. ¿Que es un Plan de Cursada?

Un **Plan de Cursada** es un escenario de planificacion que describe como se van a dictar
todas las materias de un ciclo lectivo: cuantas comisiones tiene cada materia, que horarios
tiene cada comision, y (en etapas futuras) en que aula se dicta cada clase.

Es el artefacto central del sistema — el punto de convergencia entre los datos de entrada
(cronogramas de horarios) y los resultados del proceso (asignacion de aulas y generacion
de clases con fecha).

### Diferencia con el Cronograma

| Aspecto | Cronograma (Schedule) | Plan de Cursada |
|---------|----------------------|-----------------|
| **Naturaleza** | Datos crudos de entrada | Escenario de planificacion derivado |
| **Origen** | Archivo Excel/CSV cargado desde la web de la facultad | Generado a partir de un cronograma, con edicion del usuario |
| **Contenido** | Filas: materia + dia + hora (+ comision opcional) | Comisiones formales + horarios por comision + clases con fecha |
| **Persistencia** | `ScheduleDB` + `ScheduleEntryDB` | `PlanificacionCursadaDB` + `ComisionDB` + `HorarioDB` + `ClaseDB` |
| **Editable** | Si, via prevalidacion (Phase 2) | Si, via tab Detalle del Plan |
| **Multiplicidad** | Varios cronogramas por ciclo (versiones) | Varios planes por ciclo (escenarios), pero solo 1 activo |
| **Rol** | Input del proceso | Output del proceso / artefacto gestionable |

### Analogia

Si el cronograma es el "boceto" de los horarios que llega desde las autoridades de la
facultad, el plan de cursada es el "plano ejecutivo" que organiza esos horarios en
comisiones concretas, asigna clases a fechas del calendario, y eventualmente asigna
aulas a cada clase.

---

## 2. Componentes de un Plan de Cursada

Un plan de cursada se compone jerarquicamente:

```
PlanificacionCursada (escenario completo para un ciclo)
│
├── Comision (grupo de alumnos para una materia)
│   ├── materia_codigo (referencia a la materia del catalogo)
│   ├── numero (1, 2, 3... dentro de la materia)
│   ├── comision_key (clave plan-agnostica para comparacion entre planes)
│   ├── cupo (capacidad maxima de alumnos)
│   │
│   └── Horario (patron semanal recurrente)
│       ├── dia (Lunes, Martes, ...)
│       ├── hora_inicio, hora_fin
│       └── codigo_materia (denormalizado)
│
└── Clase (instancia individual con fecha concreta)
    ├── fecha (2026-04-21, 2026-04-28, ...)
    ├── hora_inicio, hora_fin (copiados del horario)
    ├── executed (si la clase ya ocurrio)
    └── aula_id (asignada por algoritmo, nullable)
```

### Relaciones clave

- Un plan pertenece a exactamente un **ciclo** y referencia al **cronograma** del que fue generado.
- Las **comisiones** son componentes exclusivos del plan (composicion, no existen fuera de uno).
- Los **horarios** son patrones semanales bajo una comision (ej: "Lunes 8:00-10:00").
- Las **clases** son instancias concretas generadas expandiendo cada horario sobre las fechas del ciclo.
- Solo puede haber **un plan activo por ciclo** en todo momento.

---

## 3. Ciclo de Vida

El plan de cursada atraviesa **tres etapas** claramente separadas en su ciclo de vida,
cada una con un proposito distinto y restricciones propias sobre que se puede modificar.

### 3.1 Etapa 1 — Carga y Prevalidacion

**Proposito**: Transformar los datos crudos del cronograma (Excel/CSV) en una
estructura revisada y corregida, lista para convertirse en plan.

```
1. CARGA          Importar cronograma desde archivo (Schedule + ScheduleEntries)
                  Resolver codigos Guarani, detectar errores de parseo
       ↓
2. PREVALIDACION  Phase 1: Verificar cobertura de materias del plan de estudio
                  Phase 2: Asignar comisiones, marcar tipo de clase (teorica/lab),
                           validar consistencia de horas, editar horarios
```

**Que se puede modificar**: Todos los datos del schedule — horarios, comisiones
asignadas, tipo de clase (teorica/laboratorio), horas semanales de la materia, etc.
El cronograma es mutable hasta que se genera el plan.

**Salida**: Un `ScheduleDB` con sus `ScheduleEntryDB` limpios, con asignacion de
comisiones y tipos de clase validados.

### 3.2 Etapa 2 — Generacion del Plan Inicial

**Proposito**: Construir la estructura jerarquica formal del plan a partir del
schedule prevalidado. Esta es la "foto inicial" del plan.

```
3. GENERACION     Crear PlanificacionCursada + Comisiones + Horarios
                  (propaga tipo_clase de ScheduleEntry a Horario)
       ↓
4. EDICION        Ajustar comisiones, horarios, cupos en el tab Detalle del plan
                  (propaga cambios a la estructura ya generada)
       ↓
5. VALIDACION     Verificar factibilidad:
                  - conflictos horarios por carrera
                  - cobertura de materias
                  - materias virtuales
                  - compatibilidad materia-laboratorio
```

**Que se puede modificar**: La estructura del plan (agregar/quitar comisiones,
modificar horarios, cupos, tipos de clase). Los cambios afectan el plan pero no
tocan todavia las clases individuales porque aun no fueron generadas.

**Salida**: Un `PlanificacionCursadaDB` validado, listo para activar. Pueden
coexistir multiples planes en estado "borrador" para el mismo ciclo (escenarios
alternativos).

### 3.3 Etapa 3 — Implementacion y Ajustes

**Proposito**: Activar un plan, generar las clases individuales con fecha, asignar
aulas, y gestionar excepciones puntuales durante la cursada.

```
6. ACTIVACION     Marcar el plan como activo (desactiva otros del mismo ciclo)
       ↓
7. GEN. CLASES    Expandir horarios en ClaseDB con fecha concreta
                  (propaga tipo_clase de Horario a Clase)
       ↓
8. ASIG. AULAS    Asignar aulas a clases:
                  - clases teoricas → aulas teoricas (aulas normales)
                  - clases laboratorio → aulas laboratorio (segun compatibilidad
                    definida en MateriaLaboratorioDB)
       ↓
9. AJUSTES        Durante la cursada, modificaciones puntuales a clases futuras:
                  - cambiar tipo de clase (ej: marcar clase teorica como lab)
                  - cambiar aula asignada (reserva puntual de laboratorio)
                  - cancelar/reprogramar clases
                  - respetando restricciones ya impuestas
```

**Que se puede modificar**: Solo clases individuales a futuro (fecha > hoy). Las
clases ya ejecutadas (`executed=True`) son permanentes. Los cambios deben
respetar las validaciones del plan. Si un ajuste hace inviable alguna restriccion
(ej: el laboratorio que se quiere reservar choca con otra clase), el sistema debe
indicarlo antes de aplicar el cambio.

**Casos de uso tipicos de ajustes**:
- **Reserva de laboratorio**: Materia con clases teoricas semanales que
  ocasionalmente necesita laboratorio. El docente marca una clase especifica como
  tipo "laboratorio" y le asigna un aula de laboratorio. Esto libera el aula
  teorica que tenia asignada para esa fecha.
- **Cambio de aula puntual**: Por motivos operativos (aula no disponible,
  sobrecupo, etc.) se reubica una clase especifica a otra aula.
- **Reprogramacion**: Una clase se mueve a otra fecha/hora por feriado, paro,
  evento especial.

### 3.4 Multiples escenarios

Se pueden generar multiples planes a partir del mismo cronograma (o de diferentes
cronogramas del mismo ciclo) para comparar configuraciones:

- **Plan A**: 2 comisiones para Analisis I, clases de 3h
- **Plan B**: 3 comisiones para Analisis I, clases de 2h

La comparacion se hace via `comision_key`, que es una clave plan-agnostica formada por
`{dictado_codigo}-{numero:03d}`. Permite identificar "la misma comision" entre planes.

### 3.5 Estados de Clase

Las clases derivadas de un plan tienen tres estados posibles:

| Estado | Condicion | Significado |
|--------|-----------|-------------|
| **Borrador** | plan inactivo | Clase propuesta, sin efecto real |
| **Planificada** | plan activo, fecha futura | Clase que va a ocurrir |
| **Ejecutada** | `executed = True` | Clase que ya ocurrio (marca permanente) |

La transicion Planificada → Ejecutada es automatica cuando la fecha/hora de la clase
pasa. Una vez ejecutada, la marca es permanente: no se revierte aunque el plan se
desactive.

---

## 4. Validaciones

Las validaciones se aplican en dos momentos: **antes** de generar el plan (prevalidacion
sobre el cronograma) y **despues** (validacion del plan generado).

### 4.1 Prevalidacion (sobre el cronograma)

Se ejecutan durante la Phase 2 (preview de comisiones) antes de generar el plan:

| Check | Severidad | Descripcion |
|-------|-----------|-------------|
| **Cobertura de materias** | warn | Materias con `Dictado.activo = True` linkeado al ciclo que **no estan en el cronograma** (faltantes). Las extras son materias del cronograma sin dictado activo |
| **h/sem × comisiones = total** | warn | Consistencia entre horas semanales declaradas, cantidad de comisiones y horas totales del cronograma |
| **Horas divisibles** | warn | Que el total de horas se pueda repartir equitativamente entre comisiones |
| **Comisiones equilibradas** | warn | Que todas las comisiones tengan horas similares asignadas |
| **Clases paralelas ≤ comisiones** | error | Que no haya mas clases en el mismo slot horario que comisiones disponibles |
| **Sin comisiones vacias** | warn | Que toda comision tenga al menos una clase |
| **Horas semanales definidas** | warn | Que la materia tenga `horas_semanales` cargado en el catalogo |
| **Particion teoria/lab factible** | error | Para cada comision, las clases pueden dividirse en subconjuntos cuyas duraciones sumen `horas_teoria` y `horas_laboratorio` (subset-sum) |

> **Cambio importante (2026-05)**: la cobertura de materias ya **no** se compara
> contra el `PlanEstudio` directamente, sino contra el set de `DictadoDB.activo = True`
> linkeado al ciclo (ver `modelo-planificacion-cursada.md` § RN15). Esto implica
> que el ciclo debe tener dictados creados antes de prevalidar; si no, la
> prevalidacion se aborta con un mensaje pidiendo ir a **Ciclos → Dictados**.
>
> **Edicion on-the-fly desde la prevalidacion**: el resumen de cobertura
> permite, dentro de cada expander de carrera, **activar dictados** de las
> materias listadas como "no esperadas" (extras con horarios) o
> **desactivar dictados** de las materias listadas como "faltantes" (sin
> horarios pero esperadas). Esto evita ir a otra pestaña a tocar el flag.
>
> **Toggle "excluir virtuales y optativas"**: el resumen tiene un toggle que
> recomputa las metricas excluyendo materias virtuales/optativas (que no
> requieren aula y se coordinan despues), dando una vision mas realista
> del bloque a planificar.

### 4.2 Validacion del plan generado

Se ejecutan sobre el plan ya creado, en el tab Detalle:

| Validacion | Severidad | Descripcion |
|------------|-----------|-------------|
| **Conflictos horarios por carrera** | BLOCKER | Para cada par de materias del mismo grupo curricular (carrera + año + cuatrimestre), verifica que exista al menos un par de comisiones compatible (sin superposicion). Usa algoritmo pairwise por comision |
| **Cobertura del plan** | WARNING | Toda materia con dictado activo tiene al menos 1 comision con horarios |
| **Materias virtuales** | INFO | Lista materias marcadas como virtuales que no necesitan aula fisica |

### 4.3 Validaciones futuras (al asignar aulas)

Estas validaciones se implementaran cuando se incorpore el algoritmo de asignacion:

| Validacion | Descripcion |
|------------|-------------|
| **Capacidad de aula** | `aula.capacidad >= clase.asistencia_esperada` |
| **Unicidad de aula** | No dos clases en la misma aula al mismo tiempo |
| **Sin conflictos de aula** | No hay superposicion horaria en la misma aula dentro del ciclo |

---

## 5. Generacion del Plan — ¿Que significa "generar"?

Generar un plan de cursada es el proceso de transformar las entradas del cronograma
(datos planos) en una estructura jerarquica de comisiones y horarios:

### Entrada
- Un `ScheduleDB` con sus `ScheduleEntryDB` (materia + dia + hora + comision asignada)
- Overrides del usuario: cantidad de comisiones por materia, horas semanales corregidas

### Proceso
1. **Agrupar entries por materia**
2. **Para cada materia**:
   a. Determinar cantidad de comisiones (del override del usuario o derivada automaticamente)
   b. Crear `ComisionDB` con `plan_cursada_id`, `comision_key`, `numero`
   c. Para cada entry de la materia, crear un `HorarioDB` bajo la comision correspondiente
      (la asignacion entry → comision viene del campo `ScheduleEntryDB.comision`)
3. **Crear `PlanificacionCursadaDB`** vinculado al ciclo y al schedule fuente

### Salida
- `PlanificacionCursadaDB` con nombre, ciclo, referencia al schedule
- N `ComisionDB` con materia, numero, cupo
- M `HorarioDB` con dia, hora_inicio, hora_fin, bajo la comision correspondiente

### Nota sobre Clases
Las `ClaseDB` no se generan en este paso. Se generan en un paso posterior ("Generar Clases")
expandiendo cada horario sobre las fechas del ciclo. Esto permite regenerar clases si
cambian los horarios sin tener que recrear todo el plan.

---

## 5.5 Inscriptos esperados — Forecasting + Coeficientes

Para que el LP de asignacion de aulas pueda decidir qué aula corresponde a cada
clase necesita un input clave: **cantidad esperada de alumnos por comisión**.
Ese número se construye en dos pasos:

### Paso 1 — Forecast por (materia, cuatri)

A partir de `InscripcionHistoricaDB` (datos por `(materia, anio, cuatri)`)
proyectamos el próximo punto de la serie temporal. Con datos disponibles
limitados (2022–2025, 3-4 puntos por serie) usamos métodos simples:

- **Media móvil**: promedio de los últimos N puntos (default = todos).
- **Drift**: extrapolación lineal entre primer y último punto (`y_last + slope`).
- **SES** (suavizado exponencial simple): nivel exponencial con `α` auto-calibrado
  por minimización de SSE in-sample.

Las series son por `(materia, cuatri)`: 1C y 2C separadas para cuatrimestrales,
"Anual" como serie propia para anuales (que no tienen 1C/2C). Los métodos
generan en paralelo y el usuario elige el que mejor le parezca; la elección se
persiste en `InscripcionForecastDB` con `(materia_codigo, cuatri, anio_target,
metodo, valor, fecha_calculo)`.

**UI**: pestaña **📈 Inscriptos** → expander de cada materia → sección "🔮 Forecast".
Muestra los métodos disponibles como métricas y un selectbox para elegir el
persistido. Si la serie tiene menos de 2 puntos, solo aparece "media móvil".

### Paso 2 — Coeficiente de asignación por comisión

`ComisionDB.coef_asignacion: float` define qué fracción del forecast total de la
materia le toca a esa comisión. Default uniforme: `1/n` con n comisiones del
mismo dictado en el plan. La suma por materia debe ser ≈1.0 (validación a nivel
service, tolerancia 0.01 por floating point).

**Inscriptos esperados por comisión** = `forecast(materia, cuatri_ciclo, anio) × coef_asignacion`.

Si la materia es anual, se prefiere el forecast con `cuatri='Anual'` por encima
del cuatri del ciclo.

**UI**: pestaña **📊 Planes → 🔍 Detalle** → editor de comisiones. Cada comisión
muestra **Cupo** (capacidad pretendida, legacy), **Coef** (editable, persiste
on-the-fly) y **Esperados** (read-only, calculado). Banner arriba con
"Coef total: X.XX" + botón "Normalizar" cuando la suma no es ≈1.

### Paso 3 — El LP usa `Esperados`

El próximo módulo (asignación de aulas) consume `get_inscriptos_esperados_por_comision(plan_id, anio_target)`
que devuelve `{comision_id: forecast × coef}`. Ese diccionario es el input
"esperados" del LP. Las penalizaciones de sobre/sub-ocupación se calculan contra
estos valores y la `cap[a]` del aula candidata.

Ver formulación completa en `project/1. Diseño/asignacion-aulas-LP.md`.

---

## 6. Tipos de Clase y Laboratorios

Una clase puede ser **teorica** o **de laboratorio**. Esta distincion es relevante
porque cada tipo requiere un tipo distinto de aula:

- **Clase teorica** → Aula teorica (aula comun, cualquiera con capacidad suficiente)
- **Clase laboratorio** → Aula laboratorio (laboratorio especifico, no todos los
  laboratorios son compatibles con todas las materias)

### 6.1 El campo `tipo_clase`

Es un atributo que se propaga desde la carga hasta la clase individual:

```
ScheduleEntry.tipo_clase → Horario.tipo_clase → Clase.tipo_clase
      (carga)                 (generacion)          (expansion)
```

Valores posibles: `"teorica"` (default) o `"laboratorio"`.

El usuario marca el tipo durante la prevalidacion (en la tabla editable). Al
generar el plan, el tipo se copia al `HorarioDB`. Al generar las clases, se copia
a cada `ClaseDB`. En la etapa de implementacion, el tipo de una clase
individual puede modificarse (ver seccion 3.3 — caso "reserva de laboratorio").

### 6.2 Compatibilidad Materia-Laboratorio

No todas las materias pueden dictar clases de laboratorio en cualquier lab. Los
laboratorios tienen equipamiento especifico (ej: lab de informatica, lab de quimica,
lab de electronica) y cada materia requiere uno o mas laboratorios particulares.

Esta compatibilidad se modela como una relacion **M:N sin orden de preferencia**:

```
MateriaLaboratorioDB (tabla link)
├── materia_codigo (FK a MateriaDB)
└── aula_id       (FK a AulaDB donde tipo = "laboratorio")
```

Una materia puede tener 0, 1 o varios laboratorios compatibles. A la hora de
asignar aulas, el algoritmo debe respetar esta restriccion: una clase de
laboratorio de la materia X solo puede asignarse a un lab listado como compatible
con X.

### 6.3 Dos modos de uso del laboratorio

En la practica, las materias usan los laboratorios de dos maneras distintas:

**Modo 1 — Laboratorio fijo semanal**: Algunas materias tienen una clase semanal
de laboratorio ya contemplada en su cronograma (ej: "los lunes 10-12 siempre en
lab"). Se carga con `tipo_clase = "laboratorio"` desde la prevalidacion y se
propaga automaticamente a todas las instancias semanales.

**Modo 2 — Reserva puntual**: La mayoria de las materias no tienen lab todas las
semanas. El uso se determina durante la cursada (ej: "esta semana damos lab").
En estos casos, todas las clases se cargan como teoricas, y durante la etapa de
implementacion el docente/administrador edita una clase individual especifica:
cambia su `tipo_clase` a "laboratorio" y le asigna un aula de laboratorio. Esto
libera el aula teorica que tenia asignada para esa fecha.

El modo 2 requiere que la UI de implementacion permita:
- Editar clases individuales a futuro (no las ya ejecutadas)
- Validar que el laboratorio seleccionado sea compatible con la materia
- Validar que el laboratorio no este ocupado por otra clase en ese dia/hora
- Indicar si el cambio invalida otras restricciones

---

## 7. El Plan de Cursada en el Contexto del Proyecto

El plan de cursada es el artefacto que conecta la **etapa de planificacion** con la
**etapa de asignacion de aulas** (objetivo central del sistema):

```
┌──────────────────────────────────────────────────────────────────┐
│                    ETAPA DE PLANIFICACION                        │
│                                                                  │
│  Cronograma → Prevalidacion → Plan de Cursada → Clases          │
│  (horarios)   (comisiones)    (estructura)       (instancias)    │
└───────────────────────────────┬──────────────────────────────────┘
                                │
                                ▼
┌──────────────────────────────────────────────────────────────────┐
│                    ETAPA DE ASIGNACION (futuro)                  │
│                                                                  │
│  Clases + Aulas + Restricciones → Algoritmo → AsignacionAula    │
│  (demanda)  (oferta) (capacidad)   (solver)    (resultado)       │
└──────────────────────────────────────────────────────────────────┘
```

El sistema debe garantizar que el plan de cursada sea **valido y completo** antes de
pasar a la etapa de asignacion. Las validaciones descriptas en la seccion 4 cumplen
este rol de "gate" entre etapas.

---

## 8. Supuestos y Decisiones de Diseño

| Supuesto/Decision | Justificacion |
|-------------------|---------------|
| Un alumno cursa exactamente una comision por materia | Permite validar conflictos por pares de comisiones en vez de por materia completa |
| El cronograma es dato de entrada, no variable de decision | Los horarios son determinados por las autoridades; el sistema no los optimiza |
| Solo 1 plan activo por ciclo | Simplifica la gestion; los demas planes son escenarios de comparacion |
| Las clases ejecutadas son permanentes | Una vez que una clase ocurrio, su registro no se modifica aunque cambie el plan |
| La asignacion de comisiones se persiste en el schedule | Permite que al re-prevalidar se preserven las asignaciones del usuario |
| Las comisiones son componentes del plan (composicion) | No tienen existencia independiente; se borran al borrar el plan |
| Tipo de clase se propaga por la cadena Entry → Horario → Clase | Permite definir el tipo en la carga y propagarlo automaticamente, manteniendo la posibilidad de sobrescribir individualmente en clases puntuales |
| Compatibilidad materia-laboratorio es M:N sin orden | Las autoridades definen que labs son validos para cada materia; no hay preferencia, cualquier lab compatible es aceptable para el algoritmo |

---

## 9. Glosario Especifico

| Termino | Definicion en este contexto |
|---------|---------------------------|
| **Cronograma** | Conjunto de entries (materia + dia + hora) cargados desde un archivo. Es el input crudo |
| **Prevalidacion** | Proceso de revision del cronograma antes de generar el plan: asignar comisiones, verificar consistencia |
| **Plan de Cursada** | Escenario de planificacion derivado de un cronograma, con comisiones y horarios formales |
| **Comision** | Grupo logico de alumnos dentro de una materia, con horarios propios |
| **Horario** | Patron semanal recurrente (dia + hora_inicio + hora_fin) bajo una comision |
| **Clase** | Instancia concreta de un horario en una fecha especifica del ciclo |
| **Slot paralelo** | Dos o mas entries de la misma materia en el mismo dia y rango horario, indicando comisiones simultaneas |
| **comision_key** | Clave plan-agnostica (`{dictado_codigo}-{numero:03d}`) para comparar la "misma" comision entre planes |
| **tipo_clase** | Atributo que indica si una entry/horario/clase es `"teorica"` o `"laboratorio"`. Determina si requiere aula teorica o aula laboratorio |
| **Aula teorica** | `AulaDB` con `tipo = "teorica"`. Aula comun, sin equipamiento especifico. Puede alojar clases teoricas de cualquier materia |
| **Aula laboratorio** | `AulaDB` con `tipo = "laboratorio"`. Aula con equipamiento especifico (informatica, quimica, etc.). Solo alojal clases de lab de materias compatibles |
| **Compatibilidad materia-lab** | Relacion M:N (`MateriaLaboratorioDB`) que define que laboratorios acepta cada materia para sus clases de lab |
| **Reserva de laboratorio** | Caso de uso donde se marca una clase individual especifica como `tipo_clase = "laboratorio"` durante la cursada (etapa 3), liberando el aula teorica y asignando un lab compatible |
