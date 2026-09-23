# Auditoría del importer masivo — 2026-09-23

> **Alcance**: los tres commits del 2026-09-23 — `6b21c1f` (chequeos
> inline en Ver/Editar), `391677b` (selector de hoja + toast + estado
> Revisión) y `b8dd639` (preview per-materia con Antes/Después).
> 1981 líneas agregadas sobre 13 archivos.
>
> **Método**: seis auditorías paralelas por área, con verificación
> empírica de cada hallazgo accionable. Los resultados marcados
> *(medido)* se reprodujeron ejecutando código contra bases de datos
> sintéticas o contra `data/database.db`; no son análisis estático.
>
> **Estado de la suite al momento de auditar**: 1376 tests pasan, 19
> fallan. Los 19 son el conjunto histórico de la suite del asignador
> (`test_asignacion_aulas_service.py`, `test_lp_grupos_r14.py`),
> idéntico al de antes de estos commits. Los ocho archivos de páginas
> y los diez módulos tocados importan sin error.

---

## 1. Resumen ejecutivo

La auditoría encontró **tres regresiones introducidas por estos
commits que producen pérdida de datos o rotura funcional silenciosa**,
más un problema de rendimiento que vuelve impracticable el preview con
archivos grandes. Todas se verificaron ejecutando el código.

El patrón común de las tres regresiones es el mismo: **el sistema hace
algo destructivo o incorrecto y le informa al usuario que no pasó
nada**. Esa combinación es la más costosa de todas, porque el usuario
no tiene señal de que deba revisar.

| # | Hallazgo | Sev. | Origen |
|---|---|---|---|
| H1 | Se destruye la configuración manual de las comisiones y el toast reporta "sin cambio" | 🔴 | Regresión de hoy |
| H2 | El selector de hoja rompe archivos que antes importaban bien | 🔴 | Regresión de hoy |
| H3 | La decisión `agregar` descarta el archivo en silencio | 🔴 | Regresión de hoy |
| H4 | El preview tarda ~8-10 s por interacción con archivos grandes | 🔴 | Introducido hoy |
| H5 | Una materia del archivo puede desaparecer del listado | 🔴 | Introducido hoy |
| H6 | Doble conteo en "Resumen por carrera" | 🔴 | Preexistente |
| H7 | Los contadores del toast mienten con filas duplicadas | 🟡 | Introducido hoy |
| H8 | Tres definiciones incompatibles de "cuántas comisiones tiene esta materia" | 🟡 | Amplificado hoy |
| H9 | Dos códigos que resuelven a la misma materia se pisan entre sí | 🟡 | Regresión de hoy |
| H10 | La regeneración no es atómica: puede dejar comisiones huérfanas | 🟡 | Introducido hoy |
| H11 | La decisión que muestra la pantalla puede no ser la que tiene el shadow | 🟡 | Introducido hoy |
| H12 | Textos de la interfaz que contradicen el comportamiento actual | 🟡 | Introducido hoy |
| H13 | Limpieza asimétrica del estado de sesión y shadows abandonados | 🟡 | Introducido hoy |
| H14 | El resumen del set filtrado desaparece cuando el filtro no matchea | 🟡 | Regresión de hoy |
| H15 | `restrict_materias` quedó sin consumidores | 🟡 | Introducido hoy |
| H16 | Huecos de cobertura en las categorías centrales de lo nuevo | 🟡 | — |
| H17 | Drift de documentación en cuatro documentos | 🟡 | — |
| H18 | `color_by_comision` no tiene efecto | 🟢 | Preexistente |

---

## 2. Regresiones con pérdida de datos o rotura silenciosa

### H1 🔴 Se destruye la configuración manual de las comisiones y se reporta "sin cambio"

**Ubicación**: `src/services/cronograma_import_service.py:631-636` (el
default) → `:343-353` (`commit_import`) → `:416-419`
(`_agregar_comisiones_nuevas`).

Con la decisión `reemplazar` — que desde hoy es el **default** —
`_borrar_entries_y_comisiones_de_materia` borra las `ComisionDB` del
destino y `create_comision_for_schedule` las recrea desde cero con los
valores por omisión del catálogo. Todo lo que el usuario haya
configurado a mano en la comisión se pierde, y el archivo Excel no
contiene ninguno de esos campos, así que no hay forma de restituirlos.

