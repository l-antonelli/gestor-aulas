"""Base entity class for all domain entities using Pydantic."""

from pydantic import BaseModel, ConfigDict


class Entity(BaseModel):
    """
    Base class for all domain entities.
    
    Provides:
    - Automatic validation via Pydantic
    - JSON serialization/deserialization
    - Equality based on all fields
    - Hashability for use in sets and as dict keys
    """
    
    model_config = ConfigDict(
        frozen=True,  # Makes instances immutable and hashable
        str_strip_whitespace=True,
        validate_assignment=True,
    )
    
    def __eq__(self, other: object) -> bool:
        """Two entities are equal if they have the same type and field values."""
        if not isinstance(other, self.__class__):
            return False
        return self.model_dump() == other.model_dump()
    
    def __hash__(self) -> int:
        """Hash based on all field values for use in sets/dicts."""
        return hash(tuple(sorted(self.model_dump().items(), key=lambda x: x[0])))
