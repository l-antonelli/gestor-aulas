# Auditoría de planes de estudio (2026-09-11)

**Fuente de verdad**: `data/input/Carreras/BD Study Plans and Subjects.xlsx`

## Resumen por carrera

| Carrera | Coincidentes | Faltantes en DB | Sobrantes en DB | Divergentes |
|---|---|---|---|---|
| `A` — Ingenieria Electronica | 76 | 18 | 1 | 4 |
| `C` — Ingenieria Civil | 47 | 15 | 29 | 0 |
| `E` — Ingenieria Electrica | 45 | 10 | 20 | 0 |
| `G` — Agrimensura | 55 | 20 | 7 | 0 |
| `I` — Ingenieria Industrial | 47 | 14 | 11 | 0 |
| `IA` — Tecnicatura Universitaria en Inteligencia Artificial | 36 | 17 | 4 | 0 |
| `LF` — Licenciatura en Fisica | 41 | 12 | 14 | 0 |
| `LM` — Licenciatura en Matematica | 30 | 14 | 5 | 2 |
| `M` — Ingenieria Mecanica | 49 | 20 | 14 | 2 |
| `PF` — Profesorado en Fisica | 18 | 0 | 3 | 13 |
| `PM` — Profesorado en Matematica | 27 | 1 | 1 | 0 |
| `R` — Licenciatura en Ciencias de la Computacion | 32 | 10 | 25 | 0 |

## `A` — Ingenieria Electronica

### Faltantes en DB (18)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |
| `EL1` | Participación de proyecto de investigación científica | 5°2C (opt) | Electivas |
| `EL2` | Participación en proyecto de extensión universitaria | 5°2C (opt) | Electivas |
| `EL3` | Espacio Curricular de Intercambio I | 5°2C (opt) | Electivas |
| `EL4` | Espacio Curricular de Intercambio II | 5°2C (opt) | Electivas |
| `EL5` | Espacio Curricular de Intercambio III | 5°2C (opt) | Electivas |
| `EL6` | Espacio Curricular de Intercambio IV | 5°2C (opt) | Electivas |
| `EL7` | Visita a obras, Industrias, ferias y exposiciones I | 5°2C (opt) | Electivas |
| `EL8` | Visita a obras, industrias, ferias y exposiciones II | 5°2C (opt) | Electivas |

### Sobrantes en DB (1)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |

### Divergentes (4)

Mismo código, distinta ubicación (año/cuatri/optativa) entre Excel y DB. La DB tiene la ubicación incorrecta.

| Código | Nombre | Excel (verdad) | DB (actual) | Hoja |
|---|---|---|---|---|
| `F14` | Gestión de Calidad y Operaciones | **1°2C** | 1°1C | Electronica |
| `F15` | Higiene, Seg. y Gestión Amb. | **5°1C** | 5°2C | Electronica |
| `F17` | Economía y Costos | **5°1C** | 1°2C | Electronica |
| `F18` | Emprendedorismo y Ev. Proyectos | **5°2C** | 5°1C | Electronica |

## `C` — Ingenieria Civil

### Faltantes en DB (15)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |
| `EL16` | Participación en proyectos de investigación Científica I | 5°2C (opt) | Electivas |
| `EL17` | Participación en proyecto de investigación Científica II | 5°2C (opt) | Electivas |
| `EL18` | Participación en proyecto de extensión Universitaria I | 5°2C (opt) | Electivas |
| `EL19` | Participación en proyecto de extensión universitaria II | 5°2C (opt) | Electivas |
| `FI9` | Prueba de Suficiencia de Inglés | 2°2C | Civil |

