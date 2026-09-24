"""Tests de las validaciones de entrada del importador (2026-09-23).

Cubre el lote de mejoras sobre la plantilla y el parser:

- ``hora_inicio >= hora_fin`` es un error de fila (antes entraba y
  recién rompía en las validaciones del cronograma).
- Una clase de ``laboratorio`` no puede ser ``virtual``.
- ``virtual`` es booleano: vacío/NaN se interpreta ``False``.
- Filas totalmente vacías (típico: filas de la plantilla con la
  fórmula de auto-población del código) se saltean en silencio.
- ``codigo_comision`` numérico obligatorio >= 1 con ``nombre_comision``
  opcional; el código se persiste como ``ComisionDB.numero``.
- Resolución de materia por ``nombre_materia`` cuando el código viene
  vacío (match exacto, case-insensitive, único).
- ``build_schedule_grid`` propaga el flag ``virtual`` a los bloques
  (bugfix: antes quedaba siempre en ``False`` y las clases virtuales
  no se veían en ninguna vista).
- ``_validar_filas_editor`` aplica las mismas reglas en los data
  editors de la UI antes de persistir.
"""

from __future__ import annotations

import io
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
from src.services.horario_file_parser import parse_horarios_file
from src.services.horario_loading_service import _resolve_materia_code


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
    with Session(engine) as s:
        yield s


def _csv(contenido: str, filename: str = "horarios.csv") -> io.BytesIO:
    buf = io.BytesIO(contenido.encode("utf-8"))
    buf.name = filename  # type: ignore[attr-defined]
    return buf


