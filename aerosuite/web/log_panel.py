"""The log panel: a console that slides up from the bottom of a project page and tails a job's log.

It follows the running job (else the newest one) until a job is picked from its list; a Log button in
the bottom-right corner opens it, and so does the top bar's "Running" indicator.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.runner import JobRecord
from ..engine.jobs.store import list_jobs
from .jobs import WATCHER

if TYPE_CHECKING:
    from .layout import ProjectFrame

POLL_SECONDS = 1.0
PANEL_LINES = 500
PANEL_BYTES = 256 * 1024
NO_JOBS = "No jobs yet. Submit cases on the Run page; the sweep's output appears here as it runs."


class LogPanel:
    def __init__(self, frame: "ProjectFrame") -> None:
        self.frame = frame
        self.chosen: Optional[str] = None  # a job picked from the list; None follows the running/newest one
        self._shown_text: Optional[str] = None
        self._quiet = False  # set while the list is filled in, so that is not taken as a pick

        self.button = ui.button("Log", icon="terminal", on_click=lambda: self.open(), color=None).props(
            "unelevated no-caps").classes("as-log-button").mark("log-open")
        with ui.column().classes("as-log").mark("log-panel") as self.panel:
            with ui.row().classes("as-log-head w-full no-wrap"):
                ui.icon("terminal", size="18px")
                ui.label("Log").classes("as-log-title")
                self.select = ui.select({}, on_change=lambda e: self._pick(e.value)).props(
                    "dense options-dense borderless dark").classes("as-log-select").mark("log-job")
                self.state = ui.label("").classes("as-log-state").mark("log-state")
                ui.space()
                self.follow = ui.checkbox("Follow", value=True).props("dense dark").mark("log-follow")
                ui.button(icon="close", on_click=self.close, color=None).props("flat round dense").classes(
                    "as-log-close").mark("log-close")
            with ui.scroll_area().classes("as-log-body") as self.scroll:
                self.text = ui.label("").classes("as-log-text").mark("log-text")
        self.panel.set_visibility(False)
        self.timer = ui.timer(POLL_SECONDS, self.update, active=False)

    @property
    def is_open(self) -> bool:
        return self.panel.visible

    def open(self, job_id: Optional[str] = None) -> None:
        """Show the panel on `job_id`, or following the running (else the newest) job."""
        self.chosen = job_id
        self._shown_text = None
        self.panel.set_visibility(True)
        self.button.set_visibility(False)
        self.frame.content.classes("as-log-open")  # room to scroll the page's end above the panel
        self.timer.interval = POLL_SECONDS
        self.timer.activate()
        self.update()

    def close(self) -> None:
        self.timer.deactivate()
        self.panel.set_visibility(False)
        self.button.set_visibility(True)
        self.frame.content.classes(remove="as-log-open")

    def _pick(self, job_id: Optional[str]) -> None:
        if self._quiet or not job_id:
            return
        self.chosen = job_id
        self._shown_text = None
        self.update()

    def update(self) -> None:
        if not self.is_open:
            return
        try:
            jobs = list_jobs(self.frame.session.directory)
        except (AeroSuiteError, OSError):
            jobs = []
        job = self._job(jobs)
        self._quiet = True
        try:
            self.select.set_options({j.id: j.id for j in jobs}, value=job.id if job else None)
        finally:
            self._quiet = False
        self.state.set_text(job.state.value.lower() if job else "")
        if job is None:
            text = NO_JOBS
        else:
            text = WATCHER.log_tail(self.frame.session.directory, job, lines=PANEL_LINES, max_bytes=PANEL_BYTES)
            text = "(the log could not be read)" if text is None else (text or "(nothing written yet)")
        if text != self._shown_text:
            self._shown_text = text
            self.text.set_text(text)
            if self.follow.value:
                self.scroll.scroll_to(percent=1.0)

    def _job(self, jobs: list[JobRecord]) -> Optional[JobRecord]:
        if self.chosen is not None:
            picked = next((j for j in jobs if j.id == self.chosen), None)
            if picked is not None:
                return picked
        active = next((j for j in jobs if j.is_active), None)
        return active or (jobs[0] if jobs else None)
