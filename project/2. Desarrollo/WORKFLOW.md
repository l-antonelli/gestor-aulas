# Workflow End-to-End del sistema

> **Última actualización**: 2026-06-03
>
> Documento operativo que describe el flujo completo del usuario en
> `gestor-aulas` desde la carga inicial hasta la activación del plan
> de cursada. Sirve como guía de uso y como referencia al describir
> el sistema en el informe.
>
> Vínculos:
> - Modelo de datos: [modelo-planificacion-cursada.md](../1.%20Diseño/modelo-planificacion-cursada.md)
> - Validaciones: [VALIDACIONES.md](VALIDACIONES.md)
> - Concepto de plan de cursada: [plan-de-cursada.md](../0.%20Planteo/plan-de-cursada.md)

---

## 0. Vista panorámica

El sistema tiene **un único flujo lineal** que arranca con la carga
de datos del catálogo y termina con un plan de cursada activado, listo
para que el solver de aulas lo procese.

```
┌─────────────────────┐
│  0. Carga inicial   │  Excel → MateriaDB, CarreraDB, PlanEstudio,
│  (script CLI)       │       MateriaLaboratorioDB, AulaDB
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  1. Ciclo + Plan    │  Crear CicloDB → asignar PlanCarreraVersion
│  Versions           │       → ahora el ciclo "sabe" qué se dicta
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  2. Dictados del    │  Crear DictadoDB para cada materia del ciclo;
│  ciclo              │       toggle activo/inactivo decide qué se
│                     │       espera dictar este cuatri.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  3. Cronograma      │  Cargar Excel con horarios del cuatri;
│                     │       valida contra dictados activos del ciclo;
│                     │       editor in-place para resolver issues.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  4. Generar Plan    │  Wizard de 2 pasos: del cronograma derivar
│                     │       comisiones + horarios estructurados.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  5. Detalle del     │  Por materia: editar horarios/comisiones,
│     Plan            │       peso, override manual de inscriptos
│                     │       esperados, calendario editable.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  6. Validar Plan    │  Cobertura, conflictos, partición teoría/lab,
│                     │       ignorar conflictos puntuales. Snapshot
│                     │       persistido en PlanValidationDB.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  7. Activar Plan    │  Sólo si no hay conflictos NO ignorados;
│                     │       genera ClaseDB (instancias concretas
│                     │       con fecha) para todo el cuatri.
└──────────┬──────────┘
           │
           ▼
┌─────────────────────┐
│  8. (Próximamente)  │  LP de asignación: cada ClaseDB recibe un
│  Asignar Aulas      │       AulaDB respetando capacidad, virtuales,
│                     │       partición teoría/lab, y minimizando
│                     │       cambios de aula entre clases consecutivas.
└─────────────────────┘
```

---

## 1. Carga inicial (CLI)

```bash
python -m scripts.load_initial_data --reset
```

Resetea la DB y carga desde `data/input/`:

- `aulas.xlsx` → `SedeDB("Pellegrini")` (default) + `AulaDB` con
  `sede_id` apuntando a Pellegrini, `codigo_aula` derivado como
  `Pellegrini-AULA-01` y tipo default `"teorica"`. Aulas de otras
  sedes se cargan desde la página `🏛️ Aulas y Sedes` en la UI.
- `materias.xlsx` → `MateriaDB` (código, nombre, hsem, hteo, hlab,
  período, virtual, optativa).
- `materias_carreras.xlsx` → `CarreraDB` + `PlanEstudioDB` (qué
  materia pertenece a qué carrera, año y cuatrimestre).
- `materias_laboratorios.xlsx` → `MateriaLaboratorioDB` (qué
  laboratorios son compatibles con qué materia).

Detalle completo: [CARGA_DATOS_INICIALES.md](CARGA_DATOS_INICIALES.md).

> Tras reset, **se debe recrear** desde la UI: nombres de carrera,
> ciclos, dictados, cronogramas y planes de cursada (no se persisten
> en los Excel de entrada).

