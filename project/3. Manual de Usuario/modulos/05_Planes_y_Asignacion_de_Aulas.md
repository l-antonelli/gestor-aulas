# Planes de cursada y asignación de aulas

## ¿Para qué sirve?

El **plan de cursada** es la "receta" concreta del cuatrimestre: qué
materias se dictan, en qué días y horarios, con qué comisiones, y en
qué aulas. Nace a partir de un cronograma ya validado y se convierte
en el documento vivo con el que se cierra la planificación del ciclo.

Este módulo también es donde se corre el **asignador de aulas**, la
herramienta que decide qué aula usa cada horario del plan. El
asignador mira todas las restricciones (tipos de aula, sedes por
carrera, choques, capacidad, inscriptos esperados) y elige la mejor
combinación posible. Si no puede resolver, te devuelve un
diagnóstico detallado explicando dónde está el problema.

Los dos temas están íntimamente ligados: el plan es la entrada del
asignador, y el resultado del asignador se guarda dentro del plan.
Por eso conviven en la misma página.

## ¿Cuándo vas a usar este módulo?

- **Después de validar un cronograma** como vigente para el ciclo:
  ese es el momento para generar el plan de cursada.
- **Al ajustar comisiones**: cambiar cupos, agregar o cerrar
  comisiones, marcar una comisión para una carrera específica.
- **Para correr el asignador de aulas**: siempre que quieras que el
  sistema resuelva qué aula usa cada horario.
- **Para revisar el resultado del asignador**: interpretar los mapas
  de calor, la tabla de resultados y, si hay problemas, el
  diagnóstico.
- **Para hacer ajustes finos post-asignación**: cambiar un aula a
  mano, marcar un horario como virtual, redistribuir pesos entre
  comisiones.
- **Para activar oficialmente el plan** del ciclo, generar las clases
  y dar por cerrada la planificación.

## Cómo se relaciona con el resto

Este módulo es el **último eslabón del flujo**:

```
Catálogo (Materias, Carreras, Aulas, Planes de Estudio)
        │
        ▼
    Ciclos (con dictados creados)
        │
        ▼
    Cronogramas (validado y vigente)
        │
        ▼
    Planes de Cursada + Asignación de Aulas   ← este módulo
```

- **Depende de**: Ciclos (con sus dictados) + Cronogramas (con al
  menos uno validado como vigente).
- **Consume**: Aulas (los recursos que asigna), Carreras y sus sedes
  habilitadas (las restricciones de sede), Inscriptos (para forecast
  de esperados).
- **Alimenta**: nada más. Es el módulo final del flujo. Todo lo que
  se produce acá (aulas asignadas, clases generadas) es el
  entregable operativo del cuatrimestre.

## Modelo mental (importante — leer antes de las tareas)

Este es el módulo más denso del sistema. Antes de meterte en las
pantallas, tomate unos minutos para entender estos conceptos clave.

### Cronograma vs Plan de cursada

Son dos entidades distintas aunque parezcan lo mismo.

- El **cronograma** es el modelo de base: una foto del cuatrimestre
  tal como llega desde la facultad. Es lo que subís y validás en el
  módulo de Cronogramas.
- El **plan de cursada** es una **copia viva y editable** del
  cronograma, específica de un ciclo. Cuando lo generás, el sistema
  duplica todas las comisiones y horarios del cronograma para que
  puedas trabajar sobre esa copia sin tocar el original.

En palabras concretas: **el cronograma es la receta**; **el plan de
cursada es la comida servida** que después vas ajustando y a la que
le asignás las aulas.

### Comisión modelo vs Comisión del plan

Las comisiones también existen en dos lugares:

- **Comisión modelo** (o "comisión del cronograma"): la que definiste
  al armar el cronograma. Sirve como plantilla.
- **Comisión del plan**: una copia de la comisión modelo, atada al
  plan de cursada. Es la que ves cuando editás cupos, carrera
  asignada, peso o descripción dentro del plan.

Cuando generás el plan, el sistema clona todas las comisiones modelo
del cronograma como comisiones del plan. **Modificar una comisión
del plan no afecta al cronograma origen** (y viceversa). Son ciclos
de vida independientes.

### Patrón semanal vs Clases

- El **patrón semanal** es lo que ves en la grilla horaria del plan:
  "los lunes de 8 a 10 hay Análisis I comisión 1". Es la fuente de
  verdad de la planificación y **es lo que el asignador de aulas
  mira**.
- Las **clases** son las instancias concretas de cada horario en cada
  fecha del ciclo. Si un cuatrimestre tiene 15 semanas y el patrón
  dice "los lunes de 8 a 10", entonces se generan 15 clases
  concretas (una por lunes) al activar el plan.

Vos trabajás siempre sobre el patrón semanal. Las clases se generan
automáticamente cuando activás el plan y heredan el aula del patrón.
En la práctica no necesitás editar clases una por una.

### Qué es el asignador de aulas

El asignador es el motor que decide, para cada horario del plan, qué
aula del edificio le corresponde. Le pasás el plan tal como está y él
prueba todas las combinaciones posibles buscando la mejor. Por
"mejor" entiende:

- **Minimizar aulas chicas** para materias con muchos inscriptos
  (evitar sobre-ocupación).
- **Minimizar aulas gigantes** para grupos chicos (evitar
  sub-utilización, pero con más margen de tolerancia).

Además respeta reglas duras que no se pueden violar: cada horario
recibe exactamente un aula, el tipo de aula tiene que coincidir con
el tipo de clase (teórica en aula teórica, laboratorio en aula de
lab compatible), un aula no puede estar en dos lugares a la vez, y
el aula tiene que estar en una sede habilitada para la carrera.

