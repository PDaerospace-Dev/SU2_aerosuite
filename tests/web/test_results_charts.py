"""Plots on the Results page without NiceGUI: which points make a line, and the chart's series (spec §2.2)."""
import math

import pandas as pd
import pytest

from aerosuite.engine.models import PlotSpec
from aerosuite.web.results_charts import ChartDesign, axis_options, chart_options, describe_lines, split_keys


def _table(machs=(0.6, 0.8), alphas=(0.0, 2.0, 4.0), betas=(0.0,)):
    rows = []
    for m in machs:
        for b in betas:
            for a in alphas:
                cl = 0.1 * (a + 2) * (1 + m - 0.6)
                rows.append({"Case": f"M{m}_a{a}_b{b}", "Mach": m, "Alpha": a, "Beta": b, "Converged": True,
                             "CL": cl, "CD": 0.02 + 0.05 * cl * cl, "CL(Wing)": 0.9 * cl})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("x, split, expected", [
    ("Alpha", None, ["Mach"]),         # CL vs α: one line per Mach
    ("Mach", None, ["Alpha"]),         # CL vs Mach: one line per α
    ("CD", None, ["Mach"]),            # the polar: joined along α, one line per Mach
    ("Alpha", "Alpha", ["Mach"]),      # the X axis cannot split
    ("CD", "Mach", ["Mach"]),
])
def test_split_keys(x, split, expected):
    assert split_keys(x, _table(), split) == expected


def test_two_varying_variables_both_split_unless_one_is_chosen():
    table = _table(betas=(0.0, 5.0))
    assert split_keys("Alpha", table, None) == ["Mach", "Beta"]
    assert split_keys("Alpha", table, "Beta") == ["Beta"]
    assert split_keys("Alpha", _table(machs=(0.8,)), None) == []


def test_lines_are_described_in_words():
    assert describe_lines("Alpha", ["Mach"]) == "One line per Mach, points joined along α"
    assert describe_lines("CD", ["Mach"]) == "One line per Mach, points joined along α"
    assert describe_lines("Mach", ["Alpha"]) == "One line per α, points joined along Mach"
    assert describe_lines("Alpha", []) == "One line, points joined along α"
    assert describe_lines("Alpha", ["Mach", "Beta"]) == "One line per Mach and β, points joined along α"


def test_series_colour_style_and_marker():
    base, v2 = _table(), _table()
    v2.loc[v2["Case"] == "M0.8_a4.0_b0.0", "Converged"] = False
    plot = PlotSpec(x="Alpha", y=["CL", "CL(Wing)"])
    options, owners = chart_options(plot, [ChartDesign("base", "#111111", base, "/a"),
                                           ChartDesign("v2", "#222222", v2, "/b")])
    names = [s["name"] for s in options["series"]]
    assert names[:4] == ["base · CL · Mach 0.6", "base · CL · Mach 0.8", "base · CL(Wing) · Mach 0.6",
                         "base · CL(Wing) · Mach 0.8"]
    assert len(owners) == len(options["series"]) == 8 and owners[0] == "/a" and owners[-1] == "/b"
    first, second, wing = options["series"][0], options["series"][1], options["series"][2]
    assert first["lineStyle"]["color"] == "#111111" and first["lineStyle"]["type"] == "solid"
    assert second["lineStyle"]["type"] == "dashed"  # the second Mach
    assert wing["symbol"] != first["symbol"]  # the second Y has its own marker shape
    assert [p["value"][0] for p in first["data"]] == [0.0, 2.0, 4.0]  # joined along α
    assert first["data"][0]["name"] == "M0.6_a0.0_b0.0"
    unconverged = next(p for p in options["series"][5]["data"] if p["name"] == "M0.8_a4.0_b0.0")
    assert unconverged["symbol"].startswith("empty")


