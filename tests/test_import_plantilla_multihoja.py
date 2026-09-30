"""Importación de la plantilla multihoja completa (2026-09-30).

"Crear cronograma con archivo" deja de crear el cronograma de una con
una sola hoja: arma un shadow con TODAS las hojas de la plantilla, la
UI lo revisa hoja por hoja y recién al confirmar se crea el cronograma
(`crear_shadow_import` sin destino + `finalizar_shadow_import`). El
mismo archivo completo se puede importar sobre un cronograma existente
para actualizarlo.
"""

from __future__ import annotations

from datetime import date, time

import pytest
from sqlmodel import select

from src.database.models import ScheduleDB, ScheduleEntryDB, ScheduleIgnoredConflictDB
from src.services.cronograma_import_service import (
    crear_shadow_import,
    descartar_shadow_import,
    finalizar_shadow_import,
    regenerar_materia_en_shadow,
)
from src.services.horario_file_parser import HOJAS_TODAS
from tests.test_parse_plantilla_cronograma import (
    HOJA_FIS,
    HOJA_MAT,
    _archivo,
    _fila,
    _plantilla,
)
from tests.test_template_export_service import (  # noqa: F401 (fixtures)
    ciclo_con_2_materias,
    ciclo_con_grupos,
    engine_fixture,
    session_fixture,
)


@pytest.fixture
def archivo_completo(session, ciclo_con_grupos):
    wb = _plantilla(session)
    _fila(wb[HOJA_MAT], 2, "MAT101", 1, "Lunes", "08:00", "11:00")
    _fila(wb[HOJA_MAT], 3, "MAT101", 1, "Miércoles", "08:00", "11:00")
    _fila(wb[HOJA_FIS], 2, "FIS101", 1, "Martes", "14:00", "17:00")
    return _archivo(wb)


def _entries(session, schedule_id):
    return list(session.exec(
        select(ScheduleEntryDB).where(ScheduleEntryDB.schedule_id == schedule_id)
    ).all())


class TestCrearDesdePlantilla:
    def test_el_cronograma_se_crea_recien_al_confirmar(
        self, session, archivo_completo,
    ):
        n_antes = len(session.exec(select(ScheduleDB)).all())
        shadow, preview = crear_shadow_import(
            session, None, archivo_completo, sheet_name=HOJAS_TODAS,
            ciclo_id="2025-1C", nombre_nuevo="1C 2025 desde plantilla",
        )
        assert shadow.es_shadow_import
        assert shadow.shadow_target_schedule_id is None
        assert shadow.ciclo_id == "2025-1C"
        assert {m.materia_codigo for m in preview.materias} == {"MAT101", "FIS101"}
        assert len(_entries(session, shadow.id)) == 3
        # Sólo existe el shadow: ningún cronograma real nuevo todavía.
        reales = [
            s for s in session.exec(select(ScheduleDB)).all()
            if not s.es_shadow_import
        ]
        assert len(reales) == n_antes

        res = finalizar_shadow_import(session, shadow.id)

        nuevo = session.get(ScheduleDB, res.destino_id)
        assert nuevo is not None and not nuevo.es_shadow_import
        assert nuevo.nombre == "1C 2025 desde plantilla"
        assert nuevo.ciclo_id == "2025-1C"
        assert len(_entries(session, nuevo.id)) == 3
        assert res.entries_agregadas == 3 and res.entries_eliminadas == 0
        assert session.get(ScheduleDB, shadow.id) is None

    def test_archivo_que_no_es_plantilla_se_rechaza(self, session, ciclo_con_grupos):
        import io

        f = io.BytesIO(b"codigo_materia,dia,hora_inicio,hora_fin\nMAT101,Lunes,08:00,11:00\n")
        f.name = "horarios.csv"
        with pytest.raises(ValueError, match="plantilla"):
            crear_shadow_import(
                session, None, f, sheet_name=HOJAS_TODAS,
                ciclo_id="2025-1C", nombre_nuevo="x",
            )
        assert not [
            s for s in session.exec(select(ScheduleDB)).all()
            if s.es_shadow_import
        ]

    def test_crear_sin_ciclo_falla(self, session, archivo_completo):
        with pytest.raises(ValueError, match="ciclo"):
            crear_shadow_import(
                session, None, archivo_completo, sheet_name=HOJAS_TODAS,
                nombre_nuevo="x",
            )

    def test_ignorar_una_materia_en_modo_crear(self, session, archivo_completo):
        shadow, _ = crear_shadow_import(
            session, None, archivo_completo, sheet_name=HOJAS_TODAS,
            ciclo_id="2025-1C", nombre_nuevo="x",
        )
        regenerar_materia_en_shadow(
            session, shadow.id, "FIS101", "ignorar",
            archivo_completo, sheet_name=HOJAS_TODAS,
        )
        assert {e.codigo_materia for e in _entries(session, shadow.id)} == {"MAT101"}

        regenerar_materia_en_shadow(
            session, shadow.id, "FIS101", "agregar",
            archivo_completo, sheet_name=HOJAS_TODAS,
        )
        assert len(_entries(session, shadow.id)) == 3

    def test_ignorados_marcados_en_la_vista_previa_pasan_al_nuevo(
        self, session, archivo_completo,
    ):
        from src.services.cronograma_validation_service import (
            add_ignored_pair_cronograma,
            get_ignored_pairs_cronograma,
        )

        shadow, _ = crear_shadow_import(
            session, None, archivo_completo, sheet_name=HOJAS_TODAS,
            ciclo_id="2025-1C", nombre_nuevo="x",
        )
        add_ignored_pair_cronograma(session, shadow.id, "MAT101", "FIS101", razon="r")
        res = finalizar_shadow_import(session, shadow.id)

        assert get_ignored_pairs_cronograma(session, res.destino_id) == {
            ("FIS101", "MAT101"),
        }
        assert session.exec(
            select(ScheduleIgnoredConflictDB)
            .where(ScheduleIgnoredConflictDB.schedule_id == shadow.id)
        ).all() == []

    def test_descartar_shadow_de_crear_limpia_sus_ignorados(
        self, session, archivo_completo,
    ):
        from src.services.cronograma_validation_service import (
            add_ignored_pair_cronograma,
        )

        shadow, _ = crear_shadow_import(
            session, None, archivo_completo, sheet_name=HOJAS_TODAS,
            ciclo_id="2025-1C", nombre_nuevo="x",
        )
        add_ignored_pair_cronograma(session, shadow.id, "MAT101", "FIS101")
        descartar_shadow_import(session, shadow.id)
        assert session.exec(select(ScheduleIgnoredConflictDB)).all() == []


