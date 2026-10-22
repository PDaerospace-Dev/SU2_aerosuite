"""Checking each case's config with SU2 itself before it runs: `SU2_CFD -d` (dry run) parses the config and runs
SU2's own checks on a dummy geometry, without loading the mesh (about 2 s and 20 MB on hpc1), so a config SU2
would reject is caught before a job is queued, with SU2's own message.

Each case's config is checked as it will run (cfg.render_case), in a temporary folder, up to PARALLEL at once;
results are cached by the config text, so an unchanged config is not checked again. The SU2_CFD is the Settings'
(slurm.su2_bin), or AEROSUITE_SU2_CFD. AEROSUITE_SU2_CHECK=off turns the check off (the tests do).
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional, Sequence

from .cfg import case_layers, read_template, render_case
from .errors import AeroSuiteError
from .models import Case, Project

if TYPE_CHECKING:
    from .preflight import Problem
    from .settings import AppSettings

PARALLEL = 8
TIMEOUT = 60  # seconds; a dry run takes about 2
_KEY_RE = re.compile(r"\b([A-Z][A-Z0-9]*_[A-Z0-9_]+)\b")
_LINE_KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=")
# SU2 messages that name no option, and the option they are about
_ABOUT = {"CFL adaption": "CFL_ADAPT_PARAM", "CFL adaptation": "CFL_ADAPT_PARAM"}


@dataclass(frozen=True)
class DryRun:
    ok: bool
    message: str = ""  # SU2's error, one line; "" when ok
    skipped: str = ""  # why SU2 could not check it (timeout, could not start); then ok is True


_CACHE: dict[str, DryRun] = {}


def enabled(settings: "AppSettings") -> bool:
    return settings.check_with_su2 and os.environ.get("AEROSUITE_SU2_CHECK", "on").lower() != "off"


def executable(settings: "AppSettings") -> Optional[Path]:
    override = os.environ.get("AEROSUITE_SU2_CFD")
    if override:
        return Path(override) if Path(override).is_file() else None
    candidate = Path(settings.slurm.su2_bin) / "SU2_CFD"
    if candidate.is_file():
        return candidate
    found = shutil.which("SU2_CFD")
    return Path(found) if found else None


def su2_message(output: str) -> str:
    """SU2's error, one line: the text between `Error in "...":` and `Error Exit`, without the rules."""
    lines = output.splitlines()
    start = next((i for i, line in enumerate(lines) if line.startswith("Error in ")), None)
    if start is None:
        tail = [line.strip() for line in lines if line.strip() and not line.startswith("-")]
        return tail[-1] if tail else "SU2 stopped without a message"
    message = []
    for line in lines[start + 1:]:
        if "Error Exit" in line:
            break
        if line.strip() and not set(line.strip()) <= {"-"}:
            message.append(line.strip())
    return " ".join(message) or "SU2 stopped without a message"


def dry_run(text: str, su2: Path) -> DryRun:
    """SU2's verdict on one config (cached by the config and the SU2_CFD)."""
    key = hashlib.sha256(f"{su2}\0{text}".encode()).hexdigest()
    if key in _CACHE:
        return _CACHE[key]
    with tempfile.TemporaryDirectory(prefix="aerosuite-su2-check-") as folder:
        (Path(folder) / "case.cfg").write_text(text, encoding="utf-8")
        try:
            done = subprocess.run([str(su2), "-d", "case.cfg"], cwd=folder, capture_output=True, text=True,
                                  timeout=TIMEOUT, stdin=subprocess.DEVNULL)
        except subprocess.TimeoutExpired:
            return DryRun(True, skipped=f"SU2's check took over {TIMEOUT} s")
        except OSError as exc:
            return DryRun(True, skipped=f"SU2_CFD could not start ({exc})")
    result = DryRun(True) if done.returncode == 0 else DryRun(False, su2_message(done.stdout + "\n" + done.stderr))
    _CACHE[key] = result
    return result


def where(template: str, project: Project, case: Case, message: str) -> str:
    """Where to change what SU2 complains about: the template line, or the form, placeholder or sweep."""
    from .config_edit import FORM_FIELDS, owner  # config_edit imports cfg, as this module does

    key = next((k for phrase, k in _ABOUT.items() if phrase in message), None)
    keys_here = {match.group(1) for match in map(_LINE_KEY_RE.match, render_case(template, project, case)
                                                  .splitlines()) if match}
    if key is None:
        key = next((k for k in _KEY_RE.findall(message) if k in keys_here), None)
    if key is None:
        return ""
    if key in case_layers(template, project, case):
        kind = owner(project, case, template, key)
        where = {"case": "set per case", "altitude": "from the altitude", "placeholder": "Placeholders",
                 "marker": "Placeholders"}.get(kind, f"the form ({FORM_FIELDS[key][3]})" if key in FORM_FIELDS
                                                   else "the form")
        return f" ({key}, {where})"
    for number, line in enumerate(template.splitlines(), 1):
        match = _LINE_KEY_RE.match(line)
        if match and match.group(1) == key:
            return f" ({key}, template line {number})"
    return f" ({key})"


def check_cases(project_dir: Path, project: Project, cases: Optional[Sequence[str]],
                settings: "AppSettings", run: bool) -> list["Problem"]:
    """SU2's verdict on each chosen case's config: errors (cases with the same message together). With `run`
    False, only what is cached (a page drawing its checks must not wait for SU2)."""
    from .preflight import Problem

    if not enabled(settings) or not project.cases:
        return []
    su2 = executable(settings)
    if su2 is None:
        return [Problem("warning", f"SU2_CFD was not found in {settings.slurm.su2_bin}: the configs were not "
                                   "checked with SU2")] if run else []
    try:
        template = read_template(project_dir, project)
    except AeroSuiteError:
        return []  # preflight reports the template
    chosen = [case for case in project.cases if cases is None or case.name in set(cases)]
    texts = {}
    for case in chosen:
        try:
            texts[case.name] = render_case(template, project, case)
        except AeroSuiteError:
            continue  # e.g. an altitude out of range: preflight reports it
    if run:
        with ThreadPoolExecutor(max_workers=PARALLEL) as pool:
            results = dict(zip(texts, pool.map(lambda text: dry_run(text, su2), texts.values())))
    else:
        results = {}
        for name, text in texts.items():
            cached = _CACHE.get(hashlib.sha256(f"{su2}\0{text}".encode()).hexdigest())
            if cached is not None:
                results[name] = cached
    by_message: dict[str, list[str]] = {}
    skipped = sorted({result.skipped for result in results.values() if result.skipped})
    for name, result in results.items():
        if not result.ok:
            by_message.setdefault(result.message, []).append(name)
    problems = []
    for message, names in by_message.items():
        case = next(c for c in chosen if c.name == names[0])
        who = names[0] if len(names) == 1 else f"{names[0]} and {len(names) - 1} more case" + (
            "s" if len(names) > 2 else "")
        problems.append(Problem("error", f"{who}: SU2 rejects the config: {message}"
                                         f"{where(template, project, case, message)}"))
    problems += [Problem("warning", f"Not checked with SU2: {reason}") for reason in skipped]
    return problems


def clear_cache() -> None:
    _CACHE.clear()
