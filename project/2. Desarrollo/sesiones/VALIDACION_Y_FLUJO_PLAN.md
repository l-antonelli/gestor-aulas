# Sesión: Validación por Comisión y Refactor del Flujo Schedule → Plan

> **Fecha**: 2026-04-17
> **Branch**: `fix/validaciones-plan-cursada`
> **Estado**: Implementado

---

## 1. Problema Original

Al validar el plan 2026-1C, el sistema reportaba **882 conflictos de horario falsos**. La causa raíz era que `validar_conflictos_horarios_plan()` comparaba **todos** los horarios de **todas** las comisiones de una materia como una bolsa única. En la realidad, un alumno cursa **una sola comisión** por materia. Si existe al menos un par de comisiones compatible (una de cada materia), no hay conflicto real.

### Ejemplo concreto

```
Materia M1:
  Comisión 1: Lunes 8-10
  Comisión 2: Martes 8-10

Materia M2:
  Comisión 1: Lunes 8-10
```

El algoritmo viejo reportaba conflicto (`M1 vs M2 — Lunes 8-10`) porque M1-Com1 solapa con M2-Com1. Pero un alumno puede cursar M1-Com2 (Martes) + M2-Com1 (Lunes) sin conflicto.

---

## 2. Solución Implementada

### 2.1 Algoritmo de validación por comisión (Fase 1)

**Archivo**: `src/services/validations.py`

Se refactorizó `validar_conflictos_horarios_plan()` para usar **compatibilidad pairwise entre comisiones**:

1. Se construyen dos índices:
   - `horarios_por_comision: dict[comision_id, list[HorarioDB]]`
   - `comisiones_por_materia: dict[materia_codigo, list[comision_id]]`

2. Helper `_comisiones_son_compatibles(h_com_a, h_com_b)`: retorna `True` si ningún par de horarios se superpone.

3. Para cada par de materias `(mat1, mat2)` en el mismo grupo curricular: se verifica si **existe al menos un par de comisiones** (una de cada materia) que sea compatible. Si no existe ninguno → conflicto real.

**Limitación conocida**: el check pairwise es condición necesaria pero no suficiente para grupos de >2 materias. Ejemplo: M1 compatible con M2, M2 compatible con M3, pero no existe asignación simultánea válida para M1+M2+M3. Este es un edge case raro en la práctica dado que los horarios de una carrera tienden a estar diseñados para evitar conflictos multi-materia.

### 2.2 Concepto `max_clases_paralelas` (Fase 2)

**Archivo**: `src/services/plan_generation_service.py`

Se renombró `max_duplicados` → `max_clases_paralelas` en `MateriaPreview` y en toda la lógica.

Se agregó una **regla constraint** en `_derive_comisiones()`: si `max_clases_paralelas > n_comisiones` (derivado por las reglas de ratio/optativa/exclusiva), se fuerza `n_comisiones = max_clases_paralelas` con flag `"needs_more_comisiones"`. Esta regla aplica uniformemente a optativas, exclusivas y compartidas.

Esto corrige el caso donde entries con auto-solapamiento (mismo slot, distinta comisión) no eran detectados como indicadores de múltiples comisiones.

### 2.3 Persistencia de ediciones del preview (Fase 3)

**Archivo**: `src/services/schedule_service.py`

Nueva función `sync_preview_edits_to_schedule()` que sincroniza las ediciones del data_editor del preview con la base de datos:

- `entry_id` existente → `update_schedule_entry()`
- `entry_id` con prefijo `"new_"` → `add_schedule_entry()`
- `entry_id` en DB pero no en la lista editada → `delete_schedule_entry()`

En la UI, se agregó un radio "Al cronograma original" / "Crear copia" antes de aplicar cambios. Si el usuario elige copia, se llama `duplicate_schedule()` antes del sync.

### 2.4 Simplificación del flujo de generación (Fase 4)

**Archivo**: `app/pages/5_📊_Planes.py`

