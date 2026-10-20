"""Method choices must reach review execution and invalidate cached evidence."""
from dataclasses import replace

import pytest

from Main_App.processing import pipeline_plan, raw_spectral_qc
from Main_App.processing.pipeline_plan import default_pipeline_config, PipelineMethod
from Main_App.processing.preflight_qc import _preflight_cache_settings
from Main_App.processing.preflight_qc_cache import build_preflight_qc_cache_fingerprint
from Main_App.processing.raw_channel_qc import ConditionRawChannelQCCancelled, evaluate_condition_raw_channel_qc_v2
from tests.processing.test_condition_spectral_qc import _condition_data, _settings


def test_review_methods_change_cache_keys_but_explicit_defaults_do_not(monkeypatch):
    settings = {"high_pass": 1, "low_pass": 40}
    implicit = _preflight_cache_settings(settings)
    explicit = _preflight_cache_settings({**settings, "processing_pipeline": default_pipeline_config()})
    assert implicit == explicit
    key = dict(file_identity={}, method={}, event_plan=[])
    assert build_preflight_qc_cache_fingerprint(settings=settings, **key) == build_preflight_qc_cache_fingerprint(
        settings={**settings, "processing_pipeline": default_pipeline_config()}, **key,
    )
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod(
        "raw_spectral_screening", "review_test_v1", "Review test", lambda *args, **kwargs: None,
    ))
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    config = default_pipeline_config()
    config["methods"]["raw_spectral_screening"] = "review_test_v1"
    altered = _preflight_cache_settings({**settings, "processing_pipeline": config})
    assert altered != implicit
    assert build_preflight_qc_cache_fingerprint(settings=altered, **key) != build_preflight_qc_cache_fingerprint(settings=implicit, **key)


def test_spectral_review_replacement_executes_and_retains_typed_evidence(monkeypatch):
    calls = []
    def replacement(data, **kwargs):
        calls.append(kwargs["condition_label"])
        result = raw_spectral_qc._evaluate_condition_spectral_qc_v2(data, **kwargs)
        return replace(result, message="replacement receipt")
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod(
        "raw_spectral_screening", "review_test_v1", "Review test", replacement,
    ))
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    settings = _settings(mains_hz=60, low_pass_hz=50)
    settings["processing_pipeline"] = default_pipeline_config()
    settings["processing_pipeline"]["methods"]["raw_spectral_screening"] = "review_test_v1"
    result = raw_spectral_qc.evaluate_condition_spectral_qc_v2(
        _condition_data(), sfreq=256, settings=settings,
        effective_upper_frequency_hz=50, condition_label="Faces",
    )
    assert calls == ["Faces"]
    assert result.message == "replacement receipt"
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod(
        "raw_spectral_screening", "review_test_v1", "Review test", lambda *args, **kwargs: {},
    ))
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    with pytest.raises(pipeline_plan.PipelineExecutionError, match="incompatible evidence"):
        raw_spectral_qc.evaluate_condition_spectral_qc_v2(
            _condition_data(), sfreq=256, settings=settings, effective_upper_frequency_hz=50,
        )


@pytest.mark.parametrize("spectral", [True, False])
def test_replacement_preserves_review_cancellation_type(monkeypatch, spectral):
    stage = "raw_spectral_screening" if spectral else "condition_raw_screening"
    cancelled = raw_spectral_qc.ConditionSpectralQCCancelled if spectral else ConditionRawChannelQCCancelled

    def replacement(*args, **kwargs):
        assert kwargs["should_cancel"]()
        raise cancelled("cancelled by user")

    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(PipelineMethod(
        stage, "cancellable_review_v1", "Cancellable review", replacement,
    ))
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    settings = _settings(mains_hz=60, low_pass_hz=50)
    settings["processing_pipeline"] = default_pipeline_config()
    settings["processing_pipeline"]["methods"][stage] = "cancellable_review_v1"
    with pytest.raises(cancelled, match="cancelled by user"):
        if spectral:
            raw_spectral_qc.evaluate_condition_spectral_qc_v2(
                _condition_data(), sfreq=256, settings=settings,
                effective_upper_frequency_hz=50, should_cancel=lambda: True,
            )
        else:
            evaluate_condition_raw_channel_qc_v2(
                [], [], settings, filename="test.bdf", sfreq=256,
                should_cancel=lambda: True,
            )
