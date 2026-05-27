# Asignación de Aulas — Formulación del Programa Lineal Entero (ILP)

> **Estado**: stub. La implementación queda fuera de alcance del refactor de
> forecasting (2026-05). Este documento delinea la formulación para que cuando
> arranque la sesión de implementación esté ya el contexto.
> **Fecha**: 2026-05-26
> **Próximas sesiones**: solver concreto (PuLP/CBC vs OR-Tools), parametrización
> persistida (`LPConfiguracionDB`), pipeline de ejecución y visualización de
> resultados.

---

## 1. Contexto y Motivación

Una vez generado el `PlanificacionCursadaDB` con sus `ComisionDB` y `HorarioDB`,
y expandidas las `ClaseDB` (instancias por fecha), falta decidir **a qué aula
va cada clase**. Esa decisión está acoplada con dos más:

1. **Tipo de clase** (`tipo_clase`): cuando el cronograma no lo predetermina,
   hay que decidir cuáles clases de una comisión son teoría y cuáles
   laboratorio (respetando `horas_teoria` / `horas_laboratorio` de la materia).
2. **Coeficientes de asignación de inscriptos** (`coef_asignacion`):
   opcionalmente el LP puede redistribuirlos para mejorar el ajuste a las
   capacidades disponibles, sujeto a un toggle del usuario.

Ver justificación del acoplamiento en
`modelo-planificacion-cursada.md` § 9 ("Programa Lineal único").

---

## 2. Alcance

### Lo que el LP decide
- `ClaseDB.aula_id` para cada clase no-virtual.
- `ClaseDB.tipo_clase` cuando viene `None` desde el horario (decisión variable).
- (Opcional) `ComisionDB.coef_asignacion` para cada comisión, si el toggle
  "permitir reasignación de coeficientes" está ON.

### Lo que NO toca
- **No crea ni elimina comisiones**. Toma el plan tal como está. Si el
  resultado es infactible o de mala calidad, el usuario edita las comisiones
  desde **Planes → Detalle** (subir n_comisiones, cambiar horarios, etc.) y
  vuelve a correr el LP.
- **No modifica el cronograma original** ni los horarios.
- **Excluye clases virtuales** (no requieren aula).
- **Excluye reservas ad-hoc de laboratorio** para materias con
  `horas_laboratorio = 0` que tienen labs compatibles. Esas se agendan
  durante la cursada, no en la planificación inicial.

---

## 3. Variables

Sea:
- `C` = conjunto de clases no-virtuales del plan.
- `A_t` = aulas con `tipo = "teorica"` o `"anfiteatro"`.
- `A_lab(m)` = aulas en `MateriaLaboratorioDB` para la materia `m`.
- `K` = conjunto de comisiones del plan.

| Variable | Tipo | Significado |
|---|---|---|
| `x[c, a]` | binaria | 1 si la clase `c` se asigna al aula `a` |
| `t[c]` | binaria (solo si `tipo_clase` no fijado) | 1 si la clase es laboratorio, 0 si teoría |
| `α[k]` | continua en `[0,1]` (solo si toggle ON) | coef de asignación de la comisión `k` |
| `over[c,a]` | continua, ≥ 0 | exceso de ocupación más allá de tolerancia |
| `under[c,a]` | continua, ≥ 0 | exceso de subocupación más allá de tolerancia |

Cuando `tipo_clase` está fijado en `HorarioDB` (heredado del cronograma), `t[c]`
se reduce a una constante (0 o 1) y deja de ser variable.

---

## 4. Función Objetivo — Penalty parametrizable

Sea `esperados[c]` los inscriptos esperados de la clase (= los de su comisión,
ver § 5.5 de `plan-de-cursada.md`).

Restricciones de linealización:
```
over[c,a]  ≥ x[c,a] · (esperados[c] − cap[a] · (1 + tol_over))
under[c,a] ≥ x[c,a] · (cap[a] · (1 − tol_under) − esperados[c])
```

Objetivo:
```
min  λ_over · Σ over[c,a]   +   λ_under · Σ under[c,a]
```

Parámetros expuestos al usuario (persistidos en `LPConfiguracionDB` o
extensión de `ConfiguracionHoraria`):

| Parámetro | Default | Significado |
|---|---|---|
| `tol_over` | 0% | sobreocupación aceptable sin penalty |
| `tol_under` | 20% | subocupación aceptable sin penalty |
| `λ_over` | 10 | costo por alumno excedente |
| `λ_under` | 1 | costo por lugar vacío fuera de tolerancia |
| `forma` | "lineal" | "lineal" (Σ over) o "cuadrática" (Σ over²) — cuadrática requiere MIQP solver |

### Casos particulares cubiertos

| Configuración | Comportamiento |
|---|---|
| `λ_over = ∞` | restricción dura de capacidad (sobreocupación prohibida) |
| `λ_over = λ_under, tol = 0, lineal` | penalty simétrico `\|cap − esperados\|` |
| `λ_over = λ_under, tol = 0, cuadrática` | penalty simétrico `(cap − esperados)²` |
| `λ_over = 10, λ_under = 1` | asimétrico (default): castiga sobreocupación 10× más |
| `λ_under = 0, tol_under = 100%` | solo importa no sobre-asignar |

### Implementación

Arrancar con `forma = "lineal"` (corre en PuLP/CBC sin extra). La cuadrática
queda como extensión futura (requiere OR-Tools, GLPK con add-ons, o
linealización piecewise).

