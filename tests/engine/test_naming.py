import pytest

from aerosuite.engine.errors import GenerationError
from aerosuite.engine.naming import (
    angle_token,
    case_name,
    find_collisions,
    format_value,
    mach_token,
    parse_case_name,
)


@pytest.mark.parametrize(
    "value, text",
    [(0.85, "0.85"), (0.8, "0.8"), (5.0, "5"), (-0.5, "-0.5"), (0.0, "0"), (-0.0, "0"),
     (2.25, "2.25"), (6.5e6, "6500000"), (1e-5, "0.00001")],
)
def test_format_value_is_exact(value, text):
    assert format_value(value) == text


@pytest.mark.parametrize(
    "mach, token",
    [(0.8, "M0p8"), (0.85, "M0p85"), (0.78, "M0p78"), (1.5, "M1p5"), (1.0, "M1p0"), (2, "M2p0")],
)
def test_mach_token(mach, token):
    assert mach_token(mach) == token


@pytest.mark.parametrize(
    "angle, token",
    [(5, "5"), (-5, "n5"), (0, "0"), (2.5, "2p5"), (-0.5, "n0p5"), (1.5, "1p5")],
)
def test_angle_token(angle, token):
    assert angle_token(angle) == token


def test_case_name_default_order_matches_v7():
    assert case_name(0.8, 5, 0, altitude="SL", base_name="X07") == "M0p8_sl_a5_b0_x07"


def test_case_name_respects_include_flags():
    name = case_name(0.85, -2.5, 1, include_altitude=False, include_base=False)
    assert name == "M0p85_an2p5_b1"


def test_case_name_requires_a_component():
    with pytest.raises(GenerationError):
        case_name(0.8, 0, 0, include_mach=False, include_alpha=False, include_beta=False,
                  include_altitude=False, include_base=False)


@pytest.mark.parametrize(
    "name, expected",
    [
        ("M0p85_a2p5_bn1", (0.85, 2.5, -1.0)),
        ("M0p8_sl_an5_b0_x07", (0.8, -5.0, 0.0)),
        ("M0p8_sl_an5_b0_x07.cfg", (0.8, -5.0, 0.0)),
        ("ht_M0p3_A5_B0_sl", (0.3, 5.0, 0.0)),      # v7 legacy: Mach not first, upper case
        ("M0p6_A10m", (0.6, -10.0, None)),           # legacy m/p suffix
        ("M0p6_A10p", (0.6, 10.0, None)),
        ("M0p6_A-3", (0.6, -3.0, None)),
        ("sl_a5", (None, 5.0, None)),
        ("wing_baseline", (None, None, None)),
    ],
)
def test_parse_case_name(name, expected):
    assert tuple(parse_case_name(name)) == expected


@pytest.mark.parametrize("mach", [0.3, 0.8, 0.85, 1.25])
@pytest.mark.parametrize("alpha", [-4, -0.5, 0, 2.5, 12])
@pytest.mark.parametrize("beta", [-2, 0, 1.5])
def test_names_round_trip(mach, alpha, beta):
    parsed = parse_case_name(case_name(mach, alpha, beta, altitude="10km", base_name="x07"))
    assert parsed == (mach, alpha, beta)


def test_find_collisions():
    assert find_collisions(["a", "b", "a", "c", "b"]) == ["a", "b"]
    assert find_collisions(["a", "b"]) == []
