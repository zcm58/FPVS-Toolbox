"""Executable replacement, serialization and immutable default method identity."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
import json
from types import SimpleNamespace

import pytest

from Main_App.processing import pipeline_plan as module
from Main_App.processing.pipeline_plan import (
    BUILTIN_PIPELINE_REGISTRY, PIPELINE_STEPS, PipelineConfigurationError,
    PipelineExecutionError, PipelineMethod, PipelinePlan, default_pipeline_config,
    fingerprint_settings, normalize_pipeline_config, pipeline_fingerprint_payload,
    resolve_pipeline_plan,
)


def test_implicit_and_explicit_methods_have_identical_historical_identity():
    settings = {"high_pass": 1.0, "downsample_rate": 128}
    explicit = {**settings, "processing_pipeline": default_pipeline_config()}
    assert resolve_pipeline_plan(settings) == resolve_pipeline_plan(explicit)
    assert pipeline_fingerprint_payload(settings) == pipeline_fingerprint_payload(explicit) == {}
    assert fingerprint_settings(explicit) == settings
    assert json.loads(json.dumps(default_pipeline_config())) == default_pipeline_config()
    assert normalize_pipeline_config(default_pipeline_config()) == default_pipeline_config()


def test_replacement_executes_only_its_slot_and_changes_identity(monkeypatch):
    calls = []
    def replacement(values, *, scale):
        calls.append("replacement")
        return [value * scale for value in values]
    registry = BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod(
        "temporal_filter", "test_gain_v1", "Test gain", replacement,
    ))
    monkeypatch.setattr(module, "get_pipeline_registry", lambda: registry)
    config = default_pipeline_config()
    config["methods"]["temporal_filter"] = "test_gain_v1"
    settings = {"processing_pipeline": config}
    plan = resolve_pipeline_plan(settings)
    def builtin(values, *, scale):
        calls.append("builtin")
        return values
    assert plan.execute("temporal_filter", builtin, [2, 3], scale=2) == [4, 6]
    assert plan.execute("resample", builtin, [2, 3], scale=2) == [2, 3]
    assert calls == ["replacement", "builtin"]
    assert pipeline_fingerprint_payload(settings) == settings
    assert fingerprint_settings(settings) == settings
    config["methods"]["temporal_filter"] = "corrupted_after_resolution"
    assert plan.to_config()["methods"]["temporal_filter"] == "test_gain_v1"


@pytest.mark.parametrize("change", [
    lambda value: value.update(schema_version="2.0"),
    lambda value: value.update(order=["resample", "temporal_filter"]),
    lambda value: value["methods"].pop("temporal_filter"),
    lambda value: value["methods"].update(fake="test_v1"),
    lambda value: value["methods"].update(temporal_filter="guarded_fft_resample_v1"),
    lambda value: value["methods"].update(temporal_filter="fir_hamming_zero_double_v2"),
    lambda value: value["methods"].update(temporal_filter={"module": "arbitrary.py"}),
])
def test_invalid_project_methods_fail_before_execution(change):
    value = default_pipeline_config()
    change(value)
    with pytest.raises(PipelineConfigurationError):
        resolve_pipeline_plan({"processing_pipeline": value})


@pytest.mark.parametrize("value", [None, [], "default", 1, {}])
def test_explicit_malformed_config_is_not_a_legacy_fallback(value):
    with pytest.raises(PipelineConfigurationError):
        resolve_pipeline_plan({"processing_pipeline": value})


def test_registry_cannot_redefine_historical_ids_or_move_methods():
    builtin = BUILTIN_PIPELINE_REGISTRY.methods[0]
    with pytest.raises(PipelineConfigurationError, match="unique"):
        BUILTIN_PIPELINE_REGISTRY.with_methods(builtin)
    with pytest.raises(PipelineConfigurationError, match="new method ID"):
        module.PipelineRegistry((replace(builtin, implementation=lambda: None), *BUILTIN_PIPELINE_REGISTRY.methods[1:]))
    with pytest.raises(PipelineConfigurationError, match="executable"):
        BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod("resample", "other_v1", "Other"))
    with pytest.raises(PipelineConfigurationError, match="fixed order"):
        PipelinePlan(tuple(reversed(BUILTIN_PIPELINE_REGISTRY.methods)))


def test_capability_requirements_use_generic_recording_facts():
    method = PipelineMethod("resample", "new_sampling_v1", "New sampling", lambda: None, ("resampling_allowed",))
    registry = BUILTIN_PIPELINE_REGISTRY.with_methods(method)
    settings = {"processing_pipeline": default_pipeline_config()}
    settings["processing_pipeline"]["methods"]["resample"] = method.method_id
    plan = resolve_pipeline_plan(settings, registry=registry)
    plan.validate_capabilities(SimpleNamespace(resampling_allowed=True))
    with pytest.raises(PipelineConfigurationError, match="unavailable recording"):
        plan.validate_capabilities(SimpleNamespace(resampling_allowed=False))
    assert method not in registry.available_methods("resample", SimpleNamespace(resampling_allowed=False))


def test_replacement_errors_are_distinct_from_historical_builtin_errors():
    def fail():
        raise ValueError("test failure")
    method = PipelineMethod("spectrum", "broken_v1", "Broken", fail)
    config = default_pipeline_config()
    config["methods"]["spectrum"] = method.method_id
    plan = resolve_pipeline_plan({"processing_pipeline": config}, registry=BUILTIN_PIPELINE_REGISTRY.with_methods(method))
    with pytest.raises(PipelineExecutionError, match="broken_v1") as result:
        plan.execute("spectrum", fail)
    assert isinstance(result.value.__cause__, ValueError)
    with pytest.raises(ValueError, match="test failure"):
        resolve_pipeline_plan().execute("spectrum", fail)


def test_catalog_and_config_are_detached_and_order_is_code_owned():
    config = default_pipeline_config()
    shuffled = {**config, "methods": dict(reversed(list(config["methods"].items())))}
    assert normalize_pipeline_config(shuffled) == config
    assert tuple(resolve_pipeline_plan({"processing_pipeline": shuffled}).to_config()["methods"]) == tuple(step.id for step in PIPELINE_STEPS)
    detached = deepcopy(config)
    detached["methods"].clear()
    assert default_pipeline_config() == config
