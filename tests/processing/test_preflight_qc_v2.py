from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
import threading
import time

import numpy as np
import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from Main_App.processing.processing_controller import RawFileInfo
import Main_App.processing.preflight_qc as preflight_qc
from Main_App.processing.raw_channel_qc import SCALP_CHANNELS
from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol


def _event_rows(offset: int = 0) -> np.ndarray:
    return np.asarray(
        [
            (100 + offset, 0, 1),
            (300 + offset, 0, 55),
            (513 + offset, 0, 55),
            (727 + offset, 0, 55),
            (940 + offset, 0, 55),
        ],
        dtype=int,
    )


def _settings() -> dict[str, object]:
    return {
        "stim_channel": "Trigger",
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_bad_chans": 20,
        "high_pass": 1.0,
        "low_pass": 50.0,
        "downsample": 256,
        "downsample_rate": 256,
        "base_freq": 6.0,
        "oddball_freq": 1.2,
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": 60,
        "frequency_protocol": FrequencyProtocol.from_recurrence(
            6,
            5,
            expected_analyzed_oddball_cycles=3,
            expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
        ),
    }


class _LazyRaw:
    def __init__(
        self,
        data: np.ndarray,
        channel_names: list[str],
        *,
        read_hook=None,
        first_samp: int = 0,
    ) -> None:
        self._data = data
        self.ch_names = channel_names
        self.info = {"sfreq": 256.0}
        self.n_times = data.shape[1]
        self.first_samp = int(first_samp)
        self.reads: list[tuple[tuple[int, ...], int, int]] = []
        self._read_hook = read_hook

    def get_data(self, *, picks, start, stop, verbose=False):  # noqa: ANN001, ARG002
        pick_tuple = tuple(int(value) for value in picks)
        self.reads.append((pick_tuple, int(start), int(stop)))
        if self._read_hook is not None:
            self._read_hook()
        return self._data[np.asarray(pick_tuple), int(start) : int(stop)]


def _raw_data() -> tuple[np.ndarray, list[str]]:
    names = sorted(SCALP_CHANNELS) + ["Trigger"]
    rng = np.random.default_rng(2026)
    data = rng.normal(scale=500e-6, size=(len(names), 5_000))
    data[names.index("P9")] = rng.normal(scale=1e-7, size=data.shape[1])
    data[-1] = 0.0
    return data, names


def _install_lazy_fakes(
    monkeypatch,
    raws: list[_LazyRaw],
    events: np.ndarray,
    *,
    first_n_arguments: list[int] | None = None,
) -> list[str]:
    stim_arguments: list[str] = []

    @contextmanager
    def _open(*_args, stim_channel=None, first_n_channels=None, **_kwargs):
        stim_arguments.append(str(stim_channel))
        if first_n_arguments is not None:
            first_n_arguments.append(int(first_n_channels))
        yield raws.pop(0)

    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(preflight_qc.load_utils, "open_preflight_eeg_file", _open)
    monkeypatch.setattr(
        preflight_qc.mne,
        "find_events",
        lambda *_args, **_kwargs: np.array(events, copy=True),
    )
    return stim_arguments


def test_v3_accepts_canonical_project_reference_keys() -> None:
    settings = {
        "ref_chan1": "M1",
        "ref_chan2": "M2",
        "removed_electrode_detection_mode": "off",
        "auto_detect_removed_electrodes": False,
        "manual_removed_electrodes_enabled": True,
        "_fpvs_manual_removed_electrodes": ["P9"],
    }

    assert preflight_qc._configured_ref_pair(settings) == ("M1", "M2")
    cache_settings = preflight_qc._preflight_cache_settings(settings)
    assert cache_settings["reference_pair"] == [
        "M1",
        "M2",
    ]
    assert cache_settings["removed_electrode_detection_mode"] == "off"
    assert cache_settings["auto_detect_removed_electrodes"] is False
    assert cache_settings["manual_removed_electrodes_enabled"] is True
    assert cache_settings["_fpvs_manual_removed_electrodes"] == ["P9"]
    assert "epoch_end" not in preflight_qc._preflight_cache_settings(settings)
    method = preflight_qc._preflight_cache_method()
    assert method["version"] == "v6_five_second_overlapping_transients"
    assert method["condition_io_chunk_duration_s"] == 10.0
    assert method["transient_window_duration_s"] == 5.0
    assert method["transient_window_hop_s"] == 2.5
    assert method["transient_overlap_counting"] == (
        "union_coverage_not_independent_events"
    )
    assert method["geometry"]["montage_id"] == "biosemi64"
    assert method["condition_completion_policy"] == "locked_fft_span_v1"
    assert "condition_minimum_completion_s" not in method


