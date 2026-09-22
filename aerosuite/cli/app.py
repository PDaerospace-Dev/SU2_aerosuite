"""The Typer app and the helpers every command shares."""
import functools
from pathlib import Path
from typing import Annotated, Callable, TypeVar

import typer

from ..engine.errors import AeroSuiteError

app = typer.Typer(
    help="Prepare, run and post-process SU2 sweeps.",
    no_args_is_help=True,
    add_completion=False,
    pretty_exceptions_enable=False,
)

ProjectDir = Annotated[Path, typer.Argument(help="Project folder")]

F = TypeVar("F", bound=Callable)


def engine_errors(func: F) -> F:
    """Print engine errors as one line and exit with code 1 instead of a traceback."""

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except AeroSuiteError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1) from None

    return wrapper  # type: ignore[return-value]


def main() -> None:
    app()
