# Modelo de Entidad-Relación del Sistema de Asignación de Aulas

> **⚠️ Nota sobre vigencia**: Este documento representa el **modelo conceptual original (v1)** del
> sistema, elaborado durante la etapa de planteo inicial. Incluye entidades conceptuales como
> `Inscripción`, `Asistencia` y `AsignacionAula` que forman parte del modelo teórico completo
> pero **aún no están implementadas** (fueron diferidas para etapas futuras).
>
> El modelo **efectivamente implementado** se encuentra en:
> - **`1. Diseño/diagrama-entidades.md`** — Diagrama UML de clases con políticas de borrado
> - **`1. Diseño/modelo-planificacion-cursada.md`** — Modelo detallado del flujo Schedule → Plan → Clases
>
> Las diferencias principales entre este modelo conceptual y la implementación son:
> - `AsignacionAulaDB` fue eliminada; la asignación de aula es ahora un campo directo en `ClaseDB.aula_id`
> - `Inscripción`, `Asistencia`, `Alumno` y `Profesor` están fuera de alcance actual
> - Se agregaron `ScheduleDB`, `ScheduleEntryDB`, `PlanificacionCursadaDB` como entidades de gestión
> - El versionado de planes de estudio (`PlanCarreraVersionDB`, `CicloPlanVersionDB`) reemplaza la relación simple Materia↔Carrera

Este documento presenta el modelo conceptual completo del Sistema de Información para la Asignación de Aulas de la Facultad de Ciencias Exactas, Ingeniería y Agrimensura (FCEIA) de la Universidad Nacional de Rosario. El diseño sigue un enfoque de modelado en capas que permite derivar entidades abstractas a partir de las entidades del dominio real.

---

## 1. Introducción al Modelado del Dominio

### 1.1 Enfoque Metodológico

El modelado del sistema se estructura en tres capas conceptuales:

1. **Dominio del Problema (Completo)**: Todas las entidades de existencia real y sus relaciones en el contexto universitario
2. **Dominio del Problema (Delimitado)**: Subconjunto de entidades directamente relevantes para el problema de asignación
3. **Dominio de la Solución**: Entidades abstractas derivadas para gestionar las relaciones complejas

```mermaid
flowchart TB
    subgraph Capas["Arquitectura de Capas del Modelo"]
        direction TB
        C1["🏛️ Dominio del Problema (Completo)<br/>Todas las entidades reales"]
        C2["🎯 Dominio del Problema (Delimitado)<br/>Entidades relevantes para asignación"]
        C3["💡 Dominio de la Solución<br/>Entidades abstractas derivadas"]
    end
    
    C1 -->|"Delimitación<br/>del alcance"| C2
    C2 -->|"Derivación de<br/>abstracciones"| C3
```

### 1.2 Problemática Central

La problemática que motiva este sistema es la **ineficiente asignación de aulas** que se produce debido a:

- La **naturaleza combinatoria elevada** del problema, dada la gran cantidad de asignaturas y aulas disponibles
- La **falta de información** para tomar decisiones informadas previo al inicio de clases
- La **complejidad de las relaciones** entre las entidades del dominio, particularmente la prevalencia de relaciones muchos-a-muchos (M:M)

### 1.3 Objetivos del Sistema

- Optimizar el uso de las aulas disponibles
- Minimizar problemas de falta de capacidad para el dictado de clases
- Maximizar el uso de la capacidad instalada en todo momento
- Permitir ajustes dinámicos durante el ciclo lectivo

---

## 2. Dominio del Problema (Completo)

El primer paso del modelado consiste en identificar todas las entidades de existencia real que intervienen en el contexto universitario. Estas son entidades concretas, no abstracciones de software, y de cuya relación e interacción se desprende la problemática a resolver.

### 2.1 Entidades del Problema Completo

| Entidad | Descripción | Atributos Principales |
|---------|-------------|----------------------|
| **Alumno** | Estudiante inscripto en la facultad | legajo, email, nombre, dni |
| **Materia** | Asignatura académica del plan de estudios | codigo, nombre, cupo, horas_semanales |
| **Comisión** | División de una materia para distribuir alumnos | id, materia_codigo, nombre, numero, cupo |
| **Clase** | Instancia de dictado en un horario específico | id, comision_id, horario_id, dia |
| **Aula** | Espacio físico donde se dictan las clases | codigo, capacidad, tipo |
| **Horario_Cronograma** | Franja horaria del cronograma académico | id, dia_semana, hora_inicio, hora_fin |
| **Profesor** | Docente de la facultad | id, nombre, email, dni |
| **Carrera** | Programa académico de grado | codigo, nombre, titulo_otorgado |
| **Facultad** | Unidad académica | nombre, direccion, telefono |

