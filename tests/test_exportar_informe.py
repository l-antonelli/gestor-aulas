"""Tests del armado del informe (scripts/exportar_informe_docx.py y el
filtro scripts/informe_apa.lua): la nota de cada figura y el epígrafe de
los fragmentos de código."""

import subprocess

from scripts.exportar_informe_docx import FILTRO_INFORME, PANDOC, _atributos_figura


def _texto(md: str) -> str:
    salida = subprocess.run(
        [PANDOC, "--from", "markdown", "--to", "plain", "--lua-filter", str(FILTRO_INFORME)],
        input=md, text=True, capture_output=True, check=True)
    return " ".join(salida.stdout.split())


def test_la_figura_lleva_la_nota_que_declara():
    texto = _texto('![Proceso](x.png){#fig:p nota="Diagrama de elaboración propia."}\n')
    assert "Nota: Diagrama de elaboración propia." in texto


def test_la_figura_sin_nota_declarada_lleva_la_nota_por_defecto():
    assert "Nota: Elaboración propia." in _texto("![Proceso](x.png){#fig:p}\n")


def test_nota_vacia_quiere_decir_sin_nota():
    assert "Nota" not in _texto('![Proceso](x.png){#fig:p nota=""}\n')


def test_el_fragmento_de_codigo_remite_al_repositorio():
    texto = _texto('```{fuente="src/x.py"}\nprint(1)\n```\n')
    assert "Fragmento de src/x.py (ver Anexo B)" in texto


def test_el_titulo_de_un_diagrama_puede_declarar_la_nota():
    titulo, atributos = _atributos_figura('Proceso actual {#fig:proceso nota="Diagrama de elaboración propia."}')
    assert titulo == "Proceso actual"
    assert atributos == '#fig:proceso nota="Diagrama de elaboración propia."'
