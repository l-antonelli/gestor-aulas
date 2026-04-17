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

### Principio de Separación de Responsabilidades

La arquitectura de dos capas de modelos implementa el principio **Domain-Driven Design (DDD)**, separando claramente:

- **Capa de Dominio**: Lógica de negocio pura, independiente de tecnología
- **Capa de Persistencia**: Detalles técnicos de almacenamiento

Esta separación es fundamental en arquitectura de software porque:

1. **Independencia tecnológica**: El dominio no depende de SQLite, PostgreSQL o cualquier BD
2. **Testabilidad**: Puedes testear lógica sin necesidad de base de datos
3. **Mantenibilidad**: Cambios en la BD no afectan la lógica de negocio
4. **Reutilización**: Los modelos de dominio pueden usarse en diferentes contextos

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

### Comparación: Con vs Sin Separación de Capas

#### Escenario 1: SIN Separación (Antipatrón)

```python
# ❌ Modelo único acoplado a la BD
class Aula(SQLModel, table=True):
    codigo: str = Field(primary_key=True)
    capacidad: int
    # Métodos de negocio
    def optimizar_horarios(self):
        # Problema: cada operación toca la BD
        session.query(Aula).filter(...)
        session.commit()
```

**Flujo de datos (ineficiente):**

```
┌─────────────────────────────────────────────────────────────┐
│                    MONOLÍTICO                               │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  Streamlit ──► SQLModel ──► Lógica ──► Solver ──► SQLModel │
│                   ▲                                  │       │
│                   └──────────────────────────────────┘       │
│                   (I/O en cada paso)                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘

Problemas:
- Cada operación del solver toca la BD
- Testing requiere BD real
- Imposible generar múltiples soluciones en memoria
- Bajo rendimiento (I/O es lento)
```

#### Escenario 2: CON Separación (Patrón Recomendado)

```python
# ✓ Modelos separados
class Aula(Entity):  # Dominio - Pydantic puro
    codigo: str
    capacidad: int
    
    def optimizar_horarios(self) -> list['Aula']:
        # Lógica pura, sin I/O
        return [aula for aula in self.candidatos if aula.es_valida()]

class AulaDB(SQLModel, table=True):  # Persistencia
    codigo: str = Field(primary_key=True)
    capacidad: int
```

**Flujo de datos (eficiente):**

```
┌──────────────┐
│  Streamlit   │
└──────┬───────┘
       │ (I/O)
       ▼
┌──────────────────────────────────────────────────────────┐
│              CAPA DE PERSISTENCIA                        │
│  SQLModel (AulaDB) ◄─────────────────────────────────┐  │
└──────┬───────────────────────────────────────────────┼──┘
       │ to_domain()
       ▼
┌──────────────────────────────────────────────────────────┐
│              CAPA DE DOMINIO (EN MEMORIA)               │
│                                                         │
│  Aula ──► Optimización ──► Solver ──► Soluciones      │
│  (Pydantic)  (Lógica pura)  (OR-Tools)  (Candidatas)  │
│                                                         │
│  ✓ Sin I/O                                             │
│  ✓ Rápido                                              │
│  ✓ Testeable                                           │
│                                                         │
└──────┬───────────────────────────────────────────────────┘
       │ to_db() (solo la mejor solución)
       ▼
┌──────────────────────────────────────────────────────────┐
│              CAPA DE PERSISTENCIA                        │
│  SQLModel (AulaDB) ──► Guardar en BD                    │
└──────────────────────────────────────────────────────────┘
```

### Tabla Comparativa: Impacto en Rendimiento y Mantenibilidad

| Aspecto | Sin Separación | Con Separación | Mejora |
|---------|---|---|---|
| **Experimentación ML** | Objetos acoplados a BD | Objetos livianos, en memoria | 10-100x más rápido |
| **Testing** | Requiere BD de test | Genera entidades puras | Más simple y rápido |
| **Serialización** | Hay que extraer de BD | JSON/pickle directo | Trivial |
| **Inmutabilidad** | SQLModel es mutable | `frozen=True` garantizado | Seguridad de tipos |
| **Comparación de soluciones** | Queries a BD por cada comparación | En memoria, O(1) | Órdenes de magnitud |
| **Cambio de BD** | Refactorizar toda la lógica | Solo cambiar converters | Bajo impacto |
| **Testabilidad** | Acoplada a BD | Independiente | Cobertura 100% posible |
| **Reutilización de código** | Limitada a contexto de BD | Múltiples contextos | Máxima |

