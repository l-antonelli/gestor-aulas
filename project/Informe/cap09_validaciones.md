# Capítulo 9. Validaciones y garantías de consistencia

El capítulo anterior mostró cómo el asignador de aulas resuelve el
problema de la asignación como un programa lineal entero. La
formulación matemática asumía, implícitamente, que los datos que
alimentan al modelo son consistentes: que cada horario tiene una
comisión bien definida, que cada materia tiene sus horas
declaradas, que el cronograma cubre todos los dictados esperados
del ciclo, que los pares de materias en conflicto son realmente
incompatibles.

En la práctica, garantizar esa consistencia es tan importante como
formular bien el modelo. Un asignador correcto sobre datos rotos
produce resultados rotos. Este capítulo se ocupa de la **capa de
validaciones** que envuelve al asignador: qué reglas se verifican,
en qué momentos del flujo, cómo se comunican los resultados al
operador y cómo se garantiza la trazabilidad de los cambios que se
van acumulando a lo largo del cuatrimestre.

## 9.1 Por qué las validaciones son parte del diseño

Hay una tentación común al construir sistemas de optimización:
tratar a las validaciones como un aditivo tardío, una capa de
"chequeo defensivo" que se agrega cuando algo empieza a fallar.
El sistema adopta la posición opuesta: **las validaciones son
parte del diseño de la solución, no un remiendo posterior**.

Tres motivos sostienen esta decisión:

- **Los datos del dominio son complejos y evolutivos.** Un ciclo
  lectivo tiene cientos de horarios repartidos entre docenas de
  comisiones, con dictados anuales cruzados con cuatrimestrales,
  materias que cambian de plan entre cohortes, aulas que se
  agregan o se dan de baja. Es previsible que aparezcan
  inconsistencias operativas si nadie las detecta activamente.
- **Los errores caros son los silenciosos.** Si un cronograma
  tiene una materia faltante y el sistema lo descubre recién al
  correr el asignador y devolver "infactible", el operador pierde
  tiempo diagnosticando el LP cuando el problema real está en
  otro lado. Detectar el problema en el momento y lugar
  correctos, con un mensaje explícito, es más barato.
- **La confianza operativa se construye con transparencia.** Un
  sistema que valida activamente y explica lo que valida es más
  fácil de auditar y de mantener. El operador no necesita
  conocer el detalle del modelo; con leer las validaciones sabe
  qué está bien y qué no.

En este capítulo tratamos las validaciones desde tres ángulos:
como capas de la arquitectura del sistema (§9.2), como reglas con
severidad diferenciada (§9.3) y como mecanismos de auditoría y
trazabilidad (§9.4). El detalle exhaustivo del catálogo de
validaciones se remite al documento
`project/2. Desarrollo/VALIDACIONES.md`.

## 9.2 Capas de validación

El sistema aplica validaciones en cuatro capas ordenadas de la más
básica (motor de base de datos) a la más específica (chequeo
inline en la interfaz). Cada capa cubre lo que la anterior no
puede cubrir.

### 9.2.1 Constraints declarativas del motor

La capa más profunda son las **constraints del motor de base de
datos**: claves primarias, foráneas, uniques y chequeos de tipo.
El ORM (§7.1.4) las materializa a partir de las anotaciones de los
modelos. Estas constraints garantizan invariantes atómicas: que
todo aula tiene sede, que no hay dos aulas con el mismo código,
que las capacidades son positivas.

La ventaja de esta capa es que **ninguna operación de escritura
puede saltearla**: si un servicio intenta insertar una fila que
viola una constraint, la escritura falla. La desventaja es que
sólo cubre reglas simples y locales: no puede expresar
combinaciones ni condiciones globales del plan.

### 9.2.2 Invariantes de la capa de servicios

Las reglas que no se pueden expresar directamente como constraints
declarativas se garantizan en la **capa de servicios**. Ejemplos:

- La invariante de anclaje XOR de la comisión (§6.4.3): cada
  `ComisionDB` pertenece a un cronograma o a un plan, pero no a
  ambos.
- La invariante de partición estricta materia-grupo (§6.4.4):
  cada `MateriaDB` tiene grupo, y sólo puede haber un grupo con
  marca "sin clasificar".
- La invariante de coeficientes de asignación que suman uno
  dentro de un dictado.
- La regla de recursado jerárquica (§5.5.4), que determina si
  crear o no un dictado.

Estas reglas viven en funciones de los servicios que crean o
modifican las entidades correspondientes (§7.2.3). El anexo A
lista las invariantes con nombre propio (`INV-*`) y el punto del
código en donde se garantizan.

