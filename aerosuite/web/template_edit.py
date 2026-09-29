"""Write parameters into the project's template file from a form (Aircraft's Mach, ISA's Apply)."""
from typing import Mapping, Optional

from ..engine.cfg import apply_parameters, read_template
from ..engine.errors import AeroSuiteError
from ..engine.project import set_template_text, template_file_name
from .layout import ProjectFrame


def write_template_params(frame: ProjectFrame, params: Mapping[str, Optional[str]]) -> Optional[str]:
    """Set `params` in the template file; returns an error message, or None when written.

    Like the CFG setup page, the template is written directly rather than through project.json;
    only a project whose template field is not a plain file name gets that field updated.
    """
    project = frame.session.project
    # Decided before writing: set_template_text points the in-memory project at the file it wrote.
    name = template_file_name(project)
    needs_field_update = project.template != name
    try:
        text = read_template(frame.session.directory, project)
        set_template_text(frame.session.directory, project, apply_parameters(text, params))
    except AeroSuiteError as exc:
        return str(exc)
    if needs_field_update:
        return frame.save(lambda p: setattr(p, "template", name))
    frame.refresh()
    return None
