from __future__ import annotations

from pathlib import Path

from Tools.Individual_Detectability.core import (
    discover_conditions,
    _plot_topomap_compat,
    parse_participant_id,
)


def test_parse_participant_id_scp_variants() -> None:
    assert parse_participant_id("SCP7_condition_Results.xlsx") == "P7"
    assert parse_participant_id("SCP07_condition_Results.xlsx") == "P7"


def test_parse_participant_id_p_variants() -> None:
    assert parse_participant_id("P1_Angry Neutral_Results.xlsx") == "P1"
    assert parse_participant_id("P11_Angry Neutral_Results.xlsx") == "P11"


def test_parse_participant_id_detects_with_underscores() -> None:
    assert parse_participant_id("P1_Angry_Neutral_Results") == "P1"
    assert parse_participant_id("p001_Happy_Neutral_Results") == "P1"


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


def test_missingness_across_conditions_keeps_union_of_participants(tmp_path: Path) -> None:
    excel_root = tmp_path / "1 - Excel Data Files"
    cond_a = excel_root / "AngryNeutral"
    cond_b = excel_root / "HappyNeutral"
    cond_a.mkdir(parents=True)
    cond_b.mkdir(parents=True)
    (cond_a / "P1_Angry Neutral_Results.xlsx").write_text("data")
    (cond_a / "P11_Angry Neutral_Results.xlsx").write_text("data")
    (cond_b / "P11_Happy Neutral_Results.xlsx").write_text("data")

    conditions = discover_conditions(excel_root)
    participants = {
        pid
        for condition in conditions
        for file in condition.files
        for pid in [parse_participant_id(file.stem)]
        if pid is not None
    }

    assert participants == {"P1", "P11"}


def test_topomap_wrapper_saves_svg(tmp_path: Path) -> None:
    import pytest

    np = pytest.importorskip("numpy")
    mne = pytest.importorskip("mne")
    matplotlib = pytest.importorskip("matplotlib")

    matplotlib.use("Agg", force=True)
    import matplotlib.pyplot as plt

    montage = mne.channels.make_standard_montage("biosemi64")
    electrodes = montage.ch_names
    z_threshold = 1.64
    z_values = np.full(len(electrodes), z_threshold)
    z_values[0] = z_threshold + 0.9
    z_values[10] = z_threshold + 0.4
    pos = np.array([montage.get_positions()["ch_pos"][name] for name in electrodes])

    fig, ax = plt.subplots(figsize=(2.4, 2.2))
    _plot_topomap_compat(
        z_values,
        pos,
        axes=ax,
        vmin=z_threshold,
        vmax=float(z_values.max()),
        contours=0,
        cmap="RdBu_r",
    )
    output = tmp_path / "compat_topomap.svg"
    fig.savefig(output, format="svg")
    plt.close(fig)

    assert output.exists()
    assert output.stat().st_size > 100
