from aerosuite.engine.restarts import RUNS_DIR, find_restart_file, own_case_of, restart_file


def test_restart_file_as_written_then_dat_then_csv(tmp_path):
    folder = tmp_path / "case"
    folder.mkdir()
    assert find_restart_file(folder) is None
    (folder / "restart_flow.csv").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow.csv"
    (folder / "restart_flow.dat").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow.dat"
    (folder / "restart_flow").write_text("x")
    assert find_restart_file(folder) == folder / "restart_flow"


def test_restart_filename_comes_from_the_case_cfg(tmp_path):
    folder = tmp_path / "M0p8_a0_b0"
    folder.mkdir()
    (folder / "M0p8_a0_b0.cfg").write_text("SOLVER= RANS\nRESTART_FILENAME= my_solution\n")
    (folder / "restart_flow.dat").write_text("not this one")
    (folder / "my_solution.dat").write_text("x")
    assert find_restart_file(folder) == folder / "my_solution.dat"


def test_missing_folder_and_a_project_case(tmp_path):
    assert find_restart_file(tmp_path / "nope") is None
    assert restart_file(tmp_path, "M0p8_a0_b0") is None
    folder = tmp_path / RUNS_DIR / "M0p8_a0_b0"
    folder.mkdir(parents=True)
    (folder / "restart_flow.dat").write_text("x")
    assert restart_file(tmp_path, "M0p8_a0_b0") == folder / "restart_flow.dat"


def test_own_case_of(tmp_path):
    names = ["M0p8_a0_b0", "M0p8_a2_b0"]
    runs = tmp_path / RUNS_DIR
    assert own_case_of(tmp_path, str(runs / "M0p8_a0_b0"), names) == "M0p8_a0_b0"
    assert own_case_of(tmp_path, str(runs / "M0p8_a2_b0" / "restart_flow.dat"), names) == "M0p8_a2_b0"
    assert own_case_of(tmp_path, str(runs / "other"), names) is None
    assert own_case_of(tmp_path, str(tmp_path / "elsewhere" / "M0p8_a0_b0"), names) is None
