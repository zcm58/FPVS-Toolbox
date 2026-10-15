"""Compare diagnostic read sharing with the frozen two-call implementation."""

import ast
import warnings

import mne
import numpy as np
import pytest

from Main_App.processing import qc_review_diagnostics as qc
from Main_App.processing.prepared_raw_codec import encode_state


BASELINE_REF = "6aab9fa69b926d79097991f30dd84af4b2a579fd"
# Frozen from git show at BASELINE_REF; retain an oracle in shallow CI checkouts.
BASELINE_SEGMENTS_SOURCE = '''
def _mne_segments(values, sfreq, peak):
    """Return untrimmed MNE consecutive-difference spans for one bounded row."""
    # Always a bounded plain ndarray: Raw.__del__ must not unlink a source mmap.
    scratch = np.array(values, dtype=np.float64, copy=True, subok=False)[None, :]
    raw = mne.io.RawArray(scratch, mne.create_info(["signal"], sfreq, "eeg"), copy="info", verbose=False)
    result = {"flat": [], "peak": []}
    try:
        for kind, threshold in (("flat", 0.0), ("peak", peak)):
            if threshold is None:
                continue
            annotations, bads = mne.preprocessing.annotate_amplitude(
                raw, **{kind: threshold}, bad_percent=100, min_duration=0,
                picks=[0], verbose=False,
            )
            result[kind] = [
                (int(round(onset * sfreq)), int(round((onset + duration) * sfreq)) + 1)
                for onset, duration in zip(annotations.onset, annotations.duration)
            ]
            # MNE returns a bad-channel name instead of annotations at exactly
            # 100%. On one channel this means all consecutive differences pass;
            # recover its observed support without applying that suggestion.
            if bads:
                differences = np.abs(np.diff(scratch[0]))
                all_match = (np.isfinite(differences).all()
                             and bool(np.all(differences <= threshold if kind == "flat" else differences >= threshold)))
                if all_match:
                    result[kind] = [(0, len(values))]
    finally:
        raw.close()
    return result
'''


@pytest.fixture(scope="module")
def frozen_segments():
    source = BASELINE_SEGMENTS_SOURCE
    tree = ast.parse(source)
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_mne_segments")
    namespace = {"mne": mne, "np": np}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "frozen_qc_review_diagnostics", "exec"), namespace)
    return namespace["_mne_segments"]


def _observe(call):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            result, error = call(), None
        except Exception as exc:
            result, error = None, (type(exc), str(exc))
    arrays = {}
    encoded = encode_state(result, arrays)
    return encoded, {
        name: (value.dtype.str, value.shape, value.strides, value.tobytes())
        for name, value in arrays.items()
    }, error, [(item.category, str(item.message)) for item in caught]


def _values(case):
    values = np.random.default_rng(612).normal(scale=2e-6, size=513)
    peak = 100e-6
    if case == "patterns":
        values[12:35] = 0.0
        values[73:110] = 500e-6
        values[127:192] += 400e-6
        values[-9:] = 0.0
    elif case == "constant":
        values[:] = 4e-6
    elif case == "all_peak":
        values = np.arange(513, dtype=np.float64) * 200e-6
    elif case == "signed_zero":
        values[:] = 0.0
        values[::2] = -0.0
    elif case == "nonfinite":
        values[12], values[73], values[192] = np.nan, np.inf, -np.inf
    elif case == "extreme":
        values[::2], values[1::2] = np.finfo(np.float64).max, -np.finfo(np.float64).max
    elif case == "float32":
        values = values.astype(np.float32)
    elif case == "noncontiguous":
        values = np.repeat(values, 2)[::2]
    elif case == "no_peak":
        peak = None
    elif case == "zero_peak":
        peak = 0.0
    elif case == "invalid_peak":
        peak = -1.0
    elif case == "numpy_peak":
        peak = np.float64(peak)
    elif case == "one_sample":
        values = values[:1]
    elif case == "empty":
        values = values[:0]
    return values, peak


