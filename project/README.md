# Documentación del proyecto Gestor de Aulas

> **Última actualización**: 2026-09-12.
>
> Este archivo es el índice maestro de toda la documentación del
> proyecto. Sirve como puerta de entrada al material y como mapa
> para saber dónde vive cada tipo de contenido.

---

## Cómo está organizada la documentación

El proyecto separa la documentación en cinco carpetas, cada una con
un rol bien definido en el ciclo de vida del proyecto:

| Carpeta | Rol | Audiencia |
|---|---|---|
| [`0. Planteo/`](./0.%20Planteo/) | Comprensión del problema y modelado conceptual inicial. Cómo entendemos el dominio y qué asumimos. | Autores, revisores del anteproyecto. |
| [`1. Diseño/`](./1.%20Diseño/) | Diseño de la solución: modelo de datos, arquitectura, formulación matemática. | Autores, desarrolladores. |
| [`2. Desarrollo/`](./2.%20Desarrollo/) | Detalles técnicos de la implementación. Guías operativas, validaciones, runbooks. | Desarrolladores actuales y futuros. |
| [`Informe/`](./Informe/) | Material del informe académico final: capítulos redactados, anexos, bibliografía. | Comité evaluador, lectores del informe. |
| [`diagrams/`](./diagrams/) | Diagramas fuente (Draw.io, Mermaid) reutilizados a lo largo del material. | Autores. |

También en la raíz de esta carpeta:

- [`requerimientos.md`](./requerimientos.md) — Índice maestro de
  requerimientos funcionales (RF) y no funcionales (RNF) del
  sistema, con estado de implementación y puntero al documento
  canónico de cada uno.

---

## 0. Planteo — comprensión del dominio

**Enfoque**: entender el dominio antes de diseñar. Estos documentos
describen la operatoria de FCEIA, las entidades reales, las
relaciones que existen en el mundo y las asunciones que estamos
haciendo. Preceden a cualquier decisión de diseño técnico.

| Archivo | Contenido |
|---|---|
| [`0. Planteo/ante_proyecto.md`](./0.%20Planteo/ante_proyecto.md) | Anteproyecto original: contexto de FCEIA, problemas operativos observados, objetivos generales y específicos, alcance. |
| [`0. Planteo/modelo-er.md`](./0.%20Planteo/modelo-er.md) | **Modelo ER conceptual v1** (histórico). Refleja el estado inicial del modelado, con entidades como `Inscripción` y `Asistencia` que quedaron fuera de alcance. El modelo implementado está en `1. Diseño/`. |
| [`0. Planteo/plan-de-cursada.md`](./0.%20Planteo/plan-de-cursada.md) | Descripción del concepto de "plan de cursada" y de cómo se articula con los ciclos lectivos y los cronogramas. |

---

## 1. Diseño — cómo se resuelve el problema

**Enfoque**: cómo pasamos del modelo conceptual a una solución
concreta. Aquí viven las decisiones de modelado, la formulación
matemática y el diagrama UML implementado.

| Archivo | Contenido |
|---|---|
| [`1. Diseño/modelo-planificacion-cursada.md`](./1.%20Diseño/modelo-planificacion-cursada.md) | **Referencia del modelo de datos activo**. Describe cada entidad, sus atributos, invariantes y relaciones. Incluye el catálogo completo de tablas agrupadas por zona funcional. |
| [`1. Diseño/diagrama-entidades.md`](./1.%20Diseño/diagrama-entidades.md) | **Diagrama UML del schema** con políticas de borrado, cascadas y deprecaciones. |
| [`1. Diseño/asignacion-aulas-LP.md`](./1.%20Diseño/asignacion-aulas-LP.md) | **Planteo formal del programa lineal** de asignación de aulas: conjuntos, variables, función objetivo, restricciones R1-R14, chequeo pre-solve, IIS y decisiones de diseño. Referencia técnica exhaustiva del modelo. |
| [`1. Diseño/tech_stack.md`](./1.%20Diseño/tech_stack.md) | Justificación del stack tecnológico: Python + Streamlit + SQLModel + SQLite + PuLP/CBC. |
| [`1. Diseño/orm.md`](./1.%20Diseño/orm.md) | Explicación conceptual del ORM y del rol de SQLModel en el proyecto. |

