"""Setup: four steps in one card (mesh, config template, study, run settings), each showing what is set, and a panel
on the right that stays in view: the project, what is ready and the next page."""
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator, Sequence

from nicegui import ui

from ...engine import project as engine_project
from ...engine.errors import ProjectError
from ...engine.jobs.runner import BUNDLED_SWEEP_SCRIPT, is_aerosuite_python, resolve_sweep_python
from ...engine.machine import machine
from ...engine.models import Project
from ...engine.profiles import apply_profile, list_profiles, load_profile, save_profile
from ..fields import text_field
from ..layout import ProjectFrame, open_session, project_url
from ..picker import pick_path
from ..session import parse_int
from ..status import visible_steps
from ..sweep_choice import sweep_radio
from ..ui_kit import banner, card, field, hint, primary_button, secondary_button

STEP_TITLES = ("Mesh", "Config template", "Study", "Run settings")

MESH_SUFFIXES = (".su2", ".cgns")
TEMPLATE_SUFFIXES = (".cfg",)


def register() -> None:
    @ui.page("/setup")
    def setup_page(project: str = "") -> None:
        session = open_session(project)
        if session is None:
            return
        frame = ProjectFrame(session, "setup", on_reload=lambda: body.refresh())

        @ui.refreshable
        def body() -> None:
            def panel() -> None:
                side.clear()
                with side:
                    _panel(frame)

            with ui.element("div").classes("as-run w-full"):
                with card(flush=True) as steps:
                    steps.classes("as-steps").mark("setup-steps")
                    with _step(1, STEP_TITLES[0]):
                        _mesh_section(frame, panel)
                    with _step(2, STEP_TITLES[1]):
                        _template_section(frame, panel)
                    with _step(3, STEP_TITLES[2]):
                        _study_section(frame, panel, body.refresh)
                    with _step(4, STEP_TITLES[3]):
                        _run_section(frame)
                side = ui.column().classes("as-run-panel gap-0").mark("setup-panel")
            panel()

        with frame.content:
            body()


@contextmanager
def _step(number: int, title: str) -> Iterator[None]:
    """One row of the steps card: its number, its title, then whatever the step shows."""
    with ui.row().classes("as-setup-step w-full no-wrap"):
        ui.label(str(number)).classes("as-setup-num")
        with ui.column().classes("gap-2 grow min-w-0"):
            ui.label(title).classes("as-card-title")
            yield


def _ready(mark: str, ok: bool, text: str) -> None:
    with ui.row().classes("as-ready no-wrap items-center gap-2 " + ("as-ready-ok" if ok else "as-ready-todo")):
        ui.icon("check_circle" if ok else "error_outline")
        ui.label(text).mark(mark)


def _panel(frame: ProjectFrame) -> None:
    """The project, what is ready, and the page that comes next."""
    project = frame.session.project
    with ui.column().classes("as-run-part w-full gap-1"):
        ui.label("Project").classes("as-run-head")
        ui.label(project.name).classes("as-run-big").mark("setup-project-name")
        ui.label(str(frame.session.directory)).classes("as-mono as-muted").style("word-break: break-all").mark(
            "setup-folder")
    with ui.column().classes("as-run-part w-full gap-2"):
        ui.label("Ready?").classes("as-run-head")
        mesh = project.mesh
        if not mesh.path:
            _ready("ready-mesh", False, "No mesh selected")
        elif not Path(mesh.path).is_file():
            _ready("ready-mesh", False, "Mesh file not found")
        else:
            count = len(mesh.markers)
            _ready("ready-mesh", True, f"Mesh · {count} marker{'' if count == 1 else 's'}")
        present = (frame.session.directory / project.template).is_file()
        _ready("ready-template", present, "Config template" if present else "No template yet")
        count = len(project.cases)
        study = f"Sweep · {count} case{'' if count == 1 else 's'}" if project.sweep.enabled else "Single case"
        _ready("ready-study", True, study + (f" · profile {project.profile}" if project.profile else ""))
    steps = visible_steps(project)
    keys = [key for key, _ in steps]
    following = steps[keys.index("setup") + 1] if "setup" in keys and keys.index("setup") + 1 < len(steps) else None
    if following is not None:
        with ui.column().classes("as-run-part w-full gap-2"):
            ui.label("Next").classes("as-run-head")
            key, label = following
            primary_button(label, icon="arrow_forward",
                           on_click=lambda: ui.navigate.to(project_url(key, frame.session.directory))).classes(
                "w-full").mark("setup-next")
            rest = " → ".join(text for _, text in steps[keys.index("setup") + 2:keys.index("setup") + 4])
            if rest:
                hint(f"then {rest}")