### 2.2 Diagrama ER del Problema Completo

```mermaid
erDiagram
    ALUMNO {
        string legajo PK
        string email
        string nombre
        string dni
    }
    MATERIA {
        string codigo PK
        string nombre
        int cupo
        int horas_semanales
    }
    PROFESOR {
        string id PK
        string nombre
        string email
        string dni
    }
    AULA {
        string codigo PK
        int capacidad
        string tipo
    }
    HORARIO_CRONOGRAMA {
        string id PK
        string dia_semana
        time hora_inicio
        time hora_fin
    }
    FACULTAD {
        string nombre PK
        string direccion
        string telefono
    }
    CARRERA {
        string codigo PK
        string nombre
        string titulo_otorgado
    }
    COMISION {
        string id PK
        string materia_codigo FK
        string nombre
        int numero
        int cupo
    }
    CLASE {
        string id PK
        string comision_id FK
        string horario_id FK
        string dia
    }

    ALUMNO }o--o{ MATERIA : "inscribe"
    PROFESOR }o--o{ MATERIA : "dicta"
    MATERIA ||--o{ COMISION : "tiene"
    COMISION ||--o{ CLASE : "tiene"
    CLASE }o--|| HORARIO_CRONOGRAMA : "en"
    CLASE }o--|| AULA : "en"
    CARRERA }o--o{ MATERIA : "incluye"
    CARRERA }o--o{ ALUMNO : "cursa"
    FACULTAD ||--o{ AULA : "tiene"
    COMISION }o--o{ PROFESOR : "asignado"
    HORARIO_CRONOGRAMA }o--o{ AULA : "disponible"
```

### 2.3 Análisis de Relaciones M:M

La complejidad del problema radica en la abundancia de relaciones muchos-a-muchos entre las entidades:

| Relación | Descripción | Implicancia |
|----------|-------------|-------------|
| **Alumno ↔ Materia** | Un alumno cursa muchas materias; una materia tiene muchos alumnos | Requiere gestión de inscripciones |
| **Profesor ↔ Materia** | Un profesor dicta muchas materias; una materia puede tener varios profesores | Asignación de docentes |
| **Materia ↔ Aula** | Una materia puede darse en distintas aulas; un aula aloja muchas materias | Relación indirecta via Clase |
| **Materia ↔ Horario** | Una materia tiene varios horarios; en un horario se dictan muchas materias | Cronograma complejo |
| **Horario ↔ Aula** | Toda aula está disponible en todos los horarios (a priori) | Espacio de búsqueda amplio |
| **Carrera ↔ Materia** | Una carrera tiene muchas materias; una materia puede pertenecer a varias carreras | Plan de estudios compartido |
| **Carrera ↔ Alumno** | Un alumno puede cursar varias carreras; una carrera tiene muchos alumnos | Múltiples inscripciones |

Estas relaciones M:M dificultan:
- La gestión directa de asignaciones
- El seguimiento de inscripciones y asistencia
- La optimización de recursos

---

## 3. Dominio del Problema (Delimitado)

### 3.1 Justificación de la Delimitación

No todas las entidades del dominio completo son relevantes para el diseño de la solución de asignación de aulas. La delimitación se basa en identificar las entidades que son **causa directa** de la problemática.

#### Entidades Excluidas y Justificación

| Entidad | Razón de Exclusión |
|---------|-------------------|
| **Profesor** | No afecta la capacidad ni disponibilidad de aulas. Tendrá un rol de gestión en el sistema, pero no interviene en el algoritmo de asignación. |
| **Carrera** | La asignación es por Clase, no por Carrera. No introduce complejidad adicional al problema de asignación según los parámetros definidos. |
| **Facultad** | Se asume una única sede (Pellegrini) para el alcance del proyecto. Las aulas son de uso exclusivo de la FCEIA. |
| **Relación Materia↔Aula** | Redundante: la asignación real es Clase↔Aula, no Materia↔Aula. Las materias no tienen aulas fijas. |

#### Entidades Reincorporadas al Modelo

