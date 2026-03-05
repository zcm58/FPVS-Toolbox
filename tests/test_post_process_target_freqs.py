from __future__ import annotations

from types import SimpleNamespace

import pytest

from Main_App.Legacy_App.post_process import _resolve_target_frequencies


def test_resolve_target_frequencies_from_nested_analysis_dict() -> None:
    app = SimpleNamespace(
        settings={"analysis": {"oddball_freq": 1.2, "bca_upper_limit": 24.0}}
    )

    freqs, upper = _resolve_target_frequencies(app)

    assert upper == pytest.approx(24.0)
    assert float(freqs[0]) == pytest.approx(1.2)
    assert float(freqs[-1]) == pytest.approx(24.0)
    assert len(freqs) == 20


def test_resolve_target_frequencies_from_settings_getter() -> None:
    class _FakeSettings:
        def get(self, section, option, fallback=None):
            if section == "analysis" and option == "oddball_freq":
                return "1.2"
            if section == "analysis" and option == "bca_upper_limit":
                return "19.2"
            return fallback

    app = SimpleNamespace(settings=_FakeSettings())

    freqs, upper = _resolve_target_frequencies(app)

    assert upper == pytest.approx(19.2)
    assert float(freqs[-1]) == pytest.approx(19.2)
    assert len(freqs) == 16
