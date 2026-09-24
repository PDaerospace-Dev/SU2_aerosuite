from pathlib import Path

from aerosuite.core.su2_generator import GenerationConfig, SU2Generator


def _config(tmp_path, **overrides):
    template = tmp_path / "base.cfg"
    template.write_text("AOA= 0\n")
    values = dict(
        mach_values=[0.8], alpha_values=[0.0], beta_values=[0.0],
        include_mach=True, include_alpha=True, include_beta=True,
        include_altitude=True, include_base=True, altitude="sl", base_name="x07",
        output_dir=tmp_path / "out", template_path=template,
    )
    values.update(overrides)
    return GenerationConfig(**values)


def test_format_mach_keeps_all_digits_and_v7_whole_numbers():
    assert SU2Generator.format_mach(0.85) == "M0p85"
    assert SU2Generator.format_mach(0.78) == "M0p78"
    assert SU2Generator.format_mach(0.8) == "M0p8"
    assert SU2Generator.format_mach(1.0) == "M1p0"


def test_format_angle():
    assert SU2Generator.format_angle(-5) == "n5"
    assert SU2Generator.format_angle(2.5) == "2p5"
    assert SU2Generator.format_angle(1.5) == "1p5"


def test_filenames_no_longer_collide(tmp_path):
    config = _config(tmp_path, mach_values=[0.78, 0.8, 0.82, 0.85], alpha_values=[1.5, 2.5])
    names = SU2Generator.generate_all_filenames(config)
    assert len(set(names)) == 8
    assert "M0p85_sl_a2p5_b0_x07.cfg" in names


def test_validate_config_rejects_duplicate_names(tmp_path):
    ok, message = SU2Generator.validate_config(_config(tmp_path, alpha_values=[2.0, 2.0]))
    assert not ok
    assert "M0p8_sl_a2_b0_x07.cfg" in message


def test_validate_config_accepts_distinct_values(tmp_path):
    assert SU2Generator.validate_config(_config(tmp_path, alpha_values=[1.5, 2.5])) == (True, "")


def test_update_template_content_remove_and_backslash():
    content = "MARKER_PLOTTING= ( wall )\nMESH_FILENAME= a.su2\n"
    out = SU2Generator.update_template_content(content, {
        "MARKER_PLOTTING": SU2Generator.REMOVE_LINE,
        "MESH_FILENAME": r"C:\m\wing.su2",
    })
    assert out == "MESH_FILENAME= C:\\m\\wing.su2\n"


def test_extract_mesh_markers_missing_file_returns_empty(tmp_path):
    assert SU2Generator.extract_mesh_markers(Path(tmp_path / "none.su2")) == []
