# Mejoras en la Interfaz de Materias

## Resumen de Cambios

Se ha mejorado significativamente la interfaz de gestión de materias para proporcionar un control completo sobre las asociaciones materia-carrera y las comisiones.

## Nuevos Componentes

### 1. MateriaCarreraEditor (`src/ui/materia_carrera_editor.py`)

Componente para gestionar las asociaciones materia-carrera con año y cuatrimestre.

**Características:**
- **Tabla Editable**: Usa `st.data_editor` para mostrar y editar asociaciones
- **Columnas**:
  - Código Carrera (solo lectura)
  - Nombre Carrera (solo lectura)
  - Año (editable, 1-6)
  - Cuatrimestre (editable, 1-2)
- **Guardar Cambios**: Detecta automáticamente cambios y permite guardarlos
- **Desasociar**: Permite seleccionar y eliminar múltiples asociaciones
- **Asociar Nueva**: Formulario para agregar nuevas carreras con año/cuatrimestre

### 2. ComisionManager (`src/ui/comision_manager.py`)

Componente para gestionar las comisiones de una materia.

**Características:**
- **Tabla de Comisiones**: Muestra todas las comisiones con sus datos
- **Eliminar Comisión**: Selector para eliminar comisiones existentes
- **Crear Comisión**: Formulario para crear nuevas comisiones
  - Nombre (auto-sugerido: "Comisión N")
  - Número (auto-incrementado)
  - Cupo (heredado de la materia)
  - Descripción (opcional)

## Página de Materias Actualizada

### Tab 1: Lista
- Muestra todas las materias con sus datos básicos
- Muestra carreras asociadas (solo códigos)
- Botones de Editar y Eliminar

### Tab 2: Crear
**Formulario mejorado con:**
1. **Datos Básicos**: Código, nombre, período, cupo, horas semanales
2. **Asignación de Carreras** (obligatorio):
   - Multi-select de carreras
   - Para cada carrera seleccionada:
     - Año (1-6)
     - Cuatrimestre (1-2)
   - Validación: Al menos una carrera requerida

### Tab 3: Buscar
- Búsqueda por código o nombre
- Sin cambios

### Modo Edición (al hacer clic en Editar)

Se abre un editor con **3 sub-tabs**:

#### Sub-tab 1: Datos Básicos
- Formulario para editar propiedades intrínsecas de la materia
- Código es solo lectura
- Campos editables: nombre, período, cupo, horas semanales

#### Sub-tab 2: Carreras
- **Tabla editable** con todas las asociaciones
- Permite modificar año y cuatrimestre directamente en la tabla
- Botón "Guardar Cambios" aparece cuando hay modificaciones
- Sección para desasociar carreras
- Formulario para asociar nuevas carreras con año/cuatrimestre

#### Sub-tab 3: Comisiones
- **Tabla** con todas las comisiones de la materia
- Selector para eliminar comisiones
- Formulario para crear nuevas comisiones

## Flujo de Trabajo

### Crear una Materia
1. Ir a tab "Crear"
2. Completar datos básicos
3. Seleccionar al menos una carrera
4. Especificar año y cuatrimestre para cada carrera
5. Click "Crear Materia"

### Editar Asociaciones Materia-Carrera
1. En tab "Lista", click "Editar" en una materia
2. Ir a sub-tab "Carreras"
3. Opciones:
   - **Modificar año/cuatrimestre**: Editar directamente en la tabla y click "Guardar Cambios"
   - **Desasociar**: Seleccionar carreras y click "Desasociar Seleccionadas"
   - **Asociar nueva**: Completar formulario y click "Asociar"

### Gestionar Comisiones
1. En tab "Lista", click "Editar" en una materia
2. Ir a sub-tab "Comisiones"
3. Opciones:
   - **Ver comisiones**: Tabla con todas las comisiones
   - **Eliminar**: Seleccionar y click "Eliminar Comisión"
   - **Crear**: Completar formulario y click "Crear Comisión"

## Reglas de Negocio Implementadas

### RN1: Materia debe tener al menos una carrera
- Validado al crear materia
- Validado al desasociar carreras (no permite eliminar la última)

### RN2: Año y Cuatrimestre obligatorios
- Al crear materia, se debe especificar para cada carrera
- Al asociar nueva carrera, se debe especificar
- Valores por defecto: Año 1, Cuatrimestre 1

### RN3: Comisiones pertenecen a una materia
- ID auto-generado: `{materia_codigo}-C{numero}`
- Cupo por defecto heredado de la materia
- Número auto-incrementado

## Ventajas del Nuevo Diseño

1. **Centralizado**: Toda la gestión de una materia en un solo lugar
2. **Intuitivo**: Uso de `data_editor` para edición inline
3. **Completo**: Gestión de carreras Y comisiones
4. **Validado**: Reglas de negocio aplicadas en tiempo real
5. **Flexible**: Permite modificar año/cuatrimestre sin desasociar/reasociar
6. **Eficiente**: Cambios se guardan con un solo click

## Compatibilidad

- ✅ Compatible con la página "Planes de Estudio"
- ✅ Mantiene la integridad referencial
- ✅ Respeta todas las reglas de negocio
- ✅ No requiere cambios en el esquema de base de datos

## Próximos Pasos Sugeridos

1. Agregar filtros en la lista de materias (por carrera, por período)
2. Agregar ordenamiento en la tabla de asociaciones
3. Agregar validación de conflictos de horarios al crear comisiones
4. Agregar exportación de datos a CSV/Excel