@pytest.mark.parametrize("case", [
    "noise", "patterns", "constant", "all_peak", "signed_zero", "nonfinite", "extreme",
    "float32", "noncontiguous", "no_peak", "zero_peak", "invalid_peak", "numpy_peak", "one_sample", "empty",
])
@pytest.mark.parametrize("sfreq", [100.0, 2048.0])
def test_segments_match_frozen_spans_warnings_errors_and_input_bits(frozen_segments, case, sfreq):
    values, peak = _values(case)
    before = values.tobytes()
    expected = _observe(lambda: frozen_segments(values, sfreq, peak))
    actual = _observe(lambda: qc._mne_segments(values, sfreq, peak))
    assert actual == expected
    assert values.tobytes() == before


def test_supported_rows_share_one_actual_mne_read(frozen_segments, monkeypatch):
    if mne.__version__ != "1.9.0":
        pytest.skip("The combined call is characterized for MNE 1.9.0")
    detector = mne.preprocessing.annotate_amplitude
    calls = []

    def spy(raw, **kwargs):
        calls.append(kwargs)
        return detector(raw, **kwargs)

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR_CODE", qc._callable_code(spy))
    values, peak = _values("patterns")
    expected = frozen_segments(values, 2048.0, peak)
    assert len(calls) == 2
    calls.clear()
    assert qc._mne_segments(values, 2048.0, peak) == expected
    assert len(calls) == 1
    assert calls[0]["flat"] == 0.0 and calls[0]["peak"] == peak


@pytest.mark.parametrize("case", ["nonfinite", "extreme", "float32", "noncontiguous", "zero_peak", "numpy_peak"])
def test_guarded_inputs_retain_separate_detector_calls(case, monkeypatch):
    detector = mne.preprocessing.annotate_amplitude
    calls = []

    def spy(raw, **kwargs):
        calls.append(kwargs)
        return detector(raw, **kwargs)

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR_CODE", qc._callable_code(spy))
    values, peak = _values(case)
    _observe(lambda: qc._mne_segments(values, 100.0, peak))
    assert len(calls) == 2
    assert [("flat" in call, "peak" in call) for call in calls] == [(True, False), (False, True)]


def test_replaced_public_detector_retains_original_call_contract(frozen_segments, monkeypatch):
    calls = []

    def unsupported(raw, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("Public detector replaced")

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", unsupported)
    values, peak = _values("noise")
    assert _observe(lambda: qc._mne_segments(values, 100.0, peak)) == _observe(
        lambda: frozen_segments(values, 100.0, peak)
    )
    assert all("flat" in call and "peak" not in call for call in calls)


def test_uncharacterized_mne_version_retains_original_calls(frozen_segments, monkeypatch):
    detector = mne.preprocessing.annotate_amplitude
    calls = []

    def spy(raw, **kwargs):
        calls.append(kwargs)
        return detector(raw, **kwargs)

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR", spy)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR_CODE", qc._callable_code(spy))
    monkeypatch.setattr(mne, "__version__", "uncharacterized")
    values, peak = _values("patterns")
    assert qc._mne_segments(values, 100.0, peak) == frozen_segments(values, 100.0, peak)
    assert len(calls) == 4
    assert all(not ("flat" in call and "peak" in call) for call in calls)


def test_optional_combined_allocation_failure_retries_frozen_path(frozen_segments, monkeypatch):
    if mne.__version__ != "1.9.0":
        pytest.skip("The combined call is characterized for MNE 1.9.0")
    detector = mne.preprocessing.annotate_amplitude
    calls = []

    def fail_combined(raw, **kwargs):
        calls.append(kwargs)
        if "flat" in kwargs and "peak" in kwargs:
            raise MemoryError("Optional combined allocation")
        return detector(raw, **kwargs)

    monkeypatch.setattr(mne.preprocessing, "annotate_amplitude", fail_combined)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR", fail_combined)
    monkeypatch.setattr(qc, "_AMPLITUDE_DETECTOR_CODE", qc._callable_code(fail_combined))
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 100.0, peak))
    calls.clear()
    assert _observe(lambda: qc._mne_segments(values, 100.0, peak)) == expected
    assert len(calls) == 3
    assert "flat" in calls[0] and "peak" in calls[0]
    assert "flat" in calls[1] and "peak" in calls[2]


