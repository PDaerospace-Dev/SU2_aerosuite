"""Shared pytest configuration and fixtures."""
from pathlib import Path

import matplotlib
import pytest

# Legacy results code imports pyplot at module import; never open a window in tests.
matplotlib.use("Agg")

HISTORY_HEADER = '"Inner_Iter",   "rms[Rho]",   "CL",   "CD",   "CMy"'


@pytest.fixture
def history_writer():
    """Write an SU2-style history.csv whose CL column follows `cl`."""

    def write(folder: Path, cl: list[float]) -> Path:
        folder.mkdir(parents=True, exist_ok=True)
        lines = [HISTORY_HEADER]
        for i, value in enumerate(cl):
            lines.append(f"{i:8d}, {-2 - 0.1 * i:12.6f}, {value:12.8f}, {0.02:12.8f}, {-0.1:12.8f}")
        path = folder / "history.csv"
        path.write_text("\n".join(lines) + "\n")
        return path

    return write
