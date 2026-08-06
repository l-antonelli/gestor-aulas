"""Servicio de gestión de la serie histórica de inscripciones.

Funciones para guardar/consultar `InscripcionHistoricaDB` con la
semántica correcta cuando la UI aplica un filtro de cuatrimestre.

Contexto (H01 del HALLAZGOS_AUDITORIA):
El editor de la página `📈 Inscriptos` tiene un filtro superior de
cuatrimestre (1C / 2C / Anual / Todos) que solamente restringe qué
registros se **muestran** en el editor. La lógica original guardaba
con "borrar toda la materia + reinsertar lo del editor", lo cual
borraba silenciosamente los registros del cuatri no visible. Este
servicio corrige eso: el borrado se limita al conjunto de cuatris
que el usuario está viendo.
"""

from dataclasses import dataclass
from typing import Iterable

from sqlmodel import Session, col, select

from src.database.models import InscripcionHistoricaDB


CUATRIS_VALIDOS = {"1C", "2C", "Anual"}


@dataclass(frozen=True)
class RegistroInscripcion:
    """Representa una fila del editor de Inscriptos.

    No es una entidad — solo un DTO para desacoplar el service de la
    representación (pandas DataFrame, dict, etc.) que use la UI.
    """
    anio: int
    cuatrimestre: str
    inscriptos: int


def guardar_registros_materia(
    session: Session,
    materia_codigo: str,
    registros: Iterable[RegistroInscripcion],
    *,
    cuatris_visibles: set[str],
) -> int:
    """Guarda los `registros` para `materia_codigo`, restringiendo el
    scope al conjunto de `cuatris_visibles`.

    Semántica:

    1. Los registros de la materia cuyos cuatrimestres **están** en
       `cuatris_visibles` se sincronizan con `registros`:
       - Filas en `registros` que ya existen (misma PK) → UPDATE.
       - Filas en `registros` que no existen → INSERT.
       - Filas en DB para cuatris visibles que **no** están en
         `registros` → DELETE (el usuario las eliminó del editor).
    2. Los registros de cuatrimestres **fuera** de `cuatris_visibles`
       se preservan intactos.

    Todas las filas de `registros` deben tener `cuatrimestre` en
    `cuatris_visibles`. Si alguna cae fuera, se levanta `ValueError`
    (indica un bug en la UI que no debería pasar).

    Args:
        session: sesión SQLModel activa (el commit lo hace el service).
        materia_codigo: PK de la materia.
        registros: iterable de `RegistroInscripcion`. Puede ser vacío
            (equivale a borrar todos los registros visibles).
        cuatris_visibles: conjunto no vacío con los cuatris que el
            usuario está viendo en el editor (típicamente `{"1C"}`,
            `{"2C"}` o `{"1C", "2C", "Anual"}` para "Todos"). Determina
            el scope del borrado.

    Returns:
        cantidad de filas persistidas (insert + update).

    Raises:
        ValueError: si `cuatris_visibles` está vacío, si un registro
            tiene `cuatrimestre` fuera de los visibles, o si algún
            campo es inválido (inscriptos negativos, cuatri desconocido).
    """
    if not cuatris_visibles:
        raise ValueError(
            "cuatris_visibles no puede estar vacío. Al menos un "
            "cuatrimestre tiene que estar activo en el filtro."
        )

    cuatris_invalidos = cuatris_visibles - CUATRIS_VALIDOS
    if cuatris_invalidos:
        raise ValueError(
            f"cuatris_visibles tiene valores desconocidos: "
            f"{sorted(cuatris_invalidos)}. Válidos: {sorted(CUATRIS_VALIDOS)}."
        )

    registros_list = list(registros)

    for r in registros_list:
        if r.cuatrimestre not in cuatris_visibles:
            raise ValueError(
                f"El registro (año={r.anio}, cuatri='{r.cuatrimestre}') "
                f"está fuera del cuatrimestre visible "
                f"({sorted(cuatris_visibles)}). Esto indica un bug en la "
                f"UI que no debería enviar filas de cuatris ocultos."
            )
        if r.inscriptos < 0:
            raise ValueError(
                f"inscriptos no puede ser negativo (año={r.anio}, "
                f"cuatri='{r.cuatrimestre}', valor={r.inscriptos})."
            )

    # 1) Traer las filas existentes de la materia para los cuatris visibles.
    existentes = session.exec(
        select(InscripcionHistoricaDB)
        .where(InscripcionHistoricaDB.materia_codigo == materia_codigo)
        .where(col(InscripcionHistoricaDB.cuatrimestre).in_(cuatris_visibles))
    ).all()
    existentes_por_pk = {
        (row.anio, row.cuatrimestre): row for row in existentes
    }

    # 2) Aplicar diff.
    editor_pks = {(r.anio, r.cuatrimestre) for r in registros_list}
    persistidas = 0

    # Update / insert.
    for r in registros_list:
        pk = (r.anio, r.cuatrimestre)
        row = existentes_por_pk.get(pk)
        if row is None:
            session.add(InscripcionHistoricaDB(
                materia_codigo=materia_codigo,
                anio=r.anio,
                cuatrimestre=r.cuatrimestre,
                inscriptos=r.inscriptos,
            ))
        else:
            row.inscriptos = r.inscriptos
            session.add(row)
        persistidas += 1

    # Delete: filas en DB para cuatris visibles que ya no están en el editor.
    for pk, row in existentes_por_pk.items():
        if pk not in editor_pks:
            session.delete(row)

    session.commit()
    return persistidas
