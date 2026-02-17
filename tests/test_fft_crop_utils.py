import numpy as np

from Main_App.Legacy_App.fft_crop_utils import compute_fft_crop_from_events


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
