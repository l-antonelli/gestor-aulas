# 4. Conclusiones

## 4.1 Síntesis del recorrido

El proyecto partió de una premisa: para resolver bien un problema
primero hay que entenderlo. Desde la ingeniería industrial analizamos
la facultad como organización y su proceso actual de asignación de
aulas (secciones 3.1 a 3.3), y de ese análisis surgió la definición del
problema como una asignación de recursos bajo restricciones (sección
3.4). Desde la ingeniería de software llevamos ese entendimiento a un
modelo del dominio y a un modelo de datos (secciones 3.5 y 3.6), sobre
los que se construyó la solución: una aplicación (sección 3.7) cuyo
núcleo es un programa lineal entero con verificación previa y
diagnóstico de la infactibilidad (sección 3.8), rodeado de validaciones
que garantizan que los datos que recibe son consistentes (sección 3.9).

El caso ensayado sobre el primer cuatrimestre de 2026 (secciones 3.10 y
3.11) mostró que la solución funciona con datos reales: asigna todos los
horarios presenciales de la facultad en menos de un minuto, respeta las
reglas de sedes, laboratorios y traslados, y permite comparar
configuraciones para elegir la que mejor responde a los criterios de la
institución.

## 4.2 El valor de la información en la gestión académica

No es difícil ver cómo una institución que congrega tantas personas
todos los días para realizar tantas actividades distintas puede
rápidamente transformarse en un entorno muy dinámico y complicado de
seguir día a día. Cientos de materias que se dictan, miles de alumnos
que concurren a clases, una cantidad finita de aulas para repartir en
una franja horaria limitada. Sólo la naturaleza combinatoria del
problema hace que un mínimo cambio en los supuestos o en alguna
configuración o criterio desencadene rápidamente la necesidad de
muchos otros ajustes, debido a restricciones cruzadas y a la
limitación de recursos. Poder dar respuesta rápida a las necesidades
de cursada, tan cambiantes y dinámicas, de una casa de estudio como
la FCEIA agiliza mucho la gestión de las actividades y permite tanto
a alumnos como a profesores concentrarse simplemente en el contenido
de sus clases.

Para poder dar este nivel de soporte a un proceso tan complejo como
es el de gestión de una cursada académica, es necesario partir de una
base de información sólida, completa y consistente. A menudo, cuando
la digitalización de una organización es baja, o coexisten distintos
sistemas de información que se usan con criterios no estandarizados,
suelen presentarse situaciones como las descritas en este informe. Es
de vital importancia realizar ejercicios como el propuesto al inicio
del presente trabajo para ordenar los actores y elementos
intervinientes y pasar en limpio un "manifiesto" de las operaciones
de una organización. Con esto se puede empezar a ahondar en
definiciones que terminan sirviendo para brindar cohesión y coherencia
a un sistema de información.

Sólo se pueden tomar decisiones tan buenas como los datos con los que
se analiza e interpreta la realidad y la medida en que estos modelan
correctamente el problema, sus criterios, restricciones y objetivos.
Le recomendamos a la institución seguir las recomendaciones del
presente informe, en particular en lo que concierne al mantenimiento
del catálogo de materias, carreras y planes, y del inventario de
aulas, ya que son los elementos centrales del problema de asignación
y de ellos surge la gran mayoría de las lógicas de validación de una
solución (que las aulas asignadas sean compatibles con lo que
requiere cada clase, que el esquema de asignación sea factible de
cursar para los alumnos que están al día, etc.).

La implementación del Gestor de Aulas representa un salto cualitativo
para la FCEIA, al modernizar los procesos organizativos
institucionales. Esta transición permite dejar atrás una
planificación operativa fragmentada, caracterizada por la dependencia
del esfuerzo manual y el uso de planillas dispersas, para consolidar
un modelo centralizado, transparente y auditable. Frente a los
desafíos de la problemática actual de gestión, esta solución trasciende
la mera distribución de espacios físicos: se convierte en un motor
analítico que transforma datos operativos aislados en conocimiento
estratégico para la toma de decisiones fundamentadas.

La administración eficiente, equitativa e integral de los recursos en
una institución de educación superior exige altos estándares de
certeza y previsibilidad. La consolidación de un sistema estructurado
y robusto posibilita:

- **Optimizar recursos críticos.** El algoritmo automatizado de
  asignación minimiza la subutilización o sobreocupación de la
  infraestructura física. Al cruzar las proyecciones estimadas de
  inscriptos con la capacidad real y el equipamiento de cada aula, se
  garantiza un aprovechamiento racional y eficiente de la planta
  física.
- **Anticipar problemas de capacidad.** A través de herramientas de
  diagnóstico, reportes consolidados y mapas de calor, el personal
  directivo puede identificar de forma temprana los puntos de
  saturación por sede, edificio y franja horaria. Esto facilita
  resolver superposiciones y conflictos logísticos de manera
  proactiva, antes del inicio del ciclo académico.
