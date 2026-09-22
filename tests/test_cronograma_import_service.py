"""Tests para cronograma_import_service.

Fase C2 del rediseño 2026-09-15. Cubre el flujo de preview + commit
que reemplaza al ``create_schedule_standalone`` histórico.

Casos:

- **Preview con archivo válido**: parsea, resuelve códigos, arma
  comisiones sintéticas.
- **Preview con código inexistente**: reporta en
  ``materias_no_resueltas`` sin abortar.
- **Preview con materia ya cargada**: la marca como tiene_datos_previos.
- **Commit con decisión 'agregar'**: crea comisiones nuevas sin tocar
  las existentes. Falla si el nombre colisiona.
- **Commit con decisión 'reemplazar'**: borra entries y comisiones
  previas antes de crear las nuevas.
- **Commit con decisión 'ignorar'**: no toca la materia.
- **Materia sin datos previos**: la decisión se ignora (siempre agrega).
- **Nombres de comisión strings arbitrarios**: '1', 'A', 'Mañana'
  todos válidos, comparación case-insensitive.
- **tipo_clase y virtual desde plantilla**: se propagan a las entries.
"""

from __future__ import annotations

import io
import uuid
from datetime import date, time

import pandas as pd
import pytest
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database.models import (
    ComisionDB,
    MateriaDB,
    ScheduleDB,
    ScheduleEntryDB,
)
from src.services.comision_service import create_comision_for_schedule
from src.services.cronograma_import_service import (
    ImportPreview,
    commit_import,
    preview_import,
)


# =============================================================================
# Fixtures / helpers
# =============================================================================


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


@pytest.fixture
def setup_catalogo(session):
    """Catálogo mínimo: 3 materias en la DB, más un cronograma vacío."""
    for cod, nom in [
        ("MAT101", "Análisis I"),
        ("FIS101", "Física I"),
        ("QUI101", "Química I"),
    ]:
        session.add(MateriaDB(
            codigo=cod, nombre=nom,
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
    session.commit()

    sched = ScheduleDB(
        id=str(uuid.uuid4()), ciclo_id=None,
        nombre="test", fecha_upload=date(2025, 3, 1),
    )
    session.add(sched)
    session.commit()
    return {"schedule": sched}


def _fake_excel(df: pd.DataFrame, filename: str = "test.xlsx") -> io.BytesIO:
    """Crea un archivo Excel en memoria con `.name` (mimicks
    Streamlit UploadedFile).
    """
    buf = io.BytesIO()
    df.to_excel(buf, index=False)
    buf.seek(0)
    buf.name = filename  # type: ignore[attr-defined]
    return buf


# =============================================================================
# Tests: preview
# =============================================================================


class TestPreviewBasico:
    def test_archivo_simple_arma_preview_completo(self, session, setup_catalogo):
        """Un Excel con 3 horarios de 2 materias distintas produce un
        preview con 2 MateriaEnPreview y las comisiones agrupadas.
        """
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
            {"codigo_materia": "MAT101", "comision": "2",
             "dia": "Lunes", "hora_inicio": "14:00", "hora_fin": "17:00"},
            {"codigo_materia": "FIS101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
        ])

        pv = preview_import(session, sched.id, _fake_excel(df))

        assert pv.parse_errors == []
        assert pv.materias_no_resueltas == []
        assert len(pv.materias) == 2
        cods = {m.materia_codigo for m in pv.materias}
        assert cods == {"MAT101", "FIS101"}

        # MAT101 tiene 2 comisiones nuevas
        mp_mat = next(m for m in pv.materias if m.materia_codigo == "MAT101")
        assert len(mp_mat.comisiones_nuevas) == 2
        assert {c.nombre_comision for c in mp_mat.comisiones_nuevas} == {"1", "2"}
        assert mp_mat.n_horarios_nuevos == 2
        assert not mp_mat.tiene_datos_previos

    def test_codigo_inexistente_va_a_no_resueltas(
        self, session, setup_catalogo,
    ):
        """Materia que no está en el catálogo va a materias_no_resueltas,
        no aborta el preview.
        """
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "FANTASMA", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
        ])

        pv = preview_import(session, sched.id, _fake_excel(df))

        assert len(pv.materias) == 1
        assert pv.materias[0].materia_codigo == "MAT101"
        assert pv.materias_no_resueltas == [("FANTASMA", 1)]

    def test_cronograma_inexistente_devuelve_error(self, session):
        pv = preview_import(session, "sched-fantasma", _fake_excel(pd.DataFrame([{
            "codigo_materia": "X", "dia": "Lunes",
            "hora_inicio": "08:00", "hora_fin": "10:00",
        }])))
        assert pv.tiene_errores_bloqueantes
        assert any("no existe" in e for e in pv.parse_errors)


