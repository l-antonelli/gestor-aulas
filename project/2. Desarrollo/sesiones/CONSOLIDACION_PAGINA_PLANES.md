# Sesion: Consolidacion de Paginas — Planes como Hub Central

**Fecha**: 2026-03-10
**Branch**: `refactor/jerarquia-entidades-ui`

---

## Resumen

Se reestructuro la UI para que la pagina de Planes sea el hub central del workflow de planificacion. Se eliminaron las paginas standalone de Comisiones y Horarios, y se movio la gestion de cronogramas (schedules) y la generacion de planes desde la pagina de Ciclos a la pagina de Planes.

## Motivacion

Las comisiones y horarios no son entidades independientes — solo existen como componentes internos de un Plan de Cursada. Tener paginas separadas para ellos era confuso y no reflejaba el flujo real:

```
Carrera → Plan de Estudio (version) → Ciclo → Cronograma → Plan de Cursada → Clases
```

Ademas, habia dos mecanismos redundantes para cargar horarios:
- La pagina de Horarios creaba HorarioDB + ComisionDB directamente (sin plan, sin schedule)
- La pagina de Ciclos tab Schedules creaba ScheduleDB + ScheduleEntryDB (staging)

Se unifico en un solo flujo: los cronogramas (ScheduleDB) se cargan y visualizan en la pagina de Planes, y desde ahi se generan planes de cursada.

## Cambios realizados

### Paginas eliminadas
- `3_👥_Comisiones.py` — las comisiones se ven dentro del Detalle del Plan
- `4_📅_Horarios.py` — los cronogramas se gestionan dentro de la pagina Planes

### Pagina de Ciclos (`4_📆_Ciclos.py`, antes `6_`)
- Se removieron los tabs "Schedules" y "Planes"
- Quedo solo con: tab Ciclos (CRUD + asignacion de plan versions) y tab Dictados

### Pagina de Planes (`5_📊_Planes.py`, antes `7_`)
Se reestructuro con 4 tabs:

**Tab 1: Cronogramas**
- Selector de ciclo
- Carga de archivos CSV/Excel (reutiliza `create_schedule_from_file`)
- Visualizacion de entradas con nombres de materia legibles (no UUIDs)
- Validacion de cobertura contra plan de carrera del ciclo:
  - Materias cubiertas vs esperadas
  - Materias faltantes (con nombre + codigo)
  - Materias extra (no esperadas en el plan de estudio)
- Boton para generar plan directamente desde cada cronograma

**Tab 2: Vista General**
- Cards por plan con metricas inline (materias, comisiones, horarios, clases)
- Acciones: Activar, Eliminar (cascade)

**Tab 3: Detalle del Plan**
- Metadata editable (nombre, descripcion)
- Estadisticas (5 metricas)
- Desglose por materia con expanders: comisiones con cupo y tabla de horarios

**Tab 4: Clases**
- Generar clases para un plan
- Tabla filtrable (por materia, por estado)
- Metricas: total, ejecutadas, pendientes, con aula

### Renumeracion de paginas
| Antes | Despues |
|-------|---------|
| 1_📚_Materias | 1_📚_Materias |
| 2_🏛️_Aulas | 2_🏛️_Aulas |
| 3_👥_Comisiones | (eliminada) |
| 4_📅_Horarios | (eliminada) |
| 5_🎓_Carreras | 3_🎓_Carreras |
| 6_📆_Ciclos | 4_📆_Ciclos |
| 7_📊_Planes | 5_📊_Planes |

## Estructura final de paginas

```
1. Materias      — entidad independiente
2. Aulas         — entidad independiente
3. Carreras      — entidad independiente (con versiones de plan de estudio)
4. Ciclos        — periodos lectivos + dictados
5. Planes        — hub: cronogramas → planes → comisiones/horarios → clases
```

## Archivos modificados

| Archivo | Cambio |
|---------|--------|
| `app/pages/5_📊_Planes.py` | Reescrito con tab Cronogramas + validacion cobertura |
| `app/pages/4_📆_Ciclos.py` | Simplificado: removidos tabs Schedules y Planes |
| `app/pages/3_👥_Comisiones.py` | Eliminado |
| `app/pages/4_📅_Horarios.py` | Eliminado |
| `app/pages/3_🎓_Carreras.py` | Renumerado (de 5 a 3) |

## Notas tecnicas

- La `ConfiguracionHoraria` (granularidad, hora inicio/fin, dias operativos) queda en el modelo pero no tiene UI dedicada por ahora. Se usaba solo para entrada manual de horarios, que fue removida. Si se necesita en el futuro, se puede agregar como tab de configuracion en Planes.
- De `horario_loading_service.py`, la funcion principal `load_horarios_from_data` ya no es invocada desde ninguna pagina (creaba horarios sueltos sin plan). Sin embargo, el archivo sigue siendo necesario porque exporta funciones auxiliares reutilizadas por otros servicios: `_resolve_materia_code` (schedule_service), `derive_comision_count` (plan_generation_service), `HorarioInput` (horario_file_parser), y varias por `scripts/load_initial_data.py`.
