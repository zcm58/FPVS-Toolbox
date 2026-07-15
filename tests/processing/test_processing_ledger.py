from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.Shared.post_process import _create_output_subfolder
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    PROCESSING_FINGERPRINT_VERSION,
    SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT,
    carry_forward_pre_qc_completed_states,
    classify_processing_inputs,
    clean_downstream_outputs_for_reprocess_all,
    clean_managed_excel_root,
    clean_participant_outputs,
    output_group_folder_by_file,
    record_processing_results,
    refresh_skipped_ledger_fingerprints,
    with_processing_choice,
)
from Main_App.projects.grouping import GroupConfigurationError
from Main_App.projects.project import Project
from Main_App.workers import process_runner


def _project_with_raw(tmp_path):
    project = Project.load(tmp_path / "project")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    raw_file = raw_dir / "P01.bdf"
    raw_file.write_bytes(b"raw")
    project.input_folder = raw_dir
    project.event_map = {"Condition A": 1}
    project.save()
    return project, RawFileInfo(raw_file.resolve(), "P01")


def _add_raw_file(raw_dir: Path, participant_id: str) -> RawFileInfo:
    raw_file = raw_dir / f"{participant_id}.bdf"
    raw_file.write_bytes(b"raw")
    return RawFileInfo(raw_file.resolve(), participant_id)


def _settings() -> dict[str, object]:
    return {
        "high_pass": 0.1,
        "low_pass": 50.0,
        "downsample": 256,
        "epoch_start": -1.0,
        "epoch_end": 125.0,
        "base_freq": 6.0,
        "oddball_freq": 1.2,
        "bca_upper_limit": 14.4,
    }


def _write_expected_outputs(plan) -> None:
    for state in plan.states:
        for output_path in state.expected_outputs:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text("ok", encoding="utf-8")


def _write_source_derivative_result(
    project: Project,
    participant_id: str,
    *,
    condition_id: str = "1",
    group_folder: str | None = None,
    relative_paths: bool = False,
) -> dict[str, object]:
    root = project.project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    condition_folder = root / "Condition A"
    manifest_folder = root / "manifests"
    if group_folder:
        condition_folder = condition_folder / group_folder
        manifest_folder = manifest_folder / group_folder
    fif_path = condition_folder / f"{participant_id}_{condition_id}_avg_raw.fif"
    sidecar_path = condition_folder / f"{participant_id}_{condition_id}_avg_raw.json"
    manifest_path = manifest_folder / f"{participant_id}.json"
    for path in (fif_path, sidecar_path, manifest_path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("source derivative", encoding="utf-8")

    def _stored_path(path: Path) -> str:
        if relative_paths:
            return path.relative_to(project.project_root).as_posix()
        return str(path)

    return {
        "source_derivative_status": "complete",
        "source_derivative_manifest": _stored_path(manifest_path),
        "source_derivative_outputs": [
            _stored_path(fif_path),
            _stored_path(sidecar_path),
            _stored_path(manifest_path),
        ],
        "source_derivative_warning": "",
    }


def test_classify_new_file_without_ledger(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)

    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert plan.new_count == 1
    assert plan.incremental_files == (info.path,)
    assert plan.states[0].status == "new"


def test_record_results_creates_completed_ledger_and_run_log(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)

    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    runs = (project.project_root / ".fpvs_processing" / "processing_runs.jsonl").read_text(
        encoding="utf-8"
    )

    entry = ledger["entries"]["P01"]
    assert entry["status"] == "completed"
    assert entry["processing_fingerprint_version"] == PROCESSING_FINGERPRINT_VERSION
    assert entry["run_mode"] == "Batch"
    assert '"successful_files": 1' in runs


def test_record_results_persists_complete_source_derivative_contract(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    source_result = _write_source_derivative_result(project, "P01")

    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path), **source_result}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    entry = ledger["entries"]["P01"]
    assert PROCESSING_FINGERPRINT_VERSION == "processing_fingerprint_v9_source_ready_time_domain"
    assert entry["source_derivative_status"] == "complete"
    assert entry["source_derivative_manifest"] == source_result["source_derivative_manifest"]
    assert entry["source_derivative_outputs"] == source_result["source_derivative_outputs"]
    assert entry["source_derivative_warning"] == ""
    assert classify_processing_inputs(
        project,
        [info],
        _settings(),
        project.event_map,
    ).states[0].status == "completed"


