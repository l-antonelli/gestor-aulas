# Introducción

## ¿Qué es este sistema?

El **Gestor de Aulas** es una aplicación de escritorio que permite
organizar toda la planificación académica de un cuatrimestre en la
Facultad de Ciencias Exactas, Ingeniería y Agrimensura (FCEIA) de la
Universidad Nacional de Rosario.

Lo que hace, en resumen:

- Mantiene el **catálogo académico**: materias, carreras con sus
  planes de estudio, aulas y sedes.
- Permite armar los **ciclos lectivos** (1er y 2do cuatrimestre de
  cada año), decidiendo qué materias se dictan en cada uno.
- Carga los **cronogramas** de horarios que llegan desde la facultad
  y los valida contra el plan del ciclo.
- Genera los **planes de cursada** con sus comisiones y horarios
  semanales.
- Corre el **asignador de aulas**, que le busca a cada horario un aula
  del edificio respetando restricciones de tipo (teórica, laboratorio),
  sede admisible por carrera, choques temporales y capacidad frente a
  los inscriptos esperados.
- Registra el **historial de cambios** en las decisiones importantes
  (dictados, modalidad virtual, sedes por carrera, etc.).

Todo esto se hace desde el navegador web, en la máquina donde está
instalada la aplicación. **No requiere internet** una vez instalada.

## ¿Para quién está pensado?

- **Bedeles o personal de secretaría académica** que arman el
  cuatrimestre.
- **Coordinadores de carrera** que validan que la oferta esté
  completa.
- **Gestión de espacios físicos** que necesita saber cómo se están
  usando las aulas.

No hace falta ser técnico ni tener conocimientos de programación. Sí es
útil tener claros los conceptos académicos básicos: qué es una carrera,
un plan de estudios, una materia, una comisión, un cuatrimestre.

## ¿Qué NO hace el sistema?

Para que las expectativas estén claras desde el arranque:

- **No gestiona inscripciones de alumnos**. No es SIU-Guaraní ni un
  reemplazo. Los "inscriptos" que carga son valores agregados por
  materia y cuatrimestre (útiles para estimar demanda), no listas
  nominales.
- **No coordina docentes**. No hay agenda de profesores ni asignación
  de titularidades — sólo horarios y aulas.
- **No tiene sistema de login**. Cualquiera que abra la aplicación
  accede a todo. El historial de cambios registra desde qué pantalla
  se hizo cada cambio, pero no quién.
- **No pretende ser un ERP académico**. Es una herramienta focalizada
  en un problema concreto: asignar aulas al arranque del cuatrimestre.
- **No comunica horarios a alumnos ni docentes**. Es un sistema
  interno de planificación. La comunicación externa se hace por los
  canales habituales de la facultad.

## Glosario básico

Estos términos se repiten en todo el manual. Vale la pena tenerlos
claros desde el principio.

### Términos del dominio académico

- **Materia** (o asignatura): unidad curricular del plan de estudios.
  Tiene código, nombre, carga horaria y período (cuatrimestral o
  anual). Ejemplo: "Análisis Matemático I", "Física III".
- **Carrera**: título académico completo. Ejemplo: "Ingeniería en
  Computación", "Licenciatura en Física".
- **Plan de estudios** (o "versión de plan"): la lista concreta de
  materias que componen una carrera. Una misma carrera puede tener
  varias versiones del plan (por reforma curricular). Cada versión
  tiene un nombre (ej. "Plan Original", "Plan 2020").
- **Ciclo**: cuatrimestre lectivo. Se identifica por año y número
  (ej. "2026-1C" o "2026-2C").
- **Cuatrimestre**: sinónimo de ciclo en el uso cotidiano.
- **Dictado**: la afirmación "esta materia se dicta en este ciclo".
  Si existe el dictado, la materia está activa ese cuatrimestre. Si
  no existe, no se dicta.
- **Comisión**: subgrupo de una materia. Una materia puede tener 1 o
  varias comisiones con distintos horarios o cupos.
- **Cronograma**: el archivo con horarios que llega de la facultad.
  Se sube al sistema, se valida y se convierte en un plan de cursada.
- **Plan de cursada**: la versión final y editable del cronograma
  para un ciclo. Es donde se corre el asignador de aulas y se
  guardan las asignaciones finales.
- **Aula**: espacio físico donde se dicta clase. Tiene código,
  capacidad, tipo (teórica, práctica, laboratorio, anfiteatro) y
  sede.
- **Sede**: edificio de la facultad. Un aula pertenece a una sede.
- **Horario del patrón semanal**: cada fila del cronograma/plan que
  dice "día X, de hora A a hora B, materia M, comisión C". Es la
  unidad que el asignador asigna a un aula.
- **Clase**: cada ocurrencia concreta de un horario en una fecha
  específica del ciclo. Las clases se generan automáticamente a
  partir del patrón semanal cuando se activa el plan.

