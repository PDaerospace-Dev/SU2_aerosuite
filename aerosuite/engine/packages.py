"""Packages for the Results page: parameters, derived and characteristic values, and plots that belong together.

The bundled *aero* package ships in resources/packages/; the user's own live in ~/.aerosuite/packages/<id>.json
(AEROSUITE_HOME overrides the folder, as for profiles). A user package with a bundled id replaces it until deleted.
A study's settings list the packages it uses; their definitions are combined with the study's own when the page is
read (`effective`), so switching a package off removes exactly what it brought.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional

from pydantic import BaseModel, Field, ValidationError

from .errors import ProjectError
from .formula import FormulaError, parse
from .models import DerivedValue, PlotSpec, ResultsSettings
from .results import GROUP_CONVERGENCE, GROUP_RESIDUALS, GROUP_SOLVER, group_of
from .study_results import CONSTANT_NAMES, SWEEP_NAMES

AERO = "aero"
BUNDLED_PACKAGES = Path(__file__).resolve().parents[1] / "resources" / "packages"
DEFAULT_PARAMETER_COUNT = 6  # a study without a package starts with its first flow parameters
_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


class Package(BaseModel):
    id: str
    name: str
    description: str = ""
    parameters: list[str] = Field(default_factory=list)
    derived: list[DerivedValue] = Field(default_factory=list)
    characteristics: list[DerivedValue] = Field(default_factory=list)
    plots: list[PlotSpec] = Field(default_factory=list)


def user_packages_dir() -> Path:
    home = os.environ.get("AEROSUITE_HOME")
    return (Path(home) if home else Path.home() / ".aerosuite") / "packages"


def check_package(package: Package) -> None:
    """Everything a package holds must be usable (raises ProjectError)."""
    if not _ID_RE.fullmatch(package.id or ""):
        raise ProjectError("Package ids use letters, digits, '-' and '_' only")
    if not package.name.strip():
        raise ProjectError("Give the package a name")
    names = [d.name for d in package.derived + package.characteristics]
    twice = sorted({n for n in names if names.count(n) > 1})
    if twice:
        raise ProjectError(f"{twice[0]} is defined twice")
    for definition, curve in [(d, False) for d in package.derived] + [(c, True) for c in package.characteristics]:
        try:
            parse(definition.formula, curve=curve)
        except FormulaError as exc:
            raise ProjectError(f"{definition.name}: {exc}") from None


def _read(path: Path) -> Package:
    try:
        package = Package.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError, ValueError) as exc:
        raise ProjectError(f"Invalid package {path.stem}: {exc}") from exc
    if package.id != path.stem:
        raise ProjectError(f"Invalid package {path.stem}: its id {package.id!r} does not match its file name")
    check_package(package)
    return package


def list_packages() -> list[Package]:
    """Bundled and user packages (a user package replaces a bundled one with the same id); aero first."""
    found: dict[str, Package] = {}
    for base in (BUNDLED_PACKAGES, user_packages_dir()):
        for path in sorted(base.glob("*.json")) if base.is_dir() else []:
            try:
                found[path.stem] = _read(path)
            except ProjectError:
                continue
    return sorted(found.values(), key=lambda p: (p.id != AERO, p.name.lower()))


def load_package(package_id: str) -> Package:
    if not _ID_RE.fullmatch(package_id or ""):
        raise ProjectError(f"Invalid package id {package_id!r}")
    for base in (user_packages_dir(), BUNDLED_PACKAGES):
        path = base / f"{package_id}.json"
        if path.is_file():
            return _read(path)
    raise ProjectError(f"Unknown package {package_id!r}")


def save_package(package: Package) -> Package:
    check_package(package)
    folder = user_packages_dir()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / f"{package.id}.json.tmp"
        tmp.write_text(package.model_dump_json(indent=2), encoding="utf-8")
        os.replace(tmp, folder / f"{package.id}.json")
    except OSError as exc:
        raise ProjectError(f"Cannot save package {package.id}: {exc}") from exc
    return load_package(package.id)


def delete_package(package_id: str) -> None:
    """Delete the user's package; for a bundled id this deletes the user's copy (a reset)."""
    if not _ID_RE.fullmatch(package_id or ""):
        raise ProjectError(f"Invalid package id {package_id!r}")
    path = user_packages_dir() / f"{package_id}.json"
    if not path.is_file():
        if (BUNDLED_PACKAGES / f"{package_id}.json").is_file():
            raise ProjectError(f"{package_id} is bundled with AeroSuite and cannot be deleted")
        raise ProjectError(f"Unknown package {package_id!r}")
    try:
        path.unlink()
    except OSError as exc:
        raise ProjectError(f"Cannot delete package {package_id}: {exc}") from exc


def _formula_names(definition: DerivedValue, curve: bool) -> set[str]:
    try:
        return set(parse(definition.formula, curve=curve).names)
    except FormulaError:
        return set()


def history_needs(package: Package) -> set[str]:
    """The history columns a package reads (not its own derived names, sweep variables or study constants)."""
    own = {d.name for d in package.derived}
    names = set(package.parameters)
    for d in package.derived:
        names |= _formula_names(d, curve=False)
    for c in package.characteristics:
        names |= _formula_names(c, curve=True)
    for plot in package.plots:
        names |= {plot.x, *plot.y}
    return names - own - set(SWEEP_NAMES) - set(CONSTANT_NAMES)


def availability(package: Package, columns: Iterable[str]) -> list[str]:
    """The history columns a package needs that the study lacks (sorted); empty when it can be used."""
    return sorted(history_needs(package) - set(columns))


@dataclass
class Definitions:
    """What the Results page shows for a study: its packages' definitions and its own, combined."""
    packages: list[str]
    parameters: list[str]
    derived: list[DerivedValue] = field(default_factory=list)
    characteristics: list[DerivedValue] = field(default_factory=list)
    plots: list[PlotSpec] = field(default_factory=list)  # packages' plots first, then the study's own

    @property
    def derived_names(self) -> set[str]:
        return {d.name for d in self.derived}


