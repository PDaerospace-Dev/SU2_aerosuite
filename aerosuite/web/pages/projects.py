"""Landing page: recent projects, open a project, create a new one."""
from pathlib import Path

from nicegui import ui

from ...engine import project as engine_project
from ...engine.errors import AeroSuiteError
from ...engine.imported import create_imported_study, scan
from ...engine.naming import format_value
from ...engine.profiles import list_profiles
from ...engine.study import create_study
from ..layout import header, project_url
from ..recent import add_recent, recent_projects
from ..ui_kit import (banner, card, card_head, field, hint, ok_line, path_field, pill, primary_button, secondary_button,
                      table, td, th, warning_group)


def register() -> None:
    @ui.page("/")
    def projects_page() -> None:
        header()
        with ui.column().classes("as-page w-full"):
            with ui.row().classes("as-crumbs w-full"):
                ui.label("Projects").classes("as-crumb-current")
                ui.space()
                secondary_button("Profiles", on_click=lambda: ui.navigate.to("/profiles"), icon="badge").mark(
                    "projects-profiles")
            with ui.element("div").classes("as-columns as-columns-projects"):
                with ui.column().classes("gap-4 w-full"):
                    _recent_list()
                with ui.column().classes("gap-4 w-full"):
                    _open_form()
                    _import_form()
                    _new_form()


PREVIEW_ROWS = 10


def _go_to(directory: Path) -> None:
    add_recent(directory)
    ui.navigate.to(project_url("setup", Path(directory).resolve()))


def _recent_list() -> None:
    with card(flush=True):
        card_head("Recent projects")
        recent = recent_projects()
        if not recent:
            ui.label("No recent projects yet.").classes("as-muted px-4 pb-4").mark("recent-empty")
            return
        for item in recent:
            with ui.link(target=project_url("setup", item.directory)).classes("as-recent-row").mark(
                    f"recent-{item.directory.name}"):
                with ui.column().classes("gap-0 grow min-w-0"):
                    ui.label(item.name).classes("as-strong as-truncate")
                    ui.label(str(item.directory)).classes("as-mono as-muted as-truncate")
                if item.kind:
                    ui.label(item.kind).classes("as-tag")
                if item.latest:
                    pill(item.latest)


def _open_form() -> None:
    with card("Open a project"):
        path = path_field("Project folder", mark="open-path", browse_mark="open-browse",
                          title="Open a project folder", mode="folder")
        error = ui.label("").classes("as-error-text").mark("open-error")
        with ui.row().classes("w-full justify-end"):
            secondary_button("Open", on_click=lambda: open_it()).mark("open-button")

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


def _kind_card(title: str, text: str, mark: str, on_choose) -> ui.column:
    tile = ui.column().classes("as-choice-tile").mark(mark)
    tile.on("click", lambda _: on_choose())
    with tile:
        ui.label(title).classes("as-strong")
        ui.label(text).classes("as-muted")
    return tile


def _new_form() -> None:
    profiles, problems = list_profiles()
    state = {"kind": "general"}

    def choose(kind: str) -> None:
        state["kind"] = kind
        for tile, name in ((general, "general"), (aircraft, "aircraft")):
            if name == kind:
                tile.classes(add="as-choice-selected")
            else:
                tile.classes(remove="as-choice-selected")
        profile.set_visibility(kind == "aircraft")
        use_reference.set_visibility(kind == "general")

    with card("New project"):
        for problem in problems:
            banner("warning", f"Profile skipped: {problem}").mark("profile-problem")
        with ui.element("div").classes("as-grid-2"):
            general = _kind_card("General case", "One config from a template, edited as text with SU2's "
                                 "reference beside it. One case.", "new-kind-general", lambda: choose("general"))
            aircraft = _kind_card("Aircraft study", "Aircraft Aero form with profile defaults, "
                                  "placeholders and a Mach/alpha/beta sweep.", "new-kind-aircraft",
                                  lambda: choose("aircraft"))
        profile = field(ui.select({p.id: p.name for p in profiles}, label="Aircraft profile",
                                  value=profiles[0].id if profiles else None)).classes("w-full").mark("new-profile")
        parent = path_field("Parent folder", mark="new-parent", browse_mark="new-browse",
                            title="Choose the parent folder", mode="folder")
        name = field(ui.input("Project name")).classes("w-full").mark("new-name")
        template = path_field("Template (.cfg)", mark="new-template", browse_mark="new-template-browse",
                              title="Choose the template", mode="file", suffixes=(".cfg",))
        use_reference = ui.checkbox("Start from SU2's config_template.cfg").mark("new-use-reference")
        mesh = path_field("Mesh (.su2, optional)", mark="new-mesh", browse_mark="new-mesh-browse",
                          title="Choose the mesh", mode="file", suffixes=(".su2", ".cgns"))
        error = ui.label("").classes("as-error-text").mark("new-error")
        with ui.row().classes("w-full justify-end"):
            primary_button("Create project", on_click=lambda: create()).mark("new-create")
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


