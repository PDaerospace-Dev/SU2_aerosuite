"""The Results page's rules without NiceGUI: pinning the automatic choices, filters, counts."""
import pandas as pd
import pytest

from aerosuite.engine.models import ResultsSettings
from aerosuite.engine.packages import effective
from aerosuite.web.results_view import (add_parameter, filter_rows, pin, remove_parameter, shown_values,
                                        status_counts, sweep_values, toggle_filter)

COLUMNS = ["rms[Rho]", "CL", "CD", "CMy", "CL(Wing)"]


def _table(machs=(0.6, 0.8), alphas=(0.0, 2.0)):
    rows = [{"Case": f"M{m}_a{a}", "Mach": m, "Alpha": a, "Beta": 0.0, "Converged": True, "CL": 0.1 * a}
            for m in machs for a in alphas]
    return pd.DataFrame(rows)


def test_pin_fixes_the_automatic_choices_on_the_first_change():
    settings = ResultsSettings()
    pin(settings, effective(settings, COLUMNS))
    assert settings.packages == ["aero"] and settings.parameters == ["CL", "CD", "CMy", "L/D"]
    settings.parameters = ["CL"]
    pin(settings, effective(settings, COLUMNS))
    assert settings.parameters == ["CL"]  # a choice already made stands
    cleared = ResultsSettings(packages=["aero"], parameters=[])
    pin(cleared, effective(cleared, COLUMNS))
    assert cleared.parameters == []  # cleared on purpose: stays empty


def test_adding_and_removing_parameters_pins_first():
    settings = ResultsSettings()
    add_parameter(settings, effective(settings, COLUMNS), "CL(Wing)")
    assert settings.parameters == ["CL", "CD", "CMy", "L/D", "CL(Wing)"]
    remove_parameter(settings, effective(settings, COLUMNS), "CD")
    assert settings.parameters == ["CL", "CMy", "L/D", "CL(Wing)"]
    add_parameter(settings, effective(settings, COLUMNS), "CL")  # already there: no duplicate
    assert settings.parameters.count("CL") == 1


def test_sweep_values_and_what_is_shown():
    values = sweep_values([_table(), _table(machs=(0.8, 0.9))])
    assert values == {"Mach": [0.6, 0.8, 0.9], "Alpha": [0.0, 2.0], "Beta": [0.0]}
    settings = ResultsSettings()
    assert shown_values(settings, values, comparing=False)["Mach"] == [0.6, 0.8, 0.9]
    assert shown_values(settings, values, comparing=True)["Mach"] == [0.6]  # overlays start on one Mach
    settings.filters = {"Mach": [0.8, 0.9]}
    assert shown_values(settings, values, comparing=True)["Mach"] == [0.8, 0.9]
    settings.filters = {"Mach": [0.7]}  # a value no longer in the results: fall back to all
    assert shown_values(settings, values, comparing=False)["Mach"] == [0.6, 0.8, 0.9]


def test_toggling_a_filter_never_leaves_nothing_shown():
    settings = ResultsSettings()
    values = {"Mach": [0.6, 0.8]}
    toggle_filter(settings, "Mach", 0.6, shown_values(settings, values, comparing=False)["Mach"])
    assert settings.filters == {"Mach": [0.8]}
    toggle_filter(settings, "Mach", 0.8, shown_values(settings, values, comparing=False)["Mach"])
    assert settings.filters == {"Mach": [0.8]}  # the last one stays
    toggle_filter(settings, "Mach", 0.6, shown_values(settings, values, comparing=False)["Mach"])
    assert settings.filters == {"Mach": [0.6, 0.8]}


def test_rows_are_filtered_and_counted():
    table = _table()
    table["Converged"] = table["Converged"].astype(object)  # as summarize gives it when some are not judged
    table.loc[0, "Converged"] = False
    table.loc[1, "Converged"] = None
    rows = filter_rows(table, {"Mach": [0.6], "Alpha": [0.0, 2.0], "Beta": [0.0]})
    assert rows["Case"].tolist() == ["M0.6_a0.0", "M0.6_a2.0"]
    assert status_counts([table]) == {"shown": 4, "converged": 2, "unconverged": 1, "not_judged": 1}


