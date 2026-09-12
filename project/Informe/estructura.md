# Estructura del informe (propuesta v3)

> **Estado**: propuesta en iteración. Este documento fija el esqueleto
> del informe y mapea, para cada capítulo, las fuentes internas del
> repositorio de las que se nutre la redacción. Se actualiza a medida
> que se toman decisiones sobre alcance, profundidad y bibliografía.
>
> **Última actualización**: 2026-09-08 (v3, encuadra la estructura
> dentro del formato I-32 de la cátedra, fija Morán como bibliografía
> canónica de IO y agrega restricciones e insumos del borrador
> original).

---

## 0. Encuadre según pautas de la cátedra (formato I-32)

El informe se rige por el instructivo *El informe escrito* (v2.1,
06/2023) de la Escuela de Ingeniería Industrial de FCEIA-UNR. Ese
instructivo fija la estructura global del documento en diez puntos:

1. Carátula.
2. Dedicatoria (opcional).
3. Página con advertencia.
4. Índice o tabla de contenidos.
5. Prólogo o presentación (una página; motivaciones, encuadre,
   agradecimientos; se escribe al final).
6. Síntesis inicial (una página; problema, objetivos, síntesis de
   conclusiones; se escribe al final).
7. **Desarrollo**, dividido en capítulos y secciones.
8. Conclusiones.
9. Bibliografía completa (orden alfabético, numerada).
10. Anexos.

**Todo lo que llamamos internamente "capítulos" en este documento
vive dentro del punto 7 (Desarrollo).** La numeración interna que se
propone abajo (1 a 12) es la numeración de capítulos del Desarrollo,
no la del informe global. Los puntos 1-6 se completan al final; los
puntos 8, 9 y 10 se corresponden respectivamente con nuestro
capítulo 12 (Conclusiones), la sección Referencias bibliográficas y
los anexos A a E.

Además, el instructivo fija reglas de formato que se aplican a todo
el documento sin repetirlas capítulo por capítulo: papel A4, letra
Times New Roman 12 o Arial 10 con interlineado simple, márgenes de
2,5 cm en los cuatro lados, texto justificado sin guiones separadores
de sílabas, encabezado con el título del trabajo, pie con autores y
numeración `Página X de N`, tablas y figuras numeradas con etiqueta
en negrita y título en cursiva (formato APA 7), fórmulas centradas y
numeradas a la derecha entre paréntesis. El tope de extensión son 60
páginas de cuerpo (90 en casos excepcionales, con justificación),
sin contar los anexos.

---

## 1. Hilo conductor

El informe se organiza como un recorrido que arranca en el **problema
concreto** que enfrenta la coordinación académica de la FCEIA y
termina en una **herramienta de software** que la asiste. Entre esos
dos extremos, el texto va introduciendo, cada vez que hace falta,
las herramientas conceptuales de la ingeniería industrial y de la
ingeniería de software que permiten pasar de uno al otro.

La idea controladora ya está redactada en `idea_controladora.md` y
desarrollada en `intro.md`: **el diseño de soluciones robustas
depende, en primera instancia, de una buena comprensión del dominio
del problema**. Todo el informe se construye alrededor de esa tesis.

El recorrido, en cuatro tiempos:

1. **Presentar el problema** en su forma coloquial (quiénes lo
   ejecutan, qué inputs recibe, qué outputs produce) y después
   darle marco formal (problema de asignación de recursos bajo
   restricciones, naturaleza combinatoria, efecto cascada).
2. **Modelizar el dominio**: identificar y definir explícitamente
   todas las entidades y relaciones que intervienen (carreras,
   materias, planes, comisiones, horarios, aulas, sedes) y las
   reglas de negocio que las gobiernan.
3. **Diseñar la solución**: traducir ese modelo conceptual a un
   modelo de datos, definir formalmente el problema de optimización
   como un programa lineal entero, presentar las herramientas
   matemáticas que se usan para diagnosticarlo (principio del
   palomar, teorema de Hall) y describir cómo el sistema arma el
   programa lineal dinámicamente a partir de la base de datos.
4. **Implementar y validar**: describir la herramienta construida,
   ejemplificar su uso con datos reales de FCEIA y discutir los
   resultados.

