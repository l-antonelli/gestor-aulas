"""Genera las figuras ilustrativas del informe (las que no son diagramas
mermaid ni capturas): grafo bipartito, principio del palomar, ejemplo
del programa lineal, efecto cascada, el caso A6 / A6P y el proceso
actual en notación BPMN.

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


DIAS_CASO = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]


def _datos_caso() -> dict:
    import json
    return json.loads((DESTINO / "datos" / "caso_1C2026.json").read_text())


def ocupacion_caso() -> None:
    """Porcentaje de asientos teóricos ocupados por sede, franja a franja,
    en el plan del 1C 2026."""
    d = _datos_caso()
    totales = d["asientos_por_sede"]
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    for sede, color in (("Pellegrini", AZUL), ("Siberia", NARANJA)):
        libres = d["real"]["franjas"][sede]
        ocup = [100 * (1 - x / totales[sede]) for x in libres]
        ax.plot(range(len(ocup)), ocup, color=color, lw=1.4, label=sede)
    _ejes_semana(ax, len(d["real"]["franjas"]["Total"]))
    ax.set_ylabel("Asientos ocupados (%)")
    ax.set_ylim(0, 100)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    _guardar(fig, "caso_ocupacion.png")


def asientos_libres_caso() -> None:
    """Asientos en aulas libres por franja: configuración recomendada
    contra la que no castiga la subocupación."""
    d = _datos_caso()
    fig, ax = plt.subplots(figsize=(7.4, 3.0))
    for clave, etiqueta, color in (("recomendada", "Configuración recomendada", VERDE),
                                   ("sin_sub", "Sin castigo de subocupación", ROJO)):
        ax.plot(range(len(d[clave]["franjas"]["Total"])), d[clave]["franjas"]["Total"],
                color=color, lw=1.3, label=etiqueta)
    _ejes_semana(ax, len(d["real"]["franjas"]["Total"]))
    ax.set_ylabel("Asientos en aulas libres")
    # Eje ajustado al rango de los datos (sin el cero) para que se vea
    # la diferencia entre las dos curvas.
    valores = d["recomendada"]["franjas"]["Total"] + d["sin_sub"]["franjas"]["Total"]
    margen = (max(valores) - min(valores)) * 0.05
    ax.set_ylim(min(valores) - margen, max(valores) + margen)
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=2)
    _guardar(fig, "caso_asientos_libres.png")


def _ejes_semana(ax, n: int) -> None:
    por_dia = n // len(DIAS_CASO)
    for i in range(1, len(DIAS_CASO)):
        ax.axvline(i * por_dia, color="#cccccc", lw=0.8)
    ax.set_xticks([i * por_dia + por_dia / 2 for i in range(len(DIAS_CASO))], DIAS_CASO)
    ax.tick_params(axis="x", length=0)
    ax.set_xlim(0, n)


# ---------------------------------------------------------------------------
# Proceso actual (BPMN 2.0)
# ---------------------------------------------------------------------------
# Carriles verticales (uno por área) y el flujo de arriba hacia abajo.
# Convenciones BPMN: evento de inicio (círculo fino), intermedio (doble
# círculo), de fin (círculo grueso); tareas en rectángulos redondeados;
# compuertas en rombo (X exclusiva, + paralela); flujo de secuencia en
# línea continua sólo dentro del pool; flujo de mensaje entre pools en
# línea de trazos con círculo en el origen y punta hueca; asociación a una
# anotación en línea de puntos. Los recorridos son ortogonales y ninguno
# atraviesa una figura.

_CARRILES = ["Direcciones\nde Escuelas", "Área de\nIngreso", "Secretaría\nAcadémica",
             "Secretaría\nTécnica", "Secretaría\nEstudiantil"]
_ANCHO_CARRIL, _PASO = 3.0, 1.32
_W, _H, _G, _R = 2.6, 1.0, 0.32, 0.24  # tarea (ancho, alto), compuerta (semidiagonal), evento (radio)


def _cx(carril: int) -> float:
    return carril * _ANCHO_CARRIL + _ANCHO_CARRIL / 2


def _cy(paso: float) -> float:
    return -paso * _PASO


def _bpmn_tarea(ax, carril, paso, texto):
    x, y = _cx(carril), _cy(paso)
    ax.add_patch(FancyBboxPatch((x - _W / 2, y - _H / 2), _W, _H,
                                boxstyle="round,pad=0,rounding_size=0.12",
                                facecolor=AZUL_CLARO, edgecolor=AZUL, linewidth=1.1, zorder=3))
    ax.text(x, y, texto, ha="center", va="center", fontsize=6.5, zorder=4, linespacing=1.1)


def _bpmn_compuerta(ax, carril, paso, tipo, rotulo=None):
    """Rótulo a la izquierda del rombo."""
    from matplotlib.patches import Polygon
    x, y = _cx(carril), _cy(paso)
    ax.add_patch(Polygon([(x, y + _G), (x + _G, y), (x, y - _G), (x - _G, y)], closed=True,
                         facecolor="#fff6d6", edgecolor="#a57f00", linewidth=1.1, zorder=3))
    d = _G * 0.42
    if tipo == "X":
        ax.plot([x - d, x + d], [y - d, y + d], color="#a57f00", lw=1.6, zorder=4)
        ax.plot([x - d, x + d], [y + d, y - d], color="#a57f00", lw=1.6, zorder=4)
    else:
        ax.plot([x - d * 1.25, x + d * 1.25], [y, y], color="#a57f00", lw=1.8, zorder=4)
        ax.plot([x, x], [y - d * 1.25, y + d * 1.25], color="#a57f00", lw=1.8, zorder=4)
    if rotulo:
        ax.text(x - _G - 0.1, y, rotulo, ha="right", va="center", fontsize=6.6, style="italic", zorder=4)


def _bpmn_evento(ax, carril, paso, clase, rotulo, lado="izquierda"):
    x, y = _cx(carril), _cy(paso)
    ancho = {"inicio": 1.1, "fin": 2.6, "intermedio": 1.0}[clase]
    ax.add_patch(Circle((x, y), _R, facecolor="white", edgecolor=VERDE if clase != "fin" else ROJO,
                        linewidth=ancho, zorder=3))
    if clase == "intermedio":
        ax.add_patch(Circle((x, y), _R * 0.80, facecolor="white", edgecolor=VERDE, linewidth=1.0, zorder=4))
        ax.add_patch(Circle((x, y), _R * 0.52, facecolor="white", edgecolor=GRIS, linewidth=0.8, zorder=5))
        ax.plot([x, x], [y, y + _R * 0.42], color=GRIS, lw=0.8, zorder=6)  # reloj: evento temporizado
        ax.plot([x, x + _R * 0.32], [y, y], color=GRIS, lw=0.8, zorder=6)
    if lado == "izquierda":
        ax.text(x - _R - 0.1, y, rotulo, ha="right", va="center", fontsize=6.8, zorder=4)
    else:
        ax.text(x + _R + 0.1, y, rotulo, ha="left", va="center", fontsize=6.8, zorder=4)


def _bpmn_secuencia(ax, puntos, rotulo=None, pos_rotulo=None, alinear="left"):
    xs, ys = zip(*puntos)
    ax.plot(xs[:-1] + (xs[-1],), ys, color="#333333", lw=0.9, zorder=2, solid_joinstyle="miter")
    ax.add_patch(FancyArrowPatch(puntos[-2], puntos[-1], arrowstyle="-|>", mutation_scale=8,
                                 color="#333333", linewidth=0.9, shrinkA=0, shrinkB=0, zorder=2))
    if rotulo:
        ax.text(*pos_rotulo, rotulo, fontsize=6.4, ha=alinear, va="center", style="italic", zorder=4,
                bbox=dict(facecolor="white", edgecolor="none", pad=0.6))


def _bpmn_mensaje(ax, puntos, rotulo, pos_rotulo):
    xs, ys = zip(*puntos)
    ax.plot(xs, ys, color="#333333", lw=0.9, ls=(0, (4, 3)), zorder=2)
    ax.add_patch(Circle(puntos[0], 0.06, facecolor="white", edgecolor="#333333", lw=0.9, zorder=3))
    ax.add_patch(FancyArrowPatch(puntos[-2], puntos[-1], arrowstyle="-|>,head_width=0.25,head_length=0.45",
                                 mutation_scale=9, facecolor="white", edgecolor="#333333",
                                 linewidth=0.9, shrinkA=0, shrinkB=0, zorder=3))
    ax.text(*pos_rotulo, rotulo, fontsize=6.4, ha="center", va="center", zorder=4,
            bbox=dict(facecolor="white", edgecolor="none", pad=0.6))


def _bpmn_almacen(ax, x, y, texto):
    """Almacén de datos (cilindro): un sistema de información."""
    from matplotlib.patches import Ellipse
    w, h, e = 1.2, 0.7, 0.18
    ax.add_patch(Rectangle((x - w / 2, y - h / 2), w, h, facecolor="white", edgecolor="#333333", lw=1.0, zorder=3))
    ax.add_patch(Ellipse((x, y - h / 2), w, e, facecolor="white", edgecolor="#333333", lw=1.0, zorder=3))
    ax.add_patch(Rectangle((x - w / 2 + 0.01, y - h / 2), w - 0.02, 0.02, facecolor="white", edgecolor="none", zorder=3))
    ax.add_patch(Ellipse((x, y + h / 2), w, e, facecolor="white", edgecolor="#333333", lw=1.0, zorder=4))
    ax.text(x, y - 0.06, texto, ha="center", va="center", fontsize=6.2, zorder=5, linespacing=1.0)


def _bpmn_anotacion(ax, x, y, texto, alto=0.8):
    ax.plot([x + 0.12, x, x, x + 0.12], [y + alto / 2, y + alto / 2, y - alto / 2, y - alto / 2],
            color="#333333", lw=0.9)
    ax.text(x + 0.1, y, texto, fontsize=6.5, ha="left", va="center")


def _bpmn_leyenda(ax, x0, y0, ancho):
    """Leyenda de la notación BPMN, en tres filas debajo del diagrama."""
    from matplotlib.patches import Ellipse, Polygon
    ax.add_patch(FancyBboxPatch((x0 - 0.1, y0 - 2.35), ancho - x0, 2.65, boxstyle="round,pad=0,rounding_size=0.1",
                                facecolor="white", edgecolor="#bbbbbb", lw=0.8))
    ax.text(x0 + 0.05, y0, "Notación BPMN", fontsize=7.5, weight="bold", va="center")
    f1, f2, f3 = y0 - 0.55, y0 - 1.2, y0 - 1.85
    col = (ancho - x0) / 5
    for i, (clase, texto) in enumerate([("inicio", "Inicio del proceso"), ("intermedio", "Momento\ndel calendario"),
                                        ("fin", "Fin del proceso")]):
        x = x0 + 0.3 + i * col
        ax.add_patch(Circle((x, f1), 0.17, facecolor="white", edgecolor=ROJO if clase == "fin" else VERDE,
                            lw={"inicio": 1.1, "fin": 2.4, "intermedio": 1.0}[clase]))
        if clase == "intermedio":
            ax.add_patch(Circle((x, f1), 0.13, facecolor="white", edgecolor=VERDE, lw=0.9))
            ax.plot([x, x], [f1, f1 + 0.08], color=GRIS, lw=0.8)
            ax.plot([x, x + 0.06], [f1, f1], color=GRIS, lw=0.8)
        ax.text(x + 0.3, f1, texto, fontsize=6.6, va="center")
    x = x0 + 0.1 + 3 * col
    ax.add_patch(FancyBboxPatch((x, f1 - 0.17), 0.5, 0.34, boxstyle="round,pad=0,rounding_size=0.06",
                                facecolor=AZUL_CLARO, edgecolor=AZUL, lw=1.0))
    ax.text(x + 0.62, f1, "Tarea", fontsize=6.6, va="center")
    x = x0 + 0.15 + 4 * col
    ax.add_patch(Rectangle((x, f1 - 0.15), 0.34, 0.3, facecolor="white", edgecolor="#333333", lw=0.9))
    ax.add_patch(Ellipse((x + 0.17, f1 + 0.15), 0.34, 0.09, facecolor="white", edgecolor="#333333", lw=0.9))
    ax.text(x + 0.46, f1, "Sistema de\ninformación", fontsize=6.6, va="center")
    for i, (tipo, texto) in enumerate([
            ("X", "Decisión: se sigue uno solo de los caminos (o se reúnen caminos alternativos)"),
            ("+", "En paralelo: se siguen todos los caminos a la vez (o se espera a que terminen todos)")]):
        xg, g, yg = x0 + 0.3 + i * 2.5 * col, 0.17, f2
        ax.add_patch(Polygon([(xg, yg + g), (xg + g, yg), (xg, yg - g), (xg - g, yg)], closed=True,
                             facecolor="#fff6d6", edgecolor="#a57f00", lw=1.0))
        d = g * 0.45
        if tipo == "X":
            ax.plot([xg - d, xg + d], [yg - d, yg + d], color="#a57f00", lw=1.3)
            ax.plot([xg - d, xg + d], [yg + d, yg - d], color="#a57f00", lw=1.3)
        else:
            ax.plot([xg - d * 1.2, xg + d * 1.2], [yg, yg], color="#a57f00", lw=1.4)
            ax.plot([xg, xg], [yg - d * 1.2, yg + d * 1.2], color="#a57f00", lw=1.4)
        partes = texto.split(" (")
        ax.text(xg + 0.3, yg, partes[0] + "\n(" + partes[1], fontsize=6.4, va="center")
    for i, (tipo, texto) in enumerate([("secuencia", "Orden de las tareas dentro de la facultad"),
                                       ("mensaje", "Mensaje entre la facultad y los alumnos"),
                                       ("asociacion", "Nota o sistema asociado a una tarea")]):
        xf = x0 + 0.15 + i * (ancho - x0) / 3
        if tipo == "secuencia":
            _bpmn_secuencia(ax, [(xf, f3), (xf + 0.5, f3)])
        elif tipo == "mensaje":
            ax.plot([xf, xf + 0.5], [f3, f3], color="#333333", lw=0.9, ls=(0, (4, 3)))
            ax.add_patch(Circle((xf, f3), 0.05, facecolor="white", edgecolor="#333333", lw=0.9, zorder=3))
            ax.add_patch(FancyArrowPatch((xf + 0.3, f3), (xf + 0.5, f3),
                                         arrowstyle="-|>,head_width=0.25,head_length=0.45", mutation_scale=9,
                                         facecolor="white", edgecolor="#333333", lw=0.9, zorder=3))
        else:
            ax.plot([xf, xf + 0.5], [f3, f3], color="#333333", lw=0.9, ls=(0, (1, 2)))
        ax.text(xf + 0.62, f3, texto, fontsize=6.4, va="center")


def proceso_bpmn() -> None:
    """Proceso actual de planificación de horarios y asignación de aulas (3.3.2)."""
    ultimo = 16
    ancho = len(_CARRILES) * _ANCHO_CARRIL
    arriba, abajo = 1.6, _cy(ultimo) - 0.8
    fig, ax = plt.subplots(figsize=(8.0, 12.2))

    # Pool de la facultad y sus carriles.
    ax.add_patch(Rectangle((0, abajo), ancho, arriba - abajo, fill=False, edgecolor="#333333", lw=1.2, zorder=1))
    ax.plot([0, ancho], [arriba - 0.42, arriba - 0.42], color="#333333", lw=1.2, zorder=1)
    ax.text(ancho / 2, arriba - 0.21, "FCEIA: planificación de horarios y asignación de aulas",
            ha="center", va="center", fontsize=8, weight="bold")
    for i, nombre in enumerate(_CARRILES):
        x0 = i * _ANCHO_CARRIL
        if i:
            ax.plot([x0, x0], [abajo, arriba - 0.42], color="#333333", lw=0.8, zorder=1)
        ax.text(x0 + _ANCHO_CARRIL / 2, arriba - 0.78, nombre, ha="center", va="center", fontsize=7.2, weight="bold")
    ax.plot([0, ancho], [arriba - 1.13, arriba - 1.13], color="#333333", lw=0.8, zorder=1)

    # Pool de los alumnos, a la derecha.
    xa0, xa1 = ancho + 1.75, ancho + 2.45
    ax.add_patch(Rectangle((xa0, abajo), xa1 - xa0, arriba - abajo, fill=False, edgecolor="#333333", lw=1.2))
    ax.text((xa0 + xa1) / 2, (arriba + abajo) / 2, "Alumnos", rotation=90, ha="center", va="center",
            fontsize=8, weight="bold")

    ESC, ING, SA, ST, SE = range(5)
    x, y = _cx, _cy
    w2, h2 = _W / 2, _H / 2

    def rotulo_der(paso, texto, dy=0.0):
        ax.text(x(SA) + _G + 0.1, y(paso) + _G + 0.05 + dy, texto, ha="left", va="bottom",
                fontsize=6.6, style="italic")

    def rotulo_izq(paso, texto):
        ax.text(x(SA) - _G - 0.1, y(paso) + 0.08, texto, ha="right", va="bottom",
                fontsize=6.6, style="italic")

    # Planificación inicial.
    _bpmn_evento(ax, SA, 0, "inicio", "Comienza la\nplanificación")
    _bpmn_compuerta(ax, SA, 1, "X")
    _bpmn_compuerta(ax, SA, 2, "+")
    rotulo_izq(2, "En paralelo")
    _bpmn_tarea(ax, ESC, 3, "Establecer los\ncronogramas del\nCiclo Superior")
    _bpmn_tarea(ax, ING, 3, "Proyectar y distribuir\nlas comisiones del\nCiclo Básico")
    _bpmn_compuerta(ax, SA, 4, "+")
    ax.text(x(SA) - _G - 0.1, y(4) - 0.12, "Cuando terminan\nlas dos", ha="right", va="top",
            fontsize=6.6, style="italic")
    _bpmn_tarea(ax, SA, 5, "Integrar en una\ngrilla única y\nverificarla")
    _bpmn_compuerta(ax, SA, 6, "X", "¿Hay\ndiscrepancias?")
    _bpmn_tarea(ax, SA, 7, "Aprobar la grilla\nhoraria general")
    _bpmn_tarea(ax, ST, 8, "Asignar aulas según\ncapacidad y\nequipamiento")
    _bpmn_tarea(ax, SA, 9, "Refrendar el\ncuadro definitivo\nde ocupación")
    _bpmn_tarea(ax, SE, 10, "Cargar las aulas y\nadministrar las\ninscripciones")
    _bpmn_almacen(ax, x(SE) + 0.75, y(11.25), "SIU\nGuaraní")
    # Durante el cuatrimestre.
    _bpmn_evento(ax, SA, 12, "intermedio", "Inicio de\nclases")
    _bpmn_compuerta(ax, SA, 13, "X")
    _bpmn_compuerta(ax, SA, 14, "X")
    rotulo_der(14, "¿Novedad\noperativa?", dy=0.05)
    _bpmn_tarea(ax, ST, 14.85, "Reasignar el aula\ny comunicar\nel cambio")
    _bpmn_evento(ax, SA, 15.85, "fin", "Fin del\ncuatrimestre")

    sec = lambda *pts, **kw: _bpmn_secuencia(ax, list(pts), **kw)
    sec((x(SA), y(0) - _R), (x(SA), y(1) + _G))
    sec((x(SA), y(1) - _G), (x(SA), y(2) + _G))
    sec((x(SA) - _G, y(2)), (x(ESC), y(2)), (x(ESC), y(3) + h2))
    sec((x(SA), y(2) - _G), (x(SA), y(2.5)), (x(ING), y(2.5)), (x(ING), y(3) + h2))
    sec((x(ESC), y(3) - h2), (x(ESC), y(4)), (x(SA) - _G, y(4)))
    sec((x(ING), y(3) - h2), (x(ING), y(3.55)), (x(SA), y(3.55)), (x(SA), y(4) + _G))
    sec((x(SA), y(4) - _G), (x(SA), y(5) + h2))
    sec((x(SA), y(5) - h2), (x(SA), y(6) + _G))
    xr = x(SA) + 1.38
    sec((x(SA) + _G, y(6)), (xr, y(6)), (xr, y(1)), (x(SA) + _G, y(1)),
        rotulo="Sí: se devuelven\nlas observaciones", pos_rotulo=(x(SA) + _G + 0.08, y(6) + 0.3))
    sec((x(SA), y(6) - _G), (x(SA), y(7) + h2), rotulo="No", pos_rotulo=(x(SA) + 0.1, y(6) - _G - 0.17))
    sec((x(SA) + w2, y(7)), (x(ST), y(7)), (x(ST), y(8) + h2))
    sec((x(ST), y(8) - h2), (x(ST), y(9)), (x(SA) + w2, y(9)))
    sec((x(SA), y(9) - h2), (x(SA), y(9.55)), (x(SE), y(9.55)), (x(SE), y(10) + h2))
    sec((x(SE) - 0.5, y(10) - h2), (x(SE) - 0.5, y(12)), (x(SA) + _R, y(12)))
    sec((x(SA), y(12) - _R), (x(SA), y(13) + _G))
    sec((x(SA), y(13) - _G), (x(SA), y(14) + _G))
    sec((x(SA) + _G, y(14)), (x(ST), y(14)), (x(ST), y(14.85) + h2),
        rotulo="Sí", pos_rotulo=(x(SA) + _G + 0.1, y(14) - 0.17))
    xr = x(ST) + 1.38
    sec((x(ST) + w2, y(14.85)), (xr, y(14.85)), (xr, y(13)), (x(SA) + _G, y(13)))
    sec((x(SA), y(14) - _G), (x(SA), y(15.85) + _R), rotulo="No", pos_rotulo=(x(SA) - 0.3, y(14) - _G - 0.17))

    # Asociaciones (línea de puntos): sistema de información y anotaciones.
    ax.plot([x(SE) + 0.75, x(SE) + 0.75], [y(10) - h2, y(11.25) + 0.39], color="#333333", lw=0.9, ls=(0, (1, 2)))
    _bpmn_anotacion(ax, x(ING) - 1.4, y(14), "Por ejemplo:\ninscripciones tardías,\nmaterias más numerosas,\ncambios de último\nmomento o exámenes", alto=1.15)
    ax.plot([x(ING) + 1.35, x(SA) - _G], [y(14), y(14)], color="#333333", lw=0.9, ls=(0, (1, 2)))
    _bpmn_anotacion(ax, x(SE) - 1.2, y(8), "Trabajo manual:\nplanillas, correo\ny notas", alto=0.75)
    ax.plot([x(ST) + w2, x(SE) - 1.2], [y(8), y(8)], color="#333333", lw=0.9, ls=(0, (1, 2)))

    # Mensajes con los alumnos.
    xm = (x(SE) + w2 + xa0) / 2
    _bpmn_mensaje(ax, [(x(SE) + w2, y(10) + 0.2), (xa0, y(10) + 0.2)], "Comisiones\ny aulas", (xm, y(10) + 0.62))
    _bpmn_mensaje(ax, [(xa0, y(10) - 0.2), (x(SE) + w2, y(10) - 0.2)], "Inscripción", (xm, y(10) - 0.5))

    _bpmn_leyenda(ax, 0.1, abajo - 0.5, xa1)
    ax.set_xlim(-0.1, xa1 + 0.1)
    ax.set_ylim(abajo - 2.95, arriba + 0.1)
    ax.set_aspect("equal")
    ax.axis("off")
    _guardar(fig, "proceso_bpmn.png")

# ---------------------------------------------------------------------------
# Diagrama entidad-relación (Graphviz)
# ---------------------------------------------------------------------------
# Cada tabla con sus atributos principales (clave primaria, claves
# foráneas y los campos que usa el problema), agrupadas por zona, en
# notación pata de gallo, con una leyenda de la notación. Los atributos
# completos están en src/database/models.py (Anexo A).

_ZONAS_ER = {
    "Catálogo": ("#eef4fa", [
        ("carrera", "Carrera", "carreras", [("PK", "codigo"), ("", "nombre"), ("", "dicta_recursado")]),
        ("materia", "Materia", "materias", [("PK", "codigo"), ("", "nombre"), ("", "horas_teoria"),
                                            ("", "horas_laboratorio"), ("", "periodo"), ("", "virtual"),
                                            ("FK", "grupo_id")]),
        ("correlativa", "Correlativa", "correlativas", [("PK FK", "carrera_codigo"), ("PK FK", "materia_codigo"),
                                                       ("PK FK", "materia_correlativa_codigo")]),
        ("grupo", "Grupo de materias", "grupo_materia", [("PK", "id"), ("", "nombre"), ("", "es_sin_clasificar")]),
        ("grupo_sede", "Sede del grupo", "grupo_materia_sede", [("PK FK", "grupo_id"), ("PK FK", "sede_id"),
                                                              ("PK", "tipo (duro / blando)"), ("", "orden")]),
        ("sede", "Sede", "sedes", [("PK", "id"), ("", "nombre"), ("", "hora_apertura"), ("", "hora_cierre")]),
        ("aula", "Aula", "aulas", [("PK", "id"), ("FK", "sede_id"), ("", "codigo_aula"), ("", "capacidad"),
                                    ("", "tipo"), ("", "activa")]),
        ("mat_lab", "Laboratorio compatible", "materia_laboratorio", [("PK FK", "materia_codigo"),
                                                                     ("PK FK", "aula_id")]),
    ]),
    "Plan de estudios": ("#f1f7ee", [
        ("version", "Versión de plan", "plan_carrera_version", [("PK", "id"), ("FK", "carrera_codigo"),
                                                               ("", "nombre"), ("", "active")]),
        ("entrada", "Entrada de plan", "plan_estudio", [("PK", "id"), ("FK", "plan_version_id"),
                                                       ("FK", "materia_codigo"), ("", "anio_plan"),
                                                       ("", "cuatrimestre_plan"), ("", "optativa")]),
    ]),
    "Ciclo lectivo": ("#fbf3e8", [
        ("ciclo", "Ciclo lectivo", "ciclos", [("PK", "id"), ("", "anio"), ("", "numero"),
                                             ("", "fecha_inicio"), ("", "fecha_fin")]),
        ("ciclo_version", "Versión vigente", "ciclo_plan_version", [("PK FK", "ciclo_id"),
                                                                   ("PK FK", "plan_version_id")]),
        ("dictado", "Dictado", "dictados", [("PK", "id"), ("FK", "materia_codigo"), ("", "inicio_dictado"),
                                           ("", "fin_dictado"), ("", "virtual")]),
        ("dictado_ciclo", "Dictado en el ciclo", "dictado_ciclo", [("PK FK", "dictado_id"), ("PK FK", "ciclo_id")]),
        ("inscripcion", "Inscripción histórica", "inscripciones_historicas", [("PK FK", "materia_codigo"),
                                                                            ("PK", "anio"), ("PK", "cuatrimestre"),
                                                                            ("", "inscriptos")]),
    ]),
    "Cronograma y plan de cursada": ("#f6eef6", [
        ("cronograma", "Cronograma", "schedules", [("PK", "id"), ("FK", "ciclo_id"), ("", "nombre")]),
        ("horario_cron", "Horario del cronograma", "schedule_entries", [("PK", "id"), ("FK", "schedule_id"),
                                                                       ("FK", "comision_id"), ("", "dia"),
                                                                       ("", "hora_inicio / hora_fin"),
                                                                       ("", "tipo_clase")]),
        ("plan", "Plan de cursada", "planificaciones_cursada", [("PK", "id"), ("FK", "ciclo_id"),
                                                               ("FK", "schedule_id"), ("", "nombre")]),
        ("comision", "Comisión", "comisiones", [("PK", "id"), ("FK", "materia_codigo"), ("FK", "dictado_id"),
                                               ("FK", "schedule_id"), ("FK", "plan_cursada_id"),
                                               ("", "cupo"), ("", "coef_asignacion")]),
        ("horario", "Horario semanal", "horarios", [("PK", "id"), ("FK", "comision_id"), ("", "dia"),
                                                   ("", "hora_inicio / hora_fin"), ("", "tipo_clase"),
                                                   ("FK", "aula_id")]),
    ]),
}

# (padre, hijo, multiplicidad del lado padre, del lado hijo, rótulo)
UNO, CERO_O_UNO, MUCHOS, UNO_O_MUCHOS = "teetee", "teeodot", "crowodot", "crowtee"
_RELACIONES_ER = [
    ("carrera", "version", UNO, MUCHOS, "tiene"),
    ("version", "entrada", UNO, MUCHOS, "detalla"),
    ("materia", "entrada", UNO, MUCHOS, "aparece en"),
    ("materia", "correlativa", UNO, MUCHOS, "requiere"),
    ("carrera", "correlativa", UNO, MUCHOS, "en la carrera"),
    ("grupo", "materia", UNO, UNO_O_MUCHOS, "agrupa"),
    ("grupo", "grupo_sede", UNO, MUCHOS, "admite"),
    ("sede", "grupo_sede", UNO, MUCHOS, "admitida en"),
    ("sede", "aula", UNO, MUCHOS, "tiene"),
    ("materia", "mat_lab", UNO, MUCHOS, "usa"),
    ("aula", "mat_lab", UNO, MUCHOS, "sirve a"),
    ("ciclo", "ciclo_version", UNO, MUCHOS, "aplica"),
    ("version", "ciclo_version", UNO, MUCHOS, "rige en"),
    ("materia", "dictado", UNO, MUCHOS, "se dicta"),
    ("dictado", "dictado_ciclo", UNO, UNO_O_MUCHOS, "cubre"),
    ("ciclo", "dictado_ciclo", UNO, MUCHOS, "ofrece"),
    ("materia", "inscripcion", UNO, MUCHOS, "registra"),
    ("ciclo", "cronograma", CERO_O_UNO, MUCHOS, "tiene"),
    ("ciclo", "plan", UNO, MUCHOS, "tiene"),
    ("cronograma", "plan", CERO_O_UNO, MUCHOS, "origina"),
    ("cronograma", "comision", CERO_O_UNO, MUCHOS, "propone"),
    ("plan", "comision", CERO_O_UNO, MUCHOS, "abre"),
    ("materia", "comision", UNO, MUCHOS, "se abre en"),
    ("dictado", "comision", CERO_O_UNO, MUCHOS, "se divide en"),
    ("cronograma", "horario_cron", UNO, MUCHOS, "contiene"),
    ("comision", "horario_cron", CERO_O_UNO, MUCHOS, "programa"),
    ("comision", "horario", UNO, MUCHOS, "programa"),
    ("aula", "horario", CERO_O_UNO, MUCHOS, "aloja"),
]


def _er_tabla(titulo: str, tabla: str, atributos: list[tuple[str, str]], fondo: str) -> str:
    filas = "".join(
        f'<TR><TD ALIGN="LEFT" WIDTH="26">{"<FONT POINT-SIZE=\"7\" COLOR=\"#555555\">" + clave + "</FONT>" if clave else " "}</TD>'
        f'<TD ALIGN="LEFT"><FONT POINT-SIZE="9">{"<B>" + nombre + "</B>" if "PK" in clave else nombre}</FONT></TD></TR>'
        for clave, nombre in atributos)
    return (f'<<TABLE BORDER="1" CELLBORDER="0" CELLSPACING="0" CELLPADDING="2" COLOR="#2f5d8a" BGCOLOR="white">'
            f'<TR><TD COLSPAN="2" BGCOLOR="{fondo}"><B>{titulo}</B><BR/>'
            f'<FONT POINT-SIZE="8" COLOR="#555555">{tabla}</FONT></TD></TR>{filas}</TABLE>>')


# Ubicación de cada tabla en la grilla (columna, fila): cada tabla queda
# al lado de las que se relaciona y Materia, que se vincula con casi
# todo, queda en el centro.
_GRILLA_ER = {
    "carrera": (0, 0), "version": (1, 0), "ciclo_version": (2, 0), "ciclo": (3, 0),
    "correlativa": (0, 1), "entrada": (1, 1), "dictado_ciclo": (2, 1), "plan": (3, 1),
    "inscripcion": (0, 2), "materia": (1, 2), "dictado": (2, 2), "cronograma": (3, 2),
    "grupo": (0, 3), "mat_lab": (1, 3), "comision": (2, 3), "horario_cron": (3, 3),
    "grupo_sede": (0, 4), "sede": (1, 4), "aula": (2, 4), "horario": (3, 4),
}
_ALTO_FILA_ER = [1.85, 2.4, 2.3, 2.2, 1.85]  # pulgadas


def diagrama_er() -> None:
    """Modelo de datos implementado, en notación pata de gallo."""
    import subprocess
    col_w = 2.45
    ys, y = [], 0.0
    for alto in _ALTO_FILA_ER:
        ys.append(-(y + alto / 2))
        y += alto
    lineas = [
        "graph er {",
        '  graph [splines=true, fontname="Arial", pad=0.15, outputorder=edgesfirst, sep="+1"];',
        '  node [shape=plaintext, fontname="Arial", fontsize=10];',
        '  edge [fontname="Arial", fontsize=8, fontcolor="#333333", color="#444444", dir=both,'
        ' arrowsize=0.85, penwidth=0.9];',
    ]
    zona_de, fondos = {}, {}
    for zona, (fondo, entidades) in _ZONAS_ER.items():
        fondos[zona] = fondo
        for clave, titulo, tabla, atributos in entidades:
            col, fila = _GRILLA_ER[clave]
            lineas.append(f'  {clave} [label={_er_tabla(titulo, tabla, atributos, fondo)},'
                          f' pos="{col * col_w:.2f},{ys[fila]:.2f}!"];')
    for padre, hijo, mult_padre, mult_hijo, rotulo in _RELACIONES_ER:
        lineas.append(f'  {padre} -- {hijo} [arrowtail={mult_padre}, arrowhead={mult_hijo},'
                      f' label=" {rotulo} "];')
    # Leyenda: multiplicidades y zonas, en una fila debajo de la grilla.
    y_ley = -(y + 0.4)
    ejemplos = [(UNO, "exactamente uno"), (CERO_O_UNO, "cero o uno"),
                (UNO_O_MUCHOS, "uno o muchos"), (MUCHOS, "cero o muchos")]
    for j, (punta, texto) in enumerate(ejemplos):
        x0 = 0.6 + j * 1.6
        yj = y_ley
        lineas.append(f'  ley_a{j} [label="", shape=point, width=0.02, pos="{x0:.2f},{yj:.2f}!"];')
        lineas.append(f'  ley_b{j} [label="", shape=point, width=0.02, pos="{x0 + 0.75:.2f},{yj:.2f}!"];')
        lineas.append(f'  ley_t{j} [label="{texto}", fontsize=9, pos="{x0 + 0.38:.2f},{yj - 0.36:.2f}!"];')
        lineas.append(f'  ley_a{j} -- ley_b{j} [dir=forward, arrowhead={punta}];')
    zonas = "".join(f'<TD BGCOLOR="{f}" BORDER="1" COLOR="#2f5d8a"> {z} </TD>' for z, f in fondos.items())
    lineas.append(f'  ley_zonas [label=<<TABLE BORDER="0" CELLSPACING="4"><TR><TD><B>Zonas:</B></TD>{zonas}'
                  f'</TR></TABLE>>, fontsize=9, pos="{1.5 * col_w:.2f},{y_ley - 1.0:.2f}!"];')
    lineas.append(f'  ley_claves [label=<<B>PK</B> clave primaria   <B>FK</B> clave foránea   '
                  f'<BR/>Cada caja es una tabla: arriba, su nombre en el modelo; abajo, en la base.<BR/>'
                  f'Cada extremo de una línea dice cuántas filas de esa tabla corresponden a una de la otra:<BR/>'
                  f'una carrera tiene cero o muchas versiones de plan, y cada versión es de exactamente una carrera.>,'
                  f' fontsize=9, pos="{1.5 * col_w:.2f},{y_ley - 1.7:.2f}!"];')
    lineas.append(f'  ley_titulo [label=<<B>Notación</B>>, fontsize=10, pos="{-0.2:.2f},{y_ley + 0.2:.2f}!"];')
    lineas.append("}")
    dot = "\n".join(lineas)
    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "modelo_er.dot").write_text(dot, encoding="utf-8")
    subprocess.run(["neato", "-Tpng", "-Gdpi=220", "-o", str(DESTINO / "modelo_er.png")],
                   input=dot, text=True, check=True)
    print("✓ modelo_er.png")

if __name__ == "__main__":
    diagrama_er()
    proceso_bpmn()
    grafo_bipartito()
    palomar()
    ejemplo_lp()
    efecto_cascada()
    a6_vs_a6p()
    ramificacion_acotacion()
    ocupacion_caso()
    asientos_libres_caso()