Medido, con un archivo que trae la misma comisión y el mismo horario
que ya estaban en el destino (es decir: un import donde objetivamente
no cambia nada):

```
antes:   cupo=123  coef_asignacion=0.6  descripcion='Turno mañana…'  carrera_asignada='I'
después: cupo=30   coef_asignacion=1.0  descripcion=''               carrera_asignada=None
toast:   agregadas=0  eliminadas=0  sin_cambio=1
```

`carrera_asignada` es el override de sede del asignador (RF-LP-15), así
que su pérdida cambia el resultado del programa lineal sin ninguna
señal.

Conviene notar que el default anterior (`agregar`) no tenía este
problema: la comisión homónima colisionaba, se salteaba y sobrevivía
intacta. El cambio de default de la task #359 abrió el agujero.

**Corrección sugerida**: en modo `reemplazar`, borrar únicamente las
*entries* y reutilizar la `ComisionDB` existente cuando el nombre
canónico coincide, eliminando sólo las comisiones que quedan sin
entries. Alternativa: tomar una instantánea de
`{nombre_canónico: (cupo, descripcion, coef_asignacion, carrera_asignada)}`
antes de borrar y reinyectarla al recrear.

---

### H2 🔴 El selector de hoja rompe archivos que antes importaban bien

**Ubicación**: `app/pages/6_📅_Cronogramas.py:731-737` y
`app/pages/7_📈_Inscriptos.py:392-401`.

El `st.selectbox` se instancia sin `index=`, de modo que su valor
inicial es siempre la **primera hoja visible del libro**. Antes de
estos commits, `sheet_name=None` hacía que el parser prefiriera
explícitamente la hoja `Horarios` (o `Inscriptos`) sin importar su
posición. Ahora la interfaz manda un `sheet_name` explícito que gana
sobre esa preferencia.

Medido, con la plantilla que genera el propio sistema más una hoja
"Resumen" agregada por el usuario antes de "Horarios":

```
list_horarios_sheets       → ['Resumen', 'Horarios']
el selectbox arranca en    → 'Resumen'
con lo que elige la UI     → 0 horarios, ['Columnas faltantes: codigo_materia, dia, hora_fin, hora_inicio']
con el fallback anterior   → 1 horario, sin errores
```

El usuario ve un error de columnas faltantes sobre un archivo que está
perfectamente bien formado.

**Corrección sugerida**: calcular el índice inicial con la misma
preferencia que aplica el parser, y exponer esa preferencia como
constante del servicio (`HOJA_PREFERIDA`) para que interfaz y parser no
puedan volver a divergir.

---

### H3 🔴 La decisión `agregar` descarta el archivo en silencio

**Ubicación**: `src/services/cronograma_import_service.py:896-903`
(se ignora el `ImportResult`) → `:404-414` (donde se generan los
errores).

`commit_import` no levanta excepción cuando el nombre de comisión
colisiona: acumula el mensaje en `ImportResult.errors` y continúa.
`regenerar_materia_en_shadow` devuelve `None` y descarta ese resultado.
La interfaz sólo captura `ValueError`, así que no hay nada que mostrar.

El caso que lo dispara no es marginal, es **el caso típico**: el
archivo es la versión actualizada de la misma cátedra, con la misma
comisión "1". Medido:

```
shadow con default 'reemplazar':  Viernes 15:00-18:00  (la del archivo)
usuario cambia el radio a 'agregar'
shadow después:                   Lunes 08:00-11:00    (sólo la del destino)
excepción levantada:              ninguna
```

El horario del archivo se perdió, la columna "Después" quedó idéntica a
"Antes", el radio dice `agregar`, y no apareció ni una advertencia.

**Corrección sugerida**: que `regenerar_materia_en_shadow` devuelva el
`ImportResult` y que la interfaz persista `result.errors` en el estado
de sesión para mostrarlos después del rerun (un `st.error` emitido
antes del `st.rerun()` se pierde).

---

### H5 🔴 Una materia del archivo puede desaparecer del listado

**Ubicación**: `app/pages/6_📅_Cronogramas.py:996-1001`.

El listado se deriva de la base de datos:
`_materias_del_archivo = _mats_con_prev | (_all_mat_shadow - _all_mat_dest)`.
Una materia cuyo import falló por colisión de nombre y que no tiene
entries en el destino no cae en ninguno de los dos conjuntos: no está
en `_mats_con_prev` (no tenía entries previas) ni en la diferencia (no
se creó ninguna entry). La materia se evapora del listado.

