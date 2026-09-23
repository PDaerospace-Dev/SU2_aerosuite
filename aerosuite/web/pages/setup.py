"""Setup: mesh, master template and run settings."""
from pathlib import Path
from typing import Callable, Sequence

from nicegui import ui

from ...engine import project as engine_project
from ...engine.jobs.runner import BUNDLED_SWEEP_SCRIPT, is_aerosuite_python, resolve_sweep_python
from ...engine.models import Project
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
            _mesh_section(frame)
            _template_section(frame)
            _run_section(frame)

        with frame.content:
            ui.label("Setup").classes("text-2xl")
            body()


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
