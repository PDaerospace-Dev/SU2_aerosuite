"""Where a run's cases start from, on the Run page and in the rerun dialog: the choice (as the sweep says, each
case's own last solution, from scratch) and, under it, what each selected case starts from (engine/jobs/plan.py's
preview_starts) in words, folded into groups that start from the same kind of solution."""
from __future__ import annotations

from typing import Callable, NamedTuple, Optional, Sequence

from nicegui import ui

from ..engine.jobs.plan import Start
from .sweep_view import detect_rule
from .ui_kit import hint

MODE_LABELS = {"sweep": "As the sweep says", "last": "Each case's own last solution", "scratch": "From scratch"}
SINGLE_LABELS = {"sweep": "As set up", "last": "Its own last solution", "scratch": "From scratch"}
LAST_WORDS = "its run folder's solution, or the one a failed run started from while that is kept"
TAGS = {"own": "own", "kept": "kept", "case": "from case", "after": "after it runs", "running": "waits",
        "folder": "folder", "attempt": "attempt", "scratch": "scratch", "none": "none yet"}
PER_CASE = ("case", "after", "running")  # each case its own line: the case it starts from differs


def rule_words(cases: Sequence) -> str:
    """The sweep's own restarts in a few words (Sweep page › Restarts)."""
    rule, _, differing = detect_rule(cases)
    words = {"none": "every case from scratch",
             "previous": "each case from the previous one; the first of each altitude from scratch",
             "custom": "each from its solution in a folder"}[rule]
    return words + (f" ({len(differing)} set differently)" if differing else "")


def mode_words(mode: str, cases: Sequence) -> str:
    return {"sweep": f"Sweep page › Restarts: {rule_words(cases)}", "last": LAST_WORDS,
            "scratch": "no solution, whatever the sweep says"}[mode]


def start_text(start: Start, many: bool = False) -> str:
    """Where `start.case` starts from, in words (`many`: said of a group of cases)."""
    their = "their" if many else "its"
    source = start.source
    return {
        "own": f"{their} own last solution, in {their} run folder" if many else "its own last solution",
        "kept": f"the solution {their} failed run started from, kept by job {source}",
        "case": f"{source}'s solution",
        "after": f"{source}'s, once it has run in this batch",
        "running": f"{source}'s, once it finishes in the running job",
        "folder": f"a solution in {source}",
        "attempt": "a solution from an earlier attempt",
        "scratch": f"from scratch: {source} has no solution yet" if source else "from scratch",
        "none": "no solution yet: choose another start",
    }[start.kind]


class StartGroup(NamedTuple):
    kind: str
    text: str
    cases: list[str]


def start_groups(starts: Sequence[Start]) -> list[StartGroup]:
    """The cases by what they start from, in case order: those that start from the same kind of solution (and the
    same job or folder) together; a case that starts from another case's solution on its own line."""
    groups: list[StartGroup] = []
    index: dict[tuple, int] = {}
    for start in starts:
        key = (start.kind, start.source) if start.kind not in PER_CASE else (start.kind, start.case)
        if key in index:
            groups[index[key]].cases.append(start.case)
            continue
        index[key] = len(groups)
        groups.append(StartGroup(start.kind, "", [start.case]))
    by_case = {start.case: start for start in starts}
    return [group._replace(text=start_text(by_case[group.cases[0]], len(group.cases) > 1)) for group in groups]


def summary(starts: Sequence[Start]) -> str:
    """The folded preview's line: how many start from each kind, e.g. "6 kept" or "2 from case · 4 after it runs"."""
    counts: dict[str, int] = {}
    for start in starts:
        counts[start.kind] = counts.get(start.kind, 0) + 1
    return " · ".join(f"{count} {TAGS[kind]}" for kind, count in counts.items())


def _tag(kind: str):
    return ui.label(TAGS[kind]).classes(f"as-start-tag as-start-{kind}")


def start_choice(mode: str, cases: Sequence, on_change: Callable[[str], None], single: bool = False,
                 mark: str = "start-mode") -> None:
    """The three ways to start, and a line on the chosen one."""
    ui.label("Starts from").classes("as-run-head")
    ui.radio(SINGLE_LABELS if single else MODE_LABELS, value=mode, on_change=lambda e: on_change(e.value)).props(
        "dense").classes("as-start-choice").mark(mark)
    hint(mode_words(mode, cases)).mark(f"{mark}-words")


def start_preview(starts: Sequence[Start], opened: bool, on_toggle: Callable[[bool], None],
                  error: Optional[str] = None) -> None:
    """What each case starts from, folded under one line that counts them."""
    if error:
        hint(error).classes("as-error-text").mark("starts-error")
        return
    if not starts:
        return
    noun = f"{len(starts)} case{'' if len(starts) == 1 else 's'}"
    with ui.expansion("What each starts from", caption=f"{noun} · {summary(starts)}", value=opened,
                      on_value_change=lambda e: on_toggle(e.value)).props("dense dense-toggle").classes(
            "as-starts w-full").mark("starts"):
        for group in start_groups(starts):
            if group.kind in PER_CASE:
                with ui.column().classes("as-start-line w-full gap-0").mark(f"start-{group.cases[0]}"):
                    with ui.row().classes("items-center no-wrap w-full gap-2"):
                        ui.label(group.cases[0]).classes("as-mono as-start-name grow min-w-0")
                        _tag(group.kind)
                    ui.label(f"← {group.text}").classes("as-muted as-small")
                continue
            with ui.column().classes("as-start-group w-full gap-1").mark(f"start-{group.cases[0]}"):
                with ui.row().classes("items-start no-wrap gap-2 w-full"):
                    _tag(group.kind)
                    ui.label(group.text).classes("as-muted as-small grow min-w-0")
                with ui.row().classes("gap-1"):
                    for name in group.cases:
                        ui.label(name).classes("as-mono as-start-chip")
