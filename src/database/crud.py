"""
CRUD operations for database models.

Este módulo implementa el patrón Repository usando Generics de Python.
Proporciona operaciones CRUD (Create, Read, Update, Delete) reutilizables
para todas las entidades de la base de datos.

ARQUITECTURA:
    Este módulo es parte de la capa de PERSISTENCIA en la arquitectura
    de dos capas del proyecto:
    
    ┌─────────────────────────────────────────────────────┐
    │  CAPA DE DOMINIO (src/domain/)                      │
    │  - Lógica de negocio pura                           │
    │  - Modelos Pydantic inmutables                      │
    │  - Independiente de tecnología                      │
    └─────────────────────────────────────────────────────┘
                            ▲
                            │ to_domain()
                            │
    ┌─────────────────────────────────────────────────────┐
    │  CAPA DE PERSISTENCIA (src/database/) ◄─ AQUÍ       │
    │  - Modelos SQLModel con table=True                  │
    │  - CRUD genérico (este archivo)                     │
    │  - Converters entre capas                           │
    │  - Acceso a BD SQLite                               │
    └─────────────────────────────────────────────────────┘

PATRONES IMPLEMENTADOS:
    1. Repository Pattern: Abstrae el acceso a datos
    2. Generic Programming: Código reutilizable con type safety
    3. Dependency Injection: Session se inyecta en cada operación

REFERENCIAS:
    - Ver project/orm.md para documentación completa
    - Domain-Driven Design (DDD)
    - Repository Pattern (Martin Fowler)
"""

from sqlmodel import Session, select
from typing import TypeVar, Generic, Type, Optional
from src.database.models import (
    AlumnoDB, MateriaDB, ComisionDB, HorarioCronogramaDB,
    AulaDB, ClaseDB, InscripcionDB, AsistenciaDB, AsignacionAulaDB,
    ConfiguracionHoraria, CarreraDB, ProfesorDB, CicloDB, DictadoDB
)

# ============================================================================
# GENERICS: TypeVar y Generic[T]
# ============================================================================
# 
# TypeVar("T") crea una variable de tipo genérica que puede representar
# cualquier tipo de dato. Es como un "comodín" que se especifica cuando
# se usa la clase.
#
# Ejemplo:
#   T = TypeVar("T")
#   class CRUDBase(Generic[T]):
#       def create(self, obj: T) -> T: ...
#
# Uso:
#   alumno_crud = CRUDBase[AlumnoDB](AlumnoDB)  # T = AlumnoDB
#   materia_crud = CRUDBase[MateriaDB](MateriaDB)  # T = MateriaDB
#
# Beneficios:
#   - Type checking: El IDE sabe qué tipo retorna cada método
#   - Reutilización: Una sola clase para todos los modelos
#   - Seguridad: Errores de tipo detectados antes de ejecutar
#   - Documentación: El código es autodocumentado
#
# Ver: https://docs.python.org/3/library/typing.html#typing.TypeVar
# ============================================================================

T = TypeVar("T")


