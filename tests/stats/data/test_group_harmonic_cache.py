from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

from Main_App.projects.project import Project
from Tools.Stats.data import group_harmonic_cache as cache_mod
from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
)
from Tools.Stats.data.group_harmonic_cache import (
    GROUP_HARMONIC_METHOD_VERSION,
    PREPROCESSING_ORDER_VERSION_LABEL,
    PROCESSING_FINGERPRINT_VERSION_LABEL,
    build_group_harmonic_cache_request,
    build_project_processing_signature,
    clear_cached_group_harmonic_selections,
    lookup_cached_group_harmonic_selection,
    save_cached_group_harmonic_selection,
)


def _write_manifest(project_root: Path, *, high_pass: float = 0.1) -> None:
    project_root.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema_version": "2.1.0",
        "input_folder": "Input",
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "event_map": {"Face": 1, "Object": 2},
        "preprocessing": {
            "low_pass": 50.0,
            "high_pass": high_pass,
            "downsample": 256,
            "rejection_z": 5.0,
            "epoch_start_s": -1.0,
            "epoch_end_s": 125.0,
            "ref_chan1": "EXG1",
            "ref_chan2": "EXG2",
            "max_chan_idx_keep": 64,
            "max_bad_chans": 10,
            "max_parallel_workers_override": 0,
            "stim_channel": "Status",
        },
        "groups": {
            "control": {
                "label": "Control",
                "folder_name": "Control",
                "raw_input_folder": "Input",
            }
        },
        "participants": {"S1": {"group_id": "control"}},
    }
    (project_root / "project.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def _request(project_root: Path, workbook: Path):
    return build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=["S1"],
        conditions=["Face"],
        subject_data={"S1": {"Face": str(workbook)}},
        base_frequency_hz=6.0,
        max_freq_hz=8.4,
        settings=normalize_dv_policy({"name": GROUP_SIGNIFICANT_POLICY_NAME}),
    )


def _multi_request(
    project_root: Path,
    *,
    subjects: list[str],
    conditions: list[str],
    subject_data: dict[str, dict[str, str]],
):
    return build_group_harmonic_cache_request(
        project_root=project_root,
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_frequency_hz=6.0,
        max_freq_hz=8.4,
        settings=normalize_dv_policy({"name": GROUP_SIGNIFICANT_POLICY_NAME}),
    )