Este orden no es casual: refleja el orden natural en que un
lector-no-experto puede seguir el razonamiento sin haber leído nada
del contexto previamente.

---

## 2. Patrón cuerpo-anexo

Se adopta como criterio general de composición el siguiente patrón:

- **El cuerpo del informe** presenta cada tema con la profundidad
  suficiente para que la línea argumental cierre por sí misma:
  contexto, definiciones formales, resultados clave, ejemplos
  ilustrativos.
- **Los anexos** albergan el detalle técnico exhaustivo (desarrollo
  matemático completo, referencia de la base de datos, catálogo
  detallado de restricciones e implementación, matrices de trazabilidad)
  de manera que el lector interesado pueda profundizar sin que el
  cuerpo pierda ritmo.

Este patrón se aplica de manera uniforme: cada capítulo técnico
central del cuerpo tiene, cuando corresponde, un anexo hermano al que
apunta explícitamente.

---

## 3. Esqueleto propuesto

Se propone la siguiente estructura de seis partes, doce capítulos y
anexos. Los capítulos con `→` indican fuente principal ya escrita en
el repositorio.

### 3.1 Parte I. Planteo

#### Capítulo 1. Introducción

- La FCEIA como organización.
- Marco teórico organizacional: Mintzberg y Chiavenato, la facultad
  como burocracia profesional compleja.
- Presentación coloquial del dominio del problema.
- Idea controladora: el dominio como punto de partida.
- Objetivos del proyecto (general y específicos).
- Estructura del informe.
- Nota preliminar sobre el stack tecnológico: párrafo corto que
  enumera Python, Streamlit, SQLModel/SQLite, PuLP + CBC, y remite al
  capítulo 7 para el detalle. La idea es que el lector, ya en la
  introducción, sepa con qué piezas se implementó la solución antes
  de sumergirse en el modelo.
- → `intro.md` (ya redactado), `idea_controladora.md`,
  `0. Planteo/ante_proyecto.md`.

#### Capítulo 2. Marco teórico

- 2.1 Marco organizacional (síntesis de lo introducido en el
  capítulo 1: Chiavenato para tipología, Mintzberg para configuración
  estructural).
- 2.2 Marco metodológico para el modelado del dominio: *Domain-Driven
  Design* (Evans). Concepto de dominio, lenguaje ubicuo, entidades,
  agregados, invariantes.
- 2.3 Marco técnico: investigación de operaciones aplicada a la
  asignación de recursos. Programación lineal, programación lineal
  entera, resolutores, ramificación y acotación. Bibliografía por
  confirmar (ver § 6).
- 2.4 Herramientas conceptuales de combinatoria: principio del
  palomar y teorema de Hall. Se los presenta aquí como piezas
  teóricas y se los aplica más adelante en el diagnóstico.
- → aún por redactar; usar como base el glosario y sección 6 de
  `1. Diseño/asignacion-aulas-LP.md`.

### 3.2 Parte II. El problema

#### Capítulo 3. La organización y su operatoria

- 3.1 FCEIA en detalle: sedes (Pellegrini y CUR), carreras,
  volumen operativo.
- 3.2 El proceso actual de asignación de aulas: quiénes lo ejecutan
  (Direcciones de Escuelas, Área de Ingreso, Secretaría Académica,
  Secretaría Técnica, Secretaría Estudiantil, Bedelías), cuándo
  (por cuatrimestre y en régimen dinámico), con qué información
  (planillas, cronogramas, listas de comisiones, inscripciones
  parciales).
- 3.3 Diagrama del proceso de negocio actual (BPMN informal o
  diagrama de flujo).
- 3.4 Problemas operativos observados: aulas superpobladas, demoras,
  movimientos de bancos por los pasillos, incertidumbre antes del
  inicio de clases.
- 3.5 Datos y silos: cómo viven hoy los datos (SIU Guaraní, planillas,
  códigos internos por carrera).
- → `0. Planteo/ante_proyecto.md` (secciones "Descripción del Entorno"
  y "Problemas Operativos"), `intro.md`.

#### Capítulo 4. Definición del problema

- 4.1 Formulación coloquial: qué tiene que decidir la coordinación
  académica y bajo qué restricciones.
