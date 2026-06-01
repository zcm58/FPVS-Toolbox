from __future__ import annotations

from tests import repo_root


def test_legacy_stats_ui_active_namespace_removed() -> None:
    root = repo_root()
    active_legacy_root = root / "src" / "Tools" / "Stats" / ("Leg" + "acy")

    assert not active_legacy_root.exists()
