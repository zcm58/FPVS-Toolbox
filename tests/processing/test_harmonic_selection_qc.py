from __future__ import annotations

import copy
import json
import math
import os
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pandas as pd
import pytest
from openpyxl import load_workbook

from Main_App.processing import full_fft_provenance, harmonic_selection_qc
from Main_App.processing.spectral_eligibility import resolve_spectral_eligibility
from Main_App.processing.roi_settings import build_roi_definition_snapshot
from Main_App.processing.post_processing_context import post_processing_validation_scope
from Main_App.projects.frequency_protocol import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.projects import Project
from Tools.LORETA_Visualizer import stats_ready_workbook as stats_ready_workbook_mod
from Tools.LORETA_Visualizer.source_producers.project_inputs import (
    _read_selected_harmonics,
)
from Tools.Stats.analysis import dv_policies, dv_policy_fixed_predefined
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_NAME,
    HARMONIC_PROFILE_FIXED_ID,
    HARMONIC_PROFILE_LEGACY_ID,
    HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
    HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
)
from Tools.Stats.analysis.dv_policies import prepare_summed_bca_data
from Tools.Stats.data.group_harmonic_cache import (
    clear_cached_group_harmonic_selections,
)
from Tools.Stats.io.stats_ready_export import HARMONIC_SELECTION_COLUMNS


TEST_FREQUENCY_PROTOCOL = FrequencyProtocol.from_recurrence(
    6,
    5,
    expected_analyzed_oddball_cycles=12,
    expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
)


@pytest.fixture(autouse=True)
def _current_workbook_geometry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        lambda _root, *, dataset_index=None: {},
    )
    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_full_fft_provenance",
        lambda _root, *, dataset_index=None: object(),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_current_project_frequency_protocol",
        lambda _project, _root: TEST_FREQUENCY_PROTOCOL,
    )

    def _released_context(_root):
        rois = harmonic_selection_qc.load_rois_from_settings()
        snapshot = build_roi_definition_snapshot(rois)
        normalization = SimpleNamespace(excluded_channels=())
        coverage = SimpleNamespace(
            fingerprint="test-roi-coverage",
            decision_fingerprint="test-frequency-decisions",
            roi_snapshot=snapshot,
            cells=(),
            cell_for=lambda _identity, _condition: SimpleNamespace(
                source_evidence=object(),
                whole_scalp_normalization=normalization,
                downstream_cell_excluded=False,
                workbook_path="synthetic-test-workbook",
            ),
        )
        return (
            SimpleNamespace(fingerprint="test-outcomes"),
            coverage,
            SimpleNamespace(fingerprint="test-final-release"),
        )

    monkeypatch.setattr(
        harmonic_selection_qc,
        "_current_final_release_context",
        _released_context,
    )
    from Main_App.processing import roi_coverage

    monkeypatch.setattr(
        roi_coverage,
        "require_project_final_release",
        _released_context,
    )
    monkeypatch.setattr(
        dv_policy_fixed_predefined,
        "_require_matching_coverage_workbook",
        lambda _cell, supplied_path, *, context: str(supplied_path),
    )


def test_processing_harmonic_entry_rejects_legacy_geometry_before_workbook_math(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_processing_harmonic_selection_inputs",
        lambda *_args, **_kwargs: SimpleNamespace(project_root=tmp_path),
    )

    def reject_geometry(_root, *, dataset_index=None):
        raise full_fft_provenance.FullFftProvenanceError(
            "Legacy or unknown geometry cannot be analyzed; reprocess the EEG."
        )

    monkeypatch.setattr(
        full_fft_provenance,
        "require_current_project_workbook_geometry",
        reject_geometry,
    )

    with pytest.raises(
        full_fft_provenance.FullFftProvenanceError,
        match="Legacy or unknown geometry",
    ):
        harmonic_selection_qc.run_processing_harmonic_selection_qc(
            SimpleNamespace(project_root=tmp_path)
        )


def test_processing_harmonic_entry_requires_final_release_before_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_processing_harmonic_selection_inputs",
        lambda *_args, **_kwargs: SimpleNamespace(project_root=tmp_path),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_current_final_release_context",
        lambda _root: (_ for _ in ()).throw(
            RuntimeError("QC-20 final release is missing")
        ),
    )

    with pytest.raises(RuntimeError, match="QC-20 final release is missing"):
        harmonic_selection_qc.run_processing_harmonic_selection_qc(
            SimpleNamespace(project_root=tmp_path)
        )


def test_managed_harmonic_selection_requires_explicit_canonical_oddball_rate() -> None:
    assert harmonic_selection_qc._require_canonical_oddball_frequency(
        SimpleNamespace(oddball_frequency_hz=0.3)
    ) == pytest.approx(0.3)

    with pytest.raises(RuntimeError, match="explicit canonical project oddball"):
        harmonic_selection_qc._require_canonical_oddball_frequency(SimpleNamespace())
    with pytest.raises(RuntimeError, match="explicit positive canonical"):
        harmonic_selection_qc._require_canonical_oddball_frequency(
            SimpleNamespace(oddball_frequency_hz=0.0)
        )
    with pytest.raises(ValueError, match="lacks its project oddball frequency"):
        _ = harmonic_selection_qc.PersistedFixedHarmonicSelection(
            selection_metadata={}
        ).oddball_frequency_hz