- 4.2 Formulación formal: problema de asignación de recursos bajo
  restricciones. Recursos = aulas; demanda = clases; restricciones =
  tipo de aula, capacidad, no doble asignación, sedes admisibles,
  horas declaradas por materia.
- 4.3 Naturaleza combinatoria: orden de magnitud del espacio de
  soluciones para el caso FCEIA.
- 4.4 El efecto cascada: por qué una perturbación local puede
  disparar reasignaciones globales.
- 4.5 Qué queda dentro del alcance del proyecto y qué no (exámenes,
  indisponibilidad de aulas, ausencias, paros).
- → `0. Planteo/ante_proyecto.md`, `1. Diseño/asignacion-aulas-LP.md`
  § 1.1 y § 2.

### 3.3 Parte III. Modelización del dominio

#### Capítulo 5. El modelo conceptual

- 5.1 Enfoque en capas: dominio completo → dominio delimitado →
  dominio de la solución (metodología del anteproyecto).
- 5.2 Entidades del dominio, presentadas una a una con su definición
  formal, sus atributos y sus relaciones: Carrera, Plan de Estudios
  (con versionado), Materia, Correlativa, Ciclo Lectivo, Dictado,
  Comisión, Horario semanal, Sede, Aula, Laboratorio compatible,
  Cronograma, Plan de Cursada.
- 5.3 Relaciones y multiplicidades, con especial atención a las
  relaciones muchos-a-muchos que motivan entidades intermedias.
- 5.4 Reglas de negocio e invariantes del dominio (jerarquía de
  virtualidad, regla de recursado, sede admisible por materia).
- 5.5 Diagrama UML de clases del dominio.
- → `0. Planteo/modelo-er.md`, `0. Planteo/plan-de-cursada.md`,
  `1. Diseño/modelo-planificacion-cursada.md`,
  `1. Diseño/diagrama-entidades.md`.

#### Capítulo 6. Del dominio al modelo de datos

- 6.1 Transición: cómo se traduce el modelo conceptual a un esquema
  relacional. Diferencia entre entidad de dominio y tabla del ORM.
- 6.2 Diagrama entidad-relación implementado.
- 6.3 Decisiones de diseño relevantes:
  - Versionado de planes de estudio.
  - `ClaseDB` como cache técnico deprecado (para no romper el hilo
    si el lector se cruza con la sigla en el código).
  - Comisión como entidad de primera clase.
  - Modelo de auditoría y snapshots (`LPRunDB`, `PlanValidationDB`,
    `ChangeLog`).
- 6.4 El cuerpo se queda con el ER y las decisiones clave; el detalle
  ficha-por-ficha se remite al **Anexo A. Referencia técnica de la
  base de datos**.
- → `anexos/Anexo_Base_de_Datos.md`,
  `1. Diseño/modelo-planificacion-cursada.md`, `1. Diseño/orm.md`.

### 3.4 Parte IV. La solución

#### Capítulo 7. Arquitectura de la solución

- 7.1 Visión general del sistema y su relación con el flujo de
  trabajo de las áreas responsables.
- 7.2 Stack tecnológico completo, presentado de una sola vez: Python
  como lenguaje base, Streamlit para la UI, SQLModel sobre SQLite
  para persistencia con validación de tipos, PuLP como interfaz al
  resolutor CBC. Justificación de cada elección y encaje con las
  fases futuras. Esta sección es referenciada desde los capítulos 6
  (SQLite/SQLModel) y 8 (PuLP/CBC), pero se desarrolla acá una sola
  vez.
- 7.3 Separación en capas: dominio puro, servicios, persistencia,
  UI. Cómo se refleja el modelo conceptual en el código.
- 7.4 Workflow end-to-end: catálogo → ciclo → dictados → cronograma
  → plan de cursada → validación → activación → asignación de aulas.
  Diagrama de secuencia.
- → `1. Diseño/tech_stack.md`, `1. Diseño/orm.md`,
  `2. Desarrollo/WORKFLOW.md`.

#### Capítulo 8. El problema de asignación como programa lineal entero

