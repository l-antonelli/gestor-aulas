"""Tests para grupo_materia_service.py."""

from __future__ import annotations

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    GrupoMateriaSedeDB,
    MateriaDB,
    SedeDB,
)
from src.services.grupo_materia_service import (
    asignar_materia_a_grupo,
    contar_materias_por_grupo,
    create_grupo,
    delete_grupo,
    get_config_grupo,
    get_grupo,
    get_grupo_por_nombre,
    get_grupo_sin_clasificar,
    list_grupos,
    list_materias_por_grupo,
    list_materias_sin_clasificar,
    resolver_grupo_de_materia,
    resolver_sedes_admisibles_por_materia,
    update_grupo,
)


@pytest.fixture(name="engine")
def engine_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    return eng


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


def _seed_sedes(session: Session) -> dict[str, str]:
    """Crea 3 sedes (S1/S2/S3) y devuelve {nombre: id}."""
    s1 = SedeDB(id="S1", nombre="Sede 1")
    s2 = SedeDB(id="S2", nombre="Sede 2")
    s3 = SedeDB(id="S3", nombre="Sede 3")
    session.add_all([s1, s2, s3])
    session.commit()
    return {"S1": "S1", "S2": "S2", "S3": "S3"}


def _add_materia(session: Session, codigo: str, grupo_id: str | None = None) -> MateriaDB:
    m = MateriaDB(codigo=codigo, nombre=f"Materia {codigo}", grupo_id=grupo_id)
    session.add(m)
    session.commit()
    session.refresh(m)
    return m


class TestCreateGrupo:

    def test_create_duro_con_sedes(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "FB", "DURO", ["S1", "S2"])
        assert g.nombre == "FB"
        assert g.modo == "DURO"
        assert g.es_sin_clasificar is False
        sedes, modo = get_config_grupo(session, g.id)
        assert sedes == ["S1", "S2"]
        assert modo == "DURO"

    def test_create_blando_conserva_orden(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "Elec", "BLANDO", ["S3", "S1", "S2"])
        sedes, modo = get_config_grupo(session, g.id)
        assert sedes == ["S3", "S1", "S2"]
        assert modo == "BLANDO"

    def test_create_lista_vacia(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "Vacio", "DURO", [])
        sedes, modo = get_config_grupo(session, g.id)
        assert sedes == []
        assert modo == "DURO"

    def test_create_modo_invalido(self, session):
        _seed_sedes(session)
        with pytest.raises(ValueError, match="modo debe ser"):
            create_grupo(session, "X", "SEMI", ["S1"])  # type: ignore[arg-type]

    def test_create_nombre_duplicado(self, session):
        _seed_sedes(session)
        create_grupo(session, "X", "DURO", ["S1"])
        with pytest.raises(ValueError, match="Ya existe un grupo"):
            create_grupo(session, "X", "BLANDO", ["S2"])

    def test_create_sin_clasificar_unico(self, session):
        _seed_sedes(session)
        create_grupo(session, "SC1", "DURO", [], es_sin_clasificar=True)
        with pytest.raises(ValueError, match="Ya existe un grupo 'Sin clasificar'"):
            create_grupo(session, "SC2", "DURO", [], es_sin_clasificar=True)