def _write_frequency_domain_qc_state(
    project_root: Path,
    *,
    downstream_outputs_stale: bool,
    manual_participant_exclusions: list[str] | None = None,
) -> None:
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    tools = manifest.setdefault("tools", {})
    tools["frequency_domain_qc"] = {
        "method_version": "frequency_domain_qc_v1",
        "thresholds": {"absolute_z_threshold": 3.0},
        "auto_participant_electrode_exclusions": [],
        "auto_participant_exclusions": [],
        "manual_participant_exclusions": list(
            manual_participant_exclusions or []
        ),
        "downstream_outputs_stale": downstream_outputs_stale,
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")


def _selection_metadata() -> dict[str, object]:
    return {
        "harmonic_policy": "group_level_significant_harmonics",
        "selected_harmonics_hz": [1.2, 3.6, 7.2],
        "highest_significant_harmonic_hz": 7.2,
        "highest_significant_harmonic_index": 6,
        "base_frequency_hz": 6.0,
        "oddball_frequency_hz": 1.2,
        "z_threshold": 1.64,
        "electrode_scope": "all_scalp_electrodes",
        "selection_scope": "group_level_all_scalp_electrodes_all_selected_conditions",
        "selection_conditions": ["Face"],
        "selection_subjects": ["S1"],
        "selection_spectra_count": 1,
        "selection_electrode_count": 3,
        "base_overlap_tolerance_hz": 0.01,
        "matching_tolerance_hz": 0.01,
        "noise_window_bins": 10,
        "selected_columns": ["1.2000_Hz", "3.6000_Hz", "7.2000_Hz"],
        "selected_bin_indices": [2, 6, 12],
        "selection_z_by_harmonic": {1.2: 5.0, 3.6: 4.0, 7.2: 3.0},
        "selection_rows": [],
    }


def test_group_harmonic_cache_roundtrip_and_settings_invalidation(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root, high_pass=0.1)
    workbook = project_root / "1 - Excel Data Files" / "S1_Face.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"placeholder")

    request = _request(project_root, workbook)
    assert request is not None
    assert request.fingerprint["method_version"] == (
        "group_significant_harmonics_roi_union_through_highest_gap_guard_v3"
    )
    assert request.fingerprint["method_version"] == GROUP_HARMONIC_METHOD_VERSION
    saved_at = save_cached_group_harmonic_selection(request, _selection_metadata())
    assert saved_at

    lookup = lookup_cached_group_harmonic_selection(_request(project_root, workbook))
    assert lookup.hit is not None
    assert lookup.hit.selection_metadata["selected_harmonics_hz"] == [1.2, 3.6, 7.2]

    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["preprocessing"]["high_pass"] = 0.5
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    stale_lookup = lookup_cached_group_harmonic_selection(_request(project_root, workbook))
    assert stale_lookup.hit is None
    assert "preprocessing/settings changed" in stale_lookup.reason


def test_group_harmonic_cache_identity_ignores_subject_and_condition_order(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    subject_data: dict[str, dict[str, str]] = {}
    for subject in ("S1", "S2"):
        subject_data[subject] = {}
        for condition in ("Face", "Object"):
            workbook = (
                project_root
                / "1 - Excel Data Files"
                / condition
                / f"{subject}_{condition}.xlsx"
            )
            workbook.parent.mkdir(parents=True, exist_ok=True)
            workbook.write_bytes(b"placeholder")
            subject_data[subject][condition] = str(workbook)

    forward = _multi_request(
        project_root,
        subjects=["S1", "S2"],
        conditions=["Face", "Object"],
        subject_data=subject_data,
    )
    subject_reordered = _multi_request(
        project_root,
        subjects=["S2", "S1"],
        conditions=["Face", "Object"],
        subject_data=subject_data,
    )
    condition_reordered = _multi_request(
        project_root,
        subjects=["S1", "S2"],
        conditions=["Object", "Face"],
        subject_data=subject_data,
    )
    both_reordered = _multi_request(
        project_root,
        subjects=["S2", "S1"],
        conditions=["Object", "Face"],
        subject_data=subject_data,
    )

    assert forward is not None
    for reordered in (
        subject_reordered,
        condition_reordered,
        both_reordered,
    ):
        assert reordered is not None
        assert reordered.cache_key == forward.cache_key
        assert reordered.fingerprint == forward.fingerprint


def test_reordered_cache_inputs_still_detect_changed_workbook(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    subject_data: dict[str, dict[str, str]] = {}
    for subject in ("S1", "S2"):
        subject_data[subject] = {}
        for condition in ("Face", "Object"):
            workbook = (
                project_root
                / "1 - Excel Data Files"
                / condition
                / f"{subject}_{condition}.xlsx"
            )
            workbook.parent.mkdir(parents=True, exist_ok=True)
            workbook.write_bytes(b"placeholder")
            subject_data[subject][condition] = str(workbook)

    saved_request = _multi_request(
        project_root,
        subjects=["S1", "S2"],
        conditions=["Face", "Object"],
        subject_data=subject_data,
    )
    assert saved_request is not None
    save_cached_group_harmonic_selection(saved_request, _selection_metadata())

    changed_workbook = Path(subject_data["S2"]["Object"])
    changed_workbook.write_bytes(b"changed-placeholder")
    changed_request = _multi_request(
        project_root,
        subjects=["S2", "S1"],
        conditions=["Object", "Face"],
        subject_data=subject_data,
    )
    lookup = lookup_cached_group_harmonic_selection(changed_request)

    assert lookup.hit is None
    assert "Source workbook files changed" in lookup.reason


def test_lookup_accepts_legacy_cache_with_different_input_order(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    subject_data: dict[str, dict[str, str]] = {}
    for subject in ("S1", "S2"):
        subject_data[subject] = {}
        for condition in ("Face", "Object"):
            workbook = (
                project_root
                / "1 - Excel Data Files"
                / condition
                / f"{subject}_{condition}.xlsx"
            )
            workbook.parent.mkdir(parents=True, exist_ok=True)
            workbook.write_bytes(b"placeholder")
            subject_data[subject][condition] = str(workbook)

    request = _multi_request(
        project_root,
        subjects=["S1", "S2"],
        conditions=["Face", "Object"],
        subject_data=subject_data,
    )
    assert request is not None
    save_cached_group_harmonic_selection(request, _selection_metadata())

    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["tools"]["stats"]["group_significant_harmonics_cache"][
        "entries"
    ]
    legacy_entry = entries.pop(request.cache_key)
    legacy_fingerprint = deepcopy(legacy_entry["fingerprint"])
    legacy_fingerprint["selection_inputs"]["subjects"].reverse()
    legacy_fingerprint["selection_inputs"]["conditions"].reverse()
    legacy_fingerprint["source_workbooks"].reverse()
    legacy_key = cache_mod._hash_payload(legacy_fingerprint)
    legacy_entry["cache_key"] = legacy_key
    legacy_entry["fingerprint"] = legacy_fingerprint
    entries[legacy_key] = legacy_entry
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lookup = lookup_cached_group_harmonic_selection(request)

    assert lookup.hit is not None
    assert lookup.hit.cache_key == legacy_key
    assert "normalizing legacy cache ordering" in lookup.reason


def test_project_processing_signature_tracks_fft_multinotch_settings(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    enabled_60 = build_project_processing_signature(manifest)
    manifest["preprocessing"]["line_noise_frequency_hz"] = 50
    enabled_50 = build_project_processing_signature(manifest)
    manifest["preprocessing"]["line_noise_filter_enabled"] = False
    disabled = build_project_processing_signature(manifest)

    assert enabled_60["preprocessing_order_version"] == PREPROCESSING_ORDER_VERSION_LABEL
    assert enabled_60["processing_fingerprint_version"] == PROCESSING_FINGERPRINT_VERSION_LABEL
    assert enabled_60["preprocessing"]["line_noise_filter_enabled"] is True
    assert enabled_60["preprocessing"]["line_noise_frequency_hz"] == 60
    assert enabled_60 != enabled_50
    assert enabled_50 != disabled


def test_project_processing_signature_tracks_participant_condition_exclusions(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    manifest = json.loads(
        (project_root / "project.json").read_text(encoding="utf-8")
    )

    included = build_project_processing_signature(manifest)
    manifest["preprocessing"]["manual_excluded_participant_conditions"] = {
        "P1": ["Negative Valence"]
    }
    excluded = build_project_processing_signature(manifest)

    assert included != excluded
    assert excluded["preprocessing"][
        "manual_excluded_participant_conditions"
    ] == {"P1": ["Negative Valence"]}


def test_frequency_domain_workflow_status_does_not_invalidate_harmonics(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    workbook = project_root / "1 - Excel Data Files" / "S1_Face.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"placeholder")
    _write_frequency_domain_qc_state(
        project_root,
        downstream_outputs_stale=True,
        manual_participant_exclusions=["S2"],
    )

    stale_request = _request(project_root, workbook)
    assert stale_request is not None
    assert "downstream_outputs_stale" not in stale_request.project_processing_signature[
        "frequency_domain_qc"
    ]
    save_cached_group_harmonic_selection(stale_request, _selection_metadata())

    _write_frequency_domain_qc_state(
        project_root,
        downstream_outputs_stale=False,
        manual_participant_exclusions=["S2"],
    )
    current_request = _request(project_root, workbook)
    assert current_request is not None
    assert current_request.cache_key == stale_request.cache_key
    assert lookup_cached_group_harmonic_selection(current_request).hit is not None

    _write_frequency_domain_qc_state(
        project_root,
        downstream_outputs_stale=False,
        manual_participant_exclusions=["S2", "S3"],
    )
    changed_exclusions_request = _request(project_root, workbook)
    assert changed_exclusions_request is not None
    assert changed_exclusions_request.cache_key != current_request.cache_key
    assert lookup_cached_group_harmonic_selection(changed_exclusions_request).hit is None


def test_lookup_accepts_legacy_cache_differing_only_by_workflow_status(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    workbook = project_root / "1 - Excel Data Files" / "S1_Face.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"placeholder")
    _write_frequency_domain_qc_state(
        project_root,
        downstream_outputs_stale=False,
    )
    request = _request(project_root, workbook)
    assert request is not None
    save_cached_group_harmonic_selection(request, _selection_metadata())

    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    entries = manifest["tools"]["stats"]["group_significant_harmonics_cache"][
        "entries"
    ]
    legacy_entry = entries.pop(request.cache_key)
    legacy_fingerprint = deepcopy(legacy_entry["fingerprint"])
    legacy_signature = legacy_fingerprint["project_processing_signature"]
    legacy_signature["frequency_domain_qc"]["downstream_outputs_stale"] = True
    legacy_signature_hash = cache_mod._hash_payload(legacy_signature)
    legacy_fingerprint["project_processing_signature_hash"] = legacy_signature_hash
    legacy_key = cache_mod._hash_payload(legacy_fingerprint)
    legacy_entry["cache_key"] = legacy_key
    legacy_entry["fingerprint"] = legacy_fingerprint
    legacy_entry["project_processing_signature"] = legacy_signature
    legacy_entry["project_processing_signature_hash"] = legacy_signature_hash
    entries[legacy_key] = legacy_entry
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    lookup = lookup_cached_group_harmonic_selection(_request(project_root, workbook))

    assert lookup.hit is not None
    assert lookup.hit.cache_key == legacy_key
    assert lookup.hit.selection_metadata["selected_harmonics_hz"] == [1.2, 3.6, 7.2]
    assert "downstream-output workflow status" in lookup.reason


def test_cache_miss_reports_method_upgrade_before_older_workbook_drift(
    tmp_path: Path,
) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    workbook = project_root / "1 - Excel Data Files" / "S1_Face.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"placeholder")
    request = _request(project_root, workbook)
    assert request is not None

    matching_legacy = deepcopy(request.fingerprint)
    matching_legacy["method_version"] = (
        "group_significant_harmonics_roi_union_through_highest_v2"
    )
    stale_legacy = deepcopy(matching_legacy)
    stale_workbooks = stale_legacy["source_workbooks"]
    assert isinstance(stale_workbooks, list)
    assert isinstance(stale_workbooks[0], dict)
    stale_workbooks[0]["size_bytes"] = int(stale_workbooks[0]["size_bytes"] or 0) + 1

    reason = cache_mod._cache_miss_reason(
        {
            "older-stale-entry": {"fingerprint": stale_legacy},
            "newer-workbook-matching-entry": {"fingerprint": matching_legacy},
        },
        request,
    )

    assert reason == "Harmonic-selection method version changed since saved harmonics."


def test_clear_group_harmonic_cache_preserves_manifest_shape(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    workbook = project_root / "1 - Excel Data Files" / "S1_Face.xlsx"
    workbook.parent.mkdir(parents=True)
    workbook.write_bytes(b"placeholder")
    request = _request(project_root, workbook)
    assert request is not None
    save_cached_group_harmonic_selection(request, _selection_metadata())

    assert clear_cached_group_harmonic_selections(project_root) == 1
    manifest = json.loads((project_root / "project.json").read_text(encoding="utf-8"))
    cache = manifest["tools"]["stats"]["group_significant_harmonics_cache"]
    assert cache["entries"] == {}
    assert manifest["groups"]["control"]["label"] == "Control"
    assert manifest["participants"]["S1"]["group_id"] == "control"


def test_project_save_preserves_stats_tools_metadata_written_to_disk(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _write_manifest(project_root)
    project = Project.load(project_root)

    manifest_path = project_root / "project.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["tools"] = {
        "stats": {
            "group_significant_harmonics_cache": {
                "schema_version": 1,
                "entries": {"abc": {"saved_at": "2026-01-01T00:00:00Z"}},
            }
        }
    }
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    project.name = "Renamed Project"
    project.save()

    saved = json.loads(manifest_path.read_text(encoding="utf-8"))
    cache = saved["tools"]["stats"]["group_significant_harmonics_cache"]
    assert cache["entries"]["abc"]["saved_at"] == "2026-01-01T00:00:00Z"
    assert saved["name"] == "Renamed Project"
