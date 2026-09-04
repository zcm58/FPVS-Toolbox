from __future__ import annotations

import json
import warnings

import mne
import numpy as np
import pytest

from Main_App.io import (
    BIOSEMI64_1020_AB_CHANNEL_MAP,
    BIOSEMI64_CHANNELS,
    BIOSEMI64_CHANNEL_SET,
    BIOSEMI64_COORDINATE_FINGERPRINT,
    BIOSEMI64_GEOMETRY_VERSION,
    BIOSEMI64_MONTAGE_ID,
    BIOSEMI64_SCALP_SET_FINGERPRINT,
    BioSemi64GeometryError,
    attach_raw_biosemi64_geometry,
    biosemi64_geometry_identity,
    cached_biosemi64_montage,
    read_raw_biosemi64_geometry,
    validate_biosemi64_acquisition_channels,
    validate_raw_biosemi64_geometry,
)
from Main_App.projects.preprocessing_settings import (
    ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
    ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
)


def _acquisition_names(scalp_names=None):
    return [
        *(scalp_names or BIOSEMI64_CHANNELS),
        "EXG1",
        "EXG2",
        "EXG3",
        "Status",
    ]


def _validated(channel_names, *, profile=ELECTRODE_MAPPING_PROFILE_ANATOMICAL):
    return validate_biosemi64_acquisition_channels(
        channel_names,
        ref_pair=("EXG1", "EXG2"),
        stim_name="Status",
        electrode_mapping_profile=profile,
    )


