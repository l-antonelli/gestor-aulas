"""Acceso a Google Drive y Google Docs a través de la CLI de Composio.

Requiere la CLI instalada y con sesión iniciada (`composio login`) y las
cuentas de Google Drive y Google Docs conectadas (`composio link
googledrive`, `composio link googledocs`).
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

CLI = shutil.which("composio") or str(Path.home() / ".local/bin/composio")
GDOC = "application/vnd.google-apps.document"
CARPETA = "application/vnd.google-apps.folder"


def run(slug: str, data: dict | None = None, file: str | None = None, reintentos: int = 2) -> dict:
    """Ejecuta una herramienta de Composio y devuelve `data`."""
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(data or {}, f, ensure_ascii=False)
    cmd = [CLI, "execute", slug, "-d", f"@{f.name}"]
    if file:
        cmd += ["--file", str(file)]
    out: dict = {}
    for intento in range(reintentos + 1):
        r = subprocess.run(cmd, capture_output=True, text=True)
        try:
            out = json.loads(r.stdout, strict=False)
        except json.JSONDecodeError:
            out = {"successful": False, "error": (r.stdout + r.stderr)[-800:]}
        if out.get("successful"):
            return out["data"]
        if intento < reintentos:
            time.sleep(3)
    raise RuntimeError(f"{slug} falló: {out.get('error')}")


def proxy(url: str, method: str = "GET", body: dict | None = None, toolkit: str = "googledrive") -> dict:
    """Llamada directa a la API de Google con la cuenta conectada."""
    cmd = [CLI, "proxy", url, "--toolkit", toolkit, "--method", method]
    if body is not None:
        cmd += ["-d", json.dumps(body, ensure_ascii=False)]
    r = subprocess.run(cmd, capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if r.returncode == 0 and not r.stdout.strip():
        return {}  # 204 sin cuerpo (por ejemplo, DELETE)
    try:
        return json.loads(r.stdout, strict=False)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"proxy {method} {url}: {(r.stdout + r.stderr)[-800:]}") from exc


def descargar(url_firmada: str, destino: Path) -> Path:
    destino.write_bytes(urllib.request.urlopen(url_firmada).read())
    return destino


def hijo(carpeta: str, nombre: str, mime: str | None = None) -> str | None:
    """ID del archivo `nombre` dentro de `carpeta` (no en la papelera)."""
    nombre_q = nombre.replace("\\", "\\\\").replace("'", "\\'")
    q = f"'{carpeta}' in parents and trashed=false and name='{nombre_q}'"
    if mime:
        q += f" and mimeType='{mime}'"
    archivos = run("GOOGLEDRIVE_FIND_FILE", {"q": q, "fields": "files(id)", "pageSize": 10}).get("files", [])
    return archivos[0]["id"] if archivos else None


def asegurar_carpeta(padre: str, nombre: str) -> str:
    fid = hijo(padre, nombre, CARPETA)
    if fid:
        return fid
    d = run("GOOGLEDRIVE_CREATE_FOLDER", {"name": nombre, "parent_id": padre})
    return d.get("id") or d["folder_id"]


def a_papelera(fid: str) -> None:
    """A la papelera (recuperable), nunca borrado definitivo."""
    proxy(f"https://www.googleapis.com/drive/v3/files/{fid}", "PATCH", {"trashed": True})


def docx_a_gdoc(docx: Path, carpeta: str, nombre: str, existente: str | None) -> str:
    """Sube un .docx como Google Doc. Si `existente` es un Google Doc,
    actualiza su contenido en el lugar (mismo link, permisos y ubicación);
    si no, sube el .docx, crea la copia convertida y manda el .docx
    intermedio a la papelera."""
    if existente:
        run("GOOGLEDRIVE_UPLOAD_UPDATE_FILE", {"fileId": existente, "uploadType": "media"}, file=str(docx))
        return existente
    subido = run("GOOGLEDRIVE_UPLOAD_FILE", {"folder_to_upload_to": carpeta}, file=str(docx))
    doc = run("GOOGLEDRIVE_COPY_FILE_ADVANCED", {
        "fileId": subido["id"], "name": nombre, "mimeType": GDOC,
        "parents": [carpeta], "fields": "id"})
    a_papelera(subido["id"])
    return doc["id"]


def exportar_pdf(fid: str, destino: Path) -> Path:
    d = run("GOOGLEDRIVE_EXPORT_GOOGLE_WORKSPACE_FILE", {"fileId": fid, "mimeType": "application/pdf"})
    return descargar(d["file"]["s3url"], destino)


def exportar_pestana_docx(doc_id: str, tab_id: str, destino: Path) -> Path:
    """Exporta una pestaña de un Google Doc como .docx."""
    d = proxy(f"https://docs.google.com/document/d/{doc_id}/export?format=docx&tab={tab_id}",
              toolkit="googledocs")
    return descargar(d["binary_data"]["url"], destino)


def texto_doc(doc_id: str, revision_link: str | None = None) -> str:
    """Texto plano del Google Doc (o de una revisión), sin las marcas
    que Google agrega por cada comentario ("[a]", "[b]"...) ni el bloque
    final con el texto de los comentarios. Sirve para detectar
    ediciones de texto ignorando los comentarios."""
    import re
    url = revision_link or f"https://docs.google.com/document/d/{doc_id}/export?format=txt"
    r = subprocess.run([CLI, "proxy", url, "--toolkit", "googledrive", "--method", "GET"],
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    t = r.stdout
    corte = re.search(r"\n\[a\][^\n]*\n", t)
    if corte:
        t = t[:corte.start()]
    t = re.sub(r"\[[a-z]{1,2}\]", "", t)
    return "\n".join(l.rstrip() for l in t.splitlines() if l.strip())
