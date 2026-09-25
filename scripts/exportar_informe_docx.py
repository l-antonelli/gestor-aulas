"""Convierte los .md del informe a .docx listos para importar en Google Docs.

Uso:
    python -m scripts.exportar_informe_docx            # convierte todo el informe
    python -m scripts.exportar_informe_docx cap08      # solo los archivos cuyo nombre contenga "cap08"

Requisitos (ya instalados via Homebrew):
    - pandoc  (fórmulas $$...$$ -> ecuaciones nativas de Word)
    - mmdc    (mermaid-cli; los diagramas se renderizan antes de pasar por pandoc)
      La primera vez hay que instalar el navegador headless que usa mermaid-cli:
      npx -y puppeteer browsers install chrome-headless-shell@150.0.7871.24

Sobre el formato de los diagramas: en el docx se embebe un PNG a escala 3x
(~288 ppp, nítido en zoom e impresión). No se embebe SVG porque ni Google Docs
(descarta el vectorial al importar) ni Word (no renderiza los foreignObject que
usa Mermaid para las etiquetas) lo muestran bien. Igual se archiva el SVG de
cada diagrama en dist/informe_docx/_diagramas/ por si hace falta en otro destino.

Salida: dist/informe_docx/, espejando la estructura de project/Informe/.
Se excluye la carpeta interna _auditoria.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
DIR_INFORME = RAIZ / "project" / "Informe"
DIR_SALIDA = RAIZ / "dist" / "informe_docx"

BLOQUE_MERMAID = re.compile(r"^```mermaid\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

# Límites de los diagramas dentro del documento (una página A4 tiene ~16 cm de
# ancho útil y ~24 cm de alto útil; una imagen más alta que la página se recorta).
# Los diagramas más chicos conservan su tamaño natural para no verse estirados.
ANCHO_MAXIMO_CM = 16.0
ALTO_MAXIMO_CM = 24.0

# Config de mermaid: sin esto los nodos de flowchart envuelven el texto a 200 px
# y los diagramas con descripciones largas quedan angostos y kilométricos.
CONFIG_MERMAID = '{"flowchart": {"wrappingWidth": 450}}'


def _ancho_diagrama(svg: Path) -> str:
    """Devuelve el ancho a usar en el docx.

    Parte del tamaño natural del diagrama y lo reduce proporcionalmente si
    excede el ancho o el alto útiles de una página A4.
    """
    match = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
    if match:
        ancho_cm = float(match.group(1)) / 96 * 2.54
        alto_cm = float(match.group(2)) / 96 * 2.54
        escala = min(1.0, ANCHO_MAXIMO_CM / ancho_cm, ALTO_MAXIMO_CM / alto_cm)
        return f"{ancho_cm * escala:.1f}cm"
    return f"{ANCHO_MAXIMO_CM:.0f}cm"


def _renderizar_mermaid(codigo: str, destino_png: Path, destino_svg: Path) -> bool:
    """Renderiza un bloque mermaid a PNG 3x (para el docx) y SVG (archivo).

    Devuelve False si mmdc falla.
    """
    with tempfile.NamedTemporaryFile("w", suffix=".mmd", delete=False) as f:
        f.write(codigo)
        origen = Path(f.name)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        f.write(CONFIG_MERMAID)
        config = Path(f.name)
    try:
        for destino, extra in ((destino_png, ["-s", "3"]), (destino_svg, [])):
            resultado = subprocess.run(
                ["mmdc", "-i", str(origen), "-o", str(destino), "-b", "white", "-q",
                 "-c", str(config), *extra],
                capture_output=True,
                text=True,
            )
            if resultado.returncode != 0:
                print(f"  ⚠ mmdc falló: {resultado.stderr.strip().splitlines()[-1] if resultado.stderr else '?'}")
                return False
        return destino_png.exists()
    finally:
        origen.unlink(missing_ok=True)
        config.unlink(missing_ok=True)


def _preprocesar(md: Path, dir_diagramas: Path) -> str:
    """Reemplaza los bloques ```mermaid por referencias a imágenes renderizadas."""
    texto = md.read_text(encoding="utf-8")
    contador = 0

    def reemplazo(match: re.Match) -> str:
        nonlocal contador
        contador += 1
        base = dir_diagramas / f"{md.stem}_diagrama_{contador}"
        png = base.with_suffix(".png")
        svg = base.with_suffix(".svg")
        if _renderizar_mermaid(match.group(1), png, svg):
            return f"![]({png}){{width={_ancho_diagrama(svg)}}}"
        # Si el render falla, se deja el código como bloque literal para no perder contenido.
        return f"```\n{match.group(1)}```"

    return BLOQUE_MERMAID.sub(reemplazo, texto)


def convertir(md: Path, dir_diagramas: Path) -> bool:
    relativo = md.relative_to(DIR_INFORME)
    destino = DIR_SALIDA / relativo.with_suffix(".docx")
    destino.parent.mkdir(parents=True, exist_ok=True)

    contenido = _preprocesar(md, dir_diagramas)

    resultado = subprocess.run(
        [
            "pandoc",
            "--from", "markdown+tex_math_dollars",
            "--to", "docx",
            "--resource-path", str(md.parent),
            "-o", str(destino),
        ],
        input=contenido,
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"✗ {relativo}: {resultado.stderr.strip()}")
        return False
    print(f"✓ {relativo} -> {destino.relative_to(RAIZ)}")
    return True


def main() -> int:
    filtro = sys.argv[1] if len(sys.argv) > 1 else ""
    archivos = sorted(
        p for p in DIR_INFORME.rglob("*.md")
        if "_auditoria" not in p.parts and filtro in p.name
    )
    if not archivos:
        print(f"No se encontraron .md que contengan '{filtro}' en {DIR_INFORME}")
        return 1

    dir_diagramas = DIR_SALIDA / "_diagramas"
    dir_diagramas.mkdir(parents=True, exist_ok=True)

    fallos = sum(0 if convertir(md, dir_diagramas) else 1 for md in archivos)
    print(f"\n{len(archivos) - fallos}/{len(archivos)} archivos convertidos en {DIR_SALIDA.relative_to(RAIZ)}/")
    return 1 if fallos else 0


if __name__ == "__main__":
    raise SystemExit(main())
