# Auditoría de restricciones del LP de asignación de aulas

> **Objetivo.** Documentar exhaustivamente el modelo de programación
> lineal entera que asigna aulas al plan: variables, restricciones,
> función objetivo, parámetros configurables, condiciones que lo
> vuelven infactible, y hallazgos abiertos que motivan las próximas
> fases (fix de doble conteo, preferencia blanda, restricción de
> sedes consecutivas, panel de restricciones en la UI).
>
> Fecha de escritura: 2026-09-04. Autor: sesión de auditoría previa
> a rediseñar la semántica de sedes. **Snapshot del código** en
> commit `6220522` (main).

Referencias primarias:

- `src/services/asignacion_aulas_service.py` — armado de inputs,
  construcción del modelo (`build_model`), corrida
  (`solve`, `run_lp_dry`), aplicación al patrón (`apply_solution`).
- `src/services/asignacion_aulas_helpers.py` — funciones puras
  reutilizables: compatibilidad, grupos de simultaneidad,
  diagnóstico estructural, heatmaps.
- `src/services/carrera_sede_service.py` — resolución de sedes
  admisibles por carrera y por materia.
- `project/1. Diseño/asignacion-aulas-LP.md` — planteo matemático
  original. Sigue vigente como referencia teórica.

---

## Qué tiene en cuenta el asignador (versión en criollo)

Esta sección es una guía rápida para el operador o para quien
lea el informe: qué mira el sistema al elegir aulas, qué datos
alimentan cada decisión y dónde tocar cuando algo no da como
uno esperaba. Los detalles técnicos y el detrás de escena
matemático están en las secciones siguientes.

### Qué elige el asignador

Para cada **horario semanal** (materia + comisión + día + rango
horario) del plan, el asignador decide **qué aula ocupa**.
Después esa asignación se propaga a las clases concretas del
cuatrimestre.

### Qué mira para decidir

En orden de prioridad:

1. **Compatibilidad del tipo de aula con el tipo de clase.** Si
   la clase es teórica, sólo la puede meter en aulas teóricas o
   anfiteatros. Si es de laboratorio, sólo en aulas de laboratorio
   listadas como compatibles para esa materia.
2. **Sedes admisibles.** Cada materia puede dictarse solamente en
   ciertas sedes: las habilitadas para la carrera si la materia es
   específica, la sede default para comunes si la materia es
   compartida. Excepción: si un laboratorio compatible con la
   materia vive físicamente en otra sede, esa sede también entra
   como admisible (para poder usar ese lab).
3. **No superponer clases en la misma aula.** Dos horarios que se
   solapan en el tiempo no pueden compartir aula.
4. **Respetar la carga teoría/laboratorio declarada por la
   materia.** Si la materia tiene por ejemplo 3h de teoría y 6h
   de lab, la suma de duraciones de cada tipo tiene que dar
   exactamente eso a nivel de la comisión.
