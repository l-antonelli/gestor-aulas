# Sesion: Editor de Planes, Dictados Mejorados y Validaciones de Factibilidad

**Fecha**: 2026-03-10
**Branch**: `refactor/jerarquia-entidades-ui`

---

## Resumen

Se implemento un conjunto de mejoras para pasar de un workflow basado en import CSV a una interfaz completa para: gestionar dictados por ciclo con control granular, editar planes de cursada interactivamente, visualizar horarios en una grilla tipo cronograma, y validar factibilidad de los planes.

## Motivacion

El sistema previamente solo permitia importar cronogramas desde CSV y generar planes automaticamente, sin posibilidad de edicion posterior. Faltaban controles para:

- Decidir que materias se dictan en cada ciclo (dictados) con logica de recursado
- Marcar materias como virtuales (no necesitan aula fisica)
- Editar comisiones y horarios dentro de un plan generado
- Visualizar el plan completo en una grilla horaria
- Validar que el plan no tenga conflictos antes de activarlo

## Cambios realizados

### Sprint 1: Cambios de modelo

Se agregaron 3 campos booleanos a los modelos existentes:

| Modelo | Campo | Default | Proposito |
|--------|-------|---------|-----------|
| `CarreraDB` | `dicta_recursado` | `True` | Si FALSE, materias exclusivas del cuatrimestre opuesto no generan dictado |
| `MateriaDB` | `virtual` | `False` | Default para el flag virtual del dictado |
| `DictadoDB` | `virtual` | `False` | Si la materia se dicta virtualmente (no necesita aula) |

- Domain models (`Carrera`, `Materia`) actualizados con los campos correspondientes
- Converters (`to_db`/`to_domain`) actualizados para round-trip correcto
- Migracion SQLite idempotente via `ALTER TABLE ADD COLUMN` con try/except en `connection.py`
- UI pages Carreras y Materias muestran los nuevos campos

### Sprint 2: Dictado service mejorado + UI de dictados

**Logica de recursado** en `dictado_service.py`:
- Si una materia es exclusiva de 1 carrera con `dicta_recursado=False`, se verifica el `cuatrimestre_plan`
- Si el cuatrimestre del plan no coincide con el ciclo actual y no es "Anual", la materia se skipea
- Materias compartidas entre carreras siempre se dictan
- Herencia de virtual: `dictado.virtual = materia.virtual`

**Nuevas funciones**:
- `get_dictados_for_ciclo()` — obtiene dictados de un ciclo
- `get_skipped_materias_for_ciclo()` — materias del plan sin dictado + razon
- `update_dictado()` — edicion individual de activo/virtual
- `SkippedMateria` dataclass para info de materias omitidas

**UI en Ciclos** (tab Dictados):
- Dictados agrupados por carrera en expanders
- Checkboxes para `activo` y `virtual` por dictado
- Boton "Guardar cambios" con batch update
- Seccion "Materias sin dictado" informativa

### Sprint 3: Editor de plan — comisiones + horarios + configuracion

**Tab "Detalle del Plan"** — de read-only a editable:
- Filtros por carrera, anio y cuatrimestre (join con PlanEstudioDB)
- Comisiones: nombre y cupo editables inline, boton eliminar (cascade horarios), boton agregar comision
- Horarios por comision: tabla con boton eliminar por fila, form "Agregar Horario" via popover con dia selectbox y hora inicio/fin basados en franjas de ConfiguracionHoraria

**Tab "Configuracion"**:
- Form para ConfiguracionHoraria (granularidad, hora inicio/fin, dias operativos)
- Preview de franjas horarias generadas

**Helper**: `generate_time_slots(config) -> list[tuple[time, time]]` en `plan_generation_service.py`

### Sprint 4: Grilla visual de horarios

**Tab "Grilla Horaria"** en pagina de Planes:
- Selector de ciclo + plan + filtros (carrera, anio, cuatrimestre)
- Grilla read-only: columnas = dias, filas = franjas horarias
- Bloques coloreados por materia/comision, virtuales marcados con "[V]"
- Implementacion con `st.columns()` + `st.markdown()` con `unsafe_allow_html=True`

**Helper**: `build_timetable_grid(session, plan_id, config, filtered_materia_codigos) -> dict[str, list[TimetableBlock]]`
- `TimetableBlock` dataclass con materia_codigo, materia_nombre, comision_nombre, hora_inicio, hora_fin, virtual

### Sprint 5: Validaciones de factibilidad

Tres funciones de validacion scoped a un plan:

| Funcion | Severidad | Que valida |
|---------|-----------|------------|
| `validar_conflictos_horarios_plan()` | BLOCKER | Overlaps horarios dentro de carrera+anio+cuatrimestre. Incluye anuales en checks cuatrimestrales |
| `validar_cobertura_plan()` | WARNING | Toda materia con dictado activo tiene >= 1 comision con horarios |
| `identificar_virtuales_plan()` | INFO | Lista materias virtuales que no necesitan aula |

Reutiliza `ValidationResult` y `horarios_se_superponen()` de `validations.py`.

### Sprint 6: Integracion validaciones en UI + documentacion

**Panel de validaciones** en tab "Detalle del Plan":
- Boton "Validar Plan" ejecuta las 3 validaciones
- Resultados en session_state con clave `validation_results_{plan_id}`
- BLOCKER: `st.error()` — deshabilita boton "Activar"
- WARNING: `st.warning()`
- INFO: `st.info()`
- Detalles expandibles por resultado
- El boton Activar verifica que no haya BLOCKERs antes de proceder

**Documentacion**: actualizado diagrama de entidades con nuevos campos.

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `src/database/models.py` | Campos `dicta_recursado`, `virtual` (x2) |
| `src/domain/problem/carrera.py` | Campo `dicta_recursado` |
| `src/domain/problem/materia.py` | Campo `virtual` |
| `src/database/converters.py` | Round-trip nuevos campos |
| `src/database/connection.py` | Migraciones SQLite idempotentes |
| `src/services/dictado_service.py` | Logica recursado, virtual, funciones CRUD dictados |
| `src/services/plan_generation_service.py` | `generate_time_slots`, `TimetableBlock`, `build_timetable_grid` |
| `src/services/validations.py` | 3 funciones de validacion por plan |
| `app/pages/1_📚_Materias.py` | Display campo virtual |
| `app/pages/3_🎓_Carreras.py` | Display campo dicta_recursado |
| `app/pages/4_📆_Ciclos.py` | Tab Dictados completo |
| `app/pages/5_📊_Planes.py` | Editor, grilla horaria, configuracion, panel validaciones |
| `project/1. Diseño/diagrama-entidades.md` | Actualizado UML con nuevos campos |

## Tests agregados

| Archivo | Tests | Que cubren |
|---------|-------|------------|
| `tests/test_dictado_service.py` | 12 | Recursado skip/no-skip, virtual inheritance, get_skipped, update_dictado |
| `tests/test_plan_generation_service.py` | 7 | generate_time_slots (4), build_timetable_grid (3) |
| `tests/test_validations.py` | 11 | Conflictos horarios (5), cobertura (3), virtuales (3) |

Tests totales: 718 passed, 10 skipped.

## Notas tecnicas

- **Migracion SQLite**: Se usa `ALTER TABLE ADD COLUMN` envuelto en try/except. SQLite no soporta IF NOT EXISTS para columnas, asi que se swallowea el error si la columna ya existe. Esto es idempotente.
- **Recursado**: La logica de `_should_skip_for_recursado()` verifica: (1) la materia es exclusiva de exactamente 1 carrera, (2) esa carrera tiene `dicta_recursado=False`, (3) el cuatrimestre del plan no coincide con el ciclo ni es "Anual". Si todas se cumplen, la materia no genera dictado.
- **Grilla horaria**: Streamlit no soporta drag & drop nativo. La grilla es puramente visual (HTML/CSS con `unsafe_allow_html=True`). La edicion se hace via formularios en el tab Detalle.
- **Validaciones y activacion**: Los resultados de validacion se almacenan en `st.session_state` para persistir entre reruns. El boton Activar verifica la presencia de BLOCKERs en los resultados almacenados.
- **Anuales en validacion**: `validar_conflictos_horarios_plan()` incluye materias anuales al validar grupos cuatrimestrales, ya que una materia anual ocupa horarios tanto en 1C como en 2C.

## Estructura de tabs en Planes (estado final)

```
5_📊_Planes.py
├── Tab 1: 📥 Cronogramas      — Carga CSV, validacion cobertura, generar plan
├── Tab 2: 📋 Vista General     — Cards por plan, activar/eliminar
├── Tab 3: 🔍 Detalle del Plan  — Editor comisiones/horarios, validaciones, activacion
├── Tab 4: 📋 Grilla Horaria    — Visualizacion grilla coloreada
├── Tab 5: 📅 Clases            — Generacion y gestion de clases
└── Tab 6: ⚙️ Configuracion     — Granularidad, hora inicio/fin, dias operativos
```