Sin jerga: **le buscás un aula del edificio a cada horario y él te
devuelve la mejor asignación que encontró, o te avisa que no se pudo
y te muestra por qué**.

### Virtualidad jerárquica ("el nivel más específico manda")

Un horario puede ser presencial o virtual. La virtualidad se puede
declarar en tres niveles:

1. **A nivel horario individual**: "este horario específico es
   virtual" (por ejemplo, la teoría del jueves se da por Zoom, pero
   el laboratorio del viernes es presencial).
2. **A nivel dictado del ciclo**: "esta materia se dicta virtual en
   este ciclo" (por ejemplo, un recursado por Zoom).
3. **A nivel materia del catálogo**: "esta materia es siempre
   virtual".

La regla es simple: **el nivel más específico manda**. Si el
horario tiene una virtualidad seteada, se usa esa. Si no, se busca
en el dictado. Si tampoco, se cae en la materia. Un horario marcado
como virtual **queda excluido del asignador**: no consume aula.

## Recorrido rápido de la página

La página de Planes se organiza en 6 tabs:

1. **📥 Generar Plan**: wizard de 2 pasos para crear un plan nuevo a
   partir de un cronograma validado y vigente.
2. **📋 Vista General**: listado de todos los planes existentes del
   ciclo, con acciones rápidas (activar, eliminar).
3. **🔍 Detalle del Plan**: editor central del plan seleccionado.
   Metadata, validaciones, ajustes por materia.
4. **📋 Grilla Horaria**: vista global del plan como calendario
   semanal, con dos modos ("por grupo curricular" y "por materia").
5. **🏛️ Aulas**: entrada del asignador de aulas. Acá lo configurás,
   lo corrés, y ves el resultado.
6. **⚙️ Configuración**: parámetros globales de la grilla temporal
   (granularidad en minutos, hora de inicio operativo, días
   operativos).

Cada tab se puede navegar independientemente. Si estás editando un
plan, tenés que seleccionarlo primero desde el selector superior de
la mayoría de los tabs.

## Tareas comunes

### Generar un plan nuevo a partir de un cronograma validado

El plan nace de un cronograma que ya está en estado **🟢 Validado y
vigente**. Si el cronograma no tiene ese estado, no lo vas a poder
elegir.

**Paso 1 — Selección**:

1. Andá al tab **📥 Generar Plan**.
2. Elegí el ciclo desde el selector.
3. Elegí el cronograma. Sólo aparecen los cronogramas validados y
   vigentes. Los cronogramas "sin validar" o "validados pero
   desactualizados" quedan listados en un expander informativo pero
   no se pueden seleccionar.
4. Poné un nombre al plan (por default el sistema te sugiere algo
   tipo "Plan 2026-1C (Nombre del cronograma)").
5. Descripción opcional.
6. Elegí el método de forecast default: `media_movil`, `drift` o
   `ses`. Si no tenés preferencia, dejá `media_movil`.
7. Apretá **"Crear borrador y continuar →"**.

El sistema clona en cascada todas las comisiones y horarios del
cronograma. Cuando termina, vas a ver un toast del estilo `"Borrador
creado: 47 comision(es), 82 horario(s)."` y automáticamente pasás al
paso 2.

**Paso 2 — Edición inicial**:

En este paso, el wizard embebe el mismo editor que después vas a
usar en el tab "Detalle del Plan". Podés revisar validaciones,
ajustar comisiones o pesos que hayan quedado raros. Cuando estés
conforme, apretá **"✅ Confirmar y salir del wizard"**.

Al confirmar, el plan queda como borrador (no activo) y el sistema
te lleva al tab Detalle con ese plan pre-seleccionado.

> ⚠️ **Cuidado con "Cancelar"**: el botón **"🗑️ Cancelar (borra el
> plan)"** del paso 2 borra el plan **sin pedir confirmación
> intermedia**. Un click y se va. Si lo apretaste sin querer, no hay
> forma de recuperarlo — hay que volver a generar el plan desde
> cero.

Si cerrás la pestaña del wizard sin apretar nada, el borrador queda
persistido y lo vas a ver aparecer en la Vista General.

### Ver los planes existentes de un ciclo

Andá al tab **📋 Vista General** y elegí el ciclo. Vas a ver una
tarjeta por cada plan del ciclo, con:

- **Nombre del plan** y **badge** (🟢 ACTIVO o ⚪ inactivo).
- **Descripción** y nombre del cronograma origen.
- **Métricas**: Materias distintas, Comisiones, Horarios.
- **Acciones**: Activar (si está inactivo) o Eliminar.

Podés tener varios planes por ciclo, pero **sólo uno puede estar
activo a la vez**. Al activar un plan, el sistema desactiva
automáticamente cualquier otro plan activo del mismo ciclo.

> ⚠️ **Eliminar borra sin confirmación**: el botón **"Eliminar"** de
> cada tarjeta borra el plan y todo lo asociado (comisiones,
> horarios, clases) sin pedir confirmación intermedia. Es
> destructivo. Antes de apretarlo, verificá dos veces cuál es el
> plan que estás por borrar.

### Editar los detalles de un plan

Andá al tab **🔍 Detalle del Plan**, elegí el ciclo y el plan. Vas a
ver:

- **Metadata**: nombre, descripción, método de forecast default. Se
  edita en un formulario con botón "Guardar".
- **Estadísticas**: 4 métricas rápidas (Materias, Comisiones,
  Horarios, Horarios con aula).
