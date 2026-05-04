from __future__ import annotations

from pathlib import Path


def test_legacy_stats_ui_reference_source_is_quarantined_only() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    quarantine_root = repo_root / "src" / "quarantine" / "Tools" / "Stats" / "Legacy_UI"
    active_legacy_root = repo_root / "src" / "Tools" / "Stats" / "Legacy"

    assert not active_legacy_root.exists()
    assert (quarantine_root / "stats.py").is_file()
    assert (quarantine_root / "stats_ui.py").is_file()
