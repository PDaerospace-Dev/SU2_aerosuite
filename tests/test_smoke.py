"""Import-level checks for the legacy app and the bundled sweep script."""
import ast
import importlib
from pathlib import Path

import pytest

SWEEP_SCRIPT = Path(__file__).resolve().parents[1] / "aerosuite" / "resources" / "aoa_sweep_v8.py"


def test_core_and_utils_import():
    importlib.import_module("aerosuite.core")
    importlib.import_module("aerosuite.utils")


def test_legacy_ui_imports_headless(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PyQt5.QtWidgets")
    importlib.import_module("aerosuite.ui")
    importlib.import_module("aerosuite.main")


def test_sweep_script_stays_python37_compatible():
    source = SWEEP_SCRIPT.read_text(encoding="utf-8")
    ast.parse(source, feature_version=(3, 7))