---

## 2. Ciclo + Plan Versions (📆 Ciclos)

### 2.1 Crear el ciclo

`📆 Ciclos → Lista → Crear ciclo nuevo`. Atributos:

- `id` (ej. `2026-1C`)
- `anio`, `numero` (1 ó 2)
- `fecha_inicio`, `fecha_fin` (rango del cuatri)

### 2.2 Asignar versiones de plan

Cada carrera tiene una o más `PlanCarreraVersionDB` (planes de
estudio versionados). Para que un ciclo "sepa" qué materias se
ofrecen, hay que crear `CicloPlanVersionDB` (uno por carrera que
participa).

Esto se gestiona desde `📆 Ciclos → Versiones de plan` y permite:
- Cambiar la plan version asignada a una carrera para un ciclo
  puntual (`swap_plan_version_for_ciclo`).
- Que distintas carreras del mismo ciclo apunten a distintas
  versiones.

---

## 3. Dictados del ciclo (📆 Ciclos → 📚 Dictados)

Los `DictadoDB` representan **qué materia se dicta y cómo en este
ciclo concreto**. Crear dictados es necesario antes de cargar
cronogramas y planes — sin dictados no hay set de "materias
esperadas" contra el cual validar.

### 3.1 Crear los dictados

Botón **"Crear dictados"**: para cada materia del plan asignado al
ciclo, crea un `DictadoDB` con:

- `dictado_codigo` (`{materia}-{ciclo.anio}-{numero}C` para
  cuatrimestral; `{materia}-{ciclo.anio}` para anual).
- `activo`: por default `True`, salvo que la materia tenga
  `dicta_recursado=False` (override por carrera o por materia)
  o que sea anual y este sea el 2C (linkea a la versión del 1C).

### 3.2 Toggle activo/inactivo (con edición a mano)

Cada fila de la grilla de dictados tiene un toggle "Activo".
**Activo = la materia es esperada este cuatri**. Inactivo = la
materia NO se considera para validaciones de cobertura.

**Auto-save + marca de edición a mano**: cuando el usuario cambia el
toggle, el cambio se persiste inmediatamente en `DictadoDB.activo`
y además queda registrado en `DictadoDB.activo_override_manual` (con
el mismo valor) como marca de "esto lo editó el usuario". El
indicador 🟢/⚪ a la izquierda del nombre se actualiza al instante,
y aparece la etiqueta **✋ editado a mano** que lo deja explícito.

**Por qué importa la marca**: la próxima ejecución de "Recalcular
según reglas" **respeta las ediciones manuales por default** (no las
toca). De esta manera el usuario puede desactivar materias comodín
o sumar excepciones puntuales sin que la regla se las pise.

**Cómo quitar una edición manual**: cada fila marcada muestra un
botón "Quitar edición manual" debajo del toggle. Al apretarlo se
borra la marca (`activo_override_manual` vuelve a `None`) sin tocar
el estado actual de `activo`. La próxima recalculación vuelve a
evaluar la regla para ese dictado.

> **Source of truth**: el `DictadoDB.activo` sigue siendo la fuente
> para "qué materias se esperan en el cuatri". El campo
> `activo_override_manual` sólo afecta cómo se comporta "Recalcular
> según reglas" frente a esa entrada.

### 3.3 Recalcular según reglas

Botón que aplica las reglas de `dicta_recursado` (más los flags
overrideables por carrera y por materia) a todos los dictados
existentes y reporta los cambios pendientes sin aplicarlos hasta que
el usuario confirme.

