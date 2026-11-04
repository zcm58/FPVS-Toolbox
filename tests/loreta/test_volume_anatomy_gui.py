"""Volume backdrop preferences must stay outside source-map refresh paths."""

from types import MethodType, SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer import gui


def _unexpected(*_args, **_kwargs):
    pytest.fail("Backdrop changes reached a source, scale or camera refresh")


def test_backdrop_toggle_updates_both_panes_without_reapplying_payloads():
    calls = []

    def renderer(name):
        return SimpleNamespace(
            set_volume_smooth_shell_enabled=lambda value: calls.append((name, value)),
            set_activation_payload=_unexpected, reset_camera=_unexpected,
            set_activation_scalar_range=_unexpected,
        )

    host = SimpleNamespace(
        renderer=renderer("left"), _comparison_renderer=renderer("right"),
        _volume_smooth_shell_enabled=False,
    )
    change = gui.LoretaVisualizerWindow._set_volume_smooth_shell_enabled
    change(host, False)
    change(host, True)
    change(host, True)
    change(host, False)
    assert calls == [("left", True), ("right", True), ("left", False), ("right", False)]
    assert host._volume_smooth_shell_enabled is False


@pytest.mark.parametrize("available", [False, True])
def test_options_close_changes_only_backdrop_and_reopens_with_same_preference(monkeypatch, available):
    calls, options = [], []
    source_values = np.array([2., np.nan, 4.])
    payload = SimpleNamespace(values=source_values, metadata={"cluster_mask_source_indices": [0, 2]})
    backdrop = SimpleNamespace(
        current_brain_mesh=lambda: SimpleNamespace(volume_context=object() if available else None),
        set_volume_smooth_shell_enabled=calls.append,
    )
    host = SimpleNamespace(
        renderer=backdrop, _comparison_renderer=None, _volume_smooth_shell_enabled=False,
        _include_flagged_subjects=False, _zscore_display_threshold=1.64,
        _use_cluster_mask=True, _activation_visible=True, _transparent_spin_enabled=False,
        _l2_source_orientation_mode="cortical_normal", _project=None,
        _source_export_thread=None, _stats_ready_export_thread=None, _source_export_worker=None,
        _refresh_project_root=lambda: None, _source_activation_payload=payload,
        _current_activation_payload=payload, _set_zscore_display_threshold=_unexpected,
        _set_cluster_mask_enabled=_unexpected, _set_activation_visibility_enabled=_unexpected,
        _set_transparent_spin_enabled=_unexpected, _refresh_current_activation=_unexpected,
        _apply_activation_scalar_range=_unexpected,
    )
    host._set_volume_smooth_shell_enabled = MethodType(gui.LoretaVisualizerWindow._set_volume_smooth_shell_enabled, host)

    def dialog(_parent, **kwargs):
        options.append(kwargs)
        return SimpleNamespace(
            # This options dialog applies its controls on Close, as before.
            exec=lambda: 0, selected_action=None,
            include_flagged_check=SimpleNamespace(isChecked=lambda: False),
            source_orientation_combo=SimpleNamespace(currentData=lambda: "cortical_normal"),
            zscore_threshold_spin=SimpleNamespace(value=lambda: 1.64),
            use_cluster_mask_check=SimpleNamespace(isChecked=lambda: True),
            source_map_visible_check=SimpleNamespace(isChecked=lambda: True),
            transparent_spin_check=SimpleNamespace(isChecked=lambda: False),
            volume_smooth_shell_check=SimpleNamespace(isChecked=lambda: True if available else kwargs["volume_smooth_shell_enabled"]),
        )

    monkeypatch.setattr(gui, "SourceMapOptionsDialog", dialog)
    gui.LoretaVisualizerWindow._open_source_map_options(host)
    gui.LoretaVisualizerWindow._open_source_map_options(host)
    assert [option["volume_smooth_shell_enabled"] for option in options] == [False, available]
    assert all(option["volume_smooth_shell_available"] == available for option in options)
    assert calls == ([True] if available else [])
    assert host._source_activation_payload is payload and host._current_activation_payload is payload
    assert payload.values is source_values
    np.testing.assert_array_equal(payload.values, [2., np.nan, 4.])
    assert payload.metadata == {"cluster_mask_source_indices": [0, 2]}


def test_lazy_comparison_renderer_inherits_backdrop_before_its_first_payload(monkeypatch):
    calls, mesh = [], object()
    peer = SimpleNamespace(
        replace_brain_mesh=lambda value, **kwargs: calls.append(("mesh", value, kwargs)),
        set_volume_smooth_shell_enabled=lambda value: calls.append(("shell", value)),
        set_activation_payload=_unexpected,
        shutdown=lambda: calls.append(("shutdown",)), deleteLater=lambda: None,
    )
    monkeypatch.setattr(gui, "BrainRendererWidget", lambda *_a, **_k: peer)
    monkeypatch.setattr(gui, "QWidget", lambda *_a: object())
    monkeypatch.setattr(gui, "QVBoxLayout", lambda *_a: SimpleNamespace(
        setContentsMargins=lambda *_a: None, setSpacing=lambda *_a: None, addWidget=lambda *_a: None,
    ))
    monkeypatch.setattr(gui, "QLabel", lambda *_a: SimpleNamespace(
        setObjectName=lambda *_a: None, setAlignment=lambda *_a: None, setWordWrap=lambda *_a: None,
    ))
    host = SimpleNamespace(
        _comparison_renderer=None, brain_views=object(), _volume_smooth_shell_enabled=True,
        transparency_slider=SimpleNamespace(value=lambda: 40),
        renderer=SimpleNamespace(current_brain_mesh=lambda: mesh),
        brain_views_layout=SimpleNamespace(addWidget=lambda *_a: None),
    )
    assert gui.LoretaVisualizerWindow._ensure_group_comparison_renderer(host) is peer
    assert calls == [("mesh", mesh, {"reset_camera": False}), ("shell", True)]
    assert gui.LoretaVisualizerWindow._ensure_group_comparison_renderer(host) is peer
    assert len(calls) == 2
