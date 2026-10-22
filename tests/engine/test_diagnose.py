"""Why a case failed, in plain words (from the ends of real SU2 and Slurm outputs on hpc1, trimmed)."""
import pytest

from aerosuite.engine.jobs.diagnose import diagnose, last_iteration, residual_trend

DIVERGED = """Slurm: FAILED (exit 1:0) on hpc1.
|         591|    3.584994|  3.8582e+00|  1.0000e+00|    0.922846|    0.978883|
|         592|    3.600066|  3.8578e+00|  1.0000e+00|    0.922425|    0.977734|


Error in "void CSolver::SetResidual_RMS(const CGeometry*, const CConfig*)":
-------------------------------------------------------------------------
SU2 has diverged (NaN detected).
------------------------------ Error Exit -------------------------------


[2026-10-22T11:53:13.787] error: *** STEP 45.0 ON hpc1 CANCELLED AT 2026-10-22T11:53:13 DUE TO TASK FAILURE ***
srun: error: hpc1: tasks 31,33,35: Exited with exit code 1
AEROSUITE_EXIT 1 2026-10-22T11:53:15+09:00
"""
CONFIG = """Slurm: FAILED (exit 1:0) on hpc1.
AeroSuite: Slurm job 48 on hpc1, 96 ranks, start 2026-10-22T13:46:14+09:00

Error in "void CConfig::SetPostprocessing(SU2_COMPONENT, short unsigned int, short unsigned int)":
-------------------------------------------------------------------------
CFL adaption factor down should be less than 1.0.
------------------------------ Error Exit -------------------------------
srun: error: hpc1: tasks 60,62,64,78,80: Exited with exit code 1
AEROSUITE_EXIT 1 2026-10-22T13:46:20+09:00
"""
MESH = """SU2 exited with code 1.
Error in "static short unsigned int CConfig::GetnDim(const std::string&, short unsigned int)":
-------------------------------------------------------------------------
The SU2 mesh file named /data/x07/mesh/wing.su2 was not found.
------------------------------ Error Exit -------------------------------
"""
TIMEOUT = """Slurm: TIMEOUT (exit 0:15) on hpc1.
|        4812|    3.6|  3.8e+00|  1.0e+00|    0.92|    0.97|
slurmstepd: error: *** JOB 61 ON hpc1 CANCELLED AT 2026-10-23T01:00:00 DUE TO TIME LIMIT ***
"""
LAUNCH = """Slurm: FAILED (exit 2:0) on hpc1.
AeroSuite: Slurm job 70 on hpc1, 96 ranks, start 2026-10-22T13:46:14+09:00
/var/spool/slurm/d/job00070/slurm_script: line 9: SU2_CFD: command not found
AEROSUITE_EXIT 127 2026-10-22T13:46:15+09:00
"""


@pytest.mark.parametrize("tail, state, kind, summary", [
    (DIVERGED, "FAILED", "diverged", "Diverged at iteration 592 (SU2 found NaN)"),
    (CONFIG, "FAILED", "config", "SU2 rejected the config: CFL adaption factor down should be less than 1.0."),
    (MESH, None, "mesh", "SU2 couldn't read the mesh: The SU2 mesh file named /data/x07/mesh/wing.su2 was not found."),
    (TIMEOUT, "TIMEOUT", "time_limit", "Stopped at the time limit (12:00:00) at iteration 4812"),
    (LAUNCH, "FAILED", "launch", "SU2 didn't start: /var/spool/slurm/d/job00070/slurm_script: line 9: SU2_CFD: "
                                 "command not found"),
    ("Slurm: OUT_OF_MEMORY (exit 0:125) on hpc2.\n", "OUT_OF_MEMORY", "memory", "Ran out of memory"),
    ("Slurm: NODE_FAIL (exit 0:0) on hpc2.\n", "NODE_FAIL", "node", "The node failed"),
    ("Cancelled from the Cluster page.", "CANCELLED", "cancelled", "Cancelled from the Cluster page."),
    ("Not run: M0p8_a0 ended FAILED, so its solution, which M0p8_a2 restarts from, does not exist.", None, "blocked",
     "M0p8_a0 ended FAILED, so its solution, which M0p8_a2 restarts from, does not exist."),
    ("SU2 exited with code 3. No Slurm accounting record.\n", "FAILED", "failed", "SU2 exited with code 3"),
])
def test_each_failure_reads_in_plain_words(tail, state, kind, summary):
    found = diagnose(tail, state, time_limit="12:00:00")
    assert (found.kind, found.summary) == (kind, summary)


def test_every_kind_but_a_plain_stop_says_what_to_try():
    assert diagnose(DIVERGED, "FAILED").advice == ("Rerun with a lower CFL or a first-order start, from its last "
                                                   "solution")
    assert diagnose(TIMEOUT, "TIMEOUT").advice == "Continue from its last solution, with a longer time limit"


def test_the_last_iteration_is_read_from_su2s_screen_table():
    assert last_iteration(DIVERGED) == 592 and last_iteration(CONFIG) is None


@pytest.mark.parametrize("rms, words", [
    ([-3.0 - i * 0.01 for i in range(100)] + [-3.99 + i * 0.03 for i in range(60)],  # down, then up by 1.8
     "the residuals were rising (rms[Rho] from 1e-4.0 at iteration 99 to 1e-2.2)"),
    ([-2.0 - i * 0.02 for i in range(80)] + [-3.6] * 60, "the residuals had stopped falling (rms[Rho] around 1e-3.6)"),
    ([-2.0 - i * 0.05 for i in range(60)], ""),  # still falling: nothing to say
])
def test_the_residuals_before_a_divergence_in_words(tmp_path, rms, words):
    history = tmp_path / "history.csv"
    rows = [f"{i}, {value}, 0.5" for i, value in enumerate(rms)]
    history.write_text('"Inner_Iter","rms[Rho]","CD"\n' + "\n".join(rows) + "\n")
    assert residual_trend(history) == words
    assert residual_trend(tmp_path / "missing.csv") == ""
