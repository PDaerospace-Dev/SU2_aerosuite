"""Monitor's Parameters tab: its pure parts, then the tab on the page."""
import math

import pandas as pd
import pytest
from nicegui.testing import User

from aerosuite.engine.project import PROJECT_FILE
from aerosuite.web import monitor_params
from aerosuite.web.layout import project_url
from aerosuite.web.monitor_params import (Window, param_options, plottable_columns, thinned_indices, window_of,
                                          window_range, window_stats, zoom_percent)

A0, A2 = "M0p8_a0_b0", "M0p8_a2_b0"


@pytest.fixture(autouse=True)
def fresh_state():
    """The plots are kept while the server runs: each test starts without any."""
    monitor_params._STATES.clear()
    yield
    monitor_params._STATES.clear()


def _element(user, marker):
    return next(iter(user.find(marker=marker).elements))


def _history(folder, rows=30, columns=("CL", "CD", "Avg_Massflow(outlet)")):
    folder.mkdir(parents=True, exist_ok=True)
    lines = ["Inner_Iter,rms[Rho]," + ",".join(columns)]
    for i in range(rows):
        lines.append(f"{i},{-2 - 0.1 * i}," + ",".join(str(round(k + 1 + 0.01 * i, 4)) for k in range(len(columns))))
    path = folder / "history.csv"
    path.write_text("\n".join(lines) + "\n")
    return path


# -- pure parts -----------------------------------------------------------------------


def test_every_numeric_column_but_the_iteration_counters_can_be_plotted():
    df = pd.DataFrame({"Time_Iter": [0, 0], "Inner_Iter": [0, 1], "rms[Rho]": [-1.0, -2.0], "CL": [0.1, 0.2],
                       "Avg_Massflow(outlet)": [5.0, 5.1], "note": ["a", "b"]})
    assert plottable_columns(df) == ["rms[Rho]", "CL", "Avg_Massflow(outlet)"]
    assert plottable_columns(None) == []


def test_stats_are_the_mean_and_range_of_the_last_rows_and_the_latest_value():
    stats = window_stats([9.0, 1.0, 2.0, 3.0], 3)
    assert stats.mean == pytest.approx(2.0) and stats.latest == 3.0 and stats.spread == pytest.approx(2.0)
    assert window_stats([1.0, 2.0], 100).mean == pytest.approx(1.5)  # fewer rows than asked: all of them
    stats = window_stats([1.0, math.nan, 3.0, math.nan], 3)  # not-a-number rows are left out
    assert stats.mean == pytest.approx(3.0) and stats.latest == 3.0
    assert window_stats([], 5) == (None, None, None)


def test_thinning_keeps_the_last_row():
    assert thinned_indices(5, 10) == [0, 1, 2, 3, 4]
    indices = thinned_indices(10001, 2000)
    assert len(indices) <= 2000 and indices[0] == 0 and indices[-1] == 10000


def test_a_zoom_event_from_the_slider_or_the_wheel():
    assert zoom_percent({"type": "datazoom", "start": 10, "end": 60.5}) == (10.0, 60.5)
    assert zoom_percent({"batch": [{"start": 25, "end": 100}]}) == (25.0, 100.0)
    assert zoom_percent({"batch": []}) is None and zoom_percent(None) is None


def test_a_zoomed_window_stays_on_its_iterations_unless_it_ends_on_the_newest():
    assert window_of(0, 100, 0, 1000) is None  # the whole run: not a zoom
    back = window_of(20, 50, 0, 1000)
    assert back == Window(200, 500, following=False)
    assert window_range(back, 0, 1400) == (200, 500)  # the run grew: the same iterations
    live = window_of(80, 100, 0, 1000)
    assert live == Window(800, 1000, following=True)
    assert window_range(live, 0, 1400) == (1200, 1400)  # the same 200 iterations, ending on the newest
    assert window_range(None, 0, 1400) is None


def test_options_have_one_line_per_parameter_in_the_file_and_the_zoom():
    df = pd.DataFrame({"Inner_Iter": [0, 1, 2], "CL": [0.1, math.nan, 0.3], "CD": [1.0, 2.0, 3.0]})
    options = param_options([0, 1, 2], df, ["CL", "gone", "CD"], {"CL": "#111", "gone": "#222", "CD": "#333"},
                            None, 2000)
    assert [(s["name"], s["color"]) for s in options["series"]] == [("CL", "#111"), ("CD", "#333")]
    assert options["series"][0]["data"] == [[0, 0.1], [1, None], [2, 0.3]]  # a gap, not a NaN
    assert [(z["type"], z["start"], z["end"]) for z in options["dataZoom"]] == [("inside", 0, 100),
                                                                                  ("slider", 0, 100)]
    zoomed = param_options([0, 1, 2], df, ["CL"], {"CL": "#111"}, (1, 2), 2000)
    assert all(z["startValue"] == 1 and z["endValue"] == 2 and "start" not in z for z in zoomed["dataZoom"])