def test_optional_finite_guard_allocation_failure_uses_frozen_path(frozen_segments, monkeypatch):
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 100.0, peak))
    original = np.isfinite
    rejected = []

    def fail_guard(value, *args, **kwargs):
        if isinstance(value, np.ndarray) and value.shape == (1, len(values)):
            rejected.append(True)
            raise MemoryError("Optional finite-input guard")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(np, "isfinite", fail_guard)
    assert _observe(lambda: qc._mne_segments(values, 100.0, peak)) == expected
    if mne.__version__ == "1.9.0":
        assert rejected == [True]


@pytest.mark.parametrize("case", ["patterns", "constant", "nonfinite", "signed_zero"])
@pytest.mark.parametrize("sfreq", [100.0, 256.0, 2048.0])
def test_complete_diagnostic_report_matches_frozen_bits_and_fingerprint(frozen_segments, monkeypatch, case, sfreq):
    values, _peak = _values(case)
    data = np.vstack([values, values[::-1], np.random.default_rng(982).normal(scale=2e-6, size=len(values))])
    before = data.tobytes()
    kwargs = {
        "sfreq": sfreq, "channels": ("Fp1", "Fp2", "EXG1"), "positions": {},
        "occurrences": [
            {"start_sample": 0, "stop_sample": 256, "condition_label": "Faces", "occurrence": 0},
            {"start_sample": 280, "stop_sample": 513, "condition_label": "Objects", "occurrence": 1},
        ],
        "signal_stage": "loaded_raw_before_reference", "evaluation_scope": "all_analyzed_occurrences",
        "sample_offset": 137, "source_first_samp": 37,
        "unusable_channels": ("Fp2",),
        "settings": qc.QCReviewDiagnosticSettings(chunk_samples=127, max_events=3),
    }
    current = qc._mne_segments
    monkeypatch.setattr(qc, "_mne_segments", frozen_segments)
    expected = _observe(lambda: qc.build_qc_review_diagnostics(data, **kwargs))
    monkeypatch.setattr(qc, "_mne_segments", current)
    actual = _observe(lambda: qc.build_qc_review_diagnostics(data, **kwargs))
    assert expected[2] is None
    assert actual == expected
    assert data.tobytes() == before


@pytest.mark.parametrize("sfreq", [1.0, 2.0, 128.0, 256.0, 2048.0, 16384.0])
def test_direct_path_uses_installed_mask_helper_and_frozen_threshold_boundaries(frozen_segments, monkeypatch, sfreq):
    if qc._MNE_DIAGNOSTIC_RUNTIME is None:
        pytest.skip("Installed MNE source differs from the characterized runtime")
    peak = float(2 ** -20)
    values = np.array([0.0, np.nextafter(peak, 0.0), 0.0, peak, peak, 0.0,
                       np.nextafter(peak, np.inf), -0.0, 0.0, -peak, 0.0])
    expected = _observe(lambda: frozen_segments(values, sfreq, peak))
    direct = qc._direct_mne_segments
    calls = []

    def direct_spy(*args):
        calls.append(True)
        return direct(*args)

    def unexpected_combined(*args):
        raise AssertionError("Supported direct input must bypass MNE Raw/annotations")

    monkeypatch.setattr(qc, "_direct_mne_segments", direct_spy)
    monkeypatch.setattr(qc, "_combined_mne_segments", unexpected_combined)
    assert _observe(lambda: qc._mne_segments(values, sfreq, peak)) == expected
    assert calls == [True]


