"""Pure complete-pair backend for versioned repeated-session FPVS inference.

The primary outcome is a participant delta (visit 2 minus visit 1) within each
declared Condition x ROI cell.  Primary inference compares those deltas between
the two stable participant groups with Welch's t-test.  Secondary inference
tests the paired delta within each group.  Missing sessions and unusable cells
remain explicit audit rows; this module never imputes or selects a fallback
test.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats

from Tools.Stats.analysis.inference_contracts import FamilySpec
from Tools.Stats.analysis.multiple_comparisons import apply_family_correction
from Tools.Stats.analysis.repeated_session_contracts import (
    FIXED_ORDER_CONFOUNDING,
    SESSION_PHASE_AT_VISIT_TERM,
    RepeatedSessionInferenceContract,
)


REPEATED_SESSION_ANALYSIS_SCHEMA_VERSION = "1.0.0"
REPEATED_SESSION_CORE_COLUMNS: tuple[str, ...] = (
    "participant_id",
    "recording_id",
    "session_id",
    "visit_index",
    "group_id",
    "condition",
    "roi",
    "summed_bca_uv",
)
REPEATED_SESSION_NORMALIZED_COLUMNS: tuple[str, ...] = (
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
)

PRIMARY_RESULTS_SHEET = "Repeated Session Primary"
SECONDARY_RESULTS_SHEET = "Repeated Session Secondary"
PAIR_DELTAS_SHEET = "Repeated Session Deltas"
PARTICIPANT_SESSION_AUDIT_SHEET = "Participant Session Audit"
OUTCOME_PAIR_AUDIT_SHEET = "Outcome Pair Audit"
PAIR_COVERAGE_SHEET = "Session Pair Coverage"
ANALYSIS_METADATA_SHEET = "Repeated Session Metadata"


class RepeatedSessionDesignError(ValueError):
    """Raised when repeated-session identity or row grain is ambiguous."""


@dataclass(frozen=True, slots=True)
class RepeatedSessionOutcome:
    """One explicitly declared Condition x ROI outcome."""

    condition: str
    roi: str
    outcome_id: str | None = None

    def __post_init__(self) -> None:
        condition = str(self.condition).strip()
        roi = str(self.roi).strip()
        outcome_id = str(self.outcome_id or f"{condition}::{roi}").strip()
        if not condition or not roi or not outcome_id:
            raise ValueError("Condition, ROI, and outcome_id must be non-empty.")
        object.__setattr__(self, "condition", condition)
        object.__setattr__(self, "roi", roi)
        object.__setattr__(self, "outcome_id", outcome_id)


@dataclass(frozen=True, slots=True)
class RepeatedSessionDesignAudit:
    """Complete-pair and missing-session audit for declared outcomes."""

    normalized_data: pd.DataFrame
    participant_sessions: pd.DataFrame
    outcome_pairs: pd.DataFrame
    pair_deltas: pd.DataFrame
    coverage: pd.DataFrame
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        return {
            PARTICIPANT_SESSION_AUDIT_SHEET: self.participant_sessions.copy(),
            OUTCOME_PAIR_AUDIT_SHEET: self.outcome_pairs.copy(),
            PAIR_DELTAS_SHEET: self.pair_deltas.copy(),
            PAIR_COVERAGE_SHEET: self.coverage.copy(),
        }


@dataclass(frozen=True, slots=True)
class RepeatedSessionAnalysisResult:
    """Primary, secondary, and audit frames for one repeated-session run."""

    primary_results: pd.DataFrame
    secondary_results: pd.DataFrame
    audit: RepeatedSessionDesignAudit
    metadata: pd.DataFrame

    def to_frames(self) -> dict[str, pd.DataFrame]:
        frames = {
            PRIMARY_RESULTS_SHEET: self.primary_results.copy(),
            SECONDARY_RESULTS_SHEET: self.secondary_results.copy(),
            ANALYSIS_METADATA_SHEET: self.metadata.copy(),
        }
        frames.update(self.audit.to_frames())
        return frames


def _normalize_identifier_column(frame: pd.DataFrame, column: str) -> None:
    raw = frame[column]
    normalized = raw.map(lambda value: "" if pd.isna(value) else str(value).strip())
    if bool(normalized.eq("").any()):
        raise RepeatedSessionDesignError(f"{column} values must be non-empty.")
    display_by_key: dict[str, str] = {}
    for value in normalized:
        display_by_key.setdefault(value.casefold(), value)
    frame[column] = normalized.map(lambda value: display_by_key[value.casefold()])


def _canonicalize_contract_ids(
    frame: pd.DataFrame,
    column: str,
    canonical_values: Sequence[str],
) -> None:
    lookup = {value.casefold(): value for value in canonical_values}
    raw = frame[column].map(lambda value: "" if pd.isna(value) else str(value).strip())
    unknown = sorted(
        {value for value in raw if not value or value.casefold() not in lookup},
        key=str.casefold,
    )
    if unknown:
        rendered = ", ".join(repr(value) for value in unknown)
        raise RepeatedSessionDesignError(
            f"{column} must use the two IDs declared by the inference contract; "
            f"unknown value(s): {rendered}."
        )
    frame[column] = raw.map(lambda value: lookup[value.casefold()])


def _coerce_boolean(value: object, *, column: str) -> bool:
    if value is None or bool(pd.isna(value)):
        return False
    if isinstance(value, (bool, np.bool_)):
        return bool(value)
    if isinstance(value, (int, np.integer)) and int(value) in (0, 1):
        return bool(value)
    text = str(value).strip().casefold()
    if text in {"true", "yes", "y", "1"}:
        return True
    if text in {"false", "no", "n", "0", ""}:
        return False
    raise RepeatedSessionDesignError(
        f"{column} must contain boolean/yes-no values; got {value!r}."
    )


def _label_column(
    frame: pd.DataFrame,
    *,
    id_column: str,
    label_column: str,
    expected: Mapping[str, str],
) -> None:
    expected_by_key = {key.casefold(): value for key, value in expected.items()}
    if label_column not in frame.columns:
        frame[label_column] = frame[id_column].map(expected)
        return
    raw = frame[label_column].map(
        lambda value: "" if pd.isna(value) else str(value).strip()
    )
    invalid_rows: list[int] = []
    canonical: list[str] = []
    for position, (identifier, label) in enumerate(zip(frame[id_column], raw)):
        expected_label = expected_by_key[str(identifier).casefold()]
        if not label or label.casefold() != expected_label.casefold():
            invalid_rows.append(position)
        canonical.append(expected_label)
    if invalid_rows:
        raise RepeatedSessionDesignError(
            f"{label_column} must match the canonical labels in the inference "
            f"contract; mismatch at row position(s) {invalid_rows[:10]}."
        )
    frame[label_column] = canonical


def prepare_repeated_session_data(
    data: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
) -> pd.DataFrame:
    """Validate identities and return the canonical analysis/export row schema."""

    if not isinstance(data, pd.DataFrame):
        raise TypeError("data must be a pandas DataFrame.")
    if not isinstance(contract, RepeatedSessionInferenceContract):
        raise TypeError("contract must be a RepeatedSessionInferenceContract.")
    missing = [column for column in REPEATED_SESSION_CORE_COLUMNS if column not in data]
    if missing:
        raise RepeatedSessionDesignError(f"Missing required column(s): {missing}")

    frame = data.copy()
    for column in ("participant_id", "recording_id", "condition", "roi"):
        _normalize_identifier_column(frame, column)
    _canonicalize_contract_ids(frame, "group_id", contract.group_ids)
    _canonicalize_contract_ids(frame, "session_id", contract.session_ids)

    _label_column(
        frame,
        id_column="group_id",
        label_column="group_label",
        expected=contract.group_label_map,
    )
    _label_column(
        frame,
        id_column="session_id",
        label_column="session_label",
        expected=contract.session_label_map,
    )

    visit_numeric = pd.to_numeric(frame["visit_index"], errors="coerce")
    invalid_visit = visit_numeric.isna() | (visit_numeric % 1 != 0)
    if bool(invalid_visit.any()):
        raise RepeatedSessionDesignError(
            "visit_index must contain the integer visit defined for each session."
        )
    frame["visit_index"] = visit_numeric.astype(int)
    expected_visits = frame["session_id"].map(contract.session_visit_map).astype(int)
    mismatch = frame["visit_index"].ne(expected_visits)
    if bool(mismatch.any()):
        examples = frame.loc[
            mismatch,
            ["participant_id", "session_id", "visit_index"],
        ].head(10)
        raise RepeatedSessionDesignError(
            "session_id and visit_index disagree with the ordered inference "
            f"contract: {examples.to_dict('records')}"
        )

    if "days_from_baseline" not in frame:
        frame["days_from_baseline"] = np.nan
    days_raw = frame["days_from_baseline"]
    days_numeric = pd.to_numeric(days_raw, errors="coerce")
    invalid_days = days_numeric.isna() & days_raw.notna() & days_raw.map(
        lambda value: str(value).strip() != ""
    )
    if bool(invalid_days.any()):
        examples = days_raw.loc[invalid_days].head(10).tolist()
        raise RepeatedSessionDesignError(
            "days_from_baseline must be numeric or missing; invalid value(s): "
            f"{examples!r}."
        )
    frame["days_from_baseline"] = days_numeric.astype(float)

    observed_groups = tuple(
        group for group in contract.group_ids if bool(frame["group_id"].eq(group).any())
    )
    if observed_groups != contract.group_ids:
        raise RepeatedSessionDesignError(
            "Repeated-session inference requires observations from exactly both "
            f"declared groups {contract.group_ids!r}; observed {observed_groups!r}."
        )
    observed_sessions = tuple(
        session
        for session in contract.session_ids
        if bool(frame["session_id"].eq(session).any())
    )
    if observed_sessions != contract.session_ids:
        raise RepeatedSessionDesignError(
            "Repeated-session inference requires observations from exactly both "
            f"declared sessions {contract.session_ids!r}; observed {observed_sessions!r}."
        )

    participant_groups = frame.groupby("participant_id", sort=False)["group_id"].nunique()
    inconsistent_groups = participant_groups[participant_groups.ne(1)]
    if not inconsistent_groups.empty:
        raise RepeatedSessionDesignError(
            "group_id must be stable across sessions for every participant; "
            "conflicts: "
            + ", ".join(map(str, inconsistent_groups.index.tolist()))
        )

    recording_owners = frame.groupby("recording_id", sort=False)[
        ["participant_id", "session_id", "group_id"]
    ].nunique()
    conflicting_recordings = recording_owners[
        recording_owners.max(axis=1).gt(1)
    ]
    if not conflicting_recordings.empty:
        raise RepeatedSessionDesignError(
            "recording_id must belong to exactly one participant, session, and "
            "group; conflicts: "
            + ", ".join(map(str, conflicting_recordings.index.tolist()))
        )

    recordings_per_session = frame.groupby(
        ["participant_id", "session_id"],
        sort=False,
    )["recording_id"].nunique()
    duplicate_sessions = recordings_per_session[recordings_per_session.gt(1)]
    if not duplicate_sessions.empty:
        raise RepeatedSessionDesignError(
            "Each participant may have at most one recording per declared session; "
            f"conflicts: {list(duplicate_sessions.index[:10])}"
        )

    grain = ["participant_id", "session_id", "condition", "roi"]
    duplicate_mask = frame.duplicated(grain, keep=False)
    if bool(duplicate_mask.any()):
        examples = frame.loc[duplicate_mask, grain].head(10).to_dict("records")
        raise RepeatedSessionDesignError(
            "Exactly one row is allowed per participant x session x Condition x "
            f"ROI; duplicates: {examples}"
        )

    original_value = frame["summed_bca_uv"]
    numeric_value = pd.to_numeric(original_value, errors="coerce")
    original_missing = original_value.isna() | original_value.map(
        lambda value: str(value).strip() == "" if not pd.isna(value) else True
    )
    invalid_numeric = numeric_value.isna() & ~original_missing
    if bool(invalid_numeric.any()):
        examples = original_value.loc[invalid_numeric].head(10).tolist()
        raise RepeatedSessionDesignError(
            "summed_bca_uv must be numeric or missing; invalid value(s): "
            f"{examples!r}."
        )
    frame["summed_bca_uv"] = numeric_value.astype(float)

    for column in ("qc_flag", "excluded"):
        if column not in frame:
            frame[column] = False
        frame[column] = frame[column].map(
            lambda value, column=column: _coerce_boolean(value, column=column)
        )
    for column in ("qc_notes", "exclusion_reason"):
        if column not in frame:
            frame[column] = ""
        frame[column] = frame[column].map(
            lambda value: "" if pd.isna(value) else str(value).strip()
        )
    missing_reasons = frame["excluded"] & frame["exclusion_reason"].eq("")
    if bool(missing_reasons.any()):
        raise RepeatedSessionDesignError(
            "Every excluded row must include a non-empty exclusion_reason."
        )

    return frame.loc[:, REPEATED_SESSION_NORMALIZED_COLUMNS].reset_index(drop=True)


def _normalize_outcomes(
    outcomes: Iterable[
        RepeatedSessionOutcome | Sequence[object] | Mapping[str, object]
    ],
) -> tuple[RepeatedSessionOutcome, ...]:
    normalized: list[RepeatedSessionOutcome] = []
    for raw in outcomes:
        if isinstance(raw, RepeatedSessionOutcome):
            outcome = raw
        elif isinstance(raw, Mapping):
            outcome = RepeatedSessionOutcome(
                condition=str(raw.get("condition", "")),
                roi=str(raw.get("roi", "")),
                outcome_id=(
                    None
                    if raw.get("outcome_id") in (None, "")
                    else str(raw.get("outcome_id"))
                ),
            )
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            values = tuple(raw)
            if len(values) not in (2, 3):
                raise ValueError(
                    "Outcome sequences must contain Condition, ROI, and optional ID."
                )
            outcome = RepeatedSessionOutcome(
                condition=str(values[0]),
                roi=str(values[1]),
                outcome_id=None if len(values) == 2 else str(values[2]),
            )
        else:
            raise TypeError(
                "outcomes must contain RepeatedSessionOutcome, mapping, or tuple values."
            )
        normalized.append(outcome)
    if not normalized:
        raise ValueError("At least one Condition x ROI outcome must be declared.")

    pair_keys = [(item.condition.casefold(), item.roi.casefold()) for item in normalized]
    if len(pair_keys) != len(set(pair_keys)):
        raise ValueError("Declared Condition x ROI outcomes must be unique.")
    ids = [str(item.outcome_id).casefold() for item in normalized]
    if len(ids) != len(set(ids)):
        raise ValueError("Declared outcome_id values must be unique.")
    return tuple(normalized)


def _participant_session_audit(
    data: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
) -> pd.DataFrame:
    first_session, second_session = contract.session_ids
    first_label, second_label = contract.session_labels
    rows: list[dict[str, object]] = []
    participant_groups = data.groupby("participant_id", sort=True)
    for participant, participant_rows in participant_groups:
        group_id = str(participant_rows["group_id"].iloc[0])
        group_label = str(participant_rows["group_label"].iloc[0])
        recording_by_session = {
            session: tuple(
                participant_rows.loc[
                    participant_rows["session_id"].eq(session),
                    "recording_id",
                ].drop_duplicates()
            )
            for session in contract.session_ids
        }
        first_observed = bool(recording_by_session[first_session])
        second_observed = bool(recording_by_session[second_session])
        if first_observed and second_observed:
            status = "complete_recording_pair"
            status_label = f"Complete {SESSION_PHASE_AT_VISIT_TERM} recording pair"
        elif first_observed:
            status = "missing_visit_2_recording"
            status_label = (
                f"Missing visit 2 {SESSION_PHASE_AT_VISIT_TERM} recording "
                f"({second_label})"
            )
        else:
            status = "missing_visit_1_recording"
            status_label = (
                f"Missing visit 1 {SESSION_PHASE_AT_VISIT_TERM} recording "
                f"({first_label})"
            )
        rows.append(
            {
                "participant_id": participant,
                "group_id": group_id,
                "group_label": group_label,
                "visit_1_session_id": first_session,
                "visit_1_session_label": first_label,
                "visit_1_recording_id": (
                    recording_by_session[first_session][0] if first_observed else ""
                ),
                "visit_1_observed": first_observed,
                "visit_2_session_id": second_session,
                "visit_2_session_label": second_label,
                "visit_2_recording_id": (
                    recording_by_session[second_session][0] if second_observed else ""
                ),
                "visit_2_observed": second_observed,
                "n_recordings_observed": int(first_observed) + int(second_observed),
                "complete_recording_pair": first_observed and second_observed,
                "pair_status": status,
                "pair_status_label": status_label,
            }
        )
    return pd.DataFrame(rows)


def _outcome_status(
    *,
    first_session_observed: bool,
    second_session_observed: bool,
    first_row: Mapping[str, object] | None,
    second_row: Mapping[str, object] | None,
) -> tuple[str, str]:
    problems: list[str] = []
    for visit, session_observed, row in (
        (1, first_session_observed, first_row),
        (2, second_session_observed, second_row),
    ):
        if row is None:
            problems.append(
                f"missing_visit_{visit}_{'outcome' if session_observed else 'session'}"
            )
            continue
        if bool(row["excluded"]):
            problems.append(f"excluded_visit_{visit}")
        value = float(row["summed_bca_uv"])
        if not np.isfinite(value):
            problems.append(f"nonfinite_visit_{visit}")
    if not problems:
        return (
            "complete_usable_pair",
            f"Complete usable {SESSION_PHASE_AT_VISIT_TERM} outcome pair",
        )
    code = "+".join(problems)
    label = (
        f"Incomplete {SESSION_PHASE_AT_VISIT_TERM} outcome pair: "
        + "; ".join(problem.replace("_", " ") for problem in problems)
    )
    return code, label


def _outcome_pair_audit(
    data: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
    outcomes: Sequence[RepeatedSessionOutcome],
    participant_sessions: pd.DataFrame,
) -> pd.DataFrame:
    first_session, second_session = contract.session_ids
    lookup = {
        (
            str(row["participant_id"]).casefold(),
            str(row["session_id"]).casefold(),
            str(row["condition"]).casefold(),
            str(row["roi"]).casefold(),
        ): row.to_dict()
        for _, row in data.iterrows()
    }
    rows: list[dict[str, object]] = []
    for outcome_order, outcome in enumerate(outcomes):
        for _, participant in participant_sessions.iterrows():
            participant_key = str(participant["participant_id"]).casefold()
            common_key = (
                participant_key,
                outcome.condition.casefold(),
                outcome.roi.casefold(),
            )
            first_row = lookup.get(
                (common_key[0], first_session.casefold(), common_key[1], common_key[2])
            )
            second_row = lookup.get(
                (common_key[0], second_session.casefold(), common_key[1], common_key[2])
            )
            first_present = first_row is not None
            second_present = second_row is not None
            first_value = (
                float(first_row["summed_bca_uv"]) if first_present else np.nan
            )
            second_value = (
                float(second_row["summed_bca_uv"]) if second_present else np.nan
            )
            first_excluded = bool(first_row["excluded"]) if first_present else False
            second_excluded = bool(second_row["excluded"]) if second_present else False
            first_finite = first_present and bool(np.isfinite(first_value))
            second_finite = second_present and bool(np.isfinite(second_value))
            first_usable = first_present and first_finite and not first_excluded
            second_usable = second_present and second_finite and not second_excluded
            complete_pair = first_usable and second_usable
            status, status_label = _outcome_status(
                first_session_observed=bool(participant["visit_1_observed"]),
                second_session_observed=bool(participant["visit_2_observed"]),
                first_row=first_row,
                second_row=second_row,
            )
            rows.append(
                {
                    "outcome_order": outcome_order,
                    "outcome_id": outcome.outcome_id,
                    "condition": outcome.condition,
                    "roi": outcome.roi,
                    "participant_id": participant["participant_id"],
                    "group_id": participant["group_id"],
                    "group_label": participant["group_label"],
                    "visit_1_session_id": first_session,
                    "visit_1_session_label": contract.session_labels[0],
                    "visit_1_recording_id": participant["visit_1_recording_id"],
                    "visit_1_session_observed": bool(participant["visit_1_observed"]),
                    "visit_1_outcome_observed": first_present,
                    "visit_1_value": first_value,
                    "visit_1_qc_flag": bool(first_row["qc_flag"]) if first_present else False,
                    "visit_1_excluded": first_excluded,
                    "visit_1_finite": first_finite,
                    "visit_1_usable": first_usable,
                    "visit_2_session_id": second_session,
                    "visit_2_session_label": contract.session_labels[1],
                    "visit_2_recording_id": participant["visit_2_recording_id"],
                    "visit_2_session_observed": bool(participant["visit_2_observed"]),
                    "visit_2_outcome_observed": second_present,
                    "visit_2_value": second_value,
                    "visit_2_qc_flag": bool(second_row["qc_flag"]) if second_present else False,
                    "visit_2_excluded": second_excluded,
                    "visit_2_finite": second_finite,
                    "visit_2_usable": second_usable,
                    "complete_usable_pair": complete_pair,
                    "delta_session2_minus_session1": (
                        second_value - first_value if complete_pair else np.nan
                    ),
                    "pair_status": status,
                    "pair_status_label": status_label,
                    "missing_values_imputed": False,
                }
            )
    return pd.DataFrame(rows)


def _coverage_frame(
    pairs: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
    outcomes: Sequence[RepeatedSessionOutcome],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for outcome in outcomes:
        outcome_rows = pairs[pairs["outcome_id"].eq(outcome.outcome_id)]
        for group_id in contract.group_ids:
            cell = outcome_rows[outcome_rows["group_id"].eq(group_id)]
            group_label = contract.group_label_map[group_id]
            rows.append(
                {
                    "outcome_id": outcome.outcome_id,
                    "condition": outcome.condition,
                    "roi": outcome.roi,
                    "group_id": group_id,
                    "group_label": group_label,
                    "n_participants": len(cell),
                    "n_complete_recording_pairs": int(
                        (cell["visit_1_session_observed"] & cell["visit_2_session_observed"]).sum()
                    ),
                    "n_missing_visit_1_sessions": int(
                        (~cell["visit_1_session_observed"]).sum()
                    ),
                    "n_missing_visit_2_sessions": int(
                        (~cell["visit_2_session_observed"]).sum()
                    ),
                    "n_visit_1_outcomes_observed": int(
                        cell["visit_1_outcome_observed"].sum()
                    ),
                    "n_visit_2_outcomes_observed": int(
                        cell["visit_2_outcome_observed"].sum()
                    ),
                    "n_visit_1_usable": int(cell["visit_1_usable"].sum()),
                    "n_visit_2_usable": int(cell["visit_2_usable"].sum()),
                    "n_complete_usable_pairs": int(cell["complete_usable_pair"].sum()),
                    "n_incomplete_outcome_pairs": int(
                        (~cell["complete_usable_pair"]).sum()
                    ),
                    "n_visit_1_excluded": int(cell["visit_1_excluded"].sum()),
                    "n_visit_2_excluded": int(cell["visit_2_excluded"].sum()),
                    "n_visit_1_nonfinite": int(
                        (cell["visit_1_outcome_observed"] & ~cell["visit_1_finite"]).sum()
                    ),
                    "n_visit_2_nonfinite": int(
                        (cell["visit_2_outcome_observed"] & ~cell["visit_2_finite"]).sum()
                    ),
                    "analysis_scope": "complete_pair_per_declared_outcome",
                    "missing_values_imputed": False,
                    "session_contrast_label": contract.session_contrast_label,
                    "fixed_order_confounding": FIXED_ORDER_CONFOUNDING,
                }
            )
    return pd.DataFrame(rows)


def audit_repeated_session_design(
    data: pd.DataFrame,
    *,
    contract: RepeatedSessionInferenceContract,
    outcomes: Iterable[
        RepeatedSessionOutcome | Sequence[object] | Mapping[str, object]
    ],
) -> RepeatedSessionDesignAudit:
    """Audit recording pairs and outcome-specific usable pairs without imputation."""

    declared = _normalize_outcomes(outcomes)
    normalized = prepare_repeated_session_data(data, contract)
    participants = _participant_session_audit(normalized, contract)
    pairs = _outcome_pair_audit(normalized, contract, declared, participants)
    deltas = pairs.loc[
        pairs["complete_usable_pair"],
        [
            "outcome_order",
            "outcome_id",
            "condition",
            "roi",
            "participant_id",
            "group_id",
            "group_label",
            "visit_1_recording_id",
            "visit_2_recording_id",
            "visit_1_value",
            "visit_2_value",
            "delta_session2_minus_session1",
        ],
    ].reset_index(drop=True)
    coverage = _coverage_frame(pairs, contract, declared)
    metadata_row = contract.to_metadata()
    metadata_row.update(
        {
            "repeated_session_analysis_schema_version": (
                REPEATED_SESSION_ANALYSIS_SCHEMA_VERSION
            ),
            "n_declared_outcomes": len(declared),
            "n_participants": len(participants),
            "n_complete_recording_pairs": int(
                participants["complete_recording_pair"].sum()
            ),
            "n_missing_visit_1_recordings": int(
                (~participants["visit_1_observed"]).sum()
            ),
            "n_missing_visit_2_recordings": int(
                (~participants["visit_2_observed"]).sum()
            ),
            "n_complete_usable_outcome_pairs": len(deltas),
        }
    )
    return RepeatedSessionDesignAudit(
        normalized_data=normalized,
        participant_sessions=participants,
        outcome_pairs=pairs,
        pair_deltas=deltas,
        coverage=coverage,
        metadata=pd.DataFrame([metadata_row]),
    )


def _effectively_zero_sd(sd: float, values: np.ndarray) -> bool:
    if sd == 0.0:
        return True
    scale = float(np.max(np.abs(values))) if values.size else 0.0
    if scale == 0.0:
        return True
    return bool(sd <= np.finfo(float).eps * scale * 8.0)


def _hedges_g(
    difference: float,
    *,
    n_a: int,
    n_b: int,
    variance_a: float,
    variance_b: float,
) -> float:
    pooled_df = n_a + n_b - 2
    if pooled_df <= 0:
        return np.nan
    pooled_variance = (
        (n_a - 1) * variance_a + (n_b - 1) * variance_b
    ) / pooled_df
    if not np.isfinite(pooled_variance) or pooled_variance <= 0.0:
        return np.nan
    cohen_d = difference / np.sqrt(pooled_variance)
    correction = 1.0 - (3.0 / (4.0 * pooled_df - 1.0))
    return float(correction * cohen_d)


def _welch_delta_statistics(
    values_a: np.ndarray,
    values_b: np.ndarray,
    *,
    alpha: float,
) -> dict[str, object]:
    n_a = int(values_a.size)
    n_b = int(values_b.size)
    mean_a = float(np.mean(values_a)) if n_a else np.nan
    mean_b = float(np.mean(values_b)) if n_b else np.nan
    sd_a = float(np.std(values_a, ddof=1)) if n_a >= 2 else np.nan
    sd_b = float(np.std(values_b, ddof=1)) if n_b >= 2 else np.nan
    difference = mean_a - mean_b if n_a and n_b else np.nan
    result: dict[str, object] = {
        "n_pairs_group_a": n_a,
        "mean_delta_group_a": mean_a,
        "sd_delta_group_a": sd_a,
        "n_pairs_group_b": n_b,
        "mean_delta_group_b": mean_b,
        "sd_delta_group_b": sd_b,
        "estimate_delta_difference_group_a_minus_group_b": difference,
        "standard_error": np.nan,
        "welch_t": np.nan,
        "welch_df": np.nan,
        "p_raw": np.nan,
        "ci_difference_low": np.nan,
        "ci_difference_high": np.nan,
        "hedges_g": np.nan,
        "inference_status": "not_estimable",
        "status_code": "insufficient_complete_pairs",
    }
    if n_a < 2 or n_b < 2:
        return result
    variance_a = sd_a**2
    variance_b = sd_b**2
    term_a = variance_a / n_a
    term_b = variance_b / n_b
    se_squared = term_a + term_b
    if not np.isfinite(se_squared) or se_squared <= 0.0:
        result["status_code"] = "zero_or_invalid_standard_error"
        return result
    denominator = (term_a**2) / (n_a - 1) + (term_b**2) / (n_b - 1)
    if not np.isfinite(denominator) or denominator <= 0.0:
        result["status_code"] = "invalid_welch_degrees_of_freedom"
        return result
    welch_df = se_squared**2 / denominator
    standard_error = float(np.sqrt(se_squared))
    welch_t = float(difference / standard_error)
    p_raw = float(2.0 * stats.t.sf(abs(welch_t), df=welch_df))
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df=welch_df))
    margin = critical * standard_error
    finite_results = (
        welch_df,
        welch_t,
        p_raw,
        difference - margin,
        difference + margin,
    )
    if not all(np.isfinite(value) for value in finite_results):
        result["status_code"] = "invalid_welch_result"
        return result
    result.update(
        {
            "standard_error": standard_error,
            "welch_t": welch_t,
            "welch_df": float(welch_df),
            "p_raw": p_raw,
            "ci_difference_low": float(difference - margin),
            "ci_difference_high": float(difference + margin),
            "hedges_g": _hedges_g(
                difference,
                n_a=n_a,
                n_b=n_b,
                variance_a=variance_a,
                variance_b=variance_b,
            ),
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return result


def _paired_delta_statistics(
    values: np.ndarray,
    *,
    visit_1_values: np.ndarray,
    visit_2_values: np.ndarray,
    alpha: float,
) -> dict[str, object]:
    n = int(values.size)
    mean_delta = float(np.mean(values)) if n else np.nan
    sd_delta = float(np.std(values, ddof=1)) if n >= 2 else np.nan
    result: dict[str, object] = {
        "n_complete_pairs": n,
        "mean_visit_1": float(np.mean(visit_1_values)) if n else np.nan,
        "mean_visit_2": float(np.mean(visit_2_values)) if n else np.nan,
        "mean_delta_session2_minus_session1": mean_delta,
        "sd_delta": sd_delta,
        "standard_error": np.nan,
        "paired_t": np.nan,
        "df": float(n - 1) if n else np.nan,
        "p_raw": np.nan,
        "ci_delta_low": np.nan,
        "ci_delta_high": np.nan,
        "cohens_dz": np.nan,
        "inference_status": "not_estimable",
        "status_code": "insufficient_complete_pairs",
    }
    if n < 3:
        return result
    if not np.isfinite(sd_delta):
        result["status_code"] = "invalid_delta_variance"
        return result
    if _effectively_zero_sd(sd_delta, values):
        result.update(
            {
                "ci_delta_low": mean_delta,
                "ci_delta_high": mean_delta,
                "cohens_dz": 0.0 if mean_delta == 0.0 else np.nan,
                "status_code": (
                    "zero_variance_zero_change"
                    if mean_delta == 0.0
                    else "zero_variance_nonzero_change"
                ),
            }
        )
        return result
    standard_error = float(sd_delta / np.sqrt(n))
    test = stats.ttest_1samp(values, popmean=0.0, alternative="two-sided")
    t_value = float(test.statistic)
    p_raw = float(test.pvalue)
    critical = float(stats.t.ppf(1.0 - alpha / 2.0, df=n - 1))
    margin = critical * standard_error
    finite_results = (t_value, p_raw, mean_delta - margin, mean_delta + margin)
    if not all(np.isfinite(value) for value in finite_results):
        result["status_code"] = "invalid_paired_result"
        return result
    result.update(
        {
            "standard_error": standard_error,
            "paired_t": t_value,
            "p_raw": p_raw,
            "ci_delta_low": float(mean_delta - margin),
            "ci_delta_high": float(mean_delta + margin),
            "cohens_dz": float(mean_delta / sd_delta),
            "inference_status": "estimated",
            "status_code": "ok",
        }
    )
    return result


def _apply_declared_holm(
    results: pd.DataFrame,
    family: FamilySpec,
) -> pd.DataFrame:
    """Apply Holm while conservatively retaining non-estimable declared tests."""

    raw = pd.to_numeric(results["p_raw"], errors="coerce").astype(float)
    finite = np.isfinite(raw.to_numpy(dtype=float))
    correction_input = results.copy()
    correction_input["p_raw"] = raw.where(finite, 1.0)
    corrected = apply_family_correction(correction_input, family, p_col="p_raw")
    corrected["family_size"] = len(results)
    corrected["p_raw"] = raw
    corrected.loc[~finite, "p_adjusted"] = np.nan
    corrected.loc[~finite, "reject_adjusted"] = False
    return corrected


def run_repeated_session_analysis(
    data: pd.DataFrame,
    *,
    contract: RepeatedSessionInferenceContract,
    outcomes: Iterable[
        RepeatedSessionOutcome | Sequence[object] | Mapping[str, object]
    ],
) -> RepeatedSessionAnalysisResult:
    """Run the locked complete-pair repeated-session analysis version 1."""

    declared = _normalize_outcomes(outcomes)
    audit = audit_repeated_session_design(
        data,
        contract=contract,
        outcomes=declared,
    )
    deltas = audit.pair_deltas
    group_a, group_b = contract.group_ids
    group_labels = contract.group_label_map

    primary_rows: list[dict[str, object]] = []
    for outcome_order, outcome in enumerate(declared):
        cell = deltas[deltas["outcome_id"].eq(outcome.outcome_id)]
        values_by_group = {
            group_id: cell.loc[
                cell["group_id"].eq(group_id),
                "delta_session2_minus_session1",
            ].to_numpy(dtype=float)
            for group_id in contract.group_ids
        }
        row: dict[str, object] = {
            "outcome_order": outcome_order,
            "outcome_id": outcome.outcome_id,
            "condition": outcome.condition,
            "roi": outcome.roi,
            "group_a_id": group_a,
            "group_a_label": group_labels[group_a],
            "group_b_id": group_b,
            "group_b_label": group_labels[group_b],
            "estimand_label": (
                f"{group_labels[group_a]} minus {group_labels[group_b]} in participant "
                f"{SESSION_PHASE_AT_VISIT_TERM} delta"
            ),
            "session_contrast_label": contract.session_contrast_label,
            "test_method": (
                "Two-sided Welch comparison of participant "
                f"{SESSION_PHASE_AT_VISIT_TERM} deltas"
            ),
            "effect_size_method": (
                "Hedges g using pooled delta SD; positive means group_a has the "
                "larger visit-2-minus-visit-1 change"
            ),
            "fixed_order_confounding": FIXED_ORDER_CONFOUNDING,
            "missing_values_imputed": False,
            "fallback_method": "none",
        }
        row.update(
            _welch_delta_statistics(
                values_by_group[group_a],
                values_by_group[group_b],
                alpha=contract.alpha,
            )
        )
        primary_rows.append(row)
    primary = _apply_declared_holm(
        pd.DataFrame(primary_rows),
        contract.primary_family,
    )

    secondary_rows: list[dict[str, object]] = []
    for outcome_order, outcome in enumerate(declared):
        cell = deltas[deltas["outcome_id"].eq(outcome.outcome_id)]
        for group_order, group_id in enumerate(contract.group_ids):
            group_cell = cell[cell["group_id"].eq(group_id)]
            delta_values = group_cell["delta_session2_minus_session1"].to_numpy(
                dtype=float
            )
            row = {
                "outcome_order": outcome_order,
                "group_order": group_order,
                "outcome_id": outcome.outcome_id,
                "condition": outcome.condition,
                "roi": outcome.roi,
                "group_id": group_id,
                "group_label": group_labels[group_id],
                "estimand_label": (
                    f"Paired within-{group_labels[group_id]} "
                    f"{SESSION_PHASE_AT_VISIT_TERM} change"
                ),
                "session_contrast_label": contract.session_contrast_label,
                "test_method": (
                    "Two-sided one-sample t-test of paired participant "
                    f"{SESSION_PHASE_AT_VISIT_TERM} deltas"
                ),
                "effect_size_method": (
                    "Cohen's dz; positive means visit 2 exceeds visit 1"
                ),
                "fixed_order_confounding": FIXED_ORDER_CONFOUNDING,
                "missing_values_imputed": False,
                "fallback_method": "none",
            }
            row.update(
                _paired_delta_statistics(
                    delta_values,
                    visit_1_values=group_cell["visit_1_value"].to_numpy(dtype=float),
                    visit_2_values=group_cell["visit_2_value"].to_numpy(dtype=float),
                    alpha=contract.alpha,
                )
            )
            secondary_rows.append(row)
    secondary = _apply_declared_holm(
        pd.DataFrame(secondary_rows),
        contract.secondary_family,
    )

    metadata_row = contract.to_metadata()
    metadata_row.update(
        {
            "repeated_session_analysis_schema_version": (
                REPEATED_SESSION_ANALYSIS_SCHEMA_VERSION
            ),
            "analysis_scope": "complete_pair_per_declared_outcome",
            "n_declared_primary_outcomes": len(declared),
            "primary_family_size": len(primary),
            "secondary_family_size": len(secondary),
            "n_primary_estimable": int(primary["inference_status"].eq("estimated").sum()),
            "n_secondary_estimable": int(
                secondary["inference_status"].eq("estimated").sum()
            ),
            "n_participants": len(audit.participant_sessions),
            "n_complete_recording_pairs": int(
                audit.participant_sessions["complete_recording_pair"].sum()
            ),
            "n_missing_recording_pairs": int(
                (~audit.participant_sessions["complete_recording_pair"]).sum()
            ),
            "missing_values_imputed": False,
            "fallback_method": "none",
        }
    )
    return RepeatedSessionAnalysisResult(
        primary_results=primary,
        secondary_results=secondary,
        audit=audit,
        metadata=pd.DataFrame([metadata_row]),
    )


__all__ = [
    "ANALYSIS_METADATA_SHEET",
    "OUTCOME_PAIR_AUDIT_SHEET",
    "PAIR_COVERAGE_SHEET",
    "PAIR_DELTAS_SHEET",
    "PARTICIPANT_SESSION_AUDIT_SHEET",
    "PRIMARY_RESULTS_SHEET",
    "REPEATED_SESSION_ANALYSIS_SCHEMA_VERSION",
    "REPEATED_SESSION_CORE_COLUMNS",
    "REPEATED_SESSION_NORMALIZED_COLUMNS",
    "SECONDARY_RESULTS_SHEET",
    "RepeatedSessionAnalysisResult",
    "RepeatedSessionDesignAudit",
    "RepeatedSessionDesignError",
    "RepeatedSessionOutcome",
    "audit_repeated_session_design",
    "prepare_repeated_session_data",
    "run_repeated_session_analysis",
]
