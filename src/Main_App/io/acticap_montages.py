"""Nominal Brain Products actiCAP slim/snap GACS scalp coordinates.

The GACS archive at https://www.brainproducts.com/downloads/cap-montages/
supplies CACS-64 and CACS-128 BVEF files for the REF and NO_REF wiring.
The numbered positions also match the corresponding ASPG and CACS/CAS files.
Numbered sites below follow acquisition order. Values are the vendor's signed
polar angle (theta) and azimuth (phi) in degrees on its idealized unit sphere.
"""

from __future__ import annotations

from math import cos, radians, sin
from typing import TYPE_CHECKING

from Main_App.projects.hardware import ACTICAP_GACS_64, ACTICAP_GACS_128

if TYPE_CHECKING:
    from mne.channels import DigMontage


_CHANNEL_COUNTS = {
    ACTICAP_GACS_64: 64,
    ACTICAP_GACS_128: 128,
}

# The first 64 numbered sites are identical across the two cap densities.
_REF_SITES = (
    ("Fp1", -90, -72),
    ("Fz", 45, 90),
    ("F3", -60, -51),
    ("F7", -90, -36),
    ("FT9", -113, -18),
    ("FC5", -69, -22),
    ("FC1", -31, -46),
    ("C3", -45, 0),
    ("T7", -90, 0),
    ("TP9", -113, 18),
    ("CP5", -69, 21),
    ("CP1", -31, 46),
    ("Pz", 45, -90),
    ("P3", -60, 51),
    ("P7", -90, 36),
    ("O1", -90, 72),
    ("Oz", 90, -90),
    ("O2", 90, -72),
    ("P4", 60, -51),
    ("P8", 90, -36),
    ("TP10", 113, -18),
    ("CP6", 69, -21),
    ("CP2", 31, -46),
    ("Cz", 0, 0),
    ("C4", 45, 0),
    ("T8", 90, 0),
    ("FT10", 113, 18),
    ("FC6", 69, 21),
    ("FC2", 31, 46),
    ("F4", 60, 51),
    ("F8", 90, 36),
    ("Fp2", 90, 72),
    ("AF7", -90, -54),
    ("AF3", -74, -68),
    ("AFz", 67, 90),
    ("F1", -49, -68),
    ("F5", -74, -41),
    ("FT7", -90, -18),
    ("FC3", -49, -29),
    ("C1", -23, 0),
    ("C5", -68, 0),
    ("TP7", -90, 18),
    ("CP3", -49, 29),
    ("P1", -49, 68),
    ("P5", -74, 41),
    ("PO7", -90, 54),
    ("PO3", -74, 68),
    ("POz", 67, -90),
    ("PO4", 74, -68),
    ("PO8", 90, -54),
    ("P6", 74, -41),
    ("P2", 49, -68),
    ("CPz", 22, -90),
    ("CP4", 49, -29),
    ("TP8", 90, -18),
    ("C6", 68, 0),
    ("C2", 23, 0),
    ("FC4", 49, 29),
    ("FT8", 90, 18),
    ("F6", 74, 41),
    ("AF8", 90, 54),
    ("AF4", 74, 68),
    ("F2", 49, 68),
    ("Iz", 112, -90),
    ("F9", -113, -36),
    ("AFF1h", -57, -82),
    ("FFC1h", -35, -73),
    ("FFC5h", -62, -35),
    ("FTT7h", -79, -10),
    ("FCC3h", -35, -19),
    ("CCP1h", -16, 45),
    ("CCP5h", -57, 12),
    ("TPP7h", -81, 29),
    ("P9", -113, 36),
    ("PPO9h", -101, 45),
    ("PO9", -113, 54),
    ("O9", -112, 72),
    ("OI1h", -101, 81),
    ("PPO1h", -57, 82),
    ("CPP3h", -46, 48),
    ("CPP4h", 46, -48),
    ("PPO2h", 57, -82),
    ("OI2h", 101, -81),
    ("O10", 112, -72),
    ("PO10", 113, -54),
    ("PPO10h", 101, -45),
    ("P10", 113, -36),
    ("TPP8h", 81, -29),
    ("CCP6h", 57, -12),
    ("CCP2h", 16, -45),
    ("FCC4h", 35, 19),
    ("FTT8h", 79, 10),
    ("FFC6h", 62, 35),
    ("FFC2h", 35, 73),
    ("AFF2h", 57, 82),
    ("F10", 113, 36),
    ("AFp1", -79, -82),
    ("AFF5h", -72, -55),
    ("FFT9h", -101, -27),
    ("FFT7h", -81, -29),
    ("FFC3h", -46, -48),
    ("FCC1h", -16, -45),
    ("FCC5h", -57, -12),
    ("FTT9h", -101, -9),
    ("TTP7h", -79, 10),
    ("CCP3h", -35, 19),
    ("CPP1h", -35, 73),
    ("CPP5h", -62, 35),
    ("TPP9h", -101, 27),
    ("POO9h", -101, 63),
    ("PPO5h", -72, 55),
    ("POO1", -79, 82),
    ("POO2", 79, -82),
    ("PPO6h", 72, -55),
    ("POO10h", 101, -63),
    ("TPP10h", 101, -27),
    ("CPP6h", 62, -35),
    ("CPP2h", 35, -73),
    ("CCP4h", 35, -19),
    ("TTP8h", 79, -10),
    ("FTT10h", 101, 9),
    ("FCC6h", 57, 12),
    ("FCC2h", 16, 45),
    ("FFC4h", 46, 48),
    ("FFT8h", 81, 29),
    ("FFT10h", 101, 27),
    ("AFF6h", 72, 55),
    ("AFp2", 79, 82),
)


def make_acticap_montage(montage_id: str, *, recorded_fcz: bool = False) -> DigMontage:
    """Build the named cap using its verified Iz or FCz channel-64 wiring."""
    from mne.channels import make_dig_montage

    try:
        count = _CHANNEL_COUNTS[montage_id]
    except KeyError as exc:
        raise ValueError(f"Unknown actiCAP GACS montage: {montage_id!r}.") from exc

    # MNE interprets an idealized BrainVision radius of 1 as 95 mm in head
    # coordinates. The BVEF separates numbered EEG from physical GND and REF.
    radius = 0.095
    positions = {}
    for name, theta, phi in _REF_SITES[:count]:
        if recorded_fcz and name == "Iz":
            name, theta, phi = "FCz", 23, 90
        polar = radians(theta)
        azimuth = radians(phi)
        xy = radius * sin(polar)
        positions[name] = (xy * cos(azimuth), xy * sin(azimuth), radius * cos(polar))
    return make_dig_montage(ch_pos=positions, coord_frame="head")