- **🔧 Acciones del plan**: expander con acciones puntuales
  (auto-completar tipo de horarios, ver más abajo).
- **Validaciones**: panel unificado con cobertura contra dictados,
  conflictos de horarios, editor inline por materia, forecast por
  materia, particiones teoría/lab, y el botón de activación con su
  gate.

El panel de validaciones es donde vas a pasar la mayor parte del
tiempo cuando estés cerrando un plan.

### Ver la grilla horaria completa del plan

Andá al tab **📋 Grilla Horaria**. La grilla te ofrece dos modos de
trabajo:

- **Por grupo curricular**: filtrás por Carrera, Año y Cuatrimestre.
  Ves un calendario semanal editable con todas las comisiones del
  grupo, coloreadas por comisión. Podés arrastrar, redimensionar,
  hacer click para editar, o seleccionar un rango vacío para crear
  un horario nuevo. Los cambios se guardan al momento.
- **Por materia**: buscás por código o nombre y ves esa materia
  aislada, con:
  - Un calendario semanal con sus horarios.
  - Una tabla editable de horarios (día, hora, tipo).
  - Una tabla editable de comisiones (nombre, cupo, peso, carrera
    asignada, descripción).

Los dos modos comparten el mismo motor. En "Por grupo" trabajás
transversalmente; en "Por materia" te enfocás en una sola.

### Ajustar comisiones (cupo, carrera asignada, peso)

Las comisiones se editan desde el tab **Detalle del Plan → por
materia** o desde **📋 Grilla Horaria → modo Por materia**. En
ambos vas a encontrar la tabla de comisiones con estas columnas:

- **Número** y **Nombre**: identificadores administrativos.
- **Cupo**: el cupo declarado de la comisión. Es un número
  administrativo que **no** entra al asignador (el asignador usa
  capacidades de aulas e inscriptos esperados).
- **Peso** (columna llamada "coef" o similar): cuánto de la
  demanda total de la materia le corresponde a esta comisión. Los
  pesos de todas las comisiones de una materia deberían sumar 1.0.
- **Carrera asignada**: opcional, ver más abajo.
- **Descripción**: comentarios libres.

**Qué es "Carrera asignada"**

Por default, una comisión no está atada a ninguna carrera en
particular. Las sedes admisibles se resuelven automáticamente por la
materia (si es una materia exclusiva de una carrera, se usan las
sedes de esa carrera; si es una materia común, se usa la sede
default de comunes).

A veces esto no alcanza. Ejemplo típico: la materia "Física III" es
común a varias carreras, pero **una comisión específica** está
organizada especialmente para alumnos de Ingeniería Electrónica y
se dicta en Siberia (en vez de Pellegrini, la sede default de
comunes). En ese caso, seteás **carrera asignada = "electrónica"** en
esa comisión, y el asignador va a considerar sólo las sedes
habilitadas para esa carrera al buscarle aula.

Una comisión con carrera asignada afecta a **todos sus horarios**:
no podés tener "un horario de esta comisión en Pellegrini y otro en
Siberia". La comisión es la unidad de sede.

**Qué hace el "Peso"**

El peso decide cómo se reparten los inscriptos esperados entre las
comisiones. Si la materia tiene 120 inscriptos y hay tres
comisiones con pesos 0.5, 0.25 y 0.25, entonces el asignador espera
60, 30 y 30 alumnos respectivamente. Ese número es el que compara
contra la capacidad del aula para decidir sobre-ocupación o
sub-utilización.

El peso también entra en juego cuando activás la **redistribución
de pesos** (ver más abajo).

### Marcar horarios como virtuales (sin aula)

Un horario marcado como virtual queda excluido del asignador: no
consume aula y no aparece en los mapas de calor de saturación.

Hay dos formas de marcarlo:

1. **Desde la grilla horaria**: hacé click en el bloque del
   horario → se abre el dialog "Editar horario" → tildá **"Virtual"**
   → confirmar.
2. **Desde el inspector de franja del asignador**: cuando estás
   inspeccionando una franja saturada, cada horario listado tiene un
   botón "✏️ Editar" que abre el mismo dialog.

La segunda vía es especialmente útil cuando el asignador te dice
"no se pudo resolver" por saturación: marcás como virtual un
recursado por Zoom que estaba compitiendo por aula, y el problema
desaparece sin mover a nadie de horario.

Recordá que la virtualidad respeta la jerarquía: si marcás el
horario individual como virtual, gana ese nivel sobre el dictado y
la materia.

### Correr el asignador de aulas

Los pasos concretos:

1. Andá al tab **🏛️ Aulas** del plan seleccionado.
2. Verificá que el plan tiene al menos un horario cargado. Si no,
   vas a ver el mensaje **"El plan no tiene horarios cargados.
   Agregá horarios desde el tab 📋 Grilla Horaria."**
3. Ajustá los parámetros del asignador (ver detalle abajo):
   - **Aplicar desde la fecha**: default hoy (o fecha de inicio del
     ciclo si es futura). Las clases previas a esta fecha quedan
     intactas.
   - **Peso de sobre-ocupación** (default 10.0): cuánto castiga
     poner una materia grande en un aula chica.
   - **Peso de sub-utilización** (default 1.0): cuánto castiga poner
     un grupo chico en un aula gigante.
   - **Tolerancia de sobre-ocupación** (default 0.0): margen antes
     de empezar a castigar.
   - **Tolerancia de sub-utilización** (default 0.20): 20% de vacío
     "gratis".
   - **Respetar ediciones manuales** (default ON): ver aclaración
     abajo.
   - **Tiempo máximo** (default 300 segundos): corte del asignador.
   - **Redistribuir pesos entre comisiones (avanzado)**: ver más
     abajo.
