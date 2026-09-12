# Capítulo 7. Arquitectura de la solución

Los capítulos 5 y 6 dejaron fijado *qué* se modela y *cómo* se
guarda. Este capítulo se ocupa del **cómo se implementa**: qué
tecnologías sostienen la solución, cómo se organiza el código y
cómo fluye una operación de punta a punta, desde una acción del
operador en la interfaz hasta la persistencia en la base y la
respuesta de vuelta a la pantalla.

El capítulo cumple tres objetivos:

- Presentar el **stack tecnológico completo** de una sola vez, con
  la justificación de cada elección y las alternativas que se
  descartaron. El capítulo 6 pospuso esa justificación
  intencionalmente para no mezclar la discusión del modelo de
  datos con la elección de tecnología.
- Explicar la **separación en capas** que estructura el código y
  cómo cada capa se apoya sobre la anterior.
- Describir el **flujo end-to-end** que atraviesa el sistema, con
  los hitos operativos que después van a servir para explicar las
  validaciones (capítulo 9) y la corrida del programa lineal
  (capítulo 8).

## 7.1 Stack tecnológico

El sistema se implementa como una **aplicación web de una sola
página** con backend en Python y persistencia local. El stack
completo se resume en la siguiente pila:

| Capa | Tecnología | Rol |
| --- | --- | --- |
| Interfaz de usuario | Streamlit | Renderiza la aplicación web, maneja el estado de sesión y expone formularios, tablas y visualizaciones. |
| Lenguaje base | Python 3.11+ | Corre todo el código: interfaz, servicios, resolutor. |
| Validación de datos | Pydantic | Valida los objetos que atraviesan las capas y expone anotaciones de tipo consistentes. |
| Mapeo objeto-relacional | SQLModel | Combina Pydantic con SQLAlchemy: define entidades como clases Python y las materializa como tablas. |
| Motor de base de datos | SQLite | Guarda todo el estado del sistema en un archivo local (`data/database.db`). |
| Optimización | PuLP | Biblioteca de programación lineal que expresa el modelo como código Python. |
| Resolutor | CBC | Resolutor de programación lineal entera libre y open source, invocado a través de PuLP. |
| Visualización | Altair y componentes nativos de Streamlit | Gráficos de saturación, tablas de resultado, calendarios semanales. |

Cada elección se justifica a continuación.

### 7.1.1 Python como lenguaje base

Elegir Python como lenguaje base es la decisión más consecuente
del stack, porque condiciona todo lo demás. Los motivos:

- **Ecosistema maduro de optimización y datos.** Bibliotecas como
  PuLP, OR-Tools, NumPy, Pandas y scikit-learn son de primer
  nivel en Python. Cualquier extensión futura del proyecto que
  involucre pronósticos de matrícula, análisis de resultados de
  corridas o reportes cuantitativos se apoya en herramientas
  disponibles nativamente.
- **Interfaz gráfica sin cambio de contexto.** Las bibliotecas
  actuales de Python permiten construir interfaces web sin salir
  del lenguaje. Evitar la mezcla Python-backend con
  JavaScript-frontend reduce la superficie de fricción del
  desarrollo y facilita mantener una única base de código.
- **Legibilidad como criterio.** Python favorece código que se lee
  con facilidad. Para un proyecto académico de mediano plazo,
  donde la claridad del código sobrevive al desarrollo original,
  esto pesa.

Se descartaron alternativas como Java (más ceremonioso, ecosistema
de optimización más limitado en el nicho libre) y JavaScript o
TypeScript (buenos para la interfaz pero flojos para
optimización combinatoria).

### 7.1.2 Streamlit como interfaz

Streamlit es una biblioteca de Python que permite construir
aplicaciones web interactivas escribiendo código Python
convencional, sin manejar directamente HTML, CSS ni JavaScript. Sus
características determinantes para este proyecto:

- **Modelo declarativo simple.** Cada página de la aplicación se
  escribe como un script Python que se re-ejecuta ante cada
  interacción. Streamlit se encarga de renderizar los widgets, el
  layout y el estado. No hay necesidad de plantillas ni endpoints
  REST.
- **Widgets ricos con muy poco código.** Formularios, tablas
  editables, selects, sliders, uploaders de archivo, calendarios,
  gráficos: todo está disponible como funciones cortas. La
  velocidad de iteración es alta.
- **Integración natural con Pandas y Altair.** Los DataFrames de
  Pandas se renderizan como tablas interactivas con casi cero
  configuración; los gráficos de Altair aparecen como componentes
  nativos.

