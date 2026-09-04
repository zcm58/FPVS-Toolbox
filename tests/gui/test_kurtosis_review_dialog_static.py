from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
DIALOG_PATH = ROOT / "src" / "Main_App" / "gui" / "kurtosis_review_dialog.py"
SCANNER_PATH = ROOT / "src" / "Main_App" / "processing" / "kurtosis_review_scan.py"
WORKFLOW_PATH = ROOT / "src" / "Main_App" / "gui" / "preprocessing_qc_workflow.py"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_kurtosis_review_dialog_uses_pyside6_and_shared_components() -> None:
    source = _source(DIALOG_PATH)
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert "PySide6.QtCore" in imports
    assert "PySide6.QtGui" in imports
    assert "PySide6.QtWidgets" in imports
    assert "Main_App.gui.components" in imports
    assert "class KurtosisReviewDialog(AppDialog):" in source
    assert "Tkinter" not in source
    assert "CustomTkinter" not in source
    application_constructor = "Q" + "Application("
    assert application_constructor not in source
    assert ".exec(" not in source


def test_dialog_has_no_default_decision_and_requires_a_reason() -> None:
    source = _source(DIALOG_PATH)
    placeholder = source.index('decision.addItem("Choose Approve or Reject…", "")')
    approve = source.index("KURTOSIS_DECISION_APPROVE", placeholder)
    reject = source.index("KURTOSIS_DECISION_REJECT", approve)

    assert placeholder < approve < reject
    assert "decision.setCurrentIndex(0)" in source
    assert "reason = reason_control.text().strip()" in source
    assert "if not decision:" in source
    assert "if not reason:" in source
    assert "build_kurtosis_review_decision(" in source


def test_dialog_exposes_required_scientific_evidence_and_fixed_scope() -> None:
    source = _source(DIALOG_PATH)

    for label in (
        "Participant",
        "Recording / session",
        "Electrode",
        "Review status",
        "Affected analyzed conditions / occurrences",
        "Raw kurtosis",
        "Signed normalized score",
        "Threshold |z| >",
        "Approved corroborator state",
        "Other channel-health results",
        "Compact signal evidence",
        "Fixed repair scope",
    ):
        assert f'"{label}"' in source
    assert "whole processed recording" in source
    assert "Every analyzed condition named here" in source
    assert '", ".join(item.analyzed_conditions)' in source
    assert '"Whole processed recording → {conditions}"' in source
    assert '"Changed evidence — review again"' in source
    assert "display_only_channel_health_summary" in source
    assert "review-only; not an approved corroborator" in _source(SCANNER_PATH)


def test_compact_signal_view_is_bounded_and_presentation_only() -> None:
    source = _source(DIALOG_PATH)

    assert "class KurtosisSignalPreviewWidget(QWidget):" in source
    assert "def paintEvent(" in source
    assert "QPainter(self)" in source
    assert "QPolygonF" in source
    assert "drawPolyline" in source
    assert "setMaximumHeight(62)" in source
    assert "prepare_kurtosis_review_evidence" not in source
    assert "load_eeg_file" not in source


def test_cancel_and_close_cannot_expose_review_receipts() -> None:
    source = _source(DIALOG_PATH)

    assert "self.cancel_button.clicked.connect(self.reject)" in source
    assert "def reject(self)" in source
    assert "def closeEvent(self, event: QCloseEvent)" in source
    assert "self._accepted_receipts = None" in source
    assert "self.result() != QDialog.DialogCode.Accepted" in source
    assert "downstream processing remains blocked" in source


def test_dialog_merges_fingerprint_current_receipts_with_new_decisions() -> None:
    source = _source(DIALOG_PATH)

    assert "KurtosisReviewDecisionReconciliation" in source
    assert "review.processing_decisions_by_recording" in source
    assert "self._current_receipts = deepcopy(current_receipts)" in source
    assert "receipts = deepcopy(self._current_receipts)" in source


def test_scanner_remains_gui_neutral_and_callback_driven() -> None:
    source = _source(SCANNER_PATH)
    tree = ast.parse(source)
    imports = {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}

    assert all(not module.startswith("PySide6") for module in imports)
    assert "QWidget" not in source
    assert "QMessageBox" not in source
    assert "ProgressCallback = Callable[[str, int, int], None]" in source
    assert "CancelCallback = Callable[[], bool]" in source
    assert "should_cancel" in source
    assert "prepare_kurtosis_review_evidence(" in source
    assert "validate_source_analysis_span_plan(" in source
    assert "validate_raw_biosemi64_geometry(" in source
    assert "BIOSEMI64_MONTAGE_ID" in source


def test_preprocessing_workflow_runs_and_persists_the_fail_closed_review() -> None:
    source = _source(WORKFLOW_PATH)

    assert "class _KurtosisReviewWorker(QObject):" in source
    assert "scan_kurtosis_review(" in source
    assert "worker.moveToThread(thread)" in source
    assert "reconcile_kurtosis_review_decisions(scan, existing)" in source
    assert "KurtosisReviewDialog(reconciliation, parent=host)" in source
    assert "dialog.exec() != QDialog.DialogCode.Accepted" in source
    assert "KURTOSIS_REVIEW_DECISIONS_BY_RECORDING_KEY" in source
    assert "project.update_preprocessing(updated_preprocessing)" in source

    event_plan_index = source.index(
        'params["_fpvs_preflight_event_plans_by_file"] = existing_event_plans'
    )
    scan_index = source.index(
        "_run_kurtosis_review_scan_embedded(",
        event_plan_index,
    )
    remainder_index = source.index("_show_suspicious_remainder(", scan_index)
    assert event_plan_index < scan_index < remainder_index
