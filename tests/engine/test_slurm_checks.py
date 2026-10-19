import builtins

import pytest

from aerosuite.engine import slurm_checks
from aerosuite.engine.cfg import generate_configs
from aerosuite.engine.jobs.executors import slurm_options
from aerosuite.engine.preflight import preflight
from aerosuite.engine.project import save_project, set_mesh
from aerosuite.engine.settings import AppSettings, set_value
from aerosuite.engine.slurm_checks import memory_check, memory_notes, mesh_elements, slurm_problems

MESH_HEADER = "% a comment\n%\nNDIME= 3\nNELEM= {nelem}\n"


def _mesh(path, nelem, tail=""):
    path.write_text(MESH_HEADER.format(nelem=nelem) + tail + "NMARK= 2\nMARKER_TAG= farfield\nMARKER_TAG= wall\n")
    return path


def _settings(root, **values):
    settings = set_value(AppSettings(), "slurm.shared_root", str(root))
    for key, value in values.items():
        settings = set_value(settings, key, value)
    return settings


@pytest.fixture
def study(ready_project, tmp_path, fake_slurm):
    """ready_project with a 15M-cell mesh header, configs generated, everything under tmp_path."""
    project_dir, project = ready_project
    set_mesh(project, _mesh(tmp_path / "wing.su2", 15_000_000))
    save_project(project_dir, project)
    generate_configs(project_dir, project)
    return project_dir, project


def _problems(study, settings, partition="node1", ntasks=None, time_limit=None, cases=None, read_configs=True):
    project_dir, project = study
    return slurm_problems(project_dir, project, cases, partition, ntasks, time_limit, settings, read_configs)


def _messages(problems, severity):
    return [p.message for p in problems if p.severity == severity]


def test_mesh_elements_from_the_header(tmp_path):
    assert mesh_elements(_mesh(tmp_path / "m.su2", 15_000_000)) == 15_000_000
    assert mesh_elements(tmp_path / "missing.su2") is None
    (tmp_path / "m.cgns").write_bytes(b"\x89HDF")
    assert mesh_elements(tmp_path / "m.cgns") is None
    (tmp_path / "no.su2").write_text("NDIME= 3\nNPOIN= 10\n")
    assert mesh_elements(tmp_path / "no.su2") is None


def test_mesh_elements_reads_only_the_first_lines(tmp_path, monkeypatch):
    path = tmp_path / "big.su2"
    with open(path, "w") as fh:
        fh.write("NDIME= 3\n")
        fh.write("x" * 1_000_000 + "\n")  # one enormous "line"
        for _ in range(100_000):
            fh.write("1 2 3 4 5\n")
        fh.write("NELEM= 7\n")  # too far down to be a header
    read = []
    real_open = builtins.open

    def counting_open(*args, **kwargs):
        handle = real_open(*args, **kwargs)
        real_readline = handle.readline

        def readline(limit=-1):
            line = real_readline(limit)
            read.append(len(line))
            return line

        handle.readline = readline
        return handle

    monkeypatch.setattr(builtins, "open", counting_open)
    assert mesh_elements(path) is None
    assert len(read) <= slurm_checks.HEADER_LINES
    assert max(read) <= slurm_checks.LINE_LIMIT


def test_memory_check_note():
    check = memory_check("/data/x.su2", "node1", AppSettings())
    assert check.estimate_gb is None and "No memory estimate" in check.note
    assert memory_check("/data/x.su2", "node9", AppSettings()) is None


def test_a_good_submit_has_no_problems(study, tmp_path):
    problems = _problems(study, _settings(tmp_path))
    assert problems == []


def test_memory_estimate_in_the_notes(study, tmp_path):
    project_dir, project = study
    notes = memory_notes(project_dir, project, None, "node1", _settings(tmp_path))
    assert notes == ["≈ 58 GB of 120 GB on node1 (15.0M cells)"]


def test_over_the_limit_warns_on_node1_and_blocks_on_node2(study, tmp_path):
    project_dir, project = study
    set_mesh(project, _mesh(tmp_path / "wing.su2", 40_000_000))  # ≈ 156 GB
    generate_configs(project_dir, project)
    settings = _settings(tmp_path)
    node1 = _problems(study, settings, "node1")
    assert _messages(node1, "error") == []
    assert any("over node1's 120 GB" in m for m in _messages(node1, "warning"))
    set_mesh(project, _mesh(tmp_path / "wing.su2", 16_000_000))  # ≈ 62.4 GB: under node1, over node2's 60.5
    generate_configs(project_dir, project)
    assert _problems(study, settings, "node1") == []
    node2 = _problems(study, settings, "node2")
    assert any("OUT_OF_MEMORY" in m and "node2" in m for m in _messages(node2, "error"))


