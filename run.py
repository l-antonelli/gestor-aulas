#!/usr/bin/env python
"""Entry point to run the Streamlit app with correct Python path."""

import sys
import os

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from streamlit.web import cli as stcli
    sys.argv = ["streamlit", "run", "app/main.py", "--server.headless", "true"]
    stcli.main()
