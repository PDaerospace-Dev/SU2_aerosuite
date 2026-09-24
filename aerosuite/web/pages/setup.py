"""Setup: mesh, master template and run settings."""
from pathlib import Path
from typing import Callable, Sequence

from nicegui import ui

from ...engine import project as engine_project
from ...engine.cfg import build_cases
from ...engine.errors import ProjectError
from ...engine.jobs.runner import BUNDLED_SWEEP_SCRIPT, is_aerosuite_python, resolve_sweep_python
from ...engine.models import Project
from ...engine.profiles import apply_profile, list_profiles, load_profile, save_profile
from ..fields import text_field
from ..layout import ProjectFrame, open_session
from ..picker import pick_path
from ..session import parse_int

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
            _study_section(frame)
            _mesh_section(frame)
            _template_section(frame)
            _run_section(frame)

        with frame.content:
            ui.label("Setup").classes("text-2xl")
            body()


def _study_section(frame: ProjectFrame) -> None:
    project = frame.session.project
    profiles, problems = list_profiles()
    ui.label("Study").classes("text-lg")
    for problem in problems:
        ui.label(f"Profile skipped: {problem}").classes("text-warning text-xs").mark("setup-profile-problem")
    options = {"": "None (general case)", **{p.id: p.name for p in profiles}}
    if project.profile and project.profile not in options:
        options[project.profile] = f"{project.profile} (not found)"

    def choose(value) -> None:
        message = frame.save(lambda p: setattr(p, "profile", value or None))
        if message:
            ui.notify(message, type="negative")

    with ui.row().classes("w-full items-center no-wrap gap-4"):
        select = ui.select(options, value=project.profile or "", label="Aircraft profile",
                           on_change=lambda e: choose(e.value)).classes("w-64").mark("setup-profile")
        ui.button("Apply profile defaults", on_click=lambda: apply_defaults()).props("flat").mark(
            "setup-apply-profile")
        ui.button("Save as profile…", on_click=lambda: save_as()).props("flat").mark("setup-save-profile")

    def sweep(on: bool) -> None:
        def change(p) -> None:
            p.sweep.enabled = on
            p.cases = build_cases(p)

        message = frame.save(change)
        if message:
            ui.notify(message, type="negative")

    ui.switch("Sweep (Mach / alpha / beta cases)", value=project.sweep.enabled,
              on_change=lambda e: sweep(e.value)).mark("setup-sweep")

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
        with ui.dialog() as dialog, ui.card():
            ui.label(f"Overwrite the settings {profile.name} defines with its defaults?")
            with ui.row():
                ui.button("Apply", on_click=lambda: dialog.submit(True)).mark("confirm-apply")
                ui.button("Cancel", on_click=lambda: dialog.submit(False)).props("flat").mark("confirm-cancel")
        confirmed = await dialog
        dialog.delete()
        if not confirmed:
            return
        message = frame.save(lambda p: apply_profile(frame.session.directory, p, profile))
        ui.notify(message or f"Applied {profile.name} defaults", type="negative" if message else "positive")

    async def save_as() -> None:
        with ui.dialog() as dialog, ui.card().classes("w-96"):
            ui.label("Save this project's template and settings as a profile").classes("text-lg")
            id_box = ui.input("Profile id (letters, digits, - and _)").classes("w-full").mark("profile-id")
            name_box = ui.input("Name").classes("w-full").mark("profile-name")
            description_box = ui.input("Description").classes("w-full").mark("profile-description")
            error = ui.label("").classes("text-negative text-xs").mark("profile-error")
            with ui.row():
                ui.button("Save", on_click=lambda: attempt(False)).mark("profile-save")
                replace = ui.button("Replace existing", on_click=lambda: attempt(True)).mark("profile-replace")
                ui.button("Cancel", on_click=lambda: dialog.submit(None)).props("flat").mark("profile-cancel")
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
) -> None:
    """A path box with Browse and Set; Set applies `apply(project, path)` through the session."""
    with ui.row().classes("w-full items-center no-wrap"):
        field = ui.input(label).classes("grow").mark(f"{mark}-input")

        async def browse() -> None:
            chosen = await pick_path(title, mode="file", suffixes=suffixes)
            if chosen is not None:
                field.value = str(chosen)
                commit()

        ui.button("Browse", on_click=browse).props("flat").mark(f"{mark}-browse")
        ui.button("Set", on_click=lambda: commit()).mark(f"{mark}-set")
    error = ui.label("").classes("text-negative text-xs").mark(f"{mark}-error")

    def commit() -> None:
        text = (field.value or "").strip()
        if not text:
            error.text = "Choose or paste a file"
            return
        message = frame.save(lambda p: apply(p, Path(text)), then=then)
        error.text = message or ""


def _mesh_section(frame: ProjectFrame) -> None:
    @ui.refreshable
    def summary() -> None:
        mesh = frame.session.project.mesh
        ui.label(mesh.path or "No mesh selected").mark("mesh-path")
        markers = ", ".join(mesh.markers) if mesh.markers else "(none found)"
        ui.label(f"Markers: {markers}").classes("text-sm").mark("mesh-markers")

    ui.label("Mesh").classes("text-lg")
    summary()
    _path_setter(
        frame, label="Mesh file (.su2)", mark="mesh", title="Choose the mesh", suffixes=MESH_SUFFIXES,
        apply=lambda p, path: engine_project.set_mesh(p, path), then=summary.refresh,
    )


def _template_section(frame: ProjectFrame) -> None:
    @ui.refreshable
    def summary() -> None:
        present = (frame.session.directory / frame.session.project.template).is_file()
        text = f"{frame.session.project.template} (copied into the project)" if present else "No template yet"
        ui.label(text).mark("template-status")

    ui.label("Master template").classes("text-lg")
    summary()
    _path_setter(
        frame, label="Template (.cfg)", mark="template", title="Choose the master template",
        suffixes=TEMPLATE_SUFFIXES,
        apply=lambda p, path: engine_project.set_template(frame.session.directory, p, path),
        then=summary.refresh,
    )


def _run_section(frame: ProjectFrame) -> None:
    run = frame.session.project.run
    ui.label("Run settings").classes("text-lg")
    text_field(
        "MPI partitions per case", run.partitions,
        lambda text: frame.save(lambda p: setattr(p.run, "partitions", parse_int(text, "Partitions"))),
        mark="partitions",
    )

    @ui.refreshable
    def python_info() -> None:
        resolved = resolve_sweep_python(frame.session.project.run.sweep_python)
        text = f"Runs as: {resolved}"
        if is_aerosuite_python(resolved):
            text += "  ⚠ This is AeroSuite's own Python; SU2 is normally importable only from the system Python."
        ui.label(text).classes("text-xs text-grey-8").mark("sweep-python-info")

    text_field(
        "Python for the sweep script (must import SU2)", run.sweep_python,
        lambda text: frame.save(
            lambda p: setattr(p.run, "sweep_python", text.strip() or "python3"), then=python_info.refresh),
        mark="sweep-python",
    )
    python_info()

    @ui.refreshable
    def script_info() -> None:
        script = frame.session.project.run.sweep_script
        text = script if script else f"bundled {BUNDLED_SWEEP_SCRIPT.name}"
        ui.label(f"Script: {text}").classes("text-xs text-grey-8").mark("sweep-script-info")

    text_field(
        "Sweep script (empty = bundled)", run.sweep_script,
        lambda text: frame.save(lambda p: setattr(p.run, "sweep_script", text.strip()), then=script_info.refresh),
        mark="sweep-script",
    )
    script_info()
