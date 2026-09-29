"""Packages of parameters, derived and characteristic values and plots (spec §4)."""
import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.models import DerivedValue, PlotSpec, ResultsSettings
from aerosuite.engine.packages import (AERO, Package, delete_package, disable_package, effective, enable_package,
                                       history_needs, list_packages, load_package, save_package)

AERO_COLUMNS = ["rms[Rho]", "CL", "CD", "CMy", "CL(Wing)"]
DUCT_COLUMNS = ["rms[Rho]", "Avg_Massflow(outlet)", "Avg_TotalPress(inlet)", "Avg_TotalPress(outlet)"]


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


def _duct() -> Package:
    return Package(id="duct", name="Duct performance", parameters=["Avg_Massflow(outlet)", "Pt loss"],
                   derived=[DerivedValue(name="Pt loss",
                                         formula="1 - {Avg_TotalPress(outlet)} / {Avg_TotalPress(inlet)}")],
                   plots=[PlotSpec(x="Mach", y=["Pt loss"])])


def test_the_bundled_aero_package():
    aero = load_package(AERO)
    assert aero.name == "Aerodynamic characteristics"
    assert [d.name for d in aero.derived] == ["L/D"]
    assert [c.name for c in aero.characteristics] == ["CLα", "α₀", "CD₀", "(L/D)max", "α at (L/D)max", "CMα"]
    assert [(p.x, p.y) for p in aero.plots] == [("Alpha", ["CL"]), ("Alpha", ["CD"]), ("Alpha", ["CMy"]),
                                                 ("CD", ["CL"])]
    assert history_needs(aero) == {"CL", "CD", "CMy"}


def test_user_packages_save_load_list_and_delete():
    save_package(_duct())
    assert load_package("duct") == _duct()
    assert [p.id for p in list_packages()] == [AERO, "duct"]
    assert history_needs(_duct()) == {"Avg_Massflow(outlet)", "Avg_TotalPress(inlet)", "Avg_TotalPress(outlet)"}
    delete_package("duct")
    with pytest.raises(ProjectError, match="Unknown package"):
        load_package("duct")


def test_a_user_package_with_the_bundled_id_replaces_it_until_deleted():
    save_package(Package(id=AERO, name="My aero", parameters=["CL"]))
    assert load_package(AERO).name == "My aero"
    delete_package(AERO)
    assert load_package(AERO).name == "Aerodynamic characteristics"


def test_invalid_packages_are_refused():
    with pytest.raises(ProjectError, match="letters, digits"):
        save_package(Package(id="bad id", name="x"))
    with pytest.raises(ProjectError, match="not a valid formula"):
        save_package(Package(id="p", name="x", derived=[DerivedValue(name="a", formula="CL /")]))
    with pytest.raises(ProjectError, match="twice"):
        save_package(Package(id="p", name="x", derived=[DerivedValue(name="a", formula="CL"),
                                                        DerivedValue(name="a", formula="CD")]))


def test_effective_definitions_switch_on_aero_when_the_history_supports_it():
    fresh = effective(ResultsSettings(), AERO_COLUMNS)
    assert fresh.packages == [AERO]
    assert fresh.parameters == ["CL", "CD", "CMy", "L/D"]
    assert [d.name for d in fresh.derived] == ["L/D"] and len(fresh.plots) == 4 and len(fresh.characteristics) == 6
    duct = effective(ResultsSettings(), DUCT_COLUMNS)
    assert duct.packages == [] and duct.derived == [] and duct.plots == []
    assert duct.parameters == ["Avg_Massflow(outlet)", "Avg_TotalPress(inlet)", "Avg_TotalPress(outlet)"]


def test_own_definitions_come_after_the_packages():
    settings = ResultsSettings(packages=[AERO], parameters=["CL", "CD", "CL(Wing)"],
                               derived=[DerivedValue(name="CL share", formula="{CL(Wing)} / CL")],
                               plots=[PlotSpec(x="Alpha", y=["CL(Wing)", "CL"])])
    result = effective(settings, AERO_COLUMNS)
    assert result.parameters == ["CL", "CD", "CL(Wing)"]  # the user's own choice and order stand
    assert [d.name for d in result.derived] == ["L/D", "CL share"]
    assert [p.y for p in result.plots][-1] == ["CL(Wing)", "CL"]


def test_enabling_and_disabling_a_package():
    save_package(_duct())
    settings = ResultsSettings(packages=[], parameters=["Avg_TotalPress(inlet)", "Avg_Massflow(outlet)"])
    enable_package(settings, load_package("duct"))
    assert settings.packages == ["duct"]
    assert settings.parameters == ["Avg_TotalPress(inlet)", "Avg_Massflow(outlet)", "Pt loss"]
    disable_package(settings, load_package("duct"))
    assert settings.packages == []
    assert settings.parameters == ["Avg_TotalPress(inlet)"]  # what the package brought goes; the rest stays


def test_a_package_unavailable_for_a_study():
    from aerosuite.engine.packages import availability
    assert availability(load_package(AERO), DUCT_COLUMNS) == ["CD", "CL", "CMy"]
    assert availability(load_package(AERO), AERO_COLUMNS) == []
