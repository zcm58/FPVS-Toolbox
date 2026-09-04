from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / "src" / "Main_App" / "gui" / "preprocessing_qc_workflow.py"


def _workflow_source() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def test_marker_review_precedes_every_signal_qc_decision() -> None:
    source = _workflow_source()
    workflow = source[source.index("def run_preprocessing_qc_workflow(") :]

    initial_scan = workflow.index("scan = _run_scan_embedded(")
    marker_review = workflow.index("scan = _review_marker_occurrences(")
    condition_review = workflow.index("if not _confirm_condition_crop_exclusions(")
    condition_scoped_rescan = workflow.index(
        "scan = _run_scan_embedded(",
        condition_review,
    )
    electrode_review = workflow.index("if active_infos and not _review_removed_electrodes(")

    assert (
        initial_scan
        < marker_review
        < condition_review
        < condition_scoped_rescan
        < electrode_review
    )


def test_marker_review_rescans_only_affected_files_and_blocks_unresolved() -> None:
    source = _workflow_source()
    start = source.index("def _review_marker_occurrences(")
    stop = source.index("\ndef _review_removed_electrodes(", start)
    review = source[start:stop]

    assert "affected_infos = [" in review
    assert "rescanned = _run_scan_embedded(" in review
    assert "affected_infos," in review
    assert "collect_marker_occurrence_reviews(merged_scan)" in review
    assert "if unresolved:" in review
    assert 'params["_fpvs_marker_review_decisions_by_file"]' in review


def test_successful_workflow_hands_full_event_plans_to_runner() -> None:
    source = _workflow_source()
    workflow = source[source.index("def run_preprocessing_qc_workflow(") :]

    assert 'params["_fpvs_preflight_event_plans_by_file"]' in workflow
    assert "canonical_event_plans_by_file(" in workflow
    assert workflow.index("canonical_event_plans_by_file(") > workflow.index(
        "_show_suspicious_remainder("
    )


def test_occurrence_review_offers_all_scientific_dispositions() -> None:
    source = _workflow_source()

    assert '"Use Verified Span"' in source
    assert '"Retain Full Occurrence"' in source
    assert '"Exclude Occurrence"' in source
    assert '"Cancel Processing"' in source
    assert '"marker_evidence_type_combo"' in source
    assert '"marker_evidence_note_edit"' in source
    assert '"marker_evidence_reference_edit"' in source
    assert '"marker_exclusion_reason_dialog"' in source
    assert '"marker_exclusion_reason_edit"' in source
    assert "_collect_marker_exclusion_reason(host, item)" in source


def test_marker_review_shows_sample_and_time_evidence() -> None:
    source = _workflow_source()

    assert "from recording start" in source
    assert "duration" in source
