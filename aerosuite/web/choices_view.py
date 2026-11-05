"""The Sweep page's "Your choices": what every case will run with, from the pages that set it (mesh, solver, scheme,
CFL, iterations, freestream, reference, hand-set keys), in one place before Generate.

A choice is marked when the project changes it from the template, and flagged when it differs from what the cases
last ran with (the configs in their run folders): a restart then continues with other settings. Folded, the card is
one line of the main values."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional, Sequence

from nicegui import ui

from ..engine.cfg import read_template, settings_parameters
from ..engine.config_rules import _options
from ..engine.errors import AeroSuiteError
from ..engine.models import Case, Project
from ..engine.restarts import RUNS_DIR
from .layout import ProjectFrame, project_url
from .ui_kit import card_head, fold_button, titled


@dataclass(frozen=True)
class Choice:
    key: str  # its marker: choice-<key>
    label: str
    value: str
    detail: str = ""
    page: str = ""  # the page that sets it ("": this page)
    own: bool = False  # the project changes it from the template
    last_run: str = ""  # what the cases last ran with, when that differs


def _same(a: Optional[str], b: Optional[str]) -> bool:
    if a is None or b is None:
        return a == b
    try:
        return float(a) == float(b)
    except ValueError:
        return " ".join(a.split()).upper() == " ".join(b.split()).upper()


def _changed(keys: Sequence[str], params: Mapping[str, Optional[str]], template: Mapping[str, str]) -> bool:
    return any(key in params and not _same(params[key], template.get(key)) for key in keys)


def _since(keys: Sequence[str], now: Mapping[str, Optional[str]], last: Mapping[str, set[str]]) -> str:
    """What the cases last ran with for `keys`, when any differs from `now` ("" when the same, or never run)."""
    parts = []
    for key in keys:
        ran = last.get(key)
        if not ran:
            continue
        if any(not _same(value, now.get(key)) for value in ran):
            parts.append(f"{key}= {' / '.join(sorted(ran))}")
    return "; ".join(parts)


def _order(muscl: Optional[str]) -> str:
    return "2nd order" if (muscl or "").upper() == "YES" else "1st order"


def last_run_options(project_dir: Path, cases: Sequence[Case], keys: Sequence[str]) -> dict[str, set[str]]:
    """The values of `keys` in the configs the cases last ran with (runs/<case>/<case>.cfg), each key's distinct
    values; a case never run has no config there."""
    values: dict[str, set[str]] = {}
    for case in cases:
        options = _run_options(Path(project_dir) / RUNS_DIR / case.name / f"{case.name}.cfg")
        for key in keys:
            if key in options:
                values.setdefault(key, set()).add(options[key])
    return values


_RUN_CACHE: dict[str, tuple[int, dict[str, str]]] = {}  # a run config's options, by path, while its mtime holds


def _run_options(path: Path) -> dict[str, str]:
    try:
        stamp = os.stat(path).st_mtime_ns
    except OSError:
        return {}
    cached = _RUN_CACHE.get(str(path))
    if cached is not None and cached[0] == stamp:
        return cached[1]
    try:
        options = _options(path.read_text(encoding="utf-8", errors="replace"))
    except OSError:
        return {}
    _RUN_CACHE[str(path)] = (stamp, options)
    return options


TILE_KEYS = {
    "solver": ("SOLVER", "KIND_TURB_MODEL"),
    "scheme": ("CONV_NUM_METHOD_FLOW", "MUSCL_FLOW"),
    "cfl": ("CFL_NUMBER", "CFL_ADAPT", "CFL_ADAPT_PARAM"),
    "iterations": ("ITER", "CONV_FIELD", "CONV_RESIDUAL_MINVAL", "CONV_CAUCHY_ELEMS", "CONV_CAUCHY_EPS",
                   "CONV_STARTITER"),
    "reference": ("REF_LENGTH", "REF_AREA", "REF_ORIGIN_MOMENT_X", "REF_ORIGIN_MOMENT_Y", "REF_ORIGIN_MOMENT_Z"),
}
COMPARED = tuple(key for keys in TILE_KEYS.values() for key in keys) + ("REYNOLDS_LENGTH",)


def _stopping(options: Mapping[str, str]) -> str:
    """When SU2 stops before ITER, in words (its defaults where the config says nothing)."""
    from ..engine.editing import COEFFICIENT_FIELDS, conv_fields

    fields = conv_fields(options.get("CONV_FIELD") or "RMS_DENSITY")
    if all(field in COEFFICIENT_FIELDS for field in fields):
        names = ", ".join(COEFFICIENT_FIELDS[field] for field in fields)
        return (f"or when {names} settle ({options.get('CONV_CAUCHY_EPS') or '1e-10'} over "
                f"{options.get('CONV_CAUCHY_ELEMS') or '100'} iterations)")
    return f"or when {', '.join(fields)} reaches {options.get('CONV_RESIDUAL_MINVAL') or '-8'}"


def project_choices(project: Project, template: str, last: Optional[Mapping[str, set[str]]] = None) -> list[Choice]:
    """The choices for `project` whose template text is `template`; `last` what the cases last ran with
    (last_run_options)."""
    last = last or {}
    tmpl = _options(template)
    params = settings_parameters(project.settings)
    now = {**tmpl, **{key: value for key, value in params.items() if value is not None}}

    def get(key: str, default: str = "—") -> str:
        return now.get(key) or default

    def tile(key: str, label: str, value: str, detail: str = "", page: str = "aircraft") -> Choice:
        keys = TILE_KEYS[key]
        return Choice(key, label, value, detail, page, _changed(keys, params, tmpl), _since(keys, now, last))

    fs, overrides = project.settings.freestream, project.settings.overrides
    adaptive = get("CFL_ADAPT", "NO").upper() == "YES"
    altitude = fs.mode == "altitude"
    reynolds_length = get("REYNOLDS_LENGTH", "")
    freestream_detail = (f"Re length {reynolds_length} m" if reynolds_length else "") if altitude else " · ".join(
        part for part in (f"Re {get('REYNOLDS_NUMBER', '')}" if now.get("REYNOLDS_NUMBER") else "",
                          f"T {get('FREESTREAM_TEMPERATURE', '')} K" if now.get("FREESTREAM_TEMPERATURE") else "")
        if part)
    hand_set = len(overrides)
    return [
        Choice("mesh", "Mesh", Path(project.mesh.path).name if project.mesh.path else "—",
               f"{len(project.mesh.markers)} markers" if project.mesh.markers else "", "setup",
               bool(project.mesh.path)),
        tile("solver", "Solver", f"{get('SOLVER')} · {get('KIND_TURB_MODEL', 'no turbulence model')}",
             "turbulence model" if now.get("KIND_TURB_MODEL") else ""),
        tile("scheme", "Scheme", f"{get('CONV_NUM_METHOD_FLOW')} · {_order(now.get('MUSCL_FLOW'))}",
             f"MUSCL_FLOW= {get('MUSCL_FLOW', 'NO')}"),
        tile("cfl", "CFL", f"{get('CFL_NUMBER')} · {'adaptive' if adaptive else 'fixed'}",
             f"adapt {get('CFL_ADAPT_PARAM')}" if adaptive else ""),
        tile("iterations", "Iterations", f"{get('ITER')} per case", _stopping(now)),
        Choice("freestream", "Freestream", "From altitude (ISA)" if altitude else "Set by hand", freestream_detail,
               "aircraft", altitude or _changed(("REYNOLDS_NUMBER", "FREESTREAM_TEMPERATURE", "REYNOLDS_LENGTH"),
                                                params, tmpl),
               _since(("REYNOLDS_LENGTH",), now, last)),
        tile("reference", "Reference", f"L {get('REF_LENGTH')} · S {get('REF_AREA')}",
             f"moments about ({get('REF_ORIGIN_MOMENT_X', '0')}, {get('REF_ORIGIN_MOMENT_Y', '0')}, "
             f"{get('REF_ORIGIN_MOMENT_Z', '0')})"),
        Choice("hand-set", "Hand-set keys", f"{hand_set} key{'' if hand_set == 1 else 's'}" if hand_set else "none",
               ", ".join(sorted(overrides)), "config", bool(hand_set)),
    ]


def folded_line(choices: Sequence[Choice]) -> str:
    """The folded card's line: the main values, e.g. "RANS · SST · ROE · 2nd order · CFL 1 · adaptive · …"."""
    by_key = {choice.key: choice for choice in choices}
    parts = [by_key["solver"].value, by_key["scheme"].value, f"CFL {by_key['cfl'].value}",
             by_key["iterations"].value.replace(" per case", " iterations"), by_key["freestream"].value]
    return " · ".join(part for part in parts if part)


