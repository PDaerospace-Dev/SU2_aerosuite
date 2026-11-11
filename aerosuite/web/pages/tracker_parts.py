"""What the Run matrix pages share: their links, the crumbs, a status pill, the legend, the solver order choice and
small texts."""
from datetime import datetime
from urllib.parse import quote

from nicegui import ui

from ...engine.tracker import ORDERS
from ...engine.tracker_links import LinkReport
from ..tracker_view import PILL_TONES, SEGMENTS
from ..ui_kit import (
    fold_at_start,
    hint,
)

ROWS_AT_MOST = 300  # rows a preview table draws
# the sheet's Status values -> pill tone, and the bar segment they count in
AXES = ["Mach", "altitudes", "AoA", "elevator", "sideslip"]
SWEEP_FIELDS = [("Mach", ""), ("Altitude", "km"), ("AoA", "deg"), ("Elevator δe", "deg"), ("Sideslip β", "deg")]
NEW_URL = "/tracker/new"
GROUPS = {"ongoing": "Ongoing", "completed": "Completed"}
fold_at_start("tracker-log")  # Recent writes: one click away


def preview_url(link_id: str) -> str:
    return f"/tracker/preview?link={quote(link_id)}"


def edit_url(link_id: str = "") -> str:
    return f"/tracker/link?link={quote(link_id)}" if link_id else "/tracker/link"


def _crumbs(*parts: tuple[str, str]) -> None:
    """Projects › Run matrix › ...: (text, url) pairs, the last one the current page."""
    with ui.row().classes("as-crumbs w-full"):
        ui.link("Projects", "/").classes("as-crumb-link").mark("crumb-projects")
        for text, url in parts[:-1]:
            ui.label("›").classes("as-crumb-sep")
            ui.link(text, url).classes("as-crumb-link").mark("crumb-tracker")
        ui.label("›").classes("as-crumb-sep")
        ui.label(parts[-1][0]).classes("as-crumb-current as-truncate").mark("crumb-page")


def status_pill(status: str) -> ui.label:
    if not status:
        return ui.label("blank").classes("as-muted")
    return ui.label(status).classes(f"as-pill as-pill-{PILL_TONES.get(status, 'pending')}")


def legend() -> None:
    with ui.row().classes("as-legend w-full"):
        for key, label, _statuses in SEGMENTS:
            with ui.row().classes("as-legend-item"):
                ui.element("span").classes(f"as-swatch as-mseg-{key}")
                ui.label(label)
        with ui.row().classes("as-legend-item"):
            ui.element("span").classes("as-swatch as-mseg-none")
            ui.label("No status yet")


def order_choice(value: str, on_change=None) -> ui.toggle:
    """Which solver order a sheet takes: any, or only the cases a job ran at 1st or 2nd order."""
    with ui.column().classes("w-full gap-1"):
        ui.label("Solver order").classes("as-strong")
        toggle = ui.toggle({"": "Any", **ORDERS}, value=value if value in ORDERS else "", on_change=on_change).props(
            "dense no-caps unelevated toggle-color=primary").classes("as-toggle")
        hint("Read from the config each job ran with (MUSCL_FLOW on is 2nd order), so it does not depend on the "
             "note. A job that kept no config counts as 2nd order only with #2nd_order in its note.")
    return toggle


def stack_cell() -> ui.column:
    """A table cell whose lines stack (a name over its hint)."""
    return ui.column().classes("as-td as-td-stack")


def when_text(moment: datetime) -> str:
    today = datetime.now().date()
    return moment.strftime("Today %H:%M" if moment.date() == today else "%d %b %H:%M")


def sweep_text(report_: LinkReport) -> str:
    levels = report_.matrix.levels
    counts = " × ".join(f"{max(1, len(level))} {axis}" for level, axis in zip(levels, AXES))
    return f"{counts} = {len(report_.matrix.rows)} runs"


def _log_text(entry) -> str:
    if entry.error:
        return f"not written: {entry.error}"
    if entry.trigger == "new-sheet":
        return "added from the template"
    if entry.trigger == "edit":
        return f"{entry.written} run{'' if entry.written == 1 else 's'} edited"
    text = f"{entry.written} status{'' if entry.written == 1 else 'es'} written"
    return text + (f", completed on {entry.completed_on:%Y-%m-%d}" if entry.completed_on else "")
