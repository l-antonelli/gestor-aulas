"""Reemplaza las páginas iniciales del informe (carátula, dedicatoria y
advertencia) por las de otro .docx, por ejemplo la pestaña "Informe" del
borrador en Google Docs exportada como .docx, que tiene la carátula con
los logos armada a mano.

Del .docx de portada se toma todo lo anterior al título "ÍNDICE"; del
informe (scripts/exportar_informe_docx.py --informe) se descarta lo
anterior al salto de sección que cierra las páginas sin numerar, y se
conserva ese salto (sin cabecera ni pie) y todo lo que sigue.

Uso (docxcompose no es dependencia del proyecto):
    uv run --with docxcompose python scripts/componer_informe.py \\
        PORTADA.docx dist/informe_docx/Informe.docx SALIDA.docx
"""

import sys

from docx import Document
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docxcompose.composer import Composer


def _texto(el) -> str:
    return "".join(t.text or "" for t in el.iter(qn("w:t"))).strip()


def _vacio(el) -> bool:
    return (el.tag == qn("w:p") and not _texto(el)
            and el.find(".//" + qn("w:drawing")) is None)


def _normalizar_portada(cuerpo) -> None:
    """La portada del borrador diagrama con párrafos vacíos (pensados para
    tamaño Carta). En A4 eso empuja la fila de logos a la página 2 y deja
    la dedicatoria y la advertencia sin saltos reales. Se deja un solo
    párrafo vacío seguido en la carátula (ninguno antes de la tabla de logos), se sacan los rellenos antes de
    DEDICATORIA y ADVERTENCIA, y ambas empiezan en página nueva."""
    els = list(cuerpo)
    for i, el in enumerate(els):
        if el.tag == qn("w:tbl"):
            j = i - 1
            vacios = []
            while j >= 0 and _vacio(els[j]):
                vacios.append(els[j]); j -= 1
            for v in vacios:
                cuerpo.remove(v)
    # En la carátula, a lo sumo dos párrafos vacíos seguidos.
    racha = 0
    for el in list(cuerpo):
        if _texto(el).upper() == "DEDICATORIA":
            break
        if _vacio(el):
            racha += 1
            if racha > 2:
                cuerpo.remove(el)
        else:
            racha = 0
    els = list(cuerpo)
    for i, el in enumerate(els):
        if _texto(el).upper() in ("DEDICATORIA", "ADVERTENCIA"):
            j = i - 1
            while j >= 0 and _vacio(els[j]):
                cuerpo.remove(els[j]); j -= 1
            ppr = el.find(qn("w:pPr"))
            if ppr is None:
                ppr = OxmlElement("w:pPr"); el.insert(0, ppr)
            ppr.insert(0, OxmlElement("w:pageBreakBefore"))


def main(portada_path: str, informe_path: str, salida: str) -> None:
    portada = Document(portada_path)
    cuerpo = portada.element.body
    elementos = list(cuerpo)
    corte = next(i for i, el in enumerate(elementos) if _texto(el).upper() == "ÍNDICE")
    for el in elementos[corte:]:
        if el.tag != qn("w:sectPr"):
            cuerpo.remove(el)
    _normalizar_portada(cuerpo)

    informe = Document(informe_path)
    cuerpo_inf = informe.element.body
    elementos = list(cuerpo_inf)
    fin_portada = next(i for i, el in enumerate(elementos)
                       if el.find(".//" + qn("w:sectPr")) is not None and el.tag == qn("w:p"))
    for el in elementos[:fin_portada]:
        cuerpo_inf.remove(el)

    composer = Composer(informe)
    composer.insert(0, portada)
    composer.save(salida)
    print(f"✓ {salida}: portada de {portada_path} ({corte} bloques) + informe")


if __name__ == "__main__":
    main(*sys.argv[1:4])
