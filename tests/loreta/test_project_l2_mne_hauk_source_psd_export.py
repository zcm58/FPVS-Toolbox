from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import mne
import numpy as np
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Main_App.exports.source_time_domain_export import write_source_ready_time_domain_derivatives
from Main_App.processing.processing_ledger import PROCESSING_FINGERPRINT_VERSION
from Main_App.projects.project import Project
from Tools.LORETA_Visualizer.source_producers.hauk_source_psd import (
    HAUK_2021_REFERENCE_DOI,
    HAUK_REFERENCE_CODE_URL,
    HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID,
    HAUK_SOURCE_PSD_METHOD_ID,
    SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
    SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
)
from Tools.LORETA_Visualizer.source_producers.l2_mne_cortical import L2MNECorticalForwardModel
from Tools.LORETA_Visualizer.source_producers.project_inputs import ProjectSourceParticipantSelection
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_export import (
    MneFsaverageSourcePsdModel,
    ProjectL2MNEExportError,
    _array_content_sha256,
    _source_aligned_leadfield,
)
from Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export import (
    DEFAULT_PROJECT_HAUK_SOURCE_PSD_MANIFEST_NAME,
    ProjectL2MNEHaukSourcePsdExportError,
    default_project_l2_mne_hauk_source_psd_output_dir,
    write_project_l2_mne_hauk_source_psd_payloads,
)
from Tools.LORETA_Visualizer.source_producers.project_time_domain_inputs import (
    ProjectTimeDomainInputError,
)
import Tools.LORETA_Visualizer.source_producers.project_l2_mne_hauk_source_psd_export as export_module


SFREQ = 200.0
N_TIMES = 200
PROCESSING_FINGERPRINT = "f" * 64


def test_source_aligned_leadfield_collapses_only_the_display_descriptor() -> None:
    native = np.asarray(
        [
            [3.0, 4.0, 0.0, 0.0, 0.0, 5.0],
            [0.0, 0.0, 2.0, 1.0, 2.0, 2.0],
        ]
    )

    collapsed = _source_aligned_leadfield(native, source_count=2)

    np.testing.assert_allclose(collapsed, [[5.0, 5.0], [2.0, 3.0]])
    np.testing.assert_array_equal(
        _source_aligned_leadfield(collapsed, source_count=2),
        collapsed,
    )


def test_source_aligned_leadfield_rejects_incompatible_orientation_count() -> None:
    with pytest.raises(ProjectL2MNEExportError, match="one or three orientation columns"):
        _source_aligned_leadfield(np.ones((64, 5)), source_count=2)


def test_native_leadfield_fingerprint_distinguishes_equal_orientation_norms() -> None:
    first = np.asarray([[3.0, 4.0, 0.0]])
    rotated = np.asarray([[4.0, 3.0, 0.0]])

    np.testing.assert_allclose(
        _source_aligned_leadfield(first, source_count=1),
        _source_aligned_leadfield(rotated, source_count=1),
    )
    assert _array_content_sha256(first) != _array_content_sha256(rotated)


