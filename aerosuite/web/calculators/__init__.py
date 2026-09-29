"""The Calculators page's calculators. Each is a module with CALCULATOR = Calculator(...); to add one,
write the module and list it in calculators()."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from ..layout import ProjectFrame


@dataclass
class CalcContext:
    frame: Optional["ProjectFrame"]  # the open project's frame; None outside a project
    handoff: dict  # values handed over from another calculator (ISA -> y+); may be empty
    open: Callable[[str, dict], None]  # show another calculator with a handoff


@dataclass(frozen=True)
class Calculator:
    key: str
    title: str
    description: str
    build: Callable[[CalcContext], None]  # draws the calculator's card


def calculators() -> list[Calculator]:
    from . import isa, yplus  # here, not at the top: the calculator modules import this one

    return [isa.CALCULATOR, yplus.CALCULATOR]
