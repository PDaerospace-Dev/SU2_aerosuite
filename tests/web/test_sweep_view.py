"""The Sweep page's rules without NiceGUI: short value text, the restart rule and the cases set differently."""
from aerosuite.engine.editing import parse_value_list
from aerosuite.engine.models import Case
from aerosuite.web.sweep_view import case_formula, detect_rule, restart_text, rule_restarts, values_text


def test_evenly_spaced_values_read_as_a_range():
    alphas = parse_value_list("-10:20:2")
    assert values_text(alphas) == "-10:20:2"
    assert parse_value_list(values_text(alphas)) == alphas  # it reads back the same
    assert values_text([1.5, 2.0]) == "1.5, 2"  # too few for a range
    assert values_text([0.0, 2.0, 4.0, 25.0, 45.0]) == "0, 2, 4, 25, 45"
    assert values_text([0.6, 0.7, 0.8, 0.9]) == "0.6:0.9:0.1"
    assert values_text([]) == ""


def _cases(restarts=None):
    cases = [Case(name=f"M{m}_{h}km_a{a}", mach=m, alpha=float(a), beta=0.0, altitude_km=h)
             for h in (5.0, 10.0) for m in (1.5,) for a in (0, 2, 4)]
    for case, (restart, ref) in zip(cases, restarts or []):
        case.restart, case.restart_ref = restart, ref
    return cases


def test_the_rules_give_each_case_its_restart():
    cases = _cases()
    assert rule_restarts(cases, "none") == [("none", None)] * 6
    # each altitude starts fresh
    assert rule_restarts(cases, "previous") == [("none", None), ("previous", None), ("previous", None)] * 2
    assert rule_restarts(cases, "custom", "/old/runs")[1] == ("custom", "/old/runs/M1.5_5.0km_a2")


def test_the_rule_is_the_one_most_cases_follow():
    assert detect_rule(_cases()) == ("none", None, [])
    previous = rule_restarts(_cases(), "previous")
    assert detect_rule(_cases(previous)) == ("previous", None, [])
    previous[1] = ("custom", "/data/a2/restart_flow.dat")
    assert detect_rule(_cases(previous)) == ("previous", None, ["M1.5_5.0km_a2"])
    custom = rule_restarts(_cases(), "custom", "/old/runs")
    custom[5] = ("none", None)
    assert detect_rule(_cases(custom)) == ("custom", "/old/runs", ["M1.5_10.0km_a4"])
    one = [("none", None)] * 6
    one[2] = ("previous", None)
    assert detect_rule(_cases(one)) == ("none", None, ["M1.5_5.0km_a4"])
    assert detect_rule([]) == ("none", None, [])


def test_restarts_in_words():
    cases = _cases([("none", None), ("previous", None), ("custom", "/data/x.dat"), ("custom", None)])
    assert [restart_text(cases, i) for i in range(4)] == [
        "from scratch", "continues from M1.5_5.0km_a0", "from /data/x.dat", "from a file (not chosen)"]


def test_the_count_as_a_product():
    assert case_formula(2, 16, 1, 2) == "2 Mach × 2 altitudes × 16 α × 1 β"
    assert case_formula(1, 3, 1, 0) == "1 Mach × 3 α × 1 β"
