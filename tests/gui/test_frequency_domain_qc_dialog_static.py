from __future__ import annotations

import ast
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path

import pytest


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
    assert 'None — review flag only' in source
    assert "validate_frequency_domain_qc_review_decisions" in source
    assert "combo.setCurrentIndex(saved_index)" not in source
    assert 'combo.setToolTip(context)' in source
    assert 'not in {_CHOOSE_DECISION, DECISION_RETAIN}' in source
    assert '"Reason (optional)"' in source
    assert 'reason.setPlaceholderText("Optional reason")' in source


def test_frequency_review_submits_exact_decisions_and_recording_reasons() -> None:
    dialog_source = DIALOG.read_text(encoding="utf-8")
    workflow_source = WORKFLOW.read_text(encoding="utf-8")

    assert "def review_decisions" in dialog_source
    assert "def manual_recording_reasons" in dialog_source
    assert "review_decisions=dialog.review_decisions()" in workflow_source
    assert "manual_recording_reasons=dialog.manual_recording_reasons()" in workflow_source


def _presentation_helpers():
    """Execute the real pure formatting helpers without importing Qt."""
    tree = ast.parse(DIALOG.read_text(encoding="utf-8"))
    helpers = [node for node in tree.body if isinstance(node, ast.FunctionDef)]
    namespace = {"Mapping": Mapping}
    exec(compile(ast.Module(body=helpers, type_ignores=[]), str(DIALOG), "exec"), namespace)
    return namespace


@pytest.mark.parametrize(
    "values, expected_signed, expected_absolute",
    [
        ({"summed_bca_uv": -55.625, "abs_summed_bca_uv": 55.625}, "-55.625 uV", "55.625 uV"),
        ({"finding_type": "cohort_relative_summed_bca_context", "value_uv": 2.405}, "2.405 uV", "2.405 uV"),
        ({"finding_type": "cohort_relative_summed_bca_context", "abs_summed_bca_uv": 1.399}, "1.399 uV", "1.399 uV"),
        ({"finding_type": "cohort_relative_summed_bca_context"}, "Unavailable", "Unavailable"),
    ],
)
def test_selected_evidence_keeps_original_values_and_full_recording_context(
    values, expected_signed, expected_absolute,
) -> None:
    item = {
        "participant_id": "P01", "recording_id": "P01-visit2",
        "session_label": "Follow-up", "visit_index": 2, "condition": "Neutral Angry",
        "roi": "A very long ROI name", "band_crossed": "cohort_warning",
        "selected_harmonics_hz": [1.2, 2.4, 3.6, 4.8],
        "expected_analyzed_oddball_cycles": 144, "analyzed_duration_seconds": 120,
        "independent_qc": ["original evidence: " + "x" * 500], **values,
    }
    original = deepcopy(item)
    helpers = _presentation_helpers()
    signed, absolute = helpers["_value_texts"](item)
    assert (signed, absolute) == (expected_signed, expected_absolute)
    evidence = helpers["_finding_evidence_text"](
        item, "Control", signed, absolute, "Prior reviewed decision: Retain this finding.",
    )
    for text in (
        "Participant: P01", "Recording: P01-visit2", "Follow-up (visit 2)",
        "Group: Control", "Condition: Neutral Angry", "A very long ROI name",
        f"Signed value: {expected_signed}", f"Absolute value: {expected_absolute}",
        "cohort_warning", "4: 1.2, 2.4, 3.6, 4.8 Hz", "144 cycles / 120 s",
        item["independent_qc"][0], "Prior reviewed decision: Retain this finding.",
        "Choose a new decision for this review.",
    ):
        assert text in evidence
    assert item == original


def test_unavailable_input_context_keeps_each_status_instead_of_a_pass() -> None:
    helpers = _presentation_helpers()
    rows = [
        {"status": "complete", "participant_id": "P1"},
        {"status": "unavailable", "participant_id": "P9", "recording_id": "P9-visit2",
         "condition": "Neutral Angry", "roi": "LOT", "reason_codes": ["source_workbook_missing"]},
    ]
    unavailable = helpers["_technical_context_rows"]({"cohort_relative_rows": rows})
    assert unavailable == [rows[1]]
    assert helpers["_technical_context_text"](unavailable[0]) == (
        "P9-visit2 / Neutral Angry / LOT: source_workbook_missing"
    )