---

## 2. Desarrollo — detalles técnicos e implementación

**Enfoque**: cómo está implementada la solución. Runbooks, guías
operativas, catálogos de validaciones y notas por área. Sirve como
material de referencia para el equipo de desarrollo y para
onboarding.

### Documentos activos

| Archivo | Contenido |
|---|---|
| [`2. Desarrollo/WORKFLOW.md`](./2.%20Desarrollo/WORKFLOW.md) | **Workflow end-to-end del sistema**: desde la carga inicial hasta la corrida del asignador. Documento operativo con nombres de tablas y servicios. |
| [`2. Desarrollo/CICLOS_Y_DICTADOS.md`](./2.%20Desarrollo/CICLOS_Y_DICTADOS.md) | **Guía técnica y operativa de ciclos y dictados**. Cubre las tres puertas de decisión (pertenencia, recursado, virtualidad), la sincronización con reglas y la auditoría (change log). Incluye runbook paso a paso para configurar un ciclo desde cero. |
| [`2. Desarrollo/asignador_guia_operativa.md`](./2.%20Desarrollo/asignador_guia_operativa.md) | **Guía operativa del asignador de aulas**. Cómo se corre desde la UI, panel de parámetros, grupos de materias, interpretación del veredicto, diagnóstico, troubleshooting. |
| [`2. Desarrollo/asignador_implementacion.md`](./2.%20Desarrollo/asignador_implementacion.md) | **Implementación del asignador**. Arquitectura del servicio, contratos de las funciones principales, diagnóstico e IIS, saneamiento de virtuales, tests. |
| [`2. Desarrollo/VALIDACIONES.md`](./2.%20Desarrollo/VALIDACIONES.md) | **Catálogo completo de validaciones** del sistema: por capa (servicio, agregador, UI inline), con severidades y snapshots. |
| [`2. Desarrollo/CARGA_DATOS_INICIALES.md`](./2.%20Desarrollo/CARGA_DATOS_INICIALES.md) | Procedimiento de carga inicial de datos desde Excel (`scripts/load_initial_data.py`). |
| [`2. Desarrollo/DISTRIBUCION.md`](./2.%20Desarrollo/DISTRIBUCION.md) | Notas sobre distribución del sistema (empaquetado, deploy local). |

### `sesiones/` — Registro histórico del proceso de desarrollo

Documentos que capturan sesiones de trabajo puntuales, refactors
importantes o decisiones de diseño en su contexto original. No son
material vigente sino registro histórico. Los más relevantes:

- `DEPRECACION_CLASEDB.md` — plan de retiro del caché `ClaseDB`.
- `COMISIONES_POR_CARRERA.md` — refactor de comisiones a entidad
  de primera clase y override `carrera_asignada` (este último
  deprecado como semántica LP en 2026-09).
- `PLAN_VERSIONING_IMPLEMENTATION.md` — introducción de versiones
  de plan.
- Otros: material sobre carrera-completeness, editor de planes,
  prevalidación de comisiones, troubleshooting.

### `auditorias/` — Auditorías de datos y hallazgos

Reportes de auditoría de datos concretos y sus hallazgos. No son
de interés inmediato para nadie fuera del contexto de la
auditoría, pero se conservan como referencia:

- `AUDITORIA_PLANES_2026-09-11.md` — auditoría de planes de
  estudio a la fecha.
- `HALLAZGOS_AUDITORIA.md` — hallazgos de auditorías sobre datos
  y UI, con estado de resolución.
- `backups/` — backups JSON generados durante las auditorías.

---

## Informe — material del informe académico

