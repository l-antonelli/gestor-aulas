"""Tests for base entity class."""

import pytest
from src.domain.base import Entity


class SampleEntity(Entity):
    """Sample entity for testing."""
    id: str
    name: str


class TestEntity:
    """Tests for the Entity base class."""
    
    def test_entity_creation(self):
        """Test that entities can be created with valid data."""
        entity = SampleEntity(id="1", name="Test")
        assert entity.id == "1"
        assert entity.name == "Test"
    
    def test_entity_equality(self):
        """Test that entities with same values are equal."""
        e1 = SampleEntity(id="1", name="Test")
        e2 = SampleEntity(id="1", name="Test")
        assert e1 == e2
    
    def test_entity_inequality(self):
        """Test that entities with different values are not equal."""
        e1 = SampleEntity(id="1", name="Test")
        e2 = SampleEntity(id="2", name="Test")
        assert e1 != e2
    
    def test_entity_hashable(self):
        """Test that entities can be used in sets."""
        e1 = SampleEntity(id="1", name="Test")
        e2 = SampleEntity(id="1", name="Test")
        e3 = SampleEntity(id="2", name="Other")
        
        entity_set = {e1, e2, e3}
        assert len(entity_set) == 2
    
    def test_entity_immutable(self):
        """Test that entities are immutable (frozen)."""
        entity = SampleEntity(id="1", name="Test")
        with pytest.raises(Exception):  # ValidationError for frozen model
            entity.id = "2"
