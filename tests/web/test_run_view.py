"""The Run page's rules without NiceGUI: layout by study size, groups, counts, durations, time left."""
from aerosuite.engine.jobs.overview import CaseRow
from aerosuite.engine.models import Case
from aerosuite.web.run_view import (case_conditions, case_groups, clock_text, duration_text, layout, status_counts,
                                    time_left)


def _cases(machs=(1.5, 2.0), altitudes=(5.0, 10.0), alphas=range(8)):
    return [Case(name=f"M{m}_{h}km_a{a}", mach=m, alpha=float(a), beta=0.0, altitude_km=h)
            for h in altitudes for m in machs for a in alphas]


def test_layout_follows_the_number_of_cases():
    assert layout([]) == "none"
    assert layout(_cases((0.8,), (None,), (0,))) == "single"
    assert layout(_cases((0.8,), (None,), range(5))) == "list"
    assert layout(_cases((0.8,), (None,), range(40))) == "list"  # one Mach and altitude: nothing to group by
    assert layout(_cases(alphas=range(2))) == "list"  # 8 cases: too few for groups
    assert layout(_cases()) == "groups"


def test_cases_group_by_mach_and_altitude_in_case_order():
    groups = case_groups(_cases(alphas=(0, 2)))
    assert [(g.label, len(g.names)) for g in groups] == [
        ("Mach 1.5 · 5 km", 2), ("Mach 2 · 5 km", 2), ("Mach 1.5 · 10 km", 2), ("Mach 2 · 10 km", 2)]
    assert groups[0].names == ["M1.5_5.0km_a0", "M1.5_5.0km_a2"]
    assert [g.label for g in case_groups(_cases((0.8, 0.9), (None,), (0,)))] == ["Mach 0.8", "Mach 0.9"]


def test_statuses_are_counted_in_a_fixed_order():
    rows = [CaseRow(n, s, None) for n, s in [("a", "CONVERGED"), ("b", "RUNNING"), ("c", "FAILED"),
                                             ("d", "UNCONVERGED"), ("e", "CANCELLED"), ("f", "PENDING"),
                                             ("g", "NOT_RUN"), ("h", "CONVERGED")]]
    assert status_counts(rows) == [("CONVERGED", 2), ("RUNNING", 1), ("PENDING", 1), ("NOT_RUN", 1),
                                   ("UNCONVERGED", 1), ("FAILED", 1), ("CANCELLED", 1)]
    assert status_counts(rows[:1]) == [("CONVERGED", 1)]


def test_durations_and_time_left():
    assert [duration_text(s) for s in (8, 59.6, 400, 3600, 7500)] == ["8 s", "1 min", "6 min 40 s", "1 h", "2 h 5 min"]
    assert time_left(elapsed=600, finished=2, total=5) == 900  # 5 min a case, 3 to go
    assert time_left(elapsed=30, finished=0, total=5) is None  # nothing finished: no guess
    assert time_left(elapsed=600, finished=5, total=5) == 0


def test_the_job_clock_text():
    assert clock_text(600, 2, 5) == "Elapsed 10 min · about 15 min left"
    assert clock_text(30, 0, 5) == "Elapsed 30 s · time left shown after the first case"


def test_a_single_cases_conditions_come_from_its_config():
    text = "SOLVER= RANS\nKIND_TURB_MODEL= SA\nMACH_NUMBER= 0.8 % comment\nAOA= 1.25\nSIDESLIP_ANGLE= 0.0\nITER= 5000\n"
    assert case_conditions(text, "/data/mesh_NACA0012_inv.su2") == [
        ("Solver", "RANS · SA"), ("Mach", "0.8"), ("α (deg)", "1.25"), ("β (deg)", "0.0"),
        ("Iterations (max)", "5000"), ("Mesh", "mesh_NACA0012_inv.su2")]
    assert case_conditions("SOLVER= EULER\nKIND_TURB_MODEL= NONE\n", None) == [("Solver", "EULER")]


def test_board_sections_are_one_grid_per_altitude_and_beta():
    from aerosuite.engine.models import Case
    from aerosuite.web.run_view import board_sections, has_board

    cases = [Case(name=f"M{m}_{h}km_a{a}_b{b}", mach=m, alpha=a, beta=b, altitude_km=h)
             for h in (0.0, 10.0) for m in (0.3, 0.6) for a in (0.0, 5.0) for b in (0.0, 2.0)]
    sections = board_sections(cases)
    assert [s.label for s in sections] == ["0 km · β 0°", "0 km · β 2°", "10 km · β 0°", "10 km · β 2°"]
    first = sections[0]
    assert (first.key, first.machs, first.alphas) == ("0|0", [0.3, 0.6], [0.0, 5.0])
    assert first.cells[(0.6, 5.0)] == "M0.6_0.0km_a5.0_b0.0"
    assert has_board(cases)
    one_mach = [Case(name=f"a{a}", mach=0.8, alpha=a, beta=0.0) for a in (0.0, 2.0, 4.0)]
    assert not has_board(one_mach) and board_sections(one_mach)[0].label == ""


def test_tile_text():
    from aerosuite.engine.jobs.overview import NOT_RUN
    from aerosuite.web.run_view import tile_text

    assert tile_text("CONVERGED", 812) == "✓ 812 it" and tile_text("CONVERGED") == "✓"
    assert tile_text("UNCONVERGED", 1500) == "1500 it" and tile_text("RUNNING", 930) == "930 it"
    assert tile_text("PENDING", place=3) == "#3" and tile_text("FAILED") == "! failed"
    assert tile_text(NOT_RUN) == "—"


def test_state_sections_put_failed_first_in_needs_a_look():
    from aerosuite.engine.jobs.overview import NOT_RUN, CaseRow
    from aerosuite.web.run_view import state_sections

    rows = [CaseRow("a", "UNCONVERGED", "j"), CaseRow("b", "CONVERGED", "j"), CaseRow("c", "FAILED", "j"),
            CaseRow("d", "RUNNING", "j"), CaseRow("e", NOT_RUN, None), CaseRow("f", "PENDING", "j")]
    sections = state_sections(rows)
    assert [(key, [r.name for r in members]) for key, _title, members in sections] == [
        ("running", ["d"]), ("queued", ["f"]), ("attention", ["c", "a"]), ("not-run", ["e"]), ("done", ["b"])]


def test_a_case_is_read_back_from_its_name():
    from aerosuite.web.run_view import case_from_name

    case = case_from_name("M0p6_20km_an2p5_b0")
    assert (case.mach, case.alpha, case.beta, case.altitude_km) == (0.6, -2.5, 0.0, 20.0)
    assert case_from_name("M0p8_a2_b1").altitude_km is None
    assert case_from_name("study") is None


def test_earlier_cases_group_by_altitude_lowest_first():
    from aerosuite.web.run_view import earlier_groups
    rows = [CaseRow(name, "CONVERGED", "j") for name in
            ("M0p6_10km_a0", "M0p3_10km_a5", "M0p3_0km_a10", "M0p3_0km_a5", "odd_case")]
    groups = earlier_groups(rows)
    assert [(g.label, g.key) for g in groups] == [("0 km", "0"), ("10 km", "10"), ("Other cases", "other")]
    assert [r.name for r in groups[0].rows] == ["M0p3_0km_a5", "M0p3_0km_a10"]  # by α, not by name
    assert [r.name for r in groups[1].rows] == ["M0p3_10km_a5", "M0p6_10km_a0"]
    assert groups[2].cases == []  # no Mach or α in the name: listed, not drawn on a grid
