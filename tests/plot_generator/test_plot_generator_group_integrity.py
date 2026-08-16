from __future__ import annotations

import os
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Plot_Generator import data_collection
from Tools.Plot_Generator.source_identity import sha256_file
from Tools.Plot_Generator.worker import _Worker


def _worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    **kwargs,
) -> _Worker:
    monkeypatch.setattr(
        _Worker,
        "_read_analysis_float",
        lambda self, option, fallback: fallback,
    )
    return _Worker(
        str(tmp_path),
        "Faces",
        {"Posterior": ["Oz", "O1"]},
        "Posterior",
        "Faces",
        "Frequency (Hz)",
        "SNR",
        0.0,
        3.0,
        0.0,
        10.0,
        str(tmp_path / "plots"),
        spectral_qc_enabled=False,
        **kwargs,
    )


def test_nonfinite_values_are_missing_from_means_and_exported_counts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    subject_data = {
        "P01": {"Posterior": [1.0, float("inf"), float("nan")]},
        "P02": {"Posterior": [3.0, 5.0, float("-inf")]},
        "P03": {"Posterior": [float("inf"), float("-inf"), float("nan")]},
    }

    averaged = worker._aggregate_roi_data(subject_data)
    worker._prepare_single_source_curves(
        frequencies_hz=[1.0, 2.0, 3.0],
        condition="Faces",
        subject_data=subject_data,
        plotted_roi_data=averaged,
    )
    curve = worker._pending_source_curves["Posterior"][0]

    assert averaged["Posterior"][:2] == pytest.approx([2.0, 5.0])
    assert np.isnan(averaged["Posterior"][2])
    assert curve.plotted_values == (2.0, 5.0, None)
    assert curve.participant_n_by_frequency == (2, 1, 0)
    assert curve.participant_n_roi == 2
    assert curve.participant_ids == ("P01", "P02")


def test_electrode_roi_mean_ignores_positive_and_negative_infinity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    condition_dir = tmp_path / "Faces"
    condition_dir.mkdir()
    workbook = condition_dir / "P01_Faces_Results.xlsx"
    workbook.write_bytes(b"not read")
    frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "O1"],
            "1.0_Hz": [2.0, 4.0],
            "2.0_Hz": [float("inf"), 6.0],
            "3.0_Hz": [float("-inf"), float("inf")],
        }
    )
    monkeypatch.setattr(worker, "_load_dataset_index", lambda: None)
    monkeypatch.setattr(
        worker,
        "_read_full_snr_direct",
        lambda _path, **_kwargs: (
            frame,
            [1.0, 2.0, 3.0],
            ["1.0_Hz", "2.0_Hz", "3.0_Hz"],
        ),
    )
    monkeypatch.setattr(
        data_collection,
        "active_frequency_domain_exclusions",
        lambda _root: SimpleNamespace(
            excluded_participants=frozenset({"P08", "P09", "P10"}),
            auto_excluded_participants=frozenset({"p10", "P09"}),
            manual_excluded_participants=frozenset({"p08"}),
            auto_excluded_electrodes_by_participant={
                "p07": frozenset({"cz"}),
                "P02": frozenset({"Oz", "o1"}),
            },
            downstream_outputs_stale=True,
        ),
    )

    frequencies, subject_data = worker._collect_data(
        "Faces",
        excel_files=[workbook],
    )

    values = subject_data["P01"]["Posterior"]
    assert frequencies == [1.0, 2.0, 3.0]
    assert values[:2] == pytest.approx([3.0, 6.0])
    assert np.isnan(values[2])
    disposition = worker._input_workbook_rows[workbook.resolve()]
    assert disposition["_read_sha256"] == sha256_file(workbook)
    assert disposition["_read_size_bytes"] == workbook.stat().st_size