La pantalla queda autocontradictoria: las métricas de arriba dicen
"Materias del archivo: 1" y el cuerpo dice "El archivo no aportó
materias reconocibles al preview".

**Corrección sugerida**: no derivar el listado de la base de datos.
Guardar `[m.materia_codigo for m in _preview.materias]` en el resumen
del preview y usar eso como fuente de verdad.

---

## 3. Rendimiento

### H4 🔴 El preview tarda entre 8 y 10 segundos por interacción

**Ubicación**: `app/pages/6_📅_Cronogramas.py:1212-1215` y `:1242-1245`,
dentro del `for _mc in _materias_del_archivo`.

`build_schedule_grid` no filtra por materia: carga todas las entries
del cronograma, resuelve nombres, arma todos los `ScheduleBlock` y
ordena. El filtrado por materia se hace después, en Python. Se la llama
**dos veces por materia**, con sesión nueva cada vez.

Medido contra `data/database.db` (cronograma de 634 entries, 248
materias):

| Operación | Costo unitario | Total en el loop |
|---|---|---|
| `build_schedule_grid` | 46 ms | 496 llamadas → **~8 s** |
| `compute_materia_checks_from_db` | 7 ms | 248 llamadas → ~1,7 s |

A eso se suma que Streamlit reejecuta el script completo en cada
interacción — cada cambio de radio, cada apertura de expander — y que
se instancian dos componentes `streamlit_calendar` por materia, cada
uno un `iframe` con el paquete de FullCalendar.

**Corrección sugerida**, por orden de impacto:

1. Construir las dos grillas **una sola vez** antes del loop,
   agruparlas por materia e indexar dentro del loop. Reduce 496
   llamadas a 2 (~8 s → ~90 ms).
2. Eliminar la segunda sesión de `_derive_n_comisiones`: el `com_map`
   que el llamador ya tiene contiene ese dato.
3. Renderizar los calendarios sólo cuando el usuario los pide
   (un `st.toggle` "Ver Antes/Después" por materia), o paginar el
   listado reusando el patrón que ya existe en `validation_ui`.

---

## 4. Aritmética y consistencia

### H6 🔴 Doble conteo en "Resumen por carrera" *(preexistente)*

**Ubicación**: `src/ui/validation_ui.py:2336-2345`.

`_filtered` tiene una fila por ubicación curricular, pero el campo
`carreras_set` de cada fila contiene el conjunto **completo** de
carreras de la materia. El loop incrementa el contador de cada carrera
por cada fila, de modo que una materia común a dos carreras se cuenta
dos veces en ambas. Medido:

```
materias reales:  A = {M1, M2} = 2      B = {M1} = 1
la tabla muestra: A = 3                 B = 2
```

El factor de inflación es la cantidad de ubicaciones curriculares de
cada materia común.

En el mismo bloque, la fila `**Total (únicas)**` usa `len(_filtered)`,
que cuenta filas, no materias distintas — de modo que el rótulo
"(únicas)" y el texto explicativo que lo acompaña afirman algo que el
código no hace. La función ya tiene el número correcto calculado en
`_n_mat_visibles`, así que la métrica "Mostrando" y la fila del total
muestran números distintos en la misma pantalla.

**Corrección sugerida**: deduplicar por `(carrera, código)` antes de
contar, y calcular la fila del total sobre códigos únicos. Conviene
extraer ambos cálculos a funciones de módulo y escribir primero los
tests que reproducen el doble conteo: hoy ese bloque no es testeable
porque está embebido en una función de 875 líneas que abre sesiones y
renderiza widgets.

---

### H7 🟡 Los contadores del toast mienten con filas duplicadas

**Ubicación**: `src/services/cronograma_import_service.py:795-809`.

`_fingerprint_entries` devuelve un `set`, de modo que dos entries con
fingerprint idéntico colapsan en una. Eso rompe los contadores en las
dos direcciones. Medido:

```
(a) archivo con 3 filas idénticas
    entries insertadas: 3     toast: agregadas=1, finales=3
    invariante agregadas+sin_cambio == finales:  FALSA

(b) destino con 2 entries idénticas, archivo trae 1
    toast: previas=2  finales=1  agregadas=0  eliminadas=0  sin_cambio=1
    se borró una entry real y el toast informa cero eliminadas
```

