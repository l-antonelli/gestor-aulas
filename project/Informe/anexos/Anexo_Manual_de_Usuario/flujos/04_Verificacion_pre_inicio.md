# Flujo 4 — Verificación pre-inicio de cuatrimestre

## ¿Cuándo usar este flujo?

**Días antes del inicio del cuatrimestre**, cuando vas a dar por
cerrado el plan y comunicar la asignación oficial. Es un **checklist
consolidado** que recorre varias páginas para asegurarte que todo
esté en orden.

Se recomienda hacerlo:
- **48 a 72 horas antes** del primer día de clases.
- **Después de cualquier reasignación tardía**.
- Como **rutina periódica** durante el cuatrimestre (una vez por
  mes) para detectar drift.

## Estado esperado antes de arrancar

- Plan activo del ciclo, con al menos una corrida del asignador
  óptima.

## Cómo usar esta guía

Recorré cada sección en orden. En cada punto, hacé la verificación
que se indica y marcá el checkbox mentalmente (o imprimí este
documento y usá los `[ ]` como checklist real).

Si algún punto **no cumple**, el flujo te dice qué hacer para
corregirlo (típicamente, volver a alguna página y usar el
**[Flujo 3 — Reasignación](03_Reasignacion_de_aulas.md)**).

---

## 1. Ciclos y dictados

**Página**: 📆 Ciclos, solapa **📚 Dictados**.