@pytest.mark.parametrize(
    ("sample_count", "sfreq", "expected"),
    (
        (
            100,
            10.0,
            ((0, 50, "regular"), (25, 75, "regular"), (50, 100, "regular")),
        ),
        (
            113,
            10.0,
            (
                (0, 50, "regular"),
                (25, 75, "regular"),
                (50, 100, "regular"),
                (63, 113, "tail_aligned"),
            ),
        ),
        (30, 10.0, ((0, 30, "short"),)),
        (50, 10.0, ((0, 50, "regular"),)),
        (
            100,
            7.5,
            (
                (0, 38, "regular"),
                (19, 57, "regular"),
                (38, 76, "regular"),
                (57, 95, "regular"),
                (62, 100, "tail_aligned"),
            ),
        ),
    ),
)
def test_transient_window_bounds_are_deterministic_and_fully_bounded(
    sample_count: int,
    sfreq: float,
    expected: tuple[tuple[int, int, str], ...],
) -> None:
    bounds = preflight_qc._transient_window_bounds(sample_count, sfreq=sfreq)

    assert bounds == expected
    assert len({(start, stop) for start, stop, _kind in bounds}) == len(bounds)
    covered = np.zeros(sample_count, dtype=bool)
    for start, stop, _kind in bounds:
        assert 0 <= start < stop <= sample_count
        covered[start:stop] = True
    assert covered.all()


def test_condition_windows_are_views_inside_one_analyzed_occurrence() -> None:
    data = np.arange(2 * 113, dtype=float).reshape(2, 113)
    span = preflight_qc.ConditionQcSpan(
        condition_label="Arbitrary rate condition",
        condition_id=17,
        repetition_index=2,
        onset_sample=350,
        time_start_sample=400,
        time_stop_sample=513,
        spectral_start_sample=400,
        spectral_stop_sample=513,
        oddball_id=55,
        last_oddball_sample=512,
    )

    windows = preflight_qc._condition_blocks(data, span=span, sfreq=10.0)

    assert [(item.start_sample, item.stop_sample) for item in windows] == [
        (400, 450),
        (425, 475),
        (450, 500),
        (463, 513),
    ]
    assert all(item.condition_id == "Arbitrary rate condition" for item in windows)
    assert all(item.occurrence == 2 for item in windows)
    assert all(np.shares_memory(item.data, data) for item in windows)
    assert windows[-1].window_kind == "tail_aligned"
    assert sum(item.is_final for item in windows) == 1


@pytest.mark.parametrize("burst_duration_ms", (50, 100, 300))
def test_overlap_supplies_one_window_containing_a_boundary_burst(
    burst_duration_ms: int,
) -> None:
    sfreq = 100.0
    bounds = preflight_qc._transient_window_bounds(1_000, sfreq=sfreq)
    duration = int(round(burst_duration_ms / 1_000 * sfreq))
    burst_start = 500 - duration // 2
    burst_stop = burst_start + duration

    assert burst_start < 500 < burst_stop
    assert not any(
        start <= burst_start and burst_stop <= stop
        for start, stop in ((0, 500), (500, 1_000))
    )
    assert any(
        start <= burst_start and burst_stop <= stop
        for start, stop, _kind in bounds
    )


def test_occurrence_evaluation_scope_keeps_unavailable_rows_out_of_denominator() -> None:
    event_plan = SimpleNamespace(
        spans=(SimpleNamespace(condition_id=1, repetition_index=0),),
        approved_occurrences=(
            {
                "condition_code": 1,
                "repetition_index": 1,
                "disposition": "exclude_occurrence",
            },
        ),
        unresolved_occurrences=(
            {
                "condition_code": 2,
                "repetition_index": 0,
                "review_reasons": ["missing_required_marker"],
            },
        ),
        marker_integrity_plan={
            "occurrences": [
                {
                    "condition_label": "Faces",
                    "condition_code": 1,
                    "repetition_index": 0,
                    "fingerprint": "evaluated",
                },
                {
                    "condition_label": "Faces",
                    "condition_code": 1,
                    "repetition_index": 1,
                    "fingerprint": "excluded",
                },
                {
                    "condition_label": "Words",
                    "condition_code": 2,
                    "repetition_index": 0,
                    "fingerprint": "missing",
                },
            ]
        },
    )

    rows = preflight_qc._occurrence_evaluation_scope(event_plan)

    assert [row["evaluation_status"] for row in rows] == [
        "evaluated",
        "not_evaluated",
        "not_evaluated",
    ]
    assert rows[1]["reason"] == "excluded_after_marker_review"
    assert rows[2]["reason"] == "missing_required_marker"


