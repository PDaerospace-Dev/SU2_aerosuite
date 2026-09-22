"""One open project: apply edits with validation and autosave; notice changes made elsewhere."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Optional

from pydantic import ValidationError

from ..engine import project as engine_project
from ..engine.errors import AeroSuiteError, ProjectError
from ..engine.models import Project

Change = Callable[[Project], object]


def _stamp(directory: Path) -> Optional[tuple[int, int]]:
    try:
        stat = (directory / engine_project.PROJECT_FILE).stat()
    except OSError:
        return None
    return stat.st_mtime_ns, stat.st_size


def _validation_message(exc: ValidationError) -> str:
    first = exc.errors()[0]
    where = ".".join(str(part) for part in first["loc"])
    return f"{where}: {first['msg']}" if where else str(first["msg"])


class ProjectSession:
    """The project behind one page. Edits are all-or-nothing: copy, change, validate, save, keep."""

    def __init__(self, directory: Path) -> None:
        self.directory = Path(directory).resolve()
        self.project: Project = engine_project.open_project(self.directory)
        self._seen = _stamp(self.directory)

    def apply(self, change: Change) -> Optional[str]:
        """Run `change` on a copy of the project; save it if valid. Returns None, or the error message."""
        candidate = self.project.model_copy(deep=True)
        try:
            change(candidate)
            candidate = Project.model_validate(candidate.model_dump())
            engine_project.save_project(self.directory, candidate)
        except AeroSuiteError as exc:
            return str(exc)
        except ValidationError as exc:
            return _validation_message(exc)
        self.project = candidate
        self._seen = _stamp(self.directory)
        return None

    def changed_on_disk(self) -> bool:
        return _stamp(self.directory) != self._seen

    def reload(self) -> None:
        """Re-read project.json. The change is acknowledged first, so a broken file is reported only once."""
        self._seen = _stamp(self.directory)
        self.project = engine_project.open_project(self.directory)


def parse_optional_number(text: Optional[str], what: str) -> Optional[float]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        raise ProjectError(f"{what}: {text!r} is not a number") from None


def parse_optional_int(text: Optional[str], what: str) -> Optional[int]:
    text = (text or "").strip()
    if not text:
        return None
    try:
        return int(text)
    except ValueError:
        raise ProjectError(f"{what}: {text!r} is not a whole number") from None


def parse_int(text: Optional[str], what: str) -> int:
    value = parse_optional_int(text, what)
    if value is None:
        raise ProjectError(f"{what} is required")
    return value