def test_all_nonfinite_roi_values_are_excluded_from_the_plotted_cohort(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    condition_dir = tmp_path / "Faces"
    condition_dir.mkdir()
    workbook = condition_dir / "P01_Faces_Results.xlsx"
    workbook.write_bytes(b"not read")
    frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "O1"],
            "1.0_Hz": [float("inf"), float("nan")],
            "2.0_Hz": [float("-inf"), float("nan")],
        }
    )
    monkeypatch.setattr(worker, "_load_dataset_index", lambda: None)
    monkeypatch.setattr(
        worker,
        "_read_full_snr_direct",
        lambda _path, **_kwargs: (
            frame,
            [1.0, 2.0],
            ["1.0_Hz", "2.0_Hz"],
        ),
    )
    monkeypatch.setattr(
        data_collection,
        "active_frequency_domain_exclusions",
        lambda _root: SimpleNamespace(
            excluded_participants=(),
            auto_excluded_electrodes_by_participant={},
        ),
    )

    frequencies, subject_data = worker._collect_data(
        "Faces",
        excel_files=[workbook],
    )

    assert frequencies == []
    assert subject_data == {}
    disposition = worker._input_workbook_rows[workbook.resolve()]
    assert disposition["status"] == "excluded"
    assert disposition["reason"] == "no usable selected-ROI data"


def test_workbook_mutated_during_read_is_rejected_before_contributing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    condition_dir = tmp_path / "Faces"
    condition_dir.mkdir()
    workbook = condition_dir / "P01_Faces_Results.xlsx"
    workbook.write_bytes(b"A" * 40)
    frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "O1"],
            "1.0_Hz": [2.0, 4.0],
            "2.0_Hz": [3.0, 5.0],
        }
    )

    def _read_and_mutate(path: Path, **_kwargs):
        read_stat = path.stat()
        path.write_bytes(b"B" * 40)
        os.utime(
            path,
            ns=(read_stat.st_atime_ns, read_stat.st_mtime_ns),
        )
        return frame, [1.0, 2.0], ["1.0_Hz", "2.0_Hz"]

    monkeypatch.setattr(worker, "_load_dataset_index", lambda: None)
    monkeypatch.setattr(worker, "_read_full_snr_direct", _read_and_mutate)
    monkeypatch.setattr(
        data_collection,
        "active_frequency_domain_exclusions",
        lambda _root: SimpleNamespace(
            excluded_participants=(),
            auto_excluded_electrodes_by_participant={},
        ),
    )

    with pytest.raises(RuntimeError, match="changed while SNR data were being read"):
        worker._collect_data("Faces", excel_files=[workbook])

    disposition = worker._input_workbook_rows[workbook.resolve()]
    assert disposition["status"] == "failed"
    assert disposition["reason"] == (
        "source workbook changed during read-time fingerprinting"
    )
    assert "_read_sha256" not in disposition


def test_first_usable_workbook_establishes_the_frequency_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    condition_dir = tmp_path / "Faces"
    condition_dir.mkdir()
    missing_workbook = condition_dir / "P01_Faces_Results.xlsx"
    usable_workbook = condition_dir / "P02_Faces_Results.xlsx"
    missing_workbook.write_bytes(b"not read")
    usable_workbook.write_bytes(b"not read")
    missing_frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "O1"],
            "1.0_Hz": [float("inf"), float("nan")],
            "2.0_Hz": [float("-inf"), float("nan")],
        }
    )
    usable_frame = pd.DataFrame(
        {
            "Electrode": ["Oz", "O1"],
            "1.0_Hz": [2.0, 4.0],
            "3.0_Hz": [6.0, 8.0],
        }
    )
    monkeypatch.setattr(worker, "_load_dataset_index", lambda: None)

    def _read(path: Path, **_kwargs):
        if path == missing_workbook:
            return missing_frame, [1.0, 2.0], ["1.0_Hz", "2.0_Hz"]
        return usable_frame, [1.0, 3.0], ["1.0_Hz", "3.0_Hz"]

    monkeypatch.setattr(worker, "_read_full_snr_direct", _read)
    monkeypatch.setattr(
        data_collection,
        "active_frequency_domain_exclusions",
        lambda _root: SimpleNamespace(
            excluded_participants=(),
            auto_excluded_electrodes_by_participant={},
        ),
    )

    frequencies, subject_data = worker._collect_data(
        "Faces",
        excel_files=[missing_workbook, usable_workbook],
    )

    assert frequencies == [1.0, 3.0]
    assert subject_data == {"P02": {"Posterior": [3.0, 7.0]}}
    assert worker.failed_items == []
    assert worker._input_workbook_rows[missing_workbook.resolve()]["reason"] == (
        "no usable selected-ROI data"
    )
    assert worker._input_workbook_rows[usable_workbook.resolve()]["status"] == (
        "included"
    )


