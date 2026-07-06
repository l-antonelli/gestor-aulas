"""Clona un ciclo + plan + cascada para preservar un escenario de demo.

Use case principal: preservar un estado actual del plan (con su
saturacion, infactibilidad, comisiones, horarios, asignacion de aulas,
corridas del LP, etc.) como caso ejemplo no editable, mientras se sigue
trabajando sobre el original.

Estrategia: clonado profundo de las entidades operativas (ciclo, plan,
comisiones, horarios, clases, dictados, lp_runs, etc.) generando nuevos
IDs y reescribiendo FKs. NO se clonan catalogos compartidos (materias,
carreras, aulas, sedes, plan_estudio, carrera_sede, etc.) — el demo
toma los datos vigentes de catalogo.

Que se clona:
- CicloDB → id sufijo "-demo-saturacion".
- DictadoDB (todos los dictados asociados al ciclo via DictadoCicloDB)
  → nuevos UUIDs, mismo materia_codigo, preserva el flag `virtual`
  actual ("fotografia" del estado).
- DictadoCicloDB → puente al ciclo nuevo + dictados nuevos.
- PlanificacionCursadaDB → nuevo UUID, activo=False, descripcion con
  marca "[CASO EJEMPLO DE SATURACION — clonado YYYY-MM-DD]".
  schedule_id queda apuntando al schedule original (metadata historica).
- ComisionDB del plan → nuevos UUIDs, rewire de plan_cursada_id y
  dictado_id.
- HorarioDB de las comisiones → nuevos UUIDs (con sufijo), rewire de
  comision_id. Preserva aula_id del patron y tipo_clase.
- ClaseDB del plan → nuevos UUIDs, rewire de plan_cursada_id,
  horario_id, comision_id, dictado_id. Preserva aula_id,
  aula_asignada_manualmente, executed.
- LPRunDB del plan → nuevos UUIDs, rewire de plan_cursada_id.
  details_json reescrito con el mapping de horario_id (asi el heatmap
  y el detalle apuntan a los horarios clonados).
- MateriaForecastConfigDB del plan → rewire de plan_cursada_id.
- IgnoredConflictDB del plan → rewire de plan_cursada_id.

Que NO se clona:
- PlanValidationDB (snapshots de validacion: se re-corren desde la UI).
- ScheduleDB / ScheduleEntryDB / ScheduleValidationDB (cronogramas
  son inmutables; el plan demo conserva el FK al schedule original).
- Catalogos: MateriaDB, CarreraDB, AulaDB, SedeDB, PlanEstudioDB,
  CarreraSedeDB, PlanCarreraVersionDB, CicloPlanVersionDB,
  MateriaLaboratorioDB, InscripcionHistoricaDB.

Uso:
    python -m scripts.clonar_ciclo_para_demo --ciclo-id 2026-1C
    python -m scripts.clonar_ciclo_para_demo --ciclo-id 2026-1C --dry-run
    python -m scripts.clonar_ciclo_para_demo --ciclo-id 2026-1C \
        --sufijo "demo-infactible-1"
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from datetime import date

from sqlmodel import Session, col, select

from src.database.connection import get_session, init_db
from src.database.models import (
    CicloDB,
    ClaseDB,
    ComisionDB,
    DictadoCicloDB,
    DictadoDB,
    HorarioDB,
    IgnoredConflictDB,
    LPRunDB,
    MateriaForecastConfigDB,
    PlanificacionCursadaDB,
)


SUFIJO_DEFAULT = "demo-saturacion"


def clonar_ciclo(
    session: Session,
    ciclo_id_origen: str,
    sufijo: str = SUFIJO_DEFAULT,
    *,
    dry_run: bool = False,
) -> dict:
    """Clona el ciclo + cascada. Retorna resumen de filas creadas.

    Si ``dry_run=True``, hace todo en memoria y luego rollback. El
    resumen es identico al de la corrida real.
    """
    ciclo_orig = session.get(CicloDB, ciclo_id_origen)
    if ciclo_orig is None:
        raise ValueError(f"Ciclo '{ciclo_id_origen}' no encontrado.")

    nuevo_ciclo_id = f"{ciclo_id_origen}-{sufijo}"
    if session.get(CicloDB, nuevo_ciclo_id) is not None:
        raise ValueError(
            f"Ya existe un ciclo con id '{nuevo_ciclo_id}'. "
            "Borralo primero o usá otro --sufijo."
        )

    resumen: dict[str, int] = {}

    # 1) CicloDB
    session.add(CicloDB(
        id=nuevo_ciclo_id,
        anio=ciclo_orig.anio,
        numero=ciclo_orig.numero,
        fecha_inicio=ciclo_orig.fecha_inicio,
        fecha_fin=ciclo_orig.fecha_fin,
        descripcion=(
            (ciclo_orig.descripcion + " " if ciclo_orig.descripcion else "")
            + "[CASO EJEMPLO DE SATURACION — "
            f"clonado de {ciclo_id_origen} el {date.today().isoformat()}]"
        ),
    ))
    resumen["ciclos"] = 1

    # 2) DictadoDB asociado al ciclo via DictadoCicloDB.
    bridge_rows = list(session.exec(
        select(DictadoCicloDB).where(
            DictadoCicloDB.ciclo_id == ciclo_id_origen,
        )
    ).all())
    dictado_ids_orig = [b.dictado_id for b in bridge_rows]
    dictados_orig = (
        list(session.exec(
            select(DictadoDB).where(
                col(DictadoDB.id).in_(dictado_ids_orig),
            )
        ).all())
        if dictado_ids_orig else []
    )
    dictado_id_map: dict[str, str] = {}
    for d in dictados_orig:
        new_id = str(uuid.uuid4())
        dictado_id_map[d.id] = new_id
        session.add(DictadoDB(
            id=new_id,
            materia_codigo=d.materia_codigo,
            dictado_codigo=d.dictado_codigo + f"-{sufijo}",
            inicio_dictado=d.inicio_dictado,
            fin_dictado=d.fin_dictado,
            virtual=d.virtual,
        ))
    resumen["dictados"] = len(dictado_id_map)

    # 3) DictadoCicloDB → puente al ciclo nuevo + dictados nuevos.
    for b in bridge_rows:
        new_d_id = dictado_id_map.get(b.dictado_id)
        if new_d_id is None:
            continue  # consistencia: deberia estar pero no abortamos.
        session.add(DictadoCicloDB(
            dictado_id=new_d_id, ciclo_id=nuevo_ciclo_id,
        ))
    resumen["dictado_ciclo"] = len(bridge_rows)

    # 4) PlanificacionCursadaDB del ciclo origen.
    planes_orig = list(session.exec(
        select(PlanificacionCursadaDB).where(
            PlanificacionCursadaDB.ciclo_id == ciclo_id_origen,
        )
    ).all())
    plan_id_map: dict[str, str] = {}
    today_str = date.today().isoformat()
    for plan in planes_orig:
        new_plan_id = str(uuid.uuid4())
        plan_id_map[plan.id] = new_plan_id
        descripcion_demo = (
            (plan.descripcion + " " if plan.descripcion else "")
            + f"[CASO EJEMPLO DE SATURACION — clonado de {plan.id} "
            f"el {today_str}]"
        )
        session.add(PlanificacionCursadaDB(
            id=new_plan_id,
            nombre=plan.nombre + " (demo)",
            descripcion=descripcion_demo,
            ciclo_id=nuevo_ciclo_id,
            activo=False,  # arranque colapsado, no es el "activo"
            schedule_id=plan.schedule_id,  # apuntar al schedule original
            forecast_metodo_default=plan.forecast_metodo_default,
        ))
    resumen["planificaciones_cursada"] = len(plan_id_map)

    if not plan_id_map:
        # Sin planes para clonar, listo. Commiteamos el ciclo + dictados.
        if dry_run:
            session.rollback()
        else:
            session.commit()
        return resumen

    # 5) ComisionDB de los planes → rewire de plan_cursada_id y dictado_id.
    plan_ids_orig = list(plan_id_map.keys())
    comisiones_orig = list(session.exec(
        select(ComisionDB).where(
            col(ComisionDB.plan_cursada_id).in_(plan_ids_orig),
        )
    ).all())
    comision_id_map: dict[str, str] = {}
    for c in comisiones_orig:
        new_c_id = str(uuid.uuid4())
        comision_id_map[c.id] = new_c_id
        # plan_cursada_id puede ser None en el modelo pero en la query
        # filtramos por col(..).in_(plan_ids_orig) — siempre llega no-None.
        assert c.plan_cursada_id is not None
        new_plan_id = plan_id_map[c.plan_cursada_id]
        new_dictado_id = (
            dictado_id_map.get(c.dictado_id) if c.dictado_id else None
        )
        # Si el dictado no estaba en el mapping (raro: comision que
        # apunta a un dictado de OTRO ciclo), dejamos el id original.
        if c.dictado_id and new_dictado_id is None:
            new_dictado_id = c.dictado_id
        session.add(ComisionDB(
            id=new_c_id,
            materia_codigo=c.materia_codigo,
            dictado_id=new_dictado_id,
            plan_cursada_id=new_plan_id,
            comision_key=c.comision_key,
            nombre=c.nombre,
            numero=c.numero,
            cupo=c.cupo,
            descripcion=c.descripcion,
            coef_asignacion=c.coef_asignacion,
        ))
    resumen["comisiones"] = len(comision_id_map)

    # 6) HorarioDB de las comisiones → rewire de comision_id.
    com_ids_orig = list(comision_id_map.keys())
    horarios_orig = (
        list(session.exec(
            select(HorarioDB).where(
                col(HorarioDB.comision_id).in_(com_ids_orig),
            )
        ).all())
        if com_ids_orig else []
    )
    horario_id_map: dict[str, str] = {}
    for h in horarios_orig:
        new_h_id = f"{h.id}-{sufijo}"
        horario_id_map[h.id] = new_h_id
        session.add(HorarioDB(
            id=new_h_id,
            comision_id=comision_id_map[h.comision_id],
            codigo_materia=h.codigo_materia,
            dia=h.dia,
            hora_inicio=h.hora_inicio,
            hora_fin=h.hora_fin,
            tipo_clase=h.tipo_clase,
            aula_id=h.aula_id,  # preserva aula del patron
        ))
    resumen["horarios"] = len(horario_id_map)

    # 7) ClaseDB del plan → rewire de plan_cursada_id, horario_id,
    #    comision_id, dictado_id.
    clases_orig = (
        list(session.exec(
            select(ClaseDB).where(
                col(ClaseDB.plan_cursada_id).in_(plan_ids_orig),
            )
        ).all())
        if plan_ids_orig else []
    )
    clase_id_map: dict[str, str] = {}
    for cl in clases_orig:
        new_cl_id = str(uuid.uuid4())
        clase_id_map[cl.id] = new_cl_id
        new_horario_id = horario_id_map.get(cl.horario_id, cl.horario_id)
        new_com_id = comision_id_map.get(cl.comision_id, cl.comision_id)
        new_plan_id = plan_id_map[cl.plan_cursada_id]
        new_dictado_id = (
            dictado_id_map.get(cl.dictado_id) if cl.dictado_id else None
        )
        if cl.dictado_id and new_dictado_id is None:
            new_dictado_id = cl.dictado_id
        session.add(ClaseDB(
            id=new_cl_id,
            horario_id=new_horario_id,
            comision_id=new_com_id,
            plan_cursada_id=new_plan_id,
            dictado_id=new_dictado_id,
            fecha=cl.fecha,
            hora_inicio=cl.hora_inicio,
            hora_fin=cl.hora_fin,
            executed=cl.executed,
            aula_id=cl.aula_id,
            tipo_clase=cl.tipo_clase,
            aula_asignada_manualmente=cl.aula_asignada_manualmente,
        ))
    resumen["clases"] = len(clase_id_map)

    # 8) LPRunDB del plan → rewire de plan_cursada_id + reescritura del
    #    details_json para que los horario_id apunten a los clonados.
    lp_runs_orig = list(session.exec(
        select(LPRunDB).where(
            col(LPRunDB.plan_cursada_id).in_(plan_ids_orig),
        )
    ).all())
    for run in lp_runs_orig:
        new_run_id = str(uuid.uuid4())
        details = _reescribir_horario_ids_en_json(
            run.details_json, horario_id_map,
        )
        session.add(LPRunDB(
            id=new_run_id,
            plan_cursada_id=plan_id_map[run.plan_cursada_id],
            run_at=run.run_at,
            fecha_desde=run.fecha_desde,
            lambda_over=run.lambda_over,
            lambda_under=run.lambda_under,
            tol_over=run.tol_over,
            tol_under=run.tol_under,
            activar_alpha=run.activar_alpha,
            respetar_ediciones_manuales=run.respetar_ediciones_manuales,
            timeout_seconds=run.timeout_seconds,
            status=run.status,
            objective_value=run.objective_value,
            n_horarios_total=run.n_horarios_total,
            n_horarios_asignados=run.n_horarios_asignados,
            n_clases_actualizadas=run.n_clases_actualizadas,
            n_clases_sobreocupadas=run.n_clases_sobreocupadas,
            n_clases_subutilizadas=run.n_clases_subutilizadas,
            n_ediciones_manuales_respetadas=(
                run.n_ediciones_manuales_respetadas
            ),
            solver_seconds=run.solver_seconds,
            error_message=run.error_message,
            details_json=details,
        ))
    resumen["lp_runs"] = len(lp_runs_orig)

    # 9) MateriaForecastConfigDB → rewire de plan_cursada_id.
    forecast_cfgs = list(session.exec(
        select(MateriaForecastConfigDB).where(
            col(MateriaForecastConfigDB.plan_cursada_id).in_(plan_ids_orig),
        )
    ).all())
    for fc in forecast_cfgs:
        session.add(MateriaForecastConfigDB(
            plan_cursada_id=plan_id_map[fc.plan_cursada_id],
            materia_codigo=fc.materia_codigo,
            cuatrimestre=fc.cuatrimestre,
            metodo=fc.metodo,
            valor_override=fc.valor_override,
        ))
    resumen["materia_forecast_config"] = len(forecast_cfgs)

    # 10) IgnoredConflictDB → rewire de plan_cursada_id.
    ignored_rows = list(session.exec(
        select(IgnoredConflictDB).where(
            col(IgnoredConflictDB.plan_cursada_id).in_(plan_ids_orig),
        )
    ).all())
    for ig in ignored_rows:
        session.add(IgnoredConflictDB(
            plan_cursada_id=plan_id_map[ig.plan_cursada_id],
            materia_a=ig.materia_a,
            materia_b=ig.materia_b,
            razon=ig.razon,
            fecha_creacion=ig.fecha_creacion,
        ))
    resumen["ignored_conflicts"] = len(ignored_rows)

    if dry_run:
        session.rollback()
    else:
        session.commit()
        # Disponer el engine: hay sesiones cacheadas en la app que
        # podrian no ver el ciclo nuevo hasta proximo request.
        from src.database.connection import engine as _engine
        _engine.dispose()
    return resumen


def _reescribir_horario_ids_en_json(
    details_json: str, mapping: dict[str, str],
) -> str:
    """Reescribe en el JSON crudo cada ``horario_id`` viejo por el nuevo.

    Estrategia: parseamos el JSON, paseamos recursivamente las strings
    que coincidan con valores de keys conocidas (``horario_id``,
    ``horario_ids``, ``id`` dentro de listas de horarios). Si el JSON
    no parsea, fallback a reemplazo literal string.

    Como cada horario_id viejo se mapea 1:1 al nuevo y los ids viejos
    no son substrings de strings ajenas en el JSON (son ids como
    ``{uuid}-...``), el fallback de reemplazo literal es seguro pero
    mas costoso.
    """
    if not details_json or not mapping:
        return details_json
    try:
        data = json.loads(details_json)
    except json.JSONDecodeError:
        # Fallback literal por orden de longitud decreciente para evitar
        # que un id corto reemplace dentro de uno largo.
        ordered = sorted(mapping.items(), key=lambda kv: -len(kv[0]))
        out = details_json
        for old, new in ordered:
            out = out.replace(old, new)
        return out
    new_data = _walk_replace(data, mapping)
    return json.dumps(new_data)


_HORARIO_ID_KEYS = {"horario_id"}
_HORARIO_IDS_LIST_KEYS = {"horario_ids"}


def _walk_replace(obj, mapping: dict[str, str]):
    """Recorre dict/list y reescribe valores de ``horario_id``."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if k in _HORARIO_ID_KEYS and isinstance(v, str):
                out[k] = mapping.get(v, v)
            elif k in _HORARIO_IDS_LIST_KEYS and isinstance(v, list):
                out[k] = [
                    mapping.get(x, x) if isinstance(x, str) else x
                    for x in v
                ]
            else:
                out[k] = _walk_replace(v, mapping)
        return out
    if isinstance(obj, list):
        return [_walk_replace(x, mapping) for x in obj]
    return obj


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Clona un ciclo + plan + cascada para preservar un escenario "
            "de demo. El clon queda con activo=False y descripcion marcada."
        ),
    )
    parser.add_argument(
        "--ciclo-id", required=True,
        help="ID del ciclo a clonar (ej. '2026-1C').",
    )
    parser.add_argument(
        "--sufijo", default=SUFIJO_DEFAULT,
        help=(
            "Sufijo para el nuevo id del ciclo: "
            "'{ciclo}-{sufijo}'. Default: 'demo-saturacion'."
        ),
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Simula sin persistir; muestra el resumen de filas a crear.",
    )
    args = parser.parse_args()

    init_db()
    with next(get_session()) as session:
        try:
            resumen = clonar_ciclo(
                session,
                ciclo_id_origen=args.ciclo_id,
                sufijo=args.sufijo,
                dry_run=args.dry_run,
            )
        except ValueError as e:
            print(f"❌ Error: {e}", file=sys.stderr)
            return 1

    nuevo_ciclo_id = f"{args.ciclo_id}-{args.sufijo}"
    modo = "DRY-RUN" if args.dry_run else "OK"
    print(f"[{modo}] Ciclo origen: {args.ciclo_id}")
    print(f"[{modo}] Ciclo destino: {nuevo_ciclo_id}")
    print(f"[{modo}] Resumen de filas creadas:")
    for tabla, n in resumen.items():
        print(f"  - {tabla}: {n}")
    if args.dry_run:
        print("(Cambios revertidos: nada se persistio.)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
