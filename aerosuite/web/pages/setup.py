"""Setup: mesh, master template and run settings."""
from nicegui import ui

from ..layout import ProjectFrame, open_session


def register() -> None:
    @ui.page("/setup")
    def setup_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "setup", on_reload=lambda: None)
        with frame.content:
            ui.label("Setup").classes("text-2xl")
