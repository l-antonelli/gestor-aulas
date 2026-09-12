# Reporte de verificación final del manual

## Resumen ejecutivo

El manual está en muy buen estado general. La terminología orientada al
usuario final (asignador, patrón semanal, dictado, plan de cursada) se
usa de manera consistente en los 15 archivos. Los enlaces internos entre
README, módulos y flujos resuelven correctamente. La cobertura de los
bugs críticos H01–H13 está prácticamente completa. Los hallazgos
materiales quedan reducidos a: cuatro fugas puntuales de jerga técnica
(nombres de tablas/columnas de base de datos, "stale", "infeasible"),
una inconsistencia leve entre "regla de recursado" y "política de
recursado", y algunos huecos menores de cross-linking.

## 1. Jerga técnica que se coló

Estos son los casos donde asoma vocabulario técnico en cuerpo de texto
(no dentro de secciones etiquetadas "Términos técnicos") y que sería
razonable pulir:

- **`modulos/05_Planes_y_Asignacion_de_Aulas.md:843`** — en la FAQ
  "¿Puedo correr el asignador de aulas antes de activar el plan?"
  aparece la frase "la asignación de aulas se guarda en el patrón
  (`HorarioDB`)". El nombre de la tabla `HorarioDB` es jerga y no aporta
  nada al usuario final. Sugerencia: reemplazar por "se guarda en el
  patrón semanal" o similar.
- **`flujos/03_Reasignacion_de_aulas.md:80`** — "podés compararla
  revisando los `LPRunDB` antiguos, aunque hoy no hay UI directa para
  eso". El nombre `LPRunDB` es jerga técnica que además contradice el
  espíritu del README (que promete "no hablamos de tablas de base de
  datos"). Sugerencia: "revisando el histórico de corridas del
  asignador".
- **`modulos/06_Cronogramas.md:194, 527, 531`** — aparece `codigo_guarani`
  en el body de la sección de warnings del importador, y luego "código
  Guaraní" (con G mayúscula) en el paso a paso. `codigo_guarani` es
  literalmente el nombre técnico de un campo. En este caso el texto es
  un warning literal que muestra el sistema, así que la mención está
  justificada, pero conviene aclarar en una nota qué significa
  "Guaraní" para el usuario que no conoce SIU-Guaraní.
- **`modulos/01_Materias.md:246, 266`** — la frase "error de tipo
  'FOREIGN KEY constraint failed'" aparece dos veces (en cuerpo y en
  tabla de errores). Es un error literal del sistema; conviene
  mantenerlo, pero enriquecerlo con una traducción del tipo "el sistema
  te va a mostrar un error de integridad referencial" para orientar al
  usuario no técnico.
- **`modulos/08_Historial.md`** — usa "hook" y "hooks" varias veces
  (`:134, :152, :389, :448`) para describir el mecanismo interno. Es
  jerga técnica y el usuario final no necesita entenderlo así. Además
  se referencia el nombre de tabla `change_log` (`:346, :382`) para
  usuarios avanzados que exportan por SQLite — este uso está
  justificado dado que el manual dice "consultar la base de datos".
- **`modulos/07_Inscriptos.md:98, 105`** — aparece el símbolo "α" (alfa)
  en la descripción del método SES ("SES (suavizado exponencial simple,
  α auto)") y en las métricas ("α para SES"). Para un usuario final es
  jerga estadística. Sugerencia: "parámetro de suavizado" en lugar de
  "α".
