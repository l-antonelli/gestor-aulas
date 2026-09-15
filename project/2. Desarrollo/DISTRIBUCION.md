# Distribución del sistema a usuarios no técnicos

> **Estado**: implementado a partir de la release **v0.9.2**. Este
> documento describe cómo funciona el mecanismo de distribución
> actual, por qué se eligió y cómo mantenerlo.

Este documento cubre cómo se distribuye la aplicación de asignación
de aulas (Streamlit + SQLite + PuLP) a un usuario final no técnico,
respetando las siguientes restricciones no negociables:

- El usuario no puede instalar Python, no puede correr `pip install`
  ni abrir una terminal. Idealmente hace doble click a un archivo y
  la aplicación se abre en el navegador.
- La ejecución es 100% local. Cada usuario tiene su propia base
  SQLite (`data/database.db`) en su computadora.
- El desarrollador trabaja en macOS (Apple Silicon) y necesita
  re-empaquetar la aplicación con baja fricción cada vez que
  actualiza el código, sin recompilar cientos de megabytes.
- El usuario final puede estar en Windows o macOS (Intel o Apple
  Silicon).

---

## 1. Cómo funciona la distribución (visión general)

La distribución se apoya en una herramienta relativamente nueva
llamada [**`uv`**](https://docs.astral.sh/uv/), un gestor de
paquetes y entornos de Python escrito en Rust por
[Astral](https://astral.sh/). `uv` es lo que hace posible que la
aplicación arranque con un doble click sin que el usuario tenga
Python instalado. Vale la pena entender por qué antes de entrar en
el detalle de los scripts.

### 1.1. Qué es `uv` y por qué lo usamos

`uv` es un ejecutable único, portable y sin dependencias que
reemplaza —y unifica— buena parte del ecosistema clásico de
Python: `pip`, `virtualenv`, `pip-tools`, `pyenv` y `pipx`. Todas
esas herramientas tradicionalmente hay que instalarlas por
separado y coordinar entre sí. `uv` las trae juntas en un solo
binario que además hace cada operación
[**una o dos órdenes de magnitud más rápido**](https://astral.sh/blog/uv)
que las herramientas tradicionales, gracias a paralelización
agresiva, un resolvedor propio y un cache global inteligente.

Para el problema de distribución las capacidades relevantes de
`uv` son cuatro:

1. **Es un único ejecutable portable, sin dependencias.** Se baja
   un archivo (`uv` en macOS/Linux, `uv.exe` en Windows) de
   aproximadamente 30 MB y funciona. No pide instalar nada más.
2. **Sabe descargar y gestionar interpretes Python.** Si el sistema
   no tiene Python 3.11, `uv sync` lo baja de forma automática
   desde el proyecto oficial [python-build-standalone](https://github.com/astral-sh/python-build-standalone)
   y lo cachea en `~/.cache/uv` (o `%LOCALAPPDATA%\uv` en Windows).
   Esto evita el peor punto de fricción para el usuario final:
   pedirle que instale Python.
3. **Instala dependencias muy rápido y de forma reproducible.**
   Toma el `pyproject.toml` + `uv.lock` del proyecto, arma un
   `.venv` local, y baja/instala todas las librerías. La primera
   corrida tarda un minuto porque baja ~200 MB; las siguientes son
   casi instantáneas gracias al cache.
4. **Es cross-plataforma con el mismo lock file.** El mismo
   `uv.lock` resuelve correctamente en Windows y macOS: `uv` elige
   los wheels apropiados para cada sistema operativo en tiempo de
   sincronización. **No hay compilación cruzada** porque no se
   compila nada: se distribuye Python fuente y `uv` baja los
   binarios que corresponden a cada máquina.

En criollo, lo que `uv` nos permite es distribuir un ZIP muy
liviano (~80 MB, dominado por los binarios de `uv` para las tres
plataformas soportadas) que contiene el código fuente tal cual y
un lanzador simple que delega en `uv` toda la parte pesada. El
usuario no ve nada de esto: doble click, esperar un minuto la
primera vez, la app se abre.

### 1.2. Alternativa a "compilar un ejecutable"

Lo que hace `uv` es fundamentalmente diferente de lo que hacen
PyInstaller, Nuitka, Briefcase o `streamlit-desktop-app`. Esas
herramientas **empaquetan un intérprete Python y todas las
librerías dentro de un único binario nativo** (un `.exe` o un
`.app` de cientos de megabytes). Con ese modelo:

- Cada release hay que **recompilar todo el ejecutable** aunque
  haya cambiado una sola línea de Python.
- No se puede cross-compilar Windows desde macOS sin Wine, así
  que hace falta acceso a una máquina Windows para generar el
  `.exe`.
- Actualizar componentes JS custom (por ejemplo
  `streamlit-calendar`) requiere ajustes manuales en la config
  del empaquetador.

Con el modelo `uv`-bootstrap:

- El código se distribuye **como está** (los mismos `.py` del
  repo).
- El ZIP se arma en macOS pero **sirve para Windows también**,
  porque `uv` es lo único plataforma-específico y lo empaquetamos
  para las tres arquitecturas.
- Cada nueva release es re-empaquetar el ZIP con `rsync` + `zip`,
  que corre en segundos.

---

## 2. Comparativa de opciones evaluadas

| Opción | Setup inicial | Tamaño paquete | UX usuario final | Windows desde macOS | Re-distribución | Gotchas |
|---|---|---|---|---|---|---|
| **`uv`-bootstrap (elegida)** | Bajo | ~80 MB ZIP + primera corrida baja ~200 MB en cache local del usuario | Doble click a `.command`/`.bat`; primera vez tarda 30-90 s | Sí (mismo ZIP sirve ambos SO) | Correr `scripts/build_portable_zip.sh` | Requiere Internet la primera vez; macOS Gatekeeper bloquea `.command` sin firmar (se resuelve con click derecho > Abrir) |
| PyInstaller manual | Alto | 300-500 MB | Doble click al `.app`/`.exe`; Gatekeeper prompt en macOS | **No** (sin Wine) | Rebuild completo cada vez | Requiere `--collect-all streamlit`, hook con `copy_metadata`, forzar `developmentMode=false`; componentes JS custom como `streamlit-calendar` requieren `datas` explícitos |
| `streamlit-desktop-app` | Bajo (1 comando) | 300-500 MB | Doble click; abre ventana pywebview nativa | **No** | Rebuild completo | Última release diciembre 2024, sin updates en 2025-2026; Windows requiere WebView2 + .NET 4 |
| stlite desktop (Pyodide + Electron) | Medio-alto (npm + electron-builder) | 400-800 MB | Doble click | Parcial | Rebuild | **Bloqueante: PuLP no funciona en WASM** (CBC es binario nativo Mach-O/PE/ELF) |
| Nuitka | Alto | ~ igual o mayor que PyInstaller | Doble click | **No** | Rebuild completo | Sin caso documentado con Streamlit; principal ventaja (ofuscación) no aplica |
| Briefcase (BeeWare) | Alto | 200-400 MB | Doble click | No confirmado | Rebuild completo | Diseñado para apps GUI cliente (Toga), sin caso documentado con Streamlit ni con server HTTP local |
| Docker Desktop | Bajo (dev) / muy alto (usuario) | ~600 MB imagen + Docker Desktop | Requiere instalar Docker, aceptar licencia, correr comando en terminal | Sí | Sólo `docker pull` | **Inviable para usuario no técnico** |

### Notas verificadas durante la investigación

- **PuLP** incluye binarios CBC embebidos en el wheel oficial
  (`pulp/solverdir/cbc/{osx,win,linux}/...`), a pesar de que la
  documentación pública sugiere lo contrario. En Apple Silicon corre
  bajo Rosetta 2 porque sólo se envía `osx/i64`. Esto habilita el
  path `uv`-bootstrap sin instalaciones adicionales del solver.
- **stlite** (`@stlite/browser`) queda descartado: aunque SQLite
  existe en Pyodide, PuLP no puede ejecutar CBC en WASM.
- **Cross-compilar Windows desde macOS con PyInstaller es imposible
  sin Wine.** Cualquier opción basada en PyInstaller obliga a tener
  acceso a una máquina Windows (o una VM/CI runner) para generar el
  `.exe`.
- **Marimo, Reflex y Solara** ofrecen paths de packaging propios,
  pero migrar la aplicación (ya escrita en Streamlit con
  `streamlit-calendar`) queda fuera del alcance de este análisis.

---

## 3. Implementación actual

### 3.1. Estructura del ZIP distribuible

El ZIP portable se llama `gestor-aulas-vX.Y.Z-portable.zip` y tiene
esta estructura:

```
gestor-aulas/
├── start.command               Lanzador macOS (permiso +x)
├── start.bat                   Lanzador Windows
├── LEEME.txt                   Instrucciones para el usuario final
├── README.md                   README del proyecto
├── pyproject.toml              Configuración del proyecto (deps)
├── uv.lock                     Lock reproducible de versiones
├── app/                        Código Streamlit
├── src/                        Código de dominio
├── scripts/                    Scripts CLI
├── data/                       Base pre-cargada + Excel de entrada
├── project/                    Documentación
└── bin/
    ├── uv-macos-arm64          Binario portable macOS Apple Silicon
    ├── uv-macos-x86_64         Binario portable macOS Intel
    └── uv.exe                  Binario portable Windows x86_64
```

Los tres binarios `uv` (uno por arquitectura soportada) suman
alrededor de 120 MB descomprimidos y ~55 MB comprimidos en el ZIP.
El ZIP final pesa cerca de **80 MB**.

Excluidos del ZIP (vs. el repo completo): `tests/`, `pytest.ini`,
`CLAUDE.md`, `TODO.md`, `run.py`, `requirements-proj.txt`, migraciones
sueltas en la raíz del repo, caches de desarrollo (`.pytest_cache/`,
`__pycache__/`, `.mypy_cache/`, `.ruff_cache/`, `.hypothesis/`),
metadata de editor (`.vscode/`, `.cursor/`, `.claude/`), y las
subcarpetas de `project/Informe/` con material fuente local
(bibliografía, pautas de cátedra, borradores).

### 3.2. Lanzadores

**`start.command` (macOS)** detecta la arquitectura con `uname -m`
y elige entre `bin/uv-macos-arm64` (Apple Silicon) y
`bin/uv-macos-x86_64` (Intel). Después corre:

```bash
"$UV_BIN" sync --frozen
"$UV_BIN" run streamlit run app/main.py \
    --server.headless=false \
    --server.address=localhost \
    --server.port=8501 \
    --browser.gatherUsageStats=false
```

`sync --frozen` respeta el `uv.lock` exactamente y no lo actualiza.
Streamlit se levanta en modo no-headless para que abra el
navegador automáticamente.

**`start.bat` (Windows)** hace lo mismo con `bin\uv.exe`.

Ambos scripts imprimen mensajes en castellano y muestran el error
en un `pause` si algo falla, para que el usuario final pueda
copiar el mensaje y compartirlo con soporte.

### 3.3. Script `scripts/build_portable_zip.sh`

Se corre con:

```bash
scripts/build_portable_zip.sh [version]
```

Si no se pasa versión, la lee del `pyproject.toml`. Los pasos que
ejecuta:

1. Baja los binarios `uv` para las tres arquitecturas soportadas
   desde el [repositorio oficial de Astral](https://github.com/astral-sh/uv/releases).
   La versión se controla con la variable de entorno `UV_VERSION`
   (default: `0.12.15`). Se cachea en `dist/uv-cache/` para no
   volver a bajarlos en corridas siguientes.
2. Descomprime cada archivo y copia el binario correspondiente a
   `dist/gestor-aulas/bin/` con el nombre apropiado.
3. Copia el código del repo a `dist/gestor-aulas/` con `rsync`,
   aplicando la lista de exclusiones descrita más arriba.
4. Empaqueta todo en `dist/gestor-aulas-vX.Y.Z-portable.zip`.
5. Imprime el path del ZIP y el comando para subirlo como asset
   de la release en GitHub.

### 3.4. `pyproject.toml` y `uv.lock`

Las dependencias están pineadas a versiones exactas en
`pyproject.toml`:

```toml
[project]
name = "gestor-aulas"
version = "0.1.0"
description = "Sistema de asignación de aulas para FCEIA - UNR"
requires-python = ">=3.11,<3.13"
dependencies = [
    "streamlit==1.52.2",
    "streamlit-calendar==1.4.0",
    "sqlmodel==0.0.31",
    "pulp==3.3.2",
    "pandas==2.3.3",
    "pydantic==2.12.5",
    "openpyxl==3.1.5",
    "altair==6.0.0",
]

[dependency-groups]
dev = [
    "pytest==9.0.2",
    "hypothesis==6.148.7",
]
```

El `uv.lock` completa la resolución exhaustiva a nivel wheel,
plataforma y hash. Cuando el usuario corre `uv sync --frozen`, `uv`
lee ese lock y baja exactamente los mismos wheels que se probaron
al armar la release.

Para actualizar las dependencias durante desarrollo se corre
`uv lock` (que regenera el lock respetando los pins del
`pyproject.toml`) y se commitean ambos archivos.

### 3.5. `LEEME.txt` para el usuario final

Se distribuye en la raíz del ZIP con:

- Requisitos previos.
- Paso a paso ilustrado en criollo.
- Preguntas frecuentes (Gatekeeper macOS, SmartScreen Windows,
  puerto ocupado, primera corrida lenta).
- Estructura del ZIP.

El README.md raíz del repositorio duplica esta información y la
extiende con el modo desarrollador, para que sirva tanto de guía
al usuario final como al desarrollador que baja el repo.

### 3.6. Firma del binario en macOS (opcional pero recomendado)

Sin firma, macOS bloquea `.command` con Gatekeeper y el usuario
debe hacer click derecho > Abrir la primera vez. Alternativas:

- **Sin firma (más simple, actualmente en uso)**: aceptable si el
  usuario está dispuesto a hacer click derecho > Abrir la primera
  vez y ver un prompt de Gatekeeper. Documentado en `LEEME.txt`.
- **Con Apple Developer ID (~99 USD/año)**: firmar y notarizar el
  ZIP completo con `codesign --deep --sign "Developer ID Application: TU_NOMBRE" gestor-aulas/`
  y luego `xcrun notarytool submit`. Elimina todos los prompts. Sólo
  vale la pena si se va a distribuir a muchos usuarios.

Para este caso (uno o dos usuarios finales), la firma no es
necesaria. Alcanza con documentar el paso de "click derecho > Abrir".

### 3.7. Cross-plataforma desde macOS

`uv` es multiplataforma: el mismo `pyproject.toml` y `uv.lock`
resuelven correctamente en Windows y macOS. **No hay compilación
cruzada** porque no se compila nada: se distribuye Python fuente y
`uv` descarga los wheels apropiados para cada SO en la primera
corrida.

---

## 4. Workflow de re-distribución

Cuando se actualice el código (después de recibir feedback):

1. Hacer los cambios en el repo como siempre.
2. Si cambiaron dependencias: `uv lock` para regenerar `uv.lock` y
   commitear.
3. Actualizar la versión en `pyproject.toml` si aplica.
4. Empaquetar y publicar:

   ```bash
   # 1. Armar el ZIP portable
   scripts/build_portable_zip.sh 0.9.2

   # 2. Commit + push si hay cambios pendientes en main
   git add -A && git commit -m "..." && git push

   # 3. Crear tag anotado y push
   git tag -a v0.9.2 -m "v0.9.2"
   git push --tags

   # 4. Crear release y subir el ZIP portable como asset
   gh release create v0.9.2 \
       --title "v0.9.2 — <título breve>" \
       --notes-file <(cat <<EOF
   Notas de la release...
   EOF
   )
   gh release upload v0.9.2 dist/gestor-aulas-v0.9.2-portable.zip
   ```

5. **Alternativa "sólo código" para actualizaciones menores**:
   mandarle al usuario únicamente los archivos `.py` cambiados o un
   ZIP de las carpetas `app/` y `src/`, con instrucciones de
   "reemplazar por sobre la carpeta anterior". El usuario mantiene
   el `bin/`, el cache de `uv` y su `data/database.db` intactos.
   Este atajo es útil para hotfixes rápidos sin regenerar los ~80 MB
   del ZIP portable.

---

## 5. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Primera corrida requiere Internet para bajar Python y wheels | Alto si el usuario está sin conexión al arranque inicial | Documentar en `LEEME.txt`; opcionalmente pre-armar un ZIP "offline" corriendo `uv sync` en una máquina de referencia por SO y distribuyendo también el cache pre-poblado |
| Gatekeeper bloquea `.command` sin firmar en macOS | Bajo (fricción única en la primera apertura) | Documentar "click derecho > Abrir"; a futuro, notarizar si se distribuye a más gente |
| Windows Defender / SmartScreen bloquea `.bat` la primera vez | Bajo | Instruir "Más información > Ejecutar de todas formas" |
| PuLP CBC en Apple Silicon corre bajo Rosetta | Bajo (sólo si el usuario está en Mac Intel/ARM sin Rosetta 2 instalado) | Rosetta 2 se instala automáticamente al primer uso; documentar |
| El usuario corre múltiples versiones en simultáneo | Bajo | El puerto `8501` puede quedar ocupado; documentar cerrar la terminal antes de abrir otra versión |
| `data/database.db` empaquetado pisa la DB del usuario en una actualización | Alto | En el workflow de re-distribución, **excluir** `data/database.db` del ZIP en actualizaciones incrementales; documentar que el archivo `data/database.db` es del usuario y no debe reemplazarse |
| Cambios de esquema en la DB rompen la instalación del usuario | Alto | Escribir migraciones idempotentes (ya se hace) y ejecutarlas al arrancar en `init_db()`; en cambios mayores, enviar un script de migración aparte y documentarlo |
| El usuario borra `bin/` o el cache de `uv` accidentalmente | Bajo | El script re-baja automáticamente en la próxima corrida (si hay Internet) |
| Streamlit-calendar (componente JS) no funciona por algún motivo | Bajo (se instala como wheel normal desde PyPI) | Ya viene con sus estáticos empaquetados en el wheel; sin acciones especiales |

---

## 6. Alternativas explícitamente descartadas

- **stlite / Pyodide**: descartado porque PuLP requiere el solver
  CBC compilado nativamente, y en WASM no puede ejecutarse.
- **Docker Desktop**: descartado por UX del usuario final (requiere
  instalación pesada, licencia, y comandos en terminal).
- **Streamlit Community Cloud**: descartado por el requisito de
  ejecución local con base SQLite propia por usuario.
- **Migración a Marimo / Reflex / Solara**: fuera de alcance;
  requeriría reescribir toda la UI.
- **PyInstaller / Nuitka / Briefcase**: descartadas por la
  combinación de tres problemas — el requisito de acceso a una
  máquina Windows para generar el `.exe`, la necesidad de recompilar
  el ejecutable en cada release, y la fricción de configurar
  componentes JS custom de Streamlit.

---

## 7. Preguntas frecuentes

**¿Por qué no distribuir sólo `pip install -r requirements.txt`?**
Porque el usuario final no tiene Python instalado ni sabe usar la
terminal. El objetivo es "doble click", no "abrir la terminal y
correr tres comandos".

**¿Por qué `uv` y no `pip`?** `uv` incluye la gestión de Python
como interpretes (baja 3.11 si no está) y es mucho más rápido. `pip`
requiere tener Python previamente instalado.

**¿Por qué el ZIP pesa 80 MB si el código son unos pocos MB?**
Porque incluye tres binarios de `uv` (uno por arquitectura
soportada) que suman ~120 MB descomprimidos. Al comprimir bajan a
~55 MB. Los otros 25 MB son código + docs + base pre-cargada.

**¿Y si el usuario está sin Internet la primera vez?** No arranca.
Se puede armar un ZIP "offline" pre-poblando el cache de `uv`, pero
por ahora no se soporta oficialmente porque el caso de uso actual
(compañero de trabajo con acceso a Internet) no lo requiere.

**¿Puedo distribuir sólo los `.py` cambiados sin regenerar el ZIP?**
Sí, mientras no cambien las dependencias. Alcanza con mandar las
carpetas `app/` y/o `src/` para pisar las anteriores. El cache de
`uv` y la base de datos del usuario se mantienen intactos.

**¿Es seguro correr esto en la máquina de otra persona?** Sí. `uv`
es open-source (Apache 2.0 / MIT), muy popular en la comunidad
Python y viene firmado por Astral. La app en sí sólo corre en
`localhost` y no se conecta a Internet más allá de la instalación
inicial de dependencias.
