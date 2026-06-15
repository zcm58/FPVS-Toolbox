"""Project-local state for the Publication Workflow stepper."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from Tools.Publication_Report.discovery import resolve_project_paths

WORKFLOW_STATE_NAME = "Workflow_State.json"
QC_DECISIONS_NAME = "QC_Decisions.json"
QC_DECISIONS_WORKBOOK_NAME = "QC_Decisions.xlsx"
SENSITIVITY_SUMMARY_NAME = "Sensitivity_Summary.xlsx"
WORKFLOW_SCHEMA_VERSION = 1
QC_DECISION_SCHEMA_VERSION = 1

STEP_DATA_READY = "data_ready"
STEP_QC_REVIEW = "qc_review"
STEP_OUTLIER_DECISIONS = "outlier_decisions"
STEP_FREEZE_ANALYSIS_SET = "freeze_analysis_set"
STEP_PUBLICATION_REPORT = "publication_report"
STEP_FIGURES = "figures"
STEP_EXPORT_PACKAGE = "export_package"

STEP_ORDER = (
    STEP_DATA_READY,
    STEP_QC_REVIEW,
    STEP_OUTLIER_DECISIONS,
    STEP_FREEZE_ANALYSIS_SET,
    STEP_PUBLICATION_REPORT,
    STEP_FIGURES,
    STEP_EXPORT_PACKAGE,
)

STEP_LABELS = {
    STEP_DATA_READY: "Data Ready",
    STEP_QC_REVIEW: "QC Review",
    STEP_OUTLIER_DECISIONS: "Outlier Decisions",
    STEP_FREEZE_ANALYSIS_SET: "Freeze Analysis Set",
    STEP_PUBLICATION_REPORT: "Publication Report",
    STEP_FIGURES: "Figures",
    STEP_EXPORT_PACKAGE: "Export Package",
}

VALID_STEP_STATUSES = {"blocked", "ready", "running", "complete", "stale", "warning"}
VALID_DECISIONS = {"include", "watch", "exclude"}


def utc_now_iso() -> str:
    """Return a stable UTC timestamp for workflow audit records."""

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


@dataclass(frozen=True)
class StepRecord:
    """Status for one step in the Publication Workflow."""

    key: str
    label: str
    status: str = "blocked"
    message: str = ""
    artifacts: tuple[str, ...] = ()
    updated_at: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "StepRecord":
        key = str(payload.get("key") or "")
        label = str(payload.get("label") or STEP_LABELS.get(key, key))
        status = str(payload.get("status") or "blocked")
        if status not in VALID_STEP_STATUSES:
            status = "blocked"
        artifacts = payload.get("artifacts") or ()
        return cls(
            key=key,
            label=label,
            status=status,
            message=str(payload.get("message") or ""),
            artifacts=tuple(str(value) for value in artifacts if str(value)),
            updated_at=str(payload.get("updated_at") or ""),
        )


@dataclass(frozen=True)
class WorkflowState:
    """Project-local Publication Workflow state."""

    schema_version: int = WORKFLOW_SCHEMA_VERSION
    project_root: str = ""
    output_root: str = ""
    steps: tuple[StepRecord, ...] = field(default_factory=tuple)
    selected_conditions: tuple[str, ...] = ()
    frozen_excluded_subjects: tuple[str, ...] = ()
    source_fingerprints: dict[str, dict[str, Any]] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    updated_at: str = ""

    @classmethod
    def default(cls, project_root: Path) -> "WorkflowState":
        root, _excel_root, output_root = resolve_project_paths(Path(project_root))
        return cls(
            project_root=str(root),
            output_root=str(output_root),
            steps=tuple(
                StepRecord(
                    key=key,
                    label=STEP_LABELS[key],
                    status="blocked",
                    updated_at=utc_now_iso(),
                )
                for key in STEP_ORDER
            ),
            updated_at=utc_now_iso(),
        )

    @classmethod
    def from_mapping(cls, payload: dict[str, Any], project_root: Path) -> "WorkflowState":
        default = cls.default(project_root)
        raw_steps = payload.get("steps") if isinstance(payload, dict) else None
        steps = tuple(
            StepRecord.from_mapping(step)
            for step in raw_steps
            if isinstance(step, dict)
        ) if isinstance(raw_steps, list) else default.steps
        step_keys = {step.key for step in steps}
        if step_keys != set(STEP_ORDER):
            by_key = {step.key: step for step in steps}
            steps = tuple(by_key.get(key) or default_step for key, default_step in zip(STEP_ORDER, default.steps))
        fingerprints = payload.get("source_fingerprints") if isinstance(payload, dict) else {}
        if not isinstance(fingerprints, dict):
            fingerprints = {}
        return cls(
            schema_version=int(payload.get("schema_version") or WORKFLOW_SCHEMA_VERSION),
            project_root=str(payload.get("project_root") or default.project_root),
            output_root=str(payload.get("output_root") or default.output_root),
            steps=steps,
            selected_conditions=tuple(str(value) for value in payload.get("selected_conditions") or ()),
            frozen_excluded_subjects=normalize_participant_ids(
                payload.get("frozen_excluded_subjects") or ()
            ),
            source_fingerprints=fingerprints,
            warnings=tuple(str(value) for value in payload.get("warnings") or ()),
            updated_at=str(payload.get("updated_at") or default.updated_at),
        )


@dataclass(frozen=True)
class QCDecision:
    """Manual decision for one QC candidate row."""

    participant_id: str
    condition: str
    roi: str
    metric_source: str
    metric_label: str = ""
    value: float | None = None
    lower_iqr_fence: float | None = None
    upper_iqr_fence: float | None = None
    outlier_direction: str = ""
    decision: str = "watch"
    reason: str = ""
    timestamp: str = ""

    @classmethod
    def from_mapping(cls, payload: dict[str, Any]) -> "QCDecision":
        decision = str(payload.get("decision") or "watch").strip().lower()
        if decision not in VALID_DECISIONS:
            decision = "watch"
        return cls(
            participant_id=normalize_participant_id(payload.get("participant_id")),
            condition=str(payload.get("condition") or ""),
            roi=str(payload.get("roi") or ""),
            metric_source=str(payload.get("metric_source") or ""),
            metric_label=str(payload.get("metric_label") or ""),
            value=_optional_float(payload.get("value")),
            lower_iqr_fence=_optional_float(payload.get("lower_iqr_fence")),
            upper_iqr_fence=_optional_float(payload.get("upper_iqr_fence")),
            outlier_direction=str(payload.get("outlier_direction") or ""),
            decision=decision,
            reason=str(payload.get("reason") or ""),
            timestamp=str(payload.get("timestamp") or ""),
        )


def workflow_output_root(project_root: Path) -> Path:
    """Return the project-local Publication Report output root."""

    return resolve_project_paths(Path(project_root))[2]


def workflow_state_path(project_root: Path) -> Path:
    """Return the project-local workflow state path."""

    return workflow_output_root(Path(project_root)) / WORKFLOW_STATE_NAME


def qc_decisions_path(project_root: Path) -> Path:
    """Return the project-local QC decisions path."""

    return workflow_output_root(Path(project_root)) / QC_DECISIONS_NAME


def load_workflow_state(project_root: Path) -> WorkflowState:
    """Load workflow state, returning defaults when no state exists yet."""

    path = workflow_state_path(project_root)
    if not path.exists():
        return WorkflowState.default(project_root)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return WorkflowState.default(project_root)
    if not isinstance(payload, dict):
        return WorkflowState.default(project_root)
    return WorkflowState.from_mapping(payload, project_root)


def save_workflow_state(project_root: Path, state: WorkflowState) -> Path:
    """Persist workflow state under the project-local report folder."""

    path = workflow_state_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def update_step(
    state: WorkflowState,
    step_key: str,
    *,
    status: str,
    message: str = "",
    artifacts: tuple[str, ...] = (),
) -> WorkflowState:
    """Return state with one step status updated."""

    if step_key not in STEP_LABELS:
        raise ValueError(f"Unknown workflow step: {step_key!r}")
    if status not in VALID_STEP_STATUSES:
        raise ValueError(f"Unknown workflow status: {status!r}")
    steps = []
    for step in state.steps:
        if step.key == step_key:
            steps.append(
                StepRecord(
                    key=step.key,
                    label=step.label,
                    status=status,
                    message=message,
                    artifacts=artifacts,
                    updated_at=utc_now_iso(),
                )
            )
        else:
            steps.append(step)
    return WorkflowState(
        schema_version=state.schema_version,
        project_root=state.project_root,
        output_root=state.output_root,
        steps=tuple(steps),
        selected_conditions=state.selected_conditions,
        frozen_excluded_subjects=state.frozen_excluded_subjects,
        source_fingerprints=state.source_fingerprints,
        warnings=state.warnings,
        updated_at=utc_now_iso(),
    )


def with_selected_conditions(state: WorkflowState, conditions: tuple[str, ...]) -> WorkflowState:
    """Return state with selected condition names updated."""

    return WorkflowState(
        schema_version=state.schema_version,
        project_root=state.project_root,
        output_root=state.output_root,
        steps=state.steps,
        selected_conditions=tuple(str(value) for value in conditions),
        frozen_excluded_subjects=state.frozen_excluded_subjects,
        source_fingerprints=state.source_fingerprints,
        warnings=state.warnings,
        updated_at=utc_now_iso(),
    )


def with_frozen_exclusions(state: WorkflowState, exclusions: tuple[str, ...]) -> WorkflowState:
    """Return state with participant-level frozen exclusions updated."""

    return WorkflowState(
        schema_version=state.schema_version,
        project_root=state.project_root,
        output_root=state.output_root,
        steps=state.steps,
        selected_conditions=state.selected_conditions,
        frozen_excluded_subjects=normalize_participant_ids(exclusions),
        source_fingerprints=state.source_fingerprints,
        warnings=state.warnings,
        updated_at=utc_now_iso(),
    )


def file_fingerprint(path: Path) -> dict[str, Any]:
    """Return a small stale-state fingerprint for a source artifact."""

    target = Path(path)
    if not target.exists():
        return {"path": str(target), "exists": False}
    stat = target.stat()
    return {
        "path": str(target),
        "exists": True,
        "size": int(stat.st_size),
        "mtime_ns": int(stat.st_mtime_ns),
    }


def load_qc_decisions(project_root: Path) -> tuple[QCDecision, ...]:
    """Load project-local QC decisions."""

    path = qc_decisions_path(project_root)
    if not path.exists():
        return ()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return ()
    rows = payload.get("decisions") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return ()
    return tuple(QCDecision.from_mapping(row) for row in rows if isinstance(row, dict))


def save_qc_decisions(project_root: Path, decisions: tuple[QCDecision, ...]) -> Path:
    """Persist project-local QC decisions."""

    path = qc_decisions_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": QC_DECISION_SCHEMA_VERSION,
        "updated_at": utc_now_iso(),
        "decisions": [asdict(decision) for decision in decisions],
    }
    path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    return path


def excluded_participants(decisions: tuple[QCDecision, ...]) -> tuple[str, ...]:
    """Return participant IDs with manually confirmed exclude decisions."""

    return normalize_participant_ids(
        decision.participant_id
        for decision in decisions
        if decision.decision == "exclude" and decision.participant_id
    )


def normalize_participant_id(value: object) -> str:
    """Return an uppercase participant ID for matching report rows."""

    return str(value or "").strip().upper()


def normalize_participant_ids(values: Any) -> tuple[str, ...]:
    """Return sorted, de-duplicated participant IDs."""

    seen = {normalize_participant_id(value) for value in values or ()}
    seen.discard("")
    return tuple(sorted(seen, key=_participant_sort_key))


def relative_artifact(project_root: Path, artifact: Path) -> str:
    """Return a project-relative artifact path when possible."""

    root = Path(project_root).resolve()
    target = Path(artifact).resolve()
    try:
        return str(target.relative_to(root))
    except ValueError:
        return str(target)


def _optional_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _participant_sort_key(value: str) -> tuple[int, str]:
    text = str(value).strip().upper()
    if text.startswith("P") and text[1:].isdigit():
        return int(text[1:]), text
    return 10**9, text


__all__ = (
    "QC_DECISIONS_NAME",
    "QC_DECISIONS_WORKBOOK_NAME",
    "SENSITIVITY_SUMMARY_NAME",
    "STEP_DATA_READY",
    "STEP_EXPORT_PACKAGE",
    "STEP_FIGURES",
    "STEP_FREEZE_ANALYSIS_SET",
    "STEP_LABELS",
    "STEP_ORDER",
    "STEP_OUTLIER_DECISIONS",
    "STEP_PUBLICATION_REPORT",
    "STEP_QC_REVIEW",
    "WORKFLOW_STATE_NAME",
    "QCDecision",
    "StepRecord",
    "WorkflowState",
    "excluded_participants",
    "file_fingerprint",
    "load_qc_decisions",
    "load_workflow_state",
    "qc_decisions_path",
    "relative_artifact",
    "save_qc_decisions",
    "save_workflow_state",
    "update_step",
    "utc_now_iso",
    "with_frozen_exclusions",
    "with_selected_conditions",
    "workflow_output_root",
    "workflow_state_path",
)
