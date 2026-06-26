from __future__ import annotations

from pathlib import Path
import threading
import time

import mne
import numpy as np

from Main_App.io.load_utils import BdfPreflightInfo
from Main_App.processing.processing_controller import RawFileInfo
import Main_App.processing.preflight_qc as preflight_qc
from Main_App.processing.preflight_qc import (
    scan_preprocessing_qc,
    scan_recording_not_started_files,
)


def _raw_with_removed_channel(channel: str) -> mne.io.RawArray:
    montage = mne.channels.make_standard_montage("biosemi64")
    names = list(montage.ch_names)
    rng = np.random.default_rng(99)
    data = rng.normal(scale=500e-6, size=(len(names), 4096))
    data[names.index(channel)] = rng.normal(scale=2e-6, size=data.shape[1])
    raw = mne.io.RawArray(
        data,
        mne.create_info(names, sfreq=256.0, ch_types=["eeg"] * len(names)),
        verbose=False,
    )
    raw.set_montage(montage)
    return raw


def test_scan_recording_not_started_files_uses_bdf_header(monkeypatch, tmp_path: Path) -> None:
    raw_path = tmp_path / "P01.bdf"
    raw_path.write_bytes(b"header")

    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.inspect_bdf_header",
        lambda _path: BdfPreflightInfo(
            file_size=19_000,
            header_bytes=19_000,
            data_records=0,
            record_duration=1.0,
            channel_count=72,
        ),
    )

    flagged = scan_recording_not_started_files([RawFileInfo(raw_path, "P01")])

    assert len(flagged) == 1
    assert flagged[0].participant_id == "P01"
    assert flagged[0].path == raw_path


def test_scan_preprocessing_qc_prepopulates_auto_removed_electrodes(
    monkeypatch,
    tmp_path: Path,
) -> None:
    raw_path = tmp_path / "P03.bdf"
    raw_path.write_bytes(b"not a real bdf for this unit test")

    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.inspect_bdf_header",
        lambda _path: None,
    )
    monkeypatch.setattr(
        "Main_App.processing.preflight_qc.load_utils.load_eeg_file",
        lambda *_args, **_kwargs: _raw_with_removed_channel("P9"),
    )

    scan = scan_preprocessing_qc(
        [RawFileInfo(raw_path, "P03")],
        {"stim_channel": "Status", "max_bad_chans": 20},
    )

    assert scan.cancelled is False
    assert scan.suggested_removed_electrodes == {"P03": ["P9"]}
    assert scan.hard_exclusion_candidates == ()


def test_scan_preprocessing_qc_uses_parallel_workers(
    monkeypatch,
    tmp_path: Path,
) -> None:
    paths = []
    for index in range(6):
        raw_path = tmp_path / f"P{index + 1:02d}.bdf"
        raw_path.write_bytes(b"not a real bdf for this unit test")
        paths.append(raw_path)

    lock = threading.Lock()
    active = 0
    max_active = 0

    class _RawQcResult:
        excluded = False
        reason = None
        message = ""

        def to_payload(self) -> dict[str, object]:
            return {"channels_to_interpolate": []}

    class _SpectralQcResult:
        def to_payload(self) -> dict[str, object]:
            return {"evaluated": True, "widespread": False, "flagged_channels": []}

    def _fake_load(*_args, **_kwargs):
        nonlocal active, max_active
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.05)
            return object()
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(preflight_qc.load_utils, "inspect_bdf_header", lambda _path: None)
    monkeypatch.setattr(preflight_qc.load_utils, "load_eeg_file", _fake_load)
    monkeypatch.setattr(
        preflight_qc,
        "evaluate_raw_channel_qc",
        lambda *_args, **_kwargs: _RawQcResult(),
    )
    monkeypatch.setattr(
        preflight_qc,
        "evaluate_raw_spectral_qc",
        lambda *_args, **_kwargs: _SpectralQcResult(),
    )

    scan = scan_preprocessing_qc(
        [
            RawFileInfo(path, f"P{index + 1:02d}")
            for index, path in enumerate(paths)
        ],
        {"stim_channel": "Status", "max_bad_chans": 20},
        max_workers=3,
    )

    assert scan.cancelled is False
    assert max_active > 1
    assert [result.participant_id for result in scan.results] == [
        "P01",
        "P02",
        "P03",
        "P04",
        "P05",
        "P06",
    ]