4. Apretá **"🚀 Asignar aulas"**.
5. Aparece un spinner mientras el asignador corre. Al terminar, vas
   a ver el resultado con status y métricas.

> ℹ️ **Sobre el toggle "Respetar ediciones manuales"**: hoy por hoy,
> este toggle **no cambia nada visible en el resultado**. La
> capacidad de editar aulas puntualmente por clase (una clase
> puntual) fue removida del sistema en 2026, y desde entonces el
> flag que este toggle usaba quedó sin ninguna forma de activarse
> desde la interfaz. Queda expuesto por si en el futuro se
> reintroduce la edición puntual — no lo apagues sin razón, pero
> tampoco esperes que cambie el comportamiento hoy.

Cada corrida crea una entrada en el historial de corridas del plan.
Podés correrlo tantas veces como quieras: la última corrida es la
que se muestra por default, pero las anteriores quedan guardadas.

### Interpretar un resultado "resuelto"

Cuando el asignador termina exitosamente vas a ver:

- Un toast: **"Asignación resuelta en X.Xs. Y clases actualizadas."**
- El status humano en el resumen: **✅ resuelta**.
- Un bloque de **métricas**:
  - **Horarios totales / Asignados**: idealmente iguales.
  - **Clases actualizadas**: cuántas clases del ciclo recibieron el
    aula del patrón.
  - **Sobre-ocupados**: horarios que quedaron con aula más chica que
    los esperados.
  - **Sub-utilizados**: horarios con aula demasiado grande.
  - **Costo total**: la suma ponderada que el asignador minimizó.
  - **Tiempo de resolución**.

**Herramientas de análisis** que aparecen debajo del resumen:

- **📊 Mapa de calor de simultaneidad** (día × franja): matriz que
  te muestra cuántas clases están activas simultáneamente en cada
  franja horaria. Podés filtrar por tipo (teóricas, laboratorios,
  todas).
- **🔥 Mapa de saturación por sede**: para cada sede con demanda,
  mostrás qué tan cargada está en relación a las aulas disponibles.
  Escala:
  - 🟢 verde: ≤80% de ocupación
  - 🟡 amarillo: 80–100%
  - 🔴 rojo: >100% (saturación segura, hay más horarios que aulas)
  Este mapa se recalcula en vivo en cada rerun, así que si marcás
  un horario como virtual desde el inspector, el mapa se actualiza
  sin necesidad de correr el asignador de nuevo.
- **🔍 Inspeccionar franja**: elegís sede, tipo de aula, día y
  franja, y ves en un mini calendario todos los horarios que
  compiten por esa franja, coloreados por carrera. Cada bloque tiene
  un botón "✏️ Editar".
- **📅 Cronograma por aula**: vista final por aula. Elegís el aula
  desde el selector y ves todos los horarios que le quedaron
  asignados a lo largo de la semana. Esta es la vista que le vas a
  querer mostrar al usuario final.

También aparece una **tabla por horario** con las columnas Materia,
Comisión, Día, Inicio, Fin, Aula, Sede, Capacidad, Esperados, Δ y
Estado. La columna Estado usa semáforos:

- 🟢 **ok**: el aula alcanza cómodamente.
- 🟡 **sub** (sub-utilizado): aula demasiado grande respecto a los
  esperados, fuera de la tolerancia.
- 🔴 **sobre** (sobre-ocupado): aula chica, los esperados exceden
  la capacidad.

Y una sección **🪓 Candidatas a partir comisión**: te sugiere qué
materias podrían beneficiarse de dividir una comisión en dos
(cuando el sobre está concentrado en pocas comisiones grandes).

### Interpretar un resultado "no se pudo resolver"

Este es el caso más difícil de interpretar y donde más ayuda
necesita el usuario. Vas a ver:

- El status humano: **❌ no se pudo resolver** (o **⏱️ se agotó el
  tiempo**, semánticamente similar).
- Un mensaje concreto en la parte superior.
- **Nada se persiste**: las aulas del patrón quedan como estaban.

Debajo aparece el **diagnóstico**, que puede tener hasta cinco
secciones, presentadas en orden de utilidad para el usuario. Leelas
en orden — la primera que muestre contenido suele ser suficiente
para entender el problema.

#### 1. Horarios sin aula compatible

