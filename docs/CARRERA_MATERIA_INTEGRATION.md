# Carrera-Materia Integration Documentation

## Overview

This document describes the many-to-many relationship between Carrera and Materia entities, including the schema design, business rules, and implementation details.

## Schema Design

### Link Table: `materia_carrera`

The relationship between Materia and Carrera is implemented using a link table with additional curriculum placement attributes:

```sql
CREATE TABLE materia_carrera (
    materia_codigo VARCHAR NOT NULL,
    carrera_codigo VARCHAR NOT NULL,
    anio_carrera INTEGER NOT NULL DEFAULT 1,
    cuatrimestre_carrera INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (materia_codigo, carrera_codigo),
    FOREIGN KEY(materia_codigo) REFERENCES materias (codigo),
    FOREIGN KEY(carrera_codigo) REFERENCES carreras (codigo),
    CHECK (anio_carrera >= 1 AND anio_carrera <= 6),
    CHECK (cuatrimestre_carrera >= 1 AND cuatrimestre_carrera <= 2)
)
```

### Key Design Decisions

1. **Curriculum Placement in Link Table**: The `anio_carrera` (year) and `cuatrimestre_carrera` (semester) fields are stored in the link table rather than in the `materias` table. This is because:
   - The same materia can appear in different years/semesters depending on the carrera
   - Example: "Matemática I" might be in Year 1 for Engineering but Year 2 for another program
   - This provides maximum flexibility for curriculum design

2. **Constraints**:
   - `anio_carrera`: 1-6 (supports up to 6-year programs)
   - `cuatrimestre_carrera`: 1-2 (semester 1 or 2)
   - For annual materias (periodo="anual"), the cuatrimestre_carrera is typically set to 1 by convention

## Business Rules

### RN1: Materia Must Have At Least One Carrera

Every materia must be associated with at least one carrera. This is enforced at the service layer:

- `MateriaService.set_carreras()` validates that the list is not empty
- UI forms require at least one carrera selection
- Validation error is raised if attempting to create/update a materia without carreras

### RN2: Carrera Completeness Tracking

Carreras have an optional `cantidad_materias` field that represents the expected total number of materias in the curriculum. The system tracks:

- **Completeness Percentage**: (actual materias / expected materias) × 100
- **Status**: Complete, Incomplete, or Undefined (if cantidad_materias not set)
- **Warnings**: Displayed in UI when carreras are incomplete

## Service Layer API

### MateriaService

#### `get_carreras(session, materia_codigo) -> List[Carrera]`
Get all carreras associated with a materia.

#### `set_carreras(session, materia_codigo, carrera_codigos) -> bool`
Replace all carrera associations for a materia. Creates links with default values (year=1, semester=1).

**Raises**: `ValidationError` if carrera_codigos is empty (RN1)

#### `add_carrera(session, materia_codigo, carrera_codigo, anio_carrera=1, cuatrimestre_carrera=1) -> bool`
Add a single carrera association with specific year and semester placement.

**Returns**: `True` if created, `False` if already exists

#### `remove_carrera(session, materia_codigo, carrera_codigo) -> bool`
Remove a carrera association.

**Returns**: `True` if removed, `False` if didn't exist

### CarreraService

#### `get_materias(session, carrera_codigo) -> List[Materia]`
Get all materias associated with a carrera (without year/semester info).

#### `get_materias_by_year_and_semester(session, carrera_codigo, anio, cuatrimestre=None) -> List[Tuple[Materia, int, int]]`
Get materias for a specific year and optionally semester.

**Returns**: List of tuples `(Materia, anio_carrera, cuatrimestre_carrera)`

**Example**:
```python
# Get all materias for year 2
materias = carrera_service.get_materias_by_year_and_semester(session, "ING001", 2)

# Get only semester 1 materias for year 2
materias = carrera_service.get_materias_by_year_and_semester(session, "ING001", 2, 1)
```

#### `add_materia(session, carrera_codigo, materia_codigo, anio_carrera=1, cuatrimestre_carrera=1) -> bool`
Add a materia to a carrera with specific year and semester placement.

**Returns**: `True` if created, `False` if already exists

#### `remove_materia(session, carrera_codigo, materia_codigo) -> bool`
Remove a materia from a carrera.

**Returns**: `True` if removed, `False` if didn't exist

## UI Implementation

### Materias Page (`app/pages/1_📚_Materias.py`)

- **Create/Edit Forms**: Use `MateriaFormRenderer` with `ManyToManySelector` for carrera selection
- **Validation**: Enforces RN1 (at least one carrera required)
- **Completeness Panel**: Shows carrera status summary and warnings

### Carreras Page (`app/pages/7_🎓_Carreras.py`)

#### Tab 1: Lista
- List all carreras with inline editing
- Shows completeness status for each carrera
- Delete with validation (prevents deletion if materias are associated)

#### Tab 2: Crear
- Form to create new carrera
- Includes `cantidad_materias` field for completeness tracking

#### Tab 3: Planes de Estudio
**Year-Based Curriculum View** with 3-column layout:

1. **Year Selector**: Dropdown to select year 1-6
2. **Three Columns**:
   - **Anuales**: Materias with periodo="anual"
   - **1er Cuatrimestre**: Materias with cuatrimestre_carrera=1
   - **2do Cuatrimestre**: Materias with cuatrimestre_carrera=2

Each column has:
- Expandable section showing associated materias
- Delete button to disassociate materias
- Form to add new materias with pre-filled year/semester values

**Key Features**:
- Materias are filtered by both year and period type
- Adding a materia automatically sets the correct year and semester
- Only shows materias not already associated with the carrera
- Respects materia periodo (anual vs cuatrimestral)

## Migration History

### Migration: `migrate_materia_carrera_schema.py`

**Date**: Applied during schema refactoring

**Changes**:
1. Added `anio_carrera` and `cuatrimestre_carrera` columns to `materia_carrera` table
2. Removed `anio_carrera` and `cuatrimestre_carrera` columns from `materias` table
3. Migrated existing data with default values (year=1, semester=1)

**Results**:
- Preserved all existing materia-carrera associations
- All existing materias retained their data
- No data loss

## Testing

Comprehensive tests verify:
- ✓ Adding materias to different years and semesters
- ✓ Querying materias by year and semester
- ✓ Getting all materias for a carrera
- ✓ Bidirectional relationship (Materia→Carrera and Carrera→Materia)
- ✓ Removing associations
- ✓ Validation rules (RN1)

## Future Enhancements

Potential improvements:
1. **Correlatividades**: Add prerequisite relationships between materias
2. **Bulk Operations**: Import/export curriculum plans
3. **Version Control**: Track changes to curriculum over time
4. **Materia Reordering**: Drag-and-drop interface for curriculum planning
5. **Curriculum Templates**: Copy curriculum structure between carreras
