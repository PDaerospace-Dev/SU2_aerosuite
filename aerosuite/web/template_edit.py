"""Write parameters into the project's template file from a form (Aircraft's Mach, ISA's Apply)."""
from typing import Mapping, Optional

from ..engine.cfg import apply_parameters, read_template
from ..engine.errors import AeroSuiteError
from ..engine.project import set_template_text, template_file_name
from .layout import ProjectFrame


def write_template_params(frame: ProjectFrame, params: Mapping[str, Optional[str]]) -> Optional[str]:
    """Set `params` in the template file; returns an error message, or None when written.

    Like the CFG setup page, the template is written directly rather than through project.json;
    project.json is saved only when its template field is not a plain file name, or the single case was
    renamed after the template's Mach, AoA or β.
    """
    project = frame.session.project
    try:
        text = read_template(frame.session.directory, project)
    except AeroSuiteError as exc:
        return str(exc)
    return save_template_text(frame, apply_parameters(text, params))[0]


def save_template_text(frame: ProjectFrame, text: str) -> tuple[Optional[str], list[str]]:
    """Write the template file; save project.json too when the template field or the case name changes.
    Returns (error message or None, the template's warnings)."""
    project = frame.session.project
    # Decided before writing: set_template_text points the in-memory project at the file it wrote.
    name = template_file_name(project)
    needs_field_update = project.template != name
    before = list(project.cases)
    try:
        warnings = set_template_text(frame.session.directory, project, text)
    except AeroSuiteError as exc:
        return str(exc), []
    cases = list(project.cases)
    if needs_field_update or cases != before:
        def change(p) -> None:
            p.template = name
            p.cases = cases

        return frame.save(change), warnings
    frame.refresh()
    return None, warnings
