"""The Typer app and the helpers every command shares."""
import functools
from pathlib import Path
from typing import Annotated, Callable, Iterable, TypeVar

import typer

from ..engine.errors import AeroSuiteError
from ..engine.preflight import Problem

app = typer.Typer(
    help="Prepare, run and post-process SU2 sweeps.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ProjectDir = Annotated[Path, typer.Argument(help="Project folder")]

F = TypeVar("F", bound=Callable)


def engine_errors(func: F) -> F:
    """Print engine errors (and, as a backstop, OS errors) as one line and exit 1 instead of a traceback."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except (AeroSuiteError, OSError) as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None

    return wrapper  # type: ignore[return-value]


def print_problems(problems: Iterable[Problem]) -> None:
    """Warnings to stdout, errors to stderr, one per line."""
    for problem in problems:
        is_error = problem.severity == "error"
        typer.echo(f"{'Error' if is_error else 'Warning'}: {problem.message}", err=is_error)


def main() -> None:
    app()
