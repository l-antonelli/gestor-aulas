# Aulas y Sedes

## ¿Para qué sirve?

La página **🏛️ Aulas y Sedes** es el catálogo de recursos físicos del
sistema. Es donde se dan de alta las aulas (con su capacidad, tipo y
sede) y las sedes de la facultad. Las aulas son lo que el asignador
distribuye entre los patrones semanales de cada plan de cursada, así
que su catálogo condiciona directamente qué asignaciones son posibles.

## ¿Cuándo vas a usar este módulo?

- **Setup inicial**: después de la carga masiva, para completar aulas
  fuera de la sede default, crear sedes adicionales (Zeballos, Beltrán,
  Siberia, etc.) y marcar la sede default para materias comunes.
- **Alta de una sede nueva**: cuando la facultad habilita un edificio
  o anexo que antes no se usaba.
- **Alta de un aula nueva**: cuando se acondiciona un espacio nuevo o
  se reasigna un aula existente.
- **Baja o remodelación**: cuando un aula deja de estar disponible
  temporalmente o para siempre.
- **Cambio de capacidad**: cuando se reacondiciona un aula y cambia el
  cupo (por ejemplo, se le sacan bancos).
- **Reconfiguración de laboratorios**: cambiar el tipo de un aula
  general a laboratorio o viceversa.
- **Consolidación**: fusionar dos sedes cuando alguien creó una con el
  nombre mal escrito y hay que unificar.
- **Antes de correr el asignador de aulas por primera vez**: revisar
  que las sedes habilitadas por carrera y la sede default de comunes
  estén configuradas correctamente.

## Cómo se relaciona con el resto

- **Depende del catálogo de sedes**: no se puede crear un aula si no
  existe al menos una sede. La carga inicial crea la sede "Pellegrini"
  por default, pero otras sedes hay que crearlas a mano.
- **Alimenta Materias**: las aulas de tipo laboratorio son las que se
  pueden asociar como "laboratorios compatibles" de una materia.
- **Alimenta Carreras**: cada carrera puede tener una lista de sedes
  habilitadas (donde el asignador puede colocar sus materias
  exclusivas).
- **Alimenta el asignador de aulas**: las aulas son el recurso que el
  asignador distribuye. Su capacidad, tipo y sede determinan qué
  asignaciones son factibles.
- **Depende de Planes**: para borrar un aula, no puede tener clases
  asignadas en ningún plan activo.

## Recorrido rápido de la página

Cuatro solapas:

- **📋 Listado**: vista tabular de todas las aulas, con filtro por
  sede. Es solo lectura.
- **➕ Crear**: formulario para dar de alta un aula nueva.
- **👁️ Ver detalle**: seleccionás un aula y accedés a la edición
  inline, más la opción de borrarla y (si es laboratorio) la
  asociación con materias.
- **📍 Sedes**: catálogo de sedes de la facultad, con opciones para
  crear, renombrar, borrar y fusionar sedes, más la marca de "sede
  default para materias comunes".

## Tareas comunes

### Crear una sede

1. Andá a la solapa **📍 Sedes**.
2. Desplegá el expander **"➕ Crear sede"**.
3. Escribí un **nombre único** para la sede (por ejemplo, "Zeballos" o
   "Siberia"). El nombre no puede repetirse con otra sede existente.
4. Confirmá.
5. Verificación: la sede aparece en la tabla superior de la solapa con
   conteo de aulas en cero.

**Cuándo**: hacelo antes de dar de alta las aulas de esa sede. Si
intentás crear un aula sin haber creado la sede, el sistema te lo va
a avisar.

### Renombrar una sede

1. En la solapa **📍 Sedes**, desplegá el expander **"✏️ Renombrar /
   borrar sede"**.
2. Elegí la sede que querés renombrar.
3. Escribí el nombre nuevo.
4. Apretá **Renombrar**.
5. Verificación: la tabla de sedes muestra el nombre nuevo. Todas las
   aulas asociadas siguen apuntando a la misma sede (con nombre
   actualizado).

**Ojo con el código autogenerado**: si algún aula tiene el nombre viejo
de la sede embebido en su código (porque se creó dejando el campo
Código vacío y se autogeneró), ese código se queda con el nombre viejo
pegado. Renombrar la sede no reescribe los códigos autogenerados de sus
aulas — hay que editarlas una por una si molesta.

