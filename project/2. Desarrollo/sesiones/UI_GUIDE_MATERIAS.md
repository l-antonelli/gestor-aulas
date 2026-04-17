# UI Guide: Materia Management with Carrera Assignment

## Overview

The enhanced Materia page now includes full support for managing the many-to-many relationship between Materias and Carreras, with validation to ensure every materia is assigned to at least one carrera.

## Page Structure

The Materia page is organized into three tabs:

### 1. 📋 Lista (List)

**Purpose:** View all materias with their associated carreras

**Features:**
- Expandable cards for each materia
- Two-column layout showing:
  - Left: Basic info (código, nombre, período, año, cuatrimestre)
  - Right: Capacity info (cupo, horas/semana) and **associated carreras**
- Warning indicator (⚠️) for materias without carreras
- Edit and Delete buttons for each materia

**Carrera Display:**
```
Carreras: ING001 - Ingeniería Civil, ING002 - Ingeniería Mecánica
```

**Actions:**
- ✏️ Edit: Opens inline edit form with current values pre-populated
- 🗑️ Delete: Shows confirmation dialog before deletion

### 2. ➕ Crear (Create)

**Purpose:** Create new materias with carrera assignment

**Form Fields:**

1. **Código** (required)
   - Text input
   - Unique identifier for the materia

2. **Nombre** (required)
   - Text input
   - Full name of the materia

3. **Cupo** (required)
   - Number input (must be > 0)
   - Maximum student capacity

4. **Horas Semanales** (required)
   - Number input (must be > 0)
   - Weekly hours

5. **Período** (required)
   - Select: "anual" or "cuatrimestral"
   - Default: "cuatrimestral"

6. **Año** (required)
   - Number input (1-6)
   - Suggested year in curriculum
   - Default: 1

7. **Cuatrimestre** (required)
   - Number input (1-2)
   - Suggested semester
   - Default: 1

8. **Carreras** (required) ⭐ NEW
   - Multi-select dropdown
   - Shows all available carreras
   - Format: "CODIGO - Nombre"
   - **Must select at least one**

**Validation:**
- All fields validated on submission
- Error messages displayed for invalid inputs
- Special validation for carrera selection:
  ```
  ❌ Debe seleccionar al menos una carrera
  ```

**Success Flow:**
1. Fill in all fields
2. Select one or more carreras
3. Click "Crear Materia"
4. Success message: "✅ Materia creada exitosamente"
5. Page refreshes to show new materia

### 3. 🔍 Buscar (Search)

**Purpose:** Search for materias by código or nombre

**Features:**
- Text input for search term
- Case-insensitive search
- Searches both código and nombre fields
- Results displayed as list with código and nombre

**Example:**
```
Search: "mat"
Results:
📚 MAT101 - Matemática I
📚 MAT102 - Matemática II
📚 MAT201 - Matemática III
```

## Carrera Multi-Select Component

### Visual Appearance

```
┌─────────────────────────────────────────────────┐
│ Carreras *                                      │
├─────────────────────────────────────────────────┤
│ ☑ ING001 - Ingeniería Civil                    │
│ ☑ ING002 - Ingeniería Mecánica                 │
│ ☐ ING003 - Ingeniería Eléctrica                │
│ ☐ ING004 - Ingeniería Química                  │
│ ☐ LIC001 - Licenciatura en Matemática          │
└─────────────────────────────────────────────────┘
```

### Behavior

- **Multiple Selection:** Click to select/deselect multiple carreras
- **Required Field:** Asterisk (*) indicates at least one must be selected
- **Help Text:** "Seleccione las carreras a las que pertenece esta materia. Debe seleccionar al menos una."
- **Validation:** Error shown if form submitted without selection

### Display Format

Each option shows:
- Carrera código (e.g., "ING001")
- Separator: " - "
- Carrera nombre (e.g., "Ingeniería Civil")

## Edit Flow

### Inline Editing