**Enfoque**: material entregable del informe académico final. Sigue
la estructura fijada en [`Informe/estructura.md`](./Informe/estructura.md).

### Documento maestro

- [`Informe/estructura.md`](./Informe/estructura.md) — **Estructura
  del informe** (v3). Define el esqueleto, la política de anexos,
  el hilo conductor y el estado de redacción de cada capítulo.
- [`Informe/idea_controladora.md`](./Informe/idea_controladora.md) —
  Idea controladora del trabajo.
- [`Informe/intro.md`](./Informe/intro.md) — Borrador de la
  introducción.

### Capítulos redactados

| Capítulo | Archivo | Estado |
|---|---|---|
| 2 — Marco teórico | [`Informe/cap02_marco_teorico.md`](./Informe/cap02_marco_teorico.md) | ✅ Redactado. |
| 3 — La organización y su operatoria | [`Informe/cap03_organizacion_y_operatoria.md`](./Informe/cap03_organizacion_y_operatoria.md) | ✅ Redactado. |
| 4 — Definición del problema | [`Informe/cap04_definicion_del_problema.md`](./Informe/cap04_definicion_del_problema.md) | ✅ Redactado. |
| 5 — Modelo conceptual | [`Informe/cap05_modelo_conceptual.md`](./Informe/cap05_modelo_conceptual.md) | ✅ Redactado. |
| 6 — Modelo de datos | [`Informe/cap06_modelo_de_datos.md`](./Informe/cap06_modelo_de_datos.md) | ✅ Redactado. |
| 7 — Arquitectura de la solución | [`Informe/cap07_arquitectura.md`](./Informe/cap07_arquitectura.md) | ✅ Redactado. |
| 8 — El problema como programa lineal entero | [`Informe/cap08_programa_lineal.md`](./Informe/cap08_programa_lineal.md) | ✅ Redactado. |
| 9 — Validaciones y garantías de consistencia | [`Informe/cap09_validaciones.md`](./Informe/cap09_validaciones.md) | ✅ Redactado. |
| 1 — Introducción | — | ⏳ Pendiente (se redacta al final). |
| 10 — La herramienta en acción | — | ⏳ Pendiente (requiere capturas de UI). |
| 11 — Análisis y discusión | — | ⏳ Pendiente. |
| 12 — Conclusiones | — | ⏳ Pendiente. |

### Anexos

| Anexo | Contenido | Estado |
|---|---|---|
| [`Informe/anexos/Anexo_Base_de_Datos.md`](./Informe/anexos/Anexo_Base_de_Datos.md) | **Referencia técnica exhaustiva** de la base de datos: ficha por tabla, invariantes, migraciones, políticas de borrado, snapshots, change log. | ✅ Redactado. |
| [`Informe/anexos/Anexo_Manual_de_Usuario/`](./Informe/anexos/Anexo_Manual_de_Usuario/) | **Manual de usuario completo**: introducción, primeros pasos, flujos operativos (setup inicial, armar un ciclo, reasignación de aulas, verificación pre-inicio) y módulos (materias, aulas, carreras, ciclos, planes, cronogramas, inscriptos, historial). | ✅ Redactado (pendiente pasada final tras revisión de UI). |
| Anexo — Matriz de requerimientos | — | ⏳ Pendiente. Derivar de [`requerimientos.md`](./requerimientos.md). |
| Anexo E — Desarrollo formal del programa lineal | — | ⏳ Pendiente. Consolidación del planteo formal del capítulo 8 con derivaciones exhaustivas. Fuente: [`1. Diseño/asignacion-aulas-LP.md`](./1.%20Diseño/asignacion-aulas-LP.md), [`2. Desarrollo/asignador_guia_operativa.md`](./2.%20Desarrollo/asignador_guia_operativa.md), [`2. Desarrollo/asignador_implementacion.md`](./2.%20Desarrollo/asignador_implementacion.md). |

### Material de soporte

