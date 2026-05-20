from __future__ import annotations

import pandas as pd
import pytest

from Tools.Stats.io import stats_ready_export as export_mod
from Tools.Stats.io.stats_ready_export import (
    DATA_DICTIONARY_SHEET,
    JASP_RM_ANOVA_SHEET,
    RSTUDIO_LONG_SHEET,
    SAS_LONG_SHEET,
    build_stats_ready_frames,
    prepare_stats_ready_export,
)


def _fixture_inputs():
    subjects = ["S1", "S2"]
    conditions = ["Face", "Object"]
    rois = {"Occipital": ["Oz"], "Frontal": ["Fz"]}
    subject_data = {
        "S1": {"Face": "S1_Face.xlsx", "Object": "S1_Object.xlsx"},
        "S2": {"Face": "S2_Face.xlsx", "Object": "S2_Object.xlsx"},
    }
    summed_bca = {
        "S1": {
            "Face": {"Occipital": 1.0, "Frontal": 0.5},
            "Object": {"Occipital": 2.0, "Frontal": 1.5},
        },
        "S2": {
            "Face": {"Occipital": 3.0, "Frontal": 2.5},
            "Object": {"Occipital": 4.0, "Frontal": 3.5},
        },
    }
    provenance = {
        (subject, condition, roi): {
            "source_file": subject_data[subject][condition],
            "col_label": ["6_Hz", "12_Hz"],
        }
        for subject in subjects
        for condition in conditions
        for roi in rois
    }
    dv_metadata = {
        "policy_name": "Rossion",
        "empty_list_policy": "fallback_fixed_k",
        "rossion_method": {
            "union_harmonics_by_roi": {
                "Occipital": [6.0, 12.0],
                "Frontal": [18.0],
            },
            "fallback_info_by_roi": {
                "Occipital": {
                    "policy": "fallback_fixed_k",
                    "fallback_used": False,
                },
                "Frontal": {
                    "policy": "fallback_fixed_k",
                    "fallback_used": True,
                },
            },
        },
    }
    return subjects, conditions, rois, subject_data, summed_bca, provenance, dv_metadata


def test_build_stats_ready_frames_preserves_canonical_long_and_group_data():
    subjects, conditions, rois, subject_data, summed_bca, provenance, dv_metadata = _fixture_inputs()

    frames = build_stats_ready_frames(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        summed_bca=summed_bca,
        provenance_map=provenance,
        dv_metadata=dv_metadata,
        dv_policy={"name": "Rossion"},
        group_map={"S1": "Control", "S2": "Clinical"},
    )

    long_df = frames[RSTUDIO_LONG_SHEET]
    assert len(long_df) == 8
    row = long_df[
        (long_df["subject_id"] == "S2")
        & (long_df["condition"] == "Object")
        & (long_df["roi"] == "Frontal")
    ].iloc[0]
    assert row["subject_uid"] == "S2"
    assert row["group_id"] == "Clinical"
    assert row["summed_bca_uv"] == pytest.approx(3.5)
    assert row["selected_harmonics_hz"] == "18"
    assert bool(row["fallback_used"]) is True
    assert row["source_workbook"] == "S2_Object.xlsx"

    sas_df = frames[SAS_LONG_SHEET]
    assert "condition_n" in sas_df.columns
    assert "harmonics_hz" in sas_df.columns
    assert "empty_harmonic_policy" not in sas_df.columns

    jasp_df = frames[JASP_RM_ANOVA_SHEET]
    assert list(jasp_df.columns) == [
        "subject_uid",
        "subject_id",
        "group_id",
        "Face__Occipital",
        "Face__Frontal",
        "Object__Occipital",
        "Object__Frontal",
    ]
    s1_wide = jasp_df[jasp_df["subject_uid"] == "S1"].iloc[0]
    assert s1_wide["Object__Occipital"] == pytest.approx(2.0)

    dictionary = frames[DATA_DICTIONARY_SHEET]
    assert "Object__Frontal" in set(dictionary["column"])


def test_build_stats_ready_frames_requires_complete_group_labels_when_groups_exist():
    subjects, conditions, rois, subject_data, summed_bca, provenance, dv_metadata = _fixture_inputs()

    with pytest.raises(RuntimeError, match="Group labels are missing"):
        build_stats_ready_frames(
            subjects=subjects,
            conditions=conditions,
            subject_data=subject_data,
            rois=rois,
            summed_bca=summed_bca,
            provenance_map=provenance,
            dv_metadata=dv_metadata,
            dv_policy={"name": "Rossion"},
            group_map={"S1": "Control"},
        )


def test_prepare_stats_ready_export_reuses_summed_bca_facade_and_writes_workbook(
    tmp_path,
    monkeypatch,
):
    subjects, conditions, rois, subject_data, summed_bca, provenance, _dv_metadata = _fixture_inputs()
    captured: dict[str, object] = {}

    def fake_prepare_summed_bca_data(**kwargs):
        captured.update(kwargs)
        kwargs["provenance_map"].update(provenance)
        kwargs["dv_metadata"].update(
            {
                "policy_name": "Fixed-K",
                "empty_list_policy": "fallback_fixed_k",
            }
        )
        return summed_bca

    monkeypatch.setattr(
        export_mod,
        "prepare_summed_bca_data",
        fake_prepare_summed_bca_data,
    )

    target = tmp_path / "Stats_Ready_Summed_BCA.xlsx"
    result = prepare_stats_ready_export(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        base_freq=6.0,
        rois=rois,
        dv_policy={"name": "Fixed-K", "fixed_k": 2},
        group_map={},
        log_func=lambda _message: None,
        save_path=target,
        max_freq=16.8,
    )

    assert captured["base_freq"] == 6.0
    assert captured["max_freq"] == 16.8
    assert result.workbook_path == target
    assert result.row_count == 8

    with pd.ExcelFile(target, engine="openpyxl") as workbook:
        assert RSTUDIO_LONG_SHEET in workbook.sheet_names
        assert SAS_LONG_SHEET in workbook.sheet_names
        assert JASP_RM_ANOVA_SHEET in workbook.sheet_names
        roundtrip = pd.read_excel(workbook, sheet_name=RSTUDIO_LONG_SHEET)

    assert len(roundtrip) == 8
    assert set(roundtrip["group_id"]) == {"single_group"}
