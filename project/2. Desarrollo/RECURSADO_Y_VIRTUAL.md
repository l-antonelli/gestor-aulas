# Recursado, virtualidad y auditoría de cambios

Documenta el refactor completado en la Etapa 1 + Fases 2 y 3 del
trabajo sobre dictados. Los tres cambios se pensaron y ejecutaron
juntos porque comparten un mismo objetivo: **hacer explícito y
auditable el contrato entre las reglas del catálogo y el estado de
cada ciclo lectivo**.

Estado: **implementado y en uso**. La DB fue migrada de forma
destructiva (318 dictados con `activo=False` borrados; 280 clases
huérfanas quedaron con `dictado_id=NULL`).

---

## 1. Semántica "existencia = activación"

**Antes**: `DictadoDB` tenía un campo `activo: bool` (default `True`) y
un override manual `activo_override_manual`. Existía la posibilidad de
que un dictado estuviera creado en un ciclo pero marcado como inactivo
— lo cual generaba dos preguntas conceptualmente distintas ("¿existe?"
y "¿está activo?") que en la práctica eran redundantes y difíciles de
mantener sincronizadas.

**Ahora**: un dictado **existe ↔ se dicta en ese ciclo**. Punto. No
hay flag `activo`. Para "desactivar" hay que borrar la fila con
`borrar_dictado_de_ciclo` (que también nullifica `ClaseDB.dictado_id`
en las clases huérfanas para que sobrevivan). Para "reactivar" hay que
volver a crear el dictado.

**Implicancias**:
- `create_dictados_for_ciclo` ya **no crea** dictados que la regla de
  recursado dice omitir; antes los creaba con `activo=False`.
- La sincronización de dictados vs el plan es explícita
  (`sync_dictados_para_ciclo`) y siempre en modo preview + apply, sin
  auto-borrado.
- Las 3 secciones del panel de divergencias son ortogonales y
  autoexplicativas.

**Campos eliminados de `DictadoDB`**: `activo`, `activo_override_manual`.
También el parámetro `activo` del helper `update_dictado`.

---

## 2. Virtualidad jerárquica (regla "el nivel más específico manda")

Un horario efectivamente virtual se resuelve en cascada:

```
HorarioDB.virtual  >  DictadoDB.virtual  >  MateriaDB.virtual
   (Optional[bool])     (Optional[bool])       (bool, raíz)
```

- `None` = heredar del padre.
- `True/False` = forzar el valor, ignorando padres.

El helper `resolve_virtual(horario, dictado, materia) -> bool` centraliza
la resolución. Los cuatro consumidores importantes (LP `build_inputs`,
generación de bloques del plan, inspector de franja, validación de
cronograma) ya lo usan.

**Uso típico**:
- Una materia catalogada como virtual (`MateriaDB.virtual=True`) → todos
  sus dictados y horarios son virtuales por default.
- Un ciclo puntual donde la materia se dicta por Zoom
  → `DictadoDB.virtual=True` (override para ese ciclo únicamente).
- Un horario específico dentro de un dictado presencial que se dicta
  virtual (ej. clase invertida un día por semana)
  → `HorarioDB.virtual=True`.

**Regla análoga para recursado**: `MateriaDB.dicta_recursado` (Optional[bool])
prevalece sobre `CarreraDB.dicta_recursado` (bool). Se resuelve con
`resolve_dicta_recursado(materia, carrera) -> bool`. Es el mismo patrón
con sólo 2 niveles.

---

## 3. Sincronización con reglas + panel de divergencias

### 3.1 La API — `sync_dictados_para_ciclo`

Compara el set de dictados existentes en un ciclo contra las materias
del plan + reglas vigentes, y devuelve un `SyncResult` con 3 listas:

- **`to_create`**: materias del plan sin dictado y la regla NO dice
  skippear. Deberían existir.
- **`to_delete`**: dictados existentes cuya materia ya no está en el
  plan del ciclo (huérfanos, típicamente aparecen tras cambiar la
  versión de plan asignada).
