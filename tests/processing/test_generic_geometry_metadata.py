"""Upstream geometry metadata preserves existing identities and rejects drift."""

from copy import deepcopy

import mne
import numpy as np
import pytest

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS, biosemi64_geometry_identity
from Main_App.io.geometry_metadata import (
    configured_geometry_identity,
    project_spectral_geometry,
    validate_source_geometry_identity,
)
from Main_App.io.hardware_identity import brain_products_settings_identity
from Main_App.io.recorded_eeg_geometry import attach_raw_recorded_geometry


@pytest.mark.parametrize("limit", [None, 20, 64])
def test_fixed_configuration_preserves_historical_identity(limit):
    settings = {"max_idx_keep": limit, "electrode_mapping_profile": "anatomical_labels"}
    expected = biosemi64_geometry_identity(retained_channels=BIOSEMI64_CHANNELS[:limit])
    assert configured_geometry_identity(settings) == expected
    assert validate_source_geometry_identity(expected) == expected


def test_recorded_configuration_and_observed_identity_stay_separate():
    settings = {
        "hardware_platform": "brain_products", "hardware_confirmed": True,
        "electrode_montage": "recorded", "initial_reference": "recorded",
    }
    names = ["Fp1", "Fp2", "O1", "O2"]
    raw = mne.io.RawArray(np.zeros((4, 10)), mne.create_info(names, 100, "eeg"), verbose=False)
    geometry = attach_raw_recorded_geometry(raw)
    metadata = project_spectral_geometry(settings)
    assert configured_geometry_identity(settings) == brain_products_settings_identity(settings)
    assert metadata.per_recording and metadata.fixed_geometry is None
    assert metadata.matches_source(geometry)
    assert validate_source_geometry_identity(geometry) == geometry
    changed = {**geometry, "montage_id": "another-template"}
    assert not metadata.matches_source(changed)


@pytest.mark.parametrize("field", ["geometry_version", "coordinate_fingerprint", "geometry_identity_fingerprint"])
def test_unknown_or_tampered_identity_is_rejected(field):
    geometry = deepcopy(biosemi64_geometry_identity())
    geometry[field] = "unrecognized"
    with pytest.raises(ValueError):
        validate_source_geometry_identity(geometry)


def test_unknown_platform_cannot_reuse_default_geometry():
    with pytest.raises(ValueError, match="Unsupported EEG hardware"):
        configured_geometry_identity({"hardware_platform": "unknown"})
