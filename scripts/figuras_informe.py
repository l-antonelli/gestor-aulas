"""Genera las figuras ilustrativas del informe (las que no son diagramas
mermaid ni capturas): grafo bipartito, principio del palomar, ejemplo
del programa lineal, efecto cascada y el caso A6 / A6P.

Uso:
    python -m scripts.figuras_informe

Deja los PNG en project/Informe/figuras/. Todo el texto de las figuras
va en castellano (pautas del informe, CLAUDE.md 8.a).
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.patches import Circle, FancyArrowPatch, FancyBboxPatch, Rectangle  # noqa: E402

RAIZ = Path(__file__).resolve().parent.parent
DESTINO = RAIZ / "project" / "Informe" / "figuras"

plt.rcParams.update({
    "font.family": ["Arial", "Arial Unicode MS"],
    "font.size": 10,
    "axes.spines.top": False,
    "axes.spines.right": False,
})

AZUL, AZUL_CLARO = "#2f5d8a", "#d6e4f0"
NARANJA, NARANJA_CLARO = "#c0612b", "#f6dccb"
VERDE, VERDE_CLARO = "#3c7d4f", "#d5ead9"
GRIS, GRIS_CLARO = "#6b6b6b", "#e6e6e6"
ROJO = "#b23a3a"


def _guardar(fig, nombre: str) -> None:
    DESTINO.mkdir(parents=True, exist_ok=True)
    fig.savefig(DESTINO / nombre, dpi=220, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print("✓", nombre)


def _caja(ax, x, y, w, h, texto, fondo, borde, **kw):
    ax.add_patch(FancyBboxPatch((x - w / 2, y - h / 2), w, h,
                                boxstyle="round,pad=0.02,rounding_size=0.08",
                                facecolor=fondo, edgecolor=borde, linewidth=1.3))
    ax.text(x, y, texto, ha="center", va="center", **kw)


def _flecha(ax, a, b, color=GRIS, **kw):
    ax.add_patch(FancyArrowPatch(a, b, arrowstyle="-|>", mutation_scale=12,
                                 color=color, linewidth=1.3, **kw))


def grafo_bipartito() -> None:
    """Clases y aulas compatibles, con un apareamiento que satura a las clases."""
    clases = ["h₁", "h₂", "h₃", "h₄"]
    aulas = ["a", "b", "c", "d"]
    aristas = [(0, 0), (0, 1), (1, 1), (1, 2), (2, 0), (2, 3), (3, 2), (3, 3)]
    apareamiento = {(0, 1), (1, 2), (2, 0), (3, 3)}
    fig, ax = plt.subplots(figsize=(5.6, 3.4))
    yc = [3, 2, 1, 0]
    for i, j in aristas:
        en = (i, j) in apareamiento
        ax.plot([0, 3], [yc[i], yc[j]], color=AZUL if en else "#b5b5b5",
                linewidth=2.6 if en else 1.1, zorder=1)
    for i, c in enumerate(clases):
        ax.add_patch(Circle((0, yc[i]), 0.27, facecolor=NARANJA_CLARO, edgecolor=NARANJA, lw=1.4, zorder=2))
        ax.text(0, yc[i], c, ha="center", va="center", fontsize=11, zorder=3)
    for j, a in enumerate(aulas):
        ax.add_patch(Circle((3, yc[j]), 0.27, facecolor=AZUL_CLARO, edgecolor=AZUL, lw=1.4, zorder=2))
        ax.text(3, yc[j], a, ha="center", va="center", fontsize=11, zorder=3)
    ax.text(0, 3.75, "X: clases simultáneas", ha="center", fontsize=10, weight="bold")
    ax.text(3, 3.75, "Y: aulas disponibles", ha="center", fontsize=10, weight="bold")
    ax.plot([], [], color="#b5b5b5", lw=1.1, label="arista: el aula es compatible con la clase")
    ax.plot([], [], color=AZUL, lw=2.6, label="apareamiento que satura a X")
    ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.02), frameon=False, ncol=1)
    ax.set_xlim(-0.8, 3.8)
    ax.set_ylim(-0.5, 4.1)
    ax.set_aspect("equal")
    ax.axis("off")
    _guardar(fig, "grafo_bipartito.png")


def palomar() -> None:
    """Cuatro clases simultáneas y tres aulas: una aula debería recibir dos."""
    fig, ax = plt.subplots(figsize=(6.2, 2.9))
    xs_aula = [1, 3, 5]
    for k, x in enumerate(xs_aula):
        ax.add_patch(Rectangle((x - 0.75, 0), 1.5, 1.25, facecolor="white",
                               edgecolor=ROJO if k == 0 else AZUL, linewidth=1.6))
        ax.text(x, -0.3, f"Aula {k + 1}", ha="center", va="center", fontsize=10)
    ubic = [(0.62, 0.62), (1.38, 0.62), (3, 0.62), (5, 0.62)]
    for n, (x, y) in enumerate(ubic):
        ax.add_patch(Circle((x, y), 0.3, facecolor=NARANJA_CLARO if n > 1 else "#f3c9c9",
                                edgecolor=NARANJA if n > 1 else ROJO, lw=1.3))
        ax.text(x, y, f"h{'₁₂₃₄'[n]}", ha="center", va="center", fontsize=10)
    ax.text(1, 1.55, "dos clases en la misma aula\n(prohibido)", ha="center", va="bottom",
            fontsize=9, color=ROJO)
    ax.text(7.1, 0.62, "n = 4 clases\nk = 3 aulas\nn > k ⇒ no hay\nasignación posible",
            ha="left", va="center", fontsize=10)
    ax.set_xlim(-0.1, 9.2)
    ax.set_ylim(-0.6, 2.3)
    ax.axis("off")
    _guardar(fig, "palomar.png")


# Ejemplo del programa lineal (§8.2.6): cuatro horarios del lunes y tres aulas.
EJ_HORARIOS = [
    # (id, materia, tipo, inicio, fin, inscriptos)
    ("h₁", "Análisis Matemático I", "teoría", 8, 10, 70),
    ("h₂", "Física I", "teoría", 9, 11, 35),
    ("h₃", "Física I", "laboratorio", 8, 10, 25),
    ("h₄", "Álgebra y Geometría", "teoría", 10, 12, 45),
]
EJ_SOLUCION = {"h₁": "B", "h₂": "A", "h₃": "L", "h₄": "B"}
EJ_AULAS = [("A", "teórica", 40), ("B", "teórica", 80), ("L", "laboratorio de Física", 30)]


def ejemplo_lp() -> None:
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(6.6, 5.0), gridspec_kw={"hspace": 0.55})
    # (a) Los horarios y los grupos de simultaneidad.
    for x0, x1, rot, color in ((9, 10, "grupo {h₁, h₂, h₃}", GRIS_CLARO), (10, 11, "grupo {h₂, h₄}", "#f1f1f1")):
        ax1.axvspan(x0, x1, color=color, zorder=0)
        ax1.text((x0 + x1) / 2, 3.55, rot, ha="center", va="bottom", fontsize=8.5, color=GRIS)
    ax1.axvline(10, color="#bdbdbd", lw=0.8, ls="--", zorder=0)
    for fila, (hid, mat, tipo, ini, fin, insc) in enumerate(EJ_HORARIOS):
        y = 3 - fila
        lab = tipo == "laboratorio"
        ax1.text(7.9, y, f"{hid} {mat} ({tipo}), {insc} insc.", ha="right", va="center", fontsize=8.5)
        ax1.add_patch(Rectangle((ini, y - 0.32), fin - ini, 0.64,
                                facecolor=VERDE_CLARO if lab else AZUL_CLARO,
                                edgecolor=VERDE if lab else AZUL, lw=1.2))
        ax1.text((ini + fin) / 2, y, hid, ha="center", va="center", fontsize=9)
    ax1.set_yticks([])
    ax1.set_xlim(8, 12.2)
    ax1.set_ylim(-0.6, 4.0)
    ax1.set_xticks([8, 9, 10, 11, 12], ["08:00", "09:00", "10:00", "11:00", "12:00"])
    ax1.spines["left"].set_visible(False)
    ax1.set_title("(a) Horarios del lunes y grupos de simultaneidad", fontsize=10, loc="left")
    # (b) La asignación óptima, por aula.
    for fila, (aid, tipo, cap) in enumerate(EJ_AULAS):
        y = 2 - fila
        ax2.text(7.9, y, f"{aid} ({tipo}, cap. {cap})", ha="right", va="center", fontsize=8.5)
        for hid, mat, tipoh, ini, fin, insc in EJ_HORARIOS:
            if EJ_SOLUCION[hid] != aid:
                continue
            lab = tipoh == "laboratorio"
            ax2.add_patch(Rectangle((ini, y - 0.32), fin - ini, 0.64,
                                    facecolor=VERDE_CLARO if lab else AZUL_CLARO,
                                    edgecolor=VERDE if lab else AZUL, lw=1.2))
            ax2.text((ini + fin) / 2, y, f"{hid}: {insc}/{cap}", ha="center", va="center", fontsize=8.5)
    ax2.set_yticks([])
    ax2.set_xlim(8, 12.2)
    ax2.set_ylim(-0.6, 2.6)
    ax2.set_xticks([8, 9, 10, 11, 12], ["08:00", "09:00", "10:00", "11:00", "12:00"])
    ax2.spines["left"].set_visible(False)
    ax2.set_title("(b) Asignación óptima (inscriptos / capacidad)", fontsize=10, loc="left")
    _guardar(fig, "ejemplo_lp.png")


def efecto_cascada() -> None:
    """Un aula pasa a mantenimiento y el reacomodo se propaga en cadena."""
    fig, ax = plt.subplots(figsize=(6.6, 3.3))
    aulas = ["Aula X (cap. 90)", "Aula Y (cap. 90)", "Aula Z (cap. 60)", "Aula W (cap. 40)"]
    xs = [1, 3, 5, 7]
    for x, a in zip(xs, aulas):
        ax.text(x, 3.05, a, ha="center", weight="bold", fontsize=9)
    ax.text(-0.35, 2.2, "Antes", ha="right", va="center", color=GRIS)
    ax.text(-0.35, 0.5, "Después", ha="right", va="center", color=GRIS)
    antes = ["H₁\n(80 insc.)", "H₂\n(50 insc.)", "H₃\n(30 insc.)", "libre"]
    for x, t in zip(xs, antes):
        libre = t == "libre"
        _caja(ax, x, 2.2, 1.5, 0.8, t, "white" if libre else AZUL_CLARO,
              GRIS if libre else AZUL, fontsize=9, color=GRIS if libre else "black")
    ax.plot([0.3, 1.7], [1.85, 2.55], color=ROJO, lw=2)
    ax.text(1, 2.72, "pasa a mantenimiento", ha="center", fontsize=8.5, color=ROJO)
    despues = ["fuera de uso", "H₁", "H₂", "H₃"]
    for x, t in zip(xs, despues):
        fuera = t == "fuera de uso"
        _caja(ax, x, 0.5, 1.5, 0.8, t, GRIS_CLARO if fuera else NARANJA_CLARO,
              GRIS if fuera else NARANJA, fontsize=9, color=GRIS if fuera else "black")
    for x0, x1, n in ((1, 3, "1"), (3, 5, "2"), (5, 7, "3")):
        _flecha(ax, (x0 + 0.2, 1.75), (x1 - 0.2, 0.95), color=NARANJA)
        ax.text((x0 + x1) / 2 + 0.25, 1.38, n, color=NARANJA, fontsize=9, weight="bold")
    ax.set_xlim(-1.3, 8)
    ax.set_ylim(-0.1, 3.35)
    ax.axis("off")
    _guardar(fig, "efecto_cascada.png")


def a6_vs_a6p() -> None:
    """Cómo cargar una materia con una teoría y tres grupos de laboratorio."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.9), gridspec_kw={"wspace": 0.08})
    for ax in (ax1, ax2):
        ax.set_xlim(0, 6)
        ax.set_ylim(0, 6.2)
        ax.axis("off")
    labs = ["Lab. martes", "Lab. miércoles", "Lab. jueves"]
    # Incorrecto: todo bajo A6, en una sola comisión.
    ax1.text(3, 5.9, "Incorrecto: todo bajo un solo código", ha="center", weight="bold", color=ROJO)
    _caja(ax1, 3, 5.0, 4.4, 0.65, "Materia A6 · Comisión 1", GRIS_CLARO, GRIS, fontsize=9)
    _caja(ax1, 3, 3.9, 4.4, 0.55, "Teoría lunes", AZUL_CLARO, AZUL, fontsize=9)
    for k, t in enumerate(labs):
        _caja(ax1, 3, 3.1 - 0.7 * k, 4.4, 0.55, t, VERDE_CLARO, VERDE, fontsize=9)
    ax1.text(3, 0.45, "El sistema entiende que cada alumno\ncursa los cuatro horarios.",
             ha="center", va="center", fontsize=9, color=ROJO)
    # Correcto: A6 (teoría) y A6P (práctica) con tres comisiones.
    ax2.text(3, 5.9, "Correcto: teoría y práctica separadas", ha="center", weight="bold", color=VERDE)
    _caja(ax2, 3, 5.0, 4.4, 0.65, "Materia A6 · Comisión 1", GRIS_CLARO, GRIS, fontsize=9)
    _caja(ax2, 3, 3.9, 4.4, 0.55, "Teoría lunes", AZUL_CLARO, AZUL, fontsize=9)
    _caja(ax2, 3, 2.95, 4.4, 0.55, "Materia A6P (práctica)", GRIS_CLARO, GRIS, fontsize=9)
    for k, t in enumerate(labs):
        x = 1.05 + 1.95 * k
        _caja(ax2, x, 1.95, 1.75, 0.95, f"Comisión {k + 1}\n{t}", VERDE_CLARO, VERDE, fontsize=8)
    ax2.text(3, 0.45, "Cada alumno cursa la teoría\ny uno solo de los laboratorios.",
             ha="center", va="center", fontsize=9, color=VERDE)
    _guardar(fig, "a6_vs_a6p.png")