- **Garantizar la trazabilidad y la memoria institucional.** El
  registro detallado en el historial resguarda el fundamento y el
  contexto de cada modificación del catálogo y de las políticas de
  planificación. Este mecanismo reduce la dependencia del
  conocimiento tácito de personas específicas y fortalece la
  continuidad operativa de la facultad.

## 4.3 Principios de gestión de calidad

El diseño funcional y la adopción de esta plataforma están alineados
con los principios rectores de la gestión de calidad que recoge la
norma ISO 9001 [12]:

- **Toma de decisiones basada en evidencia.** La oferta académica, la
  aprobación de nuevas comisiones y la asignación de modalidades
  (presencial o virtual) se fundamentan en pronósticos de inscripción
  comprobables y métricas objetivas de capacidad, dejando de lado
  estimaciones empíricas o intuitivas.
- **Estandarización de procesos académicos.** La unificación del
  catálogo de asignaturas, los planes de estudio y las normativas de
  recursado asegura la consistencia administrativa, minimizando la
  variabilidad en la gestión y previniendo errores humanos.
- **Ciclo de mejora continua.** La posibilidad de crear escenarios en
  borrador, evaluar múltiples configuraciones y ajustar los pesos o
  cupos de las comisiones promueve una dinámica iterativa que eleva
  progresivamente la calidad del servicio educativo.

## 4.4 Factores clave para el éxito de la solución

Para maximizar el valor de la plataforma y asegurar su
sostenibilidad, el soporte tecnológico debe ir acompañado de una
cultura de rigor organizativo y operativo:

- **Integridad y actualización de los datos de origen.** La precisión
  de las asignaciones depende directamente de la exactitud de los
  datos ingresados. Mantener actualizadas las dimensiones y el
  equipamiento de las aulas y los planes de estudio vigentes es un
  requisito innegociable.
- **Disciplina en el resguardo de la información.** Dado que el
  sistema opera de forma local y sin autenticación centralizada,
  resulta crucial instituir rutinas periódicas de copia de seguridad
  de la base de datos.
- **Coordinación del equipo de usuarios.** Es indispensable formalizar
  acuerdos y protocolos internos que delimiten roles, momentos y
  permisos de edición, para evitar que las modificaciones de un
  usuario sobrescriban el trabajo de otro.

## 4.5 Configuración recomendada del asignador

Los escenarios de §3.10.4 dejan una recomendación concreta para usar
el asignador:

- **Grupos de materias.** Mantener la configuración de sedes de los
  grupos tal como está: modo duro para las materias que se dictan
  siempre en una sede, como las comunes de Formación Básica en
  Pellegrini, y modo blando para las carreras de la Siberia, cuyos
  alumnos también cursan esas comunes y quedan acoplados a Pellegrini
  por el margen de traslado.
- **Sin tolerancia de sobreocupación.** Una tolerancia del 10 % parece
  inofensiva, pero el asignador la aprovecha y, sumada, deja más de mil
  alumnos sin lugar. Sin tolerancia, la cifra baja un 22 %.
- **Castigar la subocupación, con una tolerancia moderada.** Sin ese
  castigo, el asignador ocupa aulas grandes con grupos chicos y reduce
  un 30 % la capacidad libre en los momentos de más demanda. Un peso
  bajo (1) con una tolerancia del 20 % reserva las aulas grandes para
  quien las necesita.
- **Pesos de sobreocupación y sede.** Un peso de sobreocupación de 25 y
  uno de sede preferida de 15 dan un buen equilibrio: priorizan que
  todos entren y que cada carrera curse en su sede, sin forzar ninguna
  de las dos cosas.

## 4.6 Trabajos futuros

El sistema deja abiertas varias líneas de continuidad:

- **Excepciones por fecha** sobre el patrón semanal, para feriados,
  semanas de exámenes o cambios puntuales.
- **Corridas incrementales** durante el cuatrimestre, que reasignen sólo
  lo afectado por un cambio y respeten el resto de la asignación.
- **Un pronóstico de inscripción más sofisticado**, que combine la serie
  histórica con datos de la cohorte, como la cantidad de alumnos que
  aprobaron las correlativas.
- **Penalizar los traslados entre sedes**, además de prohibir los que no
  dan el margen, para preferir los días con menos cambios de sede.
- **Días operativos por sede**, que complementen el horario propio que
  ya admite cada sede.
- **Extensión a otros recursos**, como las mesas de examen o los
  laboratorios de investigación.
- **Integración con el SIU Guaraní**, para tomar de ahí las comisiones y
  las inscripciones sin cargarlas a mano.
