#!/usr/bin/env bash
# Lanzador para macOS del Sistema de Gestión de Aulas.
#
# Doble click en Finder arranca la aplicación en el navegador. La primera
# corrida descarga Python 3.11 y las dependencias (~200 MB, ~1 minuto).
# Corridas siguientes son casi instantáneas.

set -euo pipefail

# Directorio del script (funciona con doble click desde Finder).
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

# Detectar arquitectura y elegir el binario correcto de uv.
ARCH="$(uname -m)"
case "$ARCH" in
    arm64)
        UV_BIN="$DIR/bin/uv-macos-arm64"
        ;;
    x86_64)
        UV_BIN="$DIR/bin/uv-macos-x86_64"
        ;;
    *)
        echo "Arquitectura desconocida: $ARCH"
        echo "Este lanzador soporta Apple Silicon (arm64) e Intel (x86_64)."
        read -n 1 -s -r -p "Presioná cualquier tecla para cerrar..."
        exit 1
        ;;
esac

if [[ ! -x "$UV_BIN" ]]; then
    echo "No encuentro el binario de uv en:"
    echo "  $UV_BIN"
    echo ""
    echo "Verificá que el ZIP se haya descomprimido completo, con la carpeta bin/ adentro."
    read -n 1 -s -r -p "Presioná cualquier tecla para cerrar..."
    exit 1
fi

echo "==================================================================="
echo "  Sistema de Gestión de Aulas"
echo "==================================================================="
echo ""
echo "Preparando el entorno (la primera vez tarda ~1 minuto)..."
echo ""

# Primera corrida: uv baja Python 3.11 y las dependencias.
# Corridas siguientes: no-op, casi instantáneo.
"$UV_BIN" sync --frozen

echo ""
echo "Iniciando la aplicación..."
echo "La app se va a abrir en el navegador en http://localhost:8501"
echo ""
echo "Para cerrar la aplicación, cerrá esta ventana de terminal."
echo "==================================================================="
echo ""

# Forzar que la raíz del proyecto esté en sys.path, así los imports
# `from src.database.connection import ...` de app/main.py funcionan
# independientemente del contexto de arranque.
export PYTHONPATH="$DIR${PYTHONPATH:+:$PYTHONPATH}"

"$UV_BIN" run streamlit run app/main.py \
    --server.headless=false \
    --server.address=localhost \
    --server.port=8501 \
    --browser.gatherUsageStats=false
