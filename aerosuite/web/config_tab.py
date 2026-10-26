"""Aircraft's Config tab: a case's config, in two views. *Written lines*: only the lines AeroSuite writes over the
template, coloured by where each comes from (a click opens the form tab that sets it). *Whole config*: all of it,
editable; each changed line goes back where it came from (engine/config_edit.py): to the template, in place, or to
the form field or placeholder that writes it; a line set per case (the sweep's Mach, α, β, the mesh, the altitude's
freestream) goes back as it was, with a note saying where to change it."""
from typing import Callable, Optional

from nicegui import background_tasks, run, ui

from ..engine.cfg import read_template, render_case
from ..engine.config_edit import FORM_FIELDS, WrittenLine, apply_changes, split_edit, written_lines
from ..engine.errors import AeroSuiteError
from ..engine.settings import load_settings
from ..engine.su2_check import dry_run, enabled, executable, where
from .layout import ProjectFrame
from .template_edit import save_template_text
from .template_editor import SAVE_DELAY
from .ui_kit import banner, field, hint, ok_line

VIEWS = {"written": "Written lines", "whole": "Whole config"}
# who writes a line -> (the legend's word, its colour); see theme.py's .as-wl-*
SOURCES = {"form": ("form", "#2f6fe4"), "altitude": ("altitude", "#0a7ea4"), "marker": ("boundaries", "#8250df"),
           "placeholder": ("extra options", "#bc4c00"), "case": ("per case", "#8c959f")}
FORM_TABS = {"Flight & air": "flight", "Reference": "reference", "Solver": "solver"}
TAB_NAMES = {"flight": "Flight & air", "solver": "Solver", "boundaries": "Boundaries", "reference": "Reference",
             "extra": "Extra options"}


def line_tab(line: WrittenLine) -> Optional[str]:
    """The Aircraft form tab that sets a written line, or None (the case's own file names and mesh)."""
    key = line.text.split("=", 1)[0].strip()
    if line.source == "marker":
        return "boundaries"
    if line.source == "placeholder":
        return "extra"
    if line.source == "altitude" or key in ("MACH_NUMBER", "AOA", "SIDESLIP_ANGLE"):
        return "flight"
    if line.source == "form" and key in FORM_FIELDS:
        return FORM_TABS.get(FORM_FIELDS[key][3])
    return None


