"""Create a study the way the web start screen describes it: a general case or an aircraft study."""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from .cfg import build_cases
from .errors import ProjectError, TemplateError
from .models import Project
from .profiles import apply_profile, load_profile
from .project import create_project, save_project, set_mesh, set_template
from .reference import BUNDLED_REFERENCE


def create_study(
    directory: Path,
    *,
    profile_id: Optional[str] = None,
    sweep: Optional[bool] = None,
    template: Optional[Path] = None,
    use_reference_template: bool = False,
    mesh: Optional[Path] = None,
) -> Project:
    """New project folder. With a profile: aircraft study (sweep on by default); without: general case.

    Every input is checked before anything is created, so a failure leaves no half-made project.
    The template is, in order: `template`, SU2's reference (`use_reference_template`), the profile's.
    """
    profile = load_profile(profile_id) if profile_id else None
    if template is not None and not Path(template).is_file():
        raise TemplateError(f"Template not found: {template}")
    if mesh is not None and not Path(mesh).is_file():
        raise ProjectError(f"Mesh not found: {mesh}")
    source = template or (BUNDLED_REFERENCE if use_reference_template else None) or (
        profile.template if profile else None)
    if source is None:
        suffix = f" (profile {profile.name} has none)" if profile else ""
        raise TemplateError(f"Choose a template{suffix}")
    project = create_project(directory)
    if profile is not None:
        apply_profile(directory, project, profile)
    set_template(directory, project, source)
    if mesh is not None:
        set_mesh(project, mesh)
    project.sweep.enabled = (profile is not None) if sweep is None else sweep
    if not project.sweep.enabled:
        # With the sweep on, an empty Mach list would build_cases into a fake Mach-0 case
        # instead of the empty, todo state a new study should start in.
        project.cases = build_cases(project)
    save_project(directory, project)
    return project
