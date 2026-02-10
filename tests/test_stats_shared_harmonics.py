from __future__ import annotations

from Tools.Stats.PySide6.shared_harmonics import (
    _select_two_consecutive_significant,
    intersect_condition_harmonics,
)


def _lookup(freqs: list[float], values: list[float]) -> dict[float, float]:
    return {float(f): float(v) for f, v in zip(freqs, values)}


def test_core_two_consecutive_criterion() -> None:
    freqs = [1.2, 2.4, 3.6, 4.8, 6.0]
    z_values = [1.7, 1.8, 1.1, 2.2, 2.3]
    out = _select_two_consecutive_significant(freqs, _lookup(freqs, z_values), z_threshold=1.64)
    assert out == [1.2, 2.4, 4.8, 6.0]


def test_exclude_harmonic1_effect_via_domain() -> None:
    freqs_with_h1 = [1.2, 2.4, 3.6]
    z_values = [1.8, 1.9, 0.8]
    out_with_h1 = _select_two_consecutive_significant(
        freqs_with_h1,
        _lookup(freqs_with_h1, z_values),
        z_threshold=1.64,
    )
    assert out_with_h1 == [1.2, 2.4]

    freqs_without_h1 = [2.4, 3.6]
    out_without_h1 = _select_two_consecutive_significant(
        freqs_without_h1,
        _lookup(freqs_with_h1, z_values),
        z_threshold=1.64,
    )
    assert out_without_h1 == []


def test_condition_intersection() -> None:
    out = intersect_condition_harmonics(
        condition_harmonics_by_roi={
            "CondA": {"ROI1": [1.2, 2.4, 3.6], "ROI2": [2.4]},
            "CondB": {"ROI1": [2.4, 3.6, 4.8], "ROI2": [3.6]},
        },
        conditions=["CondA", "CondB"],
        rois=["ROI1", "ROI2"],
    )

    assert out["ROI1"] == [2.4, 3.6]
    assert out["ROI2"] == []


def test_determinism_ordering() -> None:
    freqs = [6.0, 4.8, 3.6, 2.4]
    z_values = [2.1, 2.2, 0.5, 0.4]
    out = _select_two_consecutive_significant(freqs, _lookup(freqs, z_values), z_threshold=1.64)
    assert out == sorted(out)
