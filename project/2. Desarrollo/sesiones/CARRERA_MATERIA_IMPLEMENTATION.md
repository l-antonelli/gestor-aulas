# Carrera-Materia Relationship Implementation

## Overview

This document describes the implementation of the many-to-many relationship between Carrera and Materia entities in the classroom assignment system, including UI components for managing this relationship.

## Changes Made

### 1. Extended MateriaService with Carrera Relationship Methods

**File:** `src/services/crud_services.py`

Added the following methods to `MateriaService`:

- `get_carreras(session, materia_codigo)`: Get all carreras associated with a materia
- `set_carreras(session, materia_codigo, carrera_codigos)`: Set carreras for a materia (replaces existing)
- `add_carrera(session, materia_codigo, carrera_codigo)`: Add a single carrera association
- `remove_carrera(session, materia_codigo, carrera_codigo)`: Remove a carrera association

**Key Features:**
- Validates that at least one carrera is assigned (business rule RN1)
- Checks for entity existence before creating associations
- Handles duplicate associations gracefully
- Uses the `MateriaCarreraLink` table for M:M relationships

### 2. Created Many-to-Many Selector Component

**File:** `src/ui/many_to_many_selector.py`

New UI component for handling many-to-many relationships:

- `ManyToManySelector.render_many_to_many_selector()`: Generic M:M selector
- `ManyToManySelector.render_carrera_selector_for_materia()`: Specialized carrera selector

**Features:**
- Multi-select dropdown with entity display
- Validation for required selections
- Integration with relationship metadata
- Reusable for other M:M relationships

### 3. Created Specialized Materia Form Renderer

**File:** `src/ui/materia_form_renderer.py`

Custom form renderer for Materia entities with carrera selection:

- `render_materia_create_form()`: Create form with carrera selection
- `render_materia_update_form()`: Update form with current carreras pre-selected
- `create_materia_with_carreras()`: Create materia and set carrera associations
- `update_materia_with_carreras()`: Update materia and carrera associations

**Features:**
- Integrates standard form fields with carrera multi-select
- Validates that at least one carrera is selected
- Handles form submission and database operations
- Shows current carrera associations when editing

### 4. Updated Materia Domain Model

**File:** `src/domain/problem/materia.py`

Added missing fields to match the database model:

- `periodo`: "anual" or "cuatrimestral" (default: "cuatrimestral")
- `anio_carrera`: Year in curriculum (1-6, default: 1)
- `cuatrimestre_carrera`: Semester in curriculum (1-2, default: 1)

These fields are essential for:
- Validating schedule feasibility (RN2 in modelo-er.md)
- Organizing materias within the curriculum
- Supporting the validation system

### 5. Enhanced Materia Page UI

**File:** `app/pages/1_📚_Materias.py`

Completely redesigned the Materia page with:

**List Tab:**
- Shows all materias with their associated carreras
- Warning indicator for materias without carreras
- Edit and delete buttons for each materia
- Inline editing and deletion with confirmation

**Create Tab:**
- Custom form with carrera multi-select
- Validation for all fields including carrera selection
- Success feedback with automatic page refresh

**Search Tab:**
- Search by codigo or nombre
- Filtered results display

## Validation Rules Implemented

### Business Rule RN1: Materia Must Have at Least One Carrera

**Implementation:**
- `MateriaService.set_carreras()` raises `ValidationError` if no carreras provided
- UI form validation prevents submission without carrera selection
- Error messages guide users to select at least one carrera

**Validation Points:**
1. Form submission (client-side)
2. Service layer (server-side)
3. Database constraints (via relationship metadata)

## Database Schema

The many-to-many relationship uses the existing `MateriaCarreraLink` table:

```sql
CREATE TABLE materia_carrera (
    materia_codigo TEXT NOT NULL,
    carrera_codigo TEXT NOT NULL,
    PRIMARY KEY (materia_codigo, carrera_codigo),
    FOREIGN KEY (materia_codigo) REFERENCES materias(codigo),
    FOREIGN KEY (carrera_codigo) REFERENCES carreras(codigo)
);
```

## Usage Examples

### Creating a Materia with Carreras

```python
from src.services.crud_services import materia_service
from src.domain.problem.materia import Materia

# Create materia
materia = Materia(
    codigo="MAT101",
    nombre="Matemática I",
    cupo=50,
    horas_semanales=6,
    periodo="cuatrimestral",
    anio_carrera=1,
    cuatrimestre_carrera=1
)

with get_session() as session:
    # Create in database
    created = materia_service.create(session, materia)
    
    # Associate with carreras
    materia_service.set_carreras(session, "MAT101", ["ING001", "ING002"])
```

### Getting Carreras for a Materia

```python
with get_session() as session:
    carreras = materia_service.get_carreras(session, "MAT101")
    for carrera in carreras:
        print(f"{carrera.codigo}: {carrera.nombre}")
```

### UI Usage

1. Navigate to "📚 Materias" page
2. Click "➕ Crear" tab
3. Fill in materia details
4. Select one or more carreras from the multi-select dropdown
5. Click "Crear Materia"

## Testing

A test script is provided: `test_carrera_integration.py`

Run with:
```bash
python test_carrera_integration.py
```

This tests:
- Creating carreras and materias
- Associating materias with carreras
- Retrieving carreras for a materia
- Retrieving materias for a carrera

## Architecture Alignment

This implementation follows the architecture described in `project/modelo-er.md`:

- **Domain of Problem (Delimited)**: Materia and Carrera are core entities
- **Domain of Solution**: MateriaCarreraLink materializes the M:M relationship
- **Validation Layer**: Enforces RN1 (materia must have at least one carrera)
- **Service Layer**: Encapsulates business logic and database operations
- **UI Layer**: Provides intuitive interface for managing relationships

## Future Enhancements

Possible improvements:

1. **Bulk Operations**: Add/remove multiple materias to/from a carrera at once
2. **Validation Dashboard**: Show materias without carreras in a dedicated view
3. **Import/Export**: CSV import for bulk materia-carrera associations
4. **History Tracking**: Track changes to materia-carrera associations over time
5. **Conflict Detection**: Warn when removing a carrera would violate constraints

## Related Documentation

- `project/modelo-er.md`: Complete ER model documentation
- `src/services/relationship_definitions.py`: Relationship metadata definitions
- `src/services/validations.py`: Validation functions including carrera checks
