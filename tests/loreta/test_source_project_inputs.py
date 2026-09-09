from __future__ import annotations

import json
import shutil
from dataclasses import replace
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.processing.artifact_freshness import (
    STATS_READY_SUMMED_BCA_ARTIFACT,
    StalePostProcessingArtifactError,
    activate_selection_freshness,
    mark_artifact_current,
    mark_selection_derivatives_stale,
)
from Main_App.processing.frequency_domain_qc import FrequencyDomainExclusions
from Main_App.projects import SessionInfo
from Tools.LORETA_Visualizer.source_producers import project_inputs
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    SOURCE_TOPOGRAPHY_METRIC_BCA,
    SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
    _read_metric_sheet,
    _read_selected_harmonics,
    _subject_in_ids,
    build_l2_mne_conditions_from_project,
    project_source_participant_selection,
)


@pytest.mark.parametrize("suffix", [".xlsx", ".fpvs"])
@pytest.mark.parametrize("sheet", ["BCA (uV)", "FFT Amplitude (uV)"])
def test_metric_companion_preserves_selected_topography_bits(tmp_path, suffix, sheet):
    from Main_App.Shared.post_process_excel import write_results_workbook

    path = tmp_path / f"P01{suffix}"
    values = np.asarray([-0.0, np.nextafter(1.0, 2.0)], dtype=np.float64)
    frame = pd.DataFrame({
        "Electrode": ["Cz", "Pz"], "2.4000_Hz": values,
        "4.8000_Hz": np.asarray([0.125, np.nextafter(0.0, 1.0)]),
    })
    write_results_workbook(str(path), {sheet: frame})
    actual = _read_metric_sheet(
        path, sheet_name=sheet, selected_harmonics=(2.4, 4.8),
        expected_electrodes=("CZ", "PZ"),
    )
    for harmonic in (2.4, 4.8):
        expected = frame[f"{harmonic:.4f}_Hz"].to_numpy()
        np.testing.assert_array_equal(actual[harmonic].view(np.uint64), expected.view(np.uint64))


@pytest.mark.parametrize("damage,expected_error", [
    ("order", "expected BioSemi64 electrode order"),
    ("row_count", "expected 2 electrode rows"),
    ("nonfinite", "non-finite source topography"),
    ("column", "missing columns: 4.8000_Hz"),
    ("companion", "[Cc]ompanion"),
])
def test_native_metric_reader_preserves_source_validation(tmp_path, damage, expected_error):
    from Main_App.Shared.post_process_excel import write_results_workbook
    from Main_App.io.condition_data import condition_companion_identity

    path = tmp_path / "P01.fpvs"
    frame = pd.DataFrame({
        "Electrode": ["Cz", "Pz"], "2.4000_Hz": [1.0, 2.0], "4.8000_Hz": [3.0, 4.0],
    })
    if damage == "order":
        frame = frame.iloc[::-1]
    elif damage == "row_count":
        frame = frame.iloc[:1]
    elif damage == "nonfinite":
        frame.loc[0, "2.4000_Hz"] = np.inf
    elif damage == "column":
        frame = frame.drop(columns=["4.8000_Hz"])
    write_results_workbook(str(path), {"BCA (uV)": frame})
    if damage == "companion":
        descriptor = condition_companion_identity(path)
        path.with_name(descriptor["path"]).unlink()
    with pytest.raises(ValueError, match=expected_error):
        _read_metric_sheet(
            path, sheet_name="BCA (uV)", selected_harmonics=(2.4, 4.8),
            expected_electrodes=("CZ", "PZ"),
        )