def _study_section(frame: ProjectFrame, changed: Callable[[], None], redraw: Callable[[], None]) -> None:
    project = frame.session.project
    profiles, problems = list_profiles()
    options = {"": "None (general case)", **{p.id: p.name for p in profiles}}
    if project.profile and project.profile not in options:
        options[project.profile] = f"{project.profile} (not found)"

    def choose(value) -> None:
        message = frame.save(lambda p: setattr(p, "profile", value or None), then=changed)
        if message:
            ui.notify(message, type="negative")

    with ui.column().classes("w-full gap-2"):
        for problem in problems:
            banner("warning", f"Profile skipped: {problem}").mark("setup-profile-problem")
        sweep_radio(frame, mark="setup-sweep", then=changed)
        with ui.row().classes("w-full items-center gap-2"):
            select = field(ui.select(options, value=project.profile or "", label="Aircraft profile",
                                     on_change=lambda e: choose(e.value))).classes("w-64").mark("setup-profile")
            secondary_button("Apply profile defaults", on_click=lambda: apply_defaults()).mark("setup-apply-profile")
            secondary_button("Save as profile…", on_click=lambda: save_as()).mark("setup-save-profile")
            ui.link("Manage profiles", "/profiles" + (f"?id={project.profile}" if project.profile else "")).classes(
                "as-hint").mark("setup-manage-profiles")

    async def apply_defaults() -> None:
        profile_id = frame.session.project.profile
        if not profile_id:
            ui.notify("Choose a profile first", type="warning")
            return
        try:
            profile = load_profile(profile_id)
        except ProjectError as exc:
            ui.notify(str(exc), type="negative")
            return
        text = f"Overwrite the settings {profile.name} defines with its defaults?"
        if profile.template is not None:
            text += (f" The template {frame.session.project.template} will be replaced by the profile's "
                     f"{profile.template.name}.")
        with ui.dialog() as dialog, ui.card():
            ui.label(text)
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(False)).mark("confirm-cancel")
                primary_button("Apply", on_click=lambda: dialog.submit(True)).mark("confirm-apply")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        # Copy the profile's template only once the settings/naming change has actually been
        # saved: apply_profile's file copy must not be a side effect of a change that might yet
        # be refused (a stale project.json) or fail validation.
        message = frame.save(lambda p: apply_profile(frame.session.directory, p, profile, copy_template=False))
        if message is None and profile.template is not None:
            # Saved too: set_template renames the project's template, and project.json must name the new file.
            message = frame.save(
                lambda p: engine_project.set_template(frame.session.directory, p, profile.template))
        ui.notify(message or f"Applied {profile.name} defaults", type="negative" if message else "positive")
        if message is None:
            redraw()  # the mesh, template, sweep and run settings may all have changed

    async def save_as() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Save this project's template and settings as a profile").classes("as-dialog-title")
            id_box = field(ui.input("Profile id (letters, digits, - and _)")).classes("w-full").mark("profile-id")
            name_box = field(ui.input("Name")).classes("w-full").mark("profile-name")
            description_box = field(ui.input("Description")).classes("w-full").mark("profile-description")
            error = ui.label("").classes("as-error-text").mark("profile-error")
            with ui.row().classes("w-full justify-end gap-2"):
                secondary_button("Cancel", on_click=lambda: dialog.submit(None)).mark("profile-cancel")
                replace = secondary_button("Replace existing", on_click=lambda: attempt(True)).mark(
                    "profile-replace")
                primary_button("Save", on_click=lambda: attempt(False)).mark("profile-save")
            replace.set_visibility(False)

        def attempt(overwrite: bool) -> None:
            try:
                saved = save_profile(frame.session.directory, frame.session.project,
                                     (id_box.value or "").strip(), name_box.value or "",
                                     description_box.value or "", overwrite=overwrite)
            except ProjectError as exc:
                error.text = str(exc)
                replace.set_visibility("already exists" in str(exc))
                return
            dialog.submit(saved)

        saved = await dialog
        dialog.delete()
        if saved is None:
            return
        # Show the new profile in the dropdown and select it; choose() saves project.profile.
        select.set_options({**select.options, saved.id: saved.name}, value=saved.id)
        if frame.session.project.profile != saved.id:
            choose(saved.id)
        ui.notify(f"Saved profile {saved.name}", type="positive")