La causa más simple: existe un horario que **ninguna aula del
sistema** puede cubrir. Se muestra la materia, día, franja, tipo y
la razón concreta (por ejemplo: "no hay laboratorios compatibles
cargados para esta materia" o "no hay aulas de tipo laboratorio en
las sedes admisibles").

**Qué hacer**:

- Si es un lab: cargá los laboratorios compatibles desde el módulo
  de Materias.
- Si es un tipo mal seteado: marcá el horario como teoría (o al
  revés) desde la grilla.
- Si faltan aulas: dá de alta el aula desde el módulo de Aulas y
  Sedes.

#### 2. Franjas con faltante de aulas de un tipo específico

En una franja concreta hay más horarios de un tipo (por ejemplo,
laboratorios) que aulas de ese tipo disponibles en las sedes
admisibles. Se muestra el día, franja, tipo problemático, cuántas
necesitás vs cuántas hay disponibles, y las materias involucradas.

**Qué hacer**:

- Marcar como virtual algún dictado que sea recursado por Zoom.
- Agregar aulas del tipo faltante.
- Ampliar la lista de laboratorios compatibles de alguna materia
  para que pueda usar aulas alternativas.
- Mover algún horario a otra franja donde haya menos competencia.

#### 3. Cuellos de botella (grupos de simultaneidad)

Aparece un grupo chico de clases simultáneas que comparten una
lista **también chica** de aulas compatibles. Aunque en el edificio
haya muchas aulas en total, este subgrupo específico no logra
distribuirse sin choques. Se muestran las aulas exactas del cuello
de botella.

**Qué hacer**: mirar las aulas listadas y pensar qué falta:
laboratorios compatibles nuevos, alguna materia que se pueda mover
a otro momento, o compartir aulas de otra sede.

#### 4. Franjas saturadas globalmente

Una cota más gruesa que las dos anteriores: en tal franja horaria,
la cantidad total de horarios simultáneos supera la cantidad total
de aulas disponibles, sumando todos los tipos. Se muestra el
desglose (cuántas teóricas, cuántas de lab, cuántas sin tipo
definido).

**Qué hacer**: descomprimir la franja. Marcar virtualidades,
reprogramar algún horario, o ampliar el pool de aulas.

#### 5. Diagnóstico cruzado

Sólo aparece cuando las cuatro secciones anteriores están vacías
pero el asignador **igual** dijo que no se pudo resolver. En ese
caso, el sistema hace un análisis extra: prueba relajar cada
restricción una a una y ve cuál, al ignorarse, permite resolver.
Esa es la causa probable, y se muestra en rojo (por ejemplo,
"Causa probable: choques temporales entre horarios").

**Qué hacer**: leer con atención qué tipo de restricción es la
sospechosa y actuar sobre ella. Si la causa es "combinada" (nada
individual resuelve), significa que hay que descomprimir por más de
un lado.

**Consejo general**: aún con un resultado infactible, el **mapa de
saturación por sede** y el **inspector de franja** siguen
funcionando. Son las mejores herramientas para navegar y encontrar
la franja concreta que hay que descomprimir. Marcar como virtual un
horario desde el inspector suele ser el arreglo más rápido cuando
el problema es un recursado por Zoom compitiendo por aula.

### Cambiar manualmente el aula de un horario

Hay dos formas de intervenir a mano después de una corrida del
asignador:

1. **Desde el Cronograma por aula** (tab 🏛️ Aulas, expander al
   final): elegís el aula, ves su semana, y cada horario tiene un
   botón "Editar aula" que abre un dialog para cambiarla. El
   sistema chequea compatibilidad de tipo, sede admisible y choques
   con otros horarios del plan antes de dejarte confirmar.
2. **Desde la Grilla Horaria** o desde el editor por materia: si
   movés un horario a otro día u hora, el aula previamente asignada
   queda atada al horario pero puede volverse inconsistente.

> ⚠️ **Después de mover horarios en la grilla**: el aula que el
> asignador había puesto queda pegada al horario, y si el nuevo
> día/hora ya tenía otra clase con esa misma aula, quedan dos
> horarios pisándose. La política correcta es **volver a correr el
> asignador** después de mover slots. El asignador re-arma todo desde
> cero y detecta cualquier inconsistencia. Si hay choques residuales,
> te lo va a decir con un diagnóstico claro.

### Redistribuir los pesos entre comisiones (redistribución de
pesos)

Los pesos de las comisiones se cargan al armar el cronograma y se
copian al plan. A veces es difícil elegir bien esos pesos a mano —
por ejemplo, cuando querés que el asignador reparta los inscriptos
de forma que las aulas queden más balanceadas.

Para eso existe el toggle **"Redistribuir pesos entre comisiones
(avanzado)"** en la configuración del asignador. Cuando lo
activás, el asignador propone **nuevos pesos** para cada comisión
además de asignar aulas.

Cómo funciona en la práctica:

1. Activás el toggle antes de correr el asignador.
2. Corrés el asignador normalmente.
3. Si resuelve, el resultado incluye una tabla con los **pesos
   propuestos** (uno nuevo por cada comisión) además de la
   asignación de aulas.
4. Tenés dos botones: **"Aplicar nuevos pesos"** o **"Descartar"**.
   - Si aplicás: los pesos nuevos se guardan en las comisiones y la
     asignación de aulas queda como está.
   - Si descartás: se conservan los pesos viejos, pero el asignador
     te avisa que la asignación de aulas que estás viendo está
     calculada con los pesos nuevos, así que puede no ser
     consistente con lo que se persistió.

Es una función avanzada. Recomendable sólo si tenés experiencia
con la asignación y querés experimentar con distintas
redistribuciones.

### Activar el plan

El sistema tiene **dos botones distintos con la palabra "Activar"**,
y hacen cosas diferentes. Es importante entender la diferencia.

**Opción A — "Activar" desde la Vista General (rápido)**

En el tab **📋 Vista General**, cada tarjeta de plan inactivo tiene
un botón **"Activar"**. Lo que hace este botón:

- Marca el plan como activo (`activo = true`).
- Desactiva cualquier otro plan activo del mismo ciclo (invariante:
  sólo un plan activo por ciclo).
- **No genera las clases del cuatrimestre**.

Es una activación de "atajo" pensada para cambiar rápido cuál plan
del ciclo se considera vigente, sin necesariamente materializar el
cuatrimestre.

**Opción B — "Activar plan" desde el panel de validación del Detalle
(completo)**

