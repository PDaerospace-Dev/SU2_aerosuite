"""Project folders: create, open, save, schema migration, template and mesh selection."""
from __future__ import annotations

import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from . import models
from .cfg import extract_markers, read_template
from .errors import ProjectError, TemplateError
from .models import Mesh, Project
from .restarts import RUNS_DIR

PROJECT_FILE = "project.json"
TEMPLATE_FILE = "template.cfg"


def _v1_to_v2(data: dict, directory: Optional[Path]) -> dict:
    """Schema 2 adds aircraft profiles and a sweep on/off switch; old projects keep their sweep."""
    data.setdefault("profile", None)
    sweep = data.setdefault("sweep", {})
    if isinstance(sweep, dict):
        sweep.setdefault("enabled", True)
    return data


def _v2_to_v3(data: dict, directory: Optional[Path]) -> dict:
    """Schema 3 keeps three restart options: none, previous and custom (a restart file or case folder).

    `initial` becomes `custom` with the old run.initial_restart; `from_case X` becomes `previous`
    when X is the case just before it, else `custom` pointing at this project's runs/X/.
    """
    run = data.get("run")
    initial = run.pop("initial_restart", None) if isinstance(run, dict) else None
    cases = data.get("cases")
    if not isinstance(cases, list):
        return data
    names = [case.get("name") if isinstance(case, dict) else None for case in cases]
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            continue
        option = case.get("restart")
        if option == "initial":
            case["restart"], case["restart_ref"] = "custom", initial
        elif option == "from_case":
            ref = case.get("restart_ref")
            if index > 0 and ref is not None and ref == names[index - 1]:
                case["restart"], case["restart_ref"] = "previous", None
            elif not ref:
                case["restart"], case["restart_ref"] = "custom", None
            else:
                # Without the folder (e.g. text being edited elsewhere) the path stays relative,
                # which preflight reports so the user can fix it.
                folder = Path(directory).resolve() / RUNS_DIR / ref if directory is not None else Path(RUNS_DIR) / ref
                case["restart"], case["restart_ref"] = "custom", str(folder)
    return data


def _v3_to_v4(data: dict, directory: Optional[Path]) -> dict:
    """Schema 4 adds freestream from altitude; older projects keep setting it by hand (the default)."""
    return data


# {from_version: function(data, project folder or None) -> data at from_version + 1}
MIGRATIONS: dict[int, Callable[[dict, Optional[Path]], dict]] = {1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4}


def create_project(directory: Path, name: Optional[str] = None) -> Project:
    directory = Path(directory)
    if (directory / PROJECT_FILE).exists():
        raise ProjectError(f"{directory} already contains a project")
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ProjectError(f"Cannot create project folder {directory}: {exc}") from exc
    project = Project(name=name or directory.resolve().name)
    save_project(directory, project)
    return project


def migrate(data: dict, directory: Optional[Path] = None) -> dict:
    if not isinstance(data, dict):
        raise ProjectError("project.json must contain a JSON object")
    try:
        version = int(data.get("schema_version", 1))
    except (TypeError, ValueError) as exc:
        raise ProjectError(
            f"Invalid schema_version {data.get('schema_version')!r} in project file"
        ) from exc
    if version > models.SCHEMA_VERSION:
        raise ProjectError(
            f"This project was saved by a newer AeroSuite (schema {version}); please upgrade AeroSuite"
        )
    while version < models.SCHEMA_VERSION:
        step = MIGRATIONS.get(version)
        if step is None:
            raise ProjectError(
                f"No migration registered from schema {version} to {version + 1}"
            )
        data = step(data, directory)
        version += 1
        data["schema_version"] = version
    return data


def read_project_text(directory: Path) -> str:
    """The raw text of project.json (for editing)."""
    path = Path(directory) / PROJECT_FILE
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ProjectError(f"No project found in {directory}") from None
    except UnicodeDecodeError as exc:
        raise ProjectError(f"{path} is not UTF-8 text: {exc}") from exc
    except OSError as exc:
        raise ProjectError(f"Cannot read {path}: {exc}") from exc


def parse_project(text: str, source: str = PROJECT_FILE, directory: Optional[Path] = None) -> Project:
    """Validate project.json text (migrating old schemas) into a Project."""
    try:
        data = json.loads(text.lstrip("﻿"))  # some editors write a UTF-8 BOM
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{source} is not valid JSON: {exc}") from exc
    try:
        return Project.model_validate(migrate(data, directory))
    except ValidationError as exc:
        raise ProjectError(f"{source} is not a valid project:\n{exc}") from exc


def open_project(directory: Path) -> Project:
    path = Path(directory) / PROJECT_FILE
    return parse_project(read_project_text(directory), str(path), directory=Path(directory))


def save_project(directory: Path, project: Project) -> None:
    """Write project.json atomically (temp file + rename)."""
    project.modified = datetime.now()
    path = Path(directory) / PROJECT_FILE
    tmp = path.with_name(PROJECT_FILE + ".tmp")
    try:
        tmp.write_text(project.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise ProjectError(f"Cannot save {path}: {exc}") from exc


def set_template(directory: Path, project: Project, source: Path) -> None:
    """Copy a master template into the project so later edits to the original don't leak in."""
    source = Path(source)
    if not source.is_file():
        raise TemplateError(f"Template not found: {source}")
    target = Path(directory) / TEMPLATE_FILE
    try:
        shutil.copyfile(source, target)
    except OSError as exc:
        raise TemplateError(f"Cannot copy template {source} to {target}: {exc}") from exc
    project.template = TEMPLATE_FILE


def set_mesh(project: Project, mesh_path: Path) -> None:
    mesh_path = Path(mesh_path).resolve()
    if not mesh_path.is_file():
        raise ProjectError(f"Mesh not found: {mesh_path}")
    markers = extract_markers(mesh_path) if mesh_path.suffix.lower() == ".su2" else []
    project.mesh = Mesh(path=str(mesh_path), markers=markers)


_OPTION_LINE_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=")


def template_warnings(text: str) -> list[str]:
    """Lines that are not options or comments, and options set more than once."""
    warnings: list[str] = []
    seen: dict[str, list[int]] = {}
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("%"):
            continue
        match = _OPTION_LINE_RE.match(line)
        if match is None:
            shown = line if len(line) <= 60 else line[:57] + "..."
            warnings.append(f'Line {number} is not an option or a comment: "{shown}"')
            continue
        seen.setdefault(match.group(1), []).append(number)
    for key, lines in seen.items():
        if len(lines) > 1:
            where = ", ".join(str(n) for n in lines[:-1]) + f" and {lines[-1]}"
            together = "both" if len(lines) == 2 else "all"
            warnings.append(f"{key} is set on lines {where}; {together} will be changed together")
    return warnings


def read_template_text(project_dir: Path, project: Project) -> str:
    return read_template(project_dir, project)


def set_template_text(project_dir: Path, project: Project, text: str) -> list[str]:
    """Save edited template text as the project's template.cfg; returns warnings (never blocks)."""
    path = Path(project_dir) / TEMPLATE_FILE
    tmp = path.with_name(TEMPLATE_FILE + ".tmp")
    try:
        tmp.write_text(text, encoding="utf-8", newline="\n")
        os.replace(tmp, path)
    except OSError as exc:
        raise TemplateError(f"Cannot write {path}: {exc}") from exc
    project.template = TEMPLATE_FILE
    return template_warnings(text)