# -- the tab ---------------------------------------------------------------------------


async def _open(user, project_dir):
    await user.open(project_url("monitor", project_dir))


async def _add(user, *names):
    user.find(marker="params-add").click()
    await user.should_see(marker="params-pick-confirm")
    with user:
        for name in names:
            _element(user, f"params-pick-{name}").set_value(True)
    user.find(marker="params-pick-confirm").click()
    await user.should_not_see(marker="params-pick-confirm")
    await user.should_see(marker=f"params-value-{names[-1]}")  # the plot is drawn once the picker's answer is taken


async def _open_file(user, path, eventually):
    user.find(marker="monitor-open-file").click()
    await user.should_see(marker="picker-path")
    user.find(marker="picker-path").type(str(path))
    user.find(marker="picker-use").click()
    await eventually(lambda: _element(user, "monitor-source").text == f"{path.parent.name}/{path.name}")


async def test_the_page_opens_on_convergence_and_parameters_is_a_second_tab(user: User, ready_project):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    assert "as-tab-on" in _element(user, "monitor-tab-convergence").classes
    await user.should_see(marker="monitor-normalize")
    await user.should_not_see(marker="params-add")
    await user.should_not_see(marker="monitor-average")
    user.find(marker="monitor-tab-parameters").click()
    await user.should_see(marker="params-add")
    await user.should_see(marker="monitor-average")
    await user.should_not_see(marker="monitor-normalize")  # no Normalize and no Columns on this tab
    await user.should_not_see(marker="params-values")  # no plots yet: nothing to list
    assert _element(user, "monitor-follow").visible and _element(user, "monitor-stop").visible  # shared


async def test_adding_plots_of_an_opened_files_columns(user: User, ready_project, tmp_path, eventually):
    project_dir, _ = ready_project
    before = (project_dir / PROJECT_FILE).read_text()
    path = _history(tmp_path / "old_run")
    await _open(user, project_dir)
    await _open_file(user, path, eventually)
    user.find(marker="monitor-tab-parameters").click()
    assert _element(user, "monitor-iteration").text == "iteration 29 · updates every 2 s"
    user.find(marker="params-add").click()
    await user.should_see(marker="params-pick-rms[Rho]")  # every column, not only residuals and CL/CD
    await user.should_not_see(marker="params-pick-Inner_Iter")
    user.find(marker="params-pick-confirm").click()
    await user.should_see("Tick at least one parameter")
    user.find(marker="params-pick-cancel").click()
    await _add(user, "CL", "CD")
    await _add(user, "Avg_Massflow(outlet)")
    first, second = _element(user, "params-chart-1"), _element(user, "params-chart-2")
    assert [s["name"] for s in first.options["series"]] == ["CL", "CD"]  # one plot, one value axis
    assert [s["name"] for s in second.options["series"]] == ["Avg_Massflow(outlet)"]
    assert len(first.options["series"][0]["data"]) == 30
    assert _element(user, "params-chip-1-CL").text == "1.29"  # the latest value, on the plot's chip
    # The block on the left: the mean in bold, the latest value on the line below. No iteration there.
    assert _element(user, "params-window").text == "mean of the last 100 iterations"
    assert _element(user, "params-mean-CL").text == "1.145"
    assert "as-value-mean" in _element(user, "params-mean-CL").classes
    assert _element(user, "params-latest-CL").text == "latest 1.29 · range 0.29"
    assert (project_dir / PROJECT_FILE).read_text() == before  # nothing of this is written to project.json


async def test_the_averaged_iterations_can_be_chosen(user: User, ready_project, tmp_path, eventually):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await _open_file(user, _history(tmp_path / "old_run"), eventually)
    user.find(marker="monitor-tab-parameters").click()
    await _add(user, "CL")
    assert _element(user, "monitor-average").value == "100"  # the Results page's number to start with
    user.find(marker="monitor-average").clear().type("10").trigger("blur")
    assert _element(user, "params-mean-CL").text == "1.245"  # rows 20..29
    assert _element(user, "params-window").text == "mean of the last 10 iterations"
    user.find(marker="monitor-average").clear().type("0").trigger("blur")
    await user.should_see("At least 1")
    assert _element(user, "params-mean-CL").text == "1.245"