def test_condition_overlay_keeps_shared_rois_and_reports_missing_pairs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch, condition_b="Objects", overlay=True)
    messages: list[str] = []
    monkeypatch.setattr(worker, "_emit", lambda message, *_args: messages.append(message))

    matched_a, matched_b = worker._matched_overlay_roi_data(
        {"Posterior": [2.0], "Central": [3.0]},
        {"Posterior": [4.0]},
    )

    assert matched_a == {"Posterior": [2.0]}
    assert matched_b == {"Posterior": [4.0]}
    assert worker.warning_items == [
        {
            "code": "overlay_roi_unavailable",
            "item": "Objects:Central",
            "message": (
                "Condition overlay omitted ROI 'Central' because 'Objects' "
                "has no usable participant data."
            ),
        }
    ]
    assert messages == [f"Warning: {worker.warning_items[0]['message']}"]


def test_dataset_index_diagnostics_are_exportable_run_warnings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    diagnostic = SimpleNamespace(
        code="duplicate_workbook",
        message="P01 has two candidate workbooks; the preferred record was used.",
        paths=(),
    )
    index = SimpleNamespace(
        diagnostics=(diagnostic,),
        workbooks=(),
        manifest=None,
        ordered_groups=(),
        scan_root=tmp_path,
        project_root=tmp_path,
    )
    monkeypatch.setattr(
        data_collection,
        "load_project_dataset_index",
        lambda _source: index,
    )
    monkeypatch.setattr(worker, "_configure_analysis_context", lambda _index: None)
    monkeypatch.setattr(worker, "_emit", lambda *_args: None)

    assert worker._load_dataset_index() is index
    assert worker.warning_items == [
        {
            "code": "dataset_index_duplicate_workbook",
            "item": str(tmp_path),
            "message": diagnostic.message,
        }
    ]


def test_dataset_index_exclusions_are_manifest_dispositions_without_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    excluded = tmp_path / "Faces" / "P01_Faces_Results.xlsx"
    index = SimpleNamespace(
        diagnostics=(),
        workbooks=(),
        excluded_workbooks=(
            SimpleNamespace(
                path=excluded,
                participant_id="P01",
                condition="Faces",
            ),
        ),
        manifest=None,
        ordered_groups=(),
        scan_root=tmp_path,
        project_root=tmp_path,
    )
    monkeypatch.setattr(
        data_collection,
        "load_project_dataset_index",
        lambda _source: index,
    )
    monkeypatch.setattr(worker, "_configure_analysis_context", lambda _index: None)

    assert worker._load_dataset_index() is index

    disposition = worker._input_workbook_rows[excluded.resolve()]
    assert disposition == {
        "absolute_path": str(excluded.resolve()),
        "path": "Faces/P01_Faces_Results.xlsx",
        "condition": "Faces",
        "status": "excluded",
        "participant_id": "P01",
        "reason": "project participant-condition exclusion",
    }
    assert not excluded.exists()


def test_worker_refuses_implicit_pooled_multigroup_plot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(
        tmp_path,
        monkeypatch,
        subject_groups={"P01": "Control", "P02": "Patient"},
        multi_group_mode=True,
    )
    collected = False

    def _unexpected_collect(_condition: str):
        nonlocal collected
        collected = True
        return [1.0], {"P01": {"Posterior": [2.0]}}

    monkeypatch.setattr(worker, "_collect_data", _unexpected_collect)
    messages: list[str] = []
    monkeypatch.setattr(worker, "_emit", lambda message, *_args: messages.append(message))

    worker._run()

    assert not collected
    assert worker.failed_items == [
        {
            "item": "Faces",
            "error": (
                "Canonical multi-group projects require group-overlay plotting "
                "with at least one selected project group."
            ),
        }
    ]
    assert messages == [worker.failed_items[0]["error"]]