### 9.2.3 Validaciones agregadoras del cronograma y del plan

Encima de las invariantes puntuales hay una capa de **validaciones
agregadoras** que corren periódicamente sobre entidades completas
(un cronograma entero, un plan entero) y producen un reporte
consolidado. Son el corazón de la validación operativa del
sistema: el operador las dispara desde botones específicos de la
interfaz y recibe un resumen ejecutivo con detalle expandible.

Las dos validaciones agregadoras más importantes son:

- **`validar_cronograma`**: corre sobre un `ScheduleDB` en el
  contexto de un ciclo dado. Chequea cobertura (todas las
  materias esperadas están presentes), detecta materias extras
  (presentes en el cronograma pero no esperadas por el ciclo),
  verifica la partición teoría-laboratorio de cada comisión y
  detecta conflictos horarios dentro de cada grupo curricular.
- **`validar_plan`**: corre sobre un `PlanificacionCursadaDB`
  ya generado. Chequea las mismas dimensiones que la validación
  del cronograma, más las excepciones ignoradas (§6.4.7) y el
  chequeo de camino de cursada intersede (§8.4, R13-camino).

Ambas validaciones **persisten un snapshot** del resultado
(`ScheduleValidationDB` o `PlanValidationDB`) que la interfaz
puede volver a mostrar sin recomputar. Los snapshots quedan
disponibles para auditoría (§9.4).

Un caso especial que se documenta con nombre propio es la
**auto-limpieza de excepciones ignoradas** que corre como parte de
`validar_plan`: cuando el plan cambia y una excepción entre dos
materias deja de aplicar (porque las materias ya no coexisten en
ningún grupo curricular), la excepción se elimina automáticamente
y se reporta la limpieza al operador. Esta auto-limpieza es un
ejemplo puntual de una filosofía general: **el sistema mantiene
la coherencia por sí mismo cuando la puede detectar, y avisa al
operador de lo que hizo**.

### 9.2.4 Validaciones inline de la interfaz

La capa más superficial son las **validaciones inline** que corren
en la interfaz mientras el operador edita datos. Sirven para dar
feedback inmediato sin esperar a que se dispare la validación
agregadora completa. Ejemplos:

- Al editar las horas de una materia, la interfaz muestra si la
  suma teoría más laboratorio cierra con las horas semanales.
- Al asignar un aula manualmente, la interfaz detecta colisiones
  con otros horarios que la ocupan en la misma franja y ofrece
  liberar el ocupante para dejar que el asignador lo reasigne.
- Al editar comisiones dentro del panel de una materia, la
  interfaz muestra las validaciones locales de la materia (horas
  divisibles entre comisiones, clases paralelas dentro del
  límite, etc.).

Las validaciones inline no reemplazan a las agregadoras: son un
mecanismo de temprana detección para evitar que el operador
avance con datos inconsistentes hasta el próximo hito operativo.
Toda regla que aparece inline también aparece en la validación
agregadora correspondiente para garantizar cobertura completa.

### 9.2.5 Chequeo estructural del programa lineal

Como se documentó en §8.4, el asignador dispone además de un
**chequeo estructural pre-solve** que corre antes de invocar al
resolutor. Es una quinta capa de validación específica del
programa lineal: verifica condiciones que hacen infactible al
modelo antes de gastarle tiempo al resolutor. Los bloqueos que
detecta (R1 sin aula compatible, R3+R4 pigeonhole, Hall,
partición teoría-laboratorio, R11 pin incompatible, R13
intersede, R13-camino) están documentados en §8.4.

Este chequeo se apoya en las capas anteriores: para que tenga
sentido correrlo, los datos deben cumplir las invariantes básicas
(§9.2.1-2) y las validaciones agregadoras deberían haber corrido
al menos una vez sobre el plan (§9.2.3). El chequeo estructural
detecta los problemas que sólo se ven al considerar la
combinación de todas las restricciones simultáneamente.

## 9.3 Severidades y su semántica

Las validaciones del sistema producen tres severidades. La
distinción es intencional y sostiene el flujo operativo.

- **BLOCKER**: la validación detectó una violación que hace
  operativamente imposible avanzar al próximo paso. Ejemplo: un
  plan con conflictos horarios no ignorados dentro de un grupo
  curricular no puede activarse. Un cronograma con partición
  teoría-laboratorio infactible en al menos una comisión no
  puede generar un plan.