class TestPreviewConDatosPrevios:
    def test_materia_ya_cargada_se_marca(self, session, setup_catalogo):
        """Una materia que ya tiene comisiones + entries en el cronograma
        aparece con tiene_datos_previos=True y las comisiones existentes
        listadas por nombre.
        """
        sched = setup_catalogo["schedule"]
        # Pre-cargar MAT101 con 1 comisión y 1 entry
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "2",
             "dia": "Martes", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))

        assert len(pv.materias) == 1
        mp = pv.materias[0]
        assert mp.tiene_datos_previos
        assert mp.n_entries_existentes == 1
        assert mp.comisiones_existentes == ["1"]
        assert [c.nombre_comision for c in mp.comisiones_nuevas] == ["2"]

    def test_orden_materias_prioriza_las_con_conflicto(
        self, session, setup_catalogo,
    ):
        """Materias con datos previos aparecen primero en pv.materias
        para que la UI las muestre destacadas al usuario.
        """
        sched = setup_catalogo["schedule"]
        # MAT101 ya tiene datos, FIS101 no
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "FIS101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
            {"codigo_materia": "MAT101", "comision": "2",
             "dia": "Miércoles", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))

        assert [m.materia_codigo for m in pv.materias] == ["MAT101", "FIS101"]


class TestPreviewTipoYVirtual:
    def test_tipo_clase_y_virtual_se_propagan(self, session, setup_catalogo):
        """Las columnas tipo_clase y virtual leídas de la plantilla
        aparecen en los horarios del preview.
        """
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00",
             "tipo_clase": "teorica", "virtual": "SI"},
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Martes", "hora_inicio": "14:00", "hora_fin": "17:00",
             "tipo_clase": "laboratorio", "virtual": "NO"},
        ])

        pv = preview_import(session, sched.id, _fake_excel(df))
        assert len(pv.materias) == 1
        com = pv.materias[0].comisiones_nuevas[0]
        assert com.horarios[0].tipo_clase == "teorica"
        assert com.horarios[0].virtual is True
        assert com.horarios[1].tipo_clase == "laboratorio"
        assert com.horarios[1].virtual is False


# =============================================================================
# Tests: commit
# =============================================================================


class TestCommitAgregarSinDatosPrevios:
    def test_commit_crea_entries_y_comisiones(self, session, setup_catalogo):
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
            {"codigo_materia": "MAT101", "comision": "2",
             "dia": "Martes", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(session, pv, decisiones={})

        assert result.entries_creados == 2
        assert result.comisiones_creadas == 2
        assert result.errors == []

        # Verificar en DB
        entries_db = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).all()
        assert len(entries_db) == 2
        coms_db = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert len(coms_db) == 2


