"""SlurmRunner: each case of a job is one Slurm batch job, submitted from its own case folder.

A submit writes runs/<case>/<case>.cfg and a self-contained runs/<case>/su2_job.sh (so the folder records exactly
how the case ran), then `sbatch --parsable` from that folder. A case that restarts from a case running earlier in
the same job waits for it to end, however it ends (--dependency=afterany). Each script writes its SU2 exit code to
aerosuite_exit; the waiting case restarts only when that says 0 and the solution file exists, else it sets
RESTART_SOL= NO in its cfg and starts from scratch, as the local sweep script does. (Jobs submitted before this
waited with afterok and were cancelled by Slurm when the case failed; AeroSuite shows those BLOCKED.)

States come from one poll (engine/slurm.py: one squeue, at most one sacct): queued -> PENDING/RUNNING; left the
queue -> its accounting row (COMPLETED is judged from history.csv as locally); without accounting, the case's
slurm-<id>.out. A failed squeue never changes a state. The web applies the server poller's snapshot
(`apply_snapshot`, no subprocess on the event loop); the CLI calls `refresh`, which queries Slurm itself.
"""
from __future__ import annotations

import functools
import json
import os
import re
import shlex
import shutil
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Mapping, Optional, Sequence

from ..cfg import CONFIGS_DIR, RUN_CONTROL_FILE, apply_parameters
from ..errors import JobError
from ..models import Project
from ..restarts import DEFAULT_RESTART_NAME, RUNS_DIR
from ..results import HISTORY_FILE, check_convergence, read_history
from ..settings import AppSettings, SlurmSettings, current_settings, env_pairs
from .. import slurm as sl
from .executors import SlurmOptions, slurm_options
from ..attempts import archive_before_rerun, keep_aside, settle_attempts
from .diagnose import diagnose
from .rerun import describe
from .plan import _batches, _referenced_case, drop_kept, prepare_job, prune_restarts
from .runner import (FINAL_CASE_STATES, CaseState, JobRecord, JobState, SlurmCase, new_job_id, sweep_environment,
                     unfinished)
from .store import JOBS_DIR, active_lock, clear_lock, load_job, save_job, write_lock

JOB_SCRIPT = "su2_job.sh"
STATS_FILE = "slurm_stats.json"
EXIT_MARK = "AEROSUITE_EXIT"
EXIT_FILE = "aerosuite_exit"  # the case's SU2 exit code, for the case that restarts from it
FALLBACK_POLLS = 10  # polls without an accounting row before the case's files decide
SEFF_TRIES = 3
TAIL_LINES = 50
_SAFE = re.compile(r"^[A-Za-z0-9_.:+-]+$")
_EXIT_RE = re.compile(rf"^{EXIT_MARK}\s+(-?\d+)", re.MULTILINE)
_RESTART_NAME_RE = re.compile(r"^\s*RESTART_FILENAME\s*=\s*(\S+)", re.MULTILINE)
_SOLUTION_RE = re.compile(r"^\s*SOLUTION_FILENAME\s*=\s*(\S+)", re.MULTILINE)
OK_STATES = {CaseState.CONVERGED, CaseState.UNCONVERGED}


# -- the job script -------------------------------------------------------------------------------------------

def _safe(what: str, value: str) -> str:
    if not _SAFE.match(value):
        raise JobError(f"{what} {value!r} may hold only letters, digits and _ . : + -")
    return value


def job_name(study: str, case: str) -> str:
    """<study>/<case>, with anything a shell or Slurm would trip over replaced by '_'."""
    return re.sub(r"[^A-Za-z0-9_.+-]", "_", study) + "/" + re.sub(r"[^A-Za-z0-9_.+-]", "_", case)


def script_head(name: str, options: SlurmOptions, slurm: SlurmSettings, comment: str, out: str = "slurm-%j.out",
                after: Optional[str] = None) -> tuple[list[str], str]:
    """A batch script's start: the #SBATCH lines, `comment`, the environment (the partition's own, else the
    Slurm-wide one) and `cd "$SLURM_SUBMIT_DIR"`; and the launch command that starts SU2_CFD there."""
    part = slurm.partition(options.partition)
    own = part if part is not None and part.launch_command else None  # a partition with its own launch command
    lines = ["#!/bin/bash" if own is not None and not own.login_shell else "#!/bin/bash -l",
             f"#SBATCH -J {name}",
             f"#SBATCH -p {_safe('Partition', options.partition)}",
             "#SBATCH -N 1",
             f"#SBATCH -n {int(options.ntasks)}"]
    if options.exclusive:
        lines.append("#SBATCH --exclusive")
    if options.account:
        lines.append(f"#SBATCH -A {_safe('Account', options.account)}")
    if options.time_limit:
        lines.append(f"#SBATCH -t {_safe('Time limit', options.time_limit)}")
    lines.append(f"#SBATCH -o {out}")
    if after:
        lines += [f"#SBATCH --dependency=afterany:{_safe('Job id', after)}", "#SBATCH --kill-on-invalid-dep=yes"]
    module_line, launch = (own.module_line, own.launch_command) if own is not None else (slurm.module_line,
                                                                                      slurm.srun_command)
    for value in (module_line, launch, slurm.su2_bin, comment):
        if "\n" in value or "\r" in value:
            raise JobError("Settings for the job script must be single lines")
    lines.append(comment)
    if own is not None:  # only its own environment: the Slurm-wide one is for the cluster's nodes
        if module_line:
            lines.append(module_line)
        lines += [f"export {name}={shlex.quote(value)}" for name, value in env_pairs(own.job_env)]
        if own.path:
            lines.append(f"export PATH={shlex.quote(own.path)}")
        if own.unset_vars.strip():
            lines.append("unset " + " ".join(own.unset_vars.split()))
    else:
        lines.append(module_line)
        lines += [f"export {name}={shlex.quote(value)}" for name, value in env_pairs(slurm.job_env)]
        lines.append(f"export PATH={shlex.quote(slurm.su2_bin)}:\"$PATH\"")
    lines.append('cd "$SLURM_SUBMIT_DIR"')
    return lines, launch


