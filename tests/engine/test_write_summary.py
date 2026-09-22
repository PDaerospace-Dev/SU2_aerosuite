import pandas as pd
import pytest

from aerosuite.engine.errors import ProjectError
from aerosuite.engine.results import RESULTS_DIR, SUMMARY_FILE, write_summary


def test_write_summary_creates_results_folder(tmp_path):
    df = pd.DataFrame([{"Case": "M0p8_a0_b0", "Mach": 0.8, "Alpha": 0.0, "Beta": 0.0, "CL": 0.5}])
    path = write_summary(tmp_path, df)
    assert path == tmp_path / RESULTS_DIR / SUMMARY_FILE
    assert pd.read_csv(path)["CL"].tolist() == [0.5]


def test_write_summary_reports_os_errors(tmp_path):
    (tmp_path / RESULTS_DIR).write_text("a file, not a folder")
    with pytest.raises(ProjectError, match="Cannot write"):
        write_summary(tmp_path, pd.DataFrame([{"Case": "x"}]))
