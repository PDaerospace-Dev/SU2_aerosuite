"""Shared building blocks for every page (NiceGUI only): cards, pills, banners, tiles, tables, fields
and buttons. Pages use these instead of styling widgets themselves; the look lives in theme.py."""
from contextlib import contextmanager
from typing import Any, Callable, Iterator, Literal, Optional, Sequence

from nicegui import ui

from ..engine.jobs.overview import NOT_RUN

Tone = Literal["done", "running", "failed", "unconverged", "pending", "cancelled"]
BannerKind = Literal["info", "warning", "error", "success"]

PILL_TONES: dict[str, Tone] = {
    "CONVERGED": "done", "DONE": "done",
    "RUNNING": "running",
    "FAILED": "failed",
    "UNCONVERGED": "unconverged",
    "PENDING": "pending", "QUEUED": "pending", NOT_RUN: "pending",
    "CANCELLED": "cancelled",
}
BANNER_ICONS = {"info": "info", "warning": "warning", "error": "error", "success": "check_circle"}


def _value(status: Any) -> str:
    """A CaseState/JobState member's value, or the string itself."""
    return str(getattr(status, "value", status))


def pill_tone(status: Any) -> Tone:
    """The colour family of a case or job status; unknown statuses are grey ("pending")."""
    return PILL_TONES.get(_value(status).upper(), "pending")


def pill_text(status: Any) -> str:
    """What a pill says: the status as the pages always named it ("Not run" for NOT_RUN).

    CSS shows it in sentence case ("CONVERGED" reads "Converged"); the element's text is unchanged.
    """
    value = _value(status)
    return "Not run" if value == NOT_RUN else value


def pill(status: Any) -> ui.label:
    return ui.label(pill_text(status)).classes(f"as-pill as-pill-{pill_tone(status)}")


def set_pill(label: ui.label, status: Any) -> None:
    """Change a pill in place (keeps its markers)."""
    label.set_text(pill_text(status))
    label.classes(replace=f"as-pill as-pill-{pill_tone(status)}")


def status_dot(state: str) -> ui.element:
    """A small round dot: a sidebar step badge (done, attention, todo, running, plain, later)."""
    return ui.element("span").classes(f"as-dot as-dot-{state}")


def banner(kind: BannerKind, text: str) -> ui.label:
    """A coloured message box; returns its text label, which is where markers go."""
    with ui.row().classes(f"as-banner as-banner-{kind}"):
        ui.icon(BANNER_ICONS[kind])
        return ui.label(text).classes("grow")


_OPEN_GROUPS: set[str] = set()  # warning groups the user opened (by marker), kept while the server runs


def warning_group(messages: Sequence[str], *, mark: str, label: Optional[str] = None) -> ui.expansion:
    """Warnings folded into one amber row ("3 warnings", or `label`), opened with a click; errors stay banners.

    It stays open or closed as the user left it, also when the page is redrawn."""
    count = len(messages)

    def remember(event) -> None:
        (_OPEN_GROUPS.add if event.value else _OPEN_GROUPS.discard)(mark)

    with ui.expansion(label or f"{count} warning{'' if count == 1 else 's'}", icon="warning", value=mark in _OPEN_GROUPS,
                      on_value_change=remember).classes("as-warn-group w-full").mark(mark) as group:
        for message in messages:
            ui.label(message).classes("as-warn-line")
    return group


def ok_line(text: str) -> ui.label:
    """The clean state: one green dot and a line of text; returns the text label."""
    with ui.row().classes("as-ok-line"):
        status_dot("done")
        return ui.label(text)


@contextmanager
def card(title: Optional[str] = None, subtitle: Optional[str] = None, *,
         flush: bool = False, fold: Optional[str] = None) -> Iterator[ui.column]:
    """A white card; `flush` drops the padding for a card that holds a table; `fold` (a key) gives it a button
    that folds it down to its title row."""
    with ui.column().classes("as-card w-full" + (" as-card-flush" if flush else "")) as box:
        if fold is not None:
            with card_head(title, subtitle):
                ui.space()
                fold_button(box, fold)
        elif title is not None or subtitle is not None:
            card_head(title, subtitle)
        yield box


_FOLDED: set[str] = set()  # cards the user folded (by key), kept while the server runs


def fold_button(box: ui.element, key: str) -> ui.button:
    """A chevron for a card's title row: folds the card `box` down to that row and opens it again. Folded cards
    stay folded when the page is drawn again."""
    def apply() -> None:
        folded = key in _FOLDED
        box.classes(**({"add": "as-card-folded"} if folded else {"remove": "as-card-folded"}))
        button.props(f'icon={"expand_more" if folded else "expand_less"}')
        button.props(f'title="{"Open" if folded else "Fold"} this card"')

    def toggle() -> None:
        (_FOLDED.discard if key in _FOLDED else _FOLDED.add)(key)
        apply()

    button = ui.button(icon="expand_less", color=None, on_click=toggle).props("flat round dense size=sm").mark(
        f"fold-{key}")
    apply()
    return button


