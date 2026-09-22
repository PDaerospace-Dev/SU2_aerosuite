"""The `aerosuite` command line: commands parse input, call the engine and print."""
from . import project_cmds, run_cmds, web_cmds  # noqa: F401  (registers the commands)
from .app import app, main

__all__ = ["app", "main"]
