"""Busca en el PDF del informe la página de cada título del índice.

Uso (pymupdf no es dependencia del proyecto):
    uv run --with pymupdf python scripts/paginas_indice.py INFORME.pdf

Lee dist/informe_docx/titulos_indice.json (lo deja la primera pasada de
`exportar_informe_docx.py --informe`) y escribe paginas_indice.json con
título → página. Los títulos se buscan en orden, cada uno a partir de
la página del anterior, saltando las páginas del propio índice.
"""

import json
import re
import sys
from pathlib import Path

import pymupdf

DIR = Path(__file__).resolve().parent.parent / "dist" / "informe_docx"


def _norm(t: str) -> str:
    t = t.replace("\u200b", "").replace("“", '"').replace("”", '"').replace("’", "'")
    return re.sub(r"\s+", " ", t).strip()


def main() -> int:
    titulos = json.loads((DIR / "titulos_indice.json").read_text())
    paginas_pdf = [_norm(p.get_text()) for p in pymupdf.open(sys.argv[1])]
    # Primera página del cuerpo: la que tiene el primer título y no el
    # segundo (cada parte de primer nivel empieza en una página nueva; el
    # índice, en cambio, los tiene a los dos).
    primero, segundo = _norm(titulos[0][1]), _norm(titulos[1][1])
    desde = next(i for i, t in enumerate(paginas_pdf) if primero in t and segundo not in t)
    resultado, faltan = {}, []
    for _nivel, titulo in titulos:
        buscado = _norm(titulo)
        pagina = next((i for i in range(desde, len(paginas_pdf)) if buscado in paginas_pdf[i]), None)
        if pagina is None:
            faltan.append(titulo)
            continue
        resultado[titulo] = pagina + 1
        desde = pagina
    (DIR / "paginas_indice.json").write_text(json.dumps(resultado, ensure_ascii=False, indent=1))
    print(f"✓ {len(resultado)} títulos con página" + (f"; sin encontrar: {faltan}" if faltan else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
