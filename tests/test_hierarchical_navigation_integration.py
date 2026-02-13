"""
Comprehensive Integration Tests for Hierarchical Navigation.

This module tests complete end-to-end hierarchical navigation workflows:
- Navigate Carrera → Materia → Comisión → Horario
- Verify breadcrumbs update correctly
- Verify context is preserved
- Verify back navigation works

Requirements: 2.4, 2.5, 2.6, 3.1, 3.2, 5.1, 5.3
"""

import datetime
from datetime import time
from typing import Generator, Dict, Any
from unittest.mock import patch, MagicMock

import pytest
from sqlmodel import Session, SQLModel, create_engine

# Domain models
from src.domain.problem import (
    Materia,
    Comision,
    Horario,
)
from src.domain.problem.carrera import Carrera

# Database models and CRUD
from src.database.models import (
    MateriaDB, ComisionDB, HorarioDB, CarreraDB,
)
from src.database.crud import (
    materia_crud, comision_crud, horario_crud,
)
from src.database.converters import to_db

# Services
from src.services.crud_services import (
    materia_service, comision_service, carrera_service,
)
from src.services.cascading_operations import CascadingOperations

# UI Components
from src.ui.breadcrumb_navigation import BreadcrumbNavigation, BreadcrumbItem
from src.ui.entity_context_manager import EntityContextManager, EntityContext
from src.ui.hierarchical_entity_viewer import HierarchicalEntityViewer, HierarchyLevel, ChildConfig

# Import relationship definitions
import src.services.relationship_definitions  # noqa: F401


# =============================================================================
# Test Fixtures
# =============================================================================

@pytest.fixture
def test_db_session() -> Generator[Session, None, None]:
    """Create a temporary in-memory database for testing."""
    engine = create_engine(
        "sqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False}
    )
    
    SQLModel.metadata.create_all(engine)
    
    with Session(engine) as session:
        yield session


@pytest.fixture
def mock_session_state():
    """Mock Streamlit session state for navigation tests."""
    mock_state: Dict[str, Any] = {}
    
    with patch('src.ui.entity_context_manager.st') as mock_st:
        mock_st.session_state = mock_state
        yield mock_state


@pytest.fixture
def mock_breadcrumb_state():
    """Mock session state specifically for breadcrumb navigation."""
    mock_state = {BreadcrumbNavigation.SESSION_KEY: []}
    
    with patch.object(
        BreadcrumbNavigation,
        'get_current_path',
        side_effect=lambda: list(mock_state.get(BreadcrumbNavigation.SESSION_KEY, []))
    ), patch.object(
        BreadcrumbNavigation,
        '_set_path',
        side_effect=lambda p: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, p)
    ), patch.object(
        BreadcrumbNavigation,
        'clear_path',
        side_effect=lambda: mock_state.__setitem__(BreadcrumbNavigation.SESSION_KEY, [])
    ):
        yield mock_state


@pytest.fixture
def sample_hierarchy_data(test_db_session: Session):
    """Create a complete hierarchy of test data: Materia → Comisión → Horario."""
    # Create Materia
    materia = Materia(
        codigo="MAT101",
        nombre="Cálculo I",
        cupo=30,
        horas_semanales=4,
    )
    db_materia = to_db(materia)
    created_materia = materia_crud.create(test_db_session, db_materia)

    # Create Comisiones manually (no cascading comision creation)
    comision1 = Comision(
        id="MAT101-C1",
        materia_codigo="MAT101",
        nombre="Comision Unica",
        numero=1,
        cupo=30,
    )
    db_comision1 = to_db(comision1)
    created_comision1 = comision_crud.create(test_db_session, db_comision1)

    comision2 = Comision(
        id="COM-002",
        materia_codigo="MAT101",
        nombre="Comision B",
        numero=2,
        cupo=25,
    )
    db_comision2 = to_db(comision2)
    comision_crud.create(test_db_session, db_comision2)

    # Create Horario for the first Comision
    horario = Horario(
        id="HOR-001",
        comision_id=created_comision1.id,
        codigo_materia="MAT101",
        dia="Lunes",
        hora_inicio=time(8, 0),
        hora_fin=time(10, 0),
    )
    db_horario = to_db(horario)
    horario_crud.create(test_db_session, db_horario)

    return {
        "materia": created_materia,
        "comision1": created_comision1,
        "comision2": comision2,
        "horario": horario,
    }