def _loaded(ids: Iterable[str]) -> list[Package]:
    packages = []
    for package_id in ids:
        try:
            packages.append(load_package(package_id))
        except ProjectError:
            continue  # deleted since: its definitions are simply gone
    return packages


def _merge(first: Iterable[DerivedValue], then: Iterable[DerivedValue]) -> list[DerivedValue]:
    merged: dict[str, DerivedValue] = {}
    for definition in list(first) + list(then):
        merged.setdefault(definition.name, definition)
    return list(merged.values())


def effective(settings: ResultsSettings, columns: Iterable[str]) -> Definitions:
    columns = list(columns)
    if settings.packages is None:  # not chosen yet: aero when the history supports it
        aero = _loaded([AERO])
        ids = [AERO] if aero and not availability(aero[0], columns) else []
    else:
        ids = list(settings.packages)
    packages = _loaded(ids)
    derived = _merge((d for p in packages for d in p.derived), settings.derived)
    characteristics = _merge((c for p in packages for c in p.characteristics), settings.characteristics)
    plots = [plot for p in packages for plot in p.plots] + list(settings.plots)
    parameters = list(settings.parameters) or list(dict.fromkeys(n for p in packages for n in p.parameters))
    if not parameters:
        solver_groups = (GROUP_CONVERGENCE, GROUP_SOLVER, GROUP_RESIDUALS)
        parameters = [c for c in columns if group_of(c) not in solver_groups][:DEFAULT_PARAMETER_COUNT]
    return Definitions([p.id for p in packages], parameters, derived, characteristics, plots)


def enable_package(settings: ResultsSettings, package: Package) -> None:
    """Use `package` in this study: it is listed, and its parameters are added to the chosen ones."""
    settings.packages = list(settings.packages or [])
    if package.id not in settings.packages:
        settings.packages.append(package.id)
    settings.parameters += [p for p in package.parameters if p not in settings.parameters]


def disable_package(settings: ResultsSettings, package: Package, others: Optional[Iterable[Package]] = None) -> None:
    """Stop using `package`: its parameters go unless another package in use lists them."""
    settings.packages = [p for p in (settings.packages or []) if p != package.id]
    kept = {n for p in (others if others is not None else _loaded(settings.packages)) for n in p.parameters}
    settings.parameters = [p for p in settings.parameters if p not in package.parameters or p in kept]