def test_project_source_psd_export_streams_inputs_writes_payloads_and_reuses_cache(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(tmp_path, participants=("P01",))
    _write_time_domain_derivative(project.project_root, participant_id="P01")
    model = _source_psd_model()
    calls: list[str] = []
    pick_ori_calls: list[str | None] = []

    first = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        project_root=project.project_root,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable(
            calls,
            pick_ori_calls=pick_ori_calls,
        ),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert first.manifest_path.name == DEFAULT_PROJECT_HAUK_SOURCE_PSD_MANIFEST_NAME
    assert first.manifest_path.is_file()
    assert first.participant_sidecar_path.is_file()
    assert first.validation_report_path is not None and first.validation_report_path.is_file()
    assert (
        first.validation_report_markdown_path is not None
        and first.validation_report_markdown_path.is_file()
    )
    assert first.producer_result.method_id == HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID
    assert first.method_id == HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID
    assert first.source_orientation_mode == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    assert first.selected_harmonics_hz == (20.0,)
    assert first.included_participants == ("P01",)
    assert first.cache_hit_count == 0
    assert first.cache_miss_count == 1
    assert calls == ["P01"]
    assert pick_ori_calls == ["normal"]
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert (
        manifest["metadata"]["producer_method"]
        == HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID
    )
    assert manifest["metadata"]["source_psd_method"]["source_orientation_mode"] == (
        SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    )
    assert manifest["metadata"]["reference_publication_doi"] == HAUK_2021_REFERENCE_DOI
    assert manifest["metadata"]["reference_code_repository"] == HAUK_REFERENCE_CODE_URL
    participant_sidecar = json.loads(first.participant_sidecar_path.read_text(encoding="utf-8"))
    assert participant_sidecar["metadata"]["reference_publication_doi"] == HAUK_2021_REFERENCE_DOI
    payload = json.loads(
        (first.output_dir / manifest["conditions"][0]["file"]).read_text(encoding="utf-8")
    )
    assert payload["metadata"]["config_source_psd_method_metadata"][
        "reference_publication_doi"
    ] == HAUK_2021_REFERENCE_DOI
    assert payload["metadata"]["config_source_orientation_mode"] == (
        SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    )
    validation_report = json.loads(first.validation_report_path.read_text(encoding="utf-8"))
    assert validation_report["input_summary"]["selected_harmonics_hz"] == [20.0]
    assert validation_report["input_summary"]["condition_count"] == 1
    assert validation_report["input_summary"]["condition_summaries"][0][
        "included_subject_count"
    ] == 1
    assert validation_report["input_summary"]["condition_summaries"][0][
        "input_file_count"
    ] == 1
    assert validation_report["input_summary"]["candidate_noise_offsets"] == [
        *range(-10, -1),
        *range(2, 11),
    ]
    assert validation_report["input_summary"][
        "required_candidate_noise_bin_count"
    ] == 18
    assert validation_report["input_summary"][
        "retained_noise_bin_count_after_extreme_drop"
    ] == 16
    assert validation_report["input_summary"]["min_noise_bins"] == 18

    def fail_if_recomputed(**_kwargs: Any) -> Any:
        raise AssertionError("valid compact source-PSD cache entry should have been reused")

    second = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=fail_if_recomputed,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert second.cache_hit_count == 1
    assert second.cache_miss_count == 0
    assert second.manifest_path == first.manifest_path


def test_project_source_psd_orientation_modes_have_distinct_methods_and_caches(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(tmp_path, participants=("P01",))
    _write_time_domain_derivative(project.project_root, participant_id="P01")
    model = _source_psd_model()
    calls: list[str] = []
    pick_ori_calls: list[str | None] = []
    source_psd_callable = _source_psd_callable(
        calls,
        pick_ori_calls=pick_ori_calls,
    )

    normal = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=source_psd_callable,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )
    legacy = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        source_orientation_mode=SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=source_psd_callable,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert normal.method_id == HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID
    assert normal.source_orientation_mode == SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL
    assert legacy.method_id == HAUK_SOURCE_PSD_METHOD_ID
    assert legacy.source_orientation_mode == SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM
    assert normal.cache_hit_count == 0 and normal.cache_miss_count == 1
    assert legacy.cache_hit_count == 0 and legacy.cache_miss_count == 1
    assert pick_ori_calls == ["normal", None]

    cache_metadata_paths = sorted(
        (project.project_root / ".fpvs_processing" / "source_psd_cache" / "v1").glob(
            "*.json"
        )
    )
    assert len(cache_metadata_paths) == 2
    cached_methods = {
        (
            metadata["key_payload"]["method_metadata"]["method_id"],
            metadata["key_payload"]["method_metadata"]["source_orientation_mode"],
        )
        for metadata in (
            json.loads(path.read_text(encoding="utf-8"))
            for path in cache_metadata_paths
        )
    }
    assert cached_methods == {
        (
            HAUK_SOURCE_PSD_CORTICAL_NORMAL_METHOD_ID,
            SOURCE_ORIENTATION_MODE_CORTICAL_NORMAL,
        ),
        (
            HAUK_SOURCE_PSD_METHOD_ID,
            SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
        ),
    }

    def fail_if_recomputed(**_kwargs: Any) -> Any:
        raise AssertionError("orientation-specific compact cache entry should have been reused")

    normal_cached = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=fail_if_recomputed,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )
    legacy_cached = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=model,
        source_orientation_mode=SOURCE_ORIENTATION_MODE_LEGACY_MNE_PSD_POWER_NORM,
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=fail_if_recomputed,
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert normal_cached.cache_hit_count == 1 and normal_cached.cache_miss_count == 0
    assert legacy_cached.cache_hit_count == 1 and legacy_cached.cache_miss_count == 0