def test_outside_the_shared_root_is_an_error(study, tmp_path):
    problems = _problems(study, _settings(tmp_path / "elsewhere"))
    errors = _messages(problems, "error")
    assert any("must be under" in m and "elsewhere" in m for m in errors)
    assert any("Other nodes cannot see" in m for m in _messages(problems, "warning"))


def test_mesh_outside_the_shared_root_is_a_warning(study, tmp_path):
    project_dir, project = study
    settings = _settings(project_dir)  # the study is under the root, the mesh (tmp_path/wing.su2) is not
    problems = _problems(study, settings)
    assert _messages(problems, "error") == []
    assert [m for m in _messages(problems, "warning") if "wing.su2" in m]


def test_too_many_tasks_on_node2_warns_only(study, tmp_path):
    problems = _problems(study, _settings(tmp_path), "node2", ntasks=96)
    assert _messages(problems, "error") == []
    assert _messages(problems, "warning") == ["node2 gains nothing above about 48 tasks; 96 asked"]
    assert _problems(study, _settings(tmp_path), "node2", ntasks=48) == []


def test_partition_tasks_and_time_limit_are_checked(study, tmp_path):
    settings = _settings(tmp_path)
    assert any("Unknown partition 'node9'" in m for m in _messages(_problems(study, settings, "node9"), "error"))
    assert any("at least 1" in m for m in _messages(_problems(study, settings, ntasks=0), "error"))
    assert any("Time limit 'soon'" in m for m in _messages(_problems(study, settings, time_limit="soon"), "error"))
    assert _problems(study, settings, time_limit="2-00:00:00") == []


def test_missing_configs_and_bad_mesh_lines(study, tmp_path):
    project_dir, project = study
    settings = _settings(tmp_path)
    (project_dir / "configs" / "M0p8_a2_b0.cfg").unlink()
    errors = _messages(_problems(study, settings), "error")
    assert errors == ["Configs are missing for M0p8_a2_b0; generate configs first"]
    assert _problems(study, settings, read_configs=False) == []  # the web generates them at Submit
    cfg = project_dir / "configs" / "M0p8_a0_b0.cfg"
    cfg.write_text(cfg.read_text().replace(f"MESH_FILENAME= {tmp_path / 'wing.su2'}", "MESH_FILENAME= wing.su2"))
    errors = _messages(_problems(study, settings, cases=["M0p8_a0_b0"]), "error")
    assert errors == ["MESH_FILENAME must be an absolute path for a Slurm job: wing.su2"]
    cfg.write_text(cfg.read_text().replace("MESH_FILENAME= wing.su2", f"MESH_FILENAME= {tmp_path / 'gone.su2'}"))
    errors = _messages(_problems(study, settings, cases=["M0p8_a0_b0"]), "error")
    assert errors == [f"Mesh not found: {tmp_path / 'gone.su2'}"]


def test_sbatch_missing_is_an_error(study, tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path / "empty-bin"))
    errors = _messages(_problems(study, _settings(tmp_path)), "error")
    assert any("sbatch was not found on PATH" in m for m in errors)


def test_preflight_uses_the_slurm_checks_for_a_slurm_project(study, tmp_path, monkeypatch):
    project_dir, project = study
    monkeypatch.delenv("SU2_RUN", raising=False)
    settings = _settings(tmp_path)
    local = preflight(project_dir, project, "submit", settings=settings)
    assert any("SU2_RUN" in p.message for p in local)
    project.run.backend = "slurm"
    slurm = preflight(project_dir, project, "submit", settings=settings)
    assert not any("SU2_RUN" in p.message for p in slurm)
    assert slurm == []
    options = slurm_options(project, settings, partition="node2", ntasks=96)
    problems = preflight(project_dir, project, "run", options=options, settings=settings)
    assert [p.message for p in problems] == ["node2 gains nothing above about 48 tasks; 96 asked"]
