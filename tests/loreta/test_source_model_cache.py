"""Synthetic native-model tests: never read or download real fsaverage assets."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import mne
import numpy as np
import pytest
from scipy import sparse

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.source_producers import project_l2_mne_export as l2
from Tools.LORETA_Visualizer.source_producers import project_eloreta_volume_export as eloreta
from Tools.LORETA_Visualizer.source_producers import source_model_cache as cache


@pytest.fixture
def native_models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    cache.clear_source_model_session_cache()
    templates = (
        "bem/fsaverage-5120-5120-5120-bem-sol.fif",
        "bem/fsaverage-trans.fif",
        "surf/lh.white",
        "surf/rh.white",
        "surf/lh.sphere",
        "surf/rh.sphere",
        "mri/T1.mgz",
    )
    for relative in templates:
        path = tmp_path / "fsaverage" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"synthetic template")
    counts = dict(source=0, forward=0, inverse=0, prepare=0)
    src = [
        {
            "vertno": np.array([0, 1, 2, 3]),
            "rr": np.array([[-0.02, 0.0, 0.0], [-0.01, 0.01, 0.0], [0.01, 0.0, 0.0], [0.02, 0.01, 0.0]]),
        }
    ]

    def source(*_args, **_kwargs):
        counts["source"] += 1
        return deepcopy(src)

    def forward(*_args, **_kwargs):
        counts["forward"] += 1
        return {"sol": {"data": np.ones((64, 12)), "row_names": list(DEFAULT_ELECTRODE_NAMES_64)}, "src": deepcopy(src)}

    def inverse(*_args, **_kwargs):
        counts["inverse"] += 1
        return {"weights": np.arange(6, dtype=float), "source_count": 4}

    def prepare(value, **_kwargs):
        counts["prepare"] += 1
        return deepcopy(value)

    for module in (l2, eloreta):
        monkeypatch.setattr(module, "_resolve_fsaverage_subjects_dir", lambda *_a, **_k: tmp_path)
    monkeypatch.setattr(mne, "setup_source_space", source)
    monkeypatch.setattr(mne, "setup_volume_source_space", source)
    monkeypatch.setattr(mne, "make_forward_solution", forward)
    monkeypatch.setattr(mne, "convert_forward_solution", lambda value, **_kwargs: value)
    monkeypatch.setattr(mne, "spatial_src_adjacency", lambda *_a, **_k: sparse.eye(4, format="csr"))
    monkeypatch.setattr(mne.minimum_norm, "make_inverse_operator", inverse)
    monkeypatch.setattr(mne.minimum_norm, "prepare_inverse_operator", prepare)
    monkeypatch.setattr(
        l2,
        "_surface_source_points_and_faces",
        lambda *_a, **_k: (
            np.array([[-20.0, 0.0, 0.0], [-10.0, 10.0, 0.0], [10.0, 0.0, 0.0], [20.0, 10.0, 0.0]]),
            np.array([[0, 1, 2], [1, 2, 3]]),
            (2, 2),
            (0, 1, 0, 1),
            ("lh", "lh", "rh", "rh"),
        ),
    )
    yield tmp_path, counts
    cache.clear_source_model_session_cache()


def _build(method: str, **kwargs):
    builder = (
        l2.build_mne_fsaverage_source_psd_model
        if method == "MNE"
        else eloreta.build_mne_fsaverage_eloreta_volume_source_psd_model
    )
    return builder(sfreq=kwargs.pop("sfreq", 200.0), channel_names=DEFAULT_ELECTRODE_NAMES_64, **kwargs)


def test_models_reuse_separate_native_resources_without_mutable_aliasing(native_models) -> None:
    _root, counts = native_models
    cold = {method: _build(method) for method in ("MNE", "eLORETA")}
    snapshots = {method: model.inverse_operator["weights"].copy() for method, model in cold.items()}
    for model in cold.values():
        model.inverse_operator["weights"][:] = -99
        model.forward_model.leadfield[:] = -99
    for method in cold:
        warm = _build(method)
        np.testing.assert_array_equal(warm.inverse_operator["weights"], snapshots[method])
        assert np.all(warm.forward_model.leadfield >= 0)
        assert warm.metadata["model_preparation_signature"] == cold[method].metadata["model_preparation_signature"]
        warm.inverse_operator["weights"][:] = -55
        np.testing.assert_array_equal(_build(method).inverse_operator["weights"], snapshots[method])
    assert counts == dict(source=2, forward=2, inverse=2, prepare=1)
    assert (
        cold["MNE"].metadata["model_preparation_signature"] != cold["eLORETA"].metadata["model_preparation_signature"]
    )


@pytest.mark.parametrize("method", ["MNE", "eLORETA"])
@pytest.mark.parametrize(
    "change", ["sfreq", "mindist", "loose", "spacing", "template", "geometry", "mne", "numpy", "scipy"]
)
def test_native_model_invalidation(native_models, monkeypatch, method, change) -> None:
    root, counts = native_models
    cold = _build(method)
    kwargs = {}
    if change == "sfreq":
        kwargs["sfreq"] = 256.0
    elif change == "mindist":
        kwargs["mindist_mm"] = 4.0
    elif change == "loose":
        kwargs["loose_orientation"] = 0.5
    elif change == "spacing":
        kwargs.update({"spacing": "ico4"} if method == "MNE" else {"volume_pos_mm": 8.0})
    elif change == "template":
        relative = "surf/lh.sphere" if method == "MNE" else "mri/T1.mgz"
        (root / "fsaverage" / relative).write_bytes(b"changed template")
    elif change == "geometry":
        module = l2 if method == "MNE" else eloreta
        original = module._biosemi64_info

        def changed_info(*args, **kwargs):
            info = original(*args, **kwargs)
            info["chs"][0]["loc"][0] += 0.001
            return info

        monkeypatch.setattr(module, "_biosemi64_info", changed_info)
    elif change == "mne":
        monkeypatch.setattr(mne, "__version__", "changed-mne")
    elif change in ("numpy", "scipy"):
        monkeypatch.setattr(cache.np if change == "numpy" else cache.scipy, "__version__", "changed-version")
    changed = _build(method, **kwargs)
    assert counts["inverse"] == 2
    assert cold.metadata["model_preparation_signature"] != changed.metadata["model_preparation_signature"]


@pytest.mark.parametrize(
    "method,relative",
    [
        ("MNE", "bem/fsaverage-5120-5120-5120-bem-sol.fif"),
        ("MNE", "bem/fsaverage-trans.fif"),
        ("MNE", "surf/lh.white"),
        ("MNE", "surf/rh.white"),
        ("MNE", "surf/lh.sphere"),
        ("MNE", "surf/rh.sphere"),
        ("eLORETA", "bem/fsaverage-5120-5120-5120-bem-sol.fif"),
        ("eLORETA", "bem/fsaverage-trans.fif"),
        ("eLORETA", "mri/T1.mgz"),
    ],
)
def test_all_native_template_inputs_invalidate(native_models, method, relative) -> None:
    root, counts = native_models
    cold = _build(method)
    path = root / "fsaverage" / relative
    before = path.stat()
    path.write_bytes(b"different template")
    # Content identity is authoritative even when a timestamp is restored.
    import os

    os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
    changed = _build(method)
    assert counts["inverse"] == 2
    assert cold.metadata["model_preparation_signature"] != changed.metadata["model_preparation_signature"]
    path.unlink()
    with pytest.raises((OSError, RuntimeError)):
        _build(method)
    assert counts["inverse"] == 2


@pytest.mark.parametrize("method", ["MNE", "eLORETA"])
def test_new_session_rebuilds_identical_native_resources(native_models, method) -> None:
    _root, counts = native_models
    cold = _build(method)
    cache.clear_source_model_session_cache()
    restarted = _build(method)
    assert counts["inverse"] == 2
    assert cold.metadata["model_preparation_signature"] == restarted.metadata["model_preparation_signature"]
    np.testing.assert_array_equal(cold.inverse_operator["weights"], restarted.inverse_operator["weights"])


def test_full_surface_spacing_does_not_require_unused_sphere_files(native_models) -> None:
    root, counts = native_models
    for hemi in ("lh", "rh"):
        (root / "fsaverage" / "surf" / f"{hemi}.sphere").unlink()
    _build("MNE", spacing="all")
    _build("MNE", spacing="all")
    assert counts["inverse"] == 1


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lambda2": 0.2},
        {"method_params": {"eps": 1e-5}},
        {"prepare_inverse": False},
    ],
)
def test_eloreta_preparation_settings_invalidate(native_models, kwargs) -> None:
    _root, counts = native_models
    cold = _build("eLORETA")
    changed = _build("eLORETA", **kwargs)
    assert counts["inverse"] == 2
    assert cold.metadata["model_preparation_signature"] != changed.metadata["model_preparation_signature"]


def test_session_cache_evicts_and_does_not_retain_failed_builds() -> None:
    cache.clear_source_model_session_cache()
    calls = []

    def build():
        calls.append(1)
        return np.ones(2)

    for key in ("a", "b", "a", "c", "a", "b"):
        cache.cached_source_model_resources(key, build)
    assert len(calls) == 4

    def fail():
        raise RuntimeError("native solver failed")

    with pytest.raises(RuntimeError, match="native solver failed"):
        cache.cached_source_model_resources("failed", fail)
    cache.cached_source_model_resources("failed", build)
    assert len(calls) == 5
    cache.clear_source_model_session_cache()


@pytest.mark.parametrize("method", ["MNE", "eLORETA"])
def test_automatic_project_rebuild_reuses_models_and_skips_eeg_preload(native_models, monkeypatch, method) -> None:
    from tests.loreta import test_project_l2_mne_hauk_source_psd_export as l2_fixture
    from tests.loreta import test_project_eloreta_volume_hauk_source_psd_export as volume_fixture
    from Tools.LORETA_Visualizer.source_producers import project_time_domain_inputs as inputs
    from Tools.LORETA_Visualizer.source_producers import source_rois

    root, counts = native_models
    fixture = l2_fixture if method == "MNE" else volume_fixture
    project = fixture._project_with_ledger(root / "project", participants=("P01",))
    fixture._write_time_domain_derivative(project.project_root, participant_id="P01")
    # Supply only synthetic anatomical labels as well as the synthetic native solver.
    monkeypatch.setattr(
        source_rois,
        "_read_desikan_killiany_temporal_label_vertices",
        lambda **_k: {
            hemi: {label: (0, 1) for label in source_rois.DESIKAN_KILLIANY_TEMPORAL_LABELS} for hemi in ("lh", "rh")
        },
    )
    reads = []
    original_read = inputs._read_and_validate_raw

    def tracked_read(record, *, preload, require_finite):
        reads.append((preload, require_finite))
        return original_read(record, preload=preload, require_finite=require_finite)

    monkeypatch.setattr(inputs, "_read_and_validate_raw", tracked_read)
    calls = []
    writer = (
        fixture.write_project_l2_mne_hauk_source_psd_payloads
        if method == "MNE"
        else fixture.write_project_eloreta_volume_hauk_source_psd_payloads
    )
    compute = (
        {"compute_source_psd_func": fixture._source_psd_callable(calls)}
        if method == "MNE"
        else {"apply_inverse_func": fixture._apply_inverse_callable(calls)}
    )
    kwargs = dict(
        project=project, selected_harmonics_hz=(20.0,), aggregations=("mean",), cluster_mask_enabled=False, **compute
    )
    cold = writer(**kwargs)
    manifest = json.loads(cold.manifest_path.read_text(encoding="utf-8"))
    values = json.loads((cold.output_dir / manifest["conditions"][0]["file"]).read_text(encoding="utf-8"))["values"]
    assert reads == [(False, False), (True, True)]
    reads.clear()
    warm = writer(**kwargs)
    assert warm.cache_hit_count == 1
    assert len(calls) == 1
    assert counts["inverse"] == 1
    assert counts["prepare"] == (1 if method == "eLORETA" else 0)
    assert reads == [(False, False)]
    assert (
        json.loads((warm.output_dir / manifest["conditions"][0]["file"]).read_text(encoding="utf-8"))["values"]
        == values
    )

    # A changed template invalidates both the model and the participant result,
    # even though this deterministic test solver returns identical arrays.
    (root / "fsaverage" / "bem" / "fsaverage-trans.fif").write_bytes(b"changed transform")
    reads.clear()
    changed = writer(**kwargs)
    assert changed.cache_miss_count == 1
    assert len(calls) == 2
    assert counts["inverse"] == 2
    assert reads == [(False, False), (True, True)]
