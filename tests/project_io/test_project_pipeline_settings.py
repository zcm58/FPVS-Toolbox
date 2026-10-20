"""Project-owned method selections persist without changing legacy behavior."""
from __future__ import annotations

from copy import deepcopy
import json

import pytest

from Main_App.processing import pipeline_plan
from Main_App.processing.pipeline_plan import PipelineMethod, default_pipeline_config
from Main_App.processing.processing_ledger import build_processing_fingerprint
from Main_App.projects.hardware import confirm_hardware_selection
from Main_App.projects.preprocessing_settings import (
    new_project_preprocessing_settings, normalize_preprocessing_settings,
    processing_metadata_snapshot,
)
from Main_App.projects.project import Project


@pytest.fixture
def alternate_methods(monkeypatch):
    # Register inert test callables to exercise future method identity/persistence;
    # these tests never invoke numerical processing or claim method validation.
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(
        PipelineMethod("temporal_filter", "test_filter_a_v1", "Test filter A", lambda *args, **kwargs: None),
        PipelineMethod("temporal_filter", "test_filter_b_v1", "Test filter B", lambda *args, **kwargs: None),
    )
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    first, second = default_pipeline_config(), default_pipeline_config()
    first["methods"]["temporal_filter"] = "test_filter_a_v1"
    second["methods"]["temporal_filter"] = "test_filter_b_v1"
    return first, second


def _save_manifest(project):
    project.save()
    return json.loads((project.project_root / "project.json").read_text(encoding="utf-8"))


def test_legacy_projects_do_not_gain_method_configuration_on_roundtrip(tmp_path):
    assert "processing_pipeline" not in normalize_preprocessing_settings({})
    project = Project.load(tmp_path, manifest={"preprocessing": {}})
    assert "processing_pipeline" not in _save_manifest(project)["preprocessing"]
    assert "processing_pipeline" not in Project.load(tmp_path).preprocessing
    assert processing_metadata_snapshot(normalize_preprocessing_settings({})) == {}


def test_new_project_has_detached_explicit_default_methods():
    first = new_project_preprocessing_settings()
    second = new_project_preprocessing_settings()
    assert first["processing_pipeline"] == default_pipeline_config()
    first["processing_pipeline"]["methods"]["temporal_filter"] = "invalid"
    assert second["processing_pipeline"] == default_pipeline_config()


@pytest.mark.parametrize("value", [None, {}, {"schema_version": "unknown", "methods": {}},
                                  {"schema_version": "1.0", "methods": {}}])
def test_explicit_invalid_configuration_is_not_discarded_by_legacy_load_fallback(tmp_path, value):
    with pytest.raises(ValueError):
        normalize_preprocessing_settings({"processing_pipeline": value})
    with pytest.raises(ValueError, match="preprocessing settings"):
        Project.load(tmp_path, manifest={"preprocessing": {"processing_pipeline": value}})


def test_unknown_method_is_rejected_on_load_and_before_fingerprinting(tmp_path):
    selected = default_pipeline_config()
    selected["methods"]["temporal_filter"] = "unavailable_filter_v1"
    with pytest.raises(ValueError, match="Unavailable processing method"):
        Project.load(tmp_path, manifest={"preprocessing": {"processing_pipeline": selected}})
    project = Project.load(tmp_path)
    with pytest.raises(ValueError, match="Unavailable processing method"):
        build_processing_fingerprint(project, {"processing_pipeline": selected}, {})


def test_existing_methods_roundtrip_and_survive_old_style_settings_updates(tmp_path):
    project = Project.load(tmp_path, manifest={"preprocessing": {"processing_pipeline": default_pipeline_config()}})
    project.update_preprocessing({"low_pass": 42.0})
    saved = _save_manifest(project)
    assert saved["preprocessing"]["processing_pipeline"] == default_pipeline_config()
    assert Project.load(tmp_path).preprocessing["processing_pipeline"] == default_pipeline_config()


def test_alternate_method_roundtrips_in_project_and_detached_worker_snapshot(tmp_path, alternate_methods):
    first, _ = alternate_methods
    project = Project.load(tmp_path, manifest={"preprocessing": {"processing_pipeline": first}})
    _save_manifest(project)
    reopened = Project.load(tmp_path)
    assert reopened.preprocessing["processing_pipeline"] == first
    snapshot = processing_metadata_snapshot(reopened.preprocessing)
    snapshot["processing_pipeline"]["methods"]["temporal_filter"] = "test_filter_b_v1"
    assert reopened.preprocessing["processing_pipeline"] == first


def test_stale_unrelated_save_preserves_newer_pipeline_and_parameters(tmp_path, alternate_methods):
    first, _ = alternate_methods
    stale = Project.load(tmp_path)
    stale.save()
    concurrent = Project.load(tmp_path)
    concurrent.preprocessing["processing_pipeline"] = first
    concurrent.save()
    stale.name = "Unrelated edit"
    stale.preprocessing["low_pass"] = 42.0
    stale.save()
    reopened = Project.load(tmp_path)
    assert reopened.name == "Unrelated edit"
    assert reopened.preprocessing["low_pass"] == 42.0
    assert reopened.preprocessing["processing_pipeline"] == first


