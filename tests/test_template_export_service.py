"""Tests para template_export_service.

Fase C1 del rediseño 2026-09-15: verifica la generación de la
plantilla Excel de cronograma. Foco en la estructura correcta del
archivo generado (hojas presentes, DataValidation aplicado a las
columnas correctas, listas de códigos válidos) y en los guards
razonables (ciclo inexistente, ciclo sin dictados).
"""

from __future__ import annotations

import io
import uuid
from datetime import date

import pytest
from openpyxl import load_workbook
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from src.database.models import (
    CarreraDB,
    CicloDB,
    CicloPlanVersionDB,
    MateriaDB,
    PlanCarreraVersionDB,
    PlanEstudioDB,
)
from src.services.dictado_service import create_dictados_for_ciclo
from src.services.template_export_service import (
    generar_plantilla_cronograma_excel,
    obtener_referencia_materias_del_ciclo,
)


# =============================================================================
# Fixtures
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
def ciclo_con_2_materias(session):
    """Ciclo 2025-1C con MAT101 y FIS101 activos como dictados."""
    session.add(CarreraDB(codigo="ING", nombre="Ingeniería"))
    session.flush()

    pv = PlanCarreraVersionDB(
        id=str(uuid.uuid4()), carrera_codigo="ING",
        nombre="Plan A", fecha_creacion=date(2025, 1, 1),
    )
    session.add(pv)
    session.flush()

    session.add(MateriaDB(
        codigo="MAT101", nombre="Análisis I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    ))
    session.add(MateriaDB(
        codigo="FIS101", nombre="Física I",
        periodo="cuatrimestral", active=True, horas_semanales=6,
    ))
    session.flush()

    for mc in ("MAT101", "FIS101"):
        session.add(PlanEstudioDB(
            plan_version_id=pv.id, materia_codigo=mc,
            carrera_codigo="ING", anio_plan=1, cuatrimestre_plan="1C",
        ))

    ciclo = CicloDB(
        id="2025-1C", anio=2025, numero=1,
        fecha_inicio=date(2025, 3, 10), fecha_fin=date(2025, 7, 5),
    )
    session.add(ciclo)
    session.flush()
    session.add(CicloPlanVersionDB(ciclo_id=ciclo.id, plan_version_id=pv.id))
    session.commit()
    create_dictados_for_ciclo(session, ciclo.id)

    return {"ciclo": ciclo, "pv": pv}


# =============================================================================
# Tests
# =============================================================================


class TestGuards:
    def test_ciclo_inexistente_falla(self, session):
        with pytest.raises(ValueError, match="no existe"):
            generar_plantilla_cronograma_excel(session, "ciclo-fantasma")

    def test_ciclo_sin_dictados_falla(self, session, ciclo_con_2_materias):
        """Sin dictados creados, la plantilla no tiene lista de códigos
        posibles → mejor abortar con mensaje claro que generar un
        dropdown vacío.
        """
        # Crear un ciclo separado sin dictados
        c2 = CicloDB(
            id="2025-2C", anio=2025, numero=2,
            fecha_inicio=date(2025, 8, 1), fecha_fin=date(2025, 11, 30),
        )
        session.add(c2)
        session.commit()

        with pytest.raises(ValueError, match="dictados"):
            generar_plantilla_cronograma_excel(session, c2.id)


class TestEstructuraDelArchivo:
    def test_plantilla_tiene_hojas_esperadas(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        assert "Instrucciones" in wb.sheetnames
        assert "Horarios" in wb.sheetnames
        # Hoja VISIBLE de referencia (2026-09-23): reemplaza a la
        # oculta `_materias` y expone codigo+nombre.
        assert "Materias" in wb.sheetnames
        assert "_materias" not in wb.sheetnames
        # Hojas ocultas de listas
        assert "_dias" in wb.sheetnames
        assert "_tipos" in wb.sheetnames
        assert "_virtual" in wb.sheetnames

    def test_hojas_de_listas_estan_ocultas(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        for nombre in ("_dias", "_tipos", "_virtual"):
            assert wb[nombre].sheet_state == "hidden", (
                f"Hoja {nombre} debería estar oculta"
            )
        # La referencia de materias es VISIBLE (2026-09-23).
        assert wb["Materias"].sheet_state == "visible"

    def test_instrucciones_es_la_primera_hoja(self, session, ciclo_con_2_materias):
        """`Instrucciones` es la pestaña activa al abrir el archivo."""
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        assert wb.sheetnames[0] == "Instrucciones"
        assert wb.active.title == "Instrucciones"

    def test_headers_horarios_correctos(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        headers = [ws.cell(row=1, column=c).value for c in range(1, 10)]
        # Esquema 2026-09-24: el NOMBRE va primero (pedido del
        # usuario) pero es de sólo lectura — se autocompleta por
        # fórmula al elegir el código en la segunda columna, que es
        # la única entrada de materia. Comisión con código numérico
        # obligatorio + nombre opcional.
        assert headers == [
            "nombre_materia", "codigo_materia",
            "codigo_comision", "nombre_comision",
            "dia", "hora_inicio", "hora_fin",
            "tipo_clase", "virtual",
        ]

    def test_fila_2_esta_vacia_para_evitar_import_del_ejemplo(
        self, session, ciclo_con_2_materias,
    ):
        """Bugfix task #341 (2026-09-22): la fila 2 no debe contener el
        ejemplo `MAT101 · Lunes · 08:00 · 11:00`. Antes se escribía en
        amarillo como guía visual pero el parser no distingue ejemplo
        de dato real: si el usuario subía la plantilla sin borrar la
        fila 2, el ejemplo se importaba como horario válido.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        # La columna A (nombre) lleva la fórmula de autocompletado,
        # que evalúa a "" mientras no se elija código. La B (código)
        # es entrada pura del usuario, sin fórmula.
        _a2 = ws.cell(row=2, column=1).value
        assert _a2 is None or str(_a2).startswith("=IFERROR"), (
            f"Fila 2 col A debería ser fórmula o vacía: {_a2!r}"
        )
        # Las demás celdas de la fila 2 deben estar vacías (sin datos
        # de ejemplo).
        for col in range(2, 10):
            assert ws.cell(row=2, column=col).value in (None, ""), (
                f"Fila 2 columna {col} no está vacía: "
                f"{ws.cell(row=2, column=col).value!r}"
            )

    def test_roundtrip_template_no_importa_filas_fantasma(
        self, session, ciclo_con_2_materias,
    ):
        """Regresión task #341: descargar la plantilla y pasarla al
        parser no debe devolver ningún ``HorarioInput`` — el usuario
        aún no cargó nada.
        """
        from src.services.horario_file_parser import parse_horarios_file

        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        upload = io.BytesIO(contenido)
        upload.name = "plantilla.xlsx"  # type: ignore[attr-defined]
        inputs, errors = parse_horarios_file(upload)
        assert inputs == [], (
            f"El parser debería devolver una lista vacía, obtuvo: {inputs}"
        )
        assert errors == [], f"No debería haber errores, obtuvo: {errors}"


class TestListasDeValores:
    def test_lista_de_materias_incluye_solo_dictados_activos(
        self, session, ciclo_con_2_materias,
    ):
        """La hoja `Materias` tiene exactamente los códigos con
        dictado activo en el ciclo (con su nombre al lado). Ni más
        ni menos.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Materias"]
        # Fila 1 = header; datos desde fila 2. Desde 2026-09-24 el
        # nombre va primero (col A) y el código segundo (col B).
        nombres = [
            ws.cell(row=r, column=1).value
            for r in range(2, ws.max_row + 1)
        ]
        codigos = [
            ws.cell(row=r, column=2).value
            for r in range(2, ws.max_row + 1)
        ]
        assert sorted(codigos) == ["FIS101", "MAT101"]
        assert sorted(nombres) == ["Análisis I", "Física I"]

    def test_hoja_materias_protegida_y_con_contexto(
        self, session, ciclo_con_2_materias,
    ):
        """La hoja `Materias` queda protegida (sólo lectura,
        2026-09-24) y suma el contexto completo de cada materia:
        atributos del catálogo, en qué planes de carrera aparece y
        en qué momento, y cómo está configurado el dictado del ciclo
        (modalidad, recursado).
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Materias"]
        assert ws.protection.sheet is True

        headers = [
            ws.cell(row=1, column=c).value
            for c in range(1, ws.max_column + 1)
        ]
        for esperado in (
            "Nombre", "Código", "Código Guaraní", "Período",
            "Hs/sem", "Hs teoría", "Hs laboratorio", "Cupo",
            "Optativa", "Virtual (catálogo)",
            "Planes de carrera (año y cuatrimestre)",
            "Dictado del ciclo", "Modalidad del dictado",
            "Dictado de recursado",
        ):
            assert esperado in headers, f"Falta header {esperado!r}"

        # Fila de MAT101 (Análisis I): plan ING 1° año 1C, dictado
        # presencial (sin overrides) y no recursado (mismo cuatri).
        _por_codigo = {
            ws.cell(row=r, column=2).value: r
            for r in range(2, ws.max_row + 1)
        }
        _r = _por_codigo["MAT101"]
        _fila = {
            headers[c - 1]: ws.cell(row=_r, column=c).value
            for c in range(1, ws.max_column + 1)
        }
        assert _fila["Nombre"] == "Análisis I"
        assert _fila["Período"] == "cuatrimestral"
        assert _fila["Hs/sem"] == 6
        assert _fila["Virtual (catálogo)"] == "no"
        assert "ING" in str(_fila["Planes de carrera (año y cuatrimestre)"])
        assert "1C" in str(_fila["Planes de carrera (año y cuatrimestre)"])
        assert "MAT101" in str(_fila["Dictado del ciclo"])
        assert _fila["Modalidad del dictado"] == "presencial"
        assert _fila["Dictado de recursado"] == "no"

    def test_lista_dias_estandar(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["_dias"]
        dias = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        assert dias == [
            "Lunes", "Martes", "Miércoles", "Jueves", "Viernes",
            "Sábado", "Domingo",
        ]

    def test_lista_tipos_clase(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["_tipos"]
        tipos = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        assert tipos == ["teorica", "laboratorio"]

    def test_lista_virtual_booleana(self, session, ciclo_con_2_materias):
        """La columna virtual es un booleano (2026-09-23): la lista
        ofrece VERDADERO/FALSO como **booleanos reales** de Excel, no
        los textos SI/NO. Elegir del desplegable deja un bool en la
        celda, que pandas lee como ``bool`` y el parser interpreta
        directo (vacío = FALSO).
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["_virtual"]
        opts = [ws.cell(row=r, column=1).value for r in range(1, ws.max_row + 1)]
        assert opts == [True, False]
        assert all(isinstance(o, bool) for o in opts)


class TestDataValidations:
    def test_hay_data_validation_en_columnas_esperadas(
        self, session, ciclo_con_2_materias,
    ):
        """La hoja Horarios tiene DataValidation configurados para
        codigo_materia (B), codigo_comision (C), dia (E),
        hora_inicio (F), hora_fin (G), tipo_clase (H) y virtual (I).

        La columna A (nombre_materia) NO lleva desplegable
        (2026-09-24): es de sólo lectura, se autocompleta por fórmula
        al elegir el código. La D (nombre_comision) es texto libre.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        # openpyxl expone las DataValidation en ws.data_validations
        ranges_cubiertos: list[str] = []
        for dv in ws.data_validations.dataValidation:
            for r in dv.sqref.ranges:
                ranges_cubiertos.append(str(r))

        # Cada columna crítica debe tener al menos un rango.
        cols_letra = ["B", "C", "E", "F", "G", "H", "I"]
        for letra in cols_letra:
            assert any(
                r.startswith(f"{letra}2") for r in ranges_cubiertos
            ), (
                f"Falta DataValidation para columna {letra}. "
                f"Rangos vistos: {ranges_cubiertos}"
            )
        # Nombre de materia (A) y nombre de comisión (D) sin validación.
        for letra in ("A", "D"):
            assert not any(
                r.startswith(f"{letra}2") for r in ranges_cubiertos
            ), (
                f"La columna {letra} no debería tener DataValidation. "
                f"Rangos vistos: {ranges_cubiertos}"
            )

    def test_lista_materias_referencia_hoja_materias(
        self, session, ciclo_con_2_materias,
    ):
        """La validación de codigo_materia (B) referencia la columna
        de códigos de la hoja visible `Materias` (col B desde
        2026-09-24: la hoja Materias también lleva el nombre
        primero). El nombre (A) no tiene desplegable: se autocompleta
        por fórmula.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]

        dv_materias = None
        for dv in ws.data_validations.dataValidation:
            if any(str(r).startswith("B2") for r in dv.sqref.ranges):
                dv_materias = dv
                break

        assert dv_materias is not None
        assert dv_materias.type == "list"
        assert "Materias!$B$" in (dv_materias.formula1 or "")

    def test_nombre_materia_se_autocompleta_por_formula(
        self, session, ciclo_con_2_materias,
    ):
        """La columna A (nombre_materia) trae la fórmula que muestra
        el nombre al elegir un código (2026-09-24): es de sólo
        lectura, el usuario no la completa.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        for fila in (2, 500, 1001):
            _a = str(ws.cell(row=fila, column=1).value or "")
            assert _a.startswith("=IFERROR"), f"Fila {fila}: {_a!r}"
            assert "Materias!$A$" in _a
            assert f"$B{fila}" in _a

    def test_hoja_protegida_con_nombre_bloqueado(
        self, session, ciclo_con_2_materias,
    ):
        """La hoja Horarios queda protegida (sin contraseña,
        2026-09-24) para que la columna del nombre no se pueda editar
        ni elegir a mano: sólo el código es entrada del usuario. Las
        celdas de las demás columnas están desbloqueadas.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        assert ws.protection.sheet is True
        # A (nombre_materia) bloqueada; el resto editable.
        assert ws.cell(row=2, column=1).protection.locked is True
        for col in range(2, 10):
            assert ws.cell(row=2, column=col).protection.locked is False, (
                f"Columna {col} debería estar desbloqueada"
            )

    def test_laboratorio_y_virtual_son_desplegables_dependientes(
        self, session, ciclo_con_2_materias,
    ):
        """Excel no debe dejar combinar laboratorio + virtual
        (2026-09-24): las fuentes de los desplegables son fórmulas
        condicionales por fila. Con tipo = laboratorio, la lista de
        virtual sólo ofrece FALSO; con virtual = VERDADERO, la lista
        de tipo sólo ofrece teorica. La validación también rechaza el
        valor si se tipea a mano.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]

        dv_tipo = dv_virt = None
        for dv in ws.data_validations.dataValidation:
            if any(str(r).startswith("H2") for r in dv.sqref.ranges):
                dv_tipo = dv
            if any(str(r).startswith("I2") for r in dv.sqref.ranges):
                dv_virt = dv

        assert dv_virt is not None
        _f_virt = dv_virt.formula1 or ""
        assert _f_virt.startswith("=IF(")
        assert "$H2" in _f_virt
        # Rama restringida: sólo FALSO (fila 2 de _virtual).
        assert "_virtual!$A$2:$A$2" in _f_virt
        assert "_virtual!$A$1:$A$2" in _f_virt

        assert dv_tipo is not None
        _f_tipo = dv_tipo.formula1 or ""
        assert _f_tipo.startswith("=IF(")
        assert "$I2" in _f_tipo
        # Rama restringida: sólo teorica (fila 1 de _tipos).
        assert "_tipos!$A$1:$A$1" in _f_tipo
        assert "_tipos!$A$1:$A$2" in _f_tipo

    def test_hoja_horarios_es_tabla_de_excel(
        self, session, ciclo_con_2_materias,
    ):
        """La hoja Horarios queda definida como tabla de Excel
        (2026-09-23): filtros por columna y bandas de color.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        ws = wb["Horarios"]
        assert "TablaHorarios" in ws.tables
        assert ws.tables["TablaHorarios"].ref == "A1:I1001"

    def test_recalculo_al_abrir_activado(
        self, session, ciclo_con_2_materias,
    ):
        """`fullCalcOnLoad` queda activado (2026-09-23): openpyxl no
        guarda valores cacheados de las fórmulas, así que sin este
        flag algunos programas muestran la columna del código sin
        recalcular hasta que el usuario fuerza un recálculo.
        """
        ciclo = ciclo_con_2_materias["ciclo"]
        contenido = generar_plantilla_cronograma_excel(session, ciclo.id)

        wb = load_workbook(io.BytesIO(contenido))
        assert wb.calculation.fullCalcOnLoad is True


class TestReferenciaMaterias:
    def test_devuelve_pares_codigo_nombre(self, session, ciclo_con_2_materias):
        ciclo = ciclo_con_2_materias["ciclo"]
        refs = obtener_referencia_materias_del_ciclo(session, ciclo.id)
        assert refs == [
            ("FIS101", "Física I"),
            ("MAT101", "Análisis I"),
        ]

    def test_devuelve_vacio_si_no_hay_dictados(self, session):
        c = CicloDB(
            id="2025-2C", anio=2025, numero=2,
            fecha_inicio=date(2025, 8, 1), fecha_fin=date(2025, 11, 30),
        )
        session.add(c)
        session.commit()
        assert obtener_referencia_materias_del_ciclo(session, c.id) == []
