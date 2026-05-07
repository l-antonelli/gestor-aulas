# Plan de Cursada — Definicion Conceptual

> **Fecha**: 2026-04-19
> **Estado**: Documento de planteo. Complementa `modelo-er.md` (modelo conceptual) y
> `1. Diseño/modelo-planificacion-cursada.md` (modelo tecnico implementado).

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

### 3.1 Flujo de trabajo

```
1. CARGA          Cargar cronograma desde archivo (Schedule + ScheduleEntries)
       ↓
2. PREVALIDACION  Revisar: materias presentes/faltantes, asignar comisiones,
                  validar consistencia de horas (Phase 1 + Phase 2 en la UI)
       ↓
3. GENERACION     Crear el plan: PlanificacionCursada + Comisiones + Horarios
                  (copiar entries del schedule a horarios bajo comisiones)
       ↓
4. EDICION        Ajustar comisiones, horarios, cupos en el tab Detalle
       ↓
5. VALIDACION     Verificar factibilidad: conflictos horarios por carrera,
                  cobertura de materias, materias virtuales
       ↓
6. ACTIVACION     Marcar el plan como activo (desactiva otros del mismo ciclo)
       ↓
7. GEN. CLASES    Expandir horarios en clases con fecha concreta
       ↓
8. ASIG. AULAS    (Futuro) Ejecutar algoritmo de optimizacion para asignar aulas
```

### 3.2 Multiples escenarios

Se pueden generar multiples planes a partir del mismo cronograma (o de diferentes
cronogramas del mismo ciclo) para comparar configuraciones:

- **Plan A**: 2 comisiones para Analisis I, clases de 3h
- **Plan B**: 3 comisiones para Analisis I, clases de 2h

La comparacion se hace via `comision_key`, que es una clave plan-agnostica formada por
`{dictado_codigo}-{numero:03d}`. Permite identificar "la misma comision" entre planes.

### 3.3 Estados de Clase

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
| **Cobertura de materias** | warn | Materias esperadas por el plan de estudio que no estan en el cronograma |
| **h/sem × comisiones = total** | warn | Consistencia entre horas semanales declaradas, cantidad de comisiones y horas totales del cronograma |
| **Horas divisibles** | warn | Que el total de horas se pueda repartir equitativamente entre comisiones |
| **Comisiones equilibradas** | warn | Que todas las comisiones tengan horas similares asignadas |
| **Clases paralelas ≤ comisiones** | error | Que no haya mas clases en el mismo slot horario que comisiones disponibles |
| **Sin comisiones vacias** | warn | Que toda comision tenga al menos una clase |
| **Horas semanales definidas** | warn | Que la materia tenga `horas_semanales` cargado en el catalogo |

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

## 6. El Plan de Cursada en el Contexto del Proyecto

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

## 7. Supuestos y Decisiones de Diseño

| Supuesto/Decision | Justificacion |
|-------------------|---------------|
| Un alumno cursa exactamente una comision por materia | Permite validar conflictos por pares de comisiones en vez de por materia completa |
| El cronograma es dato de entrada, no variable de decision | Los horarios son determinados por las autoridades; el sistema no los optimiza |
| Solo 1 plan activo por ciclo | Simplifica la gestion; los demas planes son escenarios de comparacion |
| Las clases ejecutadas son permanentes | Una vez que una clase ocurrio, su registro no se modifica aunque cambie el plan |
| La asignacion de comisiones se persiste en el schedule | Permite que al re-prevalidar se preserven las asignaciones del usuario |
| Las comisiones son componentes del plan (composicion) | No tienen existencia independiente; se borran al borrar el plan |

---

## 8. Glosario Especifico

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
