"""Asientos en aulas libres por franja de 15 minutos (lunes a viernes,
8 a 22): suma de capacidades de las aulas teóricas activas sin clase en
esa franja. Se calcula sobre el estado de cada base, sin correr nada."""
import os, sys, json
db = sys.argv[1]
os.environ["DATABASE_URL"] = f"sqlite:////tmp/exp/{db}.db"
sys.path.insert(0, "/Users/lantonelli/dev/other/gestor-aulas")
from sqlmodel import Session, select
from src.database.connection import init_db, engine
init_db()
from src.database.models import *
from src.services.metricas_calidad_service import compute_metricas_calidad
with Session(engine) as s:
    plan = [p for p in s.exec(select(PlanificacionCursadaDB)).all() if p.nombre == "Plan v0" and p.ciclo_id == "2026-1C"][0]
    sedes = {x.id: x.nombre for x in s.exec(select(SedeDB)).all()}
    aulas = {a.id: a for a in s.exec(select(AulaDB)).all() if a.activa and a.tipo != "laboratorio"}
    coms = {c.id for c in s.exec(select(ComisionDB).where(ComisionDB.plan_cursada_id == plan.id)).all()}
    hs = [h for h in s.exec(select(HorarioDB)).all() if h.comision_id in coms and h.aula_id]
    franjas = {"Pellegrini": [], "Siberia": [], "Total": []}
    for d in ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]:
        for m in range(8 * 60, 22 * 60, 15):
            ocup = {h.aula_id for h in hs if h.dia == d and h.hora_inicio.hour*60+h.hora_inicio.minute <= m < h.hora_fin.hour*60+h.hora_fin.minute}
            por = {"Pellegrini": 0, "Siberia": 0}
            for aid, a in aulas.items():
                if aid not in ocup:
                    por[sedes[a.sede_id]] += a.capacidad
            for k in por: franjas[k].append(por[k])
            franjas["Total"].append(por["Pellegrini"] + por["Siberia"])
    met = compute_metricas_calidad(s, plan.id)
    out = {"db": db, "asientos_totales": sum(a.capacidad for a in aulas.values())}
    for k, v in franjas.items():
        v2 = sorted(v); n = len(v2)
        out[k] = {"min": v2[0], "p10": v2[n // 10], "mediana": v2[n // 2], "promedio": round(sum(v2) / n)}
    out["metricas"] = {"asignados": met.cobertura.n_horarios_asignados, "sobreocupados": met.ocupacion.n_sobreocupados,
                       "faltantes": met.ocupacion.sobrecupo_total_asientos, "subutilizados": met.ocupacion.n_subutilizados,
                       "vacios": met.ocupacion.subutilizacion_total_asientos, "fuera_pref": met.cobertura.n_horarios_en_sede_alternativa,
                       "traslados": met.lp.n_comisiones_con_traslado_intersede, "ratio_p50": round(met.ocupacion.ratio_p50, 2)}
    json.dump({"franjas": franjas, **out}, open(f"/tmp/exp/libres_{db}.json", "w"), ensure_ascii=False)
    print(json.dumps(out, ensure_ascii=False))
