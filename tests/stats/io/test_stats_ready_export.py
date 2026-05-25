from __future__ import annotations

import pandas as pd
import pytest

from Tools.Stats.io import stats_ready_export as export_mod
from Tools.Stats.io.stats_ready_export import (
    HARMONIC_SELECTION_SHEET,
    LONG_FORMAT_SHEET,
    WIDE_FORMAT_SHEET,
    build_stats_ready_frames,
    prepare_stats_ready_export,
)
from Tools.Stats.analysis.dv_policy_settings import (
    FIXED_PREDEFINED_POLICY_ID,
    FIXED_PREDEFINED_POLICY_NAME,
    GROUP_SIGNIFICANT_POLICY_ID,
    GROUP_SIGNIFICANT_POLICY_NAME,
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
        "policy_name": FIXED_PREDEFINED_POLICY_NAME,
        "fixed_predefined_harmonics": {
            "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
            "harmonic_policy_label": (
                "Fixed predefined harmonic list applied uniformly across participants, "
                "conditions, and ROIs"
            ),
            "fixed_harmonic_included_frequencies_hz": [6.0, 12.0],
            "excluded_base_overlap_frequencies_hz": [],
            "selection_rows": [],
            "snr_used_for_statistics": False,
            "applied_uniformly_across_participants": True,
            "applied_uniformly_across_conditions": True,
            "applied_uniformly_across_rois": True,
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
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        group_map={"S1": "Control", "S2": "Clinical"},
    )

    long_df = frames[LONG_FORMAT_SHEET]
    assert len(long_df) == 8
    row = long_df[
        (long_df["subject_id"] == "S2")
        & (long_df["condition"] == "Object")
        & (long_df["roi"] == "Frontal")
    ].iloc[0]
    assert row["group_id"] == "Clinical"
    assert row["summed_bca_uv"] == pytest.approx(3.5)
    assert list(long_df.columns) == [
        "subject_id",
        "group_id",
        "condition",
        "roi",
        "summed_bca_uv",
    ]

    wide_df = frames[WIDE_FORMAT_SHEET]
    assert list(wide_df.columns) == [
        "subject_id",
        "group_id",
        "Face__Occipital",
        "Face__Frontal",
        "Object__Occipital",
        "Object__Frontal",
    ]
    s1_wide = wide_df[wide_df["subject_id"] == "S1"].iloc[0]
    assert s1_wide["Object__Occipital"] == pytest.approx(2.0)
    assert set(frames) == {
        LONG_FORMAT_SHEET,
        WIDE_FORMAT_SHEET,
        HARMONIC_SELECTION_SHEET,
    }


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
            dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
            group_map={"S1": "Control"},
        )


def test_build_stats_ready_frames_exports_fixed_predefined_metadata():
    subjects, conditions, rois, subject_data, summed_bca, provenance, _dv_metadata = _fixture_inputs()
    fixed_meta = {
        "harmonic_policy": FIXED_PREDEFINED_POLICY_ID,
        "harmonic_policy_label": "Fixed predefined harmonic list applied uniformly across participants, conditions, and ROIs",
        "fixed_harmonic_included_frequencies_hz": [1.2, 2.4, 3.6, 4.8, 7.2],
        "excluded_base_overlap_frequencies_hz": [6.0],
        "base_frequency_hz": 6.0,
        "oddball_frequency_hz": 1.2,
        "base_overlap_exclusion_enabled": True,
        "base_overlap_tolerance_hz": 0.01,
        "matching_tolerance_hz": 0.01,
        "frequency_resolution_hz": 1.2,
        "applied_uniformly_across_participants": True,
        "applied_uniformly_across_conditions": True,
        "applied_uniformly_across_rois": True,
        "snr_used_for_statistics": False,
        "bca_negative_values_retained": True,
        "bca_near_zero_values_retained": True,
        "selection_rows": [
            {
                "requested_frequency_hz": 1.2,
                "matched_frequency_hz": 1.2,
                "matched_column": "1.2000_Hz",
                "matched_bin_index": 1,
                "included": True,
                "exclusion_reason": "",
                "warning": "",
            },
            {
                "requested_frequency_hz": 6.0,
                "matched_frequency_hz": None,
                "matched_column": None,
                "matched_bin_index": None,
                "included": False,
                "exclusion_reason": "base_rate_overlap",
                "warning": "Base-rate overlap excluded.",
            },
        ],
    }
    frames = build_stats_ready_frames(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        summed_bca=summed_bca,
        provenance_map=provenance,
        dv_metadata={
            "policy_name": FIXED_PREDEFINED_POLICY_NAME,
            "fixed_predefined_harmonics": fixed_meta,
        },
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
        group_map={},
    )

    long_df = frames[LONG_FORMAT_SHEET]
    assert "selected_harmonics_hz" not in long_df.columns
    assert "selection_scope" not in long_df.columns
    assert "selection_z_scores" not in long_df.columns
    assert "source_workbook" not in long_df.columns

    selection_df = frames[HARMONIC_SELECTION_SHEET]
    assert list(selection_df.columns) == [
        "harmonic_policy",
        "selection_scope",
        "base_frequency_hz",
        "oddball_frequency_hz",
        "z_threshold",
        "requested_harmonic_hz",
        "harmonic_hz",
        "z_score",
        "selected",
        "excluded_base_rate",
        "exclusion_reason",
    ]
    selected_row = selection_df[selection_df["requested_harmonic_hz"] == 1.2].iloc[0]
    excluded_row = selection_df[selection_df["requested_harmonic_hz"] == 6.0].iloc[0]
    assert bool(selected_row["selected"]) is True
    assert selected_row["base_frequency_hz"] == pytest.approx(6.0)
    assert selected_row["oddball_frequency_hz"] == pytest.approx(1.2)
    assert excluded_row["exclusion_reason"] == "base_rate_overlap"