class TestValidacionHoras:
    def test_inicio_mayor_que_fin_es_error(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Lunes,12:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert "anterior a hora_fin" in errors[0]

    def test_inicio_igual_a_fin_es_error(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Lunes,10:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1


class TestValidacionLaboratorioVirtual:
    def test_laboratorio_virtual_es_error(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,tipo_clase,virtual\n"
            "MAT101,Lunes,08:00,10:00,laboratorio,SI\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert "laboratorio" in errors[0]

    def test_laboratorio_presencial_ok(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,tipo_clase,virtual\n"
            "MAT101,Lunes,08:00,10:00,laboratorio,NO\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert len(entries) == 1
        assert entries[0].virtual is False

    def test_teorica_virtual_ok(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,tipo_clase,virtual\n"
            "MAT101,Lunes,08:00,10:00,teorica,SI\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].virtual is True


class TestVirtualBooleano:
    def test_vacio_se_interpreta_false(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,virtual\n"
            "MAT101,Lunes,08:00,10:00,\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].virtual is False

    def test_variantes_afirmativas_y_negativas(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,virtual\n"
            "MAT101,Lunes,08:00,10:00,SI\n"
            "MAT101,Martes,08:00,10:00,sí\n"
            "MAT101,Miércoles,08:00,10:00,true\n"
            "MAT101,Jueves,08:00,10:00,no\n"
            "MAT101,Viernes,08:00,10:00,0\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert [e.virtual for e in entries] == [True, True, True, False, False]

    def test_valor_no_reconocido_es_error(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,virtual\n"
            "MAT101,Lunes,08:00,10:00,quizás\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert "virtual" in errors[0]


class TestVirtualBooleanoDesdeExcel:
    """Regresión 2026-09-24 (reporte del usuario): en un Excel real,
    una columna `virtual` con UN solo booleano y el resto vacío llega
    al parser como float — pandas convierte la mezcla bool + NaN a
    numérica (True → 1.0). El parser rechazaba '1.0' como no
    reconocido, con lo que la plantilla nueva fallaba en el caso más
    normal (marcar virtual una sola fila).
    """

    def _xlsx(self, virtuales: list) -> io.BytesIO:
        from openpyxl import Workbook

        wb = Workbook()
        ws = wb.active
        ws.title = "Horarios"
        ws.append(["codigo_materia", "dia", "hora_inicio",
                   "hora_fin", "virtual"])
        dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
        for i, v in enumerate(virtuales):
            ws.append(["MAT101", dias[i], "08:00", "10:00", v])
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)
        buf.name = "horarios.xlsx"  # type: ignore[attr-defined]
        return buf

    def test_bool_true_mezclado_con_vacios(self):
        archivo = self._xlsx([None, True, None])
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert [e.virtual for e in entries] == [False, True, False]

    def test_bool_false_y_true_mezclados_con_vacios(self):
        archivo = self._xlsx([False, None, True, None])
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert [e.virtual for e in entries] == [False, False, True, False]

    def test_numero_distinto_de_cero_y_uno_es_error(self):
        archivo = self._xlsx([2])
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert "virtual" in errors[0]


class TestFilasVacias:
    def test_fila_totalmente_vacia_se_saltea_sin_error(self):
        """Las filas de la plantilla con la fórmula de auto-población
        del código (y nada más) llegan como vacías — no son un error.
        """
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Lunes,08:00,10:00\n"
            ",,,\n"
            ",,,\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert len(entries) == 1


class TestCodigoComision:
    def test_codigo_valido_setea_comision_codigo(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,2,Turno mañana,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].comision_codigo == 2
        assert entries[0].comision_nombre == "Turno mañana"

    def test_codigo_sin_nombre_autogenera_nombre(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,3,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].comision_codigo == 3
        assert entries[0].comision_nombre == "C3"

    def test_codigo_no_numerico_es_error(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,abc,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert "no es un número entero" in errors[0]

    def test_codigo_menor_a_uno_es_error(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,0,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert entries == []
        assert len(errors) == 1
        assert ">= 1" in errors[0]

    def test_texto_libre_historico_sigue_aceptado(self):
        archivo = _csv(
            "codigo_materia,comision,dia,hora_inicio,hora_fin\n"
            "MAT101,Comision A,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].comision_codigo is None
        assert entries[0].comision_nombre == "Comision A"


class TestComisionCodigoNombreUnoAUno:
    """Validación 1:1 dentro del archivo (2026-09-24): si se declara
    nombre de comisión, la correspondencia código ↔ nombre tiene que
    ser unívoca dentro de cada materia. Un mismo código no puede
    aparecer con dos nombres, ni un mismo nombre con dos códigos.
    """

    def test_mismo_codigo_dos_nombres_es_error(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Mañana,Lunes,08:00,10:00\n"
            "MAT101,1,Tarde,Miércoles,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert len(errors) == 1
        assert "nombres distintos" in errors[0]
        assert "Mañana" in errors[0] and "Tarde" in errors[0]

    def test_mismo_nombre_dos_codigos_es_error(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Mañana,Lunes,08:00,10:00\n"
            "MAT101,2,Mañana,Miércoles,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert len(errors) == 1
        assert "códigos distintos" in errors[0]

    def test_correspondencia_consistente_ok(self):
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Mañana,Lunes,08:00,10:00\n"
            "MAT101,1,Mañana,Miércoles,08:00,10:00\n"
            "MAT101,2,Tarde,Lunes,14:00,16:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert len(entries) == 3

    def test_mismo_nombre_en_materias_distintas_ok(self):
        """La unicidad es POR MATERIA: dos materias pueden tener cada
        una su comisión 'Mañana' con códigos distintos.
        """
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Mañana,Lunes,08:00,10:00\n"
            "FIS201,2,Mañana,Martes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []

    def test_nombre_omitido_en_algunas_filas_no_es_error(self):
        """Filas sin nombre declarado (queda el default C{código}) no
        participan del chequeo: declarar el nombre en una sola fila
        de la comisión es válido.
        """
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Mañana,Lunes,08:00,10:00\n"
            "MAT101,1,,Miércoles,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []

    def test_import_prefiere_el_nombre_declarado(self, session):
        """Al agrupar en la vista previa, si una fila de la comisión
        declara nombre y otra no, gana el declarado (antes dependía
        del orden de las filas).
        """
        from src.services.cronograma_import_service import (
            commit_import,
            preview_import,
        )

        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        sched = ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        session.commit()

        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,,Lunes,08:00,10:00\n"
            "MAT101,1,Mañana,Miércoles,08:00,10:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.parse_errors == []
        commit_import(session, pv, {})
        coms = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert len(coms) == 1
        assert coms[0].numero == 1
        assert coms[0].nombre == "Mañana"


class TestResolucionPorNombre:
    def _catalogo(self, session):
        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        session.add(MateriaDB(
            codigo="FIS201", nombre="Física II",
            periodo="cuatrimestral", active=True, horas_semanales=4,
        ))
        session.commit()

    def test_nombre_exacto_unico_resuelve(self, session):
        self._catalogo(session)
        res = _resolve_materia_code(session, "análisis i")
        assert res.resolution_type == "nombre"
        assert res.resolved_code == "MAT101"

    def test_nombre_inexistente_no_resuelve(self, session):
        self._catalogo(session)
        res = _resolve_materia_code(session, "Química Orgánica")
        assert res.resolution_type == "unresolved"
        assert res.resolved_code is None

    def test_nombre_ambiguo_no_resuelve(self, session):
        self._catalogo(session)
        session.add(MateriaDB(
            codigo="MAT201", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        session.commit()
        res = _resolve_materia_code(session, "Análisis I")
        assert res.resolution_type == "unresolved"

    def test_parser_propaga_nombre_cuando_codigo_vacio(self):
        archivo = _csv(
            "codigo_materia,nombre_materia,dia,hora_inicio,hora_fin\n"
            ",Análisis I,Lunes,08:00,10:00\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].codigo_materia == "Análisis I"


class TestCodigoNombreNoCorresponden:
    """Guardia del importador (2026-09-23): en el Excel no se puede
    impedir del todo que el usuario escriba un código y elija un
    nombre de materias distintas — la vista previa rechaza la fila.
    """

    def _setup(self, session) -> ScheduleDB:
        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        session.add(MateriaDB(
            codigo="FIS201", nombre="Física II",
            periodo="cuatrimestral", active=True, horas_semanales=4,
        ))
        sched = ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        session.commit()
        return sched

    def test_mismatch_es_error_bloqueante(self, session):
        from src.services.cronograma_import_service import preview_import

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,nombre_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Física II,Lunes,08:00,10:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.tiene_errores_bloqueantes
        assert any("no se corresponden" in e for e in pv.parse_errors)

    def test_codigo_y_nombre_consistentes_ok(self, session):
        from src.services.cronograma_import_service import preview_import

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,nombre_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,Análisis I,Lunes,08:00,10:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.parse_errors == []
        assert {m.materia_codigo for m in pv.materias} == {"MAT101"}

    def test_nombre_con_mayusculas_distintas_no_es_mismatch(self, session):
        from src.services.cronograma_import_service import preview_import

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,nombre_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,  análisis i ,Lunes,08:00,10:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.parse_errors == []

    def test_solo_codigo_o_solo_nombre_no_chequea(self, session):
        from src.services.cronograma_import_service import preview_import

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,nombre_materia,dia,hora_inicio,hora_fin\n"
            "MAT101,,Lunes,08:00,10:00\n"
            ",Física II,Martes,08:00,10:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.parse_errors == []
        assert {m.materia_codigo for m in pv.materias} == {"MAT101", "FIS201"}


class TestImportConCodigoComision:
    """El código declarado en la plantilla se persiste como
    ``ComisionDB.numero`` y agrupa los horarios de la comisión.
    """

    def _setup(self, session) -> ScheduleDB:
        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        sched = ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        session.commit()
        return sched

    def test_numero_declarado_se_respeta(self, session):
        from src.services.cronograma_import_service import (
            commit_import,
            preview_import,
        )

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,codigo_comision,nombre_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,5,Turno noche,Lunes,18:00,20:00\n"
            "MAT101,5,Turno noche,Miércoles,18:00,20:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        assert pv.parse_errors == []
        res = commit_import(session, pv, {})
        assert res.entries_creados == 2

        coms = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert len(coms) == 1
        assert coms[0].numero == 5
        assert coms[0].nombre == "Turno noche"

    def test_codigos_distintos_generan_comisiones_distintas(self, session):
        from src.services.cronograma_import_service import (
            commit_import,
            preview_import,
        )

        sched = self._setup(session)
        archivo = _csv(
            "codigo_materia,codigo_comision,dia,hora_inicio,hora_fin\n"
            "MAT101,1,Lunes,08:00,10:00\n"
            "MAT101,2,Lunes,10:00,12:00\n"
        )
        pv = preview_import(session, sched.id, archivo)
        commit_import(session, pv, {})

        coms = session.exec(
            select(ComisionDB).where(ComisionDB.schedule_id == sched.id)
        ).all()
        assert sorted(c.numero for c in coms) == [1, 2]


class TestBuildScheduleGridVirtual:
    """Bugfix 2026-09-23: ``ScheduleBlock.virtual`` nunca se populaba —
    las clases marcadas virtual no se veían en ninguna vista.
    """

    def _setup(self, session, *, materia_virtual: bool) -> ScheduleDB:
        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
            virtual=materia_virtual,
        ))
        sched = ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        session.commit()
        return sched

    def _entry(self, session, sched, eid, virtual):
        session.add(ScheduleEntryDB(
            id=eid, schedule_id=sched.id, codigo_materia="MAT101",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            virtual=virtual,
            # Invariante 2026-09-24: virtual explícito exige teorica.
            tipo_clase="teorica" if virtual else None,
        ))
        session.commit()

    def test_override_true_en_entry(self, session):
        from src.services.schedule_service import build_schedule_grid

        sched = self._setup(session, materia_virtual=False)
        self._entry(session, sched, "e1", True)
        grid = build_schedule_grid(session, sched.id)
        assert grid["Lunes"][0].virtual is True

    def test_none_hereda_flag_de_la_materia(self, session):
        from src.services.schedule_service import build_schedule_grid

        sched = self._setup(session, materia_virtual=True)
        self._entry(session, sched, "e1", None)
        grid = build_schedule_grid(session, sched.id)
        assert grid["Lunes"][0].virtual is True

    def test_override_false_gana_a_materia_virtual(self, session):
        from src.services.schedule_service import build_schedule_grid

        sched = self._setup(session, materia_virtual=True)
        self._entry(session, sched, "e1", False)
        grid = build_schedule_grid(session, sched.id)
        assert grid["Lunes"][0].virtual is False


class TestInvarianteVirtualTeorica:
    """Invariante 2026-09-24 (pedido del usuario): una clase virtual
    es siempre teórica, y un laboratorio es siempre presencial
    EXPLÍCITO (virtual=False, no None — así la herencia del dictado
    nunca puede volver virtual a un laboratorio). Se deriva en todos
    los caminos de escritura y se refuerza con CHECK de base de datos
    en ``schedule_entries`` y ``horarios``.
    """

    def test_helper_normalizacion(self):
        from src.services.horario_loading_service import (
            normalizar_tipo_virtual,
        )

        # virtual=True sin tipo → teorica.
        assert normalizar_tipo_virtual(None, True) == ("teorica", True)
        assert normalizar_tipo_virtual("teorica", True) == ("teorica", True)
        # laboratorio → presencial explícito (pisa la herencia).
        assert normalizar_tipo_virtual("laboratorio", None) == (
            "laboratorio", False,
        )
        assert normalizar_tipo_virtual("laboratorio", False) == (
            "laboratorio", False,
        )
        # laboratorio + virtual → error.
        with pytest.raises(ValueError):
            normalizar_tipo_virtual("laboratorio", True)
        # Sin virtual ni lab, no toca nada.
        assert normalizar_tipo_virtual(None, None) == (None, None)
        assert normalizar_tipo_virtual("teorica", False) == (
            "teorica", False,
        )

    def test_parser_virtual_autocompleta_teorica(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,tipo_clase,virtual\n"
            "MAT101,Lunes,08:00,10:00,,SI\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].virtual is True
        assert entries[0].tipo_clase == "teorica"

    def test_parser_laboratorio_queda_presencial_explicito(self):
        archivo = _csv(
            "codigo_materia,dia,hora_inicio,hora_fin,tipo_clase,virtual\n"
            "MAT101,Lunes,08:00,10:00,laboratorio,\n"
        )
        entries, errors = parse_horarios_file(archivo)
        assert errors == []
        assert entries[0].tipo_clase == "laboratorio"
        assert entries[0].virtual is False

    def _setup(self, session):
        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        session.add(ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        ))
        session.commit()

    def test_add_schedule_entry_normaliza(self, session):
        from src.services.schedule_service import add_schedule_entry

        self._setup(session)
        e1 = add_schedule_entry(
            session, "sched1", "MAT101", "Lunes",
            time(8, 0), time(10, 0), virtual=True,
        )
        assert e1.tipo_clase == "teorica"
        assert e1.virtual is True
        e2 = add_schedule_entry(
            session, "sched1", "MAT101", "Martes",
            time(8, 0), time(10, 0), tipo_clase="laboratorio",
        )
        assert e2.virtual is False

    def test_update_schedule_entry_normaliza_y_valida(self, session):
        from src.services.schedule_service import (
            add_schedule_entry,
            update_schedule_entry,
        )

        self._setup(session)
        e = add_schedule_entry(
            session, "sched1", "MAT101", "Lunes",
            time(8, 0), time(10, 0),
        )
        # Marcar virtual sin tipo → autocompleta teorica.
        e = update_schedule_entry(session, e.id, virtual=True)
        assert e.tipo_clase == "teorica"
        # Cambiar a laboratorio una clase virtual → error.
        with pytest.raises(ValueError):
            update_schedule_entry(session, e.id, tipo_clase="laboratorio")
        # Despejar virtual y pasar a laboratorio → presencial explícito.
        e = update_schedule_entry(
            session, e.id, virtual=False, tipo_clase="laboratorio",
        )
        assert e.virtual is False

    def test_orm_deriva_en_insert_directo(self, session):
        """Escrituras directas por ORM (sin pasar por el service
        layer) también derivan la invariante: listener
        ``before_insert``/``before_update`` en los modelos.
        """
        self._setup(session)
        session.add(ScheduleEntryDB(
            id="d1", schedule_id="sched1", codigo_materia="MAT101",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase=None, virtual=True,
        ))
        session.add(ScheduleEntryDB(
            id="d2", schedule_id="sched1", codigo_materia="MAT101",
            dia="Martes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="laboratorio", virtual=None,
        ))
        session.commit()
        assert session.get(ScheduleEntryDB, "d1").tipo_clase == "teorica"
        assert session.get(ScheduleEntryDB, "d2").virtual is False

    def test_check_constraint_lab_virtual_es_integrity_error(self, session):
        """La contradicción real (laboratorio + virtual) no se
        auto-corrige: la rechaza el CHECK de la tabla.
        """
        from sqlalchemy.exc import IntegrityError

        self._setup(session)
        session.add(ScheduleEntryDB(
            id="bad1", schedule_id="sched1", codigo_materia="MAT101",
            dia="Lunes", hora_inicio=time(8, 0), hora_fin=time(10, 0),
            tipo_clase="laboratorio", virtual=True,
        ))
        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()

    def test_check_constraint_protege_sql_crudo(self, session):
        """El CHECK también cubre escrituras que salteen el ORM (SQL
        crudo): virtual sin teorica y laboratorio sin presencial
        explícito se rechazan a nivel de base de datos.
        """
        from sqlalchemy import text
        from sqlalchemy.exc import IntegrityError

        self._setup(session)
        _ins = (
            "INSERT INTO schedule_entries "
            "(id, schedule_id, codigo_materia, dia, hora_inicio, "
            "hora_fin, tipo_clase, virtual, comision_id) "
            "VALUES (:id, 'sched1', 'MAT101', 'Lunes', '08:00:00', "
            "'10:00:00', :tipo, :virt, NULL)"
        )
        with pytest.raises(IntegrityError):
            session.connection().execute(
                text(_ins), {"id": "raw1", "tipo": None, "virt": 1},
            )
        session.rollback()
        with pytest.raises(IntegrityError):
            session.connection().execute(
                text(_ins),
                {"id": "raw2", "tipo": "laboratorio", "virt": None},
            )
        session.rollback()


class TestBuildScheduleGridTipoClase:
    """Regresión 2026-09-24: `ScheduleBlock.tipo_clase` existía pero
    `build_schedule_grid` no lo populaba — el ícono 🧪/📖 no se veía
    en las vistas de cronograma que usan el render simple (por
    ejemplo, los calendarios Antes/Después de la vista previa).
    """

    def test_grid_propaga_tipo_clase(self, session):
        from src.services.schedule_service import build_schedule_grid

        session.add(MateriaDB(
            codigo="MAT101", nombre="Análisis I",
            periodo="cuatrimestral", active=True, horas_semanales=6,
        ))
        sched = ScheduleDB(
            id="sched1", nombre="test", fecha_upload=date(2026, 3, 1),
        )
        session.add(sched)
        for eid, dia, tipo, virt in (
            ("e1", "Lunes", "laboratorio", False),
            ("e2", "Martes", "teorica", None),
            ("e3", "Miércoles", None, None),
        ):
            session.add(ScheduleEntryDB(
                id=eid, schedule_id="sched1", codigo_materia="MAT101",
                dia=dia, hora_inicio=time(8, 0), hora_fin=time(10, 0),
                tipo_clase=tipo, virtual=virt,
            ))
        session.commit()

        grid = build_schedule_grid(session, "sched1")
        assert grid["Lunes"][0].tipo_clase == "laboratorio"
        assert grid["Martes"][0].tipo_clase == "teorica"
        assert grid["Miércoles"][0].tipo_clase is None


class TestValidarFilasEditor:
    """Las mismas reglas de coherencia aplicadas en los data editors
    de la UI antes de persistir.
    """

    def _df(self, filas):
        return pd.DataFrame(filas)

    def test_df_valido_sin_errores(self):
        from src.ui.schedule_materia_editor import _validar_filas_editor

        df = self._df([
            {"Día": "Lunes", "Inicio": "08:00", "Fin": "10:00",
             "Tipo": "teorica", "Virtual": False},
        ])
        assert _validar_filas_editor(df) == []

    def test_inicio_mayor_o_igual_a_fin(self):
        from src.ui.schedule_materia_editor import _validar_filas_editor

        df = self._df([
            {"Día": "Lunes", "Inicio": "12:00", "Fin": "10:00",
             "Tipo": "", "Virtual": False},
            {"Día": "Martes", "Inicio": "10:00", "Fin": "10:00",
             "Tipo": "", "Virtual": False},
        ])
        errs = _validar_filas_editor(df)
        assert len(errs) == 2
        assert all("anterior" in e for e in errs)

    def test_laboratorio_virtual(self):
        from src.ui.schedule_materia_editor import _validar_filas_editor

        df = self._df([
            {"Día": "Lunes", "Inicio": "08:00", "Fin": "10:00",
             "Tipo": "laboratorio", "Virtual": True},
        ])
        errs = _validar_filas_editor(df)
        assert len(errs) == 1
        assert "laboratorio" in errs[0]


class TestOpcionesHorariasDinamicas:
    """Fix 2026-09-24 (reporte del usuario): las opciones de
    Inicio/Fin de los data editors de horarios se generan
    dinámicamente desde ``ConfiguracionHoraria`` (granularidad +
    rango operativo) — antes eran una lista hardcodeada con pasos de
    30 minutos y las horas :15/:45 no aparecían.
    """

    def _con_config(self, monkeypatch, granularidad, inicio, fin):
        from src.database.models import ConfiguracionHoraria
        import src.ui.schedule_materia_editor as sme

        cfg = ConfiguracionHoraria(
            granularidad_minutos=granularidad,
            hora_inicio_operativo=inicio,
            hora_fin_operativo=fin,
        )

        class _FakeSession:
            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        monkeypatch.setattr(
            sme, "get_session", lambda: iter([_FakeSession()]),
        )
        monkeypatch.setattr(
            sme, "get_or_create_config", lambda _s: cfg,
        )
        return sme._opciones_horarias()

    def test_granularidad_15_incluye_cuartos(self, monkeypatch):
        opts = self._con_config(
            monkeypatch, 15, time(7, 0), time(23, 0),
        )
        assert "07:15" in opts and "13:45" in opts and "22:45" in opts

    def test_granularidad_30_no_ofrece_cuartos(self, monkeypatch):
        opts = self._con_config(
            monkeypatch, 30, time(8, 0), time(20, 0),
        )
        assert "08:30" in opts
        assert "08:15" not in opts and "08:45" not in opts

    def test_respeta_rango_operativo(self, monkeypatch):
        opts = self._con_config(
            monkeypatch, 15, time(9, 0), time(18, 0),
        )
        assert opts[0] == "09:00" and opts[-1] == "18:00"
        assert "07:00" not in opts and "22:00" not in opts

    def test_config_ilegible_cae_al_fallback(self, monkeypatch):
        import src.ui.schedule_materia_editor as sme

        def _boom():
            raise RuntimeError("sin DB")

        monkeypatch.setattr(sme, "get_session", _boom)
        opts = sme._opciones_horarias()
        # Fallback: paso de 15 minutos, 07:00-23:00.
        assert "07:15" in opts and "22:45" in opts
