"""Concise display text for FFT crop review; no data or exclusion decisions change."""

from __future__ import annotations

from typing import TYPE_CHECKING

from Main_App.processing.missing_condition_outputs import MissingConditionOutput

if TYPE_CHECKING:
    from Main_App.processing.full_fft_grid_qc import (
        FullFftGridAudit,
        FullFftGridObservation,
    )


def status_label(
    observation: FullFftGridObservation | MissingConditionOutput,
    audit: FullFftGridAudit,
) -> str:
    """Summarize the existing assessment without reevaluating the FFT grid."""

    if isinstance(observation, MissingConditionOutput):
        return "Missing output"
    if observation.issue is not None:
        return "Check FFT"
    if audit.reference_oddball_cycles is None:
        return "No reference"
    if observation.oddball_cycles != audit.reference_oddball_cycles:
        return "Different length"
    return "Matches"


def needs_attention(
    observation: FullFftGridObservation | MissingConditionOutput,
    audit: FullFftGridAudit,
) -> bool:
    """Keep unresolved or excluded problem rows visible in the attention filter."""

    return status_label(observation, audit) != "Matches"


def reference_text(audit: FullFftGridAudit) -> str:
    """Describe the project's reference, never a vote among available files."""

    if audit.reference_oddball_cycles is None or audit.reference_duration_s is None:
        return "Project reference: unavailable. Check project frequency settings."
    return (
        f"Project reference: {audit.reference_oddball_cycles} oddball cycles / "
        f"{audit.reference_duration_s:g} s."
    )


def evidence_text(
    observation: FullFftGridObservation | MissingConditionOutput,
    audit: FullFftGridAudit,
) -> str:
    """Keep complete identities and source evidence outside the compact table."""

    status = status_label(observation, audit)
    lines = [f"Status: {status}"]
    if isinstance(observation, MissingConditionOutput):
        lines.extend([
            "The last Processing run found no input for this condition, so there "
            "is no FFT crop to compare. Missing start markers cannot be reconstructed.",
            "Exclude this condition or correct its source. If you change this "
            "decision or correct the source, rerun Processing before post-processing.",
        ])
    else:
        lines.append(
            "A common FFT grid keeps harmonic and neighboring-noise bins "
            "aligned across the included data."
        )
        if status == "Matches":
            lines.append("This FFT crop matches the project reference. No crop-related exclusion is needed.")
        elif status == "No reference":
            lines.append("Check the project's expected oddball-cycle count before deciding which data to include.")
        else:
            lines.append("Review the source. Exclude this condition downstream, or correct the source and rerun Processing.")
    lines.extend(["", reference_text(audit), ""])

    session = observation.session_label or observation.session_id or "Unavailable"
    if observation.session_label and observation.session_id:
        if observation.session_label != observation.session_id:
            session = f"{observation.session_label} ({observation.session_id})"
    group = observation.group_label or observation.group_id or "Ungrouped"
    if observation.group_label and observation.group_id:
        if observation.group_label != observation.group_id:
            group = f"{observation.group_label} ({observation.group_id})"
    lines.extend([
        f"Participant: {observation.participant_id}",
        f"Condition: {observation.condition}",
        f"Recording: {observation.recording_id or 'Not registered'}",
        f"Session / phase-at-visit: {session}",
        f"Visit: {observation.visit_index if observation.visit_index is not None else 'Unavailable'}",
        f"Group: {group}",
        f"Active valid FFT grids matching reference: {audit.reference_support}/{audit.reference_total}",
        "",
    ])
    if isinstance(observation, MissingConditionOutput):
        lines.extend([
            "Source workbook: no condition output",
            f"Recorded outcome: {observation.outcome_status}",
        ])
    else:
        cycles = (
            str(observation.oddball_cycles)
            if observation.oddball_cycles is not None else "Unavailable"
        )
        duration = (
            f"{observation.duration_s} s"
            if observation.duration_s is not None else "Unavailable"
        )
        spacing = (
            f"{observation.bin_spacing_hz} Hz"
            if observation.bin_spacing_hz is not None else "Unavailable"
        )
        lines.extend([
            f"Observed oddball cycles: {cycles}",
            f"Usable FFT crop: {duration}",
            f"FFT bin spacing: {spacing}",
            f"Frequency columns: {observation.frequency_column_count}",
            f"Source workbook: {observation.path}",
        ])
        if observation.issue is not None:
            lines.append(f"Recorded issue: {observation.issue}")
    lines.extend([
        "",
        "Exclusions change downstream inclusion only; source data and saved outputs remain unchanged.",
    ])
    return "\n".join(lines)


__all__ = ["evidence_text", "needs_attention", "reference_text", "status_label"]
