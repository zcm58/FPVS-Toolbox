from __future__ import annotations

import hashlib

import numpy as np
import pytest

from Main_App.io.acticap_montages import make_acticap_montage


# Reference digests come independently from the numbered sites in the vendor's
# CACS-{64,128}_{REF,NO_REF}.bvef files, passed through MNE's BrainVision
# spherical-to-Cartesian conversion and rounded to integer nanometres.
@pytest.mark.parametrize(
    "count, recorded_fcz, expected_digest",
    [
        (64, False, "37e0a9592e353d857154b571b7649d761812812d351750305e0a208e63a43d4f"),
        (64, True, "4706adc9c0d58a5b40d2201ed12c75f8a82196564446f514c4e023796a25d5de"),
        (128, False, "5ea80e8423e3324b58be8982e43412b10fee466b226303d3bb27cb6010e338da"),
        (128, True, "0613c3e48cad50f962b6c1b3df5240cd982c50b0c768a31cc3c8fb8371a55d8c"),
    ],
)
def test_named_scalp_sites_match_vendor_bvef(count, recorded_fcz, expected_digest):
    montage = make_acticap_montage(f"brainproducts_acticap_gacs_{count}", recorded_fcz=recorded_fcz)
    assert len(montage.ch_names) == count
    assert montage.ch_names[63] == ("FCz" if recorded_fcz else "Iz")
    assert not {"REF", "GND"}.intersection(montage.ch_names)

    positions = montage.get_positions()
    assert positions["coord_frame"] == "head"
    coords = positions["ch_pos"]
    np.testing.assert_allclose(coords["T7"], [-0.095, 0, 0], atol=1e-12)
    np.testing.assert_allclose(coords["Oz"], [0, -0.095, 0], atol=1e-12)
    np.testing.assert_allclose(coords["Cz"], [0, 0, 0.095], atol=1e-12)
    rows = []
    for name in montage.ch_names:
        x, y, z = np.rint(1e9 * coords[name]).astype(int)
        rows.append(f"{name} {x} {y} {z}\n")
    assert hashlib.sha256("".join(rows).encode("ascii")).hexdigest() == expected_digest


def test_unsupported_acticap_model_is_rejected():
    with pytest.raises(ValueError, match="Unknown actiCAP GACS montage"):
        make_acticap_montage("brainproducts_acticap_gacs_96")
