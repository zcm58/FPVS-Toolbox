"""Workbook-ready long-format export frames for repeated-session Stats data."""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from Tools.Stats.analysis.repeated_session_analysis import (
    prepare_repeated_session_data,
)
from Tools.Stats.analysis.repeated_session_contracts import (
    FIXED_ORDER_CONFOUNDING,
    SESSION_PHASE_AT_VISIT_TERM,
    RepeatedSessionInferenceContract,
)


REPEATED_SESSION_EXPORT_SCHEMA_VERSION = "1.0.0"
REPEATED_SESSION_LONG_SHEET = "Repeated Session Long"
REPEATED_SESSION_SCHEMA_SHEET = "Repeated Session Schema"
REPEATED_SESSION_EXPORT_METADATA_SHEET = "Session Export Metadata"
REPEATED_SESSION_LONG_COLUMNS: tuple[str, ...] = (
    "participant_id",
    "recording_id",
    "session_id",
    "session_label",
    "visit_index",
    "days_from_baseline",
    "group_id",
    "group_label",
    "condition",
    "roi",
    "summed_bca_uv",
    "qc_flag",
    "qc_notes",
    "excluded",
    "exclusion_reason",
    "pair_status",
    "pair_status_label",
)

_COLUMN_SCHEMA: tuple[tuple[str, str, bool, str], ...] = (
    ("participant_id", "string", False, "Stable person and pairing identity."),
    ("recording_id", "string", False, "Stable recording and derivative identity."),
    ("session_id", "string", False, "Stable within-participant session identity."),
    (
        "session_label",
        "string",
        False,
        f"Display label for the {SESSION_PHASE_AT_VISIT_TERM} session.",
    ),
    ("visit_index", "integer", False, "Ordered visit index; version 1 uses visits 1 and 2."),
    (
        "days_from_baseline",
        "number",
        True,
        "Recorded interval from visit 1 in days; retained as provenance, not a model covariate.",
    ),
    ("group_id", "string", False, "Stable between-participant group identity."),
    ("group_label", "string", False, "Human-readable group display label."),
    ("condition", "string", False, "Task Condition identity."),
    ("roi", "string", False, "Region-of-interest identity."),
    ("summed_bca_uv", "number", True, "Summed baseline-corrected amplitude in microvolts."),
    ("qc_flag", "boolean", False, "Whether the row carries a QC flag."),
    ("qc_notes", "string", True, "QC detail retained for audit."),
    ("excluded", "boolean", False, "Whether the row is excluded from inference."),
    ("exclusion_reason", "string", True, "Explicit reason for an inferential exclusion."),
    ("pair_status", "string", False, "Machine-readable recording-pair coverage code."),
    (
        "pair_status_label",
        "string",
        False,
        f"Human-readable {SESSION_PHASE_AT_VISIT_TERM} recording-pair status.",
    ),
)


@dataclass(frozen=True, slots=True)
class RepeatedSessionExportBundle:
    """Canonical long data plus its explicit schema and contract metadata."""

    long_data: pd.DataFrame
    schema: pd.DataFrame
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        return {
            REPEATED_SESSION_LONG_SHEET: self.long_data.copy(),
            REPEATED_SESSION_SCHEMA_SHEET: self.schema.copy(),
            REPEATED_SESSION_EXPORT_METADATA_SHEET: self.metadata.copy(),
        }


def repeated_session_schema_frame() -> pd.DataFrame:
    """Return a stable, machine-readable description of every long column."""

    return pd.DataFrame(
        [
            {
                "export_schema_version": REPEATED_SESSION_EXPORT_SCHEMA_VERSION,
                "column_order": order,
                "column_name": column,
                "data_type": data_type,
                "nullable": nullable,
                "description": description,
            }
            for order, (column, data_type, nullable, description) in enumerate(
                _COLUMN_SCHEMA,
                start=1,
            )
        ]
    )