def card_head(title: Optional[str] = None, subtitle: Optional[str] = None) -> ui.row:
    """A card's title row; enter it (`with card_head(...):`) to add controls after the title."""
    with ui.row().classes("as-card-head w-full") as head:
        if title is not None:
            ui.label(title).classes("as-card-title")
        if subtitle is not None:
            ui.label(subtitle).classes("as-card-subtitle")
    return head


def summary_tile(label: str, value: object, tone: Optional[Literal["danger"]] = None) -> ui.label:
    """A number with a caption above it; returns the number's label."""
    with ui.column().classes("as-tile" + (f" as-tile-{tone}" if tone else "")):
        ui.label(label).classes("as-tile-label")
        return ui.label(str(value)).classes("as-tile-value")


def field(widget, *, mono: bool = False):
    """Style an input, select or textarea as a form field (outlined box; the label floats above a value)."""
    widget.props("outlined dense").classes("as-field" + (" as-field-mono" if mono else ""))
    return widget


def hint(text: str = "") -> ui.label:
    return ui.label(text).classes("as-hint")


def readonly(text: str, *, mono: bool = False) -> ui.label:
    """A value shown in a field-like box that cannot be edited."""
    return ui.label(text).classes("as-readonly w-full" + (" as-mono" if mono else ""))


def path_field(label: str, *, mark: str, browse_mark: str, title: str,
               mode: Literal["file", "folder", "any"], suffixes: Sequence[str] = ()) -> ui.input:
    """An input for a workstation path with a Browse button that fills it from the picker."""
    with ui.row().classes("w-full items-center no-wrap gap-2"):
        box = field(ui.input(label), mono=True).classes("grow").mark(mark)

        async def browse() -> None:
            from .picker import pick_path  # imported here: the picker itself uses this module's buttons

            chosen = await pick_path(title, mode=mode, suffixes=suffixes)
            if chosen is not None:
                box.value = str(chosen)

        secondary_button("Browse", on_click=browse).mark(browse_mark)
    return box


def table(columns: str) -> ui.grid:
    """A table drawn as a CSS grid: `columns` is its grid-template-columns; each direct child is a cell."""
    return ui.grid().classes("as-table").style(f"grid-template-columns: {columns}")


def th(text: str = "") -> ui.label:
    return ui.label(text).classes("as-th")


def td(text: str = "", *, mono: bool = False, strong: bool = False) -> ui.label:
    return ui.label(text).classes("as-td" + (" as-mono as-muted" if mono else "") + (" as-strong" if strong else ""))


@contextmanager
def td_box() -> Iterator[ui.row]:
    """A cell that holds widgets (a checkbox, a select, a pill)."""
    with ui.row().classes("as-td") as box:
        yield box


def failure_row(text: str) -> ui.label:
    """A red box spanning the whole table row under a failed case; returns the box (markers go on it)."""
    with ui.element("div").classes("as-td-failure").style("grid-column: 1 / -1"):
        return ui.label(text).classes("as-failure")


def _button(text: str, kind: str, on_click: Optional[Callable] = None, icon: Optional[str] = None) -> ui.button:
    return ui.button(text, on_click=on_click, icon=icon, color=None).props("unelevated no-caps").classes(
        f"as-btn as-btn-{kind}")


def primary_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    """The page's one main action (dark)."""
    return _button(text, "primary", on_click, icon)


def secondary_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "secondary", on_click, icon)


def danger_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "danger", on_click, icon)


def flat_button(text: str, on_click: Optional[Callable] = None, *, icon: Optional[str] = None) -> ui.button:
    return _button(text, "flat", on_click, icon)


def chip_button(text: str, on_click: Optional[Callable] = None) -> ui.button:
    """A small filter chip (Run's All / Failed / ... selectors)."""
    return ui.button(text, on_click=on_click, color=None).props("unelevated no-caps dense").classes("as-chip")


def sci(value: float) -> str:
    """Three significant figures with a plain exponent: 34769586 -> '3.48e7', 0.00226 -> '0.00226'."""
    text = f"{value:.3g}"
    if "e" in text:
        mantissa, exponent = text.split("e")
        text = f"{mantissa}e{int(exponent)}"
    return text


def stat(label: str, value: str) -> ui.label:
    """A small caption over a bold value, for summary strips; returns the value label."""
    with ui.column().classes("gap-0"):
        ui.label(label).classes("as-stat-label")
        return ui.label(value).classes("as-stat-value")


def result(label: str, highlight: bool = False) -> ui.label:
    """A calculator result tile; returns its value label."""
    with ui.column().classes("as-result" + (" as-result-hi" if highlight else "")):
        ui.label(label).classes("as-stat-label")
        return ui.label("—").classes("as-result-value")
