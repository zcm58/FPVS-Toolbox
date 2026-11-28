import mne
import numpy as np
import pytest

from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry


@pytest.fixture(scope="module")
def hydrocel_geometry():
    """Four synthetic HydroCel channels with explicit template coordinates in metres."""
    from Tools.Publication_Maps.scalp_io import recorded_map_geometry

    channels = ["E4", "E12", "E20", "E29"]
    raw = mne.io.RawArray(np.zeros((4, 4)), mne.create_info(channels, 100, "eeg"), verbose=False)
    identity = attach_raw_recorded_geometry(
        raw, montage_id="GSN-HydroCel-32", template_montage="GSN-HydroCel-32", hardware_platform="egi",
    )
    return recorded_map_geometry(identity, source_id="synthetic-recording")