### Ejemplo Práctico: Generación de Soluciones

**Sin separación (❌ Ineficiente):**

```python
# Cada iteración toca la BD
for i in range(1000):
    aula = session.query(AulaDB).filter(AulaDB.codigo == "A101").first()
    aula.capacidad = calcular_nueva_capacidad()
    session.commit()  # ◄─ I/O lento
    
# Resultado: 1000 queries a BD = muy lento
```

**Con separación (✓ Eficiente):**

```python
# Cargar una sola vez
aula_db = session.query(AulaDB).filter(AulaDB.codigo == "A101").first()
aula = to_domain(aula_db)  # Conversión única

# Generar soluciones en memoria
soluciones = []
for i in range(1000):
    aula_candidata = aula.clone()  # Copia en memoria
    aula_candidata.capacidad = calcular_nueva_capacidad()
    soluciones.append(aula_candidata)

# Elegir la mejor
mejor = max(soluciones, key=lambda a: a.score())

# Guardar solo la mejor
aula_db_final = to_db(mejor)
session.add(aula_db_final)
session.commit()  # ◄─ Una sola operación I/O

# Resultado: 1 query + 1000 operaciones en memoria = muy rápido
```

**Diferencia de rendimiento:**

```
Sin separación:  1000 queries × 10ms = 10 segundos
Con separación:  1 query + 1000 ops en memoria = 50ms
                 ────────────────────────────────
                 Mejora: 200x más rápido
```

### Conversión entre capas

Las funciones de conversión están en `src/database/converters.py`:

```python
# DB → Domain
aula_domain = to_domain(aula_db)

# Domain → DB  
aula_db = to_db(aula_domain)
```

## Conceptos Académicos y Patrones de Diseño

### 1. Domain-Driven Design (DDD)

Este proyecto implementa **DDD**, un enfoque de arquitectura que coloca la lógica de negocio en el centro:

```
┌─────────────────────────────────────────────────────┐
│                  DOMINIO (Negocio)                  │
│  - Entidades (Aula, Profesor, Alumno)              │
│  - Value Objects (Horario, Capacidad)              │
│  - Agregados (Comisión = Aula + Horario + Profesor)│
│  - Servicios de Dominio (Optimización)             │
└─────────────────────────────────────────────────────┘
                          ▲
                          │
        ┌─────────────────┴─────────────────┐
        │                                   │
┌───────────────────┐           ┌───────────────────┐
│  PERSISTENCIA     │           │  PRESENTACIÓN     │
│  (SQLModel)       │           │  (Streamlit)      │
│  - Converters     │           │  - UI Components  │
│  - Repositories   │           │  - Controllers    │
└───────────────────┘           └───────────────────┘
```

**Beneficios de DDD:**

- El dominio es el corazón del sistema
- Fácil de entender para stakeholders no técnicos
- Cambios en tecnología no afectan la lógica
- Escalable y mantenible a largo plazo

### 2. Patrón Repository

El patrón Repository abstrae el acceso a datos:

```python
# src/database/crud.py
class CRUDBase(Generic[T]):
    """
    Patrón Repository genérico.
    
    T = Tipo de entidad de dominio
    
    Beneficios:
    - Abstrae detalles de persistencia
    - Permite cambiar BD sin cambiar lógica
    - Facilita testing con mocks
    """
    
    def create(self, obj: T) -> T:
        """Crear entidad"""
        pass
    
    def read(self, id: int) -> T:
        """Leer entidad"""
        pass
    
    def update(self, obj: T) -> T:
        """Actualizar entidad"""
        pass
    
    def delete(self, id: int) -> None:
        """Eliminar entidad"""
        pass
```

**¿Por qué es importante?**

```python
# Sin Repository (acoplado):
def obtener_aula(id: int):
    return session.query(AulaDB).filter(AulaDB.id == id).first()

# Con Repository (desacoplado):
def obtener_aula(id: int):
    return aula_repository.read(id)

# Ventaja: Si cambias de BD, solo cambias el Repository
```

### 3. Patrón Converter (Adapter)

Convierte entre capas sin acoplamiento:

```python
# src/database/converters.py
def to_domain(aula_db: AulaDB) -> Aula:
    """SQLModel → Pydantic (BD → Dominio)"""
    return Aula(
        codigo=aula_db.codigo,
        capacidad=aula_db.capacidad
    )

def to_db(aula: Aula) -> AulaDB:
    """Pydantic → SQLModel (Dominio → BD)"""
    return AulaDB(
        codigo=aula.codigo,
        capacidad=aula.capacidad
    )
```

