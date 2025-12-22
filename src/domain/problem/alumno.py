"""Alumno entity - Student in the university system."""

from pydantic import Field, field_validator

from src.domain.base import Entity
from src.domain.types import Legajo, DNI


class Alumno(Entity):
    """
    Represents a student enrolled in the university.
    
    Attributes:
        legajo: Unique student identifier (e.g., "A-12345")
        email: Student's email address
        nombre: Student's full name
        dni: National ID number (7-8 digits)
    """
    
    legajo: Legajo = Field(..., description="Unique student identifier")
    email: str = Field(..., description="Student email address")
    nombre: str = Field(..., min_length=1, description="Student full name")
    dni: DNI = Field(..., description="National ID number")
    
    @field_validator("legajo")
    @classmethod
    def validate_legajo(cls, v: str) -> str:
        """Validate that legajo is not empty."""
        if not v or not v.strip():
            raise ValueError("legajo cannot be empty")
        return v
    
    @field_validator("email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format (basic check)."""
        if not v or not v.strip():
            raise ValueError("email cannot be empty")
        if "@" not in v:
            raise ValueError("email must contain @")
        return v
    
    @field_validator("dni")
    @classmethod
    def validate_dni(cls, v: str) -> str:
        """Validate DNI is 7-8 digits."""
        if not v or not v.strip():
            raise ValueError("dni cannot be empty")
        digits_only = v.replace(".", "").replace("-", "")
        if not digits_only.isdigit():
            raise ValueError("dni must contain only digits")
        if not (7 <= len(digits_only) <= 8):
            raise ValueError("dni must be 7-8 digits")
        return v
