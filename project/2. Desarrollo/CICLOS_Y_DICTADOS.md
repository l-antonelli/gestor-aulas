# Runbook: gestión de ciclos y dictados

> Guía operativa para configurar un ciclo lectivo desde cero en
> gestor-aulas: qué crear, en qué orden, cómo cargar los horarios,
> qué chequear antes de correr el asignador de aulas y cómo
> resolver los problemas típicos que aparecen.
>
> **Referencias conceptuales**:
> - Semántica de dictados y las tres puertas de decisión:
>   `RECURSADO_Y_VIRTUAL.md` § 1.
> - Modelo de datos y regla de independencia entre ciclos (RN19):
>   `1. Diseño/modelo-planificacion-cursada.md`.
> - Flujo end-to-end del sistema (con la etapa de asignación de
>   aulas): `WORKFLOW.md`.

## 0. Modelo mental en una página

Un **ciclo lectivo** es un cuatrimestre concreto (por ejemplo,
`2026-1C` o `2026-2C`). Cada ciclo se configura de forma
**independiente** de los demás: crear el 1C no crea nada del 2C, y
viceversa. La única entidad que se comparte es el `DictadoDB` de una
materia **anual**, que se materializa como una fila única linkeada
a ambos ciclos del año lectivo vía dos filas de `DictadoCicloDB`.

La configuración de un ciclo se compone de tres capas apiladas:

```text
┌──────────────────────────────────────────────────────────────┐
│ 3. Cronograma cargado (horarios semanales por comisión)       │
│    ScheduleDB + ScheduleEntryDB                               │
├──────────────────────────────────────────────────────────────┤
│ 2. Dictados del ciclo (qué materias se dictan y cómo)         │
│    DictadoDB + DictadoCicloDB                                 │
├──────────────────────────────────────────────────────────────┤
│ 1. Plan versions asignadas al ciclo (qué carreras participan) │
│    CicloPlanVersionDB → PlanCarreraVersionDB                  │
└──────────────────────────────────────────────────────────────┘
                    ↓ alimenta ↓
┌──────────────────────────────────────────────────────────────┐
│ Plan de cursada + Programa lineal de asignación de aulas      │
└──────────────────────────────────────────────────────────────┘
```

Cada capa filtra o transforma lo que llega desde arriba. Las
decisiones de una capa se validan contra las anteriores (por
ejemplo, el cronograma se prevalida contra los dictados creados).

## 1. Crear un ciclo desde cero

### 1.1 Prerrequisitos

Antes de crear un ciclo hay que asegurar el estado del catálogo:

- **Carreras** cargadas (`📚 Carreras`) con su flag `dicta_recursado`
  puesto en el valor correcto. Default `True` (la carrera acepta
  recursado); ponerlo en `False` si la carrera nunca ofrece materias
  del cuatrimestre opuesto.
- **Materias** cargadas (`📚 Materias`) con:
  - `periodo`: `"cuatrimestral"` o `"anual"`.
  - `horas_teoria` y `horas_laboratorio` correctas (impactan
    directamente al asignador vía R5).
  - `virtual`: `True` solo si la materia se dicta virtual **por
    diseño en el plan** (no para casos puntuales de un ciclo).
  - `dicta_recursado`: `None` por defecto (heredar de la carrera);
    poner `True` o `False` solo como override explícito para casos
    puntuales.
- **Planes de estudio versionados** (`PlanCarreraVersionDB`) para
  cada carrera que va a participar del ciclo, con sus
  `PlanEstudioDB` cargados (materia + carrera + año + cuatrimestre).

### 1.2 Crear el ciclo

En `📆 Ciclos → 📋 Ciclos`:

1. Botón **"Crear ciclo nuevo"**.
2. Completar:
   - **Año**: por ejemplo `2026`.
   - **Cuatrimestre**: `1` o `2`.
   - **Fecha inicio / Fecha fin**: el rango calendario del cuatri.
   - **Descripción** (opcional).
   - **Versiones de plan a asignar**: seleccionar la versión de
     plan vigente de cada carrera que va a participar del ciclo.
     Por default se pre-selecciona la versión activa de cada carrera
     (o la más reciente si no hay activa).

3. **Guardar**. Se crea la fila en `CicloDB` con id
   `"{año}-{numero}C"` (por ejemplo `2026-2C`) más las filas de
   `CicloPlanVersionDB` correspondientes.

> Regla operativa clave: **asegurate de incluir todas las carreras
> relevantes**. Si olvidás una carrera, las materias exclusivas de
> esa carrera van a quedar fuera del ciclo sin ninguna advertencia.
> Es el error más común al configurar un ciclo por primera vez.

### 1.3 Crear los dictados

