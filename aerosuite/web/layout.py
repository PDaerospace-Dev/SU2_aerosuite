"""Shared page parts: the top bar (brand, search, Run matrix, Cluster, the project, the ⚙ menu), the project frame
(collapsible sidebar whose Run step shows a running job, breadcrumbs with the page's actions slot) and the
outside-change watcher."""
import re
import zlib
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import quote

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.store import active_lock
from .calc_panel import CalcPanel
from .command_bar import Command, CommandBar
from .guide import app_version, guide_groups, guide_sections, search_sections, section_for
from .jobs import WATCHER, job_progress
from .log_panel import LogPanel
from .paraview_menu import ParaViewMenu
from .recent import add_recent, load_recent
from .session import Change, ProjectSession
from .status import STEPS, project_kind, step_badges, visible_steps
from .theme import BADGE_COLORS, TOGGLE_SIDEBAR, apply_theme
from .ui_kit import banner, status_dot

WATCH_SECONDS = 2.0
PAGE_OF_STEP = {"setup": "setup", "config": "config", "aircraft": "aircraft", "sweep": "sweep", "run": "run",
                "monitor": "monitor", "results": "results"}
PAGE_TITLES = dict(STEPS)
IMPORTED_PAGES = ("results", "monitor")  # the pages of an imported (read-only) study
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


def _cluster_button() -> None:
    """The top bar's Cluster button: a dot for the cluster's health and the number of your running jobs."""
    from . import slurm_watch
    from .cluster_view import cluster_status, running_count

    if not slurm_watch.slurm_available():
        return
    watch = slurm_watch.WATCH
    target, current = "/cluster", ""
    try:  # remember this page, so the Cluster page's Close comes back here
        url = ui.context.client.request.url
        here = url.path + (f"?{url.query}" if url.query else "")
        target = here if url.path == "/cluster" else f"/cluster?back={quote(here, safe='')}"
        current = " as-topbar-link-on" if url.path == "/cluster" else ""
    except (RuntimeError, AttributeError):
        pass
    with ui.link(target=target).classes("as-topbar-link row" + current).mark("cluster"):
        ui.icon("dns", size="18px")
        ui.label("Cluster").classes("as-topbar-label")
        dot = ui.element("span").classes("as-cluster-dot as-dot-grey").mark("cluster-dot")
        count = ui.label("").classes("as-cluster-count").mark("cluster-count")
    watch.show_cluster()
    ui.context.client.on_delete(watch.hide_cluster)  # not on_disconnect: a brief socket drop reconnects

    shown: list = [None]

    def update() -> None:
        if dot.is_deleted:
            return
        tone, tip = cluster_status(watch.snapshot, watch.cluster)
        running = running_count(watch.snapshot, watch.user)
        if (tone, tip, running) == shown[0]:
            return  # nothing to say: the timer fires every 2 s, in every tab, and each update is a message
        shown[0] = (tone, tip, running)
        dot.classes(replace=f"as-cluster-dot as-dot-{tone}")
        dot.props["title"] = tip
        dot.update()
        count.text = str(running) if running else ""

    update()
    ui.timer(2.0, update)


def _tracker_link(here: bool) -> None:
    """Run matrix in the top bar: a place of its own, for every project's workbooks."""
    with ui.link(target="/tracker").classes("as-topbar-link row" + (" as-topbar-link-on" if here else "")).mark(
            "topbar-tracker"):
        ui.icon("table_view", size="18px")
        ui.label("Run matrix").classes("as-topbar-label")


