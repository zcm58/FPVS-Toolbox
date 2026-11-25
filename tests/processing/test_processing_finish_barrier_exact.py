"""Native scientific bytes across the optional unconditional resource barrier."""

import pytest
from threadpoolctl import threadpool_limits

from Main_App.processing import preprocess
from Main_App.processing.prepared_raw_codec import raw_state
from tests.processing.test_review_resource_admission_independent import _bits, _source
from tests.processing.test_preprocess_kurtosis_gate import _params


def _capture(source, *, reject, callback=None, checkpoint=False):
    params = _params(source)
    params.update(downsample_rate=80.0, reject_thresh=reject,
                  project_root=str(source.parent), enable_kurtosis_checkpoint_cache=checkpoint,
                  _fpvs_stop_before_kurtosis_interpolation=True)
    raw = _source()
    processed = None
    try:
        kwargs = {} if callback is None else {"before_processing_finish": callback}
        processed, rejected = preprocess.perform_preprocessing(raw, params, lambda *_: None, source.name, **kwargs)
        assert processed is not None, params.get("_fpvs_preprocessing_error")
        return _bits({
            "raw": raw_state(processed), "samples": processed._data,
            "rejected": rejected, "evidence": params.get("_fpvs_kurtosis_qc_evidence"),
            "decisions": params.get("_fpvs_kurtosis_decision_plan"),
        })
    finally:
        if processed is not None and processed is not raw:
            processed.close()
        raw.close()


@pytest.mark.parametrize("reject", [0.0, 10.0])
def test_unconditional_finish_barrier_preserves_native_samples_state_and_evidence(tmp_path, reject):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable synthetic resource-barrier source")
    observed = []
    with threadpool_limits(limits=1):
        baseline = _capture(source, reject=reject)
        actual = _capture(source, reject=reject,
                          callback=lambda raw: observed.append((len(raw.ch_names), raw.n_times, raw.info["sfreq"])))
    assert actual == baseline
    assert observed == [(21, 800, 80.0)]


def test_disabled_kurtosis_still_observes_source_rate_fallback_before_finish(tmp_path, monkeypatch):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable native failed-resample source")

    def unavailable(*_args, **_kwargs):
        raise MemoryError("Injected native resample allocation failure")

    monkeypatch.setattr(preprocess, "resample_raw", unavailable)
    observed = []
    with threadpool_limits(limits=1):
        baseline = _capture(source, reject=0)
        actual = _capture(source, reject=0, callback=lambda raw: observed.append((raw.n_times, raw.info["sfreq"])))
    assert actual == baseline
    assert observed == [(1000, 100.0)]


def test_warm_checkpoint_observes_same_finish_barrier_without_changing_values(tmp_path):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable native warm resource-barrier source")
    observed = []
    with threadpool_limits(limits=1):
        _capture(source, reject=10, checkpoint=True)
        baseline = _capture(source, reject=10, checkpoint=True)
        actual = _capture(source, reject=10, checkpoint=True,
                          callback=lambda raw: observed.append((raw.n_times, raw.info["sfreq"])))
    assert actual == baseline
    assert observed == [(800, 80.0)]


@pytest.mark.parametrize("fir_succeeds", [False, True])
def test_preprocessing_notch_gate_uses_applied_fir_cutoff(tmp_path, monkeypatch, fir_succeeds):
    source = tmp_path / "P001.bdf"
    source.write_bytes(b"Immutable native FFT barrier source")

    def filter_raw(raw, _l_freq, h_freq, **_kwargs):
        if not fir_succeeds:
            raise MemoryError("Injected FIR allocation failure")
        with raw.info._unlock():
            raw.info["lowpass"] = h_freq

    monkeypatch.setattr(preprocess, "filter_raw_with_prepared_fir", filter_raw)
    observed = []

    def run(before_notch=None):
        raw = _source()
        with raw.info._unlock():
            raw.info["sfreq"] = 200.0
            raw.info["lowpass"] = 100.0
        params = _params(source)
        params.pop("_fpvs_source_analysis_span_plan")
        params.update(downsample_rate=200.0, low_pass=50.0, reject_thresh=0.0,
                      line_noise_filter_enabled=True, enable_kurtosis_checkpoint_cache=False,
                      _fpvs_require_analysis_spans=False, _fpvs_stop_before_kurtosis_interpolation=True)
        try:
            processed, _ = preprocess.perform_preprocessing(
                raw, params, lambda *_: None, source.name, before_notch=before_notch,
            )
            assert processed is not None, params.get("_fpvs_preprocessing_error")
            return _bits({
                "samples": processed._data,
                "requested": params["_fpvs_fft_multinotch_requested_centers_hz"],
                "applied": params["_fpvs_fft_multinotch_applied_centers_hz"],
                "skipped": params["_fpvs_fft_multinotch_skipped_centers"],
            })
        finally:
            raw.close()

    with threadpool_limits(limits=1):
        baseline = run()
        actual = run(lambda *shape: observed.append(shape))

    assert actual == baseline
    assert observed == ([] if fir_succeeds else [(21, 1000, 200.0)])