def _path_setter(
    frame: ProjectFrame,
    *,
    label: str,
    mark: str,
    title: str,
    suffixes: Sequence[str],
    apply: Callable[[Project, Path], object],
    then: Callable[[], None],
    shown: bool,
) -> ui.column:
    """A path box with Browse and Set; Set applies `apply(project, path)` through the session. Hidden until
    "Change…" unless nothing is chosen yet (`shown`); it hides again once a file is set."""
    with ui.column().classes("w-full gap-1").mark(f"{mark}-setter") as holder:
        with ui.row().classes("w-full items-center no-wrap gap-2"):
            box = field(ui.input(label), mono=True).classes("grow").mark(f"{mark}-input")

            async def browse() -> None:
                chosen = await pick_path(title, mode="file", suffixes=suffixes)
                if chosen is not None:
                    box.value = str(chosen)
                    commit()

            secondary_button("Browse", on_click=browse).mark(f"{mark}-browse")
            secondary_button("Set", on_click=lambda: commit()).mark(f"{mark}-set")
        error = ui.label("").classes("as-error-text").mark(f"{mark}-error")
    holder.set_visibility(shown)

    def commit() -> None:
        text = (box.value or "").strip()
        if not text:
            error.text = "Choose or paste a file"
            return
        message = frame.save(lambda p: apply(p, Path(text)), then=then)
        error.text = message or ""
        if message is None:
            box.value = ""
            holder.set_visibility(False)

    return holder


def _change_button(mark: str, text: str, setter: ui.column) -> None:
    secondary_button(text, on_click=lambda: setter.set_visibility(not setter.visible)).mark(f"{mark}-change")


def _chosen_file(mark: str, state: str, icon: str) -> ui.row:
    """The box that says which file is chosen: green (chosen), amber (gone from disk) or grey (none)."""
    suffix = "" if state == "selected" else f"-{state}"
    with ui.row().classes(f"as-selected{suffix} w-full no-wrap items-start").mark(mark) as box:
        ui.icon(icon).classes("as-selected-icon")
    return box


def _mesh_section(frame: ProjectFrame, changed: Callable[[], None]) -> None:
    holders: dict = {}

    @ui.refreshable
    def summary() -> None:
        mesh = frame.session.project.mesh
        if not mesh.path:
            with _chosen_file("mesh-status", "empty", "radio_button_unchecked"):
                ui.label("No mesh selected").classes("as-muted")
            return
        path = Path(mesh.path)
        exists = path.is_file()
        box = _chosen_file("mesh-status", "selected" if exists else "missing",
                           "check_circle" if exists else "warning")
        with box:
            with ui.column().classes("gap-1 grow min-w-0"):
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(path.name).classes("as-strong").mark("mesh-name")
                    if not exists:
                        ui.label("File not found").classes("as-error-text")
                ui.label(str(path)).classes("as-mono as-muted as-truncate").mark("mesh-path")
                with ui.row().classes("items-center gap-1"):
                    ui.label("Markers").classes("as-label mr-1")
                    if not mesh.markers:
                        ui.label("none found").classes("as-muted").mark("mesh-markers-none")
                    for marker in mesh.markers:
                        ui.label(marker).classes("as-tag as-mono").mark(f"mesh-marker-{marker}")
            _change_button("mesh", "Change…", holders["setter"])

    def after() -> None:
        summary.refresh()
        changed()

    box = ui.column().classes("w-full gap-2")
    holders["setter"] = _path_setter(
        frame, label="Mesh file (.su2)", mark="mesh", title="Choose the mesh", suffixes=MESH_SUFFIXES,
        apply=lambda p, path: engine_project.set_mesh(p, path), then=after,
        shown=not frame.session.project.mesh.path,
    )
    with box:
        summary()