- **WARNING**: la validación detectó una situación anómala que el
  operador debería revisar, pero que no impide avanzar. Ejemplo:
  la presencia de materias en el grupo "sin clasificar" (§6.4.4)
  es un warning: se puede correr el asignador con esas materias
  en fallback permisivo, pero conviene curar la asignación.
- **INFO**: información puramente notificativa, sin implicancia
  operativa directa. Ejemplo: la auto-limpieza de excepciones
  ignoradas se reporta como INFO para que el operador sepa qué
  ocurrió, aunque no requiera acción.

La interfaz colorea las validaciones según severidad (rojo,
amarillo, azul) y las lista ordenadas: primero los BLOCKER,
después los WARNING, después los INFO. Los mensajes son
específicos y accionables: no dicen "hay un problema" sino "la
comisión C de Análisis Matemático I tiene 3 horas de horarios
teóricos pero la materia declara 4 horas de teoría", con enlaces
directos a la entidad afectada.

La responsabilidad del operador es resolver los BLOCKER antes de
avanzar; los WARNING se pueden dejar para revisar más tarde; los
INFO se leen y se archivan. El sistema no bloquea al operador por
WARNING salvo que la lógica operativa lo requiera explícitamente
(por ejemplo, no permite activar un plan con conflictos no
ignorados).

## 9.4 Auditoría y trazabilidad

Todo sistema que opera sobre datos con impacto real necesita
garantías de trazabilidad: quién cambió qué, cuándo y por qué. En
el sistema, esta trazabilidad se sostiene con tres mecanismos
complementarios.

### 9.4.1 Snapshots de validaciones y corridas

Cada vez que se corre una validación agregadora o una corrida del
asignador, el sistema persiste un **snapshot completo** del
resultado. `ScheduleValidationDB` para el cronograma,
`PlanValidationDB` para el plan, `LPRunDB` para el asignador.
Todos incluyen:

- Referencia a la entidad validada (el cronograma, el plan).
- Fecha y hora de la corrida.
- Configuración aplicada.
- Resumen agregado (contadores, métricas top-line).
- Detalle serializado en JSON con toda la información puntual
  (por horario, por comisión, por materia).

Los snapshots **no se sobreescriben**: cada corrida agrega una
fila nueva. La interfaz muestra por defecto la más reciente pero
mantiene todas para consulta. Esta política permite:

- Comparar dos corridas con configuraciones distintas.
- Auditar la evolución del plan a lo largo del cuatrimestre.
- Reproducir cualquier corrida vieja con exactitud (todos los
  parámetros están persistidos).

Cada snapshot lleva además un mecanismo de **staleness**: el
sistema calcula, a partir de contadores clave del entorno de
ejecución (cantidad de comisiones, horarios, dictados al momento
de correr), si el snapshot sigue vigente respecto del estado
actual de la base. Si el operador cambia el plan después de
correr la validación, la interfaz señala que el snapshot está
desactualizado y ofrece re-ejecutarlo.

### 9.4.2 Registro de mutaciones (change log)

Complementando los snapshots operativos, el sistema mantiene un
**registro global de mutaciones** sobre las entidades del
catálogo. Cada evento del log guarda:

- Qué entidad se modificó (`entity_type` y `entity_id`).
- Qué campo cambió y sus valores previo y nuevo.
- Cuándo ocurrió y qué origen tuvo (por ejemplo,
  `origin=ui:ciclos` o `origin=lp:run`).
- Opcionalmente, una razón textual del cambio.