Este es el capítulo técnico central del informe. Sigue una progresión
de coloquial → formal, pero con **versión resumida en el cuerpo**: se
presenta el modelo completo (conjuntos, variables, función objetivo,
las diez restricciones y su lectura en prosa) y se dejan al **Anexo E,
Desarrollo formal del programa lineal**, las demostraciones,
alternativas rechazadas y el análisis fino de complejidad (por
ejemplo, la justificación de por qué la formulación por grupos de
simultaneidad domina a la formulación por pares).

- 8.1 De la operatoria al modelo: por qué el problema es naturalmente
  formulable como un PLE. Qué decisiones toma el programa lineal y
  qué queda fuera de él (comisiones, horarios, virtualidad).
- 8.2 Formulación matemática resumida:
  - Conjuntos: horarios `H`, aulas `A`, subconjuntos `A_t`,
    `A_lab(m)`, comisiones `K`, dictados `D`, grupos de simultaneidad
    `Sim`.
  - Parámetros y variables de decisión.
  - Función objetivo asimétrica (sobre/sub-ocupación).
  - Restricciones R1 a R10, cada una acompañada de su lectura en
    prosa. Las derivaciones se remiten al anexo.
- 8.3 Herramientas conceptuales para el diagnóstico:
  - Principio del palomar (*pigeonhole*): motivación y aplicación al
    chequeo de saturación por franja horaria.
  - Teorema de Hall y apareamiento bipartito: cuándo el principio
    del palomar no alcanza y hay que mirar subconjuntos.
  - Grupos de simultaneidad como formulación de la restricción R4;
    la comparación detallada con la formulación por pares queda en
    el anexo.
- 8.4 Chequeo estructural pre-solve: el semáforo de factibilidad
  que corre antes de invocar al resolutor.
- 8.5 Construcción dinámica del programa lineal: cómo la aplicación
  arma variables, parámetros y restricciones a partir del estado
  actual de la base de datos y la configuración que elige el
  usuario. Explicita que el programa no está hard-codeado sino
  parametrizado.
- 8.6 Resolución: el resolutor CBC vía PuLP; qué devuelve; cómo se
  aplica la solución al patrón semanal y se propaga.
- → cuerpo: síntesis de `1. Diseño/asignacion-aulas-LP.md`;
  anexo E: desarrollo completo tomando de `asignacion-aulas-LP.md`,
  `2. Desarrollo/asignador_guia_operativa.md` y
  `2. Desarrollo/asignador_implementacion.md`.

#### Capítulo 9. Validaciones y garantías de consistencia

- 9.1 Por qué las validaciones son parte del diseño: no alcanza con
  un modelo correcto si los datos que se le pasan no lo son.
- 9.2 Capas de validación: dominio → servicios → agregadores → UI.
- 9.3 Severidades (`BLOCKER`, `WARNING`, `INFO`) y su semántica.
- 9.4 Auditoría y trazabilidad: `LPRunDB`, `PlanValidationDB`,
  Change Log.
- → cuerpo: síntesis de `2. Desarrollo/VALIDACIONES.md`; el catálogo
  completo de validaciones queda en el mismo documento anexado.

### 3.5 Parte V. Uso y resultados

#### Capítulo 10. La herramienta en acción

- 10.1 Recorrido guiado por la interfaz, siguiendo el workflow del
  capítulo 7. Un puñado de capturas comentadas alcanzan; el detalle
  paso-a-paso vive en el manual de usuario (Anexo B).
- 10.2 Ejemplo integral: cargar el cronograma real de un cuatrimestre
  de FCEIA, generar el plan de cursada, correr el asignador de aulas.
- 10.3 Escenarios "what-if": qué pasa si se suma una comisión, se
  cambia el peso de sobre-ocupación, se restringe una materia a una
  sede.
- → cuerpo: recorrido selectivo con capturas nuevas; anexo B: manual
  operativo completo derivado de `Informe/anexos/Anexo_Manual_de_Usuario/`.

#### Capítulo 11. Análisis y discusión

- 11.1 Métricas de la corrida sobre datos reales: tiempo de
  resolución, sobre-ocupación agregada, sub-ocupación, cobertura del
  cronograma, ocupación por sede.
