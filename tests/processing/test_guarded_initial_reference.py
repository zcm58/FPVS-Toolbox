from dataclasses import replace

import mne
import numpy as np
import pytest

from Main_App.io.acquisition_metadata import resolve_recording_contract
from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS
from Main_App.io.load_utils import load_eeg_file
from Main_App.processing import guarded_initial_reference
from tests.processing.test_shared_load_utils import _app, _write_sampling_bdf


pytestmark = [
    pytest.mark.processing,
    pytest.mark.skipif(
        not guarded_initial_reference._supported_runtime(),
        reason="Exact reference arithmetic is qualified on the pinned runtime.",
    ),
]


def _load_bdf(tmp_path, *, preload_ram, reference_pair):
    path = tmp_path / "reference.bdf"
    labels = (
        "EXG1", *BIOSEMI64_CHANNELS[:31], "EXG3", *BIOSEMI64_CHANNELS[31:], "EXG2", "Status"
    )
    _write_sampling_bdf(path, labels=labels, samples=(151,) * len(labels))
    raw = load_eeg_file(
        _app([], tmp_path),
        str(path),
        ref_pair=reference_pair,
        preload_in_memory=preload_ram,
        preload_path=None if preload_ram else tmp_path / "preload.dat",
        raise_on_error=True,
    )
    assert raw is not None
    data = raw._data
    data[:-1] = np.random.default_rng(731).normal(size=data[:-1].shape) * 1e-6
    data[raw.ch_names.index("EXG1"), :4] = -0.0, 0.0, 1e-300, 1e-6
    data[raw.ch_names.index("EXG2"), :4] = -0.0, -0.0, -1e-300, -1e-6
    data[-1, ::11] = 55
    policy = resolve_recording_contract(
        {"ref_channel1": reference_pair[0], "ref_channel2": reference_pair[1]},
        raw=raw,
    )
    return raw, policy


@pytest.mark.parametrize("preload_ram", [True, False])
@pytest.mark.parametrize("bad_channels", [[], ["EXG2", "Fp1", "Pz"]])
def test_bounded_reference_matches_native_bits_and_metadata(tmp_path, monkeypatch, preload_ram, bad_channels):
    reference_pair = ("EXG2", "EXG1")
    raw, policy = _load_bdf(tmp_path, preload_ram=preload_ram, reference_pair=reference_pair)
    with raw:
        assert isinstance(raw._data, np.memmap) == (not preload_ram)
        raw.info["bads"] = bad_channels
        with raw.copy() as expected:
            expected.set_eeg_reference(ref_channels=list(reference_pair), projection=False, verbose=False)
            monkeypatch.setattr(guarded_initial_reference, "_REFERENCE_BLOCK_SAMPLES", 17)
            storage = raw._data

            assert guarded_initial_reference.try_bounded_initial_reference(raw, reference_pair, policy)

            assert raw._data is storage
            assert raw._data.tobytes() == expected._data.tobytes()
            assert mne.utils.object_diff(raw.info, expected.info) == ""
            assert raw._projector is expected._projector is None
            assert raw.annotations == expected.annotations


@pytest.mark.parametrize("unsupported", ["projectors", "runtime", "geometry", "nonfinite_reference"])
def test_bounded_reference_declines_before_mutation(tmp_path, monkeypatch, unsupported):
    reference_pair = ("EXG1", "EXG2")
    raw, policy = _load_bdf(tmp_path, preload_ram=True, reference_pair=reference_pair)
    with raw:
        if unsupported == "projectors":
            raw.set_eeg_reference(ref_channels="average", projection=True, verbose=False)
        elif unsupported == "runtime":
            monkeypatch.setattr(guarded_initial_reference, "_supported_runtime", lambda: False)
        elif unsupported == "geometry":
            policy = replace(policy, geometry_json="")
        else:
            raw._data[raw.ch_names.index("EXG1"), 0] = np.nan
        with raw.copy() as unchanged:
            assert not guarded_initial_reference.try_bounded_initial_reference(raw, reference_pair, policy)
            assert raw._data.tobytes() == unchanged._data.tobytes()
            assert mne.utils.object_diff(raw.info, unchanged.info) == ""