Sin embargo, para efectos de validación y gestión académica, se reincorporan al modelo:

| Entidad | Razón de Inclusión |
|---------|-------------------|
| **Carrera** | Permite validar que los horarios de materias del mismo año/cuatrimestre no se superpongan (factibilidad para alumnos) |
| **Profesor** | Permite asignar docentes a comisiones y clases para gestión académica |
| **Ciclo** | Período lectivo que contextualiza las asignaciones temporalmente |
| **Dictado** | Instancia de una materia en un ciclo específico, permite manejar materias anuales vs cuatrimestrales |

### 3.2 Entidades del Problema Delimitado

| Entidad | Atributos | Descripción |
|---------|-----------|-------------|
| **Alumno** | legajo, email, nombre, dni | Estudiante inscripto en la facultad |
| **Materia** | codigo, nombre, cupo, horas_semanales, periodo, anio_carrera, cuatrimestre_carrera | Asignatura académica con ubicación en el plan de estudios |
| **Comisión** | id, materia_codigo, dictado_id, nombre, numero, cupo | División de una materia para un dictado específico |
| **Carrera** | codigo, nombre, titulo_otorgado, duracion_anios | Carrera universitaria |
| **Profesor** | id, nombre, email, dni | Docente de la facultad |
| **Ciclo** | id, anio, numero, fecha_inicio, fecha_fin | Período lectivo (cuatrimestre) |
| **Dictado** | id, materia_codigo, ciclo_id, tipo, activo | Instancia de materia en un ciclo |
| **Aula** | id, sede, nombre, capacidad, tipo, descripcion | Espacio físico |
| **Horario_Cronograma** | id, dia_semana, hora_inicio, hora_fin | Franja horaria |
| **Clase** | id, comision_id, horario_id, profesor_id, dia | Dictado de una comisión en un horario |

### 3.3 Diagrama ER del Problema Delimitado

```mermaid
erDiagram
    ALUMNO {
        string legajo PK
        string email
        string nombre
        string dni
    }
    MATERIA {
        string codigo PK
        string nombre
        int cupo
        int horas_semanales
        string periodo "anual | cuatrimestral"
        int anio_carrera "1-6"
        int cuatrimestre_carrera "1-2"
    }
    CARRERA {
        string codigo PK
        string nombre
        string titulo_otorgado
        int duracion_anios
    }
    PROFESOR {
        string id PK
        string nombre
        string email
        string dni
    }
    CICLO {
        string id PK "ej: 2024-1C"
        int anio
        int numero "1 o 2"
        date fecha_inicio
        date fecha_fin
    }
    DICTADO {
        string id PK
        string materia_codigo FK
        string ciclo_id FK
        string tipo "normal | recursado | intensivo"
        bool activo
    }
    COMISION {
        string id PK
        string materia_codigo FK
        string dictado_id FK
        string nombre
        int numero
        int cupo
    }
    AULA {
        string id PK
        string sede
        string nombre
        int capacidad
        string tipo
        string descripcion
    }
    HORARIO_CRONOGRAMA {
        string id PK
        string dia_semana
        time hora_inicio
        time hora_fin
    }
    CLASE {
        string id PK
        string comision_id FK
        string horario_id FK
        string profesor_id FK
        string dia
    }

    %% Relaciones de Materia
    MATERIA ||--o{ COMISION : "tiene"
    MATERIA ||--o{ DICTADO : "tiene"
    MATERIA }o--o{ CARRERA : "pertenece"
    
    %% Relaciones de Dictado y Ciclo
    DICTADO }o--|| CICLO : "en"
    DICTADO ||--o{ COMISION : "tiene"
    
    %% Relaciones de Comisión
    COMISION ||--o{ CLASE : "tiene"
    COMISION }o--o{ PROFESOR : "asignado"
    
    %% Relaciones de Clase
    CLASE }o--|| HORARIO_CRONOGRAMA : "en"
    CLASE }o--o| PROFESOR : "dicta"
    CLASE }o--|| AULA : "asignada en"
    
    %% Relaciones de Alumno (via entidades de solución)
    ALUMNO }o--o{ COMISION : "inscripto en"
    
    %% Relaciones de Aula y Horario
    HORARIO_CRONOGRAMA }o--o{ AULA : "disponible"
```

### 3.4 Ejes Principales del Problema

La delimitación se justifica en función de los tres ejes principales del problema de asignación:

