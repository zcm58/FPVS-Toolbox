from __future__ import annotations

from pathlib import Path

from Tools.Individual_Detectability.core import (
    discover_conditions,
    parse_participant_id,
    render_topomap_svg,
)


def test_parse_participant_id_scp_variants() -> None:
    assert parse_participant_id("SCP7_condition_Results.xlsx") == "P7"
    assert parse_participant_id("SCP07_condition_Results.xlsx") == "P7"


def test_discover_conditions_with_subfolders(tmp_path: Path) -> None:
    cond_a = tmp_path / "CondA"
    cond_b = tmp_path / "CondB"
    cond_a.mkdir()
    cond_b.mkdir()
    (cond_a / "a.xlsx").write_text("data")
    (cond_b / "b.xlsx").write_text("data")

    conditions = discover_conditions(tmp_path)
    names = [c.name for c in conditions]
    assert names == ["CondA", "CondB"]
    assert all(c.files for c in conditions)


def test_discover_conditions_single_root(tmp_path: Path) -> None:
    (tmp_path / "root.xlsx").write_text("data")
    conditions = discover_conditions(tmp_path)
    assert len(conditions) == 1
    assert conditions[0].path == tmp_path


def test_topomap_svg_nonblank(tmp_path: Path) -> None:
    import pytest

    np = pytest.importorskip("numpy")
    mne = pytest.importorskip("mne")

    montage = mne.channels.make_standard_montage("biosemi64")
    electrodes = montage.ch_names
    z_threshold = 1.64
    z_values = np.full(len(electrodes), z_threshold)
    z_values[0] = z_threshold + 1.2
    z_values[5] = z_threshold + 0.5

    output = tmp_path / "topomap.svg"
    render_topomap_svg(z_values, electrodes, z_threshold, output)
    contents = output.read_text(encoding="utf-8")
    assert output.stat().st_size > 200
    assert "<svg" in contents
    assert "path" in contents