El caso (b) es particularmente incómodo porque el commit se titula
"toast honesto" y es justamente el escenario donde no lo es. Una fila
pegada dos veces en el Excel de una cátedra alcanza para disparar (a).

**Corrección sugerida**: usar `collections.Counter` en lugar de `set` y
hacer aritmética de multiconjuntos. Con eso las invariantes
`agregadas + sin_cambio == finales` y `eliminadas + sin_cambio == previas`
se cumplen siempre y se pueden fijar con un test.

---

### H8 🟡 Tres definiciones incompatibles de "cuántas comisiones tiene esta materia"

**Ubicación**: `src/ui/schedule_materia_editor.py:1148` y `:889-907`
frente a `src/ui/validation_ui.py:1978`.

| Consumidor | Fórmula |
|---|---|
| Panel Validar | `len({comision_id distintos})` |
| `compute_materia_checks_from_db` | `max(max(ComisionDB.numero), paralelas, 1)` |
| Editor por materia | valor del `number_input`, con la fórmula anterior como valor inicial |

El helper usa el **máximo número** de comisión, no la **cantidad**. Con
una numeración que tiene huecos —lo que ocurre en cuanto el usuario
borra una comisión del medio, algo que la tabla de comisiones del
propio tab Ver/Editar permite— los dos paneles emiten veredictos
opuestos. Medido, con dos comisiones reales numeradas 1 y 3:

```
helper:        n_comisiones=3  estado=Revisión
               [warn] h/sem × comisiones: 3h × 3 = 9h, pero hay 6h
               [warn] Sin comisiones vacías: Comisión 2 sin clases
panel Validar: n_coms=2  sin mismatch  estado=OK
```

De esta misma raíz se desprenden tres consecuencias más: el chequeo
"Clases paralelas ≤ comisiones" es estructuralmente incapaz de fallar
en el helper (porque `paralelas` participa del cálculo de `n_com`); las
entries sin comisión asignada se acumulan todas en la comisión 1,
contradiciendo la fila "Sin asignar" que aparece cincuenta líneas más
arriba en la misma pantalla; y un `comision_id` que apunta a otro
cronograma infla `n_com` sin aportar horas.

**Corrección sugerida**: una única función que derive el contexto de
comisiones de un `(cronograma, materia)` —cantidad, opciones, horas por
comisión y entries sin asignar— consumida por los tres lugares. Es la
unificación que el commit `6b21c1f` se propuso: unificó el *render* de
los chequeos pero dejó tres cálculos distintos de sus *insumos*.

---

### H9 🟡 Dos códigos que resuelven a la misma materia se pisan entre sí

**Ubicación**: `src/services/cronograma_import_service.py:330-353` y
`:891-896`.

`preview_import` agrupa por el código **original** del archivo y
resuelve después. Si el archivo trae el mismo dictado dos veces —una
por código de plan y otra por código Guaraní— quedan dos
`MateriaEnPreview` con el mismo `materia_codigo`. Con `reemplazar`, la
segunda iteración borra lo que creó la primera y sólo sobrevive el
último grupo. Con el default anterior esto no borraba nada, de modo que
es otra regresión del cambio de default.

**Corrección sugerida**: consolidar por código resuelto en
`preview_import`. Como mínimo, un guard en `commit_import` que levante
`ValueError` si hay códigos resueltos repetidos.

---

## 5. Robustez del flujo

### H10 🟡 La regeneración no es atómica

**Ubicación**: `src/services/comision_service.py:127`
(`session.commit()` dentro de `create_comision_for_schedule`),
consumido desde `cronograma_import_service.py:416`.

`finalizar_shadow_import` **sí** es atómico (un único commit, sin pasar
por `create_comision_for_schedule`), de modo que el cronograma destino
nunca queda a medio escribir. El problema está en la regeneración: el
primer `create_comision_for_schedule` confirma el borrado del estado
previo de la materia, así que un fallo posterior deja la materia con
cero entries y comisiones huérfanas. Como SQLite corre sin
`PRAGMA foreign_keys`, nada lo impide, y si el usuario confirma,
`finalizar_shadow_import` copia esas comisiones vacías al destino.

