# Decisión de Stack Tecnológico

## Contexto

Este documento registra las decisiones tecnológicas para el desarrollo del POC (Proof of Concept) del Sistema de Asignación de Aulas. Los criterios de selección fueron:

- **Velocidad de desarrollo**: Proyecto académico con tiempo limitado
- **Valor de aprendizaje**: Stack relevante para la industria
- **Compatibilidad con ML/Optimización**: Futuras fases requieren algoritmos de optimización y machine learning
- **Simplicidad**: Minimizar complejidad innecesaria para un POC

## Stack Seleccionado

### Frontend: Streamlit

**Justificación:**
- Python-nativo → sin cambio de contexto entre lenguajes
- Visualización de datos integrada (tablas, gráficos) ideal para el dominio
- Formularios CRUD triviales de implementar
- Hot reload para iteración rápida
- Excelente para POCs que evolucionan hacia dashboards con visualizaciones de ML
- Facilita mostrar resultados de optimización (diagramas de Gantt, heatmaps de ocupación, etc.)

**Alternativas descartadas:**
- React/Vue/Angular: Overhead innecesario para un POC, requiere API separada
- Flask + Jinja: Más trabajo manual para formularios y tablas

### Base de Datos: SQLite

**Justificación:**
- Cero configuración, basada en archivo
- Portable (un archivo que se puede compartir/respaldar)
- Suficiente para el volumen de datos (cronogramas universitarios no son big data)
- Camino de migración fácil a PostgreSQL si se necesita escalar

**Alternativas descartadas:**
- PostgreSQL: Overhead de setup innecesario para desarrollo local
- MongoDB: No aporta valor para datos relacionales bien estructurados

### ORM: SQLModel

**Justificación:**
- Creado por Sebastián Ramírez (mismo autor de FastAPI)
- Combina Pydantic + SQLAlchemy → los modelos Pydantic existentes se adaptan fácilmente
- Type hints en todo el código, excelente experiencia de desarrollo
- Validación automática en operaciones de BD
- Compatible con el ecosistema de datos de Python (Pandas, etc.)

**Alternativas descartadas:**
- SQLAlchemy puro: Más verboso, sin validación integrada
- Peewee: Menos integración con Pydantic

## Arquitectura

```
┌─────────────────────────────────────────┐
│           Streamlit Frontend            │
│  (Formularios CRUD, tablas, gráficos)   │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│         SQLModel (ORM + Validación)     │
│    (Adapta las entidades Pydantic)      │
└─────────────────────────────────────────┘
                    │
┌─────────────────────────────────────────┐
│              SQLite Database            │
│         (archivo local: data.db)        │
└─────────────────────────────────────────┘
```

## Compatibilidad con Fases Futuras

| Necesidad Futura | Cómo el Stack lo Soporta |
|------------------|--------------------------|
| Algoritmos de optimización (OR-Tools, PuLP) | Python nativo, integración directa |
| Machine Learning (scikit-learn, predicción de asistencia) | DataFrames desde SQLModel, visualización en Streamlit |
| Visualización de resultados | Streamlit soporta Plotly, Altair, Matplotlib |
| Exportación de datos | SQLite → CSV/DataFrame trivial |
| Escalamiento futuro | SQLModel permite migrar a PostgreSQL sin cambiar código |

## Dependencias Principales

```
streamlit>=1.28.0
sqlmodel>=0.0.14
pydantic>=2.0.0  # Ya existente en el proyecto
```

## Fecha de Decisión

Diciembre 2024
