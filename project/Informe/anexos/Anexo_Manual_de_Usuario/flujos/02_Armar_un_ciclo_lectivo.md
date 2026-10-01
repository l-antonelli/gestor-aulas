# Flujo 2: Armar un cuatrimestre nuevo

## ¿Cuándo usar este flujo?

Este es el flujo **troncal** del sistema. Lo vas a usar:

- **Cada arranque de cuatrimestre** (1er o 2do de cada año) cuando
  llegan los horarios de la facultad.
- **Como referencia** cuando enseñes el sistema a alguien nuevo.

Es un flujo largo pero secuencial y repetible: hacé cada paso, verificá
que salió bien, y pasá al siguiente.

## Estado esperado antes de arrancar

- El **catálogo maestro** está estable y actualizado:
  - Materias con nombres y horas correctas.
  - Carreras con nombres reales, cantidad de materias y plan de
    estudio activo.
  - Grupos de materias con sus sedes admisibles configuradas
    (📚 Materias → 📦 Grupos de materias).
  - Aulas con capacidad y tipo correctos.
  - Laboratorios compatibles asociados a las materias con carga de
    lab.
- Tenés los **horarios que llegaron de la facultad** para el
  cuatrimestre, listos para volcar en la plantilla Excel que genera
  la aplicación.
- (Opcional pero recomendado) Los **inscriptos históricos** están
  cargados para que la estimación de demanda funcione.

## Pasos

### Paso 1: Crear el ciclo lectivo

**Página**: 📆 Ciclos.

1. Andá a la solapa **📋 Ciclos**.
2. Bajá hasta el bloque **Nuevo Ciclo**.
3. Completá:
   - **Anio**: el año del cuatrimestre (ej. 2026).
   - **Cuatrimestre**: 1C o 2C.
   - **Fecha de inicio** y **Fecha de fin**: rango real del
     cuatrimestre.
   - **Descripcion (opcional)**: libre.
   - **Versiones de plan a asignar**: selección múltiple obligatoria.
     Por default el sistema preselecciona la versión activa de cada
     carrera (o la más reciente). Revisá que sea la que corresponde a
     las materias que se dictan este ciclo.
4. Apretá **Guardar**.

El ID del ciclo se genera automáticamente como `{año}-{numero}C` (por
ejemplo `2026-1C`) y no se puede editar después.

![Formulario para crear un ciclo nuevo](../capturas/ciclos/ciclos_formulario_nuevo_ciclo.png)

**Verificación**: el ciclo aparece en la tabla de ciclos registrados.

> **Cuidado**: el paso "Versiones de plan a asignar" es obligatorio y
> fácil de olvidar. Sin al menos una versión de plan asignada, no
> podés crear dictados. Si te olvidaste, aparece un aviso amarillo
> cuando vayas a la solapa Dictados.

### Paso 2: Crear los dictados del ciclo

**Página**: 📆 Ciclos, solapa **📚 Dictados**.

1. Seleccioná el ciclo recién creado en el selector de arriba.
2. Apretá el botón **➕ Crear Dictados**.

El sistema recorre las materias de las versiones de plan asignadas y
crea un **dictado** por cada una que la regla de recursado autoriza
para ese cuatrimestre. Un mensaje te confirma cuántos creó, cuántos
son anuales (vinculados de un cuatri al otro) y cuántos omitió por
recursado.

![Pestaña Dictados: selector de ciclo, métricas y botones de operación](../capturas/ciclos/dictados_selector_metricas_y_botones.png)

**Verificación**: mirá las métricas de arriba. Deberías ver
"Dictados existentes" con el número esperado. El **panel de
divergencias** te muestra si hay materias del plan sin dictado o
dictados que sobran (típicamente no debería haber después de la
creación en bloque).

### Paso 3: Revisar y ajustar dictados

Todavía en 📆 Ciclos → 📚 Dictados.

Recorré las materias por carrera (los desplegables de cada carrera)
y ajustá:

- **Modalidad virtual**: por cada materia que este cuatrimestre se
  dicta por Zoom (o modalidad no presencial), elegí **Virtual** en
  el selector **Virtual** de su fila (las otras opciones son
  **Heredar** y **Presencial**).