En el tab **🔍 Detalle del Plan**, dentro del panel de validaciones,
hay un botón **"Activar plan"** (a veces "Activar y generar
clases"). Este:

- Chequea que no haya conflictos no ignorados (gate).
- Marca el plan como activo.
- Desactiva los otros planes del ciclo.
- **Genera todas las clases del cuatrimestre**: una por cada horario
  del patrón, replicada por cada fecha del ciclo cuyo día coincida.

Esta es la activación **oficial**, la que corresponde hacer cuando
el plan está listo para arrancar el cuatrimestre.

> ⚠️ **Elegí bien cuál usás**: si activás desde Vista General y no
> pasás después por el panel de validación, el plan va a quedar
> "activo" pero **sin clases materializadas**. Al operativo del
> cuatrimestre le van a faltar esas clases. Si te pasó, andá al
> panel de validación del Detalle y volvé a apretar "Activar plan"
> desde ahí para forzar la generación de clases.

### Borrar un plan

Desde la **Vista General**, cada tarjeta de plan tiene un botón
**"Eliminar"**. El borrado es en cascada:

1. Se borran las clases materializadas.
2. Se borran los horarios del plan.
3. Se borran las comisiones del plan.
4. Se borra el plan en sí.

El cronograma origen **no se toca**. Podés generar un plan nuevo a
partir del mismo cronograma cuando quieras.

> ⚠️ **Advertencia**: el borrado es **inmediato y sin confirmación
> intermedia**. Un solo click y el plan desaparece. Antes de
> apretar el botón, verificá dos veces que estás sobre el plan
> correcto.

### Auto-completar tipos de horarios (teoría/laboratorio)

Cuando el cronograma se subió, algunos horarios pueden haber
quedado sin tipo definido (ni teoría ni laboratorio). El sistema
tiene una acción rápida para inferir el tipo automáticamente cuando
la materia lo permite:

- Si la materia declara sólo horas de teoría (`hteo > 0`,
  `hlab = 0`) → todos sus horarios se marcan como **teoría**.
- Si la materia declara sólo horas de laboratorio → todos como
  **laboratorio**.
- Si tiene ambas, no se puede auto-completar (se necesita decisión
  humana).

Andá al tab **🔍 Detalle del Plan → 🔧 Acciones del plan →
Auto-completar tipo de horarios**. Vas a ver un preview live que te
dice cuántos horarios cambiarían y a qué tipo. Si te convence,
apretá **"✅ Aplicar auto-completado"**.

No es una acción crítica — el asignador aplica esta misma inferencia
en memoria de todas formas antes de correr. Aplicarla en firme
sirve para que **otras vistas** (mapa de calor filtrado, editor por
materia, validaciones) muestren el tipo correcto en vez de "sin
determinar".

## Errores frecuentes y qué hacer

**"No hay ciclos registrados. Crea uno en la página de Ciclos."**

Todavía no creaste ningún ciclo. Andá a **📆 Ciclos** y creá uno.

**"No hay cronogramas cargados para este ciclo. Cargá uno desde 📅
Cronogramas."**

El ciclo existe pero no hay cronogramas subidos. Andá a **📅
Cronogramas → 📤 Cargar**.

**"Ningún cronograma del ciclo está validado y vigente. Andá a 📅
Cronogramas → ✅ Validar para habilitar uno."**

Hay cronogramas pero ninguno está en estado 🟢. Andá a validarlo
desde el módulo de Cronogramas.

**"El plan no tiene horarios cargados. Agregá horarios desde el tab
📋 Grilla Horaria."**

Generaste el plan pero está vacío (raro, salvo que hayas borrado
todos los horarios manualmente). Agregá horarios desde la grilla o
volvé a generar el plan desde el cronograma.

**"El plan borrador ya no existe. Empezá de nuevo."**

Estabas en el paso 2 del wizard y en el medio se borró el plan
(por ejemplo, alguien lo eliminó desde Vista General). Volvé al
paso 1 y regenerálo.

**"El aula 'X' no es laboratorio compatible con la materia MAT."**

Al cambiar un aula a mano, elegiste un aula que no está en la lista
de laboratorios compatibles de esa materia. Andá al módulo de
Materias, expandí la materia, y agregá el aula a los laboratorios
compatibles.

**"El aula 'X' es de tipo 'lab' y no admite clase teórica."**

Estás tratando de asignar un aula de laboratorio a un horario que
está marcado como teórico. Cambiá el aula o cambiá el tipo del
horario.

**"El aula 'X' ya está asignada a otro horario del plan (Lu 14:00-
16:00)."**

El aula que elegiste choca con otro horario en el mismo día/franja.
El sistema te lo indica con el horario concreto. Elegí otra aula o
resolvé el otro horario primero.

**"No se puede borrar: la comisión tiene entries asociadas en el
cronograma."**

Intentaste borrar una comisión modelo que sigue siendo referenciada
por filas del cronograma. Reasignálos o borralos primero desde el
cronograma.

**"No se puede borrar: la comisión tiene horarios asociados en el
plan. Reasignalos o borrá los horarios primero."**

Análogo pero a nivel plan: la comisión tiene horarios vivos. Borralos
o reasignalos primero.

**Asignador devuelve "no se pudo resolver" sin datos claros en las
primeras 4 secciones del diagnóstico**

Espera a que corra el diagnóstico cruzado (sección 5). Si tampoco
te aporta, el problema puede ser una combinación de restricciones.
Revisá el mapa de saturación por sede — las celdas rojas te dicen
dónde mirar primero.

## Preguntas frecuentes

**¿Por qué no aparece mi cronograma en el wizard de generación?**

