"""Chequeo de factibilidad estructural del plan antes de correr el LP
(Fase 7).

Consolida en un único servicio los chequeos que detectan situaciones
que van a hacer al LP infactible por diseño — antes de gastarnos el
tiempo de un solve completo. Recorre las mismas familias que
`diagnose_infeasibility` y las extiende con compatibilidad de labs
por celda (pigeonhole + Hall).

La función pública es `check_factibilidad_estructural(session, plan_id)`.
Devuelve un `ReporteFactibilidad` que la UI puede renderizar como
semáforo + panel de detalles.

Familias de bloqueos detectadas:

- **R1 · Horario sin aula compatible**: un horario individual no
  tiene ninguna aula del catálogo que pueda recibirlo (falta lab
  compatible, sede admisible vacía, tipo desalineado).
- **R3+R4 · Franja saturada por tipo**: refinamiento de pigeonhole
  discriminando teórica vs laboratorio.
- **R5 · Partición teoría/lab imposible**: la suma de duraciones de
  los horarios de una comisión no admite bipartición según las horas
  declaradas por la materia.
- **compat-pigeonhole**: en una franja, la unión de labs
  compatibles de las materias con demanda no alcanza para la demanda.
- **compat-hall**: subconjunto de materias con lab que comparten un
  pool insuficiente aunque la unión global cierre.
- **R11 · Pin manual incompatible**: un horario tiene un aula
  manual fijada que ya no es compatible (cambió tipo, sede, etc.).
- **R13 · Sedes consecutivas sin sede común**: un par de horarios
  contiguos de la misma comisión con gap < margen no tiene ninguna
  sede admisible en común.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from sqlmodel import Session, select

from src.database.models import (
    AulaDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    MateriaDB,
    MateriaLaboratorioDB,
    PlanificacionCursadaDB,
    SedeDB,
)
from src.services.asignacion_aulas_helpers import (
    AulaSlot,
    HorarioSlot,
    check_lab_compatibilidad_en_celda,
    compute_compat,
    compute_pares_intersede_riesgo,
    compute_simultaneidad_groups,
    diagnose_infeasibility,
    validar_particion_factible,
)
from src.services.carrera_sede_service import (
    sedes_admisibles_para_carrera,
    sedes_admisibles_para_materia,
)
from src.services.resolucion_jerarquica import resolve_virtual


# =============================================================================
# Dataclasses de salida
# =============================================================================


@dataclass
class Bloqueo:
    """Un problema concreto detectado por el chequeo estructural."""
    codigo_regla: str          # p.ej. "R1", "R5", "compat-hall"
    severidad: str             # "bloqueante" | "advertencia"
    titulo: str                # línea corta con el problema
    detalle: str               # markdown con contexto (materias, aulas, día)
    entidades_a_revisar: list[str] = field(default_factory=list)


@dataclass
class ReporteFactibilidad:
    plan_id: str
    factible: bool
    bloqueos: list[Bloqueo] = field(default_factory=list)
    advertencias: list[Bloqueo] = field(default_factory=list)
    resumen_por_regla: dict[str, int] = field(default_factory=dict)

    def n_bloqueos(self) -> int:
        return len(self.bloqueos)


# =============================================================================
# Chequeo principal
# =============================================================================


def check_factibilidad_estructural(
    session: Session,
    plan_id: str,
    *,
    margen_min_intersede_minutos: int = 30,
) -> ReporteFactibilidad:
    """Analiza el plan y devuelve un reporte con bloqueos estructurales.

    `factible=True` significa que el chequeo no encontró bloqueos
    estructurales conocidos — el LP todavía puede resultar infactible
    por combinaciones no detectadas, pero no por las causas típicas.
    """
    reporte = ReporteFactibilidad(plan_id=plan_id, factible=True)

    plan = session.get(PlanificacionCursadaDB, plan_id)
    if plan is None:
        reporte.factible = False
        reporte.bloqueos.append(Bloqueo(
            codigo_regla="input",
            severidad="bloqueante",
            titulo="Plan inexistente",
            detalle=f"No se encontró el plan `{plan_id}` en la base.",
        ))
        return reporte

    # -------------------------------------------------------------------------
    # Cargar horarios activos y catálogos (misma lógica que build_inputs).
    # -------------------------------------------------------------------------
    comisiones = list(session.exec(
        select(ComisionDB).where(ComisionDB.plan_cursada_id == plan_id)
    ).all())
    if not comisiones:
        reporte.advertencias.append(Bloqueo(
            codigo_regla="input",
            severidad="advertencia",
            titulo="Plan sin comisiones",
            detalle="El plan no tiene ninguna comisión asociada.",
        ))
        return reporte
    com_ids = [c.id for c in comisiones]
    com_by_id = {c.id: c for c in comisiones}
    carrera_override = {c.id: c.carrera_asignada for c in comisiones}

    horarios_db = list(session.exec(
        select(HorarioDB).where(HorarioDB.comision_id.in_(com_ids))  # type: ignore[attr-defined]
    ).all())

    mat_codes = sorted({h.codigo_materia for h in horarios_db})
    materias_db = list(session.exec(
        select(MateriaDB).where(MateriaDB.codigo.in_(mat_codes))  # type: ignore[attr-defined]
    ).all()) if mat_codes else []
    mat_nombre = {m.codigo: m.nombre for m in materias_db}
    materia_virtual = {m.codigo: m.virtual for m in materias_db}
    materia_dict_virtual: dict[str, Optional[bool]] = {}
    if plan.ciclo_id:
        for mc, v in session.exec(
            select(DictadoDB.materia_codigo, DictadoDB.virtual)
            .join(DictadoCicloDB, DictadoDB.id == DictadoCicloDB.dictado_id)  # type: ignore[arg-type]
            .where(DictadoCicloDB.ciclo_id == plan.ciclo_id)
        ).all():
            materia_dict_virtual[mc] = v

    # Filtrar virtuales para todo lo que tiene que ver con asignación
    # de aula (R1, R3, R4, R10, R13, compat-hall). Pero mantener una
    # lista aparte con TODOS los horarios (incluidos virtuales) para
    # R5 — la partición teoría/lab tiene que reflejar todas las horas
    # que se dictan, no sólo las que ocupan aula.
    hteo = {m.codigo: float(m.horas_teoria or 0) for m in materias_db}
    hlab = {m.codigo: float(m.horas_laboratorio or 0) for m in materias_db}

    horarios_slots: list[HorarioSlot] = []
    horarios_slots_con_virtuales: list[HorarioSlot] = []
    materia_de_horario: dict[str, str] = {}
    comision_de_horario: dict[str, str] = {}
    dur: dict[str, float] = {}
    horario_db_by_id: dict[str, HorarioDB] = {}
    for h in horarios_db:
        # Inferir tipo si materia sólo declara uno.
        tipo_efectivo = h.tipo_clase
        if tipo_efectivo is None:
            m_hteo = hteo.get(h.codigo_materia, 0)
            m_hlab = hlab.get(h.codigo_materia, 0)
            if m_hteo > 0 and m_hlab == 0:
                tipo_efectivo = "teorica"
            elif m_hlab > 0 and m_hteo == 0:
                tipo_efectivo = "laboratorio"
        slot = HorarioSlot(
            id=h.id, dia=h.dia,
            hora_inicio=h.hora_inicio, hora_fin=h.hora_fin,
            materia_codigo=h.codigo_materia,
            tipo_clase=tipo_efectivo,
        )
        materia_de_horario[h.id] = h.codigo_materia
        comision_de_horario[h.id] = h.comision_id
        h_s = h.hora_inicio.hour + h.hora_inicio.minute / 60
        h_e = h.hora_fin.hour + h.hora_fin.minute / 60
        dur[h.id] = h_e - h_s
        horario_db_by_id[h.id] = h

        horarios_slots_con_virtuales.append(slot)
        # Los virtuales quedan afuera de las validaciones que dependen
        # de asignación de aula, pero entran en la lista completa para R5.
        if resolve_virtual(
            horario_virtual=h.virtual,
            dictado_virtual=materia_dict_virtual.get(h.codigo_materia),
            materia_virtual=materia_virtual.get(h.codigo_materia, False),
        ):
            continue
        horarios_slots.append(slot)

    if not horarios_slots:
        reporte.advertencias.append(Bloqueo(
            codigo_regla="input",
            severidad="advertencia",
            titulo="Plan sin horarios activos",
            detalle="No hay horarios no-virtuales en el plan.",
        ))
        return reporte

    aulas_db = list(session.exec(select(AulaDB)).all())
    aulas_slots = [
        AulaSlot(id=a.id, tipo=a.tipo, capacidad=a.capacidad)
        for a in aulas_db
    ]
    aula_by_id = {a.id: a for a in aulas_db}
    aula_sede_id = {a.id: a.sede_id for a in aulas_db}
    aulas_lab_ids_total = {a.id for a in aulas_db if a.tipo == "laboratorio"}

    sedes_db = list(session.exec(select(SedeDB)).all())
    sede_nombre = {s.id: s.nombre for s in sedes_db}

    # materia_lab_map.
    lab_pairs = list(session.exec(select(MateriaLaboratorioDB)).all())
    materia_lab_map: dict[str, set[str]] = {}
    for ml in lab_pairs:
        materia_lab_map.setdefault(ml.materia_codigo, set()).add(ml.aula_id)

    # Sedes admisibles resueltas por HORARIO (respetando override).
    sedes_admis_mat: dict[str, Optional[set[str]]] = {
        mc: sedes_admisibles_para_materia(session, mc)
        for mc in mat_codes
    }
    carreras_over_unicas = sorted({
        c for c in carrera_override.values() if c
    })
    sedes_admis_carr: dict[str, Optional[set[str]]] = {
        cc: sedes_admisibles_para_carrera(session, cc)
        for cc in carreras_over_unicas
    }

    def _sedes_admis_del_horario(h_id: str) -> Optional[set[str]]:
        cid = comision_de_horario.get(h_id)
        car = carrera_override.get(cid) if cid else None
        if car:
            return sedes_admis_carr.get(car)
        mc = materia_de_horario.get(h_id, "")
        return sedes_admis_mat.get(mc)

    # -------------------------------------------------------------------------
    # Construir compat[(h,a)] con filtro R3 + R10 (idéntico a build_inputs
    # de manera abreviada).
    # -------------------------------------------------------------------------
    compat: dict[tuple[str, str], bool] = {}
    for h in horarios_slots:
        labs_m = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas_slots:
            compat[(h.id, a.id)] = compute_compat(h, a, labs_m)
    for h in horarios_slots:
        admis = _sedes_admis_del_horario(h.id)
        if admis is None:
            continue
        labs_m = materia_lab_map.get(h.materia_codigo, set())
        for a in aulas_slots:
            if not compat[(h.id, a.id)]:
                continue
            if a.id in labs_m:
                continue  # Lab compatible prevalece sobre R10.
            if aula_sede_id.get(a.id) not in admis:
                compat[(h.id, a.id)] = False

    sim_groups = compute_simultaneidad_groups(horarios_slots)

    # =========================================================================
    # 1. Diagnóstico estructural clásico (R1, R3+R4, R5, Hall global).
    # =========================================================================
    diag = diagnose_infeasibility(
        horarios=horarios_slots, aulas=aulas_slots,
        materia_lab_map=materia_lab_map, sim_groups=sim_groups,
        compat_override=compat,
    )

    # R1: horarios sin aula compatible.
    for item in diag.horarios_sin_aula_compatible:
        mc = item["materia_codigo"]
        reporte.bloqueos.append(Bloqueo(
            codigo_regla="R1",
            severidad="bloqueante",
            titulo=(
                f"Horario sin aula compatible · {mc} "
                f"({mat_nombre.get(mc, '?')})"
            ),
            detalle=(
                f"- **Materia**: `{mc}` · {mat_nombre.get(mc, '?')}\n"
                f"- **Día/Hora**: {item['dia']} "
                f"{item['hora_inicio']}–{item['hora_fin']}\n"
                f"- **Tipo de clase**: {item['tipo_clase']}\n"
                f"- **Motivo**: {item['razon']}"
            ),
            entidades_a_revisar=[f"materia:{mc}"],
        ))

    # R3+R4: saturación por tipo (más informativa que la global).
    for item in diag.saturacion_por_tipo:
        tipo = item["tipo"]
        codigo = "R3+R4"
        mats = item.get("materias", [])
        materia_ref = item.get("materia")  # para labs, la materia puntual
        titulo = (
            f"{item['n_necesarias']} clases {tipo} simultáneas · "
            f"sólo hay {item['n_disponibles']} aula(s) del tipo · "
            f"{item['dia']} {item['solapan_inicio']}–{item['solapan_fin']}"
        )
        detalle_lines = [
            f"- **Franja de solapamiento**: {item['dia']} "
            f"{item['solapan_inicio']}–{item['solapan_fin']}",
            f"- **Clases {tipo} necesarias**: {item['n_necesarias']}",
            f"- **Aulas del tipo disponibles**: {item['n_disponibles']}",
        ]
        if materia_ref:
            detalle_lines.append(f"- **Materia**: `{materia_ref}`")
        if mats:
            detalle_lines.append(
                "- **Materias involucradas**: "
                + ", ".join(f"`{m}`" for m in mats)
            )
        reporte.bloqueos.append(Bloqueo(
            codigo_regla=codigo,
            severidad="bloqueante",
            titulo=titulo,
            detalle="\n".join(detalle_lines),
            entidades_a_revisar=[f"materia:{m}" for m in mats],
        ))

    # R5: particiones teoría/lab imposibles.
    # Sólo aplica a materias con laboratorio (hlab > 0). Para materias
    # sin laboratorio, la ecuación R5 del LP no se instancia: los
    # horarios teóricos "flotan libres" y una suma menor a hteo+hlab
    # no genera infactibilidad estructural. Alineado con la validación
    # oficial del panel de Detalle (que también filtra por hlab > 0).
    #
    # IMPORTANTE: acá usamos `horarios_slots_con_virtuales` (no la
    # lista filtrada). Los horarios virtuales SÍ cuentan hacia las
    # horas totales de la materia — "virtual" significa "no ocupa
    # aula", no "no se dicta". Si la teoría se divide en presencial
    # + virtual, ambas partes suman para hteo. El LP no valida esto
    # hoy (bug conocido: sólo verifica igualdad sobre hlab), pero
    # nuestro chequeo pre-solve sí puede detectarlo.
    horarios_por_comision: dict[str, list[tuple[str, float, str | None]]] = {}
    for h in horarios_slots_con_virtuales:
        cid = comision_de_horario[h.id]
        # Materias sin laboratorio: R5 no se aplica.
        if hlab.get(h.materia_codigo, 0.0) <= 0:
            continue
        horarios_por_comision.setdefault(cid, []).append(
            (h.id, dur[h.id], h.tipo_clase)
        )
    materia_de_comision: dict[str, str] = {}
    for cid, lista in horarios_por_comision.items():
        if lista:
            materia_de_comision[cid] = materia_de_horario[lista[0][0]]
    problemas_particion = validar_particion_factible(
        horarios_por_comision=horarios_por_comision,
        hteo=hteo, hlab=hlab,
        materia_de_comision=materia_de_comision,
    )
    for prob in problemas_particion:
        cid = prob.get("comision_id", "")
        com = com_by_id.get(cid) if cid else None
        com_lbl = com.nombre if com else cid
        mc = prob.get("materia", "")
        reporte.bloqueos.append(Bloqueo(
            codigo_regla="R5",
            severidad="bloqueante",
            titulo=(
                f"Partición teoría/lab imposible · {mc} "
                f"({mat_nombre.get(mc, '?')}) · com. {com_lbl}"
            ),
            detalle=(
                f"- **Materia**: `{mc}` · {mat_nombre.get(mc, '?')}\n"
                f"- **Comisión**: {com_lbl}\n"
                f"- **Motivo**: {prob.get('razon', '')}"
            ),
            entidades_a_revisar=[f"materia:{mc}"],
        ))

    # =========================================================================
    # 2. Compatibilidad de labs por celda: pigeonhole + Hall.
    # =========================================================================
    # Agrupar horarios de lab por (día, franja de 15min).
    # Para pigeonhole/Hall miramos la unión de labs compatibles filtrando
    # también por sede: labs = compatibles ∩ (sedes admisibles del horario).
    # Para simplificar, primero chequeamos con el catálogo total (peor caso
    # más informativo) — así detectamos aunque las sedes admisibles cubran
    # todo.
    from datetime import time as _time

    # Instantes de inicio y fin únicos por día.
    def _min(t: _time) -> int:
        return t.hour * 60 + t.minute

    # Para chequeo por celda: recorremos cada franja de 15 min y agrupamos
    # horarios de lab activos ahí.
    lab_por_celda: dict[tuple[str, int], list[HorarioSlot]] = {}
    for h in horarios_slots:
        if h.tipo_clase != "laboratorio":
            continue
        h_s = _min(h.hora_inicio)
        h_e = _min(h.hora_fin)
        # cada franja de 15 min que intersecta el horario
        for slot_ini in range(h_s, h_e, 15):
            lab_por_celda.setdefault((h.dia, slot_ini), []).append(h)

    hall_reportado: set[tuple[str, ...]] = set()
    pigeon_reportado: set[tuple[str, ...]] = set()
    for (dia, slot_ini), horarios_celda in lab_por_celda.items():
        if len(horarios_celda) < 2:
            continue
        check = check_lab_compatibilidad_en_celda(
            horarios_lab_en_celda=horarios_celda,
            materia_lab_map=materia_lab_map,
            aulas_lab_catalogo=aulas_lab_ids_total,
        )
        if not (check.infactible_pigeonhole or check.infactible_hall):
            continue
        mats_involucradas = tuple(sorted({
            h.materia_codigo for h in horarios_celda
        }))
        franja = (
            f"{slot_ini // 60:02d}:{slot_ini % 60:02d}–"
            f"{(slot_ini + 15) // 60:02d}:{(slot_ini + 15) % 60:02d}"
        )
        if check.infactible_pigeonhole:
            # Dedup por (materias, día) para no saturar con la misma
            # infactibilidad repetida por cada franja de 15 min.
            key_p = ("pigeon", dia, *mats_involucradas)
            if key_p not in pigeon_reportado:
                pigeon_reportado.add(key_p)
                reporte.bloqueos.append(Bloqueo(
                    codigo_regla="compat-pigeonhole",
                    severidad="bloqueante",
                    titulo=(
                        f"{check.demanda} labs simultáneos, sólo "
                        f"{check.oferta_compatible} lab(s) compatibles "
                        f"· {dia} {franja}"
                    ),
                    detalle=(
                        f"- **Día/Franja**: {dia} {franja}\n"
                        f"- **Horarios de lab simultáneos**: "
                        f"{check.demanda}\n"
                        f"- **Labs compatibles (unión)**: "
                        f"{check.oferta_compatible}\n"
                        f"- **Materias involucradas**: "
                        + ", ".join(
                            f"`{m}` ({mat_nombre.get(m, '?')})"
                            for m in mats_involucradas
                        )
                        + "\n\n"
                        "Amplía los labs compatibles de esas materias "
                        "o cambiá el cronograma para desolapar."
                    ),
                    entidades_a_revisar=[
                        f"materia:{m}" for m in mats_involucradas
                    ],
                ))
        elif check.infactible_hall:
            sub = tuple(sorted(check.subconjunto_hall))
            key_h = ("hall", dia, *sub)
            if key_h not in hall_reportado:
                hall_reportado.add(key_h)
                reporte.bloqueos.append(Bloqueo(
                    codigo_regla="compat-hall",
                    severidad="bloqueante",
                    titulo=(
                        f"Subconjunto Hall · {{"
                        + ", ".join(f"`{m}`" for m in sub)
                        + f"}} · {dia} {franja}"
                    ),
                    detalle=(
                        f"- **Día/Franja**: {dia} {franja}\n"
                        f"- **Subconjunto conflictivo**: "
                        + ", ".join(
                            f"`{m}` ({mat_nombre.get(m, '?')})"
                            for m in sub
                        )
                        + "\n"
                        f"- **Motivo**: comparten un pool de labs "
                        "más chico que la cantidad de horarios "
                        "simultáneos, aunque la unión total cubra "
                        "la demanda global.\n\n"
                        "Ampliar los labs compatibles de esas materias "
                        "o desolapar en el cronograma."
                    ),
                    entidades_a_revisar=[f"materia:{m}" for m in sub],
                ))

    # =========================================================================
    # 3. R11 · Pins manuales incompatibles.
    # =========================================================================
    for h in horarios_slots:
        h_db = horario_db_by_id.get(h.id)
        if h_db is None or not h_db.aula_asignada_manualmente:
            continue
        aula_pin = h_db.aula_id
        if not aula_pin:
            continue
        if not compat.get((h.id, aula_pin), False):
            aula = aula_by_id.get(aula_pin)
            aula_lbl = aula.codigo_aula if aula else aula_pin
            reporte.bloqueos.append(Bloqueo(
                codigo_regla="R11",
                severidad="bloqueante",
                titulo=(
                    f"Pin manual incompatible · {h.materia_codigo} "
                    f"→ {aula_lbl}"
                ),
                detalle=(
                    f"- **Materia**: `{h.materia_codigo}` "
                    f"({mat_nombre.get(h.materia_codigo, '?')})\n"
                    f"- **Día/Hora**: {h.dia} "
                    f"{h.hora_inicio.strftime('%H:%M')}–"
                    f"{h.hora_fin.strftime('%H:%M')}\n"
                    f"- **Aula fijada a mano**: {aula_lbl}\n"
                    "El aula dejó de ser compatible (cambió tipo, "
                    "sede u otra restricción). Desmarcá el pin o "
                    "elegí otra aula."
                ),
                entidades_a_revisar=[
                    f"materia:{h.materia_codigo}",
                    f"aula:{aula_pin}",
                ],
            ))

    # =========================================================================
    # 4. R13 · Sedes consecutivas sin sede común admisible.
    # =========================================================================
    pares_riesgo = compute_pares_intersede_riesgo(
        horarios=horarios_slots,
        comision_de_horario=comision_de_horario,
        margen_min_intersede_minutos=margen_min_intersede_minutos,
    )
    horario_slot_by_id = {h.id: h for h in horarios_slots}
    aulas_por_sede_lab_y_teo: dict[str, set[str]] = {}
    aulas_por_sede_lab: dict[str, set[str]] = {}
    aulas_por_sede_teo: dict[str, set[str]] = {}
    for a in aulas_db:
        aulas_por_sede_lab_y_teo.setdefault(a.sede_id, set()).add(a.id)
        if a.tipo == "laboratorio":
            aulas_por_sede_lab.setdefault(a.sede_id, set()).add(a.id)
        elif a.tipo in ("teorica", "anfiteatro"):
            aulas_por_sede_teo.setdefault(a.sede_id, set()).add(a.id)

    for h1_id, h2_id, gap in pares_riesgo:
        h1 = horario_slot_by_id.get(h1_id)
        h2 = horario_slot_by_id.get(h2_id)
        if h1 is None or h2 is None:
            continue
        # Sedes en las que cada uno tiene al menos un aula compatible.
        sedes_h1: set[str] = {
            sd for a in aulas_slots
            if compat.get((h1_id, a.id))
            and (sd := aula_sede_id.get(a.id)) is not None
        }
        sedes_h2: set[str] = {
            sd for a in aulas_slots
            if compat.get((h2_id, a.id))
            and (sd := aula_sede_id.get(a.id)) is not None
        }
        interseccion = sedes_h1 & sedes_h2
        if not interseccion:
            cid = comision_de_horario.get(h1_id)
            com = com_by_id.get(cid) if cid else None
            com_lbl = com.nombre if com else "?"
            reporte.bloqueos.append(Bloqueo(
                codigo_regla="R13",
                severidad="bloqueante",
                titulo=(
                    f"Comisión {com_lbl} · {h1.materia_codigo}/"
                    f"{h2.materia_codigo}: sin sede común entre "
                    f"horarios contiguos ({h1.dia})"
                ),
                detalle=(
                    f"- **Comisión**: {com_lbl}\n"
                    f"- **Día**: {h1.dia}\n"
                    f"- **Horario 1**: {h1.materia_codigo} "
                    f"{h1.hora_inicio.strftime('%H:%M')}–"
                    f"{h1.hora_fin.strftime('%H:%M')}\n"
                    f"- **Horario 2**: {h2.materia_codigo} "
                    f"{h2.hora_inicio.strftime('%H:%M')}–"
                    f"{h2.hora_fin.strftime('%H:%M')}\n"
                    f"- **Gap entre horarios**: {gap} minutos "
                    f"(< {margen_min_intersede_minutos} min de margen)\n"
                    f"- **Sedes candidatas para h1**: "
                    + (
                        ", ".join(sede_nombre.get(s, "?") for s in sedes_h1)
                        or "—"
                    )
                    + f"\n- **Sedes candidatas para h2**: "
                    + (
                        ", ".join(sede_nombre.get(s, "?") for s in sedes_h2)
                        or "—"
                    )
                    + "\n\n"
                    "No hay ninguna sede que ambos puedan usar "
                    "simultáneamente. Bajá el margen intersede o "
                    "ajustá compatibilidades/sedes admisibles."
                ),
                entidades_a_revisar=[
                    f"materia:{h1.materia_codigo}",
                    f"materia:{h2.materia_codigo}",
                ],
            ))

    # -------------------------------------------------------------------------
    # Consolidar.
    # -------------------------------------------------------------------------
    reporte.factible = len(reporte.bloqueos) == 0
    for b in reporte.bloqueos:
        reporte.resumen_por_regla[b.codigo_regla] = (
            reporte.resumen_por_regla.get(b.codigo_regla, 0) + 1
        )

    return reporte
