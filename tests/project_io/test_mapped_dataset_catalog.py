"""Mapped datasets admit only folders belonging to the saved condition catalog."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from Main_App.projects import FrequencyProtocol, load_project_dataset_index
from Main_App.projects.grouping import condition_output_folder_name


def _project(root: Path, *, label: str = "Renamed condition", mapped: bool = True) -> Path:
    raw = root / "Raw" / "Control"
    raw.mkdir(parents=True)
    protocol = FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    )
    if mapped:
        protocol = protocol.with_condition_trigger_maps({
            "schema_version": "1.0",
            "canonical_conditions": {"stable_condition_id": {"label": label}},
            "profiles": {"source": {"conditions": {
                "stable_condition_id": {"onset_code": 11, "oddball_code": 55},
            }}},
            "recording_assignments": {"P01": "source"},
        })
    manifest = {
        "results_folder": ".",
        "subfolders": {"excel": "1 - Excel Data Files"},
        "groups": {"control": {
            "label": "Control", "folder_name": "Control", "raw_input_folder": str(raw),
        }},
        "participants": {"P01": {"group_id": "control", "raw_file": "Raw/Control/P01.bdf"}},
        "frequency_protocol": protocol.to_manifest(),
        "event_map": {} if mapped else {label: 11},
    }
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root / "1 - Excel Data Files"


def _result(excel_root: Path, folder: str, suffix: str = ".xlsx", *, identity: str = "P01") -> Path:
    path = excel_root / folder / "Control" / f"{identity}_{folder}_Results{suffix}"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("Discovery must not open result payloads.", encoding="utf-8")
    return path


@pytest.mark.parametrize("suffix", [".xlsx", ".fpvs"])
def test_renamed_catalog_ignores_old_results_when_both_folders_exist(tmp_path, suffix):
    excel = _project(tmp_path)
    old = _result(excel, "Original condition", suffix)
    current = _result(excel, "Renamed condition", suffix)
    before = {path: path.read_bytes() for path in (old, current)}

    index = load_project_dataset_index(tmp_path)

    assert index.conditions == ("Renamed condition",)
    assert [(row.condition, row.path, row.participant_id) for row in index.workbooks] == [
        ("Renamed condition", current, "P01"),
    ]
    assert not index.excluded_workbooks
    assert all(path.read_bytes() == data for path, data in before.items())


@pytest.mark.parametrize("suffix", [".xlsx", ".fpvs"])
def test_renamed_catalog_does_not_fall_back_to_old_results_before_reprocessing(tmp_path, suffix):
    excel = _project(tmp_path)
    old = _result(excel, "Original condition", suffix)

    index = load_project_dataset_index(excel)

    assert index.workbooks == ()
    assert index.conditions == ()
    assert index.excluded_workbooks == ()
    assert old.is_file()


@pytest.mark.parametrize("label", ["1 - Faces", "123 Hz"])
def test_output_folder_maps_back_to_exact_canonical_label(tmp_path, label):
    excel = _project(tmp_path, label=label)
    folder = condition_output_folder_name(label)
    current = _result(excel, folder)

    for requested in (tmp_path, current.parent.parent, current):
        index = load_project_dataset_index(requested)
        assert index.conditions == (label,)
        assert len(index.workbooks) == 1
        assert index.workbooks[0].path == current
        assert index.workbooks[0].condition == label
        assert index.select(conditions=(label,)) == index.workbooks


def test_explicit_obsolete_result_cannot_bypass_catalog_and_is_diagnosed(tmp_path):
    excel = _project(tmp_path)
    old = _result(excel, "Original condition")
    _result(excel, "Renamed condition")

    index = load_project_dataset_index(old)

    assert index.workbooks == ()
    assert index.excluded_workbooks == ()
    assert index.conditions == ()
    assert any(diagnostic.code == "condition_not_in_catalog" and old in diagnostic.paths for diagnostic in index.diagnostics)


@pytest.mark.parametrize("label", ["Faces", "1 - Faces"])
def test_repeated_recording_identity_uses_output_component_but_keeps_canonical_label(tmp_path, label):
    excel = _project(tmp_path, label=label)
    path = tmp_path / "project.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["sessions"] = {"visit1": {"label": "Visit 1", "visit_index": 1}}
    manifest["recording_sources"] = {"control_visit1": {
        "group_id": "control", "session_id": "visit1", "raw_input_folder": "Raw/Control",
    }}
    manifest["recordings"] = {"P01_visit1": {
        "participant_id": "P01", "session_id": "visit1", "source_id": "control_visit1",
        "raw_file": "Raw/Control/P01.bdf", "visit_index": 1,
    }}
    manifest["frequency_protocol"]["condition_trigger_maps"]["recording_assignments"] = {"P01_visit1": "source"}
    path.write_text(json.dumps(manifest), encoding="utf-8")
    current = _result(excel, condition_output_folder_name(label), identity="P01_visit1")

    index = load_project_dataset_index(tmp_path)

    assert [(row.condition, row.recording_id, row.participant_id, row.path) for row in index.workbooks] == [
        (label, "P01_visit1", "P01", current),
    ]


def test_legacy_shared_map_keeps_historical_folder_discovery(tmp_path):
    excel = _project(tmp_path, mapped=False)
    old = _result(excel, "Original condition")
    current = _result(excel, "Renamed condition")

    index = load_project_dataset_index(tmp_path)

    assert index.conditions == ("Original condition", "Renamed condition")
    assert {row.path for row in index.workbooks} == {old, current}
    assert load_project_dataset_index(old).workbooks[0].path == old
