## 3.11 Análisis y discusión

### 3.11.1 Desempeño del asignador sobre datos reales

El caso ensayado confirma que el modelo es resoluble en la práctica.
El programa lineal del cuatrimestre tiene 13.697 variables, 12.429 de
ellas binarias, y 6.952 restricciones (§3.4.7.1). Todas las corridas
de §3.10.4 terminaron en la solución óptima, en tiempos de entre 24 y
64 segundos según la configuración, y en todas quedaron con aula los
546 horarios presenciales.

Las reglas de política se cumplen por construcción. Ningún horario de
un grupo en modo duro quedó fuera de sus sedes admitidas (R8), salvo
en laboratorios declarados compatibles, los
laboratorios sólo se asignaron a materias declaradas compatibles, ninguna
comisión quedó repartida entre sedes (R12) y la validación del plan
confirmó que cada año de cada carrera tiene al menos un camino de
cursada sin superposiciones ni traslados imposibles. Lo que el modelo
no puede resolver es la falta física de aulas: cuando una comisión no
entra en ningún aula compatible, como los laboratorios de Informática
Aplicada (§3.10.2), el asignador minimiza el exceso y lo informa, pero
la solución está en la operatoria, por ejemplo abrir otra comisión.

### 3.11.2 Comparación con el proceso actual

No contamos con la asignación manual de un cuatrimestre completo en
formato comparable, por lo que la comparación es cualitativa, frente al
proceso descripto en la sección 3.3:

- **Tiempo.** Lo que hoy se resuelve con un proceso manual repartido
  entre varias áreas y apoyado en planillas (§3.3.2), el asignador lo
  resuelve en menos de un minuto, y volver a correrlo ante un cambio
  cuesta lo mismo.
- **Calidad verificable.** La asignación manual no tiene una medida de
  qué tan buena es. El sistema informa, para cada corrida, cuántos
  alumnos quedan sin lugar, cuántos asientos sobran y qué horarios
  salen de su sede, y garantiza que no haya dos clases en un aula a la
  vez.
- **Detección temprana.** La validación del cronograma señala antes de
  asignar las materias faltantes, los horarios que se superponen dentro
  de un año y los que no respetan la grilla; en el caso ensayado,
  detectó 29 materias esperadas que el cronograma no traía.
- **Escenarios.** Comparar configuraciones, como en §3.10.4, es
  impracticable a mano y lleva minutos con el sistema.
- **Trazabilidad.** Cada corrida queda registrada con su configuración y
  su resultado, y los cambios del catálogo quedan en el historial.

### 3.11.3 Limitaciones del modelo y del sistema

- **Patrón semanal.** El sistema asigna el patrón de la semana; las
  excepciones puntuales por fecha (un feriado, un examen) quedan fuera.
- **Calidad de los datos.** El resultado es tan bueno como el
  inventario de aulas, el catálogo de materias y los cronogramas que se
  cargan (§3.11.4).
- **Pronóstico de inscriptos.** Los métodos de pronóstico son simples y
  dependen de una serie histórica a veces corta; un error en el
  pronóstico se traslada a la asignación.
- **Falta física de aulas.** El modelo reparte la capacidad que existe;
  si una comisión no entra en ningún aula compatible, lo informa pero no
  lo resuelve.
- **Uso local.** El sistema está pensado para un único usuario a la vez,
  sin gestión de usuarios ni permisos.

### 3.11.4 Criterios de uso y buenas prácticas

El sistema descansa sobre algunos supuestos acerca de cómo se cargan
los datos. Cuando se respetan, las validaciones y el asignador
razonan sobre la cursada real; cuando no, el modelo resuelve con
corrección un problema distinto del que se tiene. Resumimos los
principales en forma de directivas de uso.