5. **Ediciones manuales del operador.** Si en la UI se fijó a
   mano el aula de un horario (marcada como "asignada
   manualmente"), el asignador respeta esa decisión y no la
   pisa (salvo que se apague ese toggle).
6. **Ajuste de capacidad al forecast de inscriptos.** Entre las
   aulas que cumplen todo lo anterior, prefiere las que entran
   con margen razonable a la cantidad esperada de inscriptos.
   Penaliza fuerte quedarse corto (aula chica que rebalsa) y
   penaliza suave quedarse con mucho sobrante.

### Qué **no** mira todavía

- **No** tiene en cuenta desplazamientos entre sedes a lo largo
  del día de una misma comisión o carrera+año. Puede mandar dos
  clases contiguas a sedes distintas sin darse cuenta.
- **No** tiene noción de "sede preferida" versus "sede tolerable":
  cualquier sede admisible es igual de válida para el asignador
  actual.
- **No** puede reservar o bloquear aulas puntualmente (por
  mantenimiento, evento externo, etc.).
- **No** considera preferencias de docentes ni de estudiantes:
  los horarios los toma como fijos del cronograma.

### Datos que alimentan cada decisión

| Decisión | Datos que la controlan | Dónde se editan |
|---|---|---|
| Qué tipo de aula acepta cada clase. | `tipo_clase` del horario, `tipo` del aula. | Cronogramas → Editar horario · Aulas → Ver detalle. |
| Qué laboratorios sirven para una materia. | Lista `MateriaLaboratorioDB` (relación materia ↔ aula). | Aulas → Ver detalle de un laboratorio → "Materias que usan este laboratorio". |
| Sedes habilitadas para una carrera. | Multiselect en Carreras. | Carreras → carrera → "Sedes habilitadas". |
| Sede por defecto para materias comunes. | Marca `es_default_comunes` en la sede. | Aulas → Sedes → "Sede por defecto para materias comunes". |
| Excepción: comisión pensada para una carrera en particular. | Campo `carrera_asignada` de la comisión. | Cronogramas / Planes → editar comisión. |
| Cuántos inscriptos esperar. | Serie histórica + método de forecast por plan. | Inscriptos (para cargar datos) · Planes → Detalle (para ajustar el método). |
| Horas de teoría / laboratorio de la materia. | Campos `horas_teoria`, `horas_laboratorio`. | Materias → Ficha de la materia. |
| Respetar un aula fijada a mano. | Flag `aula_asignada_manualmente` del horario. | Panel de asignación → editar aula → "Mantener manual". |

### Casos típicos y qué revisar

- **El asignador no encuentra solución (infactible).** Revisar en
  orden: (1) horarios sin ninguna aula compatible (falta lab
  compatible, tipo desalineado, o R10 dejó cero sedes admisibles);
  (2) franjas con más clases simultáneas que aulas del tipo
  requerido; (3) partición teoría/lab que no cierra con las horas
  declaradas por la materia. El panel de validación del plan
  reporta las tres.
- **Una clase queda en una sede que no es la esperada.**
  Habitualmente es porque la sede "esperada" no tenía aula del
  tipo o la capacidad necesaria en esa franja, y el asignador
  encontró una alternativa admisible en otra sede. Revisar las
  sedes habilitadas de la carrera, la capacidad del aula esperada
  y la carga simultánea en esa franja.
- **Un aula queda subutilizada.** El asignador tolera hasta 20 %
  de asientos vacíos sin penalidad. Si querés apretar más las
  aulas, se puede bajar `tol_under` en la configuración del LP.
- **Un aula queda con sobrecupo.** El sistema penaliza sobrecupo
  10× más que subutilización, pero si no hay aula grande
  disponible en la franja puede pasar. Ampliar aulas o partir la
  comisión en más grupos.
- **Cambié el forecast y no veo diferencia.** Los cambios de
  forecast recién impactan al correr de nuevo el asignador desde
  el panel de Aulas del plan.

### Diferencia entre "saturación" y "ocupación" en los mapas

- **Saturación**: cuenta la **demanda proyectada** (horarios que
  la sede podría recibir según las reglas). Es una cota de
  presión sobre la sede antes de resolver.
- **Ocupación**: cuenta las **aulas efectivamente usadas** por el
  asignador en el estado actual del plan.

Cuando saturación > ocupación en una celda, indica que había
demanda que la sede podía absorber pero el asignador la mandó a
otra sede admisible (típicamente por capacidad o por combinación
de restricciones). Cada teórica se cuenta una sola vez, en su
**sede preferida** (la del lab compatible si tiene lab; si no, la
sede de la carrera). Ya no aparece inflada por conectividad de
laboratorios en sedes distintas.

Más adelante el mapa de saturación va a soportar varias vistas
para analizar factibilidad de antemano: **demanda dura** (lo que
no tiene alternativa de sede — si supera la oferta es
infactibilidad segura), **demanda preferida** (la actual),
**demanda máxima** (todo lo que podría caer en la sede) y
**demanda total sin sede** (cota global). Ver §8 para el detalle
de cada vista.

---

## 1. Variables de decisión

| Variable | Tipo | Dominio | Semántica |
|---|---|---|---|
| `x[h, a]` | binaria | 0/1 | 1 si el horario `h` se asigna al aula `a`, 0 si no. Sólo existe para pares `(h, a)` **compatibles** (ver §3, R3+R6+R10). |
| `t[h]` | binaria | 0/1 | 1 = laboratorio, 0 = teórica. Sólo se crea para horarios con `tipo_clase=None`. Los demás son constantes (`t_const[h]`). |
| `α[k]` | continua | [0, 1] | Coeficiente de asignación de inscriptos a la comisión `k`. Sólo se crea cuando `config.activar_alpha=True` (hoy off). |
| `over[h]` | continua | ≥ 0 | Cuántos inscriptos excedieron la capacidad del aula asignada. |
| `under[h]` | continua | ≥ 0 | Cuántos asientos sobraron respecto de los inscriptos. |

Notas de implementación:

- `t[h]` **no se crea** si el horario ya tiene `tipo_clase` fijo
  (el LP no tiene que decidir). Se lee como constante en R5 y R6.
  Además, `build_inputs` infiere el tipo en memoria (sin persistir)
  cuando la materia declara sólo teoría **o** sólo laboratorio,
  reduciendo variables innecesarias.
- `α[k]` está detrás de un flag (`config.activar_alpha`). Cuando
  está apagado (default), `insc[h]` se toma del forecast persistido
  (`get_inscriptos_esperados_por_comision`) como constante.

---

## 2. Función objetivo

```
minimizar  λ_over · Σ over[h]  +  λ_under · Σ under[h]
```

Parámetros:

- `λ_over = 10.0` (default en `LPConfig`). Penaliza sobrecupo con
  peso alto.
- `λ_under = 1.0`. Penaliza subutilización con peso 10× menor.

Interpretación: preferimos aulas que caben **con margen** antes que
aulas apretadas. Cuando el margen no alcanza, preferimos apretar
antes que rebalsar. Los pesos son parametrizables desde `LPConfig`
pero no están expuestos en la UI hoy.

**Sin término de preferencia de sede** — hoy la sede es una
restricción dura (R10). Fase 3 sumará un término
`λ_sede · Σ pref_penalty[h]` para hacerla blanda.

---

## 3. Restricciones

### R1 — Asignación única
**Fuente:** `asignacion_aulas_service.py:576-587`.

Para cada horario `h`:

```
Σ_{a compatible con h} x[h, a] = 1
```

Cada horario debe recibir exactamente una aula. Si el conjunto de
aulas compatibles está vacío, `build_model` emite
`R1_sin_aulas_compat_<hid>` (una restricción imposible) para que
el solver reporte infactibilidad con nombre parlante.

- **Tipo:** dura.
- **Parámetros:** ninguno.
- **Infactible si:** existe un horario sin ninguna aula compatible
  (falta lab en `MateriaLaboratorioDB`, R10 dejó cero admisibles,
  el tipo de la materia no coincide con el catálogo, etc.).
  Detectado en `diagnose_infeasibility → horarios_sin_aula_compatible`.

### R3 — Compatibilidad horario ↔ aula (por tipo)
**Fuente:** `asignacion_aulas_helpers.py:134-167` (`compute_compat`).

Determina si el par `(h, a)` puede formar una variable `x[h, a]`:

- Si `h.tipo_clase == "teorica"`: `a.tipo ∈ {"teorica", "anfiteatro"}`.
- Si `h.tipo_clase == "laboratorio"`: `a.id ∈ materia_lab_map[h.materia]`
  (aulas listadas en `MateriaLaboratorioDB` para esa materia).
- Si `h.tipo_clase is None`: cualquier aula pasa **pre-modelo**; la
  consistencia real se fuerza por R6 usando `t[h]`.

- **Tipo:** dura, pre-modelo (filtra variables antes de crearlas).
- **Parámetros:** ninguno.
- **Infactible si:** ver R1 (compatibilidad vacía).

### R4 — No solapamiento por aula (grupos de simultaneidad)
**Fuente:** `asignacion_aulas_service.py:608-621` +
`asignacion_aulas_helpers.py:57-127` (`compute_simultaneidad_groups`).

Para cada grupo maximal de horarios que se solapan en el tiempo `G`,
y cada aula `a`:

```
Σ_{h ∈ G} x[h, a] ≤ 1
```

Los grupos se calculan con barrido de eventos por día (O(N log N)).
Sólo se emiten grupos de tamaño ≥ 2 y maximales (no subconjuntos
de otros).

- **Tipo:** dura. Relajable en `build_model(relax={"R4"})` sólo
  para diagnóstico IIS.
- **Parámetros:** ninguno.
- **Infactible si:** pigeonhole clásico — más horarios simultáneos
  que aulas compatibles con la unión (`franjas_saturadas`) o que
  aulas admiten a un subconjunto Hall-violador (`hall_violators`).

### R5 — Partición teoría / lab por comisión
**Fuente:** `asignacion_aulas_service.py:623-653`.

Para cada comisión `k` con materia `m`:

```
Σ_{h ∈ k} dur[h] · t[h] = hlab[m]
```

La partición teoría es implícita (`dur_total - hlab`). Los horarios
con `tipo_clase` fijo contribuyen con `t_const` como constante.

- **Tipo:** dura. Relajable con `relax={"R5"}` para diagnóstico.
- **Parámetros:** ninguno directos, pero depende de los valores de
  `MateriaDB.horas_laboratorio` y `MateriaDB.horas_teoria` +
  la lista de horarios cargados.
- **Infactible si:** la suma de duraciones de los horarios de la
  comisión no permite bipartir exactamente en `hteo + hlab`.
  Detectado por `validar_particion_factible` antes del solve.

### R6 — Consistencia tipo ↔ pool de aulas (para tipos indefinidos)
**Fuente:** `asignacion_aulas_service.py:655-689`.

Sólo aplica a horarios con `t[h]` variable (`tipo_clase=None`):

- **R6a (teórica):** si `t[h] = 0`, sólo puede caer en aulas teóricas:
  `Σ_{a ∈ A_teoricas} x[h, a] ≥ 1 - t[h]`.
- **R6b (laboratorio):** si `t[h] = 1`, sólo puede caer en labs
  compatibles con la materia: `Σ_{a ∈ A_lab(m)} x[h, a] ≥ t[h]`.

Casos degenerados:

- Sin aulas teóricas: fuerza `t[h] = 1`.
- Sin labs compatibles: fuerza `t[h] = 0`.

- **Tipo:** dura. Relajable con `relax={"R6"}`.
- **Parámetros:** ninguno.
- **Infactible si:** ambos casos degenerados aplican simultáneamente
  para el mismo horario.

### R7 — Penalty de capacidad lineal asimétrico
**Fuente:** `asignacion_aulas_service.py:691-723`.

Linealización de `|cap - insc|` con dos tolerancias:

```
over[h]  ≥ insc[h] − Σ x[h, a] · cap[a] · (1 + tol_over)
under[h] ≥ Σ x[h, a] · cap[a] · (1 − tol_under) − insc[h]
```

Cuando `α` está activo, `insc[h]` se reemplaza por
`total_esp[materia(h)] · α[comision(h)]` (expresión lineal).

- **Tipo:** blanda (aparece en el objetivo).
- **Parámetros de `LPConfig`:**
  - `lambda_over = 10.0`, `lambda_under = 1.0` (pesos).
  - `tol_over = 0.0` (por default, sobrecupo puro cuenta).
  - `tol_under = 0.20` (permitimos 20 % de subutilización sin
    penalidad — pensado para no forzar aulas chicas cuando la
    demanda oscila).
- **Nunca vuelve el problema infactible** (over, under ≥ 0).

### R9 — Toggle α de redistribución de coeficientes (opcional, hoy off)
**Fuente:** `asignacion_aulas_service.py:523-553`.

Cuando `config.activar_alpha=True`:

- Se crea `α[k]` continua por comisión.
- Por dictado `d`, `Σ_{k ∈ d} α[k] = 1` — los coeficientes de
  asignación entre comisiones del mismo dictado deben sumar 1.
- Comisiones sin dictado quedan con `α = 1` forzado.

- **Tipo:** dura cuando el toggle está on.
- **Parámetros:** `LPConfig.activar_alpha` (bool). No expuesto en UI.

### R10 — Sedes admisibles por horario
**Fuente:** `asignacion_aulas_service.py:339-388`.

Filtra `compat[(h, a)]` post-R3 según sede del aula:

1. Se resuelve el conjunto de sedes admisibles del horario:
   - Si la comisión tiene `carrera_asignada != None`, se toma
     `sedes_admisibles_para_carrera(carrera_asignada)` (override).
   - Si no, `sedes_admisibles_para_materia(materia)`.
   - Si el resultado es `None` → sin restricción (cualquier sede).
2. Para cada aula, si su `sede_id` no está en el conjunto y el
   aula no está en `MateriaLaboratorioDB` para esa materia,
   `compat[(h, a)] = False`.

Excepción clave: **si el aula está en `MateriaLaboratorioDB` para la
materia, prevalece sobre R10** (líneas 383-386). Un lab compatible
puede recibir la materia aunque esté en una sede fuera del set
admisible.

`sedes_admisibles_para_materia` (definida en
`carrera_sede_service.py`) hoy devuelve:

- **Materias específicas** (aparecen en una sola carrera):
  sedes habilitadas de esa carrera.
- **Materias comunes** (2+ carreras): la sede default para
  comunes (`SedeDB.es_default_comunes=True`) si existe; si no,
  `None` (sin restricción).

- **Tipo:** dura.
- **Parámetros:**
  - `SedeDB.es_default_comunes` global.
  - `CarreraSedeDB` (M:N carrera↔sede) por carrera.
  - `ComisionDB.carrera_asignada` (override por comisión).
- **Infactible si:** después de aplicar R10 un horario queda sin
  aulas compatibles (`horarios_sin_aula_compatible` con
  razón "R10").

### R11 — Pins de ediciones manuales
**Fuente:** `asignacion_aulas_service.py:589-606`.

Cuando `config.respetar_ediciones_manuales=True` y
`HorarioDB.aula_asignada_manualmente=True`:

```
x[h, aula_manual] = 1
```

Si el aula pinneada ya no es compatible (cambió tipo, sede, etc.),
se emite una restricción imposible con nombre `R11_pin_incompat_<hid>`.

- **Tipo:** dura, opcional (controlada por
  `config.respetar_ediciones_manuales`).
- **Parámetros:** `LPConfig.respetar_ediciones_manuales` (bool).
  Toggle expuesto en UI.
- **Infactible si:** el pin apunta a un aula incompatible.

---

## 4. Restricciones NO implementadas hoy

### Sedes consecutivas / margen de viaje
No existe restricción alguna sobre secuencia de sedes a lo largo del
día de una comisión, carrera o año. El LP puede asignar la primera
clase de una comisión en Pellegrini y la contigua (misma comisión,
sin gap) en Siberia sin ninguna penalidad.

Este es uno de los focos de Fase 4: definir semántica (¿por
comisión? ¿por carrera+año?) + parámetro de margen mínimo entre
sedes distintas y agregarlo al modelo.

### Preferencia de sede blanda
No existe. Hoy R10 es dura y admite cualquier sede del set. No hay
noción de "sede preferida" ni penalidad por caer en otra. Fase 3.

### Reservas / bloqueos manuales de aulas
No existe. No hay forma hoy de decir "aula X no disponible el lunes
por mantenimiento".

### Preferencia horaria de docentes
Fuera del alcance del LP actual (los horarios ya vienen fijos desde
el cronograma).

---

## 5. Función objetivo — resumen y parámetros

```python
# asignacion_aulas_service.py:565-569
prob += (
    config.lambda_over * pulp.lpSum(over_vars.values())
    + config.lambda_under * pulp.lpSum(under_vars.values())
), "objetivo"
```

Sólo hay dos términos (R7 over y under). Todo lo demás son
restricciones duras.

Parámetros de `LPConfig` (`asignacion_aulas_service.py:66-84`):

| Parámetro | Default | Semántica | Expuesto en UI |
|---|---|---|---|
| `lambda_over` | 10.0 | Peso del sobrecupo. | No |
| `lambda_under` | 1.0 | Peso de la subutilización. | No |
| `tol_over` | 0.0 | Fracción de cap[a] permitida sobre insc antes de penalizar. | No |
| `tol_under` | 0.20 | Fracción de cap[a] permitida bajo insc antes de penalizar (20 %). | No |
| `activar_alpha` | False | Habilita R9 (redistribución de coeficientes). | No |
| `timeout_seconds` | 300 | Timeout de CBC. | No |
| `respetar_ediciones_manuales` | True | Habilita R11. | Sí (toggle en panel de asignación) |
| `fecha_desde` | None | Fecha desde la que propagar la solución a ClaseDB. | Sí (implícito, por default = mín) |

---

## 6. Semántica de "sede admisible" y el bug de doble conteo

> **Estado (2026-09-05)**: el bug descripto en esta sección está
> corregido. Ver "Fix implementado" al final. Se conserva el
> planteo original porque describe el problema y el razonamiento
> que llevó a la solución (base del criterio de "sede preferida"
> que se reutiliza en Fases 3 y 4).

`compute_heatmap_por_sede`
(`asignacion_aulas_helpers.py:898-1137`) cuenta la demanda teórica
de una sede iterando **todas las sedes** por horario:

```python
# líneas 1032-1069 (simplificado)
for h in horarios:
    admis = sedes_admisibles_por_materia[h.materia]
    labs = materia_lab_map[h.materia]
    for sede in sedes_con_aulas:
        tiene_lab_en_sede = any(aula_sede_id[a] == sede for a in labs)
        if admis is None:
            sede_admisible = True
        else:
            sede_admisible = (sede in admis) or tiene_lab_en_sede
        if not sede_admisible:
            continue
        if h.tipo_clase == "teorica":  # ← se suma a cada sede admisible
            ... demanda_teorica[sede] += 1
```

Efecto: para materias con carrera en sede X pero labs compatibles
físicamente ubicados en sede Y, **la teórica se cuenta como
demanda de X y de Y simultáneamente**. Ejemplo verificado:

- Materia `A5` (Informática Aplicada), carrera `A`.
- Sedes habilitadas de `A` = {Siberia}.
- Labs compatibles de `A5` = {LAB-004, LAB-005}, ambos en
  **Pellegrini**.
- La regla `sede in admis OR tiene_lab_en_sede` marca Pellegrini
  como admisible por el lab.
- La clase teórica de A5 en Lunes 08:00 se cuenta como demanda
  teórica de **Pellegrini** (14/22) y de **Siberia** (parte del
  17 total de Siberia teórica). El solver la manda a una sola
  (Siberia, IMAE-Aula-13), y la ocupación de Pellegrini queda en
  13/22 → gap de 1.

Nota: para categoría `laboratorio` **no** hay doble conteo
(líneas 1054-1055 filtran: si la sede no tiene lab compatible con
la materia, no cuenta como demandante de labs). El bug es
específico de la categoría teórica.

**Decisión de la Fase 2 (según acuerdo con el usuario 2026-09-04):**
la "sede preferida" para el conteo de saturación de una teórica es:

1. **Si la materia tiene labs compatibles**: la sede del(los) lab(s)
   — coherente con "las teóricas deberían darse donde está el lab
   para minimizar desplazamientos".
2. **Si no tiene labs**: cualquiera de las sedes habilitadas para
   su carrera (o `None` si no hay restricción — se cuenta en todas
   igual que hoy en las materias comunes).

Cuando el lab está en una sede distinta de las de la carrera, la
teórica sigue "prefiriendo" la del lab: eso hace que el mapa de
saturación refleje la realidad esperada (donde el solver la va a
querer poner) sin inflar sedes por conectividad de lab.

### Fix implementado (Fase 2, 2026-09-05)

Se agregó la función pura `sede_preferida_para_horario` en
`asignacion_aulas_helpers.py` con las reglas descriptas arriba, y
se modificó `compute_heatmap_por_sede` para consumirla:

- La **categoría teórica** se contabiliza una sola vez, en la sede
  preferida devuelta por la función. Nunca se suma en más de una
  sede.
- La **categoría laboratorio** se sigue contabilizando en la(s)
  sede(s) donde vive un aula de lab compatible (sin cambio). Nunca
  hubo doble conteo acá — el lab físicamente se dicta donde está
  el aula.
- **Fallback**: si la materia no tiene ni labs compatibles ni set
  de sedes admisibles restringido (caso común sin default para
  comunes), la teórica se cuenta en todas las sedes admisibles.
  Es el mismo comportamiento previo, aplicable sólo a ese caso
  residual.

Verificación empírica sobre el caso A5 (Lunes 08:00-08:15,
Plan v0, ciclo 2026-1C):

| Sede | Teórica antes | Teórica ahora |
|---|---|---|
| Pellegrini | 14/22 | 14/22 |
| Siberia | 4/20 | 3/20 |

A5 ahora se contabiliza **sólo en Pellegrini** (donde viven los
labs LAB-004 y LAB-005). La divergencia visible entre saturación
14 y ocupación 13 en Pellegrini deja de ser doble conteo y pasa a
ser **una divergencia real y accionable**: el LP mandó A5 a
Siberia (IMAE-Aula-13) aunque su sede preferida era Pellegrini,
típicamente por capacidad o combinación con otras restricciones.
Esa clase de casos es lo que las Fases 3 y 4 van a capturar y
señalizar.

Tests agregados en `tests/test_asignacion_aulas_helpers.py`:

- `TestHeatmapPorSede.test_teorica_no_duplica_conteo_si_lab_esta_en_otra_sede`
- `TestHeatmapPorSede.test_teorica_va_a_sede_de_carrera_cuando_no_hay_lab`
- `TestHeatmapPorSede.test_lab_no_cambia_su_conteo_por_el_fix_de_teoricas`
- `TestHeatmapPorSede.test_materia_con_lab_en_misma_sede_que_carrera`
- `TestSedePreferidaParaHorario.*` (5 tests dedicados a la función pura).

---

## 7. Diagnóstico de infactibilidad estructural

Antes de correr el solver, `diagnose_infeasibility` detecta 5
familias de causas (`asignacion_aulas_helpers.py:276-414`):

1. **Horarios sin aula compatible** (R1 + R3, + R10 si aplica).
2. **Franjas saturadas** (pigeonhole sobre la unión de aulas
   compatibles del grupo de simultaneidad).
3. **Saturación por tipo** dentro de una franja (refina 2 con
   pools separados teóricas / labs).
4. **Hall violators** — para cada grupo, matching bipartito.
   Detecta subconjuntos S donde `|N(S)| < |S|`, más informativo
   que pigeonhole.
5. **Partición teoría/lab infactible** (R5).

Este diagnóstico corre **antes** del solve (sin costar tiempo de
CBC) y devuelve mensajes accionables via
`InfeasibilityDiagnosis.to_messages()`. Se puede reforzar en Fase 5
con un panel dedicado en la UI.

Fase 5 (panel de restricciones) puede reutilizar este diagnóstico
como fuente principal para responder al usuario "por qué el LP dio
infactible".

---

## 8. Puntos abiertos que motivan las próximas fases

| Fase | Estado | Problema | Cambio |
|---|---|---|---|
| 2 | ✅ Hecho (2026-09-05) | Doble conteo en saturación teórica cuando lab está en otra sede. | Introducida `sede_preferida_para_horario`; `compute_heatmap_por_sede` cuenta cada teórica una vez. |
| 3 | Pendiente | R10 es dura → un horario puede volver infactible el plan por sede aunque haya aula en otra sede admisible. | R10 se descompone: (a) restricción dura de "sedes admisibles" (mismo set actual), (b) penalidad blanda por caer fuera de la sede preferida (misma función que ya expuso Fase 2). |
| 3.5 | Pendiente | El mapa de saturación es una sola vista estática y no distingue "demanda dura" de "demanda preferida"; una vez introducida la blanda va a mentir todavía más. | Selector de vista con al menos 4 opciones: **demanda dura por sede** (horarios sin alternativa, cota de infactibilidad), **demanda preferida por sede** (actual, corregida en Fase 2), **demanda máxima por sede** (cota superior: todos los que podrían caer ahí), **demanda total sin sede** (cota inferior de factibilidad global). Objetivo: analizar factibilidad **antes** de correr el LP y ver cuánto margen hay entre lo duro y lo preferido. |
| 4 | Pendiente | No hay restricción de sedes consecutivas. | Nueva restricción parametrizable: margen mínimo entre horarios contiguos de la misma comisión (o carrera+año) que caen en sedes distintas. |
| 5 | Pendiente | El operador no tiene visibilidad de qué restricciones están activas ni de sus parámetros al debuggear una infactibilidad. | Panel en `Planes → Configuración` (o pestaña nueva) que liste cada Ri con estado (dura/blanda/off), parámetros editables (dentro de bounds razonables), y link al diagnóstico estructural. |

La función pura `sede_preferida_para_horario` (Fase 2) queda
disponible en `asignacion_aulas_helpers` y va a ser reutilizada
por Fases 3, 3.5 y 4 para calcular la sede preferida por horario
sin duplicar lógica.

### Anatomía de las 4 vistas del mapa (Fase 3.5)

Cada vista responde una pregunta distinta sobre la factibilidad
del plan. Los 4 números se computan para la misma celda
(sede × día × franja × categoría) y el usuario elige cuál mirar.

- **Demanda dura por sede.** Cuenta los horarios cuya única sede
  admisible es ésta (no tienen alternativa). Si este número
  supera la oferta de la sede, es **infactibilidad estructural**:
  el LP no puede resolverlo pase lo que pase.
- **Demanda preferida por sede.** Cuenta los horarios cuya sede
  preferida es ésta (regla `sede_preferida_para_horario`). Es la
  vista que ya existe hoy — refleja el "plan feliz" donde cada
  materia va a la sede natural.
- **Demanda máxima por sede.** Cuenta los horarios que podrían
  caer en esta sede aunque prefieran otra (todo el set de sedes
  admisibles). Cota superior: si esto es menor que la oferta,
  hay margen; si es mayor, el LP eligirá desplazar algunos a
  otras sedes.
- **Demanda total sin sede.** Ignora la sede: cuenta cuántos
  horarios simultáneos hay en cada franja del sistema entero.
  Es la cota inferior global. Si supera la oferta agregada
  (todas las sedes juntas), el plan no cabe ni redistribuyendo.

La lectura conjunta es la que da información accionable:

- `dura ≤ oferta ≤ preferida`: el plan feliz no cabe pero hay
  espacio para desplazar. La Fase 3 (preferencia blanda) va a
  poder resolverlo minimizando desplazamientos.
- `dura > oferta`: bloqueante. Hay que revisar configuración
  (sedes habilitadas, labs compatibles) o el catálogo de aulas.
- `preferida ≤ oferta ≤ máxima`: la sede tiene margen; el LP
  puede recibir más carga si otra sede se satura.
- `total_sin_sede > sum(oferta)`: infactibilidad global por
  cantidad simultánea. Repartir sedes no lo salva.
