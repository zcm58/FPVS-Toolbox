from __future__ import annotations

import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest

from config import DEFAULT_ELECTRODE_NAMES_64
from Tools.LORETA_Visualizer.source_producers import project_eloreta_volume_export as export_module
from Tools.LORETA_Visualizer.source_producers.project_eloreta_volume_export import (
    MneFsaverageELORETAVolumeSourcePsdModel,
    ProjectELORETAVolumeExportError,
    build_mne_fsaverage_eloreta_volume_forward_model,
    build_mne_fsaverage_eloreta_volume_source_psd_model,
)


class _FakeInfo:
    def __init__(self, channel_names: tuple[str, ...], sfreq: float) -> None:
        self.ch_names = list(channel_names)
        self._sfreq = float(sfreq)

    def __getitem__(self, key: str) -> float:
        if key != "sfreq":
            raise KeyError(key)
        return self._sfreq

    def copy(self) -> _FakeInfo:
        return _FakeInfo(tuple(self.ch_names), self._sfreq)


class _FakeEvoked:
    def apply_proj(self, *, verbose: bool = False) -> _FakeEvoked:
        _ = verbose
        return self


def test_source_psd_model_uses_actual_sfreq_and_prepares_eloreta_once(
    tmp_path,
    monkeypatch,
) -> None:
    calls = _install_fake_mne(tmp_path, monkeypatch)
    channels = tuple(DEFAULT_ELECTRODE_NAMES_64)

    model = build_mne_fsaverage_eloreta_volume_source_psd_model(
        sfreq=256.0,
        channel_names=channels,
        prepare_inverse=True,
        lambda2=0.125,
        method_params={"eps": 1e-6},
    )

    assert isinstance(model, MneFsaverageELORETAVolumeSourcePsdModel)
    assert model.info["sfreq"] == pytest.approx(256.0)
    assert tuple(model.info.ch_names) == channels
    assert model.prepared is True
    assert model.inverse_operator is calls["prepared_inverse"]
    assert len(calls["prepare_inverse"]) == 1
    assert calls["prepare_inverse"][0] == {
        "orig": calls["raw_inverse"],
        "nave": 1,
        "lambda2": 0.125,
        "method": "eLORETA",
        "method_params": {"eps": 1e-6},
        "copy": True,
        "verbose": False,
    }
    assert calls["info_sfreq"] == [256.0]
    assert model.forward_model.metadata["model_sfreq_hz"] == pytest.approx(256.0)
    assert model.metadata["source_psd_inverse_method"] == "eLORETA"
    assert model.metadata["source_psd_inverse_prepared"] is True
    assert model.metadata["source_psd_method_params"] == {"eps": 1e-6}

    values = model.forward_model.source_estimator(
        np.ones(len(channels), dtype=float),
        lambda2=0.125,
        method_params={"eps": 1e-6},
    )
    assert values.tolist() == pytest.approx([2.0, 3.0])
    assert calls["apply_inverse"][-1]["prepared"] is True
    assert calls["apply_inverse"][-1]["method"] == "eLORETA"


def test_source_psd_model_can_leave_inverse_unprepared(tmp_path, monkeypatch) -> None:
    calls = _install_fake_mne(tmp_path, monkeypatch)

    model = build_mne_fsaverage_eloreta_volume_source_psd_model(
        sfreq=128.0,
        channel_names=tuple(DEFAULT_ELECTRODE_NAMES_64),
        prepare_inverse=False,
    )

    assert model.prepared is False
    assert model.inverse_operator is calls["raw_inverse"]
    assert calls["prepare_inverse"] == []
    assert model.metadata["model_sfreq_hz"] == pytest.approx(128.0)


def test_source_psd_model_rejects_noncanonical_channels_before_mne_build() -> None:
    with pytest.raises(ProjectELORETAVolumeExportError, match="canonical BioSemi64 channel order"):
        build_mne_fsaverage_eloreta_volume_source_psd_model(
            sfreq=100.0,
            channel_names=tuple(reversed(DEFAULT_ELECTRODE_NAMES_64)),
        )


