"""Convierte los .md del informe a .docx listos para importar en Google Docs.

Uso:
    python -m scripts.exportar_informe_docx            # convierte todo el informe
    python -m scripts.exportar_informe_docx cap08      # solo los archivos cuyo nombre contenga "cap08"
    python -m scripts.exportar_informe_docx --consolidado  # un único docx: informe + anexos + docs técnicos

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


def _pandoc() -> str:
    """Ruta a un pandoc >= 3 (hace falta para el bloque Figure del filtro
    del informe). Puede haber varios en el PATH: por ejemplo, Anaconda
    trae pandoc 2.12 y queda antes que el de Homebrew."""
    import shutil
    candidatos = [c for c in dict.fromkeys(
        [shutil.which("pandoc"), "/opt/homebrew/bin/pandoc", "/usr/local/bin/pandoc"]) if c]
    for c in candidatos:
        try:
            v = subprocess.run([c, "--version"], capture_output=True, text=True).stdout.split()[1]
        except (OSError, IndexError):
            continue
        if int(v.split(".")[0]) >= 3:
            return c
    raise SystemExit("Hace falta pandoc 3 o más nuevo (brew install pandoc).")


PANDOC = _pandoc()
DIR_INFORME = RAIZ / "project" / "Informe"
DIR_SALIDA = RAIZ / "dist" / "informe_docx"

BLOQUE_MERMAID = re.compile(r"^```mermaid\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL)

# Límites de los diagramas dentro del documento (una página A4 tiene ~16 cm de
# ancho útil y ~24 cm de alto útil; una imagen más alta que la página se recorta).
# Los diagramas más chicos conservan su tamaño natural para no verse estirados.
ANCHO_MAXIMO_CM = 16.0
ALTO_MAXIMO_CM = 24.0
ALTO_FIGURA_INFORME_CM = 19.0

# Config de mermaid: sin esto los nodos de flowchart envuelven el texto a 200 px
# y los diagramas con descripciones largas quedan angostos y kilométricos.
CONFIG_MERMAID = '{"flowchart": {"wrappingWidth": 450}}'


def _ancho_diagrama(svg: Path, alto_maximo_cm: float = ALTO_MAXIMO_CM) -> str:
    """Devuelve el ancho a usar en el docx.

    Parte del tamaño natural del diagrama y lo reduce proporcionalmente si
    excede el ancho o el alto útiles de una página A4.
    """
    match = re.search(r'viewBox="[\d.\-]+ [\d.\-]+ ([\d.]+) ([\d.]+)"', svg.read_text(encoding="utf-8"))
    if match:
        ancho_cm = float(match.group(1)) / 96 * 2.54
        alto_cm = float(match.group(2)) / 96 * 2.54
        escala = min(1.0, ANCHO_MAXIMO_CM / ancho_cm, alto_maximo_cm / alto_cm)
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
            PANDOC,
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


# Documento consolidado: (título de la parte, archivos en orden). Las
# rutas son relativas a project/. Se dejan afuera las auditorías, las
# notas de sesiones y los borradores internos del informe.
DIR_PROJECT = RAIZ / "project"
PARTES_CONSOLIDADO: list[tuple[str, list[str]]] = [
    ("Parte I · Informe", [
        "Informe/intro.md",
        "Informe/cap02_marco_teorico.md",
        "Informe/cap03_organizacion_y_operatoria.md",
        "Informe/cap04_definicion_del_problema.md",
        "Informe/cap05_modelo_conceptual.md",
        "Informe/cap06_modelo_de_datos.md",
        "Informe/cap07_arquitectura.md",
        "Informe/cap08_programa_lineal.md",
        "Informe/cap09_validaciones.md",
    ]),
    ("Anexos del informe", [
        "Informe/anexos/Anexo_Base_de_Datos.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/README.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/00_Introduccion.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/01_Primeros_pasos.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/flujos/01_Setup_inicial.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/flujos/02_Armar_un_ciclo_lectivo.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/flujos/03_Reasignacion_de_aulas.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/flujos/04_Verificacion_pre_inicio.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/01_Materias.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/02_Aulas_y_Sedes.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/03_Carreras.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/04_Ciclos.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/05_Planes_y_Asignacion_de_Aulas.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/06_Cronogramas.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/07_Inscriptos.md",
        "Informe/anexos/Anexo_Manual_de_Usuario/modulos/08_Historial.md",
    ]),
    ("Parte II · Documentación técnica", [
        "README.md",
        "requerimientos.md",
        "0. Planteo/ante_proyecto.md",
        "0. Planteo/modelo-er.md",
        "0. Planteo/plan-de-cursada.md",
        "1. Diseño/tech_stack.md",
        "1. Diseño/modelo-planificacion-cursada.md",
        "1. Diseño/diagrama-entidades.md",
        "1. Diseño/orm.md",
        "1. Diseño/asignacion-aulas-LP.md",
        "2. Desarrollo/WORKFLOW.md",
        "2. Desarrollo/VALIDACIONES.md",
        "2. Desarrollo/CICLOS_Y_DICTADOS.md",
        "2. Desarrollo/CARGA_DATOS_INICIALES.md",
        "2. Desarrollo/asignador_implementacion.md",
        "2. Desarrollo/asignador_guia_operativa.md",
        "2. Desarrollo/DISTRIBUCION.md",
    ]),
]

IMAGEN_MD = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
CERCO = re.compile(r"^(```|~~~)")


def _bajar_titulos(texto: str) -> str:
    """Baja un nivel los títulos Markdown (``#`` -> ``##``) para que cada
    archivo cuelgue de su parte, sin tocar los bloques de código."""
    salida, en_codigo = [], False
    for linea in texto.split("\n"):
        if CERCO.match(linea):
            en_codigo = not en_codigo
        elif not en_codigo and re.match(r"^#{1,5} ", linea):
            linea = "#" + linea
        salida.append(linea)
    return "\n".join(salida)


def _imagenes_absolutas(texto: str, base: Path, dir_diagramas: Path) -> str:
    """Vuelve absolutas las rutas relativas de las imágenes (al unir
    archivos de carpetas distintas dejan de resolverse). Los SVG se pasan
    a PNG: Google Docs descarta el SVG al importar un docx."""
    def reemplazo(m: re.Match) -> str:
        alt, ruta = m.group(1), m.group(2)
        if re.match(r"^[a-z]+://", ruta) or ruta.startswith("/"):
            return m.group(0)
        origen = (base / ruta).resolve()
        if origen.suffix.lower() == ".svg" and origen.exists():
            png = dir_diagramas / f"{origen.stem}.png"
            r = subprocess.run(
                ["rsvg-convert", "--zoom", "3", "-o", str(png), str(origen)],
                capture_output=True,
            )
            if r.returncode == 0:
                origen = png
        return f"![{alt}]({origen})"
    return IMAGEN_MD.sub(reemplazo, texto)


def consolidar(dir_diagramas: Path) -> bool:
    """Arma un único .docx con el informe, sus anexos y la documentación
    técnica, en el orden de ``PARTES_CONSOLIDADO``, con índice."""
    bloques = []
    for titulo, archivos in PARTES_CONSOLIDADO:
        bloques.append(f"# {titulo}\n")
        for rel in archivos:
            md = DIR_PROJECT / rel
            if not md.exists():
                print(f"  ⚠ no existe {rel}, se omite")
                continue
            texto = _preprocesar(md, dir_diagramas)
            texto = _imagenes_absolutas(texto, md.parent, dir_diagramas)
            bloques.append(_bajar_titulos(texto))
    destino = DIR_SALIDA / "Gestor_de_Aulas_documentacion_consolidada.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    resultado = subprocess.run(
        [
            PANDOC,
            "--from", "markdown+tex_math_dollars",
            "--to", "docx",
            "--toc", "--toc-depth", "2",
            "--metadata", "title=Gestor de Aulas · FCEIA-UNR",
            "--metadata", "subtitle=Informe del proyecto y documentación técnica",
            "--metadata", "toc-title=Índice",
            "-o", str(destino),
        ],
        input="\n\n".join(bloques),
        capture_output=True,
        text=True,
    )
    if resultado.returncode != 0:
        print(f"✗ consolidado: {resultado.stderr.strip()}")
        return False
    print(f"✓ consolidado -> {destino.relative_to(RAIZ)}")
    return True


# Informe completo según las pautas de la cátedra (CLAUDE.md, regla 8.b).
ORDEN_INFORME = [
    "preliminares.md", "prologo.md", "sintesis_inicial.md", "intro.md",
    "cap02_marco_teorico.md", "cap03_organizacion_y_operatoria.md",
    "cap04_definicion_del_problema.md", "cap05_modelo_conceptual.md",
    "cap06_modelo_de_datos.md", "cap07_arquitectura.md",
    "cap08_programa_lineal.md", "cap09_validaciones.md",
    "cap10_herramienta_en_accion.md", "cap11_analisis_y_discusion.md",
    "cap12_conclusiones.md", "bibliografia.md", "anexos_indice.md",
]
REFERENCIA_INFORME = RAIZ / "scripts" / "informe_referencia.docx"
FILTRO_INFORME = RAIZ / "scripts" / "informe_apa.lua"
FIGURA_CON_TITULO = re.compile(
    r"^<!-- figura: (.+?) -->\s*\n```mermaid\s*\n(.*?)^```\s*$", re.MULTILINE | re.DOTALL,
)
TITULO_TABLA = re.compile(r"^<!-- tabla: (.+?) -->\s*$", re.MULTILINE)
# Referencias cruzadas: la figura o la tabla se rotula con `{#fig:clave}`
# o `{#tab:clave}` (en el comentario del título o en los atributos de la
# imagen) y el texto la cita como "Figura @fig:clave". Al armar el
# informe, @fig:clave pasa a ser el número que le da el filtro.
ID_REFERENCIA = re.compile(r"\s*\{#((?:fig|tab):[\w-]+)\}\s*$")
REFERENCIA = re.compile(r"@((?:fig|tab):[\w-]+)")
LINEA_FIGURA = re.compile(r"^\s*!\[[^\]]+\]\([^)]+\)(\{[^}]*\})?\s*$")
FORMULA_BLOQUE = re.compile(r"^\$\$(.*?)\$\$[ \t]*$", re.MULTILINE | re.DOTALL)
# Fin de la sección sin numerar (carátula, dedicatoria y advertencia):
# una sección sin cabecera ni pie, A4 con márgenes de 2,5 cm. La sección
# siguiente toma la cabecera y el pie del documento de referencia.
FIN_SECCION_SIN_NUMERAR = """
```{=openxml}
<w:p><w:pPr><w:sectPr><w:pgSz w:w="11906" w:h="16838"/><w:pgMar w:top="1418" w:right="1418" w:bottom="1418" w:left="1418" w:header="709" w:footer="709" w:gutter="0"/></w:sectPr></w:pPr></w:p>
```
"""


def _preparar_capitulo(md: Path, dir_diagramas: Path, n_formula: list[int]) -> str:
    """Markdown de un capítulo listo para el informe: diagramas como
    figuras con título (el filtro APA arma "Figura N"), tablas con
    título ("Table:" de pandoc, que el filtro convierte en "Tabla N") y
    fórmulas numeradas a la derecha."""
    texto = md.read_text(encoding="utf-8")
    contador = [0]

    def figura(m: re.Match) -> str:
        contador[0] += 1
        base = dir_diagramas / f"{md.stem}_diagrama_{contador[0]}"
        png, svg = base.with_suffix(".png"), base.with_suffix(".svg")
        if not _renderizar_mermaid(m.group(2), png, svg):
            return f"```\n{m.group(2)}```"
        # En el informe la figura lleva rótulo, título y nota: con más de
        # 19 cm de alto no entran juntos en una página A4 y Google Docs
        # la parte en tres páginas.
        titulo, clave = m.group(1), ""
        rotulo = ID_REFERENCIA.search(titulo)
        if rotulo:
            titulo, clave = titulo[:rotulo.start()], f"#{rotulo.group(1)} "
        return f"\n![{titulo}]({png}){{{clave}width={_ancho_diagrama(svg, ALTO_FIGURA_INFORME_CM)}}}\n"

    texto = FIGURA_CON_TITULO.sub(figura, texto)
    if BLOQUE_MERMAID.search(texto):
        raise ValueError(
            f"{md.name}: hay un diagrama sin título; agregá "
            "`<!-- figura: … -->` en la línea anterior al bloque."
        )

    # Tablas: el título declarado antes de la tabla pasa a "Table: …"
    # después de ella (sintaxis de pandoc). Cada tabla con título va en
    # su propio bloque `::: tabla`: si no, con dos tablas seguidas pandoc
    # le asigna el título de la primera a la segunda.
    lineas, salida, pendiente = texto.split("\n"), [], None
    for i, linea in enumerate(lineas):
        m = TITULO_TABLA.match(linea)
        if m:
            pendiente = m.group(1)
            continue
        anterior = lineas[i - 1] if i > 0 else ""
        if pendiente and linea.lstrip().startswith("|") and not anterior.lstrip().startswith("|"):
            salida += ["::: tabla", ""]
        salida.append(linea)
        siguiente = lineas[i + 1] if i + 1 < len(lineas) else ""
        if pendiente and linea.lstrip().startswith("|") and not siguiente.lstrip().startswith("|"):
            salida += ["", f"Table: {pendiente}", "", ":::"]
            pendiente = None
    texto = "\n".join(salida)

    def formula(m: re.Match) -> str:
        n_formula[0] += 1
        return f"$${m.group(1).strip()} \\qquad ({n_formula[0]})$$"

    texto = FORMULA_BLOQUE.sub(formula, texto)
    texto = _imagenes_absolutas(texto, md.parent, dir_diagramas)
    if md.name == "preliminares.md":
        texto = texto.replace("\n# Índice", FIN_SECCION_SIN_NUMERAR + "\n# Índice", 1)
    return texto


def _numerar_referencias(texto: str) -> str:
    """Reemplaza @fig:clave y @tab:clave por el número de la figura o la
    tabla, contadas en el mismo orden que el filtro (informe_apa.lua):
    toda imagen con título sola en su párrafo es una figura y toda línea
    "Table:" cierra una tabla."""
    numeros: dict[str, int] = {}
    n_fig = n_tab = 0
    for linea in texto.split("\n"):
        m = LINEA_FIGURA.match(linea)
        if m:
            n_fig += 1
            clave = re.search(r"#(fig:[\w-]+)", m.group(1) or "")
            if clave:
                numeros[clave.group(1)] = n_fig
        elif linea.startswith("Table: "):
            n_tab += 1
            clave = ID_REFERENCIA.search(linea)
            if clave:
                numeros[clave.group(1)] = n_tab
    faltan = sorted(set(REFERENCIA.findall(texto)) - numeros.keys())
    if faltan:
        raise ValueError(f"referencias a figuras o tablas inexistentes: {', '.join(faltan)}")
    texto = re.sub(r"^(Table: .*?)\s*\{#tab:[\w-]+\}\s*$", r"\1", texto, flags=re.MULTILINE)
    return REFERENCIA.sub(lambda m: str(numeros[m.group(1)]), texto)


def informe(dir_diagramas: Path) -> bool:
    """Arma dist/informe_docx/Informe.docx con el formato de las pautas."""
    n_formula = [0]
    partes = [_preparar_capitulo(DIR_INFORME / n, dir_diagramas, n_formula) for n in ORDEN_INFORME]
    partes = [_numerar_referencias("\n\n".join(partes))]
    destino = DIR_SALIDA / "Informe.docx"
    destino.parent.mkdir(parents=True, exist_ok=True)
    resultado = subprocess.run(
        [
            PANDOC, "--from", "markdown+tex_math_dollars", "--to", "docx",
            "--reference-doc", str(REFERENCIA_INFORME),
            "--lua-filter", str(FILTRO_INFORME),
            "-o", str(destino),
        ],
        input="\n\n".join(partes), capture_output=True, text=True,
    )
    if resultado.returncode != 0:
        print(f"✗ informe: {resultado.stderr.strip()}")
        return False
    print(f"✓ informe -> {destino.relative_to(RAIZ)} ({n_formula[0]} fórmulas numeradas)")
    return True


def main() -> int:
    if len(sys.argv) > 1 and sys.argv[1] == "--informe":
        dir_diagramas = DIR_SALIDA / "_diagramas"
        dir_diagramas.mkdir(parents=True, exist_ok=True)
        return 0 if informe(dir_diagramas) else 1
    if len(sys.argv) > 1 and sys.argv[1] == "--consolidado":
        dir_diagramas = DIR_SALIDA / "_diagramas"
        dir_diagramas.mkdir(parents=True, exist_ok=True)
        return 0 if consolidar(dir_diagramas) else 1

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
