#!/usr/bin/env bash
# Arma el ZIP portable para distribuir a usuarios no técnicos.
#
# Descarga los binarios portables de `uv` para macOS (arm64 + x86_64) y
# Windows (x86_64), copia el código del repo a dist/gestor-aulas/, deja los
# binarios en dist/gestor-aulas/bin/ y empaqueta todo en un único ZIP listo
# para subir como asset de la release en GitHub.
#
# El usuario final descarga ese ZIP, lo descomprime, hace doble click a
# start.command (macOS) o start.bat (Windows) y listo — no necesita tener
# Python ni saber usar la terminal.
#
# Uso:
#   scripts/build_portable_zip.sh [version]
#
# Si no se pasa versión, la lee de pyproject.toml. Requiere curl y unzip.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

# Versión del release del proyecto (nombre del ZIP).
if [[ $# -ge 1 ]]; then
    VERSION="$1"
else
    VERSION="$(grep '^version' pyproject.toml | head -1 | cut -d'"' -f2)"
fi

# Versión de uv a bajar. Se puede sobreescribir con la env UV_VERSION.
UV_VERSION="${UV_VERSION:-0.12.15}"

DIST="$REPO_ROOT/dist"
STAGE="$DIST/gestor-aulas"
CACHE="$DIST/uv-cache"

echo "==================================================================="
echo "  Build ZIP portable de gestor-aulas v$VERSION"
echo "  (uv $UV_VERSION)"
echo "==================================================================="

rm -rf "$STAGE"
mkdir -p "$STAGE"
mkdir -p "$CACHE"

# ------------------------------------------------------------------
# 1. Bajar los binarios portables de uv
# ------------------------------------------------------------------

download_uv() {
    local triple="$1"      # p. ej. aarch64-apple-darwin
    local ext="$2"         # tar.gz o zip
    local dest_name="$3"   # nombre final dentro de bin/

    local asset="uv-${triple}.${ext}"
    local url="https://github.com/astral-sh/uv/releases/download/${UV_VERSION}/${asset}"
    local cache_file="$CACHE/$asset"

    if [[ ! -f "$cache_file" ]]; then
        echo "Bajando $asset..."
        curl --fail --location --output "$cache_file" "$url"
    else
        echo "Usando cache: $asset"
    fi

    local tmp_dir
    tmp_dir="$(mktemp -d)"
    if [[ "$ext" == "tar.gz" ]]; then
        tar -xzf "$cache_file" -C "$tmp_dir"
    else
        unzip -q "$cache_file" -d "$tmp_dir"
    fi

    # tar.gz de uv trae subcarpeta uv-<triple>/, zip trae los binarios sueltos.
    local src_dir
    if [[ -d "$tmp_dir/uv-${triple}" ]]; then
        src_dir="$tmp_dir/uv-${triple}"
    else
        src_dir="$tmp_dir"
    fi

    if [[ "$ext" == "zip" ]]; then
        cp "$src_dir/uv.exe" "$STAGE/bin/$dest_name"
    else
        cp "$src_dir/uv" "$STAGE/bin/$dest_name"
        chmod +x "$STAGE/bin/$dest_name"
    fi

    rm -rf "$tmp_dir"
}

mkdir -p "$STAGE/bin"

download_uv "aarch64-apple-darwin"      "tar.gz" "uv-macos-arm64"
download_uv "x86_64-apple-darwin"       "tar.gz" "uv-macos-x86_64"
download_uv "x86_64-pc-windows-msvc"    "zip"    "uv.exe"

# ------------------------------------------------------------------
# 2. Copiar el código del repo al staging
# ------------------------------------------------------------------

echo ""
echo "Copiando código del repo..."

rsync -a \
    --exclude='.git/' \
    --exclude='.github/' \
    --exclude='.venv/' \
    --exclude='__pycache__/' \
    --exclude='*.pyc' \
    --exclude='.pytest_cache/' \
    --exclude='.mypy_cache/' \
    --exclude='.ruff_cache/' \
    --exclude='.hypothesis/' \
    --exclude='dist/' \
    --exclude='node_modules/' \
    --exclude='.claude/' \
    --exclude='.cursor/' \
    --exclude='.vscode/' \
    --exclude='.streamlit/' \
    --exclude='.envrc' \
    --exclude='.env' \
    --exclude='.DS_Store' \
    --exclude='.gitignore' \
    --exclude='tests/' \
    --exclude='pytest.ini' \
    --exclude='CLAUDE.md' \
    --exclude='TODO.md' \
    --exclude='run.py' \
    --exclude='requirements.txt' \
    --exclude='requirements-proj.txt' \
    --exclude='migrate_*.py' \
    --exclude='project/Informe/bibliografia/' \
    --exclude='project/Informe/pautas informe/' \
    --exclude='project/Informe/borradores/' \
    --exclude='data/*.backup*' \
    --exclude='data/database.db.backup-*' \
    "$REPO_ROOT/" "$STAGE/"

# ------------------------------------------------------------------
# 3. Empaquetar ZIP
# ------------------------------------------------------------------

ZIP_NAME="gestor-aulas-v${VERSION}-portable.zip"
ZIP_PATH="$DIST/$ZIP_NAME"

echo ""
echo "Empaquetando $ZIP_NAME..."

rm -f "$ZIP_PATH"
cd "$DIST"
zip -qr "$ZIP_NAME" gestor-aulas/
cd "$REPO_ROOT"

# Tamaño humano del ZIP.
SIZE="$(du -h "$ZIP_PATH" | cut -f1)"

echo ""
echo "==================================================================="
echo "  ZIP portable listo:"
echo "  $ZIP_PATH   ($SIZE)"
echo ""
echo "  Subir como asset de la release con:"
echo "    gh release upload v${VERSION} $ZIP_PATH"
echo "==================================================================="
