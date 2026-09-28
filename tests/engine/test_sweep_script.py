"""The bundled aoa_sweep_v8.py, run against a stand-in SU2 package that records each case it is given."""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

SWEEP_SCRIPT = Path(__file__).resolve().parents[2] / "aerosuite" / "resources" / "aoa_sweep_v8.py"

# Just enough of SU2's Python package for the script: Config reads KEY= VALUE lines, and run.CFD
# behaves like SU2 on restarts: with RESTART_SOL= YES it must open SOLUTION_FILENAME or fail.
FAKE_SU2 = {
    "__init__.py": "from . import io, run\n",
    "io.py": textwrap.dedent('''
        class Config(dict):
            def __init__(self, path):
                super().__init__(SOLUTION_FILENAME="solution_flow.dat", RESTART_FILENAME="restart_flow.dat",
                                 CONV_FILENAME="history", VOLUME_FILENAME="flow", SURFACE_FILENAME="surface_flow")
                for line in open(path):
                    if "=" in line and not line.lstrip().startswith("%"):
                        key, value = line.split("=", 1)
                        self[key.strip()] = value.strip()

            def __getattr__(self, name):
                try:
                    return self[name]
                except KeyError:
                    raise AttributeError(name)

            def __setattr__(self, name, value):
                self[name] = value


        class State:
            def find_files(self, config):
                pass

            def update(self, info):
                pass
    '''),
    "run.py": textwrap.dedent('''
        import json, os

        def CFD(config):
            case = os.path.dirname(config.RESTART_FILENAME)
            restart = config.get("RESTART_SOL", "NO").upper() == "YES"
            with open(os.environ["FAKE_SU2_RECORD"], "a") as record:
                record.write(json.dumps({"case": case, "restart_sol": restart,
                                         "solution": config.SOLUTION_FILENAME}) + "\\n")
            if restart and not os.path.isfile(config.SOLUTION_FILENAME):
                raise RuntimeError("Unable to open SU2 restart file " + config.SOLUTION_FILENAME)
            if case in os.environ.get("FAKE_SU2_FAIL", "").split(","):
                raise RuntimeError("NaN in the residuals")
            open(config.RESTART_FILENAME, "w").write("restart")
            return {}
    '''),
}


def _run_sweep(tmp_path, control_lines, fail=(), restart_sol="YES"):
    su2_dir = tmp_path / "su2" / "SU2"
    su2_dir.mkdir(parents=True)
    for name, text in FAKE_SU2.items():
        (su2_dir / name).write_text(text)
    configs = tmp_path / "configs"
    configs.mkdir()
    for line in control_lines:
        (configs / line.split(",")[0].strip()).write_text(f"MACH_NUMBER= 0.8\nRESTART_SOL= {restart_sol}\n")
    control = configs / "run_control.txt"
    control.write_text("\n".join(control_lines) + "\n")
    runs = tmp_path / "runs"
    runs.mkdir()
    record = tmp_path / "record.jsonl"
    env = {**os.environ, "SU2_RUN": str(su2_dir.parent), "FAKE_SU2_RECORD": str(record),
           "FAKE_SU2_FAIL": ",".join(fail), "PYTHONIOENCODING": "utf-8"}  # the script prints ✓
    done = subprocess.run(
        [sys.executable, str(SWEEP_SCRIPT), "-d", str(configs), "-c", str(control)],
        cwd=runs, input="yes\n", capture_output=True, text=True, encoding="utf-8", env=env, timeout=60,
    )
    assert done.returncode == 0, done.stdout + done.stderr
    return {row["case"]: row for row in map(json.loads, record.read_text().splitlines())}


def test_a_previous_case_after_a_failed_case_starts_from_scratch(tmp_path):
    """The script says "Starting from scratch instead", so SU2 must not be told to read a restart."""
    runs = _run_sweep(tmp_path, ["a.cfg, none", "b.cfg, previous", "c.cfg, previous"], fail=["a"])
    assert runs["b"]["restart_sol"] is False
    assert runs["c"]["restart_sol"] is True  # b ran from scratch and succeeded, so c continues from it
    assert runs["c"]["solution"] == "b/restart_flow.dat"


def test_every_missing_restart_falls_back_to_a_fresh_start(tmp_path):
    runs = _run_sweep(tmp_path, [
        "a.cfg, previous",  # first line: nothing before it
        "b.cfg, custom, /no/such/restart.dat",
        "c.cfg, from_case, never_run.cfg",
        "d.cfg, initial",  # no -r given
    ])
    assert [runs[case]["restart_sol"] for case in "abcd"] == [False] * 4


def test_a_none_case_never_reads_a_restart(tmp_path):
    runs = _run_sweep(tmp_path, ["a.cfg, none", "b.cfg, none"])
    assert runs["b"]["restart_sol"] is False


def test_a_previous_case_after_a_success_restarts_from_it(tmp_path):
    runs = _run_sweep(tmp_path, ["a.cfg, none", "b.cfg, previous"])
    assert runs["b"]["restart_sol"] is True
    assert runs["b"]["solution"] == "a/restart_flow.dat"