def _raw_with_geometry():
    names = _acquisition_names()
    types = ["stim" if name == "Status" else "eeg" for name in names]
    raw = mne.io.RawArray(
        np.zeros((len(names), 16), dtype=float),
        mne.create_info(names, 256.0, types),
        verbose=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        raw.set_channel_types({"EXG1": "misc", "EXG2": "misc", "EXG3": "misc"})
    raw.set_montage(
        cached_biosemi64_montage(),
        on_missing="raise",
        match_case=True,
        verbose=False,
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        raw.set_channel_types({"EXG1": "eeg", "EXG2": "eeg"})
    return raw


def test_canonical_biosemi64_identity_has_exact_finite_mne_coordinates():
    montage = cached_biosemi64_montage()
    positions = montage.get_positions()["ch_pos"]

    assert BIOSEMI64_MONTAGE_ID == "biosemi64"
    assert BIOSEMI64_GEOMETRY_VERSION == "1.0"
    assert len(BIOSEMI64_CHANNELS) == 64
    assert tuple(montage.ch_names) == BIOSEMI64_CHANNELS
    assert set(positions) == BIOSEMI64_CHANNEL_SET
    assert all(np.isfinite(positions[name]).all() for name in BIOSEMI64_CHANNELS)
    assert BIOSEMI64_COORDINATE_FINGERPRINT.startswith("sha256:")
    assert BIOSEMI64_SCALP_SET_FINGERPRINT.startswith("sha256:")

    identity = biosemi64_geometry_identity()
    assert identity["canonical_scalp_channel_count"] == 64
    assert identity["retained_scalp_channels"] == list(BIOSEMI64_CHANNELS)
    assert identity["electrode_mapping_profile"] == "anatomical_labels"
    json.dumps(identity)


def test_anatomical_labels_resolve_by_name_and_first_n_is_canonical_and_source_ordered():
    reordered_scalp = list(reversed(BIOSEMI64_CHANNELS))
    geometry = _validated(_acquisition_names(reordered_scalp))

    assert geometry.scalp_canonical_names == tuple(reordered_scalp)
    assert geometry.retained_scalp_names(3) == BIOSEMI64_CHANNELS[:3]
    assert geometry.included_source_names(3) == [
        "AF3",
        "AF7",
        "Fp1",
        "EXG1",
        "EXG2",
        "Status",
    ]


def test_ab_labels_require_explicit_1020_profile_and_map_by_label():
    ab_names = list(reversed(tuple(BIOSEMI64_1020_AB_CHANNEL_MAP)))

    with pytest.raises(BioSemi64GeometryError, match="Select the tested"):
        _validated(_acquisition_names(ab_names))

    geometry = _validated(
        _acquisition_names(ab_names),
        profile=ELECTRODE_MAPPING_PROFILE_BIOSEMI64_1020_AB_V1,
    )
    mapping = geometry.source_to_canonical
    assert mapping["A1"] == "Fp1"
    assert mapping["A32"] == "CPz"
    assert mapping["B1"] == "Fpz"
    assert mapping["B16"] == "Cz"
    assert mapping["B32"] == "O2"
    assert geometry.retained_scalp_names(4) == BIOSEMI64_CHANNELS[:4]
    assert geometry.included_source_names(4)[:4] == ["A4", "A3", "A2", "A1"]


@pytest.mark.parametrize(
    ("channel_names", "message"),
    [
        (_acquisition_names(BIOSEMI64_CHANNELS[:-1]), "exact 64-channel"),
        (_acquisition_names([*BIOSEMI64_CHANNELS, "Fp1"]), "duplicate"),
        ([*_acquisition_names(), "EEG65"], "unsupported or custom"),
        ([*_acquisition_names(), "CMS"], "not recorded data channels"),
        ([*_acquisition_names(), "DRL"], "not recorded data channels"),
    ],
)
def test_acquisition_validation_rejects_missing_duplicate_custom_and_cms_drl(
    channel_names,
    message,
):
    with pytest.raises(BioSemi64GeometryError, match=message):
        _validated(channel_names)


def test_runtime_identity_validates_scalp_coordinates_refs_and_stim_and_survives_copy():
    raw = _raw_with_geometry()
    identity = attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile=ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
        retained_channels=BIOSEMI64_CHANNELS,
        reference_channels=("EXG1", "EXG2"),
        stim_channel="Status",
    )

    validated = validate_raw_biosemi64_geometry(
        raw,
        require_full=True,
        reference_channels=("EXG1", "EXG2"),
        stim_channel="Status",
    )
    assert validated == identity
    assert np.isnan(raw.info["chs"][raw.ch_names.index("EXG1")]["loc"]).all()
    assert np.isnan(raw.info["chs"][raw.ch_names.index("EXG2")]["loc"]).all()
    assert raw.get_channel_types(picks=["Status"]) == ["stim"]
    assert read_raw_biosemi64_geometry(raw.copy()) == identity

    detached = read_raw_biosemi64_geometry(raw)
    detached["retained_scalp_channels"].clear()
    assert read_raw_biosemi64_geometry(raw)["retained_scalp_channel_count"] == 64


def test_runtime_validation_rejects_nonfinite_scalp_coordinate():
    raw = _raw_with_geometry()
    raw.info["chs"][raw.ch_names.index("Fp1")]["loc"][:3] = np.nan

    with pytest.raises(BioSemi64GeometryError, match="no finite BioSemi64 coordinate"):
        attach_raw_biosemi64_geometry(
            raw,
            electrode_mapping_profile=ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
            retained_channels=BIOSEMI64_CHANNELS,
            reference_channels=("EXG1", "EXG2"),
            stim_channel="Status",
        )


def test_runtime_attachment_rejects_legacy_standard_1005_coordinates():
    raw = mne.io.RawArray(
        np.zeros((64, 16), dtype=float),
        mne.create_info(list(BIOSEMI64_CHANNELS), 256.0, "eeg"),
        verbose=False,
    )
    raw.set_montage(
        mne.channels.make_standard_montage("standard_1005"),
        on_missing="raise",
        match_case=True,
        verbose=False,
    )

    with pytest.raises(BioSemi64GeometryError, match="does not match canonical BioSemi64"):
        attach_raw_biosemi64_geometry(
            raw,
            electrode_mapping_profile=ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
            retained_channels=BIOSEMI64_CHANNELS,
        )


def test_runtime_validation_rejects_unknown_eeg_channel():
    raw = _raw_with_geometry()
    raw.add_channels(
        [
            mne.io.RawArray(
                np.zeros((1, raw.n_times), dtype=float),
                mne.create_info(["CustomEEG"], raw.info["sfreq"], "eeg"),
                verbose=False,
            )
        ],
        force_update_info=True,
    )

    with pytest.raises(BioSemi64GeometryError, match="unsupported non-BioSemi64 EEG"):
        attach_raw_biosemi64_geometry(
            raw,
            electrode_mapping_profile=ELECTRODE_MAPPING_PROFILE_ANATOMICAL,
            retained_channels=BIOSEMI64_CHANNELS,
            reference_channels=("EXG1", "EXG2"),
            stim_channel="Status",
        )
