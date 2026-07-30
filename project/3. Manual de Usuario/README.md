# Manual de Usuario — Sistema de Asignación de Aulas

Bienvenido al manual de usuario del sistema **Gestor de Aulas** de FCEIA
(UNR). Este manual está pensado como material de consulta rápida y como
base para escribir manuales impresos o videos instructivos.

Todo el contenido está redactado para un usuario final que no necesita
conocer detalles técnicos: hablamos de "el asignador de aulas", no de
"el solver LP"; de "el patrón semanal", no de tablas de base de datos.

---

## ¿Por dónde empezar?

Si es tu primera vez con el sistema, seguí este orden:

1. **[00 — Introducción](00_Introduccion.md)** — qué es el sistema, qué
   podés hacer con él, para quién está pensado, y un glosario de los
   términos que más se repiten.
2. **[01 — Primeros pasos](01_Primeros_pasos.md)** — cómo abrir la
   aplicación, orientarte en la interfaz y verificar que los datos
   base estén cargados.
3. Después, según lo que necesites hacer, consultá el flujo o el módulo
   correspondiente (secciones de abajo).

Si ya conocés el sistema y necesitás resolver una tarea puntual, andá
directamente al **módulo** de la página que estás usando (sección
Módulos) o al **flujo** que estás ejecutando (sección Flujos).

---

## Flujos completos

Cada flujo describe una tarea end-to-end que atraviesa varios módulos.
Usalos cuando querés hacer algo "de la cuna a la tumba":

- **[Flujo 1 — Setup inicial de la base](flujos/01_Setup_inicial.md)**:
  primera instalación, cargar los Excel maestros, ajustar el catálogo
  antes de empezar a trabajar.
- **[Flujo 2 — Armar un cuatrimestre nuevo](flujos/02_Armar_un_ciclo_lectivo.md)**:
  el flujo troncal — crear el ciclo, cargar el cronograma, generar el
  plan de cursada, correr el asignador. Este es el flujo que más vas
  a usar.
- **[Flujo 3 — Reasignar aulas tras cambios](flujos/03_Reasignacion_de_aulas.md)**:
  qué hacer cuando ya corrió el asignador pero después hubo cambios
  (una comisión nueva, un aula que se dio de baja, un horario que se
  mueve, etc.).
- **[Flujo 4 — Verificación pre-inicio de cuatrimestre](flujos/04_Verificacion_pre_inicio.md)**:
  checklist consolidado para dar por cerrado el plan antes del arranque
  del cuatrimestre.

---

## Módulos (por página de la aplicación)

Uno por cada solapa del menú lateral. Cada módulo incluye tareas
comunes, errores frecuentes y preguntas frecuentes específicas:

- **[01 — Materias](modulos/01_Materias.md)** — catálogo maestro de
  asignaturas.
- **[02 — Aulas y Sedes](modulos/02_Aulas_y_Sedes.md)** — recursos
  físicos y su organización por sede.
- **[03 — Carreras](modulos/03_Carreras.md)** — carreras y planes de
  estudio.
- **[04 — Ciclos](modulos/04_Ciclos.md)** — períodos lectivos y
  dictados.
- **[05 — Planes y asignación de aulas](modulos/05_Planes_y_Asignacion_de_Aulas.md)**
  — plan de cursada, asignador de aulas, diagnóstico. Es el módulo más
  denso; conviene leer primero la sección "Modelo mental" antes de
  meterse en las tareas.
- **[06 — Cronogramas](modulos/06_Cronogramas.md)** — cronogramas de
  horarios que alimentan a los planes.
- **[07 — Inscriptos](modulos/07_Inscriptos.md)** — serie histórica de
  inscriptos y proyecciones para el forecast.
- **[08 — Historial](modulos/08_Historial.md)** — registro de cambios
  del sistema.

---

## ¿Cómo se relacionan los módulos entre sí?

El sistema tiene un flujo natural de dependencias. Este diagrama muestra
qué necesita estar en su lugar antes de que otra cosa funcione:

```
┌────────────────────────────────────────────────────────────┐
│  Catálogo maestro                                          │
│  ┌────────────┐  ┌────────────────┐  ┌──────────────────┐  │
│  │  Materias  │  │  Aulas y Sedes │  │    Carreras      │  │
│  └─────┬──────┘  └────────┬───────┘  └────────┬─────────┘  │
│        │                  │                   │            │
└────────┼──────────────────┼───────────────────┼────────────┘
         │                  │                   │
         └──────────┬───────┴───────────────────┘
                    ▼
         ┌────────────────────┐   ← acá arranca cada cuatrimestre
         │       Ciclos       │
         └──────┬─────────────┘
                │
                ▼
         ┌────────────────────┐
         │    Cronogramas     │
         └──────┬─────────────┘
                │
                ▼
         ┌────────────────────────────────────────┐
         │  Planes de cursada y asignación de     │
         │  aulas (con inscriptos como insumo)    │
         └────────────────────────────────────────┘

Historial: registra cambios de todo el proceso.
```

En rasgos generales:

1. **Catálogo maestro** (Materias, Aulas y Sedes, Carreras) se carga una
   vez y se mantiene con cambios puntuales. Es la base de todo lo
   demás.
2. **Ciclos** define un período lectivo (1er o 2do cuatri de un año).
   Se crea uno cada vez que arranca un cuatrimestre nuevo.
3. **Cronogramas** son los borradores de horarios que llegan de la
   facultad. Se cargan y validan contra los dictados del ciclo.
4. **Planes de cursada** se generan a partir de un cronograma validado.
   Es donde se corre el asignador de aulas.
5. **Inscriptos** alimenta el forecast que usa el asignador (opcional
   pero recomendado).
6. **Historial** registra automáticamente las decisiones importantes;
   sirve para investigar cambios pasados.

---

## Convenciones del manual

- **Rioplatense**. Tratamiento de tú informal ("vos", "poné", "andá").
- **Estilo**: instrucciones directas, sin exceso de tecnicismos.
- **Íconos**: los que aparecen en el manual son los mismos que la
  aplicación muestra en la interfaz (📚 📅 🎓, etc.). No inventamos.
- **Advertencias**: cuando algo tiene un comportamiento que puede
  sorprender o que hay que hacer con cuidado, aparece un bloque tipo:
  > **Cuidado**: ...
- **TODO**: si en algún manual aparece un bloque `> TODO`, significa
  que ese punto necesita confirmación del equipo de desarrollo antes
  de darlo por definitivo.

---

## ¿Encontraste un problema?

Si algún paso no funciona como el manual dice, hay tres posibilidades:

1. **Es un bug conocido**: los bugs identificados durante la auditoría
   están consolidados en
   `project/2. Desarrollo/HALLAZGOS_AUDITORIA.md` (uso interno del
   equipo). Chequealo antes de reportar.
2. **Cambió el código**: el manual se generó a partir del estado del
   código en 2026-07-30. Es posible que un cambio posterior desalinee
   una instrucción.
3. **Hueco en el manual**: si es algo que directamente no se cubre,
   avisale al equipo — se puede completar en una revisión posterior.

---

## Para el equipo técnico

El documento **[`project/2. Desarrollo/WORKFLOW.md`](../2.%20Desarrollo/WORKFLOW.md)**
sigue siendo la referencia técnica interna con nombres de tablas,
servicios y detalles de implementación. Este manual de usuario **no**
lo reemplaza — son complementarios.

El registro de hallazgos de la auditoría está en
**[`project/2. Desarrollo/HALLAZGOS_AUDITORIA.md`](../2.%20Desarrollo/HALLAZGOS_AUDITORIA.md)**.
