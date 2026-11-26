"""Verify exact run-local reuse of the automatic raw-channel detector."""

from dataclasses import asdict, replace
import hashlib
import os
import pickle
from types import SimpleNamespace

import pytest

from Main_App.io.acquisition_metadata import source_load_kwargs
from Main_App.io.load_utils import load_eeg_file
from Main_App.processing import pipeline_plan, raw_channel_qc_reuse as reuse
from Main_App.processing.analysis_spans import read_source_analysis_span_plan, relative_spans_from_plan
from Main_App.processing.pipeline_plan import PREPARED_RAW_QC_BY_FILE
from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
from Main_App.processing.prepared_raw_codec import encode_state
from Main_App.processing.processing_ledger import build_processing_fingerprint
from Main_App.processing.qc_signal_view import source_content_identity
from Main_App.processing.raw_channel_qc import evaluate_raw_channel_qc
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
from Main_App.workers.process_runner import _recording_job_settings
from Main_App.workers.processing_resource_budget import plain_metadata_bytes
from tests.processing.test_kurtosis_review_process_parity import _small_bdf
from tests.processing.test_preprocess_kurtosis_gate import _params


@pytest.fixture
def recording(tmp_path):
    source = tmp_path / "P001.bdf"
    events = _small_bdf(source)
    protocol = FrequencyProtocol.from_recurrence(
        10, 5, expected_analyzed_oddball_cycles=10,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    event_map = {"Condition": 1}
    event_plan = plan_preflight_qc_events(
        events=events, event_map=event_map, sfreq=100.0, n_times=1_000,
        first_samp=0, frequency_protocol=protocol,
    ).to_payload()
    source_plan = read_source_analysis_span_plan(event_plan)
    settings = {
        **_params(source),
        "_fpvs_source_analysis_span_plan": source_plan,
        "frequency_protocol": protocol,
        "project_root": str(tmp_path),
        "max_idx_keep": 64,
        "removed_electrode_detection_mode": "auto",
        "auto_detect_removed_electrodes": True,
        "manual_removed_electrodes_enabled": True,
    }
    raw = load_eeg_file(
        SimpleNamespace(log=lambda *_: None), str(source), **source_load_kwargs(settings),
        acquisition_settings=settings, preload_in_memory=True, raise_on_error=True,
    )
    try:
        assert raw is not None
        yield source, raw, settings, relative_spans_from_plan(source_plan)
    finally:
        if raw is not None:
            raw.close()


@pytest.fixture
def prepared(recording):
    source, raw, settings, spans = recording
    result = evaluate_raw_channel_qc(raw, settings, filename=source.name, analysis_spans=spans)
    inputs = reuse.raw_channel_qc_inputs(raw, settings, spans)
    assert inputs is not None
    identity = source_content_identity(source)
    return reuse.PreparedRawChannelQC(
        inputs=inputs, source_path=identity["path"], source_size=identity["size_bytes"],
        source_sha256=identity["sha256"],
        samples_sha256=hashlib.sha256(memoryview(raw._data).cast("B")).hexdigest(),
        result=result,
    )


def test_worker_transport_preserves_exact_result_and_scientific_identity(recording, prepared):
    source, raw, settings, spans = recording
    other = source.with_name("other.bdf")
    unrelated = replace(prepared, source_path=str(other), samples_sha256="x" * (1024**2 + 1))
    transported = {**settings, PREPARED_RAW_QC_BY_FILE: {str(source): prepared, str(other): unrelated}}
    local = _recording_job_settings(source, transported)
    assert local[PREPARED_RAW_QC_BY_FILE] == {str(source): prepared}
    assert PREPARED_RAW_QC_BY_FILE not in _recording_job_settings(source.with_name("unreviewed.bdf"), transported)
    assert plain_metadata_bytes(local) > plain_metadata_bytes(settings)
    with pytest.raises(ValueError, match="Unbounded metadata"):
        plain_metadata_bytes(transported)

    project = SimpleNamespace(preprocessing={})
    event_map = {"Condition": 1}
    assert build_processing_fingerprint(project, transported, event_map) == build_processing_fingerprint(
        project, settings, event_map,
    )
    worker_settings = pickle.loads(pickle.dumps(local))
    actual = reuse.restore_raw_channel_qc(
        worker_settings[PREPARED_RAW_QC_BY_FILE][str(source)], raw, worker_settings, source, spans,
    )
    fresh = evaluate_raw_channel_qc(raw, settings, filename=source.name, analysis_spans=spans)
    assert actual is not None
    assert encode_state(asdict(actual), {}) == encode_state(asdict(fresh), {})


@pytest.mark.parametrize("change", ["spans", "plan", "threshold", "manual", "mode", "bads", "geometry", "sample"])
def test_prepared_result_is_rejected_when_detector_inputs_change(recording, prepared, change):
    source, raw, settings, spans = recording
    if change == "spans":
        spans = ((spans[0][0] + 1, spans[0][1]), *spans[1:])
    elif change == "plan":
        settings["_fpvs_source_analysis_span_plan"] = {
            **settings["_fpvs_source_analysis_span_plan"], "fingerprint": "a changed reviewed plan",
        }
    elif change == "threshold":
        settings["max_bad_chans"] = prepared.inputs.config.max_bad_channels + 1
    elif change == "manual":
        settings["_fpvs_manual_removed_electrodes"] = ["Cz"]
    elif change == "mode":
        settings["removed_electrode_detection_mode"] = "off"
    elif change == "bads":
        raw.info["bads"] = ["Cz"]
    elif change == "geometry":
        raw.info["chs"][raw.ch_names.index("Cz")]["loc"][0] += 0.001
    elif change == "sample":
        raw._data[raw.ch_names.index("Cz"), spans[0][0]] = 0.125
    assert reuse.restore_raw_channel_qc(prepared, raw, settings, source, spans) is None


def test_prepared_result_rejects_source_mutation_with_restored_size_and_mtime(recording, prepared):
    source, raw, settings, spans = recording
    before = source.stat()
    with source.open("r+b") as stream:
        stream.seek(-1, os.SEEK_END)
        original = stream.read(1)
        stream.seek(-1, os.SEEK_END)
        stream.write(bytes([original[0] ^ 1]))
    os.utime(source, ns=(before.st_atime_ns, before.st_mtime_ns))
    assert (source.stat().st_size, source.stat().st_mtime_ns) == (before.st_size, before.st_mtime_ns)
    assert reuse.restore_raw_channel_qc(prepared, raw, settings, source, spans) is None


def test_prepared_result_rejects_unknown_native_execution_policy(recording, prepared, monkeypatch):
    source, raw, settings, spans = recording
    monkeypatch.setattr(reuse, "_native_execution_identity", lambda: None)
    assert reuse.restore_raw_channel_qc(prepared, raw, settings, source, spans) is None



def test_prepared_result_does_not_replace_a_registered_detector(recording, prepared, monkeypatch):
    source, raw, settings, spans = recording
    calls = []

    def replacement(_raw, _settings, **_kwargs):
        calls.append(True)
        return prepared.result

    method = pipeline_plan.PipelineMethod("raw_screening", "test_raw_screen_v1", "Test replacement", replacement)
    registry = pipeline_plan.BUILTIN_PIPELINE_REGISTRY.with_methods(method)
    monkeypatch.setattr(pipeline_plan, "get_pipeline_registry", lambda: registry)
    config = pipeline_plan.default_pipeline_config()
    config["methods"]["raw_screening"] = method.method_id
    settings[pipeline_plan.PIPELINE_SETTINGS_KEY] = config
    assert reuse.restore_raw_channel_qc(prepared, raw, settings, source, spans) is None
    assert evaluate_raw_channel_qc(raw, settings, filename=source.name, analysis_spans=spans) is prepared.result
    assert calls == [True]
