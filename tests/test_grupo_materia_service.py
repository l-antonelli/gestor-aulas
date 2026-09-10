"""Tests para grupo_materia_service.py con el modelo nuevo (2026-09-09):
cada grupo declara AMBAS configuraciones de sede (set DURO y lista
BLANDA) al mismo tiempo, y puede asociarse a 0..N carreras.
"""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CarreraDB,
    GrupoMateriaDB,
    GrupoMateriaSedeDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
    SedeDB,
)
from src.services.grupo_materia_service import (
    asignar_materia_a_grupo,
    chequear_consistencia_grupo,
    contar_materias_por_grupo,
    create_grupo,
    delete_grupo,
    get_config_grupo,
    get_grupo,
    get_grupo_por_nombre,
    get_grupo_sin_clasificar,
    get_plan_activo,
    list_grupos,
    list_materias_por_grupo,
    list_materias_sin_clasificar,
    resolver_config_sedes_por_materia,
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

    def test_create_solo_duras(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G1", sedes_duras=["S1", "S2"],
        )
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == ["S1", "S2"]
        assert cfg.sedes_blandas_ordenadas == []

    def test_create_solo_blandas(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G_BLND",
            sedes_blandas_ordenadas=["S3", "S1", "S2"],
        )
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == []
        assert cfg.sedes_blandas_ordenadas == ["S3", "S1", "S2"]

    def test_create_ambas_configs(self, session):
        """Un grupo puede tener AMBAS configs a la vez."""
        _seed_sedes(session)
        g = create_grupo(
            session, "G_AMBAS",
            sedes_duras=["S1"],
            sedes_blandas_ordenadas=["S1", "S2", "S3"],
        )
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == ["S1"]
        assert cfg.sedes_blandas_ordenadas == ["S1", "S2", "S3"]

    def test_create_con_carreras_asociadas(self, session):
        _seed_sedes(session)
        session.add(CarreraDB(codigo="A", nombre="Carrera A"))
        session.add(CarreraDB(codigo="B", nombre="Carrera B"))
        session.commit()
        g = create_grupo(
            session, "G_CARR",
            sedes_duras=["S1"],
            carreras_asociadas=["A", "B"],
        )
        cfg = get_config_grupo(session, g.id)
        assert cfg.carreras_asociadas == ["A", "B"]

    def test_create_nombre_duplicado(self, session):
        _seed_sedes(session)
        create_grupo(session, "X", sedes_duras=["S1"])
        with pytest.raises(ValueError, match="Ya existe un grupo"):
            create_grupo(session, "X", sedes_duras=["S2"])

    def test_create_sin_clasificar_unico(self, session):
        _seed_sedes(session)
        create_grupo(session, "SC1", es_sin_clasificar=True)
        with pytest.raises(ValueError, match="Ya existe un grupo 'Sin clasificar'"):
            create_grupo(session, "SC2", es_sin_clasificar=True)


class TestUpdateGrupo:

    def test_update_solo_duras_preserva_blandas(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1"],
            sedes_blandas_ordenadas=["S2", "S3"],
        )
        update_grupo(session, g.id, sedes_duras=["S2"])
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == ["S2"]
        assert cfg.sedes_blandas_ordenadas == ["S2", "S3"]  # preservadas

    def test_update_solo_blandas_preserva_duras(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1"],
            sedes_blandas_ordenadas=["S2"],
        )
        update_grupo(session, g.id, sedes_blandas_ordenadas=["S3", "S1"])
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == ["S1"]
        assert cfg.sedes_blandas_ordenadas == ["S3", "S1"]

    def test_update_ambas_reemplaza(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1"],
            sedes_blandas_ordenadas=["S2"],
        )
        update_grupo(
            session, g.id,
            sedes_duras=["S3"],
            sedes_blandas_ordenadas=["S1", "S2"],
        )
        cfg = get_config_grupo(session, g.id)
        assert cfg.sedes_duras == ["S3"]
        assert cfg.sedes_blandas_ordenadas == ["S1", "S2"]

    def test_update_reemplaza_carreras(self, session):
        _seed_sedes(session)
        session.add(CarreraDB(codigo="A", nombre="A"))
        session.add(CarreraDB(codigo="B", nombre="B"))
        session.commit()
        g = create_grupo(
            session, "G",
            sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        update_grupo(session, g.id, carreras_asociadas=["B"])
        cfg = get_config_grupo(session, g.id)
        assert cfg.carreras_asociadas == ["B"]

    def test_update_renombra(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "Viejo", sedes_duras=["S1"])
        update_grupo(session, g.id, nombre="Nuevo")
        assert get_grupo(session, g.id).nombre == "Nuevo"

    def test_update_nombre_colisiona(self, session):
        _seed_sedes(session)
        create_grupo(session, "A", sedes_duras=["S1"])
        gb = create_grupo(session, "B", sedes_duras=["S1"])
        with pytest.raises(ValueError, match="Ya existe otro grupo"):
            update_grupo(session, gb.id, nombre="A")


class TestDeleteGrupo:

    def test_delete_grupo_vacio(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G", sedes_duras=["S1"])
        delete_grupo(session, g.id)
        assert get_grupo_por_nombre(session, "G") is None

    def test_delete_con_materias_falla(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G", sedes_duras=["S1"])
        _add_materia(session, "M1", grupo_id=g.id)
        with pytest.raises(ValueError, match="tiene materias asignadas"):
            delete_grupo(session, g.id)

    def test_delete_sin_clasificar_falla(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "SC", es_sin_clasificar=True)
        with pytest.raises(ValueError, match="No se puede borrar el grupo 'Sin clasificar'"):
            delete_grupo(session, g.id)


class TestAsignarMateria:

    def test_asignar_actualiza_grupo(self, session):
        _seed_sedes(session)
        g1 = create_grupo(session, "G1", sedes_duras=["S1"])
        g2 = create_grupo(session, "G2", sedes_duras=["S2"])
        _add_materia(session, "M1", grupo_id=g1.id)
        asignar_materia_a_grupo(session, "M1", g2.id)
        m = session.get(MateriaDB, "M1")
        assert m is not None and m.grupo_id == g2.id


class TestResolverPorMateria:

    def test_resolver_duro_devuelve_set_duro(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1", "S2"],
            sedes_blandas_ordenadas=["S3", "S1"],
        )
        _add_materia(session, "M1", grupo_id=g.id)
        sedes, modo = resolver_config_sedes_por_materia(
            session, "M1", "DURO",
        )
        assert set(sedes) == {"S1", "S2"}
        assert modo == "DURO"

    def test_resolver_blando_devuelve_lista_ordenada(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1", "S2"],
            sedes_blandas_ordenadas=["S3", "S1"],
        )
        _add_materia(session, "M1", grupo_id=g.id)
        sedes, modo = resolver_config_sedes_por_materia(
            session, "M1", "BLANDO",
        )
        assert sedes == ["S3", "S1"]
        assert modo == "BLANDO"

    def test_resolver_sin_grupo_fallback(self, session):
        _seed_sedes(session)
        _add_materia(session, "M1", grupo_id=None)
        # Sin grupo Sin clasificar, devuelve vacío.
        sedes, modo = resolver_config_sedes_por_materia(
            session, "M1", "DURO",
        )
        assert sedes == []
        assert modo == "DURO"


class TestListGrupos:

    def test_list_ordenado_por_nombre(self, session):
        _seed_sedes(session)
        create_grupo(session, "Zeta", sedes_duras=["S1"])
        create_grupo(session, "Alpha", sedes_duras=["S1"])
        create_grupo(session, "Mid", sedes_duras=["S1"])
        grupos = list_grupos(session)
        assert [g.nombre for g in grupos] == ["Alpha", "Mid", "Zeta"]


class TestListMaterias:

    def test_list_por_grupo(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G", sedes_duras=["S1"])
        _add_materia(session, "M2", grupo_id=g.id)
        _add_materia(session, "M1", grupo_id=g.id)
        materias = list_materias_por_grupo(session, g.id)
        assert [m.codigo for m in materias] == ["M1", "M2"]

    def test_list_sin_clasificar(self, session):
        _seed_sedes(session)
        sc = create_grupo(session, "SC", es_sin_clasificar=True)
        _add_materia(session, "MA", grupo_id=sc.id)
        materias = list_materias_sin_clasificar(session)
        assert [m.codigo for m in materias] == ["MA"]


class TestContarMaterias:

    def test_contar(self, session):
        _seed_sedes(session)
        g1 = create_grupo(session, "G1", sedes_duras=["S1"])
        g2 = create_grupo(session, "G2", sedes_duras=["S2"])
        _add_materia(session, "M1", grupo_id=g1.id)
        _add_materia(session, "M2", grupo_id=g1.id)
        _add_materia(session, "M3", grupo_id=g2.id)
        counts = contar_materias_por_grupo(session)
        assert counts[g1.id] == 2
        assert counts[g2.id] == 1


class TestSedeAmbosTipos:
    """Una misma sede puede aparecer en DURO y BLANDO al mismo tiempo."""

    def test_misma_sede_en_ambos(self, session):
        _seed_sedes(session)
        g = create_grupo(
            session, "G",
            sedes_duras=["S1"],
            sedes_blandas_ordenadas=["S1", "S2"],
        )
        rows = list(session.exec(
            GrupoMateriaSedeDB.__table__.select().where(  # type: ignore[attr-defined]
                GrupoMateriaSedeDB.grupo_id == g.id,
            )
        ).all())
        # Debería haber 1 fila DURO(S1) + 2 filas BLANDO(S1, S2).
        assert len(rows) == 3
        tipos = sorted((r.sede_id, r.tipo) for r in rows)
        assert tipos == [
            ("S1", "BLANDO"), ("S1", "DURO"), ("S2", "BLANDO"),
        ]


class TestChequeoConsistencia:
    """Chequeo de consistencia grupo↔carreras asociadas."""

    def _seed_plan(
        self, session, carrera_codigo: str, materias: list[str],
        activo: bool = True, plan_id: str | None = None,
    ) -> str:
        if session.get(CarreraDB, carrera_codigo) is None:
            session.add(CarreraDB(
                codigo=carrera_codigo, nombre=f"Carrera {carrera_codigo}",
            ))
        pv_id = plan_id or f"pv-{carrera_codigo}"
        session.add(PlanCarreraVersionDB(
            id=pv_id,
            carrera_codigo=carrera_codigo,
            nombre=f"Plan {carrera_codigo}",
            fecha_creacion=date(2026, 1, 1),
            active=activo,
        ))
        session.commit()
        for mc in materias:
            if session.get(MateriaDB, mc) is None:
                session.add(MateriaDB(codigo=mc, nombre=f"Mat {mc}"))
            session.add(PlanEstudioDB(
                id=f"{pv_id}-{mc}",
                plan_version_id=pv_id,
                materia_codigo=mc,
                carrera_codigo=carrera_codigo,
                anio_plan=1,
                cuatrimestre_plan="1C",
            ))
        session.commit()
        return pv_id

    def test_sin_carreras_asociadas_devuelve_warning(self, session):
        _seed_sedes(session)
        g = create_grupo(session, "G", sedes_duras=["S1"])
        faltantes, _ajenas, warnings = chequear_consistencia_grupo(session, g.id)
        assert faltantes == []
        assert any("carreras asociadas" in w for w in warnings)

    def test_carrera_sin_planes_warning(self, session):
        """Carrera sin ninguna versión de plan cargada: el chequeo
        emite warning ("no tiene ninguna versión de plan cargada") y
        no lista faltantes."""
        _seed_sedes(session)
        session.add(CarreraDB(codigo="A", nombre="A"))
        session.commit()
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        faltantes, _ajenas, warnings = chequear_consistencia_grupo(session, g.id)
        assert faltantes == []
        assert any(
            "no tiene ninguna versión de plan cargada" in w
            for w in warnings
        )

    def test_carrera_con_plan_no_marcado_activo_usa_fallback(
        self, session,
    ):
        """Cuando la carrera tiene planes pero ninguno activo, el
        chequeo usa el más reciente como fallback y emite warning."""
        _seed_sedes(session)
        self._seed_plan(session, "A", ["MA1"], activo=False)
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        faltantes, _ajenas, warnings = chequear_consistencia_grupo(session, g.id)
        # El fallback encuentra MA1 como exclusiva de A.
        assert {f.codigo for f in faltantes} == {"MA1"}
        # Warning explícito de que se está usando fallback.
        assert any(
            "fallback" in w.lower() or "más reciente" in w.lower()
            for w in warnings
        )

    def test_detecta_materia_exclusiva_faltante(self, session):
        _seed_sedes(session)
        self._seed_plan(session, "A", ["MA1", "MA2"], activo=True)
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        # MA1 ya está en G, MA2 en otro grupo.
        g_otro = create_grupo(session, "G_OTRO", sedes_duras=["S2"])
        asignar_materia_a_grupo(session, "MA1", g.id)
        asignar_materia_a_grupo(session, "MA2", g_otro.id)
        faltantes, _ajenas, warnings = chequear_consistencia_grupo(session, g.id)
        codigos_faltantes = {f.codigo for f in faltantes}
        # MA1 ya está en G → no faltante.
        # MA2 está en otro grupo → faltante.
        assert codigos_faltantes == {"MA2"}
        f_ma2 = next(f for f in faltantes if f.codigo == "MA2")
        assert f_ma2.grupo_actual_nombre == "G_OTRO"

    def test_ignora_materia_en_otra_carrera_activa(self, session):
        """MA está en el plan activo de A y también de B → no es
        exclusiva de A → no se reporta si el grupo sólo está asociado
        a A."""
        _seed_sedes(session)
        self._seed_plan(session, "A", ["MA"], activo=True)
        self._seed_plan(session, "B", ["MA"], activo=True, plan_id="pv-B")
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        faltantes, _ajenas, _ = chequear_consistencia_grupo(session, g.id)
        assert faltantes == []

    def test_multiples_carreras_asociadas(self, session):
        _seed_sedes(session)
        self._seed_plan(session, "A", ["MA"], activo=True)
        self._seed_plan(session, "F", ["MF"], activo=True, plan_id="pv-F")
        # Grupo asociado a A y F. MA es exclusiva de A, MF exclusiva
        # de F → ambas faltantes.
        g = create_grupo(
            session, "G", sedes_duras=["S1"],
            carreras_asociadas=["A", "F"],
        )
        faltantes, _ajenas, _ = chequear_consistencia_grupo(session, g.id)
        codigos = {f.codigo for f in faltantes}
        assert codigos == {"MA", "MF"}

    def test_detecta_materia_ajena_con_sugerencia_univoca(self, session):
        """MA está en el grupo G (asociado a A), pero en el plan
        vigente sólo aparece en B (no A). Además, existe otro grupo
        asociado a B → sugerencia unívoca de destino."""
        _seed_sedes(session)
        self._seed_plan(session, "A", [], activo=True)
        self._seed_plan(session, "B", ["MA"], activo=True, plan_id="pv-B")
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        # Grupo destino sugerido.
        g_b = create_grupo(
            session, "G_B", sedes_duras=["S2"], carreras_asociadas=["B"],
        )
        # MA está en el grupo G "por error".
        asignar_materia_a_grupo(session, "MA", g.id)

        faltantes, ajenas, _ = chequear_consistencia_grupo(session, g.id)
        assert faltantes == []
        assert len(ajenas) == 1
        assert ajenas[0].codigo == "MA"
        assert ajenas[0].carreras_donde_aparece == ["B"]
        assert ajenas[0].sugerencia_grupo_id == g_b.id
        assert ajenas[0].sugerencia_grupo_nombre == "G_B"

    def test_ajena_sin_sugerencia_cuando_hay_ambiguedad(self, session):
        """MA aparece en el plan de B y de C, dos carreras distintas
        y no asociadas al grupo → carreras_donde_aparece tiene 2 items,
        sin sugerencia unívoca."""
        _seed_sedes(session)
        self._seed_plan(session, "A", [], activo=True)
        self._seed_plan(session, "B", ["MA"], activo=True, plan_id="pv-B")
        self._seed_plan(session, "C", ["MA"], activo=True, plan_id="pv-C")
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        asignar_materia_a_grupo(session, "MA", g.id)
        _, ajenas, _ = chequear_consistencia_grupo(session, g.id)
        assert len(ajenas) == 1
        assert set(ajenas[0].carreras_donde_aparece) == {"B", "C"}
        assert ajenas[0].sugerencia_grupo_id is None

    def test_no_reporta_ajena_si_aparece_tambien_en_asociada(self, session):
        """MA está en el grupo G (asociado a A) y aparece en el plan
        de A y también de B. No es ajena porque aparece en carrera
        asociada."""
        _seed_sedes(session)
        self._seed_plan(session, "A", ["MA"], activo=True)
        self._seed_plan(session, "B", ["MA"], activo=True, plan_id="pv-B")
        g = create_grupo(
            session, "G", sedes_duras=["S1"], carreras_asociadas=["A"],
        )
        asignar_materia_a_grupo(session, "MA", g.id)
        _, ajenas, _ = chequear_consistencia_grupo(session, g.id)
        assert ajenas == []


class TestPlanActivo:

    def test_get_plan_activo_devuelve_el_activo(self, session):
        session.add(CarreraDB(codigo="A", nombre="A"))
        session.commit()
        session.add(PlanCarreraVersionDB(
            id="pv-vieja", carrera_codigo="A", nombre="Vieja",
            fecha_creacion=date(2025, 1, 1), active=False,
        ))
        session.add(PlanCarreraVersionDB(
            id="pv-nueva", carrera_codigo="A", nombre="Nueva",
            fecha_creacion=date(2026, 1, 1), active=True,
        ))
        session.commit()
        pv = get_plan_activo(session, "A")
        assert pv is not None and pv.id == "pv-nueva"

    def test_get_plan_activo_devuelve_none_si_ninguno(self, session):
        session.add(CarreraDB(codigo="A", nombre="A"))
        session.add(PlanCarreraVersionDB(
            id="pv1", carrera_codigo="A", nombre="Plan 1",
            fecha_creacion=date(2026, 1, 1), active=False,
        ))
        session.commit()
        assert get_plan_activo(session, "A") is None
