"""Tests para scripts.clonar_ciclo_para_demo."""

import json
from datetime import date, time

import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from scripts.clonar_ciclo_para_demo import clonar_ciclo
from src.database.models import (
    CicloDB,
    ClaseDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    IgnoredConflictDB,
    LPRunDB,
    MateriaDB,
    MateriaForecastConfigDB,
    PlanificacionCursadaDB,
)


@pytest.fixture(name="session")
def session_fixture():
    eng = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(eng)
    with Session(eng) as s:
        yield s


def _seed_basico(session: Session) -> str:
    """Crea ciclo + materia + dictado + plan + comision + horario + clase
    + lp_run + ignored_conflict + forecast_config. Devuelve ciclo_id."""
    ciclo = CicloDB(
        id="2026-1C", anio=2026, numero=1,
        fecha_inicio=date(2026, 3, 9), fecha_fin=date(2026, 7, 3),
    )
    mat = MateriaDB(
        codigo="M1", nombre="Mat 1",
        horas_semanales=4, horas_teoria=4, horas_laboratorio=0,
    )
    dictado = DictadoDB(
        id="d1", materia_codigo="M1", dictado_codigo="M1-2026-1C",
        virtual=False,
    )
    bridge = DictadoCicloDB(dictado_id="d1", ciclo_id="2026-1C")
    plan = PlanificacionCursadaDB(
        id="plan-1", nombre="Plan Test", ciclo_id="2026-1C", activo=True,
    )
    com = ComisionDB(
        id="c1", materia_codigo="M1", dictado_id="d1",
        plan_cursada_id="plan-1", comision_key="M1-001",
        nombre="Com 1", numero=1, cupo=30,
    )
    h = HorarioDB(
        id="h1", comision_id="c1", codigo_materia="M1",
        dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
        tipo_clase="teorica",
    )
    cl = ClaseDB(
        id="cl1", horario_id="h1", comision_id="c1",
        plan_cursada_id="plan-1", dictado_id="d1",
        fecha=date(2026, 3, 9),
        hora_inicio=time(8, 0), hora_fin=time(10, 0),
        executed=False, tipo_clase="teorica",
    )
    run = LPRunDB(
        id="run1", plan_cursada_id="plan-1",
        fecha_desde=date(2026, 3, 9),
        status="optimal",
        details_json=json.dumps({
            "horarios": [{"horario_id": "h1", "aula_id": "a1"}],
            "heatmap_por_sede": {
                "data": {
                    "S1": {
                        "teorica": {
                            "ratio": [[1.5]],
                            "demanda": [[3]],
                            "oferta": [[2]],
                        }
                    }
                },
            },
        }),
    )
    ig = IgnoredConflictDB(
        plan_cursada_id="plan-1",
        materia_a="A", materia_b="B", razon="test",
    )
    fc = MateriaForecastConfigDB(
        plan_cursada_id="plan-1", materia_codigo="M1",
        cuatrimestre="1C", metodo="media_movil", valor_override=42.0,
    )
    session.add_all([ciclo, mat, dictado, bridge, plan, com, h, cl, run, ig, fc])
    session.commit()
    return "2026-1C"


