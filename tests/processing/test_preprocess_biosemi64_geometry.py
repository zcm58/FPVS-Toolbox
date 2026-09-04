from __future__ import annotations

import numpy as np
import pytest

mne = pytest.importorskip("mne")

from Main_App.io.eeg_geometry import (  # noqa: E402
    BIOSEMI64_CHANNELS,
    attach_raw_biosemi64_geometry,
    cached_biosemi64_montage,
    read_raw_biosemi64_geometry,
)
from Main_App.processing.preprocess import (  # noqa: E402
    _interpolate_current_bads,
    perform_preprocessing,
)


def _raw(
    scalp_names: list[str],
    *,
    include_references: bool,
    samples: int = 512,
) -> mne.io.RawArray:
    ch_names = [*scalp_names, "Status"]
    ch_types = ["eeg"] * len(scalp_names) + ["stim"]
    reference_channels: tuple[str, ...] = ()
    if include_references:
        ch_names = ["EXG1", "EXG2", *ch_names]
        ch_types = ["eeg", "eeg", *ch_types]
        reference_channels = ("EXG1", "EXG2")
    rng = np.random.RandomState(64015)
    data = rng.standard_normal((len(ch_names), samples)) * 1e-6
    data[ch_names.index("Status")] = 0.0
    raw = mne.io.RawArray(
        data,
        mne.create_info(ch_names, sfreq=256.0, ch_types=ch_types),
        verbose=False,
    )
    raw.set_montage(cached_biosemi64_montage(), on_missing="ignore", verbose=False)
    if reference_channels:
        for reference in reference_channels:
            raw.info["chs"][raw.ch_names.index(reference)]["loc"][:] = np.nan
    attach_raw_biosemi64_geometry(
        raw,
        electrode_mapping_profile="anatomical_labels",
        retained_channels=scalp_names,
        reference_channels=reference_channels,
        stim_channel="Status",
    )
    return raw


def test_channel_limit_uses_canonical_identity_and_preserves_source_order() -> None:
    source_scalp_order = ["F1", "AF3", "AF7", "Fp1"]
    raw = _raw(source_scalp_order, include_references=True)
    raw.reorder_channels(["EXG1", "EXG2", "Status", *source_scalp_order])
    params: dict[str, object] = {
        "downsample_rate": 256,
        "high_pass": None,
        "low_pass": None,
        "reject_thresh": None,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 2,
        "stim_channel": "Status",
        "line_noise_filter_enabled": False,
    }

    processed, rejected = perform_preprocessing(
        raw,
        params,
        lambda _message: None,
        "source_order.bdf",
    )

    assert processed is not None
    assert rejected == 0
    assert processed.ch_names == ["Status", "AF7", "Fp1"]
    identity = read_raw_biosemi64_geometry(processed)
    assert identity is not None
    assert identity["retained_scalp_channels"] == ["Fp1", "AF7"]


def test_interpolation_records_only_successfully_repaired_channels() -> None:
    raw = _raw(list(BIOSEMI64_CHANNELS), include_references=False)
    raw.info["bads"] = ["Cz"]
    params: dict[str, object] = {}

    _interpolate_current_bads(
        raw,
        params,
        lambda _message: None,
        filename_for_log="interpolate.bdf",
        description="test bads",
    )

    assert raw.info["bads"] == []
    assert params["_fpvs_interpolation_requested_channels"] == ["Cz"]
    assert params["_fpvs_interpolation_status"] == "succeeded"
    assert params["_fpvs_interpolated_channels"] == ["Cz"]
    assert params["_fpvs_interpolation_error"] == ""


def test_interpolation_failure_does_not_claim_a_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _raw(list(BIOSEMI64_CHANNELS), include_references=False)
    raw.info["bads"] = ["Cz"]
    params: dict[str, object] = {}

    def _fail_interpolation(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("synthetic interpolation failure")

    monkeypatch.setattr(raw, "interpolate_bads", _fail_interpolation)

    with pytest.raises(RuntimeError, match="Interpolation failed"):
        _interpolate_current_bads(
            raw,
            params,
            lambda _message: None,
            filename_for_log="failed.bdf",
            description="test bads",
        )

    assert params["_fpvs_interpolation_status"] == "failed"
    assert params["_fpvs_interpolated_channels"] == []
    assert params["_fpvs_interpolation_error"] == "synthetic interpolation failure"
