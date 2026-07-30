from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis import anova_compatibility as compatibility


PARTICIPANTS = tuple(f"P{index}" for index in range(1, 7))
CONDITIONS = ("A", "B")
ROIS = ("R1", "R2")
GROUPS = {
    participant: "control" if index <= 3 else "anxious"
    for index, participant in enumerate(PARTICIPANTS, start=1)
}


def _balanced_data(
    *,
    participants: tuple[str, ...] = PARTICIPANTS,
    conditions: tuple[str, ...] = CONDITIONS,
    rois: tuple[str, ...] = ROIS,
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for subject_index, participant in enumerate(participants):
        for condition_index, condition in enumerate(conditions):
            for roi_index, roi in enumerate(rois):
                group = GROUPS.get(
                    participant,
                    "control" if subject_index < len(participants) / 2 else "anxious",
                )
                rows.append(
                    {
                        "participant": participant,
                        "condition": condition,
                        "roi": roi,
                        "group_id": group,
                        "value": (
                            0.2 * subject_index
                            + 0.5 * condition_index
                            + 0.3 * roi_index
                            + 0.1 * subject_index * condition_index
                            + (0.6 if group == "anxious" else 0.0)
                        ),
                    }
                )
    return pd.DataFrame(rows)


def _single_backend_table(
    p_values: tuple[float, ...] = (0.01, 0.03, 0.20),
) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Effect": ["condition", "roi", "condition * roi"],
            "F Value": [8.0, 6.0, 2.0],
            "Num DF": [1.0, 1.0, 1.0],
            "Den DF": [5.0, 5.0, 5.0],
            "Pr > F": list(p_values),
            "p_raw_or_uncorrected": list(p_values),
            "p_reported": list(p_values),
            "p_correction": ["none_two_level_effect"] * 3,
            "inference_status": ["primary_uncorrected_two_level_effect"] * 3,
            "reportable": [True, True, True],
        }
    )


def _run_single(data: pd.DataFrame, **kwargs) -> compatibility.AnovaCompatibilityBundle:
    return compatibility.run_single_anova_compatibility(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        frozen_participants=kwargs.pop("frozen_participants", PARTICIPANTS),
        retained_conditions=kwargs.pop("retained_conditions", CONDITIONS),
        selected_rois=kwargs.pop("selected_rois", ROIS),
        **kwargs,
    )


def _run_multi(data: pd.DataFrame, **kwargs) -> compatibility.AnovaCompatibilityBundle:
    return compatibility.run_multigroup_anova_compatibility(
        data,
        dv_col="value",
        subject_col="participant",
        condition_col="condition",
        roi_col="roi",
        group_col="group_id",
        frozen_participants=kwargs.pop("frozen_participants", PARTICIPANTS),
        retained_conditions=kwargs.pop("retained_conditions", CONDITIONS),
        selected_rois=kwargs.pop("selected_rois", ROIS),
        canonical_group_ids=kwargs.pop("canonical_group_ids", GROUPS),
        group_pair=kwargs.pop("group_pair", ("anxious", "control")),
        **kwargs,
    )


