"""Checks before cases are submitted to Slurm: shared storage, configs and mesh, the partition, tasks and memory.

The memory estimate reads NELEM from the .su2 header only (a 15M-cell mesh is gigabytes), times the configured
GB per million cells, and compares it with the partition's limit for an --exclusive job.
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .cfg import CONFIGS_DIR
from .models import Project
from .preflight import Problem
from .settings import AppSettings, valid_time_limit

HEADER_LINES = 64
LINE_LIMIT = 4096  # a header line is short; never read a binary mesh's "line" of gigabytes
_NELEM_RE = re.compile(r"^\s*NELEM\s*=\s*(\d+)")
_MESH_RE = re.compile(r"^\s*MESH_FILENAME\s*=\s*(\S+)", re.MULTILINE)


def mesh_elements(path: Path) -> Optional[int]:
    """NELEM from a .su2 mesh's first lines; None for other formats, an unreadable file or no NELEM there."""
    path = Path(path)
    if path.suffix.lower() != ".su2":
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for _ in range(HEADER_LINES):
                line = fh.readline(LINE_LIMIT)
                if not line:
                    break
                match = _NELEM_RE.match(line)
                if match:
                    return int(match.group(1))
    except OSError:
        return None
    return None


def memory_estimate_gb(elements: int, gb_per_million_cells: float) -> float:
    return elements / 1e6 * gb_per_million_cells


def _under(path: Path, root: Path) -> bool:
    try:
        Path(path).resolve().relative_to(Path(root).resolve())
    except ValueError:
        return False
    return True


def config_mesh(cfg_text: str) -> Optional[str]:
    match = _MESH_RE.search(cfg_text)
    return match.group(1) if match else None


@dataclass(frozen=True)
class MemoryCheck:
    mesh: str
    elements: Optional[int]
    estimate_gb: Optional[float]
    limit_gb: float
    partition: str

    @property
    def note(self) -> str:
        if self.estimate_gb is None:
            return f"No memory estimate for {Path(self.mesh).name} (only .su2 headers are read)"
        return (f"≈ {self.estimate_gb:.0f} GB of {self.limit_gb:.0f} GB on {self.partition} "
                f"({self.elements / 1e6:.1f}M cells)")

    @property
    def over(self) -> bool:
        return self.estimate_gb is not None and self.estimate_gb > self.limit_gb


def memory_check(mesh: str, partition: str, settings: AppSettings) -> Optional[MemoryCheck]:
    """The estimate for `mesh` against `partition`'s limit; None for an unknown partition."""
    part = settings.slurm.partition(partition)
    if part is None:
        return None
    elements = mesh_elements(Path(mesh))
    estimate = None if elements is None else memory_estimate_gb(elements, settings.slurm.gb_per_million_cells)
    return MemoryCheck(mesh, elements, estimate, part.memory_limit_mb / 1024, part.name)


