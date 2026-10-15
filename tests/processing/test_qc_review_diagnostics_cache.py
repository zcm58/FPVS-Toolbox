from copy import deepcopy
import hashlib
import json
import struct

import mne
import numpy as np
import pytest

from Main_App.processing import prepared_kurtosis_cache
from Main_App.processing import qc_review_diagnostics as diagnostics
from Main_App.processing import qc_review_diagnostics_cache as cache
from Main_App.processing.preflight_qc_cache import preflight_qc_cache_directory, preflight_qc_cache_path
from Main_App.processing.preflight_qc_reuse import decode_evidence, encode_evidence
from Main_App.processing.project_processing_cache import clear_project_processing_cache
from Main_App.processing.qc_review_diagnostics import build_raw_qc_review_diagnostics
from Main_App.processing.qc_signal_view import source_content_identity


@pytest.fixture
def context(tmp_path, monkeypatch):
    source = tmp_path / "P1.bdf"
    source.write_bytes(b"verified synthetic source")
    names = ["Fp1", "Fp2", "EXG1", "EXG2"]
    raw = mne.io.RawArray(np.random.default_rng(0).normal(0, 1e-6, (4, 512)),
                         mne.create_info(names, 128.0, ["eeg"] * 4), verbose=False)
    monkeypatch.setattr(cache, "read_raw_biosemi64_geometry", lambda _raw: {"retained": names, "identity": "synthetic"})
    monkeypatch.setattr(prepared_kurtosis_cache, "_native_execution_identity", lambda: (("fake_blas", "v1", 1),))
    kwargs = {
        "project_root": tmp_path, "source_identity": source_content_identity(source),
        "participant_id": "P1", "recording_id": "P1__session1",
        "occurrences": [{"start_sample": 0, "stop_sample": 256, "condition_label": "Objects", "occurrence": 0, "occurrence_key": "11:0"},
                        {"start_sample": 256, "stop_sample": 512, "condition_label": "Faces", "occurrence": 1, "occurrence_key": "13:1"}],
        "ref_channels": ["EXG1", "EXG2"], "unusable_channels": [],
    }
    yield raw, source, kwargs
    raw.close()


def _report(raw, kwargs):
    return build_raw_qc_review_diagnostics(raw, occurrences=kwargs["occurrences"],
                                         ref_channels=kwargs["ref_channels"], unusable_channels=kwargs["unusable_channels"])


def _exact(left, right):
    if isinstance(left, dict):
        assert isinstance(right, dict) and list(left) == list(right)
        for key in left:
            _exact(left[key], right[key])
    elif isinstance(left, (tuple, list)):
        assert type(left) is type(right) and len(left) == len(right)
        for old, new in zip(left, right):
            _exact(old, new)
    elif isinstance(left, (float, np.floating)):
        assert struct.pack(">d", left) == struct.pack(">d", right)
    else:
        assert left == right


def test_native_report_cache_hit_is_complete_exact_detached_and_display_only(context):
    raw, _source, kwargs = context
    before = raw._data.copy()
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    assert key is not None and cache.load_raw_diagnostics(key) is None
    report = _report(raw, kwargs)
    cache.save_raw_diagnostics(key, report)
    warmed = cache.load_raw_diagnostics(key)
    _exact(report, warmed)
    assert warmed["authority"] == "review_only"
    assert warmed["shadow_evidence"]["eligible_kurtosis_corroborator"] is False
    assert warmed["fingerprint"] == report["fingerprint"]
    warmed["channels"].append("mutated caller")
    _exact(report, cache.load_raw_diagnostics(key))
    assert raw._data.tobytes() == before.tobytes()


def test_lossless_codec_retains_nan_payload_signed_zero_and_mapping_order():
    nan = struct.unpack(">d", bytes.fromhex("7ff8000000000042"))[0]
    report = {"z": {"b": (nan, -0.0, float("inf")), "a": [None, 0.0]}, "a": "last"}
    restored = cache._restore_mapping_order(decode_evidence(encode_evidence(report)), cache._mapping_order(report))
    _exact(report, restored)


def test_nonfinite_loaded_samples_still_reuse_exact_valid_native_report(context):
    raw, _source, kwargs = context
    raw._data[0, 0] = float("nan")
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    report = _report(raw, kwargs)
    cache.save_raw_diagnostics(key, report)
    _exact(report, cache.load_raw_diagnostics(key))