def test_processing_spectral_domain_intersects_verified_workbook_eligibility(
    tmp_path: Path,
) -> None:
    protocol = FrequencyProtocol.from_recurrence(
        6,
        5,
        expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    paths = {
        "S1": {"Faces": str(tmp_path / "S1.xlsx")},
        "S2": {"Faces": str(tmp_path / "S2.xlsx")},
    }
    results = []
    for subject, notch_centers in (("S1", ()), ("S2", (24,))):
        result = resolve_spectral_eligibility(
            protocol=protocol,
            sampling_rate_hz=256,
            analyzed_samples=30_720,
            requested_high_pass_hz=0.1,
            requested_low_pass_hz=50,
            applied_high_pass_hz=0.1,
            applied_low_pass_hz=50,
            applied_notch_centers_hz=notch_centers,
        )
        results.append(result)
        with pd.ExcelWriter(paths[subject]["Faces"], engine="openpyxl") as writer:
            pd.DataFrame(result.to_rows()).to_excel(
                writer,
                sheet_name="Spectral Eligibility",
                index=False,
            )

    orders, fingerprint, identities = (
        harmonic_selection_qc._project_spectral_eligibility_domain(
            protocol=protocol,
            subjects=["S1", "S2"],
            conditions=["Faces"],
            subject_data=paths,
            log_func=None,
        )
    )

    assert 20 not in orders  # 24 Hz is deliberately notched in S2.
    assert orders == tuple(
        item.target.oddball_harmonic_order
        for item in results[1].eligible_targets
    )
    assert len(fingerprint) == 64
    assert identities == (
        ("S1", "Faces", results[0].fingerprint),
        ("S2", "Faces", results[1].fingerprint),
    )

def test_processing_harmonic_selection_qc_writes_quality_check_workbook_and_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition_root = excel_root / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": excel_root},
        event_map={"Faces": 1},
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.workbook_path == project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    assert report.workbook_path.exists()
    assert report.selection_metadata["detected_significant_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )
    assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    workbook = load_workbook(report.workbook_path)
    assert workbook.sheetnames == ["Selection_Summary", "Harmonic_Selection"]
    harmonic_headers = [
        cell.value for cell in next(workbook["Harmonic_Selection"].iter_rows(max_row=1))
    ]
    assert harmonic_headers == HARMONIC_SELECTION_COLUMNS
    summary_values = {
        row[0].value: row[1].value
        for row in workbook["Selection_Summary"].iter_rows(min_row=2, max_col=2)
    }
    assert summary_values["Included harmonic frequencies (Hz)"] == "1.2; 2.4; 3.6; 4.8; 7.2"

    manifest = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    entries = manifest["tools"]["stats"]["group_significant_harmonics_cache"]["entries"]
    assert len(entries) == 1

    assert clear_cached_group_harmonic_selections(project_root) == 1
    repaired_report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)
    assert repaired_report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    repaired_manifest = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    repaired_entries = repaired_manifest["tools"]["stats"][
        "group_significant_harmonics_cache"
    ]["entries"]
    assert len(repaired_entries) == 1

    def _unexpected_recalculation(**_kwargs):
        raise AssertionError("Downstream loading must not recalculate significant harmonics")

    monkeypatch.setattr(
        harmonic_selection_qc,
        "build_group_significant_harmonic_selection",
        _unexpected_recalculation,
    )
    loaded = harmonic_selection_qc.load_processing_harmonic_selection(project)
    assert loaded.selected_harmonics_hz == pytest.approx([1.2, 2.4, 3.6, 4.8, 7.2])
    assert loaded.selection_cache_source == "saved_processing_metadata"


def test_processing_harmonic_selection_survives_project_event_order_reload(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    disk_event_map = {"Faces": 1, "Objects": 2}
    live_event_map = {"Objects": 2, "Faces": 1}
    for condition in disk_event_map:
        condition_root = excel_root / condition
        condition_root.mkdir(parents=True, exist_ok=True)
        _write_group_policy_workbook(
            condition_root / f"S1_{condition}_Results.xlsx",
            scale=1,
        )
        _write_group_policy_workbook(
            condition_root / f"S2_{condition}_Results.xlsx",
            scale=2,
        )
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": disk_event_map,
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    live_project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": excel_root},
        event_map=live_event_map,
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )

    harmonic_selection_qc.run_processing_harmonic_selection_qc(live_project)
    reloaded_project = Project.load(project_root)
    loaded = harmonic_selection_qc.load_processing_harmonic_selection(
        reloaded_project
    )

    assert loaded.selected_harmonics_hz == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    assert loaded.selection_cache_source == "saved_processing_metadata"


def test_processing_harmonic_selection_qc_uses_project_summation_settings(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    condition_root = excel_root / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {
                    "group_significant_summation_method": "significant_only",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": excel_root},
        event_map={"Faces": 1},
        preprocessing={"group_significant_summation_method": "significant_only"},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.selection_metadata["summation_method"] == "significant_only"
    assert report.selection_metadata["detected_significant_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )
    assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 3.6, 7.2]
    )


def test_processing_harmonic_selection_method_upgrade_error_is_actionable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = SimpleNamespace(
        project_root=tmp_path,
        subjects=("S1",),
        conditions=("Faces",),
        subject_data={"S1": {"Faces": str(tmp_path / "S1_Faces_Results.xlsx")}},
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
        max_frequency_hz=8.4,
        settings=SimpleNamespace(name=harmonic_selection_qc.GROUP_SIGNIFICANT_POLICY_NAME),
        rois={"Posterior": ["O1", "O2"]},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_processing_harmonic_selection_inputs",
        lambda _project, log_func=None: inputs,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "build_group_harmonic_cache_request",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "lookup_cached_group_harmonic_selection",
        lambda _request: SimpleNamespace(
            hit=None,
            reason="Harmonic-selection method version changed since saved harmonics.",
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        harmonic_selection_qc.load_processing_harmonic_selection(object())

    message = str(exc_info.value)
    assert "Settings > Recalculate Harmonics" in message
    assert "current FPVS Toolbox version" in message
    assert "EEG/FIF reprocessing is not required" in message
    assert "method version changed" in message


def test_processing_harmonic_selection_does_not_report_success_without_saved_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    inputs = SimpleNamespace(
        project_root=tmp_path,
        subjects=("S1",),
        conditions=("Faces",),
        subject_data={"S1": {"Faces": str(tmp_path / "S1_Faces_Results.xlsx")}},
        base_frequency_hz=6.0,
        oddball_frequency_hz=1.2,
        max_frequency_hz=8.4,
        settings=SimpleNamespace(name=harmonic_selection_qc.GROUP_SIGNIFICANT_POLICY_NAME),
        rois={"Posterior": ["O1", "O2"]},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_processing_harmonic_selection_inputs",
        lambda _project, log_func=None: inputs,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "build_group_significant_harmonic_selection",
        lambda **_kwargs: SimpleNamespace(to_metadata=lambda: {"selected_harmonics_hz": [1.2]}),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "build_group_harmonic_cache_request",
        lambda **_kwargs: object(),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "lookup_cached_group_harmonic_selection",
        lambda _request: SimpleNamespace(
            hit=None,
            reason="No saved group-significant harmonics.",
        ),
    )

    with pytest.raises(RuntimeError) as exc_info:
        harmonic_selection_qc.run_processing_harmonic_selection_qc(object())

    message = str(exc_info.value)
    assert "calculated but could not be saved" in message
    assert "downstream tools cannot load it" in message
    assert "Settings > Recalculate Harmonics" in message


def test_processing_harmonic_selection_qc_resolves_relative_excel_subfolder(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        subfolders={"excel": "1 - Excel Data Files"},
        event_map={"Faces": 1},
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.workbook_path == project_root / "Quality Check" / "Harmonic_Selection_Summary.xlsx"
    assert report.workbook_path.exists()


def test_processing_harmonic_inputs_omit_excluded_participant_condition(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    faces_root = excel_root / "Faces"
    negative_root = excel_root / "Negative Valence"
    faces_root.mkdir(parents=True)
    negative_root.mkdir(parents=True)
    p1_faces = faces_root / "P1_Faces_Results.xlsx"
    p1_negative = negative_root / "P1_Negative Valence_Results.xlsx"
    p2_negative = negative_root / "P2_Negative Valence_Results.xlsx"
    for path in (p1_faces, p1_negative, p2_negative):
        path.write_text("fixture", encoding="utf-8")
    preprocessing = {
        "manual_excluded_participant_conditions": {
            "P1": ["Negative Valence"]
        }
    }
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1, "Negative Valence": 2},
                "preprocessing": preprocessing,
            }
        ),
        encoding="utf-8",
    )
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1, "Negative Valence": 2},
        preprocessing=preprocessing,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_filter_to_completed_subjects",
        lambda **kwargs: (kwargs["subjects"], kwargs["subject_data"]),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "filter_frequency_domain_subjects",
        lambda _root, subjects, subject_data: (subjects, subject_data, []),
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"]},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_project_spectral_eligibility_domain",
        lambda **_kwargs: ((1,), "fixture-eligibility", ()),
    )

    inputs = harmonic_selection_qc._processing_harmonic_selection_inputs(project)

    assert inputs.subject_data == {
        "P1": {"Faces": str(p1_faces)},
        "P2": {"Negative Valence": str(p2_negative)},
    }
    assert str(p1_negative) not in {
        path
        for participant_data in inputs.subject_data.values()
        for path in participant_data.values()
    }