def _template_section(frame: ProjectFrame, changed: Callable[[], None]) -> None:
    holders: dict = {}

    @ui.refreshable
    def summary() -> None:
        present = (frame.session.directory / frame.session.project.template).is_file()
        with _chosen_file("template-status-box", "selected" if present else "empty",
                          "check_circle" if present else "radio_button_unchecked"):
            if present:
                with ui.row().classes("items-center gap-2 grow"):
                    ui.label(frame.session.project.template).classes("as-strong as-mono")
                    ui.label("(copied into the project)").classes("as-muted").mark("template-status")
                _change_button("template", "Replace…", holders["setter"])
            else:
                ui.label("No template yet").classes("as-muted").mark("template-status")

    def after() -> None:
        summary.refresh()
        changed()

    box = ui.column().classes("w-full gap-2")
    holders["setter"] = _path_setter(
        frame, label="Template (.cfg)", mark="template", title="Choose the master template",
        suffixes=TEMPLATE_SUFFIXES,
        apply=lambda p, path: engine_project.set_template(frame.session.directory, p, path),
        then=after, shown=not (frame.session.directory / frame.session.project.template).is_file(),
    )
    with box:
        summary()


def _run_section(frame: ProjectFrame) -> None:
    run = frame.session.project.run

    @ui.refreshable
    def python_info() -> None:
        resolved = resolve_sweep_python(frame.session.project.run.sweep_python)
        text = f"Runs as: {resolved}"
        own = is_aerosuite_python(resolved)
        if own:
            text += "  ⚠ This is AeroSuite's own Python; SU2 is normally importable only from the system Python."
        label = hint(text).mark("sweep-python-info")
        if own:
            label.classes("as-hint-warning")

    @ui.refreshable
    def script_info() -> None:
        script = frame.session.project.run.sweep_script
        text = script if script else f"bundled {BUNDLED_SWEEP_SCRIPT.name}"
        hint(f"Script: {text}").mark("sweep-script-info")

    with ui.column().classes("w-full gap-2").mark("run-settings"):
        with ui.element("div").classes("as-grid-3"):
            with ui.column().classes("gap-1"):
                text_field(
                    "MPI partitions per case", run.partitions,
                    lambda text: frame.save(lambda p: setattr(p.run, "partitions", parse_int(text, "Partitions"))),
                    mark="partitions",
                )
                here = machine()
                hint(f"This machine: {here.cores} cores, about {here.free_cores} free now").mark("partitions-machine")
        # Rarely changed, so folded away -- unless the sweep would run under the wrong Python.
        wrong_python = is_aerosuite_python(resolve_sweep_python(run.sweep_python))
        with ui.expansion("Advanced · sweep Python and script", value=wrong_python).classes(
                "as-expansion w-full").mark("run-advanced"):
            with ui.element("div").classes("as-grid-2"):
                with ui.column().classes("gap-1"):
                    text_field(
                        "Python for the sweep script (must import SU2)", run.sweep_python,
                        lambda text: frame.save(
                            lambda p: setattr(p.run, "sweep_python", text.strip() or "python3"),
                            then=python_info.refresh),
                        mark="sweep-python", mono=True,
                    )
                    python_info()
                with ui.column().classes("gap-1"):
                    text_field(
                        "Sweep script (empty = bundled)", run.sweep_script,
                        lambda text: frame.save(lambda p: setattr(p.run, "sweep_script", text.strip()),
                                                then=script_info.refresh),
                        mark="sweep-script", mono=True,
                    )
                    script_info()
