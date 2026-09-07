from __future__ import annotations

import ast
import re
from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from Main_App.projects.experimental_qc_settings import ExperimentalQcSettings, SummedBcaScreeningSettings


REPO_ROOT = Path(__file__).resolve().parents[2]
DIALOG = REPO_ROOT / "src" / "Main_App" / "gui" / "frequency_domain_qc_dialog.py"
WORKFLOW = REPO_ROOT / "src" / "Main_App" / "gui" / "processing_workflows.py"


def test_frequency_review_offers_no_narrow_exclusions_and_requires_confirmation_for_repair():
    source = DIALOG.read_text(encoding="utf-8")
    assert "DECISION_EXCLUDE_CONDITION_ELECTRODE" not in source
    assert "DECISION_EXCLUDE_CONDITION_ROI" not in source
    assert 'report.get("condition_specific_interpolation_enabled") is True' in source
    assert "repair_allowed = can_interpolate_finding(" in source
    assert '"I confirmed an artifact in this condition."' in source
    assert '"I confirmed an artifact in every listed condition."' in source
    assert 'payload["artifact_confirmed"]' in source
    assert "self.bulk_interpolate_button.setVisible(self._interpolation_enabled)" in source


@pytest.mark.parametrize("enabled", [False, True])
def test_experimental_editor_roundtrips_interpolation_capability_without_changing_other_settings(enabled):
    path = REPO_ROOT / "src/Main_App/gui/settings_panel.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    method = next(node for node in ast.walk(tree)
                  if isinstance(node, ast.FunctionDef) and node.name == "_experimental_qc_settings_from_editor")
    namespace = {"ExperimentalQcSettings": ExperimentalQcSettings,
                 "SummedBcaScreeningSettings": SummedBcaScreeningSettings}
    exec(compile(ast.Module(body=[method], type_ignores=[]), str(path), "exec"), namespace)
    original = ExperimentalQcSettings().with_raw_spectral_screening({"enabled": False})
    values = original.summed_bca_screening.to_manifest()
    controls = SimpleNamespace(
        project=SimpleNamespace(experimental_qc_settings=original),
        summed_bca_threshold_edits={key: SimpleNamespace(text=lambda value=value: str(value))
                                    for key, value in values.items() if key not in {"enabled", "policy_version"}},
        summed_bca_screening_enabled_check=SimpleNamespace(isChecked=lambda: True),
        raw_spectral_screening_enabled_check=SimpleNamespace(isChecked=lambda: False),
        condition_specific_interpolation_enabled_check=SimpleNamespace(isChecked=lambda: enabled),
    )
    result = namespace[method.name](controls)
    assert result == original.with_condition_specific_interpolation_enabled(enabled)
    assert "experimental_settings.condition_specific_interpolation_enabled" in source


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
    namespace = {"Mapping": Mapping, "re": re}
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


@pytest.mark.parametrize(
    "values, expected",
    [
        (["P10", "P2", "P1"], ["P1", "P2", "P10"]),
        (["PO10", "PO2", "PO1"], ["PO1", "PO2", "PO10"]),
        (["visit10", "Visit2", "visit1"], ["visit1", "Visit2", "visit10"]),
    ],
)
def test_column_sort_uses_natural_identifier_order(values, expected) -> None:
    assert sorted(values, key=_presentation_helpers()["_natural_sort_key"]) == expected


@pytest.mark.parametrize(
    "item, expected",
    [
        ({"summed_bca_uv": -12.345678}, 12.345678),
        ({"summed_bca_uv": -12.345678, "abs_summed_bca_uv": 9.876543}, 9.876543),
        ({"finding_type": "cohort_relative_summed_bca_context", "value_uv": -2.00049}, 2.00049),
        ({"finding_type": "cohort_relative_summed_bca_context", "abs_summed_bca_uv": 2.00041}, 2.00041),
    ],
)
def test_amplitude_sort_preserves_exact_unrounded_display_source(item, expected) -> None:
    original = deepcopy(item)
    assert _presentation_helpers()["_absolute_value"](item) == expected
    assert item == original


@pytest.mark.parametrize(
    "terms, filters, expected",
    [
        ([], {}, True),
        (["p2", "faces"], {}, True),
        (["p2", "objects"], {}, False),
        ([], {0: {"P2", "P10"}, 1: {"Faces"}}, True),
        ([], {0: {"P2"}, 1: {"Objects"}}, False),
        ([], {0: {"P20"}}, False),
        ([], {0: set()}, False),
        (["kurtosis"], {1: {"Faces"}, 4: {"Undecided"}}, True),
        (["missing"], {1: {"Faces"}}, False),
    ],
)
def test_column_filters_combine_exact_choices_with_existing_evidence_search(
    terms, filters, expected,
) -> None:
    helpers = _presentation_helpers()
    values = ["P2", "Faces", "PO8", "12.346 uV", "Undecided"]
    evidence = "Participant: P2\nCondition: Faces\nIndependent QC: Kurtosis review current"
    original = deepcopy(filters)
    assert helpers["_matches_filters"](evidence, values, terms, filters) is expected
    assert filters == original
