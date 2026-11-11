"""The Run page's cases on the left: the Board (a grid per altitude), the cases of earlier sweeps, the List by state
and the bar for several ticked cases."""
from typing import Optional

from nicegui import ui

from ...engine.editing import update_sweep
from ...engine.freestream import sweeps_altitude
from ...engine.naming import format_value
from ...engine.restarts import RUNS_DIR
from ...engine.results import HISTORY_FILE
from ..cluster_view import (
    case_slurm_text,
)
from ..jobs import JobView
from ..run_view import (
    TILE_WORDS,
    board_sections,
    case_from_name,
    earlier_groups,
    state_sections,
    status_counts,
    tile_text,
)
from ..ui_kit import flat_button, hint, pill, pill_text, pill_tone, secondary_button, table, td, td_box, titled
from .run_parts import _iterations, _plural, _Selection, _tone


class RunBoard:
    """Part of RunPage (pages/run.py), which holds the state these methods use."""

    # -- the board -------------------------------------------------------------------------------------------

    def _rows(self, view: JobView) -> dict:
        return {row.name: row for row in view.overview.rows}

    def _places(self, view: JobView) -> dict[str, int]:
        """Each queued case's place in the running job (1 = next)."""
        job = view.active
        if job is None:
            return {}
        queued = [name for name in job.cases if job.case_status.get(name) is not None
                  and job.case_status[name].value == "PENDING"]
        return {name: index for index, name in enumerate(queued, 1)}

    def _open(self, key: str, members: list, first: bool, default: bool = False) -> bool:
        """Whether a section shows its cases: as the user left it; else open when something happens there (running,
        queued, failed), when it is the first one, or by `default`."""
        if key in self.sections_open:
            return self.sections_open[key]
        return first or default or any(row.status in ("RUNNING", "FAILED", "BLOCKED", "PENDING") for row in members)

    def _shown_cases(self, view: JobView) -> list:
        """The project's cases, then the cases a running job has that the sweep no longer makes (by their names)."""
        others = [case_from_name(row.name) for row in view.overview.others]
        return list(self.project.cases) + [case for case in others if case is not None]

    def _board(self, view: JobView) -> None:
        rows = {row.name: row for row in view.overview.all_rows}
        places = self._places(view)
        others = {row.name for row in view.overview.others}
        sections = board_sections(self._shown_cases(view))
        compact = self._compact()
        for index, section in enumerate(sections):
            members = [rows[name] for name in section.cells.values() if name in rows]
            key = f"board:{section.key}"
            opened = self._open(key, members, first=index == 0)
            with ui.column().classes("as-card w-full gap-2").mark(f"board-{section.key}"):
                with ui.row().classes("items-center w-full gap-2 no-wrap as-section-head").mark(
                        f"board-head-{section.key}") as head:
                    ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                    ui.label(section.label or "Cases").classes("as-strong")
                    ui.label(_plural(len(members), "case")).classes("as-muted")
                    if members and all(row.name in others for row in members):
                        ui.label("in the running job, not in the sweep now").classes("as-muted as-small").mark(
                            f"board-others-{section.key}")
                    for status, count in status_counts(members):  # the rest is in the bar above and on the tiles
                        if status in ("FAILED", "BLOCKED"):
                            ui.label(f"{count} {pill_text(status).lower()}").classes(
                                f"as-pill as-pill-{pill_tone(status)}").mark(f"board-{status.lower()}-{section.key}")
                head.on("click", lambda _, k=key, o=opened: self._fold(k, not o))
                if not opened:
                    continue
                with ui.element("div").classes("as-board" + (" as-board-compact" if compact else "")).style(
                        f"grid-template-columns: 64px repeat({len(section.alphas)}, minmax(0, 1fr))"):
                    corner = ui.label(section.corner).classes("as-board-col as-board-corner").mark(
                        f"board-all-{section.key}")
                    corner.on("click", lambda _, n=list(section.cells.values()): self._toggle_names(n))
                    for alpha in section.alphas:
                        names = [name for (m, a), name in section.cells.items() if a == alpha]
                        col = ui.label(f"α {format_value(alpha)}°").classes("as-board-col").mark(
                            f"board-col-{section.key}-{format_value(alpha)}")
                        col.on("click", lambda _, n=names: self._toggle_names(n))
                    for value in section.rows:
                        names = [name for (r, a), name in section.cells.items() if r == value]
                        head_cell = ui.label(section.row_text(value)).classes("as-board-row").mark(
                            f"board-row-{section.key}-{format_value(value)}")
                        head_cell.on("click", lambda _, n=names: self._toggle_names(n))
                        for alpha in section.alphas:
                            name = section.cells.get((value, alpha))
                            if name is None or name not in rows:
                                ui.element("div")
                                continue
                            self._tile(rows[name], places.get(name), compact, other=name in others)
        hint("Click a tile for its details · Ctrl-click (⌘ on a Mac) or Shift-click to select several · click a heading "
             "to select its row or column").mark("board-help")

    def _tile(self, row, place: Optional[int], compact: bool, other: bool = False) -> None:
        iterations = (_iterations(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
                      if row.status in ("CONVERGED", "UNCONVERGED", "RUNNING", "CANCELLED") else None)
        text = tile_text(row.status, iterations, place)
        classes = f"as-tile as-tile-{_tone(row.status)}"
        if row.name in self.ticked:
            classes += " as-tile-selected"
        if row.name == self.focus:
            classes += " as-tile-focus"
        with ui.column().classes(classes + " gap-0").mark(f"tile-{row.name}") as tile:
            if not compact:
                ui.label(TILE_WORDS.get(row.status, row.status)).classes("as-tile-word")
            ui.label(text).classes("as-tile-text")
        titled(tile, f"{row.name} · {TILE_WORDS.get(row.status, row.status)}"
               + (" · in the running job, not in the sweep now" if other else "")
               + ("" if row.name not in self.ticked else " · selected"))
        tile.on("click", lambda e, n=row.name: self._tile_click(n, e.args), ["ctrlKey", "metaKey", "shiftKey"])

    def _tile_click(self, name: str, keys) -> None:
        keys = keys if isinstance(keys, dict) else {}
        if keys.get("ctrlKey") or keys.get("metaKey") or keys.get("shiftKey"):
            self._tick(name, name not in self.ticked)
            return
        self.focus = None if self.focus == name else name
        self.render()

    def _toggle_names(self, names: list) -> None:
        """Select these cases, or, when all of them are selected, unselect them."""
        names = [name for name in names if name in {case.name for case in self.project.cases}]
        if names and all(name in self.ticked for name in names):
            self.ticked -= set(names)
        else:
            self.ticked |= set(names)
        self.render()

    def _fold(self, key: str, opened: bool) -> None:
        self.sections_open[key] = opened
        self.render()

    # -- earlier sweeps ----------------------------------------------------------------------------------------

    def _earlier(self, view: JobView) -> None:
        """The cases earlier sweeps ran, kept but not in the next run: one folded line per altitude (its cases, their
        outcomes, the jobs), its grid when opened, a click on a case opening it in Monitor; Add to sweep puts the
        altitude back in the sweep, which makes its cases (same names) the sweep's again."""
        rows = view.overview.earlier
        hint(f"{_plural(len(rows), 'case')} from earlier sweeps: their runs, histories and results are kept. They are "
             "not part of the next run; click one for it in Monitor.").mark("earlier-note")
        can_add = sweeps_altitude(self.project)
        for group in earlier_groups(rows):
            key = f"earlier:{group.key}"
            opened = self.sections_open.get(key, False)
            jobs = list(dict.fromkeys(row.job_id for row in group.rows))
            counts = " · ".join(f"{count} {pill_text(status).lower()}" for status, count in status_counts(group.rows))
            with ui.column().classes("as-card as-earlier w-full gap-2").mark(f"earlier-{group.key}"):
                with ui.row().classes("items-center w-full gap-2 no-wrap"):
                    with ui.row().classes("items-center grow min-w-0 gap-2 no-wrap as-earlier-head").mark(
                            f"earlier-head-{group.key}") as head:
                        ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                        ui.label(group.label).classes("as-strong")
                        ui.label(f"{_plural(len(group.rows), 'case')} · {counts} · "
                                 f"job{'s' if len(jobs) > 1 else ''} {', '.join(jobs)}").classes("as-muted as-truncate")
                    head.on("click", lambda _, k=key, o=opened: self._fold(k, not o))
                    if can_add and group.altitude is not None:
                        secondary_button("Add to sweep", icon="add",
                                         on_click=lambda a=group.altitude: self._add_altitude(a)).mark(
                            f"earlier-add-{group.key}")
                if opened:
                    self._earlier_cases(group)

    def _earlier_cases(self, group) -> None:
        """An opened earlier altitude: a grid per β (Mach down, α across), then any case its name places on none."""
        compact = self._compact()
        by_name = {row.name: row for row in group.rows}
        sections = board_sections(group.cases)
        for section in sections:
            if len(sections) > 1:
                ui.label(section.label).classes("as-muted")
            with ui.element("div").classes("as-board" + (" as-board-compact" if compact else "")).style(
                    f"grid-template-columns: 64px repeat({len(section.alphas)}, minmax(0, 1fr))"):
                ui.label(section.corner).classes("as-board-col as-board-corner")
                for alpha in section.alphas:
                    ui.label(f"α {format_value(alpha)}°").classes("as-board-col")
                for value in section.rows:
                    ui.label(section.row_text(value)).classes("as-board-row")
                    for alpha in section.alphas:
                        name = section.cells.get((value, alpha))
                        if name is None:
                            ui.element("div")
                        else:
                            self._earlier_tile(by_name[name], compact)
        drawn = {case.name for case in group.cases}
        for row in group.rows:
            if row.name not in drawn:
                with ui.row().classes("items-center gap-2 w-full no-wrap").mark(f"earlier-row-{row.name}"):
                    ui.label(row.name).classes("as-mono")
                    pill(row.status)
                    ui.space()
                    flat_button("Monitor", icon="show_chart",
                                on_click=lambda n=row.name: ui.navigate.to(self._monitor_url(n)))

    def _earlier_tile(self, row, compact: bool) -> None:
        iterations = (_iterations(self.directory / RUNS_DIR / row.name / HISTORY_FILE)
                      if row.status in ("CONVERGED", "UNCONVERGED", "CANCELLED") else None)
        with ui.column().classes(f"as-tile as-tile-{_tone(row.status)} gap-0").mark(f"tile-{row.name}") as tile:
            if not compact:
                ui.label(TILE_WORDS.get(row.status, row.status)).classes("as-tile-word")
            ui.label(tile_text(row.status, iterations)).classes("as-tile-text")
        titled(tile, f"{row.name} · {TILE_WORDS.get(row.status, row.status)} · job {row.job_id} · click for Monitor")
        tile.on("click", lambda _, n=row.name: ui.navigate.to(self._monitor_url(n)))

    def _add_altitude(self, altitude: float) -> None:
        message = self.frame.save(lambda p: update_sweep(
            p, altitudes_km=sorted({*p.sweep.altitudes_km, altitude})))
        if message is not None:
            ui.notify(message, type="negative")
            return
        ui.notify(f"{format_value(altitude)} km is in the sweep again: generate its configs, then run its cases",
                  type="positive")
        self.tab = None  # back to the board, where its cases now are
        self.render()

    # -- the list by state -------------------------------------------------------------------------------------

    def _list(self, view: JobView, rows: Optional[list] = None) -> None:
        """The cases by state (`rows`: only these, e.g. a single case's running job's others)."""
        cases = {case.name: case for case in self.project.cases}
        places = self._places(view)
        sections = state_sections(view.overview.all_rows if rows is None else rows)
        cases.update({c.name: c for c in self._shown_cases(view) if c.name not in cases})
        own = {case.name for case in self.project.cases}
        with ui.column().classes("as-card as-card-flush w-full gap-0").mark("run-list"):
            for key, title, members in sections:
                skey = f"list:{key}"
                # Queued and done fold when long; the rest is what to look at or act on
                opened = self.sections_open.get(skey, key in ("running", "attention", "not-run") or len(members) <= 8)
                ticked = [row.name for row in members if row.name in self.ticked]
                selectable = [row.name for row in members if row.name in own]
                with ui.row().classes(f"as-list-section as-list-{key} items-center w-full no-wrap gap-2").mark(
                        f"list-{key}") as head:
                    ui.icon("expand_more" if opened else "chevron_right").classes("as-muted")
                    ui.label(title).classes("as-strong")
                    for status, count in status_counts(members):
                        ui.label(f"{count} {pill_text(status).lower()}").classes(f"as-pill as-pill-{pill_tone(status)}")
                    ui.space()
                    if key == "queued" and places:
                        nxt = min(places, key=places.get)
                        ui.label(f"next: {nxt}").classes("as-muted as-small")
                    if key in ("attention", "not-run", "done") and selectable:
                        everyone = len(ticked) == len(selectable)
                        flat_button("Unselect all" if everyone else f"Select all {len(selectable)}",
                                    on_click=lambda n=selectable: self._toggle_names(n)).props(
                            "dense").mark(f"list-select-{key}")
                head.on("click", lambda _, k=skey, o=opened: self._fold(k, not o))
                if not opened:
                    continue
                with table("36px minmax(10rem, 1.5fr) minmax(9rem, 1fr) minmax(8rem, .9fr) minmax(12rem, 1.2fr) "
                           "72px").classes("as-table-compact"):
                    for row in members:
                        self._list_row(row, cases.get(row.name), places.get(row.name), own=row.name in own)

    def _list_row(self, row, case, place: Optional[int], own: bool = True) -> None:
        with td_box():
            if own:  # a case the sweep no longer makes is the job's: it cannot be selected
                ui.checkbox(value=row.name in self.ticked,
                            on_change=lambda e, n=row.name: self._tick(n, e.value)).props("dense").mark(
                    f"tick-{row.name}")
            else:
                titled(ui.icon("lock", size="16px").classes("as-muted"),
                       "In the running job, not in the sweep now").mark(f"other-{row.name}")
        found = self._diagnosis(row)
        with td_box():
            with ui.column().classes("gap-0 min-w-0"):
                ui.label(row.name).classes("as-strong as-mono")
                if found is not None:
                    ui.label(found.summary).classes("as-failure-reason as-truncate").mark(f"why-{row.name}")
                self._ran_with(row)
                self._attempts_link(row.name)
        conditions = [f"M {format_value(case.mach)}", f"α {format_value(case.alpha)}"] if case else []
        if case is not None and len({c.beta for c in self.project.cases}) > 1:
            conditions.append(f"β {format_value(case.beta)}")
        if case is not None and case.altitude_km is not None:
            conditions.append(f"{format_value(case.altitude_km)} km")
        td(" · ".join(conditions)).classes("as-muted")
        with td_box():
            self._status(row)
            if place:
                ui.label(f"#{place}").classes("as-muted as-small")
        job = self.jobs_by_id.get(row.job_id)
        if job is not None and job.backend == "slurm":
            with td_box() as cell:
                cell.classes("as-slurm-cell")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(row.job_id).classes("as-mono as-small").mark(f"job-{row.name}")
                    ui.label(case_slurm_text(job, row.name)).classes("as-mono as-muted as-small").mark(
                        f"slurm-{row.name}")
                self._resubmit_button(job, row.name)
        else:
            td(row.job_id or "—", mono=True).classes("as-small").mark(f"job-{row.name}")
        with td_box():
            flat_button("Details", on_click=lambda n=row.name: self._focus(n)).props("dense").mark(
                f"details-{row.name}")
        if row.name in self.attempts_open:
            with ui.element("div").style("grid-column: 1 / -1"):
                self._attempts_list(row.name)

    def _focus(self, name: str) -> None:
        self.focus = None if self.focus == name else name
        self.render()

    def _selection_bar(self, selection: _Selection) -> None:
        if not selection.ticked:
            return
        with ui.row().classes("as-selbar w-full items-center no-wrap gap-3").mark("selection-bar"):
            ui.label(f"{len(selection.ticked)} selected").classes("as-strong").mark("selection-count")
            shown = ", ".join(selection.ticked[:4]) + (f" … and {len(selection.ticked) - 4} more"
                                                       if len(selection.ticked) > 4 else "")
            ui.label(shown).classes("as-mono as-small as-truncate grow")
            flat_button("Clear", on_click=lambda: self._select(None, set())).props("dense").mark("selection-clear")