### Borrar una sede

1. Desplegá el expander **"✏️ Renombrar / borrar sede"** y elegí la
   sede.
2. Apretá **Borrar**.
3. Confirmá.
4. Verificación: la sede desaparece de la tabla.

**Restricción importante**: no se puede borrar una sede que tenga aulas
asociadas. El botón queda deshabilitado y muestra el motivo. Si
necesitás borrarla igual, la forma correcta es **fusionarla** con otra
sede (ver más abajo), que reasigna las aulas al destino y borra la
origen.

### Marcar la sede default para materias comunes

Esta configuración es clave para el asignador de aulas: las materias
"comunes" (las que aparecen en dos o más carreras distintas) se asignan
únicamente a la sede que esté marcada como default de comunes.

1. En la solapa **📍 Sedes**, desplegá el expander **"🏛️ Sede por
   defecto para materias comunes"**.
2. En el selector, elegí la sede que querés marcar como default. Solo
   una sede puede tener este rol a la vez — si activás una nueva, la
   anterior se desmarca automáticamente sin aviso.
3. También podés elegir "— ninguna —" para no tener default. En ese
   caso, el asignador considera "todas las sedes" para las materias
   comunes.
4. Guardá.
5. Verificación: en la tabla superior de sedes, la columna "Default
   comunes" muestra el ícono 🏛️ en la sede marcada.

**Gotcha**: si nunca marcaste ninguna, no falla nada, pero el asignador
va a tener libertad total para poner las materias comunes en cualquier
sede — lo cual puede no ser lo que querés.

### Fusionar dos sedes

Sirve para consolidar cuando alguien creó una sede con el nombre mal
escrito ("Pelegrini" vs "Pellegrini") y hay que unificar.

1. En la solapa **📍 Sedes**, desplegá el expander **"🔗 Fusionar
   sedes"**.
2. Elegí la **sede origen** (la que va a desaparecer) y la **sede
   destino** (la que absorbe todas las aulas).
3. Confirmá.
4. Verificación: todas las aulas de la sede origen ahora aparecen bajo
   la sede destino. La sede origen desaparece de la tabla.

**Precauciones**:

- Necesitás al menos dos sedes creadas.
- La operación no se puede deshacer. Verificá bien cuál es cuál antes
  de confirmar.
- Los códigos autogenerados de las aulas reasignadas siguen pegados al
  nombre viejo (ver "Renombrar una sede").

### Crear un aula nueva

1. Andá a la solapa **➕ Crear**.
2. Completá los campos:
   - **Nombre del aula** (obligatorio): por ejemplo, "AULA 101" o
     "Laboratorio 3".
   - **Sede** (obligatorio): elegí la sede a la que pertenece. Si no
     hay sedes, primero creá una desde la solapa 📍 Sedes.
   - **Código** (opcional): identificador visible del aula. Si lo
     dejás vacío, se autogenera como
     `{nombre de la sede}-{nombre del aula}` con guiones en lugar de
     espacios. Ejemplo: sede "Pellegrini" + aula "AULA 01" da como
     código `Pellegrini-AULA-01`. Un placeholder te muestra en tiempo
     real cómo va a quedar.
   - **Capacidad**: mínimo 1, default 30. Cantidad máxima de personas
     que entran en el aula.
   - **Tipo**: elegí entre teorica, practica, laboratorio o anfiteatro.
     El default es teorica. Este campo condiciona qué materias
     pueden usar el aula (por ejemplo, las clases de tipo laboratorio
     solo van a aulas laboratorio).
   - **Descripción** (opcional): notas libres sobre el aula.
3. Apretá **Crear aula**.
4. Verificación: el aula aparece en el listado (solapa 📋 Listado) con
   los datos que le cargaste.

**Gotcha**: el código del aula tiene que ser único a nivel sistema, no
solo dentro de la sede. Si el autogenerado choca con uno existente,
vas a ver el error "Ya existe un aula con código '{codigo}'. Editalo
manualmente para usar otro." — en ese caso, escribí un código
manualmente.

### Editar un aula existente

