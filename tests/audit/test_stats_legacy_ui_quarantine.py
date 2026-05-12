from __future__ import annotations

from tests import repo_root


def test_legacy_stats_ui_reference_source_is_quarantined_only() -> None:
    root = repo_root()
    quarantine_root = root / "src" / "quarantine" / "Tools" / "Stats" / "Legacy_UI"
    active_legacy_root = root / "src" / "Tools" / "Stats" / ("Leg" + "acy")

    assert not active_legacy_root.exists()
    assert (quarantine_root / "stats.py").is_file()
    assert (quarantine_root / "stats_ui.py").is_file()
