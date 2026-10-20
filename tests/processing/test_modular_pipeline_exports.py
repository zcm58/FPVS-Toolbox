"""Characterize default arithmetic and exercise real registered replacements."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import mne
import numpy as np
import pytest

from Main_App.exports import post_process as export_module
from Main_App.exports import source_time_domain_export as source_export
from Main_App.io.condition_data import read_condition_sheet
from Main_App.io.load_utils import open_preflight_eeg_file
from Main_App.io.spectral_data import read_spectral_sheet
from Main_App.processing import pipeline_plan, raw_channel_qc
from Main_App.processing.pipeline_plan import (
    PipelineConfigurationError, PipelineExecutionError, PipelineMethod,
    default_pipeline_config,
)
from Main_App.processing.preflight_qc import _find_preflight_events
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers import process_runner
from Tools.Stats.analysis.full_snr import (
    compute_full_snr_from_amplitudes, compute_full_snr_prefix_from_amplitudes,
)
from Tools.Stats.analysis.noise_utils import compute_qc14_standard_metrics
from tests.processing.test_multi_hardware_bids_integration import _bdf_recording
from tests.processing.test_post_process_output_receipts import _app, _epochs
from tests.processing.test_source_time_domain_export import (
    _epochs as _source_epochs, _processing_provenance,
)


def _select(monkeypatch, implementations):
    config = default_pipeline_config()
    methods = []
    for stage, implementation in implementations.items():
        method = PipelineMethod(stage, f"test_{stage}_v1", "Test replacement", implementation)
        methods.append(method)
        config["methods"][stage] = method.method_id
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(*methods)
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    return config


@pytest.mark.parametrize("strided", [False, True])
def test_default_spectral_helpers_preserve_expression_bytes(strided):
    data = np.random.default_rng(13).normal(size=(3, 1024))
    if strided:
        data = data[:, ::2]
    count = data.shape[1]
    frequencies, amplitudes = export_module._amplitude_spectrum(data, 128.0)
    expected = np.abs(np.fft.fft(data, axis=1)[:, :count // 2 + 1]) / count * 2
    assert frequencies.tobytes() == np.fft.rfftfreq(count, d=1 / 128).tobytes()
    assert amplitudes.tobytes() == expected.tobytes()
    assert export_module._average_accumulated(amplitudes, 3).tobytes() == (amplitudes / 3).tobytes()
    assert export_module._full_snr(amplitudes).tobytes() == compute_full_snr_from_amplitudes(amplitudes).tobytes()
    assert export_module._full_snr(amplitudes, output_bin_count=80).tobytes() == compute_full_snr_prefix_from_amplitudes(amplitudes, output_bin_count=80).tobytes()


@pytest.mark.parametrize("stage,objects,sheet,scale,offset", [
    ("repetition_average", 1, "FullFFT Amplitude (uV)", 2, 0),
    ("spectrum", 1, "FullFFT Amplitude (uV)", 2, 0),
    ("full_snr", 1, "FullSNR", 1, 7),
    ("full_snr", 2, "FullSNR", 1, 7),
    ("target_metrics", 1, "BCA (uV)", 1, 7),
    ("occurrence_average", 2, "FullFFT Amplitude (uV)", 2, 0),
])
def test_registered_spectral_method_changes_published_values(
    tmp_path, monkeypatch, stage, objects, sheet, scale, offset,
):
    baseline_root, changed_root = tmp_path / "baseline", tmp_path / "changed"
    baseline_root.mkdir()
    changed_root.mkdir()
    epochs = _epochs()
    baseline = _app(baseline_root, epochs)
    baseline.preprocessed_data["Faces"] *= objects
    export_module.post_process(baseline, ["Faces"])
    calls = []

    def replacement(*args, **kwargs):
        calls.append(kwargs.copy())
        if stage == "repetition_average":
            return export_module._mean_epochs_float64(*args) * 2
        if stage == "spectrum":
            frequencies, amplitudes = export_module._amplitude_spectrum(*args)
            return frequencies, amplitudes * 2
        if stage == "full_snr":
            return export_module._full_snr(*args, **kwargs) + 7
        if stage == "target_metrics":
            result = compute_qc14_standard_metrics(*args, **kwargs)
            return replace(result, bca=result.bca + 7 if result.bca is not None else None)
        return export_module._average_accumulated(*args) * 2

    changed = _app(changed_root, epochs)
    changed.preprocessed_data["Faces"] *= objects
    changed.settings["processing_pipeline"] = _select(monkeypatch, {stage: replacement})
    export_module.post_process(changed, ["Faces"])
    assert calls
    assert changed.export_receipts[0]["processing_pipeline"] == changed.settings["processing_pipeline"]
    if stage == "full_snr":
        assert all((call["output_bin_count"] is None) == (objects > 1) for call in calls)
    baseline_file, = baseline_root.rglob("*.fpvs")
    changed_file, = changed_root.rglob("*.fpvs")
    reader = read_spectral_sheet if sheet.startswith("Full") else read_condition_sheet
    expected = reader(baseline_file, sheet_name=sheet)
    actual = reader(changed_file, sheet_name=sheet)
    assert actual.columns.tolist() == expected.columns.tolist()
    assert actual.iloc[:, 0].tolist() == expected.iloc[:, 0].tolist()
    np.testing.assert_allclose(
        actual.iloc[:, 1:].to_numpy(dtype=float),
        expected.iloc[:, 1:].to_numpy(dtype=float) * scale + offset,
        rtol=1e-14, atol=1e-12, equal_nan=True,
    )


@pytest.mark.parametrize("stage,replacement", [
    ("repetition_average", lambda data: data[0, :, :-1]),
    ("spectrum", lambda *_: None),
    ("spectrum", lambda data, sf: (np.fft.rfftfreq(data.shape[1], 1 / sf) + 1, np.zeros((data.shape[0], data.shape[1] // 2 + 1)))),
    ("full_snr", lambda data, **_: data[:, :1]),
    ("target_metrics", lambda *_args, **_kwargs: None),
    ("occurrence_average", lambda data, _count: data[:, :-1]),
])
def test_invalid_replacement_output_blocks_publication(tmp_path, monkeypatch, stage, replacement):
    app = _app(tmp_path, _epochs())
    app.settings["processing_pipeline"] = _select(monkeypatch, {stage: replacement})
    with pytest.raises(PipelineExecutionError):
        export_module.post_process(app, ["Faces"])
    assert not list(tmp_path.rglob("*.fpvs"))


def test_replacement_exception_cannot_silently_drop_export_object(tmp_path, monkeypatch):
    def fail(*_args, **_kwargs):
        raise ValueError("deliberate method failure")

    app = _app(tmp_path, _epochs())
    app.settings["processing_pipeline"] = _select(monkeypatch, {"full_snr": fail})
    with pytest.raises(PipelineExecutionError, match="full_snr"):
        export_module.post_process(app, ["Faces"])
    assert not list(tmp_path.rglob("*.fpvs"))


def test_unknown_plan_fails_before_export_path_access(tmp_path):
    app = _app(tmp_path, _epochs())
    config = default_pipeline_config()
    config["methods"]["spectrum"] = "missing_method_v1"
    app.settings["processing_pipeline"] = config
    app.save_folder_path.get = lambda: pytest.fail("Invalid plan reached export path access.")
    with pytest.raises(PipelineConfigurationError, match="Unavailable"):
        export_module.post_process(app, ["Faces"])


def test_explicit_default_pipeline_exports_are_byte_identical(tmp_path, monkeypatch):
    monkeypatch.setattr(export_module, "_capture_occurrence_values", lambda *_args, **_kwargs: pytest.fail("The default aggregator must not retain extra occurrence arrays."))
    for name in ("implicit", "explicit"):
        root = tmp_path / name
        root.mkdir()
        app = _app(root, _epochs())
        if name == "explicit":
            app.settings["processing_pipeline"] = default_pipeline_config()
        export_module.post_process(app, ["Faces"])
    before = {path.relative_to(tmp_path / "implicit"): path.read_bytes() for path in (tmp_path / "implicit").rglob("*") if path.suffix in {".fpvs", ".npz"}}
    after = {path.relative_to(tmp_path / "explicit"): path.read_bytes() for path in (tmp_path / "explicit").rglob("*") if path.suffix in {".fpvs", ".npz"}}
    assert before and after == before


def test_registered_occurrence_median_uses_original_unequal_values(tmp_path, monkeypatch):
    baseline_root, changed_root = tmp_path / "baseline", tmp_path / "changed"
    baseline_root.mkdir()
    changed_root.mkdir()
    epochs = _epochs()
    baseline = _app(baseline_root, epochs)
    export_module.post_process(baseline, ["Faces"])
    received_metrics = []

    def occurrence_median(accumulated, count, *, occurrence_values, metric_name):
        assert count == 3
        assert isinstance(occurrence_values, tuple) and len(occurrence_values) == 3
        assert all(not values.flags.writeable for values in occurrence_values)
        assert all(not np.shares_memory(values, accumulated) for values in occurrence_values)
        received_metrics.append(metric_name)
        return np.median(np.stack(occurrence_values), axis=0)

    changed = _app(changed_root, epochs)
    occurrences = []
    for scale in (1, 2, 9):
        occurrence = epochs.copy()
        occurrence._data *= scale
        occurrences.append(occurrence)
    changed.preprocessed_data["Faces"] = occurrences
    changed.settings["processing_pipeline"] = _select(monkeypatch, {"occurrence_average": occurrence_median})
    export_module.post_process(changed, ["Faces"])
    assert received_metrics == ["fft", "snr", "z", "bca", "full_snr", "full_fft"]
    baseline_file, = baseline_root.rglob("*.fpvs")
    changed_file, = changed_root.rglob("*.fpvs")
    expected = read_spectral_sheet(baseline_file, sheet_name="FullFFT Amplitude (uV)").iloc[:, 1:].to_numpy(dtype=float)
    actual = read_spectral_sheet(changed_file, sheet_name="FullFFT Amplitude (uV)").iloc[:, 1:].to_numpy(dtype=float)
    np.testing.assert_array_equal(actual, expected * 2)
    assert not np.allclose(actual, expected * 4)


def test_repetition_method_requires_unaveraged_epochs(tmp_path, monkeypatch):
    app = _app(tmp_path, _epochs())
    app.preprocessed_data["Faces"] = [_epochs().average()]
    app.settings["processing_pipeline"] = _select(monkeypatch, {
        "repetition_average": lambda data: np.mean(data, axis=0, dtype=np.float64),
    })
    with pytest.raises(PipelineExecutionError, match="original Epochs"):
        export_module.post_process(app, ["Faces"])


def test_metric_replacement_cannot_override_static_eligibility(tmp_path, monkeypatch):
    def replacement(*args, **kwargs):
        return replace(compute_qc14_standard_metrics(*args, **kwargs), bca=7.0)

    app = _app(tmp_path, _epochs())
    # A notch through 3 Hz removes both the target and surrounding-noise support.
    app.settings.update(line_noise_filter_enabled=True, _fpvs_fft_multinotch_applied_centers_hz=[3.0])
    app.settings["processing_pipeline"] = _select(monkeypatch, {"target_metrics": replacement})
    with pytest.raises(PipelineExecutionError, match="spectrally ineligible"):
        export_module.post_process(app, ["Faces"])
    assert not list(tmp_path.rglob("*.fpvs"))


def test_selected_repetition_method_reaches_source_derivative(tmp_path, monkeypatch):
    config = _select(monkeypatch, {
        "repetition_average": lambda data: np.mean(data, axis=0, dtype=np.float64) * 2,
    })
    epochs = _source_epochs()
    result = source_export.write_source_ready_time_domain_derivatives(
        project_root=tmp_path, participant_id="P01", condition_epochs={"Faces": epochs},
        processing_provenance=_processing_provenance(),
        pipeline_settings={"processing_pipeline": config},
    )
    with mne.io.read_raw_fif(result.artifacts[0].fif_path, preload=True, verbose=False) as raw:
        expected = np.mean(epochs.get_data(picks="eeg"), axis=0, dtype=np.float64) * 2
        np.testing.assert_array_equal(raw.get_data(), expected.astype(np.float32).astype(np.float64))
    import json
    sidecar = json.loads(result.artifacts[0].sidecar_path.read_text())
    assert sidecar["processing"]["provenance"]["processing_pipeline"] == config


def test_invalid_source_plan_preserves_published_artifacts(tmp_path):
    kwargs = dict(
        project_root=tmp_path, participant_id="P01", condition_epochs={"Faces": _source_epochs()},
        processing_provenance=_processing_provenance(),
    )
    original = source_export.write_source_ready_time_domain_derivatives(**kwargs)
    paths = [original.manifest_path, original.artifacts[0].fif_path, original.artifacts[0].sidecar_path]
    previous = {path: path.read_bytes() for path in paths}
    config = default_pipeline_config()
    config["methods"]["repetition_average"] = "missing_method_v1"
    with pytest.raises(PipelineConfigurationError, match="Unavailable"):
        source_export.write_source_ready_time_domain_derivatives(
            **kwargs, pipeline_settings={"processing_pipeline": config},
        )
    assert {path: path.read_bytes() for path in paths} == previous


@pytest.mark.parametrize("original_is_default", [False, True])
def test_source_merge_rejects_retained_condition_from_another_plan(
    tmp_path, monkeypatch, original_is_default,
):
    alternate = _select(monkeypatch, {
        "repetition_average": lambda data: np.mean(data, axis=0, dtype=np.float64) * 2,
    })
    original_config = default_pipeline_config() if original_is_default else alternate
    current_config = alternate if original_is_default else default_pipeline_config()
    kwargs = dict(project_root=tmp_path, participant_id="P01", processing_provenance=_processing_provenance())
    original = source_export.write_source_ready_time_domain_derivatives(
        **kwargs, condition_epochs={"Faces": _source_epochs(), "Objects": _source_epochs(scale=2)},
        pipeline_settings={"processing_pipeline": original_config},
    )
    paths = [original.manifest_path, *[path for item in original.artifacts for path in (item.fif_path, item.sidecar_path)]]
    previous = {path: path.read_bytes() for path in paths}
    with pytest.raises(PipelineConfigurationError, match="different pipeline methods"):
        source_export.write_source_ready_time_domain_derivatives(
            **kwargs, condition_epochs={"Faces": _source_epochs(scale=3)}, merge_existing=True,
            pipeline_settings={"processing_pipeline": current_config},
        )
    assert {path: path.read_bytes() for path in paths} == previous


def test_source_explicit_settings_cannot_relabel_conflicting_provenance(tmp_path, monkeypatch):
    alternate = _select(monkeypatch, {
        "repetition_average": lambda data: np.mean(data, axis=0, dtype=np.float64) * 2,
    })
    kwargs = dict(
        project_root=tmp_path, participant_id="P01", condition_epochs={"Faces": _source_epochs()},
        processing_provenance={**_processing_provenance(), "processing_pipeline": alternate},
    )
    original = source_export.write_source_ready_time_domain_derivatives(**kwargs)
    paths = [original.manifest_path, original.artifacts[0].fif_path, original.artifacts[0].sidecar_path]
    previous = {path: path.read_bytes() for path in paths}
    with pytest.raises(PipelineConfigurationError, match="provenance disagrees"):
        source_export.write_source_ready_time_domain_derivatives(
            **kwargs, pipeline_settings={"processing_pipeline": default_pipeline_config()},
        )
    assert {path: path.read_bytes() for path in paths} == previous


def test_source_merge_treats_implicit_and_explicit_defaults_identically(tmp_path):
    kwargs = dict(project_root=tmp_path, participant_id="P01", processing_provenance=_processing_provenance())
    original = source_export.write_source_ready_time_domain_derivatives(
        **kwargs, condition_epochs={"Faces": _source_epochs(), "Objects": _source_epochs(scale=2)},
    )
    retained = next(item for item in original.artifacts if item.condition_label == "Objects")
    previous = retained.sidecar_path.read_bytes(), retained.fif_path.read_bytes()
    merged = source_export.write_source_ready_time_domain_derivatives(
        **{**kwargs, "processing_provenance": {**_processing_provenance(), "processing_pipeline": default_pipeline_config()}},
        condition_epochs={"Faces": _source_epochs(scale=3)}, merge_existing=True,
        pipeline_settings={"processing_pipeline": default_pipeline_config()},
    )
    assert len(merged.artifacts) == 2
    assert (retained.sidecar_path.read_bytes(), retained.fif_path.read_bytes()) == previous
    import json
    updated = next(item for item in merged.artifacts if item.condition_label == "Faces")
    assert "processing_pipeline" not in json.loads(updated.sidecar_path.read_text())["processing"]["provenance"]


def test_condition_raw_screening_dispatch_preserves_lazy_block_input(monkeypatch):
    calls = []
    settings = {"raw_signal_screening_enabled": False, "auto_detect_removed_electrodes": False}
    blocks = iter(())

    def replacement(*args, **kwargs):
        calls.append(args[0])
        return raw_channel_qc._evaluate_condition_raw_channel_qc_v2(*args, **kwargs)

    settings["processing_pipeline"] = _select(monkeypatch, {"condition_raw_screening": replacement})
    result = raw_channel_qc.evaluate_condition_raw_channel_qc_v2(
        blocks, ["Oz"], settings, filename="sample.bdf", sfreq=250,
    )
    assert calls == [blocks]
    assert isinstance(result, raw_channel_qc.ConditionRawChannelQCResult)


def test_runner_replacements_change_outputs_and_invalidate_raw_cache(tmp_path, monkeypatch):
    path, _, settings, _, rate, _ = _bdf_recording(tmp_path, "unicorn_classic")
    protocol = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=128,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    with open_preflight_eeg_file(SimpleNamespace(log=lambda _: None), str(path), acquisition_settings=settings) as raw:
        events, _ = _find_preflight_events(raw, stim_channel="Status")
        event_plan = plan_preflight_qc_events(
            events=events, event_map={"Faces": 21}, sfreq=rate, n_times=raw.n_times,
            frequency_protocol=protocol,
        )
    settings.update(frequency_protocol=protocol, _fpvs_preflight_event_plans_by_file={str(path.resolve()): event_plan.to_payload()})
    baseline = process_runner._run_full_pipeline_for_file(path, settings, {"Faces": 21}, tmp_path, tmp_path)
    assert baseline["status"] == "ok", baseline
    assert baseline["preproc_cache_status"] == "stored"
    bundle, = tmp_path.rglob("*.fpvs")
    expected = read_spectral_sheet(bundle, sheet_name="FullFFT Amplitude (uV)").iloc[:, 1:].to_numpy(dtype=float)
    default_payload = process_runner._preproc_cache_payload(path, settings, mne_version=mne.__version__)
    explicit_default_payload = process_runner._preproc_cache_payload(path, {**settings, "processing_pipeline": default_pipeline_config()}, mne_version=mne.__version__)
    assert default_payload == explicit_default_payload
    assert "processing_pipeline" not in default_payload
    calls = []

    def raw_screen(raw, settings, **kwargs):
        calls.append("raw_screening")
        return raw_channel_qc._evaluate_raw_channel_qc(raw, settings, **kwargs)

    def epoching(raw, spans):
        calls.append("epoching")
        result = process_runner._build_epoch_data_from_spans(raw, spans)
        result[:, :-1] *= 2
        return result

    settings["processing_pipeline"] = _select(monkeypatch, {"raw_screening": raw_screen, "epoching": epoching})
    changed_payload = process_runner._preproc_cache_payload(path, settings, mne_version=mne.__version__)
    assert process_runner._preproc_cache_key(changed_payload) != process_runner._preproc_cache_key(default_payload)
    changed = process_runner._run_full_pipeline_for_file(path, settings, {"Faces": 21}, tmp_path, tmp_path)
    assert changed["status"] == "ok", changed
    assert changed["preproc_cache_status"] == "stored"
    assert calls == ["raw_screening", "epoching"]
    actual = read_spectral_sheet(bundle, sheet_name="FullFFT Amplitude (uV)").iloc[:, 1:].to_numpy(dtype=float)
    np.testing.assert_array_equal(actual, expected * 2)
    calls.clear()
    repeated = process_runner._run_full_pipeline_for_file(path, settings, {"Faces": 21}, tmp_path, tmp_path)
    assert repeated["status"] == "ok", repeated
    assert repeated["preproc_cache_status"] == "hit"
    assert calls == ["epoching"]
    settings["processing_pipeline"] = _select(monkeypatch, {
        "epoching": lambda raw, spans: process_runner._build_epoch_data_from_spans(raw, spans)[:, :, :-1],
    })
    broken = process_runner._run_full_pipeline_for_file(path, settings, {"Faces": 21}, tmp_path, tmp_path)
    assert broken["status"] == "error"
    assert broken["stage"] == "epochs"
