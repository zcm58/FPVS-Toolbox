from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from Tools.Stats.ui.stats_window_pipeline import StatsWindowPipelineMixin


def test_managed_stats_uses_accepted_project_base_rate(tmp_path: Path) -> None:
    manifest_path = tmp_path / "project.json"
    manifest_path.write_text("{}", encoding="utf-8")

    class _Host:
        _canonical_harmonic_selection = SimpleNamespace(
            metadata={"base_frequency_hz": 3.0}
        )

        @staticmethod
        def _project_manifest_path() -> Path:
            return manifest_path

        @staticmethod
        def _safe_settings_get(section: str, key: str, default):
            assert (section, key) == ("analysis", "alpha")
            return True, 0.05

        @staticmethod
        def _load_canonical_harmonic_selection():
            raise AssertionError("cached canonical selection should be used")

    assert StatsWindowPipelineMixin._get_analysis_settings(_Host()) == (3.0, 0.05)