class CRUDBase(Generic[T]):
    """
    Clase base genérica para operaciones CRUD.
    
    Implementa el patrón Repository, proporcionando una interfaz uniforme
    para acceder a cualquier entidad de la base de datos.
    
    PATRÓN REPOSITORY:
        El Repository abstrae los detalles de persistencia, permitiendo:
        - Cambiar de BD sin tocar la lógica de negocio
        - Testear con mocks sin necesidad de BD real
        - Centralizar la lógica de acceso a datos
        
        Flujo típico:
            1. Crear instancia: crud = CRUDBase[MateriaDB](MateriaDB)
            2. Usar métodos: crud.create(session, materia)
            3. El Repository maneja la BD internamente
    
    GENERIC[T]:
        T es un parámetro de tipo que se especifica al instanciar:
        
        - CRUDBase[AlumnoDB] → CRUD para Alumnos
        - CRUDBase[MateriaDB] → CRUD para Materias
        - CRUDBase[ProfesorDB] → CRUD para Profesores
        
        Mismo código, diferentes tipos. Type-safe.
    
    ATRIBUTOS:
        model (Type[T]): La clase del modelo SQLModel que maneja este CRUD
    
    EJEMPLO DE USO:
        ```python
        # Crear CRUD para Materias
        materia_crud = CRUDBase[MateriaDB](MateriaDB)
        
        # Usar en operaciones
        nueva_materia = MateriaDB(codigo="MAT101", nombre="Cálculo")
        materia_guardada = materia_crud.create(session, nueva_materia)
        
        # El IDE sabe que materia_guardada es MateriaDB
        print(materia_guardada.codigo)  # ✓ Autocompletado
        ```
    
    VENTAJAS SOBRE CÓDIGO SIN GENERICS:
        ❌ Sin generics:
            def create(self, obj):  # ¿Qué tipo es obj?
                session.add(obj)
                return obj
        
        ✓ Con generics:
            def create(self, obj: T) -> T:  # Tipo explícito
                session.add(obj)
                return obj
    """
    
    def __init__(self, model: Type[T]):
        """
        Inicializa el CRUD con un modelo específico.
        
        ARGS:
            model (Type[T]): La clase del modelo SQLModel.
                            Ejemplo: AlumnoDB, MateriaDB, etc.
        
        EJEMPLO:
            ```python
            # Crear CRUD para Alumnos
            alumno_crud = CRUDBase[AlumnoDB](AlumnoDB)
            
            # Ahora alumno_crud solo trabaja con AlumnoDB
            # El tipo checker lo valida
            ```
        """
        self.model = model
    
    def get(self, session: Session, id: str) -> Optional[T]:
        """
        Obtiene un registro por su ID.
        
        ARGS:
            session (Session): Sesión de BD (inyectada)
            id (str): Identificador único del registro
        
        RETURNS:
            Optional[T]: El registro si existe, None si no
        
        COMPLEJIDAD:
            O(1) - Búsqueda por clave primaria
        
        EJEMPLO:
            ```python
            materia = materia_crud.get(session, "MAT101")
            if materia:
                print(f"Materia: {materia.nombre}")
            ```
        """
        return session.get(self.model, id)
    
    def get_all(self, session: Session, skip: int = 0, limit: int = 100) -> list[T]:
        """
        Obtiene todos los registros con paginación.
        
        ARGS:
            session (Session): Sesión de BD (inyectada)
            skip (int): Cantidad de registros a saltar (default: 0)
            limit (int): Cantidad máxima de registros (default: 100)
        
        RETURNS:
            list[T]: Lista de registros del tipo T
        
        COMPLEJIDAD:
            O(n) donde n = limit
        
        PAGINACIÓN:
            Útil para no cargar toda la BD en memoria.
            
            Ejemplo: Obtener página 2 (10 registros por página)
            ```python
            page = 2
            per_page = 10
            materias = materia_crud.get_all(
                session,
                skip=(page - 1) * per_page,
                limit=per_page
            )
            ```
        
        EJEMPLO:
            ```python
            # Obtener primeros 50 alumnos
            alumnos = alumno_crud.get_all(session, skip=0, limit=50)
            
            # Obtener alumnos 50-100
            alumnos_page2 = alumno_crud.get_all(session, skip=50, limit=50)
            ```
        """
        statement = select(self.model).offset(skip).limit(limit)
        return list(session.exec(statement).all())
    
    def create(self, session: Session, obj: T) -> T:
        """
        Crea un nuevo registro en la BD.
        
        ARGS:
            session (Session): Sesión de BD (inyectada)
            obj (T): Objeto del modelo a crear
        
        RETURNS:
            T: El objeto creado con ID asignado por la BD
        
        TRANSACCIÓN:
            - session.add(obj): Agrega a la sesión
            - session.commit(): Confirma la transacción
            - session.refresh(obj): Recarga desde BD (obtiene ID generado)
        
        VALIDACIÓN:
            Pydantic valida el objeto antes de guardarlo.
            Si hay error de validación, lanza ValidationError.
        
        EJEMPLO:
            ```python
            nueva_materia = MateriaDB(
                codigo="MAT101",
                nombre="Cálculo I",
                cupo=30
            )
            materia_guardada = materia_crud.create(session, nueva_materia)
            print(f"ID generado: {materia_guardada.id}")
            ```
        """
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def update(self, session: Session, obj: T) -> T:
        """
        Actualiza un registro existente en la BD.
        
        ARGS:
            session (Session): Sesión de BD (inyectada)
            obj (T): Objeto con los datos actualizados
        
        RETURNS:
            T: El objeto actualizado
        
        PRECONDICIÓN:
            El objeto debe tener un ID válido (debe existir en BD)
        
        TRANSACCIÓN:
            - session.add(obj): Marca como modificado
            - session.commit(): Confirma cambios
            - session.refresh(obj): Recarga desde BD
        
        NOTA:
            SQLModel detecta automáticamente qué campos cambiaron.
            Solo actualiza los campos modificados.
        
        EJEMPLO:
            ```python
            materia = materia_crud.get(session, "MAT101")
            materia.cupo = 40  # Modificar
            materia_actualizada = materia_crud.update(session, materia)
            ```
        """
        session.add(obj)
        session.commit()
        session.refresh(obj)
        return obj
    
    def delete(self, session: Session, id: str) -> bool:
        """
        Elimina un registro de la BD.
        
        ARGS:
            session (Session): Sesión de BD (inyectada)
            id (str): ID del registro a eliminar
        
        RETURNS:
            bool: True si se eliminó, False si no existía
        
        TRANSACCIÓN:
            - session.get(): Busca el registro
            - session.delete(): Marca para eliminar
            - session.commit(): Confirma eliminación
        
        SEGURIDAD:
            Verifica que el registro existe antes de eliminar.
            Retorna False si no existe (no lanza error).
        
        EJEMPLO:
            ```python
            if materia_crud.delete(session, "MAT101"):
                print("Materia eliminada")
            else:
                print("Materia no encontrada")
            ```
        """
        obj = session.get(self.model, id)
        if obj:
            session.delete(obj)
            session.commit()
            return True
        return False