class TestClonarCiclo:

    def test_crea_ciclo_con_sufijo_y_descripcion(self, session):
        _seed_basico(session)
        resumen = clonar_ciclo(session, "2026-1C")
        nuevo = session.get(CicloDB, "2026-1C-demo-saturacion")
        assert nuevo is not None
        assert nuevo.anio == 2026
        assert "CASO EJEMPLO" in nuevo.descripcion
        assert resumen["ciclos"] == 1

    def test_clona_dictados_y_bridge(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        bridges = list(session.exec(
            select(DictadoCicloDB).where(
                DictadoCicloDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).all())
        assert len(bridges) == 1
        # El bridge apunta a un dictado NUEVO (no a "d1" original).
        assert bridges[0].dictado_id != "d1"
        nuevo_d = session.get(DictadoDB, bridges[0].dictado_id)
        assert nuevo_d is not None
        assert nuevo_d.materia_codigo == "M1"
        # Original sigue intacto.
        orig = session.get(DictadoDB, "d1")
        assert orig is not None

    def test_clona_plan_inactivo(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        nuevos = list(session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).all())
        assert len(nuevos) == 1
        plan_demo = nuevos[0]
        assert plan_demo.id != "plan-1"
        assert plan_demo.activo is False
        assert "(demo)" in plan_demo.nombre
        assert "CASO EJEMPLO" in plan_demo.descripcion

    def test_clona_comisiones_y_horarios(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        plan_demo = session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).first()
        coms = list(session.exec(
            select(ComisionDB).where(
                ComisionDB.plan_cursada_id == plan_demo.id,
            )
        ).all())
        assert len(coms) == 1
        nueva_com = coms[0]
        assert nueva_com.id != "c1"
        # FK a dictado reescrita al clon.
        assert nueva_com.dictado_id is not None
        assert nueva_com.dictado_id != "d1"

        horarios = list(session.exec(
            select(HorarioDB).where(HorarioDB.comision_id == nueva_com.id)
        ).all())
        assert len(horarios) == 1
        assert horarios[0].id == "h1-demo-saturacion"

    def test_clona_clases_con_fks_reescritas(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        plan_demo = session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).first()
        clases = list(session.exec(
            select(ClaseDB).where(ClaseDB.plan_cursada_id == plan_demo.id)
        ).all())
        assert len(clases) == 1
        cl = clases[0]
        # Todas las FKs reescritas al clon.
        assert cl.id != "cl1"
        assert cl.horario_id == "h1-demo-saturacion"
        assert cl.comision_id != "c1"
        assert cl.dictado_id != "d1"
        assert cl.plan_cursada_id == plan_demo.id

    def test_lp_run_details_json_reescrito(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        plan_demo = session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).first()
        runs = list(session.exec(
            select(LPRunDB).where(LPRunDB.plan_cursada_id == plan_demo.id)
        ).all())
        assert len(runs) == 1
        details = json.loads(runs[0].details_json)
        # horario_id reescrito.
        assert details["horarios"][0]["horario_id"] == "h1-demo-saturacion"
        # Datos numericos no afectados.
        assert details["heatmap_por_sede"]["data"]["S1"]["teorica"]["demanda"] == [[3]]

    def test_ignored_conflicts_reasignado_al_plan_demo(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        plan_demo = session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).first()
        ig_rows = list(session.exec(
            select(IgnoredConflictDB).where(
                IgnoredConflictDB.plan_cursada_id == plan_demo.id,
            )
        ).all())
        assert len(ig_rows) == 1
        assert ig_rows[0].materia_a == "A"
        # Original sigue presente.
        ig_orig = list(session.exec(
            select(IgnoredConflictDB).where(
                IgnoredConflictDB.plan_cursada_id == "plan-1",
            )
        ).all())
        assert len(ig_orig) == 1

    def test_forecast_config_clonado(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        plan_demo = session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).first()
        fcs = list(session.exec(
            select(MateriaForecastConfigDB).where(
                MateriaForecastConfigDB.plan_cursada_id == plan_demo.id,
            )
        ).all())
        assert len(fcs) == 1
        assert fcs[0].valor_override == 42.0

    def test_dry_run_no_persiste(self, session):
        _seed_basico(session)
        resumen = clonar_ciclo(session, "2026-1C", dry_run=True)
        # El resumen reporta correctamente.
        assert resumen["ciclos"] == 1
        # Pero la DB no cambio.
        assert session.get(CicloDB, "2026-1C-demo-saturacion") is None
        clones = list(session.exec(
            select(PlanificacionCursadaDB).where(
                PlanificacionCursadaDB.ciclo_id == "2026-1C-demo-saturacion",
            )
        ).all())
        assert clones == []

    def test_falla_si_ciclo_no_existe(self, session):
        _seed_basico(session)
        with pytest.raises(ValueError, match="no encontrado"):
            clonar_ciclo(session, "INEXISTENTE")

    def test_falla_si_clon_ya_existe(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        # Segundo intento debe fallar.
        with pytest.raises(ValueError, match="Ya existe"):
            clonar_ciclo(session, "2026-1C")

    def test_sufijo_custom(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C", sufijo="demo-foo")
        assert session.get(CicloDB, "2026-1C-demo-foo") is not None

    def test_original_intacto(self, session):
        _seed_basico(session)
        clonar_ciclo(session, "2026-1C")
        # Todo lo original sigue exactamente igual.
        assert session.get(CicloDB, "2026-1C") is not None
        plan_orig = session.get(PlanificacionCursadaDB, "plan-1")
        assert plan_orig is not None
        assert plan_orig.activo is True
        assert "demo" not in plan_orig.nombre.lower()
        # Comision original con plan_cursada_id original.
        c_orig = session.get(ComisionDB, "c1")
        assert c_orig is not None
        assert c_orig.plan_cursada_id == "plan-1"
        # Horario original con id original.
        h_orig = session.get(HorarioDB, "h1")
        assert h_orig is not None