class Guide:
    """The Web UI guide (docs/WEB_UI.md) in a dialog: its sections listed on the left, opened on `page`'s section,
    or the one asked for. Built at the page's top level: a dialog made inside a menu would close with it."""

    def __init__(self, page: str = "") -> None:
        self.page = page
        self._build()

    def _build(self) -> None:
        page = self.page
        with ui.dialog() as dialog, ui.card().classes("as-guide"):
            with ui.row().classes("as-guide-head w-full"):
                ui.icon("menu_book", size="20px").classes("as-guide-head-icon")
                ui.label("Web UI guide").classes("as-dialog-title")
                ui.label(f"AeroSuite {app_version()}").classes("as-muted")
                ui.space()
                ui.button(icon="close", on_click=dialog.close, color=None).props("flat round dense").mark(
                    "guide-close")
            with ui.row().classes("as-guide-body w-full"):
                with ui.column().classes("as-guide-side"):
                    search = ui.input(placeholder="Search the guide").props("dense outlined clearable").classes(
                        "as-guide-search w-full").mark("guide-search")
                    nav = ui.column().classes("as-guide-nav").mark("guide-nav")
                with ui.column().classes("as-guide-page") as page_area:
                    title = ui.label("").classes("as-guide-title").mark("guide-title")
                    guide = ui.markdown("").classes("as-guide-text w-full").mark("guide-text")

        sections: list[tuple[str, str]] = []
        links: list = []

        def show(index: int) -> None:
            title.text = sections[index][0]
            guide.set_content(sections[index][1])
            for i, link in enumerate(links):
                if i == index:
                    link.classes(add="as-guide-current")
                else:
                    link.classes(remove="as-guide-current")
            page_area.run_method("scrollTo", 0, 0)

        def filter_links(query) -> None:
            """Only the sections that mention every word typed; a group's name stays while one of its sections
            does."""
            found = set(search_sections(sections, query or ""))
            for i, link in enumerate(links):
                link.set_visibility(i in found)
            for heading, (start, end) in heads:
                heading.set_visibility(any(i in found for i in range(start, end)))
            none.set_visibility(not found)

        def show_guide(index: Optional[int] = None) -> None:
            sections[:] = guide_sections()
            starts = {start: name for name, start in guide_groups()}
            nav.clear()
            links.clear()
            heads.clear()
            with nav:
                bounds = sorted(starts) + [len(sections)]
                for i, (name, _) in enumerate(sections):
                    if i in starts:
                        end = next(bound for bound in bounds if bound > i)
                        heads.append((ui.label(starts[i]).classes("as-guide-group"), (i, end)))
                    links.append(ui.button(name, on_click=lambda i=i: show(i), color=None).props(
                        "flat dense no-caps align=left").classes("as-guide-link").mark(f"guide-link-{i}"))
                nonlocal none
                none = ui.label("No section mentions that").classes("as-muted as-guide-none").mark("guide-none")
            search.value = ""
            filter_links("")
            show(section_for(page, [name for name, _ in sections]) if index is None else index)
            dialog.open()

        heads: list = []
        none = None
        search.on_value_change(lambda e: filter_links(e.value))

        self.sections, self.show = sections, show_guide


def _app_menu(guide: Guide) -> None:
    """⚙ at the right end: what belongs to AeroSuite, not to a project."""
    with ui.button(icon="settings", color=None).props('flat dense aria-label="AeroSuite menu"').classes(
            "as-topbar-icon as-round").mark("app-menu"):
        with ui.menu().mark("app-menu-items"):
            ui.menu_item("Settings", on_click=lambda: ui.navigate.to("/settings")).mark("menu-settings")
            ui.menu_item("Profiles", on_click=lambda: ui.navigate.to("/profiles")).mark("menu-profiles")
            ui.menu_item("Web UI guide", on_click=lambda: guide.show()).mark("menu-guide")
            ui.separator()
            ui.menu_item(f"AeroSuite {app_version()}").props("disable").mark("menu-version")


def _shell_commands(guide: Guide, panel: CalcPanel, frame: Optional["ProjectFrame"] = None) -> list[Command]:
    """What the search finds: the places, the calculators, the recent projects, the run-matrix sheets, the guide;
    in a project also its steps, its job's log, its cases and its flow files."""
    from ..engine.tracker_links import load_tracker
    from . import slurm_watch
    from .calculators import calculators
    from .pages.tracker_coverage import coverage_url

    go = ui.navigate.to
    commands = [Command("projects", "Go to", "Projects", "folder_open", lambda: go("/"), words="all home"),
                Command("tracker", "Go to", "Run matrix", "table_view", lambda: go("/tracker"),
                        words="tracker workbook excel sheets status")]
    if slurm_watch.slurm_available():
        commands.append(Command("cluster", "Go to", "Cluster", "dns", lambda: go("/cluster"),
                                words="slurm nodes queue jobs"))
    commands += [Command("settings", "Go to", "Settings", "settings", lambda: go("/settings"),
                         words="backend slurm su2 preferences"),
                 Command("profiles", "Go to", "Profiles", "tune", lambda: go("/profiles"), words="aircraft defaults"),
                 Command("calculators", "Tools", "Calculators", "calculate", lambda: panel.open(),
                         words="calc")]
    commands += [Command(f"calc-{calc.key}", "Tools", calc.title, "calculate",
                         lambda k=calc.key: panel.open(k), hint=calc.description, words="calculator")
                 for calc in calculators()]
    here = Path(frame.session.directory).resolve() if frame else None
    for directory in load_recent():
        if directory.resolve() != here:
            commands.append(Command(f"project-{directory.name}", "Projects", directory.name, "science",
                                    lambda d=directory: go(project_url("setup", d)), hint=str(directory.parent)))
    try:
        links = load_tracker().links
    except Exception:  # the tracker file is the Run matrix page's to report
        links = []
    commands += [Command(f"sheet-{link.id}", "Run matrix", link.sheet, "grid_view",
                         lambda i=link.id: go(coverage_url(i)), hint=Path(link.workbook).name,
                         words="coverage sheet") for link in links]
    if frame is not None:
        commands += frame.commands()
    commands.append(Command("guide", "Help", "Web UI guide", "menu_book", lambda: guide.show(), words="help docs"))
    commands += [Command(f"guide-{i}", "Help", name, "article", lambda i=i: guide.show(i), hint="Web UI guide")
                 for i, (name, _text) in enumerate(guide_sections())]  # by title: a long section has every word
    return commands


