import pytest

from aerosuite.core.isa_calculator import ISACalculator as LegacyISA
from aerosuite.core.yplus_calculator import calculate as legacy_yplus
from aerosuite.engine.atmosphere import ISACalculator, yplus


def test_isa_sea_level():
    r = ISACalculator.calculate(0.0, 0.0, 1.0)
    assert r["temperature"] == pytest.approx(288.15)
    assert r["pressure"] == pytest.approx(101325.0)
    assert r["density"] == pytest.approx(1.2250, abs=1e-3)


def test_isa_tropopause():
    r = ISACalculator.calculate(11.0, 0.8, 1.0)
    assert r["temperature"] == pytest.approx(216.65)
    assert r["pressure"] == pytest.approx(22632, rel=1e-3)


def test_isa_rejects_out_of_range():
    with pytest.raises(ValueError):
        ISACalculator.calculate(101.0, 0.5, 1.0)


def test_yplus_turbulent_external():
    r = yplus(velocity=50.0, density=1.225, viscosity=1.789e-5, length=1.0,
              y_plus=1.0, domain_type="External")
    assert r["flow_type"] == "Turbulent"
    assert r["y1"] > 0
    assert r["y1_mm"] == pytest.approx(r["y1"] * 1000)


def test_legacy_imports_still_work():
    assert LegacyISA is ISACalculator
    assert legacy_yplus is yplus