def test_project_source_psd_export_loads_harmonics_from_the_active_project(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_with_ledger(tmp_path, participants=("P01",))
    _write_time_domain_derivative(project.project_root, participant_id="P01")
    seen_projects: list[Any] = []

    class _Selection:
        selected_harmonics_hz = (20.0,)

        @staticmethod
        def to_metadata() -> dict[str, Any]:
            return {
                "harmonic_policy": "group_significant",
                "selected_harmonics_hz": [20.0],
                "selection_z_by_harmonic": {20.0: 5.1},
                "selection_cache_source": "saved_processing_metadata",
                "selection_cache_saved_at": "2026-07-16T10:00:00Z",
                "selection_cache_key": "harmonic-cache-key",
            }

    def fake_load_processing_harmonics(active_project: Any, **_kwargs: Any) -> _Selection:
        seen_projects.append(active_project)
        return _Selection()

    monkeypatch.setattr(
        export_module,
        "load_processing_harmonic_selection",
        fake_load_processing_harmonics,
    )

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert seen_projects == [project]
    assert result.selected_harmonics_hz == (20.0,)
    cache_metadata = json.loads(
        next(
            (project.project_root / ".fpvs_processing" / "source_psd_cache" / "v1").glob(
                "*.json"
            )
        ).read_text(encoding="utf-8")
    )
    cached_selection = cache_metadata["key_payload"]["method_metadata"][
        "custom_metadata"
    ]["harmonic_selection"]
    assert cached_selection["selection_z_by_harmonic"] == {"20.0": 5.1}
    assert set(cached_selection).isdisjoint(
        {
            "selection_cache_source",
            "selection_cache_saved_at",
            "selection_cache_key",
        }
    )
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    manifest_selection = manifest["metadata"]["source_psd_method"][
        "custom_metadata"
    ]["harmonic_selection"]
    assert manifest_selection["selection_cache_source"] == "saved_processing_metadata"
    assert manifest_selection["selection_cache_saved_at"] == "2026-07-16T10:00:00Z"
    assert manifest_selection["selection_cache_key"] == "harmonic-cache-key"


def test_project_source_psd_export_refuses_missing_completed_participant_derivative(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02"),
        entry_changes={
            "P01": {"source_derivative_status": "complete"},
            "P02": {"source_derivative_status": "complete"},
        },
    )
    _write_time_domain_derivative(project.project_root, participant_id="P01")

    with pytest.raises(ProjectTimeDomainInputError, match="missing for: P02"):
        write_project_l2_mne_hauk_source_psd_payloads(
            project=project,
            source_psd_model=_source_psd_model(),
            selected_harmonics_hz=(20.0,),
            compute_source_psd_func=_source_psd_callable([]),
            cluster_mask_enabled=False,
        )


def test_project_source_psd_export_applies_shared_project_exclusions(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = _project_with_ledger(tmp_path, participants=("P01", "P02"))
    _write_time_domain_derivative(project.project_root, participant_id="P01")

    monkeypatch.setattr(
        export_module,
        "project_source_participant_selection",
        lambda *_args, **_kwargs: ProjectSourceParticipantSelection(
            excluded_subjects=("P02",),
            flagged_subjects=("P02",),
        ),
    )

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert result.included_participants == ("P01",)
    assert result.excluded_subjects == ("P02",)
    assert [record.participant_id for record in result.project_inputs.records] == ["P01"]


def test_project_source_psd_export_validates_canonical_group_manifest_folder(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01",),
        group_id="control",
        group_folder="Control Group",
    )
    _write_time_domain_derivative(
        project.project_root,
        participant_id="P01",
        group_id="control",
        group_folder="Control Group",
    )

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert result.project_inputs.records[0].group_id == "control"
    assert result.project_inputs.records[0].group_folder == "Control Group"


def test_project_source_psd_export_splits_multi_group_summaries_and_validation(
    tmp_path: Path,
) -> None:
    participant_groups = {
        "P01": ("control", "Control Group"),
        "P02": ("patient", "Patient Group"),
    }
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02"),
        participant_groups=participant_groups,
    )
    for participant_id, (group_id, group_label) in participant_groups.items():
        _write_time_domain_derivative(
            project.project_root,
            participant_id=participant_id,
            group_id=group_id,
            group_folder=group_label,
        )

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["metadata"]["group_summary_policy"] == (
        "separate_canonical_project_groups"
    )
    assert [condition["id"] for condition in manifest["conditions"]] == [
        "control_21_mean",
        "patient_21_mean",
    ]
    assert [condition["label"] for condition in manifest["conditions"]] == [
        "Control Group - Condition A Raw mean z-score",
        "Patient Group - Condition A Raw mean z-score",
    ]
    expected_participants = {
        "control": ["P01"],
        "patient": ["P02"],
    }
    for manifest_condition in manifest["conditions"]:
        group_provenance = manifest_condition["metadata"]["project_group"]
        group_id = group_provenance["group_id"]
        assert group_provenance["group_split_applied"] is True
        assert group_provenance["canonical_condition_id"] == "21"
        assert group_provenance["canonical_condition_label"] == "Condition A"
        assert group_provenance["participant_ids"] == expected_participants[group_id]
        payload = json.loads(
            (result.output_dir / manifest_condition["file"]).read_text(encoding="utf-8")
        )
        assert payload["metadata"]["participant_count"] == 1
        assert payload["metadata"]["participant_ids"] == expected_participants[group_id]
        assert payload["metadata"]["condition_group_id"] == group_id
        assert payload["metadata"]["condition_group_split_applied"] is True

    sidecar = json.loads(result.participant_sidecar_path.read_text(encoding="utf-8"))
    assert [row["condition_id"] for row in sidecar["conditions"]] == [
        "control_21",
        "patient_21",
    ]
    assert [
        [participant["participant_id"] for participant in row["participants"]]
        for row in sidecar["conditions"]
    ] == [["P01"], ["P02"]]
    assert [
        row["metadata"]["project_group"]["group_id"]
        for row in sidecar["conditions"]
    ] == ["control", "patient"]

    assert result.validation_report_path is not None
    validation = json.loads(result.validation_report_path.read_text(encoding="utf-8"))
    assert validation["input_summary"]["condition_count"] == 2
    assert validation["input_summary"]["condition_summaries"] == [
        {
            "condition": "Control Group - Condition A",
            "input_file_count": 1,
            "workbook_count": 0,
            "included_subject_count": 1,
            "included_subjects": ["P01"],
            "flagged_subjects": [],
        },
        {
            "condition": "Patient Group - Condition A",
            "input_file_count": 1,
            "workbook_count": 0,
            "included_subject_count": 1,
            "included_subjects": ["P02"],
            "flagged_subjects": [],
        },
    ]


def test_project_source_psd_export_keeps_single_group_condition_identity(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01",),
        group_id="control",
        group_folder="Control Group",
    )
    _write_time_domain_derivative(
        project.project_root,
        participant_id="P01",
        group_id="control",
        group_folder="Control Group",
    )

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["metadata"]["group_summary_policy"] == "single_project_cohort"
    assert manifest["conditions"][0]["id"] == "21_mean"
    assert manifest["conditions"][0]["label"] == "Condition A Raw mean z-score"
    assert manifest["conditions"][0]["metadata"]["project_group"]["group_id"] == (
        "control"
    )
    assert manifest["conditions"][0]["metadata"]["project_group"][
        "group_split_applied"
    ] is False


@pytest.mark.parametrize(
    ("entry_changes", "match"),
    [
        (
            {"P02": {"processing_fingerprint": "e" * 64}},
            "do not share one current processing fingerprint",
        ),
        (
            {"P01": {"processing_fingerprint_version": "processing_fingerprint_v7"}},
            "current processing fingerprint version",
        ),
        (
            {"P01": {"expected_outputs": []}},
            "condition expectations",
        ),
        (
            {"P02": {"status": "failed"}},
            "Source participant P02 is not completed",
        ),
    ],
)
def test_project_source_psd_export_rejects_stale_or_invalid_ledger_sets(
    tmp_path: Path,
    entry_changes: dict[str, dict[str, Any]],
    match: str,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02") if "P02" in entry_changes else ("P01",),
        entry_changes=entry_changes,
    )

    with pytest.raises(ProjectL2MNEHaukSourcePsdExportError, match=match):
        write_project_l2_mne_hauk_source_psd_payloads(
            project=project,
            source_psd_model=_source_psd_model(),
            selected_harmonics_hz=(20.0,),
            compute_source_psd_func=_source_psd_callable([]),
            cluster_mask_enabled=False,
        )


def test_project_source_psd_export_uses_complete_case_cohort_and_records_omissions(
    tmp_path: Path,
) -> None:
    conditions = {"Condition A": 21, "Condition B": 22}
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02", "P03"),
        event_map=conditions,
        entry_changes={
            "P01": {"source_derivative_status": "complete"},
            "P02": {
                "condition_completeness": "partial",
                "missing_condition_labels": ["Condition B"],
                "source_derivative_status": "incomplete",
                "source_derivative_warning": "Missing source epoch condition(s): Condition B",
            },
            "P03": {
                "source_derivative_status": "incomplete",
                "source_derivative_warning": "Windows path publication failed",
            },
        },
    )
    _write_time_domain_derivative(
        project.project_root,
        participant_id="P01",
        conditions=conditions,
    )
    calls: list[str] = []
    progress: list[str] = []

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable(calls),
        aggregations=("mean",),
        cluster_mask_enabled=False,
        progress_callback=progress.append,
    )

    assert result.included_participants == ("P01",)
    assert result.excluded_subjects == ()
    assert [record.participant_id for record in result.project_inputs.records] == [
        "P01",
        "P01",
    ]
    assert len(calls) == 1
    assert result.cache_miss_count == 1
    assert result.cache_hit_count == 1
    assert [item.participant_id for item in result.source_ineligible_participants] == [
        "P02",
        "P03",
    ]
    assert result.source_ineligible_participants[0].to_metadata() == {
        "participant_id": "P02",
        "group_id": None,
        "reason_code": "incomplete_condition_set",
        "detail": "Missing canonical condition output(s): Condition B",
        "missing_condition_labels": ["Condition B"],
        "source_derivative_status": "incomplete",
        "scope": "all_source_conditions",
    }
    assert result.source_ineligible_participants[1].reason_code == (
        "source_derivative_incomplete"
    )
    assert any("omitting P02, P03 from every source condition" in item for item in progress)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    participant_sidecar = json.loads(
        result.participant_sidecar_path.read_text(encoding="utf-8")
    )
    for payload in (manifest, participant_sidecar):
        assert payload["metadata"]["participant_eligibility_policy"] == (
            "complete_case_all_canonical_conditions_v1"
        )
        assert payload["metadata"]["included_participants"] == ["P01"]
        assert [
            item["participant_id"]
            for item in payload["metadata"]["source_ineligible_participants"]
        ] == ["P02", "P03"]

    validation = json.loads(result.validation_report_path.read_text(encoding="utf-8"))
    assert validation["input_summary"]["source_cohort_status"] == (
        "complete_with_warnings"
    )
    assert [
        item["participant_id"]
        for item in validation["input_summary"]["source_ineligible_participants"]
    ] == ["P02", "P03"]
    validation_markdown = result.validation_report_markdown_path.read_text(
        encoding="utf-8"
    )
    assert "| P02 | incomplete_condition_set |" in validation_markdown
    assert "| P03 | source_derivative_incomplete |" in validation_markdown