En `📆 Ciclos → 📚 Dictados`, seleccionar el ciclo recién creado y
tocar **"Crear dictados"**. Esto llama a
`create_dictados_for_ciclo`, que recorre las materias de los planes
asignados y aplica las tres puertas de decisión (ver
`RECURSADO_Y_VIRTUAL.md § 1.2`):

1. Filtra las materias que están en algún `PlanEstudioDB` de las
   versiones asignadas al ciclo.
2. Para cada materia:
   - Si es **anual**, crea un `DictadoDB` con `dictado_codigo` =
     `"{materia}-{año}"` y `fin_dictado=None`. Si estamos creando
     el 2C y ya existe un dictado anual del 1C del mismo año, en
     lugar de crear uno nuevo se linkea el existente al 2C y se
     completa `fin_dictado`.
   - Si es **cuatrimestral del mismo cuatrimestre que el ciclo**,
     crea un `DictadoDB` con `dictado_codigo` =
     `"{materia}-{año}-{N}C"`.
   - Si es **cuatrimestral del cuatrimestre opuesto**, aplica la
     regla de recursado:
     - Si la materia está en **múltiples carreras**, se crea igual
       (nunca se skippea).
     - Si la materia es **exclusiva de una carrera** y
       `resolve_dicta_recursado(materia, carrera)` da `False`, se
       omite (`skipped_recursado` en el resultado).
     - Si da `True`, se crea normalmente.

El resultado devuelve conteos: creados, linkeados (anuales 2C),
omitidos por recursado, saltados (ya existían), errores.

### 1.4 Revisar divergencias

Después de "Crear dictados", el panel de la tab **📚 Dictados**
muestra el listado de dictados existentes y expone dos operaciones
adicionales:

- **🔄 Sincronizar según reglas** (`sync_dictados_para_ciclo`).
  Compara el estado actual del ciclo contra lo que las reglas dicen
  hoy y reporta tres tipos de divergencia:
  - **Faltantes**: materias del plan sin dictado que las reglas dicen
    que deberían dictarse. Acción: `[✅ Crear]`.
  - **Huérfanos**: dictados en el ciclo cuya materia ya no está en
    ningún plan asignado. Acción: `[🗑️ Borrar]`.
  - **La regla dice omitir pero existe**: dictados que se crearon
    manualmente o como excepción, pero cuya regla actual dice que
    no debería estar. Acciones: `[🗑️ Borrar]` para alinear con la
    regla, o `[⬆️ Promover a regla]` para actualizar
    `MateriaDB.dicta_recursado=True` (que la regla acompañe la
    decisión del ciclo).

- **Toggle Virtual por dictado**. Marca el dictado como virtual
  **solo en este ciclo** (`DictadoDB.virtual=True`, override del
  catálogo). Sus horarios se filtran del LP pero cuentan como
  cubiertos en la validación del cronograma.

> El panel de sincronización es la herramienta para curar
> excepciones puntuales sin ensuciar el catálogo. Recomendado
> correrlo al final de la carga del ciclo para chequear que el
> estado esté alineado con las reglas vigentes.

### 1.5 Cargar el cronograma

En `📅 Cronogramas → 📤 Cargar`:

1. Seleccionar el ciclo.
2. Cargar el archivo Excel/CSV con los horarios.
3. La prevalidación contrasta el cronograma contra los dictados
   creados en el paso 1.3 y reporta:
   - **Materias esperadas cubiertas** (dictado existe y hay
     horarios en el cronograma). ✅
   - **Materias esperadas no cubiertas** (dictado existe pero no hay
     horarios cargados). ⚠️
   - **Horarios no esperados** (hay horarios cargados para una
     materia sin dictado, o materia inexistente en el ciclo). ❌
4. Resolver issues en el editor in-place o volver al panel de
   dictados si faltan crear dictados.

Las materias marcadas como virtuales (por cualquiera de los tres
niveles) cuentan como cubiertas aunque no tengan horarios: es
consistente con el hecho de que no consumen aula.

### 1.6 Generar plan, validar, activar, asignar aulas

Este tramo del flujo lo cubre `WORKFLOW.md` a partir de la § 4. En
resumen:

1. `📊 Planes → Generar plan`: deriva comisiones y horarios
   estructurados desde el cronograma.
2. `📊 Planes → Detalle`: ajustes finos por materia (comisiones,
   pesos, override de inscriptos esperados).
3. Validar el plan: cobertura de dictados, no-superposición por
   carrera-año-cuatri, partición teoría/lab consistente con lo
   declarado en las materias.
4. Activar el plan (genera `ClaseDB` con fechas concretas).
5. Correr el asignador de aulas (`🎯 Asignación`).

## 2. Chequeos previos al asignador de aulas

