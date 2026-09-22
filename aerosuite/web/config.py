"""Server-wide settings: the folder the file picker starts in."""
from pathlib import Path

_root: Path = Path.home()


def set_root(path: Path) -> None:
    global _root
    _root = Path(path).expanduser().resolve()


def root() -> Path:
    return _root
