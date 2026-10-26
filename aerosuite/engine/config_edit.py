"""Editing a case's whole config (the Aircraft page's Config tab): each changed line goes back where it came from.

A case's config is the template with layers written over it (cfg.case_layers): the form's fields, the markers and
placeholders, the freestream from the altitude and the per-case values. `split_edit` takes the shown text as edited
and splits it: a line a layer owns becomes a change of that layer's value (`apply_changes`), or a note when it is set
per case; every other line goes into the template, where it was.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Optional

from .cfg import apply_parameters, case_layers, case_mach, case_parameters
from .editing import parse_cfl_adapt_param
from .errors import ProjectError
from .freestream import case_altitude, freestream_for
from .models import Case, Project

_KEY_RE = re.compile(r"^\s*([A-Z][A-Z0-9_]*)\s*=\s*(.*?)\s*$")
_OWNED = "\x00owned:"  # stands for a layer-owned line when lining up the shown and the edited text

# SU2 key -> (settings group, field, type, the Aircraft tab it is on); as cfg.settings_parameters writes them
FORM_FIELDS = {
    "FREESTREAM_TEMPERATURE": ("freestream", "temperature_K", float, "Flight & air"),
    "REYNOLDS_NUMBER": ("freestream", "reynolds", float, "Flight & air"),
    "REYNOLDS_LENGTH": ("freestream", "reynolds_length", float, "Flight & air"),
    "REF_ORIGIN_MOMENT_X": ("reference", "origin_x", float, "Reference"),
    "REF_ORIGIN_MOMENT_Y": ("reference", "origin_y", float, "Reference"),
    "REF_ORIGIN_MOMENT_Z": ("reference", "origin_z", float, "Reference"),
    "REF_LENGTH": ("reference", "ref_length", float, "Reference"),
    "REF_AREA": ("reference", "ref_area", float, "Reference"),
    "KIND_TURB_MODEL": ("numerics", "turb_model", str, "Solver"),
    "CFL_NUMBER": ("numerics", "cfl", float, "Solver"),
    "CFL_ADAPT": ("numerics", "cfl_adapt", str, "Solver"),
    "CFL_ADAPT_PARAM": ("numerics", "cfl_adapt_param", parse_cfl_adapt_param, "Solver"),
    "ITER": ("numerics", "iter", int, "Solver"),
    "CONV_NUM_METHOD_FLOW": ("numerics", "conv_method", str, "Solver"),
    "MUSCL_FLOW": ("numerics", "muscl", str, "Solver"),
}
SWEEP_KEYS = {"MACH_NUMBER": "Mach", "AOA": "α", "SIDESLIP_ANGLE": "β"}


@dataclass
class ConfigEdit:
    template: str  # the template with the edit's own lines in place
    changes: dict[str, str] = field(default_factory=dict)  # layer-owned keys -> the value typed
    notes: list[str] = field(default_factory=list)  # owned lines that could not change, and why


def _key(line: str) -> Optional[str]:
    match = _KEY_RE.match(line)
    return match.group(1) if match else None


def _values(lines: list[str], keys: set[str]) -> dict[str, str]:
    values = {}
    for line in lines:
        match = _KEY_RE.match(line)
        if match and match.group(1) in keys:
            values[match.group(1)] = match.group(2)
    return values


def split_edit(template: str, project: Project, case: Case, text: str) -> ConfigEdit:
    """Split `text`, the case's config as edited, into the new template and the changes of layer-owned lines."""
    params = case_layers(template, project, case)
    owned = set(params)
    t_lines = template.splitlines()
    # The shown text, line by line, with each line's place in the template (None: appended by a layer). Owned lines
    # are stand-ins; lines a layer removed are kept aside, to go back in after the line before them.
    shown, place = [], []
    hidden: dict[int, list[int]] = {}
    for index, line in enumerate(t_lines):
        key = _key(line)
        if key in owned and params[key] is None:
            hidden.setdefault(len(shown) - 1, []).append(index)
            continue
        shown.append(_OWNED + key if key in owned else line)
        place.append(index)
    t_keys = {_key(line) for line in t_lines}
    appended = [key for key, value in params.items() if value is not None and key not in t_keys]
    if appended:  # apply_parameters: the template's trailing blank lines, one blank line, the added lines
        while shown and not shown[-1].strip():
            shown.pop()
            hidden.setdefault(len(shown) - 1, []).insert(0, place.pop())
        shown.append("")
        place.append(None)
        for key in appended:
            shown.append(_OWNED + key)
            place.append(None)
    e_lines = text.splitlines()
    edited = [_OWNED + key if (key := _key(line)) in owned else line for line in e_lines]

    out = [t_lines[index] for index in hidden.get(-1, [])]

    def keep(i: int) -> None:
        if place[i] is not None:
            out.append(t_lines[place[i]])
        out.extend(t_lines[index] for index in hidden.get(i, []))

    for tag, i1, i2, j1, j2 in SequenceMatcher(None, shown, edited, autojunk=False).get_opcodes():
        if tag == "equal":
            for i in range(i1, i2):
                keep(i)
            continue
        for i in range(i1, i2):  # gone from the text: a template line goes; an owned one stays in the template
            if shown[i].startswith(_OWNED) and place[i] is not None:
                out.append(t_lines[place[i]])
            out.extend(t_lines[index] for index in hidden.get(i, []))
        out.extend(e_lines[j] for j in range(j1, j2) if not edited[j].startswith(_OWNED))
    new_template = "\n".join(out) + ("\n" if out and (template.endswith("\n") or not template) else "")

    edit = ConfigEdit(new_template)
    typed = _values(e_lines, owned)
    for key, value in params.items():
        if key in typed:
            if value is None or " ".join(typed[key].split()) != " ".join(value.split()):
                edit.changes[key] = typed[key]
        elif value is not None:
            edit.notes.append(_removed_note(project, case, template, key))
    return edit


