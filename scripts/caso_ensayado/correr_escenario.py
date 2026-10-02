"""Corre el asignador del Plan v0 (2026-1C) con distintas configuraciones,
cada una sobre una copia fresca de la base, y mide los resultados."""
import json, shutil, sys, os, time as _t
from pathlib import Path

nombre, cambios = sys.argv[1], json.loads(sys.argv[2])
db = f"/tmp/exp/{nombre}.db"
shutil.copy("/Users/lantonelli/dev/other/gestor-aulas/data/database.db", db)
os.environ["DATABASE_URL"] = f"sqlite:///{db}"
sys.path.insert(0, "/Users/lantonelli/dev/other/gestor-aulas")
from sqlmodel import Session, select
from src.database.connection import init_db, engine
init_db()
from src.database.models import PlanificacionCursadaDB, AulaDB, HorarioDB, ComisionDB, SedeDB, LPRunDB
from src.services.asignacion_aulas_service import LPConfig, run_lp
from src.services.metricas_calidad_service import compute_metricas_calidad

with Session(engine) as s:
    plan = [p for p in s.exec(select(PlanificacionCursadaDB)).all() if p.nombre == "Plan v0" and p.ciclo_id == "2026-1C"][0]
    ult = s.exec(select(LPRunDB).where(LPRunDB.plan_cursada_id == plan.id, LPRunDB.status == "optimal").order_by(LPRunDB.run_at.desc())).first()
    base = json.loads(ult.details_json)["veredicto"]["restricciones_activas"]
    cfg = LPConfig(
        lambda_over=base["lambda_over"], lambda_under=base["lambda_under"], lambda_sede_pref=base["lambda_sede_pref"],
        tol_over=base["tol_over"], tol_under=base["tol_under"],
        margen_min_intersede_minutos=base["margen_min_intersede_minutos"],
        forzar_misma_sede_por_comision=base["forzar_misma_sede_por_comision"],
        modos_por_grupo=base["modos_por_grupo"], strict_r5=base["strict_r5"],
        respetar_ediciones_manuales=base["respetar_ediciones_manuales"], timeout_seconds=300,
    )
    for k, v in cambios.items():
        setattr(cfg, k, v)
    t0 = _t.time()
    res = run_lp(s, plan.id, cfg)
    dt = _t.time() - t0
    s.expire_all()
    m = compute_metricas_calidad(s, plan.id)
    # Capacidad grande libre: por franja de 15 min (lunes a viernes, 8 a 22),
    # cantidad de aulas grandes (capacidad >= 80) que quedan libres.
    aulas = {a.id: a for a in s.exec(select(AulaDB)).all() if a.activa}
    grandes = {aid for aid, a in aulas.items() if a.capacidad >= 80 and a.tipo != "laboratorio"}
    com_ids = {c.id for c in s.exec(select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)).all()}
    hs = [h for h in s.exec(select(HorarioDB)).all() if h.comision_id in com_ids and h.aula_id]
    dias = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]
    libres_por_franja = []
    for d in dias:
        for minuto in range(8 * 60, 22 * 60, 15):
            ocupadas = {h.aula_id for h in hs if h.dia == d
                        and h.hora_inicio.hour * 60 + h.hora_inicio.minute <= minuto
                        and h.hora_fin.hour * 60 + h.hora_fin.minute > minuto}
            libres_por_franja.append(len(grandes - ocupadas))
    libres_por_franja.sort()
    n = len(libres_por_franja)
    corrida = s.exec(select(LPRunDB).where(LPRunDB.plan_cursada_id == plan.id).order_by(LPRunDB.run_at.desc())).first()
    det = json.loads(corrida.details_json)
    out = {
        "lp_sobreocupados": corrida.n_clases_sobreocupadas, "lp_subutilizados": corrida.n_clases_subutilizadas,
        "lp_reasignados": corrida.n_horarios_reasignados,
        "nombre": nombre, "cambios": cambios, "status": getattr(res, "status", None), "segundos": round(dt, 1),
        "asignados": m.cobertura.n_horarios_asignados, "total": m.cobertura.n_horarios_total,
        "sobreocupados": m.ocupacion.n_sobreocupados, "asientos_faltantes": m.ocupacion.sobrecupo_total_asientos,
        "subutilizados": m.ocupacion.n_subutilizados, "asientos_vacios": m.ocupacion.subutilizacion_total_asientos,
        "ratio_p50": round(m.ocupacion.ratio_p50, 2), "ratio_promedio": round(m.ocupacion.ratio_promedio, 2),
        "en_sede_preferida": m.cobertura.n_horarios_en_sede_preferida, "en_sede_alternativa": m.cobertura.n_horarios_en_sede_alternativa,
        "comisiones_con_traslado": m.lp.n_comisiones_con_traslado_intersede,
        "aulas_usadas": m.aulas.n_aulas_usadas, "aulas_catalogo": m.aulas.n_aulas_catalogo,
        "n_grandes": len(grandes),
        "grandes_libres_min": libres_por_franja[0], "grandes_libres_p10": libres_por_franja[n // 10],
        "grandes_libres_mediana": libres_por_franja[n // 2],
        "franjas_sin_grande_libre": sum(1 for x in libres_por_franja if x == 0),
    }
    print(json.dumps(out, ensure_ascii=False))
    Path(f"/tmp/exp/{nombre}.json").write_text(json.dumps(out, ensure_ascii=False, indent=1))