def test_processing_harmonic_selection_succeeds_after_grid_outlier_exclusion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    faces_root = excel_root / "Faces"
    negative_root = excel_root / "Negative Valence"
    faces_root.mkdir(parents=True)
    negative_root.mkdir(parents=True)
    _write_group_policy_workbook(
        faces_root / "S1_Faces_Results.xlsx",
        scale=1,
    )
    _write_group_policy_workbook(
        faces_root / "S2_Faces_Results.xlsx",
        scale=2,
    )
    _write_group_policy_workbook(
        negative_root / "S3_Negative Valence_Results.xlsx",
        scale=1,
        spacing_hz=0.4,
    )
    preprocessing = {
        "manual_excluded_participant_conditions": {
            "S3": ["Negative Valence"]
        }
    }
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1, "Negative Valence": 2},
                "preprocessing": preprocessing,
            }
        ),
        encoding="utf-8",
    )
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1, "Negative Valence": 2},
        preprocessing=preprocessing,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )

    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    assert report.workbook_path.exists()
    assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )


@pytest.mark.parametrize(
    "profile_id",
    (
        HARMONIC_PROFILE_LEGACY_ID,
        HARMONIC_PROFILE_FIXED_ID,
        HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
        HARMONIC_PROFILE_TWO_CONSECUTIVE_FAILURES_ID,
    ),
)
def test_processing_record_persists_and_loads_every_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    profile_id: str,
) -> None:
    project_root = tmp_path / profile_id
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    preprocessing = {"harmonic_selection_profile": profile_id}
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": preprocessing,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    _write_group_policy_workbook(condition_root / "S2_Faces_Results.xlsx", scale=2)
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1},
        preprocessing=preprocessing,
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"], "Central": ["FZ"]},
    )
    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)
    loaded = harmonic_selection_qc.load_processing_harmonic_selection(project)
    manifest = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )
    active = manifest["tools"]["processing"]["harmonic_selection"]["active"]

    assert report.selection_metadata == active["selection_metadata"]
    assert active["harmonic_selection_profile"] == profile_id
    assert active["harmonic_selection_profile_version"] == "1.0"
    assert active["selection_fingerprint"] == report.selection_metadata[
        "selection_fingerprint"
    ]
    assert loaded.to_metadata()["selection_fingerprint"] == active[
        "selection_fingerprint"
    ]
    assert loaded.selected_harmonics_hz == pytest.approx(
        report.selection_metadata["selected_harmonics_hz"]
    )
    assert all(
        not Path(str(row["path"])).is_absolute()
        for row in active["selection_metadata"]["source_workbook_fingerprints"]
    )

    from Main_App.io import xlsx_read_cache_scope

    uncached = Mock(wraps=harmonic_selection_qc._load_processing_harmonic_selection_uncached)
    monkeypatch.setattr(harmonic_selection_qc, "_load_processing_harmonic_selection_uncached", uncached)
    with xlsx_read_cache_scope(), post_processing_validation_scope():
        first_messages, hit_messages = [], []
        first = harmonic_selection_qc.load_processing_harmonic_selection(project, log_func=first_messages.append)
        repeated = harmonic_selection_qc.load_processing_harmonic_selection(project, log_func=hit_messages.append)
        assert repeated is not first
        assert repeated.to_metadata() == first.to_metadata() == loaded.to_metadata()
        assert hit_messages == first_messages
        assert uncached.call_count == 1

        # Publishing a sibling derivative changes no scientific input.
        manifest["tools"].setdefault("post_processing", {})["artifact_freshness"] = {
            "updated_at": "test publication", "artifacts": {},
        }
        (project_root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
        after_publication = harmonic_selection_qc.load_processing_harmonic_selection(project)
        assert after_publication.to_metadata() == first.to_metadata()
        assert uncached.call_count == 1

        # Even identical bytes with a restored mtime must be revalidated when
        # a source file is replaced, rather than inheriting the cached result.
        path = condition_root / "S1_Faces_Results.xlsx"
        previous = path.stat()
        replacement = path.with_suffix(".replacement")
        replacement.write_bytes(path.read_bytes())
        os.utime(replacement, ns=(previous.st_atime_ns, previous.st_mtime_ns))
        replacement.replace(path)
        replaced = harmonic_selection_qc.load_processing_harmonic_selection(project)
        assert replaced.to_metadata() == first.to_metadata()
        assert uncached.call_count == 2
    harmonic_selection_qc.load_processing_harmonic_selection(project)
    assert uncached.call_count == 3


@pytest.mark.parametrize("profile_id", [HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID, HARMONIC_PROFILE_FIXED_ID])
def test_processing_report_matches_persisted_metadata_for_strict_full_audit_export(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, profile_id: str,
) -> None:
    from Main_App.exports import analysis_ready_workbook
    from Tools.Stats.analysis.dv_policy_group_significant import clear_group_significant_selection_cache

    project_root = tmp_path / profile_id
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    preprocessing = {"harmonic_selection_profile": profile_id}
    manifest_path = project_root / "project.json"
    manifest_path.write_text(json.dumps({
        "schema_version": "2.1.0", "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1}, "preprocessing": preprocessing,
    }), encoding="utf-8")
    workbook = condition_root / "S1_Faces_Results.xlsx"
    _write_group_policy_workbook(workbook, scale=1)
    # A constant local-noise neighborhood legitimately yields an undefined Z
    # diagnostic. Harmonics above 9 Hz also distinguish numeric/lexical key sort.
    full_fft = pd.read_excel(workbook, sheet_name="FullFFT Amplitude (uV)", index_col=0)
    for column in full_fft:
        if 7.4 <= float(str(column).removesuffix("_Hz")) <= 9.4:
            full_fft[column] = 1.0
    eligibility = resolve_spectral_eligibility(
        protocol=TEST_FREQUENCY_PROTOCOL, sampling_rate_hz=128, analyzed_samples=1_280,
        requested_high_pass_hz=0.1, requested_low_pass_hz=12.0,
        applied_high_pass_hz=0.1, applied_low_pass_hz=12.0,
    )
    with pd.ExcelWriter(workbook, engine="openpyxl", mode="a", if_sheet_exists="replace") as writer:
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")
        pd.DataFrame(eligibility.to_rows()).to_excel(writer, sheet_name="Spectral Eligibility", index=False)
    monkeypatch.setattr(harmonic_selection_qc, "load_rois_from_settings", lambda: {"Posterior": ["O1", "O2"]})
    project = SimpleNamespace(project_root=project_root, event_map={"Faces": 1}, preprocessing=preprocessing)
    adaptive_metadata = []
    real_builder = harmonic_selection_qc.build_group_significant_harmonic_selection

    def capture_selection(*args, **kwargs):
        selection = real_builder(*args, **kwargs)
        adaptive_metadata.append(selection.to_metadata())
        return selection

    monkeypatch.setattr(harmonic_selection_qc, "build_group_significant_harmonic_selection", capture_selection)
    expected_harmonics = (
        [1.2, 3.6, 7.2] if profile_id == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID
        else [1.2, 2.4, 3.6, 4.8, 7.2]
    )
    fingerprints = []
    for _run in ("fresh", "cached"):
        if _run == "cached":
            clear_group_significant_selection_cache()
        report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)
        accepted = harmonic_selection_qc.load_processing_harmonic_selection_metadata(Project.load(project_root))
        durable = json.loads(manifest_path.read_text(encoding="utf-8"))["tools"]["processing"]["harmonic_selection"]["active"]["selection_metadata"]
        assert accepted == durable
        assert report.selection_metadata["selected_harmonics_hz"] == pytest.approx(expected_harmonics)
        fingerprints.append(report.selection_metadata["selection_fingerprint"])
        assert fingerprints[-1] == accepted["selection_fingerprint"]
        if profile_id == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID:
            raw_z = adaptive_metadata[-1]["selection_z_by_harmonic"]
            assert 10.8 in raw_z
            if _run == "fresh":
                assert not math.isfinite(raw_z[8.4])
                assert accepted["selection_z_by_harmonic"]["8.4"] is None
            raw = adaptive_metadata[-1]
            normalized = harmonic_selection_qc._json_safe(raw)
            raw_frames = analysis_ready_workbook.build_harmonic_selection_frames(raw)
            normalized_frames = analysis_ready_workbook.build_harmonic_selection_frames(normalized)
            assert raw_frames.keys() == normalized_frames.keys()
            for sheet in raw_frames:
                pd.testing.assert_frame_equal(raw_frames[sheet], normalized_frames[sheet])
            assert harmonic_selection_qc.compute_selection_fingerprint(raw) == (
                harmonic_selection_qc.compute_selection_fingerprint(normalized)
            )
        # Exercise the actual caller/persisted comparison, without replacing
        # either the public loader or the strict export guard.
        frames, source = analysis_ready_workbook._load_selection_frames(
            project_root, selection_metadata=report.selection_metadata,
            expected_release_fingerprint="test-final-release",
        )
        assert frames and source == "processing-time metadata"
        assert analysis_ready_workbook._semantic_metadata_json(report.selection_metadata) == (
            analysis_ready_workbook._semantic_metadata_json(accepted)
        )
        assert report.selection_metadata == accepted
        for change in ("harmonics", "source", "release"):
            tampered = copy.deepcopy(report.selection_metadata)
            if change == "harmonics":
                tampered["selected_harmonics_hz"] = [1.2]
            elif change == "source":
                tampered["source_workbook_fingerprints"][0]["path"] += ".changed"
            else:
                tampered["final_release_receipt_fingerprint"] = "stale-release"
            with pytest.raises(RuntimeError, match="differs from the current persisted"):
                analysis_ready_workbook._load_selection_frames(
                    project_root, selection_metadata=tampered,
                    expected_release_fingerprint="test-final-release",
                )
    assert fingerprints[0] == fingerprints[1]
    if profile_id == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID:
        assert adaptive_metadata[0]["selection_cache_source"] == "computed_this_run_saved_project_metadata"
        assert adaptive_metadata[1]["selection_cache_source"] == "saved_project_metadata"