def slurm_problems(project_dir: Path, project: Project, cases: Optional[Sequence[str]], partition: Optional[str],
                   ntasks: Optional[int], time_limit: Optional[str], settings: AppSettings,
                   read_configs: bool = True) -> list[Problem]:
    """Every reason not to submit (errors) and every thing worth knowing first (warnings).

    With read_configs each case's generated config must exist and its MESH_FILENAME is checked; without (the web
    generates the configs at Submit) a missing config stands for the project's mesh.
    """
    slurm = settings.slurm
    problems: list[Problem] = []
    if shutil.which("sbatch") is None:
        problems.append(Problem("error", "Slurm's sbatch was not found on PATH; is this the cluster's controller?"))
    root = Path(slurm.shared_root)
    project_dir = Path(project_dir)
    if not _under(project_dir, root):
        problems.append(Problem("error", f"Case folders must be under {root} so every node can see them "
                                         f"(this study is in {project_dir.resolve()})"))
    part = slurm.partition(partition)
    if part is None:
        names = ", ".join(p.name for p in slurm.partitions)
        problems.append(Problem("error", f"Unknown partition {partition!r}; the settings have {names}"))
    tasks = ntasks if ntasks is not None else (part.default_ntasks if part else None)
    if tasks is not None and tasks < 1:
        problems.append(Problem("error", f"Tasks must be at least 1 ({tasks} asked)"))
    limit = time_limit if time_limit is not None else slurm.default_time_limit
    if not valid_time_limit(limit):
        problems.append(Problem("error", f"Time limit {limit!r} is not in a Slurm format such as 12:00:00 "
                                         "or 2-00:00:00"))
    if part is not None and tasks is not None and part.ntasks_warn_above and tasks > part.ntasks_warn_above:
        problems.append(Problem("warning", f"{part.name} gains nothing above about {part.ntasks_warn_above} "
                                           f"tasks; {tasks} asked"))

    names = [case.name for case in project.cases] if cases is None else list(cases)
    meshes, missing, unreadable = _case_meshes(project_dir, project, names, read_configs)
    if missing:
        problems.append(Problem("error", "Configs are missing for " + ", ".join(missing) + "; generate configs first"))
    problems += unreadable
    for mesh, users in meshes.items():
        which = users[0] if len(users) == 1 else f"{len(users)} cases"
        reported = mesh == project.mesh.path  # the general checks already report the project's mesh
        if not mesh:
            if not reported:
                problems.append(Problem("error", f"MESH_FILENAME is not set in the config of {which}"))
        elif not Path(mesh).is_absolute():
            if not reported:
                problems.append(Problem("error", f"MESH_FILENAME must be an absolute path for a Slurm job: {mesh}"))
        elif not Path(mesh).is_file():
            if not reported:
                problems.append(Problem("error", f"Mesh not found: {mesh}"))
        else:
            if not _under(Path(mesh), root):
                problems.append(Problem("warning", f"Other nodes cannot see {mesh}: it is not under {root}"))
            check = memory_check(mesh, part.name, settings) if part is not None else None
            if check is not None and check.over:
                severity = "error" if part.block_over_memory else "warning"
                problems.append(Problem(severity, f"{Path(mesh).name} needs about {check.estimate_gb:.0f} GB, "
                                                  f"over {part.name}'s {check.limit_gb:.0f} GB limit: the job "
                                                  "would be killed (OUT_OF_MEMORY)"))
    for case in project.cases:
        if case.name in names and case.restart == "custom" and case.restart_ref and not _under(
                Path(case.restart_ref), root):
            problems.append(Problem("warning", f"{case.name}: other nodes cannot see its restart "
                                               f"{case.restart_ref}: it is not under {root}"))
    return problems


def _case_meshes(project_dir: Path, project: Project, names: Sequence[str], read_configs: bool
                 ) -> tuple[dict[str, list[str]], list[str], list[Problem]]:
    """{mesh: the cases using it}, the cases whose config is missing, and configs that cannot be read."""
    configs = Path(project_dir) / CONFIGS_DIR
    meshes: dict[str, list[str]] = {}
    missing: list[str] = []
    problems: list[Problem] = []
    for name in names:
        path = configs / f"{name}.cfg"
        if not path.is_file():
            if read_configs:
                missing.append(name)
            else:
                meshes.setdefault(project.mesh.path, []).append(name)
            continue
        try:
            mesh = config_mesh(path.read_text(encoding="utf-8", errors="replace"))
        except OSError as exc:
            problems.append(Problem("error", f"Cannot read configs/{name}.cfg: {exc}"))
            continue
        meshes.setdefault(mesh or "", []).append(name)
    return meshes, missing, problems


def memory_notes(project_dir: Path, project: Project, cases: Optional[Sequence[str]], partition: Optional[str],
                 settings: AppSettings) -> list[str]:
    """The Checks panel's memory line for each mesh the cases use."""
    part = settings.slurm.partition(partition)
    if part is None:
        return []
    names = [case.name for case in project.cases] if cases is None else list(cases)
    meshes, _missing, _problems = _case_meshes(project_dir, project, names, read_configs=False)
    return [memory_check(mesh, part.name, settings).note for mesh in meshes if mesh and Path(mesh).is_file()]