```mermaid
flowchart LR
    subgraph Eje1["1️⃣ ASISTENCIA"]
        A1[ALUMNO] -->|"se inscribe"| A2[MATERIA]
        A2 -->|"asiste a"| A3[CLASE]
    end
    
    subgraph Eje2["2️⃣ ASIGNACIÓN"]
        B1[AULA] -->|"se asigna a"| B2[CLASE]
        B3[MATERIA] -.->|"NO directamente"| B1
    end
    
    subgraph Eje3["3️⃣ DISPONIBILIDAD"]
        C1[CLASE] -->|"tiene asignado"| C2[HORARIO]
        C3["Autoridades"] -->|"determinan"| C2
    end
    
    A3 --> B2
    B2 --> C1
```

1. **En función de la ASISTENCIA**: Un alumno se inscribe a una materia y luego se espera que asista a sus clases. Esta es la principal variable estocástica del problema de optimización.

2. **En función de la ASIGNACIÓN**: Las aulas se asignan a **clases**, no a materias. La clase emerge como el elemento central de organización y gestión de aulas.

3. **En función de la DISPONIBILIDAD**: Las clases tienen asignado un horario del cronograma. Esto viene determinado por las autoridades de la facultad y es un dato de entrada, no una variable de decisión.

---

## 4. Dominio de la Solución

### 4.1 Derivación de Entidades Abstractas

Las entidades del dominio de la solución son **abstracciones** que permiten gestionar las relaciones M:M del dominio del problema de manera efectiva. Estas entidades no tienen existencia física real, sino que son constructos del sistema de información.

```mermaid
flowchart TD
    subgraph Problema["Dominio del Problema"]
        P1["Alumno ↔ Materia<br/>(M:M)"]
        P2["Alumno ↔ Clase<br/>(M:M)"]
        P3["Clase ↔ Aula<br/>(M:M por horario)"]
        P4["Materia ↔ Carrera<br/>(M:M)"]
        P5["Comisión ↔ Profesor<br/>(M:M)"]
    end
    
    subgraph Solucion["Dominio de la Solución"]
        S1["📝 Inscripción"]
        S2["✅ Asistencia"]
        S3["🏫 AsignacionAula"]
        S4["🔗 MateriaCarreraLink"]
        S5["🔗 ComisionProfesorLink"]
    end
    
    P1 -->|"materializa"| S1
    P2 -->|"materializa"| S2
    P3 -->|"materializa"| S3
    P4 -->|"materializa"| S4
    P5 -->|"materializa"| S5
```

### 4.2 Entidades de Solución

| Entidad | Atributos | Relación M:M que Resuelve | Propósito |
|---------|-----------|---------------------------|-----------|
| **Inscripción** | id, alumno_legajo, comision_id, fecha_inscripcion, activa | Alumno ↔ Materia/Comisión | Gestionar inscripciones, calcular demanda esperada |
| **Asistencia** | id, alumno_legajo, clase_id, fecha, presente | Alumno ↔ Clase | Registrar asistencia real, alimentar predicciones |
| **AsignacionAula** | id, clase_id, aula_id, ciclo_id, fecha_asignacion, vigente | Clase ↔ Aula (por Ciclo) | Gestionar asignaciones, detectar conflictos |

### 4.3 Tablas de Enlace (Link Tables)

Para las relaciones M:M que no requieren atributos adicionales significativos, se utilizan tablas de enlace:

| Tabla de Enlace | Atributos | Relación que Resuelve |
|-----------------|-----------|----------------------|
| **PlanEstudio** | id (UUID PK), plan_version_id FK, materia_codigo FK, carrera_codigo FK, anio_plan, cuatrimestre_plan, correlativas | Materia ↔ Carrera (versionada via PlanCarreraVersion) |
| **CicloPlanVersion** | ciclo_id FK+PK, plan_version_id FK+PK | Ciclo ↔ PlanCarreraVersion |
| **ComisionProfesorLink** | comision_id, profesor_id, es_titular | Comisión ↔ Profesor |

> **Nota**: La relacion Materia-Carrera se resuelve mediante `PlanEstudio`, que pertenece
> a una `PlanCarreraVersion` especifica. Esto permite versionar los planes de estudio
> por carrera y asignar versiones a ciclos para determinar que materias se ofrecen.

### 4.4 Justificación de las Entidades de Solución

