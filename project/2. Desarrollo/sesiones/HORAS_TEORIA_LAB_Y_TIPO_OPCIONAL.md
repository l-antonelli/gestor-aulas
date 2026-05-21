# Sesión: Horas teoría/laboratorio + tipo_clase opcional + prevalidación de partición

> **Fecha**: 2026-05-21
> **Branch**: `main`
> **Estado**: Implementado

---

## 1. Contexto

Antes de esta sesión, el modelo asumía que cada `ScheduleEntryDB`/`HorarioDB`/`ClaseDB` se distinguía como `tipo_clase = "teorica"` o `"laboratorio"` antes de pasar al programa lineal (LP) de asignación de aulas. La carga manual era tediosa y muchos casos no se conocen hasta que el LP los decide en función de aulas, laboratorios compatibles y horarios fijos de laboratorio.

A partir del análisis registrado en `project/1. Diseño/modelo-planificacion-cursada.md` §9, se confirmó que la asignación de aula, la asignación de laboratorio y la determinación del tipo (teoría/laboratorio) son **decisiones acopladas** que deben resolverse en un único LP. Esto motiva los cambios que documentamos acá.

---

## 2. Cambios al modelo

### 2.1 `tipo_clase` opcional (`None` = "sin determinar")

Archivos: `src/database/models.py`, `src/services/plan_generation_service.py`, `src/services/schedule_service.py`, `app/pages/5_📊_Planes.py`, `app/pages/6_📅_Cronogramas.py`.

- `ScheduleEntryDB.tipo_clase`, `HorarioDB.tipo_clase`, `ClaseDB.tipo_clase` ahora son `Optional[str]` con default `None`.
- Semántica:
  - `None` → "sin determinar": el LP decide.
  - `"teorica"` → predeterminado como teoría (no toca laboratorio fijo).
  - `"laboratorio"` → predeterminado como laboratorio (debe asignarse a un lab compatible).
- En la UI los selectbox/`SelectboxColumn` de tipo agregan la opción `"sin determinar"`. Al guardar se mapea `"sin determinar" → None`.
- No fue necesaria una migración de SQLite: las columnas ya permitían `NULL` (`notnull=0`); sólo cambió el default en el modelo Python.

### 2.2 `horas_teoria` y `horas_laboratorio` en `MateriaDB`

Archivos: `src/database/models.py`, `src/database/connection.py`, `src/domain/problem/materia.py`, `src/ui/materia_form_renderer.py`, `app/pages/1_📚_Materias.py`.

- Se agregan los campos `horas_teoria: Optional[float]` y `horas_laboratorio: Optional[float]`, ambos `>= 0`.
- Restricción funcional: `horas_teoria + horas_laboratorio == horas_semanales`. Se valida al crear/editar materia y se bloquea el guardado si no se cumple.
- Default en `init_db()`: `horas_teoria = horas_semanales`, `horas_laboratorio = 0` para materias preexistentes (idempotente: sólo actualiza filas con `horas_teoria IS NULL`).
- Caso "reserva": `horas_laboratorio = 0` pero la materia tiene laboratorios compatibles → la materia **no entra al LP**, se reserva un laboratorio sin restringir el horario.

---

## 3. Nueva validación: factibilidad de partición de horas

Archivo: `src/services/validations.py`.

### 3.1 Función

```python
def validar_factibilidad_particion_horas(
    session: Session,
    schedule_id: str | None = None,
    plan_cursada_id: str | None = None,
) -> ValidationResult: ...
```

Verifica, para cada comisión cuya materia tiene `horas_laboratorio > 0`, que las clases de esa comisión puedan particionarse en dos subconjuntos cuyas duraciones sumen `horas_teoria` y `horas_laboratorio` respectivamente.

### 3.2 Reglas

1. **Skip**: materias con `horas_laboratorio is None` o `== 0` se ignoran (no requieren laboratorio fijo).
2. **Consistencia de predeterminados**:
   - `Σ duraciones predeterminadas como "laboratorio" ≤ horas_laboratorio`.
   - `Σ duraciones predeterminadas como "teorica" ≤ horas_teoria`.
3. **Total**: `Σ todas las duraciones == horas_teoria + horas_laboratorio` (tolerancia 0.01h).
4. **Subset-sum**: existe un subconjunto de las duraciones que suma exactamente `horas_laboratorio` (DP discretizado a cuartos de hora, escala = 4).

### 3.3 Helper

```python
def _subset_sum_exists(values: list[float], target: float, tol: float = 0.01) -> bool:
    """DP O(n*sum) sobre cuartos de hora."""
```

### 3.4 Integración en UI

Archivo: `app/pages/5_📊_Planes.py`.

- Se importa `validar_factibilidad_particion_horas` junto al resto de validaciones.
- Al presionar **Prevalidar cronograma contra ciclo**, además del resumen de cobertura se ejecuta la validación de partición y se persiste en `st.session_state[_prevalidation_key]` con las claves: `particion_valid`, `particion_message`, `particion_details`.
- En el render del resumen: si `particion_valid` es `True` se muestra `st.success` con el mensaje; si es `False` se muestra `st.error` y un expander con los detalles (una línea por comisión infactible).

---

## 4. Vistas y editores complementarios

- **Cronogramas → Visualizar**: nuevo modo "Por materia" con selector de materia y coloreado por comisión (ver `src/ui/calendar_render.py:render_schedule_calendar(color_by_comision=True)`).
- **Aulas**: tab de detalle muestra editor de materias compatibles para aulas tipo laboratorio (M:N sobre `MateriaLaboratorioDB`); tab de listado muestra resumen inverso lab → materias.

---

## 5. Qué puede romperse

- Código que asuma `tipo_clase != None` (por ejemplo comparaciones directas con strings) puede ahora caer en ramas no anticipadas. Búsqueda recomendada: `tipo_clase ==`, `tipo_clase !=`, `getattr(..., "tipo_clase", "teorica")`.
- La validación de partición es estricta sobre la suma total: cronogramas legacy con `horas_teoria + horas_laboratorio != horas_semanales` aparecerán como infactibles. Se mitigó con el seed por defecto (`horas_teoria = horas_semanales`, `horas_laboratorio = 0`).
- El subset-sum DP usa cuartos de hora; duraciones más finas (5 min) se redondearían y darían falsos negativos. No esperado en datos actuales (todos los slots son de 30 min o más).

## 6. Tests sugeridos

- `validar_factibilidad_particion_horas` con casos:
  - Materia sin `horas_laboratorio` → skip.
  - Comisión con duraciones `[2, 2]` y `ht=2, hl=2` → válido.
  - Comisión con duraciones `[3, 1]` y `ht=2, hl=2` → infactible (no hay subset que sume 2).
  - Predeterminados inconsistentes (`pre_lab_sum > hl`) → infactible con mensaje específico.
  - Total mismatch (`Σ != ht+hl`) → infactible con mensaje específico.
- Round-trip de `tipo_clase = None` en `ScheduleEntryDB` (insert + read).
- Crear/editar materia con `horas_teoria + horas_laboratorio != horas_semanales` → form bloquea con warning.
