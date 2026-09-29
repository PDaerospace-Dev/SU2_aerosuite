"""Formulas for derived values (per case) and characteristic values (per curve).

Read with Python's `ast` and checked against an allowed list, then evaluated by walking the tree: never `eval`.

Per case:  numbers, + - * / ^ ( ), names (bare, or in braces: {Avg_TotalPress(outlet)}), and the functions
           sqrt abs log exp sin cos tan (degrees) min max.
Per curve: the same arithmetic around the curve functions slope(Y, X, from, to), at(Y, X, value), max(Y), min(Y),
           argmax(Y, X), argmin(Y, X), where Y and X name series along the curve.
A value that cannot be computed (division by zero, a missing column, a value off the curve) is `Missing(reason)`.
"""
from __future__ import annotations

import ast
import math
import re
from dataclasses import dataclass
from typing import Callable, Iterable, Mapping, Optional, Sequence, Union

from .errors import ProjectError
from .naming import format_value

_BRACED = re.compile(r"\{([^{}]*)\}")
_PLACEHOLDER = "__v{}__"


class FormulaError(ProjectError):
    """The text is not a formula this reader accepts."""


@dataclass(frozen=True)
class Missing:
    """A value that cannot be computed, and why."""
    reason: str


Value = Union[float, Missing]


def _degrees(function: Callable[[float], float]) -> Callable[[float], float]:
    return lambda x: function(math.radians(x))


def _sqrt(x: float) -> Value:
    return math.sqrt(x) if x >= 0 else Missing("sqrt of a negative number")


def _log(x: float) -> Value:
    return math.log(x) if x > 0 else Missing("log of a number ≤ 0")


SCALAR_FUNCTIONS: dict[str, tuple[Callable[..., Value], Optional[int]]] = {  # name: (function, argument count)
    "sqrt": (_sqrt, 1), "abs": (abs, 1), "log": (_log, 1), "exp": (math.exp, 1),
    "sin": (_degrees(math.sin), 1), "cos": (_degrees(math.cos), 1), "tan": (_degrees(math.tan), 1),
    "min": (min, None), "max": (max, None),
}
# name: (argument count, how many leading arguments are series)
CURVE_FUNCTIONS = {"slope": (4, 2), "at": (3, 2), "max": (1, 1), "min": (1, 1), "argmax": (2, 2), "argmin": (2, 2)}
_OPERATORS = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b,
              ast.Div: None, ast.Pow: None}


@dataclass(frozen=True)
class Formula:
    text: str
    tree: ast.Expression
    names: frozenset
    curve: bool
    _placeholders: tuple  # (placeholder, real name) pairs


def parse(text: str, *, curve: bool = False, known: Optional[Iterable[str]] = None) -> Formula:
    """Read `text` (per case, or per curve with `curve`); `known` names, when given, are the only ones allowed."""
    if not text or not text.strip():
        raise FormulaError("Give a formula")
    placeholders: dict[str, str] = {}

    def brace(match: re.Match) -> str:
        name = match.group(1).strip()
        if not name:
            raise FormulaError("Empty braces: write a name inside, e.g. {Avg_Massflow(outlet)}")
        key = _PLACEHOLDER.format(len(placeholders))
        placeholders[key] = name
        return key

    source = _BRACED.sub(brace, text).replace("^", "**")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError:
        raise FormulaError(f"{text.strip()!r} is not a valid formula") from None
    names: set[str] = set()
    _check(tree.body, placeholders, names, curve, in_series=False)
    if known is not None:
        unknown = sorted(names - set(known))
        if unknown:
            raise FormulaError(f"{unknown[0]} is not a known name")
    return Formula(text, tree, frozenset(names), curve, tuple(placeholders.items()))


def _name(node: ast.Name, placeholders: Mapping[str, str]) -> str:
    return placeholders.get(node.id, node.id)


