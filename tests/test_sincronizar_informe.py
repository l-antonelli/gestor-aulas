"""Tests de scripts/drive/sincronizar.py: traer al repo las ediciones que
el usuario hace a mano en el Google Doc del informe.

El Doc es texto plano (sin la sintaxis de Markdown y con los párrafos en
una sola línea); los fuentes .md tienen los párrafos partidos en varias
líneas y marcas de formato. Una edición se aplica sólo si su fragmento
original aparece una única vez en los fuentes; si no, se informa para
pasarla a mano.
"""

from scripts.drive.sincronizar import Edicion, aplicar, aplicar_todas, ediciones


def test_detecta_un_reemplazo_de_palabra():
    viejo = "Titulo\nEn la seccion identificamos los cuatro ingredientes de un problema.\nOtro"
    nuevo = "Titulo\nEn la seccion identificamos los cuatro componentes de un problema.\nOtro"
    (e,) = ediciones(viejo, nuevo)
    assert e.antes == "ingredientes"
    assert e.despues == "componentes"
    assert "cuatro" in e.izq and "de" in e.der


def test_detecta_una_oracion_borrada_al_final_del_parrafo():
    viejo = "Da una velocidad alta. Las alternativas exigian dos piezas."
    nuevo = "Da una velocidad alta."
    (e,) = ediciones(viejo, nuevo)
    assert e.antes == "Las alternativas exigian dos piezas."
    assert e.despues == ""
    assert e.der == ""


def test_sin_cambios_no_hay_ediciones():
    assert ediciones("a b c\nd e", "a b c\nd e") == []


def test_parrafo_agregado_se_reporta_sin_contexto_de_linea():
    (e,) = ediciones("uno\ntres", "uno\ndos nuevo\ntres")
    assert e.antes == "" and e.despues == "dos nuevo"
    assert e.parrafo_nuevo


def test_aplica_aunque_el_fuente_tenga_saltos_de_linea():
    fuentes = {"cap.md": "En la seccion identificamos los cuatro\ningredientes de un problema de\nasignacion."}
    e = Edicion(antes="ingredientes", despues="componentes",
                izq="seccion identificamos los cuatro", der="de un problema de")
    archivo, texto = aplicar(e, fuentes)
    assert archivo == "cap.md"
    assert texto == "En la seccion identificamos los cuatro\ncomponentes de un problema de\nasignacion."


def test_aplica_un_borrado_de_oracion_partida_en_lineas():
    fuentes = {"cap.md": "lo que da una velocidad de desarrollo alta. Las alternativas que\nseparan exigian dos piezas.\n\nSiguiente parrafo."}
    e = Edicion(antes="Las alternativas que separan exigian dos piezas.", despues="",
                izq="una velocidad de desarrollo alta.", der="")
    _, texto = aplicar(e, fuentes)
    assert texto == "lo que da una velocidad de desarrollo alta.\n\nSiguiente parrafo."


def test_tolera_marcas_de_formato_en_el_contexto():
    fuentes = {"cap.md": "La **regla central** es que solo la capa de servicios expresa reglas."}
    e = Edicion(antes="expresa", despues="define", izq="La regla central es que solo la capa de servicios", der="reglas.")
    _, texto = aplicar(e, fuentes)
    assert texto == "La **regla central** es que solo la capa de servicios define reglas."


def test_no_aplica_si_el_fragmento_editado_tiene_formato_adentro():
    fuentes = {"cap.md": "sabe que la **regla** central importa."}
    e = Edicion(antes="regla central", despues="regla principal", izq="sabe que la", der="importa.")
    assert aplicar(e, fuentes) is None


def test_conserva_el_formato_que_rodea_al_fragmento_editado():
    fuentes = {"cap.md": "sabe que la **regla central** importa."}
    e = Edicion(antes="regla central", despues="regla principal", izq="sabe que la", der="importa.")
    _, texto = aplicar(e, fuentes)
    assert texto == "sabe que la **regla principal** importa."


def test_no_aplica_si_el_fragmento_es_ambiguo():
    fuentes = {"a.md": "el aula grande queda libre", "b.md": "el aula grande queda libre"}
    e = Edicion(antes="grande", despues="amplia", izq="el aula", der="queda libre")
    assert aplicar(e, fuentes) is None


def test_no_aplica_si_no_encuentra_el_fragmento():
    e = Edicion(antes="inexistente", despues="x", izq="nada que", der="ver")
    assert aplicar(e, {"a.md": "otro texto"}) is None


def test_aplicar_todas_acumula_cambios_y_separa_las_pendientes():
    fuentes = {"a.md": "uno dos tres cuatro cinco", "b.md": "seis siete ocho"}
    eds = [
        Edicion(antes="dos", despues="DOS", izq="uno", der="tres cuatro"),
        Edicion(antes="siete", despues="SIETE", izq="seis", der="ocho"),
        Edicion(antes="nueve", despues="NUEVE", izq="no", der="existe"),
    ]
    nuevos, pendientes = aplicar_todas(eds, fuentes)
    assert nuevos == {"a.md": "uno DOS tres cuatro cinco", "b.md": "seis SIETE ocho"}
    assert [p.antes for p in pendientes] == ["nueve"]


def test_varias_ediciones_en_un_parrafo_se_aplican_todas_o_ninguna():
    # Caso real: el título de R6 cambió en dos lugares del mismo párrafo.
    # Antes se aplicaba sólo una parte y quedaba "Sobre y asientos vacíos".
    viejo = "R6. Alumnos sin lugar y asientos vacíos de más. Para cada horario, los alumnos"
    nuevo = "R6. Sobre y subocupación. Para cada horario, los alumnos"
    fuentes = {"c.md": "**R6. Alumnos sin lugar y asientos vacíos de más.** *Para cada\nhorario, los alumnos"}
    eds = ediciones(viejo, nuevo)
    cambiados, pendientes = aplicar_todas(eds, fuentes)
    if pendientes:
        assert cambiados == {}  # nada a medias
    else:
        assert cambiados["c.md"] == "**R6. Sobre y subocupación.** *Para cada\nhorario, los alumnos"


def test_dos_cambios_separados_en_un_parrafo_quedan_completos():
    viejo = "La regla de coherencia teoria y laboratorio se aplica a cada comision del plan."
    nuevo = "La regla de horas de teoria y laboratorio se aplica a cada comision del cronograma."
    fuentes = {"c.md": "La regla de coherencia teoria y laboratorio se aplica\na cada comision del plan."}
    cambiados, pendientes = aplicar_todas(ediciones(viejo, nuevo), fuentes)
    assert pendientes == []
    assert cambiados["c.md"] == "La regla de horas de teoria y laboratorio se aplica\na cada comision del cronograma."