@pytest.mark.parametrize("missing", ["Beta", "Altitude"])
def test_absent_sweep_columns_are_ignored(missing):
    table = _table().drop(columns=[c for c in [missing] if c in _table().columns])
    assert missing not in sweep_values([table])


def test_the_table_as_tab_separated_text():
    from aerosuite.web.results_view import table_text

    table = _table(machs=(0.8,), alphas=(0.0, 2.0))
    table["Converged"] = [True, False]
    text = table_text([("base", table)], sweep=["Alpha"], parameters=["CL"])
    assert text.splitlines() == ["Case\tα (deg)\tCL\tStatus", "M0.8_a0.0\t0\t0\tConverged",
                                 "M0.8_a2.0\t2\t0.2\tUnconverged"]
    two = table_text([("base", table), ("v2", table)], sweep=[], parameters=["CL"])
    assert two.splitlines()[0] == "Design\tCase\tCL\tStatus" and two.splitlines()[3].startswith("v2\t")


def _configs():
    return pd.DataFrame([{"Case": f"{c}_b{b}", "Config": c, "Mach": 1.2, "Alpha": 0.0, "Beta": float(b),
                          "Temperature": 223.25, "Converged": True, "CSF": 0.01 * b} for c in ("vt", "ht")
                         for b in (0, 2)])


def test_config_is_a_label_variable():
    values = sweep_values([_configs()])
    assert values["Config"] == ["ht", "vt"] and values["Temperature"] == [223.25]
    settings = ResultsSettings()
    shown = shown_values(settings, values, comparing=False)
    toggle_filter(settings, "Config", "ht", shown["Config"])
    assert settings.filters == {"Config": ["vt"]}
    assert filter_rows(_configs(), shown_values(settings, values, comparing=False))["Case"].tolist() == [
        "vt_b0", "vt_b2"]
    from aerosuite.web.results_view import table_text, varying
    assert varying(values) == ["Config", "Beta"]
    assert table_text([("s", _configs())], ["Config", "Beta"], ["CSF"]).splitlines()[1] == "vt_b0\tvt\t0\t0\tConverged"


def test_the_conditions_of_the_shown_cases():
    from aerosuite.web.results_view import conditions

    table = pd.DataFrame([{"Case": f"c{a}_{b}", "Mach": 0.9, "Altitude": 10.0, "Temperature": 223.15,
                           "Alpha": float(a), "Beta": float(b), "Config": None}
                          for a in (-10, 0, 10, 25, 45) for b in (2, 6, 10)])
    assert conditions([table]) == [("Mach", "0.9"), ("Altitude (km)", "10"), ("T (K)", "223.15"),
                                   ("α (deg)", "-10 … 45 · 5"), ("β (deg)", "2, 6, 10")]
    labels = pd.DataFrame([{"Case": f"x{i}", "Mach": 1.2, "Alpha": 0.0, "Config": c}
                           for i, c in enumerate(("ht", "vt"))])
    assert conditions([labels, table.head(1)]) == [("Mach", "0.9, 1.2"), ("Altitude (km)", "10"),
                                                   ("T (K)", "223.15"), ("α (deg)", "-10, 0"), ("β (deg)", "2"),
                                                   ("Config", "ht, vt")]
    assert conditions([]) == []


def test_the_converged_text():
    from aerosuite.web.results_view import converged_text

    assert converged_text({"shown": 15, "converged": 0, "unconverged": 15, "not_judged": 0}) == (
        "0 / 15 converged", "unconverged")
    assert converged_text({"shown": 4, "converged": 4, "unconverged": 0, "not_judged": 0}) == (
        "4 / 4 converged", "done")
    assert converged_text({"shown": 3, "converged": 0, "unconverged": 0, "not_judged": 3}) == (
        "convergence not judged", "pending")