#### Inscripción
Materializa la relación entre Alumno y Comisión (y por transitividad, Materia). Permite:
- Contar inscriptos por comisión para estimar demanda de capacidad
- Trackear cambios en inscripciones post-inicio de clases
- Calcular la asistencia esperada como input para el algoritmo de asignación

#### Asistencia
Materializa la relación entre Alumno y Clase. Permite:
- Registrar asistencia efectiva (variable estocástica principal del problema)
- Calcular tasas de asistencia históricas por materia, comisión y horario
- Alimentar modelos predictivos de ocupación para optimización futura

#### AsignacionAula
Materializa la relación entre Clase y Aula **dentro del contexto de un Ciclo**. Es el **objetivo central** del sistema:
- Asignar aulas a clases respetando restricciones de capacidad
- Detectar y resolver conflictos de horario dentro del mismo período lectivo
- Permitir reasignaciones dinámicas durante el ciclo lectivo
- El campo `ciclo_id` permite validar que no haya conflictos de aula dentro del mismo período

### 4.5 Diagrama ER Completo de la Solución

```mermaid
erDiagram
    %% Entidades del Problema (gris)
    ALUMNO {
        string legajo PK
        string email
        string nombre
        string dni
    }
    MATERIA {
        string codigo PK
        string nombre
        int cupo
        int horas_semanales
        string periodo
        int anio_carrera
        int cuatrimestre_carrera
    }
    CARRERA {
        string codigo PK
        string nombre
        string titulo_otorgado
        int duracion_anios
    }
    PROFESOR {
        string id PK
        string nombre
        string email
        string dni
    }
    CICLO {
        string id PK
        int anio
        int numero
        date fecha_inicio
        date fecha_fin
    }
    DICTADO {
        string id PK
        string materia_codigo FK
        string ciclo_id FK
        string tipo
        bool activo
    }
    COMISION {
        string id PK
        string materia_codigo FK
        string dictado_id FK
        string nombre
        int numero
        int cupo
    }
    AULA {
        string id PK
        string sede
        string nombre
        int capacidad
        string tipo
    }
    HORARIO_CRONOGRAMA {
        string id PK
        string dia_semana
        time hora_inicio
        time hora_fin
    }
    CLASE {
        string id PK
        string comision_id FK
        string horario_id FK
        string profesor_id FK
        string dia
    }

    %% Entidades de Solución (verde)
    INSCRIPCION {
        string id PK
        string alumno_legajo FK
        string comision_id FK
        date fecha_inscripcion
        bool activa
    }
    ASISTENCIA {
        string id PK
        string alumno_legajo FK
        string clase_id FK
        date fecha
        bool presente
    }
    ASIGNACION_AULA {
        string id PK
        string clase_id FK
        string aula_id FK
        string ciclo_id FK
        date fecha_asignacion
        bool vigente
    }

    %% Tablas de Enlace (amarillo)
    PLAN_CARRERA_VERSION {
        string id PK
        string carrera_codigo FK
        string nombre
        date fecha_creacion
    }
    PLAN_ESTUDIO {
        string id PK
        string plan_version_id FK
        string materia_codigo FK
        string carrera_codigo FK
        int anio_plan
        string cuatrimestre_plan
    }
    COMISION_PROFESOR {
        string comision_id FK
        string profesor_id FK
        bool es_titular
    }

    %% Relaciones del Problema
    MATERIA ||--o{ COMISION : "tiene"
    MATERIA ||--o{ DICTADO : "tiene"
    DICTADO }o--|| CICLO : "en"
    DICTADO ||--o{ COMISION : "tiene"
    COMISION ||--o{ CLASE : "tiene"
    CLASE }o--|| HORARIO_CRONOGRAMA : "en"
    CLASE }o--o| PROFESOR : "dicta"

    %% Relaciones de Solución
    INSCRIPCION }o--|| ALUMNO : "alumno_legajo"
    INSCRIPCION }o--|| COMISION : "comision_id"
    ASISTENCIA }o--|| ALUMNO : "alumno_legajo"
    ASISTENCIA }o--|| CLASE : "clase_id"
    ASIGNACION_AULA }o--|| CLASE : "clase_id"
    ASIGNACION_AULA }o--|| AULA : "aula_id"
    ASIGNACION_AULA }o--|| CICLO : "ciclo_id"

    %% Relaciones de Tablas de Enlace (versionado de planes)
    CARRERA ||--o{ PLAN_CARRERA_VERSION : "versiones"
    PLAN_CARRERA_VERSION ||--o{ PLAN_ESTUDIO : "materias"
    PLAN_ESTUDIO }o--|| MATERIA : "materia_codigo"
    COMISION_PROFESOR }o--|| COMISION : "comision_id"
    COMISION_PROFESOR }o--|| PROFESOR : "profesor_id"
```

