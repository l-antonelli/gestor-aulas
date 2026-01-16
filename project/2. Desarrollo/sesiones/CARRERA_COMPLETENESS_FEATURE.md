# Feature: Carrera Completeness Tracking

## Overview

This feature adds the ability to track and validate the completeness of carreras based on the number of materias assigned. It provides visual indicators and warnings to help ensure that all carreras have the expected number of materias configured.

## Business Requirements

### Problem Statement

The system needed a way to:
1. Define the expected number of materias for each carrera
2. Track how many materias are actually assigned to each carrera
3. Provide visual feedback on completeness status
4. Alert users when carreras are incomplete or missing configuration

### Solution

Added a `cantidad_materias` field to the Carrera entity that allows administrators to specify the expected total number of materias in the curriculum. The system then validates and displays the completeness status throughout the UI.

## Changes Made

### 1. Domain Model Updates

**File:** `src/domain/problem/carrera.py`

Added new field:
```python
cantidad_materias: Optional[int] = Field(
    default=None,
    ge=1,
    description="Expected total number of materias in the curriculum"
)
```

**Features:**
- Optional field (can be None if not yet defined)
- Must be >= 1 if specified
- Represents the total expected materias in the curriculum

### 2. Database Model Updates

**File:** `src/database/models.py`

Added corresponding database field:
```python
cantidad_materias: Optional[int] = Field(default=None, ge=1)
```

**Migration:**
- Column added to existing `carreras` table via ALTER TABLE
- Existing records have NULL value (not yet defined)
- No data loss or breaking changes

### 3. Converter Updates

**File:** `src/database/converters.py`

Updated converters to include new fields:
- `to_db()` for Carrera: includes `cantidad_materias`
- `to_domain()` for Carrera: includes `cantidad_materias`
- `to_db()` for Materia: includes `periodo`, `anio_carrera`, `cuatrimestre_carrera`
- `to_domain()` for Materia: includes `periodo`, `anio_carrera`, `cuatrimestre_carrera`

### 4. Validation Service

**File:** `src/services/carrera_validation.py`

New validation service with:

#### CarreraValidationStatus Class

Encapsulates validation status for a carrera:

**Properties:**
- `tiene_cantidad_definida`: Whether cantidad_materias is set
- `esta_completa`: Whether all expected materias are assigned
- `porcentaje_completitud`: Percentage of materias assigned (0-100%)
- `materias_faltantes`: Number of missing materias
- `nivel_advertencia`: Warning level ("success", "warning", "error")

**Methods:**
- `get_mensaje_estado()`: Human-readable status message

#### Validation Functions

- `get_carrera_status(session, carrera_codigo)`: Get status for one carrera
- `get_all_carreras_status(session)`: Get status for all carreras
- `get_carreras_incompletas(session)`: Get incomplete carreras
- `get_carreras_sin_cantidad_definida(session)`: Get carreras without cantidad_materias
- `get_validation_summary(session)`: Get summary statistics

### 5. UI Widget

**File:** `src/ui/carrera_status_widget.py`

New UI components for displaying carrera status:

#### CarreraStatusWidget Class

**Methods:**
- `render_status_badge(status)`: Colored badge with status message
- `render_progress_bar(status)`: Progress bar showing completeness
- `render_status_card(status)`: Complete card with all details
- `render_summary_metrics(session)`: Summary metrics for all carreras
- `render_warnings_panel(session)`: Panel showing incomplete carreras
- `render_inline_status(session, carrera_codigo)`: Compact inline status

**Visual Elements:**
- ✅ Green for complete carreras
- ⚠️ Yellow for incomplete carreras
- ❌ Red for carreras without cantidad_materias defined
- Progress bars showing X/Y materias
- Percentage indicators

### 6. Enhanced Materia Page

**File:** `app/pages/1_📚_Materias.py`

Added completeness panel at the top:

```python
with st.expander("📊 Estado de Completitud de Carreras", expanded=False):
    CarreraStatusWidget.render_summary_metrics(session)
    st.divider()
    CarreraStatusWidget.render_warnings_panel(session)
```

**Features:**
- Collapsible panel (not expanded by default)
- Summary metrics showing total/complete/incomplete carreras
- Warnings panel listing problematic carreras
- Helpful suggestions for resolving issues

### 7. Enhanced Carrera Page

**File:** `app/pages/7_🎓_Carreras.py`

Added:
- `cantidad_materias` field to display and edit forms
- Inline status widget when viewing carrera details
- Progress bar showing materia assignment progress

## User Interface

### Materia Page - Completeness Panel

**Summary Metrics:**
```
┌─────────────────────────────────────────────────────────┐
│ Total Carreras │ Completas │ Incompletas │ Sin Cantidad │
│       5        │     3     │      1      │      1       │
│                │   60%     │     ⚠️      │     ❌       │
└─────────────────────────────────────────────────────────┘
```

**Warnings Panel:**

❌ **Carreras sin cantidad de materias definida (1)**
- ING005: Ingeniería Química (15 materias asignadas)
- 💡 Defina la cantidad esperada de materias para cada carrera en la página de Carreras.

⚠️ **Carreras incompletas (1)**
- ING001: Ingeniería Civil
  [████████░░] 25/40
- 💡 Asigne las materias faltantes en la página de Materias.

### Carrera Page - Status Display

When viewing a carrera's materias:

```
Estado de Completitud
[████████████████░░] 80%
32/40 materias        ⚠️ Faltan 8
```

### Carrera Form - New Field

**Cantidad de Materias** (optional)
- Number input
- Minimum value: 1
- Help text: "Cantidad total esperada de materias en el plan de estudios"

## Validation Rules

### Status Levels