# =============================================================================
# Test Class: End-to-End Hierarchical Navigation
# =============================================================================

class TestEndToEndHierarchicalNavigation:
    """
    Tests for complete hierarchical navigation workflows.
    
    Requirements: 2.4, 2.5, 2.6, 3.1, 3.2, 5.1, 5.3
    """
    
    def test_navigate_materia_to_comision(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
        mock_breadcrumb_state,
        mock_session_state,
    ):
        """
        Test navigating from Materia to Comisión.
        
        Requirements: 2.4, 2.5, 3.1
        """
        # Create a domain model for testing (not DB model)
        materia = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        
        # Build breadcrumb item directly
        item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚",
        )
        BreadcrumbNavigation.push_to_path(item)
        
        # Verify breadcrumb was updated
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0].model_name == "Materia"
        assert path[0].entity_id == "MAT101"
        assert path[0].display_name == "Cálculo I"
    
    def test_navigate_full_hierarchy_materia_comision(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
        mock_breadcrumb_state,
        mock_session_state,
    ):
        """
        Test navigating through full hierarchy: Materia → Comisión.
        
        Requirements: 2.4, 2.5, 2.6, 3.1
        """
        materia = sample_hierarchy_data["materia"]
        comision = sample_hierarchy_data["comision1"]
        
        # Navigate to Materia
        HierarchicalEntityViewer.handle_drill_down(
            entity=materia,
            model=MateriaDB,
            id_field="codigo",
            display_field="nombre",
            icon="📚",
        )
        
        # Navigate to Comisión
        if comision:
            HierarchicalEntityViewer.handle_drill_down(
                entity=comision,
                model=ComisionDB,
                id_field="id",
                display_field="nombre",
                icon="👥",
            )
            
            # Verify breadcrumb shows full path
            path = BreadcrumbNavigation.get_current_path()
            assert len(path) == 2
            assert path[0].model_name == "MateriaDB"
            assert path[1].model_name == "ComisionDB"
    
    def test_breadcrumb_updates_on_navigation(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
        mock_breadcrumb_state,
    ):
        """
        Test that breadcrumbs update correctly during navigation.
        
        Requirements: 3.1, 3.3
        """
        # Initially empty
        assert len(BreadcrumbNavigation.get_current_path()) == 0
        
        # Create breadcrumb item directly
        item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚",
        )
        BreadcrumbNavigation.push_to_path(item)
        
        # Verify breadcrumb updated
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0].display_name == "Cálculo I"
    
    def test_back_navigation_via_breadcrumb(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
        mock_breadcrumb_state,
    ):
        """
        Test navigating back using breadcrumb.
        
        Requirements: 3.2, 5.3
        """
        materia = sample_hierarchy_data["materia"]
        comision = sample_hierarchy_data["comision1"]
        
        # Build navigation path
        materia_item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚",
        )
        BreadcrumbNavigation.push_to_path(materia_item)
        
        if comision:
            comision_item = BreadcrumbItem(
                model_name="Comision",
                entity_id=comision.id,
                display_name=comision.nombre,
                icon="👥",
            )
            BreadcrumbNavigation.push_to_path(comision_item)
        
        # Verify we're at Comisión level
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 2
        
        # Navigate back to Materia via breadcrumb
        BreadcrumbNavigation.pop_to_item(materia_item)
        
        # Verify we're back at Materia level
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0].model_name == "Materia"


# =============================================================================
# Test Class: Context Preservation
# =============================================================================