class TestActualizarExistenteConPlantilla:
    @pytest.fixture
    def destino(self, session, ciclo_con_grupos):
        sched = ScheduleDB(
            id="dest", ciclo_id="2025-1C", nombre="Vigente",
            fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        session.add(ScheduleEntryDB(
            id="vieja", schedule_id="dest", codigo_materia="MAT101",
            dia="Viernes", hora_inicio=time(18, 0), hora_fin=time(21, 0),
        ))
        session.commit()
        return sched

    def test_reemplaza_con_el_archivo_completo(
        self, session, destino, archivo_completo,
    ):
        shadow, _ = crear_shadow_import(
            session, destino.id, archivo_completo, sheet_name=HOJAS_TODAS,
        )
        finalizar_shadow_import(session, shadow.id)

        entries = _entries(session, destino.id)
        assert sorted((e.codigo_materia, e.dia) for e in entries) == [
            ("FIS101", "Martes"), ("MAT101", "Lunes"), ("MAT101", "Miércoles"),
        ]

    def test_plantilla_de_otro_ciclo_se_rechaza(
        self, session, destino, archivo_completo,
    ):
        from src.database.models import CicloDB

        session.add(CicloDB(
            id="2026-2C", anio=2026, numero=2,
            fecha_inicio=date(2026, 8, 1), fecha_fin=date(2026, 12, 1),
        ))
        destino.ciclo_id = "2026-2C"
        session.add(destino)
        session.commit()

        with pytest.raises(ValueError, match="ciclo 2025-1C"):
            crear_shadow_import(
                session, destino.id, archivo_completo, sheet_name=HOJAS_TODAS,
            )


class TestMateriasAusentesEnLaPlantilla:
    """Fix revisión 2026-09-30: con la plantilla completa el archivo es
    la foto entera del cronograma. Una materia que tiene horarios en el
    destino pero ya no está en el archivo se elimina por defecto (antes
    conservaba sus horarios viejos en silencio), con opción de
    conservarla."""

    @pytest.fixture
    def destino_con_dos(self, session, ciclo_con_grupos):
        session.add(ScheduleDB(
            id="dest2", ciclo_id="2025-1C", nombre="Vigente",
            fecha_upload=date(2026, 3, 1),
        ))
        for eid, cod, dia in (("m", "MAT101", "Lunes"), ("f", "FIS101", "Martes")):
            session.add(ScheduleEntryDB(
                id=eid, schedule_id="dest2", codigo_materia=cod,
                dia=dia, hora_inicio=time(8, 0), hora_fin=time(11, 0),
            ))
        session.commit()
        wb = _plantilla(session)
        _fila(wb[HOJA_MAT], 2, "MAT101", 1, "Jueves", "08:00", "11:00")
        # La hoja de FIS101 vuelve vacía.
        return _archivo(wb)

    def test_materia_ausente_se_elimina_por_defecto(self, session, destino_con_dos):
        shadow, preview = crear_shadow_import(
            session, "dest2", destino_con_dos, sheet_name=HOJAS_TODAS,
        )
        assert preview.materias_ausentes == ["FIS101"]
        assert {e.codigo_materia for e in _entries(session, shadow.id)} == {"MAT101"}

        finalizar_shadow_import(session, shadow.id)
        assert {e.codigo_materia for e in _entries(session, "dest2")} == {"MAT101"}

    def test_se_puede_conservar_y_volver_a_eliminar(self, session, destino_con_dos):
        shadow, _ = crear_shadow_import(
            session, "dest2", destino_con_dos, sheet_name=HOJAS_TODAS,
        )
        regenerar_materia_en_shadow(
            session, shadow.id, "FIS101", "ignorar",
            destino_con_dos, sheet_name=HOJAS_TODAS,
        )
        fis = [e for e in _entries(session, shadow.id) if e.codigo_materia == "FIS101"]
        assert [(e.dia, e.hora_inicio) for e in fis] == [("Martes", time(8, 0))]

        regenerar_materia_en_shadow(
            session, shadow.id, "FIS101", "eliminar",
            destino_con_dos, sheet_name=HOJAS_TODAS,
        )
        assert {e.codigo_materia for e in _entries(session, shadow.id)} == {"MAT101"}

    def test_una_sola_hoja_no_elimina_ausentes(self, session, destino_con_dos):
        """El camino viejo (una hoja explícita) mantiene su semántica:
        las materias que no vienen en la hoja no se tocan."""
        shadow, preview = crear_shadow_import(
            session, "dest2", destino_con_dos, sheet_name=HOJA_MAT,
        )
        assert preview.materias_ausentes == []
        assert {e.codigo_materia for e in _entries(session, shadow.id)} == {
            "MAT101", "FIS101",
        }


def test_preview_conserva_el_codigo_tal_como_vino_en_el_archivo(
    session, ciclo_con_grupos,
):
    """Fix revisión 2026-09-30: la UI ubica cada materia en su hoja con
    el código del archivo. `original_code` sólo se completa en la
    resolución por Guaraní, así que una materia resuelta de otra forma
    (por ejemplo por nombre) no encajaba en ninguna hoja y desaparecía
    de la revisión. `codigo_en_archivo` se completa siempre."""
    from src.services.cronograma_import_service import preview_import

    session.add(ScheduleDB(
        id="dst3", ciclo_id="2025-1C", nombre="x",
        fecha_upload=date(2026, 3, 1),
    ))
    session.commit()
    wb = _plantilla(session)
    _fila(wb[HOJA_MAT], 2, "MAT101", 1, "Lunes", "08:00", "11:00")
    _fila(wb[HOJA_FIS], 2, "Física I", 1, "Martes", "08:00", "11:00")

    pv = preview_import(session, "dst3", _archivo(wb), sheet_name=HOJAS_TODAS)

    por_cod = {m.materia_codigo: m for m in pv.materias}
    assert por_cod["MAT101"].codigo_en_archivo == "MAT101"
    if "FIS101" in por_cod:  # resuelta por nombre
        assert por_cod["FIS101"].codigo_en_archivo == "Física I"


def test_codigo_no_reconocido_indica_hoja_y_fila(session, ciclo_con_grupos):
    """Fix revisión 2026-09-30: con la plantilla multihoja las filas se
    numeraban sobre todas las hojas juntas ('Fila ~412'). El mensaje
    tiene que decir la hoja y la fila reales."""
    from src.services.cronograma_import_service import preview_import

    session.add(ScheduleDB(
        id="dst4", ciclo_id="2025-1C", nombre="x",
        fecha_upload=date(2026, 3, 1),
    ))
    session.commit()
    wb = _plantilla(session)
    _fila(wb[HOJA_MAT], 2, "MAT101", 1, "Lunes", "08:00", "11:00")
    _fila(wb[HOJA_MAT], 3, "MAT101", 1, "Martes", "08:00", "11:00")
    _fila(wb[HOJA_FIS], 2, "FIS101", 1, "Martes", "14:00", "17:00")
    _fila(wb[HOJA_FIS], 3, "XYZ999", 1, "Jueves", "08:00", "11:00")

    pv = preview_import(session, "dst4", _archivo(wb), sheet_name=HOJAS_TODAS)

    assert pv.materias_no_resueltas == [("XYZ999", f"Hoja '{HOJA_FIS}', fila 3")]