async def test_new_rows_update_the_plot_and_the_values_in_place(user: User, ready_project, tmp_path, eventually,
                                                                monkeypatch):
    from aerosuite.web.pages import monitor
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0.05)
    project_dir, _ = ready_project
    path = _history(tmp_path / "live_run", rows=10)
    await _open(user, project_dir)
    await _open_file(user, path, eventually)
    user.find(marker="monitor-tab-parameters").click()
    await _add(user, "CL")
    chart = _element(user, "params-chart-1")
    assert len(chart.options["series"][0]["data"]) == 10
    with path.open("a") as fh:
        for i in range(10, 15):
            fh.write(f"{i},-3,2.0,2.0,2.0\n")
    await eventually(lambda: len(chart.options["series"][0]["data"]) == 15)
    assert _element(user, "params-chart-1") is chart  # the same chart: a zoom or a tooltip survives the update
    assert _element(user, "params-chip-1-CL").text == "2"
    assert _element(user, "monitor-iteration").text.startswith("iteration 14 ·")


async def test_a_zoom_is_kept_across_updates_and_reset_shows_the_whole_run(user: User, ready_project, tmp_path,
                                                                           eventually, monkeypatch):
    from aerosuite.web.pages import monitor
    monkeypatch.setattr(monitor, "POLL_SECONDS", 0.05)
    project_dir, _ = ready_project
    path = _history(tmp_path / "live_run", rows=101)  # iterations 0..100
    await _open(user, project_dir)
    await _open_file(user, path, eventually)
    user.find(marker="monitor-tab-parameters").click()
    await _add(user, "CL")
    await _add(user, "CD")
    chart, other = _element(user, "params-chart-1"), _element(user, "params-chart-2")
    user.find(marker="params-chart-1").trigger("chart:datazoom", {"batch": [{"start": 20, "end": 50}]})
    with path.open("a") as fh:
        for i in range(101, 201):
            fh.write(f"{i},-3,2.0,2.0,2.0\n")
    await eventually(lambda: len(chart.options["series"][0]["data"]) == 201)
    assert [(z["startValue"], z["endValue"]) for z in chart.options["dataZoom"]] == [(20, 50), (20, 50)]
    assert all(z.get("start") == 0 and z.get("end") == 100 for z in other.options["dataZoom"])  # zoomed on its own
    user.find(marker="params-zoom-reset-1").click()
    assert all(z.get("start") == 0 and z.get("end") == 100 for z in chart.options["dataZoom"])


async def test_changing_and_removing_a_plot(user: User, ready_project, tmp_path, eventually):
    project_dir, _ = ready_project
    await _open(user, project_dir)
    await _open_file(user, _history(tmp_path / "old_run"), eventually)
    user.find(marker="monitor-tab-parameters").click()
    await _add(user, "CL")
    user.find(marker="params-edit-1").click()
    await user.should_see(marker="params-pick-confirm")
    assert _element(user, "params-pick-CL").value is True  # the plot's own parameters come ticked
    with user:
        _element(user, "params-pick-CL").set_value(False)
        _element(user, "params-pick-CD").set_value(True)
    user.find(marker="params-pick-confirm").click()
    await user.should_see(marker="params-mean-CD")
    assert [s["name"] for s in _element(user, "params-chart-1").options["series"]] == ["CD"]
    await user.should_not_see(marker="params-mean-CL")
    user.find(marker="params-remove-1").click()
    await user.should_not_see(marker="params-chart-1")
    await user.should_not_see(marker="params-values")


async def test_plots_stay_for_another_case_and_a_reload_and_say_what_a_file_lacks(user: User, ready_project,
                                                                                    tmp_path, eventually):
    project_dir, _ = ready_project
    _history(project_dir / "runs" / A0, columns=("CL", "CD"))
    await _open(user, project_dir)
    await _open_file(user, _history(tmp_path / "old_run"), eventually)
    user.find(marker="monitor-tab-parameters").click()
    await _add(user, "CL", "Avg_Massflow(outlet)")
    await user.open(project_url("monitor", project_dir))  # a reload: the tab and the plot are still there
    assert "as-tab-on" in _element(user, "monitor-tab-parameters").classes
    await user.should_see(marker="params-plot-1")
    # A case that has not run: the plot is kept, with nothing to draw.
    await user.should_see("This case has not run yet.")
    await user.should_see(marker="params-empty-1")
    assert _element(user, "params-latest-CL").text == "no history yet"
    # A file without one of the plot's columns: the other is drawn, the missing one says so.
    await _open_file(user, project_dir / "runs" / A0 / "history.csv", eventually)
    assert [s["name"] for s in _element(user, "params-chart-1").options["series"]] == ["CL"]
    assert _element(user, "params-chip-1-Avg_Massflow(outlet)").text == "not in this file"
    assert _element(user, "params-latest-Avg_Massflow(outlet)").text == "not in this file"