1. Andá a la solapa **👁️ Ver detalle**.
2. En el selector, elegí el aula que querés editar (formato: `código —
   nombre (sede)`).
3. Modificá los campos que necesites: Nombre, Sede, Código, Capacidad,
   Tipo o Descripción.
4. Apretá **Guardar cambios**.
5. Verificación: el aula se refresca con los nuevos datos.

Si no hiciste ningún cambio, el sistema muestra "Sin cambios" y el
botón de guardar no dispara nada.

**Cambio de sede**: si cambiás la sede de un aula, se mueve al nuevo
edificio en el sistema. Los códigos autogenerados no se actualizan
solos.

**Cambio de tipo a/desde laboratorio**: el sistema te avisa
explícitamente en un mensaje al costado que **no** se borran las
asociaciones con materias que la tenían como laboratorio compatible.
Estas relaciones quedan "colgando" — probablemente inofensivas porque
las consultas filtran por tipo antes de mostrarlas, pero conviene
revisarlas manualmente si el cambio es definitivo.

### Cargar materias que usan un laboratorio

Cuando el aula es tipo laboratorio, en la solapa **👁️ Ver detalle**
aparece una sección adicional debajo del formulario, llamada
**"Materias que usan este laboratorio"**.

1. En esa sección hay un multiselect con todas las materias del
   catálogo.
2. Elegí las materias que se pueden dictar en este laboratorio.
3. Guardá los cambios.
4. Verificación: al volver a la página de Materias y ver la sub-solapa
   Laboratorios de esas materias, el aula que acabás de configurar
   aparece asociada.

Esta lista es la que el asignador consulta cuando tiene que asignar
aula a un patrón semanal de tipo laboratorio.

### Eliminar un aula

1. Andá a **👁️ Ver detalle**, elegí el aula.
2. Bajá al expander **"🗑️ Borrar aula"**.
3. Confirmá.
4. Verificación: el aula desaparece del listado.

**Restricción**: no se puede borrar un aula que tenga clases asignadas
en un plan activo. El sistema muestra el error "No se puede borrar: el
aula tiene clases asignadas. Reasignalas primero." — en ese caso, hay
que primero reasignar esas clases a otras aulas (desde el panel de
asignación del plan) o desactivar el plan que las contiene.

**Nota**: los cambios en aulas **no quedan registrados en el
Historial**. Si necesitás llevar rastro de "quién cambió la capacidad de
tal aula", tenés que anotarlo en otro lado.

## Errores frecuentes y qué hacer

| Mensaje | ¿Qué significa? | Cómo lo resolvés |
|---|---|---|
| "No hay sedes cargadas. Creá al menos una sede en la pestaña '📍 Sedes' antes de crear un aula." | Estás intentando crear un aula pero el catálogo de sedes está vacío | Andá a la solapa Sedes y creá al menos una |
| "Ya existe un aula con código '{codigo}'. Editalo manualmente para usar otro." | El código autogenerado choca con uno existente | Escribí un código manualmente en el campo Código |
| "Ya existe otra aula con código '{codigo}'." | Al editar cambiaste el código a uno que ya usa otra aula | Elegí un código distinto |
| "No se puede borrar: el aula tiene clases asignadas. Reasignalas primero." | El aula está siendo usada por un plan activo | Reasigná esas clases desde el panel de asignación del plan, o desactivá el plan |
| "Ya existe la sede '{nombre}'." | Estás intentando crear o renombrar una sede con un nombre ya en uso | Elegí otro nombre |
| "No se puede borrar la sede '...': tiene aulas asociadas. Reasignalas primero o usá 'fusionar' para moverlas a otra sede." | Estás intentando borrar una sede que aún tiene aulas | Fusionala con otra sede, o cambiale la sede a cada aula manualmente |
| "La sede origen y la destino son la misma." | Al fusionar elegiste la misma sede en ambos campos | Elegí sedes distintas |

## Preguntas frecuentes

**¿Puedo tener dos aulas con el mismo nombre en distintas sedes?**
Sí, siempre que el código sea distinto. El código se autogenera con el
nombre de la sede, así que "AULA 01" en Pellegrini y "AULA 01" en
Zeballos generan códigos distintos (`Pellegrini-AULA-01` y
`Zeballos-AULA-01`) y no chocan.

