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

**Bug detectado (foco de Fase 2).**

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

| Fase | Problema | Cambio propuesto |
|---|---|---|
| 2 | Doble conteo en saturación teórica cuando lab está en otra sede. | Definir sede preferida por materia (lab-first, luego carrera). Contar cada teórica una vez. |
| 3 | R10 es dura → un horario puede volver infactible el plan por sede aunque haya aula en otra sede admisible. | R10 se descompone: (a) restricción dura de "sedes admisibles" (mismo set actual), (b) penalidad blanda por caer fuera de la sede preferida. |
| 4 | No hay restricción de sedes consecutivas. | Nueva restricción parametrizable: margen mínimo entre horarios contiguos de la misma comisión (o carrera+año) que caen en sedes distintas. |
| 5 | El operador no tiene visibilidad de qué restricciones están activas ni de sus parámetros al debuggear una infactibilidad. | Panel en `Planes → Configuración` (o pestaña nueva) que liste cada Ri con estado (dura/blanda/off), parámetros editables (dentro de bounds razonables), y link al diagnóstico estructural. |

**Prerrequisito común a Fases 2-4.** Introducir un concepto de
"sede preferida por horario" (o materia) accesible desde
`asignacion_aulas_helpers` sin duplicar lógica de resolución. La
Fase 2 puede exponerlo como función pura y las Fases 3-4 lo
consumen.
