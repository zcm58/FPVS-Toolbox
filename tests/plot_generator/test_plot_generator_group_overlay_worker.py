from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from Tools.Plot_Generator import data_collection
from Tools.Plot_Generator.generation_outcome import (
    format_completion_summary,
    format_no_plots_message,
    normalize_worker_outcome,
)
from Tools.Plot_Generator.rendering import _group_color, _group_marker
from Tools.Plot_Generator.worker import _Worker
from Tools.Stats.analysis.stats_analysis import ALL_ROIS_OPTION


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


def test_group_overlay_completion_outcome_helpers() -> None:
    outcome = normalize_worker_outcome(
        {
            "generated_paths": ["plot.png", "", None],
            "warning_items": [
                {
                    "code": "selected_group_no_data",
                    "item": "Patient",
                    "message": "No usable data.",
                },
                "invalid",
            ],
            "failed_items": [{"item": "P02.xlsx", "error": "Grid mismatch"}],
        }
    )

    assert outcome.generated_paths == ("plot.png",)
    assert outcome.warning_items[0]["code"] == "selected_group_no_data"
    assert outcome.failed_items == (
        {"item": "P02.xlsx", "error": "Grid mismatch"},
    )
    assert format_completion_summary(
        generated_count=1,
        warning_count=1,
        failed_count=2,
    ) == "Generated 1 figure file; 1 warning; 2 failed items."
    assert format_no_plots_message(warning_count=2).endswith(
        "2 warnings were reported."
    )


def test_worker_rejects_manifest_without_participant_group_assignments(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    index = SimpleNamespace(
        diagnostics=(),
        workbooks=(),
        manifest={},
        ordered_groups=(),
        participant_group_label_map=lambda **_kwargs: {},
    )
    monkeypatch.setattr(
        data_collection,
        "load_project_dataset_index",
        lambda _source: index,
    )
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
        str(tmp_path),
        subject_groups={"P01": "Control"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )

    with pytest.raises(
        RuntimeError,
        match="No current canonical participant group assignments",
    ):
        worker._load_dataset_index()


def test_group_overlay_matches_project_participant_ids_from_excel_names(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    after_raw = project_root / "Raw" / "After"
    before_raw = project_root / "Raw" / "Before"
    after_raw.mkdir(parents=True)
    before_raw.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "after": {
                        "label": "After Creatine",
                        "folder_name": "After Creatine",
                        "raw_input_folder": str(after_raw),
                    },
                    "before": {
                        "label": "Before Creatine",
                        "folder_name": "Before Creatine",
                        "raw_input_folder": str(before_raw),
                    },
                },
                "participants": {
                    "e2p2final": {"group_id": "after"},
                    "E2P1INITIAL": {"group_id": "before"},
                },
            }
        ),
        encoding="utf-8",
    )
    excel_root = project_root / "1 - Excel Data Files"
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
            "E2P2FINAL": "Before Creatine",
            "E2P1INITIAL": "After Creatine",
        },
        selected_groups=["After Creatine", "Before Creatine"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    captured: dict[str, object] = {}

    def fake_plot(freqs, roi_data, group_curves=None):
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


def test_worker_uses_shared_index_preference_for_grouped_workbook(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    raw_root = project_root / "Raw" / "Control"
    raw_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "control": {
                        "label": "Control",
                        "folder_name": "Control",
                        "raw_input_folder": str(raw_root),
                    }
                },
                "participants": {"P01": {"group_id": "control"}},
            }
        ),
        encoding="utf-8",
    )
    excel_root = project_root / "1 - Excel Data Files"
    condition = "Faces"
    _write_full_snr(
        excel_root / condition / "P01_Faces_Results.xlsx",
        [90.0, 90.0],
    )
    _write_full_snr(
        excel_root / condition / "Control" / "P01_Faces_Results.xlsx",
        [2.0, 4.0],
    )
    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        condition,
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        100.0,
        str(tmp_path / "plots"),
    )
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        worker,
        "_plot",
        lambda freqs, roi_data, group_curves=None: captured.update(
            {"freqs": freqs, "roi_data": roi_data}
        ),
    )

    worker.run()

    assert captured == {
        "freqs": [1.0, 2.0],
        "roi_data": {"Central": [2.0, 4.0]},
    }
    assert worker.failed_items == []


