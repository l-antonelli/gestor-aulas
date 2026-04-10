"""
Carrera validation utilities.

Provides validation functions for checking carrera completeness,
including materia count validation and progress tracking.
"""

from typing import Dict, List
from sqlmodel import Session, select, func

from src.services.crud_services import carrera_service
from src.database.models import PlanEstudioDB
from src.domain.problem.carrera import Carrera


class CarreraValidationStatus:
    """Status information for a carrera's materia completeness."""
    
    def __init__(
        self,
        carrera: Carrera,
        materias_asignadas: int,
        cantidad_esperada: int = None,
    ):
        self.carrera = carrera
        self.materias_asignadas = materias_asignadas
        self.cantidad_esperada = cantidad_esperada
        
    @property
    def tiene_cantidad_definida(self) -> bool:
        """Check if the carrera has a defined cantidad_materias."""
        return self.cantidad_esperada is not None
    
    @property
    def esta_completa(self) -> bool:
        """Check if the carrera has all expected materias assigned."""
        if not self.tiene_cantidad_definida:
            return False
        return self.materias_asignadas >= self.cantidad_esperada
    
    @property
    def porcentaje_completitud(self) -> float:
        """Calculate the percentage of materias assigned."""
        if not self.tiene_cantidad_definida or self.cantidad_esperada == 0:
            return 0.0
        return min(100.0, (self.materias_asignadas / self.cantidad_esperada) * 100)
    
    @property
    def materias_faltantes(self) -> int:
        """Calculate how many materias are missing."""
        if not self.tiene_cantidad_definida:
            return 0
        return max(0, self.cantidad_esperada - self.materias_asignadas)
    
    @property
    def nivel_advertencia(self) -> str:
        """
        Get warning level based on completeness.
        
        Returns:
            "success" if complete (100%)
            "warning" if partially complete (1-99%)
            "error" if no cantidad_materias defined or 0 materias
        """
        if not self.tiene_cantidad_definida:
            return "error"
        
        if self.materias_asignadas == 0:
            return "error"
        
        if self.esta_completa:
            return "success"
        
        return "warning"
    
    def get_mensaje_estado(self) -> str:
        """Get a human-readable status message."""
        if not self.tiene_cantidad_definida:
            return "⚠️ Cantidad de materias no definida"
        
        if self.materias_asignadas == 0:
            return f"❌ Sin materias asignadas (esperadas: {self.cantidad_esperada})"
        
        if self.esta_completa:
            return f"✅ Completa ({self.materias_asignadas}/{self.cantidad_esperada} materias)"
        
        return f"⚠️ Incompleta ({self.materias_asignadas}/{self.cantidad_esperada} materias, faltan {self.materias_faltantes})"


def get_carrera_status(session: Session, carrera_codigo: str) -> CarreraValidationStatus:
    """
    Get validation status for a carrera.
    
    Args:
        session: Database session
        carrera_codigo: Carrera codigo
        
    Returns:
        CarreraValidationStatus with completeness information
    """
    # Get carrera
    carrera = carrera_service.get(session, carrera_codigo)
    if carrera is None:
        raise ValueError(f"Carrera {carrera_codigo} not found")
    
    # Use the latest plan version for counting
    from src.database.models import PlanCarreraVersionDB
    latest_version = session.exec(
        select(PlanCarreraVersionDB)
        .where(PlanCarreraVersionDB.carrera_codigo == carrera_codigo)
        .order_by(PlanCarreraVersionDB.fecha_creacion.desc())
    ).first()

    # Count distinct obligatory materias (cantidad_materias refers to obligatorias only)
    stmt = (
        select(func.count(func.distinct(PlanEstudioDB.materia_codigo)))
        .where(PlanEstudioDB.carrera_codigo == carrera_codigo)
        .where(PlanEstudioDB.optativa == False)
    )
    if latest_version:
        stmt = stmt.where(PlanEstudioDB.plan_version_id == latest_version.id)
    materias_asignadas = session.exec(stmt).one()
    
    # Safely get cantidad_materias (handle cases where attribute might not exist)
    cantidad_esperada = getattr(carrera, 'cantidad_materias', None)
    
    return CarreraValidationStatus(
        carrera=carrera,
        materias_asignadas=materias_asignadas,
        cantidad_esperada=cantidad_esperada,
    )


def get_all_carreras_status(session: Session) -> List[CarreraValidationStatus]:
    """
    Get validation status for all carreras.
    
    Args:
        session: Database session
        
    Returns:
        List of CarreraValidationStatus for all carreras
    """
    carreras = carrera_service.get_all(session)
    statuses = []
    
    for carrera in carreras:
        try:
            status = get_carrera_status(session, carrera.codigo)
            statuses.append(status)
        except Exception:
            # Skip carreras that fail validation
            continue
    
    return statuses


def get_carreras_incompletas(session: Session) -> List[CarreraValidationStatus]:
    """
    Get all carreras that are incomplete (missing materias).
    
    Args:
        session: Database session
        
    Returns:
        List of CarreraValidationStatus for incomplete carreras
    """
    all_statuses = get_all_carreras_status(session)
    return [
        status for status in all_statuses
        if not status.esta_completa
    ]


def get_carreras_sin_cantidad_definida(session: Session) -> List[CarreraValidationStatus]:
    """
    Get all carreras without cantidad_materias defined.
    
    Args:
        session: Database session
        
    Returns:
        List of CarreraValidationStatus for carreras without cantidad_materias
    """
    all_statuses = get_all_carreras_status(session)
    return [
        status for status in all_statuses
        if not status.tiene_cantidad_definida
    ]


def get_validation_summary(session: Session) -> Dict[str, any]:
    """
    Get a summary of carrera validation status.
    
    Args:
        session: Database session
        
    Returns:
        Dictionary with summary statistics
    """
    all_statuses = get_all_carreras_status(session)
    
    total_carreras = len(all_statuses)
    carreras_completas = sum(1 for s in all_statuses if s.esta_completa)
    carreras_incompletas = sum(1 for s in all_statuses if not s.esta_completa and s.tiene_cantidad_definida)
    carreras_sin_cantidad = sum(1 for s in all_statuses if not s.tiene_cantidad_definida)
    
    return {
        "total_carreras": total_carreras,
        "carreras_completas": carreras_completas,
        "carreras_incompletas": carreras_incompletas,
        "carreras_sin_cantidad": carreras_sin_cantidad,
        "porcentaje_completas": (carreras_completas / total_carreras * 100) if total_carreras > 0 else 0,
    }
