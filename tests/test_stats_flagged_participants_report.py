from __future__ import annotations

from PySide6.QtWidgets import QTableWidget

from Tools.Stats.PySide6.stats_core import PipelineId
from Tools.Stats.PySide6.stats_outlier_exclusion import (
    OUTLIER_REASON_LIMIT,
    format_worst_value_display,
)
from Tools.Stats.PySide6.stats_qc_exclusion import (
    QC_REASON_MAXABS,
    QC_REASON_SUMABS,
    QC_SEVERITY_WARNING,
    QcExclusionReport,
    QcExclusionSummary,
    QcParticipantReport,
    QcViolation,
)
from Tools.Stats.PySide6.stats_run_report import StatsRunReport
from Tools.Stats.PySide6.stats_ui_pyside6 import StatsWindow


def test_flagged_participants_report_dialog_labels(qtbot, monkeypatch) -> None:
    monkeypatch.setattr(StatsWindow, "_load_default_data_folder", lambda self: None, raising=False)
    window = StatsWindow(project_dir=".")
    qtbot.addWidget(window)

    violation = QcViolation(
        condition="CondA",
        roi="ROI1",
        metric=QC_REASON_MAXABS,
        severity=QC_SEVERITY_WARNING,
        value=12.3456,
        robust_center=0.0,
        robust_spread=1.0,
        robust_score=2.0,
        threshold_used=1.5,
        abs_floor_used=0.5,
        trigger_harmonic_hz=None,
        roi_mean_bca_at_trigger=None,
    )
    participant = QcParticipantReport(
        participant_id="P1",
        reasons=[QC_REASON_MAXABS],
        n_violations=1,
        worst_value=12.3456,
        worst_condition="CondA",
        worst_roi="ROI1",
        worst_metric=QC_REASON_MAXABS,
        robust_center=0.0,
        robust_spread=1.0,
        robust_score=2.0,
        threshold_used=1.5,
        trigger_harmonic_hz=None,
        roi_mean_bca_at_trigger=None,
        violations=[violation],
    )
    qc_summary = QcExclusionSummary(
        n_subjects_before=1,
        n_subjects_flagged=1,
        n_subjects_after=1,
        warn_threshold=6.0,
        critical_threshold=10.0,
        warn_abs_floor_sumabs=5.0,
        critical_abs_floor_sumabs=10.0,
        warn_abs_floor_maxabs=1.0,
        critical_abs_floor_maxabs=2.0,
    )
    qc_report = QcExclusionReport(
        summary=qc_summary,
        participants=[participant],
        screened_conditions=["CondA"],
        screened_rois=["ROI1"],
    )
    report = StatsRunReport(
        manual_excluded_pids=[],
        qc_report=qc_report,
        dv_report=None,
        required_exclusions=[],
        final_modeled_pids=[],
    )
    window._pipeline_run_reports[PipelineId.SINGLE] = report

    dialog = window._build_flagged_participants_dialog(PipelineId.SINGLE)
    assert dialog is not None
    qtbot.addWidget(dialog)

    table = dialog.findChild(QTableWidget)
    assert table is not None

    headers = [table.horizontalHeaderItem(i).text() for i in range(table.columnCount())]
    assert "Flag count" in headers
    assert all("n_flags" not in header for header in headers)

    flag_types_text = table.item(0, 1).text()
    assert "QC_MAXABS" not in flag_types_text
    assert "Large single-harmonic peak" in flag_types_text

    worst_value_text = table.item(0, 3).text()
    assert "Max |ROI mean BCA|" in worst_value_text
    assert "µV" in worst_value_text


def test_format_worst_value_display_qc_and_dv() -> None:
    qc_max_text, qc_max_tooltip = format_worst_value_display(QC_REASON_MAXABS, 1.23456)
    qc_sum_text, _ = format_worst_value_display(QC_REASON_SUMABS, 2.34567)

    assert "Max |ROI mean BCA|" in qc_max_text
    assert "µV" in qc_max_text
    assert qc_max_tooltip is None
    assert "Sum |ROI mean BCA|" in qc_sum_text
    assert "µV" in qc_sum_text

    dv_text, dv_tooltip = format_worst_value_display(
        OUTLIER_REASON_LIMIT,
        3.45678,
        dv_display_name="Z",
        dv_unit="",
    )
    dv_bca_text, _ = format_worst_value_display(
        OUTLIER_REASON_LIMIT,
        4.56789,
        dv_display_name="BCA",
        dv_unit="µV",
    )
    dv_fallback_text, dv_fallback_tooltip = format_worst_value_display(
        OUTLIER_REASON_LIMIT,
        5.6789,
    )

    assert dv_text.startswith("DV (Z):")
    assert "µV" not in dv_text
    assert dv_tooltip is None
    assert dv_bca_text.startswith("DV (BCA):")
    assert "µV" in dv_bca_text
    assert dv_fallback_text.startswith("DV:")
    assert dv_fallback_tooltip == "DV type not provided by the analysis context."