def owner(project: Project, case: Case, template: str, key: str) -> str:
    """Which layer writes `key` into the case's config: case, altitude, placeholder, marker or form."""
    if key in case_parameters(project, case):
        return "case"
    try:
        altitude = freestream_for(project.settings, case_mach(project, case, template), case_altitude(project, case))
    except ProjectError:  # an altitude that cannot be computed: preflight reports it
        altitude = None
    if altitude and key in altitude and key != "REYNOLDS_LENGTH":  # the length is the form's, also then
        return "altitude"
    if key in project.settings.overrides:
        return "placeholder"
    if key in project.settings.markers:
        return "marker"
    return "form"


def _per_case_note(project: Project, key: str) -> str:
    if key in SWEEP_KEYS:
        return f"{key} is set per case by the sweep: change {SWEEP_KEYS[key]} on the Sweep page"
    if key == "MESH_FILENAME":
        return "MESH_FILENAME is the project's mesh: change it on Setup"
    if key == "BREAKDOWN_FILENAME":
        return "BREAKDOWN_FILENAME is named after the case"
    return f"{key} is set per case"


def _removed_note(project: Project, case: Case, template: str, key: str) -> str:
    kind = owner(project, case, template, key)
    if kind == "case":
        return _per_case_note(project, key)
    if kind == "altitude":
        return f"{key} comes from the altitude: it stays"
    if kind in ("placeholder", "marker"):
        return f"{key} is set under Extra options: remove it there"
    card = FORM_FIELDS[key][3] if key in FORM_FIELDS else "the form"
    return f"{key} is set by the form ({card}): clear it there to use the template's value"


def apply_changes(project: Project, case: Case, template: str, changes: dict[str, str]) -> tuple[list[str], list[str]]:
    """Change the layers' values in `project` (a copy the caller saves); returns (what changed, notes)."""
    done, notes = [], []
    for key, value in changes.items():
        kind = owner(project, case, template, key)
        if kind == "case":
            notes.append(_per_case_note(project, key))
        elif kind == "altitude":
            notes.append(f"{key} comes from the altitude: change the altitude or the Mach, or set the air "
                         "by hand on the Flight & air tab")
        elif kind == "placeholder":
            project.settings.overrides[key] = value
            done.append(f"{key} (Extra options)")
        elif kind == "marker":
            project.settings.markers[key] = value
            done.append(f"{key} (Boundaries)")
        elif key in FORM_FIELDS:
            group, name, kind_of, card = FORM_FIELDS[key]
            try:
                setattr(getattr(project.settings, group), name, kind_of(value))
            except ValueError as exc:
                notes.append(f"{key}: {value!r} is not a{'n integer' if kind_of is int else ' number'}"
                             if kind_of in (int, float) else str(exc))
                continue
            done.append(f"{key} ({card})")
        else:
            notes.append(f"{key} is set by the form")
    return done, notes


@dataclass
class WrittenLine:
    number: int  # 1-based, in the case's config
    text: str
    source: str  # who writes it: case, altitude, placeholder, marker or form (see owner)
    template: Optional[str] = None  # the template's own value for the key, when it has the line


def written_lines(template: str, project: Project, case: Case) -> list[WrittenLine]:
    """The lines of `case`'s config that AeroSuite writes over the template, in config order: what is not the
    template's own text. (Lines a layer removes are not shown: they are not in the config.)"""
    params = case_layers(template, project, case)
    own = _values(template.splitlines(), set(params))
    lines = []
    for number, line in enumerate(apply_parameters(template, params).splitlines(), 1):
        key = _key(line)
        if key in params and params[key] is not None:
            lines.append(WrittenLine(number, line, owner(project, case, template, key), own.get(key)))
    return lines
