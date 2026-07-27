# Distribución del Sistema de Asignación de Aulas a usuarios no técnicos

Este documento describe el análisis, la comparativa y la guía de implementación para
distribuir el sistema (aplicación Streamlit + SQLite + PuLP) a un usuario final no
técnico, cumpliendo las siguientes restricciones:

- El usuario no puede instalar Python, no puede correr `pip install` ni abrir una
  terminal. Idealmente debe hacer doble click a un archivo y abrir la aplicación en
  el navegador.
- La ejecución es 100% local. Cada usuario tiene su propia base SQLite
  (`data/database.db`).
- El desarrollador trabaja en macOS (Apple Silicon) y necesita re-empaquetar la
  aplicación con baja fricción cada vez que actualice el código, sin recompilar
  cientos de megabytes.
- El usuario final puede estar en Windows o macOS.

## 1. Resumen ejecutivo

La opción recomendada es **`uv`-bootstrap**: un script `start.command` (macOS) y
`start.bat` (Windows) que, al hacer doble click, invocan al binario portable
[`uv`](https://docs.astral.sh/uv/) para descargar la versión correcta de Python y
resolver las dependencias en la primera corrida, y luego lanzan Streamlit contra el
código fuente que se distribuye tal cual (los mismos `.py` del repo). Es la única
alternativa que combina las tres propiedades no negociables del problema:
funciona en Windows y macOS desde una máquina de build macOS, soporta PuLP con
su solver CBC nativo (que descarta stlite/Pyodide), y permite re-distribuir
actualizaciones enviando únicamente los archivos `.py` modificados (o el
repositorio completo comprimido), sin volver a compilar un ejecutable de cientos
de megabytes cada vez.

El **plan B** es empaquetar con **PyInstaller + `streamlit-desktop-app`** para
macOS únicamente (el compañero, si está en Windows, recibiría de todas formas el
ZIP con `uv`-bootstrap). PyInstaller entrega un `.app` autocontenido pero
requiere rebuild completo por cada cambio y no cross-compila a Windows desde
macOS.

## 2. Comparativa de opciones evaluadas

| Opción | Setup inicial | Tamaño paquete | UX usuario final | Windows desde macOS | Re-distribución | Gotchas |
|---|---|---|---|---|---|---|
| **`uv`-bootstrap (recomendado)** | Bajo | ~5 MB script + ~30 MB `uv` + primera corrida descarga ~200 MB en cache local del usuario | Doble click a `.command`/`.bat`; primera vez tarda 30-90s | Sí (mismo ZIP sirve ambos SO) | **Sólo enviar los `.py` modificados** o el repo completo comprimido | Requiere Internet la primera vez; macOS Gatekeeper puede bloquear `.command` sin firmar (se resuelve con click derecho > Abrir) |
| **PyInstaller manual** | Alto | 300-500 MB | Doble click al `.app`/`.exe`; Gatekeeper prompt en macOS | **No** (sin Wine) | Rebuild completo cada vez | Requiere `--collect-all streamlit`, hook con `copy_metadata`, forzar `developmentMode=false`; componentes JS custom como `streamlit-calendar` requieren `datas` explícitos |
| **`streamlit-desktop-app`** | Bajo (1 comando) | 300-500 MB | Doble click; abre ventana pywebview nativa | **No** | Rebuild completo | Última release dic-2024, sin updates en 2025-2026; Windows requiere WebView2 + .NET 4; no aborda componentes custom |
| **stlite desktop (Pyodide + Electron)** | Medio-alto (npm + electron-builder) | 400-800 MB | Doble click | Parcial | Rebuild | **Bloqueante: PuLP no funciona en WASM** (CBC es binario nativo Mach-O/PE/ELF) |
| **Nuitka** | Alto | ~ igual o mayor que PyInstaller | Doble click | **No** | Rebuild completo | Sin caso documentado con Streamlit; principal ventaja (ofuscación) no aplica |
| **Briefcase (BeeWare)** | Alto | 200-400 MB | Doble click | No confirmado | Rebuild completo | Diseñado para apps GUI cliente (Toga), sin caso documentado con Streamlit ni con server HTTP local |
| **Docker Desktop** | Bajo (dev) / muy alto (usuario) | ~600 MB imagen + Docker Desktop | Requiere instalar Docker, aceptar licencia, correr comando en terminal | Sí | Sólo `docker pull` | **Inviable para usuario no técnico** |

### Notas verificadas durante la investigación

- **PuLP** incluye binarios CBC embebidos en el wheel oficial (`pulp/solverdir/cbc/{osx,win,linux}/...`), a pesar de que la documentación pública sugiere lo contrario. En Apple Silicon corre bajo Rosetta 2 porque sólo se envía `osx/i64`. Esto habilita el path `uv`-bootstrap sin instalaciones adicionales del solver.
- **stlite** (`@stlite/browser` v1.8.1, junio 2026) queda descartado: aunque SQLite existe en Pyodide, PuLP no puede ejecutar CBC en WASM.
- **Cross-compilar Windows desde macOS con PyInstaller es imposible sin Wine.** Cualquier opción basada en PyInstaller obliga a tener acceso a una máquina Windows (o una VM/CI runner) para generar el `.exe`.
- **Marimo, Reflex y Solara** ofrecen paths de packaging propios, pero migrar la aplicación (ya escrita en Streamlit con `streamlit-calendar` y `streamlit-pydantic`) queda fuera del alcance de este análisis.

## 3. Guía de implementación de la opción recomendada (`uv`-bootstrap)

### 3.1. Estructura del ZIP distribuible

```
gestor-aulas/
  app/
  src/
  scripts/
  data/                       (con database.db inicial o vacío)
  requirements.txt
  pyproject.toml              (opcional, mejor con dependencias fijadas)
  bin/
    uv-macos                  (~30 MB, binario portable)
    uv.exe                    (~30 MB, binario portable Windows)
  start.command               (macOS, con permiso +x)
  start.bat                   (Windows)
  LEEME.txt                   (instrucciones para el usuario final)
```

El binario `uv` se descarga desde [releases oficiales de Astral](https://github.com/astral-sh/uv/releases)
para cada plataforma. Es un único ejecutable sin dependencias.

### 3.2. Archivo `pyproject.toml` para fijar dependencias

Recomendado migrar de `requirements.txt` a `pyproject.toml` con versiones exactas
para que `uv` resuelva reproduciblemente:

```toml
[project]
name = "gestor-aulas"
version = "0.1.0"
requires-python = ">=3.11,<3.13"
dependencies = [
    "streamlit>=1.28,<2.0",
    "streamlit-calendar>=1.2",
    "streamlit-pydantic==0.6.0",
    "sqlmodel>=0.0.14",
    "pulp>=2.7",
    "pandas>=2.0",
    "openpyxl>=3.1",
    "pydantic>=2.0",
]
```

Se puede generar un `uv.lock` con `uv lock` para lockear las versiones exactas
que probaste vos.

### 3.3. `start.command` (macOS)

```bash
#!/usr/bin/env bash
set -euo pipefail

# Resolver el directorio del script (funciona con doble click desde Finder)
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

export PATH="$DIR/bin:$PATH"

# La primera corrida descarga Python 3.11 y todas las dependencias en el cache
# de uv (~/.cache/uv/). Corridas siguientes son casi instantáneas.
./bin/uv-macos sync --frozen

# Lanza Streamlit y abre el navegador automáticamente
./bin/uv-macos run streamlit run app/main.py \
    --server.headless=false \
    --server.address=localhost \
    --server.port=8501 \
    --browser.gatherUsageStats=false
```

Dar permiso de ejecución antes de empaquetar el ZIP:

```bash
chmod +x start.command
chmod +x bin/uv-macos
```

### 3.4. `start.bat` (Windows)

```bat
@echo off
setlocal
cd /d "%~dp0"

set "PATH=%~dp0bin;%PATH%"

bin\uv.exe sync --frozen
if errorlevel 1 goto error

bin\uv.exe run streamlit run app\main.py ^
    --server.headless=false ^
    --server.address=localhost ^
    --server.port=8501 ^
    --browser.gatherUsageStats=false
goto end

:error
echo Hubo un problema al preparar la aplicacion. Contactame para ayudarte.
pause

:end
endlocal
```

### 3.5. `LEEME.txt` para el compañero

```
Sistema de Asignación de Aulas - Instrucciones

Primera vez:
- macOS: hacer click derecho sobre "start.command" y elegir "Abrir". Va a
  aparecer un mensaje de seguridad; confirmar. La primera corrida tarda
  aproximadamente un minuto porque descarga Python y las librerías necesarias
  (una única vez, requiere conexión a internet).
- Windows: hacer doble click sobre "start.bat". Windows Defender puede pedir
  confirmación la primera vez. La primera corrida tarda aproximadamente un
  minuto y requiere conexión a internet.

En corridas posteriores el arranque es inmediato y no requiere conexión.

La aplicación se abre automáticamente en el navegador (Chrome/Edge/Safari).
Para cerrarla, cerrar la ventana de la terminal negra que se abre junto con
el navegador.
```

### 3.6. Firma del binario en macOS (opcional pero recomendado)

Sin firma, macOS bloquea `.command` con Gatekeeper y el usuario debe hacer
click derecho > Abrir la primera vez. Alternativas:

- **Sin firma (más simple)**: aceptable si el usuario está dispuesto a hacer
  click derecho > Abrir la primera vez y ver un prompt de Gatekeeper.
- **Con Apple Developer ID (~99 USD/año)**: firmar y notarizar el ZIP completo
  con `codesign --deep --sign "Developer ID Application: TU_NOMBRE" gestor-aulas/`
  y luego `xcrun notarytool submit`. Elimina todos los prompts. Sólo vale la
  pena si van a distribuir a muchos usuarios.

Para este caso (un solo compañero), la firma no es necesaria. Alcanza con
documentar en `LEEME.txt` el paso de "click derecho > Abrir".

### 3.7. Cross-plataforma desde macOS

`uv` es multiplataforma: el mismo `pyproject.toml` y `uv.lock` resuelven
correctamente en Windows y macOS. **No hay compilación cruzada** porque no se
compila nada: se distribuye Python fuente y `uv` descarga los wheels
apropiados para cada SO en la primera corrida.

## 4. Workflow de re-distribución

Cuando se actualice el código (después de recibir feedback del compañero):

1. Hacer los cambios en el repo como siempre.
2. Si cambiaron dependencias: `uv lock` para actualizar `uv.lock`.
3. Actualizar la versión en `pyproject.toml`.
4. Empaquetar el repo:

   ```bash
   # Desde la raíz del proyecto
   VERSION=$(grep '^version' pyproject.toml | cut -d'"' -f2)
   rm -rf dist/
   mkdir -p dist/gestor-aulas
   rsync -av \
       --exclude='.git' \
       --exclude='.venv' \
       --exclude='__pycache__' \
       --exclude='*.pyc' \
       --exclude='.pytest_cache' \
       --exclude='tests' \
       --exclude='dist' \
       --exclude='data/database.db.backup-*' \
       ./ dist/gestor-aulas/
   cd dist
   zip -r "gestor-aulas-v${VERSION}.zip" gestor-aulas/
   ```

5. **Alternativa "sólo código" para actualizaciones menores**: enviar
   únicamente los archivos `.py` cambiados o un ZIP de las carpetas
   `app/` y `src/`, con instrucciones de "reemplazar por sobre la carpeta
   anterior". El compañero mantiene el `bin/`, el cache de `uv` y su
   `data/database.db` intactos.

## 5. Riesgos y mitigaciones

| Riesgo | Impacto | Mitigación |
|---|---|---|
| Primera corrida requiere Internet para bajar Python y wheels | Alto si el compañero está sin conexión al arranque inicial | Documentar en `LEEME.txt`; opcionalmente pre-armar un ZIP "offline" corriendo `uv sync` en una máquina de referencia por SO y distribuyendo también el cache pre-poblado |
| Gatekeeper bloquea `.command` sin firmar en macOS | Bajo (fricción única en la primera apertura) | Documentar "click derecho > Abrir"; a futuro, notarizar si se distribuye a más gente |
| Windows Defender / SmartScreen bloquea `.bat` la primera vez | Bajo | Instruir "Más información > Ejecutar de todas formas" |
| PuLP CBC en Apple Silicon corre bajo Rosetta | Bajo (sólo si el compañero está en Mac Intel/ARM sin Rosetta 2 instalado) | Rosetta 2 se instala automáticamente al primer uso; documentar |
| `streamlit-pydantic` está pinneado a 0.6.0 (no mantenido activamente) | Medio si en el futuro rompe con Streamlit nuevo | Fijar Streamlit a `<2.0`; migrar a `st.form` nativo si `streamlit-pydantic` deja de andar |
| El compañero corre múltiples versiones en simultáneo | Bajo | El puerto `8501` puede quedar ocupado; documentar cerrar la terminal negra antes de abrir otra versión |
| `data/database.db` empaquetado pisa la DB del usuario en una actualización | Alto | En el workflow de re-distribución, **excluir** `data/database.db` del ZIP y sólo enviar código; documentar que el archivo `data/database.db` es del usuario y no debe reemplazarse |
| Cambios de esquema en la DB rompen la instalación del compañero | Alto | Escribir migraciones idempotentes (ya se hace) y ejecutarlas al arrancar en `init_db()`; en cambios mayores, enviar un script de migración aparte y documentarlo |
| El compañero borra `bin/` o el cache de `uv` accidentalmente | Bajo | El script re-baja automáticamente en la próxima corrida |
| Streamlit-calendar (componente JS) no funciona por algún motivo | Bajo (se instala como wheel normal desde PyPI) | Ya viene con sus estáticos empaquetados en el wheel; sin acciones especiales |

## 6. Alternativas explícitamente descartadas

- **stlite / Pyodide**: descartado porque PuLP requiere el solver CBC compilado
  nativamente, y en WASM no puede ejecutarse.
- **Docker Desktop**: descartado por UX del usuario final (requiere instalación
  pesada, licencia, y comandos en terminal).
- **Streamlit Community Cloud**: descartado por el requisito de ejecución local
  con base SQLite propia por usuario.
- **Migración a Marimo / Reflex / Solara**: fuera de alcance; requeriría
  reescribir toda la UI.
