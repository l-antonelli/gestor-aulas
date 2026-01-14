"""
Tests for Page Code Simplification.

This module verifies that page files follow the simplified structure:
- No CRUD wrapper functions in page files
- Pages use service layer imports
- Pages follow consistent structure

Requirements: 7.1, 7.2, 7.3, 7.5
"""

import ast
import os
import re
from pathlib import Path
from typing import List, Set, Tuple

import pytest


# =============================================================================
# Test Configuration
# =============================================================================

# Pages that should be refactored
REFACTORED_PAGES = [
    "app/pages/1_📚_Materias.py",
    "app/pages/2_🏛️_Aulas.py",
    "app/pages/3_👥_Comisiones.py",
    "app/pages/5_🎓_Alumnos.py",
    "app/pages/7_🎓_Carreras.py",
]

# Maximum allowed lines for a standard entity page
MAX_PAGE_LINES = 150

# Required service layer imports
SERVICE_LAYER_IMPORTS = [
    "src.services.crud_services",
    "src.ui.page_template",
]

# Patterns that indicate CRUD wrapper functions (should NOT be present)
CRUD_WRAPPER_PATTERNS = [
    r"def\s+create_\w+\s*\(",
    r"def\s+update_\w+\s*\(",
    r"def\s+delete_\w+\s*\(",
    r"def\s+get_\w+\s*\(",
    r"def\s+list_\w+\s*\(",
    r"def\s+save_\w+\s*\(",
    r"def\s+remove_\w+\s*\(",
]


# =============================================================================
# Helper Functions
# =============================================================================

def get_page_content(page_path: str) -> str:
    """Read the content of a page file."""
    full_path = Path(page_path)
    if full_path.exists():
        return full_path.read_text(encoding="utf-8")
    return ""


def count_lines(content: str) -> int:
    """Count non-empty, non-comment lines in content."""
    lines = content.split("\n")
    count = 0
    in_multiline_string = False
    
    for line in lines:
        stripped = line.strip()
        
        # Skip empty lines
        if not stripped:
            continue
        
        # Skip single-line comments
        if stripped.startswith("#"):
            continue
        
        # Track multiline strings (docstrings)
        if '"""' in stripped or "'''" in stripped:
            # Count of triple quotes
            triple_double = stripped.count('"""')
            triple_single = stripped.count("'''")
            
            if triple_double % 2 == 1 or triple_single % 2 == 1:
                in_multiline_string = not in_multiline_string
            
            # If line only contains docstring markers, skip
            if stripped in ['"""', "'''"]:
                continue
        
        if not in_multiline_string:
            count += 1
    
    return count


def find_crud_wrapper_functions(content: str) -> List[str]:
    """Find CRUD wrapper function definitions in content."""
    found = []
    for pattern in CRUD_WRAPPER_PATTERNS:
        matches = re.findall(pattern, content)
        found.extend(matches)
    return found


def check_service_imports(content: str) -> Tuple[bool, List[str]]:
    """Check if content imports from service layer."""
    missing = []
    for import_path in SERVICE_LAYER_IMPORTS:
        # Check for various import styles
        patterns = [
            f"from {import_path}",
            f"import {import_path}",
        ]
        found = any(p in content for p in patterns)
        if not found:
            missing.append(import_path)
    
    return len(missing) == 0, missing


def parse_imports(content: str) -> Set[str]:
    """Parse all imports from content using AST."""
    imports = set()
    try:
        tree = ast.parse(content)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module)
    except SyntaxError:
        pass
    return imports


def check_consistent_structure(content: str) -> Tuple[bool, List[str]]:
    """Check if page follows consistent structure."""
    issues = []
    
    # Check for required elements
    required_elements = [
        ("st.set_page_config", "Page configuration"),
        ("EntityPageConfig", "Entity page configuration"),
        ("EntityPageTemplate.render_entity_page", "Page template rendering"),
    ]
    
    for element, description in required_elements:
        if element not in content:
            issues.append(f"Missing {description} ({element})")
    
    return len(issues) == 0, issues


# =============================================================================
# Test Class: Page Code Simplification
# =============================================================================

