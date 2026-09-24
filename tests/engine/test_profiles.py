import json

import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.models import Project
from aerosuite.engine.profiles import (
    BUNDLED_PROFILES,
    PROFILE_FILE,
    apply_profile,
    list_profiles,
    load_profile,
    save_profile,
    user_profiles_dir,
)
from aerosuite.engine.project import TEMPLATE_FILE


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("AEROSUITE_HOME", str(tmp_path / "home"))


def test_bundled_x07():
    x07 = load_profile("x07")
    assert x07.bundled and x07.name == "X07" and x07.template is None
    assert x07.data.settings["reference"]["ref_area"] == 16.213
    assert x07.hints["MARKER_FAR"] == "( FarField )"
    assert x07.setting_hints["reference.ref_area"] == "16.213"
    assert x07.setting_hints["numerics.conv_method"] == "ROE"
    profiles, problems = list_profiles()
    assert "x07" in [p.id for p in profiles] and problems == []


def test_apply_profile(ready_project):
    project_dir, project = ready_project
    project.settings.numerics.cfl = 9.0
    project.settings.overrides = {"CONV_FIELD": "LIFT"}
    apply_profile(project_dir, project, load_profile("x07"))
    assert project.profile == "x07"
    assert project.settings.reference.ref_area == 16.213
    assert project.settings.numerics.cfl == 1.0          # the profile defines it
    assert project.settings.numerics.turb_model == "SST"
    assert project.settings.overrides == {"CONV_FIELD": "LIFT"}  # untouched
    assert (project_dir / TEMPLATE_FILE).read_text().startswith("MACH_NUMBER= 0.3")  # no profile template


def _write_user_profile(profile_id, body):
    folder = user_profiles_dir() / profile_id
    folder.mkdir(parents=True)
    (folder / PROFILE_FILE).write_text(json.dumps(body))
    return folder


def test_user_profile_overrides_bundled_and_broken_ones_are_reported():
    _write_user_profile("x07", {"id": "x07", "name": "My X07"})
    _write_user_profile("broken", {"id": "other", "name": "Broken"})
    _write_user_profile("typo", {"id": "typo", "name": "Typo", "settings": {"reference": {"ref_areaa": 1}}})
    profiles, problems = list_profiles()
    assert {p.id: p.name for p in profiles}["x07"] == "My X07"
    assert "broken" not in [p.id for p in profiles] and "typo" not in [p.id for p in profiles]
    assert any("broken" in m for m in problems) and any("ref_areaa" in m for m in problems)
    with pytest.raises(ProjectError, match="Unknown profile"):
        load_profile("nope")


def test_load_profile_rejects_ids_outside_the_profile_folders():
    with pytest.raises(ProjectError, match="Invalid profile id"):
        load_profile("../x")
    with pytest.raises(ProjectError, match="Invalid profile id"):
        load_profile("x07\n")  # _ID_RE's trailing $ alone would accept a trailing newline
    with pytest.raises(ProjectError, match="Invalid profile id"):
        load_profile(str(BUNDLED_PROFILES / "x07"))  # an absolute path


def test_save_profile_rejects_a_trailing_newline_in_the_id(ready_project):
    project_dir, project = ready_project
    with pytest.raises(ProjectError, match="letters, digits"):
        save_profile(project_dir, project, "ok_id\n", "Name")


def test_load_profile_falls_back_to_the_bundled_copy_when_the_users_own_is_broken():
    folder = user_profiles_dir() / "x07"
    folder.mkdir(parents=True)
    (folder / PROFILE_FILE).write_text("{not valid json")
    profiles, problems = list_profiles()
    assert "x07" in [p.id for p in profiles]  # the bundled one is still offered
    assert any("x07" in m for m in problems)
    profile = load_profile("x07")  # must not raise: falls back to the bundled copy
    assert profile.bundled is True and profile.name == "X07"


def test_apply_profile_can_skip_the_template_copy(ready_project, tmp_path):
    project_dir, project = ready_project
    saved = save_profile(project_dir, project, "acft", "Acft")
    assert saved.template is not None
    other_dir = tmp_path / "other"
    other_dir.mkdir()
    (other_dir / TEMPLATE_FILE).write_text("ORIGINAL\n")
    other = Project(name="other")
    apply_profile(other_dir, other, saved, copy_template=False)
    assert other.profile == "acft"
    assert (other_dir / TEMPLATE_FILE).read_text() == "ORIGINAL\n"  # not copied
    apply_profile(other_dir, other, saved)  # default: copies it
    assert (other_dir / TEMPLATE_FILE).read_text() != "ORIGINAL\n"


def test_save_profile(ready_project):
    project_dir, project = ready_project
    project.settings.reference.ref_area = 20.0
    project.settings.markers = {"MARKER_FAR": "( far )", "MARKER_PLOTTING": None}
    project.settings.overrides = {"CONV_FIELD": "LIFT"}
    project.sweep.naming.base_name = "jet"
    saved = save_profile(project_dir, project, "my_jet", "My jet", "test")
    assert not saved.bundled and saved.template is not None
    data = json.loads((user_profiles_dir() / "my_jet" / PROFILE_FILE).read_text())
    assert data["settings"]["reference"] == {"ref_area": 20.0}
    assert data["settings"]["markers"] == {"MARKER_FAR": "( far )", "MARKER_PLOTTING": None}
    assert data["settings"]["overrides"] == {"CONV_FIELD": "LIFT"}
    assert data["naming"]["base_name"] == "jet"
    assert set(data) == {"id", "name", "description", "settings", "hints", "naming"}
    text = json.dumps(data)
    assert "wing.su2" not in text and "M0p8" not in text  # no mesh, no cases
    with pytest.raises(ProjectError, match="already exists"):
        save_profile(project_dir, project, "my_jet", "Again")
    assert save_profile(project_dir, project, "my_jet", "Again", overwrite=True).name == "Again"
    with pytest.raises(ProjectError, match="letters, digits"):
        save_profile(project_dir, project, "bad id", "x")
    with pytest.raises(ProjectError, match="name"):
        save_profile(project_dir, project, "ok_id", "  ")
