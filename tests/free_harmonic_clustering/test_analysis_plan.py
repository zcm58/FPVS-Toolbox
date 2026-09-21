from dataclasses import replace
from pathlib import Path

import pytest

from Tools.Free_Harmonic_Clustering.analysis_plan import AnalysisFamily, build_analysis_plan
from Tools.Free_Harmonic_Clustering.planned_analysis import derive_planned_comparison_seed
from Tools.Free_Harmonic_Clustering.models import FreeHarmonicInputError
from tests.free_harmonic_clustering.test_inputs import _write_project, _write_repeated_project


def test_repeated_families_have_stable_comparison_identity(tmp_path: Path) -> None:
    root = _write_repeated_project(
        tmp_path / "project",
        participants_by_group={"bc_group": ("A1", "A2"), "control_group": ("B1", "B2")},
        conditions=("C1", "C2", "C3", "C4"),
    )
    plan = build_analysis_plan(
        root,
        group_ids=("bc_group", "control_group"),
        conditions=("C1", "C2", "C3", "C4"),
        session_ids=("luteal_phase", "follicular_phase"),
    )
    counts = {family.value: sum(row.family_id == family.value for row in plan.comparisons) for family in plan.families}
    assert counts == {"between_groups": 4, "within_group_visits": 8, "group_visit_change": 4}
    comparison = plan.comparisons[0]
    regrouped = replace(comparison, family_id="different_family")
    assert derive_planned_comparison_seed(17, comparison.comparison_id) == derive_planned_comparison_seed(
        17, regrouped.comparison_id
    )
    subset = build_analysis_plan(
        root,
        group_ids=plan.group_ids,
        conditions=("C1",),
        session_ids=plan.session_ids,
        families=(AnalysisFamily.BETWEEN_GROUPS,),
    )
    assert subset.comparisons[0].comparison_id == comparison.comparison_id


def test_reversed_condition_pair_is_not_an_additional_test(tmp_path: Path) -> None:
    root, _ = _write_project(
        tmp_path / "project",
        groups={"g": ("Group", "Group")},
        participant_groups={"P1": "g", "P2": "g"},
        participant_conditions={"P1": ("C1", "C2"), "P2": ("C1", "C2")},
    )
    with pytest.raises(FreeHarmonicInputError, match="reversed duplicates"):
        build_analysis_plan(
            root, group_ids=("g",), conditions=("C1", "C2"), condition_pairs=(("C1", "C2"), ("C2", "C1"))
        )
