"""Registered methods execute in fixed slots without bypassing scientific gates."""

from copy import deepcopy
from dataclasses import replace

import numpy as np
import pytest

from Main_App.io.acquisition_metadata import resolve_recording_contract
from Main_App.io.eeg_geometry import read_raw_biosemi64_geometry
from Main_App.processing import pipeline_plan, preprocess
from Main_App.processing.pipeline_plan import PipelineConfigurationError, PipelineExecutionError, PipelineMethod
from tests.processing.test_condition_electrode_interpolation import _case as condition_case
from tests.processing.test_generic_recording_pipeline import _admitted_recording


def _settings():
    return {
        "high_pass": None, "low_pass": None, "downsample_rate": 128,
        "line_noise_filter_enabled": False, "kurtosis_screening_enabled": False,
        "raw_signal_screening_enabled": False, "removed_electrode_detection_mode": "off",
    }


def _select(monkeypatch, *methods):
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(*methods)
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    config = pipeline_plan.default_pipeline_config()
    for method in methods:
        config["methods"][method.stage_id] = method.method_id
    return config


def test_registered_filter_and_resampler_execute_in_their_fixed_slots(monkeypatch):
    raw, contract = _admitted_recording()
    expected = raw.copy()
    expected.set_eeg_reference(["R1", "R2"], projection=False, verbose=False)
    expected.drop_channels(["R1", "R2"])
    expected.pick_channels(["E9", "E1", "E4", "Trigger"], ordered=False)
    expected._data[:3] *= 2.0
    expected.resample(128, npad="auto", window="hann", verbose=False)
    expected.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
    expected.apply_proj(verbose=False)
    calls = []

    def gain_filter(context):
        assert context.raw.ch_names == ["E9", "E1", "E4", "Trigger"]
        assert context.raw.info["sfreq"] == 256
        assert context.params["_fpvs_geometry"]["retained_scalp_channels"] == ["E9", "E1", "E4"]
        calls.append("filter")
        context.raw._data[:3] *= 2.0

    def replacement_resampler(context):
        assert calls == ["filter"]
        calls.append("resample")
        preprocess._stage_resample(context)

    config = _select(monkeypatch,
        PipelineMethod("temporal_filter", "test_gain_v1", "Test gain", gain_filter),
        PipelineMethod("resample", "test_resampler_v1", "Test resampler", replacement_resampler),
    )
    params = {**_settings(), "processing_pipeline": config}
    processed, rejected = preprocess.perform_preprocessing(
        raw, params, lambda _: None, recording_contract=contract,
    )
    assert processed is not None, params.get("_fpvs_preprocessing_error")
    assert rejected == 0 and calls == ["filter", "resample"]
    np.testing.assert_array_equal(processed.get_data(), expected.get_data())


def test_defaults_preserve_fingerprint_and_replacement_invalidates_it(monkeypatch):
    raw, contract = _admitted_recording()
    settings = _settings()
    original = preprocess._build_preproc_fingerprint(settings, contract)
    explicit = {**settings, "processing_pipeline": pipeline_plan.default_pipeline_config()}
    assert preprocess._build_preproc_fingerprint(explicit, contract) == original
    config = _select(monkeypatch, PipelineMethod(
        "temporal_filter", "test_filter_identity_v1", "Test filter", lambda _context: None,
    ))
    changed = preprocess._build_preproc_fingerprint({**settings, "processing_pipeline": config}, contract)
    assert changed != original and "|pipeline_methods=sha256:" in changed
    for identity, extra in ((preprocess._kurtosis_filter_identity, {}),
                            (preprocess._kurtosis_downsample_identity, {"source_sfreq_hz": 256})):
        original_identity = identity(raw, settings, **extra)
        assert identity(raw, explicit, **extra) == original_identity
        assert identity(raw, {**settings, "processing_pipeline": config}, **extra) != original_identity


@pytest.mark.parametrize("failure", ["unknown", "wrong_slot", "unavailable_capability"])
def test_invalid_plan_blocks_before_raw_mutation_or_checkpoint(monkeypatch, failure):
    raw, contract = _admitted_recording()
    before = raw.get_data().copy()
    names = raw.ch_names.copy()
    config = pipeline_plan.default_pipeline_config()
    if failure == "unknown":
        config["methods"]["temporal_filter"] = "missing_method"
    elif failure == "wrong_slot":
        config["methods"]["temporal_filter"] = config["methods"]["resample"]
    else:
        config = _select(monkeypatch, PipelineMethod(
            "temporal_filter", "requires_qualified_geometry_v1", "Test qualified method",
            lambda _context: pytest.fail("incompatible method executed"),
            required_capabilities=("supports_template_spatial_tools",),
        ))
    monkeypatch.setattr(preprocess, "checkpoint_identity", lambda *_args: pytest.fail("checkpoint lookup"))
    with pytest.raises(PipelineConfigurationError):
        preprocess.perform_preprocessing(
            raw, {**_settings(), "processing_pipeline": config}, lambda _: None,
            recording_contract=contract,
        )
    assert raw.ch_names == names
    np.testing.assert_array_equal(raw.get_data(), before)