### Sobrantes en DB (29)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `ELC1` | Dibujo asistido por computadora | None°None (opt) |
| `ELC10` | Estructuras Sismorresistentes | None°None (opt) |
| `ELC11` | Estructuras metálicas especiales | None°None (opt) |
| `ELC12` | Sistemas de riego y drenaje | None°None (opt) |
| `ELC13` | Planificación y gestión integrada de recursos hídricos | None°None (opt) |
| `ELC14` | Hidráulica Fluvial | None°None (opt) |
| `ELC15` | Tratamiento de aguas residuales | None°None (opt) |
| `ELC16` | Obras Ferroviarias | None°None (opt) |
| `ELC17` | Puertos y vías navegables | None°None (opt) |
| `ELC18` | Movilidad Urbana | None°None (opt) |
| `ELC19` | Vialidad Especial | None°None (opt) |
| `ELC2` | Metodos de los elementos finitos. Modelizaciones | None°None (opt) |
| `ELC20` | Construcción y mantenimiento de infraestructuras de transp. | None°None (opt) |
| `ELC21` | Logistica urbana y regional | None°None (opt) |
| `ELC22` | Hidrología e hidráulica en territorios urbanizados | None°None (opt) |
| `ELC23` | Sustentabilidad en ing. civil | None°None (opt) |
| `ELC24` | Construcciones Bioclimáticas | None°None (opt) |
| `ELC26` | Gestión Integral de Residuos Sólidos | None°None (opt) |
| `ELC27` | Hidrología Digital | None°None (opt) |
| `ELC28` | Desarrollo Emprendedor y Proyección de Emprendimientos | None°None (opt) |
| `ELC3` | Dirección y gestión de empresas de la construcción | None°None (opt) |
| `ELC4` | Gestión pública | None°None (opt) |
| `ELC5` | Gestión ambiental | None°None (opt) |
| `ELC6` | Estudios geotécnicos para obras civiles | None°None (opt) |
| `ELC7` | Estructuras de hormigón especiales | None°None (opt) |
| `ELC8` | Hormigón pretensado | None°None (opt) |
| `ELC9` | Puentes | None°None (opt) |
| `FI0` | Inglés | 2°2C |

## `E` — Ingenieria Electrica

### Faltantes en DB (10)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |

### Sobrantes en DB (20)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `EL25` | Sensores y transductores | None°None (opt) |
| `ELE02` | Centrales Nucleares II | None°None (opt) |
| `ELE11` | Protecciones Eléctricas | None°None (opt) |
| `ELE12` | Tracción Eléctrica Aplicada | None°None (opt) |
| `ELE13` | Centrales Nucleares I | None°None (opt) |
| `ELE14` | Operación y Control de Sep con Fuentes Renovables | None°None (opt) |
| `ELE15` | Dinámica y Control de Sistemas Mecatrónicos | None°None (opt) |
| `ELE16` | Electrónica de Potencia | None°None (opt) |
| `ELE17` | Análisis de falla en instalaciones industriales... | None°None (opt) |
| `ELE18` | Sistemas de Potencia II | None°None (opt) |
| `ELE19` | Electrónica II | None°None (opt) |
| `ELE20` | Informática II | None°None (opt) |
| `ELE21` | Mecánica | None°None (opt) |
| `ELE22` | Desarrollo Emprendedor y Proyección... | None°None (opt) |
| `ELE23` | Nuevos materiales y procesos para nuevas energías... | None°None (opt) |
| `ELE24` | Sensores Instrumentos y Actuadores Industriales | None°None (opt) |
| `ELE25` | Electroreología | None°None (opt) |
| `FI1` | Inglés I | 2°1C |
| `FI2` | Inglés II | 2°2C |

## `G` — Agrimensura

### Faltantes en DB (20)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |
| `EL1` | Participación de Proyecto de Inv. Científica | 5°2C (opt) | Electivas |
| `EL10` | Asistencia a Congresos II | 5°2C (opt) | Electivas |
| `EL2` | Participación en Proyecto de Extensión Univ. | 5°2C (opt) | Electivas |
| `EL3` | Espacio Curricular de Intercambio I | 5°2C (opt) | Electivas |
| `EL4` | Espacio Curricular de Intercambio II | 5°2C (opt) | Electivas |
| `EL5` | Espacio Curricular de Intercambio | 5°2C (opt) | Electivas |
| `EL6` | Espacio Curricular de Intercambio IV | 5°2C (opt) | Electivas |
| `EL7` | Visita a Obras, Ind., Ferias y Exposiciones | 5°2C (opt) | Electivas |
| `EL8` | Visita a Obras, Ind., Ferias y Exposiciones | 5°2C (opt) | Electivas |
| `EL9` | Asistencia A Congresos I | 5°2C (opt) | Electivas |

### Sobrantes en DB (7)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `ELG11` | Ciencia, Tecnología y Sociedad | None°None (opt) |
| `ELG12` | Lectura y Escritura de Textos Académicos | None°None (opt) |
| `ELG13` | Agrimensura, Sociedad y Ambiente | None°None (opt) |
| `ELG15` | Imágenes Radar y sus Apl. al Ord. Territorial... | None°None (opt) |
| `ELG16` | Seminario: Aplicaciones VANT a la Agrimensura | None°None (opt) |
| `ELG17` | Seminario Administración y Gestión... | None°None (opt) |

