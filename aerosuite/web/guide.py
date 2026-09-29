"""The help menu's content: AeroSuite's version and the README's web UI section (read from disk, so it
works offline). NiceGUI-free."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"
SECTION = "## Web UI"
MISSING = "The web UI guide is in README.md, which is not installed with this copy of AeroSuite."


def app_version() -> str:
    try:
        return version("aerosuite")
    except PackageNotFoundError:
        return "dev"


def web_ui_guide(readme: Path = README) -> str:
    """The README's "## Web UI" section without its heading, or MISSING when it cannot be read."""
    try:
        lines = Path(readme).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return MISSING
    try:
        start = lines.index(SECTION) + 1
    except ValueError:
        return MISSING
    end = next((i for i in range(start, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[start:end]).strip() or MISSING