1. **Cada comisión es un único esquema semanal que el alumno cursa
   completo.** El sistema entiende que quien está en una comisión
   asiste a todos sus horarios, y que de cada materia el alumno cursa
   una sola comisión. Por eso las materias deben definirse según cómo
   se organiza efectivamente su cursada. Un caso frecuente es el de
   una materia, digamos A6, con una teoría común y el laboratorio
   dividido en tres grupos: si los cuatro horarios se cargan bajo el
   código A6, en una sola comisión, el sistema concluye que cada
   alumno debe asistir a los tres laboratorios. La forma correcta es
   separar la práctica en una materia propia, A6P, con tres
   comisiones de un laboratorio cada una, como muestra la Figura
   @fig:a6. Así cada alumno cursa la teoría y uno solo de los grupos,
   y tanto la verificación de superposiciones como el reparto entre
   teoría y laboratorio (R4) se calculan sobre la carga real.

   ![Carga de una materia con una teoría común y tres grupos de laboratorio](figuras/a6_vs_a6p.png){#fig:a6 width=14cm}

2. **Representación Gráfica.**

   ::: revisar
   **Para completar a mano:** describir el caso de Representación
   Gráfica, que presenta una situación análoga a la anterior, y cómo
   conviene cargarla.
   :::

3. **Las horas de la materia deben coincidir con las del
   cronograma.** Las horas de teoría y de laboratorio declaradas en
   la materia son la referencia contra la que se verifica cada
   comisión. Si el catálogo está desactualizado, el sistema marca
   como error un cronograma correcto, o deja pasar uno incorrecto.

4. **El inventario de aulas es la oferta del problema.** El asignador
   sólo usa las aulas cargadas, con la capacidad, el tipo y la sede
   que figuran en el sistema. Un laboratorio que no se declaró
   compatible con una materia no se le asigna nunca, aunque en la
   práctica sirva.

5. **Cada materia, en el grupo de materias que le corresponde.** El
   grupo determina en qué sedes puede dictarse. Conviene reservar el
   modo duro para las reglas institucionales firmes y usar el modo
   blando cuando la sede es sólo una preferencia: un modo duro
   innecesario reduce las alternativas y puede volver infactible el
   problema. Es el caso típico de las carreras de la Siberia, cuyos
   alumnos cursan comunes en Pellegrini (§3.8.2.5).

6. **Los inscriptos esperados son un pronóstico.** Se estiman a partir
   de la serie histórica, que sólo es útil si las inscripciones de
   años anteriores quedaron vinculadas a la materia correcta (con su
   código actual o mediante un código equivalente registrado).
   Cuando se sabe algo que la serie no refleja (un cambio de plan,
   una cohorte excepcional), conviene reemplazar el valor estimado.

7. **Las excepciones, justificadas y revisadas.** Ignorar un conflicto
   horario es legítimo cuando se sabe que las materias involucradas
   no comparten alumnos, pero cada excepción debería tener un motivo
   y revisarse en cada cuatrimestre.

8. **Fijar aulas a mano, con moderación.** Cada aula fijada le quita
   libertad al asignador; muchas fijaciones, o fijaciones
   incompatibles entre sí, pueden impedir que exista una solución.

9. **Un plan activo por ciclo y los demás como escenarios.** Los
   planes adicionales sirven para comparar alternativas sin tocar el
   plan con el que se trabaja; el que se comunica es siempre el
   activo.

### 3.11.5 Cumplimiento de los objetivos del anteproyecto

La Tabla @tab:objetivos recorre los objetivos específicos del
anteproyecto y señala dónde se verifica su cumplimiento.

<!-- tabla: Cumplimiento de los objetivos específicos del anteproyecto {#tab:objetivos} -->
| Objetivo específico | Dónde se verifica |
| ---------------------------------------------- | ---------------------------------------- |
| Modelizar la problemática, sus variables y restricciones | Definición del problema (3.4) y modelo conceptual (3.5) |
| Definir distintas reglas y restricciones de asignación | Reglas del dominio (3.5.5) y restricciones R1 a R12 (3.8.2.5) |
| Proponer modelos y técnicas de optimización basados en esas reglas | Programa lineal entero, verificación previa y diagnóstico (3.8) |
| Desarrollar el soporte informático para registrar los datos e implementar las técnicas | Modelo de datos (3.6), arquitectura (3.7) y validaciones (3.9) |
| Generar distintos esquemas de asignación según los modelos propuestos y compararlos | Caso ensayado y escenarios (3.10) |

Los cinco objetivos se cumplieron. El objetivo general, optimizar la
asignación de aulas para mejorar el uso de la capacidad instalada, se
verifica en el caso ensayado: todos los horarios quedan con aula, la
sobreocupación se reduce a la que impone la falta física de aulas y la
configuración recomendada deja una holgura de casi mil asientos aun en
la franja más ocupada.