def test_legacy_preflight_loader_uses_project_channel_limit(
    monkeypatch,
    tmp_path: Path,
) -> None:
    captured: dict[str, object] = {}
    sentinel = object()

    def _load(_app, _path, **kwargs):
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(preflight_qc.load_utils, "load_eeg_file", _load)
    settings = _settings()
    settings["max_idx_keep"] = None
    settings["max_chan_idx_keep"] = 24

    loaded = preflight_qc._load_raw_for_preflight(
        tmp_path / "P24.bdf",
        settings,
    )

    assert loaded is sentinel
    assert captured["first_n_channels"] == 24


def test_reduced_project_channel_limit_controls_preflight_loader_qc_and_geometry(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P16.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names)
    first_n_arguments: list[int] = []
    _install_lazy_fakes(
        monkeypatch,
        [raw],
        _event_rows(),
        first_n_arguments=first_n_arguments,
    )
    settings = _settings()
    settings["max_idx_keep"] = None
    settings["max_chan_idx_keep"] = 16

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P16", "control")],
        settings,
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    result = scan.results[0]
    geometry = result.condition_qc["geometry"]
    expected_retained = list(BIOSEMI64_CHANNELS[:16])
    assert first_n_arguments == [16]
    assert geometry["retained_scalp_channels"] == expected_retained
    assert geometry["retained_scalp_channel_count"] == 16
    assert preflight_qc._preflight_cache_settings(settings)[
        "channel_subset_first_n"
    ] == 16
    assert preflight_qc._preflight_cache_method(settings)["geometry"][
        "retained_scalp_channels"
    ] == expected_retained
    assert raw.reads
    assert all(
        names[pick_index] in expected_retained
        for pick_indices, _start, _stop in raw.reads
        for pick_index in pick_indices
    )


def test_v3_reads_exact_locked_condition_samples_and_reuses_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P06.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    first_raw = _LazyRaw(data, names)
    second_raw = _LazyRaw(data, names)
    stim_arguments = _install_lazy_fakes(
        monkeypatch,
        [first_raw, second_raw],
        _event_rows(),
    )
    progress: list[tuple[str, int, int]] = []

    first = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
        progress=lambda message, completed, total: progress.append(
            (message, completed, total)
        ),
    )

    assert first.cancelled is False
    assert first_raw.reads == [(tuple(range(len(names) - 1)), 300, 940)]
    assert first.results[0].condition_qc["samples_read_per_channel"] == 640
    assert first.results[0].condition_qc["recording_samples_per_channel"] == 5_000
    assert first.results[0].condition_qc["disk_buffered_condition_count"] == 0
    assert first.results[0].condition_qc["cache_status"] == "miss"
    assert "P9" in first.results[0].auto_removed_electrodes
    assert first.results[0].raw_spectral_qc["review_only"] is True
    assert first.results[0].raw_spectral_qc["widespread"] is False
    assert first.results[0].raw_spectral_qc["condition_results"][0][
        "fft_bin_spacing_hz"
    ] == pytest.approx(0.4)
    assert any("Faces 1/1" in message for message, _done, _total in progress)

    settings_with_ignored_legacy_window = _settings()
    settings_with_ignored_legacy_window["epoch_end"] = 1.0
    second = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        settings_with_ignored_legacy_window,
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    assert second.results[0].condition_qc["cache_status"] == "hit"
    assert second_raw.reads == []
    assert stim_arguments == ["Trigger", "Trigger"]


def test_preflight_preserves_detector_off_without_signal_candidate_leakage(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P06-off.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names)
    _install_lazy_fakes(monkeypatch, [raw], _event_rows())
    settings = {
        **_settings(),
        "removed_electrode_detection_mode": "off",
        "auto_detect_removed_electrodes": False,
    }

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        settings,
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    payload = scan.results[0].raw_channel_qc
    assert payload["low_variance_channels"] == []
    assert payload["high_amplitude_channels"] == []
    assert payload["rare_burst_channels"] == []
    assert payload["spatial_outlier_channels"] == []
    assert payload["candidate_sources"] == {}
    assert payload["candidate_burden_findings"] == []
    assert payload["occurrence_review_findings"] == []
    assert payload["transient_review_findings"] == []
    assert payload["experimental_removed_electrode_detector"] == {
        "evaluation_status": "not_evaluated",
        "reason": "disabled_in_project_settings",
    }


