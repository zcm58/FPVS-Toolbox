from copy import deepcopy
from dataclasses import replace
import json

import pytest

from Main_App.io.eeg_geometry import biosemi64_geometry_identity
from Main_App.processing.frequency_domain_qc import mark_frequency_domain_outputs_current
from Main_App.processing.pipeline_plan import default_pipeline_config
from Main_App.processing.pipeline_settings_freshness import (
    PipelineSettingsChangedError, RECEIPT_KEY, REQUIREMENT_KEY,
    apply_pipeline_setup_freshness, pipeline_settings_identity,
    require_current_pipeline_settings,
)
from Main_App.processing.processing_controller import RawFileInfo
from Main_App.processing.processing_ledger import (
    build_processing_fingerprint, classify_processing_inputs, load_ledger,
    record_processing_results, require_current_preprocessing_qc_settings,
    save_ledger, with_processing_choice,
)
from Main_App.projects.hardware import brain_products_qc_defaults
from Main_App.projects.experimental_qc_settings import ExperimentalQcSettings
from Main_App.projects.preprocessing_settings import confirm_removed_electrode_detection_choice
from Main_App.projects.project import Project


def _write_manifest(root, manifest):
    (root / "project.json").write_text(json.dumps(manifest), encoding="utf-8")


def _marked_manifest():
    previous = {"preprocessing": {"low_pass": 50}}
    current = {"preprocessing": {"low_pass": 40}}
    assert apply_pipeline_setup_freshness(current, previous)
    return current


def test_same_defaults_and_confirmations_do_not_stale_outputs():
    previous = {"preprocessing": {}}
    current = deepcopy(previous)
    current["preprocessing"] = confirm_removed_electrode_detection_choice({}, "off")
    current["preprocessing"].update(
        processing_pipeline=default_pipeline_config(), hardware_platform="biosemi",
        hardware_confirmed=True, hardware_selection_source="user_selection",
    )
    assert not apply_pipeline_setup_freshness(current, previous)
    assert "tools" not in current


def test_nonbiosemi_implicit_qc_defaults_have_the_same_identity():
    previous = {"preprocessing": {"hardware_platform": "brain_products", "hardware_confirmed": True}}
    current = deepcopy(previous)
    current["experimental_qc"] = brain_products_qc_defaults(ExperimentalQcSettings()).to_manifest()
    assert pipeline_settings_identity(previous) == pipeline_settings_identity(current)


@pytest.mark.parametrize("field,value", [("low_pass", 40), ("downsample", 512), ("ref_chan1", "EXG3")])
def test_method_parameter_changes_mark_freshness_without_mutating_prior_manifest(field, value):
    previous = {"preprocessing": {}, "tools": {"processing": {
        "unrelated": {"value": 1}, "full_fft_provenance": {"status": "current"},
    }, "other_tool": {"retained": True}}}
    before = deepcopy(previous)
    current = deepcopy(previous)
    current["preprocessing"][field] = value
    assert apply_pipeline_setup_freshness(current, previous)
    assert previous == before
    assert current["tools"]["processing"][REQUIREMENT_KEY]["settings_identity"] == pipeline_settings_identity(current)
    assert current["tools"]["processing"]["full_fft_provenance"]["status"] == "stale"
    assert current["tools"]["processing"]["unrelated"] == {"value": 1}
    assert current["tools"]["frequency_domain_qc"]["downstream_outputs_stale"]
    assert current["tools"]["other_tool"] == {"retained": True}


@pytest.mark.parametrize("status", ["completed", "excluded", "failed", "incomplete"])
def test_one_current_recording_cannot_release_old_or_failed_other_recording(tmp_path, status):
    manifest = _marked_manifest()
    _write_manifest(tmp_path, manifest)
    ledger = {"entries": {
        "P01": {"status": "completed", RECEIPT_KEY: pipeline_settings_identity(manifest)},
        "P02": {"status": status, RECEIPT_KEY: "old"},
    }}
    with pytest.raises(PipelineSettingsChangedError, match="P02"):
        require_current_pipeline_settings(tmp_path, ledger=ledger)
    with pytest.raises(PipelineSettingsChangedError, match="P02"):
        require_current_preprocessing_qc_settings(tmp_path, ledger)


def test_missing_registered_recording_is_not_ignored(tmp_path):
    manifest = _marked_manifest()
    manifest.update(groups={"control": {"label": "Control", "raw_input_folder": "raw"}},
                    participants={"P01": {"group_id": "control"}, "P02": {"group_id": "control"}})
    _write_manifest(tmp_path, manifest)
    ledger = {"entries": {"P01": {"status": "completed", RECEIPT_KEY: pipeline_settings_identity(manifest)}}}
    with pytest.raises(PipelineSettingsChangedError, match="P02"):
        require_current_pipeline_settings(tmp_path, ledger=ledger)


def test_required_contributor_generator_is_preserved_for_freshness_checks(tmp_path):
    manifest = _marked_manifest()
    manifest.update(groups={"control": {"label": "Control", "raw_input_folder": "raw"}},
                    participants={"P01": {"group_id": "control"}})
    _write_manifest(tmp_path, manifest)
    ledger = {"entries": {"P01": {"status": "completed", RECEIPT_KEY: pipeline_settings_identity(manifest)}}}
    with pytest.raises(PipelineSettingsChangedError, match="legacy_contributor"):
        require_current_preprocessing_qc_settings(
            tmp_path, ledger, required_processing_ids=(value for value in ("legacy_contributor",)),
        )


