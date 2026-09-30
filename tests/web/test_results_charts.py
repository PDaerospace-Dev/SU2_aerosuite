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
    assert [s["name"] for s in options["series"]] == ["s · CSF · Config ht", "s · CSF · Config vt"]
    assert [p["value"][0] for p in options["series"][0]["data"]] == [0.0, 2.0, 4.0]