class TestCommitAgregar:
    def test_agregar_sin_colision_de_nombre_ok(self, session, setup_catalogo):
        """Agregar una comisión nueva a una materia que ya tiene otras
        con nombres distintos → funciona sin errores.
        """
        sched = setup_catalogo["schedule"]
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "2",
             "dia": "Martes", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(
            session, pv, decisiones={"MAT101": "agregar"},
        )

        assert result.entries_creados == 1
        assert result.comisiones_creadas == 1
        assert result.errors == []

        # La comisión "1" original sigue, más la nueva "2".
        coms_db = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert {c.nombre for c in coms_db} == {"1", "2"}

    def test_agregar_con_colision_de_nombre_falla(
        self, session, setup_catalogo,
    ):
        """Intentar agregar una comisión con el mismo nombre que una
        existente devuelve error (unicidad case-insensitive dentro
        de la materia).
        """
        sched = setup_catalogo["schedule"]
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="A",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            # Case-insensitive: 'a' choca con 'A'
            {"codigo_materia": "MAT101", "comision": "a",
             "dia": "Martes", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(
            session, pv, decisiones={"MAT101": "agregar"},
        )

        assert result.entries_creados == 0
        assert result.comisiones_creadas == 0
        assert len(result.errors) == 1
        assert "ya existe" in result.errors[0]


class TestCommitReemplazar:
    def test_reemplazar_borra_lo_previo_y_carga_nuevo(
        self, session, setup_catalogo,
    ):
        """Con decisión 'reemplazar', las entries y comisiones previas
        de esa materia se borran antes de crear las nuevas.
        """
        sched = setup_catalogo["schedule"]
        # 2 comisiones previas de MAT101 con 3 entries en total
        c1 = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        c2 = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="2",
        )
        for com_id, dia in [(c1.id, "Lunes"), (c1.id, "Miércoles"), (c2.id, "Martes")]:
            session.add(ScheduleEntryDB(
                id=str(uuid.uuid4()), schedule_id=sched.id,
                codigo_materia="MAT101", dia=dia,
                hora_inicio=time(8, 0), hora_fin=time(11, 0),
                comision_id=com_id,
            ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "A",
             "dia": "Viernes", "hora_inicio": "14:00", "hora_fin": "17:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(
            session, pv, decisiones={"MAT101": "reemplazar"},
        )

        assert result.entries_borrados == 3
        assert result.comisiones_borradas == 2
        assert result.entries_creados == 1
        assert result.comisiones_creadas == 1
        assert result.errors == []

        # DB debe tener exactamente la comisión nueva 'A' con 1 entry.
        coms_db = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert len(coms_db) == 1
        assert coms_db[0].nombre == "A"

    def test_reemplazar_permite_reusar_nombre_previo(
        self, session, setup_catalogo,
    ):
        """Después de reemplazar, se puede volver a llamar '1' a una
        comisión nueva — no hay colisión porque se borró la anterior.
        """
        sched = setup_catalogo["schedule"]
        c1 = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=c1.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Jueves", "hora_inicio": "10:00", "hora_fin": "13:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(
            session, pv, decisiones={"MAT101": "reemplazar"},
        )

        assert result.errors == []
        assert result.entries_creados == 1


class TestCommitIgnorar:
    def test_ignorar_no_toca_datos(self, session, setup_catalogo):
        """Con decisión 'ignorar', la materia queda tal cual y su
        código va a `materias_ignoradas`.
        """
        sched = setup_catalogo["schedule"]
        c1 = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=c1.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "9",
             "dia": "Sábado", "hora_inicio": "10:00", "hora_fin": "13:00"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        result = commit_import(
            session, pv, decisiones={"MAT101": "ignorar"},
        )

        assert result.materias_ignoradas == ["MAT101"]
        assert result.entries_creados == 0
        assert result.comisiones_creadas == 0

        # Sigue viva la comisión "1" original con su entry.
        entries_db = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).all()
        assert len(entries_db) == 1


class TestCommitPropagaTipoYVirtual:
    def test_tipo_clase_y_virtual_llegan_a_las_entries(
        self, session, setup_catalogo,
    ):
        """Al commitear, los valores de tipo_clase y virtual del archivo
        aparecen en las ScheduleEntryDB creadas.
        """
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00",
             "tipo_clase": "teorica", "virtual": "SI"},
        ])
        pv = preview_import(session, sched.id, _fake_excel(df))
        commit_import(session, pv, decisiones={})

        entry = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).first()
        assert entry is not None
        assert entry.tipo_clase == "teorica"
        assert entry.virtual is True


class TestPreviewConErroresParaCommit:
    def test_commit_bloqueado_por_parse_errors(self, session):
        pv = ImportPreview(schedule_id="s1")
        pv.parse_errors.append("Columnas faltantes")
        with pytest.raises(ValueError, match="bloqueantes"):
            commit_import(session, pv, decisiones={})