---

## 5. Restricciones

| # | Restricción | Forma |
|---|---|---|
| R1 | Asignación única | `Σ_a x[c,a] = 1 ∀c ∈ C` |
| R2 | Ocupación única por slot | dos clases en mismo `(día, hora)` no comparten aula |
| R3 | Tipo → pool teoría | `t[c] = 0 → x[c, a] = 0` para `a ∉ A_t` |
| R4 | Tipo → pool lab | `t[c] = 1 → x[c, a] = 0` para `a ∉ A_lab(materia(c))` |
| R5 | Horas teoría/lab por comisión | `Σ_{c∈k} dur(c) · t[c] = horas_lab(materia(k))` |
| R6 | Lab compatible | sólo aulas que aparezcan en `MateriaLaboratorioDB` |
| R7 | Coef opcional (toggle ON) | `Σ_{k del mismo dictado} α[k] = 1`, `α ∈ [0,1]` |
| R8 | Sin restricción dura de capacidad | el control va por el penalty `λ_over` |

R5 garantiza que la suma de duraciones de clases marcadas lab dentro de cada
comisión coincide con `horas_laboratorio` declarado en la materia. La
prevalidación de "factibilidad de partición" se asegura de que esto sea posible
**antes** de correr el LP (subset-sum sobre las duraciones).

---

## 6. Output

| Persiste en | Qué |
|---|---|
| `ClaseDB.aula_id` | Aula asignada. `None` queda solo para clases virtuales. |
| `ClaseDB.tipo_clase` | Si era `None`, queda fijado a `"teorica"` o `"laboratorio"`. |
| `ComisionDB.coef_asignacion` | Si toggle ON, los `α*` óptimos. Sujeto a confirmación del usuario. |

**Métricas reportadas (no persistidas, recomputables)**:
- Por clase asignada: `Δ = cap[a] − esperados[c]` y flags
  `sobreocupada` (`Δ < 0`) / `subutilizada` (`Δ > cap · tol_under`).
- Suma total de `Σ over` y `Σ under`.
- Cuántas clases caen en cada bucket (verde / amarillo / rojo).

---

## 7. Visualización del resultado

Esto es **clave para iterar**: cuando el LP devuelve un plan no ideal, el
usuario necesita ver dónde está el problema para decidir si ajusta comisiones
o relaja parámetros.

- **Tabla por clase** con columna `Δ` coloreada (verde / amarillo / rojo según
  gap vs tolerancias).
- **Heatmap por slot horario**: filas = slots `(día, hora)`, color según el
  peor `Δ` en ese slot.
- **Resumen agregado**: "X clases sobreocupadas (total +N alumnos),
  Y subutilizadas (total -M lugares)".
- **Lista de candidatas a partir comisión**: materias con clases sobreocupadas
  ordenadas por exceso, con sugerencia de subir `n_comisiones` o redistribuir
  `coef_asignacion`.
- **Comparación entre corridas**: persistir el snapshot del LP run (parámetros
  + resultado) en una tabla `LPRunDB` para auditar y comparar configuraciones.

---

## 8. Pipeline de ejecución

```
1. Usuario abre Planes → Detalle → tab "Asignar Aulas" (nuevo)
2. Verifica:
   - Plan tiene clases generadas (ClaseDB).
   - Inscriptos esperados disponibles (forecast persistido para todas las materias).
   - Particion teoria/lab factible (prevalidacion).
3. Configura parametros (tol_over, lambdas, forma, toggle coef).
4. Apreta "Correr LP".
5. El servicio:
   - Carga clases, aulas, esperados.
   - Construye el LP via PuLP.
   - Resuelve con CBC.
   - Persiste aula_id, tipo_clase, alpha (si toggle).
6. Muestra resultado (tabla + heatmap + resumen + candidatas).
7. Si no satisface: ajustar comisiones desde Detalle, volver al paso 4.
```

---

## 9. Cuestiones abiertas

- **Tamaño del problema**: con ~600 materias × varias clases por materia × ~50
  aulas, el ILP puede tener 100k+ variables binarias `x[c,a]`. Pre-filtrar
  el dominio: para cada clase, considerar solo aulas compatibles con su tipo
  y con `cap` razonable (ej. ≥ esperados / 2). Esto baja órdenes de magnitud.
- **Solver**: PuLP+CBC funciona para problemas medianos. Si CBC no escala,
  pasar a OR-Tools (más rápido) o Gurobi (académico).
- **Multi-ciclo**: el LP corre por ciclo. Si el usuario quiere comparar
  asignaciones cross-ciclo, son corridas separadas.
- **Estabilidad entre re-corridas**: si el usuario cambia algo menor y vuelve
  a correr, ¿queremos asignaciones similares a la anterior? Considerar un
  término de objective que penalice cambios respecto a la corrida previa.
- **Aulas con horarios reservados**: hoy no modelamos disponibilidad parcial
  de aulas (ej. aula tomada por examen los martes). Asumimos full disponibilidad
  durante el ciclo.

---

## 10. Referencias

- Modelo de datos: `modelo-planificacion-cursada.md` (entidades + § 9 LP)
- Forecasting: `plan-de-cursada.md` § 5.5
- Compañero ICR (planteo original): notas en sesión `PREVALIDACION_Y_DICTADOS_2026.md`
