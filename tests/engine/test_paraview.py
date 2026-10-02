import os

import pytest

from aerosuite.engine import paraview
from aerosuite.engine.errors import AeroSuiteError
from aerosuite.engine.models import Case, Project
from aerosuite.engine.paraview import case_outputs, flow_files, open_in_paraview
from aerosuite.engine.restarts import RUNS_DIR


def _case_folder(project_dir, name, files, written=None):
    folder = project_dir / RUNS_DIR / name
    folder.mkdir(parents=True)
    for file in files:
        (folder / file).write_text("x")
        if written is not None:
            os.utime(folder / file, (written, written))
    return folder


def _project(*names):
    return Project(name="study", cases=[Case(name=name, mach=0.8, alpha=0.0, beta=0.0) for name in names])


def test_flow_files_are_the_paraview_files_surface_first(tmp_path):
    folder = _case_folder(tmp_path, "a", ["flow.vtu", "surface_flow.vtu", "history.csv", "restart_flow.dat"])
    (folder / "old.vtk").mkdir()  # a folder is not a file to open
    assert [path.name for path in flow_files(folder)] == ["surface_flow.vtu", "flow.vtu"]
    assert flow_files(tmp_path / "nope") == []


def test_case_outputs_lists_cases_with_files_newest_first(tmp_path):
    _case_folder(tmp_path, "a", ["flow.vtk", "surface_flow.vtk"], written=1000)
    _case_folder(tmp_path, "b", ["history.csv"])
    _case_folder(tmp_path, "c", ["flow.vtu"], written=2000)
    outputs = case_outputs(tmp_path, _project("a", "b", "c", "d"))
    assert [output.name for output in outputs] == ["c", "a"]
    assert [path.name for path in outputs[1].surface_files] == ["surface_flow.vtk"]
    assert [path.name for path in outputs[0].surface_files] == ["flow.vtu"]  # no surface file: all of them


def test_open_starts_paraview_detached_on_the_files(tmp_path, monkeypatch):
    started = []
    monkeypatch.setattr(paraview.shutil, "which", lambda command: f"/opt/{command}")
    monkeypatch.setattr(paraview.subprocess, "Popen", lambda args, **kwargs: started.append((args, kwargs)))
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.delenv(paraview.PARAVIEW_ENV, raising=False)
    open_in_paraview([tmp_path / "surface_flow.vtu", tmp_path / "flow.vtu"])
    args, kwargs = started[0]
    assert args == ["/opt/paraview", str(tmp_path / "surface_flow.vtu"), str(tmp_path / "flow.vtu")]
    assert kwargs["start_new_session"] is True  # closing AeroSuite must not close ParaView
    monkeypatch.setenv(paraview.PARAVIEW_ENV, "paraview-5.12")
    open_in_paraview([tmp_path / "flow.vtu"])
    assert started[1][0][0] == "/opt/paraview-5.12"


def test_open_says_why_it_cannot_start(tmp_path, monkeypatch):
    monkeypatch.setattr(paraview.subprocess, "Popen", lambda *args, **kwargs: pytest.fail("must not start"))
    monkeypatch.delenv(paraview.PARAVIEW_ENV, raising=False)
    with pytest.raises(AeroSuiteError, match="No flow files"):
        open_in_paraview([])
    monkeypatch.setattr(paraview.shutil, "which", lambda command: None)
    with pytest.raises(AeroSuiteError, match="ParaView not found"):
        open_in_paraview([tmp_path / "flow.vtu"])
    monkeypatch.setattr(paraview.shutil, "which", lambda command: f"/opt/{command}")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    with pytest.raises(AeroSuiteError, match="No display"):
        open_in_paraview([tmp_path / "flow.vtu"])