def test_build_stats_ready_frames_exports_group_significant_metadata():
    subjects, conditions, rois, subject_data, summed_bca, provenance, _dv_metadata = _fixture_inputs()
    group_meta = {
        "harmonic_policy": GROUP_SIGNIFICANT_POLICY_ID,
        "harmonic_policy_label": "Group-level significant oddball harmonics from a grand-averaged amplitude spectrum",
        "selected_harmonics_hz": [1.2, 3.6, 7.2],
        "selection_z_by_harmonic": {1.2: 5.1, 2.4: 0.4, 3.6: 4.2, 6.0: 9.0, 7.2: 3.1},
        "excluded_base_harmonics_hz": [6.0],
        "selection_scope": "group_level_all_scalp_electrodes_all_selected_conditions",
        "selection_source_sheet": "FullFFT Amplitude (uV)",
        "selection_amplitude_summary": "grand_average_raw_amplitude_spectrum",
        "z_threshold": 2.32,
        "z_score_source": "computed_from_grand_averaged_amplitude_spectrum",
        "noise_window_bins": 10,
        "base_frequency_hz": 6.0,
        "oddball_frequency_hz": 1.2,
        "base_overlap_exclusion_enabled": True,
        "base_overlap_tolerance_hz": 0.01,
        "matching_tolerance_hz": 0.01,
        "frequency_resolution_hz": 0.6,
        "selection_conditions": ["Face", "Object"],
        "selection_spectra_count": 4,
        "selection_electrode_count": 3,
        "applied_uniformly_across_participants": True,
        "applied_uniformly_across_conditions": True,
        "applied_uniformly_across_rois": True,
        "snr_used_for_statistics": False,
        "bca_negative_values_retained": True,
        "bca_near_zero_values_retained": True,
        "selection_rows": [
            {
                "harmonic_index": 1,
                "target_frequency_hz": 1.2,
                "matched_frequency_hz": 1.2,
                "matched_column": "1.2000_Hz",
                "matched_bin_index": 2,
                "z_score": 5.1,
                "selected": True,
                "excluded_base_rate": False,
                "exclusion_reason": "",
                "warning": "",
            },
            {
                "harmonic_index": 5,
                "target_frequency_hz": 6.0,
                "matched_frequency_hz": 6.0,
                "matched_column": "6.0000_Hz",
                "matched_bin_index": 10,
                "z_score": None,
                "selected": False,
                "excluded_base_rate": True,
                "exclusion_reason": "base_rate_overlap",
                "warning": "Base-rate overlap excluded from oddball summation.",
            },
        ],
    }
    frames = build_stats_ready_frames(
        subjects=subjects,
        conditions=conditions,
        subject_data=subject_data,
        rois=rois,
        summed_bca=summed_bca,
        provenance_map=provenance,
        dv_metadata={
            "policy_name": GROUP_SIGNIFICANT_POLICY_NAME,
            "group_significant_harmonics": group_meta,
        },
        dv_policy={"name": GROUP_SIGNIFICANT_POLICY_NAME},
        group_map={},
    )

    long_df = frames[LONG_FORMAT_SHEET]
    assert list(long_df.columns) == [
        "subject_id",
        "group_id",
        "condition",
        "roi",
        "summed_bca_uv",
    ]

    selection_df = frames[HARMONIC_SELECTION_SHEET]
    selected_row = selection_df[selection_df["requested_harmonic_hz"] == 1.2].iloc[0]
    excluded_row = selection_df[selection_df["requested_harmonic_hz"] == 6.0].iloc[0]
    assert selected_row["harmonic_policy"] == GROUP_SIGNIFICANT_POLICY_ID
    assert bool(selected_row["selected"]) is True
    assert selected_row["z_threshold"] == pytest.approx(2.32)
    assert excluded_row["exclusion_reason"] == "base_rate_overlap"


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
                "policy_name": FIXED_PREDEFINED_POLICY_NAME,
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
        dv_policy={"name": FIXED_PREDEFINED_POLICY_NAME},
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
        assert workbook.sheet_names == [
            LONG_FORMAT_SHEET,
            WIDE_FORMAT_SHEET,
            HARMONIC_SELECTION_SHEET,
        ]
        assert WIDE_FORMAT_SHEET in workbook.sheet_names
        roundtrip = pd.read_excel(workbook, sheet_name=LONG_FORMAT_SHEET)

    assert len(roundtrip) == 8
    assert set(roundtrip["group_id"]) == {"single_group"}