def test_project_source_psd_export_fails_when_every_participant_is_source_ineligible(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01",),
        entry_changes={
            "P01": {
                "condition_completeness": "partial",
                "missing_condition_labels": ["Condition A"],
                "source_derivative_status": "incomplete",
            }
        },
    )

    with pytest.raises(
        ProjectL2MNEHaukSourcePsdExportError,
        match="No completed, source-eligible participants remain.*P01",
    ):
        write_project_l2_mne_hauk_source_psd_payloads(
            project=project,
            source_psd_model=_source_psd_model(),
            selected_harmonics_hz=(20.0,),
            compute_source_psd_func=_source_psd_callable([]),
            cluster_mask_enabled=False,
        )


def test_project_source_psd_export_records_explicit_ledger_exclusions(
    tmp_path: Path,
) -> None:
    project = _project_with_ledger(
        tmp_path,
        participants=("P01", "P02"),
        entry_changes={"P02": {"status": "excluded"}},
    )
    _write_time_domain_derivative(project.project_root, participant_id="P01")

    result = write_project_l2_mne_hauk_source_psd_payloads(
        project=project,
        source_psd_model=_source_psd_model(),
        selected_harmonics_hz=(20.0,),
        compute_source_psd_func=_source_psd_callable([]),
        aggregations=("mean",),
        cluster_mask_enabled=False,
    )

    assert result.included_participants == ("P01",)
    assert result.excluded_subjects == ("P02",)