def test_current_automatic_exclusion_receipt_satisfies_processing_guard(tmp_path):
    manifest = _marked_manifest()
    _write_manifest(tmp_path, manifest)
    require_current_pipeline_settings(tmp_path, ledger={"entries": {
        "P01": {"status": "excluded", "exclusion_reason": "raw_channel_qc",
                RECEIPT_KEY: pipeline_settings_identity(manifest)},
    }})


@pytest.mark.parametrize("reason", ["manual_participant_exclusion", "manual_recording_exclusion", "recording_not_started"])
def test_explicit_geometry_independent_exclusions_do_not_require_processing(tmp_path, reason):
    manifest = _marked_manifest()
    _write_manifest(tmp_path, manifest)
    require_current_pipeline_settings(tmp_path, ledger={"entries": {
        "P01": {"status": "excluded", "exclusion_reason": reason},
    }})


def test_direct_mark_current_cannot_clear_reprocessing_requirement(tmp_path):
    manifest = _marked_manifest()
    _write_manifest(tmp_path, manifest)
    before = (tmp_path / "project.json").read_bytes()
    save_ledger(tmp_path, {"entries": {"P01": {"status": "completed"}}})
    with pytest.raises(PipelineSettingsChangedError, match="Run Processing"):
        mark_frequency_domain_outputs_current(tmp_path)
    assert (tmp_path / "project.json").read_bytes() == before


def test_processing_receipts_allow_release_only_after_all_recordings_complete(tmp_path):
    project = Project.load(tmp_path / "project")
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    infos = []
    for name in ("P01", "P02"):
        raw = raw_dir / f"{name}.bdf"
        raw.write_bytes(b"raw")
        infos.append(RawFileInfo(raw.resolve(), name))
    project.input_folder = raw_dir
    project.event_map = {"Faces": 1}
    project.save()
    previous = json.loads(project.manifest_path.read_text(encoding="utf-8"))
    project.update_preprocessing({**project.preprocessing, "low_pass": 40})
    project.save()
    changed = json.loads(project.manifest_path.read_text(encoding="utf-8"))
    assert apply_pipeline_setup_freshness(changed, previous)
    _write_manifest(project.project_root, changed)
    project.manifest = deepcopy(changed)
    settings = {"high_pass": 0.1, "low_pass": 40, "downsample": 256}
    identity_before_receipts = build_processing_fingerprint(project, settings, project.event_map)
    save_ledger(project.project_root, {"entries": {
        info.subject_id: {"status": "completed", RECEIPT_KEY: "old"} for info in infos
    }})
    for index, info in enumerate(infos):
        plan = classify_processing_inputs(project, [info], settings, project.event_map)
        assert plan.states[0].status == "changed_settings"
        plan = with_processing_choice(plan, "incremental")
        for output in plan.states[0].expected_outputs:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text("ok", encoding="utf-8")
        record_processing_results(
            project, plan, [{"status": "ok", "geometry": biosemi64_geometry_identity(), "file": str(info.path)}],
            run_mode="Single", user_choice="incremental", cancelled=False,
        )
        receipt = load_ledger(project.project_root)["entries"][info.subject_id][RECEIPT_KEY]
        assert receipt == plan.pipeline_settings_identity == pipeline_settings_identity(changed)
        if index == 0:
            with pytest.raises(PipelineSettingsChangedError, match="P02"):
                mark_frequency_domain_outputs_current(project.project_root)
    require_current_pipeline_settings(project.project_root)
    mark_frequency_domain_outputs_current(project.project_root)
    published = json.loads(project.manifest_path.read_text(encoding="utf-8"))
    assert published["tools"]["frequency_domain_qc"]["downstream_outputs_stale"] is False
    assert REQUIREMENT_KEY in published["tools"]["processing"]
    assert build_processing_fingerprint(project, settings, project.event_map) == identity_before_receipts


def test_plan_keeps_processing_time_identity_when_project_changes_later(tmp_path):
    project = Project.load(tmp_path / "project")
    original = classify_processing_inputs(project, [], {}, {})
    project.preprocessing["low_pass"] = 40
    later = classify_processing_inputs(project, [], {}, {})
    assert original.pipeline_settings_identity != later.pipeline_settings_identity
    assert with_processing_choice(original, "reprocess_all").pipeline_settings_identity == original.pipeline_settings_identity


def test_legacy_without_setup_marker_is_unchanged(tmp_path):
    _write_manifest(tmp_path, {"preprocessing": {"low_pass": 40}})
    require_current_pipeline_settings(tmp_path, ledger={"entries": {"P01": {"status": "completed"}}})


def test_qc_review_decisions_do_not_change_global_pipeline_identity():
    previous = {"preprocessing": {}}
    current = deepcopy(previous)
    current["preprocessing"]["manual_removed_electrodes"] = {"P02": ["Cz"]}
    current["preprocessing"]["experimental_ram_preload"] = True
    current["experimental_qc"] = replace(ExperimentalQcSettings(), snr_spectral_screening_enabled=False).to_manifest()
    assert pipeline_settings_identity(current) == pipeline_settings_identity(previous)