## `I` — Ingenieria Industrial

### Faltantes en DB (14)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EL16` | Participación en proyectos de investigación Científica I | 5°2C (opt) | Electivas |
| `EL17` | Participación en proyecto de investigación Científica II | 5°1C (opt) | Electivas |
| `EL18` | Liderazgo | 5°2C (opt) | Electivas |
| `EL19` | Métodos Heurísticos | 5°2C (opt) | Electivas |
| `FI9` | Prueba de Suficiencia de Inglés | 2°2C | Industrial |

### Sobrantes en DB (11)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `EL50` | Aprendizaje Automático | None°None (opt) |
| `EL52` | Minería de Datos | None°None (opt) |
| `EL53` | Datos y Analítica Visual | None°None (opt) |
| `ELI1` | Ergonomía | None°None (opt) |
| `ELI2` | Desarrollo Emprendedor y Proyección de Emprendimientos | None°None (opt) |
| `ELI3` | Estudios de impacto ambiental en la evaluación de proyectos | None°None (opt) |
| `ELI4` | Introducción a la ingeniería del envasado | None°None (opt) |
| `ELI5` | Introducción a la Ingeniería de Alimentos | None°None (opt) |
| `ELI6` | Introducción a la Gestión de la Energía orientada a la Industria | None°None (opt) |
| `FI0` | Inglés | 2°2C |

## `IA` — Tecnicatura Universitaria en Inteligencia Artificial

### Faltantes en DB (17)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |
| `IA 5.4` | Espacio Electivo | 3°1C | TUIA |
| `IAE10` | Asistencia a Conferencias, Ferias, Congresos I | 3°2C (opt) | Electivas |
| `IAE12` | Asistencia a Conferencias, Ferias, Congresos III | 3°2C (opt) | Electivas |
| `IAE13` | Asistencia a Conferencias, Ferias, Congresos IV | 3°2C (opt) | Electivas |
| `IAE4` | Espacio Curricular de Intercambio II | 3°2C (opt) | Electivas |
| `IAE5` | Espacio Curricular de Intercambio III | 3°2C (opt) | Electivas |
| `IAE6` | Espacio Curricular de Intercambio IV | 3°1C (opt) | Electivas |

### Sobrantes en DB (4)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `IA0` | Introduccion a la Matematica (TUIA) | 1°1C |
| `IAE16` | Emprendedorismo | 3°2C (opt) |
| `IAE21` | Responsabilidad Social y Factor Humano | 3°2C (opt) |

## `LF` — Licenciatura en Fisica

### Faltantes en DB (12)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `ECE01` | Espacio curricular de intercambio I | 5°2C (opt) | Electivas |
| `ECE02` | Espacio curricular de intercambio II | 5°2C (opt) | Electivas |
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |

### Sobrantes en DB (14)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `CE0` | Introducción a la Matemática | 1°1C |
| `ECE18` | Caos y Análisis no Lineal de Series Temporales | None°None (opt) |
| `ECE19` | Física Computacional | None°None (opt) |
| `ECE20` | Aplicaciones de la Física Nuclear | None°None (opt) |
| `ECE21` | Introducción a la Física Nuclear | None°None (opt) |
| `ECE22` | Introducción a la Física de Materiales Ferroeléctricos | None°None (opt) |
| `ECE23` | Naturaleza de la Ciencia | None°None (opt) |
| `ECE24` | Teoría de Campos I | None°None (opt) |
| `ECE25` | Relatividad General y Objetos Compactos | None°None (opt) |
| `ECE26` | Métodos Matemáticos de la Física II | None°None (opt) |
| `ECE27` | Relatividad General y Objetos Compactos | None°None (opt) |
| `ECE28` | Electromagnetismo | None°None (opt) |
| `ECE29` | Aplicaciones de la Física Nuclear | None°None (opt) |
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |

## `LM` — Licenciatura en Matematica

### Faltantes en DB (14)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `CE7` | Programación | 2°1C | Lic. en matematica |
| `ECE11` | Espacio Curricular de Intercambio I | 5°2C (opt) | Electivas |
| `ECE12` | Espacio Curricular de Intercambio II | 5°2C (opt) | Electivas |
| `ECE13` | Espacio Curricular de Intercambio III | 5°2C (opt) | Electivas |
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |

### Sobrantes en DB (5)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `CE0` | Introducción a la Matemática | 1°1C |
| `ECE18` | Caos y Análisis no Lineal de Series Temporales | None°None (opt) |
| `ECE30` | Física de superficies | 5°2C (opt) |
| `ECE31` | Mecánica Cuántica Superior | 5°2C (opt) |
| `ECE32` | Ecuaciones Diferenciales I | None°None (opt) |

