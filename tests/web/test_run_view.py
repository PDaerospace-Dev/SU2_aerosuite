"""The Run page's rules without NiceGUI: layout by study size, groups, counts, durations, time left."""
from aerosuite.engine.jobs.overview import CaseRow
from aerosuite.engine.models import Case
from aerosuite.web.run_view import (case_conditions, case_groups, duration_text, layout, status_counts, time_left)


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


def test_a_single_cases_conditions_come_from_its_config():
    text = "SOLVER= RANS\nKIND_TURB_MODEL= SA\nMACH_NUMBER= 0.8 % comment\nAOA= 1.25\nSIDESLIP_ANGLE= 0.0\nITER= 5000\n"
    assert case_conditions(text, "/data/mesh_NACA0012_inv.su2") == [
        ("Solver", "RANS · SA"), ("Mach", "0.8"), ("α (deg)", "1.25"), ("β (deg)", "0.0"),
        ("Iterations (max)", "5000"), ("Mesh", "mesh_NACA0012_inv.su2")]
    assert case_conditions("SOLVER= EULER\nKIND_TURB_MODEL= NONE\n", None) == [("Solver", "EULER")]