def _import_form() -> None:
    """Existing SU2 runs, one folder per case (its .cfg and history), read into a read-only study."""
    with card("Import SU2 runs", "Read existing runs: one folder per case with its .cfg and history"):
        source = path_field("Runs folder", mark="import-source", browse_mark="import-browse",
                            title="Choose the folder that holds the case folders", mode="folder")
        with ui.element("div").classes("as-grid-2"):
            parent = path_field("Parent folder of the new study", mark="import-parent", browse_mark="import-pbrowse",
                                title="Choose the parent folder", mode="folder")
            name = field(ui.input("Study name")).classes("w-full").mark("import-name")
        error = ui.label("").classes("as-error-text").mark("import-error")
        with ui.row().classes("w-full justify-end"):
            secondary_button("Scan", icon="search", on_click=lambda: preview()).mark("import-scan")
        box = ui.column().classes("w-full gap-2").mark("import-preview")

    def preview() -> None:
        box.clear()
        error.text = ""
        text = (source.value or "").strip()
        if not text:
            error.text = "Choose the runs folder"
            return
        try:
            result = scan(Path(text))
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        if not name.value:
            name.value = Path(text).name
        if not parent.value:
            parent.value = str(Path(text).resolve().parent)
        with box:
            if not result.cases:
                banner("warning", "No case folders with a history file and a Mach and α (from a .cfg or the name)")
            else:
                ok_line(f"{len(result.cases)} case{'s' if len(result.cases) != 1 else ''} found in {Path(text).name}")
                with ui.element("div").classes("as-table-scroll w-full"):
                    with table("minmax(11rem, 1.8fr) repeat(5, minmax(3.2rem, .5fr)) minmax(4rem, .6fr)"):
                        for heading in ("Case folder", "Mach", "α", "β", "Alt (km)", "T (K)", "Config"):
                            th(heading)
                        for case in result.cases[:PREVIEW_ROWS]:
                            where = f"{case.group} / {case.folder.name}" if case.group else case.folder.name
                            td(where, mono=True).mark(f"import-row-{case.name}")
                            for value in (case.mach, case.alpha, case.beta, case.altitude_km, case.temperature_K):
                                td("—" if value is None else format_value(value))
                            td(case.base or "—")
                if len(result.cases) > PREVIEW_ROWS:
                    hint(f"… and {len(result.cases) - PREVIEW_ROWS} more")
            if result.warnings:
                warning_group(result.warnings, mark="import-warnings")
            if result.skipped:
                count = len(result.skipped)
                warning_group([f"{s.name}: {s.reason}" for s in result.skipped], mark="import-skipped",
                              label=f"{count} folder{'s' if count != 1 else ''} skipped")
            if result.cases:
                with ui.row().classes("w-full justify-end"):
                    primary_button(f"Import {len(result.cases)} case{'s' if len(result.cases) != 1 else ''}",
                                   icon="download_done", on_click=lambda: create(Path(text))).mark("import-create")

    def create(runs: Path) -> None:
        parent_text, name_text = (parent.value or "").strip(), (name.value or "").strip()
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
            create_imported_study(target, runs, name=name_text)
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        add_recent(target)
        ui.navigate.to(project_url("results", target.resolve()))
