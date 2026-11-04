from __future__ import annotations

from types import SimpleNamespace

import pytest

from Tools.LORETA_Visualizer.source_producers import project_source_psd_inputs as inputs


@pytest.mark.parametrize(
    ("metadata", "expected"),
    [({"same_sample_adaptive": True}, True), ({"exploratory": True}, True),
     ({"same_sample_adaptive": False, "exploratory": False}, False)],
)
def test_source_adapter_preserves_selection_qualification(monkeypatch, metadata, expected) -> None:
    selection = SimpleNamespace(selected_harmonics_hz=(1.2, 2.4), to_metadata=lambda: dict(metadata))
    monkeypatch.setattr(inputs, "load_processing_harmonic_selection", lambda *args, **kwargs: selection)
    harmonics, resolved = inputs._resolve_selected_harmonics(
        object(), selected_harmonics_hz=None, progress_callback=None,
    )
    assert harmonics == (1.2, 2.4)
    assert resolved["exploratory"] is expected
    assert resolved["source"] == "saved_processing_harmonics"