### Divergentes (2)

Mismo código, distinta ubicación (año/cuatri/optativa) entre Excel y DB. La DB tiene la ubicación incorrecta.

| Código | Nombre | Excel (verdad) | DB (actual) | Hoja |
|---|---|---|---|---|
| `ECE33` | Introducción a la Teoría de Juegos | **5°1C (opt)** | 5°None (opt) | Electivas |
| `EF11` | Taller de Modelos Matemáticos | **5°2C (opt)** | 5°None (opt) | Electivas |

## `M` — Ingenieria Mecanica

### Faltantes en DB (20)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |
| `EL1` | Participación de proyecto de investigación científica | 5°2C (opt) | Electivas |
| `EL10` | Asistencia a congresos II | 5°2C (opt) | Electivas |
| `EL2` | Participación en proyecto de extensión universitaria | 5°2C (opt) | Electivas |
| `EL3` | Espacio curricular de intercambio I | 5°2C (opt) | Electivas |
| `EL4` | Espacio curricular de intercambio II | 5°2C (opt) | Electivas |
| `EL5` | Espacio curricular de intercambio III | 5°2C (opt) | Electivas |
| `EL6` | Espacio curricular de intercambio IV | 5°2C (opt) | Electivas |
| `EL7` | Visita a obras, industrias, ferias y exposiciones I | 5°2C (opt) | Electivas |
| `EL8` | Visita a obras, industrias, ferias y exposiciones II | 5°2C (opt) | Electivas |
| `EL9` | Asistencia a congresos I | 5°2C (opt) | Electivas |

### Sobrantes en DB (14)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `ELM08` | Dinámica de Fluidos Computacional | None°None (opt) |
| `ELM09` | Gestión del Mantenimiento Industrial | None°None (opt) |
| `ELM10` | Hidráulica Móvil | None°None (opt) |
| `ELM13` | Energía y sostenibilidad | None°None (opt) |
| `ELM14` | Ergonomía | None°None (opt) |
| `ELM15` | Introducción a la ingeniería del envasado | None°None (opt) |
| `ELM16` | Diseño de motores de combustión interna | None°None (opt) |
| `ELM17` | Dinámica de automóviles | None°None (opt) |
| `ELM19` | Dinámica y control de sistemas mecatrónicos | None°None (opt) |
| `ELM20` | Diseño de motores de combustión interna (Repetida) | None°None (opt) |
| `ELM22` | Dinámica de automóviles (Repetida) | None°None (opt) |
| `ELM23` | Técnicas de Inteligencia Artificial | None°None (opt) |
| `ELM28` | Centrales Nucleares | None°None (opt) |

### Divergentes (2)

Mismo código, distinta ubicación (año/cuatri/optativa) entre Excel y DB. La DB tiene la ubicación incorrecta.

| Código | Nombre | Excel (verdad) | DB (actual) | Hoja |
|---|---|---|---|---|
| `ELM11` | Desarrollo Emprendedor y Proyección de Emprendimientos | **5°1C (opt)** | 5°None (opt) | Electivas |
| `ELM12` | Estudios de impacto ambiental en la evaluación de proyectos | **5°1C (opt)** | 5°None (opt) | Electivas |

## `PF` — Profesorado en Fisica

### Sobrantes en DB (3)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `CE0` | Introducción a la Matemática | 1°1C |
| `CE2` | Análisis Matemático I | 1°1C |
| `EPF01` | Taller de didáctica de la física computacional | None°None (opt) |

### Divergentes (13)

Mismo código, distinta ubicación (año/cuatri/optativa) entre Excel y DB. La DB tiene la ubicación incorrecta.

