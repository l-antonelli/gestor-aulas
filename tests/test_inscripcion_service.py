"""Tests para inscripcion_service.

Cubre el fix de H01: guardar registros de una materia con un filtro de
cuatrimestre aplicado NO debe borrar los registros de los otros
cuatrimestres.
"""

import pytest

from sqlmodel import Session, SQLModel, create_engine, select
from sqlalchemy.pool import StaticPool

from src.database.models import MateriaDB, InscripcionHistoricaDB
from src.services.inscripcion_service import (
    RegistroInscripcion,
    guardar_registros_materia,
)


@pytest.fixture(name="engine")
def engine_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return engine


@pytest.fixture(name="session")
def session_fixture(engine):
    with Session(engine) as session:
        yield session


@pytest.fixture
def materia(session):
    m = MateriaDB(
        codigo="FIS 1.1", nombre="Fisica 1", horas_semanales=6, cupo=100,
    )
    session.add(m)
    session.commit()
    return m


def _seed_10_registros(session):
    """5 en 1C y 5 en 2C, años 2021-2025."""
    for anio in range(2021, 2026):
        session.add(InscripcionHistoricaDB(
            materia_codigo="FIS 1.1", anio=anio,
            cuatrimestre="1C", inscriptos=100 + anio - 2021,
        ))
        session.add(InscripcionHistoricaDB(
            materia_codigo="FIS 1.1", anio=anio,
            cuatrimestre="2C", inscriptos=200 + anio - 2021,
        ))
    session.commit()


class TestGuardarConFiltroCuatri:
    """El bug H01 crítico: guardar filtrado por 1C borraba silenciosamente
    los registros de 2C. Los tests de esta clase blindan el fix."""

    def test_guardar_1c_no_toca_2c(self, session, materia):
        _seed_10_registros(session)
        # Edito el registro 2024/1C (paso de 103 a 999) — no toco nada más.
        # Los registros que llegan al service son solo los del cuatri visible.
        registros_editor = [
            RegistroInscripcion(anio=2021, cuatrimestre="1C", inscriptos=100),
            RegistroInscripcion(anio=2022, cuatrimestre="1C", inscriptos=101),
            RegistroInscripcion(anio=2023, cuatrimestre="1C", inscriptos=102),
            RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=999),
            RegistroInscripcion(anio=2025, cuatrimestre="1C", inscriptos=104),
        ]
        guardar_registros_materia(
            session, "FIS 1.1", registros_editor,
            cuatris_visibles={"1C"},
        )

        # Los 5 de 2C deben seguir vivos e intactos.
        c2 = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "2C")
            .order_by(InscripcionHistoricaDB.anio)
        ).all()
        assert len(c2) == 5, f"esperaba 5 registros 2C, quedaron {len(c2)}"
        assert [r.inscriptos for r in c2] == [200, 201, 202, 203, 204]

        # Los 5 de 1C reflejan el edit.
        c1 = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "1C")
            .order_by(InscripcionHistoricaDB.anio)
        ).all()
        assert [r.inscriptos for r in c1] == [100, 101, 102, 999, 104]

    def test_guardar_2c_no_toca_1c(self, session, materia):
        _seed_10_registros(session)
        registros_editor = [
            RegistroInscripcion(anio=2021, cuatrimestre="2C", inscriptos=200),
            RegistroInscripcion(anio=2022, cuatrimestre="2C", inscriptos=888),
        ]
        guardar_registros_materia(
            session, "FIS 1.1", registros_editor,
            cuatris_visibles={"2C"},
        )
        # 1C intacto.
        c1 = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "1C")
        ).all()
        assert len(c1) == 5

    def test_guardar_con_todos_pisa_todo(self, session, materia):
        """Cuando el filtro es 'Todos', se guardan todos los cuatris
        visibles y las filas que no vienen en registros_editor SÍ se
        borran (comportamiento original preservado para ese caso)."""
        _seed_10_registros(session)
        registros_editor = [
            RegistroInscripcion(anio=2025, cuatrimestre="1C", inscriptos=555),
            RegistroInscripcion(anio=2025, cuatrimestre="2C", inscriptos=666),
        ]
        guardar_registros_materia(
            session, "FIS 1.1", registros_editor,
            cuatris_visibles={"1C", "2C", "Anual"},
        )
        total = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
        ).all()
        assert len(total) == 2

    def test_borrar_fila_del_editor_borra_solo_esa(self, session, materia):
        """Si el usuario borra una fila del editor (ej. 2023/1C), esa
        fila desaparece pero las otras del cuatri visible y todo el
        otro cuatri quedan intactas."""
        _seed_10_registros(session)
        registros_editor = [
            RegistroInscripcion(anio=2021, cuatrimestre="1C", inscriptos=100),
            RegistroInscripcion(anio=2022, cuatrimestre="1C", inscriptos=101),
            # falta 2023/1C — el usuario lo eliminó del editor
            RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=103),
            RegistroInscripcion(anio=2025, cuatrimestre="1C", inscriptos=104),
        ]
        guardar_registros_materia(
            session, "FIS 1.1", registros_editor,
            cuatris_visibles={"1C"},
        )
        c1 = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "1C")
            .order_by(InscripcionHistoricaDB.anio)
        ).all()
        assert [r.anio for r in c1] == [2021, 2022, 2024, 2025]
        # 2C intacto.
        c2_count = len(session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "2C")
        ).all())
        assert c2_count == 5

    def test_agregar_fila_nueva_inserta(self, session, materia):
        """Agregar una fila 2026/1C que no existía la debe insertar."""
        _seed_10_registros(session)
        registros_editor = [
            RegistroInscripcion(anio=2021, cuatrimestre="1C", inscriptos=100),
            RegistroInscripcion(anio=2022, cuatrimestre="1C", inscriptos=101),
            RegistroInscripcion(anio=2023, cuatrimestre="1C", inscriptos=102),
            RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=103),
            RegistroInscripcion(anio=2025, cuatrimestre="1C", inscriptos=104),
            RegistroInscripcion(anio=2026, cuatrimestre="1C", inscriptos=999),
        ]
        guardar_registros_materia(
            session, "FIS 1.1", registros_editor,
            cuatris_visibles={"1C"},
        )
        c1 = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
            .where(InscripcionHistoricaDB.cuatrimestre == "1C")
            .order_by(InscripcionHistoricaDB.anio)
        ).all()
        assert [r.anio for r in c1] == list(range(2021, 2027))
        assert c1[-1].inscriptos == 999