Se descartaron alternativas como Flask con plantillas Jinja
(más código boilerplate para formularios y tablas) y React o Vue
(overhead innecesario y obliga a mantener una API separada). El
único costo real de Streamlit es que su modelo de re-ejecución
completa ante cada interacción exige cuidado con las operaciones
caras: hay que cachear resultados que no cambian. El sistema lo
resuelve con el mecanismo estándar `@st.cache_data` de Streamlit
donde aplica.

### 7.1.3 SQLite como motor de base

SQLite es un motor de base de datos relacional embebido: no requiere
un servidor separado, guarda toda la base en un archivo del sistema
de archivos y ofrece un subconjunto muy fiel del SQL estándar. Se
lo eligió porque:

- **Cero configuración.** No hay que instalar un servidor, abrir un
  puerto ni configurar credenciales. La base es un archivo que se
  puede versionar, copiar, respaldar y compartir.
- **Suficiente para el volumen.** El sistema maneja algunos miles
  de filas por tabla en el peor caso. SQLite resuelve
  cómodamente cargas hasta muchos órdenes de magnitud mayores.
- **Migración eventual sencilla.** SQLModel (ver §7.1.4) abstrae
  el motor: si el sistema escalara a un contexto multiusuario o
  distribuido, la migración a PostgreSQL requeriría cambios muy
  acotados.

Se descartaron alternativas como PostgreSQL (overhead de setup
para un despliegue local) y MongoDB (los datos son fuertemente
relacionales; forzarlos a un esquema documental introduce
duplicación e inconsistencia).

### 7.1.4 SQLModel como ORM

SQLModel es una biblioteca que combina Pydantic (validación de
datos con anotaciones de tipo) con SQLAlchemy (mapeo
objeto-relacional maduro y ampliamente usado). Ofrece:

- **Una única definición para varias tareas.** La misma clase
  Python funciona como esquema de validación, como modelo de la
  tabla en la base y como estructura que atraviesa las capas del
  sistema. Sin duplicación entre "el objeto validado en la
  interfaz" y "la fila que se persiste".
- **Anotaciones de tipo en todo el código.** Los editores y los
  chequeadores estáticos pueden razonar sobre las estructuras que
  circulan por el sistema. La lectura del código gana claridad.
- **Compatibilidad con el resto del ecosistema.** Los objetos se
  pueden convertir a DataFrames de Pandas sin ceremonia, lo que
  simplifica reportes y visualizaciones.

Se descartaron alternativas como SQLAlchemy puro (más verboso, sin
validación integrada) y Peewee (integración más pobre con
Pydantic).

### 7.1.5 PuLP y CBC para el programa lineal

PuLP es una biblioteca de Python que expresa problemas de
programación lineal y entera con una sintaxis expresiva y que
delega la resolución a un resolutor externo. El resolutor por
defecto que usa el sistema es **CBC** (*Coin-or Branch and Cut*),
un resolutor libre, open source y ampliamente probado para
programación lineal entera.

Se eligió PuLP porque:

- **Sintaxis clara.** Un modelo se escribe como una sucesión de
  variables, restricciones y una función objetivo. La cercanía
  entre la formulación matemática y el código lo hace legible.
- **Compatible con múltiples resolutores.** PuLP separa la
  formulación del resolutor: si en el futuro se necesitara
  cambiar de CBC a Gurobi (comercial) o HiGHS (libre, más nuevo),
  el modelo no cambia; sólo cambia la línea que invoca al
  resolutor.

Se descartó OR-Tools de Google porque introduce una capa de
abstracción propia menos alineada con el vocabulario matemático
estándar; para un proyecto académico, la cercanía al vocabulario
formal favorece la comprensión del modelo. El capítulo 8 desarrolla
la formulación del modelo con este vocabulario.

### 7.1.6 Visualización con Altair y componentes nativos

Los gráficos del sistema (saturación por franja, ocupación por
sede, heatmaps de conflictos) se generan con **Altair**, una
biblioteca declarativa de visualización basada en el sistema de
gramática visual de Vega-Lite. Se eligió Altair sobre Matplotlib
por su modelo declarativo (uno describe el gráfico, no el
procedimiento de dibujo) y por su integración natural con
Streamlit y Pandas. Las tablas y calendarios semanales se
renderizan con componentes nativos de Streamlit y con
`FullCalendar` embebido para las vistas por aula.

## 7.2 Separación en capas

El código del sistema se organiza en cuatro capas con
responsabilidades bien delimitadas. La regla de dependencia va
siempre de arriba hacia abajo: cada capa conoce a las que están
debajo, no al revés.

