from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.Free_Harmonic_Clustering import inputs
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    ProjectContrastRequest,
)


def _header(*, spacing_hz: float = 0.025, upper_hz: float = 3.75) -> list[str]:
    frequencies = np.arange(
        int(round(upper_hz / spacing_hz)) + 1,
        dtype=np.float64,
    ) * spacing_hz
    return ["Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies)]


def _write_project(
    root: Path,
    *,
    groups: dict[str, tuple[str, str]],
    participant_groups: dict[str, str],
    participant_conditions: dict[str, tuple[str, ...]],
    ledger_statuses: dict[str, str] | None = None,
    manual_excluded_participants: tuple[str, ...] = (),
    participant_condition_exclusions: dict[str, tuple[str, ...]] | None = None,
    frequency_excluded_participants: tuple[str, ...] = (),
    electrode_exclusions: tuple[tuple[str, str], ...] = (),
    frequency_outputs_stale: bool = False,
) -> tuple[Path, dict[tuple[str, str], Path]]:
    root.mkdir(parents=True)
    raw_root = root / "Raw"
    group_payload: dict[str, dict[str, str]] = {}
    for group_id, (label, folder_name) in groups.items():
        raw_folder = raw_root / folder_name
        raw_folder.mkdir(parents=True)
        group_payload[group_id] = {
            "label": label,
            "folder_name": folder_name,
            "raw_input_folder": str(raw_folder),
        }
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": group_payload,
        "participants": {
            participant: {"group_id": group_id}
            for participant, group_id in participant_groups.items()
        },
        "preprocessing": {
            "manual_excluded_participants": list(manual_excluded_participants),
            "manual_excluded_participant_conditions": {
                participant: list(conditions)
                for participant, conditions in (
                    participant_condition_exclusions or {}
                ).items()
            },
        },
        "tools": {
            "frequency_domain_qc": {
                "auto_participant_exclusions": [
                    {"participant_id": participant}
                    for participant in frequency_excluded_participants
                ],
                "manual_participant_exclusions": [],
                "auto_participant_electrode_exclusions": [
                    {"participant_id": participant, "electrode": electrode}
                    for participant, electrode in electrode_exclusions
                ],
                "downstream_outputs_stale": frequency_outputs_stale,
            }
        },
    }
    (root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )

    excel_root = root / "1 - Excel Data Files"
    paths: dict[tuple[str, str], Path] = {}
    for participant, conditions in participant_conditions.items():
        group_id = participant_groups[participant]
        folder_name = groups[group_id][1]
        for condition in conditions:
            parent = excel_root / condition / folder_name
            parent.mkdir(parents=True, exist_ok=True)
            path = parent / f"{participant}_{condition}_Results.xlsx"
            path.write_bytes(b"selected-reader-test-double")
            paths[(participant, condition)] = path

    ledger_directory = root / ".fpvs_processing"
    ledger_directory.mkdir()
    statuses = ledger_statuses or {
        participant: "completed" for participant in participant_groups
    }
    (ledger_directory / "processing_ledger.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    participant: {"status": status}
                    for participant, status in statuses.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return root, paths


def _install_reader_doubles(
    monkeypatch: pytest.MonkeyPatch,
    *,
    header_for_path: Callable[[Path], list[str]] | None = None,
    mutate_frame: Callable[[Path, pd.DataFrame], None] | None = None,
) -> tuple[list[Path], list[Path]]:
    header_calls: list[Path] = []
    amplitude_calls: list[Path] = []

    def read_header(path: Path) -> list[str]:
        header_calls.append(path)
        return (header_for_path or (lambda _path: _header()))(path)

    def read_selected(
        path: Path,
        required_columns: tuple[str, ...],
        timing_details: dict[str, float],
    ) -> pd.DataFrame:
        amplitude_calls.append(path)
        timing_details["xml_selected_rows"] = 0.001
        data: dict[str, object] = {
            "Electrode": list(DEFAULT_ELECTRODE_NAMES_64),
        }
        for column_number, column in enumerate(required_columns[1:]):
            frequency = float(column[:-3])
            value = 1.0 + (column_number % 7) * 0.05
            ratio = frequency / 1.2
            if abs(ratio - round(ratio)) <= 1e-7:
                value = 20.0
            data[column] = np.full(64, value, dtype=np.float64)
        frame = pd.DataFrame(data)
        if mutate_frame is not None:
            mutate_frame(path, frame)
        return frame

    monkeypatch.setattr(inputs, "_read_fullfft_header", read_header)
    monkeypatch.setattr(inputs, "_read_fullfft_selected_columns", read_selected)
    return header_calls, amplitude_calls


def _independent_project(
    tmp_path: Path,
    **kwargs: object,
) -> tuple[Path, dict[tuple[str, str], Path]]:
    participants = {
        "A1": "anxious",
        "A2": "anxious",
        "A3": "anxious",
        "N1": "non_anxious",
        "N2": "non_anxious",
        "N3": "non_anxious",
        "N4": "non_anxious",
    }
    defaults: dict[str, object] = {
        "ledger_statuses": {
            "A1": "completed",
            "A2": "completed",
            "A3": "completed",
            "N1": "completed",
            "N2": "completed",
            "N3": "completed",
            "N4": "excluded",
        },
        "manual_excluded_participants": ("A3",),
        "frequency_excluded_participants": ("N3",),
    }
    defaults.update(kwargs)
    return _write_project(
        tmp_path / "Project",
        groups={
            "anxious": ("Anxious", "Anxious"),
            "non_anxious": ("Non-Anxious", "Non-Anxious"),
        },
        participant_groups=participants,
        participant_conditions={participant: ("Faces",) for participant in participants},
        **defaults,
    )


def _independent_request(root: Path) -> ProjectContrastRequest:
    return ProjectContrastRequest(
        project_root=root,
        design=AnalysisDesign.INDEPENDENT_GROUPS,
        condition_a="Faces",
        group_ids=("anxious", "non_anxious"),
    )


def test_independent_project_cohort_honors_all_exclusions_and_reads_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    progress: list[tuple[int, int]] = []

    prepared = inputs.prepare_project_contrast(
        _independent_request(root),
        FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        progress_callback=lambda completed, total: progress.append((completed, total)),
    )

    assert prepared.participant_ids_a == ("A1", "A2")
    assert prepared.participant_ids_b == ("N1", "N2")
    assert prepared.arm_a_label == "Anxious"
    assert prepared.arm_b_label == "Non-Anxious"
    assert prepared.provenance.ledger_filter_applied is True
    assert prepared.provenance.completed_participants == (
        "A1",
        "A2",
        "A3",
        "N1",
        "N2",
        "N3",
    )
    assert prepared.provenance.ledger_excluded_participants == ("N4",)
    assert prepared.provenance.manual_excluded_participants == ("A3",)
    assert prepared.provenance.frequency_qc_excluded_participants == ("N3",)
    assert len(header_calls) == len(amplitude_calls) == 4
    assert len(set(amplitude_calls)) == 4
    assert prepared.provenance.workbook_count == 4
    assert prepared.provenance.reader_phase_seconds == (("xml_selected_rows", 0.004),)
    assert progress[-1] == (8, 8)
    assert prepared.snr_a.shape == prepared.values_a.shape == (2, 64, 3)
    assert prepared.snr_b.shape == prepared.values_b.shape == (2, 64, 3)
    assert prepared.values_a.flags.c_contiguous
    assert not prepared.values_a.flags.writeable
    assert np.sqrt(np.sum(prepared.values_a**2, axis=(1, 2))) == pytest.approx(
        np.ones(2)
    )
    assert all(
        not workbook.project_relative_path.startswith(("/", "\\"))
        for workbook in prepared.source_workbooks
    )


def test_paired_conditions_use_complete_intersection_in_identical_order(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _write_project(
        tmp_path / "Project",
        groups={"all": ("All Participants", "All")},
        participant_groups={"P1": "all", "P2": "all", "P3": "all"},
        participant_conditions={
            "P1": ("Angry", "Happy"),
            "P2": ("Angry", "Happy"),
            "P3": ("Angry",),
        },
    )
    _headers, amplitude_calls = _install_reader_doubles(monkeypatch)
    request = ProjectContrastRequest(
        project_root=root,
        design=AnalysisDesign.PAIRED_CONDITIONS,
        condition_a="Angry",
        condition_b="Happy",
        group_ids=("all",),
    )

    prepared = inputs.prepare_project_contrast(
        request,
        FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
    )

    assert prepared.participant_ids_a == prepared.participant_ids_b == ("P1", "P2")
    assert prepared.arm_a_label == "Angry"
    assert prepared.arm_b_label == "Happy"
    assert prepared.provenance.incomplete_pair_participants == ("P3",)
    assert len(amplitude_calls) == 4


def test_paired_conditions_allow_managed_project_without_group_metadata(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "Project"
    root.mkdir()
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {},
        "participants": {"P1": {}, "P2": {}},
        "preprocessing": {},
    }
    (root / "project.json").write_text(
        json.dumps(manifest),
        encoding="utf-8",
    )
    for condition in ("Angry", "Happy"):
        condition_root = root / "1 - Excel Data Files" / condition
        condition_root.mkdir(parents=True)
        for participant in ("P1", "P2"):
            (condition_root / f"{participant}_{condition}_Results.xlsx").write_bytes(
                b"selected-reader-test-double"
            )
    _headers, amplitude_calls = _install_reader_doubles(monkeypatch)

    prepared = inputs.prepare_project_contrast(
        ProjectContrastRequest(
            project_root=root,
            design=AnalysisDesign.PAIRED_CONDITIONS,
            condition_a="Angry",
            condition_b="Happy",
        ),
        FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
    )

    assert prepared.participant_ids_a == prepared.participant_ids_b == ("P1", "P2")
    assert len(amplitude_calls) == 4


def test_relevant_participant_condition_exclusions_are_preserved_in_provenance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _write_project(
        tmp_path / "Project",
        groups={"all": ("All Participants", "All")},
        participant_groups={"P1": "all", "P2": "all", "P3": "all"},
        participant_conditions={
            "P1": ("Angry", "Happy", "Unselected"),
            "P2": ("Angry", "Happy", "Unselected"),
            "P3": ("Angry", "Happy", "Unselected"),
        },
        participant_condition_exclusions={
            "P3": ("Happy", "Unselected"),
        },
    )
    _install_reader_doubles(monkeypatch)

    prepared = inputs.prepare_project_contrast(
        ProjectContrastRequest(
            project_root=root,
            design=AnalysisDesign.PAIRED_CONDITIONS,
            condition_a="Angry",
            condition_b="Happy",
        ),
        FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
    )

    exclusions = prepared.provenance.participant_condition_exclusions
    assert [
        (row.participant_id, row.condition, row.reason)
        for row in exclusions
    ] == [
        ("P3", "Happy", "Project participant-condition exclusion"),
    ]
    assert prepared.provenance.incomplete_pair_participants == ("P3",)


def test_included_frequency_qc_electrode_exclusion_fails_before_workbook_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(
        tmp_path,
        electrode_exclusions=(("A1", "Fp1"),),
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)

    with pytest.raises(FreeHarmonicInputError, match="active electrode exclusions"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


def test_independent_arm_with_fewer_than_two_participants_fails_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(
        tmp_path,
        frequency_excluded_participants=("N2", "N3"),
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)

    with pytest.raises(FreeHarmonicInputError, match="at least two participants"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


def test_paired_common_cohort_with_fewer_than_two_participants_fails_before_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _write_project(
        tmp_path / "Project",
        groups={"all": ("All Participants", "All")},
        participant_groups={"P1": "all", "P2": "all"},
        participant_conditions={
            "P1": ("Angry", "Happy"),
            "P2": ("Angry",),
        },
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    request = ProjectContrastRequest(
        project_root=root,
        design=AnalysisDesign.PAIRED_CONDITIONS,
        condition_a="Angry",
        condition_b="Happy",
    )

    with pytest.raises(FreeHarmonicInputError, match="at least two participants"):
        inputs.prepare_project_contrast(
            request,
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


def test_all_consumed_workbooks_require_one_common_fullfft_grid(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)

    def header_for_path(path: Path) -> list[str]:
        if path.name.startswith("N2_"):
            return _header(spacing_hz=0.02)
        return _header()

    _headers, amplitude_calls = _install_reader_doubles(
        monkeypatch,
        header_for_path=header_for_path,
    )

    with pytest.raises(FreeHarmonicInputError, match="one exact FullFFT grid"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert amplitude_calls == []


def test_biosemi64_order_is_strict(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)

    def reverse_channels(_path: Path, frame: pd.DataFrame) -> None:
        frame["Electrode"] = list(reversed(DEFAULT_ELECTRODE_NAMES_64))

    _install_reader_doubles(monkeypatch, mutate_frame=reverse_channels)

    with pytest.raises(FreeHarmonicInputError, match="canonical BioSemi64"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )


def test_nonfinite_selected_amplitude_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)

    def insert_nan(_path: Path, frame: pd.DataFrame) -> None:
        frame.iloc[0, 1] = np.nan

    _install_reader_doubles(monkeypatch, mutate_frame=insert_nan)

    with pytest.raises(FreeHarmonicInputError, match="non-finite"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )
