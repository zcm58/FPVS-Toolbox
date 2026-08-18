"""Dedicated non-blocking GUI for the versioned repeated-session analysis."""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QObject, QRunnable, Qt, QThreadPool, QUrl, Signal, Slot
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
)

from Main_App.gui.components import (
    ActionRow,
    AppDialog,
    SectionCard,
    StatusBanner,
    SurfaceSize,
    make_action_button,
    make_form_layout,
)
from Tools.Stats.analysis.repeated_session_analysis import (
    RepeatedSessionAnalysisResult,
    RepeatedSessionOutcome,
)
from Tools.Stats.analysis.repeated_session_contracts import FIXED_ORDER_CONFOUNDING
from Tools.Stats.io.repeated_session_project import (
    RepeatedSessionProjectData,
    analyze_repeated_session_project,
    default_repeated_session_results_path,
    load_repeated_session_project_data,
    write_repeated_session_results_workbook,
)
from Tools.Stats.widgets.elided_label import ElidedPathLabel


logger = logging.getLogger(__name__)


class _TaskSignals(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    finished = Signal()


class _Task(QRunnable):
    """Run one pure repeated-session task without touching widgets."""

    def __init__(self, callback: Callable[[], object]) -> None:
        super().__init__()
        self.callback = callback
        self.signals = _TaskSignals()

    @Slot()
    def run(self) -> None:
        try:
            result = self.callback()
        except Exception as exc:  # noqa: BLE001
            logger.exception("repeated_session_stats_task_failed")
            self.signals.failed.emit(f"{type(exc).__name__}: {exc}")
        else:
            self.signals.succeeded.emit(result)
        finally:
            self.signals.finished.emit()


def format_recording_pair_coverage(project_data: RepeatedSessionProjectData) -> str:
    """Return a concise, user-facing pre-analysis pair audit."""

    lines = [
        (
            f"Visit contrast: {project_data.contract.session_labels[1]} minus "
            f"{project_data.contract.session_labels[0]}"
        )
    ]
    for row in project_data.recording_pair_coverage().itertuples(index=False):
        lines.append(
            f"{row.group_label}: {row.n_complete_recording_pairs}/"
            f"{row.n_participants} complete recording pairs; "
            f"missing visit 1={row.n_missing_visit_1_recording}, "
            f"missing visit 2={row.n_missing_visit_2_recording}."
        )
    return "\n".join(lines)


def format_repeated_session_results(result: RepeatedSessionAnalysisResult) -> str:
    """Return a compact primary-result summary while preserving status codes."""

    def number(value: object, *, digits: int = 4) -> str:
        numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
        return "not estimable" if pd.isna(numeric) else f"{float(numeric):.{digits}g}"

    lines = [
        "Primary family: between-group comparison of participant visit-2 minus "
        "visit-1 changes (two-sided Welch tests; Holm correction)."
    ]
    for row in result.primary_results.itertuples(index=False):
        status = str(row.inference_status).replace("_", " ")
        lines.append(
            f"{row.condition} | {row.roi}: N pairs "
            f"{row.group_a_label}={row.n_pairs_group_a}, "
            f"{row.group_b_label}={row.n_pairs_group_b}; difference in change="
            f"{number(row.estimate_delta_difference_group_a_minus_group_b)}; "
            f"95% CI [{number(row.ci_difference_low)}, "
            f"{number(row.ci_difference_high)}]; Holm p="
            f"{number(row.p_adjusted)}; {status} ({row.status_code})."
        )
    lines.append("")
    lines.append(FIXED_ORDER_CONFOUNDING)
    return "\n".join(lines)


class RepeatedSessionAnalysisDialog(AppDialog):
    """Select prespecified outcomes and run the pair-delta analysis."""

    def __init__(
        self,
        project_root: str | Path,
        parent=None,
        *,
        thread_pool: QThreadPool | None = None,
    ) -> None:
        super().__init__(
            "Repeated Session / Phase-at-Visit Analysis",
            parent,
            size=SurfaceSize(920, 740, min_width=780, min_height=620),
        )
        self.project_root = Path(project_root).expanduser().resolve(strict=False)
        self._thread_pool = thread_pool or QThreadPool.globalInstance()
        self._tasks: list[_Task] = []
        self._project_data: RepeatedSessionProjectData | None = None
        self._last_result_path: Path | None = None

        self._build_ui()
        self._set_busy(True, "Loading canonical session-aware audit data…")
        self._start_task(
            lambda: load_repeated_session_project_data(self.project_root),
            on_success=self._on_project_data_loaded,
        )

    @property
    def last_result_path(self) -> Path | None:
        return self._last_result_path

    def _build_ui(self) -> None:
        caveat = StatusBanner(
            FIXED_ORDER_CONFOUNDING,
            self,
            variant="warning",
        )
        caveat.setObjectName("stats_repeated_session_order_warning")
        caveat.setWordWrap(True)
        self.root_layout.addWidget(caveat)

        design = SectionCard("Repeated design")
        design.setObjectName("stats_repeated_session_design")
        design_form = make_form_layout()
        self.groups_value = QLabel("Loading…")
        self.groups_value.setWordWrap(True)
        self.sessions_value = QLabel("Loading…")
        self.sessions_value.setWordWrap(True)
        self.source_path_value = ElidedPathLabel(str(self.project_root))
        design_form.addRow("Stable groups:", self.groups_value)
        design_form.addRow("Ordered sessions:", self.sessions_value)
        design_form.addRow("Full-audit source:", self.source_path_value)
        design.content_layout.addLayout(design_form)
        self.coverage_value = QLabel("Recording-pair coverage will appear after loading.")
        self.coverage_value.setObjectName("stats_repeated_session_pair_coverage")
        self.coverage_value.setWordWrap(True)
        self.coverage_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        design.content_layout.addWidget(self.coverage_value)
        self.root_layout.addWidget(design)

        outcomes = SectionCard("Prespecified outcomes")
        outcomes.setObjectName("stats_repeated_session_outcomes")
        outcome_note = QLabel(
            "Select the Condition × ROI outcomes declared for this run. The primary "
            "Holm family includes every selected outcome; unusable declared outcomes "
            "remain in the audit and are never replaced by a fallback test."
        )
        outcome_note.setWordWrap(True)
        outcomes.content_layout.addWidget(outcome_note)

        self.outcome_table = QTableWidget(0, 3, outcomes)
        self.outcome_table.setObjectName("stats_repeated_session_outcome_table")
        self.outcome_table.setHorizontalHeaderLabels(["Include", "Condition", "ROI"])
        self.outcome_table.setSelectionMode(QAbstractItemView.NoSelection)
        self.outcome_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.outcome_table.verticalHeader().setVisible(False)
        header = self.outcome_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.Stretch)
        header.setSectionResizeMode(2, QHeaderView.Stretch)
        self.outcome_table.setMinimumHeight(150)
        self.outcome_table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.outcome_table.itemChanged.connect(self._update_run_enabled)
        outcomes.content_layout.addWidget(self.outcome_table, 1)

        self.select_all_button = make_action_button("Select all", compact=True)
        self.select_none_button = make_action_button("Select none", compact=True)
        self.select_all_button.clicked.connect(lambda: self._set_all_outcomes(True))
        self.select_none_button.clicked.connect(lambda: self._set_all_outcomes(False))
        selection_actions = ActionRow(outcomes, alignment=Qt.AlignLeft)
        selection_actions.add_button(self.select_all_button)
        selection_actions.add_button(self.select_none_button)
        selection_actions.row_layout.addStretch(1)
        outcomes.content_layout.addWidget(selection_actions)
        self.root_layout.addWidget(outcomes, 1)

        results = SectionCard("Result and audit summary")
        results.setObjectName("stats_repeated_session_results")
        self.result_text = QPlainTextEdit(results)
        self.result_text.setReadOnly(True)
        self.result_text.setMinimumHeight(110)
        self.result_text.setPlaceholderText(
            "Primary estimates, complete-pair N, adjusted p-values, and export path "
            "will appear here."
        )
        results.content_layout.addWidget(self.result_text)
        self.root_layout.addWidget(results)

        self.status = StatusBanner("Loading repeated-session data…", self, variant="info")
        self.status.setObjectName("stats_repeated_session_status")
        self.status.setWordWrap(True)
        self.root_layout.addWidget(self.status)

        self.run_button = make_action_button(
            "Run Paired Change Analysis",
            variant="primary",
        )
        self.run_button.setObjectName("stats_run_repeated_session_analysis")
        self.run_button.setEnabled(False)
        self.run_button.setToolTip(
            "Compare participant visit-2 minus visit-1 changes between the two "
            "stable project groups for the explicitly selected outcomes."
        )
        self.run_button.clicked.connect(self._run_analysis)
        self.open_button = make_action_button("Open Results", compact=True)
        self.open_button.setEnabled(False)
        self.open_button.clicked.connect(self._open_results)
        self.close_buttons = QDialogButtonBox(QDialogButtonBox.Close, self)
        self.close_buttons.rejected.connect(self.reject)

        actions = ActionRow(self, alignment=Qt.AlignRight)
        actions.row_layout.addStretch(1)
        actions.add_button(self.run_button)
        actions.add_button(self.open_button)
        actions.row_layout.addWidget(self.close_buttons)
        self.root_layout.addWidget(actions)

    def _start_task(
        self,
        callback: Callable[[], object],
        *,
        on_success: Callable[[object], None],
    ) -> None:
        task = _Task(callback)
        self._tasks.append(task)
        task.signals.succeeded.connect(on_success)
        task.signals.failed.connect(self._on_task_failed)
        task.signals.finished.connect(lambda task=task: self._task_finished(task))
        self._thread_pool.start(task)

    def _task_finished(self, task: _Task) -> None:
        if task in self._tasks:
            self._tasks.remove(task)
        self._update_run_enabled()

    def _set_busy(self, busy: bool, message: str) -> None:
        self.status.setText(message)
        self.run_button.setEnabled(not busy and bool(self._selected_outcomes()))
        self.select_all_button.setEnabled(not busy and self._project_data is not None)
        self.select_none_button.setEnabled(not busy and self._project_data is not None)
        self.outcome_table.setEnabled(not busy and self._project_data is not None)
        self.close_buttons.setEnabled(not busy)

    @Slot(object)
    def _on_project_data_loaded(self, raw: object) -> None:
        if not isinstance(raw, RepeatedSessionProjectData):
            self._on_task_failed("The repeated-session loader returned an invalid result.")
            return
        self._project_data = raw
        contract = raw.contract
        self.groups_value.setText(
            f"{contract.group_labels[0]} [{contract.group_ids[0]}] vs "
            f"{contract.group_labels[1]} [{contract.group_ids[1]}]"
        )
        self.sessions_value.setText(contract.session_contrast_label)
        self.source_path_value.setText(str(raw.source_workbook))
        self.source_path_value.setToolTip(str(raw.source_workbook))
        self.coverage_value.setText(format_recording_pair_coverage(raw))
        self._populate_outcomes(raw.available_outcomes)
        self._set_busy(
            False,
            "Ready. Select at least one prespecified outcome; no outcome is selected by default.",
        )

    def _populate_outcomes(self, outcomes: tuple[RepeatedSessionOutcome, ...]) -> None:
        was_blocked = self.outcome_table.blockSignals(True)
        try:
            self.outcome_table.setRowCount(len(outcomes))
            for row_index, outcome in enumerate(outcomes):
                include = QTableWidgetItem("")
                include.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                include.setCheckState(Qt.Unchecked)
                include.setData(Qt.UserRole, outcome)
                self.outcome_table.setItem(row_index, 0, include)
                self.outcome_table.setItem(
                    row_index,
                    1,
                    QTableWidgetItem(outcome.condition),
                )
                self.outcome_table.setItem(row_index, 2, QTableWidgetItem(outcome.roi))
        finally:
            self.outcome_table.blockSignals(was_blocked)
        self._update_run_enabled()

    def _selected_outcomes(self) -> tuple[RepeatedSessionOutcome, ...]:
        selected: list[RepeatedSessionOutcome] = []
        for row_index in range(self.outcome_table.rowCount()):
            item = self.outcome_table.item(row_index, 0)
            if item is not None and item.checkState() == Qt.Checked:
                outcome = item.data(Qt.UserRole)
                if isinstance(outcome, RepeatedSessionOutcome):
                    selected.append(outcome)
        return tuple(selected)

    @Slot()
    def _update_run_enabled(self) -> None:
        self.run_button.setEnabled(
            self._project_data is not None
            and not self._tasks
            and bool(self._selected_outcomes())
        )

    def _set_all_outcomes(self, selected: bool) -> None:
        state = Qt.Checked if selected else Qt.Unchecked
        for row_index in range(self.outcome_table.rowCount()):
            item = self.outcome_table.item(row_index, 0)
            if item is not None:
                item.setCheckState(state)
        self._update_run_enabled()

    @Slot()
    def _run_analysis(self) -> None:
        project_data = self._project_data
        outcomes = self._selected_outcomes()
        if project_data is None or not outcomes:
            QMessageBox.information(
                self,
                "Select Outcomes",
                "Select at least one prespecified Condition × ROI outcome.",
            )
            return
        destination = default_repeated_session_results_path(self.project_root)
        self._set_busy(
            True,
            f"Analyzing {len(outcomes)} declared outcome(s) and writing the audit workbook…",
        )

        def analyze_and_write() -> tuple[RepeatedSessionAnalysisResult, Path]:
            result = analyze_repeated_session_project(
                project_data,
                outcomes=outcomes,
            )
            path = write_repeated_session_results_workbook(
                result,
                source_data=project_data.data,
                contract=project_data.contract,
                destination=destination,
            )
            return result, path

        self._start_task(analyze_and_write, on_success=self._on_analysis_complete)

    @Slot(object)
    def _on_analysis_complete(self, raw: object) -> None:
        if (
            not isinstance(raw, tuple)
            or len(raw) != 2
            or not isinstance(raw[0], RepeatedSessionAnalysisResult)
        ):
            self._on_task_failed("The repeated-session analysis returned an invalid result.")
            return
        result, path_value = raw
        path = Path(path_value)
        self._last_result_path = path
        self.result_text.setPlainText(
            format_repeated_session_results(result)
            + f"\n\nWorkbook: {path}"
        )
        self.open_button.setEnabled(True)
        self._set_busy(False, f"Analysis complete. Full results and audits: {path}")

    @Slot(str)
    def _on_task_failed(self, message: str) -> None:
        self._set_busy(False, f"Repeated-session analysis unavailable: {message}")
        QMessageBox.critical(self, "Repeated-Session Analysis", message)

    @Slot()
    def _open_results(self) -> None:
        path = self._last_result_path
        if path is None or not path.exists():
            QMessageBox.information(self, "Results Not Available", "Run the analysis first.")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))


__all__ = [
    "RepeatedSessionAnalysisDialog",
    "format_recording_pair_coverage",
    "format_repeated_session_results",
]
