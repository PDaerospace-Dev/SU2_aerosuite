"""SU2 reference beside your config: search options, Insert one, Find in the full file."""
import html
from typing import Callable, Optional

from nicegui import ui

from ..engine.errors import AeroSuiteError
from ..engine.reference import RefOption, find_lines, load_reference, read_reference_text, search
from .picker import pick_path
from .ui_kit import field, flat_button, hint, secondary_button

WINDOW = 8  # lines shown on each side of a Find match


def _window_html(text: str, line_no: int) -> str:
    lines = text.splitlines()
    start = max(1, line_no - WINDOW)
    end = min(len(lines), line_no + WINDOW)
    rows = []
    for number in range(start, end + 1):
        content = html.escape(lines[number - 1])
        if number == line_no:
            content = f"<mark>{content}</mark>"
        rows.append(f"{number:>5}  {content}")
    return '<pre style="font-size:12px;margin:0;white-space:pre-wrap">' + "\n".join(rows) + "</pre>"


def reference_panel(
    on_insert: Callable[[RefOption], Optional[str]],
    in_config: Callable[[], set[str]],
) -> Callable[[], None]:
    """Build the panel; returns a function that redraws the search results."""
    state = {"options": load_reference(), "text": read_reference_text(),
             "query": "", "find": "", "matches": [], "index": -1}

    source = hint("config_template.cfg").mark("ref-source")
    error = ui.label("").classes("as-error-text").mark("ref-error")
    field(ui.input("Search options", on_change=lambda e: on_search(e.value))).classes("w-full").mark("ref-search")
    note = hint("").mark("ref-insert-note")
    results = ui.column().classes("w-full gap-1")

    def render_results() -> None:
        results.clear()
        found = search(state["options"], state["query"])
        present = in_config()
        with results:
            if state["query"].strip() and not found:
                ui.label("No options match").classes("as-muted").mark("ref-no-results")
            for option in found:
                with ui.row().classes("w-full items-start no-wrap gap-2 py-2").style(
                        "border-top: 1px solid var(--as-hairline)"):
                    with ui.column().classes("grow gap-0"):
                        ui.label(option.line).classes("as-mono").mark(f"ref-result-{option.key}")
                        ui.label(option.description or "(no description)").classes("as-hint")
                        if option.section:
                            ui.label(option.section).classes("as-hint").mark(
                                f"ref-section-{option.key}")
                    if option.key in present:
                        ui.label("In config").classes("as-pill as-pill-done").mark(f"ref-in-config-{option.key}")
                    else:
                        secondary_button("Insert", on_click=lambda o=option: insert(o), icon="add").props(
                            "dense").mark(f"ref-insert-{option.key}")

    def on_search(value: Optional[str]) -> None:
        state["query"] = value or ""
        note.text = ""
        render_results()

    def insert(option: RefOption) -> None:
        message = on_insert(option)
        render_results()
        note.text = message or f"Inserted {option.key}"

    ui.label("Find in the full file").classes("as-label mt-2")
    with ui.row().classes("w-full items-center no-wrap"):
        find_box = field(ui.input("Find")).classes("grow").mark("ref-find")
        flat_button("Find next", on_click=lambda: find_next()).mark("ref-find-next")
    status = hint("").mark("ref-find-status")
    window = ui.html("", sanitize=False).classes("w-full").mark("ref-window")

    def find_next() -> None:
        query = (find_box.value or "").strip()
        if query != state["find"]:
            state["find"] = query
            state["matches"] = find_lines(state["text"], query)
            state["index"] = -1
        if not state["matches"]:
            status.text = "No match"
            window.content = ""
            return
        state["index"] = (state["index"] + 1) % len(state["matches"])
        line_no = state["matches"][state["index"]]
        status.text = f"Match {state['index'] + 1} of {len(state['matches'])} — line {line_no}"
        window.content = _window_html(state["text"], line_no)

    async def load_other() -> None:
        path = await pick_path("Choose a reference config", mode="file", suffixes=(".cfg",))
        if path is None:
            return
        try:
            options = load_reference(path)
            text = read_reference_text(path)
        except AeroSuiteError as exc:
            error.text = str(exc)
            return
        state.update(options=options, text=text, find="", matches=[], index=-1)
        source.text = path.name
        error.text = ""
        status.text = ""
        window.content = ""
        render_results()

    flat_button("Load another reference…", on_click=load_other).mark("ref-load")
    render_results()
    return render_results
