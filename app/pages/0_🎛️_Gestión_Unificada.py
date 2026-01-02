"""
Gestión Unificada de Entidades.

Provides a consolidated interface for managing all domain entities
through a single unified interface.
"""

import streamlit as st
from src.database.connection import init_db
from src.ui.unified_entity_manager import UnifiedEntityManager

# Initialize database
init_db()

# Page configuration
st.set_page_config(
    page_title="Gestión Unificada",
    page_icon="🎛️",
    layout="wide",
)

# Render the unified entity management interface
UnifiedEntityManager.render_unified_interface(key="unified_manager")