**¿Puedo tener dos aulas con el mismo código?**
No. El código es único a nivel sistema (no por sede).

**¿Qué pasa si cambio el tipo de un aula de "laboratorio" a "teórica"?**
El aula deja de aparecer como candidata en las asociaciones "laboratorios
compatibles" de las materias. Las asociaciones existentes con esa aula
**no se borran automáticamente**, pero como el sistema filtra por tipo,
en la práctica dejan de tener efecto. Si preferís limpiarlas
manualmente, andá a las materias afectadas y desasocialas.

**¿Qué diferencia hay entre las cuatro categorías de tipo (teorica,
practica, laboratorio, anfiteatro)?**
- **Teorica**: aula estándar para clases magistrales.
- **Practica**: aula para clases prácticas (menos frontal, más
  interacción).
- **Laboratorio**: aula equipada para prácticas experimentales.
  Requiere que la materia haya asociado el aula como compatible.
- **Anfiteatro**: aula grande, tipo auditorio, para clases con
  mucha asistencia.

El asignador respeta la compatibilidad de tipo entre aula y clase.

**¿Qué es la "sede default de comunes"?**
Es la sede a la que el asignador manda por default las materias que
aparecen en más de una carrera. Sirve para concentrar las materias
compartidas en un solo edificio y evitar duplicación entre sedes.
Solo una sede puede tener este rol a la vez.

**¿Y si no hay sede default de comunes?**
El asignador asume "todas las sedes" para las materias comunes. Podés
querer esto si tu facultad no separa las comunes por edificio.

**¿Puedo tener un aula sin sede?**
No. La sede es obligatoria. Hay que crear al menos una sede antes de
crear la primera aula.

**¿Los cambios en un aula quedan registrados en el Historial?**
No. Aulas no se auditan. Los cambios en sedes tampoco, salvo la marca
de "sede default para comunes" que sí queda registrada.

**¿Puedo fusionar tres sedes en una?**
Sí, pero de a dos por vez. Fusionás sede A → sede C, después sede B →
sede C.

**¿Cómo se decide el default "30" en el campo Capacidad?**
Es un valor arbitrario para arrancar. Cambialo al valor real del aula.
El sistema valida que sea mayor o igual a 1.

**¿La capacidad afecta el asignador?**
Sí. El asignador prefiere colocar cada comisión en un aula con
capacidad cercana a los inscriptos esperados. Aulas muy grandes para
comisiones chicas o aulas chicas para comisiones grandes generan un
"gap" que el asignador intenta minimizar.

## Términos importantes de este módulo

- **Aula**: espacio físico donde se dictan clases. Tiene un código, un
  nombre, una sede, una capacidad y un tipo.
- **Sede**: edificio o predio de la facultad donde hay aulas. Ejemplos
  típicos: Pellegrini, Zeballos, Siberia, Beltrán.
- **Tipo de aula**: categoría que dice qué clase de actividad se puede
  hacer ahí. Cuatro opciones: teorica, practica, laboratorio,
  anfiteatro.
- **Capacidad**: cantidad máxima de personas que entran en el aula.
- **Código del aula**: identificador único a nivel sistema, generalmente
  autogenerado con el formato `{sede}-{nombre}` si no se completa a
  mano.
- **Sede default para materias comunes**: sede que el asignador prefiere
  para las materias que se dictan en más de una carrera. Solo puede
  haber una activa a la vez.
- **Sedes habilitadas por carrera**: lista de sedes donde una carrera
  puede dictar sus materias exclusivas. Se configura desde la página
  de Carreras. Si una carrera no tiene ninguna configurada, el sistema
  asume "todas las sedes".
- **Materia común**: materia que aparece en dos o más carreras. Se
  asigna a la sede default de comunes.
- **Materia exclusiva**: materia que aparece en una sola carrera. Se
  asigna a las sedes habilitadas de esa carrera.
- **Laboratorio compatible**: relación entre un aula tipo laboratorio y
  una materia que puede usarlo para su parte práctica.
- **Fusión de sedes**: operación que reasigna todas las aulas de una
  sede a otra y borra la sede origen. Útil para consolidar duplicados.
