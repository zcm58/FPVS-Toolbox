from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import threading
import time

import numpy as np
import pytest

from Main_App.processing.processing_controller import RawFileInfo
import Main_App.processing.preflight_qc as preflight_qc
from Main_App.processing.raw_channel_qc import SCALP_CHANNELS


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
        "epoch_end": 5.0,
        "high_pass": 1.0,
        "low_pass": 50.0,
        "downsample": 256,
        "downsample_rate": 256,
        "base_freq": 6.0,
        "oddball_freq": 1.2,
        "line_noise_filter_enabled": True,
        "line_noise_frequency_hz": 60,
    }


class _LazyRaw:
    def __init__(
        self,
        data: np.ndarray,
        channel_names: list[str],
        *,
        read_hook=None,
    ) -> None:
        self._data = data
        self.ch_names = channel_names
        self.info = {"sfreq": 256.0}
        self.n_times = data.shape[1]
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


def _install_lazy_fakes(monkeypatch, raws: list[_LazyRaw], events: np.ndarray) -> list[str]:
    stim_arguments: list[str] = []

    @contextmanager
    def _open(*_args, stim_channel=None, **_kwargs):
        stim_arguments.append(str(stim_channel))
        yield raws.pop(0)

    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(preflight_qc.load_utils, "open_preflight_eeg_file", _open)
    monkeypatch.setattr(
        preflight_qc.mne,
        "find_events",
        lambda *_args, **_kwargs: np.array(events, copy=True),
    )
    return stim_arguments


def test_v2_accepts_canonical_project_reference_keys() -> None:
    settings = {"ref_chan1": "M1", "ref_chan2": "M2"}

    assert preflight_qc._configured_ref_pair(settings) == ("M1", "M2")
    assert preflight_qc._preflight_cache_settings(settings)["reference_pair"] == [
        "M1",
        "M2",
    ]


def test_v2_reads_only_condition_samples_and_reuses_cache(
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
    assert first_raw.reads == [(tuple(range(len(names) - 1)), 100, 1_380)]
    assert first.results[0].condition_qc["samples_read_per_channel"] == 1_280
    assert first.results[0].condition_qc["recording_samples_per_channel"] == 5_000
    assert first.results[0].condition_qc["disk_buffered_condition_count"] == 0
    assert first.results[0].condition_qc["cache_status"] == "miss"
    assert "P9" in first.results[0].auto_removed_electrodes
    assert first.results[0].raw_spectral_qc["review_only"] is True
    assert first.results[0].raw_spectral_qc["widespread"] is False
    assert any("Faces 1/1" in message for message, _done, _total in progress)

    second = preflight_qc.scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P06", "control")],
        _settings(),
        project_root=tmp_path,
        event_map={"Faces": 1},
    )

    assert second.results[0].condition_qc["cache_status"] == "hit"
    assert second_raw.reads == []
    assert stim_arguments == ["Trigger", "Trigger"]


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