def test_conflicting_method_saves_fail_without_overwriting_disk_or_local_draft(tmp_path, alternate_methods):
    first, second = alternate_methods
    stale = Project.load(tmp_path)
    stale.save()
    concurrent = Project.load(tmp_path)
    concurrent.preprocessing["processing_pipeline"] = first
    concurrent.save()
    before = (tmp_path / "project.json").read_bytes()
    stale.preprocessing["processing_pipeline"] = second
    with pytest.raises(ValueError, match="pipeline changed in another window"):
        stale.save()
    assert (tmp_path / "project.json").read_bytes() == before
    assert stale.preprocessing["processing_pipeline"] == second


def test_untouched_runtime_refresh_picks_up_new_method_and_invalid_disk_fails(tmp_path, alternate_methods):
    first, _ = alternate_methods
    stale = Project.load(tmp_path)
    stale.save()
    concurrent = Project.load(tmp_path)
    concurrent.preprocessing["processing_pipeline"] = first
    manifest = _save_manifest(concurrent)
    stale.refresh_processing_pipeline_settings()
    assert stale.preprocessing["processing_pipeline"] == first
    manifest["preprocessing"]["processing_pipeline"]["methods"]["temporal_filter"] = "unknown"
    path = tmp_path / "project.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = path.read_bytes()
    with pytest.raises(ValueError, match="Unavailable"):
        stale.save()
    assert path.read_bytes() == before


def test_default_method_configuration_keeps_legacy_ledger_fingerprint(tmp_path):
    project = Project.load(tmp_path, manifest={"preprocessing": {}})
    settings = {"high_pass": 0.1, "low_pass": 50.0, "downsample": 256}
    baseline = build_processing_fingerprint(project, settings, {})
    explicit = {"processing_pipeline": default_pipeline_config()}
    assert build_processing_fingerprint(project, {**settings, **explicit}, {}) == baseline
    project.preprocessing.update(deepcopy(explicit))
    assert build_processing_fingerprint(project, settings, {}) == baseline
    assert build_processing_fingerprint(project, {**settings, **explicit}, {}) == baseline


def test_registered_alternative_changes_identity_and_runtime_must_match_project(tmp_path, alternate_methods):
    first, second = alternate_methods
    project = Project.load(tmp_path, manifest={"preprocessing": {}})
    baseline = build_processing_fingerprint(project, {}, {})
    project.preprocessing["processing_pipeline"] = first
    selected = build_processing_fingerprint(project, {"processing_pipeline": first}, {})
    assert selected != baseline
    with pytest.raises(ValueError, match="pipeline method selections disagree"):
        build_processing_fingerprint(project, {}, {})
    with pytest.raises(ValueError, match="pipeline method selections disagree"):
        build_processing_fingerprint(project, {"processing_pipeline": second}, {})


@pytest.mark.parametrize("platform", ["brain_products", "biosemi_active_three", "unicorn"])
def test_worker_metadata_preserves_each_nonlegacy_acquisition_contract(platform):
    settings = confirm_hardware_selection({}, platform, confirmed_change=True)
    if platform == "unicorn":
        settings["electrode_mapping_profile"] = "unicorn_factory_v1"
        settings["recording_event_policy"] = {"authority": "status"}
    else:
        settings.update(initial_reference="channels", initial_reference_channels=["TP9", "TP10"],
                        drop_reference_channels=True, channel_types={"VEOG": "eog"})
    settings["processing_pipeline"] = default_pipeline_config()
    normalized = normalize_preprocessing_settings(settings)
    snapshot = processing_metadata_snapshot(normalized)
    assert snapshot["hardware_platform"] == platform
    assert snapshot["processing_pipeline"] == default_pipeline_config()
    if platform == "unicorn":
        assert snapshot["acquisition_profile"] == normalized["acquisition_profile"]
        assert snapshot["recording_event_policy"] == normalized["recording_event_policy"]
    else:
        assert snapshot["initial_reference_channels"] == ["TP9", "TP10"]
        assert snapshot["drop_reference_channels"] is True
        assert snapshot["channel_types"] == {"VEOG": "eog"}
    assert "kurtosis_screening_enabled" not in snapshot


def test_explicit_active_two_worker_metadata_keeps_previous_shape():
    settings = normalize_preprocessing_settings(confirm_hardware_selection({}, "biosemi"))
    assert processing_metadata_snapshot(settings) == {"hardware_platform": "biosemi", "hardware_confirmed": True}


def test_condition_repair_identity_preserves_explicit_defaults_and_binds_alternatives(tmp_path, alternate_methods):
    from Main_App.processing.condition_interpolation_state import project_processing_identity

    project = Project.load(tmp_path)
    project.save()
    implicit = project_processing_identity(tmp_path)
    project.preprocessing["processing_pipeline"] = default_pipeline_config()
    project.save()
    assert project_processing_identity(tmp_path) == implicit
    project.preprocessing["processing_pipeline"] = alternate_methods[0]
    project.save()
    alternative = project_processing_identity(tmp_path)
    assert alternative != implicit
    project.preprocessing["processing_pipeline"] = alternate_methods[1]
    project.save()
    assert project_processing_identity(tmp_path) not in {implicit, alternative}


def test_condition_repair_identity_rejects_unavailable_methods(tmp_path):
    from Main_App.processing.condition_interpolation_state import project_processing_identity

    invalid = default_pipeline_config()
    invalid["methods"]["temporal_filter"] = "unavailable_filter_v1"
    (tmp_path / "project.json").write_text(
        json.dumps({"preprocessing": {"processing_pipeline": invalid}}), encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Unavailable processing method"):
        project_processing_identity(tmp_path)