1. Click "✏️ Editar" on a materia in the list
2. Edit form appears below the list
3. Form pre-populated with current values
4. **Carrera multi-select shows currently associated carreras**
5. Modify any fields including carrera selection
6. Click "Actualizar Materia"
7. Success message and page refresh

### Edit Form Differences

- **Código field is read-only** (shown but disabled)
- All other fields editable
- Carrera multi-select shows current associations as default selection
- Can add or remove carrera associations

## Delete Flow

### Confirmation Dialog

1. Click "🗑️ Eliminar" on a materia
2. Warning message appears:
   ```
   ⚠️ ¿Está seguro que desea eliminar esta materia? 
   Esta acción no se puede deshacer.
   ```
3. Two buttons:
   - 🗑️ Confirmar Eliminación (primary, red)
   - ❌ Cancelar (secondary)
4. If confirmed: Success message and page refresh
5. If cancelled: Returns to list view

## Validation Messages

### Success Messages

```
✅ Materia creada exitosamente
✅ Materia actualizada exitosamente
✅ Materia eliminada exitosamente
```

### Error Messages

```
❌ Debe seleccionar al menos una carrera
❌ Error al crear materia: [details]
❌ Error al actualizar: [details]
❌ Error al eliminar: [details]
⚠️ Sin carreras asignadas (in list view)
```

### Info Messages

```
ℹ️ No hay materias registradas. Cree una nueva materia usando la pestaña 'Crear'.
ℹ️ No se encontraron materias que coincidan con la búsqueda.
```

## Keyboard Navigation

- **Tab:** Navigate between form fields
- **Space/Enter:** Toggle carrera selection in multi-select
- **Arrow keys:** Navigate within multi-select dropdown
- **Escape:** Close multi-select dropdown

## Responsive Design

The page adapts to different screen sizes:

- **Desktop:** Two-column layout in list view
- **Tablet:** Stacked columns in list view
- **Mobile:** Single column, full-width components

## Accessibility

- All form fields have labels
- Required fields marked with asterisk (*)
- Error messages associated with fields
- Color-coded feedback (green=success, red=error, yellow=warning)
- Keyboard navigation supported

## Best Practices

### When Creating a Materia

1. ✅ Choose a descriptive código (e.g., "MAT101" not "M1")
2. ✅ Use full materia name (e.g., "Matemática I" not "Mat 1")
3. ✅ Set realistic cupo based on classroom capacity
4. ✅ Select all relevant carreras (a materia can belong to multiple)
5. ✅ Set correct año and cuatrimestre for curriculum placement

### When Editing

1. ✅ Review all fields before saving
2. ✅ Check carrera associations are still correct
3. ✅ Consider impact on existing comisiones and clases
4. ⚠️ Changing cupo may affect comisiones

### When Deleting

1. ⚠️ Check for dependent entities (comisiones, clases)
2. ⚠️ Consider archiving instead of deleting
3. ⚠️ Deletion is permanent and cannot be undone

## Common Workflows

### Adding a New Materia to Multiple Carreras

1. Go to "➕ Crear" tab
2. Fill in materia details
3. In Carreras multi-select, select all relevant carreras
4. Submit form
5. Verify in "📋 Lista" that all carreras are shown

### Changing Carrera Associations

1. Find materia in "📋 Lista"
2. Click "✏️ Editar"
3. In Carreras multi-select:
   - Deselect carreras to remove
   - Select new carreras to add
4. Click "Actualizar Materia"
5. Verify changes in list view

### Finding Materias Without Carreras

1. Go to "📋 Lista" tab
2. Look for entries with "⚠️ Sin carreras asignadas"
3. Click "✏️ Editar" to add carreras
4. Select at least one carrera
5. Save changes

## Technical Notes

- Carrera data loaded from database on page load
- Multi-select uses Streamlit's native `st.multiselect` component
- Form validation happens on both client and server side
- Database transactions ensure data consistency
- Relationship managed through `materia_carrera` link table