# ============================================================================
# INSTANCIAS DE CRUD PARA CADA MODELO
# ============================================================================
#
# Aquí se crean instancias específicas del CRUD genérico para cada entidad.
# Cada una es especializada para un tipo de modelo diferente.
#
# VENTAJA DE GENERICS:
#   Sin generics, necesitarías crear una clase para cada modelo:
#   
#   ❌ Código duplicado:
#       class AlumnoCRUD:
#           def create(self, obj: AlumnoDB) -> AlumnoDB: ...
#       
#       class MateriaCRUD:
#           def create(self, obj: MateriaDB) -> MateriaDB: ...
#   
#   ✓ Con generics (DRY - Don't Repeat Yourself):
#       alumno_crud = CRUDBase[AlumnoDB](AlumnoDB)
#       materia_crud = CRUDBase[MateriaDB](MateriaDB)
#
# TIPO CHECKING:
#   El IDE sabe exactamente qué tipo retorna cada operación:
#   
#   alumno = alumno_crud.get(session, "123")  # Tipo: Optional[AlumnoDB]
#   materia = materia_crud.get(session, "MAT101")  # Tipo: Optional[MateriaDB]
#
# ============================================================================

# Instancia CRUD para Alumnos
# Uso: alumno_crud.create(session, alumno)
alumno_crud = CRUDBase[AlumnoDB](AlumnoDB)

# Instancia CRUD para Materias
# Uso: materia_crud.get_all(session)
materia_crud = CRUDBase[MateriaDB](MateriaDB)

# Instancia CRUD para Comisiones
# Uso: comision_crud.update(session, comision)
comision_crud = CRUDBase[ComisionDB](ComisionDB)

# Instancia CRUD para Horarios
horario_crud = CRUDBase[HorarioCronogramaDB](HorarioCronogramaDB)

# Instancia CRUD para Aulas
aula_crud = CRUDBase[AulaDB](AulaDB)

# Instancia CRUD para Clases
clase_crud = CRUDBase[ClaseDB](ClaseDB)

# Instancia CRUD para Inscripciones
inscripcion_crud = CRUDBase[InscripcionDB](InscripcionDB)

# Instancia CRUD para Asistencias
asistencia_crud = CRUDBase[AsistenciaDB](AsistenciaDB)

# Instancia CRUD para Asignaciones de Aulas
asignacion_crud = CRUDBase[AsignacionAulaDB](AsignacionAulaDB)

# Instancia CRUD para Carreras
carrera_crud = CRUDBase[CarreraDB](CarreraDB)

# Instancia CRUD para Profesores
profesor_crud = CRUDBase[ProfesorDB](ProfesorDB)

# Instancia CRUD para Ciclos
ciclo_crud = CRUDBase[CicloDB](CicloDB)