def test_worker_rejects_stale_selected_group_label(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    project_root = tmp_path / "Project"
    control_raw = project_root / "Raw" / "Control"
    patient_raw = project_root / "Raw" / "Patient"
    control_raw.mkdir(parents=True)
    patient_raw.mkdir(parents=True)
    manifest_path = project_root / "project.json"
    manifest = {
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": str(control_raw),
            },
            "patient": {
                "label": "Patient",
                "folder_name": "Patient",
                "raw_input_folder": str(patient_raw),
            },
        },
        "participants": {
            "P01": {"group_id": "control"},
            "P02": {"group_id": "patient"},
        },
    }
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    excel_root = project_root / "1 - Excel Data Files"
    condition = "Faces"
    _write_full_snr(
        excel_root / condition / "Control" / "P01_Faces_Results.xlsx",
        [2.0, 4.0],
    )
    worker = _Worker(
        str(excel_root),
        condition,
        {"Central": ["Cz"]},
        "Central",
        condition,
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        10.0,
        str(tmp_path / "plots"),
        subject_groups={"P01": "Control", "P02": "Patient"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
        project_root=str(project_root),
    )
    manifest["groups"]["control"]["label"] = "Comparison"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    plotted = False

    def _capture_plot(*args, **kwargs) -> None:
        nonlocal plotted
        plotted = True

    monkeypatch.setattr(worker, "_plot", _capture_plot)

    worker.run()

    assert plotted is False
    assert len(worker.failed_items) == 1
    assert "Selected project group label(s) changed" in worker.failed_items[0]["error"]


def test_group_overlay_renderer_writes_all_roi_files_with_distinct_identity(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    out_dir = tmp_path / "plots"
    out_dir.mkdir()
    normal_png = out_dir / "Angry - Central.png"
    normal_pdf = out_dir / "Angry - Central.pdf"
    normal_png.write_bytes(b"existing normal png")
    normal_pdf.write_bytes(b"existing normal pdf")
    worker = _Worker(
        str(tmp_path),
        "Angry",
        {"Central": ["Cz"], "Occipital": ["Oz"]},
        ALL_ROIS_OPTION,
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
        selected_groups=[
            "After Creatine",
            "Before Creatine",
            "Placebo",
            "Untreated",
        ],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    worker.group_roi_sample_sizes = {
        "After Creatine": {"Central": 8, "Occipital": 7},
        "Before Creatine": {"Central": 9, "Occipital": 9},
        "Placebo": {"Central": 6, "Occipital": 5},
        "Untreated": {"Central": 4, "Occipital": 4},
    }
    legend_labels: dict[str, list[str]] = {}

    def _save_figure(figure, path, *_args, **_kwargs) -> None:
        output_path = Path(path)
        output_path.write_bytes(b"figure")
        if output_path.suffix == ".png":
            legend_labels[output_path.name] = (
                figure.axes[0].get_legend_handles_labels()[1]
            )

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", _save_figure)

    worker._plot(
        [1.0, 2.0],
        {
            "Central": [1.5, 2.5],
            "Occipital": [1.4, 2.4],
        },
        {
            "After Creatine": {
                "Central": [2.0, 3.0],
                "Occipital": [2.1, 3.1],
            },
            "Before Creatine": {
                "Central": [1.0, 2.0],
                "Occipital": [1.1, 2.1],
            },
            "Placebo": {
                "Central": [1.5, 2.5],
                "Occipital": [1.6, 2.6],
            },
            "Untreated": {
                "Central": [1.2, 2.2],
                "Occipital": [1.3, 2.3],
            },
        },
    )

    expected_files = {
        "Angry - Central_group_overlay.png",
        "Angry - Central_group_overlay.pdf",
        "Angry - Occipital_group_overlay.png",
        "Angry - Occipital_group_overlay.pdf",
        "Angry - Central.png",
        "Angry - Central.pdf",
    }
    assert {path.name for path in out_dir.iterdir()} == expected_files
    assert normal_png.read_bytes() == b"existing normal png"
    assert normal_pdf.read_bytes() == b"existing normal pdf"
    assert legend_labels["Angry - Central_group_overlay.png"][:4] == [
        "After Creatine (n=8)",
        "Before Creatine (n=9)",
        "Placebo (n=6)",
        "Untreated (n=4)",
    ]
    assert legend_labels["Angry - Occipital_group_overlay.png"][:4] == [
        "After Creatine (n=7)",
        "Before Creatine (n=9)",
        "Placebo (n=5)",
        "Untreated (n=4)",
    ]
    assert [_group_marker(index) for index in range(5)] == [
        "o",
        "^",
        "s",
        "D",
        "P",
    ]
    palette = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
    ]
    colors = [
        _group_color(
            index,
            color_a="#1f77b4",
            color_b="#ff7f0e",
            palette=palette,
        )
        for index in range(5)
    ]
    assert len(set(colors)) == 5


def test_group_overlay_records_selected_groups_without_data(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
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
        str(tmp_path),
        subject_groups={"P01": "Control", "P02": "Patient"},
        selected_groups=["Control", "Patient"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    messages: list[str] = []
    monkeypatch.setattr(
        worker,
        "_emit",
        lambda message, *_args: messages.append(message),
    )

    curves = worker._build_group_curves(
        {
            "P01": {"Central": [2.0, 3.0]},
            "P02": {"Central": [float("nan"), float("nan")]},
        }
    )

    assert curves == {"Control": {"Central": [2.0, 3.0]}}
    assert worker.group_roi_sample_sizes == {
        "Control": {"Central": 1},
        "Patient": {"Central": 0},
    }
    assert worker.warning_items == [
        {
            "code": "selected_group_no_data",
            "item": "Patient",
            "message": (
                "Selected group 'Patient' has no usable participant SNR data "
                "for: Central. It will be omitted from those group-overlay plots."
            ),
        }
    ]
    assert "Group sample sizes for ROI Central: Control n=1" in messages


def test_group_overlay_skips_roi_when_every_selected_group_lacks_data(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    worker = _Worker(
        str(tmp_path),
        "Angry",
        {"Central": ["Cz"], "Occipital": ["Oz"]},
        ALL_ROIS_OPTION,
        "Angry",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        5.0,
        str(tmp_path),
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    worker.group_roi_sample_sizes = {
        "Control": {"Central": 1, "Occipital": 0}
    }
    saved_paths: list[Path] = []
    messages: list[str] = []

    def _save_figure(_figure, path, *_args, **_kwargs) -> None:
        saved_paths.append(Path(path))

    monkeypatch.setattr("matplotlib.figure.Figure.savefig", _save_figure)
    monkeypatch.setattr(
        worker,
        "_emit",
        lambda message, *_args: messages.append(message),
    )

    worker._plot(
        [1.0, 2.0],
        {
            "Central": [1.5, 2.5],
            "Occipital": [1.4, 2.4],
        },
        {"Control": {"Central": [2.0, 3.0]}},
    )

    assert [path.name for path in saved_paths] == [
        "Angry - Central_group_overlay.png",
        "Angry - Central_group_overlay.pdf",
    ]
    assert (
        "No selected group has usable data for ROI Occipital; "
        "skipping this group-overlay figure."
    ) in messages


def test_group_overlay_with_no_group_data_does_not_render_pooled_average(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
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
        str(tmp_path),
        subject_groups={"P01": "Patient"},
        selected_groups=["Patient"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    monkeypatch.setattr(
        worker,
        "_collect_data",
        lambda _condition: (
            [1.0, 2.0],
            {"P01": {"Central": [float("nan"), float("nan")]}},
        ),
    )
    monkeypatch.setattr(
        worker,
        "_plot",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("pooled average must not be rendered")
        ),
    )

    worker._run()

    assert worker.generated_paths == []
    assert worker.warning_items[0]["code"] == "selected_group_no_data"


def test_worker_finished_payload_exposes_group_overlay_warnings(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
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
        str(tmp_path),
    )
    payloads: list[dict[str, object]] = []
    worker.finished.connect(payloads.append)
    worker._record_warning(
        code="selected_group_no_data",
        item="Patient",
        message="Patient has no usable data.",
    )
    monkeypatch.setattr(worker, "_run", lambda: None)

    worker.run()

    assert payloads[-1]["warning_items"] == [
        {
            "code": "selected_group_no_data",
            "item": "Patient",
            "message": "Patient has no usable data.",
        }
    ]


def test_unassigned_workbooks_are_structured_completion_warnings(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
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
        str(tmp_path),
        subject_groups={"P01": "Control"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    messages: list[str] = []
    worker._unknown_subject_files = {
        "P99_Angry_Results.xlsx",
        "P98_Angry_Results.xlsx",
    }
    monkeypatch.setattr(
        worker,
        "_emit",
        lambda message, *_args: messages.append(message),
    )

    worker._warn_unknown_subjects()

    assert worker.warning_items == [
        {
            "code": "unassigned_participant",
            "item": (
                "P98_Angry_Results.xlsx, P99_Angry_Results.xlsx"
            ),
            "message": (
                "The following Excel files lack canonical group assignments "
                "and were excluded from group overlays: "
                "P98_Angry_Results.xlsx, P99_Angry_Results.xlsx"
            ),
        }
    ]
    assert messages[0].startswith("Warning: The following Excel files")


def test_unassigned_workbook_cannot_define_group_overlay_frequency_grid(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    condition = "Angry"
    condition_dir = tmp_path / condition
    known_path = condition_dir / "P01_Angry_Results.xlsx"
    unknown_path = condition_dir / "P99_Angry_Results.xlsx"
    _write_full_snr(known_path, [2.0, 4.0])
    with pd.ExcelWriter(unknown_path) as writer:
        pd.DataFrame(
            {
                "Electrode": ["Cz"],
                "1.0_Hz": [20.0],
                "3.0_Hz": [40.0],
            }
        ).to_excel(writer, sheet_name="FullSNR", index=False)
    worker = _Worker(
        str(tmp_path),
        condition,
        {"Central": ["Cz"]},
        "Central",
        condition,
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        50.0,
        str(tmp_path),
        subject_groups={"P01": "Control"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
        spectral_qc_enabled=False,
    )
    monkeypatch.setattr(worker, "_emit", lambda *_args: None)

    freqs, subject_data = worker._collect_data(
        condition,
        excel_files=[unknown_path, known_path],
    )
    curves = worker._build_group_curves(subject_data)

    assert freqs == [1.0, 2.0]
    assert curves == {"Control": {"Central": [2.0, 4.0]}}
    assert worker.failed_items == []
    assert any(
        warning["code"] == "unassigned_participant"
        for warning in worker.warning_items
    )
