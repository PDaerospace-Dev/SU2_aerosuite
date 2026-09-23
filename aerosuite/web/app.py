"""Registers every page of the web UI."""
from pathlib import Path

from . import config


def register_pages(root: Path) -> None:
    config.set_root(root)
    from .pages import projects, settings, setup, sweep

    projects.register()
    setup.register()
    settings.register()
    sweep.register()