Los eventos del log se emiten automáticamente para las mutaciones
más importantes (cambios en materias, carreras, dictados, grupos
de materias, sedes) a través de hooks del ORM. Los servicios
pueden emitir eventos explícitos con contexto adicional cuando la
acción no es una simple mutación de campo (por ejemplo, "materia
promovida a regla de recursado desde el ciclo 2026-1C").

El log se consulta desde la vista "Historial" con dos modos: un
feed global filtrable por tipo de entidad y origen, y una vista
por entidad puntual que muestra la línea de tiempo de esa entidad
específica.

### 9.4.3 Configuración persistida por corrida del asignador

Un caso especial de trazabilidad, ya mencionado en §8.8: cada
corrida del asignador persiste el **dump completo de la
configuración usada**, incluyendo modos por grupo, pesos,
tolerancias y toggles. Esto tiene dos consecuencias directas:

- **Reproducibilidad exacta**: cualquier corrida vieja se puede
  reproducir cargando su configuración desde el snapshot.
- **Comparabilidad**: dos corridas con configuraciones distintas
  se pueden comparar campo por campo para entender qué cambió y
  atribuir diferencias en el resultado.

La interfaz explota estos snapshots en dos direcciones: al abrir
el panel del asignador, precarga la configuración con los valores
de la última corrida (para permitir iterar sobre una config
conocida sin re-configurar desde cero), y expone en el veredicto
un expander con la configuración completa aplicada para que el
operador pueda auditarla.

## 9.5 Un ejemplo integrado

Para cerrar el capítulo, un ejemplo que ilustra cómo se articulan
las cuatro capas de validación (§9.2), las tres severidades
(§9.3) y los tres mecanismos de trazabilidad (§9.4) en una
operación cotidiana.

Supongamos que el operador está preparando el plan de cursada del
segundo cuatrimestre. Empieza con el cronograma cargado y el plan
recién generado. Los pasos:

1. **El operador entra al plan y edita la comisión "A" de una
   materia**, cambiándole el nombre de "Comisión A" a "A-Turno
   Mañana". La validación inline (§9.2.4) verifica que el nombre
   sea único dentro de la materia; la escritura al servicio
   dispara la constraint de nombre no vacío (§9.2.1) y emite un
   evento al change log (§9.4.2).

2. **El operador dispara la validación completa del plan**. El
   servicio agregador (§9.2.3) corre las validaciones: cobertura,
   conflictos, partición, camino de cursada. Detecta:
   - Un BLOCKER: la partición teoría-laboratorio de una comisión
     no cierra.
   - Un WARNING: dos materias del grupo "sin clasificar" tienen
     comisiones en el plan.
   - Un INFO: una excepción ignorada quedó stale y se
     auto-limpió.

   La interfaz muestra los tres mensajes ordenados por severidad.
   El operador arregla el BLOCKER (ajusta las horas del horario o
   las horas declaradas de la materia), deja el WARNING para
   revisar más tarde y archiva el INFO. El snapshot de la
   validación se persiste (§9.4.1).

3. **El operador dispara el asignador de aulas**. Antes de correr
   el resolutor, el chequeo estructural pre-solve (§9.2.5, §8.4)
   verifica que no haya bloqueos garantizados. Detecta:
   - Un R13-camino: para 3° año de Ingeniería Electrónica del
     primer cuatrimestre, no existe combinación de comisiones
     viable (dos materias contiguas con sedes disjuntas). El
     operador ajusta el margen intersede o reasigna una
     comisión.

4. **Con el problema resuelto, se corre el asignador**. El
   resolutor devuelve `optimal`. El sistema aplica la solución al
   patrón semanal y persiste una fila `LPRunDB` con el veredicto,
   la configuración completa y el detalle por horario (§9.4.3).

5. **Días después el operador vuelve al plan**. La interfaz
   muestra que el snapshot de la última validación tiene
   staleness (§9.4.1): entre medio se editaron horarios que la
   validación no vio. El operador re-corre la validación y
   confirma que sigue todo verde.

Todo el flujo dejó rastros que el operador o un auditor pueden
recorrer: los snapshots de validación, los `LPRunDB` con la
configuración exacta, los eventos del change log. Nada quedó
como decisión "en la cabeza del operador" sin evidencia
persistida.

## 9.6 Recapitulación

Este capítulo dejó documentada la capa de validaciones que rodea
al asignador y garantiza consistencia. Los puntos que se
retoman en el capítulo siguiente:

1. **Las validaciones son parte del diseño de la solución.** No
   son un aditivo defensivo: son un componente estructural que
   convierte al asignador de una caja negra en un asistente
   operativo confiable.
2. **Se organizan en cinco capas complementarias**: constraints
   del motor, invariantes de servicios, validaciones agregadoras,
   validaciones inline y chequeo estructural del programa lineal.
   Cada capa cubre lo que la anterior no puede cubrir.
3. **Tres severidades ordenan la comunicación con el operador**:
   BLOCKER, WARNING e INFO. Los mensajes son específicos y
   accionables.
4. **Tres mecanismos de trazabilidad sostienen la auditoría**:
   snapshots por operación (validación o corrida del LP),
   registro global de mutaciones y persistencia de configuración
   por corrida.
5. **Todos los cambios dejan rastro persistido.** El operador o
   un auditor pueden reconstruir el estado del sistema en
   cualquier momento pasado, comparar corridas y entender por
   qué el asignador tomó las decisiones que tomó.

Con la capa de validaciones documentada, el capítulo siguiente
recorre la herramienta en acción: cómo se opera efectivamente el
sistema desde la interfaz, con capturas comentadas y un ejemplo
integral sobre datos reales de FCEIA.