# Instancia CRUD para Dictados
dictado_crud = CRUDBase[DictadoDB](DictadoDB)


# ============================================================================
# FUNCIONES AUXILIARES ESPECIALIZADAS
# ============================================================================
#
# Estas funciones implementan lógica de negocio específica que va más allá
# del CRUD genérico. Son casos de uso particulares del dominio.
#
# PATRÓN: Operaciones Compuestas
#   Cuando una operación requiere múltiples pasos o validaciones,
#   se encapsula en una función dedicada.
#
# ============================================================================


def create_materia_with_comision(session: Session, materia: MateriaDB) -> tuple[MateriaDB, ComisionDB]:
    """
    Crea una materia con su comisión por defecto.
    
    LÓGICA DE NEGOCIO:
        Cuando se crea una materia, automáticamente se crea una
        "Comisión Única" asociada. Esto es una regla del dominio.
    
    TRANSACCIÓN COMPUESTA:
        1. Crear materia en BD
        2. Crear comisión con datos de la materia
        3. Retornar ambas entidades
    
    ARGS:
        session (Session): Sesión de BD
        materia (MateriaDB): Materia a crear
    
    RETURNS:
        tuple[MateriaDB, ComisionDB]: La materia y comisión creadas
    
    EJEMPLO:
        ```python
        nueva_materia = MateriaDB(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30
        )
        materia, comision = create_materia_with_comision(session, nueva_materia)
        print(f"Materia: {materia.nombre}")
        print(f"Comisión: {comision.nombre}")  # "Comisión Única"
        ```
    
    NOTA:
        Esta función encapsula una regla de negocio:
        "Toda materia debe tener al menos una comisión"
    """
    session.add(materia)
    session.commit()
    session.refresh(materia)
    
    # Create default comision
    comision = ComisionDB(
        id=f"{materia.codigo}-C1",
        materia_codigo=materia.codigo,
        nombre="Comisión Única",
        numero=1,
        cupo=materia.cupo,
        descripcion="Comisión creada automáticamente"
    )
    session.add(comision)
    session.commit()
    session.refresh(comision)
    
    return materia, comision


def get_or_create_config(session: Session) -> ConfiguracionHoraria:
    """
    Obtiene la configuración singleton, creando la por defecto si no existe.
    
    PATRÓN SINGLETON:
        La configuración es única en el sistema (id=1).
        Esta función garantiza que siempre existe.
    
    LÓGICA:
        1. Intentar obtener config con id=1
        2. Si no existe, crearla con valores por defecto
        3. Retornar la config
    
    RETURNS:
        ConfiguracionHoraria: La configuración del sistema
    
    IDEMPOTENCIA:
        Llamar múltiples veces retorna el mismo objeto.
        No crea duplicados.
    
    EJEMPLO:
        ```python
        # Primera llamada: crea la config
        config = get_or_create_config(session)
        
        # Segunda llamada: retorna la misma
        config2 = get_or_create_config(session)
        assert config.id == config2.id  # True
        ```
    
    NOTA:
        Útil para inicializar el sistema con valores por defecto.
    """
    config = session.get(ConfiguracionHoraria, 1)
    if not config:
        config = ConfiguracionHoraria(id=1)
        session.add(config)
        session.commit()
        session.refresh(config)
    return config


def update_config(session: Session, config: ConfiguracionHoraria) -> ConfiguracionHoraria:
    """
    Actualiza la configuración del sistema.
    
    PRECONDICIÓN:
        La configuración debe existir (usar get_or_create_config primero)
    
    GARANTÍA SINGLETON:
        Siempre asegura que id=1 (no permite crear múltiples configs)
    
    ARGS:
        session (Session): Sesión de BD
        config (ConfiguracionHoraria): Config con valores actualizados
    
    RETURNS:
        ConfiguracionHoraria: La config actualizada
    
    EJEMPLO:
        ```python
        config = get_or_create_config(session)
        config.hora_inicio = "08:00"
        config.hora_fin = "18:00"
        config_actualizada = update_config(session, config)
        ```
    
    NOTA:
        Esta función es un wrapper sobre el CRUD genérico,
        pero con la garantía adicional de singleton.
    """
    config.id = 1  # Ensure singleton
    session.add(config)
    session.commit()
    session.refresh(config)
    return config
