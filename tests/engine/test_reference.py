import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.reference import (
    find_lines,
    keys_in,
    load_reference,
    parse_reference,
    read_reference_text,
    search,
)

SMALL = """\
%%%%%%%%%%%%%%%%%%%%%%%%
% SU2 configuration file   %
%%%%%%%%%%%%%%%%%%%%%%%%

% ------------- SOLVER SETUP ------------%
%
% Solver type (EULER, NAVIER_STOKES,
%              RANS)
SOLVER= EULER
%
% Specify turbulence model (NONE, SA, SST)
KIND_TURB_MODEL= NONE

% ------------- BOUNDARIES ------------%
%
% Euler wall boundary marker(s)
MARKER_EULER= ( airfoil )
%
% Temperature of the wall
FREESTREAM_TEMPERATURE= 288.15
"""


def test_parse_small_file():
    options = parse_reference(SMALL)
    assert [o.key for o in options] == ["SOLVER", "KIND_TURB_MODEL", "MARKER_EULER", "FREESTREAM_TEMPERATURE"]
    solver = options[0]
    assert solver.description == "Solver type (EULER, NAVIER_STOKES, RANS)"
    assert solver.section == "SOLVER SETUP"
    assert solver.line == "SOLVER= EULER"
    assert solver.line_no == 9
    assert options[2].default_value == "( airfoil )"
    assert options[2].section == "BOUNDARIES"


def test_bundled_reference():
    options = load_reference()
    euler = [o for o in options if o.key == "MARKER_EULER"]
    assert euler and "Euler wall boundary marker" in euler[0].description
    assert euler[0].section == "BOUNDARY CONDITION DEFINITION"
    temps = [o for o in options if o.key == "FREESTREAM_TEMPERATURE"]
    assert len(temps) >= 2 and len({o.section for o in temps}) >= 2


def test_search_orders_key_matches_first():
    options = parse_reference(SMALL)
    assert [o.key for o in search(options, "euler")] == ["MARKER_EULER", "SOLVER"]
    assert [o.key for o in search(options, "TEMPERATURE")] == ["FREESTREAM_TEMPERATURE"]
    assert search(options, "  ") == []
    assert len(search(load_reference(), "marker", limit=5)) == 5


def test_keys_in_and_find_lines():
    text = "SOLVER= RANS\n% CFL_NUMBER= 5\n  AOA = 2\nnot an option\n"
    assert keys_in(text) == {"SOLVER", "AOA"}
    assert find_lines(SMALL, "euler") == [7, 9, 16, 17]
    assert find_lines(SMALL, "") == []


def test_load_errors(tmp_path):
    with pytest.raises(ProjectError, match="Cannot read"):
        read_reference_text(tmp_path / "missing.cfg")
    empty = tmp_path / "empty.cfg"
    empty.write_text("% only comments\n")
    with pytest.raises(ProjectError, match="no SU2 options"):
        load_reference(empty)
