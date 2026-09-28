import pytest

from aerosuite.engine.errors import ProjectError, TemplateError
from aerosuite.engine.project import open_project
from aerosuite.engine.reference import BUNDLED_REFERENCE
from aerosuite.engine.study import create_study


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


@pytest.fixture
def inputs(tmp_path):
    template = tmp_path / "x07.cfg"
    template.write_text("MACH_NUMBER= 0.7\nAOA= 1\n")
    mesh = tmp_path / "x07.su2"
    mesh.write_text("MARKER_TAG= Wing\n")
    return template, mesh


def test_general_case_from_the_reference(tmp_path):
    project = create_study(tmp_path / "nozzle", use_reference_template=True)
    assert project.profile is None and project.sweep.enabled is False
    assert [c.name for c in project.cases] == ["nozzle"]
    assert project.template == BUNDLED_REFERENCE.name  # the copy keeps the original's name
    assert (tmp_path / "nozzle" / project.template).read_text(encoding="utf-8") == \
        BUNDLED_REFERENCE.read_text(encoding="utf-8")
    assert open_project(tmp_path / "nozzle").sweep.enabled is False


def test_aircraft_study(tmp_path, inputs):
    template, mesh = inputs
    project = create_study(tmp_path / "x07_a", profile_id="x07", template=template, mesh=mesh)
    assert project.profile == "x07" and project.sweep.enabled is True
    assert project.settings.reference.ref_area == 16.213
    assert project.mesh.markers == ["Wing"]
    assert (tmp_path / "x07_a" / project.template).read_text() == "MACH_NUMBER= 0.7\nAOA= 1\n"


def test_aircraft_without_any_template_is_refused_before_creating(tmp_path):
    with pytest.raises(TemplateError, match="X07 has none"):
        create_study(tmp_path / "x07_b", profile_id="x07")
    assert not (tmp_path / "x07_b").exists()


def test_bad_inputs_create_nothing(tmp_path, inputs):
    template, _ = inputs
    with pytest.raises(ProjectError, match="Mesh not found"):
        create_study(tmp_path / "c", template=template, mesh=tmp_path / "gone.su2")
    with pytest.raises(TemplateError, match="Template not found"):
        create_study(tmp_path / "d", template=tmp_path / "gone.cfg")
    with pytest.raises(ProjectError, match="Unknown profile"):
        create_study(tmp_path / "e", profile_id="nope", template=template)
    assert not any((tmp_path / name).exists() for name in "cde")


def test_sweep_can_be_chosen_explicitly(tmp_path, inputs):
    template, _ = inputs
    assert create_study(tmp_path / "f", template=template, sweep=True).sweep.enabled is True


def test_a_new_sweep_on_study_starts_with_no_cases(tmp_path, inputs):
    template, mesh = inputs
    project = create_study(tmp_path / "g", profile_id="x07", template=template, mesh=mesh)
    assert project.sweep.enabled is True
    assert project.cases == []
