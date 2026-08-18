"""Project adapter and workbook writer for repeated-session Stats v1."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence

import pandas as pd

from Main_App.exports.analysis_ready_workbook import (
    ROI_LONG_SHEET,
    default_analysis_ready_workbook_path,
)
from Main_App.projects import ProjectDatasetIndex, load_project_dataset_index
from Tools.Stats.analysis.repeated_session_analysis import (
    RepeatedSessionAnalysisResult,
    RepeatedSessionOutcome,
    prepare_repeated_session_data,
    run_repeated_session_analysis,
)
from Tools.Stats.analysis.repeated_session_contracts import (
    RepeatedSessionInferenceContract,
)
from Tools.Stats.io.repeated_session_export import (
    build_repeated_session_export_frames,
)


REPEATED_SESSION_RESULTS_WORKBOOK = "Repeated_Session_Change_Analysis.xlsx"
_REQUIRED_AUDIT_COLUMNS = (
    "PID",
    "Recording ID",
    "Session ID",
    "Session",
    "Visit Index",
    "Group ID",
    "Group",
    "Condition",
    "ROI",
    "Raw Summed BCA",
    "Current Toolbox Exclusion",
    "QC Flag",
    "QC Notes",
)


@dataclass(frozen=True, slots=True)
class RepeatedSessionProjectData:
    """Canonical project identities and validated ROI-long observations."""

    project_root: Path
    source_workbook: Path
    dataset_index: ProjectDatasetIndex
    contract: RepeatedSessionInferenceContract
    data: pd.DataFrame

    @property
    def available_outcomes(self) -> tuple[RepeatedSessionOutcome, ...]:
        rows = self.data.loc[:, ["condition", "roi"]].drop_duplicates()
        return tuple(
            RepeatedSessionOutcome(str(row.condition), str(row.roi))
            for row in rows.itertuples(index=False)
        )

    def recording_pair_coverage(self) -> pd.DataFrame:
        """Return one pre-analysis recording-pair coverage row per group."""

        first_session, second_session = self.contract.session_ids
        sessions_by_participant: dict[str, set[str]] = {}
        for recording in self.dataset_index.recordings.values():
            sessions_by_participant.setdefault(
                recording.participant_id.casefold(),
                set(),
            ).add(recording.session_id)
        rows: list[dict[str, object]] = []
        for group_id, group_label in zip(
            self.contract.group_ids,
            self.contract.group_labels,
        ):
            participants = tuple(
                participant
                for participant in self.dataset_index.participants.values()
                if participant.group_id is not None
                and participant.group_id.casefold() == group_id.casefold()
            )
            observed = tuple(
                sessions_by_participant.get(
                    participant.participant_id.casefold(),
                    set(),
                )
                for participant in participants
            )
            has_first = tuple(first_session in values for values in observed)
            has_second = tuple(second_session in values for values in observed)
            rows.append(
                {
                    "group_id": group_id,
                    "group_label": group_label,
                    "n_participants": len(participants),
                    "n_complete_recording_pairs": sum(
                        first and second
                        for first, second in zip(has_first, has_second)
                    ),
                    "n_missing_visit_1_recording": sum(not value for value in has_first),
                    "n_missing_visit_2_recording": sum(not value for value in has_second),
                }
            )
        return pd.DataFrame(rows)


def repeated_session_contract_from_index(
    index: ProjectDatasetIndex,
    *,
    alpha: float = 0.05,
) -> RepeatedSessionInferenceContract:
    """Build the narrow v1 contract from canonical project metadata."""

    if not index.is_repeated_session:
        raise ValueError("The active project is not a repeated-session project.")
    groups = index.ordered_groups
    sessions = index.ordered_sessions
    if len(groups) != 2:
        raise ValueError(
            "Repeated-session inference v1 requires exactly two stable groups; "
            f"the project declares {len(groups)}."
        )
    if len(sessions) != 2:
        raise ValueError(
            "Repeated-session inference v1 requires exactly two ordered sessions; "
            f"the project declares {len(sessions)}."
        )
    if tuple(session.visit_index for session in sessions) != (1, 2):
        raise ValueError(
            "Repeated-session inference v1 requires session visit indices 1 and 2."
        )
    return RepeatedSessionInferenceContract(
        group_ids=(groups[0].group_id, groups[1].group_id),
        group_labels=(groups[0].label, groups[1].label),
        session_ids=(sessions[0].session_id, sessions[1].session_id),
        session_labels=(sessions[0].label, sessions[1].label),
        visit_indices=(1, 2),
        alpha=alpha,
    )


def _yes_no(value: object) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value or "").strip().casefold()
    if text in {"yes", "true", "1", "y"}:
        return True
    if text in {"", "no", "false", "0", "n", "nan"}:
        return False
    raise ValueError(f"Expected a Yes/No audit value, got {value!r}.")


def _project_analysis_frame(frame: pd.DataFrame) -> pd.DataFrame:
    missing = [column for column in _REQUIRED_AUDIT_COLUMNS if column not in frame]
    if missing:
        raise ValueError(
            "The analysis-ready ROI Long sheet is not session-aware; missing "
            f"column(s): {missing}. Rebuild post-processing outputs."
        )
    excluded = frame["Current Toolbox Exclusion"].map(_yes_no)
    qc_flag = frame["QC Flag"].map(_yes_no)
    qc_notes = frame["QC Notes"].fillna("").astype(str).str.strip()
    exclusion_reason = qc_notes.where(
        excluded,
        "",
    )
    exclusion_reason = exclusion_reason.mask(
        excluded & exclusion_reason.eq(""),
        "Current Toolbox exclusion recorded in the full-audit workbook.",
    )
    return pd.DataFrame(
        {
            "participant_id": frame["PID"],
            "recording_id": frame["Recording ID"],
            "session_id": frame["Session ID"],
            "session_label": frame["Session"],
            "visit_index": frame["Visit Index"],
            "days_from_baseline": (
                frame["Days From Baseline"]
                if "Days From Baseline" in frame
                else pd.Series(float("nan"), index=frame.index)
            ),
            "group_id": frame["Group ID"],
            "group_label": frame["Group"],
            "condition": frame["Condition"],
            "roi": frame["ROI"],
            "summed_bca_uv": frame["Raw Summed BCA"],
            "qc_flag": qc_flag,
            "qc_notes": qc_notes,
            "excluded": excluded,
            "exclusion_reason": exclusion_reason,
        }
    )


def _validate_canonical_project_identities(
    frame: pd.DataFrame,
    index: ProjectDatasetIndex,
) -> pd.DataFrame:
    """Reject stale/foreign audit rows and restore exact manifest ID spelling."""

    participant_lookup = {
        participant_id.casefold(): participant
        for participant_id, participant in index.participants.items()
    }
    unassigned = sorted(
        participant.participant_id
        for participant in participant_lookup.values()
        if participant.group_id is None
    )
    if unassigned:
        raise ValueError(
            "Repeated-session project participants require one stable canonical "
            "group assignment; unassigned participant(s): "
            + ", ".join(unassigned)
            + "."
        )

    recording_lookup = {
        recording_id.casefold(): recording
        for recording_id, recording in index.recordings.items()
    }
    mismatches: list[str] = []
    canonical_rows: dict[str, tuple[str, str, int, str]] = {}
    identity_rows = frame.loc[
        :,
        [
            "participant_id",
            "recording_id",
            "session_id",
            "visit_index",
            "group_id",
        ],
    ].drop_duplicates()
    for row in identity_rows.itertuples(index=False):
        recording_key = str(row.recording_id).casefold()
        recording = recording_lookup.get(recording_key)
        if recording is None:
            mismatches.append(f"unknown recording_id '{row.recording_id}'")
            continue
        participant = participant_lookup.get(recording.participant_id.casefold())
        if participant is None or participant.group_id is None:
            mismatches.append(
                f"recording '{recording.recording_id}' has no stable participant/group owner"
            )
            continue
        expected = (
            recording.participant_id,
            recording.session_id,
            int(recording.visit_index),
            participant.group_id,
        )
        observed = (
            str(row.participant_id),
            str(row.session_id),
            int(row.visit_index),
            str(row.group_id),
        )
        if (
            observed[0].casefold() != expected[0].casefold()
            or observed[1].casefold() != expected[1].casefold()
            or observed[2] != expected[2]
            or observed[3].casefold() != expected[3].casefold()
        ):
            mismatches.append(
                f"recording '{recording.recording_id}' observed owner/session/visit/group "
                f"{observed!r}, expected {expected!r}"
            )
            continue
        canonical_rows[recording_key] = expected

    if mismatches:
        details = "; ".join(mismatches[:10])
        suffix = "" if len(mismatches) <= 10 else f"; and {len(mismatches) - 10} more"
        raise ValueError(
            "The analysis-ready ROI Long sheet does not match canonical project "
            f"recording identities and may be stale or from another project: {details}{suffix}. "
            "Rebuild post-processing outputs."
        )

    canonical = frame.copy()
    for row_index, recording_id in canonical["recording_id"].items():
        recording = recording_lookup[str(recording_id).casefold()]
        participant_id, session_id, visit_index, group_id = canonical_rows[
            recording.recording_id.casefold()
        ]
        canonical.at[row_index, "recording_id"] = recording.recording_id
        canonical.at[row_index, "participant_id"] = participant_id
        canonical.at[row_index, "session_id"] = session_id
        canonical.at[row_index, "visit_index"] = visit_index
        canonical.at[row_index, "group_id"] = group_id
    return canonical


def load_repeated_session_project_data(
    project_root: str | Path,
    *,
    analysis_ready_workbook: str | Path | None = None,
    alpha: float = 0.05,
) -> RepeatedSessionProjectData:
    """Load and validate the canonical full-audit ROI-long repeated data."""

    root = Path(project_root).expanduser().resolve(strict=False)
    index = load_project_dataset_index(root)
    index.require_recording_assignments()
    index.require_session_assignments()
    contract = repeated_session_contract_from_index(index, alpha=alpha)
    source = (
        Path(analysis_ready_workbook).expanduser().resolve(strict=False)
        if analysis_ready_workbook is not None
        else default_analysis_ready_workbook_path(root)
    )
    if not source.is_file():
        raise FileNotFoundError(
            "The repeated-session analysis-ready workbook does not exist. Run "
            f"project post-processing first: {source}"
        )
    audit_frame = pd.read_excel(source, sheet_name=ROI_LONG_SHEET)
    normalized = prepare_repeated_session_data(
        _project_analysis_frame(audit_frame),
        contract,
    )
    normalized = _validate_canonical_project_identities(normalized, index)
    return RepeatedSessionProjectData(
        project_root=root,
        source_workbook=source,
        dataset_index=index,
        contract=contract,
        data=normalized,
    )


def analyze_repeated_session_project(
    project_data: RepeatedSessionProjectData,
    *,
    outcomes: Iterable[
        RepeatedSessionOutcome | Sequence[object] | Mapping[str, object]
    ],
) -> RepeatedSessionAnalysisResult:
    """Run the locked pair-delta method for explicitly selected outcomes."""

    return run_repeated_session_analysis(
        project_data.data,
        contract=project_data.contract,
        outcomes=outcomes,
    )


def default_repeated_session_results_path(project_root: str | Path) -> Path:
    return (
        Path(project_root).expanduser().resolve(strict=False)
        / "3 - Statistical Analysis Results"
        / REPEATED_SESSION_RESULTS_WORKBOOK
    )


def write_repeated_session_results_workbook(
    result: RepeatedSessionAnalysisResult,
    *,
    source_data: pd.DataFrame,
    contract: RepeatedSessionInferenceContract,
    destination: str | Path,
) -> Path:
    """Atomically write inference, audits, and canonical long data."""

    target = Path(destination).expanduser().resolve(strict=False)
    target.parent.mkdir(parents=True, exist_ok=True)
    frames = result.to_frames()
    frames.update(build_repeated_session_export_frames(source_data, contract=contract))
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            prefix=f".{target.stem}.",
            suffix=".tmp.xlsx",
            dir=target.parent,
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
        with pd.ExcelWriter(temporary_path, engine="openpyxl") as writer:
            for sheet_name, frame in frames.items():
                frame.to_excel(writer, sheet_name=sheet_name, index=False)
            for worksheet in writer.book.worksheets:
                worksheet.freeze_panes = "A2"
                worksheet.auto_filter.ref = worksheet.dimensions
        os.replace(temporary_path, target)
    finally:
        if temporary_path is not None and temporary_path.exists():
            temporary_path.unlink(missing_ok=True)
    return target


__all__ = [
    "REPEATED_SESSION_RESULTS_WORKBOOK",
    "RepeatedSessionProjectData",
    "analyze_repeated_session_project",
    "default_repeated_session_results_path",
    "load_repeated_session_project_data",
    "repeated_session_contract_from_index",
    "write_repeated_session_results_workbook",
]
