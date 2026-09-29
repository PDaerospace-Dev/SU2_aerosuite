"""Aircraft profiles: what a new study of that aircraft starts from.

A profile holds the Aircraft form's settings, naming, hints and, optionally, a master template, a mesh
path (the file stays where it is), the sweep (Mach, alpha, beta, altitudes, altitude label) and run settings.
Bundled profiles ship with AeroSuite; editing one saves the user's own copy under the same id, which
replaces it until deleted.
"""
from __future__ import annotations

import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel, Field, ValidationError

from .cfg import build_cases
from .errors import ProjectError
from .models import Mesh, Naming, Project, RunSettings, Settings, SweepSpec
from .naming import format_value
from .project import PROJECT_FILE, set_mesh, set_template

BUNDLED_PROFILES = Path(__file__).resolve().parents[1] / "resources" / "profiles"
PROFILE_FILE = "profile.json"
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_GROUPS = ("freestream", "reference", "numerics")
SWEEP_KEYS = ("mach", "alpha", "beta", "altitudes_km", "altitude")
RUN_KEYS = ("partitions", "sweep_script", "sweep_python")


class ProfileData(BaseModel):
    id: str
    name: str
    description: str = ""
    settings: dict = Field(default_factory=dict)
    hints: dict[str, str] = Field(default_factory=dict)
    naming: dict = Field(default_factory=dict)
    mesh: str = ""  # a path on this machine; "" = none
    sweep: dict = Field(default_factory=dict)  # any of SWEEP_KEYS
    run: dict = Field(default_factory=dict)  # any of RUN_KEYS


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
        """The profile's template: the .cfg in its folder (it keeps the name it was saved under)."""
        found = sorted(self.folder.glob("*.cfg"))
        return found[0] if found else None

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


def _check_part(what: str, values: dict, allowed: tuple[str, ...], model) -> None:
    unknown = set(values) - set(allowed)
    if unknown:
        raise ProjectError(f"Unknown {what} option {sorted(unknown)[0]} in profile")
    try:
        model.model_validate(values)
    except ValidationError as exc:
        raise ProjectError(f"Invalid profile {what}: {exc}") from exc


def _check(data: ProfileData) -> None:
    """Everything a profile holds must apply cleanly to a project (raises ProjectError)."""
    if not data.name.strip():
        raise ProjectError("Give the profile a name")
    _merged_settings(Settings(), data.settings)
    _merged_naming(Naming(), data.naming)
    _check_part("sweep", data.sweep, SWEEP_KEYS, SweepSpec)
    _check_part("run", data.run, RUN_KEYS, RunSettings)
    if any(m <= 0 for m in data.sweep.get("mach", [])):
        raise ProjectError("Mach numbers must be greater than 0")


def _read(folder: Path, bundled: bool) -> Profile:
    path = folder / PROFILE_FILE
    try:
        data = ProfileData.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ProjectError(f"Invalid profile {folder.name}: {exc}") from exc
    if data.id != folder.name:
        raise ProjectError(f"Invalid profile {folder.name}: its id {data.id!r} does not match its folder")
    try:
        _check(data)
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
    if not _ID_RE.fullmatch(profile_id or ""):
        raise ProjectError(f"Invalid profile id {profile_id!r}")
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
    data = profile.data
    project.settings = _merged_settings(project.settings, data.settings)
    project.sweep.naming = _merged_naming(project.sweep.naming, data.naming)
    for key, value in data.sweep.items():
        setattr(project.sweep, key, value)
    project.run = RunSettings.model_validate({**project.run.model_dump(), **data.run})
    if data.mesh:
        try:
            set_mesh(project, Path(data.mesh))
        except ProjectError:  # moved or deleted since: keep the path, so Setup shows it as missing
            project.mesh = Mesh(path=data.mesh, markers=[])
    if copy_template and profile.template is not None:
        set_template(project_dir, project, profile.template)
    project.profile = profile.id
    # The profile's naming or altitude may rename the cases, or its sweep define them; an empty sweep
    # stays empty (no fake Mach-0 case).
    if project.cases or (project.sweep.enabled and project.sweep.mach):
        project.cases = build_cases(project)