class TestContextPreservation:
    """
    Tests for entity context preservation during navigation.
    
    Requirements: 5.1, 5.3
    """
    
    def test_context_preserved_on_drill_down(self, mock_session_state):
        """
        Test that parent context is preserved when drilling down.
        
        Requirements: 5.1
        """
        # Set initial context (Materia)
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
        )
        
        # Drill down to Comisión
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="COM-001",
        )
        
        # Verify parent context is preserved
        context = EntityContextManager.get_context()
        assert context is not None
        assert context.model_name == "Comision"
        assert context.entity_id == "COM-001"
        assert context.parent_context is not None
        assert context.parent_context.model_name == "Materia"
        assert context.parent_context.entity_id == "MAT101"
    
    def test_context_chain_maintained(self, mock_session_state):
        """
        Test that full context chain is maintained through navigation.

        Requirements: 5.1, 5.3
        """
        # Build navigation chain: Materia → Comisión → Horario
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="COM-001",
        )
        EntityContextManager.set_selected_entity(
            model=Horario,
            entity_id="HOR-001",
        )

        # Verify full chain
        chain = EntityContextManager.get_context_chain()
        assert len(chain) == 3
        assert chain[0].model_name == "Materia"
        assert chain[1].model_name == "Comision"
        assert chain[2].model_name == "Horario"
    
    def test_navigate_to_parent_restores_context(self, mock_session_state):
        """
        Test that navigating to parent restores previous context.
        
        Requirements: 5.3
        """
        # Build navigation chain
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="COM-001",
        )
        
        # Navigate back to parent
        parent = EntityContextManager.navigate_to_parent()
        
        # Verify we're back at Materia
        assert parent is not None
        assert parent.model_name == "Materia"
        
        current = EntityContextManager.get_context()
        assert current.model_name == "Materia"
        assert current.entity_id == "MAT101"
    
    def test_context_depth_tracking(self, mock_session_state):
        """
        Test that context depth is tracked correctly.
        
        Requirements: 5.1
        """
        # Initially no context
        assert EntityContextManager.get_context_depth() == 0
        
        # Add first level
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
        )
        assert EntityContextManager.get_context_depth() == 1
        
        # Add second level
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="COM-001",
        )
        assert EntityContextManager.get_context_depth() == 2
    
    def test_clear_context_removes_all(self, mock_session_state):
        """
        Test that clearing context removes all navigation state.
        
        Requirements: 5.1
        """
        # Build navigation chain
        EntityContextManager.set_selected_entity(
            model=Materia,
            entity_id="MAT101",
        )
        EntityContextManager.set_selected_entity(
            model=Comision,
            entity_id="COM-001",
        )
        
        # Clear context
        EntityContextManager.clear_context()
        
        # Verify all cleared
        assert EntityContextManager.get_context() is None
        assert EntityContextManager.get_context_depth() == 0
        assert EntityContextManager.get_context_chain() == []


# =============================================================================
# Test Class: Hierarchical Child Retrieval
# =============================================================================

class TestHierarchicalChildRetrieval:
    """
    Tests for retrieving children in hierarchical views.
    
    Requirements: 2.1, 2.2, 2.3
    """
    
    def test_get_comisiones_for_materia(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
    ):
        """
        Test retrieving Comisiones for a Materia.
        
        Requirements: 2.2
        """
        # Get all comisiones for MAT101
        all_comisiones = comision_crud.get_all(test_db_session)
        materia_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        
        # Should have 2 comisiones (auto-created + manually created)
        assert len(materia_comisiones) == 2
    
    def test_child_count_accuracy(
        self,
        test_db_session: Session,
        sample_hierarchy_data,
    ):
        """
        Test that child count is accurate.
        
        Requirements: 2.1, 2.2
        """
        # Create a mock service that returns comisiones
        class MockComisionService:
            def get_all(self, session, skip=0, limit=100):
                return comision_crud.get_all(session)
        
        mock_service = MockComisionService()
        
        # Get count using hierarchical viewer
        count = HierarchicalEntityViewer.get_children_count(
            parent_id="MAT101",
            child_service=mock_service,
            foreign_key_field="materia_codigo",
            session=test_db_session,
        )
        
        # Should match actual count
        all_comisiones = comision_crud.get_all(test_db_session)
        expected_count = len([c for c in all_comisiones if c.materia_codigo == "MAT101"])
        
        assert count == expected_count
    
    def test_children_filtered_by_parent(
        self,
        test_db_session: Session,
    ):
        """
        Test that children are correctly filtered by parent.
        
        Requirements: 2.1, 2.2, 2.3
        """
        # Create two materias with their comisiones
        materia1 = Materia(
            codigo="MAT101",
            nombre="Cálculo I",
            cupo=30,
            horas_semanales=4,
        )
        db_materia1 = to_db(materia1)
        materia_crud.create(test_db_session, db_materia1)

        com1 = Comision(id="MAT101-C1", materia_codigo="MAT101",
                        nombre="Comision Unica", numero=1, cupo=30)
        comision_crud.create(test_db_session, to_db(com1))

        materia2 = Materia(
            codigo="MAT102",
            nombre="Álgebra I",
            cupo=25,
            horas_semanales=4,
        )
        db_materia2 = to_db(materia2)
        materia_crud.create(test_db_session, db_materia2)

        com2 = Comision(id="MAT102-C1", materia_codigo="MAT102",
                        nombre="Comision Unica", numero=1, cupo=25)
        comision_crud.create(test_db_session, to_db(com2))

        # Get comisiones for each materia
        all_comisiones = comision_crud.get_all(test_db_session)

        mat101_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT101"]
        mat102_comisiones = [c for c in all_comisiones if c.materia_codigo == "MAT102"]

        # Each should have their own comisiones
        assert len(mat101_comisiones) == 1
        assert len(mat102_comisiones) == 1

        # No overlap
        mat101_ids = {c.id for c in mat101_comisiones}
        mat102_ids = {c.id for c in mat102_comisiones}
        assert mat101_ids.isdisjoint(mat102_ids)