El botón "Confirmar y generar plan" ahora:
1. Obtiene el `effective_schedule_id` (original o copia del Phase 3)
2. Re-deriva el preview fresco desde la DB (que ya tiene los edits persistidos)
3. Aplica overrides del usuario (n_comisiones, horas_semanales)
4. Genera el plan referenciando el schedule correcto

### 2.5 Data editor en tab Detalle (Fase 5)

**Archivos**: `src/services/plan_generation_service.py`, `app/pages/5_📊_Planes.py`

Nueva función `apply_horario_edits()` para ediciones bulk de horarios dentro de un plan existente.

En el tab Detalle, cada materia ahora tiene un `st.data_editor` consolidado con todos los horarios de todas las comisiones, permitiendo:
- Editar día/hora/comisión de horarios existentes
- Agregar nuevos horarios
- Eliminar horarios

---

## 3. Tests Agregados

### test_validations.py (4 tests nuevos)

| Test | Descripción |
|------|-------------|
| `test_multi_comision_compatible_no_conflict` | Compatible vía comisión alternativa → `valid=True` |
| `test_multi_comision_all_overlap_is_conflict` | Todas las comisiones solapan → `valid=False` |
| `test_single_comision_overlap_detected` | Regresión: 1 comisión con overlap → `valid=False` |
| `test_single_comision_no_overlap` | Regresión: 1 comisión sin overlap → `valid=True` |

### test_plan_generation_service.py (9 tests nuevos)

| Test | Descripción |
|------|-------------|
| `test_max_paralelas_forces_minimum_comisiones` | 3 entries paralelos fuerzan 3 comisiones |
| `test_exclusive_carrera_with_parallel_classes` | Exclusiva con 2 paralelos → 2 comisiones |
| `test_optativa_respects_paralelas` | Optativa con 2 paralelos → 2 comisiones |
| `test_no_paralelas_optativa_stays_1` | Optativa sin paralelos → 1 comisión |
| `test_shared_materia_exact_ratio_no_paralelas` | Ratio exacto sin paralelos → derivación normal |
| `test_update_existing_horario` | Actualización de horario existente |
| `test_create_new_horario` | Creación de horario nuevo |
| `test_delete_removed_horario` | Eliminación de horario |
| `test_mixed_operations` | Update + create + delete combinados |

### test_schedule_service.py (4 tests nuevos)

| Test | Descripción |
|------|-------------|
| `test_sync_updates_existing_entry` | Update de entry existente |
| `test_sync_creates_new_entry` | Creación de entry nuevo |
| `test_sync_deletes_removed_entry` | Eliminación de entry |
| `test_sync_mixed_operations` | Operaciones combinadas |

---

## 4. Flujo Refactorizado

```
Schedule (cronograma)
  ↓ cargar archivo
ScheduleEntries (en DB)
  ↓ previsualizar
Preview (MateriaPreview[] en session_state)
  ↓ editar entries en data_editor
  ↓ aceptar → sync_preview_edits_to_schedule() → ScheduleEntries actualizados
  ↓ confirmar y generar
preview_plan_from_schedule() → MateriaPreview[] frescos desde DB
  ↓
generate_plan_from_preview() → PlanificacionCursada + Comisiones + Horarios
  ↓ en tab Detalle
  ↓ data_editor por materia → apply_horario_edits()
  ↓ validar
validar_conflictos_horarios_plan() (por comisión) → conflictos reales
  ↓ activar
plan.activo = True
```

---

## 5. Archivos Modificados

| Archivo | Cambios |
|---------|---------|
| `src/services/validations.py` | Refactor validación por comisión, helper `_comisiones_son_compatibles` |
| `src/services/plan_generation_service.py` | Rename `max_duplicados` → `max_clases_paralelas`, constraint paralelas, `apply_horario_edits()` |
| `src/services/schedule_service.py` | Nueva función `sync_preview_edits_to_schedule()` |
| `app/pages/5_📊_Planes.py` | UI: radio aplicar/copia, sync en accept, flujo simplificado, data_editor en detalle |
| `tests/test_validations.py` | 4 tests nuevos |
| `tests/test_plan_generation_service.py` | 9 tests nuevos |
| `tests/test_schedule_service.py` | 4 tests nuevos |
