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

---

## Instalar y correr — modo simple (doble click)

**Recomendado para usuarios que sólo quieren usar la aplicación.**
No hace falta instalar Python, ni saber usar la terminal, ni correr
`pip install`. Alcanza con descomprimir un ZIP y hacer doble click.

### Requisitos previos

- **Windows 10/11** (64 bits) o **macOS** (Intel o Apple Silicon).
- **Conexión a Internet la primera vez** que se corre la app (para
  bajar Python y las librerías, ~200 MB). Después funciona offline.
- Aproximadamente **500 MB libres** de disco.

### Paso a paso

1. Entrar a la [**página de releases del proyecto**](https://github.com/l-antonelli/gestor-aulas/releases/latest).
2. Descargar el asset **`gestor-aulas-vX.Y.Z-portable.zip`** (el que
   dice "portable" en el nombre — trae los binarios listos para
   arrancar sin instalar nada).
3. **Descomprimir el ZIP** en una carpeta cómoda (Escritorio,
   Documentos, etc.). NO abrir la app desde adentro del ZIP.
4. Entrar en la carpeta descomprimida `gestor-aulas`.
5. Doble click al lanzador correspondiente al sistema operativo:
   - **Windows**: doble click a `start.bat`.
   - **macOS**: click derecho sobre `start.command` → **Abrir**
     (la primera vez macOS muestra un aviso de seguridad — es
     esperable porque el lanzador no está firmado; hacer click en
     **Abrir** en el diálogo).
6. Se abre una ventana de terminal. La **primera corrida tarda
   aproximadamente 1 minuto** porque baja Python y las librerías.
   Las siguientes arrancan en pocos segundos.
7. Cuando termina, la aplicación se abre sola en el navegador en
   <http://localhost:8501>. Si no se abre, pegar esa URL a mano.
8. Para **cerrar** la aplicación: cerrar la ventana de terminal.

Todas las instrucciones detalladas y el troubleshooting típico
están en el archivo `LEEME.txt` dentro del ZIP.

---

## Instalar y correr — modo desarrollador

**Para colaborar en el código, correr los tests o trabajar sobre el
repositorio directamente.**

### Requisitos previos

- **Python 3.11 o 3.12** (no 3.13 todavía — algunas dependencias no
  están compatibles). Verificable con `python --version`.
- **git** para clonar el repositorio.
- Alrededor de **300 MB libres** para el entorno virtual.

### Clonar el repositorio

```bash
git clone https://github.com/l-antonelli/gestor-aulas.git
cd gestor-aulas
```

Para actualizar a una versión etiquetada:

```bash
git fetch --tags
git checkout v0.9.2   # o la versión más reciente
```

### Instalar dependencias

**Opción A — con `uv`** (recomendado, es la misma herramienta que usa
el modo simple):

```bash
# Instalar uv una sola vez (si aún no está)
curl -LsSf https://astral.sh/uv/install.sh | sh    # macOS / Linux
# powershell -c "irm https://astral.sh/uv/install.ps1 | iex"   # Windows

# Crear el entorno y bajar las dependencias
uv sync
```

`uv sync` lee `pyproject.toml` + `uv.lock`, baja Python 3.11 si no
está y arma un `.venv` con todas las dependencias pineadas al lock.

**Opción B — con `venv` + `pip`** (para quien no quiere instalar
`uv`):

```bash
python3.11 -m venv .venv
source .venv/bin/activate            # macOS / Linux
# .venv\Scripts\activate.bat         # Windows
pip install -r requirements.txt
```

### Correr la aplicación

```bash
# Con uv
uv run streamlit run app/main.py

# O con el venv activado
streamlit run app/main.py
```

Streamlit abre automáticamente el navegador en
<http://localhost:8501>. Para detener: **Ctrl + C** en la terminal.

### Correr los tests

```bash
uv run pytest tests/     # con uv
# o
pytest tests/            # con el venv activado
```

Todos los tests corren en verde y no requieren infraestructura
externa (usan una base SQLite temporal en memoria).

### Reinicializar la base de datos

El repositorio incluye una base pre-cargada en `data/database.db`
con el catálogo actual (carreras, materias, planes de estudio,
aulas). No hace falta cargar nada la primera vez.

Para reinicializarla desde los Excel de entrada en `data/input/`:

```bash
uv run python -m scripts.load_initial_data --reset
```

Después del reset hay que recrear desde la UI: nombres y atributos
de carreras, ciclos, dictados, cronogramas y planes de cursada. Ver
[`project/2. Desarrollo/CARGA_DATOS_INICIALES.md`](project/2.%20Desarrollo/CARGA_DATOS_INICIALES.md).

---

## Cómo se distribuye el sistema

El ZIP "portable" que se descarga desde las releases se arma con el
script `scripts/build_portable_zip.sh`. Ese script:

1. Baja los binarios portables de [`uv`](https://docs.astral.sh/uv/)
   para macOS (arm64 y x86_64) y Windows (x86_64) desde el
   [repositorio oficial de Astral](https://github.com/astral-sh/uv/releases).
2. Copia el código del proyecto excluyendo material de desarrollo
   (tests, docs internas, caches, etc.).
3. Empaqueta todo en un único ZIP.

Cuando el usuario final hace doble click al lanzador, `uv` baja
Python 3.11 y las dependencias del proyecto en el cache del sistema
operativo (`~/.cache/uv` en macOS y Linux, `%LOCALAPPDATA%\uv` en
Windows) y las instala en un entorno virtual local. En corridas
siguientes ese cache se reutiliza y todo arranca casi al instante.

Los detalles completos de por qué elegimos este esquema, qué
alternativas descartamos y cómo se re-empaqueta el sistema para
distribuir una nueva versión están en
[`project/2. Desarrollo/DISTRIBUCION.md`](project/2.%20Desarrollo/DISTRIBUCION.md).

---

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
├── scripts/                    Scripts CLI (load, audit, build ZIP)
├── tests/                      Suite de tests
├── project/                    Documentación del proyecto
│   └── README.md               Índice maestro de la documentación
├── start.command               Lanzador macOS (sólo en el ZIP portable)
├── start.bat                   Lanzador Windows (sólo en el ZIP portable)
├── LEEME.txt                   Instrucciones para el usuario final
├── pyproject.toml              Configuración del proyecto y dependencias
├── uv.lock                     Lock file de versiones
└── requirements.txt            Dependencias en formato pip (opcional)
```

---

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
  operativas del asignador, validaciones, ciclos y dictados,
  distribución.
- **Informe académico** (`project/Informe/`): capítulos redactados,
  anexo de base de datos, manual de usuario.

Referencias rápidas para arrancar:

- **¿Cómo se opera un ciclo lectivo desde cero?** →
  [`project/2. Desarrollo/CICLOS_Y_DICTADOS.md`](project/2.%20Desarrollo/CICLOS_Y_DICTADOS.md).
- **¿Cómo se usa el asignador de aulas?** →
  [`project/2. Desarrollo/asignador_guia_operativa.md`](project/2.%20Desarrollo/asignador_guia_operativa.md).
- **¿Cómo se distribuye la aplicación?** →
  [`project/2. Desarrollo/DISTRIBUCION.md`](project/2.%20Desarrollo/DISTRIBUCION.md).
- **Manual de usuario completo** →
  [`project/Informe/anexos/Anexo_Manual_de_Usuario/README.md`](project/Informe/anexos/Anexo_Manual_de_Usuario/README.md).

---

## Problemas comunes

**"Windows me dice que el archivo es peligroso"**

Es un falso positivo típico de scripts de arranque sin firmar. En
la ventana "Windows protegió tu equipo", hacer click en **"Más
información"** y después en **"Ejecutar de todas formas"**. La app
sólo corre en tu computadora y no se conecta a internet (más allá
de la descarga inicial de dependencias).

**"macOS me dice 'no se puede abrir porque el desarrollador no puede
verificarse'"**

Es Gatekeeper. Hacer **click derecho** sobre `start.command` (no
doble click) y elegir **"Abrir"** en el menú contextual. Aparece un
diálogo con un botón "Abrir" que hay que tocar. Esto sólo hace
falta la primera vez.

**"streamlit: command not found" (modo desarrollador)**

El entorno virtual no está activado. Correr:

```bash
source .venv/bin/activate
```

y verificar que el prompt de la terminal muestre `(.venv)`.
Alternativamente usar `uv run streamlit ...` que no requiere
activar nada.

**"Puerto 8501 ocupado"**

Cerrar cualquier otra corrida del sistema que haya quedado abierta.
Si aún así falla, correr en otro puerto (modo desarrollador):

```bash
streamlit run app/main.py --server.port 8502
```

**"La primera corrida tarda mucho"**

Es esperable: `uv` está bajando Python 3.11 (~30 MB) y las
librerías del proyecto (~200 MB) al cache del sistema. Corridas
siguientes son casi instantáneas.

**"La app arranca pero no veo la base pre-cargada"**

Verificar que `data/database.db` esté presente en la carpeta
`gestor-aulas` descomprimida. Si al descomprimir el ZIP el archivo
quedó en otra ubicación, moverlo a `data/`.

---

## Licencia y créditos

Proyecto académico desarrollado en el marco del trabajo final de la
carrera de Ingeniería Industrial de FCEIA-UNR. Consultar el
informe en [`project/Informe/`](project/Informe/) para el detalle
de autores, contexto institucional y bibliografía.
