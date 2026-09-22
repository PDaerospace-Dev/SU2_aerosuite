"""Landing page."""
from nicegui import ui


def register() -> None:
    @ui.page("/")
    def projects_page() -> None:
        ui.label("AeroSuite").classes("text-2xl")
