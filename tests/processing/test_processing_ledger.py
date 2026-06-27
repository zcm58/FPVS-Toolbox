from __future__ import annotations

import json
from pathlib import Path

from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    PROCESSING_FINGERPRINT_VERSION,
    classify_processing_inputs,
    clean_downstream_outputs_for_reprocess_all,
    clean_managed_excel_root,
    clean_participant_outputs,
    output_group_folder_by_file,
    record_processing_results,
    with_processing_choice,
)
from Main_App.projects.project import Project


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
    report_file = project.project_root / "5 - Publication Report" / "report.html"
    source_file = project.project_root / "6 - Source Localization" / "stale.npz"
    table_file = project.project_root / "9 - Tables" / "Table 1.xlsx"
    stale_qc = project.project_root / "Quality Check" / "SNR_Spectral_QC_Condition.xlsx"
    qc_summary = project.project_root / "Quality Check" / "Processing_QC_Summary.xlsx"
    preflight_review = (
        project.project_root / "Quality Check" / "Data_Quality_Check_Review_Flags.xlsx"
    )
    raw_file = Path(project.input_folder) / "P01.bdf"

    for path in (
        stats_ready,
        snr_plot,
        scalp_source,
        report_file,
        source_file,
        table_file,
        stale_qc,
        qc_summary,
        preflight_review,
    ):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("stale", encoding="utf-8")

    deleted = clean_downstream_outputs_for_reprocess_all(project)

    assert stats_ready in deleted
    assert stale_qc in deleted
    assert qc_summary in deleted
    assert not stats_ready.exists()
    assert not snr_plot.exists()
    assert not scalp_source.exists()
    assert not report_file.exists()
    assert not source_file.exists()
    assert not table_file.exists()
    assert not stale_qc.exists()
    assert not qc_summary.exists()
    assert preflight_review.exists()
    assert raw_file.exists()


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