@pytest.mark.parametrize("change", ["occurrence_order", "occurrence_bounds", "reference", "bad_channel",
                                  "geometry", "native_threads", "settings", "samples", "source", "runtime_version"])
def test_relevant_current_inputs_invalidate_cache(context, monkeypatch, change):
    raw, source, kwargs = context
    old = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    cache.save_raw_diagnostics(old, _report(raw, kwargs))
    kwargs = deepcopy(kwargs)
    if change == "occurrence_order":
        kwargs["occurrences"].reverse()
    elif change == "occurrence_bounds":
        kwargs["occurrences"][0]["stop_sample"] -= 1
    elif change == "reference":
        kwargs["ref_channels"] = ["EXG1"]
    elif change == "bad_channel":
        kwargs["unusable_channels"] = ["Fp1"]
    elif change == "geometry":
        monkeypatch.setattr(cache, "read_raw_biosemi64_geometry", lambda _raw: {"identity": "changed"})
    elif change == "native_threads":
        monkeypatch.setattr(prepared_kurtosis_cache, "_native_execution_identity", lambda: (("fake_blas", "v1", 2),))
    elif change == "settings":
        kwargs["settings"] = {"max_events": 256}
    elif change == "samples":
        raw._data.view(np.uint64)[0, 0] ^= np.uint64(1)
    elif change == "source":
        source.write_bytes(b"changed synthetic source")
        kwargs["source_identity"] = source_content_identity(source)
    else:
        monkeypatch.setattr(scipy_module := cache.scipy, "__version__", scipy_module.__version__ + "-changed")
    new = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    assert new is not None and new != old
    assert cache.load_raw_diagnostics(new) is None


@pytest.mark.parametrize("change", ["native_unknown", "geometry_unknown", "dtype_unknown", "sha_missing", "relative_root"])
def test_unknown_cache_identity_is_a_cold_math_miss(context, monkeypatch, change):
    raw, _source, kwargs = context
    if change == "native_unknown":
        monkeypatch.setattr(prepared_kurtosis_cache, "_native_execution_identity", lambda: None)
    elif change == "geometry_unknown":
        monkeypatch.setattr(cache, "read_raw_biosemi64_geometry", lambda _raw: None)
    elif change == "dtype_unknown":
        raw._data = raw._data.astype(np.float32)
    elif change == "sha_missing":
        kwargs["source_identity"].pop("sha256")
    else:
        kwargs["project_root"] = "relative"
    assert cache.build_raw_diagnostics_cache_key(raw, **kwargs) is None
    assert cache.load_raw_diagnostics(None) is None
    cache.save_raw_diagnostics(None, {})