def test_project_source_psd_export_confines_root_and_output(tmp_path: Path) -> None:
    project = _project_with_ledger(tmp_path / "project", participants=("P01",))
    other_root = tmp_path / "other"
    other_root.mkdir()

    with pytest.raises(ValueError, match="must match the active project"):
        write_project_l2_mne_hauk_source_psd_payloads(
            project=project,
            project_root=other_root,
            selected_harmonics_hz=(20.0,),
        )
    with pytest.raises(ValueError, match="must stay inside the project root"):
        write_project_l2_mne_hauk_source_psd_payloads(
            project=project,
            output_dir=tmp_path / "outside",
            selected_harmonics_hz=(20.0,),
        )

    assert default_project_l2_mne_hauk_source_psd_output_dir(project.project_root).is_relative_to(
        project.project_root
    )


def _project_with_ledger(
    root: Path,
    *,
    participants: tuple[str, ...],
    entry_changes: dict[str, dict[str, Any]] | None = None,
    group_id: str | None = None,
    group_folder: str | None = None,
    participant_groups: dict[str, tuple[str, str]] | None = None,
    event_map: dict[str, int] | None = None,
) -> Project:
    root.mkdir(parents=True, exist_ok=True)
    canonical_event_map = event_map or {"Condition A": 21}
    groups: dict[str, Any] = {}
    project_participants: dict[str, Any] = {}
    if participant_groups is not None:
        if group_id is not None:
            raise ValueError("participant_groups and group_id are mutually exclusive test inputs")
        for participant_id in participants:
            participant_group_id, participant_group_label = participant_groups[participant_id]
            groups.setdefault(
                participant_group_id,
                {
                    "label": participant_group_label,
                    "folder_name": participant_group_label,
                    "raw_input_folder": str(root / "Raw" / participant_group_id),
                },
            )
            project_participants[participant_id] = {"group_id": participant_group_id}
    elif group_id is not None:
        groups[group_id] = {
            "label": group_folder or group_id,
            "folder_name": group_folder or group_id,
            "raw_input_folder": str(root / "Raw" / group_id),
        }
        project_participants = {
            participant_id: {"group_id": group_id}
            for participant_id in participants
        }
    project = Project.load(
        root,
        manifest={
            "name": "Source PSD Test",
            "event_map": canonical_event_map,
            "groups": groups,
            "participants": project_participants,
        },
    )
    entries: dict[str, dict[str, Any]] = {}
    for participant_id in participants:
        participant_group_id = (
            participant_groups[participant_id][0]
            if participant_groups is not None
            else group_id
        )
        entries[participant_id] = {
            "participant_id": participant_id,
            "group_id": participant_group_id,
            "status": "completed",
            "condition_completeness": "complete",
            "missing_condition_labels": [],
            "processing_fingerprint": PROCESSING_FINGERPRINT,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
            "expected_outputs": [
                str(
                    root
                    / "1 - Excel Data Files"
                    / condition_label
                    / f"{participant_id}_{condition_label}_Results.xlsx"
                )
                for condition_label in canonical_event_map
            ],
        }
    for participant_id, changes in (entry_changes or {}).items():
        entries[participant_id].update(changes)
    ledger_path = root / ".fpvs_processing" / "processing_ledger.json"
    ledger_path.parent.mkdir(parents=True, exist_ok=True)
    ledger_path.write_text(
        json.dumps({"schema_version": 1, "entries": entries}, indent=2),
        encoding="utf-8",
    )
    return project