@pytest.mark.parametrize("missing_kind", ["manifest", "artifact"])
def test_classify_complete_source_derivative_with_missing_file_is_stale(
    tmp_path,
    missing_kind,
) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    source_result = _write_source_derivative_result(project, "P01")
    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path), **source_result}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    target = (
        Path(str(source_result["source_derivative_manifest"]))
        if missing_kind == "manifest"
        else Path(str(source_result["source_derivative_outputs"][0]))
    )
    target.unlink()

    stale = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert stale.states[0].status == "missing_outputs"
    assert "Source-ready time-domain derivative" in stale.states[0].reason
    assert stale.incremental_files == (info.path,)


def test_classify_explicitly_incomplete_source_derivative_is_stale(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    record_processing_results(
        project,
        plan,
        [
            {
                "status": "ok",
                "file": str(info.path),
                "source_derivative_status": "incomplete",
                "source_derivative_manifest": "",
                "source_derivative_outputs": [],
                "source_derivative_warning": "disk full",
            }
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    stale = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert stale.states[0].status == "missing_outputs"
    assert "not complete" in stale.states[0].reason


def test_classify_completed_requires_ledger_and_expected_outputs(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert plan.completed_count == 1
    assert plan.incremental_files == ()
    assert plan.states[0].status == "completed"


def test_classify_missing_expected_output_is_stale(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    initial_plan.states[0].expected_outputs[0].unlink()

    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert plan.stale_count == 1
    assert plan.states[0].status == "missing_outputs"


def test_classify_settings_change_stales_completed_entry(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    changed_settings = {**_settings(), "bca_upper_limit": 18.0}

    plan = classify_processing_inputs(project, [info], changed_settings, project.event_map)

    assert plan.states[0].status == "changed_settings"
    assert plan.incremental_files == (info.path,)


def test_classify_fft_multinotch_change_stales_completed_entry(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    initial_settings = {
        **_settings(),
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": 60,
    }
    initial_plan = classify_processing_inputs(
        project,
        [info],
        initial_settings,
        project.event_map,
    )
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    frequency_changed = classify_processing_inputs(
        project,
        [info],
        {**initial_settings, "line_noise_frequency_hz": 50},
        project.event_map,
    )
    disabled = classify_processing_inputs(
        project,
        [info],
        {**initial_settings, "line_noise_filter_enabled": False},
        project.event_map,
    )

    assert frequency_changed.states[0].status == "changed_settings"
    assert disabled.states[0].status == "changed_settings"


def test_pre_qc_completed_state_survives_new_participant_qc_metadata(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.update_preprocessing(
        {
            **project.preprocessing,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {"P01": ["P9"]},
        }
    )
    project.save()
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )

    info_2 = _add_raw_file(Path(project.input_folder), "P02")
    pre_qc_plan = classify_processing_inputs(
        project,
        [info, info_2],
        _settings(),
        project.event_map,
    )
    assert [state.status for state in pre_qc_plan.states] == ["completed", "new"]

    project.update_preprocessing(
        {
            **project.preprocessing,
            "manual_removed_electrodes": {"P01": ["P9"], "P02": ["Oz"]},
        }
    )
    project.save()
    current_plan = classify_processing_inputs(
        project,
        [info, info_2],
        _settings(),
        project.event_map,
    )
    assert [state.status for state in current_plan.states] == ["changed_settings", "new"]

    carried = carry_forward_pre_qc_completed_states(project, pre_qc_plan, current_plan)
    assert [state.status for state in carried.states] == ["completed", "new"]
    assert carried.incremental_files == (info_2.path,)

    refreshed = refresh_skipped_ledger_fingerprints(project, carried)
    assert refreshed == 1
    follow_up = classify_processing_inputs(
        project,
        [info, info_2],
        _settings(),
        project.event_map,
    )
    assert [state.status for state in follow_up.states] == ["completed", "new"]
    assert follow_up.incremental_files == (info_2.path,)


def test_pre_qc_carry_forward_does_not_hide_raw_file_changes(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.update_preprocessing(
        {
            **project.preprocessing,
            "removed_electrode_detection_mode": "manual",
            "manual_removed_electrodes": {"P01": ["P9"]},
        }
    )
    project.save()
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    pre_qc_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    assert pre_qc_plan.states[0].status == "completed"

    info.path.write_bytes(b"changed raw")
    project.update_preprocessing(
        {
            **project.preprocessing,
            "manual_removed_electrodes": {"P01": ["P9"], "P02": ["Oz"]},
        }
    )
    project.save()
    current_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    assert current_plan.states[0].status == "changed_settings"

    carried = carry_forward_pre_qc_completed_states(project, pre_qc_plan, current_plan)

    assert carried.states[0].status == "changed_settings"
    assert carried.incremental_files == (info.path,)


def test_classify_old_processing_fingerprint_version_is_stale(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    initial_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(initial_plan)
    record_processing_results(
        project,
        initial_plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"]["P01"]["processing_fingerprint_version"] = "processing_fingerprint_v1"
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert plan.states[0].status == "changed_settings"
    assert plan.states[0].reason == "Processing fingerprint version changed."


def test_record_results_locks_multigroup_project_after_success(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": info.path.parent,
        }
    }
    grouped_info = RawFileInfo(info.path, info.subject_id, "control")
    project.save()
    plan = classify_processing_inputs(project, [grouped_info], _settings(), project.event_map)
    _write_expected_outputs(plan)

    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert saved["groups_locked"] is True
    assert saved["groups_locked_at"]
    assert saved["groups_lock_fingerprint"]

    project.groups["control"]["folder_name"] = "Changed"
    with pytest.raises(ValueError, match="cannot be changed"):
        project.save()


@pytest.mark.parametrize("cancelled", [False, True])
def test_partial_current_run_output_locks_group_layout(tmp_path, cancelled) -> None:
    project, info = _project_with_raw(tmp_path)
    project.event_map = {"Condition A": 1, "Condition B": 2}
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": info.path.parent,
        }
    }
    grouped_info = RawFileInfo(info.path, info.subject_id, "control")
    project.save()
    plan = classify_processing_inputs(
        project,
        [grouped_info],
        _settings(),
        project.event_map,
    )
    partial_output = plan.states[0].expected_outputs[0]
    partial_output.parent.mkdir(parents=True, exist_ok=True)
    partial_output.write_text("current run", encoding="utf-8")

    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=cancelled,
    )

    assert project.groups_locked is True
    assert project.groups_locked_at


@pytest.mark.parametrize(
    ("outcome", "cancelled"),
    [
        pytest.param("error", False, id="worker-error"),
        pytest.param("excluded", False, id="excluded"),
        pytest.param("ok_without_outputs", False, id="ok-status-without-output"),
        pytest.param("cancelled", True, id="cancelled"),
    ],
)
def test_record_results_does_not_lock_multigroup_without_successful_output(
    tmp_path,
    outcome,
    cancelled,
) -> None:
    project, info = _project_with_raw(tmp_path)
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": info.path.parent,
        }
    }
    grouped_info = RawFileInfo(info.path, info.subject_id, "control")
    project.save()
    plan = classify_processing_inputs(project, [grouped_info], _settings(), project.event_map)

    if outcome == "error":
        results = [{"status": "error", "file": str(info.path)}]
    elif outcome == "excluded":
        results = [
            {
                "status": "excluded",
                "file": str(info.path),
                "reason": "raw_qc_exclusion",
            }
        ]
    elif outcome == "ok_without_outputs":
        results = [{"status": "ok", "file": str(info.path)}]
    else:
        results = []

    record_processing_results(
        project,
        plan,
        results,
        run_mode="Batch",
        user_choice="incremental",
        cancelled=cancelled,
    )
    saved = json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))

    assert project.groups_locked is False
    assert project.groups_locked_at is None
    assert "groups_locked" not in saved
    assert "groups_locked_at" not in saved


def test_multigroup_expected_outputs_are_condition_first_group_second(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control Group",
            "raw_input_folder": info.path.parent,
        }
    }
    grouped_info = RawFileInfo(info.path, info.subject_id, "control")
    project.save()

    plan = classify_processing_inputs(project, [grouped_info], _settings(), project.event_map)

    assert plan.states[0].expected_outputs == (
        (
            project.subfolders["excel"]
            / "Condition A"
            / "Control Group"
            / "P01_Condition A_Results.xlsx"
        ).resolve(),
    )
    assert output_group_folder_by_file(project, [grouped_info]) == {
        str(info.path.resolve()): "Control Group"
    }


def test_two_groups_receive_distinct_canonical_output_routes(tmp_path) -> None:
    project, control_info = _project_with_raw(tmp_path)
    treatment_dir = tmp_path / "treatment_raw"
    treatment_dir.mkdir()
    treatment_file = treatment_dir / "P02.bdf"
    treatment_file.write_bytes(b"raw")
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": control_info.path.parent,
        },
        "treatment": {
            "label": "Treatment",
            "folder_name": "Treatment",
            "raw_input_folder": treatment_dir,
        },
    }
    grouped_infos = [
        RawFileInfo(control_info.path, control_info.subject_id, "control"),
        RawFileInfo(treatment_file.resolve(), "P02", "treatment"),
    ]
    project.save()

    plan = classify_processing_inputs(
        project,
        grouped_infos,
        _settings(),
        project.event_map,
    )

    assert [state.expected_outputs[0].parent.name for state in plan.states] == [
        "Control",
        "Treatment",
    ]
    assert output_group_folder_by_file(project, grouped_infos) == {
        str(control_info.path.resolve()): "Control",
        str(treatment_file.resolve()): "Treatment",
    }