def test_v3_converts_absolute_plan_bounds_to_relative_raw_reads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P06-nonzero-origin.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names, first_samp=1_000)
    _install_lazy_fakes(monkeypatch, [raw], _event_rows(offset=1_000))

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    assert scan.results[0].load_error is None
    assert raw.reads == [(tuple(range(len(names) - 1)), 300, 940)]
    event_plan = scan.results[0].condition_qc["event_plan"]
    assert event_plan["first_samp"] == 1_000
    coordinates = event_plan["source_analysis_span_plan"]["spans"][0][
        "source_coordinates"
    ]
    assert coordinates["start_sample"] == 1_300
    assert coordinates["start_relative_sample"] == 300


def test_v3_missing_marker_pauses_without_sample_read_or_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P06.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names)
    _install_lazy_fakes(
        monkeypatch,
        [raw],
        np.asarray([(100, 0, 1), (300, 0, 55)], dtype=int),
    )

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    result = scan.results[0]
    assert result.load_error is None
    assert result.condition_qc["marker_review_required"] is True
    unresolved = result.condition_qc["event_plan"]["unresolved_occurrences"]
    assert unresolved[0]["review_reasons"] == [
        "insufficient_project_oddball_markers"
    ]
    assert result.condition_qc["method_name"] == "condition_aware_preflight_qc"
    assert result.condition_qc["method_version"] == (
        "v6_five_second_overlapping_transients"
    )
    assert result.condition_qc["cache_status"] == "marker_review_required"
    assert raw.reads == []
    cache_directory = (
        tmp_path
        / ".fpvs_processing"
        / "preflight_qc"
        / "v6_five_second_overlapping_transients"
    )
    assert not list(cache_directory.glob("*.json"))


def test_condition_data_buffer_uses_chunked_condition_only_memmap(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data = np.arange(2 * 6_000, dtype=np.float64).reshape(2, 6_000)
    raw = _LazyRaw(data, ["P9", "P10"])
    monkeypatch.setattr(preflight_qc, "PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES", 1)
    progress: list[str] = []

    with preflight_qc._condition_data_buffer(
        raw,
        picks=(0, 1),
        start=100,
        stop=5_500,
        sfreq=256.0,
        io_semaphore=threading.BoundedSemaphore(2),
        progress_detail=progress.append,
        detail_prefix="Faces 1/1",
    ) as (condition_data, disk_buffered):
        buffer_path = Path(condition_data.filename)
        actual = np.array(condition_data, copy=True)
        assert disk_buffered is True
        assert isinstance(condition_data, np.memmap)
        assert buffer_path.exists()
        del condition_data

    assert np.array_equal(actual, data[:, 100:5_500])
    assert raw.reads == [
        ((0, 1), 100, 2_660),
        ((0, 1), 2_660, 5_220),
        ((0, 1), 5_220, 5_500),
    ]
    assert not buffer_path.exists()
    assert progress[-1].endswith("reading condition block 3/3 (disk-buffered)")


def test_condition_data_buffer_cancellation_removes_temporary_file(
    monkeypatch,
    tmp_path: Path,
) -> None:
    data = np.arange(2 * 6_000, dtype=np.float64).reshape(2, 6_000)
    raw = _LazyRaw(data, ["P9", "P10"])
    monkeypatch.setattr(preflight_qc, "PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES", 1)
    monkeypatch.setattr(preflight_qc.tempfile, "tempdir", str(tmp_path))

    with pytest.raises(preflight_qc._PreflightQcCancelled):
        with preflight_qc._condition_data_buffer(
            raw,
            picks=(0, 1),
            start=100,
            stop=5_500,
            sfreq=256.0,
            io_semaphore=threading.BoundedSemaphore(2),
            should_cancel=lambda: True,
        ):
            pytest.fail("a cancelled disk-buffered condition must not be yielded")

    assert list(tmp_path.iterdir()) == []


def test_disk_buffered_and_in_memory_scans_have_identical_qc_payloads(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P10.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    _install_lazy_fakes(
        monkeypatch,
        [_LazyRaw(data, names), _LazyRaw(data, names)],
        _event_rows(),
    )
    ram_root = tmp_path / "ram-project"
    disk_root = tmp_path / "disk-project"
    ram_root.mkdir()
    disk_root.mkdir()

    in_memory = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P10", "control")],
        _settings(),
        project_root=ram_root,
        event_map={"Faces": 1},
    ).results[0]
    monkeypatch.setattr(preflight_qc, "PREFLIGHT_QC_MAX_IN_MEMORY_CONDITION_BYTES", 1)
    disk_buffered = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P10", "control")],
        _settings(),
        project_root=disk_root,
        event_map={"Faces": 1},
    ).results[0]

    assert disk_buffered.raw_channel_qc == in_memory.raw_channel_qc
    assert disk_buffered.raw_spectral_qc == in_memory.raw_spectral_qc
    assert in_memory.condition_qc["disk_buffered_condition_count"] == 0
    assert disk_buffered.condition_qc["disk_buffered_condition_count"] == 1


