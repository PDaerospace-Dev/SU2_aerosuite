"""NiceGUI main file for the simulated-user tests (see [tool.pytest.ini_options] main_file)."""
import os
from pathlib import Path

from nicegui import ui

from aerosuite.web.app import register_pages

register_pages(Path(os.environ.get("AEROSUITE_WEB_ROOT", ".")))
ui.run(reload=False, show=False)