def _write_time_domain_derivative(
    root: Path,
    *,
    participant_id: str,
    group_id: str | None = None,
    group_folder: str | None = None,
    conditions: dict[str, int] | None = None,
) -> None:
    canonical_conditions = conditions or {"Condition A": 21}
    times = np.arange(N_TIMES, dtype=float) / SFREQ
    repetitions: list[np.ndarray] = []
    for repetition in range(2):
        repetitions.append(
            np.vstack(
                [
                    (channel + 1) * 1e-8 * np.sin(
                        2.0 * np.pi * 5.0 * times + channel * 0.03 + repetition * 0.1
                    )
                    for channel in range(len(DEFAULT_ELECTRODE_NAMES_64))
                ]
            )
        )
    info = mne.create_info(list(DEFAULT_ELECTRODE_NAMES_64), sfreq=SFREQ, ch_types="eeg")
    info.set_montage("biosemi64", on_missing="raise")
    epochs = mne.EpochsArray(
        np.stack(repetitions),
        info,
        tmin=0.0,
        baseline=None,
        verbose=False,
    )
    epochs.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    epochs.apply_proj(verbose=False)
    write_source_ready_time_domain_derivatives(
        project_root=root,
        participant_id=participant_id,
        group_id=group_id,
        group_folder=group_folder,
        condition_epochs={label: epochs for label in canonical_conditions},
        condition_ids=canonical_conditions,
        crop_provenance_by_condition={
            label: {
                "crop_mode": "55_onbin",
                "N": N_TIMES,
                "N_step": N_TIMES,
                "N_mod_step": 0,
            }
            for label in canonical_conditions
        },
        processing_provenance={
            "processing_fingerprint": PROCESSING_FINGERPRINT,
            "processing_fingerprint_version": PROCESSING_FINGERPRINT_VERSION,
        },
    )


