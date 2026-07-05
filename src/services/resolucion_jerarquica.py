"""Resolución de atributos compartidos en jerarquías de entidades.

Regla general: **el nivel más específico manda**. Cada nivel puede ser
``None`` (heredar del padre) o un valor concreto (fuerza ese valor,
ignorando padres). La resolución camina desde el nivel más específico
hacia la raíz hasta encontrar el primer valor no-``None``.

Ejemplos de cadenas:

- ``virtual``: ``HorarioDB.virtual`` (Optional[bool]) →
  ``DictadoDB.virtual`` (Optional[bool]) → ``MateriaDB.virtual`` (bool).
- ``dicta_recursado``: ``MateriaDB.dicta_recursado`` (Optional[bool]) →
  ``CarreraDB.dicta_recursado`` (bool).

Los helpers reciben los valores en crudo (no leen DB) para poder
usarse desde cualquier lugar sin acoplar la lógica de resolución al
loading de las entidades. Los callers cargan las entidades como
prefieran (join, dicts pre-computados, etc.) y pasan los flags.
"""

from __future__ import annotations


def resolve_virtual(
    horario_virtual: bool | None,
    dictado_virtual: bool | None,
    materia_virtual: bool,
) -> bool:
    """Resuelve si un horario es virtual, aplicando la regla "nivel más
    específico manda".

    Args:
        horario_virtual: valor de ``HorarioDB.virtual``. ``None`` =
            heredar del dictado.
        dictado_virtual: valor de ``DictadoDB.virtual``. ``None`` =
            heredar de la materia.
        materia_virtual: valor de ``MateriaDB.virtual``. Es la raíz de
            la cadena, siempre concreto.

    Returns:
        ``True`` si el horario se considera virtual (no ocupa aula),
        ``False`` en caso contrario.

    Ejemplos:

        >>> resolve_virtual(None, None, True)   # heredado de materia
        True
        >>> resolve_virtual(None, True, False)  # dictado fuerza virtual
        True
        >>> resolve_virtual(False, True, True)  # horario fuerza presencial
        False
        >>> resolve_virtual(True, None, False)  # horario fuerza virtual
        True
    """
    if horario_virtual is not None:
        return horario_virtual
    if dictado_virtual is not None:
        return dictado_virtual
    return materia_virtual


def resolve_dicta_recursado(
    materia_dicta_recursado: bool | None,
    carrera_dicta_recursado: bool,
) -> bool:
    """Resuelve si una materia dicta en modo recursado, aplicando la
    regla "nivel más específico manda".

    Args:
        materia_dicta_recursado: valor de
            ``MateriaDB.dicta_recursado``. ``None`` = heredar de la
            carrera.
        carrera_dicta_recursado: valor de ``CarreraDB.dicta_recursado``.
            Es la raíz, siempre concreto.

    Returns:
        ``True`` si la materia dicta cuando toca recursado, ``False``
        en caso contrario.
    """
    if materia_dicta_recursado is not None:
        return materia_dicta_recursado
    return carrera_dicta_recursado
