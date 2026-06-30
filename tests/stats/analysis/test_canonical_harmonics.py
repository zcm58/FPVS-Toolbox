from __future__ import annotations

from Tools.Stats.analysis import canonical_harmonics
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CanonicalHarmonicSelectionError,
    select_canonical_group_harmonics,
)


class _FakeGroupSelection:
    def to_metadata(self) -> dict[str, object]:
        return {
            "harmonic_policy": "group_level_significant_harmonics",
            "harmonic_policy_label": "Group-level significant oddball harmonics",
            "selection_subjects": ["P1", "P2"],
            "selection_conditions": ["CondA", "CondB"],
            "electrode_scope": "union_roi_electrodes",
            "summation_method": "through_highest_significant",
            "z_threshold": 1.64,
            "base_frequency_hz": 6.0,
            "oddball_frequency_hz": 1.2,
            "selected_harmonics_hz": [1.2, 2.4, 3.6],
            "detected_significant_harmonics_hz": [1.2, 3.6],
            "selection_cache_source": "computed_this_run_saved_project_metadata",
        }


def test_select_canonical_group_harmonics_returns_shared_fingerprint(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_build_group_significant_harmonic_selection(**kwargs):
        captured.update(kwargs)
        return _FakeGroupSelection()

    monkeypatch.setattr(
        canonical_harmonics,
        "build_group_significant_harmonic_selection",
        fake_build_group_significant_harmonic_selection,
    )

    result = select_canonical_group_harmonics(
        subjects=["P1", "P2"],
        conditions=["CondA", "CondB"],
        subject_data={
            "P1": {"CondA": "p1a.xlsx", "CondB": "p1b.xlsx"},
            "P2": {"CondA": "p2a.xlsx", "CondB": "p2b.xlsx"},
        },
        base_frequency_hz=6.0,
        rois={"LOT": ["P7", "PO7"]},
        log_func=lambda _message: None,
        max_freq=16.8,
        project_root=None,
    )

    assert result.source == CANONICAL_HARMONIC_SOURCE
    assert result.selected_harmonics_hz == (1.2, 2.4, 3.6)
    assert result.exploratory is False
    assert result.fingerprint["selected_harmonics_hz"] == [1.2, 2.4, 3.6]
    assert result.fingerprint["detected_significant_harmonics_hz"] == [1.2, 3.6]
    assert "FPVS Toolbox significant harmonics" in result.fingerprint_text
    assert "selected: 1.2, 2.4, 3.6 Hz" in result.fingerprint_text
    assert captured["rois"] == {"LOT": ["P7", "PO7"]}


def test_select_canonical_group_harmonics_rewrites_no_selection_error(monkeypatch) -> None:
    def fake_build_group_significant_harmonic_selection(**_kwargs):
        raise RuntimeError(
            "Group-level significant harmonic selection found no oddball harmonics above z>1.64."
        )

    monkeypatch.setattr(
        canonical_harmonics,
        "build_group_significant_harmonic_selection",
        fake_build_group_significant_harmonic_selection,
    )

    try:
        select_canonical_group_harmonics(
            subjects=["P1"],
            conditions=["CondA"],
            subject_data={"P1": {"CondA": "p1a.xlsx"}},
            base_frequency_hz=6.0,
            rois={},
            log_func=lambda _message: None,
        )
    except CanonicalHarmonicSelectionError as exc:
        assert exc.reason == "no_significant_harmonics"
        assert "No group-level significant harmonics were found" in str(exc)
        assert "exploratory fixed-list check" in str(exc)
    else:
        raise AssertionError("Expected CanonicalHarmonicSelectionError")