- [ ] Seleccionaste el ciclo actual.
- [ ] El **panel de divergencias** está vacío (banner verde "✅ No
      hay divergencias") o las divergencias que quedan tienen
      justificación clara.
- [ ] Los toggles **Virtual** reflejan la modalidad real de cada
      materia este cuatrimestre.
- [ ] La regla de recursado está bien: no hay materias marcadas como
      "excepción" a menos que corresponda.
- [ ] No hay **cambios pendientes sin aplicar** al pie de la página
      (el bloque "⏳ Cambios pendientes" está vacío).
- [ ] Para materias anuales: si es 2C, verificaste que el bridge al
      1C esté vigente.

### Si algo falla acá

- Divergencias pendientes → resolver desde el panel de divergencias.
- Virtualidad mal marcada → ajustar el toggle y aplicar cambios.
- Cambios pendientes → aplicar o descartar antes de continuar.

---

## 2. Cronograma

**Página**: 📅 Cronogramas.

- [ ] Sabés cuál es el **cronograma "vigente"** del ciclo (el que se
      usó para generar el plan activo).
- [ ] Ese cronograma tiene badge **🟢 Validado y vigente**.
- [ ] No hay cronogramas "de trabajo" antiguos que puedan confundir —
      renombralos o borralos si ya no aplican.
- [ ] Si hubo cambios recientes en el cronograma, revalidaste (badge
      🟡 significa que hay que re-correr Validar).

### Si algo falla acá

- Badge 🟡 → ir a solapa Validar y volver a validar.
- Badge 🔴 → hay issues, resolverlos antes de seguir.
- Múltiples cronogramas confusos → usar la solapa Lista para
  renombrar o borrar los que no aplican.

---

## 3. Plan de cursada

**Página**: 📊 Planes, solapa **📋 Vista General** y **🔍 Detalle**.

- [ ] Hay **exactamente un plan activo** en el ciclo (badge 🟢
      ACTIVO).
- [ ] El plan activo es el que corresponde (no un borrador viejo).
- [ ] Todas las materias esperadas tienen al menos una comisión.
- [ ] Todas las comisiones tienen al menos un horario.
- [ ] Los cupos y pesos de las comisiones son coherentes con los
      inscriptos esperados de la materia.
- [ ] El **panel de validación** del plan (dentro del tab Detalle)
      no muestra conflictos sin resolver.
- [ ] Los snapshots de validación están **vigentes** (no aparecen
      marcados como desactualizados).

### Si algo falla acá

- Sin plan activo → activar el plan correcto (usar "Activar plan"
  desde el panel de validación para generar clases).
- Múltiples planes activos → activar uno solo. Al activar,
  automáticamente se desactivan los demás del ciclo.
- Conflictos en validación → resolverlos siguiendo las
  recomendaciones del propio panel.
- Snapshots stale → refrescar la validación desde el panel.

---

## 4. Asignación de aulas

**Página**: 📊 Planes, solapa **🏛️ Aulas**.

- [ ] La corrida más reciente del asignador está en **✅ resuelta**.
- [ ] La fecha de la corrida es **reciente** (no es una del mes
      pasado sin haber revalidado tras cambios).
- [ ] En el **mapa de saturación por sede** no hay celdas 🔴
      (>100%). Las 🟡 (80-100%) son tolerables pero conviene
      chequearlas.
- [ ] La **tabla de resultados** muestra mayoría de horarios en 🟢.
      Los 🔴 (sobre-ocupados) tienen justificación (por ejemplo, un
      curso muy chico en un aula grande no es problema; un curso
      grande en un aula chica sí).
- [ ] El **cronograma por aula** (expander al final) no muestra
      choques: no hay dos comisiones distintas en la misma aula, mismo
      día y misma franja.
- [ ] Todos los horarios no virtuales tienen aula asignada. Los
      virtuales están correctamente sin aula.
- [ ] Los tipos de aula coinciden con lo que la materia pide (aulas
      teóricas para clases teóricas, laboratorios compatibles para
      clases de lab).

### Si algo falla acá

- Corrida no óptima → seguir el flujo de diagnóstico (ver Flujo 2
  paso 9 y el módulo Planes).
- Corrida vieja → correr de nuevo con
  **[Flujo 3](03_Reasignacion_de_aulas.md)**.
- Saturación 🔴 → identificar la franja, redistribuir o marcar
  virtual.
- Choque en cronograma por aula → correr el asignador de nuevo
  (probablemente un horario se movió después del último run).
- Aulas incorrectas para el tipo → revisar `MateriaLaboratorioDB` de
  la materia o el tipo de aula.

---

## 5. Aulas y sedes

**Página**: 🏛️ Aulas y Sedes.

- [ ] Todas las aulas del edificio están cargadas y **activas**.
- [ ] Ninguna aula que esté fuera de servicio (por reforma, corte de
      luz, etc.) aparece como disponible. Si hay que dar de baja
      alguna temporalmente, sacala del inventario y volvé a correr
      el asignador.
- [ ] La **sede default para materias comunes** está correctamente
      marcada.
- [ ] Cada aula tiene el **tipo correcto** (teórica, práctica,
      laboratorio, anfiteatro).
- [ ] Las capacidades reflejan la realidad (no hay aulas con
      capacidad = 1 por default sin haber puesto el número real).

---

## 6. Carreras y sedes habilitadas

**Página**: 🎓 Carreras.

- [ ] Cada carrera tiene sus **sedes habilitadas** configuradas (o
      queda claro que se opta por "todas las sedes").
- [ ] La política de **recursado** de cada carrera es la deseada.
- [ ] La **cantidad de materias esperadas** está cargada, y las
      barras de completitud muestran ≥ el número esperado.

---

## 7. Inscriptos (si el forecast se usa)

**Página**: 📈 Inscriptos.

- [ ] La serie histórica está cargada al día (año actual y anteriores
      completos).
- [ ] No hay muchas materias en la sección **"Materias sin datos"**
      (idealmente cero, o justificadas).
- [ ] La sección **"Sin matchear"** está vacía o los códigos que
      quedaron sin asociar no son relevantes.
- [ ] Si alguna materia tiene **override manual** ("Total esperado
      manual"), ese valor es correcto para el cuatrimestre actual
      (revisar desde 📊 Planes → 🔍 Detalle → editor por materia).

> **Cuidado**: ediciones sobre esta página no dejan rastro en el
> historial. Es importante que todos los cambios en Inscriptos estén
> hechos por una única persona o coordinados por email para evitar
> pisadas silenciosas. Además, al filtrar por cuatrimestre y guardar,
> hay un bug conocido — ver el manual del módulo Inscriptos.

---

## 8. Historial

**Página**: 📜 Historial.

- [ ] Andá al **Feed global** y revisá los cambios de las últimas
      **48 horas**.
- [ ] No hay **cambios inesperados** de otros usuarios (dictados que
      se borraron, materias que cambiaron modalidad, etc.).
- [ ] Si hubo cambios, entendés por qué se hicieron.

Si estás compartiendo la máquina con otros operadores, este chequeo
es especialmente importante.

---

## 9. Cierre y comunicación

Una vez que todos los puntos anteriores están OK:

- [ ] **Guardá un backup manual** de la base de datos. El equipo
      técnico puede ayudarte con esto — típicamente es copiar el
      archivo `data/database.db` a `data/database_backup_YYYY-MM-DD.db`.
- [ ] Sacá **capturas de pantalla** del panel de resultado del
      asignador y del cronograma por aula para el registro oficial.
- [ ] **Comunicá** la asignación por los canales habituales de la
      facultad. El sistema no comunica automáticamente ni a alumnos
      ni a docentes.
- [ ] Anotá la **fecha de cierre** del plan por si aparecen cambios
      posteriores que haya que trackear.

---

## Rollback

Si en la verificación descubrís que algo grave está mal (por ejemplo,
un plan activo con muchas materias sin aula), tenés varias opciones:

- **Corrección puntual**: aplicar los cambios necesarios y volver a
  correr el asignador con el
  **[Flujo 3](03_Reasignacion_de_aulas.md)**.
- **Activar otro plan del mismo ciclo**: si ya hay otro plan
  borrador válido, podés activarlo (desactiva automáticamente el
  actual).
- **Empezar de cero**: si el problema es sistémico, borrá el plan y
  regenerá desde el cronograma (Flujo 2 desde el paso 7).

---

## ¿Qué NO chequear acá?

- **Datos de alumnos** (nombres, DNIs, inscripciones nominales): no
  los maneja este sistema.
- **Docentes asignados**: idem.
- **Calendario académico** (feriados, ventanas de examen): idem.

Estos aspectos se manejan por fuera del sistema en las plataformas
habituales de la facultad.

---

## Cerrado con éxito

Si todos los checks están OK, el plan está listo para el arranque
del cuatrimestre. ¡Buen cuatri! 🎓
