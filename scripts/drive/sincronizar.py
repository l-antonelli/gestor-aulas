"""Trae al repo las ediciones hechas a mano en el Google Doc del informe.

El Doc se compara, como texto plano, con el texto de la última
publicación. Cada edición (palabras reemplazadas, agregadas o borradas
dentro de un párrafo) se busca en los fuentes .md con algunas palabras
de contexto, tolerando los saltos de línea del fuente y las marcas de
formato alrededor de las palabras. Se aplica sólo si el fragmento
aparece una única vez y la parte editada no tiene formato adentro; el
resto se devuelve como pendiente para pasarlo a mano.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

CONTEXTO = 5          # palabras de contexto a cada lado
MARCAS = r"[*_`]*"    # negrita, cursiva y código alrededor de una palabra


@dataclass
class Edicion:
    antes: str
    despues: str
    izq: str = ""
    der: str = ""
    parrafo_nuevo: bool = False
    parrafo: int = -1  # índice del párrafo en el Doc: agrupa las ediciones que se aplican juntas

    def __str__(self) -> str:
        return f"«…{self.izq} [{self.antes} → {self.despues}] {self.der}…»"


def ediciones(viejo: str, nuevo: str) -> list[Edicion]:
    """Ediciones entre dos versiones del texto plano del Doc (un párrafo
    por línea)."""
    a, b = viejo.split("\n"), nuevo.split("\n")
    resultado: list[Edicion] = []
    lineas = difflib.SequenceMatcher(None, a, b, autojunk=False)
    for op, i1, i2, j1, j2 in lineas.get_opcodes():
        if op == "equal":
            continue
        if op == "replace" and i2 - i1 == j2 - j1:
            for k, (x, y) in enumerate(zip(a[i1:i2], b[j1:j2])):
                for e in _ediciones_de_parrafo(x, y):
                    e.parrafo = i1 + k
                    resultado.append(e)
        elif op == "insert":
            resultado += [Edicion(antes="", despues=l, izq=a[i1 - 1] if i1 else "", parrafo_nuevo=True)
                          for l in b[j1:j2]]
        else:
            resultado.append(Edicion(antes="\n".join(a[i1:i2]), despues="\n".join(b[j1:j2]), parrafo_nuevo=True))
    return resultado


def _ediciones_de_parrafo(x: str, y: str) -> list[Edicion]:
    px, py = x.split(), y.split()
    sm = difflib.SequenceMatcher(None, px, py, autojunk=False)
    # Las ediciones separadas por menos palabras que el contexto se
    # juntan en una sola: si no, el contexto de una incluye palabras que
    # la otra cambia y no se pueden ubicar las dos.
    ops: list[list[int]] = []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        if ops and i1 - ops[-1][1] < CONTEXTO:
            ops[-1][1], ops[-1][3] = i2, j2
        else:
            ops.append([i1, i2, j1, j2])
    out = []
    for i1, i2, j1, j2 in ops:
        out.append(Edicion(
            antes=" ".join(px[i1:i2]), despues=" ".join(py[j1:j2]),
            izq=" ".join(px[max(0, i1 - CONTEXTO):i1]), der=" ".join(px[i2:i2 + CONTEXTO]),
        ))
    return out


def _patron(palabras: list[str]) -> str:
    return r"\s+".join(MARCAS + re.escape(p) + MARCAS for p in palabras)


def _patron_interno(palabras: list[str]) -> str:
    """Como _patron, pero sin absorber las marcas de los bordes: las que
    rodean al fragmento editado quedan del lado del contexto."""
    return (MARCAS + r"\s+" + MARCAS).join(re.escape(p) for p in palabras)


def aplicar(e: Edicion, fuentes: dict[str, str]) -> tuple[str, str] | None:
    """(archivo, texto nuevo) si la edición se pudo ubicar sin ambigüedad
    en los fuentes; None si no."""
    if e.parrafo_nuevo:
        return None
    izq, antes, der = e.izq.split(), e.antes.split(), e.der.split()
    if not (izq or der):
        return None
    partes = []
    if izq:
        partes.append(f"(?P<izq>{_patron(izq)})")
    if antes:
        sep_izq = r"(?P<s1>\s+)" if izq else ""
        partes.append(f"{sep_izq}{MARCAS}(?P<antes>{_patron_interno(antes)}){MARCAS}")
    if der:
        partes.append(r"(?P<s2>\s+)" + f"(?P<der>{_patron(der)})")
    patron = re.compile("".join(partes))
    hallazgos = [(f, m) for f, t in fuentes.items() for m in patron.finditer(t)]
    if len(hallazgos) != 1:
        return None
    archivo, m = hallazgos[0]
    texto = fuentes[archivo]
    if antes and re.search(r"[*_`]", m.group("antes")):
        return None  # la parte editada tiene formato: a mano
    if antes:
        ini, fin = m.start("antes"), m.end("antes")
        if not e.despues:
            # Borrado: se va también el espacio que lo separaba de la izquierda
            # (o de la derecha, si está al principio del párrafo).
            if izq:
                ini = m.start("s1")
            elif der:
                fin = m.start("der")
        nuevo = texto[:ini] + e.despues + texto[fin:]
    else:
        # Inserción entre izq y der.
        pos = m.end("izq") if izq else m.start("der")
        nuevo = texto[:pos] + " " + e.despues + texto[pos:] if izq else texto[:pos] + e.despues + " " + texto[pos:]
    return archivo, nuevo


def aplicar_todas(eds: list[Edicion], fuentes: dict[str, str]) -> tuple[dict[str, str], list[Edicion]]:
    """Aplica las ediciones en orden sobre una copia de los fuentes.
    Devuelve los fuentes modificados (sólo los que cambiaron) y las
    ediciones pendientes."""
    actuales = dict(fuentes)
    cambiados: set[str] = set()
    pendientes = []
    # Las ediciones de un mismo párrafo se aplican todas o ninguna, para
    # no dejar un párrafo a medio cambiar.
    grupos: list[list[Edicion]] = []
    for e in eds:
        if grupos and e.parrafo >= 0 and grupos[-1][0].parrafo == e.parrafo:
            grupos[-1].append(e)
        else:
            grupos.append([e])
    for grupo in grupos:
        tentativo = dict(actuales)
        tocados = set()
        for e in grupo:
            r = aplicar(e, tentativo)
            if r is None:
                break
            archivo, texto = r
            tentativo[archivo] = texto
            tocados.add(archivo)
        else:
            actuales = tentativo
            cambiados |= tocados
            continue
        pendientes.extend(grupo)
    return {f: actuales[f] for f in cambiados}, pendientes
