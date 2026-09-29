"""The Results page's settings, saved per study in project.json (schema 6)."""
import json

import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.models import SCHEMA_VERSION, DerivedValue, PlotSpec, Project, ResultsSettings
from aerosuite.engine.project import PROJECT_FILE, create_project, open_project, save_project


def test_defaults():
    results = Project(name="p").results
    assert results == ResultsSettings()
    assert results.parameters is None  # not chosen yet: the packages' parameters (or the first ones)
    assert (results.derived, results.plots, results.compare) == ([], [], [])
    assert results.packages is None  # not chosen yet: the page switches on the packages the history supports
    assert results.average_last == 100 and results.folded == []


def test_schema_5_projects_open_with_default_results(tmp_path):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["schema_version"] = 5
    del data["results"]
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    project = open_project(tmp_path)
    assert SCHEMA_VERSION == 6 and project.schema_version == 6
    assert project.results == ResultsSettings()


def test_results_round_trip(tmp_path):
    project = create_project(tmp_path)
    project.results = ResultsSettings(
        parameters=["CL", "CD", "L/D"], derived=[DerivedValue(name="L/D", formula="CL / CD")],
        characteristics=[DerivedValue(name="CLα", formula="slope(CL, Alpha, -2, 6)", unit="1/deg")],
        plots=[PlotSpec(x="Alpha", y=["CL(Wing)", "CL(HT)"])], packages=["aero"], compare=["/data/wing-v2"],
        filters={"Mach": [0.8]}, average_last=50, folded=["results"])
    save_project(tmp_path, project)
    assert open_project(tmp_path).results == project.results


@pytest.mark.parametrize("bad", [{"average_last": 0}, {"folded": ["sideways"]}, {"plots": [{"x": "Alpha"}]}])
def test_invalid_results_are_refused(tmp_path, bad):
    create_project(tmp_path)
    data = json.loads((tmp_path / PROJECT_FILE).read_text())
    data["results"] = bad
    (tmp_path / PROJECT_FILE).write_text(json.dumps(data))
    with pytest.raises(ProjectError):
        open_project(tmp_path)
