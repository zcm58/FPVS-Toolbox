from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DIALOG = REPO_ROOT / "src" / "Main_App" / "gui" / "frequency_domain_qc_dialog.py"
WORKFLOW = REPO_ROOT / "src" / "Main_App" / "gui" / "processing_workflows.py"


def test_frequency_review_exposes_recording_scoped_evidence_without_a_default() -> None:
    source = DIALOG.read_text(encoding="utf-8")

    for label in (
        '"Recording"',
        '"Session / visit"',
        '"Condition"',
        '"Signed value"',
        '"Absolute value"',
        '"Harmonics"',
        '"Analysis window"',
        '"Independent QC"',
    ):
        assert label in source
    assert '_CHOOSE_DECISION = ""' in source
    assert '"Choose a decision…"' in source
    assert '"None — review flag only"' in source
    assert "validate_frequency_domain_qc_review_decisions" in source
    assert "combo.setCurrentIndex(saved_index)" not in source
    assert 'combo.setToolTip(context)' in source
    assert 'not in {_CHOOSE_DECISION, DECISION_RETAIN}' in source


def test_frequency_review_submits_exact_decisions_and_recording_reasons() -> None:
    dialog_source = DIALOG.read_text(encoding="utf-8")
    workflow_source = WORKFLOW.read_text(encoding="utf-8")

    assert "def review_decisions" in dialog_source
    assert "def manual_recording_reasons" in dialog_source
    assert "review_decisions=dialog.review_decisions()" in workflow_source
    assert "manual_recording_reasons=dialog.manual_recording_reasons()" in workflow_source


def test_cohort_only_summary_uses_the_persisted_value_without_false_zero() -> None:
    source = DIALOG.read_text(encoding="utf-8")

    assert 'value = item.get("value_uv")' in source
    assert 'value = item.get("abs_summed_bca_uv")' in source
    assert 'return "Unavailable", "Unavailable"' in source
