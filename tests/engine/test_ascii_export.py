import subprocess
from pathlib import Path

import pytest

from aerosuite.engine.ascii_export import (ASCII_CFG, ascii_config, ascii_script, local_script, sol_launch,
                                           write_ascii)
from aerosuite.engine.errors import JobError
from aerosuite.engine.jobs.executors import SlurmOptions
from aerosuite.engine.settings import AppSettings, SlurmSettings

from slurm_helpers import A0, slurm_study  # noqa: F401  (fixture)

CFG = """MESH_FILENAME= /data/mesh/wing.su2
SOLUTION_FILENAME= /data/s/runs/M0p6_0km_a5/restart_flow
OUTPUT_FILES= PARAVIEW, SURFACE_PARAVIEW, RESTART
VOLUME_FILENAME= flow
"""
FAKE_SU2_SOL = """#!/bin/bash
vol=$(sed -n 's/^VOLUME_FILENAME= //p' "$1"); surf=$(sed -n 's/^SURFACE_FILENAME= //p' "$1")
echo "volume" > "$vol.vtk"; echo "surface" > "$surf.vtk"
"""


def test_the_config_reads_its_own_restart_and_writes_ascii_to_scratch():
    text = ascii_config(CFG, Path("/data/s/runs/M0p6_0km_a10/restart_flow.dat"), "/tmp/x")
    assert "SOLUTION_FILENAME= /data/s/runs/M0p6_0km_a10/restart_flow\n" in text  # its own, not the one it began from
    assert "OUTPUT_FILES= PARAVIEW_ASCII, SURFACE_PARAVIEW_ASCII\n" in text
    assert "VOLUME_FILENAME= /tmp/x/flow\n" in text
    assert text.rstrip().endswith("SURFACE_FILENAME= /tmp/x/surface_flow")  # SU2's default name, added
    assert "MESH_FILENAME= /data/mesh/wing.su2" in text


@pytest.mark.parametrize("launch, expected", [
    ("srun --mpi=pmix SU2_CFD", "srun --mpi=pmix SU2_SOL"),
    ('mpirun --bind-to core -np "$SLURM_NTASKS" SU2_CFD', 'mpirun --bind-to core -np "$SLURM_NTASKS" SU2_SOL'),
    ("/opt/su2/bin/SU2_CFD", "/opt/su2/bin/SU2_SOL"),
])
def test_su2_sol_starts_as_su2_cfd_does(launch, expected):
    assert sol_launch(launch) == expected


def test_a_launch_without_su2_cfd_is_refused():
    with pytest.raises(JobError, match="SU2_SOL"):
        sol_launch("mpirun -np 4 SU2_CFD_AD")


def _case(tmp_path):
    folder, bin_dir, scratch = tmp_path / "runs" / "M0p6_0km_a10", tmp_path / "bin", tmp_path / "scratch"
    folder.mkdir(parents=True)
    bin_dir.mkdir()
    (bin_dir / "SU2_SOL").write_text(FAKE_SU2_SOL)
    (bin_dir / "SU2_SOL").chmod(0o755)
    (folder / ASCII_CFG).write_text(ascii_config(CFG, folder / "restart_flow.dat", str(scratch)))
    return folder, bin_dir, scratch


def _run(folder, script, bin_dir):
    (folder / "to_ascii.sh").write_text(script)
    return subprocess.run(["bash", "to_ascii.sh"], cwd=folder, capture_output=True, text=True,
                          env={"PATH": f"{bin_dir}:/usr/bin:/bin", "SLURM_SUBMIT_DIR": str(folder)})


def test_the_slurm_script_writes_the_files_into_the_case_folder(tmp_path):
    folder, bin_dir, scratch = _case(tmp_path)
    options = SlurmOptions(partition="node1", ntasks=96, time_limit="", exclusive=True, account="")
    script = ascii_script("study", "M0p6_0km_a10", options, SlurmSettings(module_line=":", su2_bin=str(bin_dir),
                                                                          srun_command="SU2_CFD"), str(scratch))
    assert "#SBATCH -p node1" in script and "#SBATCH -t 2:00:00" in script  # never runs on forever
    assert "#SBATCH -o to_ascii-%j.out" in script and "#SBATCH -J study/M0p6_0km_a10-ascii" in script
    done = _run(folder, script, bin_dir)
    assert done.returncode == 0, done.stderr
    assert (folder / "flow.vtk").read_text() == "volume\n" and (folder / "surface_flow.vtk").read_text() == "surface\n"
    assert not scratch.exists()  # the node's scratch folder is cleaned up


def test_the_local_script_does_the_same_on_this_machine(tmp_path):
    folder, bin_dir, scratch = _case(tmp_path)
    done = _run(folder, local_script(1, str(scratch)), bin_dir)
    assert done.returncode == 0, done.stderr
    assert (folder / "flow.vtk").is_file() and not scratch.exists()


def test_a_case_without_a_restart_has_nothing_to_write_from(ready_project):
    project_dir, project = ready_project
    (project_dir / "runs" / project.cases[0].name).mkdir(parents=True)
    with pytest.raises(JobError, match="no restart file"):
        write_ascii(project_dir, project, project.cases[0].name, AppSettings())


def test_a_case_still_running_is_refused(slurm_study):
    project_dir, project, runner, fake = slurm_study
    runner.submit(project_dir, project, cases=[A0])
    fake.run("101")
    (project_dir / "runs" / A0 / "restart_flow.dat").write_text("solution")
    with pytest.raises(JobError, match="pending in job .*once it has ended"):
        write_ascii(project_dir, project, A0, AppSettings())
