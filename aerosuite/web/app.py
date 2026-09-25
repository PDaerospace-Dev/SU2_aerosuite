"""Registers every page of the web UI."""
from pathlib import Path

from . import config


def register_pages(root: Path) -> None:
    config.set_root(root)
    from .pages import config as config_page
    from .pages import aircraft, monitor, projects, run, setup, sweep

    projects.register()
    setup.register()
    config_page.register()
    aircraft.register()
    sweep.register()
    run.register()
    monitor.register()
