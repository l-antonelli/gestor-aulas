# Historial

## ¿Para qué sirve?

La página **📜 Historial** te muestra un registro de cambios de las
decisiones importantes que se tomaron en el sistema. Cada vez que
alguien modifica una materia, un dictado, una carrera o una sede (entre
otras cosas), queda una fila con el "antes" y el "después", cuándo se
hizo y desde qué página.

Es una vista de solo lectura: sirve para consultar, no para modificar.
No permite deshacer cambios, ni editarlos, ni exportarlos a un archivo.

En resumen, sirve para responder preguntas como:

- ¿Cuándo se marcó como virtual este dictado?
- ¿Alguien tocó las horas de teoría de esta materia en los últimos días?
- ¿Cuándo se activó el recursado para esta carrera?
- ¿De qué página vino este cambio (Ciclos, Planes, Validación)?

---

## ¿Cuándo vas a usar este módulo?

Vas a entrar a **Historial** en estos escenarios típicos:

- **Investigar un cambio inesperado**: alguien pregunta "¿por qué esta
  materia figura como virtual?" o "¿desde cuándo esta carrera dicta
  recursado?".
- **Auditar la etapa previa al cierre del cuatrimestre**: antes de
  activar el plan definitivo, revisar el feed reciente para detectar
  ediciones sospechosas hechas por otras sesiones.
- **Verificar que un cambio bulk se aplicó**: por ejemplo, después de
  usar "Aplicar todo" en el panel de divergencias, revisar que las
  materias hayan quedado con los flags correctos.
- **Reconstruir el contexto** de una decisión pasada: por qué se creó
  este dictado, por qué se aceptó como virtual, etc.

No es una página que uses todos los días. Es más bien una herramienta
de diagnóstico y auditoría puntual.

---

## Cómo se relaciona con el resto

El historial se **alimenta automáticamente**: cada vez que se cambia un
campo trackeado en cualquier otra página del sistema, se genera una
fila acá. No hay que hacer nada manualmente para que se registre.

La página **no afecta** al resto del sistema. Es puramente lectura.

Pensalo así:

- **📚 Materias / 🎓 Carreras / 📆 Ciclos / 📊 Planes / ✅ Validación**:
  producen eventos.
- **📜 Historial**: los consume y los muestra.

---

## Modelo mental

### Qué eventos se registran

El sistema registra automáticamente los cambios sobre estas entidades:

**Catálogo maestro**

- **Materias**: modificación de los flags `virtual` (modalidad de
  catálogo), `dicta_recursado`, `optativa`, activación, y de las horas
  de teoría / laboratorio. También alta y baja.
- **Carreras**: modificación del flag `dicta_recursado`. También alta y
  baja.
- **Dictados**: modificación del flag `virtual` (modalidad del ciclo).
  También alta y baja.
- **Dictados por ciclo (bridge)**: alta y baja del vínculo entre un
  dictado y un ciclo.
- **Sedes**: modificación del flag "es sede default para materias
  comunes". También alta y baja.

**Cronogramas (pre-plan)**

- **Cronogramas**: modificación del nombre y del ciclo. También alta
  y baja.
- **Entradas del cronograma**: modificación del día, hora inicio,
  hora fin, comisión asignada, tipo de clase, override de
  virtualidad. También alta y baja.

**Plan de cursada**

- **Planes de cursada**: modificación del nombre, descripción, ciclo,
  y método de forecast por defecto. También alta y baja.
- **Comisiones**: modificación del nombre, número, cupo, coeficiente
  de asignación, dictado y carrera asignada. También alta y baja.
- **Horarios del plan**: modificación del aula asignada, tipo de
  clase, día, hora inicio, hora fin, override de virtualidad y del
  flag "aula asignada manualmente". También alta y baja.

### Qué NO se registra

Esto es tan importante como lo anterior. Los siguientes cambios **no
dejan rastro individual** en el historial:

- **Corridas del asignador**: no emiten un evento por cada horario
  reasignado. En su lugar, cada corrida óptima que efectivamente
  cambia alguna asignación genera **una sola fila agregada** en el
  historial (entidad `LPRunDB`, action `created`, origin `lp:run`)
  con el detalle de reasignaciones (`horario_id`, `aula_previa`,
  `aula_nueva`) en el `new_value`. Las corridas idempotentes (mismos
  parámetros, sin cambios en el patrón) NO emiten evento. La fila de
  `LPRunDB` sigue guardando la solución completa, tolerancias y
  métricas por su lado.
- Ediciones sobre la serie histórica de inscriptos.
- Ediciones sobre los overrides manuales del forecast (el "Total
  esperado (manual)" del plan).
- Ediciones sobre aulas del catálogo y sedes (excepto el flag "es
  sede default" de sedes).
- Cambios directos hechos por scripts o comandos de línea (por
  ejemplo, reinicializar la base entera con `load_initial_data
  --reset` no queda registrado).
- Cambios en el nombre, el código o el período de una materia (esos
  campos no están trackeados aunque otros de la misma materia sí lo
  estén).

> **Regla mental**: el historial audita **cambios individuales del
> catálogo, del plan y del cronograma**. Las corridas del asignador
> (bulk operations) se auditan aparte via LPRun (una fila por
> corrida) para mantener el historial legible.

### Estructura de un evento

Cada fila del historial tiene los siguientes datos:

- **Acción**: si fue una creación (➕), una edición (✏️) o un borrado
  (🗑️).
- **Tipo de entidad**: si fue una Materia, Carrera, Dictado, Sede, etc.
- **Etiqueta de la entidad**: identificación humana (nombre + código o
  similar), preservada aunque después la entidad se borre.
- **Campo**: qué campo cambió (sólo para ediciones).
- **Valor viejo → valor nuevo**: sólo para ediciones.
- **Cuándo**: timestamp del cambio, en formato relativo ("hace unos
  segundos", "hace 5 min", "hace 3 h", "hace 4 días") o fecha absoluta
  para eventos viejos.
- **Origen**: desde qué página o proceso se hizo (por ejemplo, "Ciclos",
  "Validación", "Planes", "auto" para hooks internos).
- **Razón (reason)**: descripción en texto libre del contexto. Aparece
  cuando la operación fue un bulk (aplicar todo, promover a regla,
  etc.) o una acción explícita del usuario. Puede estar vacía para
  cambios sin contexto declarado.

> **Nota sobre las fechas absolutas**: cuando un evento es más viejo que
> 30 días, la UI muestra la fecha en formato absoluto (`AAAA-MM-DD`).
> Esa fecha está en **hora UTC**, no en la hora local de Rosario. Si
> mirás un evento que dice "2026-07-15" y son las 22:00 en Argentina
> del 14 de julio, el evento efectivamente puede haber ocurrido en
> horario local del 14. La diferencia es de 3 horas.

### Origen del cambio

Cada evento incluye un **origen** que indica de dónde vino el cambio.
Los orígenes que vas a ver son:

- **auto**: hook automático (cambio hecho desde una página que no
  declara contexto explícito, como Materias o Carreras).
- **ui:ciclos**: desde la página de Ciclos, en general desde el panel
  de divergencias o desde acciones bulk.
- **ui:validacion**: desde la página de Validación (aceptar materias
  del cronograma, bulk desactivar).
- **ui:planes**: desde la página de Planes (edición del flag virtual de
  un horario, o cambio de carrera asignada de una comisión).
- **script**: cambio hecho desde línea de comandos.

> **Aclaración**: aunque en la UI aparezcan las etiquetas "Materias" y
> "Carreras" como orígenes posibles, en la práctica las páginas de
> Materias y de Carreras no marcan contexto explícito, por lo que sus
> cambios quedan con origen `auto`. Es una limitación conocida.

---

## Recorrido rápido de la página

La página se divide en dos tabs:

### Tab 1 — 🌐 Feed global

Muestra los cambios más recientes de todo el sistema, en orden
cronológico descendente.

Controles superiores:

- **Últimos N días**: cutoff temporal (default 30, mínimo 1, máximo
  365). Sólo se muestran eventos ocurridos en esa ventana.
- **Máx. eventos**: cap de resultados (default 100, mínimo 10, máximo
  500). Si hay más eventos en la ventana, se muestran los más
  recientes.

Filtros adicionales in-widget:

- **Tipo de entidad**: multiselect. Sólo aparecen los tipos que
  efectivamente hay en la ventana.
- **Origen**: multiselect. Sólo aparecen los orígenes presentes en la
  ventana.

> **Cuidado con la interacción entre "Últimos N días" y "Máx. eventos"**:
> el sistema primero trae hasta N eventos y después filtra por
> antigüedad. Si en las últimas horas hubo muchísimos cambios y el cap
> de eventos es bajo, es posible que el filtro por antigüedad no traiga
> eventos "viejos" de días anteriores porque quedaron cortados antes.
> Si sospechás que estás perdiendo eventos viejos, subí "Máx. eventos"
> a 500.

Cada evento se muestra como una fila timeline con toda la información
descripta arriba.

### Tab 2 — 🔎 Por entidad

Te permite consultar el historial completo de una entidad puntual.

- **Selector de tipo**: `Materia`, `Carrera`, `Dictado`, `Sede`.
- **Selector de entidad**: se filtra por tipo. Ejemplo: si elegís
  "Materia", te aparecen todas las materias del sistema.

Al seleccionar una entidad, se muestran hasta **50 eventos** de esa
entidad, ordenados del más reciente al más viejo.

> **Limitación**: si la entidad tiene más de 50 eventos, los más viejos
> quedan truncados sin indicador visual de "hay más". El límite no es
> configurable desde la UI. Para ver eventos más viejos de una entidad,
> hay que consultar directamente la base de datos.

---

## Tareas comunes

### Ver los cambios recientes en el sistema (feed global)

1. Entrá a **📜 Historial**.
2. Quedate en el tab **🌐 Feed global** (viene seleccionado por
   default).
3. Ajustá "Últimos N días" al rango que te interese (por default 30).
4. Si querés más resolución, subí "Máx. eventos" a 500.
5. Scrolleá el feed para ver los eventos.

### Ver el historial completo de una materia / carrera / dictado / sede

1. Entrá a **📜 Historial**.
2. Andá al tab **🔎 Por entidad**.
3. En el selector de tipo, elegí `Materia`, `Carrera`, `Dictado` o
   `Sede`.
4. En el selector de entidad, elegí la entidad específica.
5. Vas a ver hasta 50 eventos.

### Filtrar por tipo de entidad o por origen

En el tab **🌐 Feed global**:

1. Ajustá los filtros "Últimos N días" y "Máx. eventos" para definir la
   ventana.
2. En los multiselect de "Tipo de entidad" y "Origen" que aparecen bajo
   los controles, elegí los que te interesan.
3. El feed se actualiza automáticamente con la selección.

> Ojo: los filtros muestran solo los tipos y orígenes presentes en la
> ventana actual. Si un tipo no aparece en la lista, es porque en los
> últimos N días no hubo eventos de ese tipo (o quedaron cortados por
> el cap de eventos).

### Interpretar un evento

Cada fila del feed tiene:

- **Icono de acción**:
  - ➕ = creación de una entidad.
  - ✏️ = edición de un campo.
  - 🗑️ = borrado de una entidad.
- **Detalle**:
  - Para ediciones: `campo: viejo → nuevo`. Ejemplo:
    `virtual: false → true`.
  - Para creaciones: `**creada**`.
  - Para borrados: `**borrada**`.
- **Timestamp relativo**: "hace 5 min", "hace 3 h", "hace 4 días", o
  fecha absoluta si el evento es más viejo que 30 días.
- **Origen**: entre corchetes, con etiqueta humana ("Ciclos",
  "Validación", "Planes", etc.).
- **Etiqueta de la entidad**: nombre/código de la entidad afectada.
- **Razón**: en cursiva, texto libre que explica el contexto (por
  ejemplo, "Bulk promover: crear-en-regla en 4 materia(s) desde el
  panel de divergencias del ciclo 2026-1C"). Puede estar vacía.

**Ejemplo real**:

```
✏️ Dictado IA1.1-2026-1C
   virtual: false → true
   hace 2 h · [Ciclos]
```

Este evento significa que hace dos horas, alguien marcó el dictado de
"IA 1.1" del ciclo 2026-1C como virtual, desde la página de Ciclos.

**Ejemplo con razón explícita**:

```
✏️ Materia IA 2.3 - Bases de Datos
   dicta_recursado: false → true
   hace 15 min · [Ciclos]
   Bulk promover: crear-en-regla en 4 materia(s) desde el panel de
   divergencias del ciclo 2026-1C
```

Este evento significa que hace 15 minutos, desde el panel de
divergencias del ciclo 2026-1C, se activó el flag `dicta_recursado` de
IA 2.3 como parte de una acción bulk sobre 4 materias.

---

## Errores frecuentes y qué hacer

### Miré el historial y no encuentro el cambio que esperaba

Posibles causas:

- **El cambio no se audita**: revisá la sección "Qué NO se registra"
  arriba. Si es una edición sobre planes, cronogramas, comisiones (a
  menos que sea carrera asignada), horarios (a menos que sea virtual
  desde la grilla del plan), inscriptos o forecast, el historial no
  guarda ese cambio.
- **El campo no está trackeado**: aunque la entidad esté auditada, sólo
  algunos campos específicos generan eventos. Por ejemplo, el nombre y
  el código de una materia no están trackeados.
- **La ventana temporal no lo incluye**: subí "Últimos N días" hasta
  365 si buscás algo viejo.
- **El cap de eventos lo cortó**: subí "Máx. eventos" a 500 y ajustá
  los filtros para reducir el ruido.

### El evento dice "hace 3 h" pero yo lo hice hace unos minutos

Verificá el reloj del servidor. Todos los timestamps se guardan en
**hora UTC**, mientras que Argentina está en UTC-3. Cuando el evento
es reciente, la UI convierte a formato relativo comparando con la hora
UTC actual, por lo que la diferencia horaria no debería afectar. Si
ves un desfasaje mayor a segundos/minutos, capaz que el reloj del
sistema anda mal.

### La página muestra "no hay eventos"

- Verificá que la ventana temporal cubra el período que buscás
  ("Últimos N días").
- Verificá que los filtros por tipo y origen no estén excluyendo todo.
- Si acabás de iniciar el sistema por primera vez, es normal: el
  historial arranca vacío y se llena a medida que se hacen cambios.

### Necesito el historial en un archivo, pero no hay exportar

No hay funcionalidad de exportación desde la UI. Si necesitás llevarte
los datos a Excel u otra herramienta, tenés que consultar directamente
la base de datos (`data/database.db`), tabla `change_log`. Se puede
usar cualquier cliente SQLite (por ejemplo, DB Browser for SQLite).

---

## Preguntas frecuentes

### ¿Se guarda absolutamente todo?

**No**. El historial guarda **catálogo y política**, no **operación**.
En concreto:

- **Sí se guarda**: cambios sobre materias (algunos campos), carreras
  (algunos campos), dictados (algunos campos), sedes (algunos campos),
  vínculos dictado-ciclo, virtualidad de horarios editada desde la
  grilla del plan, carrera asignada de comisiones.
- **No se guarda**: todo lo relacionado con planes de cursada,
  cronogramas, horarios (edición general), comisiones (excepto carrera
  asignada), inscriptos, overrides manuales del forecast, aulas (excepto
  flag default), corridas del asignador, ciclos (creación y edición),
  cambios por script CLI, y algunos campos de materias como el nombre y
  el código.

Si necesitás trazabilidad de operaciones que no están cubiertas, hacé
backup periódico de `data/database.db`.

### ¿Puedo deshacer un cambio desde acá?

**No**. El historial es puramente informativo: no ofrece "revertir".
Si querés volver atrás un cambio, tenés que editarlo manualmente en la
página correspondiente, poniendo el valor viejo a mano.

### ¿Puedo exportar el historial?

**No desde la UI**. La única forma de sacar los datos afuera es
consultando directamente la base de datos (`data/database.db`, tabla
`change_log`) con un cliente SQLite.

### ¿Se puede saber quién hizo el cambio?

**No**. El sistema no tiene login de usuarios; es una app local. Lo
que sí queda registrado es el **origen del cambio**: desde qué página
se hizo (Ciclos, Validación, Planes, etc.) o si fue un cambio
automático de un hook interno. Si querés atribuir cambios a personas
distintas, hoy hay que coordinarlo con un mecanismo externo (por
ejemplo, ponerse de acuerdo en usar el sistema por turnos).

### ¿Por qué hay eventos con origen "auto" y sin razón?

Los eventos con origen `auto` son los que se generan por el mecanismo
automático interno cuando se toca un campo trackeado sin declarar
contexto explícito. Típicamente vienen de las páginas de Materias y
Carreras, que no envuelven sus operaciones en un contexto de auditoría.
No es un problema: significa que el cambio ocurrió, pero no hay
descripción libre de por qué.

### El historial de una entidad se corta en 50 eventos, ¿cómo veo más?

El tab "Por entidad" tiene un límite fijo de 50 eventos por entidad.
No es configurable desde la UI. Alternativas:

- Usar el tab **Feed global** con "Máx. eventos" en 500 y filtrar por
  tipo de entidad + búsqueda visual.
- Consultar la base de datos directamente.

### ¿El historial crece indefinidamente?

Sí. No hay política automática de retención ni de limpieza. La tabla
crece linealmente con el uso del sistema. Como la base es local
(SQLite), en la práctica no es un problema hasta que la tabla se pone
muy grande (decenas de miles de eventos). Si en algún momento hace
falta, hay que hacer un mantenimiento manual desde la base de datos.

### Cambio el nombre de una materia y no queda en el historial, ¿está bien?

Sí, es el comportamiento actual: los campos `nombre`, `codigo` y
`periodo` de las materias no están dentro de la lista de campos
trackeados. Sólo se auditan los flags que impactan a políticas de
asignación (`virtual`, `active`, `dicta_recursado`, `optativa`,
`horas_teoria`, `horas_laboratorio`).

### ¿Aparece "Comisión" o "Horario" en los tipos de entidad?

En el tab **Por entidad** el selector sólo ofrece `Materia`, `Carrera`,
`Dictado` y `Sede`. No aparecen `Comisión` ni `Horario` aunque haya
eventos de esos tipos (los pocos que sí se emiten explícitamente,
como el cambio de "carrera asignada" o virtualidad de horario). Para
verlos, andá al tab **Feed global** y filtrá por tipo de entidad.

---

## Términos importantes de este módulo

- **Registro de cambios**: la tabla completa de eventos que mantiene el
  sistema. Es lo que se muestra en esta página.
- **Evento**: una fila del registro. Corresponde a un cambio puntual
  (creación, edición o borrado) sobre una entidad.
- **Feed global**: vista del tab 1, con los cambios más recientes de
  todo el sistema.
- **Historial por entidad**: vista del tab 2, con los cambios de una
  entidad puntual (materia, carrera, dictado o sede).
- **Origen del cambio**: indica de dónde vino la edición (Ciclos,
  Validación, Planes, o "auto" para hooks automáticos).
- **Razón (reason)**: descripción en texto libre del contexto. Se
  completa en operaciones bulk y en acciones explícitas del usuario;
  puede estar vacía.
- **Etiqueta de la entidad**: nombre humano de la cosa afectada,
  preservado aunque la entidad se borre después.
- **Ventana temporal (últimos N días)**: filtro para acotar la cantidad
  de eventos visibles en el feed global.
- **Cap de eventos (máx. eventos)**: límite superior de resultados en el
  feed global. Por default 100; se puede subir hasta 500.
