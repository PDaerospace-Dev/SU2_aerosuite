"""Shared page parts: header, project frame (sidebar with badges), outside-change watcher."""
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from nicegui import ui

from ..engine.errors import AeroSuiteError
from .recent import add_recent
from .session import Change, ProjectSession
from .status import STEPS, step_badges

WATCH_SECONDS = 2.0
BADGE_ICONS = {
    "done": ("check_circle", "positive"),
    "attention": ("error", "warning"),
    "todo": ("radio_button_unchecked", "grey-6"),
    "later": ("schedule", "grey-4"),
}
PAGE_OF_STEP = {"setup": "setup", "settings": "settings", "sweep": "sweep", "configs": "sweep"}


def project_url(page: str, directory) -> str:
    return f"/{page}?project={quote(str(directory), safe='')}"


def header() -> None:
    with ui.header().classes("items-center gap-4"):
        ui.link("AeroSuite", "/").classes("text-white text-xl no-underline")


def open_session(project: str) -> Optional[ProjectSession]:
    """Open the project named in the URL, or show why not and return None."""
    if not project:
        header()
        ui.label("No project selected.")
        ui.link("Choose a project", "/")
        return None
    try:
        session = ProjectSession(Path(project))
    except AeroSuiteError as exc:
        header()
        ui.label(f"Error: {exc}").classes("text-negative")
        ui.link("Back to projects", "/")
        return None
    add_recent(session.directory)
    return session


class ProjectFrame:
    """Header, sidebar and content column of a project page."""

    def __init__(self, session: ProjectSession, active: str, on_reload: Callable[[], None]) -> None:
        self.session = session
        self.active = active
        self._on_reload = on_reload
        with ui.header().classes("items-center gap-4"):
            ui.link("AeroSuite", "/").classes("text-white text-xl no-underline")
            self._name = ui.label("").classes("text-lg").mark("project-name")
            ui.label(str(session.directory)).classes("text-xs opacity-80")
        with ui.left_drawer(value=True).classes("bg-grey-1"):
            self._sidebar = ui.column().classes("gap-2")
        self.content = ui.column().classes("w-full p-4 gap-4")
        self.refresh()
        ui.timer(WATCH_SECONDS, self._check_disk)

    def refresh(self) -> None:
        """Redraw the header name and the sidebar badges."""
        self._name.text = self.session.project.name
        badges = step_badges(self.session.directory, self.session.project)
        self._sidebar.clear()
        with self._sidebar:
            for key, label in STEPS:
                badge = badges[key]
                icon, color = BADGE_ICONS[badge]
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.icon(icon, color=color).mark(f"badge-{key}-{badge}")
                    page = PAGE_OF_STEP.get(key)
                    if page is None:
                        ui.label(label).classes("text-grey-5")
                    else:
                        link = ui.link(label, project_url(page, self.session.directory))
                        if key == self.active:
                            link.classes("font-bold")

    def ensure_current(self) -> Optional[str]:
        """Reload from disk if the project changed there since it was last read.

        Callers that write to the project outside of `save` (e.g. Generate, which writes
        configs rather than project.json) must call this first and not proceed on a message:
        the in-memory copy would otherwise be stale, for example after an override was changed
        by the CLI or another tab inside the disk-watch window.
        """
        if not self.session.changed_on_disk():
            # A failed reload left project.json invalid: refuse (the watcher reloads once it is fixed).
            return self.session.refusal()
        reload_error = self._reload_from_disk()
        if reload_error is not None:
            return reload_error
        return "Project changed on disk and was reloaded; enter your change again"

    def save(self, change: Change, then: Optional[Callable[[], None]] = None) -> Optional[str]:
        """Apply and save a change; on success refresh the sidebar and call `then`.

        If the project changed on disk since it was last read, the in-memory copy is stale:
        reload instead of saving over the outside change, and ask the user to redo their edit.
        """
        stale = self.ensure_current()
        if stale is not None:
            return stale
        message = self.session.apply(change)
        if message is None:
            self.refresh()
            if then is not None:
                then()
        return message

    def _check_disk(self) -> None:
        if not self.session.changed_on_disk():
            return
        self._reload_from_disk()

    def _reload_from_disk(self) -> Optional[str]:
        """Reload the session from disk and notify; returns None on success, else the error message."""
        try:
            self.session.reload()
        except AeroSuiteError as exc:
            message = f"Could not reload the project: {exc}"
            ui.notify(message, type="negative")
            return message
        ui.notify("Project changed on disk; reloaded", type="info")
        self.refresh()
        self._on_reload()
        return None