1. **Success (✅)**: 
   - `cantidad_materias` is defined
   - All expected materias are assigned
   - `materias_asignadas >= cantidad_materias`

2. **Warning (⚠️)**:
   - `cantidad_materias` is defined
   - Some materias assigned but not all
   - `0 < materias_asignadas < cantidad_materias`

3. **Error (❌)**:
   - `cantidad_materias` is not defined (NULL)
   - OR no materias assigned

### Completeness Calculation

```python
porcentaje = (materias_asignadas / cantidad_materias) * 100
esta_completa = materias_asignadas >= cantidad_materias
materias_faltantes = max(0, cantidad_materias - materias_asignadas)
```

## Usage Examples

### Setting Expected Materia Count

1. Go to "🎓 Carreras" page
2. Create or edit a carrera
3. Set "Cantidad de Materias" field (e.g., 40)
4. Save

### Viewing Completeness Status

**Option 1: From Materia Page**
1. Go to "📚 Materias" page
2. Expand "📊 Estado de Completitud de Carreras"
3. View summary and warnings

**Option 2: From Carrera Page**
1. Go to "🎓 Carreras" page
2. Select a carrera from "📚 Materias por Carrera"
3. View inline status widget

### Resolving Warnings

**For carreras without cantidad_materias:**
1. Edit the carrera
2. Set the expected number of materias
3. Save

**For incomplete carreras:**
1. Go to "📚 Materias" page
2. Create missing materias
3. Assign them to the carrera using the multi-select

## Database Schema

### Migration Applied

```sql
ALTER TABLE carreras 
ADD COLUMN cantidad_materias INTEGER DEFAULT NULL;
```

### Table Structure

```sql
CREATE TABLE carreras (
    codigo TEXT PRIMARY KEY,
    nombre TEXT NOT NULL,
    titulo_otorgado TEXT DEFAULT '',
    duracion_anios INTEGER DEFAULT 5,
    cantidad_materias INTEGER DEFAULT NULL,  -- NEW FIELD
    CHECK (duracion_anios >= 1),
    CHECK (cantidad_materias IS NULL OR cantidad_materias >= 1)
);
```

## API Reference

### CarreraValidationStatus

```python
status = get_carrera_status(session, "ING001")

# Properties
status.tiene_cantidad_definida  # bool
status.esta_completa            # bool
status.porcentaje_completitud   # float (0-100)
status.materias_faltantes       # int
status.nivel_advertencia        # str: "success", "warning", "error"

# Methods
status.get_mensaje_estado()     # str: Human-readable message
```

### Validation Functions

```python
from src.services.carrera_validation import (
    get_carrera_status,
    get_all_carreras_status,
    get_carreras_incompletas,
    get_carreras_sin_cantidad_definida,
    get_validation_summary,
)

# Get status for one carrera
status = get_carrera_status(session, "ING001")

# Get all statuses
all_statuses = get_all_carreras_status(session)

# Get incomplete carreras
incompletas = get_carreras_incompletas(session)

# Get carreras without cantidad_materias
sin_cantidad = get_carreras_sin_cantidad_definida(session)

# Get summary
summary = get_validation_summary(session)
# Returns: {
#     "total_carreras": 5,
#     "carreras_completas": 3,
#     "carreras_incompletas": 1,
#     "carreras_sin_cantidad": 1,
#     "porcentaje_completas": 60.0
# }
```

### UI Widgets

```python
from src.ui.carrera_status_widget import CarreraStatusWidget

# Render summary metrics
CarreraStatusWidget.render_summary_metrics(session)

# Render warnings panel
CarreraStatusWidget.render_warnings_panel(session)

# Render inline status for a carrera
CarreraStatusWidget.render_inline_status(session, "ING001")

# Render complete status card
status = get_carrera_status(session, "ING001")
CarreraStatusWidget.render_status_card(status, show_details=True)
```

## Benefits

### For Administrators

1. **Visibility**: Clear view of which carreras are complete
2. **Validation**: Automatic checking of materia assignments
3. **Guidance**: Helpful messages and suggestions
4. **Progress Tracking**: Visual progress bars and percentages

### For Data Quality

1. **Completeness**: Ensures all carreras have expected materias
2. **Consistency**: Validates curriculum structure
3. **Early Detection**: Identifies missing materias before they cause problems
4. **Documentation**: cantidad_materias serves as curriculum documentation

### For System Integrity

1. **Validation**: Prevents incomplete curriculum configurations
2. **Alerts**: Proactive warnings about data issues
3. **Reporting**: Summary statistics for oversight
4. **Audit Trail**: Clear indication of configuration status

## Future Enhancements

Possible improvements:

1. **Historical Tracking**: Track changes to cantidad_materias over time
2. **Bulk Updates**: Set cantidad_materias for multiple carreras at once
3. **Import/Export**: CSV import for cantidad_materias values
4. **Notifications**: Email alerts when carreras become incomplete
5. **Dashboard**: Dedicated dashboard for curriculum completeness
6. **Reports**: Exportable reports on carrera status
7. **Validation Rules**: Custom rules per carrera (e.g., required materias)
8. **Auto-calculation**: Suggest cantidad_materias based on plan de estudios

## Testing

Test coverage includes:

1. ✅ Domain model validation (cantidad_materias >= 1)
2. ✅ Database field creation and migration
3. ✅ Converter bidirectional conversion
4. ✅ Validation status calculation
5. ✅ Completeness percentage calculation
6. ✅ Warning level determination
7. ✅ Summary statistics generation
8. ✅ UI widget rendering

## Related Documentation

- `CARRERA_MATERIA_IMPLEMENTATION.md`: Carrera-Materia relationship implementation
- `project/modelo-er.md`: Complete ER model documentation
- `src/services/validations.py`: Other validation functions