---

## 5. Restricciones y Validaciones

### 5.1 Restricciones de Asignación

Las siguientes restricciones deben cumplirse para toda asignación válida:

| # | Restricción | Descripción Formal |
|---|-------------|-------------------|
| R1 | **Unicidad de Clase** | ∀ clase, horario: |AsignacionAula(clase, horario)| ≤ 1 |
| R2 | **Unicidad de Aula** | ∀ aula, horario: |Clase(aula, horario)| ≤ 1 |
| R3 | **Capacidad** | ∀ asignacion: aula.capacidad ≥ clase.asistencia_esperada |
| R4 | **Sin Conflictos** | ∀ asig1, asig2: asig1.aula = asig2.aula ∧ superponen(asig1.horario, asig2.horario) → asig1 = asig2 |

```mermaid
flowchart TD
    subgraph Restricciones["Restricciones de Asignación"]
        R1["R1: Unicidad de Clase<br/>Cada clase → máximo 1 aula por horario"]
        R2["R2: Unicidad de Aula<br/>Cada aula → máximo 1 clase por horario"]
        R3["R3: Capacidad<br/>capacidad(aula) ≥ asistencia_esperada(clase)"]
        R4["R4: Sin Conflictos<br/>No hay superposición de horarios en misma aula"]
    end
    
    R1 --> V["✅ Asignación Válida"]
    R2 --> V
    R3 --> V
    R4 --> V
```

### 5.2 Validaciones Implementadas

El sistema implementa las siguientes validaciones en el módulo `src/services/validations.py`:

#### Validación 1: Materias con Carrera Asignada

Verifica que todas las materias estén asociadas a al menos una carrera, garantizando la integridad del plan de estudios.

```mermaid
flowchart LR
    A["Obtener todas<br/>las materias"] --> B["Obtener links<br/>materia-carrera"]
    B --> C{"¿Todas tienen<br/>carrera?"}
    C -->|Sí| D["✅ Válido"]
    C -->|No| E["❌ Lista materias<br/>sin carrera"]
```

#### Validación 2: Factibilidad de Horarios por Carrera

Verifica que los horarios de las materias del mismo año y cuatrimestre de una carrera no se superpongan, permitiendo que un alumno pueda asistir a todas sus clases.

```mermaid
flowchart TD
    A["Para cada carrera"] --> B["Para cada año (1-N)"]
    B --> C["Para cada cuatrimestre (1-2)"]
    C --> D["Obtener materias del grupo"]
    D --> E["Obtener clases de cada materia"]
    E --> F{"¿Hay horarios<br/>superpuestos?"}
    F -->|No| G["✅ Sin conflictos"]
    F -->|Sí| H["❌ Lista conflictos<br/>mat1 vs mat2: día HH:MM"]
```

#### Validación 3: Conflictos de Aula por Ciclo

Verifica que no haya dos clases asignadas a la misma aula en el mismo horario dentro de un ciclo lectivo.

```mermaid
flowchart TD
    A["Obtener asignaciones<br/>del ciclo"] --> B["Agrupar por aula"]
    B --> C["Para cada aula"]
    C --> D["Obtener horarios<br/>de clases asignadas"]
    D --> E{"¿Hay horarios<br/>superpuestos?"}
    E -->|No| F["✅ Sin conflictos"]
    E -->|Sí| G["❌ Aula X: clase1 vs clase2<br/>en día HH:MM"]
```

### 5.3 Reglas de Negocio

| Regla | Descripción |
|-------|-------------|
| RN1 | Toda materia debe pertenecer a al menos una carrera |
| RN2 | Al crear una materia, se genera automáticamente una "Comisión Única" |
| RN3 | Las materias anuales generan 2 dictados (uno por cuatrimestre) |
| RN4 | Las asignaciones de aula son válidas dentro del contexto de un ciclo específico |
| RN5 | Los horarios se definen con granularidad configurable (por defecto 15 minutos) |

---

