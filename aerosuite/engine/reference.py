"""SU2's reference config (config_template.cfg): options with their descriptions, for lookup."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .errors import ProjectError

BUNDLED_REFERENCE = Path(__file__).resolve().parents[1] / "resources" / "config_template.cfg"

_BANNER_RE = re.compile(r"^%\s*-{3,}\s*(.*?)\s*-{3,}\s*%?\s*$")
_OPTION_RE = re.compile(r"^([A-Z][A-Z0-9_]*)\s*=")
_KEYS_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=", re.MULTILINE)


@dataclass(frozen=True)
class RefOption:
    key: str
    line: str
    description: str
    section: str
    line_no: int

    @property
    def default_value(self) -> str:
        return self.line.split("=", 1)[1].strip()


def parse_reference(text: str) -> list[RefOption]:
    """Options in file order; each gets the comment block above it and the latest section banner."""
    options: list[RefOption] = []
    section = ""
    block: list[str] = []
    for number, raw in enumerate(text.splitlines(), 1):
        stripped = raw.strip()
        if not stripped:
            block = []
            continue
        banner = _BANNER_RE.match(stripped)
        if banner:
            section = banner.group(1).strip()
            block = []
            continue
        if stripped.startswith("%"):
            comment = stripped.strip("%").strip()
            if comment:
                block.append(comment)
            else:
                block = []
            continue
        match = _OPTION_RE.match(stripped)
        if match:
            options.append(RefOption(match.group(1), stripped, " ".join(block), section, number))
        block = []
    return options


def read_reference_text(path: Optional[Path] = None) -> str:
    path = Path(path) if path is not None else BUNDLED_REFERENCE
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise ProjectError(f"Cannot read reference {path}: {exc}") from exc


def load_reference(path: Optional[Path] = None) -> list[RefOption]:
    options = parse_reference(read_reference_text(path))
    if not options:
        raise ProjectError(f"{path or BUNDLED_REFERENCE} contains no SU2 options")
    return options


def search(options: Sequence[RefOption], query: str, limit: int = 50) -> list[RefOption]:
    """Options whose key contains the query first, then those whose description does."""
    q = query.strip().lower()
    if not q:
        return []
    by_key = [o for o in options if q in o.key.lower()]
    by_description = [o for o in options if q not in o.key.lower() and q in o.description.lower()]
    return (by_key + by_description)[:limit]


def keys_in(text: str) -> set[str]:
    """Option keys set (not commented out) in a config text."""
    return set(_KEYS_RE.findall(text))


def find_lines(text: str, query: str) -> list[int]:
    """1-based numbers of the lines containing `query`, ignoring case."""
    q = query.strip().lower()
    if not q:
        return []
    return [number for number, line in enumerate(text.splitlines(), 1) if q in line.lower()]