- 11.2 Comparación cualitativa con el proceso manual actual.
- 11.3 Limitaciones conocidas del modelo y del sistema.
- 11.4 Cumplimiento de los objetivos del anteproyecto (recorrer los
  cinco objetivos específicos y verificar).

### 3.6 Parte VI. Cierre

#### Capítulo 12. Conclusiones

- 12.1 Síntesis del recorrido: cómo se articula la doble mirada
  (ingeniería industrial + ingeniería de software) en el resultado.
- 12.2 Aporte del proyecto a la FCEIA.
- 12.3 Trabajos futuros: rehabilitación de excepciones puntuales,
  corridas incrementales durante el cuatrimestre, incorporación de un
  módulo de pronóstico de inscripción con ML, extensión a otros
  recursos (mesas de examen, laboratorios de investigación).

#### Referencias bibliográficas

### 3.7 Anexos

- **Anexo A. Referencia técnica de la base de datos.** Documento
  independiente ya escrito. Ubicación:
  `anexos/Anexo_Base_de_Datos.md`.
- **Anexo B. Manual de usuario.** Consolidación de
  `project/Informe/anexos/Anexo_Manual_de_Usuario/` con revisión para poner al día los
  cambios acumulados desde su última edición (deprecación de clases
  puntuales, comisiones por carrera, etc.).
- **Anexo C. Matriz de requerimientos.** Derivado de
  `project/requerimientos.md`. Sirve como trazabilidad entre
  requerimientos y capítulos del informe.
- **Anexo D (opcional). Notas de diseño e historial.** Selección
  de material de `2. Desarrollo/sesiones/` con las decisiones de
  diseño más relevantes.
- **Anexo E. Desarrollo formal del programa lineal.**
  Documentación completa del modelo: derivación de restricciones,
  demostraciones, formulaciones alternativas descartadas, análisis
  de complejidad, catálogo de casos infactibles y sus diagnósticos.
  Fuente: `2. Desarrollo/asignador_guia_operativa.md`,
  `2. Desarrollo/asignador_implementacion.md` y partes de
  `1. Diseño/asignacion-aulas-LP.md` que no van al cuerpo.

---

## 4. Política de diagramas e ilustraciones

Se adopta como política por defecto **generar diagramas e
ilustraciones siempre que aporten claridad**, priorizando:

- Diagramas de proceso (BPMN informal o flowchart) para el capítulo 3.
- Diagrama UML de clases del dominio para el capítulo 5.
- Diagrama entidad-relación implementado para el capítulo 6.
- Diagrama de arquitectura por capas y diagrama de secuencia del
  workflow para el capítulo 7.
- Diagramas ilustrativos del programa lineal (grafos de
  compatibilidad, grupos de simultaneidad, matriz `x[h, a]`,
  ejemplos pequeños de infactibilidad por Hall) para el capítulo 8.
- Capturas comentadas de la UI para el capítulo 10.
- Gráficos de métricas (barras, heatmaps de ocupación) para el
  capítulo 11.

El autor revisa en cada iteración si algún diagrama resulta
redundante o de más y lo remueve puntualmente. Fuente de arte
existente: `project/diagrams/` y `0. Planteo/domain_diagrams.py`.

---

## 5. Mapa de fuentes por capítulo

Tabla de referencia para saber, ante cada capítulo, qué documentos
del repositorio son la fuente principal. Se marca con `→` cuando el
material ya está escrito y con `∅` cuando falta redactar.

