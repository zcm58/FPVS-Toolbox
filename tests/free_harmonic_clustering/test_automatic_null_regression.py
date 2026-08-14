"""Deterministic smoke envelope for automatic selection plus cluster inference.

This is a regression harness, not a calibrated FWER validation study.  Its
small, prespecified envelope is intentionally wide enough for Monte Carlo and
simulation uncertainty while still catching a gross loss of null control.
"""

from __future__ import annotations

import numpy as np

from Tools.Free_Harmonic_Clustering.analysis import run_cluster_permutation
from Tools.Free_Harmonic_Clustering.models import (
    AnalysisDesign,
    FreeHarmonicMethodSpec,
)
from Tools.Free_Harmonic_Clustering.preparation import (
    build_frequency_window_plan,
    compute_participant_snr,
    l2_normalize_snr,
    select_harmonics,
    select_snr_harmonics,
)


_NULL_REPLICATE_COUNT = 24
_MAX_ALLOWED_GLOBAL_REJECTIONS = 5
_PARTICIPANTS_PER_ARM = 10
_PERMUTATIONS_PER_REPLICATE = 199


def _full_fft_header() -> list[str]:
    frequencies = np.arange(
        int(round(5.0 / 0.025)) + 1,
        dtype=np.float64,
    ) * 0.025
    return ["Electrode", *(f"{frequency:.6f}_Hz" for frequency in frequencies)]


def test_automatic_domain_plus_permutation_null_smoke_envelope() -> None:
    """Repeat the observed-arm automatic selector inside every null replicate."""

    rejection_count = 0
    selected_counts: list[int] = []
    header = _full_fft_header()
    for replicate in range(_NULL_REPLICATE_COUNT):
        method = FreeHarmonicMethodSpec(
            max_harmonic_hz=4.8,
            n_permutations=_PERMUTATIONS_PER_REPLICATE,
            seed=9_100 + replicate,
        )
        plan = build_frequency_window_plan(header, method)
        rng = np.random.default_rng(8_100 + replicate)
        arm_a_amplitude = rng.lognormal(
            0.0,
            0.18,
            size=(
                _PARTICIPANTS_PER_ARM,
                64,
                len(plan.selected_frequency_columns),
            ),
        )
        arm_b_amplitude = rng.lognormal(
            0.0,
            0.18,
            size=arm_a_amplitude.shape,
        )

        # Both exchangeable arms receive the same population FPVS response.
        # H1/H2 are reliably present, while H3/H4 remain eligible null peaks so
        # the automatic observed-arm ceiling is genuinely rerun per replicate.
        for target_index, common_boost in zip(
            plan.target_selected_indices,
            (2.0, 1.35, 0.0, 0.0),
            strict=True,
        ):
            arm_a_amplitude[..., target_index] += common_boost
            arm_b_amplitude[..., target_index] += common_boost

        grand_a = np.mean(arm_a_amplitude, axis=(0, 1))
        grand_b = np.mean(arm_b_amplitude, axis=(0, 1))
        selection = select_harmonics(grand_a, grand_b, plan, method)
        selected_counts.append(len(selection.selected_orders))

        snr_a = compute_participant_snr(arm_a_amplitude, plan)
        snr_b = compute_participant_snr(arm_b_amplitude, plan)
        values_a = l2_normalize_snr(select_snr_harmonics(snr_a, selection))
        values_b = l2_normalize_snr(select_snr_harmonics(snr_b, selection))
        result = run_cluster_permutation(
            values_a,
            values_b,
            design=AnalysisDesign.INDEPENDENT_GROUPS,
            method=method,
            batch_size=67,
        )
        rejection_count += any(cluster.significant for cluster in result.clusters)

    assert len(selected_counts) == _NULL_REPLICATE_COUNT
    assert min(selected_counts) >= 2
    assert max(selected_counts) > min(selected_counts)
    assert rejection_count <= _MAX_ALLOWED_GLOBAL_REJECTIONS