def ramificacion_acotacion() -> None:
    """Árbol de ramificación y acotación de un problema de minimización."""
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    nodos = {
        "raiz": (4, 3.3, "Relajación del problema\ncota 12, x₁ = 0,5", AZUL_CLARO, AZUL),
        "x1_0": (1.8, 1.75, "x₁ = 0\nsolución entera 13\nmejor conocida", VERDE_CLARO, VERDE),
        "x1_1": (6.2, 1.75, "x₁ = 1\ncota 12,5, x₂ = 0,4\nse sigue ramificando", AZUL_CLARO, AZUL),
        "x2_0": (4.9, 0.2, "x₂ = 0\nentera 14, peor que 13\nse descarta", "#f3d6d6", ROJO),
        "x2_1": (7.5, 0.2, "x₂ = 1\ncota 15, peor que 13\nse poda", "#f3d6d6", ROJO),
    }
    for a, b in (("raiz", "x1_0"), ("raiz", "x1_1"), ("x1_1", "x2_0"), ("x1_1", "x2_1")):
        xa, ya = nodos[a][:2]
        xb, yb = nodos[b][:2]
        ax.plot([xa, xb], [ya - 0.42, yb + 0.42], color=GRIS, lw=1.2, zorder=1)
    for x, y, texto, fondo, borde in nodos.values():
        _caja(ax, x, y, 2.3, 0.84, texto, fondo, borde, fontsize=8.5)
    ax.text(4, 4.15, "Óptimo: 13 (rama x₁ = 0)", ha="center", fontsize=10, weight="bold", color=VERDE)
    ax.set_xlim(0.3, 9)
    ax.set_ylim(-0.45, 4.45)
    ax.axis("off")
    _guardar(fig, "ramificacion_acotacion.png")


if __name__ == "__main__":
    grafo_bipartito()
    palomar()
    ejemplo_lp()
    efecto_cascada()
    a6_vs_a6p()
    ramificacion_acotacion()