Porque para generar un plan, el cronograma tiene que estar en estado
**🟢 Validado y vigente** para el ciclo elegido. Andá a **📅
Cronogramas → ✅ Validar**, corré la validación y marcá el
cronograma como vigente. Después va a aparecer en el selector del
wizard.

**¿Cuál es la diferencia entre "Cupo" y "Esperados" de una
comisión?**

- **Cupo** es un número **administrativo** que declarás vos.
  Representa "hasta cuántos alumnos permitimos anotarse en esta
  comisión". El asignador **no lo usa**.
- **Esperados** es un número **calculado**: total esperado de
  inscriptos de la materia (según forecast) multiplicado por el
  peso de la comisión. Este número es el que el asignador compara
  contra la capacidad del aula al decidir sobre-ocupación o
  sub-utilización.

En resumen: cupo es contrato administrativo, esperados es la
demanda real estimada.

**¿El asignador respeta las aulas que edité a mano después de una
corrida previa?**

Hoy no de manera visible. El toggle **"Respetar ediciones
manuales"** existe pero está huérfano: la capacidad que se apoyaba
en él (editar aulas puntualmente por clase) fue removida en 2026, y
el flag que marca "esta aula fue editada a mano" no se puede setear
desde ninguna parte de la interfaz actual. Consecuencia: si volvés a
correr el asignador, va a re-asignar todo desde cero sin conservar
tus ediciones manuales.

Si querés preservar una asignación manual, la única forma hoy es
**no volver a correr el asignador** después de haber editado el aula
a mano. En versiones futuras se piensa reintroducir esta capacidad.

**¿Puedo tener dos planes activos en el mismo ciclo?**

No. El sistema garantiza que **sólo un plan puede estar activo por
ciclo**. Cuando activás un plan, cualquier otro plan activo del
mismo ciclo se desactiva automáticamente. Sí podés tener varios
planes en borrador (inactivos) conviviendo, útiles para comparar
escenarios.

**¿Qué pasa si edito un horario después de correr el asignador?**

El aula que el asignador había asignado queda **pegada al horario**
aunque el día/hora hayan cambiado. Puede quedar inconsistente: por
ejemplo, un aula que ahora choca con otro horario en la misma
franja. La forma limpia de resolverlo es **volver a correr el
asignador** — re-arma todo y detecta cualquier choque residual.

**¿Puedo borrar un plan activo?**

Sí, técnicamente el botón "Eliminar" te lo deja hacer. Pero es
recomendable **desactivarlo primero** (activando otro plan del
ciclo) para que no queden "vacíos operativos" durante el borrado en
cascada.

**¿Cuál es la diferencia entre "Activar" en Vista General y
"Activar plan" en el Detalle?**

Es importante:

- **"Activar" en Vista General** sólo cambia el flag: el plan pasa a
  ser el activo del ciclo, pero **no se generan las clases**.
- **"Activar plan" en el panel de validación del Detalle** hace lo
  mismo Y ADEMÁS **genera todas las clases** del cuatrimestre.

Si querés dejar el plan realmente listo para operar, usá la segunda.
La primera está pensada para cambios rápidos cuando ya activaste
antes.

**¿Qué es la "redistribución de pesos" y cuándo tiene sentido
activarla?**

Es una función avanzada del asignador que, además de asignar aulas,
propone nuevos pesos para las comisiones (cómo se reparten los
inscriptos entre ellas). Tiene sentido activarla cuando sospechás
que los pesos actuales no son los más balanceados y querés que el
sistema te sugiera una redistribución. Después ves la propuesta y
decidís si aplicarla o descartarla.

**¿Puedo correr el asignador de aulas antes de activar el plan?**

Sí. De hecho, es el flujo típico: generás el plan borrador, corrés
el asignador, revisás el resultado, hacés ajustes, y recién ahí
activás. La asignación de aulas se guarda en el patrón semanal
independientemente del estado activo/borrador del plan.

**¿Por qué el mapa de saturación por sede se actualiza en vivo pero
la tabla de resultados no?**

Porque el mapa de saturación se calcula sobre el estado actual de
la base de datos, mientras que la tabla de resultados es una foto
del momento en que corriste el asignador. Si hacés un cambio (por
ejemplo, marcar un horario como virtual) entre corridas, el mapa
refleja el cambio inmediatamente pero la tabla no — para eso hay
que volver a correr el asignador.

**¿Qué significan los pesos por default (10, 1) del asignador?**

Son los coeficientes que el asignador usa para decidir qué es peor:
poner una materia grande en un aula chica (sobre-ocupación, peso
10) o poner un grupo chico en un aula gigante (sub-utilización,
peso 1). Como el peso de sobre es 10 veces mayor, el asignador
prefiere aulas grandes con vacío antes que aulas chicas con
alumnos parados. Si querés balancear más, podés subir el peso de
sub o bajar el de sobre — pero los defaults suelen funcionar bien.

**¿Qué pasa con las clases anteriores a la "fecha desde" al correr
el asignador?**

Quedan **intactas**. La fecha desde funciona como un corte: las
clases con fecha anterior no se tocan, se preserva la asignación
histórica. Las clases desde esa fecha en adelante reciben la
asignación nueva. Esto sirve, por ejemplo, para no pisar la
asignación de clases que ya se dictaron a mitad de cuatrimestre.

**¿Por qué a veces el asignador tarda mucho?**

Depende del tamaño del problema (cantidad de horarios, aulas,
restricciones) y del **tiempo máximo** que le pusiste. Por default
son 300 segundos (5 minutos). Si el asignador no encuentra la
solución óptima en ese tiempo, corta y te dice **"se agotó el
tiempo"**. En problemas grandes podés subir el tiempo, pero
generalmente si tarda mucho es porque el problema es difícil y
conviene revisar si hay cuellos de botella evitables.