def test_legacy_forward_builder_delegates_without_preparing_inverse(monkeypatch) -> None:
    sentinel_forward = object()
    calls: list[dict[str, object]] = []

    def fake_source_psd_builder(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(forward_model=sentinel_forward)

    monkeypatch.setattr(
        export_module,
        "build_mne_fsaverage_eloreta_volume_source_psd_model",
        fake_source_psd_builder,
    )

    result = build_mne_fsaverage_eloreta_volume_forward_model(
        volume_pos_mm=8.0,
        allow_fetch_fsaverage=True,
        mindist_mm=4.0,
        loose_orientation=0.75,
    )

    assert result is sentinel_forward
    assert calls == [
        {
            "sfreq": 100.0,
            "channel_names": tuple(DEFAULT_ELECTRODE_NAMES_64),
            "volume_pos_mm": 8.0,
            "allow_fetch_fsaverage": True,
            "mindist_mm": 4.0,
            "loose_orientation": 0.75,
            "prepare_inverse": False,
        }
    ]


def _install_fake_mne(tmp_path, monkeypatch) -> dict[str, object]:
    channels = tuple(DEFAULT_ELECTRODE_NAMES_64)
    raw_inverse = object()
    prepared_inverse = object()
    calls: dict[str, object] = {
        "raw_inverse": raw_inverse,
        "prepared_inverse": prepared_inverse,
        "prepare_inverse": [],
        "apply_inverse": [],
        "info_sfreq": [],
    }

    mne_module = ModuleType("mne")
    minimum_norm_module = ModuleType("mne.minimum_norm")
    mne_module.__version__ = "test-mne"

    source_spaces = [
        {
            "vertno": np.asarray([0, 1], dtype=np.int64),
            "rr": np.asarray([[0.0, 0.0, 0.0], [0.01, 0.02, 0.03]], dtype=float),
        }
    ]
    forward = {
        "sol": {
            "data": np.ones((len(channels), 6), dtype=float),
            "row_names": list(channels),
        }
    }

    def setup_volume_source_space(*args, **kwargs):
        _ = args, kwargs
        return source_spaces

    def make_forward_solution(info, **kwargs):
        _ = info, kwargs
        return forward

    def make_ad_hoc_cov(info, *, verbose=False):
        _ = info, verbose
        return object()

    def spatial_src_adjacency(src, *, verbose=False):
        _ = src, verbose
        return object()

    def make_inverse_operator(info, forward_arg, noise_cov, **kwargs):
        _ = info, forward_arg, noise_cov, kwargs
        return raw_inverse

    def prepare_inverse_operator(orig, **kwargs):
        calls["prepare_inverse"].append({"orig": orig, **kwargs})
        return prepared_inverse

    def apply_inverse(evoked, inverse_operator, **kwargs):
        _ = evoked, inverse_operator
        calls["apply_inverse"].append(kwargs)
        return SimpleNamespace(data=np.asarray([[2.0], [3.0]], dtype=float))

    mne_module.setup_volume_source_space = setup_volume_source_space
    mne_module.make_forward_solution = make_forward_solution
    mne_module.make_ad_hoc_cov = make_ad_hoc_cov
    mne_module.spatial_src_adjacency = spatial_src_adjacency
    mne_module.EvokedArray = lambda *args, **kwargs: _FakeEvoked()
    minimum_norm_module.make_inverse_operator = make_inverse_operator
    minimum_norm_module.prepare_inverse_operator = prepare_inverse_operator
    minimum_norm_module.apply_inverse = apply_inverse
    mne_module.minimum_norm = minimum_norm_module

    monkeypatch.setitem(sys.modules, "mne", mne_module)
    monkeypatch.setitem(sys.modules, "mne.minimum_norm", minimum_norm_module)
    monkeypatch.setattr(
        export_module,
        "_resolve_fsaverage_subjects_dir",
        lambda *_args, **_kwargs: tmp_path,
    )
    monkeypatch.setattr(export_module, "_require_file", lambda *_args, **_kwargs: None)

    def fake_info(_mne, channel_names, *, sfreq):
        calls["info_sfreq"].append(float(sfreq))
        return _FakeInfo(tuple(channel_names), sfreq)

    monkeypatch.setattr(export_module, "_biosemi64_info", fake_info)
    monkeypatch.setattr(
        export_module,
        "_with_eeg_average_reference_projection",
        lambda _mne, info: info,
    )
    monkeypatch.setattr(
        export_module,
        "adjacency_from_sparse_matrix",
        lambda _matrix, *, source_count: tuple(set() for _index in range(source_count)),
    )
    return calls
