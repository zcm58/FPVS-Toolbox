from __future__ import annotations

import os
from pathlib import Path
import traceback
import weakref

import mne
from mne.io.edf.edf import RawEDF
import numpy as np
import pytest

from Main_App.io import unicorn_raw
from Main_App.io.acquisition_profiles import (
    UNICORN_FACTORY_MAPPING_SOURCE_URL,
    UNICORN_FACTORY_RECORDED_LABEL_MAP,
)
from Main_App.io.load_utils import open_unicorn_recording_raw
from Main_App.io.unicorn_units import UnicornUnitError
from tests.bdf_factory import write_bdf


@pytest.fixture
def unicorn_source(tmp_path):
    eeg = tuple(UNICORN_FACTORY_RECORDED_LABEL_MAP)
    source = write_bdf(
        tmp_path / "source.bdf", variant="BDF", record_onsets=("0",),
        eeg_names=eeg, unit="?V",
        physical_ranges=dict.fromkeys(eeg, (-750000, 750000)),
        signal_values={
            **{name: [[1000 * (index + 1)] * 250] for index, name in enumerate(eeg)},
            "Status": [[0, 55, 55] + [0] * 247],
        },
    )
    settings = {"acquisition_profile": {
        "id": "unicorn_hybrid_black", "version": "1.0",
        "montage_id": "unicorn8", "montage_version": "1.0",
        "event_decoder_id": "unicorn_sample", "event_decoder_version": "1.0",
        "reference_policy": "average_scalp",
        "source_to_canonical": dict(UNICORN_FACTORY_RECORDED_LABEL_MAP),
        "label_mapping_evidence": {
            "status": "verified", "reference": UNICORN_FACTORY_MAPPING_SOURCE_URL,
        },
    }}
    return source, settings


def test_mne_segment_failure_releases_allocated_memmap_without_masking_error(
    tmp_path, monkeypatch, unicorn_source,
):
    source, settings = unicorn_source
    original = source.read_bytes()
    failure = RuntimeError("injected MNE segment failure after memmap allocation")
    mapped_paths = []
    mapped_views = []

    def fail_segment_after_allocation(self, data, idx, fi, start, stop, cals, mult):
        assert isinstance(data, np.memmap)
        assert not data._mmap.closed
        mapped_path = Path(data.filename)
        assert mapped_path.name == "samples.dat"
        assert mapped_path.is_file()
        assert mapped_path.stat().st_size == 9 * 250 * np.dtype(np.float64).itemsize
        mapped_paths.append(mapped_path)
        mapped_views.append(weakref.ref(data))
        data[0, 0] = 123.0
        raise failure

    monkeypatch.setattr(RawEDF, "_read_segment_file", fail_segment_after_allocation)

    with pytest.raises(RuntimeError, match="injected MNE segment failure") as caught:
        with open_unicorn_recording_raw(
            source, settings, project_root=tmp_path, event_authority="status", preload="memmap",
        ):
            pytest.fail("An unsuccessful MNE preload cannot yield a recording.")

    assert caught.value is failure
    assert len(mapped_paths) == 1
    assert mapped_views[0]() is None
    assert not mapped_paths[0].exists()
    assert not mapped_paths[0].parent.exists()
    assert not list((tmp_path / ".fpvs_processing" / "unicorn_reader").iterdir())
    assert source.read_bytes() == original
    assert "fail_segment_after_allocation" in {
        frame.name for frame in traceback.extract_tb(caught.value.__traceback__)
    }


def test_replaced_staged_copy_is_rejected_before_mne_without_changing_original(
    tmp_path, monkeypatch, unicorn_source,
):
    source, settings = unicorn_source
    original = source.read_bytes()
    copy_source = unicorn_raw._copy_reader_source
    preserved_copy = tmp_path / "former-reader.bdf"
    copied_bytes = []

    def copy_then_replace(path, destination, inspection):
        receipt = copy_source(path, destination, inspection)
        before = destination.stat()
        payload = destination.read_bytes()
        copied_bytes.append(payload)
        destination.rename(preserved_copy)
        destination.write_bytes(payload)
        os.utime(destination, ns=(before.st_atime_ns, before.st_mtime_ns))
        after = destination.stat()
        assert after.st_size == before.st_size
        assert after.st_mtime_ns == before.st_mtime_ns
        assert (after.st_dev, after.st_ino) != (before.st_dev, before.st_ino)
        return receipt

    def unexpected_mne(*_args, **_kwargs):
        pytest.fail("MNE must not read a replacement for the verified staged copy.")

    monkeypatch.setattr(unicorn_raw, "_copy_reader_source", copy_then_replace)
    monkeypatch.setattr(mne.io, "read_raw_bdf", unexpected_mne)

    with pytest.raises(UnicornUnitError, match="staged Unicorn source was replaced"):
        with open_unicorn_recording_raw(
            source, settings, project_root=tmp_path, event_authority="status", preload=False,
        ):
            pytest.fail("A replaced staged copy cannot yield a recording.")

    assert source.read_bytes() == original
    assert len(copied_bytes) == 1
    assert preserved_copy.read_bytes() == copied_bytes[0]
    assert not list((tmp_path / ".fpvs_processing" / "unicorn_reader").iterdir())
