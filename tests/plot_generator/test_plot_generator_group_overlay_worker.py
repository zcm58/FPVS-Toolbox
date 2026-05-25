from __future__ import annotations

from pathlib import Path

import pandas as pd

from Tools.Plot_Generator.worker import _Worker


def _write_full_snr(path: Path, values: list[float]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(
        {
            "Electrode": ["Cz"],
            "1.0_Hz": [values[0]],
            "2.0_Hz": [values[1]],
        }
    )
    with pd.ExcelWriter(path) as writer:
        df.to_excel(writer, sheet_name="FullSNR", index=False)


def test_group_overlay_matches_project_participant_ids_from_excel_names(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    excel_root = tmp_path / "1 - Excel Data Files"
    condition = "Angry"
    _write_full_snr(
        excel_root
        / condition
        / "After Creatine"
        / "E2P2final_Angry_Results.xlsx",
        [2.0, 4.0],
    )
    _write_full_snr(
        excel_root
        / condition
        / "Before Creatine"
        / "E2P1initial_Angry_Results.xlsx",
        [1.0, 3.0],
    )

    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        "Angry",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        5.0,
        str(tmp_path / "plots"),
        subject_groups={
            "E2P2FINAL": "After Creatine",
            "E2P1INITIAL": "Before Creatine",
        },
        selected_groups=["After Creatine", "Before Creatine"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    captured: dict[str, object] = {}

    def fake_plot(freqs, roi_data, group_curves=None, scalp_inputs=None):  # noqa: ARG001
        captured["roi_data"] = roi_data
        captured["group_curves"] = group_curves or {}

    monkeypatch.setattr(worker, "_plot", fake_plot)

    worker.run()

    assert captured["roi_data"] == {"Central": [1.5, 3.5]}
    assert captured["group_curves"] == {
        "After Creatine": {"Central": [2.0, 4.0]},
        "Before Creatine": {"Central": [1.0, 3.0]},
    }
    assert worker.failed_items == []


def test_group_overlay_renderer_writes_overlay_plot(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    out_dir = tmp_path / "plots"
    out_dir.mkdir()
    worker = _Worker(
        str(tmp_path),
        "Angry",
        {"Central": ["Cz"]},
        "Central",
        "Angry",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        5.0,
        str(out_dir),
        stem_color="#005500",
        stem_color_b="#ff00ff",
        selected_groups=["After Creatine", "Before Creatine"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )

    worker._plot(
        [1.0, 2.0],
        {"Central": [1.5, 2.5]},
        {
            "After Creatine": {"Central": [2.0, 3.0]},
            "Before Creatine": {"Central": [1.0, 2.0]},
        },
    )

    assert (out_dir / "Angry_Central_SNR.png").is_file()
    assert (out_dir / "Angry_Central_SNR.svg").is_file()
