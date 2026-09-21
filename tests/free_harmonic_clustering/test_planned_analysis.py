from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

from Tools.Free_Harmonic_Clustering import planned_analysis
from Tools.Free_Harmonic_Clustering.analysis_plan import AnalysisFamily, build_analysis_plan
from Tools.Free_Harmonic_Clustering.models import FreeHarmonicInputError, FreeHarmonicMethodSpec
from tests.free_harmonic_clustering.test_inputs import (
    _install_frequency_exclusions,
    _install_reader_doubles,
    _write_project,
    _write_repeated_project,
)


@pytest.fixture(autouse=True)
def reviewed_qc(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_frequency_exclusions(monkeypatch)


def test_plan_reads_sources_once_and_uses_shared_domain(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root = _write_repeated_project(
        tmp_path / "project",
        participants_by_group={"bc_group": ("A1", "A2"), "control_group": ("B1", "B2")},
        conditions=("C1", "C2"),
    )
    headers, amplitudes = _install_reader_doubles(monkeypatch)
    plan = build_analysis_plan(
        root,
        group_ids=("bc_group", "control_group"),
        conditions=("C1", "C2"),
        session_ids=("luteal_phase", "follicular_phase"),
        families=tuple(AnalysisFamily),
    )
    prepared = planned_analysis.prepare_analysis_plan(
        plan, FreeHarmonicMethodSpec(max_harmonic_hz=3.6, n_permutations=7)
    )
    assert len(prepared.contrasts) == 10
    assert len(headers) == len(set(headers)) == 16
    assert len(amplitudes) == len(set(amplitudes)) == 16
    assert len(prepared.shared_selection_audit.cell_labels) == 8
    assert all(row.selection is prepared.shared_selection for row in prepared.contrasts)


def test_single_group_repeated_plan_can_run_without_other_group(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _write_repeated_project(
        tmp_path / "project",
        participants_by_group={"bc_group": ("A1", "A2"), "control_group": ("B1",)},
        conditions=("C1", "C2"),
    )
    _install_reader_doubles(monkeypatch)
    plan = build_analysis_plan(
        root, group_ids=("bc_group",), conditions=("C1", "C2"), session_ids=("luteal_phase", "follicular_phase")
    )
    prepared = planned_analysis.prepare_analysis_plan(plan, FreeHarmonicMethodSpec(max_harmonic_hz=3.6))
    assert len(prepared.contrasts) == 2
    assert all(row.participant_ids_a == ("A1", "A2") for row in prepared.contrasts)


def test_unavailable_condition_pair_fails_before_reading_any_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _write_project(
        tmp_path / "project",
        groups={"g": ("Group", "Group")},
        participant_groups={"P1": "g", "P2": "g", "P3": "g"},
        participant_conditions={"P1": ("C1", "C2"), "P2": ("C1", "C2"), "P3": ("C1", "C3")},
    )
    headers, amplitudes = _install_reader_doubles(monkeypatch)
    plan = build_analysis_plan(root, group_ids=("g",), conditions=("C1", "C2", "C3"))
    with pytest.raises(FreeHarmonicInputError, match="at least two"):
        planned_analysis.prepare_analysis_plan(plan, FreeHarmonicMethodSpec(max_harmonic_hz=3.6))
    assert not headers and not amplitudes


def test_incomplete_comparison_list_is_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    root, _ = _write_project(
        tmp_path / "project",
        groups={"g": ("Group", "Group")},
        participant_groups={"P1": "g", "P2": "g"},
        participant_conditions={"P1": ("C1", "C2", "C3"), "P2": ("C1", "C2", "C3")},
    )
    _install_reader_doubles(monkeypatch)
    plan = build_analysis_plan(root, group_ids=("g",), conditions=("C1", "C2", "C3"))
    invalid = replace(plan, comparisons=plan.comparisons[:-1])
    with pytest.raises(FreeHarmonicInputError, match="complete canonical comparison list"):
        planned_analysis.prepare_analysis_plan(invalid, FreeHarmonicMethodSpec(max_harmonic_hz=3.6))


def test_seed_and_raw_inference_are_independent_of_correction_membership(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root, _ = _write_project(
        tmp_path / "project",
        groups={"g": ("Group", "Group")},
        participant_groups={f"P{i}": "g" for i in range(4)},
        participant_conditions={f"P{i}": ("C1", "C2", "C3") for i in range(4)},
    )

    def perturb(path: Path, frame: object) -> None:
        offset = int(path.name[1])
        # Distinct positive participant/sensor patterns avoid degenerate t maps.
        for column in ("1.200000_Hz", "2.400000_Hz", "3.600000_Hz"):
            if column in frame:
                frame[column] += (np.arange(64) % 7 + 1) * (offset + 1) * (0.1 if "C1" in path.name else 0.2)

    _install_reader_doubles(monkeypatch, mutate_frame=perturb)
    plan = build_analysis_plan(root, group_ids=("g",), conditions=("C1", "C2", "C3"))
    prepared = planned_analysis.prepare_analysis_plan(
        plan, FreeHarmonicMethodSpec(max_harmonic_hz=3.6, n_permutations=7)
    )
    original = planned_analysis.analyze_prepared_analysis_plan(prepared)
    modified_plan = replace(
        plan, comparisons=tuple(replace(row, family_id="test_regrouping") for row in plan.comparisons)
    )
    modified = planned_analysis.analyze_prepared_analysis_plan(replace(prepared, plan=modified_plan))
    for first, second in zip(original.outcomes, modified.outcomes, strict=True):
        assert first.derived_seed == second.derived_seed
        np.testing.assert_array_equal(first.result.observed_t, second.result.observed_t)
        assert first.global_p == second.global_p