def test_one_study_gives_each_line_its_own_colour():
    from aerosuite.web.theme import SERIES_COLORS

    table = _table(machs=tuple(0.1 * m for m in range(1, 11)))  # ten lines: more than the colours
    options, _ = chart_options(PlotSpec(x="Alpha", y=["CL"]), [ChartDesign("st_tail", "#111111", table, "/a")])
    series = options["series"]
    assert [s["lineStyle"]["color"] for s in series[:8]] == SERIES_COLORS
    assert all(s["itemStyle"]["color"] == s["lineStyle"]["color"] for s in series)
    assert [s["lineStyle"]["type"] for s in series[:8]] == ["solid"] * 8
    assert series[8]["lineStyle"]["color"] == SERIES_COLORS[0] and series[8]["lineStyle"]["type"] == "dashed"
    assert series[0]["name"] == "CL · Mach 0.1"  # no study name with one study


def test_missing_values_break_the_line():
    table = _table(machs=(0.8,))
    table.loc[1, "CL"] = math.nan
    options, _ = chart_options(PlotSpec(x="Alpha", y=["CL"]), [ChartDesign("base", "#111", table, "/a")])
    assert [p["value"][1] for p in options["series"][0]["data"]][1] is None
    assert options["series"][0]["connectNulls"] is False


def test_axis_names_carry_units():
    assert axis_options("Alpha", {})["name"] == "α (deg)"
    assert axis_options("Pt loss", {"Pt loss": "%"})["name"] == "Pt loss (%)"
    assert axis_options("CL", {})["name"] == "CL"


def test_config_splits_lines_and_is_never_an_axis():
    table = pd.DataFrame([{"Case": f"{c}_b{b}", "Config": c, "Mach": 1.2, "Alpha": 0.0, "Beta": float(b),
                           "Converged": True, "CSF": 0.01 * b} for c in ("vt", "ht") for b in (0, 2, 4)])
    assert split_keys("Beta", table, None) == ["Config"]
    assert describe_lines("Beta", ["Config"]) == "One line per Config, points joined along β"
    options, _ = chart_options(PlotSpec(x="Beta", y=["CSF"]), [ChartDesign("s", "#111", table, "/a")])
    assert [s["name"] for s in options["series"]] == ["CSF · Config ht", "CSF · Config vt"]
    assert [p["value"][0] for p in options["series"][0]["data"]] == [0.0, 2.0, 4.0]


def _mixed():
    """A β sweep of two configurations at Mach 1.2 (10 km, 223.25 K) and an α sweep without a config at 2.5."""
    rows = [{"Case": f"{c}_b{b}", "Config": c, "Mach": 1.2, "Alpha": 0.0, "Beta": float(b), "Altitude": 10.0,
             "Temperature": 223.25, "Converged": True, "CL": 0.01, "CSF": 0.01 * b} for c in ("vt", "ht")
            for b in (0, 2)]
    rows += [{"Case": f"M2p5_a{a}", "Config": None, "Mach": 2.5, "Alpha": float(a), "Beta": 0.0, "Altitude": 30.0,
              "Temperature": 216.65, "Converged": True, "CL": 0.035 * a, "CSF": 0.0} for a in (0, 10, 20)]
    return pd.DataFrame(rows)


def test_cases_without_a_config_keep_their_own_lines():
    options, _ = chart_options(PlotSpec(x="Alpha", y=["CL"]), [ChartDesign("s", "#111", _mixed(), "/a")])
    no_config = next(s for s in options["series"] if "Config —" in s["name"])
    assert [p["value"] for p in no_config["data"]] == [[0.0, 0.0], [10.0, pytest.approx(0.35)],
                                                        [20.0, pytest.approx(0.7)]]


def test_variables_fixed_by_the_others_do_not_split_lines():
    # Mach, altitude and T follow from the Config here (ht and vt at 1.2, none at 2.5); β varies within a config
    assert split_keys("Alpha", _mixed(), None) == ["Config", "Beta"]
    options, _ = chart_options(PlotSpec(x="Alpha", y=["CL"]), [ChartDesign("s", "#111", _mixed(), "/a")])
    assert "Altitude" not in options["series"][0]["name"] and "T " not in options["series"][0]["name"]
