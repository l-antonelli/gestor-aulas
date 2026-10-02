# Caso ensayado (1C 2026): escenarios del asignador

Scripts con los que se armaron las tablas y figuras de la sección 3.10
del informe. Trabajan siempre sobre **copias** de `data/database.db` en
`/tmp/exp/`; nunca tocan la base real.

```bash
mkdir -p /tmp/exp
# Corre el asignador del Plan v0 (2026-1C) con la configuración de su
# última corrida, más los cambios que se pasen en JSON:
PYTHONPATH=. .venv/bin/python scripts/caso_ensayado/correr_escenario.py base '{}'
PYTHONPATH=. .venv/bin/python scripts/caso_ensayado/correr_escenario.py sin_sub '{"lambda_under": 0.0}'
PYTHONPATH=. .venv/bin/python scripts/caso_ensayado/correr_escenario.py recomendada '{"tol_over": 0.0, "tol_under": 0.2}'
# Asientos en aulas libres por franja sobre cada resultado (y sobre una
# copia sin correr nada, "real"):
cp data/database.db /tmp/exp/real.db
PYTHONPATH=. .venv/bin/python scripts/caso_ensayado/asientos_libres.py real
```

Los datos de las figuras quedaron en
`project/Informe/figuras/datos/caso_1C2026.json` (las figuras se
regeneran con `python -m scripts.figuras_informe`). Los cronogramas del
Anexo D se exportaron desde la herramienta (Cursada → Horarios →
Exportar a Excel).