**Ventajas:**

- Conversión centralizada
- Fácil de testear
- Permite transformaciones complejas
- Desacoplamiento total entre capas

### 4. Generics en Python (TypeVar)

El uso de `Generic[T]` en `CRUDBase` es un patrón avanzado:

```python
from typing import Generic, TypeVar

T = TypeVar("T")  # Variable de tipo genérica

class CRUDBase(Generic[T]):
    """
    Clase genérica que funciona con cualquier tipo T.
    
    Ejemplo:
    - CRUDBase[Aula] → CRUD para Aulas
    - CRUDBase[Profesor] → CRUD para Profesores
    - CRUDBase[Alumno] → CRUD para Alumnos
    
    Mismo código, diferentes tipos.
    """
    
    def create(self, obj: T) -> T:
        # T es el tipo específico en tiempo de análisis
        pass
```

**Beneficio académico:**

Este patrón aplica:
- Polimorfismo paramétrico
- Type safety en Python
- Reutilización de código sin duplicación (DRY)
- Cómo escribir código genérico y mantenible

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

## Mejores Prácticas Implementadas

### 1. Inmutabilidad en el Dominio

```python
# src/domain/problem/aula.py
class Aula(Entity):
    codigo: str
    capacidad: int
    
    model_config = ConfigDict(frozen=True)  # ✓ Inmutable
```

**¿Por qué?**

- Previene cambios accidentales
- Facilita razonamiento sobre el código
- Permite usar objetos como keys en diccionarios
- Seguridad en concurrencia

### 2. Validación en Múltiples Niveles

```python
# Nivel 1: Pydantic (Dominio)
class Aula(Entity):
    capacidad: int = Field(gt=0)  # Validación de negocio

# Nivel 2: SQLModel (Persistencia)
class AulaDB(SQLModel, table=True):
    capacidad: int = Field(gt=0)  # Validación de BD

# Nivel 3: Converter
def to_domain(aula_db: AulaDB) -> Aula:
    # Validaciones adicionales si es necesario
    return Aula(**aula_db.dict())
```

### 3. Type Hints Completos

```python
# ✓ Código con type hints
def procesar_aulas(aulas: list[Aula]) -> dict[str, Aula]:
    return {aula.codigo: aula for aula in aulas}

# ✗ Código sin type hints
def procesar_aulas(aulas):
    return {aula.codigo: aula for aula in aulas}
```

**Beneficios:**

- IDE proporciona autocompletado
- Errores detectados antes de ejecutar
- Documentación automática
- Facilita mantenimiento

### 4. Separación de Responsabilidades

```
┌─────────────────────────────────────────────────────┐
│  src/domain/                                        │
│  ├── problem/          ← Lógica de negocio         │
│  └── solution/         ← Soluciones del solver     │
├─────────────────────────────────────────────────────┤
│  src/database/                                      │
│  ├── models.py         ← Esquema de BD             │
│  ├── crud.py           ← Acceso a datos            │
│  └── converters.py     ← Transformaciones          │
├─────────────────────────────────────────────────────┤
│  src/services/                                      │
│  └── solver.py         ← Lógica de optimización    │
├─────────────────────────────────────────────────────┤
│  app/                                               │
│  └── pages/            ← Interfaz Streamlit        │
└─────────────────────────────────────────────────────┘
```

## Resumen: Por Qué Esta Arquitectura

| Criterio | Beneficio |
|----------|-----------|
| **Mantenibilidad** | Cambios localizados, bajo acoplamiento |
| **Testabilidad** | Tests sin BD, 100% cobertura posible |
| **Rendimiento** | Operaciones en memoria, no I/O |
| **Escalabilidad** | Fácil agregar nuevas entidades |
| **Educativo** | Enseña patrones profesionales de arquitectura |
| **Flexibilidad** | Cambiar BD sin tocar lógica de negocio |
| **Reutilización** | Código genérico y parametrizado |

## Referencias

- [SQLModel Documentation](https://sqlmodel.tiangolo.com/)
- [Pydantic V2](https://docs.pydantic.dev/)
- [SQLAlchemy ORM](https://docs.sqlalchemy.org/en/20/orm/)
- [Domain-Driven Design - Eric Evans](https://www.domainlanguage.com/ddd/)
- [Clean Architecture - Robert C. Martin](https://blog.cleancoder.com/uncle-bob/2012/08/13/the-clean-architecture.html)
- [Repository Pattern](https://martinfowler.com/eaaCatalog/repository.html)
