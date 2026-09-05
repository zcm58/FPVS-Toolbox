from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.processing.full_fft_provenance import (
    FullFftProvenanceMissingError,
)
from Main_App.processing.frequency_domain_qc import (
    FrequencyDomainCoverageDecisions,
)
from Tools.Free_Harmonic_Clustering import inputs
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicInputError,
    FreeHarmonicMethodSpec,
    ProjectContrastRequest,
    RecordingExclusionRequest,
    RepeatedSessionBatchRequest,
    RepeatedSessionContrastFamily,
    RepeatedSessionTensorSemantics,
)
from Tools.Free_Harmonic_Clustering.preparation import (
    build_available_frequency_window_plan,
)


def _header(*, spacing_hz: float = 0.025, upper_hz: float = 3.75) -> list[str]:
    frequencies = (
        np.arange(
            int(round(upper_hz / spacing_hz)) + 1,
            dtype=np.float64,
        )
        * spacing_hz
    )
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
        "participants": {participant: {"group_id": group_id} for participant, group_id in participant_groups.items()},
        "preprocessing": {
            "manual_excluded_participants": list(manual_excluded_participants),
            "manual_excluded_participant_conditions": {
                participant: list(conditions)
                for participant, conditions in (participant_condition_exclusions or {}).items()
            },
        },
        "tools": {
            "frequency_domain_qc": {
                "downstream_outputs_stale": False,
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
    statuses = ledger_statuses or {participant: "completed" for participant in participant_groups}
    (ledger_directory / "processing_ledger.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {participant: {"status": status} for participant, status in statuses.items()},
            }
        ),
        encoding="utf-8",
    )
    return root, paths


def _write_repeated_project(
    root: Path,
    *,
    participants_by_group: dict[str, tuple[str, ...]],
    conditions: tuple[str, ...],
    missing_workbooks: set[tuple[str, str, str]] | None = None,
    recording_condition_exclusions: dict[str, tuple[str, ...]] | None = None,
) -> Path:
    root.mkdir(parents=True)
    group_definitions = {
        "bc_group": ("BC Group", "BC Group"),
        "control_group": ("Control Group", "Control Group"),
    }
    session_definitions = {
        "follicular_phase": ("Follicular Phase", 2),
        "luteal_phase": ("Luteal Phase", 1),
    }
    groups: dict[str, dict[str, str]] = {}
    sources: dict[str, dict[str, str]] = {}
    participants: dict[str, dict[str, str]] = {}
    recordings: dict[str, dict[str, object]] = {}
    for group_id, (group_label, folder_name) in group_definitions.items():
        group_raw = root / "Raw" / folder_name
        group_raw.mkdir(parents=True)
        groups[group_id] = {
            "label": group_label,
            "folder_name": folder_name,
            "raw_input_folder": str(group_raw),
        }
        for session_id, (_session_label, visit_index) in session_definitions.items():
            source_id = f"{group_id}__{session_id}"
            source_root = group_raw / session_id
            source_root.mkdir()
            sources[source_id] = {
                "group_id": group_id,
                "session_id": session_id,
                "raw_input_folder": str(source_root),
            }
            for participant_id in participants_by_group[group_id]:
                participants[participant_id] = {"group_id": group_id}
                recording_id = f"{participant_id}__{session_id}"
                raw_file = source_root / f"{recording_id}.bdf"
                raw_file.write_bytes(b"bdf")
                recordings[recording_id] = {
                    "participant_id": participant_id,
                    "session_id": session_id,
                    "source_id": source_id,
                    "raw_file": str(raw_file),
                    "visit_index": visit_index,
                }
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": groups,
        "participants": participants,
        "sessions": {
            session_id: {"label": label, "visit_index": visit_index}
            for session_id, (label, visit_index) in session_definitions.items()
        },
        "recording_sources": sources,
        "recordings": recordings,
        "preprocessing": {
            "manual_excluded_recording_conditions": {
                recording_id: list(values) for recording_id, values in (recording_condition_exclusions or {}).items()
            }
        },
        "tools": {"frequency_domain_qc": {"downstream_outputs_stale": False}},
    }
    (root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    missing = missing_workbooks or set()
    for group_id, participant_ids in participants_by_group.items():
        folder_name = group_definitions[group_id][1]
        for participant_id in participant_ids:
            for session_id in session_definitions:
                recording_id = f"{participant_id}__{session_id}"
                for condition in conditions:
                    if (participant_id, session_id, condition) in missing:
                        continue
                    parent = root / "1 - Excel Data Files" / condition / folder_name
                    parent.mkdir(parents=True, exist_ok=True)
                    (parent / f"{recording_id}_{condition}_Results.xlsx").write_bytes(b"selected-reader-test-double")
    ledger_root = root / ".fpvs_processing"
    ledger_root.mkdir()
    (ledger_root / "processing_ledger.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "entries": {
                    recording_id: {
                        "status": "completed",
                        "participant_id": info["participant_id"],
                        "session_id": info["session_id"],
                    }
                    for recording_id, info in recordings.items()
                },
            }
        ),
        encoding="utf-8",
    )
    return root


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
    provenance_header = (header_for_path or (lambda _path: _header()))(Path("provenance-reference.xlsx"))

    def validate_provenance(
        _project_root: Path,
        *,
        base_frequency_hz: float,
        oddball_frequency_hz: float,
        dataset_index: object,
    ) -> object:
        plan = build_available_frequency_window_plan(
            provenance_header,
            oddball_frequency_hz=oddball_frequency_hz,
            base_frequency_hz=base_frequency_hz,
            noise_half_width_hz=0.1,
        )
        return SimpleNamespace(
            grid_fingerprint=plan.grid_fingerprint,
            method_version="test-neutral-full-fft-v1",
            source_fingerprint="source-fingerprint",
            cohort_fingerprint="cohort-fingerprint",
            frequency_qc_fingerprint="qc-fingerprint",
            processing_export_fingerprint="processing-export-fingerprint",
        )

    monkeypatch.setattr(
        inputs,
        "validate_project_full_fft_provenance",
        validate_provenance,
    )
    return header_calls, amplitude_calls


