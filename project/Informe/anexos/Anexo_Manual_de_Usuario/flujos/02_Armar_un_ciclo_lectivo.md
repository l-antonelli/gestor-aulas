# Flujo 2 — Armar un cuatrimestre nuevo

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
  - Carreras con nombres reales, cantidad de materias y sedes
    habilitadas configuradas.
  - Aulas con capacidad y tipo correctos.
  - Laboratorios compatibles asociados a las materias con carga de
    lab.
- Tenés el **archivo Excel de horarios** que llegó de la facultad
  para el cuatrimestre.
- (Opcional pero recomendado) Los **inscriptos históricos** están
  cargados para que el forecast funcione.

## Pasos

### Paso 1 — Crear el ciclo lectivo

**Página**: 📆 Ciclos.

1. Andá a la solapa **📋 Ciclos**.
2. Bajá hasta la sección **Nuevo Ciclo**.
3. Completá:
   - **Año**: el año del cuatrimestre (ej. 2026).
   - **Cuatrimestre**: 1C o 2C.
   - **Fecha de inicio y fecha de fin**: rango real del cuatrimestre.
   - **Descripción**: libre.
   - **Versiones de plan a asignar**: multiselect obligatorio. Marcá
     la **última versión** de cada carrera cuyas materias se dictan
     este ciclo. Por default el sistema te sugiere la última de cada
     carrera.
4. Apretá **Crear ciclo**.

El ID del ciclo se genera automáticamente como `{año}-{numero}C` (por
ejemplo `2026-1C`) y no se puede editar después.

**Verificación**: el ciclo aparece en la tabla "Ciclos Registrados".

> **Cuidado**: el paso "Versiones de plan a asignar" es obligatorio y
> fácil de olvidar. Sin al menos una versión de plan asignada, no
> podés crear dictados. Si te olvidaste, aparece un warning grande
> cuando vayas a la solapa Dictados.

### Paso 2 — Crear los dictados del ciclo

**Página**: 📆 Ciclos, solapa **📚 Dictados**.

1. Seleccioná el ciclo recién creado en el selector.
2. Apretá el botón **➕ Crear Dictados**.

El sistema recorre las materias de la versión de plan asignada y crea
un **dictado** por cada una que la regla de recursado autoriza para
ese cuatrimestre. Un mensaje te confirma cuántos creó, cuántos son
anuales (linkeados de un cuatri al otro) y cuántos omitió por
recursado.

**Verificación**: mirá las métricas arriba. Deberías ver "Dictados
existentes" con el número esperado. El **panel de divergencias** te
va a mostrar si hay materias del plan sin dictado o dictados que
sobran (típicamente no debería haber después del bulk create).

### Paso 3 — Revisar y ajustar dictados

Todavía en 📆 Ciclos → 📚 Dictados.

Recorré las materias por carrera (los expanders `🎓 código —
nombre`) y ajustá:

- **Modalidad virtual**: por cada materia que este cuatrimestre se
  dicta por Zoom (o modalidad no presencial), marcá el toggle
  **Virtual** correspondiente.
- **Recursado excepcional**: si alguna materia se dicta contra la
  regla habitual, ajustá el selector "Recursado" para esa fila.

Los cambios se acumulan en la sección **⏳ Cambios pendientes** al
pie. Cuando termines de ajustar, apretá **💾 Aplicar cambios**.

**Verificación**: los toggles reflejan el estado deseado y las
métricas superiores ("Virtuales", "Recursado fijado a mano") muestran
los números correctos.

Si el panel de divergencias tiene alertas, resolvelas antes de
seguir: 🎯 crear los dictados faltantes, 🗑️ borrar los huérfanos, o
⬆️ promover a regla si querés cambiar la política del catálogo. Ver
detalles en el manual del módulo Ciclos.

### Paso 4 — Cargar el cronograma

**Página**: 📅 Cronogramas, solapa **📤 Cargar**.