- **Recursado excepcional**: si alguna materia se dicta contra la
  regla habitual, ajustá el selector **Recursado** de esa fila.

Los cambios se acumulan en el bloque **⏳ Cambios pendientes (N)**.
Cuando termines de ajustar, apretá **💾 Aplicar N cambio(s)** (o
**🚫 Descartar cambios** si te arrepentiste).

![Bloque de cambios pendientes de Virtual y Recursado](../capturas/ciclos/dictados_cambios_pendientes.png)

**Verificación**: las filas reflejan el estado deseado, el bloque de
cambios pendientes desaparece y las métricas superiores (materias
virtuales, recursado fijado a mano) muestran los números correctos.

Si el panel de divergencias tiene alertas, resolvelas antes de
seguir: **✅ Crear** los dictados faltantes, **🗑️ Borrar** los
huérfanos, o **⬆️ Promover a regla** si querés cambiar la política.
El botón **⚡ Aplicar todo** resuelve en bloque las dos primeras
categorías. Ver detalles en el manual del módulo Ciclos.

### Paso 4: Cargar el cronograma

**Página**: 📅 Cronogramas, solapa **📤 Cargar**.

La aplicación sólo acepta la **plantilla Excel (`.xlsx`) que ella
misma genera**; no sirven otros formatos ni planillas armadas a mano.

1. Elegí la opción **Crear desde archivo**.
2. Poné un **nombre** al cronograma (ej. "2026-1C - v1").
3. Elegí el **ciclo** al que corresponde.
4. Si todavía no tenés la plantilla, abrí **📥 Descargar plantilla
   vacía del ciclo**, apretá **🧮 Generar plantilla** y descargala.
   Trae una hoja por grupo de materias, con listas desplegables. Se
   la repartís a las cátedras y, una vez completa, la descargás como
   `.xlsx`.
5. Subí la plantilla completa con el cargador **Plantilla completa
   (.xlsx)**.
6. Apretá **🔍 Revisar plantilla**. Si tiene errores, se listan
   agrupados por hoja: corregí el Excel y volvé a subirlo.
7. Con la plantilla limpia aparece la vista previa (el cronograma
   todavía no existe). Recorré la **🗂 Revisión hoja por hoja**,
   marcando cada hoja como revisada.
8. En **🏁 Resumen y confirmación**, apretá **✅ Crear cronograma**.

![Carga desde archivo: plantilla descargable y subida del archivo](../capturas/cronogramas/cargar_desde_archivo_con_plantilla.png)

Las comisiones de la plantilla se **crean y asocian solas** a partir
del código de comisión de cada fila.

**Verificación**: en la solapa **📋 Lista** el cronograma aparece con
el badge **⚪ sin validar**.

### Paso 5: Revisar y editar el cronograma

**Página**: 📅 Cronogramas, solapa **✏️ Ver / Editar**.

1. Seleccioná el cronograma recién creado.
2. Recorré las materias en modo **Por materia** o **Por grupo** para:
   - **Verificar horarios**: cada materia debería tener sus horarios
     esperados.
   - **Revisar comisiones**: confirmá que cada fila quedó con la
     comisión correcta; se puede cambiar desde la tabla o desde el
     diálogo de edición, donde también se puede crear una comisión
     nueva.
   - **Marcar tipo**: si alguna fila no trae el tipo (teórica /
     laboratorio), marcalo donde puedas determinarlo.
   - **Marcar virtual**: si algún horario específico se dicta por
     Zoom (y la materia entera no es virtual), marcalo desde el
     diálogo de editar horario.

Los cambios se guardan al momento. Para sólo mirar, dejá activado el
interruptor **🔒 Solo lectura**.

**Verificación**: navegá por materia y confirmá que:
- No queden horarios sin comisión asignada (o que sepas por qué los
  dejaste así).
- Los tipos de clase estén asignados donde importe (materias con
  laboratorio).

### Paso 6: Validar el cronograma

**Página**: 📅 Cronogramas, solapa **✅ Validar**.

1. Seleccioná el **Ciclo** y el **Cronograma**.
2. Apretá **Validar cronograma**.