@pytest.mark.parametrize("sfreq", [0.5, 100.0, 16385.0, 0.0, -1.0, np.nan, np.inf, 256, True])
def test_unsupported_or_invalid_rates_keep_frozen_validation(frozen_segments, monkeypatch, sfreq):
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, sfreq, peak))

    def unexpected_direct(*args):
        raise AssertionError("Uncharacterized sample rate must use the MNE path")

    monkeypatch.setattr(qc, "_direct_mne_segments", unexpected_direct)
    assert _observe(lambda: qc._mne_segments(values, sfreq, peak)) == expected


@pytest.mark.parametrize("case", ["flat", "peak", "alternating", "quiet"])
def test_long_direct_rows_preserve_full_support_and_order(frozen_segments, case):
    values = np.random.default_rng(403).normal(scale=2e-6, size=65537)
    peak = float(2 ** -16)
    if case == "flat":
        values[:] = -0.0
    elif case == "peak":
        values[::2], values[1::2] = peak, -peak
    elif case == "alternating":
        values[101:201] = 0.0
        values[40000:40010] = peak
        values[-6:] = -0.0
    expected = _observe(lambda: frozen_segments(values, 2048.0, peak))
    assert _observe(lambda: qc._mne_segments(values, 2048.0, peak)) == expected


def test_direct_optional_allocation_failure_uses_unchanged_mne_fallback(frozen_segments, monkeypatch):
    if qc._MNE_DIAGNOSTIC_RUNTIME is None:
        pytest.skip("Installed MNE source differs from the characterized runtime")
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 256.0, peak))
    calls = []

    def fail_direct(*args):
        calls.append(True)
        raise MemoryError("Optional direct diagnostic allocation")

    monkeypatch.setattr(qc, "_direct_mne_segments", fail_direct)
    assert _observe(lambda: qc._mne_segments(values, 256.0, peak)) == expected
    assert calls == [True]


def test_optional_runtime_guard_allocation_failure_keeps_frozen_path(frozen_segments, monkeypatch):
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 256.0, peak))

    def fail_guard(**kwargs):
        raise MemoryError("Optional installed-runtime guard allocation")

    monkeypatch.setattr(qc, "_mne_runtime_unchanged", fail_guard)
    assert _observe(lambda: qc._mne_segments(values, 256.0, peak)) == expected


def test_replaced_mne_helper_disables_both_shortcuts(frozen_segments, monkeypatch):
    from mne.preprocessing import _annotate_amplitude as module

    original = module._mask_to_onsets_offsets
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 256.0, peak))

    def helper(mask):
        return original(mask)

    def unexpected_shortcut(*args):
        raise AssertionError("Changed MNE helper must retain the original two-call path")

    monkeypatch.setattr(module, "_mask_to_onsets_offsets", helper)
    monkeypatch.setattr(qc, "_direct_mne_segments", unexpected_shortcut)
    monkeypatch.setattr(qc, "_combined_mne_segments", unexpected_shortcut)
    assert _observe(lambda: qc._mne_segments(values, 256.0, peak)) == expected


@pytest.mark.parametrize("name", ["_check_ptp", "_check_bad_percent", "_check_min_duration",
                                  "_annotations_starts_stops", "_picks_to_idx", "_picks_by_type",
                                  "_adjust_onset_meas_date"])
def test_changed_skipped_mne_helper_preserves_modified_frozen_behavior(frozen_segments, monkeypatch, name):
    from mne.preprocessing import _annotate_amplitude as module

    original = getattr(module, name)
    peak = 100e-6
    values = np.array([0.0, 150e-6, 150e-6, 150e-6, 150e-6, 0.0])
    before = _observe(lambda: frozen_segments(values, 128.0, peak))

    def changed(*args, **kwargs):
        result = original(*args, **kwargs)
        if name == "_check_ptp" and args[1] == "peak":
            return {kind: threshold * 2 for kind, threshold in result.items()}
        if name == "_check_bad_percent":
            return 50.0
        if name == "_check_min_duration":
            return args[1] / 3
        if name == "_annotations_starts_stops":
            return np.array([1]), np.array([args[0].n_times])
        if name == "_picks_to_idx":
            return np.array([], dtype=int)
        if name == "_picks_by_type":
            return []
        if name == "_adjust_onset_meas_date":
            args[0].onset += 1 / args[1].info["sfreq"]
        return result

    def unexpected_shortcut(*args):
        raise AssertionError("Changed validation helper must retain the original two-call path")

    monkeypatch.setattr(module, name, changed)
    expected = _observe(lambda: frozen_segments(values, 128.0, peak))
    assert expected != before
    monkeypatch.setattr(qc, "_direct_mne_segments", unexpected_shortcut)
    monkeypatch.setattr(qc, "_combined_mne_segments", unexpected_shortcut)
    assert _observe(lambda: qc._mne_segments(values, 128.0, peak)) == expected


