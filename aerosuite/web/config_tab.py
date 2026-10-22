"""Aircraft's Config tab: a case's whole config, editable. Each changed line goes back where it came from
(engine/config_edit.py): to the template, in place, or to the form field or placeholder that writes it; a line set
per case (the sweep's Mach, α, β, the mesh, the altitude's freestream) goes back as it was, with a note saying where
to change it. The raw template file is behind a toggle."""
from typing import Callable, Optional

from nicegui import ui

from ..engine.cfg import read_template, render_case
from ..engine.config_edit import apply_changes, split_edit
from ..engine.errors import AeroSuiteError
from .layout import ProjectFrame
from .template_edit import save_template_text
from .template_editor import SAVE_DELAY, TemplateEditor
from .ui_kit import banner, field, hint


class ConfigTab:
    def __init__(self, frame: ProjectFrame, state: dict, on_template_saved: Callable[[list[str]], None],
                 on_layers_saved: Callable[[], None], height: str = "55vh") -> None:
        """`on_template_saved(warnings)` runs after the template changed; `on_layers_saved()` after a form field or
        placeholder did (the page redraws its form). `state` survives page rebuilds."""
        self.frame, self.state = frame, state
        self.on_template_saved, self.on_layers_saved = on_template_saved, on_layers_saved
        self.height = height
        self.shown = ""  # the text as last rendered: what an edit is compared with
        self._timer: Optional[ui.timer] = None
        self.box = ui.column().classes("w-full gap-2")
        self.notes = ui.column().classes("w-full gap-1").mark("config-notes")
        with ui.row().classes("w-full items-center gap-2"):
            self.raw = ui.switch("Show the template file", value=bool(state.get("raw_template"))).mark(
                "config-raw-switch")
            hint("the text the form, placeholders and per-case values are written over")
        self.raw_box = ui.column().classes("w-full gap-2")
        self.raw.on_value_change(lambda e: self._show_raw(e.value))
        self.render()
        self._show_raw(self.raw.value)
        self._show_notes(state.pop("config_notes", []))

    # -- the case's config --------------------------------------------------------------------------------------

    def _case(self):
        cases = self.frame.session.project.cases
        names = [case.name for case in cases]
        if self.state.get("config_case") not in names:
            self.state["config_case"] = names[0] if names else None
        return next((case for case in cases if case.name == self.state["config_case"]), None)

    def render(self, carry: bool = True) -> None:
        """Draw the chosen case's config again (after a save, a form change or another case chosen); text typed
        but not saved yet stays, unless `carry` is False (just saved)."""
        if carry:
            carry_unsaved_config(self.state)
        self.box.clear()
        project = self.frame.session.project
        with self.box:
            case = self._case()
            if case is None:
                ui.label("No case to show yet.").mark("preview-empty")
                return
            if len(project.cases) > 1:
                field(ui.select([c.name for c in project.cases], value=case.name, label="Case",
                                on_change=lambda e: self._choose(e.value))).mark("preview-case")
            if project.sweep.enabled:
                hint("Edits apply to every case, except the lines each case gets from the sweep "
                     "(Mach, α, β, its file names).").mark("config-sweep-note")
            try:
                template = read_template(self.frame.session.directory, project)
                self.shown = render_case(template, project, case)
            except AeroSuiteError as exc:
                banner("error", f"Error: {exc}").mark("preview-error")
                return
            pending = self.state.pop("config_pending", None)
            self.editor = ui.codemirror(pending if pending is not None else self.shown, line_wrapping=False,
                                        keymap={"Mod-s": self.commit}).classes("w-full as-code").style(
                f"height: {self.height}").mark("config-edit")
            self.state["config_editor"], self.state["config_shown"] = self.editor, self.shown
            self.editor.on_value_change(self._typed)
            self.editor.on("focusout", self.commit)

    def _choose(self, name: str) -> None:
        self.commit()
        self.state["config_case"] = name
        self.render(carry=False)

    def _typed(self, _event=None) -> None:
        if self._timer is not None:
            self._timer.cancel()
        self._timer = ui.timer(SAVE_DELAY, self.commit, once=True)

    def commit(self, _event=None) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None
        editor = self.state.get("config_editor")
        case = self._case()
        if editor is None or case is None:
            return
        text = editor.value or ""
        if text == self.shown:
            return
        frame = self.frame
        try:
            template = read_template(frame.session.directory, frame.session.project)
        except AeroSuiteError as exc:
            self._show_notes([str(exc)])
            return
        edit = split_edit(template, frame.session.project, case, text)
        notes = list(edit.notes)
        if edit.template != template:
            message, warnings = save_template_text(frame, edit.template)
            if message is not None:
                self._show_notes([message])
                return
            self.on_template_saved(warnings)
        if edit.changes:
            case_name = case.name
            result: dict = {}

            def change(p) -> None:
                own = next((c for c in p.cases if c.name == case_name), p.cases[0])
                result["done"], result["notes"] = apply_changes(p, own, edit.template, edit.changes)

            message = frame.save(change)
            if message is not None:
                notes.append(message)
            else:
                notes += result.get("notes", [])
                if result.get("done"):
                    ui.notify("Changed " + ", ".join(result["done"]), type="positive")
                    self.state["config_notes"] = notes
                    self.state.pop("config_editor", None)  # saved: nothing to carry into the rebuilt page
                    self.on_layers_saved()  # the page redraws its form, and this tab with it
                    return
        self._show_notes(notes)
        self.render(carry=False)  # the lines that could not change show their values again

    def _show_notes(self, notes: list[str]) -> None:
        self.notes.clear()
        with self.notes:
            for note in notes:
                banner("warning", note).mark("config-note")

    # -- the raw template ---------------------------------------------------------------------------------------

    def _show_raw(self, on: bool) -> None:
        self.state["raw_template"] = on
        self.raw_box.clear()
        if not on:
            return
        with self.raw_box:
            TemplateEditor(self.frame, self.state, on_saved=self._raw_saved, height=self.height)

    def _raw_saved(self, warnings: list[str]) -> None:
        self.on_template_saved(warnings)
        self.render(carry=False)


def carry_unsaved_config(state: dict) -> None:
    """Before a page rebuild: keep config text typed but not yet saved (see template_editor.carry_unsaved)."""
    editor = state.get("config_editor")
    if editor is not None and state.get("config_shown") is not None:
        current = editor.value or ""
        if current != state["config_shown"]:
            state["config_pending"] = current