1. Elegí "Cargar desde archivo".
2. Poné un **nombre** al cronograma (ej. "Cronograma FCEIA 2026-1C
   v1").
3. Elegí el **ciclo** al que corresponde.
4. Subí el archivo Excel/CSV con los horarios (columnas esperadas:
   materia, día, hora inicio, hora fin, comisión).
5. Apretá **Crear cronograma**.

El sistema procesa el archivo y crea un cronograma con todas las
filas. Si hay errores por fila (materia inexistente, código sin
matchear, formato malo), aparecen listados. Corregí el Excel y volvé
a subirlo.

> **Cuidado**: por un problema conocido del sistema, aunque tu Excel
> tenga una columna "comisión" con números, esa información **no se
> persiste** al importar. Todas las filas quedan sin comisión
> asociada. Tenés que asociarlas manualmente en el paso siguiente.

### Paso 5 — Revisar y editar el cronograma

**Página**: 📅 Cronogramas, solapa **✏️ Editar**.

1. Seleccioná el cronograma recién creado.
2. Recorré las materias en modo "Por materia" o "Por grupo" para:
   - **Verificar horarios**: cada materia debería tener sus horarios
     esperados.
   - **Asociar comisiones**: por cada fila sin comisión, editar y
     asignarle un número. Podés crear comisiones nuevas desde el
     mismo diálogo si hace falta.
   - **Marcar tipo**: si el cronograma no trae el tipo (teórica /
     laboratorio) de cada fila, marcá los que puedas determinar.
   - **Marcar virtual**: si algún horario específico se dicta por
     Zoom (y la materia entera no es virtual), marcalo desde el
     diálogo de editar horario.

Este paso puede tardar bastante — es donde más tiempo se invierte al
principio del cuatrimestre.

**Verificación**: navegá por materia y confirmá que:
- No queden horarios sin comisión asignada (o al menos que sepas por
  qué los dejaste sin asignar).
- Los tipos de aula estén asignados donde importe (materias con
  laboratorio).

### Paso 6 — Validar el cronograma

**Página**: 📅 Cronogramas, solapa **✅ Validar**.

1. Seleccioná el ciclo y el cronograma.
2. Apretá **Validar cronograma**.

El sistema chequea:

- **Cobertura**: cada materia con dictado activo tiene al menos un
  horario en el cronograma. Los que no, aparecen como "faltantes".
- **Extras**: materias en el cronograma que no tienen dictado.
  Podés activarlas en bloque desde acá (🟢 Activar o 🌐 Activar y
  marcar virtual).
- **Partición teoría/laboratorio**: para materias con carga mixta,
  chequea que los horarios sumen las horas declaradas.
- **Conflictos horarios**: choques dentro de mismo año/cuatri/carrera.

Al terminar, el cronograma queda con un badge:

- 🟢 **Validado y vigente**: todo OK.
- 🟡 **Validado pero desactualizado**: cambió algo desde la última
  validación; hay que revalidar.
- 🔴 **Con issues**: hay faltantes o particiones inválidas.
- ⚪ **Sin validar**: nunca se corrió la validación.

**Verificación**: el cronograma tiene badge 🟢 antes de seguir.

**Es imprescindible** que el cronograma quede como 🟢 Validado y
vigente. Sin ese estado, no vas a poder generar el plan en el
siguiente paso.

### Paso 7 — Generar el plan de cursada

**Página**: 📊 Planes, solapa **📥 Generar Plan**.

Wizard de 2 pasos:

**Paso 1 del wizard**:
1. Elegí el ciclo.
2. Elegí el cronograma (sólo aparecen los 🟢 Validados y vigentes).
3. Poné un nombre al plan (ej. "Plan 2026-1C — v1").
4. Elegí el método de forecast default (probá con `media_movil` si
   dudás — funciona bien para la mayoría de materias con serie
   histórica).
5. Apretá **Crear borrador y continuar →**.

El sistema crea el plan como borrador (activo = No) y clona todas las
comisiones y horarios del cronograma.

**Paso 2 del wizard** — editor embebido para revisar el plan recién
creado. Ajustá comisiones si hace falta:
- Cupos.
- Peso (redistribución de la demanda entre comisiones de la misma
  materia).
- Carrera asignada (si una comisión de una materia común se orienta
  a una carrera puntual con sede distinta).

Cuando estés conforme, apretá **✅ Confirmar y salir del wizard**.

> **Cuidado**: el otro botón, **🗑️ Cancelar (borra el plan)**, borra
> el plan **sin confirmación adicional**. No lo aprietes de más.

**Verificación**: en la solapa **📋 Vista General** aparece el plan
recién creado como borrador (⚪ inactivo).

### Paso 8 — Ajustar detalles del plan

**Página**: 📊 Planes, solapa **🔍 Detalle del Plan**.

Seleccioná el plan y revisá:

- **Metadata**: nombre, descripción, método de forecast default.
- **Estadísticas**: cuántas materias, comisiones, horarios y cuántos
  tienen aula (todavía debería ser 0).
- **Acciones del plan**: si hay horarios sin tipo definido en
  materias mono-modales (sólo teórica o sólo laboratorio), el
  sistema te ofrece auto-completar. Aprietá "Aplicar" si el preview
  te convence.
- **Validaciones**: panel unificado con chequeos por materia. Corregí
  lo que aparezca.

### Paso 9 — Correr el asignador de aulas

**Página**: 📊 Planes, solapa **🏛️ Aulas**.

1. Revisá que el precheck esté OK (el plan tiene al menos un
   horario).
2. En el panel de configuración:
   - **Aplicar desde la fecha**: por defecto es hoy. Si estás
     armando un cuatrimestre a futuro, poné la fecha de inicio del
     ciclo.
   - **Pesos y tolerancias**: los valores por defecto (10, 1, 0,
     0.2) suelen andar bien. Ver el módulo Planes si querés
     entender qué hace cada uno.
   - **Tiempo máximo**: 300 segundos suele ser suficiente para
     cuatrimestres grandes.
3. Apretá **🚀 Asignar aulas**.

El sistema corre el asignador (puede tardar de 5 a 60 segundos
dependiendo del tamaño del plan). Al terminar, aparece el resumen:

- **✅ resuelta**: todos los horarios tienen aula. Ir al paso 10.
- **❌ no se pudo resolver**: hay un problema estructural. Ir a
  "Cuando no se puede resolver" abajo.
- **⏱️ se agotó el tiempo**: el sistema no terminó a tiempo. Subí
  el "Tiempo máximo" y probá de nuevo. Si sigue agotándose,
  probablemente el problema sea estructural (equivalente a "no se
  pudo resolver").

### Paso 10 — Revisar el resultado del asignador

En la misma solapa 🏛️ Aulas, después de la corrida:

- **Mapa de saturación por sede**: fijate que no haya sedes en 🔴
  (>100% de saturación). Si las hay, algo se te pasó al modelar.
- **Tabla de resultados**: horarios con aula asignada, coloreados
  por gap:
  - 🟢 ok
  - 🟡 sub-utilizado (aula grande)
  - 🔴 sobre-ocupado (aula chica)
- **Cronograma por aula** (expander al final): vista día × hora por
  aula, para verificar que no haya choques.

**Verificación**: la mayoría de los horarios están en 🟢. Si hay
🔴, revisá si el over es tolerable (una materia con 51 inscriptos en
un aula para 50 puede estar bien; una materia con 200 inscriptos en
un aula para 30 no).

### Paso 11 — Activar el plan

En **📊 Planes**, tenés dos formas de "activar":

1. Desde el **panel de Validación** del tab Detalle → botón
   **Activar plan**: activa el plan **y genera las clases** (una
   por fecha del cuatrimestre). Es la opción **completa**.
2. Desde el tab **Vista General** → botón **Activar**: sólo marca
   el plan como activo, **sin generar las clases**. Es un modo
   "rápido" pensado para toggle entre planes borrador.

Para el arranque del cuatrimestre, usá la opción 1 (activar y
generar clases).

**Verificación**: el plan queda con badge 🟢 ACTIVO. Sólo uno por
ciclo puede estar activo — al activar este, los otros del mismo
ciclo se desactivan solos.

## Cuando no se puede resolver

Si el asignador dijo "no se pudo resolver", el panel te muestra un
**diagnóstico** con hasta 5 secciones. Miralas en orden:

1. **Horarios sin aula compatible**: no hay ninguna aula del edificio
   que sirva para ese horario. Puede ser porque:
   - La materia dice que necesita laboratorio pero no tiene
     laboratorios compatibles cargados.
   - El horario es teórico pero está en un tipo que no matchea.
   - La carrera tiene sedes admisibles que no incluyen las aulas del
     tipo requerido.

2. **Franjas con faltante de aulas de un tipo específico**: en un
   día × hora hay más clases que aulas del tipo requerido en las
   sedes admisibles. Opciones:
   - Marcar alguna clase como virtual (si tiene sentido).
   - Sumar aulas al inventario (habilitar aulas que estaban sin
     cargar).
   - Ampliar las sedes admisibles de la carrera afectada.
   - Mover algún horario a otra franja.

3. **Cuellos de botella**: grupos de clases que compiten por un set
   chico de aulas específicas (típicamente laboratorios). Ídem
   consideraciones arriba.

4. **Franjas saturadas globalmente**: hay más clases simultáneas que
   aulas totales — problema de dimensionamiento macro.

5. **Diagnóstico cruzado**: si las secciones anteriores no
   revelaron nada, el sistema prueba relajar restricciones para ver
   cuál al ignorarse permite resolver. Te dice "causa probable" con
   una de las restricciones (choques temporales, particiones teoría/
   lab, compatibilidad de aula).

Después de actuar sobre la causa, volvé a apretar **🚀 Asignar
aulas**. Iterá hasta que dé óptimo.

## Verificación final del cuatrimestre

Antes de dar por cerrado el plan, mirá la
**[Verificación pre-inicio](04_Verificacion_pre_inicio.md)**.

## Rollback

En cualquier punto del flujo podés retroceder:

- **Borrar el plan** (antes o después de activar): desde 📊 Planes →
  Vista General → botón Eliminar. Borra en cascada las comisiones y
  horarios del plan, pero **no** el cronograma origen.
- **Borrar el cronograma**: desde 📅 Cronogramas → Lista → Eliminar.
  Cuidado si ya generaste un plan a partir de él — ver módulo
  Cronogramas para las advertencias.
- **Borrar el ciclo entero**: desde 📆 Ciclos → sección "Eliminar
  Ciclo". Borra en cascada **todos** los planes, cronogramas y
  dictados del ciclo. Usalo sólo si querés arrancar de cero.
- **Desactivar un plan**: activar otro plan del mismo ciclo. El
  primero se desactiva automáticamente.

## Puntos de fricción típicos

- **Paso 2 (versiones de plan)**: fácil de olvidar. Sin versiones
  asignadas, no podés crear dictados.
- **Paso 3 (marcar virtual)**: si hay muchas materias virtuales este
  cuatri, tomate tiempo. Es mejor marcarlas ahora que descubrir el
  problema en el asignador.
- **Paso 5 (asociar comisiones)**: por el bug de import, todos los
  horarios quedan sin comisión. Presupuestá tiempo para asociarlas
  a mano.
- **Paso 9 (correr asignador)**: si es infactible, es normal que
  itere 2-3 veces antes de resolver. Aceptalo como parte del flujo.
- **Paso 11 (activación)**: los dos botones de "Activar" tienen
  semántica distinta — usar el correcto (ver arriba).

## Próximo paso

- Si algo cambia después de activar (nueva comisión, aula que se dio
  de baja, etc.), usá el
  **[Flujo 3 — Reasignación de aulas](03_Reasignacion_de_aulas.md)**.
- Antes del arranque del cuatrimestre, hacé la
  **[Verificación pre-inicio](04_Verificacion_pre_inicio.md)**.
