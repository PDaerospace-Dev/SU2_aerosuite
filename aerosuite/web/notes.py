"""A job's note: its #tags in the accent colour, the field on the Run page with its tag autocomplete, the line of
config changes under it, and the dialog that edits a note and outcome (Cluster page)."""
from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Callable, Optional, Sequence

from nicegui import run, ui

from ..engine.errors import AeroSuiteError
from ..engine.jobs.changes import ConfigChange
from ..engine.jobs.runner import TAG_RE
from ..engine.tags import TagMatch, matching_tags
from .jobs import WATCHER
from .ui_kit import field, primary_button, secondary_button

_TRAILING_TAG = re.compile(r"#([\w-]*)$")
# Enter never adds a line to a note; Tab and the arrows belong to the list while it is open
_KEYS = """(e) => {
  const open = !!document.querySelector('.as-note-foot');
  const list = open && ['Tab', 'ArrowDown', 'ArrowUp', 'Escape'].includes(e.key);
  if (e.key === 'Enter' || list) { e.preventDefault(); emit({key: e.key}); }
}"""


def note_html(note: str) -> str:
    """The note as HTML (all text escaped), each #tag in the accent colour."""
    return TAG_RE.sub(lambda match: f'<span class="as-hash">{match.group(0)}</span>', escape(note))


def note_label(note: str, outcome: str = "", *, quoted: bool = False) -> ui.html:
    """A note (and "→ outcome") as one line of text with its tags coloured."""
    text = note_html(note)
    if quoted:
        text = f"“{text}”"
    if outcome:
        text += f" → {escape(outcome)}"
    return ui.html(text, sanitize=False)


def jobs_text(count: int) -> str:
    return f"{count} job{'' if count == 1 else 's'}"


class NoteField:
    """One line for what a run is for: no box, no label; wraps when long. Typing `#` lists the tags used before."""

    def __init__(self, directory: Path, value: str, on_change: Callable[[str], None], mark: str = "run-note") -> None:
        self.directory = directory
        self.value = value
        self.on_change = on_change
        self.matches: list[TagMatch] = []
        self.index = 0
        self.typed: Optional[str] = None  # the tag being typed (no #), None while the list is closed
        with ui.column().classes("as-note w-full gap-0").mark(f"{mark}-box"):
            with ui.element("div").classes("as-note-wrap w-full"):
                self.shown = ui.html(note_html(value), sanitize=False).classes("as-note-text")
                self.box = ui.textarea(value=value, placeholder="Add a note…").props(
                    'autogrow underlined dense rows=1 input-class="as-note-input"').classes("as-note-field w-full")
                self.box.mark(mark)
            self.menu = ui.column().classes("as-note-menu w-full gap-0")
        self.box.on_value_change(lambda e: self._changed(e.value or ""))
        self.box.on("keydown", lambda e: self._key((e.args or {}).get("key", "")), js_handler=_KEYS)
        self._suggest()

    # -- typing -------------------------------------------------------------------------------------------------

    def _changed(self, text: str) -> None:
        self.value = text
        self.shown.content = note_html(text)
        self.on_change(text)
        self._suggest()

    def _suggest(self) -> None:
        found = _TRAILING_TAG.search(self.value)
        self.menu.clear()
        if found is None:
            self.typed, self.matches = None, []
            return
        self.typed = found.group(1)
        self.matches = matching_tags(self.typed, self.directory)
        self.index = min(self.index, max(0, len(self.matches) - 1))
        with self.menu:
            for position, match in enumerate(self.matches):
                row = ui.row().classes("as-note-row items-center no-wrap gap-3" + (
                    " as-note-row-on" if position == self.index else "")).mark(f"note-tag-{match.tag}")
                row.on("mousedown", lambda _, t=match.tag: self._pick(t), [])
                with row:
                    ui.label(f"#{match.tag}").classes("as-hash")
                    ui.label(match.scope).classes("as-muted as-small")
                    ui.space()
                    ui.label(jobs_text(match.count)).classes("as-muted as-small")
            ui.label(f"Enter to pick · keep typing to create #{self.typed or '…'}").classes(
                "as-note-foot as-muted as-small").mark("note-menu-foot")

    def _key(self, key: str) -> None:
        if key in ("Enter", "Tab"):
            if self.typed is not None:
                self._pick(self.matches[self.index].tag if self.matches else self.typed)
        elif key in ("ArrowDown", "ArrowUp") and self.matches:
            self.index = (self.index + (1 if key == "ArrowDown" else -1)) % len(self.matches)
            self._suggest()
        elif key == "Escape":
            self.typed = None
            self.menu.clear()

    def _pick(self, tag: str) -> None:
        """Finish the tag being typed with `tag` (a new tag is created when the note is saved)."""
        text = _TRAILING_TAG.sub(f"#{tag} ", self.value)
        self.index = 0
        self.box.value = text  # on_value_change takes it from here
        self.box.run_method("focus")


def changes_line(changes: Sequence[ConfigChange], open_: bool, on_toggle: Callable[[bool], None],
                 mark: str = "run-changes") -> None:
    """"Note · N config changes since last run", grey and small; clicking it lists the lines that changed. Nothing
    when none did."""
    if not changes:
        return
    count = f"{len(changes)} config change{'' if len(changes) == 1 else 's'}"
    with ui.column().classes("as-changes w-full gap-0"):
        line = ui.row().classes("as-changes-head items-center no-wrap gap-1").mark(mark)
        with line:
            ui.icon("expand_more" if open_ else "chevron_right").classes("as-changes-icon")
            ui.label(f"Note · {count} since last run").mark(f"{mark}-text")
        line.on("click", lambda: on_toggle(not open_))
        if open_:
            with ui.column().classes("as-changes-list w-full gap-0").mark(f"{mark}-list"):
                for change in changes:
                    ui.label(f"{change.text} · {len(change.cases)} case{'' if len(change.cases) == 1 else 's'}").classes(
                        "as-mono")


async def edit_note(study: Path, job_id: str, note: str, outcome: str) -> bool:
    """A small dialog for a job's note and outcome; saved under the lock the job watcher uses. True when saved."""
    with ui.dialog() as dialog, ui.card().classes("w-[26rem] max-w-full").mark("note-dialog"):
        ui.label(f"Job {job_id}").classes("as-dialog-title")
        note_box = field(ui.textarea("Note", value=note, placeholder="What is this run for? Use #tags")).props(
            "autogrow").classes("w-full").mark("note-edit")
        outcome_box = field(ui.input("Outcome", value=outcome, placeholder="What came of it")).classes(
            "w-full").mark("outcome-edit")
        error = ui.label("").classes("as-error-text").mark("note-error")

        async def save() -> None:
            try:
                await run.io_bound(WATCHER.annotate, study, job_id, " ".join((note_box.value or "").split()),
                                   " ".join((outcome_box.value or "").split()))
            except AeroSuiteError as exc:
                error.text = str(exc)
                return
            dialog.submit(True)
            dialog.delete()

        with ui.row().classes("w-full justify-end gap-2"):
            secondary_button("Cancel", on_click=lambda: (dialog.submit(False), dialog.delete())).mark("note-cancel")
            primary_button("Save", on_click=save).mark("note-save")
    return bool(await dialog)