def _install_frequency_exclusions(
    monkeypatch: pytest.MonkeyPatch,
    *,
    excluded_participants: tuple[str, ...] = (),
    excluded_recordings: tuple[str, ...] = (),
    excluded_participant_conditions: tuple[tuple[str, str], ...] = (),
    excluded_recording_conditions: tuple[tuple[str, str], ...] = (),
    participant_condition_electrodes: dict[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
    recording_condition_electrodes: dict[
        tuple[str, str], frozenset[str]
    ]
    | None = None,
) -> None:
    """Install current reviewed QC exclusions without reviving legacy auto fields."""

    exclusions = FrequencyDomainCoverageDecisions(
        decision_fingerprint="reviewed-frequency-qc-fixture",
        review_complete=True,
        excluded_participants=frozenset(excluded_participants),
        excluded_recordings=frozenset(excluded_recordings),
        excluded_participant_conditions=frozenset(
            excluded_participant_conditions
        ),
        excluded_recording_conditions=frozenset(excluded_recording_conditions),
        excluded_electrodes_by_participant_condition=(
            participant_condition_electrodes or {}
        ),
        excluded_electrodes_by_recording_condition=(
            recording_condition_electrodes or {}
        ),
        reviewed_decisions=(),
    )
    monkeypatch.setattr(
        inputs,
        "resolve_frequency_qc_coverage_decisions",
        lambda _project_root: exclusions,
    )


@pytest.fixture(autouse=True)
def _completed_frequency_review(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_frequency_exclusions(monkeypatch)


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


def test_repeated_session_project_is_blocked_before_provenance_or_workbook_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = tmp_path / "Repeated"
    root.mkdir()
    (root / "project.json").write_text("{}", encoding="utf-8")
    index = SimpleNamespace(
        project_root=root,
        is_repeated_session=True,
    )
    monkeypatch.setattr(inputs, "load_project_dataset_index", lambda _root: index)

    def unexpected_provenance(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("provenance must not run for an unsupported design")

    monkeypatch.setattr(
        inputs,
        "validate_project_full_fft_provenance",
        unexpected_provenance,
    )

    with pytest.raises(
        FreeHarmonicInputError,
        match="Use the repeated-session batch",
    ):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )


def test_repeated_batch_prepares_four_stable_runs_per_condition_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_repeated_project(
        tmp_path / "Repeated",
        participants_by_group={
            "bc_group": ("BC1", "BC2", "BC3", "BC4"),
            "control_group": ("C1", "C2", "C3"),
        },
        conditions=("Condition A", "Condition B"),
        recording_condition_exclusions={
            "BC3__follicular_phase": ("Condition B",),
        },
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    request = RepeatedSessionBatchRequest(
        project_root=root,
        conditions=("Condition A", "Condition B"),
        group_ids=("bc_group", "control_group"),
        session_ids=("follicular_phase", "luteal_phase"),
        recording_exclusions=(
            RecordingExclusionRequest(
                recording_id="BC4__follicular_phase",
                reason="Declared P18-like outlier",
            ),
        ),
    )

    prepared = inputs.prepare_repeated_session_batch(
        request,
        FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
    )

    assert prepared.conditions == ("Condition A", "Condition B")
    assert [row.group_id for row in prepared.groups] == [
        "bc_group",
        "control_group",
    ]
    assert [row.session_id for row in prepared.sessions] == [
        "follicular_phase",
        "luteal_phase",
    ]
    assert len(prepared.contrast_runs) == 8
    assert [(row.condition, row.family, row.group_id) for row in prepared.contrast_runs] == [
        (
            "Condition A",
            RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS,
            None,
        ),
        (
            "Condition A",
            RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
            "bc_group",
        ),
        (
            "Condition A",
            RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
            "control_group",
        ),
        (
            "Condition A",
            RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE,
            None,
        ),
        (
            "Condition B",
            RepeatedSessionContrastFamily.SESSION_AVERAGED_GROUPS,
            None,
        ),
        (
            "Condition B",
            RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
            "bc_group",
        ),
        (
            "Condition B",
            RepeatedSessionContrastFamily.PAIRED_SESSIONS_WITHIN_GROUP,
            "control_group",
        ),
        (
            "Condition B",
            RepeatedSessionContrastFamily.GROUP_SESSION_CHANGE,
            None,
        ),
    ]
    assert len(header_calls) == len(amplitude_calls) == 22
    assert len(set(amplitude_calls)) == 22
    assert prepared.provenance.workbook_count == 22
    assert len(prepared.source_workbooks) == 22
    assert all(row.recording_id and row.session_id for row in prepared.source_workbooks)
    assert prepared.shared_selection_audit.z_scores.shape == (8, 3)
    assert prepared.shared_selection_audit.cell_participant_counts == (
        3,
        3,
        3,
        3,
        2,
        2,
        3,
        3,
    )
    assert prepared.shared_domain_fingerprint == (prepared.provenance.shared_domain_fingerprint)

    condition_a_runs = prepared.contrast_runs[:4]
    pooled, paired_bc, _paired_control, change = condition_a_runs
    assert pooled.tensor_semantics is (RepeatedSessionTensorSemantics.SESSION_AVERAGED_NORMALIZED_PROFILE)
    assert paired_bc.tensor_semantics is (RepeatedSessionTensorSemantics.SESSION_NORMALIZED_PAIRED_PROFILE)
    assert change.tensor_semantics is (RepeatedSessionTensorSemantics.NORMALIZED_SESSION_CHANGE)
    assert pooled.prepared.participant_ids_a == ("BC1", "BC2", "BC3")
    assert paired_bc.prepared.participant_ids_a == ("BC1", "BC2", "BC3")
    assert np.linalg.norm(
        pooled.prepared.values_a,
        axis=(1, 2),
    ) == pytest.approx(np.ones(3))
    assert change.prepared.values_a == pytest.approx(paired_bc.prepared.values_a - paired_bc.prepared.values_b)
    assert change.prepared.snr_a == pytest.approx(paired_bc.prepared.snr_a - paired_bc.prepared.snr_b)

    bc4_audit = [
        row for row in prepared.cohort_audit if row.participant_id == "BC4" and row.condition == "Condition A"
    ][0]
    assert not bc4_audit.included_complete_pair
    assert bc4_audit.available_session_ids == ("luteal_phase",)
    assert bc4_audit.missing_session_ids == ("follicular_phase",)
    assert bc4_audit.excluded_recording_ids == ("BC4__follicular_phase",)
    assert "Declared P18-like outlier" in bc4_audit.exclusion_reasons[0]
    bc3_b_audit = [
        row for row in prepared.cohort_audit if row.participant_id == "BC3" and row.condition == "Condition B"
    ][0]
    assert not bc3_b_audit.included_complete_pair
    assert bc3_b_audit.exclusion_reasons == ("Project recording/condition exclusion",)


def test_repeated_batch_unknown_analysis_exclusion_blocks_before_workbook_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_repeated_project(
        tmp_path / "Repeated",
        participants_by_group={
            "bc_group": ("BC1", "BC2"),
            "control_group": ("C1", "C2"),
        },
        conditions=("Condition A",),
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)

    with pytest.raises(FreeHarmonicInputError, match="unknown canonical recording"):
        inputs.prepare_repeated_session_batch(
            RepeatedSessionBatchRequest(
                project_root=root,
                conditions=("Condition A",),
                group_ids=("bc_group", "control_group"),
                session_ids=("follicular_phase", "luteal_phase"),
                recording_exclusions=(RecordingExclusionRequest("not-a-recording", "test"),),
            ),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


def test_repeated_batch_requires_two_complete_participants_in_every_cell(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _write_repeated_project(
        tmp_path / "Repeated",
        participants_by_group={
            "bc_group": ("BC1", "BC2", "BC3"),
            "control_group": ("C1", "C2", "C3"),
        },
        conditions=("Condition A",),
    )
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)

    with pytest.raises(FreeHarmonicInputError, match="phase-balanced participants"):
        inputs.prepare_repeated_session_batch(
            RepeatedSessionBatchRequest(
                project_root=root,
                conditions=("Condition A",),
                group_ids=("bc_group", "control_group"),
                session_ids=("follicular_phase", "luteal_phase"),
                recording_exclusions=(
                    RecordingExclusionRequest(
                        "BC2__follicular_phase",
                        "outlier",
                    ),
                    RecordingExclusionRequest(
                        "BC3__follicular_phase",
                        "outlier",
                    ),
                ),
            ),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


def test_independent_project_cohort_honors_all_exclusions_and_reads_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    _install_frequency_exclusions(
        monkeypatch,
        excluded_participants=("N3",),
    )
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
    assert prepared.provenance.full_fft_provenance_method_version == "test-neutral-full-fft-v1"
    assert prepared.provenance.full_fft_source_fingerprint == "source-fingerprint"
    assert prepared.provenance.reader_phase_seconds == (("xml_selected_rows", 0.004),)
    assert progress[-1] == (8, 8)
    assert prepared.snr_a.shape == prepared.values_a.shape == (2, 64, 3)
    assert prepared.snr_b.shape == prepared.values_b.shape == (2, 64, 3)
    assert prepared.values_a.flags.c_contiguous
    assert not prepared.values_a.flags.writeable
    assert np.sqrt(np.sum(prepared.values_a**2, axis=(1, 2))) == pytest.approx(np.ones(2))
    assert all(not workbook.project_relative_path.startswith(("/", "\\")) for workbook in prepared.source_workbooks)


def test_direct_preparation_blocks_missing_neutral_provenance_before_fullfft_io(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)

    def missing_provenance(*args: object, **kwargs: object) -> object:
        raise FullFftProvenanceMissingError(
            "Neutral FullFFT provenance is missing. Rerun post-processing; EEG preprocessing is not required."
        )

    monkeypatch.setattr(
        inputs,
        "validate_project_full_fft_provenance",
        missing_provenance,
    )

    with pytest.raises(FreeHarmonicInputError, match="provenance is missing"):
        inputs.prepare_project_contrast(
            _independent_request(root),
            FreeHarmonicMethodSpec(max_harmonic_hz=3.6),
        )

    assert header_calls == []
    assert amplitude_calls == []


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
            (condition_root / f"{participant}_{condition}_Results.xlsx").write_bytes(b"selected-reader-test-double")
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
        participant_groups={
            "P1": "all",
            "P2": "all",
            "P3": "all",
            "P4": "all",
        },
        participant_conditions={
            "P1": ("Angry", "Happy", "Unselected"),
            "P2": ("Angry", "Happy", "Unselected"),
            "P3": ("Angry", "Happy", "Unselected"),
            "P4": ("Angry", "Happy", "Unselected"),
        },
        participant_condition_exclusions={
            "P3": ("Happy", "Unselected"),
        },
    )
    _install_reader_doubles(monkeypatch)
    _install_frequency_exclusions(
        monkeypatch,
        excluded_participant_conditions=(
            ("P4", "Happy"),
            ("P4", "Unselected"),
        ),
    )

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
    assert [(row.participant_id, row.condition, row.reason) for row in exclusions] == [
        ("P3", "Happy", "Project participant-condition exclusion"),
        ("P4", "Happy", "Reviewed frequency-domain condition exclusion"),
    ]
    assert prepared.provenance.incomplete_pair_participants == ("P3", "P4")


def test_included_frequency_qc_electrode_exclusion_fails_before_workbook_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root, _paths = _independent_project(tmp_path)
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    _install_frequency_exclusions(
        monkeypatch,
        participant_condition_electrodes={
            ("A1", "Faces"): frozenset({"Fp1"})
        },
    )

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
    root, _paths = _independent_project(tmp_path)
    header_calls, amplitude_calls = _install_reader_doubles(monkeypatch)
    _install_frequency_exclusions(
        monkeypatch,
        excluded_participants=("N2", "N3"),
    )

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


def test_companion_preserves_fhc_bin_windows_sensor_order_and_snr(
    tmp_path: Path,
) -> None:
    from Main_App.io.spectral_data import (
        SpectralDataError,
        spectral_manifest_frame,
        write_spectral_companion,
    )
    from Tools.Free_Harmonic_Clustering.preparation import compute_participant_snr

    header = _header()
    rng = np.random.default_rng(3165)
    values = rng.integers(1, 129, size=(64, len(header) - 1)) / 16.0
    frame = pd.DataFrame(values, columns=header[1:])
    frame.insert(0, "Electrode", DEFAULT_ELECTRODE_NAMES_64)
    legacy = tmp_path / "legacy.xlsx"
    frame.to_excel(legacy, sheet_name="FullFFT Amplitude (uV)", index=False)
    path = tmp_path / "companion.xlsx"
    descriptor = write_spectral_companion(path, {"FullFFT Amplitude (uV)": frame})
    with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
        spectral_manifest_frame(descriptor).to_excel(
            writer, sheet_name="Spectral Data", index=False,
        )
    assert inputs._read_fullfft_header(path) == inputs._read_fullfft_header(legacy)
    plan = build_available_frequency_window_plan(
        inputs._read_fullfft_header(path), oddball_frequency_hz=1.2,
        base_frequency_hz=6.0,
    )
    legacy_frame = inputs._read_fullfft_selected_columns(legacy, plan.required_columns, {})
    companion_frame = inputs._read_fullfft_selected_columns(path, plan.required_columns, {})
    pd.testing.assert_frame_equal(companion_frame, legacy_frame, check_exact=True)
    legacy_matrix = inputs._validate_sensor_matrix(legacy_frame, legacy, plan)
    companion_matrix = inputs._validate_sensor_matrix(companion_frame, path, plan)
    np.testing.assert_array_equal(companion_matrix, legacy_matrix)
    np.testing.assert_array_equal(
        compute_participant_snr(companion_matrix, plan),
        compute_participant_snr(legacy_matrix, plan),
    )
    companion_path = path.with_name(str(descriptor["path"]))
    data = bytearray(companion_path.read_bytes())
    data[len(data) // 2] ^= 1
    companion_path.write_bytes(data)
    with pytest.raises(SpectralDataError):
        inputs._read_fullfft_header(path)
    with pytest.raises(SpectralDataError):
        inputs._read_fullfft_selected_columns(path, plan.required_columns, {})