**Corrección sugerida**: una variante de
`create_comision_for_schedule` que haga `flush()` en lugar de
`commit()`, de modo que toda la regeneración quede en una sola
transacción.

---

### H11 🟡 La decisión que muestra la pantalla puede no ser la del shadow

**Ubicación**: `app/pages/6_📅_Cronogramas.py:1178-1198`.

`_decisiones_map[_mc] = _new_dec` se ejecuta **antes** de llamar a
`regenerar_materia_en_shadow`. Si la regeneración falla, o si no hay
bytes del archivo en el estado de sesión (caso en que no se hace nada
ni se avisa), la decisión queda guardada sin haberse aplicado. Y como
no hay rerun en esos caminos, en la siguiente ejecución
`_new_dec == _decision_actual`, no se reintenta y el mensaje de error
desaparece. El botón Confirmar persiste lo que el shadow tiene, no lo
que el radio muestra.

**Corrección sugerida**: mover la escritura del mapa a después del
éxito, y hacer explícito el caso "se perdieron los bytes del archivo".

---

### H13 🟡 Limpieza asimétrica del estado y shadows abandonados

**Ubicación**: `app/pages/6_📅_Cronogramas.py:845-891`, `:904-909`,
`:810-815`.

Hay cinco claves de estado por preview y sólo dos de los cinco caminos
de salida las limpian todas:

| Camino | Limpia |
|---|---|
| Confirmar / Descartar de abajo | las cinco |
| Descartar de arriba | dos |
| "El preview se perdió" | una |
| Descartar del banner de huérfanos | ninguna |
| "Ver preview" con uno ya abierto | una |

Consecuencias: los bytes del Excel quedan acumulados en el estado de
sesión, uno por preview descartado; y volver a apretar "Ver preview"
crea un shadow nuevo abandonando el anterior en la base de datos.
Además, `list_shadows_huerfanos` incluye el shadow que el usuario está
mirando en ese momento, de modo que el banner ofrece descartar el
preview abierto.

---

### H14 🟡 El resumen del set filtrado desaparece cuando el filtro no matchea

**Ubicación**: `src/ui/validation_ui.py:2303-2307` frente a `:2323-2331`.

El `return` temprano quedó **antes** del contenedor de métricas que
este commit movió hacia abajo. Cuando el filtro deja el conjunto vacío,
el usuario pierde la referencia de cuántas materias hay en total —
precisamente en el momento en que le sirve para calibrar cuánto está
filtrando. Antes del cambio las métricas estaban arriba del filtro y
siempre se veían.

---

### H15 🟡 `restrict_materias` quedó sin consumidores

**Ubicación**: `src/ui/validation_ui.py:1780`, `:1789-1791`, `:1829-1834`.

El rediseño de hoy eliminó la única llamada que pasaba este parámetro
(el importer, que ahora usa el loop per-materia). Verificado: las seis
apariciones del identificador están todas dentro de su propia
definición. La rama nunca se ejecuta.

Dado el precedente de caché técnico latente que el proyecto ya
documenta en `DEPRECACION_CLASEDB.md`, conviene retirarlo o al menos
dejar constancia de que quedó sin llamadores para que una sesión
futura no construya encima.

---

## 6. Textos de la interfaz que contradicen el comportamiento

### H12 🟡 Cuatro textos desalineados

| Ubicación | Dice | Realidad |
|---|---|---|
| `6_📅_Cronogramas.py:925-935` | "Por default se agregaron las nuevas comisiones (**agregar**). […] descartá y usá 'reemplazar' manualmente" | El default es `reemplazar` y hay un radio por materia |
| `6_📅_Cronogramas.py:1092-1101` | "ajustar horarios manualmente en la vista **Después**" | La columna Después usa `render_schedule_calendar`, que es de sólo lectura |
| `validation_ui.py:2244-2252` | El filtro "Solo con alertas" muestra "faltantes, no esperadas, conflictivas o sin datos" | También incluye `Revisión`: el código es el complemento de `OK` |
| `validation_ui.py:2179-2183` | "Los conteos **de arriba** […] respetan estos filtros" | El mismo commit movió los conteos abajo, y la métrica "de un total" es deliberadamente pre-filtrado |

El primero es el más costoso: el usuario lo lee justo antes de
confirmar un import que puede borrar comisiones.

---