- [`Informe/bibliografia/`](./Informe/bibliografia/) — Bibliografía
  del informe (libros de investigación operativa, teoría de la
  organización, etc.).
- [`Informe/borradores/`](./Informe/borradores/) — Borradores y
  material de trabajo del informe.
- [`Informe/pautas informe/`](./Informe/pautas%20informe/) —
  Pautas y formato exigidos por la cátedra (formato I-32 de la
  Escuela de Ingeniería Industrial de FCEIA-UNR).

---

## Diagramas fuente

- [`diagrams/`](./diagrams/) — Fuente de diagramas (Draw.io,
  Mermaid) usados a lo largo del material. Los diagramas
  embebidos en los documentos suelen tener su fuente aquí para
  ser exportables a formato imprimible.

---

## Cómo mantener este material

- **Cambios en el código que afectan al modelo o al flujo**:
  actualizar la documentación correspondiente en `1. Diseño/` y/o
  `2. Desarrollo/`. Los capítulos del informe se re-alinean si
  corresponde.
- **Nuevos requerimientos**: agregar entrada en
  [`requerimientos.md`](./requerimientos.md) con su ID estable y
  el estado de implementación.
- **Refactors importantes**: dejar registro en `2. Desarrollo/sesiones/`
  con nombre auto-explicativo del cambio; actualizar los
  documentos vigentes en `1. Diseño/` y `2. Desarrollo/` para que
  reflejen el nuevo estado.
- **Auditorías de datos o hallazgos**: usar `2. Desarrollo/auditorias/`.

### Convenciones de redacción

- **Idioma**: castellano rioplatense argentino, formal-académico y
  natural.
- **No usar em-dashes (`—`)**: reemplazar según sentido de la
  oración por comas, paréntesis, dos puntos, punto seguido o
  reformulación. Ver [`requerimientos.md`](./requerimientos.md)
  § Reglas de redacción.
- **Referencias cruzadas**: preferir enlaces relativos con path
  explícito para que sean navegables desde GitHub y desde el
  filesystem.

---

## Referencias rápidas por temática

**¿Cómo funciona el asignador?**
1. Empezar por [`2. Desarrollo/asignador_guia_operativa.md`](./2.%20Desarrollo/asignador_guia_operativa.md) para la operatoria desde la UI.
2. Para el detalle matemático: [`1. Diseño/asignacion-aulas-LP.md`](./1.%20Diseño/asignacion-aulas-LP.md).
3. Para el detalle de implementación: [`2. Desarrollo/asignador_implementacion.md`](./2.%20Desarrollo/asignador_implementacion.md).

**¿Cómo funciona el modelo de datos?**
1. Vista general: [`1. Diseño/modelo-planificacion-cursada.md`](./1.%20Diseño/modelo-planificacion-cursada.md).
2. Diagrama UML: [`1. Diseño/diagrama-entidades.md`](./1.%20Diseño/diagrama-entidades.md).
3. Referencia exhaustiva por tabla: [`Informe/anexos/Anexo_Base_de_Datos.md`](./Informe/anexos/Anexo_Base_de_Datos.md).

**¿Cómo se opera un ciclo lectivo?**
1. Runbook operativo: [`2. Desarrollo/CICLOS_Y_DICTADOS.md`](./2.%20Desarrollo/CICLOS_Y_DICTADOS.md).
2. Manual de usuario, flujo específico: [`Informe/anexos/Anexo_Manual_de_Usuario/flujos/02_Armar_un_ciclo_lectivo.md`](./Informe/anexos/Anexo_Manual_de_Usuario/flujos/02_Armar_un_ciclo_lectivo.md).

**¿Qué valida el sistema y cuándo?**
- [`2. Desarrollo/VALIDACIONES.md`](./2.%20Desarrollo/VALIDACIONES.md).

**¿Qué está pendiente de implementar?**
- Filtrar [`requerimientos.md`](./requerimientos.md) por estado
  `⏳ Pendiente`.
