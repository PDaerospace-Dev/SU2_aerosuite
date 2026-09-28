"""Shared page parts: the top bar, the project frame (collapsible sidebar, breadcrumbs with the page's
actions slot, job indicator, project switcher) and the outside-change watcher."""
import re
import zlib
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.store import active_lock
from .guide import app_version, web_ui_guide
from .calc_panel import CalcPanel
from .jobs import WATCHER, job_progress
from .log_panel import LogPanel
from .recent import add_recent, load_recent
from .session import Change, ProjectSession
from .status import STEPS, project_kind, step_badges, visible_steps
from .theme import BADGE_COLORS, TOGGLE_SIDEBAR, apply_theme
from .ui_kit import banner, status_dot

WATCH_SECONDS = 2.0
PAGE_OF_STEP = {"setup": "setup", "config": "config", "aircraft": "aircraft", "sweep": "sweep", "run": "run",
                "monitor": "monitor"}
PAGE_TITLES = dict(STEPS)
STEP_ICONS = {"setup": "tune", "config": "description", "aircraft": "flight", "sweep": "grid_on",
              "run": "play_arrow", "monitor": "show_chart", "results": "bar_chart"}

RELOADED_MESSAGE = "Project changed on disk; reloaded"
STALE_MESSAGE = "Project changed on disk and was reloaded — your last change was not saved; enter it again"


def project_url(page: str, directory) -> str:
    return f"/{page}?project={quote(str(directory), safe='')}"


def calculators_url(directory=None, calc: Optional[str] = None) -> str:
    query = []
    if directory is not None:
        query.append(f"project={quote(str(directory), safe='')}")
    if calc:
        query.append(f"calc={quote(calc, safe='')}")
    return "/calculators" + ("?" + "&".join(query) if query else "")


def _calculators_button(frame=None) -> None:
    """The top bar's Calculators button: it opens the calculators over the page, from the right."""
    panel = CalcPanel(frame)
    ui.button("Calculators", icon="calculate", color=None, on_click=panel.toggle).props(
        "flat dense no-caps").classes("as-topbar-icon as-topbar-labelled").mark("calculators")


def initials(name: str) -> str:
    """Two letters for the switcher badge: the first letters of the first two words, else the first two."""
    words = [word for word in re.split(r"[\s_\-.]+", name) if word]
    if not words:
        return "?"
    if len(words) == 1:
        return words[0][:2].upper()
    return (words[0][0] + words[1][0]).upper()


def badge_color(name: str) -> str:
    return BADGE_COLORS[zlib.crc32(name.encode("utf-8")) % len(BADGE_COLORS)]


def _brand() -> None:
    with ui.link(target="/").classes("as-brand row"):
        with ui.element("span").classes("as-logo-mark"):
            ui.icon("flight", size="18px")
        ui.label("AeroSuite").classes("as-logo-text")


def _help_button() -> None:
    """A help icon with the version and "Web UI guide" (the README's web UI section in a dialog)."""
    # Built outside the menu: a dialog created inside a menu item would be unmounted as the menu closes.
    with ui.dialog() as dialog, ui.card().classes("w-[48rem] max-w-full"):
        with ui.row().classes("w-full items-center no-wrap"):
            ui.label("Web UI guide").classes("as-dialog-title grow")
            ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark("guide-close")
        guide = ui.markdown("").classes("w-full").mark("guide-text")

    def show_guide() -> None:
        guide.set_content(web_ui_guide())
        dialog.open()

    with ui.button(icon="help_outline", color=None).props("flat dense").classes(
            "as-topbar-icon as-round").mark("help"):
        with ui.menu().mark("help-menu"):
            ui.menu_item(f"AeroSuite {app_version()}").props("disable").mark("help-version")
            ui.menu_item("Web UI guide", on_click=show_guide).mark("help-guide")


def header() -> None:
    """The top bar of pages outside a project (Projects, or a project that cannot be opened)."""
    apply_theme()
    with ui.row().classes("as-topbar w-full"):
        _brand()
        ui.space()
        _calculators_button()
        _help_button()


def open_session(project: str) -> Optional[ProjectSession]:
    """Open the project named in the URL, or show why not and return None."""
    if not project:
        header()
        with ui.column().classes("as-page w-full"):
            ui.label("No project selected.")
            ui.link("Choose a project", "/")
        return None
    try:
        session = ProjectSession(Path(project))
    except AeroSuiteError as exc:
        header()
        with ui.column().classes("as-page w-full"):
            banner("error", f"Error: {exc}")
            ui.link("Back to projects", "/")
        return None
    add_recent(session.directory)
    return session


def _toggle_sidebar() -> None:
    ui.run_javascript(TOGGLE_SIDEBAR)  # fire and forget: the browser flips and remembers it


