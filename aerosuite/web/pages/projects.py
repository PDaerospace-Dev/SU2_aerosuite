"""Landing page: recent projects, open a project, create a new one."""
from pathlib import Path

from nicegui import ui

from ...engine import project as engine_project
from ...engine.errors import AeroSuiteError
from ..layout import header, project_url
from ..picker import pick_path
from ..recent import add_recent, load_recent


def register() -> None:
    @ui.page("/")
    def projects_page() -> None:
        header()
        with ui.column().classes("w-full max-w-3xl mx-auto p-4 gap-6"):
            ui.label("Projects").classes("text-2xl")
            _recent_list()
            _open_form()
            _new_form()


def _go_to(directory: Path) -> None:
    add_recent(directory)
    ui.navigate.to(project_url("setup", Path(directory).resolve()))


def _recent_list() -> None:
    ui.label("Recent").classes("text-lg")
    recent = load_recent()
    if not recent:
        ui.label("No recent projects yet.").classes("text-grey-7").mark("recent-empty")
        return
    for directory in recent:
        with ui.row().classes("items-baseline gap-3"):
            ui.link(directory.name, project_url("setup", directory)).mark(f"recent-{directory.name}")
            ui.label(str(directory)).classes("text-xs text-grey-7")


def _open_form() -> None:
    ui.label("Open a project").classes("text-lg")
    with ui.row().classes("w-full items-center no-wrap"):
        path = ui.input("Project folder").classes("grow").mark("open-path")

        async def browse() -> None:
            chosen = await pick_path("Open a project folder", mode="folder")
            if chosen is not None:
                path.value = str(chosen)

        ui.button("Browse", on_click=browse).props("flat").mark("open-browse")
        ui.button("Open", on_click=lambda: open_it()).mark("open-button")
    error = ui.label("").classes("text-negative text-sm").mark("open-error")

    def open_it() -> None:
        text = (path.value or "").strip()
        if not text:
            error.text = "Choose or paste a project folder"
            return
        try:
            engine_project.open_project(Path(text))
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        _go_to(Path(text))


def _is_plain_name(name: str) -> bool:
    """True when `parent / name` is a folder directly inside `parent` (not ., .., a drive or a path)."""
    if name in {".", ".."} or any(sep in name for sep in "/\\"):
        return False
    return Path(name).name == name and not Path(name).anchor  # anchor catches "C:x" on Windows


def _new_form() -> None:
    ui.label("New project").classes("text-lg")
    with ui.row().classes("w-full items-center no-wrap"):
        parent = ui.input("Parent folder").classes("grow").mark("new-parent")

        async def browse() -> None:
            chosen = await pick_path("Choose the parent folder", mode="folder")
            if chosen is not None:
                parent.value = str(chosen)

        ui.button("Browse", on_click=browse).props("flat").mark("new-browse")
    name = ui.input("Project name").classes("w-full").mark("new-name")
    ui.button("Create", on_click=lambda: create()).mark("new-create")
    error = ui.label("").classes("text-negative text-sm").mark("new-error")

    def create() -> None:
        parent_text = (parent.value or "").strip()
        name_text = (name.value or "").strip()
        if not parent_text or not name_text:
            error.text = "Choose a parent folder and a name"
            return
        if not _is_plain_name(name_text):
            error.text = "Choose a plain folder name (no '.', '..', drive or separators)"
            return
        if not Path(parent_text).is_dir():
            error.text = f"Parent folder not found: {parent_text}"
            return
        target = Path(parent_text) / name_text
        try:
            engine_project.create_project(target)
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        _go_to(target)
