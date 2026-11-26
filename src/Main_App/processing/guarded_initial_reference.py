"""Bound the data copy for the qualified BioSemi64 initial reference pair."""

from __future__ import annotations

from itertools import groupby
from operator import itemgetter
import sys

import mne
from mne.io.edf.edf import RawEDF
import numpy as np

from Main_App.io.eeg_geometry import (
    BIOSEMI64_MONTAGE_ID,
    read_raw_biosemi64_geometry,
)
from Main_App.io.recording_contract import RecordingContract


_REFERENCE_BLOCK_SAMPLES = 65_536
_NATIVE_SET_REFERENCE = RawEDF.set_eeg_reference
# Even a finite sample at the float64 limit cannot overflow when subtracting
# a reference this small. Acquisition data are far below this bound.
_REFERENCE_ABS_LIMIT = np.finfo(np.float64).max / 2**54


def _supported_runtime() -> bool:
    return (
        sys.implementation.name == "cpython"
        and sys.version_info[:2] == (3, 13)
        and mne.__version__ == "1.9.0"
        and np.__version__ == "2.3.1"
    )


def try_bounded_initial_reference(
    raw: mne.io.BaseRaw,
    reference_pair: tuple[str, str],
    policy: RecordingContract,
) -> bool:
    """Apply the MNE pair arithmetic in blocks, or leave Raw unchanged."""
    if (
        not _supported_runtime()
        or type(raw) is not RawEDF
        or type(raw).set_eeg_reference is not _NATIVE_SET_REFERENCE
        or "set_eeg_reference" in vars(raw)
        or not raw.preload
        or raw.info["projs"]
        or policy.initial_reference_mode != "legacy_pair"
        or policy.recorded_channel_geometry
        or policy.montage_id != BIOSEMI64_MONTAGE_ID
        or not policy.geometry_json
        or reference_pair != policy.initial_reference_channels
        or reference_pair[0] == reference_pair[1]
        or any(name not in raw.ch_names for name in reference_pair)
        or read_raw_biosemi64_geometry(raw) != policy.geometry
        or np.geterr() != {"divide": "warn", "over": "warn", "under": "ignore", "invalid": "warn"}
    ):
        return False

    storage = raw._data
    if (
        type(storage) not in (np.ndarray, np.memmap)
        or storage.dtype != np.float64
        or storage.shape != (len(raw.ch_names), raw.n_times)
        or raw.n_times == 0
        or not (storage.flags.c_contiguous and storage.flags.aligned and storage.flags.writeable)
    ):
        return False
    data = np.asarray(storage)
    references = mne.pick_channels(raw.ch_names, list(reference_pair), ordered=True)
    eeg = mne.pick_types(raw.info, meg=False, eeg=True, ref_meg=False, exclude=[])
    if not np.isin(references, eeg).all():
        return False
    targets = mne.pick_types(raw.info, meg=False, eeg=True, ref_meg=False)
    if not targets.size:
        return False
    for row in references:
        if not -_REFERENCE_ABS_LIMIT <= data[row].min() <= data[row].max() <= _REFERENCE_ABS_LIMIT:
            return False

    target_slices = []
    for _, group in groupby(enumerate(targets.tolist()), lambda pair: pair[1] - pair[0]):
        consecutive = list(map(itemgetter(1), group))
        target_slices.append(slice(consecutive[0], consecutive[-1] + 1))

    # MNE handles the reference metadata and checks, as for the explicit pair.
    # With no SSPs the empty pair changes no samples and sets the same metadata.
    raw.set_eeg_reference(ref_channels=[], projection=False, verbose=False)
    for start in range(0, raw.n_times, _REFERENCE_BLOCK_SAMPLES):
        stop = start + _REFERENCE_BLOCK_SAMPLES
        # Evaluate both references before writing any target, including the
        # reference channels that are also good EEG targets.
        reference = data[references, start:stop].mean(axis=0)
        for rows in target_slices:
            block = data[rows, start:stop]
            np.subtract(block, reference, out=block)
    return True