class ConfigTab:
    def __init__(self, frame: ProjectFrame, state: dict, on_template_saved: Callable[[list[str]], None],
                 on_layers_saved: Callable[[], None], on_pick: Callable[[str], None] = lambda tab: None,
                 height: str = "55vh") -> None:
        """`on_template_saved(warnings)` runs after the template changed; `on_layers_saved()` after a form field or
        placeholder did (the page redraws its form fields; this tab stays as it is); `on_pick(tab)` when a written
        line is clicked. `state` survives page rebuilds."""
        self.frame, self.state = frame, state
        self.on_template_saved, self.on_layers_saved, self.on_pick = on_template_saved, on_layers_saved, on_pick
        self.height = height
        self.shown = ""  # the text as last rendered: what an edit is compared with
        self._timer: Optional[ui.timer] = None
        state.setdefault("config_view", "written")
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            ui.toggle(VIEWS, value=state["config_view"], on_change=lambda e: self._view(e.value)).props(
                "no-caps unelevated dense toggle-color=primary").classes("as-toggle").style("flex: none").mark("config-view")
            self.view_hint = hint("").mark("config-view-hint")
        self.box = ui.column().classes("w-full gap-2")
        self.notes = ui.column().classes("w-full gap-1").mark("config-notes")
        self.render()
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
        if self._update_editor(carry):
            return
        if carry:
            carry_unsaved_config(self.state)
        self.box.clear()
        project = self.frame.session.project
        written = self.state["config_view"] == "written"
        self.view_hint.text = ("what AeroSuite writes over the template; click a line for its field" if written
                               else "edit any line: it goes back to the template, or to its field")
        if written:
            self.state["config_editor"] = None  # nothing typed to carry or commit in this view
        with self.box:
            case = self._case()
            if case is None:
                ui.label("No case to show yet.").mark("preview-empty")
                return
            if len(project.cases) > 1:
                with ui.row().classes("w-full items-center gap-2 no-wrap"):
                    field(ui.select([c.name for c in project.cases], value=case.name, label="Showing case",
                                    on_change=lambda e: self._choose(e.value))).classes("grow").mark("preview-case")
                    index = [c.name for c in project.cases].index(case.name)
                    hint(f"{index + 1} of {len(project.cases)}")
            if project.sweep.enabled:
                hint("Edits apply to every case, except the lines each case gets from the sweep "
                     "(Mach, α, β, its file names).").mark("config-sweep-note")
            try:
                template = read_template(self.frame.session.directory, project)
                self.shown = render_case(template, project, case)
            except AeroSuiteError as exc:
                banner("error", f"Error: {exc}").mark("preview-error")
                return
            if written:
                self._written(template, case)
            else:
                self._editor()
            self._drawn = (case.name, [c.name for c in project.cases])
            self.su2_box = ui.column().classes("w-full gap-1").mark("config-su2")
            self._check(case, template)

    def _update_editor(self, carry: bool) -> bool:
        """Whole config, same case: show the config as it is now in the editor already there, so it keeps its
        scroll and cursor (a new editor opens at the top). With `carry`, text typed but not saved yet stays: it is
        saved against the new text. Returns False when the editor has to be drawn anew."""
        editor = self.state.get("config_editor")
        if (self.state["config_view"] != "whole" or editor is None or editor is not getattr(self, "editor", None)
                or editor.is_deleted):
            return False
        project = self.frame.session.project
        case = self._case()
        if case is None or getattr(self, "_drawn", None) != (case.name, [c.name for c in project.cases]):
            return False
        try:
            template = read_template(self.frame.session.directory, project)
            text = render_case(template, project, case)
        except AeroSuiteError:
            return False
        typed = editor.value or ""
        if typed != text and (typed == self.shown or not carry):  # nothing typed since, or just saved
            editor.set_value(text)
        self.shown = self.state["config_shown"] = text
        self._check(case, template)
        return True

    def _check(self, case, template: str) -> None:
        """SU2's verdict on the config shown, under it: what was there goes (a check still running finds its box
        gone and stops)."""
        self.su2_box.clear()
        with self.su2_box:
            box = ui.column().classes("w-full gap-1")
        background_tasks.create(self._su2_check(case, template, self.shown, box))

    def _written(self, template: str, case) -> None:
        """The written lines, in config order, with the template's stretches between them folded."""
        lines = written_lines(template, self.frame.session.project, case)
        with ui.row().classes("as-legend"):
            for word, colour in SOURCES.values():
                with ui.row().classes("items-center gap-0"):
                    ui.element("span").classes("as-legend-dot").style(f"background: {colour}")
                    ui.label(word)
        total = len(self.shown.splitlines())
        with ui.column().classes("as-written gap-0").mark("config-written"):
            previous = 0
            for line in lines + [None]:
                upto = line.number if line is not None else total + 1
                if upto - previous > 1:
                    count = upto - previous - 1
                    ui.label(f"… {count} template line{'s' if count > 1 else ''}").classes("as-wl-gap").on(
                        "click", lambda: self._view("whole"))
                if line is None:
                    break
                previous = line.number
                tab = line_tab(line)
                key = line.text.split("=", 1)[0].strip()
                with ui.row().classes(f"as-wl as-wl-{line.source}").mark(
                        f"config-written-line config-written-{key}") as row:
                    ui.label(str(line.number)).classes("as-wl-no")
                    ui.label(line.text).classes("as-wl-text")
                    value = line.text.split("=", 1)[1].strip()
                    if line.template is not None and " ".join(line.template.split()) != " ".join(value.split()):
                        ui.label(f"template: {line.template}").classes("as-wl-was")
                    ui.label(TAB_NAMES.get(tab, "this case") if line.source != "altitude" else "altitude").classes(
                        "as-wl-tag")
                if tab is not None:
                    row.on("click", lambda _, t=tab: self.on_pick(t))
        hint(f"{len(lines)} of {total} lines are written by AeroSuite; the rest is the template's.").mark(
            "config-written-count")

    def _view(self, view: str) -> None:
        if view == self.state["config_view"]:
            return
        self.commit()
        self.state["config_view"] = view
        self.render(carry=False)

    def _editor(self) -> None:
        pending = self.state.pop("config_pending", None)
        self.editor = ui.codemirror(pending if pending is not None else self.shown, line_wrapping=False,
                                    keymap={"Mod-s": self.commit}).classes("w-full as-code").style(
            f"height: {self.height}").mark("config-edit")
        self.state["config_editor"], self.state["config_shown"] = self.editor, self.shown
        self.editor.on_value_change(self._typed)
        self.editor.on("focusout", self.commit)

    async def _su2_check(self, case, template: str, text: str, box: ui.column) -> None:
        """SU2's verdict on the shown config, under the editor (a dry run: about 2 s; cached)."""
        settings = load_settings()[0]
        if not enabled(settings):
            return
        su2 = executable(settings)
        if su2 is None:
            with box:
                hint(f"Not checked with SU2: SU2_CFD was not found in {settings.slurm.su2_bin}")
            return
        with box:
            hint("Checking with SU2…")
        result = await run.io_bound(dry_run, text, su2)
        if box.is_deleted:
            return  # drawn again meanwhile: the new box has its own check
        box.clear()
        with box:
            if result.skipped:
                hint(f"Not checked with SU2: {result.skipped}")
            elif result.ok:
                ok_line("SU2 accepts this config.").mark("config-su2-ok")
            else:
                banner("error", f"SU2 rejects this config: {result.message}"
                                f"{where(template, self.frame.session.project, case, result.message)}").mark(
                    "config-su2-error")

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
                    self.on_layers_saved()  # the page redraws its form fields
        self._show_notes(notes)
        self.render(carry=False)  # the lines that could not change show their values again

    def _show_notes(self, notes: list[str]) -> None:
        self.notes.clear()
        with self.notes:
            for note in notes:
                banner("warning", note).mark("config-note")


def carry_unsaved_config(state: dict) -> None:
    """Before a page rebuild: keep config text typed but not yet saved (see template_editor.carry_unsaved)."""
    editor = state.get("config_editor")
    if editor is not None and state.get("config_shown") is not None:
        current = editor.value or ""
        if current != state["config_shown"]:
            state["config_pending"] = current