def test_harmonic_metadata_map_preserves_null_without_accepting_invalid_values() -> None:
    from Tools.Stats.analysis.dv_policy_group_significant import _metadata_float_map

    restored = _metadata_float_map({
        "10.8": None, "1.2": "3.5", "bad": None, "nan": None, "inf": None,
        "2.4": "invalid", "3.6": float("nan"), "4.8": float("inf"),
    })

    assert set(restored) == {1.2, 10.8}
    assert restored[1.2] == 3.5
    assert math.isnan(restored[10.8])


def test_processing_selection_load_migrates_group_cache_only_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1},
        preprocessing={},
    )
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"]},
    )
    report = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    del manifest["tools"]["processing"]["harmonic_selection"]
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    loaded = harmonic_selection_qc.load_processing_harmonic_selection(project)
    migrated = json.loads(manifest_path.read_text(encoding="utf-8"))["tools"][
        "processing"
    ]["harmonic_selection"]["active"]

    assert loaded.selected_harmonics_hz == pytest.approx(
        report.selection_metadata["selected_harmonics_hz"]
    )
    assert migrated["selection_fingerprint"] == loaded.to_metadata()[
        "selection_fingerprint"
    ]


def test_processing_selection_record_rebases_with_copied_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(
            {
                "schema_version": "2.1.0",
                "subfolders": {"excel": "1 - Excel Data Files"},
                "event_map": {"Faces": 1},
                "preprocessing": {},
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    _write_group_policy_workbook(condition_root / "S1_Faces_Results.xlsx", scale=1)
    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_rois_from_settings",
        lambda: {"Posterior": ["O1", "O2"]},
    )
    harmonic_selection_qc.run_processing_harmonic_selection_qc(
        Project.load(project_root)
    )
    copied_root = tmp_path / "Copied Project"
    shutil.copytree(project_root, copied_root, copy_function=shutil.copy2)
    clear_cached_group_harmonic_selections(copied_root)

    loaded = harmonic_selection_qc.load_processing_harmonic_selection(
        Project.load(copied_root)
    )

    assert loaded.selected_harmonics_hz == pytest.approx(
        [1.2, 2.4, 3.6, 4.8, 7.2]
    )


def test_versioned_profile_settings_are_read_from_exact_project_manifest(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "Project"
    project_root.mkdir()
    preprocessing = {
        "harmonic_selection_profile": HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID,
        "harmonic_selection_profile_version": "1.0",
        "group_significant_electrode_scope": "frozen_selection_electrodes",
        "group_significant_selection_electrodes": ["PO8", "PO7", "PO8"],
        "group_significant_z_threshold": 1.64,
    }
    (project_root / "project.json").write_text(
        json.dumps({"preprocessing": preprocessing}),
        encoding="utf-8",
    )
    # Simulate a Project instance whose older normalization surface has not
    # retained the new keys; the processing owner reads their persisted form.
    project = SimpleNamespace(project_root=project_root, preprocessing={})

    settings = harmonic_selection_qc._harmonic_selection_settings(project)

    assert settings.harmonic_selection_profile == HARMONIC_PROFILE_SIGNIFICANT_ONLY_ID
    assert settings.harmonic_selection_profile_version == "1.0"
    assert settings.group_significant_electrode_scope == "frozen_selection_electrodes"
    assert settings.group_significant_selection_electrodes == ("PO7", "PO8")
    assert settings.group_significant_z_threshold == pytest.approx(1.64)


def test_processing_selection_atomic_manifest_failure_preserves_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manifest_path = tmp_path / "project.json"
    original = '{\n  "preserved": true\n}'
    manifest_path.write_text(original, encoding="utf-8")
    monkeypatch.setattr(
        harmonic_selection_qc,
        "_replace_manifest_with_retry",
        lambda _temporary, _manifest: (_ for _ in ()).throw(
            PermissionError("locked")
        ),
    )

    with pytest.raises(PermissionError, match="locked"):
        harmonic_selection_qc._write_manifest_atomic(
            manifest_path,
            {"preserved": False},
        )

    assert manifest_path.read_text(encoding="utf-8") == original
    assert not list(tmp_path.glob(".project.json.harmonic-selection-*.tmp"))


def test_managed_fixed_summed_bca_uses_only_accepted_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    preprocessing = {
        "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
        "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
        "harmonic_selection_profile_version": "1.0",
        "fixed_harmonic_frequencies_hz": "1.2",
    }
    manifest_path = project_root / "project.json"
    manifest = {
        "schema_version": "2.1.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1},
        "preprocessing": preprocessing,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    workbook = condition_root / "S1_Faces_Results.xlsx"
    _write_group_policy_workbook(workbook, scale=1)
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1},
        preprocessing=preprocessing,
    )
    rois = {"Posterior": ["O1", "O2"]}
    monkeypatch.setattr(harmonic_selection_qc, "load_rois_from_settings", lambda: rois)
    harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    # A caller cannot widen an accepted fixed domain ad hoc: the managed
    # project still sums only its accepted 1.2-Hz definition.
    summed = prepare_summed_bca_data(
        subjects=["S1"],
        conditions=["Faces"],
        subject_data={"S1": {"Faces": str(workbook)}},
        base_freq=6.0,
        log_func=lambda _message: None,
        rois=rois,
        dv_policy={
            "name": FIXED_PREDEFINED_POLICY_NAME,
            "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
            "fixed_harmonic_frequencies_hz": "1.2, 2.4",
        },
        project_root=str(project_root),
    )
    assert summed is not None
    assert summed["S1"]["Faces"]["Posterior"] == pytest.approx(1.5)

    # Changing persisted scientific settings without recalculation invalidates
    # the accepted input fingerprint instead of silently redefining Summed BCA.
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["fixed_harmonic_frequencies_hz"] = "1.2, 2.4"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    with pytest.raises(RuntimeError, match="Recalculate Harmonics"):
        prepare_summed_bca_data(
            subjects=["S1"],
            conditions=["Faces"],
            subject_data={"S1": {"Faces": str(workbook)}},
            base_freq=6.0,
            log_func=lambda _message: None,
            rois=rois,
            dv_policy={
                "name": FIXED_PREDEFINED_POLICY_NAME,
                "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
                "fixed_harmonic_frequencies_hz": "1.2, 2.4",
            },
            project_root=str(project_root),
        )


def test_fixed_canonical_profile_drives_stats_ready_schema_and_downstream_reader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    excel_root = project_root / "1 - Excel Data Files"
    preprocessing = {
        "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
        "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
        "harmonic_selection_profile_version": "1.0",
        "fixed_harmonic_frequencies_hz": "1.2, 2.4, 6.0, 7.2",
        # Backend v1 must ignore this obsolete opt-out and still exclude 6 Hz.
        "fixed_harmonic_auto_exclude_base": False,
    }
    manifest = {
        "schema_version": "2.1.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1, "Objects": 2},
        "preprocessing": preprocessing,
    }
    project_root.mkdir(parents=True)
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    for condition, scale in (("Faces", 1), ("Objects", 2)):
        condition_root = excel_root / condition
        condition_root.mkdir(parents=True)
        _write_group_policy_workbook(
            condition_root / f"S1_{condition}_Results.xlsx",
            scale=scale,
        )
    project = SimpleNamespace(
        project_root=project_root,
        event_map=manifest["event_map"],
        preprocessing=preprocessing,
    )
    rois = {"Posterior": ["O1", "O2"]}
    monkeypatch.setattr(harmonic_selection_qc, "load_rois_from_settings", lambda: rois)
    accepted = harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    class _Settings:
        def get(self, _section, option, fallback=""):
            return {"base_freq": "6.0", "bca_upper_limit": "8.4"}.get(
                option,
                fallback,
            )

    monkeypatch.setattr(stats_ready_workbook_mod, "SettingsManager", _Settings)
    monkeypatch.setattr(
        stats_ready_workbook_mod,
        "load_rois_from_settings",
        lambda _manager: rois,
    )
    result = stats_ready_workbook_mod.write_loreta_stats_ready_workbook(project_root)

    selection = pd.read_excel(
        result.workbook_path,
        sheet_name="Harmonic_Selection",
    )
    included = selection.loc[
        selection["included_in_summation"],
        "requested_harmonic_hz",
    ].tolist()
    excluded_base = selection.loc[
        selection["excluded_base_rate"],
        "requested_harmonic_hz",
    ].tolist()
    assert included == pytest.approx([1.2, 2.4, 7.2])
    assert excluded_base == pytest.approx([6.0])
    assert _read_selected_harmonics(result.workbook_path) == (1.2, 2.4, 7.2)

    summary = pd.read_excel(result.workbook_path, sheet_name="Selection_Summary")
    summary_map = dict(zip(summary["Summary Item"], summary["Value"]))
    assert summary_map["Harmonic selection profile ID"] == HARMONIC_PROFILE_FIXED_ID
    assert summary_map["Harmonic selection profile version"] == "1.0"
    assert summary_map["Selection fingerprint"] == accepted.selection_metadata[
        "selection_fingerprint"
    ]


@post_processing_validation_scope()
def test_managed_dv_cache_tracks_reaccepted_selection_and_workbook_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project_root = tmp_path / "Project"
    condition_root = project_root / "1 - Excel Data Files" / "Faces"
    condition_root.mkdir(parents=True)
    preprocessing = {
        "harmonic_selection_policy": FIXED_PREDEFINED_POLICY_NAME,
        "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
        "harmonic_selection_profile_version": "1.0",
        "fixed_harmonic_frequencies_hz": "1.2",
    }
    manifest_path = project_root / "project.json"
    manifest = {
        "schema_version": "2.1.0",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Faces": 1},
        "preprocessing": preprocessing,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    workbook = condition_root / "S1_Faces_Results.xlsx"
    _write_group_policy_workbook(workbook, scale=1)
    project = SimpleNamespace(
        project_root=project_root,
        event_map={"Faces": 1},
        preprocessing=preprocessing,
    )
    rois = {"Posterior": ["O1", "O2"]}
    monkeypatch.setattr(harmonic_selection_qc, "load_rois_from_settings", lambda: rois)
    dv_policies._DV_DATA_CACHE.clear()
    harmonic_selection_qc.run_processing_harmonic_selection_qc(project)

    caller_policy = {
        "name": FIXED_PREDEFINED_POLICY_NAME,
        "harmonic_selection_profile": HARMONIC_PROFILE_FIXED_ID,
        "fixed_harmonic_frequencies_hz": "1.2",
    }
    first = prepare_summed_bca_data(
        subjects=["S1"],
        conditions=["Faces"],
        subject_data={"S1": {"Faces": str(workbook)}},
        base_freq=6.0,
        log_func=lambda _message: None,
        rois=rois,
        dv_policy=caller_policy,
        project_root=str(project_root),
    )
    assert first is not None
    assert first["S1"]["Faces"]["Posterior"] == pytest.approx(1.5)

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["fixed_harmonic_frequencies_hz"] = "2.4"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    harmonic_selection_qc.run_processing_harmonic_selection_qc(
        project,
        force_recalculate=True,
    )
    second = prepare_summed_bca_data(
        subjects=["S1"],
        conditions=["Faces"],
        subject_data={"S1": {"Faces": str(workbook)}},
        base_freq=6.0,
        log_func=lambda _message: None,
        rois=rois,
        # The accepted canonical profile, not this stale caller snapshot, wins.
        dv_policy=caller_policy,
        project_root=str(project_root),
    )
    assert second is not None
    assert second["S1"]["Faces"]["Posterior"] == pytest.approx(100.0)

    _write_group_policy_workbook(workbook, scale=12345)
    with pytest.raises(RuntimeError, match="Recalculate Harmonics"):
        prepare_summed_bca_data(
            subjects=["S1"],
            conditions=["Faces"],
            subject_data={"S1": {"Faces": str(workbook)}},
            base_freq=6.0,
            log_func=lambda _message: None,
            rois=rois,
            dv_policy=caller_policy,
            project_root=str(project_root),
        )
    dv_policies._DV_DATA_CACHE.clear()


def _write_group_policy_workbook(
    path: Path,
    *,
    scale: int,
    spacing_hz: float = 0.1,
) -> None:
    frequency_values = [
        round(spacing_hz * idx, 4)
        for idx in range(0, int(round(12.0 / spacing_hz)) + 1)
    ]
    fft_values = []
    for idx, freq in enumerate(frequency_values):
        value = 20.0 if freq in {1.2, 3.6, 7.2} else (1.2 if idx % 2 == 0 else 0.8)
        fft_values.append(value)
    full_fft = pd.DataFrame(
        {
            f"{freq:.4f}_Hz": [value, value, value]
            for freq, value in zip(frequency_values, fft_values)
        },
        index=["O1", "O2", "FZ"],
    )
    full_fft.index.name = "Electrode"
    bca = pd.DataFrame(
        {
            "1.2000_Hz": [1.0 * scale, 2.0 * scale, 0.5 * scale],
            "2.4000_Hz": [100.0, 100.0, 100.0],
            "3.6000_Hz": [0.5, 0.5, 0.1],
            "4.8000_Hz": [100.0, 100.0, 100.0],
            "6.0000_Hz": [100.0, 100.0, 100.0],
            "7.2000_Hz": [1.0, 1.0, 0.1],
        },
        index=["O1", "O2", "FZ"],
    )
    bca.index.name = "Electrode"
    with pd.ExcelWriter(path, engine="openpyxl") as writer:
        bca.to_excel(writer, sheet_name="BCA (uV)")
        full_fft.to_excel(writer, sheet_name="FullFFT Amplitude (uV)")
        if spacing_hz == 0.1:
            eligibility = resolve_spectral_eligibility(
                protocol=TEST_FREQUENCY_PROTOCOL,
                sampling_rate_hz=128,
                analyzed_samples=1_280,
                requested_high_pass_hz=0.1,
                requested_low_pass_hz=11.0,
                applied_high_pass_hz=0.1,
                applied_low_pass_hz=11.0,
            )
            pd.DataFrame(eligibility.to_rows()).to_excel(
                writer,
                sheet_name="Spectral Eligibility",
                index=False,
            )