class TestShadowImport:
    """Fase G del rediseño 2026-09-15: pipeline de shadow schedule
    para el preview del importer. El shadow es un ScheduleDB
    temporal marcado con `es_shadow_import=True` que combina las
    entries del destino con las nuevas del archivo aplicadas según
    las decisiones de merge por default.
    """

    def test_crear_shadow_copia_destino_y_aplica_import(
        self, session, setup_catalogo,
    ):
        from src.services.cronograma_import_service import (
            crear_shadow_import,
        )
        sched = setup_catalogo["schedule"]
        # Cronograma destino: FB12 con 1 entry preexistente.
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "FIS101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
        ])
        shadow, preview = crear_shadow_import(
            session, sched.id, _fake_excel(df),
        )

        # Shadow marcado y apuntando al destino.
        assert shadow.es_shadow_import is True
        assert shadow.shadow_target_schedule_id == sched.id
        assert shadow.id != sched.id
        assert shadow.nombre.startswith("[SHADOW]")

        # Shadow tiene AMBAS entries: la de MAT101 (copiada) + la de FIS101 (nueva).
        entries_shadow = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == shadow.id
            )
        ).all()
        assert len(entries_shadow) == 2
        codigos = {e.codigo_materia for e in entries_shadow}
        assert codigos == {"MAT101", "FIS101"}

        # Destino no se tocó: sigue con 1 entry.
        entries_destino = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).all()
        assert len(entries_destino) == 1
        assert entries_destino[0].codigo_materia == "MAT101"

    def test_shadow_no_aparece_en_get_all_schedules(
        self, session, setup_catalogo,
    ):
        """`get_all_schedules` filtra shadows por default."""
        from src.services.cronograma_import_service import (
            crear_shadow_import,
        )
        from src.services.schedule_service import get_all_schedules

        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
        ])
        shadow, _ = crear_shadow_import(session, sched.id, _fake_excel(df))

        visibles = get_all_schedules(session)
        ids_visibles = {s.id for s in visibles}
        assert sched.id in ids_visibles
        assert shadow.id not in ids_visibles

        # Con incluir_shadows=True sí aparece.
        con_shadows = get_all_schedules(session, incluir_shadows=True)
        ids_con_shadow = {s.id for s in con_shadows}
        assert shadow.id in ids_con_shadow

    def test_finalizar_shadow_reemplaza_destino(
        self, session, setup_catalogo,
    ):
        """Al finalizar, las entries del destino se reemplazan por las
        del shadow y el shadow se borra."""
        from src.services.cronograma_import_service import (
            crear_shadow_import,
            finalizar_shadow_import,
        )
        sched = setup_catalogo["schedule"]

        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
            {"codigo_materia": "FIS101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
        ])
        shadow, _ = crear_shadow_import(session, sched.id, _fake_excel(df))
        shadow_id = shadow.id

        destino_id = finalizar_shadow_import(session, shadow_id)
        assert destino_id == sched.id

        # Destino ahora tiene las 2 entries del shadow.
        entries = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).all()
        assert len(entries) == 2
        codigos = {e.codigo_materia for e in entries}
        assert codigos == {"MAT101", "FIS101"}

        # Shadow ya no existe.
        assert session.get(ScheduleDB, shadow_id) is None

    def test_descartar_shadow_no_toca_destino(
        self, session, setup_catalogo,
    ):
        """Al descartar, el destino queda como estaba y el shadow se borra."""
        from src.services.cronograma_import_service import (
            crear_shadow_import,
            descartar_shadow_import,
        )
        sched = setup_catalogo["schedule"]
        # Destino con 1 entry.
        com = create_comision_for_schedule(
            session, sched.id, "MAT101", nombre="1",
        )
        session.add(ScheduleEntryDB(
            id=str(uuid.uuid4()), schedule_id=sched.id,
            codigo_materia="MAT101", dia="Lunes",
            hora_inicio=time(8, 0), hora_fin=time(11, 0),
            comision_id=com.id,
        ))
        session.commit()

        df = pd.DataFrame([
            {"codigo_materia": "FIS101", "comision": "1",
             "dia": "Martes", "hora_inicio": "09:00", "hora_fin": "12:00"},
        ])
        shadow, _ = crear_shadow_import(session, sched.id, _fake_excel(df))
        shadow_id = shadow.id

        descartar_shadow_import(session, shadow_id)

        # Destino intacto (MAT101).
        entries = session.exec(
            select(ScheduleEntryDB).where(
                ScheduleEntryDB.schedule_id == sched.id
            )
        ).all()
        assert len(entries) == 1
        assert entries[0].codigo_materia == "MAT101"

        # Shadow ya no existe.
        assert session.get(ScheduleDB, shadow_id) is None

    def test_list_shadows_huerfanos(self, session, setup_catalogo):
        """Después de crear un shadow sin finalizarlo/descartarlo,
        aparece en `list_shadows_huerfanos`."""
        from src.services.cronograma_import_service import (
            crear_shadow_import,
            list_shadows_huerfanos,
        )
        sched = setup_catalogo["schedule"]
        df = pd.DataFrame([
            {"codigo_materia": "MAT101", "comision": "1",
             "dia": "Lunes", "hora_inicio": "08:00", "hora_fin": "11:00"},
        ])
        assert list_shadows_huerfanos(session) == []
        crear_shadow_import(session, sched.id, _fake_excel(df))
        huerfanos = list_shadows_huerfanos(session)
        assert len(huerfanos) == 1
        assert huerfanos[0].es_shadow_import is True


