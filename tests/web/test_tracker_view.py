"""The run matrix's status table: one row per Status the engine writes, used by every page."""
from collections import Counter

from aerosuite.engine.tracker import DIVERGED, STATUS_TEXT
from aerosuite.engine.tracker_links import HAND_STATUSES
from aerosuite.web.tracker_view import (PILL_TONES, SEGMENTS, SQUARE_TONES, STATUS_CHOICES, STATUSES, bar_html,
                                        bar_text, pill_html)


def test_every_status_the_engine_writes_has_a_pill_a_square_and_a_bar_segment():
    written = set(STATUS_TEXT.values()) | {DIVERGED}
    assert set(STATUSES) == written == set(PILL_TONES) == set(SQUARE_TONES)
    counted = [status for _key, _label, statuses in SEGMENTS for status in statuses]
    assert sorted(counted) == sorted(written)  # each in one segment
    assert set(STATUS_CHOICES) == set(HAND_STATUSES)  # what the coverage page offers is what the engine takes


def test_the_bar_and_its_words():
    counts = Counter({"Converged": 2, "Failed": 1, "Diverged": 1, "Running": 1, "": 3})
    assert bar_text(counts, 8) == "2 converged · 2 not converged · 1 running · 3 no status"
    assert bar_html(counts, 8).count("<span") == 3 and 'as-mseg-converged" style="width: 25.00%"' in bar_html(counts, 8)
    assert bar_text(Counter(), 0) == "no runs"
    assert "as-pill-failed" in pill_html("Diverged") and "blank" in pill_html("")
