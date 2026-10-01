"""Sincroniza la documentación del repo con la carpeta compartida de Drive
"Proyecto de ingeniería / Consolidado".

Uso:
    python -m scripts.drive informe          # informe completo (pautas I-32), actualiza el Doc compartido
                                             # (se frena si alguien editó texto en el Doc; --forzar lo pisa)
    python -m scripts.drive previa           # lo mismo, pero sólo genera un PDF para revisar
    python -m scripts.drive docs [filtro]    # docs técnicos y anexos (.md -> Google Doc)
    python -m scripts.drive archivos         # archivos crudos e imágenes (Diagramas)
    python -m scripts.drive estructura       # crea las carpetas que falten

Cada documento se actualiza **en el lugar** (mismo link, permisos y
ubicación). Los IDs de Drive viven en scripts/drive/estado.json.

Requisitos: CLI de Composio con sesión iniciada y Google Drive/Docs
conectados; pandoc >= 3, mmdc y uv (ver scripts/exportar_informe_docx.py).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.drive import composio as cx
from scripts.exportar_informe_docx import (
    PANDOC,
    RAIZ,
    _imagenes_absolutas,
    _preprocesar,
)

ESTADO = Path(__file__).with_name("estado.json")
P = RAIZ / "project"
DIST = RAIZ / "dist"
MANUAL = "Informe/anexos/Anexo_Manual_de_Usuario"

# Carpetas de Consolidado: clave -> (clave del padre, nombre en Drive).
ARBOL = {
    "Consolidado": (None, "Consolidado"),
    "Documentacion Tecnica": ("Consolidado", "Documentacion Tecnica"),
    "Planteo": ("Documentacion Tecnica", "Planteo"),
    "Diseño": ("Documentacion Tecnica", "Diseño"),
    "Desarrollo": ("Documentacion Tecnica", "Desarrollo"),
    "Desarrollo/Sesiones": ("Desarrollo", "Sesiones"),
    "Desarrollo/Auditorias": ("Desarrollo", "Auditorias"),
    "Desarrollo/Auditorias/backups": ("Desarrollo/Auditorias", "backups"),
    "Diagramas": ("Consolidado", "Diagramas"),
    "Informe": ("Consolidado", "Informe"),
    "Anexos": ("Informe", "Anexos"),
    "Manuales": ("Anexos", "Manuales"),
    "Flujos": ("Manuales", "Flujos"),
    "Modulos": ("Manuales", "Modulos"),
}


def _estado() -> dict:
    return json.loads(ESTADO.read_text(encoding="utf-8"))


def _guardar(est: dict) -> None:
    ESTADO.write_text(json.dumps(est, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def _md_a_destino() -> list[tuple[str, str]]:
    """(.md relativo a project/, carpeta destino) de docs técnicos y anexos."""
    plan = [(r, "Documentacion Tecnica") for r in ("README.md", "requerimientos.md")]
    plan += [(f"0. Planteo/{n}", "Planteo") for n in ("ante_proyecto.md", "modelo-er.md", "plan-de-cursada.md")]
    for sub, dest in (("1. Diseño", "Diseño"), ("2. Desarrollo", "Desarrollo"),
                      ("2. Desarrollo/sesiones", "Desarrollo/Sesiones"),
                      ("2. Desarrollo/auditorias", "Desarrollo/Auditorias"),
                      (f"{MANUAL}/flujos", "Flujos"), (f"{MANUAL}/modulos", "Modulos")):
        plan += [(str(p.relative_to(P)), dest) for p in sorted((P / sub).glob("*.md"))]
    plan += [("Informe/anexos/Anexo_Base_de_Datos.md", "Anexos")]
    plan += [(f"{MANUAL}/{n}", "Manuales") for n in ("README.md", "00_Introduccion.md", "01_Primeros_pasos.md")]
    return plan


def estructura() -> None:
    est = _estado()
    for clave, (padre, nombre) in ARBOL.items():
        id_padre = est["carpeta_raiz"] if padre is None else est["carpetas"][padre]
        est["carpetas"][clave] = cx.asegurar_carpeta(id_padre, nombre)
    _guardar(est)
    print(f"✓ {len(ARBOL)} carpetas")


def docs(filtro: str = "") -> None:
    est = _estado()
    salida, diagramas = DIST / "drive_docx", DIST / "drive_docx" / "_diagramas"
    diagramas.mkdir(parents=True, exist_ok=True)
    for rel, destino in _md_a_destino():
        if filtro and filtro not in rel:
            continue
        md = P / rel
        texto = _imagenes_absolutas(_preprocesar(md, diagramas), md.parent, diagramas)
        docx = salida / Path(rel).with_suffix(".docx")
        docx.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run([PANDOC, "--from", "markdown+tex_math_dollars", "--to", "docx", "-o", str(docx)],
                       input=texto, text=True, check=True)
        clave = f"{destino}/{md.stem}"
        existente = est["documentos"].get(clave)
        est["documentos"][clave] = cx.docx_a_gdoc(docx, est["carpetas"][destino], md.stem, existente)
        _guardar(est)
        print(("↻" if existente else "✓"), clave)


def archivos() -> None:
    est = _estado()
    plan = [(P / "0. Planteo/domain_diagrams.py", "Planteo"), (P / "0. Planteo/diagrama-er.ipynb", "Planteo")]
    plan += [(f, "Desarrollo/Auditorias/backups") for f in sorted((P / "2. Desarrollo/auditorias/backups").glob("*.json"))]
    plan += [(f, "Diagramas") for f in sorted((P / "diagrams").iterdir()) if f.is_file()]
    for d in (DIST / "drive_docx/_diagramas", DIST / "informe_docx/_diagramas"):
        plan += [(f, "Diagramas") for f in sorted(d.glob("*.png"))] if d.exists() else []
    nuevos = 0
    for f, destino in plan:
        if cx.hijo(est["carpetas"][destino], f.name):
            continue
        cx.run("GOOGLEDRIVE_UPLOAD_FILE", {"folder_to_upload_to": est["carpetas"][destino]}, file=str(f))
        nuevos += 1
        print("✓", destino, f.name)
    print(f"{nuevos} archivo(s) nuevo(s) de {len(plan)}")


def _componer(inf: dict, extra: list[str]) -> Path:
    base = DIST / "informe_docx"
    subprocess.run([sys.executable, "-m", "scripts.exportar_informe_docx", "--informe", *extra], cwd=RAIZ, check=True)
    portada = cx.exportar_pestana_docx(inf["portada"]["doc_id"], inf["portada"]["tab_id"],
                                       base / "portada_borrador.docx")
    final = base / "Informe_final.docx"
    subprocess.run(["uv", "run", "--quiet", "--with", "docxcompose", "python",
                    "scripts/componer_informe.py", str(portada), str(base / "Informe.docx"), str(final)],
                   cwd=RAIZ, check=True)
    return final


def _pdf_temporal(docx: Path, pdf: Path) -> Path:
    """Convierte el .docx en un Doc temporal de tu Drive, exporta el PDF
    y manda el temporal a la papelera."""
    subido = cx.run("GOOGLEDRIVE_UPLOAD_FILE", {}, file=str(docx))
    doc = cx.run("GOOGLEDRIVE_COPY_FILE_ADVANCED", {
        "fileId": subido["id"], "name": "PREVIA Informe (temporal)", "mimeType": cx.GDOC, "fields": "id"})
    try:
        return cx.exportar_pdf(doc["id"], pdf)
    finally:
        for fid in (subido["id"], doc["id"]):
            cx.a_papelera(fid)


def _armar_informe(inf: dict) -> Path:
    """Regenera el .docx del informe con la portada del borrador, en dos
    pasadas: la primera, con números de página provisorios en el índice,
    se pagina en Google Docs para saber en qué página cae cada título; la
    segunda completa el índice con esos números."""
    base = DIST / "informe_docx"
    primera = _componer(inf, [])
    _pdf_temporal(primera, base / "Informe_paginado.pdf")
    subprocess.run(["uv", "run", "--quiet", "--with", "pymupdf", "python",
                    "scripts/paginas_indice.py", str(base / "Informe_paginado.pdf")], cwd=RAIZ, check=True)
    return _componer(inf, ["--con-paginas"])


def previa() -> None:
    """Como `informe`, pero sin tocar el Doc compartido: deja un PDF para
    revisar una iteración antes de publicarla."""
    est = _estado()
    final = _armar_informe(est["informe"])
    pdf = _pdf_temporal(final, DIST / "informe_docx" / "Informe_previa.pdf")
    print(f"✓ PDF de la vista previa: {pdf.relative_to(RAIZ)}")


def _huella(texto: str) -> str:
    import hashlib
    return hashlib.sha256(texto.encode("utf-8")).hexdigest()


def informe(*opciones: str) -> None:
    """Actualiza el Doc compartido. Antes compara el texto actual del
    Doc con el que quedó en la última publicación: si alguien lo editó
    (por ejemplo, las secciones a cargo del compañero), se detiene para
    no pisarlo. Los comentarios no cuentan como edición. `--forzar`
    publica igual."""
    est = _estado()
    inf = est["informe"]
    base = DIST / "informe_docx"
    if inf.get("doc_id") and inf.get("huella_publicada") and "--forzar" not in opciones:
        if _huella(cx.texto_doc(inf["doc_id"])) != inf["huella_publicada"]:
            raise SystemExit(
                "✗ El Doc tiene ediciones de texto posteriores a la última publicación. "
                "Traelas al repo antes de regenerar, o usá `informe --forzar` para pisarlas.")
    final = _armar_informe(inf)
    inf["doc_id"] = cx.docx_a_gdoc(final, est["carpetas"]["Informe"], "Informe", inf.get("doc_id"))
    inf["huella_publicada"] = _huella(cx.texto_doc(inf["doc_id"]))
    _guardar(est)
    pdf = cx.exportar_pdf(inf["doc_id"], base / "Informe.pdf")
    print(f"✓ Informe actualizado: https://docs.google.com/document/d/{inf['doc_id']}/edit")
    print(f"  PDF para revisar: {pdf.relative_to(RAIZ)}")


COMANDOS = {"informe": informe, "previa": previa, "docs": docs, "archivos": archivos, "estructura": estructura}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMANDOS:
        print(__doc__)
        raise SystemExit(1)
    COMANDOS[sys.argv[1]](*sys.argv[2:])
