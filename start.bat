@echo off
REM Lanzador para Windows del Sistema de Gestion de Aulas.
REM
REM Doble click arranca la aplicacion en el navegador. La primera corrida
REM descarga Python 3.11 y las dependencias (~200 MB, ~1 minuto). Corridas
REM siguientes son casi instantaneas.

setlocal enabledelayedexpansion
cd /d "%~dp0"

set "UV_BIN=%~dp0bin\uv.exe"

if not exist "%UV_BIN%" (
    echo No encuentro el binario de uv en:
    echo   %UV_BIN%
    echo.
    echo Verifica que el ZIP se haya descomprimido completo, con la carpeta bin\ adentro.
    pause
    exit /b 1
)

echo ===================================================================
echo   Sistema de Gestion de Aulas
echo ===================================================================
echo.
echo Preparando el entorno (la primera vez tarda ~1 minuto)...
echo.

"%UV_BIN%" sync --frozen
if errorlevel 1 goto error

echo.
echo Iniciando la aplicacion...
echo La app se va a abrir en el navegador en http://localhost:8501
echo.
echo Para cerrar la aplicacion, cerra esta ventana de terminal.
echo ===================================================================
echo.

REM Forzar que la raiz del proyecto este en sys.path, asi los imports
REM "from src.database.connection import ..." de app/main.py funcionan
REM independientemente del contexto de arranque.
set "PYTHONPATH=%~dp0;%PYTHONPATH%"

"%UV_BIN%" run streamlit run app/main.py ^
    --server.headless=false ^
    --server.address=localhost ^
    --server.port=8501 ^
    --browser.gatherUsageStats=false
goto end

:error
echo.
echo Hubo un problema al preparar la aplicacion.
echo Copiar el mensaje de error de arriba y contactar al soporte.
pause
exit /b 1

:end
endlocal