class TestUpdateGrupo:

    def test_update_reemplaza_sedes(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1"])
        update_grupo(session, g.id, "G1", "BLANDO", ["S2", "S3"])
        sedes, modo = get_config_grupo(session, g.id)
        assert sedes == ["S2", "S3"]
        assert modo == "BLANDO"

    def test_update_renombra(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "Viejo", "DURO", ["S1"])
        update_grupo(session, g.id, "Nuevo", "DURO", ["S1"])
        assert get_grupo(session, g.id).nombre == "Nuevo"

    def test_update_nombre_colisiona(self, session):
        _seed_sedes(session)
        create_grupo(session, "A", "DURO", ["S1"])
        gb = create_grupo(session, "B", "DURO", ["S1"])
        with pytest.raises(ValueError, match="Ya existe otro grupo"):
            update_grupo(session, gb.id, "A", "DURO", ["S1"])

    def test_update_permite_mismo_nombre(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "A", "DURO", ["S1"])
        # Renombrar a lo mismo no debe fallar.
        update_grupo(session, g.id, "A", "BLANDO", ["S2"])
        assert get_grupo(session, g.id).modo == "BLANDO"


class TestDeleteGrupo:

    def test_delete_grupo_vacio(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1"])
        delete_grupo(session, g.id)
        assert get_grupo_por_nombre(session, "G1") is None

    def test_delete_con_materias_falla(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1"])
        _add_materia(session, "M1", grupo_id=g.id)
        with pytest.raises(ValueError, match="tiene materias asignadas"):
            delete_grupo(session, g.id)

    def test_delete_sin_clasificar_falla(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "SC", "DURO", [], es_sin_clasificar=True)
        with pytest.raises(ValueError, match="No se puede borrar el grupo 'Sin clasificar'"):
            delete_grupo(session, g.id)


class TestAsignarMateria:

    def test_asignar_actualiza_grupo(self, session):
        _seed_sedes(session)
        g1 = create_grupo(session, "G1", "DURO", ["S1"])
        g2 = create_grupo(session, "G2", "DURO", ["S2"])
        _add_materia(session, "M1", grupo_id=g1.id)
        asignar_materia_a_grupo(session, "M1", g2.id)
        m = session.get(MateriaDB, "M1")
        assert m is not None and m.grupo_id == g2.id

    def test_asignar_materia_inexistente(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1"])
        with pytest.raises(ValueError, match="Materia .* no encontrada"):
            asignar_materia_a_grupo(session, "NOEXISTE", g.id)

    def test_asignar_grupo_inexistente(self, session):
        _seed_sedes(session)
        _add_materia(session, "M1")
        with pytest.raises(ValueError, match="no encontrado"):
            asignar_materia_a_grupo(session, "M1", "grupo-fantasma")


class TestListMaterias:

    def test_list_por_grupo(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1"])
        _add_materia(session, "M2", grupo_id=g.id)
        _add_materia(session, "M1", grupo_id=g.id)
        materias = list_materias_por_grupo(session, g.id)
        codigos = [m.codigo for m in materias]
        assert codigos == ["M1", "M2"]  # orden por codigo

    def test_list_sin_clasificar(self, session):
        _seed_sedes(session)
        sc = create_grupo(session, "SC", "DURO", [], es_sin_clasificar=True)
        create_grupo(session, "Otro", "DURO", ["S1"])
        _add_materia(session, "MA", grupo_id=sc.id)
        materias = list_materias_sin_clasificar(session)
        assert [m.codigo for m in materias] == ["MA"]

    def test_list_sin_clasificar_sin_grupo_falla(self, session):
        _seed_sedes(session)
        with pytest.raises(ValueError, match="No existe un grupo"):
            list_materias_sin_clasificar(session)


class TestResolverPorMateria:

    def test_resolver_devuelve_grupo(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", ["S1", "S2"])
        _add_materia(session, "M1", grupo_id=g.id)
        sedes, modo = resolver_sedes_admisibles_por_materia(session, "M1")
        assert sedes == ["S1", "S2"]
        assert modo == "DURO"

    def test_resolver_sin_grupo_asigna_a_sin_clasificar(self, session):
        _seed_sedes(session)
        # Grupo sin clasificar tiene S1
        sc = create_grupo(
            session, "SC", "DURO", ["S1"], es_sin_clasificar=True,
        )
        _add_materia(session, "M1", grupo_id=None)
        # Antes de resolver: grupo_id es None.
        grupo = resolver_grupo_de_materia(session, "M1")
        assert grupo.id == sc.id
        # Ahora la materia quedó asignada.
        m = session.get(MateriaDB, "M1")
        assert m is not None and m.grupo_id == sc.id

    def test_resolver_grupo_vacio_devuelve_lista_vacia(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "DURO", [])
        _add_materia(session, "M1", grupo_id=g.id)
        sedes, modo = resolver_sedes_admisibles_por_materia(session, "M1")
        assert sedes == []
        assert modo == "DURO"


class TestListGrupos:

    def test_list_ordenado_por_nombre(self, session):
        _seed_sedes(session)
        create_grupo(session, "Zeta", "DURO", ["S1"])
        create_grupo(session, "Alpha", "DURO", ["S1"])
        create_grupo(session, "Mid", "DURO", ["S1"])
        grupos = list_grupos(session)
        assert [g.nombre for g in grupos] == ["Alpha", "Mid", "Zeta"]

    def test_get_grupo_sin_clasificar_falla_si_no_existe(self, session):
        _seed_sedes(session)
        create_grupo(session, "G1", "DURO", ["S1"])
        with pytest.raises(ValueError, match="No existe un grupo"):
            get_grupo_sin_clasificar(session)


class TestContarMaterias:

    def test_contar_agrupa_correctamente(self, session):
        _seed_sedes(session)
        g1 = create_grupo(session, "G1", "DURO", ["S1"])
        g2 = create_grupo(session, "G2", "DURO", ["S2"])
        _add_materia(session, "M1", grupo_id=g1.id)
        _add_materia(session, "M2", grupo_id=g1.id)
        _add_materia(session, "M3", grupo_id=g2.id)
        counts = contar_materias_por_grupo(session)
        assert counts[g1.id] == 2
        assert counts[g2.id] == 1

    def test_contar_ignora_materias_sin_grupo(self, session):
        _seed_sedes(session)
        g1 = create_grupo(session, "G1", "DURO", ["S1"])
        _add_materia(session, "M1", grupo_id=g1.id)
        _add_materia(session, "M2", grupo_id=None)
        counts = contar_materias_por_grupo(session)
        assert counts.get(g1.id) == 1
        # Ninguna clave "None" en el dict.
        assert None not in counts


class TestGrupoMateriaSedeDB_orden:
    """Sanity checks sobre el modelo de orden persistido."""

    def test_update_reindexa_orden(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G1", "BLANDO", ["S1", "S2", "S3"])
        update_grupo(session, g.id, "G1", "BLANDO", ["S3", "S1"])
        rows = session.exec(
            GrupoMateriaSedeDB.__table__.select().where(  # type: ignore[attr-defined]
                GrupoMateriaSedeDB.grupo_id == g.id,
            )
        ).all()
        rows_sorted = sorted(rows, key=lambda r: r.orden)
        assert [r.sede_id for r in rows_sorted] == ["S3", "S1"]
        assert [r.orden for r in rows_sorted] == [0, 1]
