"""Write parameters into the project's template.cfg from a form (Aircraft's Mach, ISA's Apply)."""
from typing import Mapping, Optional

from ..engine.cfg import apply_parameters, read_template
from ..engine.errors import AeroSuiteError
from ..engine.project import TEMPLATE_FILE, set_template_text
from .layout import ProjectFrame


def write_template_params(frame: ProjectFrame, params: Mapping[str, Optional[str]]) -> Optional[str]:
    """Set `params` in template.cfg; returns an error message, or None when written.

    Like the Config page, template.cfg is written directly rather than through project.json;
    only a project still pointing at another template file gets its template field updated.
    """
    project = frame.session.project
    # Decided before writing: set_template_text points the in-memory project at template.cfg.
    needs_field_update = project.template != TEMPLATE_FILE
    try:
        text = read_template(frame.session.directory, project)
        set_template_text(frame.session.directory, project, apply_parameters(text, params))
    except AeroSuiteError as exc:
        return str(exc)
    if needs_field_update:
        return frame.save(lambda p: setattr(p, "template", TEMPLATE_FILE))
    frame.refresh()
    return None