Del mapa de las tres puertas de `RECURSADO_Y_VIRTUAL.md § 1.2` se
deriva un checklist operativo antes de correr el LP:

- [ ] **Versiones de plan asignadas al ciclo**. ¿Están todas las
      carreras que deberían participar? ¿La versión de cada carrera
      es la vigente para este cuatrimestre?
- [ ] **Flags `dicta_recursado` de carreras**. ¿Los defaults reflejan
      la política actual de cada carrera?
- [ ] **Overrides `MateriaDB.dicta_recursado`**. ¿Alguno arrastrado
      de decisiones viejas? Correr `🔄 Sincronizar según reglas`
      para hacer el diff visible.
- [ ] **Modalidad virtual del catálogo (`MateriaDB.virtual`)**. ¿Solo
      las materias efectivamente virtuales por diseño?
- [ ] **Modalidad virtual del ciclo (`DictadoDB.virtual`)**. ¿Algún
      dictado marcado virtual por un caso puntual del ciclo anterior
      que se copió sin querer? Revisar en el panel de dictados.
- [ ] **Cronograma cargado y prevalidado**. Todos los dictados no
      virtuales tienen horarios cargados. La prevalidación no reporta
      "no esperadas".
- [ ] **Grupos de materias configurados** (para R10 y R12 del LP).
      Ver `ASIGNACION_IMPL.md § 5`.

## 3. Escenario concreto: cargar el 2C 2026 para la demo

Este escenario documenta la carga concreta del segundo cuatrimestre
de 2026 sobre la base de datos que ya tiene el 1C 2026 configurado,
como preparación para la demo de la herramienta a fines del 2C 2026
y para dejar el patrón montado para la cursada 2027.

### 3.1 Estado de partida

- Existe `CicloDB(id="2026-1C")` con sus dictados, cronograma y (si
  aplica) plan de cursada activo.
- Existen `PlanCarreraVersionDB` vigentes para todas las carreras
  del alcance del proyecto.
- Datos concretos del cronograma del 2C 2026 disponibles en formato
  Excel (equivalente al que carga la Secretaría Académica).

### 3.2 Paso 1: crear el ciclo 2026-2C

En `📆 Ciclos → 📋 Ciclos → Crear ciclo nuevo`:

- Año: `2026`.
- Cuatrimestre: `2`.
- Fecha inicio / Fecha fin: fechas oficiales del 2C 2026.
- Versiones de plan: las **mismas** que están asignadas al
  `2026-1C`, salvo que alguna carrera haya actualizado su versión
  de plan entre cuatrimestres.

Al guardar, se crea la fila `CicloDB("2026-2C")` sin ningún
dictado todavía. El ciclo es una unidad autónoma respecto del 1C:
no hereda ni horarios ni comisiones ni asignaciones.

### 3.3 Paso 2: crear los dictados del 2C 2026

En `📆 Ciclos → 📚 Dictados`, seleccionar `2026-2C` y tocar
**"Crear dictados"**. El resultado esperado:

- **Anuales**: para cada materia anual, se **linkea** el
  `DictadoDB` existente del `2026-1C` al `2026-2C` vía una nueva
  fila de `DictadoCicloDB`, y se completa `fin_dictado` con la
  fecha de fin del 2C. En el resumen aparecen como `linked` (no
  `created`).
- **Cuatrimestrales del 2C**: se crean con `dictado_codigo` =
  `"{materia}-2026-2C"`.
- **Cuatrimestrales del 1C**: aplica la regla de recursado. Las
  que la resolución da `True` se crean; las que da `False` se
  saltan con conteo en `skipped_recursado`.

Verificar en el resumen:

- Total de dictados creados + linkeados coincide con la cantidad
  esperada de materias del 2C (según los planes asignados).
- Los `skipped_recursado` corresponden a materias que efectivamente
  no se ofrecen al recursado. Si aparece alguna que sí debería
  ofrecerse, revisar la puerta 2 (probablemente falta setear
  `MateriaDB.dicta_recursado=True` o cambiar el flag de la
  carrera).

### 3.4 Paso 3: cargar el cronograma del 2C 2026

En `📅 Cronogramas → 📤 Cargar`:

1. Seleccionar `2026-2C`.
2. Subir el Excel con los horarios del 2C.
3. Revisar el reporte de prevalidación:
   - Las materias esperadas no cubiertas indican dictados sin
     horarios cargados (o hay que agregarlos al cronograma o el
     dictado se creó de más).
   - Los horarios no esperados indican materias que están en el
     cronograma pero no tienen dictado creado. Si son legítimas,
     crear el dictado desde el panel de divergencias.

Iterar hasta que la prevalidación quede limpia.

### 3.5 Paso 4: generar plan, validar y asignar