## 7. Cobertura de tests

### H16 🟡 Faltan las categorías centrales de lo que se agregó

La suite nueva (36 tests entre los tres archivos) cubre bien los
caminos felices. Los huecos relevantes:

| Qué falta | Riesgo que esconde |
|---|---|
| `compute_materia_checks_from_db` con warnings reales | La rama `Revisión` —la categoría por la que el helper existe— no se ejecuta en ningún test. Si algún chequeo cambia de `warn` a `info`, todas las materias con problemas pasarían a mostrarse `OK` y la suite seguiría verde |
| "Confirmar preview sin tocar nada" con una materia multi-comisión | Es el escenario de pérdida de datos de H1. Nada fija la frontera "materia ausente del archivo ⇒ no se toca" |
| `_fingerprint_entries` con duplicados y con comisión renombrada | H7, en las dos direcciones. El rename se reporta hoy como agregada+eliminada, que es razonable pero no está fijado |
| `preview_import(sheet_name=)` de inscriptos | El usuario elige la hoja `2025` y se importa `2024` en silencio; esos datos alimentan el forecast y el programa lineal |
| `create_schedule_standalone` | No tiene **ningún** test, y es el camino en vivo del modo "Crear desde archivo" |
| Los cuatro `raise ValueError` de `regenerar_materia_en_shadow` | La interfaz los convierte en `st.error`; una excepción de otro tipo rompería la pantalla con un traceback |

---

## 8. Documentación

### H17 🟡 Drift en cuatro documentos

| Ubicación | Problema |
|---|---|
| `1. Diseño/modelo-planificacion-cursada.md:378` | Afirma default `"agregar"` y shadow *read-only*. Las dos son falsas hoy. Es el documento que alimenta el informe |
| `2. Desarrollo/WORKFLOW.md` § 4.1 y `requerimientos.md` § RF-IMPORT | El selector de hoja del Excel no está documentado en ningún lado. Es una capacidad visible al usuario sin requerimiento asociado |
| `WORKFLOW.md:437`, `:442-444` | Firma vieja de `preview_import`; dice "tres métricas" (son cuatro); enumera el radio como "agregar / reemplazar / ignorar", sugiriendo el default viejo |
| `WORKFLOW.md:543-549` | Dice "los mismos 10 chequeos" y omite `thl_partition` para que la cuenta cierre. Verificado: son **once** (más `materia_faltante` y `materia_no_catalogo` como casos especiales) |
| `2. Desarrollo/VALIDACIONES.md` § 4 | Presenta los chequeos como exclusivos del editor en vivo; hoy tienen tres consumidores. No menciona `compute_materia_checks_from_db` ni el chequeo `config_horaria` (que existe desde la Fase I.1) |
| `WORKFLOW.md:899-908` | El mapa de páginas lista `0_🏠_Home.py` (el landing es `app/main.py`), escribe `7_📝_Inscriptos.py` con el icono equivocado y omite `8_📜_Historial.py` |
| `WORKFLOW.md:3` | "Última actualización: 2026-09-11", tres semanas y cuatro fases atrás |
| `cronograma_import_service.py:545-550` | La docstring de `crear_shadow_import` dice que para cambiar una decisión hay que descartar el shadow. `regenerar_materia_en_shadow` existe 260 líneas más abajo, en el mismo archivo |
| `schedule_materia_editor.py:1079-1083` | La docstring enumera `Faltante` entre los valores de `estado` y en la oración siguiente dice que no lo incluye. Omite `"Sin datos"`, que sí devuelve en dos ramas |

Lo que **sí** quedó consistente: `VALIDACIONES.md` § 3.2 (los seis
estados con `Revisión`), `requerimientos.md` RF-IMPORT-02 y RF-CRONO-05
(reescritos hoy, fieles al código, incluido el texto del toast), y los
párrafos del preview per-materia de `WORKFLOW.md` § 4.1.

---

## 9. Hallazgos menores

### H18 🟢 `color_by_comision` no tiene efecto *(preexistente)*

**Ubicación**: `src/ui/calendar_render.py:221` y `:235`.

El render lee `getattr(b, "comision", None)`, pero `ScheduleBlock`
expone `comision_id`, `comision_numero` y `comision_nombre` — no
`comision`. Todas las comisiones se pintan con el primer color de la
paleta y la leyenda muestra una sola entrada. El propósito documentado
de la opción es distinguir comisiones cuando se filtra por una sola
materia, que es exactamente el caso de las columnas Antes/Después.