## Cuando algo no funciona: guía rápida de troubleshooting

**El asignador dice "no se pudo resolver"**

1. Leé la primera sección del diagnóstico que tenga contenido.
   Suele ser suficiente.
2. Mirá el **mapa de saturación por sede**: las celdas rojas
   apuntan a las franjas y sedes conflictivas.
3. Usá el **inspector de franja** sobre una celda roja: ves los
   horarios exactos que compiten.
4. Decidí: ¿faltan aulas, hay horarios mal tipeados, algún
   recursado debería ser virtual?

**La tabla de resultados no muestra un aula que esperaba**

- Verificá **sedes admisibles**: la carrera de la materia (o la
  "carrera asignada" de la comisión si está seteada) puede no tener
  esa sede habilitada. Andá a **🎓 Carreras** y revisá las sedes
  habilitadas.
- Verificá **tipo de aula**: un horario teórico no puede usar un
  aula de laboratorio, y viceversa.
- Verificá **compatibilidad de lab**: si es un horario de
  laboratorio, el aula tiene que estar en los laboratorios
  compatibles de la materia (módulo de Materias).

**El plan quedó "activo" pero al arrancar el cuatri faltan clases**

Activaste el plan desde Vista General en vez de desde el panel de
validación del Detalle. Andá a **🔍 Detalle del Plan → Validaciones
→ Activar plan** y volvé a apretar activar desde ahí. Eso fuerza la
generación de clases.

**Moví un horario en la grilla y el asignador dice que hay choques**

Esperable. Al mover el horario, el aula previa quedó pegada y ahora
choca. Volvé a correr el asignador para que re-asigne todo.

**El mapa de calor está vacío o incompleto**

Suele significar que todavía no corriste el asignador (los mapas
que dependen del snapshot vienen vacíos). O bien filtraste por un
tipo que no tiene horarios. Sacá filtros y volvé a mirar.

**Cambié la carrera asignada de una comisión pero el asignador no
cambia de sede**

Los cambios de carrera asignada afectan corridas **futuras** del
asignador. Volvé a correrlo para que aplique la nueva restricción
de sedes.

## Términos importantes de este módulo

- **Plan de cursada**: la copia editable de un cronograma para un
  ciclo específico, con sus comisiones, horarios y aulas.
- **Comisión modelo**: la comisión definida en el cronograma. Es la
  plantilla.
- **Comisión del plan**: la copia viva de la comisión modelo, atada
  al plan. Es la que el asignador mira.
- **Patrón semanal**: el conjunto de horarios recurrentes del plan
  ("los lunes de 8 a 10 hay tal materia"). Es la fuente de verdad
  de la planificación.
- **Clase**: la instancia concreta de un horario en una fecha
  específica del ciclo. Las clases se generan automáticamente al
  activar el plan.
- **Plan activo (vigente)**: el plan del ciclo marcado como
  `activo = true`. Sólo puede haber uno por ciclo.
- **Borrador**: un plan inactivo, en edición.
- **Asignador de aulas**: el motor que decide qué aula usa cada
  horario del plan.
- **Corrida del asignador**: cada ejecución del asignador. Se guarda
  en el historial de corridas del plan.
- **Peso de una comisión**: cuánto de la demanda total de la
  materia le corresponde a esa comisión. Los pesos de una materia
  deberían sumar 1.
- **Redistribución de pesos**: función avanzada del asignador que
  propone nuevos pesos para balancear mejor las comisiones.
- **Carrera asignada** (de una comisión): opcional; fuerza a la
  comisión a resolver sus sedes admisibles según esa carrera en
  lugar de la materia.
- **Sobre-ocupación**: cuando el aula asignada es más chica que los
  inscriptos esperados.
- **Sub-utilización**: cuando el aula asignada es demasiado grande
  respecto a los inscriptos esperados.
- **Tolerancia**: margen porcentual antes de castigar sobre o sub.
- **Mapa de calor de simultaneidad**: matriz día × franja que
  muestra cuántas clases están activas al mismo tiempo.
- **Mapa de saturación por sede**: para cada sede, cuán cargada
  está en relación a las aulas disponibles.
- **Inspector de franja**: herramienta para ver, en detalle, todos
  los horarios que compiten por una franja concreta.
- **Cronograma por aula**: vista final por aula que muestra qué
  clases le quedaron asignadas a lo largo de la semana.
- **Diagnóstico** (de infactibilidad): el análisis que el sistema
  produce cuando el asignador no puede resolver. Incluye horarios
  sin aula compatible, franjas con faltantes, cuellos de botella,
  franjas saturadas y diagnóstico cruzado.
- **Cuello de botella**: un grupo chico de clases simultáneas que
  comparte una lista chica de aulas compatibles y que no se puede
  distribuir sin choques.
- **Franja saturada**: franja horaria donde hay más horarios
  simultáneos que aulas totales disponibles.
- **Restricción de sedes por carrera**: regla que fuerza a una
  materia (o comisión con carrera asignada) a resolverse sólo en
  las sedes habilitadas para su carrera.
- **Virtualidad jerárquica**: la modalidad virtual se puede declarar
  en tres niveles (horario, dictado, materia) y el nivel más
  específico manda.
- **Fecha desde**: el corte temporal a partir del cual la corrida
  del asignador aplica sus cambios a las clases; las clases
  anteriores quedan intactas.