| Código | Nombre | Excel (verdad) | DB (actual) | Hoja |
|---|---|---|---|---|
| `PF3.3` | Física IV | **3°1C** | 3°None | Prof. fisica |
| `PF3.4` | Mecánica Clásica y Relatividad | **3°1C** | 3°None | Prof. fisica |
| `PF3.5` | Taller de Informática | **3°1C** | 3°None | Prof. fisica |
| `PF3.6` | Examen de suficiencia de inglés | **3°1C** | 3°None | Prof. fisica |
| `PF3.7` | Química | **3°2C** | 3°None | Prof. fisica |
| `PF3.8` | Didáctica de la Física | **3°2C** | 3°None | Prof. fisica |
| `PF3.9` | Taller de Práctica de la Enseñanza III | **3°2C** | 3°None | Prof. fisica |
| `PF4.2` | Naturaleza de la Física | **4°1C** | 4°None | Prof. fisica |
| `PF4.3` | Taller de Física Ambiental | **4°1C** | 4°None | Prof. fisica |
| `PF4.4` | Física Experimental | **4°1C** | 4°None | Prof. fisica |
| `PF4.5` | Taller de Astrofísica | **4°2C** | 4°None | Prof. fisica |
| `PF4.6` | Fís. Cuántica y Estruc. de la Materia | **4°2C** | 4°None | Prof. fisica |
| `PF4.7` | Electiva | **4°2C** | 4°None | Prof. fisica |

## `PM` — Profesorado en Matematica

### Faltantes en DB (1)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `CE2` | Análisis Matemático I | 1°1C | Prof. matematica |

### Sobrantes en DB (1)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `CE0` | Introducción a la Matemática | 1°1C |

## `R` — Licenciatura en Ciencias de la Computacion

### Faltantes en DB (10)

Materias que aparecen en el Excel pero no están en el plan activo.

| Código | Nombre | Ubicación (Excel) | Hoja |
|---|---|---|---|
| `EF1` | Espacio Curricular Flexible I | 5°1C (opt) | Electivas |
| `EF10` | Espacio Curricular Flexible X | 5°1C (opt) | Electivas |
| `EF2` | Espacio Curricular Flexible II | 5°1C (opt) | Electivas |
| `EF3` | Espacio Curricular Flexible III | 5°1C (opt) | Electivas |
| `EF6` | Espacio Curricular Flexible VI | 5°1C (opt) | Electivas |
| `EF7` | Espacio Curricular Flexible VII | 5°1C (opt) | Electivas |
| `EF8` | Espacio Curricular Flexible VIII | 5°1C (opt) | Electivas |
| `EF9` | Espacio Curricular Flexible IX | 5°1C (opt) | Electivas |
| `EFIV` | Espacio Curricular Flexible IV | 5°1C (opt) | Electivas |
| `EFV` | Espacio Curricular Flexible V | 5°1C (opt) | Electivas |

### Sobrantes en DB (25)

Materias que están en el plan activo pero no aparecen en el Excel — candidatas a borrar.

| Código | Nombre | Ubicación (DB) |
|---|---|---|
| `CE0` | Introducción a la Matemática | 1°1C |
| `EF11` | Taller de Modelos Matemáticos | 5°None (opt) |
| `XT001` | Optativa: Bases de Datos Avanzadas | None°None (opt) |
| `XT002` | Optativa: Introducción a la Programación Genérica | None°None (opt) |
| `XT003` | Construcción Formal de Programas en Teoría de Tipos | None°None (opt) |
| `XT004` | Optativa: Sistemas de Tipos | None°None (opt) |
| `XT005` | Optativa: Investigación Operativa | None°None (opt) |
| `XT006` | Optativa: Introducción al Aprendizaje Automatizado | None°None (opt) |
| `XT007` | Optativa: Procesamiento Digital de Imágenes | None°None (opt) |
| `XT008` | Optativa: Modelado y Simulación de Sistemas Dinámicos | None°None (opt) |
| `XT009` | Optativa: Modelado y Verificación de Sistemas | None°None (opt) |
| `XT010` | Optativa: Tópicos Avanzados de Optimización Combinatoria | None°None (opt) |
| `XT011` | Optativa: Redes de Datos | None°None (opt) |
| `XT012` | Optativa: Tópicos de Minería de Datos | None°None (opt) |
| `XT019` | Introducción a la Topología | None°None (opt) |
| `XT13` | Optativa: Programación con Categorías | None°None (opt) |
| `XT14` | Int. a la Comp. Cuántica y Fundamentos de Leng. de Prog. | None°None (opt) |
| `XT15` | Optativa: Emprendedorismo | None°None (opt) |
| `XT16` | Optativa: Introducción a las Redes Neuronales Profundas | None°None (opt) |
| `XT17` | Tópicos Avanzados en Teoría de Grafos | None°None (opt) |
| `XT18` | Un Método Científico para el Ingeniero de Software | None°None (opt) |
| `XT20` | Computación Paralela | None°None (opt) |
| `XT21` | Análisis y Verificación de Programas | None°None (opt) |
| `XT22` | Seguridad | None°None (opt) |
| `XT23` | Robótica Móvil | None°None (opt) |

