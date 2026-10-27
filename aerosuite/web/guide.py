"""The help menu's content: AeroSuite's version and the README's web UI section (read from disk, so it
works offline), cut into its "###" sections for the guide's table of contents. NiceGUI-free."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

README = Path(__file__).resolve().parents[2] / "README.md"
SECTION = "## Web UI"
MISSING = "The web UI guide is in README.md, which is not installed with this copy of AeroSuite."
# The guide section each page opens on (the start of its "###" title); other pages open on the first.
SECTION_OF_PAGE = {"projects": "Projects", "setup": "Setup", "config": "CFG setup", "aircraft": "Aircraft",
                   "sweep": "Sweep", "run": "Run", "monitor": "Monitor", "results": "Results",
                   "profiles": "Profiles", "cluster": "Cluster", "calculators": "Calculators",
                   "settings": "Settings"}


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


def guide_sections(readme: Path = README) -> list[tuple[str, str]]:
    """The guide as (title, markdown) per "###" section; text before the first one leads the first.
    Without "###" headings (or without the README) it is one section, "Web UI guide"."""
    text = web_ui_guide(readme)
    sections: list[tuple[str, list[str]]] = []
    lead: list[str] = []
    fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence  # a "### " inside a code block is not a heading
        if line.startswith("### ") and not fence:
            sections.append((line[4:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        else:
            lead.append(line)
    if not sections:
        return [("Web UI guide", text)]
    title, body = sections[0]
    sections[0] = (title, lead + body)
    return [(title, "\n".join(body).strip()) for title, body in sections]


def section_for(page: str, titles: list[str]) -> int:
    """The index of the section `page` opens the guide on: its own, else the first."""
    wanted = SECTION_OF_PAGE.get(page)
    if wanted:
        for index, title in enumerate(titles):
            if title.startswith(wanted):
                return index
    return 0
