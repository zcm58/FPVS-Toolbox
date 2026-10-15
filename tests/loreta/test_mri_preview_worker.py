"""Preview worker orchestration with plain Python stubs and synthetic payloads."""

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from Tools.LORETA_Visualizer import gui
from Tools.LORETA_Visualizer.source_payloads import make_source_payload


def _payload(values, mask):
    return make_source_payload(
        points=np.column_stack([np.arange(len(values)), np.zeros((len(values), 2))]),
        values=np.asarray(values, dtype=float),
        label="Synthetic source map",
        kind="volume_points",
        source_model="eloreta_volume",
        value_label="source-space z-score",
        metadata={
            "source_value_unit": "z-score",
            "cluster_mask": "source_space_cluster_permutation",
            "cluster_mask_source_indices": mask,
        },
        normalize_values=False,
    )


def _request():
    original = _payload([1.0, 2.0, 8.0], [2])
    return {
        "id": 17,
        "reference_paths": (Path("condition_a.json"), Path("condition_b.json")),
        "use_cluster_mask": True,
        "render_kwargs": {
            "payload": gui._activation_display_payload(original),
            "inspection_payload": original,
            "display_transform": object(),
            "fsaverage_dir": Path("synthetic-anatomy"),
            "anatomy": None,
            "slice_indices": None,
            "scalar_range": (0.0, 8.0),
        },
    }


def _run(request):
    events = []

    def signal(name):
        return SimpleNamespace(emit=lambda *args: events.append((name, args)))

    worker = SimpleNamespace(
        request=request, rendered=signal("rendered"), failed=signal("failed"), finished=signal("finished")
    )
    gui.MriSliceRenderWorker.run(worker)
    return events


def test_worker_builds_all_condition_reference_with_one_mask_application(monkeypatch):
    request = _request()
    source_a = request["render_kwargs"]["inspection_payload"]
    source_b = _payload([3.0, 5.0, 9.0], [1])
    sources = dict(zip(request["reference_paths"], (source_a, source_b)))
    anatomy, result = object(), object()
    seen, filtered = {}, []
    real_display_filter = gui._activation_display_payload

    def filter_once(payload, **kwargs):
        filtered.append(payload)
        return real_display_filter(payload, **kwargs)

    def load_payload(path, **kwargs):
        assert kwargs["display_transform"] is request["render_kwargs"]["display_transform"]
        return sources[path]

    def choose_indices(payload, **kwargs):
        seen["reference"] = payload
        assert kwargs["anatomy"] is anatomy
        return (4, 5, 6)

    def render(**kwargs):
        seen["render"] = kwargs
        return result

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", lambda _path: anatomy)
    monkeypatch.setattr(gui, "load_prepared_source_payload_json", load_payload)
    monkeypatch.setattr(gui, "_activation_display_payload", filter_once)
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", choose_indices)
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", render)

    events = _run(request)

    assert len(filtered) == 2 and filtered[0] is source_a and filtered[1] is source_b
    assert seen["reference"].values.tolist() == [8.0, 5.0]
    assert seen["reference"].points[:, 0].tolist() == [2.0, 1.0]
    assert seen["render"]["payload"] is request["render_kwargs"]["payload"]
    assert seen["render"]["inspection_payload"] is source_a
    assert source_a.values.tolist() == [1.0, 2.0, 8.0]
    assert seen["render"]["slice_indices"] == (4, 5, 6)
    assert request["render_kwargs"]["slice_indices"] is None
    assert request["render_kwargs"]["anatomy"] is None
    assert [name for name, _ in events] == ["rendered", "finished"]
    assert events[0][1][0] == (request, result, anatomy)


def test_worker_honors_cached_anatomy_and_manual_slice_indices(monkeypatch):
    request = _request()
    anatomy, result = object(), object()
    request["render_kwargs"].update(anatomy=anatomy, slice_indices=(7, 8, 9))
    seen = {}

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Saved navigation must not reload anatomy or recompute the reference.")

    def render(**kwargs):
        seen.update(kwargs)
        return result

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", unexpected)
    monkeypatch.setattr(gui, "load_prepared_source_payload_json", unexpected)
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", unexpected)
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", render)

    events = _run(request)

    assert seen["slice_indices"] == (7, 8, 9)
    assert seen["anatomy"] is anatomy
    assert seen["inspection_payload"] is request["render_kwargs"]["inspection_payload"]
    assert [name for name, _ in events] == ["rendered", "finished"]


@pytest.mark.parametrize("stage", ["anatomy", "reference", "render"])
def test_worker_emits_finished_after_failure_at_each_stage(monkeypatch, stage):
    request = _request()

    def failure(*_args, **_kwargs):
        raise OSError(f"Synthetic {stage} failure")

    monkeypatch.setattr(gui, "load_fsaverage_mri_volume", lambda _path: object())
    monkeypatch.setattr(
        gui, "load_prepared_source_payload_json", lambda *_args, **_kwargs: request["render_kwargs"]["inspection_payload"]
    )
    monkeypatch.setattr(gui, "mri_slice_indices_for_payload", lambda *_args, **_kwargs: (1, 2, 3))
    monkeypatch.setattr(gui, "render_mri_orthogonal_slice_image", lambda **_kwargs: object())
    monkeypatch.setattr(gui, {
        "anatomy": "load_fsaverage_mri_volume",
        "reference": "load_prepared_source_payload_json",
        "render": "render_mri_orthogonal_slice_image",
    }[stage], failure)

    events = _run(request)

    assert events == [("failed", (17, f"Synthetic {stage} failure")), ("finished", ())]
