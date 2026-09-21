"""
Sweep Runner - SU2 Batch Execution Engine.

Launches the sweep script (aoa_sweep_v8.py or compatible) as a subprocess
from inside the config directory — exactly as it was used from the terminal:

    cd cfg_dir
    python aoa_sweep_v8.py -d . -c run_control.txt -n 64

The script owns all path resolution, restart chaining, and MPI handling.
AeroSuite owns the GUI wrapper: live status table and stop control.
"""

import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from aerosuite.engine.jobs.runner import resolve_sweep_python, sweep_environment
from aerosuite.engine.jobs.store import kill_tree
from aerosuite.engine.results import HISTORY_FILE, check_convergence, read_history


def _convergence_status(folder: str) -> Tuple[str, Optional[str]]:
    """CONVERGED / UNCONVERGED from the case's history, or FAILED if there is none."""
    history = os.path.join(folder, HISTORY_FILE)
    if not os.path.isfile(history):
        return "FAILED", "No history.csv was written"
    df = read_history(history)
    if df.empty:
        return "FAILED", "history.csv is empty"
    converged, message = check_convergence(df)
    return ("CONVERGED", None) if converged else ("UNCONVERGED", message)


def parse_control_file(path: str) -> Tuple[List[Dict], List[str]]:
    """
    Parse a batch control file for display in the execution plan table.

    Each non-comment line must be:
        config.cfg, restart_option[, optional_custom_path]

    restart_option: none | previous | custom

    Returns (run_list, warnings).
    """
    run_list: List[Dict] = []
    warnings: List[str] = []

    with open(path, "r") as fh:
        for lineno, raw in enumerate(fh, 1):
            line = raw.strip()
            if not line or line.startswith("#"):
                continue

            parts = [p.strip() for p in line.split(",")]
            if len(parts) < 2:
                warnings.append(f"Line {lineno}: too few fields — skipped")
                continue

            cfg_file       = parts[0]
            restart_option = parts[1].lower()
            restart_path   = parts[2] if len(parts) > 2 else None

            if restart_option not in {"none", "previous", "custom"}:
                warnings.append(
                    f"Line {lineno}: unknown restart option "
                    f"'{restart_option}' — skipped"
                )
                continue

            if restart_option == "custom" and not restart_path:
                warnings.append(
                    f"Line {lineno}: 'custom' requires a restart path — skipped"
                )
                continue

            run_list.append({
                "cfg_file":       cfg_file,
                "restart_option": restart_option,
                "restart_path":   restart_path,
            })

    return run_list, warnings


