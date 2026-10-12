# 6. Declaración de uso de IA

<!-- tabla: Declaración de uso de IA {#tab:uso-ia} -->
| Dimensión | Descripción |
| :---------------------------- | :------------------------------------------------------------ |
| Herramienta utilizada | Claude Code (Harness) usando modelos Sonnet |
| Propósito de uso | Desarrollo de elementos de interfaz, mantenimiento de documentación, implementación de las restricciones 7 a 12, desarrollo de los tests de unidad |
| Prompts o instrucciones proporcionadas | "Propone pruebas funcionales a partir de los requerimientos y el diseño detallado antes de escribir código fuente, implementando TDD", "Actualiza el documento X sobre funcionalidad Y detallando el cambio en el esquema Z", "Definir un expander ajustado al ancho del contenedor que renderiza el elemento cronograma definido en {módulo}" |
| Uso del contenido generado | Codigo fuente y documentación del repositorio |
| Revisión y edición | Todo el contenido generado con IA fue definido y detallado comprensivamente de antemano. Se utilizó como herramienta para acelerar el desarrollo o extensión de ciertas funcionalidades previamente diseñadas y analizadas. |
| Limitaciones y consideraciones éticas | |

Se siguieron buenas prácticas de desarrollo asistido por inteligencia
artificial, asegurando:

- La revisión y confirmación explícita de cada cambio en todo momento.
- Definición proactiva y detallada de todos los aspectos de diseño e
  implementación.
- Se limitó al desarrollo y la escritura de bloques repetitivos o
  mecánicos de código, o bien la reutilización o extensión de patrones
  de código previamente definidos.
- Todos los aspectos de diseño del modelo de datos, arquitectura,
  patrones de diseño utilizados, definición de requerimientos
  funcionales, consideraciones del stack elegido y planteo matemático
  del programa lineal fue realizado de antemano, previa intervención
  de la herramienta declarada.
- No se expuso los datos de la base de datos al modelo en ningún
  momento y se corrieron las sentencias de SQL en una terminales y
  procesos aparte.
- Se mantuvo el stack elegido, librerías, técnicas y patrones
  utilizados dentro del dominio de las destrezas con las que ya
  contaba el equipo, a fin de asegurar la posibilidad de una correcta
  revisión, verificación y corrección.

# 7. Anexos

Los anexos se entregan como documentos separados (en Drive, en la
carpeta *Informe / Anexos*). Se rotulan con letras, en el orden en que
se los menciona en el texto.

- **Anexo A. Referencia técnica de la base de datos.**
    - Autores: Antonelli L. y Galliano P.
    - Fecha: 2026.
    - Título: Anexo A - Documentación Técnica.
    - Fuente: Google Drive
      (https://docs.google.com/document/d/1qr_M1OzshpZhwC8t4X6t39mmUxy361aooYKe8k9TVaU/edit?usp=drive_link)
- **Anexo B. Repositorio Github con Código Fuente.**

  El código fuente completo desarrollado para este proyecto se
  encuentra alojado y disponible en el repositorio público de GitHub
  en el siguiente enlace:
  https://github.com/l-antonelli/gestor-aulas
- **Anexo C. Manuales de usuario.**
    - Autores: Antonelli L. y Galliano P.
    - Fecha: 2026.
    - Título: Anexo C - Manuales.
    - Fuente: Google Drive
      (https://drive.google.com/drive/folders/1s2bFm00xdUkL2tEWVLMo17t14ThsZzBc?usp=sharing)
- **Anexo D. Cronogramas del caso ensayado.**
    - Autores: Antonelli L. y Galliano P.
    - Fecha: 2026.
    - Título: Anexo D - Cronogramas del caso ensayado.
    - Fuente: Google Drive
      (https://drive.google.com/drive/folders/1chE2Si3TqEiAoKsVnKezCm6R1PrwGptv?usp=drive_link)
- **Anexo E. Repositorio de videos instructivos:**
    - Autores: Antonelli L. y Galliano P.
    - Fecha: 2026.
    - Título: Anexo E - Vídeos instructivos.
    - Fuente: Google Drive
      (https://drive.google.com/drive/folders/1Y3e7oaV2eAdcF7O2zxwz43Cj4zkSuydw?usp=drive_link)