El **detalle del preview** muestra para cada cambio:
- Materia (código + nombre completo).
- Carrera (o "Compartida" cuando aplica).
- Año/cuatrimestre del plan donde figura.
- Estado actual → estado nuevo.
- **Razón** legible del cambio (ej. "Carrera FBA no dicta recursado
  y la materia es del 2C; este ciclo es 1C → inactiva").

**Tres secciones en el preview**: 🟢 Pasarán a Activo, ⚪ Pasarán a
Inactivo, ✋ Editados a mano (respetados) — estos últimos son los
que el modo default no toca porque tienen
`activo_override_manual` seteado.

**Toggle "Pisar también las ediciones manuales"** (default OFF):
cuando está activo, las ediciones manuales se descartan y la regla
se aplica a todo. Útil cuando se acumularon muchas ediciones
obsoletas y se quiere limpiar el estado del ciclo.

---

## 4. Cronograma (📅 Cronogramas)

El cronograma es el **input principal de horarios**: una snapshot
del Excel que llega desde la facultad con la oferta horaria del
cuatri. Múltiples cronogramas por ciclo (versiones de borrador,
copias para experimentar).

### 4.1 📤 Cargar

Sube un Excel `.xlsx` con columnas: `materia | día | inicio | fin |
comisión (opcional)`. Se valida la estructura y se persiste como un
`ScheduleDB` con `ScheduleEntryDB` por fila.

### 4.2 📋 Lista

Lista todos los cronogramas con:
- Badge de validación (sin validar / validado / con issues / stale).
- Acciones: duplicar, eliminar, abrir en editar/validar.

### 4.3 👁 Visualizar

Calendario semanal read-only con todos los entries del cronograma.

### 4.4 ✏️ Editar

Editor full-featured (drag/click/select) sobre `ScheduleEntryDB`:

- **Modo "Por grupo"**: filtros Carrera/Año/Cuatri/Tipo de materia
  (Ciclo Básico/Específicas) + checkbox "Excluir comunes" +
  multiselect de materias a mostrar.
- **Modo "Por materia"**: búsqueda de materia + calendario filtrado
  + tabla `data_editor` con auto-save de Día/Inicio/Fin/Comisión/
  Tipo (sin determinar / teorica / laboratorio) + resumen por
  comisión.
- **Calendario editable**: drag → mover, resize → cambiar duración,
  click → editar (dialog con materia/día/inicio/fin/comisión/tipo
  + Eliminar/Cancelar), drag sobre celdas vacías → agregar
  entrada (requiere materia activa).

### 4.5 ✅ Validar (panel unificado)

Esta es la pestaña central del cronograma. Reusa el módulo
`validation_ui.render_validation(source='schedule', ...)` que también
sirve al panel del plan.

#### Estructura

1. **Toggle "Excluir optativas"** + **toggle "Auto-revalidar al
   cambiar"** + **botón "Validar cronograma"**.
2. **Toggle "Guardar cambios como copia del cronograma"** (opcional):
   cuando está activo, cualquier edición desde el panel se aplica a
   una copia del cronograma en lugar del original.
3. **Resumen de cobertura**: 6 métricas (Materias, Clases, Horas,
   Esperadas, Cubiertas, Faltantes).
4. **Lab breakdown**: 4 métricas (Con lab asignado, Lab fijo,
   Reserva ad-hoc, Pendiente).
5. **Partición teoría/lab**: success/error global.
6. **Detalle por carrera** (expander):
   - Tabla resumen con totales (Faltantes / No esperadas /
     Conflictos / Ignorados — este último solo plan).
   - Sub-expanders por carrera con discrepancias de dictado y
     conflictos de horarios; bulk-action de activar/desactivar
     dictados desde aquí mismo.
7. **Detalle por materia** (expander):
   - Filtros: búsqueda, Carrera (multiselect, soporta materias
     comunes), Año, Cuatri, Estado (OK/Faltante/No esperada/
     Conflictiva/Sin datos), Tipo (carreras: Comunes/Exclusivas),
     Atributos (Optativa/Virtual/Anual/Con lab/etc), toggle "Solo
     con alertas".
   - Tabla resumen por carrera (sobre el set filtrado) con counts
     por estado.
   - Tabla compacta de materias.
   - **Loop paginado de expanders** (10/página) — cada materia con
     ícono dinámico según su worst-status, header con sufijo de
     modo lab (🧪 fijo / ℹ️ reserva / ⚠️ pendiente). Botones
     "Abrir todas / Cerrar todas" sobre la página actual.
   - Cada expander rendea el `schedule_materia_editor` completo:
     calendario editable filtrado a la materia, controles de
     hsem/hteo/hlab, selector de comisiones + reasignar, data_editor
     con todos los entries, **10 chequeos estructurados** con tildes
     y, cuando aplica, el check `materia_faltante` (cuando la
     materia tiene dictado activo pero 0 entries — alineado con el
     badge 📭 de la tabla).

> Para el detalle completo de los 10 checks ver
> [VALIDACIONES.md](VALIDACIONES.md#4-validaciones-inline-del-editor-por-materia-cronograma).

---

## 5. Generar Plan (📊 Planes → Generar plan)

Wizard de 2 pasos para producir un `PlanificacionCursadaDB` a partir
de un cronograma validado.

### 5.1 Paso 1 — Selección

- Ciclo + Cronograma + nombre/descripción del plan.
- Método de forecast default (media móvil / drift / SES).
- El plan se crea inmediatamente como **borrador** (`activo=False`),
  con todas las comisiones y horarios derivados del cronograma.

### 5.2 Paso 2 — Edición previa

Embebe el editor del tab "Detalle del Plan" (sección 6) para que el
usuario haga los ajustes que quiera antes de salir del wizard.
Cancelar = borra el plan en cascada. Confirmar = sale del modo
wizard y deja el plan como borrador.

---

## 6. Detalle del Plan (📊 Planes → Detalle)

Editor central del plan. Selector de plan (uno o varios por ciclo)
+ las siguientes secciones por plan:

### 6.1 Metadata

Nombre, descripción y método de forecast default. Auto-save.

### 6.2 Estadísticas

5 métricas: Materias, Comisiones, Horarios, Clases, Con Aula.

### 6.3 Validaciones (panel unificado)

Mismo módulo `validation_ui.render_validation(source='plan', ...)`
con todas las features del cronograma + extras del plan:

- **Conflictos de horarios** del plan (sobre comisiones reales,
  vía `validar_conflictos_horarios_plan_estructurados`).
- **Ignorar conflictos** puntuales (`IgnoredConflictDB`): un par
  ignorado no bloquea la activación. Se persiste por (plan, par
  lex-ordenado) y sobrevive aunque cambien los horarios.
- **Snapshot persistido** en `PlanValidationDB` con detalle JSON
  para reconstrucción sin recomputar; staleness automático cuando
  cambia algo (entries, comisiones, horarios, dictados, toggle).
- **Activación gate**: botón "Activar plan" deshabilitado si hay
  conflictos no ignorados; al activar genera `ClaseDB` para todo
  el cuatri.

#### Detalle por materia → editor inline (`plan_materia_editor`)

Cada expander del loop paginado abre el editor completo de la
materia, con esta estructura:

1. **📚 Catálogo de horas**: hsem / hteo / hlab editables con
   auto-save y validación cruzada (`hteo + hlab == hsem`).
   Período read-only.
2. **🗓️ Calendario editable**: drag/click/select sobre los
   `HorarioDB` de la materia, con dialogs adaptados (selector de
   comisión existente o `➕ Nueva comisión` que se crea al vuelo;
   selector de tipo de clase).
3. **✏️ Edición masiva de horarios** (`data_editor`): tabla con
   todos los horarios + Día/Inicio/Fin/Comisión/Tipo, auto-save al
   cambiar.
4. **👥 Inscriptos esperados**:
   - **Peso total** (suma de `coef_asignacion` de las comisiones,
     debe ser ≈1.0) + botón "Normalizar" que reparte 1/n.
   - **Total esperado (manual)**: input numérico para forzar el
     valor de inscriptos esperados de la materia, sobreescribiendo
     el forecast histórico. Persiste en
     `MateriaForecastConfigDB.valor_override`. Botón "Quitar
     manual" para volver al forecast.
   - **Forecast (automático)**: muestra el valor calculado desde
     la serie histórica + método (`Default plan` o override
     puntual). El selector de método override solo aparece cuando
     no hay valor manual seteado.
5. **🎓 Comisiones** (loop, una por expander):
   - Header del expander: `nombre · #N · peso X · esperados Y · ⚠️ partición infactible (si aplica)`.
   - Cuerpo: nombre / **peso** (antes "Coef") / esperados
     (read-only, calculado como `total_esperado × peso`) +
     listado de horarios con borrar inline + popover "Agregar
     horario" + botón "Eliminar comisión".
6. **✅ Validaciones**: los 10 chequeos estructurados (mismos
   `_compute_checks` que el editor del cronograma).

> El **cupo** del modelo se mantiene en DB con default 30 (o el
> cupo de catálogo de la materia) pero **no se edita más en el
> UI** — ya no era usado funcionalmente.

---

## 7. Grilla horaria del plan (📊 Planes → Grilla horaria)

Editor del plan a nivel global, espejo de Cronogramas → Editar pero
sobre `ComisionDB` + `HorarioDB`:

- Modo "Por grupo" (filtros Carrera/Año/Cuatri/Tipo + Excluir
  comunes + Materias a mostrar).
- Modo "Por materia" (búsqueda + calendario + data_editor).
- Calendario editable con drag/resize/click/select.
- Dialogs con selector de comisión (existente o nueva) + tipo.

Útil para detectar y resolver conflictos del mismo cuatri/carrera
en una sola vista.

---

## 8. Activación

Cuando el plan no tiene conflictos no-ignorados y el usuario aprieta
**"Activar plan"** desde el panel de validación:

1. Se invoca `activate_plan(session, plan_id)`.
2. Se desactivan todos los demás planes del mismo ciclo (solo 1
   activo por ciclo).
3. Se genera `ClaseDB` para cada `HorarioDB` × cada fecha del ciclo
   donde aplique (`generate_clases_for_plan`):
   - Para cada `HorarioDB(comision=C, dia=Lunes, 8-10)` y cada
     fecha del ciclo cuyo `weekday()` coincida con "Lunes", se
     crea una `ClaseDB(comision_id=C.id, fecha=…, hora_inicio=8,
     hora_fin=10, aula_id=None)`.
   - Materias anuales heredan ambas mitades (1C + 2C).
   - Las virtuales **se generan también** (la asignación de aula
     posterior las saltea, pero se necesitan en la planificación
     general).

El plan queda con `activo=True` y aparece como `[ACTIVO]` en la
lista. Las clases generadas son visibles en
`📊 Planes → Clases`.

---

## 9. Estado actual (qué está implementado)

✅ Pasos 0 a 8 + **LP de asignación de aulas (fases 1 a 8)**.

El LP corre sobre la "semana modelo" (variables por `HorarioDB`,
propagación a `ClaseDB` con `fecha ≥ fecha_desde`) y cubre:

- R1 asignación única, R3 compatibilidad por tipo, R4 no doble
  booking vía grupos de simultaneidad, R5 partición teoría/lab,
  R6 consistencia tipo↔aula, R7 penalty lineal asimétrico.
- Re-run incremental con flag `aula_asignada_manualmente` y toggle
  "respetar ediciones manuales" / "sobreescribir todo".
- Diagnóstico estructural de infactibilidad antes y después del
  solve (horarios sin aula compatible, franjas saturadas,
  particiones teoría/lab infactibles) + heatmap día×franja.
- Detalle del resultado coloreado + candidatas a partir comisión.
- Vista cronograma por aula con selector de semana.
- Edición manual de aula con dialog de tres modos (puntual /
  rango / desde hoy) y validación pre-confirmación.
- Toggle α opcional para que el LP redistribuya
  `coef_asignacion` entre comisiones del mismo dictado (R9), con
  diff visual y persistencia bajo confirmación.

Detalle completo de la implementación:
[`ASIGNACION_IMPL.md`](ASIGNACION_IMPL.md).

---

## 10. Mapa de páginas Streamlit

| Página | Tabs principales |
|---|---|
| `0_🏠_Home.py` | Landing |
| `1_📚_Materias.py` | CRUD Materias / Laboratorios |
| `2_🏛️_Aulas.py` | CRUD Aulas |
| `3_🎓_Carreras.py` | CRUD Carreras + plan versions |
| `4_📆_Ciclos.py` | Lista, Crear, Plan versions, **📚 Dictados** |
| `5_📊_Planes.py` | **Generar plan**, **Detalle**, **Grilla horaria**, Clases, **🏛️ Aulas** (LP), Config |
| `6_📅_Cronogramas.py` | Lista, **Cargar**, Visualizar, **Editar**, **Validar** |
| `7_📝_Inscriptos.py` | Carga histórica de inscriptos por materia/cuatri |

---

## 11. Convenciones de UI

- **Toggle "Auto-revalidar al cambiar"**: activo por default en
  los paneles de validación. Cualquier acción del panel (dialogs,
  bulk-actions, calendario editable, data_editor) marca un flag
  pending; al final del render se compara fingerprint vivo (DB) vs
  snapshot del summary cacheado y, si difieren, se dispara
  `validar_*` automáticamente con un toast.
- **Estado por materia (badges)**: ✅ OK, 📭 Faltante, 📥 No
  esperada, ⚠️ Conflictiva, ❓ Sin datos. La columna `Carrera`
  muestra `(+N)` cuando la materia es común a varias.
- **Filtro de carrera**: una materia común matchea si pertenece a
  cualquiera de las carreras seleccionadas (intersección no-vacía
  con su `carreras_set`).
- **Worst-status del expander**: el icono del header de cada
  materia refleja el peor de los 10 checks del editor (priority:
  faltante > error > warn > info > ok), cacheado en session_state
  y refrescado tras cada edición.

---

## 12. Decisiones operativas relevantes

1. **Fuente de verdad de horarios**: el `cronograma` es el
   "boceto" que llega de la facultad; el `plan` es el "plano
   ejecutivo" editable. Los conflictos del cronograma se resuelven
   editando el cronograma (o haciendo una copia); los conflictos
   del plan se pueden ignorar puntualmente.
2. **Multi-carrera y comunes**: una materia compartida entre
   varias carreras existe como un único `MateriaDB`, pero aparece
   en varios `PlanEstudioDB`. La UI respeta esto en filtros y
   counts (cada materia común suma en cada carrera donde
   pertenece).
3. **Override manual de inscriptos esperados**: cuando no hay
   serie histórica o el usuario tiene info externa
   (preinscripción), puede forzar el valor en
   `MateriaForecastConfigDB.valor_override`. Se persiste por
   (plan, materia, cuatri).
4. **Período de la materia (anual/cuatrimestral)**: las anuales
   se dictan en 1C y 2C; los `DictadoDB` anuales se crean en 1C y
   se linkean en 2C (un único dictado, dos `DictadoCicloDB`).

---

## 13. Próximos pasos (LP de asignación)

Por separado, en otro documento, vamos a plantear:

1. **Variables de decisión**: una por cada `(ClaseDB, AulaDB)`
   compatible.
2. **Restricciones**:
   - Cada `ClaseDB` no virtual recibe **exactamente un** aula.
   - Una misma `(aula, fecha, slot horario)` admite **a lo sumo
     una** clase.
   - Capacidad del aula ≥ inscriptos esperados de la comisión.
   - Compatibilidad de tipo (lab/teórica) cuando aplica.
   - Partición teoría/lab por comisión.
3. **Objetivo**: minimizar la suma ponderada de:
   - Cambios de aula entre clases consecutivas de la misma comisión.
   - Sobre-capacidad (penalización suave si la asignación se ajusta).
   - (Otras heurísticas a definir.)
4. **Implementación**: PuLP / OR-Tools, integración via
   `src/services/asignacion_service.py` (no creado aún), ejecución
   bajo demanda desde la UI con feedback de progreso y un report
   final.
