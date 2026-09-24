"""Aircraft profiles: reusable default settings (and optionally a master template) for studies."""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from pydantic import BaseModel, Field, ValidationError

from .errors import ProjectError
from .models import Naming, Project, Settings
from .naming import format_value
from .project import TEMPLATE_FILE, set_template

BUNDLED_PROFILES = Path(__file__).resolve().parents[1] / "resources" / "profiles"
PROFILE_FILE = "profile.json"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_GROUPS = ("freestream", "reference", "numerics")


class ProfileData(BaseModel):
    id: str
    name: str
    description: str = ""
    settings: dict = Field(default_factory=dict)
    hints: dict[str, str] = Field(default_factory=dict)
    naming: dict = Field(default_factory=dict)


@dataclass(frozen=True)
class Profile:
    data: ProfileData
    folder: Path
    bundled: bool

    @property
    def id(self) -> str:
        return self.data.id

    @property
    def name(self) -> str:
        return self.data.name

    @property
    def description(self) -> str:
        return self.data.description

    @property
    def hints(self) -> dict[str, str]:
        return self.data.hints

    @property
    def template(self) -> Optional[Path]:
        path = self.folder / TEMPLATE_FILE
        return path if path.is_file() else None

    @property
    def setting_hints(self) -> dict[str, str]:
        """The profile's own settings as grey hint text, keyed "group.field"."""
        hints: dict[str, str] = {}
        for group in _GROUPS:
            for name, value in self.data.settings.get(group, {}).items():
                hints[f"{group}.{name}"] = format_value(value) if isinstance(value, (int, float)) else str(value)
        return hints


def user_profiles_dir() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return (Path(home) if home else Path.home() / ".aerosuite") / "profiles"


def _merged_settings(current: Settings, partial: dict) -> Settings:
    data = current.model_dump()
    for group, values in partial.items():
        if group not in data or not isinstance(values, dict):
            raise ProjectError(f"Unknown settings group {group!r} in profile")
        if group in _GROUPS:
            unknown = set(values) - set(data[group])
            if unknown:
                raise ProjectError(f"Unknown setting {group}.{sorted(unknown)[0]} in profile")
        data[group] = {**data[group], **values}
    try:
        return Settings.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(f"Invalid profile settings: {exc}") from exc


def _merged_naming(current: Naming, partial: dict) -> Naming:
    data = current.model_dump()
    unknown = set(partial) - set(data)
    if unknown:
        raise ProjectError(f"Unknown naming option {sorted(unknown)[0]} in profile")
    data.update(partial)
    try:
        return Naming.model_validate(data)
    except ValidationError as exc:
        raise ProjectError(f"Invalid profile naming: {exc}") from exc


def _read(folder: Path, bundled: bool) -> Profile:
    path = folder / PROFILE_FILE
    try:
        data = ProfileData.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ProjectError(f"Invalid profile {folder.name}: {exc}") from exc
    if data.id != folder.name:
        raise ProjectError(f"Invalid profile {folder.name}: its id {data.id!r} does not match its folder")
    try:
        _merged_settings(Settings(), data.settings)
        _merged_naming(Naming(), data.naming)
    except ProjectError as exc:
        raise ProjectError(f"Invalid profile {folder.name}: {exc}") from exc
    return Profile(data, folder, bundled)


def list_profiles() -> tuple[list[Profile], list[str]]:
    """Bundled and user profiles (a user profile replaces a bundled one with the same id)."""
    found: dict[str, Profile] = {}
    problems: list[str] = []
    for base, bundled in ((BUNDLED_PROFILES, True), (user_profiles_dir(), False)):
        if not base.is_dir():
            continue
        for folder in sorted(p for p in base.iterdir() if p.is_dir()):
            try:
                found[folder.name] = _read(folder, bundled)
            except ProjectError as exc:
                problems.append(str(exc))
    return sorted(found.values(), key=lambda p: p.name.lower()), problems


def load_profile(profile_id: str) -> Profile:
    last_error: Optional[ProjectError] = None
    for base, bundled in ((user_profiles_dir(), False), (BUNDLED_PROFILES, True)):
        folder = base / profile_id
        if (folder / PROFILE_FILE).is_file():
            try:
                return _read(folder, bundled)
            except ProjectError as exc:
                # A broken user copy falls back to the bundled one, consistent with list_profiles
                # (which keeps offering the bundled profile when the user's own fails to load).
                last_error = exc
    if last_error is not None:
        raise last_error
    raise ProjectError(f"Unknown profile {profile_id!r}")


def apply_profile(project_dir: Path, project: Project, profile: Profile, *, copy_template: bool = True) -> None:
    """Use `profile` for this project: its settings, naming and (by default) template overwrite what it defines.

    `copy_template=False` skips copying the profile's template file, so a caller that must not let
    a file write happen before the project is known to save successfully can copy it separately,
    once that save has succeeded.
    """
    project.settings = _merged_settings(project.settings, profile.data.settings)
    project.sweep.naming = _merged_naming(project.sweep.naming, profile.data.naming)
    if copy_template and profile.template is not None:
        set_template(project_dir, project, profile.template)
    project.profile = profile.id


def save_profile(project_dir: Path, project: Project, profile_id: str, name: str,
                 description: str = "", overwrite: bool = False) -> Profile:
    """Save this project's template, settings and naming as a user profile (never mesh or sweep)."""
    if not _ID_RE.match(profile_id or ""):
        raise ProjectError("Profile ids use letters, digits, '-' and '_' only")
    if not name.strip():
        raise ProjectError("Give the profile a name")
    folder = user_profiles_dir() / profile_id
    if folder.exists() and not overwrite:
        raise ProjectError(f"Profile {profile_id} already exists")
    settings = project.settings
    saved_settings: dict = {
        group: {k: v for k, v in getattr(settings, group).model_dump().items() if v is not None}
        for group in _GROUPS
    }
    saved_settings["markers"] = dict(settings.markers)
    saved_settings["overrides"] = dict(settings.overrides)
    hints: dict[str, str] = {}
    if project.profile:
        try:
            hints = dict(load_profile(project.profile).hints)
        except ProjectError:
            hints = {}
    data = ProfileData(
        id=profile_id, name=name.strip(), description=description.strip(),
        settings=saved_settings, hints=hints, naming=project.sweep.naming.model_dump(),
    )
    template = Path(project_dir) / project.template
    try:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / PROFILE_FILE).write_text(data.model_dump_json(indent=2), encoding="utf-8")
        if template.is_file():
            shutil.copyfile(template, folder / TEMPLATE_FILE)
    except OSError as exc:
        raise ProjectError(f"Cannot save profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)
