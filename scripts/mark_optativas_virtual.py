"""One-shot: marca virtual=True a todas las materias optativas y a sus dictados.

Una materia se considera optativa si:
- `MateriaDB.optativa == True`, o
- aparece como optativa en cualquier `PlanEstudioDB.optativa == True`.

Para cada una de esas materias:
- Setea `MateriaDB.virtual = True`.
- Setea `DictadoDB.virtual = True` para todos los dictados ya creados de esa
  materia (en cualquier ciclo).

Uso:
    python -m scripts.mark_optativas_virtual           # corre el update
    python -m scripts.mark_optativas_virtual --dry-run # solo muestra que cambiaria
"""

from __future__ import annotations

import argparse
import sys

from sqlmodel import select, col

from src.database.connection import get_session, init_db
from src.database.models import DictadoDB, MateriaDB, PlanEstudioDB


def main(dry_run: bool = False) -> int:
    init_db()
    with next(get_session()) as session:
        # 1) Materias optativas (union: MateriaDB.optativa OR cualquier PE.optativa)
        opt_by_attr = set(session.exec(
            select(MateriaDB.codigo).where(MateriaDB.optativa == True)  # noqa: E712
        ).all())
        opt_by_pe = set(session.exec(
            select(PlanEstudioDB.materia_codigo)
            .where(PlanEstudioDB.optativa == True)  # noqa: E712
            .distinct()
        ).all())
        opt_codes = sorted(opt_by_attr | opt_by_pe)

        if not opt_codes:
            print("No hay materias optativas. Nada para hacer.")
            return 0

        # Cargar las materias para ver cuales ya estan virtuales
        mats = list(session.exec(
            select(MateriaDB).where(col(MateriaDB.codigo).in_(opt_codes))
        ).all())
        to_update_mats = [m for m in mats if not m.virtual]

        # Dictados existentes para esas materias
        dictados = list(session.exec(
            select(DictadoDB).where(col(DictadoDB.materia_codigo).in_(opt_codes))
        ).all())
        to_update_dicts = [d for d in dictados if not d.virtual]

        print(f"Materias optativas detectadas: {len(opt_codes)}")
        print(f"  · de attr MateriaDB.optativa: {len(opt_by_attr)}")
        print(f"  · de PlanEstudioDB.optativa:  {len(opt_by_pe)}")
        print(f"Materias que pasaran a virtual=True: {len(to_update_mats)}")
        print(f"Dictados que pasaran a virtual=True: {len(to_update_dicts)}")

        if dry_run:
            print("\n[DRY-RUN] No se aplican cambios.")
            print("Codigos afectados (materias):")
            for m in to_update_mats[:25]:
                print(f"  - {m.codigo}: {m.nombre}")
            if len(to_update_mats) > 25:
                print(f"  ... +{len(to_update_mats) - 25} mas")
            return 0

        for m in to_update_mats:
            m.virtual = True
            session.add(m)
        for d in to_update_dicts:
            d.virtual = True
            session.add(d)
        session.commit()

        print(
            f"\nOK: {len(to_update_mats)} materias y "
            f"{len(to_update_dicts)} dictados actualizados a virtual=True."
        )
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Solo muestra que cambiaria, sin aplicar.",
    )
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
