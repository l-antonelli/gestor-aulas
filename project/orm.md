# ORM y Arquitectura de Datos

## ¿Qué es un ORM?

**ORM (Object-Relational Mapping)** es una técnica que permite interactuar con una base de datos relacional usando objetos de un lenguaje de programación, en lugar de escribir SQL directamente.

ORMs (Object-Relational Mappers) are software tools that bridge the gap between object-oriented programming languages and relational databases, allowing developers to interact with data using objects and methods instead of writing raw SQL, which boosts productivity, reduces boilerplate code, improves portability, and enhances security by abstracting database operations.

```
Sin ORM:
    cursor.execute("INSERT INTO alumnos (legajo, nombre) VALUES (?, ?)", (legajo, nombre))

Con ORM:
    alumno = AlumnoDB(legajo=legajo, nombre=nombre)
    session.add(alumno)
```

**Ventajas:**
- Código más legible y mantenible
- Validación automática de tipos
- Independencia del motor de base de datos (SQLite → PostgreSQL sin cambiar código)
- Prevención de SQL injection
- Migraciones de esquema más simples

## Framework: SQLModel

Elegimos **SQLModel** porque:

1. **Combina Pydantic + SQLAlchemy** - Validación de datos y ORM en una sola definición
2. **Mismo autor que FastAPI** - Sebastián Ramírez, excelente documentación y diseño
3. **Type hints nativos** - Autocompletado y detección de errores en el IDE
4. **Compatible con el ecosistema Python de datos** - Pandas, NumPy, etc.

```python
from sqlmodel import SQLModel, Field

class AulaDB(SQLModel, table=True):
    codigo: str = Field(primary_key=True)
    capacidad: int = Field(gt=0)  # Validación: debe ser > 0
```

## Arquitectura de Dos Capas de Modelos

En este proyecto mantenemos **dos conjuntos de modelos separados**:

### 1. Modelos de Dominio (`src/domain/`)
- Pydantic puro, inmutables (`frozen=True`)
- Sin dependencia de base de datos
- Usados para lógica de negocio, algoritmos, testing

```python
# src/domain/problem/aula.py
class Aula(Entity):
    codigo: str
    capacidad: int
```

### 2. Modelos de Base de Datos (`src/database/models.py`)
- SQLModel con `table=True`
- Mapeados a tablas SQLite
- Usados para persistencia y UI (Streamlit)

```python
# src/database/models.py
class AulaDB(SQLModel, table=True):
    codigo: str = Field(primary_key=True)
    capacidad: int = Field(gt=0)
```

## ¿Por qué esta separación?

### Desacoplamiento de Experimentación y Persistencia

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   SQLModel DB   │ ──► │  Domain Models  │ ──► │  Optimización   │
│  (persistencia) │     │   (Pydantic)    │     │   ML / Solver   │
└─────────────────┘     └─────────────────┘     └─────────────────┘
```

**Caso de uso típico:**

1. Usuario carga datos via Streamlit → se guardan en SQLite (SQLModel)
2. Sistema carga datos de DB → convierte a modelos de dominio
3. Algoritmo de optimización genera N soluciones candidatas (objetos de dominio)
4. Se comparan soluciones, se elige la mejor
5. Solo la solución final se persiste en DB

**Beneficios:**

| Aspecto | Con separación | Sin separación |
|---------|----------------|----------------|
| Experimentación ML | Objetos livianos, sin I/O | Cada operación toca la DB |
| Testing (Hypothesis) | Genera entidades puras | Necesita DB de test |
| Serialización | JSON/pickle directo | Hay que extraer de DB |
| Inmutabilidad | `frozen=True` garantizado | SQLModel es mutable |
| Comparación de soluciones | En memoria, rápido | Queries a DB |

### Conversión entre capas

Las funciones de conversión están en `src/database/converters.py`:

```python
# DB → Domain
aula_domain = to_domain(aula_db)

# Domain → DB  
aula_db = to_db(aula_domain)
```

## Flujo de Datos Completo

```
┌──────────────┐
│  Streamlit   │  ← Usuario ingresa datos
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  SQLModel    │  ← Persistencia en SQLite
│   (AulaDB)   │
└──────┬───────┘
       │ to_domain()
       ▼
┌──────────────┐
│   Pydantic   │  ← Lógica de negocio
│   (Aula)     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│ Optimización │  ← OR-Tools, PuLP, ML
│   Solver     │
└──────┬───────┘
       │
       ▼
┌──────────────┐
│  Soluciones  │  ← Comparar en memoria
│  Candidatas  │
└──────┬───────┘
       │ to_db()
       ▼
┌──────────────┐
│  SQLModel    │  ← Guardar mejor solución
│   (DB)       │
└──────────────┘
```

## Referencias

- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [Pydantic V2](https://docs.pydantic.dev/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/orm/)
