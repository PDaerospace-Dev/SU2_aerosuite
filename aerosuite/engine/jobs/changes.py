"""What changed in the configs since the cases last ran: the Run page's "N config changes since last run".

A case's config now (the template with the settings, the case's values and the rerun lines for the next job) is
compared with the config its newest job ran with (jobs/<id>/configs/<case>.cfg, which already holds that job's own
lines, JobRecord.changes). Cases that changed in the same way are one change."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Mapping, NamedTuple, Optional, Sequence

from ..cfg import CONFIGS_DIR, apply_parameters, render_case
from ..errors import AeroSuiteError
from ..models import Project
from .runner import JobRecord
from .store import JOBS_DIR

_LINE = re.compile(r"^\s*([A-Za-z_][\w]*)\s*=\s*(.*?)\s*$")
IGNORED = {"RESTART_SOL"}  # set per job from how the case starts, not a setting


class ConfigChange(NamedTuple):
    key: str
    before: Optional[str]  # None: the line was not in the earlier config
    after: Optional[str]  # None: the line is not in the config now
    cases: tuple[str, ...]

    @property
    def text(self) -> str:
        before = "—" if self.before is None else self.before
        after = "—" if self.after is None else self.after
        return f"{self.key}= {before} → {after}"


def parameters(text: str) -> dict[str, str]:
    """The KEY= value lines of a config (the last of a repeated key wins; comments are skipped)."""
    found: dict[str, str] = {}
    for line in text.splitlines():
        if line.lstrip().startswith("%"):
            continue
        match = _LINE.match(line)
        if match:
            found[match.group(1)] = match.group(2)
    return found


def config_changes(project_dir: Path, project: Project, template: str, cases: Sequence[str],
                   jobs: Sequence[JobRecord], pending: Optional[Mapping[str, Mapping[str, str]]] = None
                   ) -> list[ConfigChange]:
    """The differences between each of `cases`' config now and in its newest job in `jobs` (newest first); a case
    that never ran, or whose earlier config is gone, has none. `pending`: rerun lines for the next job, by case."""
    by_name = {case.name: case for case in project.cases}
    grouped: dict[tuple, list[str]] = {}
    for name in cases:
        case = by_name.get(name)
        previous = next((job for job in jobs if name in job.cases), None)
        if case is None or previous is None:
            continue
        old_file = Path(project_dir) / JOBS_DIR / previous.id / CONFIGS_DIR / f"{name}.cfg"
        try:
            old = parameters(old_file.read_text(encoding="utf-8"))
            new = parameters(apply_parameters(render_case(template, project, case), dict((pending or {}).get(name, {}))))
        except (OSError, AeroSuiteError):
            continue
        for key in sorted((set(old) | set(new)) - IGNORED):
            if old.get(key) != new.get(key):
                grouped.setdefault((key, old.get(key), new.get(key)), []).append(name)
    return [ConfigChange(key, before, after, tuple(names)) for (key, before, after), names in grouped.items()]