def test_v2_settings_change_invalidates_cache(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "P07.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    first_raw = _LazyRaw(data, names)
    second_raw = _LazyRaw(data, names)
    _install_lazy_fakes(monkeypatch, [first_raw, second_raw], _event_rows())

    preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P07", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
    )
    changed = _settings()
    changed["low_pass"] = 100.0
    second = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P07", "control")],
        changed,
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    assert second.results[0].condition_qc["cache_status"] == "miss"
    assert second_raw.reads


def test_v2_caps_worker_and_bdf_read_concurrency(monkeypatch, tmp_path: Path) -> None:
    data, names = _raw_data()
    paths = []
    lock = threading.Lock()
    active_reads = 0
    maximum_reads = 0
    active_spectra = 0
    maximum_spectra = 0
    original_spectral_qc = preflight_qc.evaluate_condition_spectral_qc_v2

    def _read_hook() -> None:
        nonlocal active_reads, maximum_reads
        with lock:
            active_reads += 1
            maximum_reads = max(maximum_reads, active_reads)
        try:
            time.sleep(0.03)
        finally:
            with lock:
                active_reads -= 1

    def _spectral_qc(*args, **kwargs):  # noqa: ANN002, ANN003
        nonlocal active_spectra, maximum_spectra
        with lock:
            active_spectra += 1
            maximum_spectra = max(maximum_spectra, active_spectra)
        try:
            time.sleep(0.03)
            return original_spectral_qc(*args, **kwargs)
        finally:
            with lock:
                active_spectra -= 1

    raws = []
    for index in range(6):
        path = tmp_path / f"P{index + 1:02d}.bdf"
        path.write_bytes(f"identity-{index}".encode())
        paths.append(path)
        raws.append(_LazyRaw(data, names, read_hook=_read_hook))
    _install_lazy_fakes(monkeypatch, raws, _event_rows())
    monkeypatch.setattr(
        preflight_qc,
        "evaluate_condition_spectral_qc_v2",
        _spectral_qc,
    )

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(path, path.stem, "control") for path in paths],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
        max_workers=12,
    )

    assert scan.cancelled is False
    assert preflight_qc._preflight_worker_count(20, 99) == 4
    assert 1 < maximum_reads <= 2
    assert 1 < maximum_spectra <= 2
    assert [result.participant_id for result in scan.results] == [
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
    ]


def test_v2_cancellation_between_blocks_writes_no_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P08.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names)
    _install_lazy_fakes(monkeypatch, [raw], _event_rows())
    cancel = False

    def _progress(message: str, _completed: int, _total: int) -> None:
        nonlocal cancel
        if "time-domain block" in message:
            cancel = True

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P08", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
        progress=_progress,
        should_cancel=lambda: cancel,
    )

    assert scan.cancelled is True
    cache_directory = tmp_path / ".fpvs_processing" / "preflight_qc" / "v2"
    assert not cache_directory.exists()


def test_v2_cancellation_at_final_spectrum_writes_no_cache(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P09.bdf"
    raw_path.write_bytes(b"synthetic identity")
    data, names = _raw_data()
    raw = _LazyRaw(data, names)
    _install_lazy_fakes(monkeypatch, [raw], _event_rows())
    cancel = False

    def _progress(message: str, _completed: int, _total: int) -> None:
        nonlocal cancel
        if "checking exact on-bin spectrum" in message:
            cancel = True

    scan = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P09", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
        progress=_progress,
        should_cancel=lambda: cancel,
    )

    assert scan.cancelled is True
    cache_directory = tmp_path / ".fpvs_processing" / "preflight_qc" / "v2"
    assert not cache_directory.exists()
