"""Offline native-MNE reference on small, explicitly artificial sphere models.

The reference applies an inverse to signed time samples, then evaluates the DFT
with sine/cosine sums. It does not call Toolbox PSD, FFT, harmonic, or Z helpers.
The geometry is generated mathematically; no MRI, downloaded asset, or real EEG
is needed. This is numerical regression evidence, not an anatomical model.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np


@dataclass(frozen=True)
class NativeDiagnosticModel:
    method: str
    info: Any
    inverse: Any
    leadfield: np.ndarray
    points_mm: np.ndarray
    adjacency: tuple[set[int], ...]
    prepared: bool = False
    method_params: dict[str, Any] | None = None
    geometry: str = "analytic_sphere_twelve_sources"


def build_native_sphere_model(method: str, *, sfreq: float = 200.0) -> NativeDiagnosticModel:
    """Create native surface/volume inverses on artificial twelve-point geometry."""
    import mne
    from mne.io.constants import FIFF
    from mne.minimum_norm import make_inverse_operator

    from .source_space_statistics import adjacency_from_triangular_faces

    if method not in {"MNE", "eLORETA"}:
        raise ValueError("Reference method must be MNE or eLORETA.")
    axes = np.asarray([[1., 0, 0], [-1., 0, 0], [0, 1., 0], [0, -1., 0], [0, 0, 1.], [0, 0, -1.]])
    triangles = np.asarray([[0, 2, 4], [2, 1, 4], [1, 3, 4], [3, 0, 4], [2, 0, 5], [1, 2, 5], [3, 1, 5], [0, 3, 5]])
    spaces = []
    for hemisphere, centre in enumerate(([-0.025, 0, 0], [0.025, 0, 0])):
        spaces.append(dict(
            type="surf", id=101 + hemisphere, coord_frame=FIFF.FIFFV_COORD_HEAD,
            np=6, rr=axes * 0.018 + centre, nn=axes.copy(), ntri=8,
            tris=triangles.copy(), nuse=6, inuse=np.ones(6, int), vertno=np.arange(6),
            nuse_tri=8, use_tris=triangles.copy(), nearest=None, nearest_dist=None,
            pinfo=None, patch_inds=None, dist=None, dist_limit=None,
            subject_his_id="synthetic_sphere",
        ))
    points = np.vstack([space["rr"] for space in spaces])
    if method == "MNE":
        src = mne.SourceSpaces(spaces)
    else:
        src = mne.setup_volume_source_space(
            pos={"rr": points, "nn": np.tile(axes, (2, 1))}, verbose=False,
        )
    info = mne.create_info(["Fp1", "Fp2", "F3", "F4", "C3", "C4", "P3", "P4", "O1", "O2"], sfreq, "eeg")
    info.set_montage(mne.channels.make_standard_montage("standard_1020"))
    raw = mne.io.RawArray(np.zeros((10, 2)), info, verbose=False)
    raw.set_eeg_reference("average", projection=True, verbose=False)
    sphere = mne.make_sphere_model(r0=(0., 0., 0.), head_radius=0.09, verbose=False)
    forward = mne.make_forward_solution(
        raw.info, trans=None, src=src, bem=sphere, meg=False, eeg=True, mindist=0., verbose=False,
    )
    # The native surface inverse rotates its source basis; retain the matching gain.
    forward = mne.convert_forward_solution(forward, surf_ori=method == "MNE", verbose=False)
    inverse = make_inverse_operator(
        raw.info, forward, mne.make_ad_hoc_cov(raw.info, verbose=False),
        loose=0.2 if method == "MNE" else 1., depth=None, verbose=False,
    )
    faces = np.vstack([triangles, triangles + 6])
    return NativeDiagnosticModel(
        method, raw.info, inverse, np.asarray(forward["sol"]["data"]), points * 1000.,
        adjacency_from_triangular_faces(faces, source_count=12),
    )


def deterministic_reference_samples(n_times: int, *, channel_count: int = 10) -> np.ndarray:
    """Signed reproducible volts with nonzero means, phase, and broadband noise."""
    rng = np.random.default_rng(771031)
    sample = np.arange(n_times)
    data = rng.normal(size=(channel_count, n_times)) * 1e-6
    for channel in range(channel_count):
        data[channel] += (channel - 4.5) * 1e-7
        data[channel] += 8e-7 * np.cos(2 * np.pi * 24 * sample / n_times + channel * 0.31)
        data[channel] -= 5e-7 * np.sin(2 * np.pi * 48 * sample / n_times + channel * 0.13)
    return data


def independent_native_reference(
    model: NativeDiagnosticModel, data: np.ndarray, *, harmonic_bins: tuple[int, ...] = (24, 48),
) -> dict[str, Any]:
    """Use native time-domain inversion and direct DFT, independently of production."""
    import mne
    from mne.minimum_norm import apply_inverse

    data = np.asarray(data, dtype=float)
    evoked = mne.EvokedArray(data, model.info.copy(), nave=1, verbose=False)
    signed = apply_inverse(
        evoked, model.inverse, lambda2=1 / 9, method=model.method,
        pick_ori="normal" if model.method == "MNE" else "vector",
        prepared=model.prepared, method_params=model.method_params, verbose=False,
    ).data
    signed = signed - signed.mean(axis=-1, keepdims=True)
    n_times = data.shape[1]
    offsets = (0, *range(-10, -1), *range(2, 11))
    bins = sorted({harmonic + offset for harmonic in harmonic_bins for offset in offsets})
    sample = np.arange(n_times)
    window = 0.5 - 0.5 * np.cos(2 * np.pi * sample / n_times)
    angle = 2 * np.pi * np.asarray(bins)[:, None] * sample / n_times
    coefficients = (signed * window) @ (np.cos(angle) - 1j * np.sin(angle)).T
    scale = np.full(len(bins), np.sqrt(2.))
    scale[np.asarray(bins) == 0] = 1.
    if n_times % 2 == 0:
        scale[np.asarray(bins) == n_times // 2] = 1.
    coefficients *= scale
    amplitudes = np.abs(coefficients) if model.method == "MNE" else np.sqrt((np.abs(coefficients) ** 2).sum(axis=1))
    lookup = {value: index for index, value in enumerate(bins)}
    summed = np.stack([
        sum(amplitudes[:, lookup[harmonic + offset]] for harmonic in harmonic_bins)
        for offset in offsets
    ], axis=1)
    noise = np.sort(summed[:, 1:], axis=1)[:, 1:-1]
    mean = noise.mean(axis=1)
    sd = np.sqrt(((noise - mean[:, None]) ** 2).mean(axis=1))
    return {
        "required_bins": bins, "source_amplitudes": amplitudes.tolist(),
        "summed_source_amplitudes": summed.tolist(),
        "z_scores": ((summed[:, 0] - mean) / sd).tolist(),
        "noise_mean": mean.tolist(), "noise_sd": sd.tolist(),
    }


def generate_reference_fixture() -> dict[str, Any]:
    """Explicitly regenerate the frozen independent reference; never run in asserts."""
    import mne
    import scipy

    cases = []
    for method in ("MNE", "eLORETA"):
        model = build_native_sphere_model(method)
        for n_times in (511, 512):
            data = deterministic_reference_samples(n_times)
            harmonic_bins = (24, n_times // 2 - 10)
            cases.append({
                "method": method, "n_times": n_times, "sfreq": 200.,
                "harmonic_bins": list(harmonic_bins), "seed": 771031,
                **independent_native_reference(model, data, harmonic_bins=harmonic_bins),
            })
    return {
        "format": "fpvs-native-source-spectral-reference-v1",
        "reference_route": "native MNE apply_inverse on signed time samples, explicit sine/cosine DFT, independent aggregation and Z",
        "not_tested": ["anatomical realism", "real-data accuracy", "population inference", "fsaverage model construction"],
        "dependencies": {"mne": mne.__version__, "numpy": np.__version__, "scipy": scipy.__version__},
        "reference_api": "https://mne.tools/1.9/generated/mne.minimum_norm.apply_inverse.html",
        "relative_tolerance": 2e-6, "amplitude_absolute_tolerance": 1e-16,
        "z_absolute_tolerance": 2e-6, "cases": cases,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(generate_reference_fixture(), indent=2, allow_nan=False) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
