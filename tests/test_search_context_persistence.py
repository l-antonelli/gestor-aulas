"""
Tests for search context persistence in RelationshipSelector.

This module tests that search terms are remembered when navigating
between pages and restored when returning to a relationship selector.
"""

import pytest
from pydantic import BaseModel, Field
from unittest.mock import MagicMock
import streamlit as st

from src.ui.relationship_selector import RelationshipSelector
from src.services.relationship_registry import RelationshipRegistry
from src.services.relationship_metadata import RelationshipMetadata


class TestSearchContextPersistence:
    """Tests for search context persistence functionality."""

    def setup_method(self):
        """Clear registry and session state before each test."""
        RelationshipRegistry.clear_registry()
        # Clear session state
        for key in list(st.session_state.keys()):
            del st.session_state[key]

    def test_search_context_key_format(self):
        """Test that search context keys follow the expected format."""
        
        class ParentModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        class ChildModel(BaseModel):
            parent_id: str = Field(..., description="Parent")
        
        expected_key = "search_context_ParentModel_ChildModel_parent_id"
        
        # Get the search context (should be empty initially)
        context = RelationshipSelector.get_search_context(
            ParentModel, ChildModel, "parent_id"
        )
        
        assert context == ""
        assert expected_key not in st.session_state

    def test_get_search_context_returns_empty_when_not_set(self):
        """Test that get_search_context returns empty string when not set."""
        
        class Model1(BaseModel):
            id: str = Field(..., description="ID")
        
        class Model2(BaseModel):
            model1_id: str = Field(..., description="Model1")
        
        context = RelationshipSelector.get_search_context(Model1, Model2, "model1_id")
        
        assert context == ""

    def test_clear_search_context_removes_specific_context(self):
        """Test that clear_search_context removes only the specified context."""
        
        class Parent1(BaseModel):
            id: str = Field(..., description="ID")
        
        class Parent2(BaseModel):
            id: str = Field(..., description="ID")
        
        class Child(BaseModel):
            parent1_id: str = Field(..., description="Parent1")
            parent2_id: str = Field(..., description="Parent2")
        
        # Set up two search contexts
        key1 = "search_context_Parent1_Child_parent1_id"
        key2 = "search_context_Parent2_Child_parent2_id"
        
        st.session_state[key1] = "search term 1"
        st.session_state[key2] = "search term 2"
        
        # Clear only the first context
        RelationshipSelector.clear_search_context(Parent1, Child, "parent1_id")
        
        # First context should be cleared
        assert key1 not in st.session_state
        # Second context should remain
        assert key2 in st.session_state
        assert st.session_state[key2] == "search term 2"

    def test_clear_all_search_contexts_removes_all(self):
        """Test that clear_all_search_contexts removes all search contexts."""
        
        # Set up multiple search contexts
        st.session_state["search_context_Model1_Model2_field1"] = "term1"
        st.session_state["search_context_Model3_Model4_field2"] = "term2"
        st.session_state["search_context_Model5_Model6_field3"] = "term3"
        st.session_state["other_key"] = "should remain"
        
        # Clear all search contexts
        RelationshipSelector.clear_all_search_contexts()
        
        # All search contexts should be cleared
        assert "search_context_Model1_Model2_field1" not in st.session_state
        assert "search_context_Model3_Model4_field2" not in st.session_state
        assert "search_context_Model5_Model6_field3" not in st.session_state
        
        # Other keys should remain
        assert "other_key" in st.session_state
        assert st.session_state["other_key"] == "should remain"

    def test_search_context_persistence_workflow(self):
        """Test the complete workflow of search context persistence."""
        
        class ParentModel(BaseModel):
            id: str = Field(..., description="ID")
            name: str = Field(..., description="Name")
        
        class ChildModel(BaseModel):
            parent_id: str = Field(..., description="Parent")
        
        # Step 1: Initially no search context
        context = RelationshipSelector.get_search_context(
            ParentModel, ChildModel, "parent_id"
        )
        assert context == ""
        
        # Step 2: Simulate user entering a search term
        search_key = "search_context_ParentModel_ChildModel_parent_id"
        st.session_state[search_key] = "test search"
        
        # Step 3: Get search context (simulating navigation back)
        context = RelationshipSelector.get_search_context(
            ParentModel, ChildModel, "parent_id"
        )
        assert context == "test search"
        
        # Step 4: Clear the search context
        RelationshipSelector.clear_search_context(
            ParentModel, ChildModel, "parent_id"
        )
        
        # Step 5: Verify it's cleared
        context = RelationshipSelector.get_search_context(
            ParentModel, ChildModel, "parent_id"
        )
        assert context == ""

    def test_multiple_selectors_maintain_separate_contexts(self):
        """Test that multiple relationship selectors maintain separate search contexts."""
        
        class Materia(BaseModel):
            codigo: str = Field(..., description="Código")
            nombre: str = Field(..., description="Nombre")
        
        class Alumno(BaseModel):
            legajo: str = Field(..., description="Legajo")
            nombre: str = Field(..., description="Nombre")
        
        class Inscripcion(BaseModel):
            materia_codigo: str = Field(..., description="Materia")
            alumno_legajo: str = Field(..., description="Alumno")
        
        # Set up search contexts for both relationships
        materia_key = "search_context_Materia_Inscripcion_materia_codigo"
        alumno_key = "search_context_Alumno_Inscripcion_alumno_legajo"
        
        st.session_state[materia_key] = "matematica"
        st.session_state[alumno_key] = "juan"
        
        # Get contexts
        materia_context = RelationshipSelector.get_search_context(
            Materia, Inscripcion, "materia_codigo"
        )
        alumno_context = RelationshipSelector.get_search_context(
            Alumno, Inscripcion, "alumno_legajo"
        )
        
        # Each should have its own context
        assert materia_context == "matematica"
        assert alumno_context == "juan"
        
        # Clear one context
        RelationshipSelector.clear_search_context(Materia, Inscripcion, "materia_codigo")
        
        # Only the cleared one should be empty
        materia_context = RelationshipSelector.get_search_context(
            Materia, Inscripcion, "materia_codigo"
        )
        alumno_context = RelationshipSelector.get_search_context(
            Alumno, Inscripcion, "alumno_legajo"
        )
        
        assert materia_context == ""
        assert alumno_context == "juan"

    def test_search_context_survives_page_navigation(self):
        """Test that search context persists across simulated page navigation."""
        
        class Parent(BaseModel):
            id: str = Field(..., description="ID")
        
        class Child(BaseModel):
            parent_id: str = Field(..., description="Parent")
        
        # Simulate user on page 1 entering search term
        search_key = "search_context_Parent_Child_parent_id"
        st.session_state[search_key] = "my search term"
        
        # Simulate navigation to page 2 (session state persists)
        # ... user does other things ...
        
        # Simulate navigation back to page 1
        # Get the search context - it should still be there
        context = RelationshipSelector.get_search_context(Parent, Child, "parent_id")
        
        assert context == "my search term"
        assert search_key in st.session_state