def test_dataset_index_refuses_pooled_mode_before_analysis_or_workbook_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    index = SimpleNamespace(
        diagnostics=(),
        workbooks=(),
        manifest={"groups": {"control": {}, "patient": {}}},
        ordered_groups=(SimpleNamespace(label="Control"), SimpleNamespace(label="Patient")),
        participant_group_label_map=lambda **_kwargs: {
            "P01": "Control",
            "P02": "Patient",
        },
    )
    monkeypatch.setattr(
        data_collection,
        "load_project_dataset_index",
        lambda _source: index,
    )
    configured = False

    def _unexpected_configure(_index) -> None:
        nonlocal configured
        configured = True

    monkeypatch.setattr(worker, "_configure_analysis_context", _unexpected_configure)

    with pytest.raises(
        RuntimeError,
        match="require group-overlay plotting",
    ):
        worker._load_dataset_index()

    assert not configured
    assert not worker._dataset_index_loaded


def test_unselected_group_is_filtered_before_read_and_logged_as_information(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(
        tmp_path,
        monkeypatch,
        subject_groups={"P01": "Control", "P02": "Patient"},
        selected_groups=["Control"],
        enable_group_overlay=True,
        multi_group_mode=True,
    )
    condition_dir = tmp_path / "Faces"
    condition_dir.mkdir()
    selected = condition_dir / "P01_Faces_Results.xlsx"
    unselected = condition_dir / "P02_Faces_Results.xlsx"
    selected.write_bytes(b"not read")
    unselected.write_bytes(b"must not be read")
    frame = pd.DataFrame(
        {"Electrode": ["Oz"], "1.0_Hz": [2.0], "2.0_Hz": [3.0]}
    )
    read_paths: list[Path] = []

    def _read(path: Path, **_kwargs):
        read_paths.append(path)
        return frame, [1.0, 2.0], ["1.0_Hz", "2.0_Hz"]

    monkeypatch.setattr(worker, "_load_dataset_index", lambda: None)
    monkeypatch.setattr(worker, "_read_full_snr_direct", _read)
    monkeypatch.setattr(
        data_collection,
        "active_frequency_domain_exclusions",
        lambda _root: SimpleNamespace(
            excluded_participants=(),
            auto_excluded_electrodes_by_participant={},
        ),
    )
    messages: list[str] = []
    monkeypatch.setattr(worker, "_emit", lambda message, *_args: messages.append(message))

    frequencies, subject_data = worker._collect_data(
        "Faces",
        excel_files=[unselected, selected],
    )
    curves = worker._build_group_curves(subject_data)

    assert frequencies == [1.0, 2.0]
    assert read_paths == [selected]
    assert curves == {"Control": {"Posterior": [2.0, 3.0]}}
    disposition = worker._input_workbook_rows[unselected.resolve()]
    assert disposition["status"] == "excluded"
    assert disposition["reason"] == "group 'Patient' was not selected"
    assert not any(item["code"] == "unselected_group" for item in worker.warning_items)
    assert any(message.startswith("Info: The following Excel files") for message in messages)


def test_managed_provenance_filters_and_records_intentionally_inactive_workbooks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    worker = _worker(tmp_path, monkeypatch)
    active = tmp_path / "Faces" / "P01_Faces_Results.xlsx"
    inactive = tmp_path / "Faces" / "P02_Faces_Results.xlsx"
    active.parent.mkdir()
    active.write_bytes(b"active")
    inactive.write_bytes(b"intentionally excluded")
    worker._provenance_allowed_paths = frozenset({active.resolve()})
    worker._workbook_records_by_path = {
        active.resolve(): SimpleNamespace(
            participant_id="P01",
            condition="Faces",
        ),
        inactive.resolve(): SimpleNamespace(
            participant_id="P02",
            condition="Faces",
        ),
    }
    messages: list[str] = []
    monkeypatch.setattr(worker, "_emit", lambda message, *_args: messages.append(message))

    selected = worker._restrict_to_provenance_workbooks(
        [active, inactive],
        condition="Faces",
    )

    assert selected == [active]
    disposition = worker._input_workbook_rows[inactive.resolve()]
    assert disposition["participant_id"] == "P02"
    assert disposition["condition"] == "Faces"
    assert disposition["status"] == "excluded"
    assert disposition["reason"] == (
        "not in the current processing provenance active cohort"
    )
    assert messages == [
        "Info: Excluded workbook(s) outside the current active processing "
        "cohort: P02_Faces_Results.xlsx"
    ]