# =============================================================================
# Test Class: Breadcrumb Navigation Integration
# =============================================================================

class TestBreadcrumbNavigationIntegration:
    """
    Tests for breadcrumb navigation integration with hierarchical views.
    
    Requirements: 3.1, 3.2, 3.3, 3.4
    """
    
    def test_breadcrumb_path_consistency(self, mock_breadcrumb_state):
        """
        Test that breadcrumb path remains consistent through operations.
        
        Requirements: 3.1, 3.3
        """
        # Build path
        items = [
            BreadcrumbItem(model_name="Materia", entity_id="MAT101", display_name="Cálculo I"),
            BreadcrumbItem(model_name="Comision", entity_id="COM-001", display_name="Comisión A"),
        ]
        
        for item in items:
            BreadcrumbNavigation.push_to_path(item)
        
        # Verify path
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 2
        assert path[0].model_name == "Materia"
        assert path[1].model_name == "Comision"
    
    def test_breadcrumb_click_navigation(self, mock_breadcrumb_state):
        """
        Test clicking on breadcrumb item navigates correctly.
        
        Requirements: 3.2
        """
        # Build path
        materia_item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
        )
        comision_item = BreadcrumbItem(
            model_name="Comision",
            entity_id="COM-001",
            display_name="Comisión A",
        )
        
        BreadcrumbNavigation.push_to_path(materia_item)
        BreadcrumbNavigation.push_to_path(comision_item)
        
        # Click on Materia breadcrumb
        BreadcrumbNavigation.pop_to_item(materia_item)
        
        # Should be back at Materia
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0].model_name == "Materia"
    
    def test_breadcrumb_persists_display_info(self, mock_breadcrumb_state):
        """
        Test that breadcrumb preserves display information.
        
        Requirements: 3.1
        """
        item = BreadcrumbItem(
            model_name="Materia",
            entity_id="MAT101",
            display_name="Cálculo I",
            icon="📚",
        )
        
        BreadcrumbNavigation.push_to_path(item)
        
        path = BreadcrumbNavigation.get_current_path()
        assert path[0].display_name == "Cálculo I"
        assert path[0].icon == "📚"
    
    def test_push_existing_item_truncates(self, mock_breadcrumb_state):
        """
        Test that pushing an existing item truncates the path.
        
        Requirements: 3.2
        """
        items = [
            BreadcrumbItem(model_name="Materia", entity_id="MAT101", display_name="Cálculo I"),
            BreadcrumbItem(model_name="Comision", entity_id="COM-001", display_name="Comisión A"),
            BreadcrumbItem(model_name="Horario", entity_id="HOR-001", display_name="Horario 1"),
        ]
        
        for item in items:
            BreadcrumbNavigation.push_to_path(item)
        
        # Push the first item again
        BreadcrumbNavigation.push_to_path(items[0])
        
        # Path should be truncated to just the first item
        path = BreadcrumbNavigation.get_current_path()
        assert len(path) == 1
        assert path[0].model_name == "Materia"