## 6. Modelo de Implementación

### 6.1 Arquitectura de Datos

El sistema utiliza una arquitectura de dos capas de modelos para desacoplar la experimentación de la persistencia:

```mermaid
flowchart TB
    subgraph UI["Capa de Presentación"]
        ST["Streamlit<br/>Formularios CRUD"]
    end
    
    subgraph DB["Capa de Persistencia"]
        SM["SQLModel<br/>(AulaDB, ClaseDB, etc.)"]
        SQ["SQLite<br/>database.db"]
    end
    
    subgraph Domain["Capa de Dominio"]
        PY["Pydantic<br/>(Aula, Clase, etc.)"]
    end
    
    subgraph Algo["Capa de Algoritmos"]
        OPT["Optimización<br/>OR-Tools, PuLP"]
        ML["Machine Learning<br/>Predicción asistencia"]
    end
    
    ST --> SM
    SM --> SQ
    SM -->|"to_domain()"| PY
    PY --> OPT
    PY --> ML
    OPT -->|"to_db()"| SM
    ML -->|"to_db()"| SM
```

**Beneficios de esta arquitectura:**

| Aspecto | Con separación | Sin separación |
|---------|----------------|----------------|
| Experimentación ML | Objetos livianos, sin I/O | Cada operación toca la DB |
| Testing | Genera entidades puras | Necesita DB de test |
| Serialización | JSON/pickle directo | Hay que extraer de DB |
| Inmutabilidad | `frozen=True` garantizado | SQLModel es mutable |
| Comparación de soluciones | En memoria, rápido | Queries a DB |

### 6.2 Diagrama de Clases SQLModel

El modelo de base de datos está implementado en `src/database/models.py` utilizando SQLModel, que combina Pydantic (validación) con SQLAlchemy (ORM).

```mermaid
classDiagram
    direction TB

    class ConfiguracionHoraria {
        +int id
        +int granularidad_minutos
        +time hora_inicio_operativo
        +time hora_fin_operativo
        +str dias_operativos
    }

    class CicloDB {
        +str id
        +int anio
        +int numero
        +date fecha_inicio
        +date fecha_fin
        +str descripcion
    }

    class DictadoDB {
        +str id
        +str materia_codigo
        +str ciclo_id
        +str tipo
        +bool activo
    }

    class CarreraDB {
        +str codigo
        +str nombre
        +str titulo_otorgado
        +int duracion_anios
    }

    class ProfesorDB {
        +str id
        +str nombre
        +str email
        +str dni
    }

    class AlumnoDB {
        +str legajo
        +str email
        +str nombre
        +str dni
    }

    class MateriaDB {
        +str codigo
        +str nombre
        +int cupo
        +int horas_semanales
        +str periodo
        +int anio_carrera
        +int cuatrimestre_carrera
    }

    class ComisionDB {
        +str id
        +str materia_codigo
        +str dictado_id
        +str nombre
        +int numero
        +int cupo
    }

    class HorarioCronogramaDB {
        +str id
        +str dia_semana
        +time hora_inicio
        +time hora_fin
    }

    class AulaDB {
        +str id
        +str sede
        +str nombre
        +int capacidad
        +str tipo
        +str descripcion
    }

    class ClaseDB {
        +str id
        +str comision_id
        +str horario_id
        +str profesor_id
        +str dia
    }

    class InscripcionDB {
        +str id
        +str alumno_legajo
        +str comision_id
        +date fecha_inscripcion
        +bool activa
    }

    class AsistenciaDB {
        +str id
        +str alumno_legajo
        +str clase_id
        +date fecha
        +bool presente
    }

    class AsignacionAulaDB {
        +str id
        +str clase_id
        +str aula_id
        +str ciclo_id
        +date fecha_asignacion
        +bool vigente
    }

    class PlanCarreraVersionDB {
        +str id
        +str carrera_codigo
        +str nombre
        +str descripcion
        +date fecha_creacion
    }

    class PlanEstudioDB {
        +str id
        +str plan_version_id
        +str materia_codigo
        +str carrera_codigo
        +int anio_plan
        +str cuatrimestre_plan
        +str correlativas
    }

    class ComisionProfesorLink {
        +str comision_id
        +str profesor_id
        +bool es_titular
    }

    %% Relaciones principales
    CicloDB "1" --o "*" DictadoDB
    MateriaDB "1" --o "*" DictadoDB
    MateriaDB "1" --o "*" ComisionDB
    DictadoDB "1" --o "*" ComisionDB
    ComisionDB "1" --o "*" ClaseDB
    ComisionDB "1" --o "*" InscripcionDB
    HorarioCronogramaDB "1" --o "*" ClaseDB
    ClaseDB "1" --o "*" AsistenciaDB
    ClaseDB "1" --o "0..1" AsignacionAulaDB
    AulaDB "1" --o "*" AsignacionAulaDB
    AlumnoDB "1" --o "*" InscripcionDB
    AlumnoDB "1" --o "*" AsistenciaDB
    ProfesorDB "1" --o "*" ClaseDB
    CicloDB "1" --o "*" AsignacionAulaDB
    
    %% Relaciones via tablas de enlace (versionado de planes)
    CarreraDB "1" --o "*" PlanCarreraVersionDB
    PlanCarreraVersionDB "1" --o "*" PlanEstudioDB
    MateriaDB "1" --o "*" PlanEstudioDB
    ComisionDB "1" --o "*" ComisionProfesorLink
    ProfesorDB "1" --o "*" ComisionProfesorLink
```