- **`rule_says_skip_but_exists`**: dictados existentes que la regla
  actual dice que no deberían existir. **Nunca se borran
  automáticamente** — el usuario decide si los borra o si promueve la
  decisión a regla general.

Con `apply=False` (default) sólo devuelve el diff. Con `apply=True`
aplica `to_create` y `to_delete`; `rule_says_skip_but_exists` queda
siempre para revisión manual.

### 3.2 El panel — `src/ui/divergencias_panel.py`

Componente reutilizable que renderiza el `SyncResult` en tres secciones
colapsables, con acciones por fila:

- **Sección `to_create`**:
  - `[✅ Crear]`: crea el dictado en el ciclo.
  - `[⏭️ Omitir en regla]`: setea `MateriaDB.dicta_recursado=False`
    para que ciclos futuros omitan la materia (no crea nada en el ciclo
    actual).
  - `[⏭️ Omitir TODAS en regla (N)]`: bulk con confirmación en 2 pasos.

- **Sección `to_delete`**:
  - `[🗑️ Borrar]`: borra el dictado y nullifica clases huérfanas.

- **Sección `rule_says_skip_but_exists`**:
  - `[🗑️ Borrar]`.
  - `[⬆️ Promover a regla]`: setea `MateriaDB.dicta_recursado=True`
    para que en ciclos futuros ya no sea divergencia.
  - `[⬆️ Promover TODAS a regla (N)]`: bulk con confirmación.

- Botón masivo global `[⚡ Aplicar todo]` que ejecuta
  `sync_dictados_para_ciclo(apply=True)` (respeta la sección
  "rule_says_skip_but_exists", nunca borra masivamente).

### 3.3 Promoción a regla — `promover_a_regla`

Cambia `MateriaDB.dicta_recursado` según la acción:
- `"crear-en-regla"` → True (la materia pasa a ser esperada por defecto).
- `"omitir-en-regla"` → False (la materia pasa a ser omitida por
  defecto en ciclos donde el cuatrimestre no coincide).

**No modifica** dictados existentes; sólo el catálogo. El usuario tiene
que aplicar la sincronización explícitamente después si quiere que el
ciclo actual se ajuste.

---

## 4. Auditoría — change log

### 4.1 Modelo `ChangeLogDB`

Registra cada mutación relevante con:
- `entity_type` + `entity_id` + `entity_label` (label preservado
  aunque la entidad se borre).
- `action`: `created` / `updated` / `deleted`.
- `field`, `old_value`, `new_value` (para updates; JSON serializado).
- `reason` (texto libre) + `origin` (`ui:ciclos`, `ui:validacion`,
  `script:xxx`, `auto`).
- `when` con índice para queries por rango temporal.

### 4.2 Entidades trackeadas

Whitelist explícita en `TRACKED_ENTITIES` (`change_log_service.py`):

| Entidad | Campos trackeados | Modo |
|---|---|---|
| `MateriaDB` | `virtual`, `active`, `dicta_recursado`, `optativa`, `horas_teoria`, `horas_laboratorio` | create/update/delete |
| `CarreraDB` | `dicta_recursado` | create/update/delete |
| `DictadoDB` | `virtual` | create/update/delete |
| `DictadoCicloDB` | (bridge, sin campos) | create/delete solamente |
| `SedeDB` | `es_default_comunes` | create/update/delete |

Las entidades de operación (`HorarioDB`, `ComisionDB`, `ClaseDB`,
etc.) **no se auditan**. Son datos de operación, no política; su
volumen generaría ruido sin valor.

### 4.3 Hooks vs eventos explícitos

- **Hooks automáticos**: capturan cualquier cambio a las entidades
  trackeadas (sin importar quién lo dispare). Corren en el
  `after_insert/update/delete` de SQLAlchemy e insertan la fila del log
  usando `connection.execute` (no la session, porque el flush ya está
  en curso).