def _source_psd_model() -> MneFsaverageSourcePsdModel:
    points = np.asarray(
        [
            [-20.0, 0.0, 0.0],
            [-10.0, 10.0, 0.0],
            [10.0, 0.0, 0.0],
            [20.0, 10.0, 0.0],
        ]
    )
    faces = np.asarray([[0, 1, 2], [1, 2, 3]], dtype=int)
    leadfield = np.arange(64 * 4, dtype=float).reshape(64, 4) / 1000.0 + 0.01
    forward = L2MNECorticalForwardModel(
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        source_points=points,
        leadfield=leadfield,
        faces=faces,
        metadata={
            "inverse_backend": "test_injected_mne",
            "source_spacing": "test",
            "model_sfreq_hz": SFREQ,
        },
    )
    info = mne.create_info(list(DEFAULT_ELECTRODE_NAMES_64), sfreq=SFREQ, ch_types="eeg")
    info.set_montage("biosemi64", on_missing="raise")
    return MneFsaverageSourcePsdModel(
        forward_model=forward,
        info=info,
        inverse_operator={"source_count": len(points)},
    )


def _source_psd_callable(
    calls: list[str],
    *,
    pick_ori_calls: list[str | None] | None = None,
):
    def compute_source_psd(**kwargs: Any) -> SimpleNamespace:
        raw = kwargs["raw"]
        calls.append("P01" if len(calls) == 0 else f"call-{len(calls) + 1}")
        if pick_ori_calls is not None:
            pick_ori_calls.append(kwargs["pick_ori"])
        df = float(raw.info["sfreq"]) / int(kwargs["n_fft"])
        first_bin = int(round(float(kwargs["fmin"]) / df))
        last_bin = int(round(float(kwargs["fmax"]) / df))
        frequencies = np.arange(first_bin, last_bin + 1, dtype=float) * df
        source_count = int(kwargs["inverse_operator"]["source_count"])
        amplitudes = (
            1.0
            + np.arange(source_count, dtype=float)[:, None] * 0.05
            + frequencies[None, :] * 0.02
        )
        amplitudes[:, np.isclose(frequencies, 20.0)] += 1.5
        return SimpleNamespace(data=amplitudes**2, times=frequencies)

    return compute_source_psd