class SweepRunner:
    """
    Runs the sweep script as a subprocess from inside cfg_dir.

    The subprocess is detached (start_new_session=True) so that closing
    AeroSuite does NOT kill SU2 — the simulation continues independently.
    Use stop() to explicitly kill the simulation when needed.

    A timestamped log file is written to cfg_dir — tail it live with:
        tail -f sweep_YYYYMMDD_HHMM.log

    Callbacks
    ---------
    progress_cb(done, total)         called each time a new case banner appears
    case_status_cb(cfg_file, status) called with status: RUNNING
    """

    def __init__(
        self,
        script_path:     str,
        cfg_dir:         str,
        control_file:    str,
        partitions:      int = 1,
        progress_cb:     Optional[Callable[[int, int], None]] = None,
        case_status_cb:  Optional[Callable[[str, str], None]] = None,
    ):
        self.script_path    = script_path
        self.cfg_dir        = cfg_dir
        self.control_file   = control_file
        self.partitions     = partitions
        self.progress_cb    = progress_cb    or (lambda done, total: None)
        self.case_status_cb = case_status_cb or (lambda cfg, status: None)
        self.log_path:      Optional[str]   = None
        self._proc:         Optional[subprocess.Popen] = None
        self._stopped:      bool            = False

    def stop(self):
        """
        Kill the running sweep process and its entire process group (mpirun + SU2).
        Safe to call at any time; does nothing if already finished.
        """
        self._stopped = True
        if self._proc and self._proc.poll() is None:
            kill_tree(self._proc.pid)  # script + mpirun + SU2 ranks, on every platform

    def run(self) -> List[Dict]:
        """
        Launch the sweep script and wait for it to finish.

        All output goes directly to a timestamped log file — no terminal output.
        Tail the log file externally for live progress.

        Returns a list of result dicts (one per case in the control file).
        """
        # The sweep script imports SU2, so it runs under the system Python, never
        # AeroSuite's own environment. AEROSUITE_SWEEP_PYTHON overrides the choice.
        interpreter = resolve_sweep_python(os.environ.get("AEROSUITE_SWEEP_PYTHON", "python3"))
        cmd = [
            interpreter,
            self.script_path,
            "-d", ".",
            "-c", self.control_file,
            "-n", str(self.partitions),
        ]

        timestamp     = datetime.now().strftime("%Y%m%d_%H%M")
        self.log_path = os.path.join(self.cfg_dir, f"sweep_{timestamp}.log")

        header_lines = [
            f"{'='*60}",
            f"  AeroSuite — Sweep Runner",
            f"  Started  : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Python   : {interpreter}",
            f"  Script   : {self.script_path}",
            f"  Dir      : {self.cfg_dir}",
            f"  Log file : {self.log_path}",
            f"  Command  : {' '.join(cmd)}",
            f"  Tip      : tail -f {self.log_path}",
            f"{'='*60}",
            "",
        ]

        try:
            run_list, _ = parse_control_file(self.control_file)
        except Exception:
            run_list = []
        total = len(run_list)

        case_re = re.compile(r"Running Case\s+\d+/\d+:\s+(\S+\.cfg)", re.IGNORECASE)
        iter_re = re.compile(r"Iterations completed[:\s]+(.+)", re.IGNORECASE)

        case_done    = 0
        current_case: Optional[str] = None
        case_iters:  Dict[str, str] = {}

        try:
            with open(self.log_path, "w", buffering=1) as log_fh:
                for line in header_lines:
                    log_fh.write(line + "\n")
                log_fh.flush()

                self._proc = subprocess.Popen(
                    cmd,
                    cwd=self.cfg_dir,
                    stdin=subprocess.PIPE,
                    stdout=log_fh,
                    stderr=log_fh,
                    env=sweep_environment(),
                    start_new_session=True,     # detach — closing AeroSuite won't kill SU2
                )

                try:
                    self._proc.stdin.write(b"yes\n")
                    self._proc.stdin.flush()
                    self._proc.stdin.close()
                except BrokenPipeError:
                    pass

            # Tail the log to fire status/progress callbacks — no terminal output
            log_pos = 0
            while self._proc.poll() is None:
                if self._stopped:
                    break
                with open(self.log_path, "r", errors="replace") as tail_fh:
                    tail_fh.seek(log_pos)
                    for line in tail_fh:
                        stripped = line.rstrip()
                        m = case_re.search(stripped)
                        if m:
                            current_case = m.group(1)
                            case_done += 1
                            self.case_status_cb(current_case, "RUNNING")
                            if total:
                                self.progress_cb(case_done, total)
                        m = iter_re.search(stripped)
                        if m and current_case:
                            case_iters[current_case] = m.group(1).strip()
                    log_pos = tail_fh.tell()
                time.sleep(0.5)

            # Final read after process exits
            if not self._stopped:
                with open(self.log_path, "r", errors="replace") as tail_fh:
                    tail_fh.seek(log_pos)
                    for line in tail_fh:
                        stripped = line.rstrip()
                        m = case_re.search(stripped)
                        if m:
                            current_case = m.group(1)
                            case_done += 1
                            self.case_status_cb(current_case, "RUNNING")
                            if total:
                                self.progress_cb(case_done, total)
                        m = iter_re.search(stripped)
                        if m and current_case:
                            case_iters[current_case] = m.group(1).strip()

            with open(self.log_path, "a") as log_fh:
                stopped_note = "  ** Stopped by user **\n" if self._stopped else ""
                footer = (
                    f"\n{'='*60}\n"
                    f"  Finished : {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                    f"  Exit code: {self._proc.returncode}\n"
                    f"{stopped_note}"
                    f"{'='*60}\n"
                )
                log_fh.write(footer)

        except FileNotFoundError:
            raise RuntimeError(
                f"Cannot start the sweep:\n  {interpreter} {self.script_path}\n"
                "Check the script path in the Sweep Runner tab, and set "
                "AEROSUITE_SWEEP_PYTHON if python3 is not the Python that imports SU2."
            )

        return self._build_results(run_list, case_iters)

    def _build_results(
        self,
        run_list:   List[Dict],
        case_iters: Dict[str, str],
    ) -> List[Dict]:
        """
        Inspect case output folders to determine success/failure and
        merge in iteration counts captured from the log.
        """
        results = []
        for item in run_list:
            cfg_file  = item["cfg_file"]
            folder    = os.path.join(self.cfg_dir, Path(cfg_file).stem)
            error_log = os.path.join(folder, "error.log")

            if os.path.isfile(error_log):
                status = "FAILED"
                with open(error_log) as fh:
                    error = fh.read().strip()
            elif os.path.isdir(folder):
                status, error = _convergence_status(folder)
            elif self._stopped:
                status = "STOPPED"
                error  = None
            else:
                status = "NOT RUN"
                error  = None

            results.append({
                "cfg_file":       cfg_file,
                "status":         status,
                "restart_option": item["restart_option"],
                "iterations":     case_iters.get(cfg_file, "—"),
                "error":          error,
            })

        return results