El sistema verifica:

- **Cobertura**: cada materia con dictado tiene al menos un horario
  en el cronograma. Las que no, aparecen como "faltantes".
- **Extras**: materias en el cronograma que no tienen dictado.
  Podés crearles el dictado desde acá (**🟢 Activar** o
  **🌐 Activar y marcar virtual**).
- **Partición teoría/laboratorio**: para materias con carga mixta,
  verifica que los horarios sumen las horas declaradas.
- **Conflictos horarios**: choques dentro de mismo año/cuatri/carrera.
  Los que no son reales se pueden marcar como ignorados.

Al terminar, el cronograma queda con un badge:

- 🟢 **validado**: todo OK.
- 🟡 **validado pero modificado**: cambió algo desde la última
  validación; hay que revalidar.
- 🔴 **con issues**: hay faltantes o particiones inválidas.
- ⚪ **sin validar**: nunca se corrió la validación.

![Pestaña Validar: controles y resumen de cobertura](../capturas/cronogramas/validar_controles_y_resumen.png)

**Verificación**: el cronograma tiene badge 🟢 antes de seguir.

**Es imprescindible** que el cronograma quede validado y vigente. Sin
ese estado, no vas a poder elegirlo para generar el plan en el
siguiente paso.

### Paso 7: Generar el plan de cursada

**Página**: 📊 Cursada, solapa **📋 Planes del ciclo**. Antes, elegí
el **Ciclo activo** en el bloque de contexto de la barra lateral.

Al pie de la solapa, abrí el desplegable **➕ Generar plan nuevo desde
un cronograma**. El proceso tiene dos pasos.

**Paso 1 del desplegable**:
1. Elegí el cronograma en **"Cronograma (solo validados y
   vigentes)"**.
