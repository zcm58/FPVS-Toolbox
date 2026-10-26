"""Guided setup drafts are independent, validated and atomically published."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json

import pytest

from Main_App.processing import pipeline_plan
from Main_App.projects import manifest_store
from Main_App.projects.frequency_protocol import FrequencyProtocol
from Main_App.projects.hardware import HardwareChangeConfirmationRequired
from Main_App.projects.pipeline_setup import (
    PIPELINE_SETUP_PAGES, PipelineSetupConflict, PipelineSetupDraft,
)
from Main_App.projects.project import Project

pytestmark = pytest.mark.project_io


@pytest.fixture
def project(tmp_path):
    project = Project.load(tmp_path)
    project.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144,
        expected_analyzed_oddball_cycles_source="manual",
    ))
    project.save()
    return project


def _read(project):
    return json.loads(project.manifest_path.read_bytes())


def _write(project, data):
    with manifest_store.project_manifest_transaction(project.manifest_path) as transaction:
        transaction.write(data)


def test_draft_changes_and_cancel_do_not_mutate_project_or_manifest(project):
    before = deepcopy(project.__dict__)
    original = project.manifest_path.read_bytes()
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    draft.update_frequency_protocol(draft.frequency_protocol.with_expected_cycles(120, source="manual"))
    draft.update_experimental_qc_settings({"raw_signal_screening_enabled": True})
    assert draft.requires_reprocessing
    assert project.__dict__ == before
    assert project.manifest_path.read_bytes() == original


def test_all_steps_have_one_review_location_and_descriptive_methods(project):
    stages = [stage for page in PIPELINE_SETUP_PAGES for stage in page.stage_ids]
    assert len(stages) == len(set(stages)) == len(pipeline_plan.PIPELINE_STEPS)
    assert set(stages) == {step.id for step in pipeline_plan.PIPELINE_STEPS}
    draft = PipelineSetupDraft.from_project(project)
    assert draft.method_rows("filtering")[0] == ("Temporal filter", "FIR · Hamming · zero-double phase")
    draft.validate()
    assert not draft.review_changes()
    assert not draft.requires_reprocessing


def test_save_persists_processing_once_and_keeps_unrelated_live_and_disk_edits(project, monkeypatch):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    disk = _read(project)
    disk["tools"] = {"external_tool": {"revision": 23}}
    disk["unrelated"] = "new disk value"
    _write(project, disk)
    project.name = "Unsaved live name"
    project.manifest["live_note"] = "keep me"
    writes = []
    original = manifest_store.ManifestTransaction.write

    def tracked_write(self, data):
        writes.append(deepcopy(data))
        return original(self, data)

    monkeypatch.setattr(manifest_store.ManifestTransaction, "write", tracked_write)
    assert draft.save(project)
    saved = _read(project)
    assert len(writes) == 1
    assert saved["preprocessing"]["low_pass"] == 42
    assert saved["tools"]["external_tool"] == {"revision": 23}
    assert saved["unrelated"] == "new disk value"
    assert "live_note" not in saved
    assert project.name == "Unsaved live name"
    assert project.manifest["live_note"] == "keep me"
    assert project.preprocessing["low_pass"] == 42
    assert not draft.requires_reprocessing
    assert not draft.save(project)


def test_hidden_preprocessing_fields_and_protocol_provenance_survive(project):
    disk = _read(project)
    disk["preprocessing"]["future_extension"] = {"retain": [1, 2]}
    _write(project, disk)
    project = Project.load(project.project_root)
    draft = PipelineSetupDraft.from_project(project)
    original_protocol = deepcopy(disk["frequency_protocol"])
    original_harmonics = {key: value for key, value in disk["preprocessing"].items() if "harmonic" in key}
    draft.update_preprocessing({"high_pass": 0.2})
    draft.save(project)
    saved = _read(project)
    assert saved["preprocessing"]["future_extension"] == {"retain": [1, 2]}
    assert saved["frequency_protocol"] == original_protocol
    assert {key: value for key, value in saved["preprocessing"].items() if "harmonic" in key} == original_harmonics


@pytest.mark.parametrize("namespace", ["preprocessing", "frequency_protocol", "experimental_qc"])
def test_concurrent_processing_change_rejected_without_overwrite(project, namespace):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    disk = _read(project)
    if namespace == "preprocessing":
        disk[namespace]["low_pass"] = 43
    elif namespace == "frequency_protocol":
        disk[namespace]["entered_oddball_rate_hz"] = "1.2"
    else:
        disk[namespace]["raw_signal_screening_enabled"] = True
    _write(project, disk)
    before = project.manifest_path.read_bytes()
    live = deepcopy(project.__dict__)
    with pytest.raises(PipelineSetupConflict, match="another window"):
        draft.save(project)
    assert project.manifest_path.read_bytes() == before
    assert project.__dict__ == live
    assert draft.preprocessing["low_pass"] == 42


def test_concurrent_live_processing_change_rejected(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    project.preprocessing["high_pass"] = 0.3
    with pytest.raises(PipelineSetupConflict, match="while setup was open"):
        draft.save(project)
    assert project.preprocessing["high_pass"] == 0.3


def test_stale_project_cannot_open_draft_over_newer_saved_settings(project):
    disk = _read(project)
    disk["preprocessing"]["low_pass"] = 43
    _write(project, disk)
    with pytest.raises(PipelineSetupConflict, match="differ from the saved"):
        PipelineSetupDraft.from_project(project)


def test_atomic_write_failure_leaves_live_and_saved_project_unchanged(project, monkeypatch):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    before = project.manifest_path.read_bytes()
    live = deepcopy(project.__dict__)

    def fail(*args):
        raise PermissionError("Manifest is locked")

    monkeypatch.setattr(manifest_store, "_replace_manifest", fail)
    with pytest.raises(PermissionError):
        draft.save(project)
    assert project.manifest_path.read_bytes() == before
    assert project.__dict__ == live
    assert draft.preprocessing["low_pass"] == 42
    assert not list(project.project_root.glob(".project.json.*.tmp"))


def test_default_method_explicitness_preserves_legacy_identity(project):
    disk = _read(project)
    disk["preprocessing"].pop("processing_pipeline")
    _write(project, disk)
    project = Project.load(project.project_root)
    draft = PipelineSetupDraft.from_project(project)
    assert "processing_pipeline" not in draft.preprocessing
    assert not draft.save(project)
    assert "processing_pipeline" not in _read(project)["preprocessing"]
    draft.update_preprocessing({"processing_pipeline": pipeline_plan.default_pipeline_config()})
    assert not draft.requires_reprocessing
    draft.save(project)
    assert Project.load(project.project_root).preprocessing["processing_pipeline"] == pipeline_plan.default_pipeline_config()


def test_unknown_methods_fail_before_publication_and_registered_alternative_roundtrips(project, monkeypatch):
    draft = PipelineSetupDraft.from_project(project)
    with pytest.raises(ValueError, match="Unavailable"):
        draft.select_method("temporal_filter", "not_registered")
    assert not draft.requires_reprocessing
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(
        pipeline_plan.PipelineMethod("temporal_filter", "test_filter_v1", "Test filter", lambda context: None))
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    draft.select_method("temporal_filter", "test_filter_v1")
    assert draft.requires_reprocessing
    assert draft.method_rows("filtering")[0][1] == "Test filter"
    draft.save(project)
    assert Project.load(project.project_root).preprocessing["processing_pipeline"]["methods"]["temporal_filter"] == "test_filter_v1"


@pytest.mark.parametrize("platform", ["brain_products", "biosemi_active_three", "unicorn"])
def test_hardware_change_requires_explicit_confirmation_and_applies_supported_defaults(project, platform):
    draft = PipelineSetupDraft.from_project(project)
    with pytest.raises(HardwareChangeConfirmationRequired):
        draft.confirm_hardware(platform)
    draft.confirm_hardware(platform, confirmed_change=True)
    assert not draft.experimental_qc_settings.raw_signal_screening_enabled
    assert not draft.experimental_qc_settings.kurtosis_screening_enabled
    draft.validate()
    draft.save(project)
    assert Project.load(project.project_root).preprocessing["hardware_platform"] == platform
    if platform == "unicorn":
        assert draft.preprocessing["downsample"] == 250
        assert not draft.capabilities.resampling_allowed
        assert not draft.capabilities.interpolation_allowed
        assert not draft.control_policy.initial_reference_editable
        assert not draft.control_policy.channel_limit_editable
        assert draft.control_policy.allowed_montages == (("unicorn8", "Unicorn Hybrid Black 8"),)


def test_direct_hardware_mutation_cannot_bypass_warning(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.preprocessing.update(hardware_platform="brain_products", hardware_confirmed=True)
    with pytest.raises(HardwareChangeConfirmationRequired):
        draft.save(project)


@pytest.mark.parametrize("key,value,page", [("downsample", 0, "resampling"), ("low_pass", float("nan"), "filtering"),
                                         ("rejection_z", float("inf"), "qc")])
def test_invalid_numbers_rejected_by_relevant_page(project, key, value, page):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({key: value})
    with pytest.raises(ValueError):
        draft.validate_page(page)


def test_unsupported_qc_cannot_be_enabled_for_unqualified_hardware(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.confirm_hardware("brain_products", confirmed_change=True)
    draft.experimental_qc_settings = replace(draft.experimental_qc_settings, raw_signal_screening_enabled=True)
    with pytest.raises(ValueError, match="unavailable"):
        draft.validate_page("qc")


def test_protocol_requires_confirmation_and_exact_sampling_grid(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_frequency_protocol(FrequencyProtocol.confirmation_required())
    with pytest.raises(ValueError, match="Confirm the project protocol"):
        draft.validate_page("epochs")
    draft.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=1, expected_analyzed_oddball_cycles_source="manual"))
    with pytest.raises(ValueError, match="sampling-rate grid"):
        draft.validate_page("epochs")


def test_final_save_validates_concurrent_condition_marker_changes(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    disk = _read(project)
    disk["event_map"] = {"new condition": 55}
    _write(project, disk)
    with pytest.raises(ValueError, match="condition-onset code"):
        draft.save(project)
    assert _read(project)["preprocessing"]["low_pass"] == 50


def test_unicorn_mapping_change_removes_obsolete_factory_evidence(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.confirm_hardware("unicorn", confirmed_change=True)
    draft.update_preprocessing({"electrode_mapping_profile": "unicorn_factory_v1"})
    assert draft.preprocessing["acquisition_profile"]["source_to_canonical"]
    draft.update_preprocessing({"electrode_mapping_profile": "anatomical_labels"})
    assert "source_to_canonical" not in draft.preprocessing["acquisition_profile"]
    assert "label_mapping_evidence" not in draft.preprocessing["acquisition_profile"]
    draft.save(project)
    assert "source_to_canonical" not in _read(project)["preprocessing"]["acquisition_profile"]


def test_unconfirmed_hardware_can_preview_controls_but_cannot_pass_recording_page(project):
    initial = PipelineSetupDraft.from_project(project)
    initial.confirm_hardware("unicorn", confirmed_change=True)
    initial.save(project)
    disk = _read(project)
    disk["preprocessing"]["hardware_confirmed"] = False
    _write(project, disk)
    project = Project.load(project.project_root)
    draft = PipelineSetupDraft.from_project(project)
    assert not draft.capabilities.resampling_allowed
    assert draft.control_policy.initial_reference_editor == "fixed"
    assert "unavailable" in dict(draft.method_rows("qc"))["Interpolation"]
    with pytest.raises(ValueError, match="Confirm this project's EEG hardware"):
        draft.validate_page("recording")


def test_scientific_change_marks_existing_results_stale_atomically(project):
    disk = _read(project)
    disk["tools"] = {"processing": {"full_fft_provenance": {"status": "current", "keep": 123}},
                     "frequency_domain_qc": {"keep": 456}}
    _write(project, disk)
    project = Project.load(project.project_root)
    draft = PipelineSetupDraft.from_project(project)
    draft.update_preprocessing({"low_pass": 42})
    draft.save(project)
    saved = _read(project)
    processing = saved["tools"]["processing"]
    assert len(processing["pipeline_setup_requirements"]["settings_identity"]) == 64
    assert processing["full_fft_provenance"]["status"] == "stale"
    assert processing["full_fft_provenance"]["keep"] == 123
    assert saved["tools"]["frequency_domain_qc"]["downstream_outputs_stale"]
    assert saved["tools"]["frequency_domain_qc"]["keep"] == 456
    assert project.manifest["tools"] == saved["tools"]


def test_confirmation_only_does_not_require_reprocessing(project):
    draft = PipelineSetupDraft.from_project(project)
    draft.confirm_hardware("biosemi")
    draft.confirm_removed_electrode_choice("off")
    assert not draft.requires_reprocessing
    draft.save(project)
    assert "pipeline_setup_requirements" not in _read(project).get("tools", {}).get("processing", {})


def test_legacy_project_protocol_can_be_explicitly_confirmed_without_erasing_unknown_fields(tmp_path):
    project = Project.load(tmp_path, manifest={"preprocessing": {}, "retained": True})
    project.save()
    draft = PipelineSetupDraft.from_project(project)
    draft.confirm_removed_electrode_choice("off")
    draft.update_frequency_protocol(FrequencyProtocol.from_recurrence(
        6, 5, expected_analyzed_oddball_cycles=144, expected_analyzed_oddball_cycles_source="manual"))
    draft.save(project)
    saved = _read(project)
    assert saved["retained"]
    assert saved["frequency_protocol"]["status"] == "ready"
    assert "processing_pipeline" not in saved["preprocessing"]


def test_raw_screening_catalog_remains_active_for_automatic_removed_electrode_detection(project):
    draft = PipelineSetupDraft.from_project(project)
    assert "(off)" in dict(draft.method_rows("qc"))["Raw signal screening"]
    draft.confirm_removed_electrode_choice("auto")
    assert "(off)" not in dict(draft.method_rows("qc"))["Raw signal screening"]