def test_replacement_failure_never_returns_partially_processed_signal(monkeypatch):
    raw, contract = _admitted_recording()

    def failed_filter(context):
        context.raw._data[:3] = 0
        raise RuntimeError("replacement failed")

    config = _select(monkeypatch, PipelineMethod(
        "temporal_filter", "failing_filter_v1", "Failing test filter", failed_filter,
    ))
    params = {**_settings(), "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, params, lambda _: None, recording_contract=contract)
    assert result is None
    assert "failing_filter_v1" in params["_fpvs_preprocessing_error"]


def test_reference_calculation_and_channel_drop_are_separate_slots(monkeypatch):
    raw, contract = _admitted_recording()
    calls = []

    def reference(context):
        preprocess._stage_initial_reference(context)
        assert "R1" in context.raw.ch_names and "R2" in context.raw.ch_names
        calls.append("reference")

    def drop(context):
        assert calls == ["reference"]
        assert "R1" in context.raw.ch_names and "R2" in context.raw.ch_names
        preprocess._stage_reference_channel_drop(context)
        calls.append("drop")

    config = _select(monkeypatch,
        PipelineMethod("initial_reference", "test_reference_v1", "Test reference", reference),
        PipelineMethod("reference_channel_drop", "test_drop_v1", "Test drop", drop),
    )
    settings = {**_settings(), "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, settings, lambda _: None, recording_contract=contract)
    assert result is not None, settings.get("_fpvs_preprocessing_error")
    assert calls == ["reference", "drop"]


@pytest.mark.parametrize("stage", ["temporal_filter", "resample"])
def test_replacement_cannot_change_protected_native_grid(monkeypatch, stage):
    raw, contract = _admitted_recording()
    contract = replace(contract, required_sfreq=256.0, resampling_allowed=False)

    def wrong_rate(context):
        context.raw.resample(128, verbose=False)

    config = _select(monkeypatch, PipelineMethod(stage, "wrong_rate_v1", "Wrong rate", wrong_rate))
    settings = {**_settings(), "downsample_rate": None, "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, settings, lambda _: None, recording_contract=contract)
    assert result is None
    assert "native sampling grid" in settings["_fpvs_preprocessing_error"]


@pytest.mark.parametrize("failure", ["returned_raw", "replaced_raw", "channel_removed", "coordinate_changed", "stim_changed", "canonical_changed"])
def test_replacement_cannot_bypass_raw_geometry_or_event_contract(monkeypatch, failure):
    raw, contract = _admitted_recording()
    if failure == "canonical_changed":
        raw._fpvs_canonical_events = np.array([[0, 0, 22], [1, 0, 22]], dtype=np.int64)
        raw._fpvs_canonical_events_sfreq = 256.0

    def invalid_filter(context):
        if failure == "returned_raw":
            return context.raw.copy()
        if failure == "replaced_raw":
            context.raw = context.raw.copy()
        elif failure == "channel_removed":
            context.raw.drop_channels(["E9"])
        elif failure == "coordinate_changed":
            context.raw.info["chs"][0]["loc"][:3] = [0.0, 0.1, 0.0]
        elif failure == "stim_changed":
            context.raw._data[-1, 0] = 99
        elif failure == "canonical_changed":
            context.raw._fpvs_canonical_events[0, 2] = 99

    config = _select(monkeypatch, PipelineMethod("temporal_filter", "invalid_filter_v1", "Invalid filter", invalid_filter))
    settings = {**_settings(), "downsample_rate": None, "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, settings, lambda _: None, recording_contract=contract)
    assert result is None
    assert "invalid_filter_v1" in settings["_fpvs_preprocessing_error"]


def test_replacement_channel_selection_cannot_leave_one_eeg_channel(monkeypatch):
    raw, contract = _admitted_recording()

    def one_channel(context):
        context.raw.pick(["E9", "Trigger"])

    config = _select(monkeypatch, PipelineMethod("channel_selection", "one_channel_v1", "One channel", one_channel))
    settings = {**_settings(), "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, settings, lambda _: None, recording_contract=contract)
    assert result is None
    assert "at least two retained EEG channels" in settings["_fpvs_preprocessing_error"]


def test_replaced_initial_reference_cannot_bypass_minimum_after_builtin_drop(monkeypatch):
    raw, contract = _admitted_recording()
    contract = replace(contract, initial_reference_channels=("E1", "E4", "E2", "R1", "R2"))
    config = _select(monkeypatch, PipelineMethod(
        "initial_reference", "no_reference_v1", "No reference", lambda _context: None,
    ))
    settings = {**_settings(), "processing_pipeline": config}
    result, _ = preprocess.perform_preprocessing(raw, settings, lambda _: None, recording_contract=contract)
    assert result is None
    assert "at least two retained EEG channels" in settings["_fpvs_preprocessing_error"]


def test_condition_repairs_use_selected_interpolation_and_reference(monkeypatch):
    baseline, baseline_params = condition_case()
    expected, _ = preprocess._finish_preprocessing_at_kurtosis(
        baseline, baseline_params, lambda _: None, "recording", orig_sfreq=100,
        debug_enabled=False, geometry_identity=read_raw_biosemi64_geometry(baseline),
        recording_contract=resolve_recording_contract(baseline_params, raw=baseline),
    )
    raw, params = condition_case()
    original_plan = deepcopy(params["_fpvs_realized_analysis_span_plan"])
    calls = []

    def interpolation(context):
        calls.append(("interpolation", context.condition_branch))
        preprocess._stage_interpolation(context)

    def final_reference(context):
        calls.append(("final_reference", context.condition_branch))
        preprocess._stage_final_reference(context)

    params["processing_pipeline"] = _select(monkeypatch,
        PipelineMethod("interpolation", "test_interpolation_v1", "Test interpolation", interpolation),
        PipelineMethod("final_reference", "test_average_v1", "Test average", final_reference),
    )
    processed, _ = preprocess._finish_preprocessing_at_kurtosis(
        raw, params, lambda _: None, "recording", orig_sfreq=100,
        debug_enabled=False, geometry_identity=read_raw_biosemi64_geometry(raw),
        recording_contract=resolve_recording_contract(params, raw=raw),
    )
    assert calls == [("interpolation", True), ("final_reference", True),
                     ("interpolation", False), ("final_reference", False)]
    assert params["_fpvs_realized_analysis_span_plan"] == original_plan
    np.testing.assert_array_equal(processed.get_data(), expected.get_data())


@pytest.mark.parametrize("change", ["valid", "outside_span", "stimulus", "grid", "channels", "geometry", "provenance", "mutated_provenance", "nonfinite"])
def test_replacement_condition_repairs_are_confined_to_authorized_eeg_spans(monkeypatch, change):
    raw, params = condition_case()
    called = []

    def replacement(recording, repairs):
        original = recording.get_data().copy()
        result = preprocess.apply_condition_repairs(recording, repairs)
        start, stop, _values = repairs.replacements[0]
        called.append(True)
        if change == "valid":
            recording._data[repairs.eeg_picks, start:stop] *= 0.5
            assert recording._data[:, :start].tobytes() == original[:, :start].tobytes()
        elif change == "outside_span":
            recording._data[repairs.eeg_picks[0], 0] += 1
        elif change == "stimulus":
            recording._data[-1, start] += 1
        elif change == "grid":
            recording.crop(tmin=0.01)
        elif change == "channels":
            recording.drop_channels([recording.ch_names[0]])
        elif change == "geometry":
            recording.info["chs"][0]["loc"][0] += 0.01
        elif change == "provenance":
            return None
        elif change == "mutated_provenance":
            result["spans"] = []
        elif change == "nonfinite":
            recording._data[repairs.eeg_picks[0], start] = np.nan
        return result

    params["processing_pipeline"] = _select(monkeypatch, PipelineMethod(
        "condition_repairs", "test_condition_splice_v1", "Test splice", replacement,
    ))

    def finish():
        return preprocess._finish_preprocessing_at_kurtosis(
            raw, params, lambda _: None, "recording", orig_sfreq=100,
            debug_enabled=False, geometry_identity=read_raw_biosemi64_geometry(raw),
            recording_contract=resolve_recording_contract(params, raw=raw),
        )

    if change == "valid":
        result, _ = finish()
        assert result is raw
        assert params["_fpvs_condition_interpolation_provenance"]["status"] == "completed"
    else:
        with pytest.raises(PipelineExecutionError, match="test_condition_splice_v1"):
            finish()
        assert "_fpvs_condition_interpolation_provenance" not in params
    assert called == [True]