def _choices(frame: ProjectFrame) -> list[Choice]:
    project, directory = frame.session.project, frame.session.directory
    try:
        template = read_template(directory, project)
    except AeroSuiteError:
        template = ""
    return project_choices(project, template, last_run_options(directory, project.cases, COMPARED))


def choices_card(frame: ProjectFrame) -> None:
    """The card: a tile per choice (a click opens the page that sets it); folded, one line."""
    choices = _choices(frame)
    own = sum(choice.own for choice in choices)
    since = sum(bool(choice.last_run) for choice in choices)
    with ui.column().classes("as-card as-choices-card w-full").mark("choices") as box:
        with card_head("Your choices", f"{own} changed from the template"):
            ui.label(folded_line(choices)).classes("as-choices-line as-muted").mark("choices-line")
            if since:  # seen folded too
                ui.label(f"{since} changed since the cases last ran").classes("as-choices-since").mark(
                    "choices-since")
            ui.space()
            with ui.row().classes("as-choice-key no-wrap"):
                ui.element("span").classes("as-choice-own")
                ui.label("changed from the template")
            fold_button(box, "sweep-choices")
        with ui.element("div").classes("as-choices"):
            for choice in choices:
                _tile(choice, frame.session.directory)


def _tile(choice: Choice, directory: Path) -> None:
    holder = ui.link(target=project_url(choice.page, directory)) if choice.page else ui.element("div")
    with holder.classes("as-choice-item column no-wrap" + (" as-choice-since" if choice.last_run else "")).mark(
            f"choice-{choice.key}"):
        with ui.row().classes("items-center gap-1 no-wrap"):
            ui.label(choice.label).classes("as-choice-label")
            if choice.own:
                ui.element("span").classes("as-choice-own").mark(f"choice-{choice.key}-own")
        lines = [(choice.value, "as-choice-value", ""), (choice.detail, "as-choice-detail", ""),
                 (f"last run: {choice.last_run}" if choice.last_run else "", "as-choice-ran", f"choice-{choice.key}-ran")]
        for text, kind, mark in lines:
            if text:
                label = titled(ui.label(text).classes(kind), text)
                if mark:
                    label.mark(mark)
    if choice.page:
        titled(holder, f"Set on the {choice.page.capitalize()} page")
