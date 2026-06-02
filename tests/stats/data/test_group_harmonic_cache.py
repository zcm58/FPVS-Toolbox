from __future__ import annotations

import json
from pathlib import Path

from Main_App.projects.project import Project
from Tools.Stats.analysis.dv_policy_settings import (
    GROUP_SIGNIFICANT_POLICY_NAME,
    normalize_dv_policy,
)
from Tools.Stats.data.group_harmonic_cache import (
    build_group_harmonic_cache_request,
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
        "groups": {"control": {"label": "Control", "folder_name": "Control"}},
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