- **`flujos/04_Verificacion_pre_inicio.md:93, 103`** — usa "stale"
  (inglés) en el checklist ("Los snapshots de validación están vigentes
  (no aparecen como stale)"). Sugerencia: "desactualizados" en lugar
  de "stale".
- **`flujos/02_Armar_un_ciclo_lectivo.md:251, 255`** — usa "infeasible"
  entre paréntesis como sinónimo de "no se pudo resolver". En el mismo
  documento línea 363 y en otros lados se usa "infactible" (adaptación
  al español). Es un uso técnico y menor pero conviene homogenizar en
  "infactible".

**Cosas que están correctas y que este check confirmó**:
- Las únicas menciones de "LP" y "solver" en el cuerpo del manual están
  en la introducción y el README, y son declarativas ("nunca lo llamamos
  el LP ni el solver"). Correcto.
- No hay filtraciones de: `PuLP`, `CBC`, `pigeonhole`, `Hall`, `R1..R10`,
  `coef_asignacion`, `aula_asignada_manualmente`, `M:N`, `λ`.

## 2. Inconsistencias terminológicas

Los términos usados para conceptos clave son notablemente consistentes.
Sólo se detectaron dos casos:

- **"Regla de recursado" vs "política de recursado"**: el manual usa
  "regla de recursado" en 10 lugares (`modulos/04_Ciclos.md` × 7,
  `flujos/02_Armar_un_ciclo_lectivo.md`, `flujos/04_Verificacion_pre_inicio.md`)
  pero `modulos/03_Carreras.md:27` usa "política de recursado" una sola
  vez ("Cambio de política de recursado"). Recomendable unificar a
  "regla de recursado" para consistencia.
- **"Comisión modelo" vs "comisión del cronograma"**: en
  `modulos/05_Planes_y_Asignacion_de_Aulas.md:87` se define como
  sinónimos ("Comisión modelo (o 'comisión del cronograma')"), y
  `modulos/06_Cronogramas.md:682-684` los usa como sinónimos también.
  Esto está correcto porque se declara explícitamente la equivalencia;
  no es una inconsistencia sino una elección consciente.

**Íconos por módulo**: la revisión confirma consistencia en todos los
casos verificados. `📚 Materias`, `🏛️ Aulas`, `🎓 Carreras`, `📆 Ciclos`,
`📊 Planes`, `📅 Cronogramas`, `📈 Inscriptos`, `📜 Historial` se usan
uniformemente entre README, introducción, flujos y módulos. No hay
ninguna aparición de `📗` u otros íconos alternativos.

## 3. Referencias rotas

Los enlaces internos del manual fueron verificados. **Todos resuelven
correctamente**:

- README → todos los módulos (`modulos/01_Materias.md` a
  `modulos/08_Historial.md`) ✓
- README → todos los flujos (`flujos/01_Setup_inicial.md` a
  `flujos/04_Verificacion_pre_inicio.md`) ✓
- README → `../2. Desarrollo/WORKFLOW.md` ✓ (existe)
- README → `../2. Desarrollo/HALLAZGOS_AUDITORIA.md` ✓ (existe, con
  espacio URL-escapeado correctamente)
- `01_Primeros_pasos.md` → flujos y README ✓
- `flujos/02_Armar_un_ciclo_lectivo.md:335` → `04_Verificacion_pre_inicio.md`
  (path relativo dentro de `flujos/`) ✓
- `flujos/02:372` → `03_Reasignacion_de_aulas.md` (relativo) ✓
- `flujos/03:170` → `04_Verificacion_pre_inicio.md` (relativo) ✓
- `flujos/04:29, 135, 236` → `03_Reasignacion_de_aulas.md` (relativo) ✓
- `flujos/01:210` → `02_Armar_un_ciclo_lectivo.md` (relativo) ✓
- `01_Primeros_pasos.md:17` (`project/2. Desarrollo/DISTRIBUCION.md`)
  → referencia por texto (no link markdown), existe ✓

## 4. Contradicciones entre docs

No se detectaron contradicciones en flujos ni en la secuencia
recomendada de tareas. Las tres capas de virtualidad (materia →
dictado → horario) se explican consistentemente en:

- `00_Introduccion.md:140-160`
- `modulos/01_Materias.md:169-192`
- `modulos/04_Ciclos.md:104-127`
- `modulos/05_Planes_y_Asignacion_de_Aulas.md:137-154`
- `modulos/06_Cronogramas.md:80-86`

Todos coinciden en la regla "el nivel más específico manda".

Las dependencias entre módulos (catálogo → ciclos → cronogramas →
planes) también se describen de forma consistente en README,
introducción, y en la sección "Cómo se relaciona con el resto" de cada
módulo.

## 5. Cobertura de advertencias por bugs

Se verificó la cobertura de los bugs críticos H01–H13 tanto en los
módulos correspondientes como en los flujos que los atraviesan:

| Bug | Módulo (esperado) | Flujo (esperado) | Cobertura |
|-----|---|---|---|
| **H01** — Inscriptos borra otro cuatri al filtrar | `modulos/07_Inscriptos.md` (extensivo, secciones "Advertencia importante" y FAQ) ✓ | `flujos/04_Verificacion_pre_inicio.md:193` remite al manual del módulo ✓ | Completa |
| **H02** — Mover slot deja aula colgada | `modulos/05_Planes:559-561` ✓ y `modulos/06_Cronogramas` (edición) ✓ | `flujos/03_Reasignacion:52-56` ✓ | Completa |
| **H03** — Borrar cronograma deja huérfanos | `modulos/06_Cronogramas.md:456-475` (bloque "Atención" completo) ✓ | `flujos/02:346` menciona brevemente pero remite al módulo ✓ | Completa |
| **H04** — Crear carrera sin plan version | `modulos/03_Carreras.md:90-97` ("Paso siguiente crítico") ✓ | No aparece en `flujos/01_Setup_inicial.md` | **Hueco leve**: el flujo 1 (Setup Inicial) menciona verificar carreras (`:106-166`) pero no advierte explícitamente que después de crear una carrera nueva hay que crear la primera versión de plan. |
| **H06** — Import ignora comisión | `modulos/06_Cronogramas.md:164-176` ✓ | `flujos/02:117-121` ✓ | Completa |
| **H08** — Dos "Activar" distintos | `modulos/05_Planes:596-635` (extensivo) ✓ | `flujos/02:277-292` ✓ y `flujos/04:96-100` menciona indirectamente ✓ | Completa |
| **H09** — Toggle "Respetar" no hace nada | `modulos/05_Planes:381-390, 777-790` ✓ | `flujos/03:162-165` ✓ | Completa |
| **H12** — Cancelar wizard borra sin confirmar | `modulos/05_Planes:215-219` ✓ | `flujos/02:208-210` ✓ | Completa |
| **H13** — Eliminar Vista General borra sin confirmar | `modulos/05_Planes:238-243, 650-653` ✓ | Mencionado indirectamente en `flujos/02:341-343` (rollback) — no advierte lo del "sin confirmación" | **Cobertura parcial**: el flujo no advierte que el botón Eliminar de Vista General es destructivo instantáneo. |

**H07** (cutoff N días en Historial) y **H10/H11** (borrado sin
verificación de dependencias) están cubiertos parcialmente en los
módulos correspondientes (`08_Historial.md:193-199` y
`01_Materias.md:243-256` respectivamente).

## 6. Coherencia estilística

- **Tuteo (voseo rioplatense)**: consistente en todos los archivos. La
  búsqueda de "usted" no encontró ninguna ocurrencia. Uso uniforme de
  "vos", "podés", "andá", "cargá", "confirmá", "apretá".
- **Bloques de advertencia**: se usa consistentemente `> **Cuidado**:`,
  `> ⚠️ **Atención**:` y `> ℹ️`. Hay una leve heterogeneidad (a veces
  "Cuidado", a veces "Atención — operación destructiva", a veces
  "Precaución"), pero cada variante tiene un rol semántico claro.
- **Comillas**: uso consistente de comillas dobles (`"..."`). No se
  detectaron mezclas con `«...»` o comillas tipográficas.
- **Formato de listas**: mayormente con `-` (guiones). Uso ocasional
  de `1.`, `2.` para pasos numerados, coherente con la convención.

## 7. Huecos de completitud

- **`modulos/06_Cronogramas.md:666-667`** — hay un bloque
  `> TODO: verificar con el equipo si hay export disponible desde la
  interfaz.` Es el único TODO pendiente detectado en todo el manual.
  Recomendable resolverlo antes de dar el manual como cerrado.
- **Flujo 1 (Setup Inicial) no advierte de H04**: como se anotó en la
  sección 5, después de crear una carrera desde cero, hay que crear
  la primera versión del plan de estudio manualmente. El módulo de
  Carreras lo explica bien, pero el flujo de setup no cruza el
  cross-reference. Convendría agregar una nota en `flujos/01:153-166`
  (sección "En 🎓 Carreras" del paso 6) que remita al bloque "Paso
  siguiente crítico" del módulo Carreras.
- **README menciona `HALLAZGOS_AUDITORIA.md`** como "uso interno del
  equipo", pero un usuario que llegue por "encontré un problema"
  (`README.md:149-159`) podría no saber que no tiene acceso a ese
  documento. Es un tema menor: el mensaje aclara que es interno.
- **Flujo 2 paso 5** menciona "editar y asignarle un número" para las
  comisiones (`flujos/02:130-131`) pero no aclara cómo se agrega una
  comisión nueva. El detalle está en el módulo Cronogramas, pero un
  cross-link explícito ayudaría.
- **`00_Introduccion.md:141-160`** describe la "jerarquía de
  virtualidad" pero no la ilustra con un ejemplo concreto. Podría
  reforzarse con un mini-caso: "materia X no marcada como virtual,
  dictado 2026-1C sí virtual → resultado: el ciclo entero es virtual
  aunque la materia no lo sea por default".

## Recomendaciones priorizadas

**Prioridad alta** (afectan la experiencia del usuario final):

1. Reemplazar las cuatro fugas de nombres de tabla en cuerpo de texto
   (`HorarioDB` en `modulos/05`, `LPRunDB` en `flujos/03`, "stale" en
   `flujos/04`, "α" en `modulos/07`) por sinónimos accesibles.
2. Resolver el `TODO` de exportación en `modulos/06_Cronogramas.md:666`.
3. Agregar advertencia H04 en `flujos/01_Setup_inicial.md` (paso 6,
   sección Carreras).

**Prioridad media** (consistencia y pulido):

4. Unificar "política de recursado" (una ocurrencia en
   `modulos/03_Carreras.md:27`) a "regla de recursado".
5. Unificar "infeasible" (`flujos/02`) a "infactible".
6. Cross-link explícito de flujo 2 paso 5 al módulo Cronogramas para el
   detalle de creación de comisiones.

**Prioridad baja** (opcional):

7. Enriquecer las menciones a `FOREIGN KEY constraint failed` con una
   traducción para usuarios no técnicos.
8. Agregar un ejemplo concreto de la jerarquía de virtualidad en
   `00_Introduccion.md`.
9. Suavizar el uso de "hook" en `modulos/08_Historial.md` (aunque el
   módulo Historial acepta un usuario un poco más técnico dado que su
   contenido inherentemente lo es).
