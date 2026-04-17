"""
Tests for Page Code Simplification.

This module verifies that page files follow the simplified structure:
- No CRUD wrapper functions in page files
- Pages use service layer imports where applicable
- Template pages follow consistent EntityPageConfig structure
- Custom pages meet their own structural requirements

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

# Pages using EntityPageConfig / EntityPageTemplate
TEMPLATE_PAGES = [
    "app/pages/2_🏛️_Aulas.py",
]

# Pages with custom implementations (legitimate reasons not to use template)
CUSTOM_PAGES = [
    "app/pages/1_📚_Materias.py",       # Complex carrera/comision management
    "app/pages/3_👥_Comisiones.py",      # Read-only view with cupo editing
    "app/pages/4_📅_Horarios.py",        # File upload + manual entry
    "app/pages/5_🎓_Carreras.py",        # Completeness tracking + plan management
    "app/pages/6_📆_Ciclos.py",          # Simple custom CRUD
]

# All pages
ALL_PAGES = TEMPLATE_PAGES + CUSTOM_PAGES

# Maximum allowed lines for a standard entity page
MAX_PAGE_LINES = 150

# Required service layer imports for template pages
TEMPLATE_SERVICE_IMPORTS = [
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


def check_service_imports(content: str, required_imports: List[str] = None) -> Tuple[bool, List[str]]:
    """Check if content imports from service layer."""
    if required_imports is None:
        required_imports = TEMPLATE_SERVICE_IMPORTS
    missing = []
    for import_path in required_imports:
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

class TestTemplatePages:
    """
    Tests for pages using EntityPageConfig / EntityPageTemplate.

    Requirements: 7.1, 7.2, 7.3, 7.5
    """

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_no_crud_wrapper_functions(self, page_path: str):
        """Template pages should not contain CRUD wrapper functions."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        crud_wrappers = find_crud_wrapper_functions(content)
        assert len(crud_wrappers) == 0, (
            f"Page {page_path} contains CRUD wrapper functions: {crud_wrappers}. "
            "These should be moved to the service layer."
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_uses_service_layer_imports(self, page_path: str):
        """Template pages should import from service layer and page_template."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        has_imports, missing = check_service_imports(content, TEMPLATE_SERVICE_IMPORTS)
        assert has_imports, (
            f"Page {page_path} is missing service layer imports: {missing}"
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_page_line_count(self, page_path: str):
        """Template pages should not exceed maximum line count."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        line_count = count_lines(content)
        assert line_count <= MAX_PAGE_LINES, (
            f"Page {page_path} has {line_count} lines, exceeding maximum of {MAX_PAGE_LINES}."
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_follows_consistent_structure(self, page_path: str):
        """Template pages should use EntityPageConfig and EntityPageTemplate."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        is_consistent, issues = check_consistent_structure(content)
        assert is_consistent, (
            f"Page {page_path} does not follow consistent structure: {issues}"
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_uses_entity_page_config(self, page_path: str):
        """Template pages should use EntityPageConfig for configuration."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        assert "EntityPageConfig" in content, (
            f"Page {page_path} should use EntityPageConfig for declarative configuration"
        )


class TestCustomPages:
    """
    Tests for pages with custom implementations.

    These pages have legitimate reasons not to use EntityPageTemplate
    (complex relationships, file upload, read-only views, etc.)
    but should still meet basic hygiene requirements.
    """

    @pytest.mark.parametrize("page_path", CUSTOM_PAGES)
    def test_has_page_config(self, page_path: str):
        """Custom pages should still call st.set_page_config."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        assert "st.set_page_config" in content, (
            f"Page {page_path} should call st.set_page_config"
        )

    @pytest.mark.parametrize("page_path", CUSTOM_PAGES)
    def test_initializes_db(self, page_path: str):
        """Custom pages should initialize the database."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        assert "init_db" in content, (
            f"Page {page_path} should initialize the database"
        )


# =============================================================================
# Test Class: Page Structure Verification
# =============================================================================

class TestPageStructureVerification:
    """
    Tests for verifying specific page structure patterns.

    Requirements: 7.3, 7.5
    """

    def test_materias_page_structure(self):
        """Test Materias page has service imports and carrera management."""
        content = get_page_content("app/pages/1_📚_Materias.py")
        if not content:
            pytest.skip("Materias page not found")

        assert "materia_service" in content
        assert "MateriaCarreraEditor" in content or "CarreraStatusWidget" in content

    def test_aulas_page_structure(self):
        """Test Aulas page uses EntityPageConfig template."""
        content = get_page_content("app/pages/2_🏛️_Aulas.py")
        if not content:
            pytest.skip("Aulas page not found")

        assert "aula_service" in content
        assert "EntityPageConfig" in content

    def test_comisiones_page_structure(self):
        """Test Comisiones page is read-only with cupo editing."""
        content = get_page_content("app/pages/3_👥_Comisiones.py")
        if not content:
            pytest.skip("Comisiones page not found")

        assert "comision" in content.lower()
        assert "cupo" in content

    def test_carreras_page_structure(self):
        """Test Carreras page has service imports and completeness tracking."""
        content = get_page_content("app/pages/5_🎓_Carreras.py")
        if not content:
            pytest.skip("Carreras page not found")

        assert "carrera_service" in content
        assert "CarreraStatusWidget" in content


# =============================================================================
# Test Class: Import Verification
# =============================================================================

class TestImportVerification:
    """
    Tests for verifying correct imports in page files.

    Requirements: 7.2
    """

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_template_imports_from_services(self, page_path: str):
        """Template pages should import from services module."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        imports = parse_imports(content)
        service_imports = [i for i in imports if "services" in i]
        assert len(service_imports) > 0, (
            f"Page {page_path} should import from services module"
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_template_imports_from_ui(self, page_path: str):
        """Template pages should import from UI module."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        imports = parse_imports(content)
        ui_imports = [i for i in imports if "ui" in i]
        assert len(ui_imports) > 0, (
            f"Page {page_path} should import from UI module"
        )

    @pytest.mark.parametrize("page_path", TEMPLATE_PAGES)
    def test_template_imports_domain_models(self, page_path: str):
        """Template pages should import domain models."""
        content = get_page_content(page_path)
        if not content:
            pytest.skip(f"Page file not found: {page_path}")

        imports = parse_imports(content)
        domain_imports = [i for i in imports if "domain" in i]
        assert len(domain_imports) > 0, (
            f"Page {page_path} should import domain models"
        )
