from __future__ import annotations

from pathlib import Path

from Main_App.processing import harmonic_selection_qc
from Tools.Stats.analysis.canonical_harmonics import (
    CANONICAL_HARMONIC_SOURCE,
    CanonicalHarmonicSelectionError,
    load_project_processing_harmonics,
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
            "selection_cache_source": "saved_processing_metadata",
        }


def test_load_project_processing_harmonics_returns_shared_fingerprint(
    tmp_path: Path,
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_load_processing_harmonic_selection(project, *, log_func):
        captured["project_root"] = project.project_root
        captured["log_func"] = log_func
        return _FakeGroupSelection()

    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_processing_harmonic_selection",
        fake_load_processing_harmonic_selection,
    )

    result = load_project_processing_harmonics(
        project_root=tmp_path,
        log_func=lambda _message: None,
    )

    assert result.source == CANONICAL_HARMONIC_SOURCE
    assert result.selected_harmonics_hz == (1.2, 2.4, 3.6)
    assert result.exploratory is False
    assert result.fingerprint["selected_harmonics_hz"] == [1.2, 2.4, 3.6]
    assert result.fingerprint["detected_significant_harmonics_hz"] == [1.2, 3.6]
    assert "FPVS Toolbox significant harmonics" in result.fingerprint_text
    assert "selected: 1.2, 2.4, 3.6 Hz" in result.fingerprint_text
    assert captured["project_root"] == tmp_path.resolve()


def test_load_project_processing_harmonics_reports_missing_cache(
    tmp_path: Path,
    monkeypatch,
) -> None:
    def fake_load_processing_harmonic_selection(_project, *, log_func):
        _ = log_func
        raise RuntimeError("No current processing-time significant-harmonic selection is available.")

    monkeypatch.setattr(
        harmonic_selection_qc,
        "load_processing_harmonic_selection",
        fake_load_processing_harmonic_selection,
    )

    try:
        load_project_processing_harmonics(
            project_root=tmp_path,
            log_func=lambda _message: None,
        )
    except CanonicalHarmonicSelectionError as exc:
        assert exc.reason == "missing_processing_selection"
        assert "No current processing-time significant-harmonic selection" in str(exc)
    else:
        raise AssertionError("Expected CanonicalHarmonicSelectionError")