### Otros

- **Expanders anidados**: el preview llama a
  `render_materia_checks_inline` dentro de un `st.expander`, y esa
  función abre otro. Verificado en el código fuente de Streamlit
  1.52.2: **no** levanta excepción (el guard fue removido; sólo queda
  la recomendación en la docstring). Quedan dos efectos: el rótulo se
  duplica casi idéntico, y los chequeos quedan a dos clics cuando el
  estado es `OK`. Conviene parametrizar la función con
  `as_expander: bool` para que el llamador elija.
- **Pin de versiones inconsistente**: `requirements.txt:9` declara
  `streamlit>=1.28.0` mientras `pyproject.toml:7` fija `==1.52.2`. En
  las versiones que ese piso habilita, anidar expanders **sí**
  levantaba excepción. Un entorno armado desde `requirements.txt`
  rompería la pantalla del importer.
- **Extensiones sensibles a mayúsculas**: los chequeos son
  `fname.endswith((".xlsx", ".xls"))`, de modo que `HORARIOS.XLSX` cae
  en "Formato no soportado". Preexistente, pero el código nuevo
  replica el patrón.
- **Duplicación**: `list_horarios_sheets` y `list_inscriptos_sheets`
  tienen cuerpos idénticos, igual que los dos bloques de selectbox.
  Las correcciones de H2 hay que aplicarlas dos veces.
- **Rendimiento del parseo**: `pd.read_excel(sheet_name=None)`
  materializa todas las hojas para quedarse con una. Medido sobre un
  libro de 10 hojas × 3000 filas: 1,23 s contra 0,021 s que cuesta
  `openpyxl.load_workbook(read_only=True).sheetnames`. Y el bloque del
  selector no está protegido por ningún botón, de modo que corre en
  cada reejecución del script.
- **Hojas ocultas sin prefijo**: pandas ignora `sheet_state`, de modo
  que una hoja marcada como oculta llamada "Datos viejos" aparece como
  opción válida en el selector. Verificado. Para las plantillas que
  genera el sistema el filtro por prefijo `_` alcanza; para archivos
  institucionales, no.

---

## 10. Orden de corrección sugerido

**Primero, lo que destruye o falsea datos sin avisar:**

1. **H1** — preservar los atributos de las comisiones en modo
   `reemplazar`. Es lo único que destruye configuración que el archivo
   no puede restituir, y hoy se reporta como "sin cambio".
2. **H3** — propagar `ImportResult.errors` desde
   `regenerar_materia_en_shadow` hasta la pantalla. Sin esto, la
   decisión `agregar` es inservible en su caso de uso más frecuente.
3. **H2** — poner `index=` en los dos selectbox con la preferencia del
   parser. Son dos líneas y desbloquean archivos que hoy fallan.

**Después, lo que hace la pantalla impracticable o incoherente:**

4. **H4.1** — sacar los dos `build_schedule_grid` del loop. Diez
   líneas, de ~8 s a ~90 ms.
5. **H12** (los dos primeros textos) — el tooltip del default y la
   promesa de edición inexistente. Dos cadenas de texto que el usuario
   lee antes de confirmar un borrado.
6. **H5** — derivar el listado del preview en lugar de la base de datos.
7. **H11** — mover la escritura de `_decisiones_map` después del éxito.

**Luego, aritmética y cobertura:**

8. **H6** — el doble conteo por carrera, con los tests primero
   (es lógica pura, aislable de Streamlit).
9. **H7** — `Counter` en lugar de `set`, con el test de invariante.
10. **H16** — los dos tests de mayor valor: el estado `Revisión` del
    helper y "confirmar sin tocar nada" con multi-comisión.

**Finalmente, deuda y documentación:**

11. **H8** — unificar la derivación del contexto de comisiones. Es
    refactor real, conviene hacerlo con tests de regresión para los
    cuatro escenarios (numeración con huecos, entries sin comisión,
    paralelas, comisión de otro cronograma).
12. **H17** — el drift de `modelo-planificacion-cursada.md` y el
    requerimiento faltante del selector de hoja son los dos que
    afectan el informe.
13. **H9, H10, H13, H14, H15, H18** y los menores.
