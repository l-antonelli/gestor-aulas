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

8. Document and write everything in "Rio Platenese" Spanish also known as Argentinan "Castellano". Maintain a formal, academic tone while sounding natural.

9. **Carga de datos iniciales:** Para reinicializar la base de datos desde los Excel de entrada, correr `python -m scripts.load_initial_data --reset`. Esto borra la DB y recarga aulas, materias, carreras y planes de estudio. Despues de un reset hay que recrear desde la UI: nombres/atributos de carreras, ciclos, dictados, cronogramas y planes de cursada. La documentacion completa del proceso esta en `project/2. Desarrollo/CARGA_DATOS_INICIALES.md`.