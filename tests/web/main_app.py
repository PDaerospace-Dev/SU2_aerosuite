"""NiceGUI main file for the simulated-user tests (see [tool.pytest.ini_options] main_file)."""
import os
from pathlib import Path

from nicegui import ui

from aerosuite.web.app import register_pages
from aerosuite.web.fields import text_field
from aerosuite.web.layout import ProjectFrame, open_session
from aerosuite.web.picker import pick_path
from aerosuite.web.session import parse_int

register_pages(Path(os.environ.get("AEROSUITE_WEB_ROOT", ".")))


@ui.page("/_test/base")
async def _test_base_page(project: str = "") -> None:
    """Test-only page exercising ProjectFrame, text_field and pick_path together."""
    session = open_session(project)
    if session is None:
        return
    frame = ProjectFrame(session, "setup", on_reload=lambda: None)
    with frame.content:
        text_field(
            "Partitions",
            session.project.run.partitions,
            lambda t: frame.save(lambda p: setattr(p.run, "partitions", parse_int(t, "Partitions"))),
            mark="t-partitions",
        )
        script_label = ui.label(frame.session.project.run.sweep_script).mark("t-script")

        async def browse() -> None:
            path = await pick_path("Pick", mode="file", suffixes=(".cfg",))
            if path is not None:
                message = frame.save(lambda p: setattr(p.run, "sweep_script", str(path)))
                if message is None:
                    script_label.text = frame.session.project.run.sweep_script

        ui.button("Browse", on_click=browse).mark("t-browse")


from aerosuite.web.reference_panel import reference_panel  # noqa: E402


@ui.page("/_test/reference")
def _test_reference_page() -> None:
    """Test-only page: a reference panel wired to an in-memory config text."""
    state = {"text": "SOLVER= EULER\n", "inserted": []}
    shown = ui.label("").mark("t-inserted")

    def on_insert(option):
        state["inserted"].append(option.key)
        state["text"] += option.line + "\n"
        shown.text = ",".join(state["inserted"])
        return None

    reference_panel(on_insert=on_insert, in_config=lambda: {
        line.split("=")[0].strip() for line in state["text"].splitlines() if "=" in line})


ui.run(reload=False, show=False)
