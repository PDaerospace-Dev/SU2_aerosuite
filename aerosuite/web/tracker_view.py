"""The run matrix's statuses as its pages show them, kept in one table: each Status text's pill, its square on the
coverage views and the segment of a sheet's progress bar it counts in. NiceGUI-free."""
from __future__ import annotations

from html import escape
from typing import Mapping

# Status (the sheet's text): (the pill's tone, the coverage square's colour, the progress bar's segment)
STATUSES = {
    "Converged": ("done", "converged", "converged"),
    "Not Converged": ("unconverged", "not", "not"),
    "Failed": ("failed", "failed", "not"),
    "Diverged": ("failed", "failed", "not"),
    "Running": ("running", "live", "live"),
    "Pending": ("pending", "live", "live"),
    "Hold": ("cancelled", "hold", "hold"),
}
PILL_TONES = {status: tones[0] for status, tones in STATUSES.items()}
SQUARE_TONES = {status: tones[1] for status, tones in STATUSES.items()}
_SEGMENT_LABELS = {"converged": "Converged", "not": "Not converged / failed", "live": "Running / queued",
                   "hold": "Hold"}
# (key, label, the statuses it counts), in the bar's order
SEGMENTS = [(key, label, tuple(status for status, tones in STATUSES.items() if tones[2] == key))
            for key, label in _SEGMENT_LABELS.items()]
# what a run's Status can be set to by hand (the sheet's text: its label), "" blanking it
STATUS_CHOICES = {"Converged": "Converged", "Not Converged": "Not converged", "Diverged": "Diverged",
                  "Failed": "Failed", "Hold": "Hold", "": "Blank"}


def pill_html(status: str) -> str:
    return (f'<span class="as-pill as-pill-{PILL_TONES.get(status, "pending")}">{escape(status or "blank")}</span>'
            if status else '<span class="as-muted">blank</span>')


def bar_html(counts: Mapping[str, int], total: int) -> str:
    """A sheet's statuses as one bar: converged, not converged, running, hold; the rest (no job) is the track."""
    spans = []
    for key, _label, statuses in SEGMENTS:
        share = sum(counts.get(status, 0) for status in statuses) / total * 100 if total else 0
        if share:
            spans.append(f'<span class="as-mseg-{key}" style="width: {share:.2f}%"></span>')
    return f'<div class="as-mbar">{"".join(spans)}</div>'


def bar_text(counts: Mapping[str, int], total: int) -> str:
    parts = [(sum(counts.get(s, 0) for s in statuses), label.split(" /")[0].lower())
             for _key, label, statuses in SEGMENTS]
    blank = total - sum(number for number, _ in parts)
    words = [f"{number} {label}" for number, label in parts if number]
    return " · ".join(words + ([f"{blank} no status"] if blank else [])) or "no runs"
