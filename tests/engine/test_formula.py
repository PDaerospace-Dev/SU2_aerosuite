"""The formula reader for derived and characteristic values (spec 2026-09-29-results-design.md §3)."""
import math

import pytest

from aerosuite.engine.formula import FormulaError, Missing, evaluate, evaluate_curve, parse

CASE = {"CL": 0.6, "CD": 0.03, "CMy": -0.05, "Alpha": 4.0, "Mach": 0.8,
        "Avg_TotalPress(outlet)": 98000.0, "Avg_TotalPress(inlet)": 100000.0}


def value(text, values=CASE):
    return evaluate(parse(text), values)


@pytest.mark.parametrize("text, expected", [
    ("CL / CD", 20.0),
    ("1 - {Avg_TotalPress(outlet)} / {Avg_TotalPress(inlet)}", 0.02),
    ("2^3", 8.0),
    ("CL^1.5 / CD", 0.6 ** 1.5 / 0.03),
    ("-CMy", 0.05),
    ("sqrt(4) + abs(-1)", 3.0),
    ("sin(30)", 0.5),  # degrees
    ("cos(Alpha) * CL", math.cos(math.radians(4.0)) * 0.6),
    ("max(CL, CD) - min(CL, CD)", 0.57),
    ("log(exp(2))", 2.0),
    ("CL * 0.5 * 1.225 * 100^2 * 20", 0.6 * 0.5 * 1.225 * 1e4 * 20),
])
def test_arithmetic_and_functions(text, expected):
    assert value(text) == pytest.approx(expected)


def test_names_are_listed_without_braces():
    assert parse("1 - {Avg_TotalPress(outlet)} / {Avg_TotalPress(inlet)}").names == {
        "Avg_TotalPress(outlet)", "Avg_TotalPress(inlet)"}
    assert parse("CL / CD + sqrt(Mach)").names == {"CL", "CD", "Mach"}


@pytest.mark.parametrize("text", [
    "__import__('os')", "CL.real", "[1, 2]", "lambda: 1", "CL if CD else 1", "foo(1)", "CL == 1",
    "'text'", "CL[0]", "sqrt(x=1)", "True", "(CL, CD)", "CL; CD", "{CL} {CD}", "open('f')", "a := 1",
    "{}", "sqrt(*CL)",
])
def test_anything_else_is_refused(text):
    with pytest.raises(FormulaError):
        parse(text)


def test_messages_are_readable():
    with pytest.raises(FormulaError, match="foo is not a function"):
        parse("foo(1)")
    with pytest.raises(FormulaError, match="not a valid formula"):
        parse("CL / ")
    with pytest.raises(FormulaError, match="Give a formula"):
        parse("  ")
    with pytest.raises(FormulaError, match="Avg_Mass is not a known name"):
        parse("{Avg_Mass} * 2", known={"CL", "CD"})


def test_what_cannot_be_computed_is_missing_with_a_reason():
    assert value("CL / (CD - CD)") == Missing("division by zero")
    assert value("sqrt(CMy)") == Missing("sqrt of a negative number")
    assert value("log(0)") == Missing("log of a number ≤ 0")
    assert value("CL(Wing) + 1".replace("CL(Wing)", "{CL(Wing)}")) == Missing("no value for CL(Wing)")
    constants = {**CASE, "q_inf": Missing("q_inf needs the freestream from altitude")}
    assert value("CL * q_inf", constants) == Missing("q_inf needs the freestream from altitude")
    assert value("CL * nan_value", {**CASE, "nan_value": float("nan")}) == Missing("no value for nan_value")


CURVE = {"Alpha": [-4.0, -2.0, 0.0, 2.0, 4.0, 6.0, 8.0],
         "CL": [-0.2, 0.0, 0.2, 0.4, 0.6, 0.8, 0.9],
         "CD": [0.030, 0.025, 0.024, 0.026, 0.032, 0.041, 0.055]}


def curve_value(text, curve=CURVE):
    return evaluate_curve(parse(text, curve=True), curve)


def test_curve_functions():
    assert curve_value("slope(CL, Alpha, -2, 6)") == pytest.approx(0.1)
    assert curve_value("at(Alpha, CL, 0)") == pytest.approx(-2.0)  # zero-lift angle, read backwards
    assert curve_value("at(CD, CL, 0)") == pytest.approx(0.025)
    assert curve_value("at(CL, Alpha, 3)") == pytest.approx(0.5)
    assert curve_value("max(CL)") == pytest.approx(0.9)
    assert curve_value("argmax(CL, Alpha)") == pytest.approx(8.0)
    assert curve_value("argmin(CD, Alpha)") == pytest.approx(0.0)
    assert curve_value("slope(CL, Alpha, -2, 6) * 57.29578") == pytest.approx(5.729578)


def test_curve_functions_on_a_derived_series():
    curve = {**CURVE, "L/D": [cl / cd for cl, cd in zip(CURVE["CL"], CURVE["CD"])]}
    assert curve_value("max({L/D})", curve) == pytest.approx(0.8 / 0.041)
    assert curve_value("argmax({L/D}, Alpha)", curve) == pytest.approx(6.0)


def test_curve_values_that_cannot_be_read_are_missing():
    assert curve_value("at(CL, Alpha, 20)") == Missing("20 is outside the Alpha data (-4 … 8)")
    assert curve_value("slope(CL, Alpha, 10, 12)") == Missing("fewer than 2 points with Alpha in 10 … 12")
    short = {"Alpha": [0.0], "CL": [0.2]}
    assert curve_value("slope(CL, Alpha, -2, 6)", short) == Missing("fewer than 2 points with Alpha in -2 … 6")
    gaps = {"Alpha": [0.0, 2.0, 4.0], "CL": [0.2, float("nan"), 0.6]}
    assert curve_value("slope(CL, Alpha, 0, 4)", gaps) == pytest.approx(0.1)  # the gap is skipped


def test_curve_formulas_need_a_curve_function_around_series():
    with pytest.raises(FormulaError, match="CL is a series here"):
        parse("CL + 1", curve=True)
    with pytest.raises(FormulaError, match="slope takes 4 arguments"):
        parse("slope(CL, Alpha)", curve=True)
    with pytest.raises(FormulaError, match="must name a parameter"):
        parse("max(CL + 1)", curve=True)
    with pytest.raises(FormulaError, match="Argument 3 of slope must be a number"):
        parse("slope(CL, Alpha, Mach, 6)", curve=True)