def test_single_exact_grid_runs_secondary_holm_compatibility(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_backend(data, **kwargs):
        captured["data"] = data.copy()
        captured.update(kwargs)
        return _single_backend_table()

    monkeypatch.setattr(
        compatibility,
        "run_repeated_measures_anova",
        fake_backend,
    )

    bundle = _run_single(_balanced_data())
    results = bundle.results

    assert bundle.status == "completed"
    assert bundle.ran is True
    assert bundle.audit.eligible is True
    assert len(results) == 3
    assert results["effect"].tolist() == [
        "condition",
        "roi",
        "condition_roi_interaction",
    ]
    assert results["p_adjusted"].tolist() == pytest.approx(
        [0.03, 0.06, 0.20]
    )
    assert results["family_id"].eq(
        compatibility.ANOVA_COMPATIBILITY_FAMILY_ID
    ).all()
    assert results["family_size"].eq(3).all()
    assert results["planned_family_size"].eq(3).all()
    assert results["inference_role"].eq("compatibility").all()
    assert results["headline_eligible"].eq(False).all()
    assert results["analysis_label"].eq(
        compatibility.SINGLE_ANALYSIS_LABEL
    ).all()
    assert captured["within_cols"] == ["condition", "roi"]
    assert len(captured["data"]) == 24


@pytest.mark.parametrize(
    ("mutation", "audit_field"),
    [
        ("missing", "n_missing_cells"),
        ("nonfinite", "n_nonfinite_rows"),
        ("duplicate", "n_duplicate_cell_keys"),
        ("unexpected", "n_unexpected_rows"),
        ("missing_level", "n_missing_cells"),
    ],
)
def test_grid_defects_skip_without_calling_backend(
    monkeypatch,
    mutation: str,
    audit_field: str,
) -> None:
    data = _balanced_data()
    if mutation == "missing":
        data = data.iloc[1:].copy()
    elif mutation == "nonfinite":
        data.loc[0, "value"] = np.nan
    elif mutation == "duplicate":
        data = pd.concat([data, data.iloc[[0]]], ignore_index=True)
    elif mutation == "unexpected":
        extra = data.iloc[[0]].copy()
        extra["participant"] = "unexpected-participant"
        data = pd.concat([data, extra], ignore_index=True)
    elif mutation == "missing_level":
        data = data.loc[~data["condition"].eq("B")].copy()

    def fail_backend(*_args, **_kwargs):
        raise AssertionError("ineligible data reached the ANOVA backend")

    monkeypatch.setattr(
        compatibility,
        "run_repeated_measures_anova",
        fail_backend,
    )

    bundle = _run_single(data)

    assert bundle.status == "skipped"
    assert bundle.ran is False
    assert bundle.results.empty
    assert getattr(bundle.audit, audit_field) > 0
    frames = bundle.to_frames()
    assert "ANOVA Compatibility" not in frames
    assert frames["ANOVA Compatibility Status"].loc[
        0, "compatibility_status"
    ] == "skipped"


def test_constant_participant_remains_balance_eligible(monkeypatch) -> None:
    data = _balanced_data()
    data.loc[data["participant"].eq("P1"), "value"] = 1.0
    monkeypatch.setattr(
        compatibility,
        "run_repeated_measures_anova",
        lambda *_args, **_kwargs: _single_backend_table(),
    )

    bundle = _run_single(data)

    assert bundle.audit.eligible is True
    assert bundle.status == "completed"


def test_planned_family_does_not_shrink_when_effect_is_unavailable(
    monkeypatch,
) -> None:
    incomplete = _single_backend_table().iloc[:2].copy()
    monkeypatch.setattr(
        compatibility,
        "run_repeated_measures_anova",
        lambda *_args, **_kwargs: incomplete,
    )

    bundle = _run_single(_balanced_data())
    results = bundle.results

    assert bundle.status == "partial"
    assert results["family_size"].eq(3).all()
    assert results["planned_family_size"].eq(3).all()
    assert results["tested_family_size"].eq(2).all()
    assert results.loc[0, "p_adjusted"] == pytest.approx(0.03)
    unavailable = results.loc[
        results["effect"].eq("condition_roi_interaction")
    ].iloc[0]
    assert bool(unavailable["reportable"]) is False
    assert pd.isna(unavailable["p_adjusted"])


def test_multi_requires_equal_frozen_group_sizes_without_backend(
    monkeypatch,
) -> None:
    participants = PARTICIPANTS[:-1]
    assignments = {participant: GROUPS[participant] for participant in participants}
    data = _balanced_data(participants=participants)

    monkeypatch.setitem(sys.modules, "pingouin", None)
    bundle = _run_multi(
        data,
        frozen_participants=participants,
        canonical_group_ids=assignments,
    )

    assert bundle.status == "skipped"
    assert bundle.audit.equal_group_sizes is False
    assert "equal" in bundle.message.casefold()


def test_multi_rejects_row_group_mismatch_before_backend(monkeypatch) -> None:
    data = _balanced_data()
    data.loc[0, "group_id"] = "anxious"
    monkeypatch.setitem(sys.modules, "pingouin", None)

    bundle = _run_multi(data)

    assert bundle.status == "skipped"
    assert bundle.audit.n_group_mismatches == 1


def test_multi_cell_ids_are_opaque_stable_and_preserve_labels(
    monkeypatch,
) -> None:
    conditions = ("A | B", "C")
    rois = ("R_1", "R | 2")
    data = _balanced_data(conditions=conditions, rois=rois)
    monkeypatch.setitem(sys.modules, "pingouin", None)

    bundle = _run_multi(
        data,
        retained_conditions=conditions,
        selected_rois=rois,
    )
    mapping = bundle.response_cell_map

    assert mapping["response_cell_id"].tolist() == [
        "cell_001",
        "cell_002",
        "cell_003",
        "cell_004",
    ]
    assert list(zip(mapping["condition"], mapping["roi"], strict=True)) == [
        ("A | B", "R_1"),
        ("A | B", "R | 2"),
        ("C", "R_1"),
        ("C", "R | 2"),
    ]


def test_multi_pingouin_path_derives_interaction_gg_and_is_secondary(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    backend = pd.DataFrame(
        {
            "Source": [
                "_compat_group_id",
                "_response_cell_id",
                "Interaction",
            ],
            "F": [7.0, 8.0, 2.2],
            "DF1": [1.0, 3.0, 3.0],
            "DF2": [4.0, 12.0, 12.0],
            "p-unc": [0.04, 0.003, 0.14],
            "np2": [0.64, 0.67, 0.35],
            "eps": [np.nan, 0.8, np.nan],
        }
    )

    def fake_mixed_anova(**kwargs):
        captured.update(kwargs)
        return backend.copy()

    fake_pingouin = SimpleNamespace(
        mixed_anova=fake_mixed_anova,
        sphericity=lambda **_kwargs: SimpleNamespace(spher=False),
    )
    monkeypatch.setitem(sys.modules, "pingouin", fake_pingouin)

    bundle = _run_multi(_balanced_data())
    results = bundle.results

    assert bundle.status == "completed"
    assert results["effect"].tolist() == [
        "group",
        "response_cell",
        "group_response_cell_interaction",
    ]
    interaction = results.loc[
        results["effect"].eq("group_response_cell_interaction")
    ].iloc[0]
    expected_gg = compatibility.f_distribution.sf(
        2.2,
        0.8 * 3.0,
        0.8 * 12.0,
    )
    assert interaction["Pr > F (GG)"] == pytest.approx(expected_gg)
    assert (
        interaction["correction_source"]
        == "derived_from_response_cell_epsilon"
    )
    assert interaction["p_reported"] == pytest.approx(expected_gg)
    assert results["analysis_label"].eq(
        compatibility.MULTI_ANALYSIS_LABEL
    ).all()
    assert results["interpretation"].eq(
        compatibility.MULTI_LIMITATION
    ).all()
    assert results["inference_role"].eq("compatibility").all()
    assert results["headline_eligible"].eq(False).all()
    assert captured["correction"] is True
    assert captured["effsize"] == "np2"
    assert captured["within"] == "_response_cell_id"
    assert captured["between"] == "_compat_group_id"
    assert captured["subject"] == "_compat_subject_id"


def test_multi_backend_unavailable_is_nonfatal_skipped(monkeypatch) -> None:
    monkeypatch.setitem(sys.modules, "pingouin", None)

    bundle = _run_multi(_balanced_data())

    assert bundle.status == "skipped"
    assert bundle.audit.eligible is True
    assert bundle.status_code == "mixed_anova_backend_unavailable"
    assert "ANOVA Compatibility" not in bundle.to_frames()


def test_installed_pingouin_backend_returns_three_broad_effects() -> None:
    bundle = _run_multi(_balanced_data())

    assert bundle.ran is True
    assert bundle.status == "completed"
    assert bundle.results["effect"].tolist() == [
        "group",
        "response_cell",
        "group_response_cell_interaction",
    ]
