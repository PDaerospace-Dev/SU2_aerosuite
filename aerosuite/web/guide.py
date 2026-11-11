"""The help menu's content: AeroSuite's version and the web UI guide, docs/WEB_UI.md (read from disk, so it
works offline), cut into its "###" sections for the guide's table of contents, grouped under its "##" headings, and
searched. NiceGUI-free."""
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

GUIDE = Path(__file__).resolve().parents[2] / "docs" / "WEB_UI.md"
MISSING = "The web UI guide is in docs/WEB_UI.md, which is not installed with this copy of AeroSuite."
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


def web_ui_guide(guide: Path = GUIDE) -> str:
    """The guide file without its "# " title line, or MISSING when it cannot be read."""
    try:
        lines = Path(guide).read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return MISSING
    if lines and lines[0].startswith("# "):
        lines = lines[1:]
    return "\n".join(lines).strip() or MISSING


def _outline(guide: Path) -> tuple[list[tuple[str, str]], list[tuple[str, int]]]:
    """The "###" sections as (title, markdown), text before the first one leading it, and the "##" groups as (name,
    index of their first section). Without "###" headings (or without the file) it is one section, "Web UI guide"."""
    text = web_ui_guide(guide)
    sections: list[tuple[str, list[str]]] = []
    groups: list[tuple[str, int]] = []
    lead: list[str] = []
    fence = False
    for line in text.splitlines():
        if line.startswith("```"):
            fence = not fence  # a "### " inside a code block is not a heading
        if line.startswith("### ") and not fence:
            sections.append((line[4:].strip(), []))
        elif line.startswith("## ") and not fence:
            groups.append((line[3:].strip(), len(sections)))
        elif sections:
            sections[-1][1].append(line)
        else:
            lead.append(line)
    if not sections:
        return [("Web UI guide", text)], []
    title, body = sections[0]
    sections[0] = (title, lead + body)
    return [(title, "\n".join(body).strip()) for title, body in sections], groups


def guide_sections(guide: Path = GUIDE) -> list[tuple[str, str]]:
    """The guide as (title, markdown) per "###" section; text before the first one leads the first."""
    return _outline(guide)[0]


def guide_groups(guide: Path = GUIDE) -> list[tuple[str, int]]:
    """The guide's "##" groups: (name, the index of the section it starts at)."""
    return _outline(guide)[1]


def search_sections(sections: list[tuple[str, str]], query: str) -> list[int]:
    """The sections whose title or text hold every word of `query` (any case); all of them for an empty query."""
    words = query.lower().split()
    return [index for index, (title, body) in enumerate(sections)
            if all(word in f"{title}\n{body}".lower() for word in words)]


def section_for(page: str, titles: list[str]) -> int:
    """The index of the section `page` opens the guide on: its own, else the first."""
    wanted = SECTION_OF_PAGE.get(page)
    if wanted:
        for index, title in enumerate(titles):
            if title.startswith(wanted):
                return index
    return 0
