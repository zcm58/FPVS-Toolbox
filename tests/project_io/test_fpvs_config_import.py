from __future__ import annotations

import json

import pytest

from Main_App.projects.fpvs_config_import import (
    FPVSConfigImportError,
    create_project_from_fpvs_config,
    read_fpvs_config,
)
from Main_App.projects.project import Project
from Main_App.projects import (
    FREQUENCY_PROTOCOL_STATUS_INCOMPLETE,
    FREQUENCY_PROTOCOL_STATUS_READY,
    MANUAL_REMOVED_ELECTRODES_ENABLED_KEY,
    ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT,
    REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT,
)


def _write_fpvs_config(path, *, title: str = "Semantic Categories Test") -> None:
    path.write_text(
        json.dumps(
            {
                "schema_version": "1.0.0",
                "project": {
                    "project_id": "semantic-categories-test",
                    "name": title,
                    "template_id": "fpvs_6hz_every5_v1",
                },
                "conditions": [
                    {"condition_id": "condition-1", "name": "Fruit vs Vegetable", "trigger_code": 1},
                    {"condition_id": "condition-2", "name": "Veg vs Fruit", "trigger_code": 2},
                ],
                "triggers": {"oddball_trigger_code": 55},
            }
        ),
        encoding="utf-8",
    )


