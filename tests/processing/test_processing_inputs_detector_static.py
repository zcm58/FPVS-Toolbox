from __future__ import annotations

import ast
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_SOURCE_PATH = _ROOT / "src" / "Main_App" / "gui" / "processing_inputs.py"
_SOURCE = _SOURCE_PATH.read_text(encoding="utf-8")
_TREE = ast.parse(_SOURCE)
_WORKFLOW_PATH = (
    _ROOT / "src" / "Main_App" / "gui" / "preprocessing_qc_workflow.py"
)
_WORKFLOW_SOURCE = _WORKFLOW_PATH.read_text(encoding="utf-8")


def _function_source(name: str) -> str:
    node = next(
        candidate
        for candidate in _TREE.body
        if isinstance(candidate, ast.FunctionDef) and candidate.name == name
    )
    return ast.get_source_segment(_SOURCE, node) or ""


def test_processing_entry_prompts_once_and_persists_legacy_detector_choice() -> None:
    helper = _function_source(
        "_ensure_removed_electrode_detection_choice_ready"
    )
    validation = _function_source("validate_inputs")

    assert "removed_electrode_detection_choice_requires_confirmation" in helper
    assert "QMessageBox.question" in helper
    assert "QMessageBox.StandardButton.No" in helper
    assert "confirm_removed_electrode_detection_choice" in helper
    assert "project.save()" in helper
    assert "_ensure_removed_electrode_detection_choice_ready(host)" in validation


def test_processing_params_require_choice_and_carry_manual_authority_metadata() -> None:
    builder = _function_source("build_validated_params")

    assert "require_removed_electrode_detection_choice_ready(normalized)" in builder
    assert "MANUAL_REMOVED_ELECTRODES_ENABLED_KEY" in builder
    assert '"removed_electrode_detection_choice_schema_version"' in builder
    assert '"removed_electrode_detection_choice_status"' in builder
    assert '"removed_electrode_detection_choice_source"' in builder


def test_removed_electrode_review_preserves_auto_or_off_mode() -> None:
    assert "_settings_with_reviewed_manual_removed_electrodes" in _WORKFLOW_SOURCE
    assert (
        "updated[MANUAL_REMOVED_ELECTRODES_ENABLED_KEY] = True"
        in _WORKFLOW_SOURCE
    )
    assert "REMOVED_ELECTRODE_DETECTION_MODE_MANUAL" not in _WORKFLOW_SOURCE