def test_planned_group_route_matches_runner_and_export_destination(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": info.path.parent,
        }
    }
    grouped_info = RawFileInfo(info.path, info.subject_id, "control")
    project.save()
    plan = classify_processing_inputs(
        project,
        [grouped_info],
        _settings(),
        project.event_map,
    )
    group_mapping = output_group_folder_by_file(project, [grouped_info])
    file_settings = process_runner._settings_for_file(
        info.path,
        {
            "_fpvs_grouped_project": True,
            "_fpvs_output_group_by_file": group_mapping,
        },
    )
    destination = _create_output_subfolder(
        SimpleNamespace(log=lambda _message: None),
        project.subfolders["excel"],
        "Condition A",
        file_settings["output_group_folder"],
    )

    assert Path(destination) == plan.states[0].expected_outputs[0].parent


def test_expected_outputs_reject_unsafe_condition_folder(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.event_map = {"..": 1}

    with pytest.raises(GroupConfigurationError):
        classify_processing_inputs(project, [info], _settings(), project.event_map)


def test_grouped_expected_outputs_require_group_id(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.groups = {
        "control": {
            "label": "Control",
            "folder_name": "Control",
            "raw_input_folder": info.path.parent,
        }
    }
    project.save()

    with pytest.raises(ValueError, match="missing its canonical group_id"):
        classify_processing_inputs(project, [info], _settings(), project.event_map)


def test_record_results_marks_missing_run_file_failed(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    record_processing_results(
        project,
        plan,
        [],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )

    assert ledger["entries"]["P01"]["status"] == "failed"


def test_record_results_flags_partial_condition_outputs_without_excluding(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.event_map = {"Condition A": 1, "Condition B": 2}
    project.save()
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    partial_output = plan.states[0].expected_outputs[0]
    missing_output = plan.states[0].expected_outputs[1]
    partial_output.parent.mkdir(parents=True, exist_ok=True)
    partial_output.write_text("partial", encoding="utf-8")

    record_processing_results(
        project,
        plan,
        [
            {
                "status": "ok",
                "file": str(info.path),
                "audit": {
                    "n_rejected": 2,
                    "raw_qc_bad_channels": ["P9"],
                    "kurtosis_bad_channels": ["P8"],
                    "interpolated_channels": ["P9", "P8"],
                },
            }
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )

    entry = ledger["entries"]["P01"]
    assert entry["status"] == "completed"
    assert entry["condition_completeness"] == "partial"
    assert entry["completion_warning"] == "missing_expected_outputs"
    assert entry["missing_outputs"] == [str(missing_output)]
    assert entry["missing_condition_labels"] == ["Condition B"]
    assert entry["present_outputs"] == [str(partial_output)]
    assert entry["raw_qc_bad_channels"] == ["P9"]
    assert entry["interpolated_channels"] == ["P9", "P8"]
    assert entry["n_rejected"] == 2
    assert partial_output.exists()

    follow_up_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    assert follow_up_plan.completed_count == 1
    assert follow_up_plan.incremental_files == ()
    assert follow_up_plan.states[0].status == "completed"

    runs = (project.project_root / ".fpvs_processing" / "processing_runs.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"successful_files": 1' in runs
    assert '"failed_files": 0' in runs
    assert '"condition_warning_files": 1' in runs


def test_classify_legacy_missing_condition_failure_as_completed_partial(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    project.event_map = {"Condition A": 1, "Condition B": 2}
    project.save()
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    partial_output = plan.states[0].expected_outputs[0]
    partial_output.parent.mkdir(parents=True, exist_ok=True)
    partial_output.write_text("partial", encoding="utf-8")
    missing_output = plan.states[0].expected_outputs[1]
    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entry = ledger["entries"]["P01"]
    entry["status"] = "failed"
    entry.pop("failure_reason", None)
    entry.pop("completion_warning", None)
    entry.pop("condition_completeness", None)
    entry["missing_outputs"] = [str(missing_output)]
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")

    follow_up_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert follow_up_plan.completed_count == 1
    assert follow_up_plan.incremental_files == ()
    assert follow_up_plan.states[0].status == "completed"


def test_record_results_marks_excluded_file_and_skips_until_raw_changes(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    expected_outputs = tuple(plan.states[0].expected_outputs)
    assert expected_outputs
    assert all(path.exists() for path in expected_outputs)

    record_processing_results(
        project,
        plan,
        [
            {
                "status": "excluded",
                "file": str(info.path),
                "reason": "recording_not_started",
                "message": "File P01.bdf was excluded from processing and analysis.",
            }
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )
    runs = (project.project_root / ".fpvs_processing" / "processing_runs.jsonl").read_text(
        encoding="utf-8"
    )

    entry = ledger["entries"]["P01"]
    assert entry["status"] == "excluded"
    assert entry["exclusion_reason"] == "recording_not_started"
    assert entry["removed_outputs"] == [str(path.resolve()) for path in expected_outputs]
    assert all(not path.exists() for path in expected_outputs)
    assert '"excluded_files": 1' in runs
    assert '"failed_files": 0' in runs

    excluded_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    assert excluded_plan.excluded_count == 1
    assert excluded_plan.incremental_files == ()
    assert excluded_plan.states[0].status == "excluded"

    info.path.write_bytes(b"valid replacement raw bytes")
    changed_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    assert changed_plan.states[0].status == "changed_raw"
    assert changed_plan.incremental_files == (info.path,)



def test_record_results_requires_at_least_one_expected_output_for_completed_status(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)

    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    ledger = json.loads(
        (project.project_root / ".fpvs_processing" / "processing_ledger.json").read_text(
            encoding="utf-8"
        )
    )

    entry = ledger["entries"]["P01"]
    assert entry["status"] == "failed"
    assert entry["failure_reason"] == "no_expected_outputs"
    assert entry["missing_condition_labels"] == ["Condition A"]


def test_clean_managed_excel_root_removes_workbooks_and_preserves_folders(tmp_path) -> None:
    project, _info = _project_with_raw(tmp_path)
    excel_root = project.subfolders["excel"]
    keep_file = project.project_root / "keep.txt"
    stale_file = excel_root / "Old" / "P01_Old_Results.xlsx"
    notes_file = excel_root / "Old" / "notes.txt"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("old", encoding="utf-8")
    notes_file.write_text("notes", encoding="utf-8")
    keep_file.write_text("keep", encoding="utf-8")

    cleaned_root = clean_managed_excel_root(project)

    assert cleaned_root == excel_root
    assert cleaned_root.exists()
    assert stale_file.parent.exists()
    assert not stale_file.exists()
    assert notes_file.exists()
    assert keep_file.exists()


def test_clean_managed_excel_root_resolves_relative_subfolder_from_project_root(tmp_path) -> None:
    project, _info = _project_with_raw(tmp_path)
    project.subfolders["excel"] = Path("1 - Excel Data Files")
    stale_file = project.project_root / "1 - Excel Data Files" / "Cond" / "P01_Cond_Results.xlsx"
    stale_file.parent.mkdir(parents=True)
    stale_file.write_text("old", encoding="utf-8")

    cleaned_root = clean_managed_excel_root(project)

    assert cleaned_root == (project.project_root / "1 - Excel Data Files").resolve()
    assert not stale_file.exists()


def test_clean_participant_outputs_deletes_only_planned_participant(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    p02 = info.path.parent / "P02.bdf"
    p02.write_bytes(b"raw")
    info2 = RawFileInfo(p02.resolve(), "P02")
    plan = classify_processing_inputs(
        project,
        [info, info2],
        _settings(),
        project.event_map,
    )
    output_p01 = plan.states[0].expected_outputs[0]
    output_p02 = plan.states[1].expected_outputs[0]
    output_p01.parent.mkdir(parents=True)
    output_p01.write_text("p01", encoding="utf-8")
    output_p02.write_text("p02", encoding="utf-8")
    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}, {"status": "ok", "file": str(info2.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    info.path.write_bytes(b"changed")
    stale_plan = classify_processing_inputs(
        project,
        [info, info2],
        _settings(),
        project.event_map,
    )

    deleted = clean_participant_outputs(project, stale_plan)

    assert deleted == [output_p01]
    assert not output_p01.exists()
    assert output_p02.exists()


def test_clean_participant_outputs_deletes_only_recorded_source_derivatives(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    info2 = _add_raw_file(info.path.parent, "P02")
    plan = classify_processing_inputs(
        project,
        [info, info2],
        _settings(),
        project.event_map,
    )
    _write_expected_outputs(plan)
    p01_source = _write_source_derivative_result(
        project,
        "P01",
        relative_paths=True,
    )
    p02_source = _write_source_derivative_result(
        project,
        "P02",
        relative_paths=True,
    )
    source_root = project.project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    unrelated = source_root / "unrelated-source-output.json"
    unrelated.write_text("preserve", encoding="utf-8")
    record_processing_results(
        project,
        plan,
        [
            {"status": "ok", "file": str(info.path), **p01_source},
            {"status": "ok", "file": str(info2.path), **p02_source},
        ],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    info.path.write_bytes(b"changed")
    stale_plan = classify_processing_inputs(
        project,
        [info, info2],
        _settings(),
        project.event_map,
    )

    deleted = clean_participant_outputs(project, stale_plan)

    p01_paths = {
        project.project_root / Path(str(path))
        for path in p01_source["source_derivative_outputs"]
    }
    p02_paths = {
        project.project_root / Path(str(path))
        for path in p02_source["source_derivative_outputs"]
    }
    assert p01_paths.issubset(set(deleted))
    assert all(not path.exists() for path in p01_paths)
    assert all(path.exists() for path in p02_paths)
    assert unrelated.exists()


def test_clean_participant_outputs_refuses_external_ledger_derivative_path(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    source_result = _write_source_derivative_result(project, "P01")
    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path), **source_result}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    external = tmp_path / "outside-source.fif"
    external.write_text("preserve", encoding="utf-8")
    ledger_path = project.project_root / ".fpvs_processing" / "processing_ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    ledger["entries"]["P01"]["source_derivative_outputs"].append(str(external))
    ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
    info.path.write_bytes(b"changed")
    stale_plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    excel_output = stale_plan.states[0].expected_outputs[0]

    with pytest.raises(ValueError, match="outside 6 - Source Localization"):
        clean_participant_outputs(project, stale_plan)

    assert external.exists()
    assert excel_output.exists()


def test_clean_participant_outputs_removes_preexisting_output_for_new_file(
    tmp_path,
) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(
        project,
        [info],
        _settings(),
        project.event_map,
    )
    assert plan.states[0].status == "new"
    stale_output = plan.states[0].expected_outputs[0]
    stale_output.parent.mkdir(parents=True, exist_ok=True)
    stale_output.write_text("untracked stale output", encoding="utf-8")

    deleted = clean_participant_outputs(project, plan)

    assert deleted == [stale_output]
    assert not stale_output.exists()


def test_clean_downstream_outputs_for_reprocess_all_removes_stale_generated_files(
    tmp_path,
) -> None:
    project, _info = _project_with_raw(tmp_path)
    stats_ready = (
        project.project_root
        / "3 - Statistical Analysis Results"
        / "Stats_Ready_Summed_BCA.xlsx"
    )
    snr_plot = project.subfolders["snr"] / "Condition - Central.png"
    scalp_source = project.project_root / "4 - Scalp Maps" / "Publication_Scalp_Maps_Source_Data.xlsx"
    source_file = project.project_root / "6 - Source Localization" / "stale.npz"
    table_file = project.project_root / "9 - Tables" / "Table 1.xlsx"
    stale_qc = project.project_root / "Quality Check" / "SNR_Spectral_QC_Condition.xlsx"
    unexpected_peaks_qc = (
        project.project_root / "Quality Check" / "SNR_Unexpected_Peaks_Condition.xlsx"
    )
    qc_summary = project.project_root / "Quality Check" / "Processing_QC_Summary.xlsx"
    preflight_review = (
        project.project_root / "Quality Check" / "Data_Quality_Check_Review_Flags.xlsx"
    )
    raw_file = Path(project.input_folder) / "P01.bdf"

    for path in (
        stats_ready,
        snr_plot,
        scalp_source,
        source_file,
        table_file,
        stale_qc,
        unexpected_peaks_qc,
        qc_summary,
        preflight_review,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale", encoding="utf-8")

    deleted = clean_downstream_outputs_for_reprocess_all(project)

    assert stats_ready in deleted
    assert stale_qc in deleted
    assert unexpected_peaks_qc in deleted
    assert qc_summary in deleted
    assert not stats_ready.exists()
    assert not snr_plot.exists()
    assert not scalp_source.exists()
    assert not source_file.exists()
    assert not table_file.exists()
    assert not stale_qc.exists()
    assert not unexpected_peaks_qc.exists()
    assert not qc_summary.exists()
    assert preflight_review.exists()
    assert raw_file.exists()


def test_reprocess_all_removes_empty_source_ready_derivative_tree(tmp_path) -> None:
    project, _info = _project_with_raw(tmp_path)
    source_root = project.project_root / SOURCE_READY_TIME_DOMAIN_RELATIVE_ROOT
    empty_nested = source_root / "Condition A" / "Control"
    empty_nested.mkdir(parents=True)

    clean_downstream_outputs_for_reprocess_all(project)

    assert not source_root.exists()


def test_clean_downstream_outputs_for_reprocess_all_refuses_external_folder(
    tmp_path,
) -> None:
    project, _info = _project_with_raw(tmp_path)
    external = tmp_path / "outside"
    external.mkdir()
    project.subfolders["stats"] = external

    try:
        clean_downstream_outputs_for_reprocess_all(project)
    except ValueError as exc:
        assert "Refusing to delete unmanaged stats output path" in str(exc)
    else:
        raise AssertionError("Expected external downstream folder cleanup to fail")


def test_reprocess_all_choice_runs_completed_files(tmp_path) -> None:
    project, info = _project_with_raw(tmp_path)
    plan = classify_processing_inputs(project, [info], _settings(), project.event_map)
    _write_expected_outputs(plan)
    record_processing_results(
        project,
        plan,
        [{"status": "ok", "file": str(info.path)}],
        run_mode="Batch",
        user_choice="incremental",
        cancelled=False,
    )
    completed = classify_processing_inputs(project, [info], _settings(), project.event_map)

    assert completed.incremental_files == ()
    assert with_processing_choice(completed, "reprocess_all").run_files == (info.path,)
