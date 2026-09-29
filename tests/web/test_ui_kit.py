import pytest
from nicegui.testing import User

from aerosuite.engine.jobs.runner import CaseState, JobState
from aerosuite.web.ui_kit import pill_text, pill_tone

TONES = {"CONVERGED": "done", "DONE": "done", "RUNNING": "running", "FAILED": "failed",
         "UNCONVERGED": "unconverged", "PENDING": "pending", "QUEUED": "pending", "NOT_RUN": "pending",
         "CANCELLED": "cancelled"}


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


@pytest.mark.parametrize("status, tone", TONES.items())
def test_pill_tone_maps_every_case_and_job_status(status, tone):
    assert pill_tone(status) == tone


def test_pill_tone_falls_back_and_reads_enum_values():
    assert pill_tone("SOMETHING_NEW") == "pending"
    assert pill_tone(CaseState.RUNNING) == "running"
    assert pill_tone(JobState.DONE) == "done"
    assert pill_text(CaseState.RUNNING) == "RUNNING"
    assert pill_text("NOT_RUN") == "Not run"


async def test_pills_colour_every_status_and_keep_its_text(user: User):
    await user.open("/_test/kit")
    for status, tone in TONES.items():
        label = _element(user, f"t-pill-{status}")
        assert f"as-pill-{tone}" in label.classes
        assert label.text == ("Not run" if status == "NOT_RUN" else status)


async def test_banners_carry_their_kind_and_text(user: User):
    await user.open("/_test/kit")
    for kind in ("info", "warning", "error", "success"):
        label = _element(user, f"t-banner-{kind}")
        assert label.text == f"{kind} text"
        assert f"as-banner-{kind}" in label.parent_slot.parent.classes


async def test_tiles_cards_and_buttons(user: User):
    await user.open("/_test/kit")
    assert _element(user, "t-tile").text == "3"
    assert "as-tile-danger" in _element(user, "t-tile-danger").parent_slot.parent.classes
    assert "as-card" in _element(user, "t-card").classes
    assert "as-btn-primary" in _element(user, "t-primary").classes
    assert "as-btn-danger" in _element(user, "t-danger").classes
    assert _element(user, "t-ok").text == "All good"


from aerosuite.web.ui_kit import sci


def test_sci_is_three_significant_figures_with_a_plain_exponent():
    assert (sci(34769586), sci(26077190), sci(0.00226), sci(5.134e-06), sci(216.65)) == (
        "3.48e7", "2.61e7", "0.00226", "5.13e-6", "217")