```
┌───────────────────────────────────────────────────────────────┐
│  Interfaz (páginas y componentes Streamlit)                   │
│  app/pages/*.py, src/ui/*.py                                  │
└─────────────────────────────┬─────────────────────────────────┘
                              │ invoca
                              ▼
┌───────────────────────────────────────────────────────────────┐
│  Servicios (lógica de dominio agrupada por área)              │
│  src/services/*.py                                            │
└─────────────────────────────┬─────────────────────────────────┘
                              │ usa
                              ▼
┌───────────────────────────────────────────────────────────────┐
│  Persistencia (repositorios y CRUD sobre SQLModel)            │
│  src/database/*.py                                            │
└─────────────────────────────┬─────────────────────────────────┘
                              │ mapea
                              ▼
┌───────────────────────────────────────────────────────────────┐
│  Modelo (entidades del ORM)                                   │
│  src/database/models.py                                       │
└───────────────────────────────────────────────────────────────┘
```

### 7.2.1 Capa de modelo

Contiene las **clases del ORM** que representan las entidades del
capítulo 5 (una a una, salvo los desdoblamientos y agregados
técnicos justificados en el capítulo 6). Es la única capa que
conoce el motor relacional y las convenciones de mapeo.

Las clases del modelo se definen en `src/database/models.py`. Cada
clase corresponde a una tabla y cada campo, a una columna. Es un
archivo largo pero completamente descriptivo: leerlo alcanza para
tener una vista completa del esquema.

### 7.2.2 Capa de persistencia

Encima del modelo hay funciones que atienden operaciones básicas
de lectura y escritura: crear una fila, actualizar campos, borrar,
consultar por identificador, listar con filtros. Estas operaciones
viven en `src/database/crud.py` y en los archivos de
`src/database/relationship_definitions.py`, que declara las
cascadas de borrado que el sistema aplica por política aunque el
motor no las active como constraints estrictas.

La capa de persistencia **no contiene lógica de dominio**: no sabe
qué combinaciones de valores son válidas ni cuándo hay que
disparar una validación. Sólo garantiza que las operaciones básicas
funcionan y que las cascadas de borrado se respetan.

### 7.2.3 Capa de servicios

Concentra la **lógica de dominio**: qué significa crear una
comisión, generar un plan de cursada a partir de un cronograma,
correr el asignador de aulas, validar un plan, resolver la
virtualidad efectiva de un horario. Los servicios se agrupan por
área en `src/services/`:

- `carrera_sede_service.py`: legado, se conserva sólo para
  compatibilidad de esquema y no participa del asignador.
- `grupo_materia_service.py`: gestión de grupos de materias y
  resolución de sedes admisibles y preferidas por materia.
- `comision_service.py`: creación y edición de comisiones, con
  la invariante de anclaje XOR entre cronograma y plan.
- `dictado_service.py`: generación y sincronización de dictados
  con la regla de recursado jerárquica.
- `schedule_service.py` y `cronograma_validation_service.py`:
  carga y validación de cronogramas.
- `plan_generation_service.py` y `plan_validation_service.py`:
  generación y validación de planes de cursada.
- `asignacion_aulas_service.py`: núcleo del asignador de aulas
  (armado del programa lineal, ejecución, aplicación de la
  solución, persistencia de la corrida).
- `factibilidad_service.py`: chequeo estructural pre-solve del
  programa lineal (ver capítulo 8).
- `forecast_service.py`: pronóstico de inscriptos por comisión.
- `resolucion_jerarquica.py`: funciones puras para virtualidad y
  recursado en cascada.
- `change_log_service.py`: registro de auditoría.
- `validations.py`: chequeos transversales que abarcan varias
  entidades.

La regla clave de esta capa es que **es la única que expresa
reglas del dominio**. Ni la interfaz ni la persistencia deciden
qué es válido: preguntan a un servicio y actúan según su
respuesta.

### 7.2.4 Capa de interfaz

La interfaz se implementa como un conjunto de **páginas Streamlit**
en `app/pages/` (una página por área funcional principal:
materias, aulas, carreras, ciclos, cronogramas, planes, aulas del
plan, inscriptos, historial) más un conjunto de **componentes
reutilizables** en `src/ui/` (paneles, editores, validadores en
línea, calendarios).

