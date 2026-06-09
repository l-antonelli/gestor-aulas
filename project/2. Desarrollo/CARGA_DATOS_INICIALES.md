# Carga de Datos Iniciales

## Descripcion General

El script `scripts/load_initial_data.py` carga los datos maestros desde archivos Excel hacia la base de datos SQLite. Estos datos representan la informacion estructural de la facultad: aulas, materias, carreras y sus planes de estudio.

**Los cronogramas de horarios NO se cargan desde este script.** Se cargan desde la UI, en la pagina de Planes, donde se asocian a un ciclo lectivo y un plan de cursada.

## Archivos de Entrada

Todos los archivos se encuentran en `data/input/`:

| Archivo | Contenido |
|---------|-----------|
| `aulas/aulas.xlsx` | Aulas fisicas con capacidad |
| `Carreras/Maestro materias.xlsx` | Catalogo completo de materias |
| `Carreras/Maestro planes.xlsx` | Relacion materia-carrera con ubicacion curricular |

### Columnas esperadas por archivo

**aulas.xlsx:**
- `Aula`: nombre del aula (ej: "AULA 01")
- `Capacidad (Alumnos)`: capacidad entera

**Maestro materias.xlsx:**
- `codigo_plan`: codigo unico de la materia (ej: "FB5", "I11")
- `nombre`: nombre completo
- `horas`: horas semanales (puede ser 0 o "-", se convierte a NULL)
- `codigo_guarani`: codigo en SIU Guarani (puede ser "-" o vacio)
- `periodo`: "anual" o "cuatrimestral"
- `electiva`: booleano o vacio, indica si la materia es optativa/electiva

**Maestro planes.xlsx:**
- `codigo_carrera`: codigo de la carrera (ej: "A", "I", "R")
- `codigo_materia`: referencia a materia existente
- `anio_plan`: anio dentro del plan (1-6)
- `cuatrimestre_plan`: "1C", "2C" o "anual"
- `correlativas`: texto libre con codigos de correlativas
- `electiva`: booleano, si la materia es optativa en este plan

## Pasos de Carga

El script ejecuta 3 pasos en orden:

### Paso 1: Aulas
- Lee `aulas.xlsx`
- Crea (o reusa) la sede default `SedeDB(nombre="Pellegrini")`
- Crea registros `AulaDB` con `id` UUID auto-generado y `codigo_aula`
  derivado como `Pellegrini-AULA-01` (sede + nombre, con guiones)
- Tipo por defecto: `"teorica"`

### Paso 2: Materias
- Lee `Maestro materias.xlsx`
- Crea registros `MateriaDB`
- Convierte `horas <= 0` a `NULL` (materias como "Visita a Obras" no tienen horas definidas)
- Parsea el campo `electiva` para setear `optativa`

### Paso 3: Carreras + Planes de Estudio
- Lee `Maestro planes.xlsx`
- Crea las carreras como `CarreraDB` (con nombre placeholder = codigo)
- Crea una version de plan **"Plan Original"** por cada carrera (`PlanCarreraVersionDB`)
- Crea los registros `PlanEstudioDB` que vinculan materia-carrera-version con ubicacion curricular
- Copia el campo `electiva` a `optativa` en cada entrada del plan

## Como Ejecutar

### Carga incremental (sin borrar datos existentes)
```bash
python -m scripts.load_initial_data
```
Solo crea registros nuevos. Si un aula, materia o entrada de plan ya existe, la saltea.

### Reset completo (borrar todo y recargar)
```bash
python -m scripts.load_initial_data --reset
```
Elimina el archivo `data/database.db` y recrea todas las tablas vacias antes de cargar. Pide confirmacion por consola.

**IMPORTANTE:** Despues de un reset, se pierde:
- Todos los ciclos lectivos y dictados
- Todos los cronogramas cargados
- Todas las planificaciones de cursada (comisiones, horarios, clases)
- Ediciones manuales a nombres de carreras, cantidad de materias, etc.
- Versiones de plan creadas desde la UI

Se deben recrear desde la UI:
1. Editar nombres/atributos de carreras
2. Crear ciclos lectivos y asociar versiones de plan
3. Generar dictados
4. Cargar cronogramas y generar planes de cursada

## Notas

- El campo `cantidad_materias` de las carreras queda en NULL al cargar. Se debe completar manualmente desde la UI (es el numero esperado de materias **obligatorias**).
- Los nombres de carreras se crean como placeholder (codigo = nombre). Se deben editar desde la pagina de Carreras.
- Si se actualizan los Excel de entrada, se puede correr el script sin `--reset` para agregar registros nuevos sin perder datos existentes. Sin embargo, **no actualiza registros existentes** — solo crea los que no existan.