def _pair_status_by_participant(
    data: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
) -> dict[str, tuple[str, str]]:
    first_session, second_session = contract.session_ids
    first_label, second_label = contract.session_labels
    result: dict[str, tuple[str, str]] = {}
    for participant, rows in data.groupby("participant_id", sort=False):
        observed = set(rows["session_id"])
        if first_session in observed and second_session in observed:
            value = (
                "complete_recording_pair",
                f"Complete {SESSION_PHASE_AT_VISIT_TERM} recording pair",
            )
        elif first_session in observed:
            value = (
                "missing_visit_2_recording",
                f"Missing visit 2 {SESSION_PHASE_AT_VISIT_TERM} recording ({second_label})",
            )
        else:
            value = (
                "missing_visit_1_recording",
                f"Missing visit 1 {SESSION_PHASE_AT_VISIT_TERM} recording ({first_label})",
            )
        result[str(participant)] = value
    return result


def build_repeated_session_long_frame(
    data: pd.DataFrame,
    *,
    contract: RepeatedSessionInferenceContract,
) -> pd.DataFrame:
    """Build the canonical session-aware long frame without dropping QC rows."""

    normalized = prepare_repeated_session_data(data, contract)
    status_map = _pair_status_by_participant(normalized, contract)
    normalized["pair_status"] = normalized["participant_id"].map(
        lambda participant: status_map[str(participant)][0]
    )
    normalized["pair_status_label"] = normalized["participant_id"].map(
        lambda participant: status_map[str(participant)][1]
    )
    normalized = normalized.sort_values(
        ["participant_id", "visit_index", "condition", "roi"],
        kind="stable",
    ).reset_index(drop=True)
    return normalized.loc[:, REPEATED_SESSION_LONG_COLUMNS]


def build_repeated_session_export_bundle(
    data: pd.DataFrame,
    *,
    contract: RepeatedSessionInferenceContract,
) -> RepeatedSessionExportBundle:
    """Return all additive frames needed by a future workbook writer."""

    long_data = build_repeated_session_long_frame(data, contract=contract)
    metadata = contract.to_metadata()
    metadata.update(
        {
            "repeated_session_export_schema_version": (
                REPEATED_SESSION_EXPORT_SCHEMA_VERSION
            ),
            "format": "long",
            "row_grain": (
                "participant x recording x session x Condition x ROI"
            ),
            "n_rows": len(long_data),
            "n_participants": int(long_data["participant_id"].nunique()),
            "n_recordings": int(long_data["recording_id"].nunique()),
            "n_complete_recording_pairs": int(
                long_data.loc[
                    long_data["pair_status"].eq("complete_recording_pair"),
                    "participant_id",
                ].nunique()
            ),
            "n_participants_with_missing_recording": int(
                long_data.loc[
                    ~long_data["pair_status"].eq("complete_recording_pair"),
                    "participant_id",
                ].nunique()
            ),
            "qc_policy": (
                "QC flags and exclusions are retained as columns; rows are not "
                "dropped by the export builder"
            ),
            "missing_values_imputed": False,
            "fixed_order_confounding": FIXED_ORDER_CONFOUNDING,
        }
    )
    return RepeatedSessionExportBundle(
        long_data=long_data,
        schema=repeated_session_schema_frame(),
        metadata=pd.DataFrame([metadata]),
    )


def build_repeated_session_export_frames(
    data: pd.DataFrame,
    *,
    contract: RepeatedSessionInferenceContract,
) -> dict[str, pd.DataFrame]:
    """Return additive workbook-ready frames without changing legacy exports."""

    return build_repeated_session_export_bundle(data, contract=contract).to_frames()


__all__ = [
    "REPEATED_SESSION_EXPORT_METADATA_SHEET",
    "REPEATED_SESSION_EXPORT_SCHEMA_VERSION",
    "REPEATED_SESSION_LONG_COLUMNS",
    "REPEATED_SESSION_LONG_SHEET",
    "REPEATED_SESSION_SCHEMA_SHEET",
    "RepeatedSessionExportBundle",
    "build_repeated_session_export_bundle",
    "build_repeated_session_export_frames",
    "build_repeated_session_long_frame",
    "repeated_session_schema_frame",
]