def job_script(study: str, case: str, cfg_name: str, options: SlurmOptions, slurm: SlurmSettings, job_id: str,
               after: Optional[str] = None, note: str = "",
               restart_from: Optional[tuple[str, str, str]] = None) -> str:
    """The batch script of one case (see the spec's §4.2); `after` = the Slurm job id it waits for, and
    `restart_from` = (that case, its folder, the solution file): without both its 0 exit and the file, this case
    starts from scratch."""
    comment = f"# Written by AeroSuite for job {job_id}, case {case}" + (f" ({note})" if note else "") + "."
    lines, launch = script_head(job_name(study, case), options, slurm, comment, after=after)
    lines += [f"rm -f {EXIT_FILE}",
              'echo "AeroSuite: Slurm job $SLURM_JOB_ID on $(hostname), $SLURM_NTASKS ranks, start $(date -Is)"']
    if restart_from is not None:
        source, folder, solution = restart_from
        exit_file = shlex.quote(str(Path(folder) / EXIT_FILE))
        # The solution as SU2 wrote it: the name as given, or with the .dat or .csv SU2 adds (find_restart_file's rule)
        found = " || ".join(f"[ -f {shlex.quote(solution + suffix)} ]" for suffix in ("", ".dat", ".csv"))
        lines += [f'if [ "$(cat {exit_file} 2>/dev/null)" != 0 ] || ! {{ {found}; }}; then',
                  f'  echo {shlex.quote(f"AeroSuite: {source} ended without a solution; starting from scratch")}',
                  "  sed -i -E 's/^RESTART_SOL[[:space:]]*=.*/RESTART_SOL= NO/' " + shlex.quote(cfg_name),
                  "fi"]
    lines += [f"{launch} {shlex.quote(cfg_name)}",
              "code=$?",
              f"echo $code > {EXIT_FILE}",
              f'echo "{EXIT_MARK} $code $(date -Is)"',
              "exit $code"]
    return "\n".join(lines) + "\n"


# -- helpers --------------------------------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _tail(text: str, lines: int = TAIL_LINES) -> str:
    return "\n".join(text.splitlines()[-lines:])


def _restart_name(cfg_text: str) -> str:
    match = _RESTART_NAME_RE.search(cfg_text)
    return match.group(1) if match else DEFAULT_RESTART_NAME


def _control_lines(control: Path) -> list[tuple[str, str, Optional[str]]]:
    """(case, option, reference) per line of the job's run_control.txt."""
    lines = []
    for raw in _read(control).splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        parts = [part.strip() for part in raw.split(",", 2)]
        name = parts[0][:-4] if parts[0].endswith(".cfg") else parts[0]
        lines.append((name, parts[1] if len(parts) > 1 else "none", parts[2] if len(parts) > 2 else None))
    return lines


def _iterations(history: Path) -> Optional[int]:
    try:
        df = read_history(history) if history.is_file() else None
    except Exception:
        return None
    if df is None or df.empty:
        return None
    for column in ("Inner_Iter", "Outer_Iter", "Time_Iter", "Iteration"):
        if column in df.columns:
            try:
                return int(df[column].iloc[-1] - df[column].iloc[0]) + 1
            except (TypeError, ValueError):
                break
    return len(df)


TIME_COLUMN = "Time(sec)"  # SU2's WALL_TIME history output: seconds per iteration, then (same name) their average


def _su2_seconds_per_iter(history: Path) -> Optional[float]:
    """The mean of SU2's own per-iteration wall time (the first Time(sec) column), or None without one.

    Unlike elapsed / iterations it leaves out reading and partitioning the mesh and writing the solution, which
    dominate a short run."""
    try:
        df = read_history(history) if history.is_file() else None
    except Exception:
        return None
    if df is None or df.empty:
        return None
    positions = [i for i, name in enumerate(df.columns) if name == TIME_COLUMN]
    if not positions:
        return None
    try:
        value = float(df.iloc[:, positions[0]].mean())
    except (TypeError, ValueError):
        return None
    return value if value > 0 and value == value else None