2. Poné un **nombre** al plan (viene sugerido, ej. "Plan 2026-1C
   (Nombre del cronograma)") y, si querés, una descripción.
3. Elegí el **método de forecast por defecto** (método de
   pronóstico): "Media móvil", "Drift (lineal)" o "SES (α auto)".
   Si dudás, dejá "Media móvil".
4. Apretá **Crear borrador y continuar →**.

![Formulario para generar un plan nuevo desde un cronograma](../capturas/planes/generar_plan_formulario.png)

El sistema crea el plan y clona todas las comisiones y horarios del
cronograma.

**Paso 2 del desplegable**: editor embebido para revisar el plan
recién creado. Ajustá comisiones si hace falta:
- Cupos.
- Peso (reparto de la demanda entre comisiones de la misma materia).
- Carrera asignada (si una comisión de una materia común se orienta
  a una carrera puntual).

Cuando estés conforme, apretá **✅ Confirmar y salir del wizard**
(así se llama el botón en pantalla). El plan recién creado queda
seleccionado como **Plan activo** en la barra lateral.

> **Cuidado**: el otro botón, **🗑️ Cancelar (borra el plan)**, borra
> el plan **sin confirmación adicional**. No lo aprietes de más.

**Verificación**: en la solapa **📋 Planes del ciclo** aparece una
tarjeta con el plan, marcada como **✅ Activo** (seleccionado).

### Paso 8: Ajustar detalles del plan

**Página**: 📊 Cursada, solapa **🔍 Detalle del Plan** (con el plan
elegido en **Plan activo**).

Revisá:

- **Estadísticas**: cuántas materias, comisiones y horarios hay, y
  cuántos tienen aula (todavía debería ser 0).
- **Acciones del plan**: si hay horarios sin tipo definido en
  materias de un solo tipo (sólo teoría o sólo laboratorio), el
  desplegable **🔧 Acciones del plan** te ofrece auto-completarlos.
  Aplicá el auto-completado si la vista previa te convence.
- **Validaciones**: apretá **Validar plan** y corregí lo que
  aparezca en el resumen de cobertura, el detalle por carrera y por
  materia, y los conflictos horarios.

Para nombre, descripción o método de forecast, se usa **✏️ Editar
metadata** en la solapa **📋 Planes del ciclo**. Horarios y
comisiones se ajustan en la solapa **📋 Horarios**.

![Pestaña Detalle del Plan: estadísticas y calidad del resultado](../capturas/planes/detalle_estadisticas_y_calidad.png)

### Paso 9: Correr el asignador de aulas

**Página**: 📊 Cursada, solapa **🏛️ Aulas**.

1. Verificá que el plan tenga al menos un horario cargado.
2. Abrí el desplegable **🏛️ Asignador de aulas** y, dentro, **🚀
   Correr la asignación (config + botón)**. Antes de correr podés
   usar **▶️ Chequear factibilidad** (dentro de **🚦 Chequeo de
   factibilidad estructural**): es una verificación previa que
   detecta bloqueos (horarios sin aula compatible, franjas saturadas,
   etc.). Si sale en rojo, corregí los datos antes de seguir.
3. En la **⚙️ Configuración del asignador**:
   - **Aplicar desde la fecha**: por defecto es hoy (o el inicio del
     ciclo si es futuro).
   - **Pesos y tolerancias**: los valores por defecto suelen andar
     bien (λ over 10, λ under 1, tolerancia de sobre-ocupación 0,
     tolerancia de sub-utilización 0,20). Ver el módulo de Cursada si
     querés entender qué hace cada uno.
   - **Modo por grupo** (DURO / BLANDO) de cada grupo de materias:
     define cuánto se respetan las sedes de los grupos.
   - **Tiempo máximo de resolución**: 300 segundos suele ser
     suficiente para cuatrimestres grandes.
4. Apretá **🚀 Asignar aulas**.

![Configuración del asignador: alcance temporal y ajuste de capacidad](../capturas/planes/aulas_correr_parametros.png)

El sistema corre el asignador (puede tardar de unos segundos a
varios minutos, según el tamaño del plan). Al terminar, aparece el
resultado:

- **✅ resuelta**: todos los horarios presenciales tienen aula. Ir al
  paso 10.
- **❌ no se pudo resolver**: hay un problema estructural. Ir a
  "Cuando no se puede resolver" más abajo.
- **⏱️ se agotó el tiempo**: el sistema no terminó a tiempo. Subí el
  tiempo máximo y probá de nuevo. Si sigue agotándose,
  probablemente el problema sea estructural (equivalente a "no se
  pudo resolver").

### Paso 10: Revisar el resultado del asignador

En la misma solapa 🏛️ Aulas, después de la corrida:

- **Veredicto y métricas**: horarios totales, asignados,
  sobre-ocupados, sub-utilizados y colisiones (debería haber 0).
- **🔥 Mapa térmico por sede** (dentro de **📊 Estado de asignaciones
  y mapa de saturación**): fijate que no haya sedes en 🔴 (>100% de
  saturación). Si las hay, algo se te pasó al modelar.
- **Tabla por horario** (interruptor **📋 Ver detalle por horario**):
  horarios con aula asignada, con un estado de color:
  - 🟢 ok
  - 🟡 sub (sub-utilizado, aula grande)
  - 🔴 sobre (sobre-ocupado, aula chica)
- **🛠️ Gestión de asignaciones**: para revisar colisiones, filtrar
  horarios y cambiar aulas a mano si hace falta.

![Resultado de una corrida resuelta: veredicto y métricas](../capturas/planes/aulas_veredicto_corrida.png)

![Mapa de saturación de la sede Pellegrini](../capturas/planes/aulas_mapa_saturacion_pellegrini.png)

**Verificación**: la mayoría de los horarios están en 🟢. Si hay
🔴, revisá si el exceso es tolerable (una materia con 51 inscriptos en
un aula para 50 puede estar bien; una materia con 200 inscriptos en
un aula para 30 no).

### Paso 11: Dejar el plan de trabajo seleccionado

El entregable del cuatrimestre es el patrón semanal del plan con sus
aulas asignadas. Para que las demás pestañas trabajen sobre el plan
correcto, alcanza con que esté seleccionado como
**Plan activo** en la barra lateral (o con el botón **Seleccionar**
de su tarjeta en **📋 Planes del ciclo**). Si el ciclo tiene varios planes (por
ejemplo, escenarios de prueba), eliminá los que ya no sirvan para no
confundirlos.

**Verificación**: la tarjeta del plan correcto muestra la marca
**✅ Activo** y los contadores de horarios con aula coinciden con lo
esperado.

## Cuando no se puede resolver

Si el asignador dijo "no se pudo resolver", el panel te muestra un
**diagnóstico** con hasta 5 secciones. Miralas en orden:

1. **Horarios sin aula compatible**: no hay ninguna aula del edificio
   que sirva para ese horario. Puede ser porque:
   - La materia dice que necesita laboratorio pero no tiene
     laboratorios compatibles cargados.
   - El horario es teórico pero está en un tipo que no coincide.
   - El grupo de la materia tiene, en modo DURO, sedes admisibles
     que no incluyen aulas del tipo requerido.

2. **Franjas con faltante de aulas de un tipo específico**: en un
   día × hora hay más clases que aulas del tipo requerido en las
   sedes admisibles. Opciones:
   - Marcar algún horario como virtual (si tiene sentido).
   - Sumar aulas al inventario (cargar aulas que faltaban).
   - Ampliar las sedes admisibles del grupo afectado (📚 Materias →
     📦 Grupos de materias) o pasarlo a modo BLANDO.
   - Mover algún horario a otra franja.

3. **Cuellos de botella**: grupos de clases que compiten por un set
   chico de aulas específicas (típicamente laboratorios). Ídem
   consideraciones arriba.

4. **Franjas saturadas globalmente**: hay más clases simultáneas que
   aulas totales (problema de dimensionamiento macro).

5. **Diagnóstico cruzado**: si las secciones anteriores no
   revelaron nada, el sistema prueba relajar restricciones para ver
   cuál, al ignorarse, permite resolver. Te dice la "causa probable"
   con una de las restricciones (choques temporales, particiones
   teoría/lab, compatibilidad de aula).

Después de actuar sobre la causa, volvé a apretar **🚀 Asignar
aulas**. Iterá hasta que resuelva.

## Verificación final del cuatrimestre

Antes de dar por cerrado el plan, mirá la
**[Verificación pre-inicio](04_Verificacion_pre_inicio.md)**.

## Cómo volver atrás

En cualquier punto del flujo podés retroceder:

- **Borrar el plan**: desde 📊 Cursada → **📋 Planes del ciclo** →
  botón **🗑️ Eliminar** de la tarjeta (sin confirmación). Borra en
  cascada las comisiones y horarios del plan, pero **no** el
  cronograma origen.
- **Borrar el cronograma**: desde 📅 Cronogramas → **📋 Lista** →
  **🗑️ Eliminar cronograma**. Cuidado si ya generaste un plan a
  partir de él (ver el módulo Cronogramas para las advertencias).
- **Borrar el ciclo entero**: desde 📆 Ciclos → bloque "Eliminar
  ciclo". Borra en cascada **todos** los planes, cronogramas y
  dictados del ciclo. Usalo sólo si querés arrancar de cero.

## Puntos de dificultad típicos

- **Paso 1 (versiones de plan)**: fácil de olvidar. Sin versiones
  asignadas, no podés crear dictados.
- **Paso 3 (marcar virtual)**: si hay muchas materias virtuales este
  cuatri, tomate tiempo. Es mejor marcarlas ahora que descubrir el
  problema en el asignador.
- **Paso 4 (plantilla)**: la plantilla sólo se acepta tal como la
  genera la aplicación. Si una cátedra cambia columnas o la versión
  del ciclo no coincide, la revisión la rechaza.
- **Paso 9 (correr asignador)**: si es infactible, es normal que
  itere 2-3 veces antes de resolver. Aceptalo como parte del flujo.
- **Paso 11 (plan seleccionado)**: no hay "activación" que genere
  clases; si ves varios planes, fijate cuál está marcado como
  **✅ Activo** antes de editar.

## Próximo paso

- Si algo cambia después (nueva comisión, aula que se dio de baja,
  etc.), usá el
  **[Flujo 3: Reasignación de aulas](03_Reasignacion_de_aulas.md)**.
- Antes del arranque del cuatrimestre, hacé la
  **[Verificación pre-inicio](04_Verificacion_pre_inicio.md)**.
