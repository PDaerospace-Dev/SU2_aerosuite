"""What the Run page's modules share: its selectors, and small helpers for a job's rows, tones and times."""
from datetime import datetime
from typing import NamedTuple, Optional

from nicegui import ui

from ...engine.jobs.overview import NOT_RUN
from ..jobs import JobView
from ..ui_kit import pill_tone

SELECTORS = [  # (label, statuses to tick; None = every case)
    ("All", None),
    ("Failed", {"FAILED", "BLOCKED"}),
    ("Unconverged", {"UNCONVERGED"}),
    ("Not run", {NOT_RUN}),
    ("None", set()),
]
KEY_VALUES = 6  # a single case's card shows this many of the Results page's chosen parameters


_OUT_OF_MEMORY = "(OUT_OF_MEMORY)"  # ends the preflight warning about a mesh over the limit: the red box says it
_JOB_DOTS = {"done": "done", "running": "running", "failed": "red", "unconverged": "attention", "cancelled": "plain",
             "pending": "plain"}


def _iterations(history) -> Optional[int]:
    """The iterations a history file holds (its rows), or None."""
    if history is None:
        return None
    try:
        with open(history, "rb") as handle:
            rows = sum(1 for _ in handle) - 1
    except OSError:
        return None
    return rows if rows > 0 else None


def _attempt_number(attempt) -> str:
    return attempt.folder.name.split("-", 1)[0].lstrip("0") or "0"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _snapshot(view: JobView) -> tuple:
    """What the page shows from `view`: the active job, each case's row and the job history (and, for a Slurm job,
    each case's Slurm state, node and pending reason; its run time is kept current by the queue panel)."""
    active = view.active
    return (
        (active.id, active.state) if active is not None else None,
        tuple((name, sc.job_id, sc.state, sc.node, sc.reason) for job in view.overview.jobs[:1]
              for name, sc in job.slurm.items()),
        tuple((row.name, row.status, row.job_id, row.failure_tail) for row in view.overview.all_rows),
        tuple((job.id, job.state, job.finished) for job in view.overview.jobs),
        tuple(view.overview.problems),
    )


class _Row(NamedTuple):
    status: str


def _ago(when: datetime) -> str:
    """"just now", "25 min ago", "3 h ago", "2 days ago"."""
    seconds = max(0.0, (datetime.now() - when).total_seconds())
    if seconds < 60:
        return "just now"
    if seconds < 3600:
        return f"{int(seconds // 60)} min ago"
    if seconds < 86400:
        return f"{int(seconds // 3600)} h ago"
    days = int(seconds // 86400)
    return f"{days} day{'' if days == 1 else 's'} ago"


def _tone(status: str) -> str:
    """A tile's colour family: as the pills, with not run apart from queued."""
    return "notrun" if status == NOT_RUN else pill_tone(status)


def _answer(dialog: ui.dialog, value: bool) -> None:
    """Submit a dialog's result and delete it immediately (see the comment in confirm_cancel)."""
    dialog.submit(value)
    dialog.delete()


_START_MODE: dict[str, str] = {}  # each project's "Starts from" choice (START_MODES), kept while the server runs


class _Selection(NamedTuple):
    ticked: list[str]  # the selected cases, in case order