def save_profile(project_dir: Path, project: Project, profile_id: str, name: str,
                 description: str = "", overwrite: bool = False) -> Profile:
    """Save this project's template, settings, naming, mesh path, sweep and run settings as a user profile."""
    if not _ID_RE.fullmatch(profile_id or ""):
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
    sweep = project.sweep
    data = ProfileData(
        id=profile_id, name=name.strip(), description=description.strip(),
        settings=saved_settings, hints=hints, naming=sweep.naming.model_dump(),
        mesh=project.mesh.path,
        sweep={"mach": list(sweep.mach), "alpha": list(sweep.alpha), "beta": list(sweep.beta),
               "altitudes_km": list(sweep.altitudes_km), "altitude": sweep.altitude},
        run=project.run.model_dump(),
    )
    template = Path(project_dir) / project.template
    try:
        folder.mkdir(parents=True, exist_ok=True)
        _write(folder, data)
        if template.is_file():
            _replace_template(folder, template)
    except OSError as exc:
        raise ProjectError(f"Cannot save profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)


# -- the Profiles page: edit, copy, delete --------------------------------------


def _write(folder: Path, data: ProfileData) -> None:
    tmp = folder / (PROFILE_FILE + ".tmp")
    tmp.write_text(data.model_dump_json(indent=2), encoding="utf-8")
    os.replace(tmp, folder / PROFILE_FILE)


def _replace_template(folder: Path, source: Path) -> None:
    """One template per profile, under the name it had."""
    for old in folder.glob("*.cfg"):
        if old.name != source.name:
            old.unlink()
    if not ((folder / source.name).exists() and (folder / source.name).resolve() == source.resolve()):
        shutil.copyfile(source, folder / source.name)


def _own_folder(profile: Profile) -> Path:
    """The user's folder for `profile`, first copying a bundled profile there (so it can be changed)."""
    folder = user_profiles_dir() / profile.id
    if profile.bundled:
        folder.mkdir(parents=True, exist_ok=True)
        for item in profile.folder.iterdir():
            if item.is_file():
                shutil.copyfile(item, folder / item.name)
    return folder


def edit_profile(profile_id: str, change: Callable[[ProfileData], None]) -> Profile:
    """Apply `change` to a copy of the profile's data and save it, if it is still a valid profile.

    Editing a bundled profile saves the user's own copy under the same id (delete_profile resets it).
    """
    profile = load_profile(profile_id)
    data = profile.data.model_copy(deep=True)
    change(data)
    data.id = profile.id
    _check(data)
    try:
        _write(_own_folder(profile), data)
    except OSError as exc:
        raise ProjectError(f"Cannot save profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)


def set_profile_template(profile_id: str, source: Path) -> Profile:
    source = Path(source)
    if not source.is_file():
        raise ProjectError(f"Template not found: {source}")
    if source.name == PROJECT_FILE or source.name == PROFILE_FILE:
        raise ProjectError(f"A template cannot be called {source.name}; rename {source}")
    profile = load_profile(profile_id)
    try:
        _replace_template(_own_folder(profile), source)
    except OSError as exc:
        raise ProjectError(f"Cannot copy {source} into profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)


def set_profile_mesh(profile_id: str, path: Optional[Path]) -> Profile:
    """Point the profile at a mesh file (kept where it is); None removes it."""
    if path is None:
        return edit_profile(profile_id, lambda data: setattr(data, "mesh", ""))
    path = Path(path).resolve()
    if not path.is_file():
        raise ProjectError(f"Mesh not found: {path}")
    return edit_profile(profile_id, lambda data: setattr(data, "mesh", str(path)))


def duplicate_profile(source_id: str, profile_id: str, name: str) -> Profile:
    if not _ID_RE.fullmatch(profile_id or ""):
        raise ProjectError("Profile ids use letters, digits, '-' and '_' only")
    if not name.strip():
        raise ProjectError("Give the profile a name")
    source = load_profile(source_id)
    folder = user_profiles_dir() / profile_id
    if folder.exists() or (BUNDLED_PROFILES / profile_id).exists():
        raise ProjectError(f"Profile {profile_id} already exists")
    data = source.data.model_copy(deep=True, update={"id": profile_id, "name": name.strip()})
    try:
        folder.mkdir(parents=True)
        _write(folder, data)
        if source.template is not None:
            shutil.copyfile(source.template, folder / source.template.name)
    except OSError as exc:
        shutil.rmtree(folder, ignore_errors=True)
        raise ProjectError(f"Cannot create profile {profile_id}: {exc}") from exc
    return load_profile(profile_id)


def delete_profile(profile_id: str) -> None:
    """Delete the user's profile; for a bundled id this deletes the user's copy (a reset)."""
    if not _ID_RE.fullmatch(profile_id or ""):
        raise ProjectError(f"Invalid profile id {profile_id!r}")
    folder = user_profiles_dir() / profile_id
    if not folder.is_dir():
        if (BUNDLED_PROFILES / profile_id).is_dir():
            raise ProjectError(f"{profile_id} is bundled with AeroSuite and cannot be deleted")
        raise ProjectError(f"Unknown profile {profile_id!r}")
    try:
        shutil.rmtree(folder)
    except OSError as exc:
        raise ProjectError(f"Cannot delete profile {profile_id}: {exc}") from exc