def test_project_input_assembler_builds_bca_condition_topographies(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(project_root)

    assert result.metric == SOURCE_TOPOGRAPHY_METRIC_BCA
    assert result.selected_harmonics_hz == (2.4, 4.8)
    assert [condition.label for condition in result.conditions] == ["Condition A", "Condition B"]
    assert result.excluded_subjects == ("P2",)
    assert result.flagged_subjects == ("P2",)
    assert result.diagnostics == ()

    condition_a = result.conditions[0]
    expected_2_4 = np.asarray([10.0 + index for index in range(64)], dtype=float)
    expected_4_8 = np.asarray([20.0 + index for index in range(64)], dtype=float)
    assert np.allclose(condition_a.harmonic_topographies[2.4], expected_2_4)
    assert np.allclose(condition_a.harmonic_topographies[4.8], expected_4_8)
    assert condition_a.metadata["source_sheet"] == "BCA (uV)"
    assert condition_a.metadata["included_subject_count"] == 1
    assert condition_a.metadata["include_flagged_subjects"] is False
    assert condition_a.metadata["flagged_subjects_included"] == []


def test_project_input_assembler_can_include_flagged_subjects(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    condition_a = result.conditions[0]
    expected_2_4 = np.asarray([10.0 + index for index in range(64)], dtype=float) + 0.5
    assert np.allclose(condition_a.harmonic_topographies[2.4], expected_2_4)
    assert condition_a.metadata["included_subject_count"] == 2
    assert condition_a.metadata["include_flagged_subjects"] is True
    assert condition_a.metadata["flagged_subjects_included"] == ["P2"]


def _frequency_exclusions(**changes) -> FrequencyDomainExclusions:
    baseline = FrequencyDomainExclusions(
        excluded_participants=frozenset(),
        auto_excluded_participants=frozenset(),
        manual_excluded_participants=frozenset(),
        auto_excluded_electrodes_by_participant={},
        downstream_outputs_stale=False,
    )
    return replace(baseline, **changes)


def test_workbook_source_omits_only_frequency_excluded_participant_condition(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    exclusions = _frequency_exclusions(
        excluded_participant_conditions=frozenset({(" p1 ", "Condition A")}),
    )
    snapshots = []

    def load_exclusions(_root):
        snapshots.append(exclusions)
        return exclusions

    monkeypatch.setattr(project_inputs, "active_frequency_domain_exclusions", load_exclusions)
    original_reader = project_inputs._read_metric_sheet
    read_paths = []

    def read_metric(path, **kwargs):
        read_paths.append(path)
        return original_reader(path, **kwargs)

    monkeypatch.setattr(project_inputs, "_read_metric_sheet", read_metric)
    source_bytes = {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()}

    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    assert [summary.included_subjects for summary in result.summaries] == [("P2",), ("P1", "P2")]
    assert [summary.included_subject_count for summary in result.summaries] == [1, 2]
    assert result.excluded_subjects == ()
    assert result.selected_harmonics_hz == (2.4, 4.8)
    assert result.conditions[0].harmonic_topographies[2.4][0] == 11.0
    assert result.conditions[1].harmonic_topographies[2.4][0] == 100.5
    assert len(read_paths) == 3
    assert not any(path.name.startswith("SCP1_") and path.parent.name == "Condition A" for path in read_paths)
    assert len(snapshots) == 1
    assert any("P1" in message and "Condition A" in message and "participant-condition" in message for message in result.diagnostics)
    assert result.conditions[0].metadata["frequency_domain_qc_omitted_workbook_count"] == 1
    assert result.conditions[1].metadata["frequency_domain_qc_omissions"] == []
    assert {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()} == source_bytes


def _single_recording_workbook_index(project_root: Path):
    index = project_inputs.load_project_dataset_index(project_root)
    return replace(index, workbooks=tuple(
        replace(record, recording_id=f"{record.participant_id}__baseline")
        for record in index.workbooks
    ))


def _repeated_workbook_index(project_root: Path):
    index = project_inputs.load_project_dataset_index(project_root)
    sessions = {
        "baseline": SessionInfo("baseline", "Baseline", 1),
        "follow_up": SessionInfo("follow_up", "Follow up", 2),
    }
    records = []
    for record in index.workbooks:
        for session in sessions.values():
            path = record.path.parent / session.session_id / record.path.name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(record.path, path)
            records.append(replace(
                record,
                path=path,
                recording_id=f"{record.participant_id}__{session.session_id}",
                session_id=session.session_id,
                session_label=session.label,
                visit_index=session.visit_index,
            ))
    return replace(index, workbooks=tuple(records), sessions=sessions)


@pytest.mark.parametrize("scope,expected_counts,expected_read_count", [
    ("recording", (1, 1), 2),
    ("recording-condition", (1, 2), 3),
    ("participant-condition", (1, 2), 3),
    ("participant", (1, 1), 2),
])
def test_workbook_source_scoped_qc_preserves_other_participants_and_conditions(
    tmp_path: Path,
    monkeypatch,
    scope: str,
    expected_counts: tuple[int, int],
    expected_read_count: int,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    index = _single_recording_workbook_index(project_root)
    changes = {
        "recording": {"excluded_recordings": frozenset({" p1__BASELINE "})},
        "recording-condition": {"excluded_recording_conditions": frozenset({(" p1__BASELINE ", "Condition A")})},
        "participant-condition": {"excluded_participant_conditions": frozenset({(" p1 ", "Condition A")})},
        "participant": {"excluded_participants": frozenset({"P1"})},
    }
    monkeypatch.setattr(project_inputs, "load_project_dataset_index", lambda _root: index)
    monkeypatch.setattr(project_inputs, "active_frequency_domain_exclusions", lambda _root: _frequency_exclusions(**changes[scope]))
    source_bytes = {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()}
    original_reader = project_inputs._read_metric_sheet
    read_paths = []

    def read_metric(path, **kwargs):
        read_paths.append(path)
        return original_reader(path, **kwargs)

    monkeypatch.setattr(project_inputs, "_read_metric_sheet", read_metric)
    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    assert tuple(summary.included_subject_count for summary in result.summaries) == expected_counts
    assert len(read_paths) == expected_read_count
    assert result.selected_harmonics_hz == (2.4, 4.8)
    assert result.excluded_subjects == (("P1",) if scope == "participant" else ())
    if scope != "participant":
        for condition, count in zip(result.conditions, expected_counts, strict=True):
            assert condition.metadata["frequency_domain_qc_omitted_workbook_count"] == 2 - count
        assert any(scope in message for message in result.diagnostics)
    if scope in {"recording", "recording-condition"}:
        assert any(path.name.startswith("SCP2_") for path in read_paths)
        assert not any(path.name.startswith("SCP1_") and path.parent.name == "Condition A" for path in read_paths)
    if scope in {"recording-condition", "participant-condition"}:
        assert any(path.parent.name == "Condition B" and path.name.startswith("SCP1_") for path in read_paths)
    assert {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()} == source_bytes


@pytest.mark.parametrize("all_conditions", [False, True])
def test_workbook_source_empty_qc_cohort_is_omitted_with_audit_and_no_sheet_read(
    tmp_path: Path,
    monkeypatch,
    all_conditions: bool,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    omitted_conditions = ("Condition A", "Condition B") if all_conditions else ("Condition A",)
    exclusions = _frequency_exclusions(excluded_participant_conditions=frozenset(
        (participant, condition) for participant in ("P1", "P2") for condition in omitted_conditions
    ))
    monkeypatch.setattr(project_inputs, "active_frequency_domain_exclusions", lambda _root: exclusions)
    original_reader = project_inputs._read_metric_sheet
    read_paths = []

    def read_metric(path, **kwargs):
        assert path.parent.name not in omitted_conditions
        read_paths.append(path)
        return original_reader(path, **kwargs)

    monkeypatch.setattr(project_inputs, "_read_metric_sheet", read_metric)
    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    assert [condition.label for condition in result.conditions] == ([] if all_conditions else ["Condition B"])
    assert len(read_paths) == (0 if all_conditions else 2)
    assert result.excluded_subjects == ()
    for condition in omitted_conditions:
        assert any(f"No included workbooks for condition: {condition}" in message for message in result.diagnostics)
        for participant in ("P1", "P2"):
            assert any(participant in message and condition in message and "participant-condition" in message for message in result.diagnostics)


@pytest.mark.parametrize("changes", [
    {"excluded_recordings": frozenset({"P1"})},
    {"excluded_recordings": frozenset({"P01__baseline"})},
    {"excluded_recording_conditions": frozenset({("P1__baseline", "condition a")})},
    {"excluded_participant_conditions": frozenset({("P01", "Condition A")})},
])
def test_workbook_source_scoped_ids_do_not_alias_other_canonical_records(
    tmp_path: Path,
    monkeypatch,
    changes: dict,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    index = _single_recording_workbook_index(project_root)
    monkeypatch.setattr(project_inputs, "load_project_dataset_index", lambda _root: index)
    monkeypatch.setattr(project_inputs, "active_frequency_domain_exclusions", lambda _root: _frequency_exclusions(**changes))

    result = build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    assert [summary.included_subject_count for summary in result.summaries] == [2, 2]
    assert result.diagnostics == ()


@pytest.mark.parametrize("declared_sessions", [False, True])
@pytest.mark.parametrize("excluded_recordings", [
    (),
    ("P1__baseline",),
    ("P1__baseline", "P2__baseline"),
])
def test_workbook_source_rejects_repeated_cohort_before_reads_despite_qc_exclusions(
    tmp_path: Path,
    monkeypatch,
    declared_sessions: bool,
    excluded_recordings: tuple[str, ...],
) -> None:
    project_root = _build_project_fixture(tmp_path)
    index = _repeated_workbook_index(project_root)
    if not declared_sessions:
        index = replace(index, sessions={})
    monkeypatch.setattr(project_inputs, "load_project_dataset_index", lambda _root: index)
    monkeypatch.setattr(project_inputs, "active_frequency_domain_exclusions", lambda _root: _frequency_exclusions(
        excluded_recordings=frozenset(excluded_recordings),
    ))

    def unexpected_read(*_args, **_kwargs):
        raise AssertionError("Repeated cohorts must fail before workbook contents are read.")

    monkeypatch.setattr(project_inputs, "_read_selected_harmonics", unexpected_read)
    monkeypatch.setattr(project_inputs, "_read_metric_sheet", unexpected_read)
    source_bytes = {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()}

    with pytest.raises(ValueError, match="participant-keyed; a recording-aware source producer is required"):
        build_l2_mne_conditions_from_project(project_root, include_flagged_subjects=True)

    assert {path: path.read_bytes() for path in project_root.rglob("*") if path.is_file()} == source_bytes


def test_project_source_participant_selection_includes_saved_manual_exclusions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "preprocessing": {
                    "manual_excluded_participants": ["P12", "p20"],
                }
            }
        ),
        encoding="utf-8",
    )

    selection = project_source_participant_selection(project_root)

    assert selection.excluded_subjects == ("P12", "p20")


def test_source_participant_exclusion_matching_normalizes_both_id_sides() -> None:
    assert _subject_in_ids("P03", {"p03"})
    assert _subject_in_ids("SCP003", {"P3"})


def test_project_input_assembler_can_use_fft_amplitude_metric(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path)

    result = build_l2_mne_conditions_from_project(
        project_root,
        metric=SOURCE_TOPOGRAPHY_METRIC_FFT_AMPLITUDE,
        conditions=["Condition B"],
    )

    assert result.sheet_name == "FFT Amplitude (uV)"
    assert [condition.label for condition in result.conditions] == ["Condition B"]
    condition_b = result.conditions[0]
    expected = np.asarray([300.0 + index for index in range(64)], dtype=float)
    assert np.allclose(condition_b.harmonic_topographies[2.4], expected)
    assert condition_b.sensor_value_unit == "summed FFT amplitude uV"


def test_project_input_assembler_reads_group_subfolder_workbooks(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, group_subfolders=True)

    result = build_l2_mne_conditions_from_project(project_root)

    assert [condition.label for condition in result.conditions] == ["Condition A", "Condition B"]
    assert result.summaries[0].workbook_count == 2
    assert result.conditions[0].metadata["included_subject_count"] == 1


def test_project_input_assembler_splits_canonical_groups_before_aggregation(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    _convert_fixture_to_multi_group(project_root, keep_stale_flat_copy=True)

    result = build_l2_mne_conditions_from_project(
        project_root,
        include_flagged_subjects=True,
    )

    assert [condition.label for condition in result.conditions] == [
        "Control Group - Condition A",
        "Patient Group - Condition A",
        "Control Group - Condition B",
        "Patient Group - Condition B",
    ]
    assert [
        condition.metadata["group_id"] for condition in result.conditions
    ] == ["control", "patient", "control", "patient"]
    assert all(
        condition.metadata["group_split_applied"]
        for condition in result.conditions
    )
    assert result.conditions[0].metadata["included_subject_count"] == 1
    assert result.conditions[1].metadata["included_subject_count"] == 1
    assert np.isclose(result.conditions[0].harmonic_topographies[2.4][0], 10.0)
    assert np.isclose(result.conditions[1].harmonic_topographies[2.4][0], 11.0)


def test_project_input_assembler_keeps_one_group_condition_identity(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path, group_subfolders=True)
    _write_single_group_manifest(project_root)

    result = build_l2_mne_conditions_from_project(
        project_root,
        include_flagged_subjects=True,
    )

    assert [condition.condition_id for condition in result.conditions] == [
        "condition_a",
        "condition_b",
    ]
    assert [condition.label for condition in result.conditions] == [
        "Condition A",
        "Condition B",
    ]
    assert all(
        not condition.metadata["group_split_applied"]
        for condition in result.conditions
    )
    assert all(
        condition.metadata["group_id"] == "default"
        for condition in result.conditions
    )


def test_project_input_assembler_rejects_unregistered_group_workbook(
    tmp_path,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    _convert_fixture_to_multi_group(project_root, keep_stale_flat_copy=False)
    source = (
        project_root
        / "1 - Excel Data Files"
        / "Condition A"
        / "Control Group"
        / "SCP1_Condition A_Results.xlsx"
    )
    shutil.copy2(
        source,
        source.with_name("SCP3_Condition A_Results.xlsx"),
    )

    with pytest.raises(
        ValueError,
        match="workbook identity is incomplete in project.json",
    ):
        build_l2_mne_conditions_from_project(project_root)


def test_project_input_assembler_rejects_missing_selected_column(tmp_path) -> None:
    project_root = _build_project_fixture(tmp_path, omit_condition_b_4_8=True)

    with pytest.raises(ValueError, match="missing columns"):
        build_l2_mne_conditions_from_project(project_root)


def test_project_input_assembler_rejects_stale_stats_ready_in_managed_project(
    tmp_path: Path,
) -> None:
    project_root = _build_project_fixture(tmp_path)
    _write_single_group_manifest(project_root)
    mark_selection_derivatives_stale(
        project_root,
        reason="The accepted harmonic selection changed.",
    )

    with pytest.raises(StalePostProcessingArtifactError, match="is stale"):
        build_l2_mne_conditions_from_project(project_root)


def test_selected_harmonic_reader_accepts_current_stats_ready_schema(tmp_path) -> None:
    stats_ready = tmp_path / "Stats_Ready_Summed_BCA.xlsx"
    with pd.ExcelWriter(stats_ready) as writer:
        pd.DataFrame(
            {
                "requested_harmonic_hz": [1.2, 2.4, 3.6, 4.8],
                "selected": [False, True, False, True],
                "included_in_summation": [False, True, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)

    assert _read_selected_harmonics(stats_ready) == (2.4, 3.6, 4.8)


def _build_project_fixture(
    tmp_path: Path,
    *,
    omit_condition_b_4_8: bool = False,
    group_subfolders: bool = False,
) -> Path:
    project_root = tmp_path / "Project"
    stats_dir = project_root / "3 - Statistical Analysis Results"
    excel_root = project_root / "1 - Excel Data Files"
    stats_dir.mkdir(parents=True)
    excel_root.mkdir(parents=True)
    _write_stats_ready(stats_dir / "Stats_Ready_Summed_BCA.xlsx")
    _write_flagged(stats_dir / "Flagged Participants.xlsx")
    _write_empty_excluded(stats_dir / "Excluded Participants.xlsx")
    for condition in ("Condition A", "Condition B"):
        condition_dir = excel_root / condition
        condition_dir.mkdir()
        workbook_dir = condition_dir / "Default" if group_subfolders else condition_dir
        workbook_dir.mkdir(exist_ok=True)
        for subject_offset, subject in enumerate(("SCP1", "SCP2")):
            _write_participant_workbook(
                workbook_dir / f"{subject}_{condition}_Results.xlsx",
                condition=condition,
                subject_offset=subject_offset,
                omit_4_8=omit_condition_b_4_8 and condition == "Condition B",
            )
    return project_root


def _write_stats_ready(path: Path) -> None:
    with pd.ExcelWriter(path) as writer:
        pd.DataFrame(
            {
                "condition": ["Condition A", "Condition A", "Condition B", "Condition B"],
                "subject_id": ["P1", "P2", "P1", "P2"],
                "roi": ["ROI"] * 4,
                "summed_bca_uv": [1.0, 2.0, 3.0, 4.0],
            }
        ).to_excel(writer, sheet_name="Long_Format", index=False)
        pd.DataFrame(
            {
                "harmonic_hz": [1.2, 2.4, 4.8],
                "selected": [False, True, True],
            }
        ).to_excel(writer, sheet_name="Harmonic_Selection", index=False)


def _write_flagged(path: Path) -> None:
    pd.DataFrame({"participant_id": ["P2"], "flag_types": ["QC_SUMABS"]}).to_excel(
        path,
        sheet_name="Flag Summary",
        index=False,
    )


def _write_empty_excluded(path: Path) -> None:
    pd.DataFrame({"participant_id": [], "exclusion_reason": []}).to_excel(
        path,
        sheet_name="Excluded Participants",
        index=False,
    )


def _write_participant_workbook(
    path: Path,
    *,
    condition: str,
    subject_offset: int,
    omit_4_8: bool,
) -> None:
    electrodes = DEFAULT_ELECTRODE_NAMES_64
    condition_base = 10.0 if condition == "Condition A" else 100.0
    fft_base = 200.0 if condition == "Condition A" else 300.0
    bca = pd.DataFrame(
        {
            "Electrode": electrodes,
            "2.4000_Hz": [condition_base + index + subject_offset for index in range(64)],
            "4.8000_Hz": [condition_base + 10.0 + index + subject_offset for index in range(64)],
        }
    )
    fft = pd.DataFrame(
        {
            "Electrode": electrodes,
            "2.4000_Hz": [fft_base + index + subject_offset for index in range(64)],
            "4.8000_Hz": [fft_base + 10.0 + index + subject_offset for index in range(64)],
        }
    )
    if omit_4_8:
        bca = bca.drop(columns=["4.8000_Hz"])
    with pd.ExcelWriter(path) as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)", index=False)
        fft.to_excel(writer, sheet_name="FFT Amplitude (uV)", index=False)


def _convert_fixture_to_multi_group(
    project_root: Path,
    *,
    keep_stale_flat_copy: bool,
) -> None:
    excel_root = project_root / "1 - Excel Data Files"
    for condition in ("Condition A", "Condition B"):
        condition_dir = excel_root / condition
        control_dir = condition_dir / "Control Group"
        patient_dir = condition_dir / "Patient Group"
        control_dir.mkdir()
        patient_dir.mkdir()
        control_source = condition_dir / f"SCP1_{condition}_Results.xlsx"
        patient_source = condition_dir / f"SCP2_{condition}_Results.xlsx"
        control_target = control_dir / control_source.name
        patient_target = patient_dir / patient_source.name
        shutil.move(control_source, control_target)
        shutil.move(patient_source, patient_target)
        if keep_stale_flat_copy:
            shutil.copy2(control_target, control_source)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Multi-group source input fixture",
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "control": {
                        "label": "Control Group",
                        "folder_name": "Control Group",
                        "raw_input_folder": "Raw/Control",
                    },
                    "patient": {
                        "label": "Patient Group",
                        "folder_name": "Patient Group",
                        "raw_input_folder": "Raw/Patient",
                    },
                },
                "participants": {
                    "SCP1": {"group_id": "control"},
                    "SCP2": {"group_id": "patient"},
                },
            }
        ),
        encoding="utf-8",
    )
    _mark_stats_ready_current(project_root)


def _write_single_group_manifest(project_root: Path) -> None:
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "name": "Single-group source input fixture",
                "results_folder": ".",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "groups": {
                    "default": {
                        "label": "Default",
                        "folder_name": "Default",
                        "raw_input_folder": "Raw/Default",
                    }
                },
                "participants": {
                    "SCP1": {"group_id": "default"},
                    "SCP2": {"group_id": "default"},
                },
            }
        ),
        encoding="utf-8",
    )
    _mark_stats_ready_current(project_root)


def _mark_stats_ready_current(project_root: Path) -> None:
    summary = project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    summary.parent.mkdir(parents=True, exist_ok=True)
    summary.write_text("fixture selection", encoding="utf-8")
    activate_selection_freshness(
        project_root,
        {"selection_fingerprint": "fixture-selection"},
        selection_summary_path=summary,
    )
    mark_artifact_current(
        project_root,
        STATS_READY_SUMMED_BCA_ARTIFACT,
        project_root
        / "3 - Statistical Analysis Results"
        / "Stats_Ready_Summed_BCA.xlsx",
        "fixture-selection",
    )
