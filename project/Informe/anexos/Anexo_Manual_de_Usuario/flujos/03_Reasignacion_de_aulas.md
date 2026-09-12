# Flujo 3 — Reasignar aulas tras cambios

## ¿Cuándo usar este flujo?

Cuando ya corriste el asignador y tenés aulas asignadas, pero después
apareció algún cambio que hace que la asignación quede desactualizada:

- **Se abre una comisión nueva** (más inscriptos de lo previsto).
- **Se cierra una comisión** (cambios administrativos).
- **Se agrega o quita un aula** al inventario de la facultad.
- **Se mueve un horario** (día u hora distintos a los originales).
- **Se cambia la modalidad** de una materia (pasa de presencial a
  virtual, o al revés).
- **Se cambia la carrera asignada** de una comisión (por overlap
  entre carreras).
- **Se ajustan las sedes habilitadas** de una carrera.
- **Se cambian los cupos o pesos** de las comisiones.

En cualquiera de estos casos, la asignación anterior ya no
necesariamente es la mejor (ni siquiera válida). Este flujo te
guía para reflejar los cambios sin romper el trabajo previo.

## Estado esperado antes de arrancar

- Plan activo con al menos una corrida del asignador previa.
- Sabés qué cambio hay que reflejar.

## Pasos

### Paso 1 — Aplicar los cambios estructurales

Dependiendo de qué cambió, andá a la página correspondiente:

- **Comisión nueva o cerrada, o cambio de cupo/peso/carrera
  asignada**: 📊 Planes → 🔍 Detalle del Plan (o 📋 Grilla Horaria) →
  editar la materia y ajustar comisiones.
- **Horario movido o agregado**: 📊 Planes → 📋 Grilla Horaria →
  drag/click/select en el calendario.
- **Modalidad virtual de una materia**: 📆 Ciclos → 📚 Dictados →
  toggle virtual → aplicar cambios.
- **Modalidad virtual de un horario específico**: 📊 Planes → 📋
  Grilla Horaria → editar horario → cambiar virtual.
- **Aula nueva o baja de aula**: 🏛️ Aulas y Sedes.
- **Sedes admisibles de una carrera**: 🎓 Carreras → editar carrera →
  sección "Sedes habilitadas".
- **Laboratorios compatibles**: 📚 Materias → editar materia →
  solapa "Laboratorios".

Verificá siempre que el cambio se haya persistido (buscá un toast de
confirmación).

> **Cuidado**: si moviste un horario a otro día u hora, el sistema
> guarda el aula que tenía asignada previamente. Esa aula puede
> quedar en conflicto con otras clases del nuevo horario. **La única
> forma de reconciliarlo es volver a correr el asignador**. Al
> hacerlo, el asignador va a reevaluar todo y asignar de nuevo.

### Paso 2 — Volver a validar (si el cambio fue estructural)

Si el cambio afectó al cronograma origen (por ejemplo, se movió un
horario que ya estaba en el cronograma), volvé a 📅 Cronogramas → ✅
Validar y corré la validación de nuevo. El badge del cronograma tiene
que quedar 🟢.

Si el cambio fue sólo en el plan (no en el cronograma), no hace falta
revalidar el cronograma.

### Paso 3 — Correr el asignador de nuevo

**Página**: 📊 Planes, solapa **🏛️ Aulas**.

1. Revisá la configuración. Probablemente ya está OK del run
   anterior, pero fijate especialmente en:
   - **Aplicar desde la fecha**: define desde qué fecha las clases
     se pisan con la asignación nueva. Las clases anteriores a esa
     fecha se mantienen intactas.
2. Apretá **🚀 Asignar aulas**.

El sistema corre otra vez y guarda una nueva corrida. La anterior
queda como histórico (podés compararla revisando las corridas
anteriores, aunque hoy no hay una pantalla directa que las liste).

### Paso 4 — Revisar diferencias

En el mismo panel, comparación implícita:

- Mirá el **mapa de saturación por sede** — ¿mejoró respecto al
  problema que te llevó a re-correr?
- Mirá la **tabla de resultados** — ¿los horarios afectados quedaron
  con las aulas esperadas?
- Mirá el **cronograma por aula** — ¿no se generaron choques?

### Paso 5 — (Opcional) Redistribución de pesos

Si activaste el toggle **Redistribuir pesos entre comisiones**, el
asignador puede haber propuesto una redistribución de los pesos que
mejora la asignación. Vas a ver una tabla con pesos actuales vs.
propuestos y dos botones:

- **Aplicar nuevos pesos**: guarda la propuesta como el nuevo peso
  de cada comisión.
- **Descartar**: deja los pesos como estaban.

Ojo: si descartás, las aulas que asignó el asignador quedan pero los
pesos NO reflejan la asignación efectiva. Es recomendable **aplicar**
si aceptás la propuesta.

## Sobre la fecha desde

El parámetro **"Aplicar desde la fecha"** merece una mención aparte
porque tiene consecuencias que a veces sorprenden:

- Las **clases con fecha anterior** a "Aplicar desde" se **preservan
  intactas**. Si ya se dictaron o están por dictarse esta semana con
  aulas asignadas, no las tocás.
- Las **clases con fecha igual o posterior** se **actualizan** con la
  nueva asignación.

Casos típicos:

| Caso | Recomendación |
|---|---|
| Recién arrancó el cuatri, aparece cambio | Poné fecha = hoy. Las clases pasadas quedan como se dictaron. |
| Estás preparando el cuatri antes del arranque | Poné fecha = inicio del ciclo. Todas las clases se asignan. |
| Cambio que afecta sólo desde mitad de cuatri | Poné fecha del día donde arranca el cambio. |
| Querés pisar todo, incluso lo pasado | Poné una fecha muy anterior al inicio del ciclo. Ojo: reescribís el histórico. |

## Verificación final

Después de la reasignación:

- La corrida más reciente está en **✅ resuelta** (o feasible).
- Las métricas de over/under están dentro de tolerancias.
- El cambio que motivó la reasignación se ve reflejado en la tabla
  de resultados.
- El cronograma por aula del aula afectada muestra el estado nuevo
  correcto.

## Rollback

Los resultados del asignador quedan como histórico automáticamente.
Si querés "volver atrás" a una asignación anterior:

- Opción A: correr el asignador con la configuración anterior (si
  te acordás cuál era).
- Opción B: editar a mano las aulas de los horarios afectados desde
  el cronograma por aula del panel de asignación.
- No hay un botón "revertir a la corrida N-1".

## Puntos de fricción típicos

- **Moviste horarios y el cronograma por aula muestra choques**:
  es porque el sistema todavía tiene las aulas viejas asignadas.
  Corré el asignador de nuevo y se resuelve.
- **La corrida da infactible después de un cambio que "no debería"
  romper nada**: revisá si al cambio le agregaste alguna
  restricción sin querer (por ejemplo, marcar una comisión con
  carrera asignada que reduce las sedes admisibles).
- **Cambiaste sedes admisibles de una carrera y no se reflejó**:
  las sedes admisibles se leen fresco en cada corrida del
  asignador. Corré de nuevo y va a tomarlas.
- **Toggle "Respetar ediciones manuales"**: por ahora no hace nada
  visible. Si editaste un aula a mano antes de re-correr, el
  asignador probablemente la pise. Podés volver a hacer la edición
  manual después.

## Próximo paso

- Si el cambio fue justo antes del arranque del cuatri, seguí con la
  **[Verificación pre-inicio](04_Verificacion_pre_inicio.md)**.