La interfaz **no contiene lógica de dominio**: recolecta los datos
que introduce el operador, se los pasa a los servicios y renderiza
las respuestas. Cuando aparece una regla de validación en línea
(por ejemplo, "las horas de teoría más las de laboratorio deben
cerrar con las horas semanales"), esa regla vive en un servicio de
validación; la interfaz sólo la invoca y muestra el resultado.

Esta disciplina es la que permite testear la lógica del sistema de
manera independiente de Streamlit: las pruebas automatizadas
llaman directamente a los servicios sin instanciar la interfaz.

## 7.3 Flujo end-to-end

Para dar una idea integrada del funcionamiento del sistema
recorremos el flujo canónico completo: desde la carga de datos
iniciales hasta la asignación final de aulas. El flujo es lineal
y refleja el orden natural en que el usuario opera el sistema
cuatrimestre a cuatrimestre.

```
┌────────────────────┐
│ 0. Carga inicial   │  Script CLI que carga materias, carreras,
│    (script CLI)    │  planes, laboratorios y aulas desde Excel.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 1. Ciclo + planes  │  Alta del ciclo lectivo (año + 1C/2C) y
│                    │  asociación de las versiones de plan que
│                    │  aplican a ese ciclo.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 2. Dictados        │  Generación automática de dictados a partir
│                    │  de las materias del plan, aplicando la
│                    │  regla de recursado jerárquica.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 3. Cronograma      │  Carga de un archivo Excel con los horarios
│                    │  del cuatrimestre. Prevalidación contra los
│                    │  dictados activos del ciclo.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 4. Plan de cursada │  Generación del plan a partir del cronograma:
│                    │  clonado de comisiones y horarios.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 5. Refinado del    │  Edición manual de horarios, tipo de clase,
│    plan            │  comisiones, override de inscriptos esperados.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 6. Validación      │  Chequeo integral: cobertura, conflictos,
│                    │  partición teoría-laboratorio, excepciones
│                    │  ignoradas. Snapshot persistido.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 7. Asignador       │  Corrida del programa lineal: chequeo
│    de aulas        │  estructural pre-solve, resolución con CBC,
│                    │  aplicación al patrón, snapshot persistido.
└─────────┬──────────┘
          │
          ▼
┌────────────────────┐
│ 8. Análisis        │  Inspección del resultado, resolución de
│                    │  colisiones al editar manualmente, ajuste
│                    │  de configuración y re-corrida.
└────────────────────┘
```

### 7.3.1 Detalle de cada etapa

**Etapa 0. Carga inicial.** Un script de línea de comandos
(`python -m scripts.load_initial_data --reset`) inicializa la base
a partir de tres archivos Excel de entrada: materias, plan de
estudios por carrera y aulas. Es una etapa idempotente que se
ejecuta al arrancar el sistema por primera vez o cuando se decide
reiniciar el estado. El anexo del proyecto documenta el formato
esperado de cada Excel de entrada.

**Etapa 1. Ciclo lectivo.** Desde la interfaz, el operador crea el
ciclo (año, cuatrimestre, fechas) y asocia las versiones de plan
que aplican. A partir de esa asociación, el sistema *conoce* qué
materias se van a dictar en el ciclo.

**Etapa 2. Dictados.** El sistema genera automáticamente los
dictados de la etapa 1, aplicando la regla de recursado
jerárquica (§5.5.4): la carrera declara si ofrece recursado, la
materia puede sobreescribir con su propio flag. Los dictados que
la regla no permite se saltean con una advertencia en el reporte
de generación.

**Etapa 3. Cronograma.** El operador carga un archivo Excel con
los horarios del cuatrimestre. El archivo se valida contra los
dictados activos: se detectan materias esperadas pero ausentes,
materias no esperadas presentes, particiones teoría-laboratorio
que no cierran, etcétera. La interfaz muestra un reporte
consolidado y permite editar en línea las filas del cronograma
para resolver los problemas.

**Etapa 4. Plan de cursada.** A partir del cronograma validado, el
sistema genera el plan: crea comisiones (clonadas desde las
comisiones template del cronograma) y horarios semanales. Cada
plan queda registrado como una entidad separada; puede haber
varios planes por ciclo (uno activo y los demás como escenarios de
comparación).

**Etapa 5. Refinado del plan.** El operador edita el plan en
línea: ajusta comisiones, edita horarios, marca laboratorios
compatibles, sobrescribe manualmente pronósticos de inscriptos si
tiene información no reflejada en la serie histórica.

**Etapa 6. Validación.** El sistema corre un chequeo integral del
plan: cobertura de todas las materias esperadas del ciclo, ausencia
de conflictos horarios dentro de cada grupo curricular, partición
teoría-laboratorio válida en todas las comisiones. Las excepciones
que el operador quiere ignorar (materias homónimas de años
distintos que nunca comparten alumnos, por ejemplo) se declaran
como pares ignorados. El resultado se persiste como snapshot
(`PlanValidationDB`).

**Etapa 7. Asignador de aulas.** El operador dispara el asignador
desde el panel de aulas del plan. El sistema primero corre un
chequeo estructural pre-solve (¿existe alguna causa que hace
infactible al problema antes de siquiera invocar al resolutor?);
si el chequeo pasa, se construye el programa lineal, se lo resuelve
con CBC y se aplica la solución al patrón semanal. Toda la corrida
se persiste como snapshot (`LPRunDB`), con un veredicto
humano-legible que la interfaz renderiza (ver capítulo 8).

**Etapa 8. Análisis y ajuste.** Con el resultado en la mano, el
operador inspecciona la asignación. Puede editar manualmente
aulas puntuales (con detección automática de colisiones), cambiar
la configuración del asignador (pesos, tolerancias, modos de
grupo, margen intersede) y volver a correr.

## 7.4 Interacción entre capas: un ejemplo

Para ilustrar cómo se articulan las capas, tomamos un caso
concreto: el operador hace clic en el botón "Correr asignador de
aulas" desde el panel del plan.

```
Usuario                                     Interfaz
   │                                           │
   │  Click "Correr asignador"                 │
   │──────────────────────────────────────────▶│
   │                                           │
   │                                           │ Recoge la
   │                                           │ configuración
   │                                           │ del formulario
   │                                           │ (pesos, modos,
   │                                           │ toggles).
   │                                           │
   │                                           │
   │                          asignacion_aulas_service.run_lp(session, plan_id, config)
   │                                           │──────────────────▶ Servicio
   │                                           │                       │
   │                                           │                       │ 1. Chequeo
   │                                           │                       │    estructural
   │                                           │                       │    pre-solve.
   │                                           │                       │
   │                                           │                       │ 2. Construir
   │                                           │                       │    programa
   │                                           │                       │    lineal.
   │                                           │                       │
   │                                           │                       │ 3. Resolver
   │                                           │                       │    con CBC.
   │                                           │                       │
   │                                           │                       │ 4. Aplicar
   │                                           │                       │    solución al
   │                                           │                       │    patrón.
   │                                           │                       │
   │                                           │                       │ 5. Persistir
   │                                           │                       │    snapshot.
   │                                           │                       │
   │                                           │◀────────────────── LPRunDB
   │                                           │
   │                                           │ Renderiza el
   │                                           │ veredicto, la
   │                                           │ tabla de horarios
   │                                           │ y el mapa de
   │                                           │ saturación.
   │                                           │
   │  Ve resultado                             │
   │◀──────────────────────────────────────────│
```

Cada paso del servicio invoca a la capa de persistencia cuando
necesita leer o escribir en la base, y a otros servicios cuando
necesita reglas de dominio auxiliares. Toda la lógica de
factibilidad, construcción del modelo, resolución y aplicación de
la solución vive en la capa de servicios; la interfaz se limita a
recolectar parámetros y a renderizar el resultado. La aplicación
del snapshot y la propagación al caché técnico (`ClaseDB`) las
maneja el servicio en una sola transacción.

## 7.5 Recapitulación

Este capítulo dejó explicitado el andamiaje técnico sobre el que
descansa la solución. Los puntos que se retoman en los capítulos
siguientes:

1. **El stack se justificó de una sola vez.** Python como lenguaje
   base, Streamlit para la interfaz, SQLModel sobre SQLite para
   persistencia, PuLP con CBC para el programa lineal. Cada
   elección responde a criterios explícitos (velocidad de
   desarrollo, ecosistema, cercanía al vocabulario matemático,
   portabilidad).
2. **El código se organiza en cuatro capas** con dirección de
   dependencia unívoca: interfaz sobre servicios sobre
   persistencia sobre modelo. La lógica de dominio vive
   íntegramente en la capa de servicios.
3. **El flujo end-to-end es lineal** en ocho etapas identificables:
   carga inicial, alta de ciclo, dictados, cronograma, plan,
   refinado, validación, asignación. Cada etapa es punto de
   entrada operativo y punto de anclaje para las validaciones
   del capítulo 9.
4. **La invocación al programa lineal se apoya en tres momentos
   discretos**: chequeo estructural pre-solve, resolución con
   CBC y persistencia del snapshot. El capítulo 8 desarrolla en
   detalle cada uno.

Con el andamiaje fijado, el capítulo siguiente entra en el corazón
del sistema: la formulación del problema de asignación de aulas
como un programa lineal entero.
