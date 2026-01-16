# Actualización: Cuatrimestre 0 para Materias Anuales

## Resumen

Se ha actualizado el sistema para usar `cuatrimestre_carrera = 0` para materias anuales, en lugar de usar `1`. Esto es más semántico y claro.

## Cambios en el Esquema

### Base de Datos (`src/database/models.py`)

```python
# ANTES
cuatrimestre_carrera: int = Field(default=1, ge=1, le=2)  # 1 o 2

# DESPUÉS
cuatrimestre_carrera: int = Field(default=0, ge=0, le=2)  # 0=anual, 1=1C, 2=2C
```

**Valores permitidos:**
- `0`: Materia anual (se dicta todo el año)
- `1`: Primer cuatrimestre
- `2`: Segundo cuatrimestre

## Migración de Datos

Script: `migrate_cuatrimestre_anual.py`

- Actualiza automáticamente todas las materias anuales existentes para usar `cuatrimestre_carrera = 0`
- Verifica que todos los cambios se aplicaron correctamente
- No hay pérdida de datos

## Cambios en la UI

### 1. Formulario de Creación de Materias

**Antes:** Multi-select + inputs individuales para año/cuatrimestre

**Después:** `data_editor` con tabla editable

**Características:**
- Tabla dinámica para agregar/eliminar carreras
- Columnas: Carrera (selectbox), Año (number), Cuatrimestre (selectbox o text)
- Para materias **anuales**:
  - Columna "Cuatrimestre" muestra "Anual" (disabled)
  - Valor guardado: 0
- Para materias **cuatrimestrales**:
  - Columna "Cuatrimestre" es selectbox con opciones [1, 2]
  - Valor guardado: 1 o 2

**Ventajas:**
- Interfaz más intuitiva y compacta
- Fácil agregar/eliminar múltiples carreras
- Edición inline de valores
- Validación en tiempo real

### 2. Editor de Asociaciones Materia-Carrera

**Cambios:**
- Para materias anuales:
  - Columna "Cuatrimestre" muestra "Anual" (disabled)
  - No permite editar el cuatrimestre
  - Al asociar nueva carrera, cuatrimestre se fija en 0
- Para materias cuatrimestrales:
  - Columna "Cuatrimestre" es editable (selectbox 1 o 2)
  - Al asociar nueva carrera, permite seleccionar 1 o 2

### 3. Página Planes de Estudio

**Cambios:**
- Al asociar materia anual: usa `cuatrimestre_carrera = 0`
- Filtrado correcto: materias anuales aparecen en columna "Anuales"

## Lógica de Negocio

### Regla: Cuatrimestre según Período

```python
if materia.periodo == "anual":
    cuatrimestre_carrera = 0  # Anual
else:  # "cuatrimestral"
    cuatrimestre_carrera = 1 o 2  # Según corresponda
```

### Validación

- Materias anuales **siempre** tienen `cuatrimestre_carrera = 0`
- Materias cuatrimestrales **nunca** tienen `cuatrimestre_carrera = 0`
- El sistema previene inconsistencias automáticamente

## Visualización

### En Tablas

| Período | cuatrimestre_carrera | Visualización |
|---------|---------------------|---------------|
| anual | 0 | "Anual" |
| cuatrimestral | 1 | "1" o "1C" |
| cuatrimestral | 2 | "2" o "2C" |

### En Planes de Estudio

```
Año 1
├── Anuales (cuatrimestre = 0)
│   ├── Matemática I
│   └── Física I
├── 1er Cuatrimestre (cuatrimestre = 1)
│   ├── Álgebra
│   └── Química
└── 2do Cuatrimestre (cuatrimestre = 2)
    ├── Cálculo
    └── Programación
```

## Compatibilidad

### Hacia Atrás
- ✅ Datos existentes se migran automáticamente
- ✅ Queries existentes siguen funcionando
- ✅ No requiere cambios en código de usuario

### Hacia Adelante
- ✅ Nuevas materias usan el esquema correcto
- ✅ Validación automática en todos los formularios
- ✅ Interfaz adaptativa según tipo de materia

## Testing

Para verificar el funcionamiento:

1. **Crear materia anual:**
   - Seleccionar período = "anual"
   - Agregar carreras en la tabla
   - Verificar que cuatrimestre muestra "Anual"
   - Guardar y verificar en BD: `cuatrimestre_carrera = 0`

2. **Crear materia cuatrimestral:**
   - Seleccionar período = "cuatrimestral"
   - Agregar carreras con cuatrimestre 1 o 2
   - Guardar y verificar en BD: `cuatrimestre_carrera = 1 o 2`

3. **Editar asociaciones:**
   - Abrir materia anual: cuatrimestre disabled
   - Abrir materia cuatrimestral: cuatrimestre editable
   - Modificar y guardar: verificar cambios en BD

## Beneficios

1. **Semántica Clara**: 0 = anual es más intuitivo que 1 = anual
2. **Validación Automática**: El sistema previene inconsistencias
3. **UI Adaptativa**: La interfaz se adapta al tipo de materia
4. **Mejor UX**: `data_editor` es más intuitivo que múltiples inputs
5. **Escalabilidad**: Fácil agregar más opciones en el futuro (ej: trimestres)

## Archivos Modificados

- `src/database/models.py` - Esquema actualizado
- `src/ui/materia_form_renderer.py` - Formulario con data_editor
- `src/ui/materia_carrera_editor.py` - Editor adaptativo
- `app/pages/7_🎓_Carreras.py` - Uso de cuatrimestre = 0
- `migrate_cuatrimestre_anual.py` - Script de migración