def test_decorated_public_code_mutation_is_detected_without_unwrapped_change(frozen_segments, monkeypatch):
    detector = mne.preprocessing.annotate_amplitude
    unwrapped = detector.__wrapped__

    def changed_wrapper(*args, **kwargs):
        raise RuntimeError("Decorated public detector behavior changed")

    assert not detector.__code__.co_freevars and not changed_wrapper.__code__.co_freevars
    monkeypatch.setattr(detector, "__code__", changed_wrapper.__code__)
    assert detector.__wrapped__ is unwrapped
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 256.0, peak))
    assert expected[2] == (RuntimeError, "Decorated public detector behavior changed")
    assert _observe(lambda: qc._mne_segments(values, 256.0, peak)) == expected


def test_mne_source_digest_mismatch_disables_both_shortcuts(frozen_segments, monkeypatch):
    values, peak = _values("patterns")
    expected = _observe(lambda: frozen_segments(values, 256.0, peak))
    original = qc.inspect.getsource

    def changed_source(function):
        return original(function) + "\n# uncharacterized installed source\n"

    monkeypatch.setattr(qc.inspect, "getsource", changed_source)
    assert qc._characterized_mne_runtime() is None
    monkeypatch.setattr(qc, "_MNE_DIAGNOSTIC_RUNTIME", None)
    assert _observe(lambda: qc._mne_segments(values, 256.0, peak)) == expected


def test_chunk_seams_and_cancellation_match_complete_frozen_report(frozen_segments, monkeypatch):
    data = np.random.default_rng(852).normal(scale=2e-6, size=(3, 1031))
    data[0, 121:143] = -0.0
    data[1, 246:262] += 500e-6
    data[2, 510:514] = 0.0
    kwargs = {"sfreq": 256.0, "channels": ("Fp1", "Fp2", "O1"), "positions": {},
              "occurrences": [{"start_sample": 0, "stop_sample": 1031, "condition_label": "Faces", "occurrence": 0}],
              "signal_stage": "loaded_raw_before_reference",
              "settings": qc.QCReviewDiagnosticSettings(chunk_samples=127, max_events=2)}
    current = qc._mne_segments
    monkeypatch.setattr(qc, "_mne_segments", frozen_segments)
    expected = _observe(lambda: qc.build_qc_review_diagnostics(data, **kwargs))
    assert expected[2] is None
    monkeypatch.setattr(qc, "_mne_segments", current)
    assert _observe(lambda: qc.build_qc_review_diagnostics(data, **kwargs)) == expected

    def cancel_at_fourth_check():
        calls = 0

        def cancelled():
            nonlocal calls
            calls += 1
            return calls == 4

        return cancelled

    monkeypatch.setattr(qc, "_mne_segments", frozen_segments)
    expected = _observe(lambda: qc.build_qc_review_diagnostics(data, should_cancel=cancel_at_fourth_check(), **kwargs))
    monkeypatch.setattr(qc, "_mne_segments", current)
    actual = _observe(lambda: qc.build_qc_review_diagnostics(data, should_cancel=cancel_at_fourth_check(), **kwargs))
    assert actual == expected
    assert actual[2][0] is qc.QCReviewDiagnosticsCancelled
