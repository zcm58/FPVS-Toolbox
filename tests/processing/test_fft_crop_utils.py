import numpy as np
import pytest

from Main_App.Shared.fft_crop_utils import (
    CropResult,
    compute_fft_crop_from_events,
    compute_onbin_N,
    compute_onbin_step,
    plan_condition_fft_spans,
    resolve_oddball_ids_by_condition,
)


def _build_events(fs: int, onset_ids=(1,), reps=1, cycles=10, include_dups=False, missing_gap=False):
    rows = []
    sample = 0
    period = int(round(fs / 1.2))
    for rep in range(reps):
        onset_id = onset_ids[rep % len(onset_ids)]
        rows.append([sample, 0, onset_id])
        start55 = sample + int(0.2 * fs)
        for c in range(cycles):
            s55 = start55 + c * period
            rows.append([s55, 0, 55])
            if include_dups:
                rows.append([s55 + max(1, period // 10), 0, 55])
        if missing_gap and cycles >= 6:
            rows.pop(-3)
        sample += int((cycles + 2) * period)
    return np.asarray(sorted(rows, key=lambda x: x[0]), dtype=int), sample + period


def test_clean_runs_multiple_sampling_rates():
    for fs in (500, 512, 1000):
        events, stream_end = _build_events(fs, onset_ids=(1,), reps=1, cycles=12)
        results, n_step, warns = compute_fft_crop_from_events(events, fs=fs, onset_ids={1}, stream_end_sample=stream_end)
        assert warns == []
        crop = results[(1, 0)]
        assert not crop.fallback
        assert crop.n_samples > 0
        assert n_step is not None
        assert crop.n_samples % n_step == 0
        assert abs((1.2 * crop.n_samples / fs) - round(1.2 * crop.n_samples / fs)) < 1e-9


def test_supported_256_family_sampling_rates_use_three_oddball_cycle_steps():
    for fs, expected_step in [(256, 640), (512, 1280), (1024, 2560), (2048, 5120)]:
        _, n_step, warning = compute_onbin_step(fs=fs)

        assert warning is None
        assert n_step == expected_step
        assert 1.2 * n_step / fs == pytest.approx(3.0)

        samples_for_146_cycles = int(146 * fs / 1.2)
        assert 1.2 * samples_for_146_cycles / fs != pytest.approx(146.0)

        locked_n = compute_onbin_N(samples_for_146_cycles, n_step)
        assert locked_n % n_step == 0
        assert 1.2 * locked_n / fs == pytest.approx(144.0)


def test_duplicates_are_deduped():
    fs = 500
    events, stream_end = _build_events(fs, onset_ids=(1,), reps=1, cycles=12, include_dups=True)
    results, _, _ = compute_fft_crop_from_events(events, fs=fs, onset_ids={1}, stream_end_sample=stream_end)
    crop = results[(1, 0)]
    assert crop.n55_raw > crop.n55_dedup
    assert crop.dedup_dropped > 0


def test_missing_gap_warns_but_does_not_crash():
    fs = 500
    events, stream_end = _build_events(fs, onset_ids=(1,), reps=1, cycles=12, missing_gap=True)
    results, _, _ = compute_fft_crop_from_events(events, fs=fs, onset_ids={1}, stream_end_sample=stream_end)
    crop = results[(1, 0)]
    assert crop.missing_gap_count >= 1
    assert crop.n_samples >= 0


def test_condition_specific_oddball_codes_are_resolved_per_condition():
    fs = 256
    events = np.asarray(
        [
            [100, 0, 1],
            [200, 0, 51],
            [840, 0, 51],
            [1480, 0, 51],
            [2200, 0, 2],
            [2300, 0, 52],
            [2940, 0, 52],
            [3580, 0, 52],
        ],
        dtype=int,
    )
    oddball_ids = resolve_oddball_ids_by_condition(
        events,
        onset_ids={1, 2},
        stream_end_sample=5000,
    )

    assert oddball_ids == {1: 51, 2: 52}

    results, n_step, warns = compute_fft_crop_from_events(
        events,
        fs=fs,
        onset_ids={1, 2},
        oddball_id=oddball_ids,
        stream_end_sample=5000,
    )

    assert warns == []
    assert n_step == 640
    assert results[(1, 0)].oddball_id == 51
    assert results[(2, 0)].oddball_id == 52
    assert not results[(1, 0)].fallback
    assert not results[(2, 0)].fallback
    assert results[(1, 0)].n_samples % n_step == 0
    assert results[(2, 0)].n_samples % n_step == 0


def test_differing_reps_common_n_minimum():
    fs = 500
    events_a, end_a = _build_events(fs, onset_ids=(1,), reps=1, cycles=12)
    events_b, end_b = _build_events(fs, onset_ids=(1,), reps=1, cycles=8)
    shift = end_a + int(fs)
    events_b = events_b.copy()
    events_b[:, 0] += shift
    events = np.vstack([events_a, events_b])
    results, _, _ = compute_fft_crop_from_events(events, fs=fs, onset_ids={1}, stream_end_sample=end_a + end_b + shift)
    n_values = [results[(1, 0)].n_samples, results[(1, 1)].n_samples]
    assert min(n_values) == sorted(n_values)[0]


def test_no_55_fallback():
    fs = 500
    events = np.asarray([[100, 0, 1], [1000, 0, 2]], dtype=int)
    results, _, _ = compute_fft_crop_from_events(events, fs=fs, onset_ids={1, 2}, stream_end_sample=2000)
    assert results[(1, 0)].fallback
    assert results[(2, 0)].fallback


def _crop_result(
    *,
    start: int,
    n_samples: int,
    fallback: bool = False,
    fallback_reason: str | None = None,
) -> CropResult:
    return CropResult(
        crop_start_sample=start,
        n_samples=n_samples,
        n55_raw=2,
        n55_dedup=2,
        cycles=1,
        block_start_sample=start,
        block_end_sample=start + n_samples,
        fallback=fallback,
        fallback_reason=fallback_reason,
    )


def test_condition_fft_span_plan_uses_one_onbin_length_for_all_repetitions():
    crop_results = {
        (2, 0): _crop_result(start=9000, n_samples=6400),
        (1, 1): _crop_result(start=5000, n_samples=7100),
        (1, 0): _crop_result(start=1000, n_samples=7680),
    }

    plan = plan_condition_fft_spans(
        crop_results,
        condition_id=1,
        n_step=640,
    )

    assert plan.condition_id == 1
    assert plan.repetition_keys == ((1, 0), (1, 1))
    assert plan.n_step == 640
    assert plan.n_common == 7040
    assert plan.repetition_spans == ((1000, 8040), (5000, 12040))
    assert plan.fallback_repetition_reasons == ()


def test_condition_fft_span_plan_preserves_fallback_diagnostics():
    crop_results = {
        (1, 0): _crop_result(start=1000, n_samples=6400),
        (1, 1): _crop_result(
            start=9000,
            n_samples=0,
            fallback=True,
            fallback_reason="insufficient_55",
        ),
        (1, 2): _crop_result(
            start=17000,
            n_samples=0,
            fallback=True,
        ),
    }

    plan = plan_condition_fft_spans(
        crop_results,
        condition_id=1,
        n_step=640,
    )

    assert plan.n_common == 6400
    assert plan.repetition_spans == ()
    assert plan.fallback_repetition_reasons == (
        "rep=1:insufficient_55",
        "rep=2:unknown",
    )


@pytest.mark.parametrize("n_step", [None, 0])
def test_condition_fft_span_plan_has_no_spans_without_valid_step(n_step):
    crop_results = {(1, 0): _crop_result(start=1000, n_samples=6400)}

    plan = plan_condition_fft_spans(
        crop_results,
        condition_id=1,
        n_step=n_step,
    )

    assert plan.n_common is None
    assert plan.repetition_spans == ()