def case_stats(project_dir: Path, case: str) -> Optional[dict]:
    """runs/<case>/slurm_stats.json, or None."""
    try:
        data = json.loads((Path(project_dir) / RUNS_DIR / case / STATS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _serialized(method):
    """Job records change under one lock: the web's poller thread and a Cancel must not undo each other."""

    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapper


class SlurmRunner:
    backend = "slurm"

    def __init__(self, settings_loader=current_settings) -> None:
        self._settings = settings_loader
        self._lock = threading.RLock()

    # -- submit -----------------------------------------------------------------------------------------------

    @_serialized
    def submit(self, project_dir: Path, project: Project, cases: Optional[Sequence[str]] = None,
               continue_cases: Iterable[str] = (), options: Optional[SlurmOptions] = None,
               changes: Optional[Mapping[str, Mapping[str, str]]] = None, starts: Optional[Mapping[str, Optional[str]]] = None) -> JobRecord:
        project_dir = Path(project_dir).resolve()
        if active_lock(project_dir):
            raise JobError("A job is already running for this project")
        settings = self._settings()
        options = options or slurm_options(project, settings)
        for folder in (project_dir / JOBS_DIR, project_dir / RUNS_DIR):
            try:
                folder.mkdir(exist_ok=True)
            except OSError as exc:
                raise JobError(f"Cannot create {folder}: {exc}") from exc
        selected = [case.name for case in project.cases] if cases is None else list(cases)
        job_id = new_job_id(project_dir)
        configs = prepare_job(project_dir, project, job_id, selected, continue_cases, changes, starts)
        lines = _control_lines(configs / RUN_CONTROL_FILE)
        names = [name for name, _option, _ref in lines]
        archived = archive_before_rerun(project_dir, names)  # before this job is the newest to name them
        job = JobRecord(id=job_id, backend=self.backend, cases=names, log_path=f"{JOBS_DIR}/{job_id}.log",
                        case_status={name: CaseState.PENDING for name in names},
                        backend_ref={"partition": options.partition, "ntasks": options.ntasks,
                                     "time_limit": options.time_limit, "exclusive": options.exclusive,
                                     "account": options.account},
                        changes={name: dict(c) for name, c in (changes or {}).items() if name in names and c},
                        attempts=archived)
        save_job(project_dir, job)  # active (QUEUED): the lock below counts as held from here on
        try:
            write_lock(project_dir, job_id, -1, 0.0, backend=self.backend)
        except JobError:
            shutil.rmtree(project_dir / JOBS_DIR / job_id, ignore_errors=True)
            (project_dir / JOBS_DIR / f"{job_id}.json").unlink(missing_ok=True)
            raise
        self._log(project_dir, job, f"Job {job_id}: {len(names)} case(s) to Slurm partition {options.partition}, "
                                    f"{options.ntasks} tasks each" +
                  (f", time limit {options.time_limit}" if options.time_limit else ""))
        for name, changed in job.changes.items():
            self._log(project_dir, job, f"{name} runs with {describe(changed)} (this job only)")
        previous: Optional[str] = None
        for name, option, ref in lines:
            depends_on, solution = self._restart_source(project_dir, configs, previous, option, ref)
            try:
                self._prepare_case(project_dir, configs, name, solution)
                self._sbatch(project_dir, project, job, name, options, settings.slurm, depends_on,
                             note=f"restarts from {depends_on}" if depends_on else "")
            except JobError as exc:
                self._abandon(project_dir, job, name, str(exc))
                raise
            previous = name
        job.state = JobState.RUNNING
        save_job(project_dir, job)
        return job

    def _prepare_case(self, project_dir: Path, configs: Path, name: str, solution: Optional[str],
                      restart: bool = False, keep_logs: bool = False) -> None:
        """Empty runs/<case>/ and write the job's config into it (SOLUTION_FILENAME when it restarts; `restart` also
        sets RESTART_SOL= YES, for a case that waits for one still running). `keep_logs` keeps the Slurm output of
        its earlier attempts in this job (a resubmit)."""
        folder = project_dir / RUNS_DIR / name
        try:
            if folder.exists() and keep_logs:
                for path in folder.iterdir():
                    if not (path.name.startswith("slurm-") and path.suffix == ".out"):
                        shutil.rmtree(path) if path.is_dir() else path.unlink()
            elif folder.exists():
                shutil.rmtree(folder)
            folder.mkdir(parents=True, exist_ok=True)
            text = (configs / f"{name}.cfg").read_text(encoding="utf-8")
            if solution is not None:
                text = apply_parameters(text, {"SOLUTION_FILENAME": solution, **({"RESTART_SOL": "YES"} if restart
                                                                                   else {})})
            (folder / f"{name}.cfg").write_text(text, encoding="utf-8", newline="\n")
        except OSError as exc:
            raise JobError(f"Cannot prepare {folder}: {exc}") from exc

    def _sbatch(self, project_dir: Path, project: Project, job: JobRecord, name: str, options: SlurmOptions,
                slurm: SlurmSettings, depends_on: Optional[str], note: str = "",
                attempts: Sequence[str] = ()) -> None:
        folder = project_dir / RUNS_DIR / name
        after = job.slurm[depends_on].job_id if depends_on else None
        restart_from = None
        if depends_on:
            source = project_dir / RUNS_DIR / depends_on
            own = _SOLUTION_RE.search(_read(folder / f"{name}.cfg"))
            solution = own.group(1) if own else str(source / _restart_name(_read(source / f"{depends_on}.cfg")))
            restart_from = (depends_on, str(source), solution)
        script = job_script(project.name, name, f"{name}.cfg", options, slurm, job.id, after, note, restart_from)
        try:
            (folder / JOB_SCRIPT).write_text(script, encoding="utf-8", newline="\n")
            (folder / JOB_SCRIPT).chmod(0o755)
        except OSError as exc:
            raise JobError(f"Cannot write {folder / JOB_SCRIPT}: {exc}") from exc
        try:
            out = sl.run_sync(sl.sbatch_args(JOB_SCRIPT), cwd=str(folder), env=sweep_environment())
            slurm_id = sl.parse_sbatch(out)
        except sl.SlurmUnavailable as exc:
            raise JobError(f"Cannot submit {name}: {exc}") from exc
        job.slurm[name] = SlurmCase(job_id=slurm_id, attempts=list(attempts), partition=options.partition,
                                    ntasks=options.ntasks, time_limit=options.time_limit, depends_on=depends_on,
                                    scratch_fallback=bool(after), reason="Dependency" if after else "",
                                    submitted=time.time())
        job.case_status[name] = CaseState.PENDING
        job.failure_tail.pop(name, None)
        self._log(project_dir, job, f"{name} -> Slurm job {slurm_id} on {options.partition}, {options.ntasks} tasks"
                  + (f", after {after} ({depends_on})" if after else ""))
        save_job(project_dir, job)

    def _prepare_again(self, project_dir: Path, job: JobRecord, name: str, waits: bool) -> None:
        """A resubmitted case's folder as at its submit: its run so far put aside, the config of the batch that last
        submitted it written afresh (an earlier attempt's script may have switched it to start from scratch).
        `waits`: it waits for a case resubmitted with it, whose solution the script checks; else a solution that is
        not there any more makes it start from scratch now."""
        job_dir = project_dir / JOBS_DIR / job.id
        configs = next((batch / CONFIGS_DIR for batch in reversed(_batches(job_dir))
                        if (batch / CONFIGS_DIR / f"{name}.cfg").is_file()), None)
        if configs is None:  # a job from before its configs were kept: its folder runs as it is
            return
        folder = project_dir / RUNS_DIR / name
        own = _SOLUTION_RE.search(_read(folder / f"{name}.cfg"))
        restart = job.slurm[name].depends_on is not None
        keep_aside(project_dir, job.attempts, [name])
        self._prepare_case(project_dir, configs, name, own.group(1) if own else None, restart=restart,
                           keep_logs=True)
        cfg = folder / f"{name}.cfg"
        text = _read(cfg)
        if not waits and own and re.search(r"^\s*RESTART_SOL\s*=\s*YES", text, re.MULTILINE | re.IGNORECASE):
            solution = own.group(1)
            if not any(Path(solution + suffix).is_file() for suffix in ("", ".dat", ".csv")):
                cfg.write_text(apply_parameters(text, {"RESTART_SOL": "NO"}), encoding="utf-8", newline="\n")
                self._log(project_dir, job, f"{name} starts from scratch: its solution {solution} is not there")

    # -- adding cases to a running job ------------------------------------------------------------------------

    def busy_cases(self, job: JobRecord) -> set[str]:
        """The cases queued or running in `job`: they cannot be added again."""
        return {name for name in job.cases if name in job.slurm
                and job.case_status.get(name) in (CaseState.PENDING, CaseState.RUNNING)}

    @_serialized
    def add_cases(self, project_dir: Path, project: Project, job: JobRecord, cases: Sequence[str],
                  continue_cases: Iterable[str] = (), options: Optional[SlurmOptions] = None,
                  changes: Optional[Mapping[str, Mapping[str, str]]] = None,
                  starts: Optional[Mapping[str, Optional[str]]] = None) -> JobRecord:
        """Submit more cases inside the running job `job` (e.g. to the other partition while it runs).

        Cases already queued or running in it are skipped; one that finished, failed or was cancelled in it runs
        again (its earlier Slurm id kept in `attempts`). An added case that restarts from a case still queued or
        running in the job waits for it (afterany, starting from scratch if it fails), as within one submit. A failed sbatch cancels only this batch.
        """
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        if job.backend != self.backend or not job.is_active:
            raise JobError(f"Job {job.id} is not running: submit the cases instead")
        busy = self.busy_cases(job)
        order = [case.name for case in project.cases]
        wanted = [name for name in order if name in set(cases) and name not in busy]
        if not wanted:
            raise JobError(f"Every chosen case is already queued or running in job {job.id}")
        settings = self._settings()
        options = options or slurm_options(project, settings)
        number = 2
        while (project_dir / JOBS_DIR / job.id / f"add-{number}").exists():
            number += 1
        configs = prepare_job(project_dir, project, f"{job.id}/add-{number}", wanted, continue_cases, changes,
                              starts)
        keep_aside(project_dir, job.attempts, wanted)  # each is emptied below, as at a submit
        for name in wanted:  # this attempt's changes replace an earlier attempt's
            job.changes.pop(name, None)
            if (changes or {}).get(name):
                job.changes[name] = dict(changes[name])
                self._log(project_dir, job, f"{name} runs with {describe(changes[name])} (this job only)")
        lines = _control_lines(configs / RUN_CONTROL_FILE)
        by_name = {case.name: case for case in project.cases}
        continued = set(continue_cases)
        waits = {}  # added case -> the case still running in this job whose solution it restarts from
        for name, option, _ref in lines:
            if option in ("none", "custom") and name not in continued:
                target = _referenced_case(project_dir, by_name[name], order)
                if target in busy:
                    waits[name] = target
        self._log(project_dir, job, f"Adding {len(lines)} case(s) to Slurm partition {options.partition}, "
                                    f"{options.ntasks} tasks each")
        submitted: list[str] = []
        previous: Optional[str] = None
        for name, option, ref in lines:
            depends_on, solution = self._restart_source(project_dir, configs, previous, option, ref)
            if name in waits:
                depends_on = waits[name]
                target_cfg = _read(project_dir / RUNS_DIR / depends_on / f"{depends_on}.cfg")
                solution = str(project_dir / RUNS_DIR / depends_on / _restart_name(target_cfg))
            old = job.slurm.get(name)
            attempts = [*old.attempts, old.job_id] if old is not None else []
            if name not in job.cases:
                job.cases.append(name)
            try:
                self._prepare_case(project_dir, configs, name, solution, restart=name in waits)
                self._sbatch(project_dir, project, job, name, options, settings.slurm, depends_on,
                             note=f"restarts from {depends_on}" if depends_on else "", attempts=attempts)
            except JobError as exc:
                self._abandon_batch(project_dir, job, [line[0] for line in lines], submitted, name, str(exc))
                raise
            submitted.append(job.slurm[name].job_id)
            previous = name
        job.state = JobState.RUNNING
        save_job(project_dir, job)
        return job

    def _restart_source(self, project_dir: Path, configs: Path, previous: Optional[str], option: str,
                        ref: Optional[str]) -> tuple[Optional[str], Optional[str]]:
        """(the case of this batch to wait for, the solution file) for one run_control.txt line."""
        depends_on = None
        solution = None
        if option == "previous" and previous is not None:
            depends_on = previous
        elif option == "from_case" and ref:
            depends_on = ref[:-4] if ref.endswith(".cfg") else ref
        elif option == "custom" and ref:
            solution = ref
        if depends_on is not None:
            target_cfg = _read(configs / f"{depends_on}.cfg")
            solution = str(project_dir / RUNS_DIR / depends_on / _restart_name(target_cfg))
        return depends_on, solution

    def _abandon_batch(self, project_dir: Path, job: JobRecord, batch: list[str], submitted: list[str],
                       failed_case: str, message: str) -> None:
        """Adding cases failed part-way: cancel this batch's jobs only; the rest of the job runs on."""
        if submitted:
            try:
                sl.run_sync(sl.scancel_args(submitted))
            except sl.SlurmUnavailable as exc:
                self._log(project_dir, job, f"Could not cancel {', '.join(submitted)}: {exc}")
        for name in batch:
            if name in job.slurm and job.slurm[name].job_id in submitted:
                job.slurm[name].state = "CANCELLED"
                job.failure_tail[name] = f"Cancelled: {failed_case} could not be submitted.\n{message}"
            else:
                job.failure_tail[name] = f"Not submitted.\n{message}"
            job.case_status[name] = CaseState.FAILED
        self._log(project_dir, job, f"Adding cases failed: {message}")
        if all(job.case_status.get(name) in FINAL_CASE_STATES for name in job.cases):
            self._end(project_dir, job, self._final_state(job))
        else:
            save_job(project_dir, job)

    def _abandon(self, project_dir: Path, job: JobRecord, failed_case: str, message: str) -> None:
        """A submit failed part-way: cancel what was submitted, fail the job, release the lock."""
        submitted = [job.slurm[name].job_id for name in job.cases if name in job.slurm
                     and job.case_status.get(name) not in FINAL_CASE_STATES]
        if submitted:
            try:
                sl.run_sync(sl.scancel_args(submitted))
            except sl.SlurmUnavailable as exc:
                self._log(project_dir, job, f"Could not cancel {', '.join(submitted)}: {exc}")
        for name in job.cases:
            if job.case_status.get(name) in FINAL_CASE_STATES:
                continue
            job.case_status[name] = CaseState.FAILED
            if name in job.slurm and job.slurm[name].job_id in submitted:
                job.slurm[name].state = "CANCELLED"
                job.failure_tail[name] = f"Cancelled: {failed_case} could not be submitted.\n{message}"
            else:
                job.failure_tail[name] = f"Not submitted.\n{message}"
        self._log(project_dir, job, f"Submit failed: {message}")
        self._end(project_dir, job, JobState.FAILED)

    # -- refresh ----------------------------------------------------------------------------------------------

    def watched_ids(self, job: JobRecord) -> list[str]:
        """The Slurm job ids of the cases not final yet."""
        return [sc.job_id for name, sc in job.slurm.items() if job.case_status.get(name) not in FINAL_CASE_STATES]

    @_serialized
    def refresh(self, project_dir: Path, job: JobRecord) -> JobRecord:
        """Query Slurm (one squeue, at most one sacct, seff for cases that just finished) and apply it."""
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        if not job.is_active:
            return job
        job = self.apply_snapshot(project_dir, job, sl.snapshot_sync(self.watched_ids(job)))
        for name in self.pending_stats(job):
            try:
                stats = sl.parse_seff(sl.run_sync(sl.seff_args(job.slurm[name].job_id)))
            except sl.SlurmUnavailable:
                stats = None
            job = self.add_seff(project_dir, job, name, stats)
        return job

    def _reload(self, project_dir: Path, job: JobRecord) -> JobRecord:
        try:  # the caller's copy may be stale (cancelled or finished elsewhere)
            return load_job(project_dir, job.id)
        except JobError:
            return job

    @_serialized
    def apply_snapshot(self, project_dir: Path, job: JobRecord, snap: sl.Snapshot) -> JobRecord:
        """Bring `job` up to date with one poll; saves it when anything changed. Never queries Slurm, except to
        cancel a job whose dependency can never be met."""
        project_dir = Path(project_dir).resolve()
        if not job.is_active or snap.taken <= float(job.backend_ref.get("snapshot", 0.0)):
            return job
        job = self._reload(project_dir, job)
        if not job.is_active or snap.taken <= float(job.backend_ref.get("snapshot", 0.0)):
            return job
        job.backend_ref["snapshot"] = snap.taken
        if not snap.ok:
            if job.backend_ref.get("outage") is None:
                job.backend_ref["outage"] = snap.error
                job.backend_ref["outage_since"] = datetime.now().isoformat(timespec="seconds")
                self._log(project_dir, job, f"Slurm unreachable; states kept as they were: {snap.error}")
            save_job(project_dir, job)
            return job
        if job.backend_ref.get("outage") is not None:
            job.backend_ref.pop("outage", None)
            job.backend_ref.pop("outage_since", None)
            self._log(project_dir, job, "Slurm reachable again")
        for name in job.cases:
            if job.case_status.get(name) in FINAL_CASE_STATES or name not in job.slurm:
                continue
            sc = job.slurm[name]
            if snap.taken < sc.submitted:  # this poll was made before the job existed
                continue
            row = snap.queue.get(sc.job_id)
            if row is not None:
                self._queued(project_dir, job, name, sc, row)
                continue
            acct = snap.accounting.get(sc.job_id)
            if acct is not None and acct.state in sl.FINAL_STATES:
                self._final(project_dir, job, name, sc, acct.state, acct.exit_code, acct.elapsed, acct.node)
            elif acct is not None:
                continue  # left squeue a moment ago, accounting not final yet
            else:
                self._no_accounting(project_dir, job, name, sc, snap.accounting_error)
        if all(job.case_status.get(name) in FINAL_CASE_STATES for name in job.cases):
            self._end(project_dir, job, self._final_state(job))
        else:
            save_job(project_dir, job)
        return job

    def _queued(self, project_dir: Path, job: JobRecord, name: str, sc: SlurmCase, row: sl.QueueRow) -> None:
        sc.state, sc.elapsed = row.state, row.time
        if row.state in sl.RUNNING_STATES:
            sc.node, sc.reason, sc.started = row.node, "", True
            if job.case_status[name] is not CaseState.RUNNING:
                target = self._dependency_failed(job, name) if sc.scratch_fallback else None
                self._log(project_dir, job, f"{name} ({sc.job_id}) running on {row.node}" + (
                    f", from scratch: {target} ended {job.case_status[target].value}" if target else ""))
            job.case_status[name] = CaseState.RUNNING
            return
        sc.reason = row.reason
        job.case_status[name] = CaseState.PENDING
        if row.reason == sl.NEVER_SATISFIED:  # --kill-on-invalid-dep did not take: cancel it ourselves
            try:
                sl.run_sync(sl.scancel_args([sc.job_id]))
            except sl.SlurmUnavailable as exc:
                self._log(project_dir, job, f"Could not cancel {sc.job_id} ({name}): {exc}")
                return
            sc.state = "CANCELLED"
            self._block(project_dir, job, name)

    def _dependency_failed(self, job: JobRecord, name: str) -> Optional[str]:
        """The case `name` waits for, when that one ended without a solution."""
        target = job.slurm[name].depends_on
        if target and job.case_status.get(target) in FINAL_CASE_STATES - OK_STATES:
            return target
        return None

    def _block(self, project_dir: Path, job: JobRecord, name: str) -> None:
        target = job.slurm[name].depends_on or "?"
        how = job.slurm[target].state if target in job.slurm else job.case_status.get(target, "?")
        if job.case_status.get(target) is CaseState.BLOCKED:
            how = "BLOCKED"
        job.case_status[name] = CaseState.BLOCKED
        job.failure_tail[name] = f"Not run: {target} ended {getattr(how, 'value', how)}, so its solution, which " \
                                 f"{name} restarts from, does not exist."
        self._log(project_dir, job, f"{name} blocked: {target} ended {getattr(how, 'value', how)}")

    def _final(self, project_dir: Path, job: JobRecord, name: str, sc: SlurmCase, state: str, exit_code: str,
               elapsed: str, node: str) -> None:
        sc.state, sc.exit_code, sc.reason = state, exit_code, ""
        sc.elapsed = elapsed or sc.elapsed
        sc.node = node or sc.node
        ran = sc.started or (sl.parse_duration(sc.elapsed or "") or 0) > 0
        if state == "CANCELLED":
            target = None if sc.scratch_fallback else sc.depends_on  # afterany: Slurm never cancels it for that
            if target and not sc.started and job.case_status.get(target) not in FINAL_CASE_STATES:
                sc.state = "PENDING"  # wait for the case it depends on: Blocked or Cancelled follows from it
                return
            if target and self._dependency_failed(job, name) and not sc.started:
                self._block(project_dir, job, name)
            else:
                job.case_status[name] = CaseState.CANCELLED
                self._log(project_dir, job, f"{name} ({sc.job_id}) cancelled")
            return
        sc.started = sc.started or ran
        folder = project_dir / RUNS_DIR / name
        out = folder / f"slurm-{sc.job_id}.out"
        if state == "COMPLETED":
            self._judge(project_dir, job, name, folder, out)
        else:
            on = f" on {sc.node}" if sc.node else ""
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = f"Slurm: {state} (exit {exit_code}){on}.\n" + _tail(_read(out))
        why = ""
        if job.case_status[name] is CaseState.FAILED and name in job.failure_tail:
            why = f": {diagnose(job.failure_tail[name], state, sc.time_limit).summary}"
        self._log(project_dir, job, f"{name} ({sc.job_id}) ended {state} (exit {exit_code}): "
                                    f"{job.case_status[name].value}{why}")
        self._write_stats(project_dir, job, name, None)
        sc.stats_pending = True

    def _judge(self, project_dir: Path, job: JobRecord, name: str, folder: Path, out: Path) -> None:
        """A case that ran to the end: CONVERGED / UNCONVERGED from its history, FAILED without one."""
        history = folder / HISTORY_FILE
        df = read_history(history) if history.is_file() else None
        if df is None or df.empty:
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = "No history.csv was written.\n" + _tail(_read(out))
            return
        converged, _message = check_convergence(df)
        job.case_status[name] = CaseState.CONVERGED if converged else CaseState.UNCONVERGED

    def _no_accounting(self, project_dir: Path, job: JobRecord, name: str, sc: SlurmCase,
                       error: Optional[str]) -> None:
        """Out of the queue with no accounting row: wait for one, then let the case's files decide."""
        folder = project_dir / RUNS_DIR / name
        out = folder / f"slurm-{sc.job_id}.out"
        text = _read(out)
        exits = _EXIT_RE.findall(text)
        if error is not None and (exits or "Exit Success" in text):  # accounting is down: the file is enough
            code = int(exits[-1]) if exits else 0
            self._from_files(project_dir, job, name, sc, folder, out, code, error)
            return
        sc.checks += 1
        if sc.checks < FALLBACK_POLLS:
            return
        if exits or "Exit Success" in text:
            self._from_files(project_dir, job, name, sc, folder, out, int(exits[-1]) if exits else 0, error)
        elif not sc.scratch_fallback and self._dependency_failed(job, name) and not text:
            self._block(project_dir, job, name)
        else:
            sc.state = "UNKNOWN"
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = ("Ended without a result; Slurm accounting has no record of it, so the reason "
                                      "(out of memory, node failure, time limit) is unknown.\n" + _tail(text))
            self._log(project_dir, job, f"{name} ({sc.job_id}) ended, reason unknown (no accounting)")

    def _from_files(self, project_dir: Path, job: JobRecord, name: str, sc: SlurmCase, folder: Path, out: Path,
                    code: int, error: Optional[str]) -> None:
        sc.started = True
        sc.exit_code = f"{code}:0"
        note = f"Slurm accounting unreachable ({error}); judged from {out.name}." if error else \
            f"No Slurm accounting record; judged from {out.name}."
        if code == 0:
            sc.state = "COMPLETED"
            self._judge(project_dir, job, name, folder, out)
        else:
            sc.state = "FAILED"
            job.case_status[name] = CaseState.FAILED
            job.failure_tail[name] = f"SU2 exited with code {code}. {note}\n" + _tail(_read(out))
        why = ""
        if job.case_status[name] is CaseState.FAILED:
            why = f": {diagnose(job.failure_tail[name], sc.state, sc.time_limit).summary}"
        self._log(project_dir, job, f"{name} ({sc.job_id}): {job.case_status[name].value}{why}. {note}")

    def _end(self, project_dir: Path, job: JobRecord, state: JobState) -> None:
        job.state = state
        job.finished = datetime.now()
        save_job(project_dir, job)
        clear_lock(project_dir, job.id)
        settle_attempts(project_dir, job.attempts, {name for name, sc in job.slurm.items() if sc.started})
        prune_restarts(project_dir / JOBS_DIR / job.id, unfinished(job))
        drop_kept(project_dir, [name for name in job.case_status if name not in unfinished(job)], but=job.id)
        self._log(project_dir, job, f"Job {job.id} ended: {state.value}")

    # -- stats ------------------------------------------------------------------------------------------------

    def pending_stats(self, job: JobRecord) -> list[str]:
        """Finished cases still waiting for their seff figures."""
        return [name for name, sc in job.slurm.items() if sc.stats_pending]

    @_serialized
    def add_seff(self, project_dir: Path, job: JobRecord, name: str, stats: Optional[sl.SeffStats]) -> JobRecord:
        """Record seff's figures for a finished case (None: seff failed; retried a few times)."""
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        sc = job.slurm.get(name)
        if sc is None or not sc.stats_pending:
            return job
        sc.seff_tries += 1
        if stats is not None or sc.seff_tries >= SEFF_TRIES:
            sc.stats_pending = False
            self._write_stats(project_dir, job, name, stats)
        save_job(project_dir, job)
        return job

    def _write_stats(self, project_dir: Path, job: JobRecord, name: str, stats: Optional[sl.SeffStats]) -> None:
        sc = job.slurm[name]
        folder = project_dir / RUNS_DIR / name
        elapsed = sl.parse_duration(sc.elapsed) if sc.elapsed else None
        iterations = _iterations(folder / HISTORY_FILE)
        su2 = _su2_seconds_per_iter(folder / HISTORY_FILE)
        wall = (stats.wall_s if stats and stats.wall_s else None) or elapsed
        cpu = None
        if stats is not None and stats.cpu_utilized_s is not None and wall and sc.ntasks:
            cpu = stats.cpu_utilized_s / (wall * sc.ntasks)
        data = {
            "job_id": sc.job_id, "partition": sc.partition, "node": sc.node, "ntasks": sc.ntasks,
            "state": sc.state, "exit_code": sc.exit_code, "elapsed_s": elapsed, "iterations": iterations,
            "s_per_iter": su2 if su2 is not None else (elapsed / iterations if elapsed and iterations else None),
            "s_per_iter_source": "su2" if su2 is not None else "elapsed",
            "peak_memory_gb": stats.memory_gb if stats else None, "cpu_use_per_rank": cpu,
            "attempts": list(sc.attempts),
        }
        path = folder / STATS_FILE
        try:
            tmp = path.with_name(path.name + ".tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        except OSError as exc:
            self._log(project_dir, job, f"Cannot write {path}: {exc}")

    # -- cancel and resubmit ----------------------------------------------------------------------------------

    @_serialized
    def cancel(self, project_dir: Path, job: JobRecord) -> JobRecord:
        """scancel every case not finished yet (one call); they become CANCELLED and so does the job."""
        if not job.is_active:
            return job
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        if not job.is_active:
            return job
        ids = self.watched_ids(job)
        if ids:
            try:
                sl.run_sync(sl.scancel_args(ids))
            except sl.SlurmUnavailable as exc:
                raise JobError(f"Cannot cancel Slurm jobs {', '.join(ids)}: {exc}") from exc
        for name in job.cases:
            if job.case_status.get(name) in FINAL_CASE_STATES:
                continue
            job.case_status[name] = CaseState.CANCELLED
            if name in job.slurm:
                job.slurm[name].state = "CANCELLED"
        self._log(project_dir, job, f"Cancelled: scancel {' '.join(ids)}" if ids else "Cancelled")
        self._end(project_dir, job, JobState.CANCELLED)
        return job

    def _final_state(self, job: JobRecord) -> JobState:
        """How a job whose cases all ended ends: DONE when every case ran to the end, FAILED when one failed, else
        CANCELLED (cases cancelled, or blocked by a cancelled one)."""
        states = [job.case_status[name] for name in job.cases]
        if all(state in OK_STATES for state in states):
            return JobState.DONE
        return JobState.FAILED if CaseState.FAILED in states else JobState.CANCELLED

    @_serialized
    def cancel_case(self, project_dir: Path, job: JobRecord, case: str) -> JobRecord:
        """scancel one case; the job's other cases go on. Nothing happens when the case has already ended."""
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        sc = job.slurm.get(case)
        if sc is None:
            raise JobError(f"{case} is not a Slurm case of job {job.id}")
        if not job.is_active or job.case_status.get(case) in FINAL_CASE_STATES:
            return job
        # The record can lag Slurm by a poll: a job that already left the queue ended on its own, so take its real
        # outcome instead of scancelling a finished job and calling it cancelled.
        snap = sl.snapshot_sync(self.watched_ids(job))
        if not snap.ok:
            raise JobError(f"Cannot cancel {case} (Slurm job {sc.job_id}): {snap.error}")
        if sc.job_id not in snap.queue:
            return self.apply_snapshot(project_dir, job, snap)
        try:
            sl.run_sync(sl.scancel_args([sc.job_id]))
        except sl.SlurmUnavailable as exc:
            raise JobError(f"Cannot cancel {case} (Slurm job {sc.job_id}): {exc}") from exc
        job.case_status[case] = CaseState.CANCELLED
        sc.state = "CANCELLED"
        job.failure_tail[case] = "Cancelled from the Cluster page."
        self._log(project_dir, job, f"{case} ({sc.job_id}) cancelled: scancel {sc.job_id}")
        if all(job.case_status.get(name) in FINAL_CASE_STATES for name in job.cases):
            self._end(project_dir, job, self._final_state(job))
        else:
            save_job(project_dir, job)
        return job

    def resubmittable(self, job: JobRecord) -> list[str]:
        """Failed cases whose Slurm state says the case itself was fine: NODE_FAIL and OUT_OF_MEMORY."""
        return [name for name in job.cases if job.case_status.get(name) is CaseState.FAILED
                and name in job.slurm and job.slurm[name].state in sl.RESUBMITTABLE]

    @_serialized
    def resubmit(self, project_dir: Path, project: Project, job: JobRecord, cases: Optional[Sequence[str]] = None,
                 options: Optional[SlurmOptions] = None) -> JobRecord:
        """Submit `cases` (default: every NODE_FAIL / OUT_OF_MEMORY case) again inside the same job, with the cases
        blocked behind them; each earlier Slurm id is kept in `attempts`."""
        project_dir = Path(project_dir).resolve()
        job = self._reload(project_dir, job)
        allowed = self.resubmittable(job)
        wanted = list(allowed) if cases is None else list(cases)
        refused = [name for name in wanted if name not in allowed]
        if refused:
            raise JobError("Only cases that ended NODE_FAIL or OUT_OF_MEMORY can be resubmitted: " + ", ".join(refused))
        if not wanted:
            raise JobError("No case of this job ended NODE_FAIL or OUT_OF_MEMORY")
        lock = active_lock(project_dir)
        if lock is not None and lock.get("job_id") != job.id:
            raise JobError(f"Job {lock.get('job_id')} is running for this project")
        settings = self._settings()
        chosen = set(wanted)
        for name in job.cases:  # with the cases blocked behind them, in job order
            target = job.slurm[name].depends_on if name in job.slurm else None
            if job.case_status.get(name) is CaseState.BLOCKED and target in chosen:
                chosen.add(name)
        order = [name for name in job.cases if name in chosen]
        if options is None:
            first = job.slurm[order[0]]
            options = slurm_options(project, settings, partition=first.partition, ntasks=first.ntasks,
                                    time_limit=first.time_limit)
        if not job.is_active:
            write_lock(project_dir, job.id, -1, 0.0, backend=self.backend)
            job.state, job.finished = JobState.RUNNING, None
        self._log(project_dir, job, f"Resubmit {', '.join(order)} to {options.partition}, {options.ntasks} tasks")
        for name in order:
            old = job.slurm[name]
            depends_on = old.depends_on if old.depends_on in chosen else None
            job.case_status[name] = CaseState.PENDING
            try:
                self._prepare_again(project_dir, job, name, waits=depends_on is not None)
                self._sbatch(project_dir, project, job, name, options, settings.slurm, depends_on,
                             note=f"resubmit of {old.job_id}", attempts=[*old.attempts, old.job_id])
            except JobError as exc:
                job.case_status[name] = CaseState.FAILED
                job.slurm[name] = old
                for later in order[order.index(name) + 1:]:
                    job.case_status[later] = CaseState.FAILED if later in allowed else CaseState.BLOCKED
                self._log(project_dir, job, f"Resubmit failed: {exc}")
                if not any(job.case_status.get(n) not in FINAL_CASE_STATES for n in job.cases):
                    self._end(project_dir, job, JobState.FAILED)
                else:
                    save_job(project_dir, job)
                raise
        job.state = JobState.RUNNING
        save_job(project_dir, job)
        return job

    # -- logs -------------------------------------------------------------------------------------------------

    def started_cases(self, project_dir: Path, job: JobRecord) -> list[str]:
        return [name for name in job.cases if name in job.slurm and job.slurm[name].started]

    def case_log(self, project_dir: Path, job: JobRecord, case: str) -> Optional[Path]:
        sc = job.slurm.get(case)
        return None if sc is None else Path(project_dir) / RUNS_DIR / case / f"slurm-{sc.job_id}.out"

    def _log(self, project_dir: Path, job: JobRecord, text: str) -> None:
        try:
            with open(Path(project_dir) / job.log_path, "a", encoding="utf-8") as fh:
                fh.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {text}\n")
        except OSError:
            pass  # the record still holds the states
