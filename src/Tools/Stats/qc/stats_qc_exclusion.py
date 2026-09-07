"""QC exclusion helpers for the Stats tool."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence

import numpy as np


logger = logging.getLogger("Tools.Stats")

QC_REASON_SUMABS = "QC_SUMABS"
QC_REASON_MAXABS = "QC_MAXABS"
QC_REASON_ABSOLUTE_ELECTRODE = "QC_ABSOLUTE_ELECTRODE_SUMMED_BCA"

QC_SEVERITY_WARNING = "WARNING"
QC_SEVERITY_CRITICAL = "CRITICAL"
QC_SEVERITY_EXTREME = "EXTREME"

QC_METRIC_LABELS = {
    QC_REASON_SUMABS: "Unusually large total response",
    QC_REASON_MAXABS: "Unusually large peak response",
    QC_REASON_ABSOLUTE_ELECTRODE: "Unusually large electrode summed BCA",
}

# Historical public defaults retained for call/schema compatibility only.
QC_DEFAULT_WARN_THRESHOLD = 6.0
QC_DEFAULT_CRITICAL_THRESHOLD = 10.0

# Historical ROI floors are not used by active electrode screening.
QC_DEFAULT_WARN_ABS_FLOOR_SUMABS = 5.0
QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS = 10.0
QC_DEFAULT_WARN_ABS_FLOOR_MAXABS = 1.0
QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS = 2.0


@dataclass(frozen=True)
class QcViolation:
    """Represent the QcViolation part of the Stats tool."""
    condition: str
    roi: str
    metric: str
    severity: str
    value: float
    robust_center: float
    robust_spread: float
    robust_score: float
    threshold_used: float
    abs_floor_used: float
    trigger_harmonic_hz: Optional[float] = None
    roi_mean_bca_at_trigger: Optional[float] = None
    recording_id: str = ""
    participant_id: str = ""
    decision: str = ""
    decision_reason: str = ""
    evidence_fingerprint: str = ""
    source: str = "legacy_stats_local_screen"
    shared_decision_fingerprint: str = ""
    shared_source_fingerprint: str = ""
    shared_evidence_fingerprint: str = ""
    harmonic_selection_fingerprint: str = ""
    authority: str = "review_only"


@dataclass(frozen=True)
class QcParticipantReport:
    """Represent the QcParticipantReport part of the Stats tool."""
    participant_id: str
    reasons: list[str]
    n_violations: int
    worst_value: float
    worst_condition: str
    worst_roi: str
    worst_metric: str
    robust_center: float
    robust_spread: float
    robust_score: float
    threshold_used: float
    trigger_harmonic_hz: Optional[float]
    roi_mean_bca_at_trigger: Optional[float]
    violations: list[QcViolation]


@dataclass(frozen=True)
class QcExclusionSummary:
    """Represent the QcExclusionSummary part of the Stats tool."""
    n_subjects_before: int
    n_subjects_flagged: int
    n_subjects_after: int
    warn_threshold: float
    critical_threshold: float
    warn_abs_floor_sumabs: float
    critical_abs_floor_sumabs: float
    warn_abs_floor_maxabs: float
    critical_abs_floor_maxabs: float


@dataclass(frozen=True)
class QcExclusionReport:
    """Represent the QcExclusionReport part of the Stats tool."""
    summary: QcExclusionSummary
    participants: list[QcParticipantReport]
    screened_conditions: list[str]
    screened_rois: list[str]
    source: str = "legacy_stats_local_screen"
    source_fingerprint: str = ""
    decision_fingerprint: str = ""
    evidence_fingerprint: str = ""
    harmonic_selection_fingerprint: str = ""
    review_complete: bool = False
    screening_status: str = "performed"
    authority: str = "review_only"
    technical_statuses: tuple[dict[str, object], ...] = ()

    @property
    def excluded_pids(self) -> set[str]:
        """Backward-compatible accessor for excluded participant IDs."""
        if self.source == "shared_project_qc17_review":
            # The shared experimental QC-17 report carries review findings and
            # audit context. Final coverage applies its explicit decisions; the
            # Stats adapter itself has no participant-exclusion authority.
            return set()
        for attr_name in ("excluded_subjects", "excluded_participants", "excluded_ids"):
            attr_value = getattr(self, attr_name, None)
            if isinstance(attr_value, (set, list, tuple)):
                return {str(pid) for pid in attr_value}

        exclusions = getattr(self, "exclusions", None)
        if isinstance(exclusions, dict):
            return {str(pid) for pid in exclusions.keys()}
        if isinstance(exclusions, list):
            extracted: set[str] = set()
            for item in exclusions:
                if isinstance(item, (list, tuple)) and item:
                    extracted.add(str(item[0]))
                    continue
                pid_value = getattr(item, "pid", None)
                if pid_value is None:
                    pid_value = getattr(item, "participant_id", None)
                if pid_value is not None:
                    extracted.add(str(pid_value))
            if extracted:
                return extracted

        participants = getattr(self, "participants", None)
        if isinstance(participants, list):
            return {
                str(pid)
                for pid in (
                    getattr(participant, "participant_id", None) for participant in participants
                )
                if pid is not None
            }

        return set()


def format_qc_violation(violation: QcViolation) -> str:
    """Handle the format qc violation step for the Stats workflow."""
    label = QC_METRIC_LABELS.get(violation.metric, str(violation.metric))
    electrode_review = (
        violation.source == "shared_project_qc17_review"
        and violation.metric == QC_REASON_ABSOLUTE_ELECTRODE
    )
    lines = [f"{label} — {violation.severity}"]
    if electrode_review:
        # The historical `roi` slot carries the exact electrode identity in
        # shared review reports; preserve that schema without mislabeling it.
        lines.extend([
            f"Condition: {violation.condition}, Electrode: {violation.roi}",
            f"Summed-BCA magnitude: {violation.value:.4f} µV",
        ])
        if np.isfinite(violation.threshold_used):
            lines.append(f"Review threshold: {violation.threshold_used:.4f} µV")
    else:
        lines.extend([
            f"Condition: {violation.condition}, ROI: {violation.roi}, value: {violation.value:.4f}",
            (
                f"Robust score: {violation.robust_score:.3f} "
                f"(threshold {violation.threshold_used:.2f}, abs floor {violation.abs_floor_used:.2f})"
            ),
            (
                f"Robust center: {violation.robust_center:.4f}, "
                f"robust spread: {violation.robust_spread:.4f}"
            ),
        ])
    if not electrode_review and violation.trigger_harmonic_hz is not None:
        lines.append(
            "Trigger harmonic: "
            f"{violation.trigger_harmonic_hz:.3f} Hz, "
            f"mean BCA at trigger: {violation.roi_mean_bca_at_trigger:.4f}"
        )
    if violation.recording_id:
        lines.append(f"Recording: {violation.recording_id}")
    if violation.decision:
        decision_text = f"Saved QC-17 decision: {violation.decision}"
        if violation.decision_reason:
            decision_text += f" ({violation.decision_reason})"
        lines.append(decision_text)
    if violation.source == "shared_project_qc17_review":
        lines.append("Source: shared experimental QC-17 review evidence")
    return "\n".join(lines)


def load_shared_frequency_qc_review(
    *,
    project_root: str | Path,
    subjects: Sequence[str],
    conditions_all: Sequence[str],
    rois_all: Mapping[str, Sequence[str]],
    log_func: Optional[Callable[[str], None]] = None,
) -> QcExclusionReport:
    """Adapt saved QC-17 evidence for Stats without recomputing a BCA screen."""

    from Main_App.processing.frequency_domain_qc import (
        is_roi_frequency_qc_entry,
        load_current_frequency_qc_review_evidence,
        resolve_frequency_qc_coverage_decisions,
    )

    root = Path(project_root).resolve()
    decisions = resolve_frequency_qc_coverage_decisions(root)
    if not decisions.review_complete:
        raise RuntimeError(
            "Stats requires a current completed experimental summed-BCA review. "
            "Run post-processing and finish the QC-17 GUI review first."
        )
    review_evidence = load_current_frequency_qc_review_evidence(root)
    decision_by_finding = {
        str(row.get("finding_fingerprint") or ""): row
        for row in decisions.reviewed_decisions
        if str(row.get("finding_fingerprint") or "") and not is_roi_frequency_qc_entry(row)
    }
    findings = [finding for finding in (
        *_mapping_rows(review_evidence.get("ordinary_findings")),
        *_mapping_rows(review_evidence.get("reconfirmation_findings")),
    ) if not is_roi_frequency_qc_entry(finding)]
    finding_fingerprints = {
        str(finding.get("finding_fingerprint") or "")
        for finding in findings
        if str(finding.get("finding_fingerprint") or "")
    }
    for row in decisions.reviewed_decisions:
        if is_roi_frequency_qc_entry(row):
            continue
        finding_fingerprint = str(row.get("finding_fingerprint") or "")
        if (
            not finding_fingerprint
            or finding_fingerprint in finding_fingerprints
            or str(row.get("decision") or "") == "retain"
        ):
            continue
        evidence = row.get("evidence")
        if not isinstance(evidence, Mapping):
            raise RuntimeError(
                "Saved QC-17 exclusion lacks its reviewed evidence. Run "
                "post-processing and complete the review again."
            )
        findings.append(
            {
                **dict(evidence),
                "participant_id": str(row.get("participant_id") or ""),
                "recording_id": str(row.get("recording_id") or ""),
                "session_id": str(row.get("session_id") or ""),
                "visit_index": row.get("visit_index"),
                "condition": str(row.get("condition") or ""),
                "electrode": str(row.get("electrode") or ""),
                "roi": str(row.get("roi") or ""),
                "finding_fingerprint": finding_fingerprint,
            }
        )
        finding_fingerprints.add(finding_fingerprint)
    subject_lookup = {str(value).casefold(): str(value) for value in subjects}
    by_identity: dict[str, list[QcViolation]] = {}
    for finding in findings:
        finding_fingerprint = str(finding.get("finding_fingerprint") or "")
        row = decision_by_finding.get(finding_fingerprint)
        if row is None:
            raise RuntimeError(
                "Saved QC-17 evidence lacks its exact reviewed decision. "
                "Run post-processing and complete the review again."
            )
        metric = _shared_qc_metric(finding)
        if metric is None:
            continue
        participant_id = str(row.get("participant_id") or "")
        recording_id = str(row.get("recording_id") or "")
        identity = (
            subject_lookup.get(recording_id.casefold())
            or subject_lookup.get(participant_id.casefold())
            or recording_id
            or participant_id
        )
        if not identity:
            continue
        value = _finite_or_nan(
            finding.get("value_uv")
            if finding.get("value_uv") is not None
            else finding.get("abs_summed_bca_uv")
        )
        severity = str(
            finding.get("band_crossed") or finding.get("severity") or "WARNING"
        ).upper()
        if "EXTREME" in severity or "RECONFIRM" in severity:
            severity = QC_SEVERITY_EXTREME
        elif "STRONG" in severity:
            severity = "STRONG"
        else:
            severity = QC_SEVERITY_WARNING
        violation = QcViolation(
            condition=str(row.get("condition") or ""),
            roi=str(finding.get("roi") or finding.get("electrode") or ""),
            metric=metric,
            severity=severity,
            value=value,
            robust_center=_finite_or_nan(finding.get("robust_center_uv")),
            robust_spread=_finite_or_nan(finding.get("robust_spread_uv")),
            robust_score=_finite_or_nan(finding.get("robust_score")),
            threshold_used=_finite_or_nan(finding.get("threshold_used")),
            abs_floor_used=_finite_or_nan(
                finding.get("absolute_floor_used_uv")
            ),
            trigger_harmonic_hz=_optional_finite_float(
                finding.get("peak_harmonic_hz")
            ),
            roi_mean_bca_at_trigger=_optional_finite_float(
                finding.get("peak_signed_roi_mean_uv")
            ),
            recording_id=recording_id,
            participant_id=participant_id,
            decision=str(row.get("decision") or ""),
            decision_reason=str(row.get("reason") or ""),
            evidence_fingerprint=finding_fingerprint,
            source="shared_project_qc17_review",
            shared_decision_fingerprint=decisions.decision_fingerprint,
            shared_source_fingerprint=str(
                review_evidence.get("source_fingerprint") or ""
            ),
            shared_evidence_fingerprint=str(
                review_evidence.get("evidence_fingerprint") or ""
            ),
            harmonic_selection_fingerprint=str(
                finding.get("harmonic_selection_fingerprint")
                or review_evidence.get("harmonic_selection_fingerprint")
                or ""
            ),
            authority="review_only",
        )
        by_identity.setdefault(identity, []).append(violation)

    participants = [
        _shared_qc_participant_report(identity, violations)
        for identity, violations in sorted(by_identity.items(), key=lambda item: item[0].casefold())
    ]
    technical_statuses = tuple(
        dict(item)
        for item in _mapping_rows(
            review_evidence.get("technical_statuses")
        ) if not is_roi_frequency_qc_entry(item)
    )
    screened_conditions = list(
        dict.fromkeys(
            [str(value) for value in conditions_all]
            + [violation.condition for values in by_identity.values() for violation in values]
        )
    )
    report = QcExclusionReport(
        summary=QcExclusionSummary(
            n_subjects_before=len(subjects),
            n_subjects_flagged=len(participants),
            n_subjects_after=len(subjects),
            # Retain historical export columns without presenting retired ROI
            # thresholds as active electrode screening settings.
            warn_threshold=float("nan"),
            critical_threshold=float("nan"),
            warn_abs_floor_sumabs=float("nan"),
            critical_abs_floor_sumabs=float("nan"),
            warn_abs_floor_maxabs=float("nan"),
            critical_abs_floor_maxabs=float("nan"),
        ),
        participants=participants,
        screened_conditions=screened_conditions,
        screened_rois=[],
        source="shared_project_qc17_review",
        source_fingerprint=str(review_evidence.get("source_fingerprint") or ""),
        decision_fingerprint=decisions.decision_fingerprint,
        evidence_fingerprint=str(
            review_evidence.get("evidence_fingerprint") or ""
        ),
        harmonic_selection_fingerprint=str(
            review_evidence.get("harmonic_selection_fingerprint") or ""
        ),
        review_complete=True,
        screening_status=str(
            review_evidence.get("screening_status") or "performed"
        ),
        authority="review_only",
        technical_statuses=technical_statuses,
    )
    _log_message(
        log_func,
        "Stats reused the saved experimental QC-17 review; no separate "
        "summed-BCA screen was calculated.",
    )
    return report


def _shared_qc_metric(evidence: Mapping[str, object]) -> str | None:
    finding_type = str(evidence.get("finding_type") or "")
    if finding_type == "absolute_electrode_summed_bca":
        return QC_REASON_ABSOLUTE_ELECTRODE
    if (
        finding_type == "prior_outcome_informed_exclusion_reconfirmation"
        and str(evidence.get("electrode") or "")
    ):
        return QC_REASON_ABSOLUTE_ELECTRODE
    return None


def _shared_qc_participant_report(
    identity: str,
    violations: Sequence[QcViolation],
) -> QcParticipantReport:
    ordered = list(violations)
    worst = max(
        ordered,
        key=lambda item: abs(item.value) if np.isfinite(item.value) else -1.0,
    )
    return QcParticipantReport(
        participant_id=identity,
        reasons=sorted({item.metric for item in ordered}),
        n_violations=len(ordered),
        worst_value=worst.value,
        worst_condition=worst.condition,
        worst_roi=worst.roi,
        worst_metric=worst.metric,
        robust_center=worst.robust_center,
        robust_spread=worst.robust_spread,
        robust_score=worst.robust_score,
        threshold_used=worst.threshold_used,
        trigger_harmonic_hz=worst.trigger_harmonic_hz,
        roi_mean_bca_at_trigger=worst.roi_mean_bca_at_trigger,
        violations=ordered,
    )


def _finite_or_nan(value: object) -> float:
    parsed = _optional_finite_float(value)
    return float("nan") if parsed is None else parsed


def _optional_finite_float(value: object) -> float | None:
    try:
        parsed = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return parsed if np.isfinite(parsed) else None


def _mapping_rows(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes, bytearray)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def qc_metric_label(metric: str) -> str:
    """Handle the qc metric label step for the Stats workflow."""
    return QC_METRIC_LABELS.get(metric, str(metric))


def _log_message(log_func: Optional[Callable[[str], None]], message: str) -> None:
    """Handle the log message step for the Stats workflow."""
    if log_func:
        log_func(message)
    else:
        logger.debug(message)


def run_qc_exclusion(
    *,
    subjects: list[str],
    subject_data: Dict[str, Dict[str, str]],
    conditions_all: list[str],
    rois_all: Dict[str, List[str]],
    base_freq: float,
    warn_threshold: float = QC_DEFAULT_WARN_THRESHOLD,
    critical_threshold: float = QC_DEFAULT_CRITICAL_THRESHOLD,
    warn_abs_floor_sumabs: float = QC_DEFAULT_WARN_ABS_FLOOR_SUMABS,
    critical_abs_floor_sumabs: float = QC_DEFAULT_CRITICAL_ABS_FLOOR_SUMABS,
    warn_abs_floor_maxabs: float = QC_DEFAULT_WARN_ABS_FLOOR_MAXABS,
    critical_abs_floor_maxabs: float = QC_DEFAULT_CRITICAL_ABS_FLOOR_MAXABS,
    log_func: Optional[Callable[[str], None]] = None,
) -> QcExclusionReport:
    """Return a compatibility report for the retired ROI amplitude screen.

    Projectless callers keep their return shape, without reading workbooks or
    calculating ROI QC. Managed projects consume electrode review evidence via
    ``load_shared_frequency_qc_review``. Nonfinite DV integrity is independent.
    """
    _log_message(log_func, "ROI-level summed-BCA QC is retired; no ROI screen was performed.")
    return QcExclusionReport(
        summary=QcExclusionSummary(
            n_subjects_before=len(subjects),
            n_subjects_flagged=0,
            n_subjects_after=len(subjects),
            warn_threshold=float("nan"),
            critical_threshold=float("nan"),
            warn_abs_floor_sumabs=float("nan"),
            critical_abs_floor_sumabs=float("nan"),
            warn_abs_floor_maxabs=float("nan"),
            critical_abs_floor_maxabs=float("nan"),
        ),
        participants=[],
        screened_conditions=[],
        screened_rois=[],
        source="retired_roi_screen",
        screening_status="not_performed",
        review_complete=False,
        authority="none",
    )
