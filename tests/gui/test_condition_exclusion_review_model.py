from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

import pytest

from Main_App.gui.condition_exclusion_review_model import (
    evidence_text,
    needs_attention,
    reference_text,
    status_label,
)
from Main_App.processing.full_fft_grid_qc import FullFftGridAudit, FullFftGridObservation
from Main_App.processing.missing_condition_outputs import MissingConditionOutput


def _observation(**changes) -> FullFftGridObservation:
    values = dict(
        participant_id="P9",
        condition="Neutral Angry",
        path=Path("/project/processed/P9_Neutral Angry_Results.xlsx"),
        group_id="group-2",
        group_label="Comparison group",
        oddball_cycles=36,
        duration_s=120.0,
        bin_spacing_hz=1 / 120,
        frequency_column_count=6001,
        issue=None,
        already_excluded=False,
    )
    values.update(changes)
    return FullFftGridObservation(**values)


def _audit(observation: FullFftGridObservation, **changes) -> FullFftGridAudit:
    values = dict(
        observations=(observation,),
        reference_oddball_cycles=36,
        reference_support=1,
        reference_total=1,
        oddball_frequency_hz=0.3,
    )
    values.update(changes)
    return FullFftGridAudit(**values)


@pytest.mark.parametrize("already_excluded", [False, True])
def test_attention_keeps_problem_rows_even_if_previously_excluded(already_excluded) -> None:
    observation = _observation(oddball_cycles=30, already_excluded=already_excluded)
    audit = _audit(observation)

    assert needs_attention(observation, audit)
    assert status_label(observation, audit) == "Different length"


def test_nondefault_protocol_display_uses_project_reference_not_majority() -> None:
    observation = _observation()
    # No supporting workbook is required to display an explicit project setting.
    audit = _audit(observation, reference_support=0, reference_total=143)

    assert reference_text(audit) == "Project reference: 36 oddball cycles / 120 s."
    assert status_label(observation, audit) == "Matches"
    assert not needs_attention(observation, audit)
    assert "No crop-related exclusion is needed" in evidence_text(observation, audit)
    assert "Active valid FFT grids matching reference: 0/143" in evidence_text(observation, audit)
    assert "majority" not in reference_text(audit)


def test_missing_reference_stays_visible_without_guessing_a_valid_grid() -> None:
    observation = _observation()
    audit = _audit(observation, reference_oddball_cycles=None)

    assert needs_attention(observation, audit)
    assert status_label(observation, audit) == "No reference"
    assert "unavailable" in reference_text(audit)
    assert "expected oddball-cycle count" in evidence_text(observation, audit)


def test_full_issue_identity_and_numeric_evidence_survive_compact_status() -> None:
    issue = "Required neighboring-noise frequency 0.30833333333333335 Hz is absent."
    observation = _observation(
        issue=issue,
        recording_id="P9_followup_2",
        session_id="followup",
        session_label="Follow-up",
        visit_index=2,
    )
    audit = _audit(observation)
    before = asdict(audit)

    text = evidence_text(observation, audit)

    assert status_label(observation, audit) == "Check FFT"
    assert needs_attention(observation, audit)
    for value in (
        issue,
        "P9_followup_2",
        "Follow-up (followup)",
        "Visit: 2",
        "Comparison group (group-2)",
        str(observation.path),
        str(observation.bin_spacing_hz),
        "36",
        "120.0 s",
        "6001",
    ):
        assert value in text
    assert "neighboring-noise bins" in text
    assert text.index("Review the source") < text.index("Participant:")
    assert asdict(audit) == before


@pytest.mark.parametrize("outcome", ["blocked", "excluded", "unavailable"])
def test_missing_output_retains_outcome_and_processing_recovery_guidance(outcome) -> None:
    missing = MissingConditionOutput(
        participant_id="P9",
        condition="Neutral Angry",
        group_id=None,
        group_label=None,
        outcome_status=outcome,
    )
    audit = replace(_audit(_observation()), missing_condition_outputs=(missing,))

    text = evidence_text(missing, audit)

    assert status_label(missing, audit) == "Missing output"
    assert needs_attention(missing, audit)
    assert f"Recorded outcome: {outcome}" in text
    assert "found no input for this condition" in text
    assert "Missing start markers cannot be reconstructed" in text
    assert "rerun Processing before post-processing" in text
    assert "If you change this decision" in text
    assert text.index("rerun Processing") < text.index("Participant:")
    assert "saved outputs remain unchanged" in text
    assert "FFT bin spacing:" not in text


def test_missing_grid_values_stay_unavailable_and_exact_issue_remains() -> None:
    observation = _observation(
        oddball_cycles=None,
        duration_s=None,
        bin_spacing_hz=None,
        issue="No usable frequency columns found.",
    )
    audit = _audit(observation)

    text = evidence_text(observation, audit)

    assert "Observed oddball cycles: Unavailable" in text
    assert "Usable FFT crop: Unavailable" in text
    assert "FFT bin spacing: Unavailable" in text
    assert "Recorded issue: No usable frequency columns found." in text