| Cap. | Título | Fuentes principales | Estado |
| --- | --- | --- | --- |
| 1 | Introducción | `Informe/intro.md`, `Informe/idea_controladora.md`, `0. Planteo/ante_proyecto.md` | → borrador |
| 2 | Marco teórico | glosario y § 6 de `asignacion-aulas-LP.md`, bibliografía externa | ∅ |
| 3 | La organización y su operatoria | `ante_proyecto.md`, `intro.md` | ∅ (extraer) |
| 4 | Definición del problema | `ante_proyecto.md`, `asignacion-aulas-LP.md` § 1-2 | ∅ (síntesis) |
| 5 | Modelo conceptual | `modelo-er.md`, `plan-de-cursada.md`, `modelo-planificacion-cursada.md`, `diagrama-entidades.md` | → material abundante |
| 6 | Modelo de datos | `Anexo_Base_de_Datos.md`, `orm.md`, `modelo-planificacion-cursada.md` | → material abundante |
| 7 | Arquitectura | `tech_stack.md`, `orm.md`, `WORKFLOW.md` | → borradores |
| 8 | Programa lineal (cuerpo) | `asignacion-aulas-LP.md` (síntesis) | → material abundante |
| 8-E | Programa lineal (anexo E) | `asignacion-aulas-LP.md` completo, `asignador_guia_operativa.md`, `asignador_implementacion.md` | → material abundante |
| 9 | Validaciones | `VALIDACIONES.md` | → |
| 10 | Herramienta en acción | `Informe/anexos/Anexo_Manual_de_Usuario/`, `WORKFLOW.md`, capturas nuevas | ∅ (capturas) |
| 11 | Análisis y discusión | corridas experimentales sobre datos reales | ∅ |
| 12 | Conclusiones | (síntesis del propio informe) | ∅ |

---

## 6. Cómo se relaciona esta estructura con la idea controladora

La idea controladora tiene cuatro afirmaciones que ordenan el
recorrido:

1. *Toda solución informática arranca por entender el dominio.* →
   Cap. 1-5.
2. *La ingeniería industrial da las herramientas para entender la
   organización y modelar el problema.* → Cap. 1 (marco
   organizacional), 3 (operatoria), 4 (formulación), 8 (PL).
3. *La ingeniería de software da las herramientas para plasmar la
   comprensión en una implementación robusta.* → Cap. 5-9.
4. *La asignación de aulas es un problema de recursos bajo
   restricciones con efecto cascada, y por eso requiere un modelo
   formal y un soporte informático.* → Cap. 4, 8, 10.

De este modo, cada capítulo aporta piezas a la tesis global y el
informe termina, en el capítulo 12, mostrando que la doble mirada
efectivamente produjo un artefacto útil.

---

## 7. Decisiones tomadas y pendientes

### 7.1 Decisiones tomadas

1. **Patrón cuerpo-anexo (D1).** El cuerpo lleva la versión
   resumida; los desarrollos exhaustivos (matemáticos, de
   implementación, de referencia técnica) viven en anexos. Se
   consagra como patrón general del informe (ver § 2). Nace de
   esto el **Anexo E** para el capítulo 8.
2. **Manual de usuario como anexo (D2).** Se consolida
   `project/Informe/anexos/Anexo_Manual_de_Usuario/` en el **Anexo B**, con una
   revisión previa para poner al día los cambios acumulados desde
   su última edición.
3. **Stack tecnológico presentado entero al principio (D3).** Se
   introduce coloquialmente en el capítulo 1 y se desarrolla una
   sola vez en 7.2. Los capítulos 6 y 8 referencian esa sección
   en lugar de repetir el contenido.
4. **Diagramas por defecto (D4).** Política de generar diagramas
   siempre que aporten claridad; el autor decide caso por caso
   cuándo remover uno. Ver § 4.
5. **Bibliografía de investigación de operaciones (D5).** Se adopta
   como referencia canónica de IO el libro utilizado en la cátedra
   Operativa 1 de la Escuela de Ingeniería Industrial de FCEIA-UNR
   (Morán, disponible en `bibliografia/Operativa 1/`), complementado
   por el material *Introducción a la Investigación Operativa* del
   mismo curso. Para el capítulo 8 se puede reforzar puntualmente
   con Winston o Hillier & Lieberman cuando haga falta una
   referencia adicional. Para combinatoria (palomar, Hall) se toma
   una referencia estándar de teoría de grafos, a confirmar cuando
   se redacte la bibliografía final.
6. **Encuadre según el formato I-32 de la cátedra (D6).** Los
   "capítulos" del Desarrollo son subsecciones internas del punto 7
   del instructivo *El informe escrito*. El informe global respeta
   la estructura de diez puntos que fija la cátedra (ver § 0). El
   prólogo y la síntesis inicial se redactan al final.

### 7.2 Decisiones pendientes

Ninguna abierta en este momento. La próxima iteración se centra en
completar los capítulos pendientes del Desarrollo y, ya avanzada la
redacción, en escribir prólogo, síntesis inicial y conclusiones.