def _check(node: ast.AST, placeholders: Mapping[str, str], names: set, curve: bool, in_series: bool) -> None:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaError(f"{node.value!r} is not a number")
        return
    if isinstance(node, ast.Name):
        if node.id.startswith("__") and node.id not in placeholders:
            raise FormulaError(f"{node.id} is not allowed")
        name = _name(node, placeholders)
        if curve and not in_series:
            raise FormulaError(f"{name} is a series here; use it inside a function, e.g. max({name})")
        names.add(name)
        return
    if isinstance(node, ast.BinOp) and type(node.op) in _OPERATORS:
        _check(node.left, placeholders, names, curve, in_series)
        _check(node.right, placeholders, names, curve, in_series)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        _check(node.operand, placeholders, names, curve, in_series)
        return
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise FormulaError("Only plain function names can be called, e.g. sqrt(x)")
        function = node.func.id
        if node.keywords or any(isinstance(arg, ast.Starred) for arg in node.args):
            raise FormulaError(f"{function} takes plain arguments, e.g. {function}(x)")
        if curve and function in CURVE_FUNCTIONS:
            count, series = CURVE_FUNCTIONS[function]
            if len(node.args) != count:
                raise FormulaError(f"{function} takes {count} argument{'s' if count > 1 else ''}")
            for position, arg in enumerate(node.args):
                if position < series:
                    if not isinstance(arg, ast.Name):
                        raise FormulaError(f"Argument {position + 1} of {function} must name a parameter")
                    _check(arg, placeholders, names, curve, in_series=True)
                elif any(isinstance(inner, ast.Name) for inner in ast.walk(arg)):
                    raise FormulaError(f"Argument {position + 1} of {function} must be a number")
                else:
                    _check(arg, placeholders, set(), curve=False, in_series=False)
            return
        if function in SCALAR_FUNCTIONS:
            _, count = SCALAR_FUNCTIONS[function]
            if (count is not None and len(node.args) != count) or not node.args:
                raise FormulaError(f"{function} takes {count or 'one or more'} argument{'s' if count != 1 else ''}")
            for arg in node.args:
                _check(arg, placeholders, names, curve, in_series)
            return
        if function in CURVE_FUNCTIONS:
            raise FormulaError(f"{function} works on a curve: use it in a characteristic value")
        raise FormulaError(f"{function} is not a function")
    raise FormulaError(f"{ast.unparse(node)} is not allowed in a formula")


def _missing(values: Iterable[Value]) -> Optional[Missing]:
    return next((v for v in values if isinstance(v, Missing)), None)


def _arith(op: ast.operator, a: float, b: float) -> Value:
    try:
        if isinstance(op, ast.Div):
            return a / b if b != 0 else Missing("division by zero")
        if isinstance(op, ast.Pow):
            result = a ** b
            return result if isinstance(result, float) or isinstance(result, int) else Missing("not a real number")
        return _OPERATORS[type(op)](a, b)
    except OverflowError:
        return Missing("number too large")


def _walk(node: ast.AST, lookup: Callable[[ast.Name], Value], call: Callable[[ast.Call], Value]) -> Value:
    if isinstance(node, ast.Constant):
        return float(node.value)
    if isinstance(node, ast.Name):
        return lookup(node)
    if isinstance(node, ast.UnaryOp):
        operand = _walk(node.operand, lookup, call)
        if isinstance(operand, Missing):
            return operand
        return -operand if isinstance(node.op, ast.USub) else operand
    if isinstance(node, ast.BinOp):
        left, right = _walk(node.left, lookup, call), _walk(node.right, lookup, call)
        return _missing((left, right)) or _arith(node.op, left, right)
    return call(node)


def _finish(result: Value) -> Value:
    if isinstance(result, Missing):
        return result
    if isinstance(result, complex) or math.isnan(result):
        return Missing("not a real number")
    if math.isinf(result):
        return Missing("number too large")
    return float(result)