class ProjectFrame:
    """Top bar, sidebar, breadcrumb row and content column of a project page.

    `actions` (right of the breadcrumbs) holds the page's buttons, at most one of them primary;
    `content` holds its cards.
    """

    def __init__(self, session: ProjectSession, active: str, on_reload: Callable[[], None]) -> None:
        self.session = session
        self.active = active
        self._on_reload = on_reload
        apply_theme()
        self._top_bar()
        with ui.row().classes("as-body w-full"):
            self._sidebar = ui.column().classes("as-sidebar").mark("sidebar")
            with ui.column().classes("as-main"):
                with ui.row().classes("as-crumbs w-full"):
                    ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
                    ui.label("›").classes("as-crumb-sep")
                    self._crumb_project = ui.link("", project_url("setup", session.directory)).classes(
                        "as-crumb-link as-crumb-project as-truncate").mark("crumb-project")
                    ui.label("›").classes("as-crumb-sep")
                    ui.label(PAGE_TITLES.get(active, active.title())).classes("as-crumb-current").mark("crumb-page")
                    ui.space()
                    self.actions = ui.row().classes("items-center gap-2 no-wrap").mark("page-actions")
                self.content = ui.column().classes("as-content w-full")
        self.log = LogPanel(self)
        self.refresh()
        ui.timer(WATCH_SECONDS, self._tick)

    def _top_bar(self) -> None:
        with ui.row().classes("as-topbar w-full"):
            _brand()
            with ui.button(on_click=_toggle_sidebar, color=None).props("flat dense").classes(
                    "as-topbar-icon").mark("sidebar-toggle"):
                ui.icon("keyboard_double_arrow_left").classes("as-when-full")
                ui.icon("keyboard_double_arrow_right").classes("as-when-mini")
            ui.space()
            with ui.row().classes("as-topbar-control as-job").mark("job-indicator") as self._job:
                ui.element("span").classes("as-job-dot")
                ui.label("Running")
                self._job_text = ui.label("").classes("as-topbar-muted as-job-text as-truncate").mark("job-progress")
                with ui.element("span").classes("as-job-bar"):
                    self._job_fill = ui.element("div").classes("as-job-fill").style("width: 0%")
            self._job.on("click", lambda: self.log.open())  # tail the running job's log
            self._job.set_visibility(False)
            _calculators_button(self)
            _help_button()
            with ui.row().classes("as-topbar-control as-switcher").mark("project-switcher"):
                self._initials = ui.label("").classes("as-initials")
                with ui.column().classes("gap-0 min-w-0"):
                    self._name = ui.label("").classes("as-switcher-name as-truncate").mark("project-name")
                    self._kind = ui.label("").classes("as-switcher-kind as-topbar-muted").mark("project-kind")
                ui.icon("expand_more").classes("as-topbar-muted")
                with ui.menu().mark("project-menu"):
                    ui.menu_item("All projects", on_click=lambda: ui.navigate.to("/")).mark("menu-all-projects")
                    ui.menu_item("Profiles", on_click=lambda: ui.navigate.to("/profiles")).mark("menu-profiles")
                    here = Path(self.session.directory).resolve()
                    for directory in load_recent():
                        if directory.resolve() != here:
                            ui.menu_item(directory.name, on_click=lambda d=directory: ui.navigate.to(
                                project_url("setup", d))).mark(f"menu-recent-{directory.name}")

    def refresh(self) -> None:
        """Redraw the project name, the sidebar's steps and badges, and the job indicator."""
        project = self.session.project
        self._name.text = project.name
        self._kind.text = project_kind(project)
        self._initials.text = initials(project.name)
        self._initials.style(f"background: {badge_color(project.name)}")
        self._crumb_project.text = project.name
        badges = step_badges(self.session.directory, project)
        self._sidebar.clear()
        with self._sidebar:
            for key, label in visible_steps(project):
                self._step(key, label, badges[key])
        self._update_job()

    def _step(self, key: str, label: str, badge: str) -> None:
        page = PAGE_OF_STEP.get(key)
        if page is None:
            item = ui.row().classes("as-step as-step-later")
        else:
            item = ui.link(target=project_url(page, self.session.directory)).classes("as-step row")
            if key == self.active:
                item.classes("as-step-current")
        item.mark(f"step-{key}")
        with item:
            ui.icon(STEP_ICONS[key], size="20px")
            status_dot(badge).mark(f"badge-{key}-{badge}")
            ui.label(label).classes("as-step-name")
            ui.tooltip(label).classes("as-step-tip")

    def _tick(self) -> None:
        self._check_disk()
        self._update_job()

    def _update_job(self) -> None:
        """Show the job indicator while a job of this project runs (started here, in another tab or the CLI).

        With nothing shown only the cheap lock check runs; job state is read only while a job is active.
        """
        try:
            if not self._job.visible and active_lock(self.session.directory) is None:
                return
            progress = job_progress(WATCHER.state(self.session.directory, self.session.project))
        except (AeroSuiteError, OSError):
            progress = None  # a broken job record must never break navigation
        if progress is None:
            self._job.set_visibility(False)
            return
        self._job_text.set_text(progress.text)
        self._job_fill.style(f"width: {progress.percent}%")
        self._job.set_visibility(True)

    def ensure_current(self, notify: bool = True) -> Optional[str]:
        """Reload from disk if the project changed there since it was last read.

        Returns None when the in-memory copy is current, else why the caller must not proceed.
        Callers that write to the project outside of `save` (e.g. Generate, which writes
        configs rather than project.json) must call this first and not proceed on a message:
        the in-memory copy would otherwise be stale, for example after an override was changed
        by the CLI or another tab inside the disk-watch window.

        A reload rebuilds the page on the next tick, which deletes whatever label would show the
        returned message, so the reload is announced by a toast that carries the instruction.
        With `notify=False` no toast is shown: the caller reports the returned message itself.
        """
        if not self.session.changed_on_disk():
            # A failed reload left project.json invalid: refuse (the watcher reloads once it is fixed).
            return self.session.refusal()
        if not self._reload_from_disk(STALE_MESSAGE if notify else None, "warning", notify_failure=notify):
            return self.session.refusal()
        return STALE_MESSAGE

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
        self._reload_from_disk(RELOADED_MESSAGE, "info")

    def _reload_from_disk(self, toast: Optional[str], toast_type: str, *, notify_failure: bool = True) -> bool:
        """Reload the session from disk, notify `toast` (if any) and rebuild; False if the file is invalid."""
        try:
            self.session.reload()
        except AeroSuiteError as exc:
            if notify_failure:
                ui.notify(f"Could not reload the project: {exc}", type="negative")
            return False
        if toast is not None:
            ui.notify(toast, type=toast_type)
        self.refresh()
        self._on_reload()
        return True