def test_read_fpvs_config_extracts_title_and_condition_event_map(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    imported = read_fpvs_config(config_path)

    assert imported.project_title == "Semantic Categories Test"
    assert imported.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    assert imported.manual_removed_electrodes == {}
    assert imported.oddball_marker_code == 55
    assert imported.frequency_protocol is None


def test_read_fpvs_config_extracts_manual_removed_electrodes_map(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["manual_removed_electrodes"] = {
        "p1": "ft7, ft8, p9",
        "P13": ["oz", "O2", "O2"],
        "P14": "",
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    imported = read_fpvs_config(config_path)

    assert imported.manual_removed_electrodes == {
        "p1": ["FT7", "FT8", "P9"],
        "P13": ["Oz", "O2"],
        "P14": [],
    }


def test_read_fpvs_config_extracts_participant_level_removed_electrodes(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["participants"] = [
        {"participant_id": "P01", "excluded_electrodes": "ft7, p9"},
        {"pid": "P02", "physically_removed_electrodes": ["oz"]},
    ]
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    imported = read_fpvs_config(config_path)

    assert imported.manual_removed_electrodes == {
        "P01": ["FT7", "P9"],
        "P02": ["Oz"],
    }


def test_create_project_from_fpvs_config_saves_toolbox_project(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    project = create_project_from_fpvs_config(tmp_path / "projects", config_path)

    assert project.name == "Semantic Categories Test"
    assert project.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    loaded = Project.load(project.project_root)
    assert loaded.name == "Semantic Categories Test"
    assert loaded.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    assert loaded.frequency_protocol.status == FREQUENCY_PROTOCOL_STATUS_INCOMPLETE
    assert loaded.frequency_protocol.oddball_marker_code == 55
    assert (
        loaded.frequency_protocol.oddball_marker_code_source
        == ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT
    )
    assert loaded.preprocessing["harmonic_selection_profile"] == (
        "dzhelyova_poncet_two_consecutive_failures"
    )
    assert loaded.preprocessing["group_significant_electrode_scope"] == (
        "all_scalp_electrodes"
    )


def test_create_project_from_fpvs_config_seeds_manual_removed_electrodes(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["participants"] = {
        "P01": {"manual_removed_electrodes": ["ft7", "p9"]},
        "P02": {"excluded_electrodes": ""},
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    project = create_project_from_fpvs_config(tmp_path / "projects", config_path)

    assert project.preprocessing["removed_electrode_detection_mode"] == "off"
    assert project.preprocessing["auto_detect_removed_electrodes"] is False
    assert project.preprocessing[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True
    assert project.preprocessing["removed_electrode_detection_choice_source"] == (
        REMOVED_ELECTRODE_DETECTION_CHOICE_SOURCE_FPVS_STUDIO_IMPORT
    )
    assert project.preprocessing["manual_removed_electrodes"] == {
        "P01": ["FT7", "P9"],
        "P02": [],
    }
    loaded = Project.load(project.project_root)
    assert loaded.preprocessing["removed_electrode_detection_mode"] == "off"
    assert loaded.preprocessing[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] is True
    assert loaded.preprocessing["manual_removed_electrodes"] == {
        "P01": ["FT7", "P9"],
        "P02": [],
    }


def test_create_project_from_fpvs_config_ignores_participants_without_electrodes(
    tmp_path,
) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["participants"] = {
        "P01": {"group_id": "control"},
        "P02": {"notes": "no removed electrodes"},
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    project = create_project_from_fpvs_config(tmp_path / "projects", config_path)

    assert project.preprocessing["removed_electrode_detection_mode"] == "off"
    assert project.preprocessing["auto_detect_removed_electrodes"] is False
    assert project.preprocessing["manual_removed_electrodes"] == {}


def test_create_project_from_fpvs_config_uses_unique_folder(tmp_path) -> None:
    projects_root = tmp_path / "projects"
    existing = projects_root / "Semantic Categories Test"
    existing.mkdir(parents=True)
    (existing / "project.json").write_text("{}", encoding="utf-8")
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)

    project = create_project_from_fpvs_config(projects_root, config_path)

    assert project.project_root.name == "Semantic Categories Test 2"


def test_read_fpvs_config_rejects_duplicate_condition_names(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["conditions"][1]["name"] = "Fruit vs Vegetable"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="Duplicate condition name"):
        read_fpvs_config(config_path)


def test_read_fpvs_config_rejects_fractional_trigger_codes(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["conditions"][0]["trigger_code"] = 1.5
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="trigger_code must be an integer"):
        read_fpvs_config(config_path)


def test_read_fpvs_config_rejects_marker_code_that_collides_with_onset(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["triggers"]["oddball_trigger_code"] = 2
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="condition-onset"):
        read_fpvs_config(config_path)


def test_read_fpvs_config_imports_exact_frequency_protocol(tmp_path) -> None:
    config_path = tmp_path / "project.fpvsconfig"
    _write_fpvs_config(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    payload["frequency_protocol"] = {
        "presentation_rate_hz": "3",
        "oddball_input_mode": "oddball_every_n",
        "oddball_every_n": 10,
        "expected_analyzed_oddball_cycles": 90,
    }
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    imported = read_fpvs_config(config_path)

    assert imported.frequency_protocol is not None
    assert imported.frequency_protocol.status == FREQUENCY_PROTOCOL_STATUS_READY
    assert imported.frequency_protocol.oddball_every_n == 10
    assert str(imported.frequency_protocol.oddball_rate_hz) == "3/10"
    assert imported.frequency_protocol.expected_analyzed_oddball_cycles == 90
    assert (
        imported.frequency_protocol.oddball_marker_code_source
        == ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT
    )


def _write_current_studio_config(path, *, schema_version="1.2.0") -> dict:
    _write_fpvs_config(path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update(
        schema_version=schema_version,
        experiment_category="fpvs_oddball",
        protocol={"base_hz": 3.0, "oddball_every_n": 10},
        toolbox={
            "project_title": "Semantic Categories Test",
            "event_map": {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2},
            "oddball_trigger_code": 88,
        },
    )
    payload["triggers"]["oddball_trigger_code"] = 88
    for condition in payload["conditions"]:
        condition["sequence_count"] = 1
        condition["oddball_cycle_repeats_per_sequence"] = 146
    path.write_text(json.dumps(payload), encoding="utf-8")
    return payload


@pytest.mark.parametrize(
    "schema_version",
    ["1.1.0", "1.2.0", "1.3.0", "1.4.0", "1.5.0", "1.6.0", "1.7.0", "1.8.0"],
)
def test_current_studio_config_creates_project_with_declared_rates(
    tmp_path, schema_version,
) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path, schema_version=schema_version)
    # Completed exports use the same setup fields. Planned events are not an FFT span.
    payload["completed_session"] = {"ordered_runs": [{"trigger_events": [{"code": 88}]}]}
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    project = create_project_from_fpvs_config(tmp_path / "projects", config_path)
    loaded = Project.load(project.project_root)

    assert loaded.name == "Semantic Categories Test"
    assert loaded.event_map == {"Fruit vs Vegetable": 1, "Veg vs Fruit": 2}
    protocol = loaded.frequency_protocol
    assert str(protocol.presentation_rate_hz) == "3"
    assert protocol.oddball_every_n == 10
    assert str(protocol.oddball_rate_hz) == "3/10"
    assert protocol.oddball_marker_code == 88
    assert protocol.oddball_marker_code_source == ODDBALL_MARKER_SOURCE_FPVS_STUDIO_IMPORT
    assert protocol.expected_analyzed_oddball_cycles == 144
    assert protocol.is_ready
    assert protocol.derived_analyzed_seconds == 480
    assert protocol.analysis_window.maximum_oddball_cycles == 145
    assert protocol.analysis_window.mode == "studio_planned"


@pytest.mark.parametrize("presentations,expected", [(74, 72), (146, 144), (149, 147), (302, 300)])
def test_studio_project_lengths_resolve_independently(tmp_path, presentations, expected) -> None:
    path = tmp_path / "project.fpvsconfig"
    payload = _write_current_studio_config(path)
    payload["protocol"] = {"base_hz": 6, "oddball_every_n": 5}
    for condition in payload["conditions"]:
        condition["oddball_cycle_repeats_per_sequence"] = presentations
    path.write_text(json.dumps(payload), encoding="utf-8")

    project = create_project_from_fpvs_config(tmp_path / "projects", path)
    loaded = Project.load(project.project_root)

    assert loaded.frequency_protocol.expected_analyzed_oddball_cycles == expected
    assert loaded.frequency_protocol.analysis_window.maximum_oddball_cycles == presentations - 1
    assert loaded.frequency_protocol.fingerprint == project.frequency_protocol.fingerprint


@pytest.mark.parametrize("field,value", [
    ("sequence_count", None), ("sequence_count", True),
    ("oddball_cycle_repeats_per_sequence", 0),
    ("oddball_cycle_repeats_per_sequence", 146.5),
])
def test_invalid_studio_window_does_not_write_project(tmp_path, field, value) -> None:
    path = tmp_path / "project.fpvsconfig"
    payload = _write_current_studio_config(path)
    payload["conditions"][0][field] = value
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match=field):
        create_project_from_fpvs_config(tmp_path / "projects", path)
    assert not (tmp_path / "projects").exists()


def test_mixed_studio_lengths_fail_before_writing_project(tmp_path) -> None:
    path = tmp_path / "project.fpvsconfig"
    payload = _write_current_studio_config(path)
    payload["conditions"][1]["oddball_cycle_repeats_per_sequence"] = 74
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="same sequence count"):
        create_project_from_fpvs_config(tmp_path / "projects", path)
    assert not (tmp_path / "projects").exists()


def test_studio_sequence_count_is_part_of_the_planned_window(tmp_path) -> None:
    path = tmp_path / "project.fpvsconfig"
    payload = _write_current_studio_config(path)
    for condition in payload["conditions"]:
        condition.update(sequence_count=2, oddball_cycle_repeats_per_sequence=74)
    path.write_text(json.dumps(payload), encoding="utf-8")
    protocol = read_fpvs_config(path).frequency_protocol
    assert protocol.analysis_window.maximum_oddball_cycles == 147
    assert protocol.expected_analyzed_oddball_cycles == 147


def test_current_cognitive_load_config_imports_fpvs_protocol(tmp_path) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path)
    payload["experiment_category"] = "cognitive_load_fpvs"
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    imported = read_fpvs_config(config_path)

    assert imported.frequency_protocol is not None
    assert str(imported.frequency_protocol.oddball_rate_hz) == "3/10"


@pytest.mark.parametrize("schema_version", [None, "1.9.0", "2.0.0", {"version": "1.2.0"}])
def test_unknown_studio_schema_does_not_create_project(tmp_path, schema_version) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    _write_current_studio_config(config_path, schema_version=schema_version)
    projects_root = tmp_path / "projects"

    with pytest.raises(FPVSConfigImportError, match="Unsupported FPVS config schema"):
        create_project_from_fpvs_config(projects_root, config_path)

    assert not projects_root.exists()


@pytest.mark.parametrize("category", ["attentional_blink", "fpvs", "unknown"])
def test_unsupported_studio_category_does_not_create_project(tmp_path, category) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path)
    payload["experiment_category"] = category
    config_path.write_text(json.dumps(payload), encoding="utf-8")
    projects_root = tmp_path / "projects"

    with pytest.raises(FPVSConfigImportError, match="Unsupported Studio experiment category"):
        create_project_from_fpvs_config(projects_root, config_path)

    assert not projects_root.exists()


@pytest.mark.parametrize(
    "protocol",
    [None, [], {}, {"base_hz": 0, "oddball_every_n": 10},
     {"base_hz": 3, "oddball_every_n": True}, {"base_hz": 3, "oddball_every_n": 1.5}],
)
def test_malformed_current_studio_protocol_is_rejected(tmp_path, protocol) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path)
    payload["protocol"] = protocol
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="protocol"):
        read_fpvs_config(config_path)


def test_current_studio_config_requires_declared_protocol(tmp_path) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path)
    del payload["protocol"]
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="missing its protocol"):
        read_fpvs_config(config_path)


def test_studio_config_rejects_ambiguous_protocol_definitions(tmp_path) -> None:
    config_path = tmp_path / "current.fpvsconfig"
    payload = _write_current_studio_config(config_path)
    payload["frequency_protocol"] = {"presentation_rate_hz": 6, "oddball_every_n": 5}
    config_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(FPVSConfigImportError, match="both protocol and frequency_protocol"):
        read_fpvs_config(config_path)
