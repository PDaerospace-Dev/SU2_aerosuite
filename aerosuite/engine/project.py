"""Project folders: create, open, save, schema migration, template and mesh selection."""
from __future__ import annotations

import json
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from . import models
from .cfg import extract_markers
from .errors import ProjectError, TemplateError
from .models import Mesh, Project

PROJECT_FILE = "project.json"
TEMPLATE_FILE = "template.cfg"

# {from_version: function(data) -> data at from_version + 1}
MIGRATIONS: dict[int, Callable[[dict], dict]] = {}


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


def migrate(data: dict) -> dict:
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
        data = step(data)
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


def parse_project(text: str, source: str = PROJECT_FILE) -> Project:
    """Validate project.json text (migrating old schemas) into a Project."""
    try:
        data = json.loads(text.lstrip("﻿"))  # some editors write a UTF-8 BOM
    except json.JSONDecodeError as exc:
        raise ProjectError(f"{source} is not valid JSON: {exc}") from exc
    try:
        return Project.model_validate(migrate(data))
    except ValidationError as exc:
        raise ProjectError(f"{source} is not a valid project:\n{exc}") from exc


def open_project(directory: Path) -> Project:
    path = Path(directory) / PROJECT_FILE
    return parse_project(read_project_text(directory), str(path))


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