class TestValidaciones:
    """Casos borde y validaciones."""

    def test_registro_con_cuatri_fuera_del_visible_es_rechazado(
        self, session, materia,
    ):
        """Si el editor tiene filtro 1C, no debería llegar una fila 2C.
        Si llega, el service lo debe rechazar (defensivo)."""
        registros_editor = [
            RegistroInscripcion(anio=2024, cuatrimestre="2C", inscriptos=999),
        ]
        with pytest.raises(ValueError, match="fuera del cuatrimestre visible"):
            guardar_registros_materia(
                session, "FIS 1.1", registros_editor,
                cuatris_visibles={"1C"},
            )

    def test_lista_vacia_borra_solo_visibles(self, session, materia):
        """Guardar lista vacía con filtro 1C borra sólo los 1C."""
        _seed_10_registros(session)
        guardar_registros_materia(
            session, "FIS 1.1", [],
            cuatris_visibles={"1C"},
        )
        total = session.exec(
            select(InscripcionHistoricaDB)
            .where(InscripcionHistoricaDB.materia_codigo == "FIS 1.1")
        ).all()
        assert len(total) == 5
        assert all(r.cuatrimestre == "2C" for r in total)

    def test_inscriptos_negativos_falla(self, session, materia):
        registros_editor = [
            RegistroInscripcion(anio=2024, cuatrimestre="1C", inscriptos=-5),
        ]
        with pytest.raises(ValueError, match="inscriptos"):
            guardar_registros_materia(
                session, "FIS 1.1", registros_editor,
                cuatris_visibles={"1C"},
            )

    def test_cuatris_visibles_vacio_falla(self, session, materia):
        with pytest.raises(ValueError, match="cuatris_visibles"):
            guardar_registros_materia(
                session, "FIS 1.1", [],
                cuatris_visibles=set(),
            )