@pytest.mark.parametrize("corruption", ["invalid_json", "outer_digest", "report_fingerprint", "typed_scalar", "mapping_order"])
def test_corrupt_cache_never_grants_reuse(context, corruption):
    raw, _source, kwargs = context
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    cache.save_raw_diagnostics(key, _report(raw, kwargs))
    path = preflight_qc_cache_path(key.project_root, namespace="raw_diagnostics", **key.inputs)
    if corruption == "invalid_json":
        path.write_text("not-json")
    else:
        envelope = json.loads(path.read_text())
        if corruption == "outer_digest":
            envelope["result_sha256"] = "0" * 64
        elif corruption == "report_fingerprint":
            envelope["result"]["report"]["mapping"]["fingerprint"] = "0" * 64
        elif corruption == "typed_scalar":
            envelope["result"]["report"]["mapping"]["sfreq"] = {"float64": "broken"}
        else:
            envelope["result"]["mapping_order"]["keys"].reverse()
            envelope["result"]["mapping_order"]["children"] = []
        if corruption != "outer_digest":
            envelope["result_sha256"] = hashlib.sha256(json.dumps(envelope["result"], sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        path.write_text(json.dumps(envelope))
    assert cache.load_raw_diagnostics(key) is None


def test_cancellation_does_not_publish_or_return_evidence(context):
    raw, _source, kwargs = context
    calls = iter([False, True])
    with pytest.raises(InterruptedError):
        cache.build_raw_diagnostics_cache_key(raw, **kwargs, should_cancel=lambda: next(calls))
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    with pytest.raises(InterruptedError):
        cache.save_raw_diagnostics(key, _report(raw, kwargs), should_cancel=lambda: True)
    assert not preflight_qc_cache_directory(key.project_root, namespace="raw_diagnostics").exists()
    with pytest.raises(InterruptedError):
        cache.load_raw_diagnostics(key, should_cancel=lambda: True)


def test_retention_is_one_valid_generation_and_standard_reset_owns_it(context):
    raw, _source, kwargs = context
    old = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    cache.save_raw_diagnostics(old, _report(raw, kwargs))
    changed = cache.build_raw_diagnostics_cache_key(raw, **{**kwargs, "settings": {"max_events": 256}})
    cache.save_raw_diagnostics(changed, _report(raw, kwargs))
    directory = preflight_qc_cache_directory(changed.project_root, namespace="raw_diagnostics")
    assert len(list(directory.glob("*.json"))) == 1
    assert cache.load_raw_diagnostics(old) is None
    usage = clear_project_processing_cache(changed.project_root)
    assert "preflight QC cache" in usage.targets
    assert not directory.exists()


@pytest.mark.parametrize("change", ["diagnostic_helper", "wrapped_diagnostic_helper", "detector", "native_helper",
                                  "method_version", "geometry_function", "scalp_selection"])
def test_changed_same_version_helpers_or_method_cannot_reuse_saved_evidence(context, monkeypatch, change):
    raw, _source, kwargs = context
    old = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    assert old is not None
    cache.save_raw_diagnostics(old, _report(raw, kwargs))

    def changed_function(*_args, **_kwargs):
        return None

    if change == "diagnostic_helper":
        monkeypatch.setattr(diagnostics, "_robust_summary", changed_function)
    elif change == "wrapped_diagnostic_helper":
        changed_function.__wrapped__ = diagnostics._robust_summary
        monkeypatch.setattr(diagnostics, "_robust_summary", changed_function)
    elif change == "detector":
        monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", changed_function)
    elif change == "native_helper":
        from mne.preprocessing import _annotate_amplitude
        monkeypatch.setattr(_annotate_amplitude, "_mark_inner", changed_function)
    elif change == "method_version":
        monkeypatch.setattr(diagnostics, "QC_REVIEW_DIAGNOSTICS_VERSION", "new-method-version")
    elif change == "geometry_function":
        monkeypatch.setattr(diagnostics, "canonical_biosemi64_head_coordinates", changed_function)
    else:
        monkeypatch.setattr(diagnostics, "BIOSEMI64_CHANNEL_SET", {"Fp1"})
    assert cache.load_raw_diagnostics(old) is None
    new = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    assert new is None or new != old


def test_implementation_identity_is_stable_across_normal_calls(context):
    raw, _source, kwargs = context
    before = cache._implementation_identity()
    assert before is not None
    _report(raw, kwargs)
    assert cache._implementation_identity() == before


def test_runtime_policy_change_after_key_build_prevents_hit_and_publication(context, monkeypatch):
    raw, _source, kwargs = context
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    report = _report(raw, kwargs)
    cache.save_raw_diagnostics(key, report)
    path = preflight_qc_cache_path(key.project_root, namespace="raw_diagnostics", **key.inputs)
    before = path.read_bytes()
    monkeypatch.setattr(prepared_kurtosis_cache, "_native_execution_identity", lambda: (("fake_blas", "v1", 2),))
    assert cache.load_raw_diagnostics(key) is None
    cache.save_raw_diagnostics(key, report)
    assert path.read_bytes() == before


@pytest.mark.parametrize("boundary", ["key", "load", "save"])
def test_optional_memory_pressure_is_cache_miss_not_diagnostic_failure(context, monkeypatch, boundary):
    raw, _source, kwargs = context
    key = cache.build_raw_diagnostics_cache_key(raw, **kwargs)
    report = _report(raw, kwargs)

    def exhausted(*_args, **_kwargs):
        raise MemoryError("optional observer buffer")

    if boundary == "key":
        monkeypatch.setattr(cache, "_sample_digest", exhausted)
        assert cache.build_raw_diagnostics_cache_key(raw, **kwargs) is None
    elif boundary == "load":
        monkeypatch.setattr(cache, "load_preflight_qc_cache", exhausted)
        assert cache.load_raw_diagnostics(key) is None
    else:
        monkeypatch.setattr(cache, "save_preflight_qc_cache", exhausted)
        cache.save_raw_diagnostics(key, report)