Seguir el flujo estándar de `WORKFLOW.md`:

1. `📊 Planes → Generar plan` desde el cronograma del 2026-2C.
2. Ajustar detalle del plan si es necesario.
3. Validar (sin conflictos no ignorados).
4. Activar el plan.
5. Correr el asignador de aulas.

### 3.6 Notas para la demo

- La demo puede correr el asignador sobre el 2C 2026 sin afectar en
  nada al 1C 2026 (por RN19). Ambos ciclos son independientes: se
  puede correr y re-correr el LP del 2C sin que las asignaciones
  del 1C se vean tocadas.
- El plan de cursada del 2C 2026 se puede crear como escenario
  simulado ("plan inicial", "plan optimizado") sin activarlo, para
  comparar variantes durante la demo.
- Si durante la demo se quiere mostrar el efecto de un cambio
  puntual (por ejemplo, una comisión adicional), conviene tener
  preparado un plan alternativo del mismo ciclo con esa variante
  ya cargada, en lugar de editar el activo en vivo.

## 4. Escenarios recurrentes que resuelve el modelo

### 4.1 Materia del 1C que se ofrece también al recursado en el 2C

Se maneja con la puerta 2 (regla de recursado). Dos formas:

- **Regla amplia**: la carrera tiene `dicta_recursado=True` (default).
  Al crear el ciclo 2C, `create_dictados_for_ciclo` crea el dictado
  de esa materia automáticamente.
- **Override puntual**: la carrera tiene `dicta_recursado=False` en
  general, pero para esta materia se quiere ofrecer recursado.
  Setear `MateriaDB.dicta_recursado=True` como override del
  catálogo.

### 4.2 Materia declarada anual pero que solo se dicta un cuatrimestre

No es lo habitual y la herramienta no tiene una noción de "anual
que se corta en el 1C". Si esto pasa, la vía correcta es cambiar
`MateriaDB.periodo` a `"cuatrimestral"` (probablemente el plan de
estudio ya lo indica así). Como alternativa temporaria, borrar el
`DictadoCicloDB` del 2C.

### 4.3 Recursado por Zoom (virtual sólo en un ciclo)

Setear `DictadoDB.virtual=True` desde el panel de dictados del
ciclo. Los horarios de ese dictado se filtran del LP pero cuentan
como cubiertos en el cronograma. El catálogo (`MateriaDB.virtual`)
sigue en `False`.

### 4.4 Comisión híbrida (algunos horarios presenciales, otros virtuales)

Setear `HorarioDB.virtual=True` en los horarios específicos que son
virtuales, desde el editor inline de la grilla del plan. El resto
del dictado sigue presencial.

### 4.5 Materia que se saca del plan de estudio (nueva versión)

Crear una nueva `PlanCarreraVersionDB` sin esa materia. Asignar la
nueva versión al próximo ciclo vía `CicloPlanVersionDB`. Los ciclos
existentes que siguen apuntando a la versión anterior no se ven
afectados. En el nuevo ciclo, `create_dictados_for_ciclo`
directamente no considera la materia.

### 4.6 Reset y recrear todo un ciclo

Borrar el ciclo con `borrar_ciclo` (previo backup si hace falta) y
recrearlo desde cero. El borrado en cascada limpia
`CicloPlanVersionDB`, `DictadoCicloDB` (los dictados anuales que
quedan huérfanos solo del 1C no se borran, se mantienen), el
cronograma, el plan de cursada y las clases del ciclo.

## 5. Referencias cruzadas

- **Semántica formal**: `RECURSADO_Y_VIRTUAL.md § 1` (las tres
  puertas, independencia entre ciclos, sincronización).
- **RN19 (invariante de independencia)**:
  `1. Diseño/modelo-planificacion-cursada.md § 6` tabla de reglas
  de negocio.
- **Servicio principal**:
  `src/services/dictado_service.py`:
  - `create_dictados_for_ciclo`: crea dictados iniciales.
  - `sync_dictados_para_ciclo`: diff regla vs estado.
  - `_link_anual_dictado_2c`: reutilización de anuales.
  - `_should_skip_for_recursado`: aplicación de la puerta 2.
  - `borrar_dictado_de_ciclo`: baja individual.
  - `promover_a_regla`: propaga decisión del ciclo al catálogo.
- **Resolución jerárquica**:
  `src/services/resolucion_jerarquica.py` (`resolve_virtual`,
  `resolve_dicta_recursado`).
- **UI**:
  - `app/pages/4_📆_Ciclos.py` (tab Ciclos + tab Dictados).
  - `src/ui/divergencias_panel.py` (panel de sincronización).
- **Requerimientos**: `project/requerimientos.md`
  (RF-CICLO, RF-DICT).
