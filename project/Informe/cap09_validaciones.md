# Capítulo 9. Validaciones y garantías de consistencia

El capítulo anterior mostró cómo el asignador resuelve la
asignación de aulas como un programa lineal entero. Esa
formulación supone que los datos que la alimentan son
consistentes: que cada horario pertenece a una comisión bien
definida, que cada materia declara sus horas, que el cronograma
cubre todos los dictados esperados del ciclo y que los pares de
materias en conflicto son realmente incompatibles. Un asignador
correcto sobre datos inconsistentes produce resultados
inconsistentes. Por eso el sistema rodea al asignador de un
conjunto de validaciones cuyo propósito es darle al usuario
garantías concretas sobre el estado de lo que está planificando.
Este capítulo explica qué se verifica, cuándo y por qué importa.

## 9.1 Por qué las validaciones son parte del diseño

Las validaciones no son un agregado defensivo que se suma cuando
algo falla, sino una parte de la solución. Tres motivos sostienen
esa decisión:

- **Los datos del dominio son numerosos y cambian.** Un ciclo
  lectivo tiene cientos de horarios repartidos entre decenas de
  comisiones, dictados anuales que conviven con cuatrimestrales y
  aulas que cambian. Si nadie las busca, las inconsistencias
  aparecen.
- **Los errores más caros son los silenciosos.** Si a un
  cronograma le falta una materia y eso se descubre recién cuando
  el asignador responde que el problema no tiene solución, el
  usuario pierde tiempo buscando la causa en el lugar
  equivocado. Detectar el problema en el momento y el lugar
  correctos, con un mensaje explícito, es mucho más barato.
- **La confianza se construye con transparencia.** El usuario no
  necesita conocer el modelo matemático: le alcanza con leer las
  validaciones para saber qué está bien y qué hay que corregir.

## 9.2 Capas de validación

Las verificaciones se escalonan de lo más elemental a lo más
global, y cada nivel cubre lo que el anterior no alcanza. En la
base, las *restricciones* de la base de datos y las reglas de
negocio que se aplican al guardar cada cambio impiden registrar
datos imposibles: un aula sin sede, dos aulas con el mismo
código, una comisión que pertenezca a la vez a un cronograma y a
un plan, o un dictado cuyos coeficientes de asignación no sumen
uno. Mientras el usuario edita, la interfaz le avisa en el
momento si, por ejemplo, las horas de teoría y de laboratorio de
una materia no cierran con sus horas semanales o si el aula que
elige a mano ya está ocupada en esa franja.

Por encima de esos controles puntuales, el usuario puede pedir
la *validación integral* de un cronograma o de un plan de
cursada completo. Esta verificación revisa la cobertura (que
estén todas las materias esperadas y ninguna de más), la
partición entre teoría y laboratorio de cada comisión, los
conflictos horarios dentro de cada grupo curricular y, en el
plan, la existencia de un camino de cursada viable entre sedes
(R11-camino). Como parte de ella, las excepciones que el usuario
había marcado como ignoradas y que ya no aplican se eliminan
solas, y se le informa de la limpieza. Finalmente, antes de
invocar al resolutor, el asignador ejecuta la *verificación
previa* descripta en §8.4, que detecta sin gastar tiempo de cálculo
las combinaciones de datos que hacen imposible el problema: un
horario sin aula compatible, una franja con más clases que aulas
según el principio del palomar, la condición de Hall, una fijación
incompatible o un salto entre sedes inviable. Las reglas que se
aplican al guardar se detallan en el Anexo A (sección 8, reglas de
integridad e invariantes).

## 9.3 Severidades y su significado

Cada hallazgo de una validación se clasifica en una de tres
severidades, y esa distinción ordena el trabajo del usuario:

- **Bloqueante**: impide avanzar al paso siguiente. Por ejemplo,
  un plan con conflictos horarios no ignorados dentro de un grupo
  curricular no puede activarse, y un cronograma con una comisión
  cuya partición entre teoría y laboratorio es imposible no puede
  generar un plan.
- **Advertencia**: señala una situación anómala que conviene
  revisar pero que no impide seguir. Por ejemplo, que haya
  materias en el grupo "sin clasificar" (§6.4.4): el asignador
  puede correr igual, pero la clasificación debería completarse.
- **Informativa**: comunica algo que ocurrió sin exigir acción,
  como la eliminación automática de una excepción que dejó de
  aplicar.

La interfaz distingue las severidades por color (rojo, amarillo y
azul) y las lista en ese orden. Los mensajes son específicos y
accionables: no dicen "hay un problema", sino, por ejemplo, "la
comisión C de Análisis Matemático I tiene 3 horas de horarios
teóricos pero la materia declara 4", con un enlace directo a la
entidad afectada. El usuario resuelve primero lo bloqueante;
las advertencias pueden esperar y lo informativo sólo se lee.

## 9.4 Vigencia de los resultados

Cada validación y cada corrida del asignador quedan registradas
junto con la configuración que se usó (el detalle está en el
Anexo A). Para el usuario, la garantía que importa es otra: el
sistema advierte cuando un resultado dejó de describir los datos.
Si después de validar se editaron comisiones, horarios o dictados,
la interfaz indica que el resultado está desactualizado y ofrece
volver a ejecutarlo.

## 9.5 Un ejemplo integrado

Supongamos que el usuario prepara el plan de cursada del segundo
cuatrimestre, con el cronograma cargado y el plan recién
generado.

1. **Edita una comisión.** Al cambiarle el nombre, la interfaz
   verifica en el momento que no se repita dentro de la materia.
2. **Pide la validación integral del plan.** El sistema encuentra
   un hallazgo bloqueante (la partición entre teoría y
   laboratorio de una comisión no cierra), una advertencia (dos
   materias del grupo "sin clasificar" tienen comisiones en el
   plan) y uno informativo (se eliminó una excepción que ya no
   aplicaba). El usuario corrige las horas que causaban el
   bloqueo y deja la advertencia para más tarde.
3. **Ejecuta el asignador.** La verificación previa detecta que,
   para tercer año de Ingeniería Electrónica, no existe una
   combinación de comisiones viable porque dos materias
   contiguas se dictan en sedes distintas sin margen suficiente
   (R11-camino). El usuario amplía el margen entre sedes o mueve
   una comisión.
4. **Vuelve a ejecutar el asignador.** El resolutor encuentra la
   solución óptima, que se aplica al plan y queda guardada junto
   con su configuración.
5. **Días después vuelve al plan.** La interfaz le avisa que la
   última validación está desactualizada porque, entretanto, se
   editaron horarios. La repite y confirma que todo está en
   orden.

Cada problema apareció en el paso en que podía resolverse, con un
mensaje que indicaba qué corregir.

## 9.6 Recapitulación

1. **Las validaciones forman parte de la solución.** Convierten
   al asignador de una caja negra en un asistente confiable.
2. **Se escalonan en capas complementarias**: controles al
   guardar y al editar, validación integral del cronograma y del
   plan, y verificación previa del programa lineal.
3. **Tres severidades ordenan la comunicación**: bloqueante,
   advertencia e informativa, con mensajes específicos y
   accionables.
4. **Ningún resultado se usa desactualizado**: el sistema avisa
   cuando los datos cambiaron después de validar.

El capítulo siguiente recorre la herramienta en acción: cómo se
opera el sistema desde la interfaz, con capturas comentadas y un
ejemplo integral sobre datos reales de la FCEIA.
