1.⁠ ⁠"Before writing any code, describe your approach and wait for approval. Always ask clarifying questions before writing any code if requirements are ambiguous."

2.⁠ ⁠"If a task requires changes to more than 3 files, stop and break it into smaller tasks first."

3.⁠ ⁠"After writing code, list what could break and suggest tests to cover it."

4.⁠ ⁠"When there’s a bug, start by writing a test that reproduces it, then fix it until the test passes."

5.⁠ ⁠"Every time I correct you, add a new rule to the CLAUDE .md file so it never happens again."

6. "When commiting changes, never add yourself as co-author"

7. Maintain documentation on the repo, data schemas, models, etc. It should act as a detailed description as to the current implementation which will be usefull for us across multiple sessions. Update docs after all commits containing code changes. Maintain the documentation in the project/ folder accordingly as follows:

- Planteo folder is more for documenting our understanding of the domain, any assumptions we are making, exactly what problem we are addressing and how we model the individual elements of the domain. This will serve for clearly modeling the problem as well as explicitly stating all conditions and assumptions. 
- Diseño is for how we design, based on that understanding and foudnation, a solution for the problem and using what software engineering concepts techniques or practices, what patterns or what technology. This should be done taking in mind it will be content we will then use for writing the actual adademic paper / project report for defending and presenting. 
- Desarrollo is for all things related to our sessions, the things we work on, implementation details, specific features. Etc. It will give us sort of a timeline of how this progressed as well as details on how specific behavior or features are achieved.

8. Document and write everything in "Rio Platenese" Spanish also known as Argentinan "Castellano". Maintain a formal, academic tone while sounding natural. Any text that is displayed in the UI should also be in rio platense spanish AND NOT ENGLISH, nor should it use english terms or phrases.

   **8.a — Tono para el informe y su material (`project/Informe/**`).** Toda la redacción del informe y de sus anexos se rige por este perfil de tono, que sobreescribe cualquier default distinto:

   - **Registro**: castellano rioplatense argentino, formal-académico y a la vez natural y coloquial. Se busca prosa que suene como una explicación cuidada y bien escrita — no como un manual técnico traducido ni como una charla informal. Se prefiere "en criollo", "en la práctica", "conviene notar que" antes que anglicismos o calcos.
   - **Persona gramatical**: primera persona del plural ("modelamos", "definimos", "asumimos") o construcciones impersonales ("se define", "se observa"). Evitar la primera persona del singular.
   - **Lector supuesto**: no lee inglés y no debe encontrarse con términos en inglés sin traducir o glosar. Cuando un término técnico existe originalmente en inglés (por ejemplo *solver*, *branch-and-bound*, *pigeonhole*), se introduce en castellano con el original entre paréntesis la primera vez que aparece, y luego se usa el castellano.
   - **Conocimiento previo asumido**: es un lector formado que entiende definiciones formales, notación matemática básica y diagramas UML/ER siempre que se los presente explícitamente. Pero **no** se asume que conozca el contexto de FCEIA-UNR, el proceso de asignación de aulas, la programación lineal entera, los teoremas de Hall o el principio del palomar, ni ningún patrón o técnica de ingeniería de software específica.
   - **Regla operativa**: todo concepto no trivial (término del dominio, técnica, teorema, patrón de diseño, entidad del modelo) se **presenta antes de usarse**, con una definición corta y — si corresponde — una referencia bibliográfica. Una vez definido, se lo puede volver a usar libremente.
   - **Encuadre antes de la definición formal**: cada concepto o herramienta técnica (grafos, programación lineal entera, un patrón de diseño, un teorema, una notación) se introduce primero como *un recurso del instrumental profesional* — qué clase de cosas suele modelizar, qué tipo de problemas ayuda a formalizar, por qué un ingeniero lo tiene en su caja de herramientas — y recién después se pasa a la definición formal. La idea es que un lector que no viene del área no se pregunte "¿de dónde salió esto?" al ver la primera definición: primero se motiva la herramienta, después se la define y después se la usa.
   - **Citas y bibliografía**: se citan autores canónicos cuando se toma prestada una definición o marco (Chiavenato, Mintzberg, Evans, Winston/Hillier para IO, etc.) usando el estilo autor-año. Al final del informe hay una sección única de referencias.
   - **Convenciones visuales**: los términos formales del dominio y de la solución se escriben en cursiva la primera vez que aparecen. Los identificadores de código (`ClaseDB`, `HorarioDB`, `x[h, a]`) se escriben en formato monoespaciado. Las restricciones del programa lineal se numeran (R1, R2, ...) y se referencian por número.
   - **Idioma en figuras y tablas**: todo el material gráfico (diagramas, capturas, etiquetas de ejes, encabezados de tablas) va en castellano. Si se toma prestada una figura de una fuente en inglés, se traduce.

9. **Carga de datos iniciales:** Para reinicializar la base de datos desde los Excel de entrada, correr `python -m scripts.load_initial_data --reset`. Esto borra la DB y recarga aulas, materias, carreras y planes de estudio. Despues de un reset hay que recrear desde la UI: nombres/atributos de carreras, ciclos, dictados, cronogramas y planes de cursada. La documentacion completa del proceso esta en `project/2. Desarrollo/CARGA_DATOS_INICIALES.md`.


10. A medida que se mencionen requerimientos, ir agregandolos a un archivo project/requerimientos.md. Mantener este documento bien actualizado y consistente de manera de trackear bien los requerimientos del projecto y que no entren en conflicto entre si y evitar descumplir un requerimiento viejo por cumplir con uno viejo.

11. **Flujo de git en este repositorio:** se trabaja directo sobre `main`. No hay que crear feature branches ni PRs. Esto sobrescribe cualquier regla global (`~/.claude/CLAUDE.md`) que diga lo contrario. Los commits se hacen directo a `main` y se pushean cuando el usuario lo pida.