### Términos operativos del sistema

- **Asignador de aulas**: la herramienta que decide qué aula usa cada
  horario del plan. Toma en cuenta capacidad, tipo de aula, sedes
  admisibles por carrera y choques temporales. En el manual siempre
  se lo llama "el asignador" — nunca "el LP" ni "el solver".
- **Corrida** (del asignador): cada vez que se aprieta "Asignar
  aulas", el sistema hace una corrida completa y guarda el
  resultado. Podés tener varias corridas históricas por plan.
- **Peso** (de una comisión): número que indica cuánto de los
  inscriptos esperados de la materia se atribuyen a esa comisión. Si
  hay dos comisiones con peso 0.5 y 0.5, se dividen la demanda por
  la mitad.
- **Redistribución de pesos**: opción avanzada del asignador que le
  permite proponer una redistribución distinta a la actual si eso
  ayuda a resolver.
- **Cupo**: cantidad máxima de inscriptos esperada para la comisión.
  Es un dato administrativo — no se usa como restricción dura del
  asignador (que sí mira la capacidad real del aula).
- **Modalidad virtual**: cuando una materia, dictado u horario se
  dicta por Zoom (o similar) y no consume aula. Es una decisión que
  se toma **por ciclo** — la misma materia puede ser presencial un
  cuatrimestre y virtual otro.
- **Regla de recursado**: la política que decide, para cada materia,
  si se dicta en el cuatrimestre "opuesto" a su ubicación en el plan
  (una materia de 2do cuatri también se recursa en el 1er cuatri, o
  no).
- **Diagnóstico**: cuando el asignador no puede resolver, produce un
  reporte que explica dónde está el problema (aulas faltantes de un
  tipo, choques imposibles, cuellos de botella, etc.).
- **Mapa de calor**: representación visual de la carga del sistema.
  Días × franjas horarias × sede, coloreado según ocupación.
- **Panel de divergencias**: en Ciclos, muestra las diferencias entre
  los dictados actuales y los que la regla dice que deberían existir.
- **Historial**: registro automático de los cambios importantes de
  catálogo y política. Se ve desde la página 📜 Historial.

### Jerarquía de virtualidad

La modalidad virtual puede definirse a **tres niveles**:

1. **Materia** (a nivel catálogo): "esta materia es virtual siempre,
   por defecto". Se define en la página 📚 Materias.
2. **Dictado** (a nivel ciclo): "en este ciclo puntual, esta materia
   es virtual (o presencial), independientemente del catálogo". Se
   define en 📆 Ciclos → 📚 Dictados.
3. **Horario individual** (a nivel patrón): "este horario particular
   es virtual (por ejemplo, se dicta por Zoom por acuerdo con los
   alumnos)". Se define desde el editor del cronograma o desde el
   inspector de franja en la asignación de aulas.

La regla es: **el nivel más específico manda**. Si un horario está
marcado como virtual, no importa qué diga el dictado o la materia; se
respeta lo del horario. Si el horario dice "heredar", entonces se mira
el dictado; si el dictado dice "heredar", se mira la materia.

Esta jerarquía es importante porque simplifica muchos casos: podés
marcar "toda la materia virtual" sin tocar horario por horario, o
podés hacer una excepción puntual sin cambiar el catálogo.

## Modelo mental global

Si tuvieras que explicarle a alguien de qué se trata este sistema en
30 segundos, podrías decir algo así:

> "Es un sistema para organizar cada cuatrimestre de la facultad.
> Cargamos las materias y las carreras una sola vez. Después, cada
> cuatrimestre creamos un 'ciclo', decimos qué materias se dictan,
> subimos el archivo con los horarios que arma la facultad, hacemos
> un plan de cursada, y le pedimos al sistema que asigne un aula a
> cada horario. El sistema es inteligente: entiende qué materias son
> laboratorios, qué carreras se dictan en qué sedes, cuántos
> inscriptos esperar, y trata de encontrar la mejor asignación
> posible. Si no puede, te explica por qué."

Esa es la esencia. El resto son detalles operativos.

## Cómo está organizada la aplicación

La aplicación se ve como un sitio web con un **menú lateral** que
lista todas las páginas. Cada página cubre un módulo:

```
📚 Materias
🏛️ Aulas y Sedes
🎓 Carreras
📆 Ciclos
📊 Planes
📅 Cronogramas
📈 Inscriptos
📜 Historial
```

Dentro de cada página hay **solapas** (tabs) que agrupan tareas. Por
ejemplo, la página 📚 Materias tiene solapas para "Lista", "Crear" y
"Buscar".

En este manual, cada módulo del menú tiene su propio archivo:
`modulos/01_Materias.md`, `modulos/02_Aulas_y_Sedes.md`, etc.

## Próximo paso

Andá a **[01 — Primeros pasos](01_Primeros_pasos.md)** para arrancar
la aplicación y darle una recorrida.