def _calculators_link(panel: CalcPanel) -> None:
    """Calculators in the top bar: they open over the page, from the right (a second click closes them)."""
    with ui.row().classes("as-topbar-link").props('tabindex=0 role=button').mark("calculators") as link:
        ui.icon("calculate", size="18px")
        ui.label("Calculators").classes("as-topbar-label")
    link.on("click", panel.toggle)
    link.on("keydown.enter", panel.toggle)


def top_bar(page: str = "", frame: Optional["ProjectFrame"] = None) -> Guide:
    """The bar on every page: the brand, the search, Run matrix, Cluster, Calculators, the project (`frame`'s
    switcher) and ⚙."""
    guide = Guide(page)
    panel = CalcPanel(frame)
    with ui.row().classes("as-topbar w-full"):
        _brand()
        ui.space()
        CommandBar(lambda: _shell_commands(guide, panel, frame))
        ui.space()
        _tracker_link(page == "tracker")
        _cluster_button()
        _calculators_link(panel)
        if frame is not None:
            frame.switcher()
        _app_menu(guide)
    return guide


def header(page: str = "") -> None:
    """The top bar of pages outside a project (Projects, Run matrix, Settings, or a project that cannot be opened);
    `page` opens the guide on its section."""
    apply_theme()
    top_bar(page)


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
        if session.project.imported is not None and active not in IMPORTED_PAGES:
            # A read-only study of existing runs has nothing to set up or run: every link lands on Results.
            # Once the browser is connected (a navigation issued while the page is built never reaches it).
            target = project_url("results", session.directory)
            ui.timer(0, lambda: ui.navigate.to(target), once=True)
        apply_theme()
        self._run_progress: Optional[ui.label] = None  # the Run step's job progress (refresh draws the steps)
        self._run_fill: Optional[ui.element] = None
        self._running = False
        self._job_text = ""  # the running job's progress, as the search shows it
        self.paraview = ParaViewMenu(self)  # its button is on Monitor and Results; the search finds the cases
        self.guide = top_bar(active, self)
        with ui.row().classes("as-body w-full"):
            with ui.column().classes("as-sidebar").mark("sidebar"):
                self._steps = ui.column().classes("as-steps w-full")
                with ui.column().classes("as-sidebar-foot w-full"):
                    with ui.row().classes("as-step as-collapse").props('tabindex=0 role=button').mark(
                            "sidebar-toggle") as collapse:
                        ui.icon("keyboard_double_arrow_left", size="20px").classes("as-when-full")
                        ui.icon("keyboard_double_arrow_right", size="20px").classes("as-when-mini")
                        ui.label("Collapse").classes("as-step-name")
                        ui.tooltip("Expand").classes("as-step-tip")
                    collapse.on("click", _toggle_sidebar)
                    collapse.on("keydown.enter", _toggle_sidebar)
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

    def switcher(self) -> None:
        """The project in the top bar: its name (its kind on hover), and a dot while its job runs; its menu has the
        running job's log and switches project."""
        with ui.row().classes("as-topbar-control as-switcher").props('tabindex=0 role=button').mark(
                "project-switcher") as switcher:
            with ui.element("span").classes("as-initials-box"):
                self._initials = ui.label("").classes("as-initials")
                self._job_dot = ui.element("span").classes("as-switcher-dot").mark("project-running-dot")
            self._name = ui.label("").classes("as-switcher-name as-truncate").mark("project-name")
            ui.icon("expand_more").classes("as-topbar-muted")
            with ui.menu().mark("project-menu") as menu:
                self._log_item = ui.menu_item("Show the running job's log", on_click=lambda: self.log.open()).mark(
                    "menu-job-log")
                ui.menu_item("All projects", on_click=lambda: ui.navigate.to("/")).mark("menu-all-projects")
                here = Path(self.session.directory).resolve()
                recent = [directory for directory in load_recent() if directory.resolve() != here]
                if recent:
                    ui.separator()
                for directory in recent:
                    ui.menu_item(directory.name, on_click=lambda d=directory: ui.navigate.to(
                        project_url("setup", d))).mark(f"menu-recent-{directory.name}")
        switcher.on("keydown.enter", menu.open)
        self._switcher = switcher
        self._job_dot.set_visibility(False)
        self._log_item.set_visibility(False)

    def commands(self) -> list[Command]:
        """What the search finds in this project: its steps, its running job's log, its cases (on Monitor) and its
        flow files (in ParaView)."""
        from ..engine.paraview import case_outputs

        go, project, directory = ui.navigate.to, self.session.project, self.session.directory
        commands = [Command(f"step-{key}", "This project", label, STEP_ICONS[key],
                            lambda page=PAGE_OF_STEP[key]: go(project_url(page, directory)), hint=project.name)
                    for key, label in visible_steps(project) if key in PAGE_OF_STEP]
        if self._running:
            commands.insert(0, Command("job-log", "This project", "Show the running job's log", "terminal",
                                       lambda: self.log.open(), hint=self._job_text, words="job progress",
                                       featured=True))
        commands += [Command(f"case-{case.name}", "Cases", case.name, "show_chart",
                             lambda name=case.name: go(project_url("monitor", directory) + f"&case={quote(name)}"),
                             hint="Monitor", words="case") for case in project.cases]
        try:
            outputs = case_outputs(directory, project)
        except (AeroSuiteError, OSError):
            outputs = []
        commands += [Command(f"paraview-{output.name}", "ParaView", f"Open {output.name} in ParaView",
                             "view_in_ar", lambda o=output: self.paraview.choose(o), hint="flow files",
                             words="paraview vtk flow") for output in outputs]
        if project.imported is None:
            commands.append(Command("paraview-ascii", "ParaView", "Write ASCII from restart…", "description",
                                    self.paraview.ask_ascii, words="paraview vtk restart su2_sol"))
        return commands

    def refresh(self) -> None:
        """Redraw the project name, the sidebar's steps and badges, and the job indicator."""
        project = self.session.project
        self._name.text = project.name
        self._switcher.props(f'title="{project_kind(project)}"')
        self._initials.text = initials(project.name)
        self._initials.style(f"background: {badge_color(project.name)}")
        self._crumb_project.text = project.name
        badges = step_badges(self.session.directory, project)
        self._steps.clear()
        with self._steps:
            for key, label in visible_steps(project):
                self._step(key, label, badges[key])
        self._update_job()

    def _step(self, key: str, label: str, badge: str) -> None:
        """A step in the sidebar; Run also shows a running job's progress (click it for the log)."""
        page = PAGE_OF_STEP.get(key)
        if page is None:
            item = ui.row().classes("as-step as-step-later")
        else:
            item = ui.link(target=project_url(page, self.session.directory)).classes("as-step row")
            if key == self.active:
                item.classes("as-step-current")
        item.mark(f"step-{key}")
        if key == "run":
            item.classes("as-step-run")
        with item:
            ui.icon(STEP_ICONS[key], size="20px")
            status_dot(badge).mark(f"badge-{key}-{badge}")
            ui.label(label).classes("as-step-name")
            ui.tooltip(label).classes("as-step-tip")
            if key == "run":
                self._run_progress = ui.label("").classes("as-step-progress").mark("step-run-progress")
                self._run_progress.set_visibility(False)
        if key == "run":
            with ui.element("div").classes("as-step-bar").mark("step-run-bar") as self._run_bar:
                self._run_fill = ui.element("div").classes("as-step-fill").style("width: 0%")
            self._run_bar.set_visibility(False)

    def _tick(self) -> None:
        self._check_disk()
        self._update_job()

    def _update_job(self) -> None:
        """Show a running job of this project (started here, in another tab or the CLI) on the project in the top
        bar and on the Run step.

        With nothing shown only the cheap lock check runs; job state is read only while a job is active.
        """
        try:
            if not self._running and active_lock(self.session.directory) is None:
                return
            progress = job_progress(WATCHER.state(self.session.directory, self.session.project))
        except (AeroSuiteError, OSError):
            progress = None  # a broken job record must never break navigation
        self._running = progress is not None
        shown = [self._job_dot, self._log_item]
        if self._run_progress is not None and not self._run_progress.is_deleted:
            shown += [self._run_progress, self._run_bar]
        for element in shown:
            element.set_visibility(self._running)
        if progress is None:
            return
        self._job_text = progress.text
        if self._run_progress is not None and not self._run_progress.is_deleted:
            self._run_progress.set_text(progress.text.split(" · ")[0].replace(" ", ""))
            self._run_fill.style(f"width: {progress.percent}%")

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
