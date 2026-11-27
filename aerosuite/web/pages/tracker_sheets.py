"""The coverage page's sheet switcher: the pinned sheets as chips, and All sheets, a menu of every linked sheet grouped
by configuration, searchable, each with its progress; completed sheets folded away at its foot."""
from __future__ import annotations

from typing import Optional

from nicegui import run, ui

from ...engine.errors import TrackerError
from ...engine.tracker_links import PINNED_AT_MOST, Link, LinkReport, report, saved_links, set_pinned
from ..tracker_view import bar_html, segment_count
from ..ui_kit import hint, titled
from .tracker_coverage import coverage_url

OTHER = "Other"  # the heading of sheets with no group, when some have one


def chip_links(links: list[Link], current: Link) -> list[Link]:
    """The chips: the pinned sheets (the first ongoing ones while none is pinned), and the current sheet wherever it
    is, so you always see where you are."""
    pinned = [link for link in links if link.pinned][:PINNED_AT_MOST]
    chosen = pinned or [link for link in links if link.completed is not True][:PINNED_AT_MOST]
    return chosen if any(link.id == current.id for link in chosen) else chosen + [current]


def matches(link: Link, query: str) -> bool:
    query = query.strip().lower()
    return not query or query in f"{link.sheet} {link.label} {link.group}".lower()


def grouped(links: list[Link]) -> list[tuple[str, list[Link]]]:
    """The sheets by group, groups in the order they first appear and ungrouped ones last; one nameless group when no
    sheet has one."""
    groups: dict[str, list[Link]] = {}
    for link in links:
        groups.setdefault(link.group.strip(), []).append(link)
    if list(groups) == [""]:
        return [("", groups[""])]
    return [(name or OTHER, items) for name, items in sorted(groups.items(), key=lambda pair: pair[0] == "")]


class SheetSwitcher:
    def __init__(self, current: Link, view: str) -> None:
        self.current, self.view = current, view
        self.links = saved_links()
        self.reports: Optional[dict[str, LinkReport]] = None  # read when All sheets first opens
        self.query = ""
        with ui.row().classes("as-sheet-nav w-full items-center gap-2").mark("coverage-sheets"):
            self.chips = ui.row().classes("gap-2 items-center")
            with ui.button(color=None).props("no-caps unelevated").classes("as-chip as-sheet-all").mark(
                    "coverage-all-sheets") as self.all_button:
                self.all_label = ui.label("").mark("coverage-all-sheets-text")
                ui.icon("expand_more")
                with ui.menu().props("anchor='bottom right' self='top right'").classes("as-sheet-menu").mark(
                        "sheets-menu") as menu:
                    self.menu = menu
                    menu.on_value_change(lambda e: self._opened() if e.value else None)
                    ui.input(placeholder="Find a sheet", on_change=self._search).props(
                        "outlined dense clearable autofocus").classes("w-full").mark("sheets-search")
                    self.list = ui.column().classes("as-sheet-list w-full gap-0").mark("sheets-list")
        self._draw_chips()

    def _draw_chips(self) -> None:
        self.chips.clear()
        with self.chips:
            for link in chip_links(self.links, self.current):
                chip = ui.link(link.title, coverage_url(link.id, self.view)).classes(
                    "as-chip as-cov-chip" + (" as-chip-on" if link.id == self.current.id else "")).mark(
                    f"coverage-sheet-{link.id}")
                if link.label:
                    titled(chip, link.sheet)
        self.all_label.text = f"All sheets ({len(self.links)})"

    async def _opened(self) -> None:
        if self.reports is None:
            self._draw_list()  # the names straight away; the progress once the workbooks are read
            links = list(self.links)
            reports = await run.io_bound(lambda: [report(link) for link in links])
            self.reports = {item.link.id: item for item in reports}
        self._draw_list()

    def _search(self, event) -> None:
        self.query = event.value or ""
        self._draw_list()

    def _done(self, link: Link) -> bool:
        item = self.reports.get(link.id) if self.reports else None
        return item.done if item is not None else link.completed is True

    def _draw_list(self) -> None:
        if self.list.is_deleted:
            return
        self.list.clear()
        shown = [link for link in self.links if matches(link, self.query)]
        ongoing = [link for link in shown if not self._done(link)]
        completed = [link for link in shown if self._done(link)]
        with self.list:
            if not shown:
                hint("No sheet matches.").classes("as-sheet-empty").mark("sheets-none")
                return
            if self.reports is None:
                hint("Reading the sheets…").classes("as-sheet-empty").mark("sheets-reading")
            self._groups(ongoing)
            if completed:  # folded, unless you are searching or on one of them
                unfold = bool(self.query.strip()) or any(link.id == self.current.id for link in completed)
                with ui.expansion(f"Completed · {len(completed)}", value=unfold).props(
                        "dense").classes("as-sheet-done w-full").mark("sheets-completed"):
                    self._groups(completed)

    def _groups(self, links: list[Link]) -> None:
        for name, items in grouped(links):
            if name:
                with ui.row().classes("as-sheet-group w-full"):
                    ui.label(name)
                    ui.label(f"{len(items)} sheet{'' if len(items) == 1 else 's'}")
            for link in items:
                self._row(link)

    def _row(self, link: Link) -> None:
        mark = f"sheets-row-{link.id}"
        item = self.reports.get(link.id) if self.reports else None
        with ui.element("div").classes("as-sheet-row" + (" as-sheet-row-on" if link.id == self.current.id else "")
                                       ).mark(mark):
            name = ui.link(link.title, coverage_url(link.id, self.view)).classes("as-sheet-name").mark(f"{mark}-open")
            if link.label:
                titled(name, link.sheet)
            if item is None:
                ui.element("div")
                ui.element("div")
                ui.element("div")
            elif item.error or item.matrix is None:
                titled(ui.label("cannot be read").classes("as-error-text as-sheet-span"), item.error)
            else:
                counts, total = item.sheet_counts, len(item.matrix.rows)
                ui.html(bar_html(counts, total), sanitize=False).classes("as-sheet-bar")
                converged = segment_count(counts, "converged")
                hint(f"{round(100 * converged / total) if total else 0}% · {total}").classes("as-sheet-num").mark(
                    f"{mark}-progress")
                failed, live = segment_count(counts, "failed"), segment_count(counts, "live")
                if failed:
                    ui.label(f"{failed} failed").classes("as-sheet-flag as-error-text").mark(f"{mark}-failed")
                elif live:
                    ui.label(f"{live} running").classes("as-sheet-flag as-sheet-live")
                else:
                    ui.element("div")
            pin = ui.button(icon="push_pin", color=None, on_click=lambda: self._pin(link)).props(
                "flat round dense size=sm").classes("as-sheet-pin" + (" as-sheet-pinned" if link.pinned else ""))
            pin.mark(f"{mark}-pin")
            titled(pin, "Unpin from the chips" if link.pinned else "Pin as a chip")

    def _pin(self, link: Link) -> None:
        try:
            set_pinned(link.id, not link.pinned)
        except TrackerError as exc:
            ui.notify(str(exc), type="warning")
            return
        self.links = saved_links()
        if self.reports is not None:  # the reports keep the link they were read with: give them the new one
            for fresh in self.links:
                if fresh.id in self.reports:
                    self.reports[fresh.id].link = fresh
        self._draw_chips()
        self._draw_list()