def evaluate(formula: Formula, values: Mapping[str, Value]) -> Value:
    """The formula's value for one case; `values` maps names to numbers (or Missing with the reason)."""
    placeholders = dict(formula._placeholders)

    def lookup(node: ast.Name) -> Value:
        name = _name(node, placeholders)
        value = values.get(name)
        if isinstance(value, Missing):
            return value
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return Missing(f"no value for {name}")
        return float(value)

    def call(node: ast.Call) -> Value:
        function, _ = SCALAR_FUNCTIONS[node.func.id]
        args = [_walk(arg, lookup, call) for arg in node.args]
        missing = _missing(args)
        if missing:
            return missing
        try:
            return function(*args)
        except (OverflowError, ValueError):
            return Missing(f"{node.func.id} of {format_value(args[0])} cannot be computed")

    return _finish(_walk(formula.tree.body, lookup, call))


def _pairs(ys: Sequence, xs: Sequence) -> list[tuple[float, float]]:
    """(x, y) points along the curve, skipping gaps."""
    def ok(v) -> bool:
        return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    return [(float(x), float(y)) for y, x in zip(ys, xs) if ok(x) and ok(y)]


def evaluate_curve(formula: Formula, curve: Mapping[str, Sequence]) -> Value:
    """A characteristic value: `curve` maps names to series along one curve (same length, curve order)."""
    placeholders = dict(formula._placeholders)

    def series(node: ast.AST) -> Union[Sequence, Missing]:
        name = _name(node, placeholders)
        return curve[name] if name in curve else Missing(f"no values for {name}")

    def call(node: ast.Call) -> Value:
        name = node.func.id
        if name not in CURVE_FUNCTIONS:  # a scalar function around curve values, e.g. abs(slope(...))
            args = [_walk(arg, series, call) for arg in node.args]
            return _missing(args) or SCALAR_FUNCTIONS[name][0](*args)
        _, n_series = CURVE_FUNCTIONS[name]
        data = [series(arg) for arg in node.args[:n_series]]
        numbers = [_walk(arg, series, call) for arg in node.args[n_series:]]  # plain numbers (checked by parse)
        missing = _missing(data + numbers)
        if missing:
            return missing
        y_name = _name(node.args[0], placeholders)
        x_name = _name(node.args[1], placeholders) if n_series > 1 else ""
        points = _pairs(data[0], data[1] if n_series > 1 else list(range(len(data[0]))))
        return _curve_function(name, points, numbers, x_name, y_name)

    return _finish(_walk(formula.tree.body, series, call))


def _curve_function(name: str, points: list, numbers: list, x_name: str, y_name: str) -> Value:
    if not points:
        return Missing(f"no values for {y_name}")
    if name in ("max", "min", "argmax", "argmin"):
        pick = max if name.endswith("max") else min
        x, y = pick(points, key=lambda p: p[1])
        return x if name.startswith("arg") else y
    if name == "slope":
        low, high = sorted(numbers)
        inside = [p for p in points if low <= p[0] <= high]
        xs = {p[0] for p in inside}
        if len(inside) < 2 or len(xs) < 2:
            return Missing(f"fewer than 2 points with {x_name} in {format_value(numbers[0])} … "
                           f"{format_value(numbers[1])}")
        n = len(inside)
        mean_x = sum(p[0] for p in inside) / n
        mean_y = sum(p[1] for p in inside) / n
        return (sum((p[0] - mean_x) * (p[1] - mean_y) for p in inside)
                / sum((p[0] - mean_x) ** 2 for p in inside))
    # at(Y, X, value): walk the curve in its order and interpolate on the first segment that holds the value
    target = numbers[0]
    for (x0, y0), (x1, y1) in zip(points, points[1:]):
        if min(x0, x1) <= target <= max(x0, x1):
            return y0 if x1 == x0 else y0 + (y1 - y0) * (target - x0) / (x1 - x0)
    if len(points) == 1 and points[0][0] == target:
        return points[0][1]
    xs = [p[0] for p in points]
    return Missing(f"{format_value(target)} is outside the {x_name} data ({format_value(min(xs))} … "
                   f"{format_value(max(xs))})")