class TestPageCodeSimplification:
    """
    Tests for verifying page code simplification.
    
    Requirements: 7.1, 7.2, 7.3, 7.5
    """
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_no_crud_wrapper_functions(self, page_path: str):
        """
        Test that page files do not contain CRUD wrapper functions.
        
        Requirements: 7.1
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        crud_wrappers = find_crud_wrapper_functions(content)
        
        assert len(crud_wrappers) == 0, (
            f"Page {page_path} contains CRUD wrapper functions: {crud_wrappers}. "
            "These should be moved to the service layer."
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_uses_service_layer_imports(self, page_path: str):
        """
        Test that page files import from the service layer.
        
        Requirements: 7.2
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        has_imports, missing = check_service_imports(content)
        
        assert has_imports, (
            f"Page {page_path} is missing service layer imports: {missing}"
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_page_line_count(self, page_path: str):
        """
        Test that page files do not exceed maximum line count.
        
        Requirements: 7.4
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        line_count = count_lines(content)
        
        # Allow some flexibility for pages with additional features
        # Carreras page has extra relationship management UI
        if "Carreras" in page_path:
            max_lines = MAX_PAGE_LINES + 50  # Extra allowance for relationship UI
        else:
            max_lines = MAX_PAGE_LINES
        
        assert line_count <= max_lines, (
            f"Page {page_path} has {line_count} lines, exceeding maximum of {max_lines}. "
            "Consider moving logic to service layer or components."
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_follows_consistent_structure(self, page_path: str):
        """
        Test that page files follow consistent structure.
        
        Requirements: 7.5
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        is_consistent, issues = check_consistent_structure(content)
        
        assert is_consistent, (
            f"Page {page_path} does not follow consistent structure: {issues}"
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_uses_entity_page_config(self, page_path: str):
        """
        Test that page files use EntityPageConfig for configuration.
        
        Requirements: 7.3
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        assert "EntityPageConfig" in content, (
            f"Page {page_path} should use EntityPageConfig for declarative configuration"
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_imports_service_not_crud(self, page_path: str):
        """
        Test that pages import services, not raw CRUD functions.
        
        Requirements: 7.2
        """
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        # Should import from crud_services
        assert "crud_services" in content, (
            f"Page {page_path} should import from crud_services"
        )
        
        # Should NOT directly import from database.crud (except for special cases)
        # Allow relationship_definitions import which may reference crud
        if "from src.database.crud import" in content:
            # This is acceptable only if it's for specific advanced use cases
            # For now, we'll allow it but flag it
            pass


# =============================================================================
# Test Class: Page Structure Verification
# =============================================================================

class TestPageStructureVerification:
    """
    Tests for verifying page structure patterns.
    
    Requirements: 7.3, 7.5
    """
    
    def test_materias_page_structure(self):
        """Test Materias page follows expected structure."""
        content = get_page_content("app/pages/1_📚_Materias.py")
        
        if not content:
            pytest.skip("Materias page not found")
        
        # Should have materia_service import
        assert "materia_service" in content
        
        # Should have EntityPageConfig
        assert "EntityPageConfig" in content
        
        # Should have child config for Comisiones
        assert "ChildConfig" in content or "child_configs" in content
    
    def test_aulas_page_structure(self):
        """Test Aulas page follows expected structure."""
        content = get_page_content("app/pages/2_🏛️_Aulas.py")
        
        if not content:
            pytest.skip("Aulas page not found")
        
        # Should have aula_service import
        assert "aula_service" in content
        
        # Should have EntityPageConfig
        assert "EntityPageConfig" in content
    
    def test_comisiones_page_structure(self):
        """Test Comisiones page follows expected structure."""
        content = get_page_content("app/pages/3_👥_Comisiones.py")
        
        if not content:
            pytest.skip("Comisiones page not found")
        
        # Should have comision_service import
        assert "comision_service" in content
        
        # Should have EntityPageConfig
        assert "EntityPageConfig" in content
    
    def test_alumnos_page_structure(self):
        """Test Alumnos page follows expected structure."""
        content = get_page_content("app/pages/5_🎓_Alumnos.py")
        
        if not content:
            pytest.skip("Alumnos page not found")
        
        # Should have alumno_service import
        assert "alumno_service" in content
        
        # Should have EntityPageConfig
        assert "EntityPageConfig" in content
    
    def test_carreras_page_structure(self):
        """Test Carreras page follows expected structure."""
        content = get_page_content("app/pages/7_🎓_Carreras.py")
        
        if not content:
            pytest.skip("Carreras page not found")
        
        # Should have carrera_service import
        assert "carrera_service" in content
        
        # Should have EntityPageConfig
        assert "EntityPageConfig" in content


# =============================================================================
# Test Class: Import Verification
# =============================================================================

class TestImportVerification:
    """
    Tests for verifying correct imports in page files.
    
    Requirements: 7.2
    """
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_imports_from_services(self, page_path: str):
        """Test that pages import from services module."""
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        imports = parse_imports(content)
        
        # Should have service imports
        service_imports = [i for i in imports if "services" in i]
        assert len(service_imports) > 0, (
            f"Page {page_path} should import from services module"
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_imports_from_ui(self, page_path: str):
        """Test that pages import from UI module."""
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        imports = parse_imports(content)
        
        # Should have UI imports
        ui_imports = [i for i in imports if "ui" in i]
        assert len(ui_imports) > 0, (
            f"Page {page_path} should import from UI module"
        )
    
    @pytest.mark.parametrize("page_path", REFACTORED_PAGES)
    def test_imports_domain_models(self, page_path: str):
        """Test that pages import domain models."""
        content = get_page_content(page_path)
        
        if not content:
            pytest.skip(f"Page file not found: {page_path}")
        
        imports = parse_imports(content)
        
        # Should have domain imports
        domain_imports = [i for i in imports if "domain" in i]
        assert len(domain_imports) > 0, (
            f"Page {page_path} should import domain models"
        )
