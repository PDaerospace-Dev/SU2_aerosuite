"""Registers every page of the web UI."""
from pathlib import Path

from . import config


def register_pages(root: Path) -> None:
    config.set_root(root)
    from nicegui import app

    from .slurm_watch import WATCH

    app.on_startup(WATCH.start)  # the Slurm poller: idle until a Slurm job or the cluster panel needs it
    app.on_shutdown(WATCH.stop)
    from .pages import config as config_page
    from .pages import (aircraft, calculators, cluster, monitor, profiles, projects, results, run, settings, setup,
                        sweep)

    projects.register()
    setup.register()
    config_page.register()
    aircraft.register()
    sweep.register()
    run.register()
    monitor.register()
    results.register()
    calculators.register()
    profiles.register()
    settings.register()
    cluster.register()
