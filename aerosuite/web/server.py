"""Start the NiceGUI server for `aerosuite serve`."""
from pathlib import Path

from nicegui import ui

from .app import register_pages


def run_server(root: Path, host: str, port: int) -> None:
    register_pages(root)
    ui.run(host=host, port=port, reload=False, show=False, title="AeroSuite")