class TestPreviewLeeHojaHorariosDeLaPlantilla:
    """Regresión Fase C2 (2026-09-18): la plantilla generada por
    `template_export_service.generar_plantilla_cronograma_excel` tiene
    tres tipos de hojas — `Instrucciones` (primera), `Horarios`
    (contenido) y ocultas (`_materias`, `_dias`, `_tipos`, `_virtual`).

    Sin el fix, `pd.read_excel(file)` lee la primera hoja
    (`Instrucciones`) y reporta "Columnas faltantes:
    codigo_materia, dia, hora_fin, hora_inicio". El fix hace que el
    parser prefiera la hoja `Horarios` si existe.
    """

    def _crear_plantilla_del_sistema(self, session):
        """Genera la plantilla real via el service y devuelve un
        BytesIO con `.name` (mimicks Streamlit UploadedFile)."""
        from datetime import date
        from src.database.models import (
            CarreraDB, CicloDB, CicloPlanVersionDB, PlanCarreraVersionDB,
            PlanEstudioDB,
        )
        from src.services.dictado_service import create_dictados_for_ciclo
        from src.services.template_export_service import (
            generar_plantilla_cronograma_excel,
        )

        # Setup mínimo para poder generar la plantilla del ciclo.
        carrera = CarreraDB(codigo="ING", nombre="Ingeniería")
        session.add(carrera)
        session.flush()
        pv = PlanCarreraVersionDB(
            id=str(uuid.uuid4()), carrera_codigo="ING",
            nombre="P", fecha_creacion=date(2025, 1, 1),
        )
        session.add(pv)
        session.flush()
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo="MAT101",
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))
        ciclo = CicloDB(
            id="2025-1C", anio=2025, numero=1,
            fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
        )
        session.add(ciclo)
        session.flush()
        session.add(CicloPlanVersionDB(
            ciclo_id=ciclo.id, plan_version_id=pv.id,
        ))
        session.commit()
        create_dictados_for_ciclo(session, ciclo.id)

        bytes_plantilla = generar_plantilla_cronograma_excel(
            session, ciclo.id,
        )
        buf = io.BytesIO(bytes_plantilla)
        buf.name = "plantilla_horarios.xlsx"  # type: ignore[attr-defined]
        return buf

    def test_preview_no_reporta_columnas_faltantes_sobre_plantilla_real(
        self, session, setup_catalogo,
    ):
        """La plantilla generada por el sistema debe:
        1. Parsearse sin reportar "columnas faltantes" — antes del fix
           el parser leía la hoja `Instrucciones` porque era la
           primera del workbook.
        2. NO importar la fila 2 como dato real — bugfix task #341
           (2026-09-22): antes se escribía un ejemplo `MAT101 · 1 ·
           Lunes · 08:00 · 11:00` en amarillo que el parser no
           distinguía de dato del usuario.
        """
        plantilla = self._crear_plantilla_del_sistema(session)

        sched = setup_catalogo["schedule"]
        pv = preview_import(session, sched.id, plantilla)

        # No debe haber errores de columnas — la lectura llega a la
        # hoja `Horarios`.
        assert not any(
            "Columnas faltantes" in err for err in pv.parse_errors
        ), (
            f"El parser reporta 'columnas faltantes' — no está leyendo "
            f"la hoja 'Horarios'. Detalle: {pv.parse_errors}"
        )
        # La plantilla vacía no debe generar ninguna materia.
        assert pv.materias == []
