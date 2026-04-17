# Introducción

## La facultad como organización

La Facultad de Ciencias Exactas, Ingeniería y Agrimensura (FCEIA) de la Universidad Nacional de Rosario forma profesionales en múltiples carreras de grado, posgrado y tecnicaturas. Para ello, cada cuatrimestre decenas de docentes preparan contenido y planifican el dictado de sus materias. Se organizan comisiones, se asignan aulas, se establecen horarios, se toma exámen. Cada actividad tiene requerimientos distintos y demanda recursos diferentes — aulas con determinada capacidad, laboratorios con equipamiento específico, o simplemente un espacio donde un grupo de alumnos pueda sentarse.

Puede que a un ingeniero industrial no le resulte inmediatamente evidente que una facultad pueda ser objeto de estudio en su labor profesional. Sin embargo, en la carrera de Ingeniería Industrial no se estudian solamente fábricas o cadenas productivas: se estudian *organizaciones*. Chiavenato define a las organizaciones como "unidades sociales (o agrupaciones humanas) intencionalmente construidas y reconstruidas para lograr objetivos específicos" (Chiavenato, 2006, p. 2). Bajo esta definición, una facultad universitaria es tan legítimamente objeto de análisis como cualquier empresa manufacturera o de servicios.

Así, se puede empezar a comprender a la facultad no simplemente como un espacio en el que concurren personas a impartir conocimiento, sino como un sistema complejo de distintos elementos que se coordinan para la consecución de un mismo fin.

## Marco organizacional: Mintzberg y Chiavenato

Para encarar cualquier proyecto de mejora sobre una organización, la ingeniería industrial enseña que primero hay que comprenderla: su estructura, sus mecanismos de coordinación, la naturaleza de su trabajo. Mintzberg, en *La estructuración de las organizaciones* (1979), propone un modelo donde toda organización puede descomponerse en cinco partes fundamentales: la cumbre estratégica, la línea media, el núcleo operativo, la tecnoestructura y el staff de apoyo. A su vez, identifica cinco mecanismos básicos de coordinación: el ajuste mutuo, la supervisión directa, y la normalización de procesos, de resultados y de habilidades.

A partir de estas dimensiones, Mintzberg define cinco configuraciones estructurales. La que mejor describe a una universidad es la *burocracia profesional*: una organización cuyo mecanismo de coordinación principal es la *normalización de habilidades* y cuya parte clave es el *núcleo operativo*. En esta configuración, los profesionales del núcleo operativo — en nuestro caso, los docentes — poseen un alto grado de autonomía en su trabajo. La organización coordina su actividad no mediante supervisión directa ni mediante la estandarización de procesos, sino a través de la formación y las competencias que los profesionales adquieren antes de incorporarse. "La burocracia profesional cuenta para su coordinación con la normalización de las destrezas y con el parámetro de diseño correspondiente, la preparación y el adoctrinamiento" (Mintzberg, 1979).

Chiavenato, por su parte, clasifica a las organizaciones según su complejidad en simples, complejas y altamente complejas (Chiavenato, 2006). Una universidad encuadra en la categoría de *organización compleja*: presenta diferenciación horizontal alta (múltiples departamentos, carreras, cátedras), diferenciación vertical moderada (aunque la jerarquía formal existe, la autoridad real se distribuye en el núcleo operativo), y dispersión espacial (múltiples sedes, en nuestro caso Pellegrini y Siberia). La complejidad no proviene de una cadena de mando intrincada, sino de la multiplicidad de actores, actividades y recursos que deben articularse en tiempo y espacio.

Esta caracterización no es un ejercicio teórico gratuito. Comprender que estamos ante una burocracia profesional compleja nos permite anticipar, por ejemplo, que las decisiones operativas están distribuidas y que los requerimientos son heterogéneos y cambiantes — dos factores que serán determinantes a la hora de modelizar el problema y diseñar una solución.

## El dominio del problema

Una vez comprendida la naturaleza de la organización, el foco se dirige al problema concreto. En la FCEIA, cada cuatrimestre se deben asignar aulas a cada clase individual que se dicta, respetando restricciones de horarios, capacidades, tipos de espacio y políticas institucionales. Es, en esencia, un problema de *asignación de recursos bajo restricciones*.

La complejidad del problema radica en su naturaleza combinatoria. La cantidad de materias, comisiones, franjas horarias y aulas genera un espacio de soluciones que crece de manera exponencial. Pero la verdadera dificultad operativa no es solo encontrar una asignación inicial válida, sino que *cualquier cambio en las condiciones iniciales puede desencadenar una cascada de ajustes*. Un horario que se modifica, una restricción que se agrega tardíamente, una comisión que se abre por exceso de inscriptos — cada perturbación puede invalidar partes significativas del esquema y requerir reasignaciones en cadena.

