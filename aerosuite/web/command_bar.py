"""The top bar's search: one box that goes anywhere. Ctrl K (⌘K), or / outside a text field, opens it too.

What it finds: the places (Projects, Run matrix, Cluster, Settings), the open project's steps, cases and ParaView files,
the recent projects, the linked run-matrix sheets, the calculators and the Web UI guide's sections. Arrow keys move,
Enter goes, Esc closes."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from nicegui import ui

GROUPS = ["Go to", "This project", "Projects", "Run matrix", "Tools", "ParaView", "Cases", "Help"]
PER_GROUP = {"Cases": 8, "Help": 4}  # at most this many of a group (default PER_GROUP_DEFAULT)
PER_GROUP_DEFAULT = 6
EMPTY_GROUPS = ("Go to", "Projects")  # shown before anything is typed, with the featured commands
OPEN_EVENT = "as-command-open"
# Ctrl K / ⌘K anywhere (the browser's own Ctrl K is its search bar: not here), / outside a text field
KEYS_JS = f"""
<script>
if (!window.asCommandKeys) {{
  window.asCommandKeys = true;
  document.addEventListener('keydown', (e) => {{
    const typing = e.target.closest('input, textarea, select, [contenteditable="true"]');
    if (((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'k') || (e.key === '/' && !typing && !e.ctrlKey)) {{
      e.preventDefault();
      emitEvent('{OPEN_EVENT}');
    }}
  }});
}}
</script>
"""


@dataclass(frozen=True)
class Command:
    key: str  # its marker is command-<key>
    group: str  # one of GROUPS
    label: str
    icon: str
    run: Callable[[], Any]
    hint: str = ""  # shown on the right, and found by
    words: str = ""  # more text it is found by (not shown)
    featured: bool = False  # shown before anything is typed, whatever its group


def matches(commands: list[Command], query: str) -> list[Command]:
    """The commands that have every word typed (in their label, hint, group or words), grouped in GROUPS order:
    in a group, labels that start with the first word first, then labels that have it, then the rest."""
    words = query.lower().split()
    found: dict[str, list[tuple[int, int, Command]]] = {}
    for order, command in enumerate(commands):
        if not words:
            if command.group in EMPTY_GROUPS or command.featured:
                found.setdefault(command.group, []).append((0, order, command))
            continue
        text = f"{command.label} {command.hint} {command.group} {command.words}".lower()
        if all(word in text for word in words):
            label = command.label.lower()
            rank = 0 if label.startswith(words[0]) else 1 if words[0] in label else 2
            found.setdefault(command.group, []).append((rank, order, command))
    result = []
    for group in GROUPS:
        ranked = sorted(found.get(group, []), key=lambda item: item[:2])
        result += [command for _, _, command in ranked[:PER_GROUP.get(group, PER_GROUP_DEFAULT)]]
    return result


class CommandBar:
    """The search box in the top bar, and its palette. `sources` lists the commands each time it opens (projects,
    cases and flow files change)."""

    def __init__(self, sources: Callable[[], list[Command]]) -> None:
        self.sources = sources
        self.commands: list[Command] = []
        self.shown: list[Command] = []
        self.index = 0
        self.rows: list[ui.element] = []
        with ui.row().classes("as-search no-wrap").props('tabindex=0 role=button aria-label="Search"').mark(
                "command-search") as box:
            ui.icon("search", size="18px")
            ui.label("Search projects, cases, tools…").classes("as-search-text as-truncate")
            ui.label("Ctrl K").classes("as-kbd")
        box.on("click", self.open)
        box.on("keydown.enter", self.open)
        with ui.dialog().props("position=top").mark("command-palette") as self.dialog, \
                ui.card().classes("as-palette"):
            self.input = ui.input(placeholder="Search projects, cases, tools…").props(
                "dense borderless autofocus").classes("as-palette-input w-full").mark("command-input")
            with self.input.add_slot("prepend"):
                ui.icon("search")
            self.results = ui.column().classes("as-palette-results w-full").mark("command-results")
        self.input.on_value_change(lambda e: self.render(e.value or ""))
        self.input.on("keydown.down.prevent", lambda: self.move(1))
        self.input.on("keydown.up.prevent", lambda: self.move(-1))
        self.input.on("keydown.enter", lambda: self.go(self.index))
        ui.add_body_html(KEYS_JS)
        ui.on(OPEN_EVENT, self.open)

    def open(self) -> None:
        self.commands = self.sources()
        self.input.value = ""
        self.render("")
        self.dialog.open()
        self.input.run_method("focus")

    def render(self, query: str) -> None:
        self.shown = matches(self.commands, query)
        self.index = 0
        self.rows = []
        self.results.clear()
        with self.results:
            if not self.shown:
                ui.label("Nothing matches. Try a project, a case (M0p8), a sheet or a tool.").classes(
                    "as-muted as-palette-none").mark("command-none")
                return
            group = None
            for i, command in enumerate(self.shown):
                if command.group != group:
                    group = command.group
                    ui.label(group).classes("as-palette-group")
                with ui.row().classes("as-palette-item no-wrap" + (" as-palette-on" if i == 0 else "")).mark(
                        f"command-{command.key}") as row:
                    ui.icon(command.icon, size="18px").classes("as-palette-icon")
                    ui.label(command.label).classes("as-palette-label as-truncate")
                    if command.hint:
                        ui.label(command.hint).classes("as-palette-hint as-truncate")
                row.on("click", lambda _, i=i: self.go(i))
                self.rows.append(row)

    def move(self, step: int) -> None:
        if not self.rows:
            return
        self.rows[self.index].classes(remove="as-palette-on")
        self.index = (self.index + step) % len(self.rows)
        self.rows[self.index].classes(add="as-palette-on")
        ui.run_javascript(f"document.getElementById('c{self.rows[self.index].id}')"
                          f"?.scrollIntoView({{block: 'nearest'}})")

    def go(self, index: int) -> None:
        if not 0 <= index < len(self.shown):
            return
        command: Optional[Command] = self.shown[index]
        self.dialog.close()
        command.run()
