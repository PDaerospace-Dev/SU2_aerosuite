"""Landing page: recent projects, open a project, create a new one."""
from pathlib import Path

from nicegui import ui

from ...engine import project as engine_project
from ...engine.errors import AeroSuiteError
from ...engine.profiles import list_profiles
from ...engine.study import create_study
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


def _kind_card(title: str, text: str, mark: str, on_choose) -> ui.card:
    card = ui.card().classes("w-72 cursor-pointer").mark(mark)
    card.on("click", lambda _: on_choose())
    with card:
        ui.label(title).classes("text-base font-medium")
        ui.label(text).classes("text-xs text-grey-8")
    return card


def _path_row(label: str, mark: str, title: str, mode: str, suffixes=()) -> ui.input:
    with ui.row().classes("w-full items-center no-wrap"):
        box = ui.input(label).classes("grow").mark(mark)

        async def browse() -> None:
            chosen = await pick_path(title, mode=mode, suffixes=suffixes)
            if chosen is not None:
                box.value = str(chosen)

        ui.button("Browse", on_click=browse).props("flat").mark(
            "new-browse" if mark == "new-parent" else f"{mark}-browse")
    return box


def _new_form() -> None:
    ui.label("New project").classes("text-lg")
    profiles, problems = list_profiles()
    for problem in problems:
        ui.label(f"Profile skipped: {problem}").classes("text-warning text-xs").mark("profile-problem")
    state = {"kind": "general"}

    def choose(kind: str) -> None:
        state["kind"] = kind
        general.classes(add="border-2 border-primary" if kind == "general" else "",
                        remove="border-2 border-primary" if kind != "general" else "")
        aircraft.classes(add="border-2 border-primary" if kind == "aircraft" else "",
                         remove="border-2 border-primary" if kind != "aircraft" else "")
        profile.set_visibility(kind == "aircraft")
        use_reference.set_visibility(kind == "general")

    with ui.row().classes("gap-4"):
        general = _kind_card("General case", "One config from a template, edited as text with SU2's "
                             "reference beside it. One case.", "new-kind-general", lambda: choose("general"))
        aircraft = _kind_card("Aircraft study", "Aircraft Aero form with profile defaults, "
                              "placeholders and a Mach/alpha/beta sweep.", "new-kind-aircraft",
                              lambda: choose("aircraft"))
    profile = ui.select({p.id: p.name for p in profiles}, label="Aircraft profile",
                        value=profiles[0].id if profiles else None).classes("w-64").mark("new-profile")
    parent = _path_row("Parent folder", "new-parent", "Choose the parent folder", "folder")
    name = ui.input("Project name").classes("w-full").mark("new-name")
    template = _path_row("Template (.cfg)", "new-template", "Choose the template", "file", (".cfg",))
    use_reference = ui.checkbox("Start from SU2's config_template.cfg").mark("new-use-reference")
    mesh = _path_row("Mesh (.su2, optional)", "new-mesh", "Choose the mesh", "file", (".su2", ".cgns"))
    ui.button("Create", on_click=lambda: create()).mark("new-create")
    error = ui.label("").classes("text-negative text-sm").mark("new-error")
    choose("general")

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
        aircraft_study = state["kind"] == "aircraft"
        if aircraft_study and not profile.value:
            error.text = "Choose an aircraft profile"
            return
        template_text = (template.value or "").strip()
        mesh_text = (mesh.value or "").strip()
        target = Path(parent_text) / name_text
        try:
            create_study(
                target,
                profile_id=profile.value if aircraft_study else None,
                template=Path(template_text) if template_text else None,
                use_reference_template=bool(use_reference.value) and not aircraft_study,
                mesh=Path(mesh_text) if mesh_text else None,
            )
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        _go_to(target)
