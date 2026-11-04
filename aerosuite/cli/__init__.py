"""The `aerosuite` command line: commands parse input, call the engine and print."""
from . import (  # noqa: F401  (registers the commands)
    project_cmds, run_cmds, service_cmds, settings_cmds, tracker_cmds, web_cmds)
from .app import app, main

__all__ = ["app", "main"]
