from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from Tools.Stats.analysis.repeated_session_analysis import RepeatedSessionDesignError
from Tools.Stats.analysis.repeated_session_contracts import (
    FIXED_ORDER_CONFOUNDING,
    SESSION_PHASE_AT_VISIT_TERM,
    RepeatedSessionInferenceContract,
)
from Tools.Stats.io.repeated_session_export import (
    REPEATED_SESSION_EXPORT_METADATA_SHEET,
    REPEATED_SESSION_EXPORT_SCHEMA_VERSION,
    REPEATED_SESSION_LONG_COLUMNS,
    REPEATED_SESSION_LONG_SHEET,
    REPEATED_SESSION_SCHEMA_SHEET,
    build_repeated_session_export_bundle,
    build_repeated_session_export_frames,
    build_repeated_session_long_frame,
)


def _contract() -> RepeatedSessionInferenceContract:
    return RepeatedSessionInferenceContract(
        group_ids=("birth_control", "control"),
        group_labels=("Birth control", "No birth control"),
        session_ids=("luteal", "follicular"),
        session_labels=("Luteal", "Follicular"),
    )


def _data() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "participant_id": "B1",
                "recording_id": "B1__luteal",
                "session_id": "luteal",
                "visit_index": 1,
                "group_id": "birth_control",
                "condition": "Angry",
                "roi": "Occipital",
                "summed_bca_uv": 1.0,
            },
            {
                "participant_id": "B1",
                "recording_id": "B1__follicular",
                "session_id": "follicular",
                "visit_index": 2,
                "days_from_baseline": 14,
                "group_id": "birth_control",
                "condition": "Angry",
                "roi": "Occipital",
                "summed_bca_uv": 1.4,
            },
            {
                "participant_id": "C1",
                "recording_id": "C1__luteal",
                "session_id": "luteal",
                "visit_index": 1,
                "group_id": "control",
                "condition": "Angry",
                "roi": "Occipital",
                "summed_bca_uv": np.nan,
                "qc_flag": True,
                "qc_notes": "Manual review flag",
                "excluded": True,
                "exclusion_reason": "Recording-condition QC exclusion",
            },
        ]
    )


def test_long_builder_carries_session_identity_qc_exclusion_and_pair_status() -> None:
    frame = build_repeated_session_long_frame(_data(), contract=_contract())

    assert tuple(frame.columns) == REPEATED_SESSION_LONG_COLUMNS
    assert len(frame) == 3
    complete = frame[frame["participant_id"].eq("B1")]
    assert complete["pair_status"].eq("complete_recording_pair").all()
    assert complete["pair_status_label"].str.contains(
        SESSION_PHASE_AT_VISIT_TERM,
        regex=False,
    ).all()
    assert list(complete["visit_index"]) == [1, 2]
    assert np.isnan(float(complete.iloc[0]["days_from_baseline"]))
    assert complete.iloc[1]["days_from_baseline"] == 14
    assert list(complete["session_label"]) == ["Luteal", "Follicular"]
    assert complete["group_label"].eq("Birth control").all()

    incomplete = frame[frame["participant_id"].eq("C1")].iloc[0]
    assert incomplete["pair_status"] == "missing_visit_2_recording"
    assert SESSION_PHASE_AT_VISIT_TERM in incomplete["pair_status_label"]
    assert bool(incomplete["qc_flag"])
    assert bool(incomplete["excluded"])
    assert incomplete["qc_notes"] == "Manual review flag"
    assert incomplete["exclusion_reason"] == "Recording-condition QC exclusion"
    assert np.isnan(float(incomplete["summed_bca_uv"]))


def test_export_bundle_has_explicit_schema_and_fixed_order_metadata() -> None:
    bundle = build_repeated_session_export_bundle(_data(), contract=_contract())
    frames = bundle.to_frames()

    assert set(frames) == {
        REPEATED_SESSION_LONG_SHEET,
        REPEATED_SESSION_SCHEMA_SHEET,
        REPEATED_SESSION_EXPORT_METADATA_SHEET,
    }
    schema = frames[REPEATED_SESSION_SCHEMA_SHEET]
    assert list(schema["column_name"]) == list(REPEATED_SESSION_LONG_COLUMNS)
    assert schema["export_schema_version"].eq(
        REPEATED_SESSION_EXPORT_SCHEMA_VERSION
    ).all()
    assert list(schema["column_order"]) == list(
        range(1, len(REPEATED_SESSION_LONG_COLUMNS) + 1)
    )
    label_description = schema.loc[
        schema["column_name"].eq("pair_status_label"),
        "description",
    ].iloc[0]
    assert SESSION_PHASE_AT_VISIT_TERM in label_description

    metadata = frames[REPEATED_SESSION_EXPORT_METADATA_SHEET].iloc[0]
    assert metadata["repeated_session_export_schema_version"] == (
        REPEATED_SESSION_EXPORT_SCHEMA_VERSION
    )
    assert metadata["n_participants"] == 2
    assert metadata["n_recordings"] == 3
    assert metadata["n_complete_recording_pairs"] == 1
    assert metadata["n_participants_with_missing_recording"] == 1
    assert metadata["missing_values_imputed"] == False  # noqa: E712
    assert metadata["fixed_order_confounding"] == FIXED_ORDER_CONFOUNDING
    assert "rows are not dropped" in metadata["qc_policy"]

    direct_frames = build_repeated_session_export_frames(
        _data(),
        contract=_contract(),
    )
    pd.testing.assert_frame_equal(
        direct_frames[REPEATED_SESSION_LONG_SHEET],
        bundle.long_data,
    )


def test_export_hard_fails_recording_reuse_and_unexplained_exclusion() -> None:
    reused = _data()
    reused.loc[reused["participant_id"].eq("C1"), "recording_id"] = "B1__luteal"
    with pytest.raises(RepeatedSessionDesignError, match="recording_id must belong"):
        build_repeated_session_long_frame(reused, contract=_contract())

    unexplained = _data()
    unexplained.loc[unexplained["participant_id"].eq("C1"), "exclusion_reason"] = ""
    with pytest.raises(RepeatedSessionDesignError, match="exclusion_reason"):
        build_repeated_session_long_frame(unexplained, contract=_contract())


def test_export_fills_contract_labels_and_defaults_without_imputing_dv() -> None:
    data = _data().drop(
        columns=["qc_flag", "qc_notes", "excluded", "exclusion_reason"],
        errors="ignore",
    )
    frame = build_repeated_session_long_frame(data, contract=_contract())

    assert set(frame.loc[frame["group_id"].eq("birth_control"), "group_label"]) == {
        "Birth control"
    }
    assert set(frame.loc[frame["group_id"].eq("control"), "group_label"]) == {
        "No birth control"
    }
    assert frame["qc_flag"].eq(False).all()
    assert frame["excluded"].eq(False).all()
    assert frame["qc_notes"].eq("").all()
    assert frame["exclusion_reason"].eq("").all()
    control_value = frame.loc[
        frame["participant_id"].eq("C1"),
        "summed_bca_uv",
    ].iloc[0]
    assert np.isnan(float(control_value))
