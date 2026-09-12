# Gestor de Aulas

Sistema de asignación de aulas para la Facultad de Ciencias Exactas,
Ingeniería y Agrimensura (FCEIA) de la Universidad Nacional de
Rosario. Asiste al proceso de decidir qué aula del catálogo va a
recibir cada horario semanal del cuatrimestre, respetando
capacidad, tipo de aula, sedes admisibles, continuidad intersede y
la partición teoría/laboratorio declarada por cada materia.

El corazón del sistema es un **programa lineal entero** resuelto con
CBC (vía PuLP) que decide simultáneamente el aula de cada horario y,
cuando el cronograma no lo predetermina, el tipo de la clase. La
aplicación es una interfaz web en Streamlit con toda la operatoria
para gestionar el ciclo lectivo completo: carreras, materias,
grupos de materias, planes de estudio versionados, cronogramas,
comisiones, forecast de inscriptos y auditoría.

## Instalación

### Requisitos previos

- **Python 3.11 o 3.12** (no 3.13 todavía — algunas dependencias no
  están compatibles). Verificable con `python --version`.
- **git** para clonar o descargar el repositorio.
- Alrededor de **300 MB libres** para el entorno virtual y la base
  de datos.

### Bajar el código

Dos opciones equivalentes:

**Opción 1 — Descargar el ZIP de una release** (recomendado para
usuarios no técnicos):

1. Ir a la página de releases del proyecto: <https://github.com/l-antonelli/gestor-aulas/releases>.
2. Descargar el `.zip` (o `.tar.gz`) de la última release publicada.
3. Descomprimir en la carpeta donde se quiera trabajar.

**Opción 2 — Clonar con git**:

```bash
git clone https://github.com/l-antonelli/gestor-aulas.git
cd gestor-aulas
```

Para actualizar a la última versión después:

```bash
git fetch --tags
git checkout v0.9.0   # o la versión más reciente
```

### Instalar dependencias

Desde la carpeta del proyecto:

```bash
# 1) Crear un entorno virtual (una sola vez)
python3.11 -m venv .venv
# o con la versión que tengas:  python -m venv .venv

# 2) Activar el entorno
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate.bat         # Windows

# 3) Instalar las dependencias
pip install -r requirements.txt
```

Alternativa con **uv** (más rápido, si lo tenés instalado):

```bash
uv sync
source .venv/bin/activate
```

### Verificar la base de datos

El repositorio incluye una base pre-cargada en `data/database.db`
con el catálogo actual (carreras, materias, planes de estudio,
aulas). No hace falta cargar nada la primera vez.

Si querés **reinicializar la base desde los archivos Excel de
entrada** (`data/input/`):

```bash
python -m scripts.load_initial_data --reset
```

Este comando borra la base y la recarga con carreras, materias,
planes de estudio y aulas. Después del reset hay que **recrear
desde la UI**: nombres/atributos de carreras, ciclos, dictados,
cronogramas y planes de cursada. Ver
[`project/2. Desarrollo/CARGA_DATOS_INICIALES.md`](project/2.%20Desarrollo/CARGA_DATOS_INICIALES.md).

## Correr la aplicación

Con el entorno virtual activado:

```bash
streamlit run app/main.py
```

Streamlit abre automáticamente el navegador en
<http://localhost:8501>. Si no lo hace, pegar esa URL a mano.

Para detener la aplicación: **Ctrl + C** en la terminal.

## Correr los tests

```bash
pytest tests/
```

Todos los tests corren en verde y no requieren infraestructura
externa (usan una base SQLite temporal en memoria).

## Estructura del repositorio

```
gestor-aulas/
├── app/                        Aplicación Streamlit
│   ├── main.py                 Punto de entrada
│   └── pages/                  Páginas de la UI
├── src/                        Código de la aplicación
│   ├── database/               Modelos ORM y conexión
│   ├── services/               Lógica de dominio
│   ├── ui/                     Componentes reutilizables de UI
│   └── domain/                 Entidades puras
├── data/                       Datos
│   ├── database.db             Base SQLite (incluida en el repo)
│   └── input/                  Excel de entrada
├── scripts/                    Scripts CLI (load, audit)
├── tests/                      Suite de tests
├── project/                    Documentación del proyecto
│   └── README.md               Índice maestro de la documentación
├── requirements.txt            Dependencias de Python
└── pyproject.toml              Configuración del proyecto
```

## Documentación

Toda la documentación técnica y académica del proyecto vive en la
carpeta [`project/`](project/). El punto de entrada es
[`project/README.md`](project/README.md), que actúa como índice
maestro y remite a:

- **Comprensión del dominio** (`project/0. Planteo/`): anteproyecto
  y modelado conceptual inicial.
- **Diseño de la solución** (`project/1. Diseño/`): modelo de datos,
  arquitectura, planteo formal del programa lineal.
- **Detalles técnicos** (`project/2. Desarrollo/`): runbooks, guías
  operativas del asignador, validaciones, ciclos y dictados.
- **Informe académico** (`project/Informe/`): capítulos redactados,
  anexo de base de datos, manual de usuario.

Referencias rápidas para arrancar:

- **¿Cómo se opera un ciclo lectivo desde cero?** →
  [`project/2. Desarrollo/CICLOS_Y_DICTADOS.md`](project/2.%20Desarrollo/CICLOS_Y_DICTADOS.md).
- **¿Cómo se usa el asignador de aulas?** →
  [`project/2. Desarrollo/asignador_guia_operativa.md`](project/2.%20Desarrollo/asignador_guia_operativa.md).
- **Manual de usuario completo** →
  [`project/Informe/anexos/Anexo_Manual_de_Usuario/README.md`](project/Informe/anexos/Anexo_Manual_de_Usuario/README.md).

## Problemas comunes de instalación

**"pip no encuentra Python 3.11"**

En sistemas donde el `python3` default es más nuevo, instalar
Python 3.11 o 3.12 desde <https://www.python.org/downloads/> o con
el gestor de paquetes del sistema (`brew install python@3.11` en
macOS, `apt install python3.11` en Debian/Ubuntu).

**"error installing pulp / cbc"**

PuLP trae CBC como binario para las plataformas comunes (macOS x86
y arm, Linux x86, Windows). Si aparece un error de instalación,
verificar que la versión de Python sea la soportada (3.11 / 3.12).

**"streamlit: command not found"**

El entorno virtual no está activado. Correr:

```bash
source .venv/bin/activate
```

y verificar que el prompt de la terminal muestre `(.venv)` al
principio.

**La app arranca pero no se ve la base pre-cargada**

Verificar que `data/database.db` esté presente y sea el archivo del
release descargado. Si al descomprimir el ZIP el archivo quedó en
otra ubicación, mover a `data/`.

**Puerto 8501 ocupado**

Correr en otro puerto:

```bash
streamlit run app/main.py --server.port 8502
```

## Licencia y créditos

Proyecto académico desarrollado en el marco del trabajo final de la
carrera de Ingeniería Industrial de FCEIA-UNR. Consultar el
informe en `project/Informe/` para el detalle de autores, contexto
institucional y bibliografía.