- **Eventos explícitos**: los servicios pueden llamar `emit_event(...)`
  para agregar filas con `reason` contextualizada (útil cuando el
  cambio mecánico es idéntico al automático pero la razón importa
  más). Además existe `change_context(origin, reason)` como context
  manager que propaga la información a los hooks automáticos:

  ```python
  with change_context(
      origin="ui:ciclos",
      reason="Promoción a regla desde panel de divergencias del ciclo X",
  ):
      promover_a_regla(session, "MAT101", ciclo_id, accion="crear-en-regla")
  ```

  La mutación de `MateriaDB.dicta_recursado` queda registrada con esa
  razón sin necesidad de emitir el evento manualmente.

### 4.4 UI — página **📜 Historial**

Dos modos:
- **Feed global**: mutaciones recientes de todas las entidades
  trackeadas, con filtros por tipo y origen. Timestamp relativo
  ("hace 3 min", "hace 2 días").
- **Por entidad**: seleccionás una Materia/Carrera/Dictado/Sede y ves
  su historial completo.

El widget está en `src/ui/historial_widget.py` y se puede reutilizar
como pestaña dentro de páginas individuales si se necesita más adelante.

---

## 5. Flujo de trabajo típico

Un cuatrimestre nuevo:

1. **Se crea el ciclo** (`CicloDB`) y se le asignan las versiones de
   plan que aplican.
2. **Se corre `create_dictados_for_ciclo`** desde el botón de Ciclos.
   Se crean todos los dictados que la regla actual autoriza (los
   cuatrimestrales de cuatri opuesto sin recursado no se crean).
3. **Se carga el cronograma** de las materias (Excel, upload).
4. **Se corre la validación del cronograma**: aparecen extras
   (materias en el cronograma sin dictado) y faltantes (dictados sin
   horarios).
5. **Se resuelven los extras** desde el panel de validación: bulk
   `🟢 Activar` (crea el dictado como presencial) o
   `🌐 Activar y marcar virtual` (crea el dictado con
   `DictadoDB.virtual=True`). Cada acción queda en el change log con
   `origin=ui:validacion` y razón "Aceptar materia del cronograma...".
6. **Si aparecieron patrones repetidos** (ej. "la carrera X siempre
   dicta este recursado"), ir a la página de Ciclos → panel de
   divergencias → `[⬆️ Promover a regla]`. Con esto en el próximo
   ciclo ya no aparece como divergencia.

Un cambio de política a mitad de ciclo:

1. **Se edita `CarreraDB.dicta_recursado` o `MateriaDB.dicta_recursado`**
   desde la UI. El cambio queda en el change log automáticamente.
2. **Se abre el panel de Ciclos → Sincronizar**. Aparecen las
   divergencias nuevas (dictados que la regla nueva dice omitir).
3. **Se decide caso por caso**: borrar el dictado (si la política nueva
   es real) o dejarlo (si es una excepción vigente para este ciclo).

---

## 6. Archivos y símbolos relevantes

**Modelo**:
- `src/database/models.py`: `MateriaDB.dicta_recursado`,
  `CarreraDB.dicta_recursado`, `DictadoDB.virtual`,
  `HorarioDB.virtual`, `ChangeLogDB`.

**Servicios**:
- `src/services/resolucion_jerarquica.py`: helpers puros
  `resolve_virtual`, `resolve_dicta_recursado`.
- `src/services/dictado_service.py`: `create_dictados_for_ciclo`,
  `sync_dictados_para_ciclo`, `aceptar_materias_en_ciclo`,
  `borrar_dictado_de_ciclo`, `promover_a_regla`.
- `src/services/change_log_service.py`: `emit_event`,
  `change_context`, `get_log_for_entity`, `get_recent_log`,
  `TRACKED_ENTITIES`.

**UI**:
- `app/pages/4_📆_Ciclos.py`: integración del panel de divergencias.
- `app/pages/8_📜_Historial.py`: página del historial.
- `src/ui/divergencias_panel.py`: componente reutilizable.
- `src/ui/historial_widget.py`: componente reutilizable.

**Tests**:
- `tests/test_resolucion_jerarquica.py` (17 casos).
- `tests/test_dictado_service.py` (35 casos, incluyendo Sync/Promover/Borrar).
- `tests/test_change_log_service.py` (15 casos).