Hoy, este proceso se realiza de forma manual, basándose en las asignaciones del cuatrimestre anterior y en el criterio de las personas responsables. No existe un modelo formal de las restricciones ni herramientas que permitan evaluar rápidamente el impacto de un cambio. Esto no solo hace que el proceso sea tedioso y propenso a errores sino que ademas lento. Es posible que al demorar en dar respuesta no esten dadas las condiciones para el dictado de alguna materia, afectando el curso normal del ciclo lectivo. La falta de un medio centralizado para gestionar los elementos intervinientes de manera estadarizada tambien dificulta la posibilidad de *analizar y explorar alternativas* y *optimizar* la asignación según distintos criterios.

Cabe notar que, a diferencia de un sistema productivo clásico, en una organización educativa no es sencillo cuantificar la "producción" ni la "calidad" del servicio. No hay piezas por hora ni tasas de defectos. Sin embargo, sí existen indicadores operativos concretos: alumnos que no acceden a un aula por falta de capacidad, clases que empiezan tarde por falta de previsibilidad, docentes que no pueden dar su clase en condiciones adecuadas. Estos son síntomas de una operatoria que puede mejorarse, y que puede ser comprendida, modelizada y optimizada con las herramientas de la ingeniería industrial. Sin embargo, no existen registros de observaciones de estos hechos que nos sirvan para cuantificar las consecuencias del problema y su efecto en la "produccion" de manera precisa.

## Idea controladora: el dominio como punto de partida

El presente informe se estructura alrededor de una idea central: *el diseño de soluciones robustas depende, en primera instancia, de una buena comprensión del dominio del problema*.

Esta afirmación, que puede parecer obvia, tiene implicancias profundas para la metodología de trabajo. En la ingeniería industrial, existen numerosas herramientas para comprender organizaciones y sus procesos: las tipologías de Mintzberg, los modelos de Chiavenato, el análisis de procesos, el estudio de métodos, la investigación operativa. Todas estas herramientas apuntan a construir un *modelo* de la realidad que permita luego intervenir sobre ella de forma fundamentada.

En la ingeniería de software existe una disciplina que parte de exactamente la misma premisa. Eric Evans, en *Domain-Driven Design: Tackling Complexity in the Heart of Software* (2003), propone que el desarrollo de software debe estar guiado por una comprensión profunda del dominio del negocio. El concepto central es que "la estructura y el lenguaje del código fuente — nombres de clases, métodos, variables — deben reflejar el dominio del negocio" (Evans, 2003). No se trata de modelar la tecnología primero y luego adaptarla al problema, sino de modelar el problema primero y luego traducirlo en software.

Este proyecto se sitúa en la intersección de ambas disciplinas. De la ingeniería industrial toma las herramientas para comprender la organización, caracterizar el problema y definir las restricciones y objetivos. De la ingeniería de software — y en particular del diseño guiado por el dominio — toma el enfoque para traducir esa comprensión en un modelo formal que pueda implementarse como sistema de información.

El proceso que se despliega a lo largo del informe sigue, entonces, un recorrido deliberado:

1. **Comprensión del dominio**: análisis de la organización, sus procesos, sus actores y sus reglas de negocio, utilizando herramientas de la ingeniería industrial.
2. **Modelización del dominio**: identificación de las entidades, sus relaciones, sus restricciones y su comportamiento, en un lenguaje que sea compartido entre el experto del dominio y el diseñador del sistema.
3. **Diseño de la solución**: traducción del modelo de dominio en un diseño de software, utilizando prácticas de UML, patrones de diseño y arquitectura de sistemas.
4. **Implementación y validación**: desarrollo del sistema y verificación de que la solución responde efectivamente a los requerimientos del dominio.

A lo largo de este recorrido, el informe exhibe continuamente dos facetas de análisis: la comprensión organizacional — propia de la ingeniería industrial — y el diseño técnico — propio de la ingeniería de software. La tesis implícita es que ambas no solo son compatibles sino que se potencian mutuamente: una sin la otra produce soluciones incompletas. Un sistema de información construido sin comprender el dominio será técnicamente funcional pero operativamente inadecuado. Un análisis organizacional sin traducción técnica quedará en el plano descriptivo, sin producir una herramienta concreta de mejora.

## Estructura del informe

<!-- TODO: completar cuando se definan las secciones -->

## Referencias

- Chiavenato, I. (2006). *Introducción a la Teoría General de la Administración* (7ma ed.). McGraw-Hill.
- Evans, E. (2003). *Domain-Driven Design: Tackling Complexity in the Heart of Software*. Addison-Wesley.
- Mintzberg, H. (1979). *The Structuring of Organizations*. Prentice-Hall. [Edición en español: *La estructuración de las organizaciones* (2012), Ariel.]
- Mintzberg, H. (2000). *Diseño de organizaciones eficientes*. El Ateneo.
- Miró, J. (2011). *Cómo escribir un texto académico*. Universidad de las Islas Baleares.
