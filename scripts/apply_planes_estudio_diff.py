"""Aplicador interactivo del diff auditado en ``PlanEstudioDB``.

Corre la misma comparación que :mod:`scripts.audit_planes_estudio` (de hecho
reusa sus helpers) y aplica las correcciones contra la versión **activa** de
cada carrera.

Comportamiento por tipo de discrepancia:

- **Divergentes** (mismo código en Excel y DB pero distinta ubicación
  curricular): se pregunta caso por caso — ``[a]plicar Excel``,
  ``[m]antener DB``, ``[s]kip``, ``[q]uit y descartar todo``.
- **Faltantes** (Excel tiene la fila, DB no la tiene): sólo se aplican
  cuando existe una :class:`MateriaDB` con ese código. Se pregunta UNA vez
  antes de arrancar el bloque si aplicar todas las candidatas.
- **Sobrantes** (DB tiene, Excel no): NO se tocan. Se reportan al final.

Antes del commit final se muestra un resumen y se pide confirmación
explícita. Se escribe un backup JSON con el estado previo de todas las
filas mutadas (``project/2. Desarrollo/backups/plan_estudio_<ts>.json``).

Uso:

    python -m scripts.apply_planes_estudio_diff
    python -m scripts.apply_planes_estudio_diff --carreras C,E,M
    python -m scripts.apply_planes_estudio_diff --dry-run
    python -m scripts.apply_planes_estudio_diff --yes   # peligroso

Para revertir un cambio ya aplicado, ver el stub
:func:`revert_from_backup` al final del archivo.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Iterator, Optional

from sqlmodel import Session, select

from scripts.audit_planes_estudio import (
    EXCEL_PATH,
    MateriaDBRow,
    MateriaExcel,
    ReporteCarrera,
    _cargar_db_por_carrera,
    comparar,
    parse_excel,
)
from src.database.connection import engine
from src.database.models import (
    CarreraDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
)
from src.services.grupo_materia_service import get_plan_activo

BACKUP_DIR = Path("project/2. Desarrollo/backups")

# ============================================================================
# Estructuras internas
# ============================================================================


@dataclass
class DivergenciaDecision:
    """Decisión del usuario sobre una divergencia individual.

    ``accion`` ∈ {"aplicar", "mantener", "skip"}. Todas las divergencias
    sin decisión explícita quedan en "skip" (no se tocan).
    """

    carrera_codigo: str
    excel: MateriaExcel
    db: MateriaDBRow
    accion: str = "skip"


@dataclass
class FaltantePendiente:
    """Faltante que va a ser aplicado (insertado)."""

    carrera_codigo: str
    plan_version_id: str
    excel: MateriaExcel


@dataclass
class MateriaFaltanteCatalogo:
    """Faltante en Excel cuya ``MateriaDB`` no existe en el catálogo.

    Se reporta al final para que el operador la cree a mano antes de
    volver a correr el aplicador.
    """

    carrera_codigo: str
    excel: MateriaExcel


@dataclass
class PlanEstudioSnapshot:
    """Estado previo de una fila de ``PlanEstudioDB`` (o ``None`` si es INSERT)."""

    id: Optional[str]
    plan_version_id: str
    materia_codigo: str
    carrera_codigo: str
    anio_plan: Optional[int]
    cuatrimestre_plan: Optional[str]
    optativa: bool

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "plan_version_id": self.plan_version_id,
            "materia_codigo": self.materia_codigo,
            "carrera_codigo": self.carrera_codigo,
            "anio_plan": self.anio_plan,
            "cuatrimestre_plan": self.cuatrimestre_plan,
            "optativa": self.optativa,
        }


@dataclass
class BackupEntry:
    """Una operación registrada en el backup.

    ``kind`` ∈ {"update", "insert"}. Para ``update`` guardamos el
    ``before`` (para poder revertir); para ``insert``, ``before`` es
    ``None`` (revertir = DELETE por id).
    """

    kind: str
    carrera_codigo: str
    materia_codigo: str
    before: Optional[PlanEstudioSnapshot]
    after: PlanEstudioSnapshot

    def to_dict(self) -> dict:
        return {
            "kind": self.kind,
            "carrera_codigo": self.carrera_codigo,
            "materia_codigo": self.materia_codigo,
            "before": self.before.to_dict() if self.before is not None else None,
            "after": self.after.to_dict(),
        }


@dataclass
class ResumenEjecucion:
    """Contadores + listas para el resumen final."""

    actualizaciones_aplicadas: int = 0
    inserciones_aplicadas: int = 0
    divergencias_mantenidas: int = 0
    divergencias_skipped: int = 0
    sobrantes: list[MateriaDBRow] = field(default_factory=list)
    materias_faltantes_catalogo: list[MateriaFaltanteCatalogo] = field(
        default_factory=list,
    )
    carreras_sin_plan_activo: list[str] = field(default_factory=list)
    committed: bool = False
    dry_run: bool = False
    backup_path: Optional[Path] = None
    quit_early: bool = False


# ============================================================================
# Helpers de I/O
# ============================================================================


def _make_prompt_fn() -> Callable[[str], str]:
    """Devuelve una función que llama a ``input()`` real."""
    return input


def _iter_prompt_fn(respuestas: Iterable[str]) -> Callable[[str], str]:
    """Devuelve una función que consume respuestas de un iterable.

    Útil para tests: se pasa una lista de respuestas y cada llamada al
    prompt devuelve la siguiente.
    """
    it: Iterator[str] = iter(respuestas)

    def _fn(_msg: str) -> str:
        try:
            return next(it)
        except StopIteration:
            # Si el flujo pide más respuestas de las provistas, tratamos
            # como skip por default — el test debe proveer todas las que
            # espera.
            raise AssertionError(
                "El aplicador pidió más respuestas de las provistas por el test."
            )

    return _fn


def _fmt_ubicacion(anio, cuatri, optativa) -> str:
    tag = "opt" if optativa else "no-opt"
    return f"{anio}°{cuatri}, {tag}"


# ============================================================================
# Núcleo aplicable (testeable sin Excel)
# ============================================================================


def aplicar_diff(
    session: Session,
    *,
    reportes: list[ReporteCarrera],
    plan_activo_por_carrera: dict[str, PlanCarreraVersionDB],
    prompt: Callable[[str], str],
    dry_run: bool = False,
    skip_final_confirmation: bool = False,
    output=print,
) -> ResumenEjecucion:
    """Ejecuta el flujo interactivo sobre un conjunto pre-computado de reportes.

    Se separa del ``main`` para poder testearlo sin abrir el Excel ni la
    DB de disco: los tests le pasan reportes armados a mano y un
    ``prompt`` mockeado.

    ``plan_activo_por_carrera`` debe traer las versiones activas de las
    carreras que aparecen en ``reportes``. Las carreras sin versión
    activa deben venir omitidas del dict — ``aplicar_diff`` las skipea
    con warning y las registra en el resumen.
    """
    resumen = ResumenEjecucion(dry_run=dry_run)

    # Fase 1: recolectar decisiones de divergencias.
    decisiones: list[DivergenciaDecision] = []
    quit_flag = False

    for reporte in reportes:
        if quit_flag:
            break
        car_cod = reporte.carrera_codigo
        pv = plan_activo_por_carrera.get(car_cod)
        if pv is None:
            resumen.carreras_sin_plan_activo.append(car_cod)
            continue

        resumen.sobrantes.extend(reporte.sobrantes)

        if not reporte.divergentes:
            continue

        output(
            f"\n=== Divergencias en {car_cod} — {reporte.carrera_nombre} "
            f"({len(reporte.divergentes)}) ==="
        )
        for ex, db in reporte.divergentes:
            output(
                f"[{car_cod} · {ex.codigo}] "
                f"DB: {_fmt_ubicacion(db.anio, db.cuatri, db.optativa)} · "
                f"Excel: {_fmt_ubicacion(ex.anio, ex.cuatri, ex.optativa)}"
            )
            while True:
                r = prompt(
                    "[a]plicar Excel / [m]antener DB / [s]kip / "
                    "[q]uit y descartar todo: "
                ).strip().lower()
                if r in ("a", "m", "s", "q"):
                    break
                output(
                    f"Respuesta '{r}' inválida — usar una de a/m/s/q."
                )
            if r == "q":
                output("Se descartan TODAS las decisiones y no se toca la DB.")
                quit_flag = True
                break
            accion = {"a": "aplicar", "m": "mantener", "s": "skip"}[r]
            decisiones.append(DivergenciaDecision(
                carrera_codigo=car_cod, excel=ex, db=db, accion=accion,
            ))
            if accion == "mantener":
                resumen.divergencias_mantenidas += 1
            elif accion == "skip":
                resumen.divergencias_skipped += 1

    if quit_flag:
        resumen.quit_early = True
        return resumen

    # Fase 2: recolectar faltantes candidatos.
    faltantes_candidatos: list[FaltantePendiente] = []
    for reporte in reportes:
        car_cod = reporte.carrera_codigo
        pv = plan_activo_por_carrera.get(car_cod)
        if pv is None:
            continue
        for ex in reporte.faltantes:
            existe = session.get(MateriaDB, ex.codigo) is not None
            if not existe:
                resumen.materias_faltantes_catalogo.append(
                    MateriaFaltanteCatalogo(carrera_codigo=car_cod, excel=ex),
                )
                continue
            faltantes_candidatos.append(FaltantePendiente(
                carrera_codigo=car_cod, plan_version_id=pv.id, excel=ex,
            ))

    aplicar_faltantes = False
    if faltantes_candidatos:
        output(
            f"\n=== Faltantes con MateriaDB existente: "
            f"{len(faltantes_candidatos)} inserciones candidatas ==="
        )
        for f in faltantes_candidatos:
            output(
                f"  + [{f.carrera_codigo} · {f.excel.codigo}] "
                f"{_fmt_ubicacion(f.excel.anio, f.excel.cuatri, f.excel.optativa)}"
            )
        while True:
            r = prompt(
                f"¿Aplicar {len(faltantes_candidatos)} inserciones? [y/n]: "
            ).strip().lower()
            if r in ("y", "n"):
                break
            output(f"Respuesta '{r}' inválida — usar y/n.")
        aplicar_faltantes = r == "y"

    # Fase 3: resumen previo + confirmación final.
    updates_pendientes = [d for d in decisiones if d.accion == "aplicar"]
    inserts_pendientes = faltantes_candidatos if aplicar_faltantes else []

    output(
        f"\n=== Resumen a aplicar: {len(updates_pendientes)} actualizaciones "
        f"+ {len(inserts_pendientes)} inserciones ==="
    )
    if not updates_pendientes and not inserts_pendientes:
        output("No hay cambios que aplicar. Fin.")
        return resumen

    if not skip_final_confirmation:
        while True:
            r = prompt(
                "Confirmar y aplicar cambios? "
                "[y]es / [n]o (rollback): "
            ).strip().lower()
            if r in ("y", "n"):
                break
            output(f"Respuesta '{r}' inválida — usar y/n.")
        if r == "n":
            output("Cancelado por el usuario. Nada se aplica.")
            return resumen

    # Fase 4: mutaciones (todas en una transacción; rollback si dry-run).
    backup_entries: list[BackupEntry] = []

    for dec in updates_pendientes:
        row = session.exec(
            select(PlanEstudioDB).where(
                PlanEstudioDB.plan_version_id
                == plan_activo_por_carrera[dec.carrera_codigo].id,
                PlanEstudioDB.materia_codigo == dec.excel.codigo,
                PlanEstudioDB.carrera_codigo == dec.carrera_codigo,
            ).limit(1)
        ).first()
        if row is None:
            output(
                f"[WARN] no encontré fila para {dec.carrera_codigo}·"
                f"{dec.excel.codigo} al aplicar update — se ignora."
            )
            continue

        before = PlanEstudioSnapshot(
            id=row.id,
            plan_version_id=row.plan_version_id,
            materia_codigo=row.materia_codigo,
            carrera_codigo=row.carrera_codigo,
            anio_plan=row.anio_plan,
            cuatrimestre_plan=row.cuatrimestre_plan,
            optativa=row.optativa,
        )
        row.anio_plan = dec.excel.anio
        row.cuatrimestre_plan = dec.excel.cuatri
        row.optativa = dec.excel.optativa
        session.add(row)
        after = PlanEstudioSnapshot(
            id=row.id,
            plan_version_id=row.plan_version_id,
            materia_codigo=row.materia_codigo,
            carrera_codigo=row.carrera_codigo,
            anio_plan=row.anio_plan,
            cuatrimestre_plan=row.cuatrimestre_plan,
            optativa=row.optativa,
        )
        backup_entries.append(BackupEntry(
            kind="update",
            carrera_codigo=dec.carrera_codigo,
            materia_codigo=dec.excel.codigo,
            before=before,
            after=after,
        ))
        resumen.actualizaciones_aplicadas += 1

    for f in inserts_pendientes:
        new_id = str(uuid.uuid4())
        pe = PlanEstudioDB(
            id=new_id,
            plan_version_id=f.plan_version_id,
            materia_codigo=f.excel.codigo,
            carrera_codigo=f.carrera_codigo,
            anio_plan=f.excel.anio,
            cuatrimestre_plan=f.excel.cuatri,
            optativa=f.excel.optativa,
        )
        session.add(pe)
        after = PlanEstudioSnapshot(
            id=new_id,
            plan_version_id=f.plan_version_id,
            materia_codigo=f.excel.codigo,
            carrera_codigo=f.carrera_codigo,
            anio_plan=f.excel.anio,
            cuatrimestre_plan=f.excel.cuatri,
            optativa=f.excel.optativa,
        )
        backup_entries.append(BackupEntry(
            kind="insert",
            carrera_codigo=f.carrera_codigo,
            materia_codigo=f.excel.codigo,
            before=None,
            after=after,
        ))
        resumen.inserciones_aplicadas += 1

    # Backup ANTES del commit (así vale también en dry-run — sirve como
    # registro de "lo que hubiera pasado"). Sólo se escribe si hay algo.
    if backup_entries:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        path = BACKUP_DIR / f"plan_estudio_{ts}.json"
        payload = {
            "timestamp": ts,
            "dry_run": dry_run,
            "entries": [e.to_dict() for e in backup_entries],
        }
        path.write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        resumen.backup_path = path
        output(f"Backup escrito: {path}")

    if dry_run:
        session.rollback()
        output("[DRY RUN] rollback aplicado — no se persistió nada.")
    else:
        session.commit()
        resumen.committed = True
        output("Cambios persistidos.")

    return resumen


# ============================================================================
# Reporte final markdown-friendly
# ============================================================================


def render_resumen_final(resumen: ResumenEjecucion) -> str:
    lines: list[str] = []
    lines.append("## Resumen de la corrida")
    lines.append("")
    if resumen.quit_early:
        lines.append(
            "- **Ejecución abortada** por el usuario (`q`). No se aplicó nada."
        )
        return "\n".join(lines) + "\n"
    lines.append(f"- Modo: `{'dry-run' if resumen.dry_run else 'commit'}`")
    lines.append(
        f"- Actualizaciones aplicadas: {resumen.actualizaciones_aplicadas}"
    )
    lines.append(
        f"- Inserciones aplicadas: {resumen.inserciones_aplicadas}"
    )
    lines.append(
        f"- Divergencias mantenidas (DB gana): "
        f"{resumen.divergencias_mantenidas}"
    )
    lines.append(
        f"- Divergencias skipped: {resumen.divergencias_skipped}"
    )
    if resumen.backup_path is not None:
        lines.append(f"- Backup: `{resumen.backup_path}`")
    lines.append("")

    if resumen.carreras_sin_plan_activo:
        lines.append("### Carreras sin plan activo (se saltaron)")
        for c in resumen.carreras_sin_plan_activo:
            lines.append(f"- `{c}`")
        lines.append("")

    if resumen.materias_faltantes_catalogo:
        lines.append("### Materias faltantes en catálogo (crear a mano)")
        lines.append("")
        lines.append("| Carrera | Código | Nombre | Ubicación (Excel) |")
        lines.append("|---|---|---|---|")
        for m in resumen.materias_faltantes_catalogo:
            lines.append(
                f"| `{m.carrera_codigo}` | `{m.excel.codigo}` "
                f"| {m.excel.nombre} "
                f"| {_fmt_ubicacion(m.excel.anio, m.excel.cuatri, m.excel.optativa)} |"
            )
        lines.append("")

    if resumen.sobrantes:
        lines.append(
            "### Sobrantes en DB (no tocados — revisar a mano)"
        )
        lines.append("")
        lines.append("| Código | Nombre | Ubicación (DB) |")
        lines.append("|---|---|---|")
        for s in resumen.sobrantes:
            lines.append(
                f"| `{s.codigo}` | {s.nombre} "
                f"| {_fmt_ubicacion(s.anio, s.cuatri, s.optativa)} |"
            )
        lines.append("")

    return "\n".join(lines) + "\n"


# ============================================================================
# CLI
# ============================================================================


def _parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Aplica correcciones a PlanEstudioDB usando el Excel de "
            "planes como fuente de verdad."
        ),
    )
    p.add_argument(
        "--carreras",
        default=None,
        help=(
            "Lista separada por comas de códigos de carrera a procesar. "
            "Default: todas las que tengan diffs."
        ),
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Corre el flujo pero hace rollback al final.",
    )
    p.add_argument(
        "--yes",
        action="store_true",
        help=(
            "Saltea la confirmación final. Peligroso — usar sólo después "
            "de haber corrido con --dry-run."
        ),
    )
    p.add_argument(
        "--excel-path",
        default=str(EXCEL_PATH),
        help=f"Ruta al Excel fuente (default: {EXCEL_PATH}).",
    )
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = _parse_args(argv)
    excel_path = Path(args.excel_path)
    if not excel_path.exists():
        print(f"[ERROR] no existe el Excel: {excel_path}", file=sys.stderr)
        return 2

    filtro_carreras: Optional[set[str]] = None
    if args.carreras:
        filtro_carreras = {
            c.strip().upper() for c in args.carreras.split(",") if c.strip()
        }

    print(f"Leyendo Excel: {excel_path}")
    excel_data = parse_excel(excel_path)

    with Session(engine) as session:
        db_data = _cargar_db_por_carrera(session)

        # Armo reportes filtrando por --carreras si corresponde.
        reportes: list[ReporteCarrera] = []
        plan_activo_por_carrera: dict[str, PlanCarreraVersionDB] = {}
        for car_cod, (car, db_rows) in sorted(db_data.items()):
            if filtro_carreras is not None and car_cod.upper() not in filtro_carreras:
                continue
            excel_rows = excel_data.get(car_cod, [])
            r = comparar(excel_rows, db_rows, car)
            if r.total_diffs == 0:
                continue
            reportes.append(r)
            pv = get_plan_activo(session, car_cod)
            if pv is not None:
                plan_activo_por_carrera[car_cod] = pv

        if not reportes:
            print("No hay divergencias/faltantes/sobrantes para procesar.")
            return 0

        print(
            f"Carreras con diffs a procesar: "
            f"{', '.join(r.carrera_codigo for r in reportes)}"
        )

        resumen = aplicar_diff(
            session,
            reportes=reportes,
            plan_activo_por_carrera=plan_activo_por_carrera,
            prompt=_make_prompt_fn(),
            dry_run=args.dry_run,
            skip_final_confirmation=args.yes,
        )

    print()
    print(render_resumen_final(resumen))
    return 0


# ============================================================================
# Reversibilidad (stub)
# ============================================================================


def revert_from_backup(
    backup_path: Path, *, session: Optional[Session] = None,
) -> None:
    """Revierte las mutaciones registradas en un backup JSON.

    **Stub**: la implementación completa queda pendiente. La firma y la
    idea son las siguientes:

    - Se leen las entries del JSON.
    - Para cada entry ``kind="update"``: se relocaliza la fila por ``id``
      (que sobrevive al UPDATE) y se restaura ``anio_plan``,
      ``cuatrimestre_plan``, ``optativa`` con los valores de ``before``.
    - Para cada entry ``kind="insert"``: se borra la fila con ``id`` del
      ``after`` (esa fila la creó el aplicador).
    - Todo dentro de una única transacción.
    - Si ``session`` es ``None``, se abre una nueva contra
      ``src.database.connection.engine``.

    Nota práctica: si se corrió el aplicador con ``--dry-run``, igual se
    escribió el backup — llamar a ``revert_from_backup`` sobre él sería
    no-op contra la DB (los cambios nunca se persistieron). El campo
    ``dry_run`` del JSON permite detectar ese caso.
    """
    raise NotImplementedError(
        "revert_from_backup: implementación pendiente. Ver docstring."
    )


if __name__ == "__main__":
    sys.exit(main())