---

## 7. Definiciones y Glosario

### Ciclo
Período lectivo (cuatrimestre) con fechas de inicio y fin. El identificador sigue el formato `AAAA-NC` donde AAAA es el año y N es el número de cuatrimestre.
- Ejemplo: `2024-1C` (primer cuatrimestre 2024), `2024-2C` (segundo cuatrimestre 2024)

### Dictado
Instancia de una materia en un ciclo específico. Permite manejar diferentes modalidades de cursado:
- **normal**: Dictado regular de la materia según el plan de estudios
- **recursado**: Para alumnos que deben recursar la materia
- **intensivo**: Dictado intensivo, típicamente en período de verano

Una materia con `periodo = "anual"` tendrá 2 dictados (uno por cuatrimestre), mientras que una materia `cuatrimestral` tendrá 1 dictado por ciclo.

### Comisión
División de una materia para distribuir alumnos y facilitar el dictado. Cada comisión está asociada a un dictado específico y tiene su propio cupo.
- Las materias sin múltiples comisiones se consideran compuestas por una única comisión ("Comisión Única") que se crea automáticamente al registrar la materia.

### Clase
Instancia de dictado de una comisión en un horario y día específico. Es la **unidad fundamental de asignación** del sistema.
- Una comisión puede tener múltiples clases (ej: Lunes 8-10, Miércoles 14-16)
- Cada clase puede tener un profesor asignado

### Horario_Cronograma
Franja horaria del cronograma académico en la que la facultad está operativa. Se define por día de semana, hora de inicio y hora de fin.
- La granularidad de los horarios es configurable (por defecto 15 minutos)
- Los horarios operativos por defecto son de 7:00 a 23:00

### Inscripción
Relación entre un alumno y una comisión que indica su intención de cursar. Permite:
- Calcular la demanda esperada de capacidad
- Trackear cambios post-inicio de clases

### Asistencia
Registro de la presencia efectiva de un alumno en una clase específica. Es la **variable estocástica principal** del problema de optimización.

### AsignacionAula
Relación que vincula una clase con un aula específica dentro de un ciclo. El campo `ciclo_id` es fundamental para:
- Contextualizar temporalmente las asignaciones
- Validar conflictos dentro del mismo período lectivo
- Permitir diferentes asignaciones para la misma clase en diferentes ciclos

### Materia
Asignatura académica del plan de estudios. Incluye información sobre su ubicación curricular:
- `periodo`: "anual" o "cuatrimestral"
- `anio_carrera`: Año sugerido en el plan de estudios (1-6)
- `cuatrimestre_carrera`: Cuatrimestre sugerido (1 o 2)

Estos campos permiten validar la factibilidad de horarios para los alumnos.

---

## 8. Referencias

- **Documentación del Proyecto**: `project/ante_proyecto.md`
- **Stack Tecnológico**: `project/tech_stack.md`
- **Arquitectura ORM**: `project/orm.md`
- **Especificación de Requerimientos**: `.kiro/specs/classroom-assignment-system/requirements.md`
- **Documento de Diseño**: `.kiro/specs/classroom-assignment-system/design.md`
- **Modelo de Base de Datos**: `src/database/models.py`
- **Validaciones**: `src/services/validations.py`
