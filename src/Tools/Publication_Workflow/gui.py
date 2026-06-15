"""Embedded PySide6 page for the Publication Workflow orchestrator."""

from __future__ import annotations

import logging
import os
from pathlib import Path

import pandas as pd
from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QGridLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QStyle,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from Main_App import SettingsManager
from Main_App.gui.components import (
    ActionRow,
    SectionCard,
    StatusBanner,
    SurfaceSize,
    configure_window_surface,
    make_action_button,
    show_error,
    show_info,
)
from Tools.Publication_Report.discovery import (
    discover_conditions,
    participant_ids,
    resolve_project_paths,
)
from Tools.Publication_Report.models import (
    QC_OUTLIER_VALUES_SHEET,
    REPORT_DOCX_NAME,
    REPORT_MARKDOWN_NAME,
    REPORT_WORKBOOK_NAME,
    PublicationReportRequest,
    ReportOutputOptions,
    ReportRoi,
    default_base_rate_roi,
    default_report_rois,
    report_rois_from_settings_pairs,
)
from Tools.Publication_Report.worker import PublicationReportWorker
from Tools.Publication_Workflow.state import (
    QCDecision,
    STEP_DATA_READY,
    STEP_EXPORT_PACKAGE,
    STEP_FIGURES,
    STEP_FREEZE_ANALYSIS_SET,
    STEP_OUTLIER_DECISIONS,
    STEP_PUBLICATION_REPORT,
    STEP_QC_REVIEW,
    WorkflowState,
    excluded_participants,
    load_qc_decisions,
    load_workflow_state,
    qc_decisions_path,
    relative_artifact,
    save_qc_decisions,
    save_workflow_state,
    update_step,
    with_frozen_exclusions,
    with_selected_conditions,
    workflow_output_root,
)

logger = logging.getLogger(__name__)

_DECISION_OPTIONS = ("include", "watch", "exclude")


class PublicationWorkflowWindow(QWidget):
    """Guided workflow for QC, exclusions, report generation, and figures."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project_root: str | None = None,
        *,
        embedded: bool = True,
    ) -> None:
        super().__init__(parent)
        surface_size = SurfaceSize(width=1120, height=780)
        if not embedded:
            surface_size = SurfaceSize(width=1120, height=780, min_width=980)
        configure_window_surface(self, title="Publication Workflow", size=surface_size)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._project_root = self._resolve_project_root(project_root)
        self._state: WorkflowState | None = None
        self._conditions = []
        self._thread: QThread | None = None
        self._worker: PublicationReportWorker | None = None
        self._run_mode = ""
        self._settings_fallback: SettingsManager | None = None
        self._last_generated_file_count = 0
        self._host_navigation_locked = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        self.status_banner = StatusBanner("Ready.", self)
        self.status_banner.setObjectName("publication_workflow_status")
        layout.addWidget(self.status_banner)

        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(8)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 3)
        grid.setRowStretch(0, 0)
        grid.setRowStretch(1, 1)
        grid.setRowStretch(2, 0)
        layout.addLayout(grid, 1)

        grid.addWidget(self._build_steps_card(), 0, 0)
        grid.addWidget(self._build_project_card(), 0, 1)
        grid.addWidget(self._build_qc_card(), 1, 0, 1, 2)
        grid.addWidget(self._build_report_card(), 2, 0)
        grid.addWidget(self._build_run_card(), 2, 1)

        self._apply_button_icons()
        self.refresh_workflow()

    def _resolve_project_root(self, provided_root: str | None) -> Path | None:
        if provided_root:
            root = Path(provided_root)
            if root.exists():
                return root
        env_root = os.environ.get("FPVS_PROJECT_ROOT")
        if env_root:
            root = Path(env_root)
            if root.exists():
                return root
        proj = getattr(self._embedded_host(), "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
            if root.exists():
                return root
        return None

    def _build_steps_card(self) -> SectionCard:
        card = SectionCard("Workflow", self, object_name="publication_workflow_steps")
        card.set_compact(280)
        self.steps_table = QTableWidget(0, 3, card)
        self.steps_table.setObjectName("publication_workflow_steps_table")
        self.steps_table.setHorizontalHeaderLabels(("Step", "Status", "Message"))
        self.steps_table.verticalHeader().setVisible(False)
        self.steps_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.steps_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.steps_table.setSelectionMode(QTableWidget.SingleSelection)
        self.steps_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.steps_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        card.content_layout.addWidget(self.steps_table)
        return card

    def _build_project_card(self) -> SectionCard:
        card = SectionCard("Project readiness", self, object_name="publication_workflow_project")
        card.set_compact(280)

        self.project_label = QLabel("Project: not loaded", card)
        self.project_label.setWordWrap(True)
        self.conditions_label = QLabel("Conditions: 0", card)
        self.participants_label = QLabel("Participants: 0", card)
        self.output_label = QLabel("Output: not resolved", card)
        for label in (self.conditions_label, self.participants_label, self.output_label):
            label.setProperty("caption", True)
            label.setWordWrap(True)

        action_row = ActionRow(card, alignment=Qt.AlignLeft)
        self.refresh_btn = make_action_button("Refresh", compact=True, parent=card)
        self.open_output_btn = make_action_button("Open output", compact=True, parent=card)
        self.refresh_btn.clicked.connect(self.refresh_workflow)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        action_row.add_button(self.refresh_btn)
        action_row.add_button(self.open_output_btn)

        card.content_layout.addWidget(self.project_label)
        card.content_layout.addWidget(self.conditions_label)
        card.content_layout.addWidget(self.participants_label)
        card.content_layout.addWidget(self.output_label)
        card.content_layout.addWidget(action_row)
        return card

    def _build_qc_card(self) -> SectionCard:
        card = SectionCard("QC review and outlier decisions", self, object_name="publication_workflow_qc")
        self.qc_table = QTableWidget(0, 8, card)
        self.qc_table.setObjectName("publication_workflow_qc_table")
        self.qc_table.setHorizontalHeaderLabels(
            (
                "Decision",
                "Participant",
                "Condition",
                "ROI",
                "Metric",
                "Value",
                "Direction",
                "Reason",
            )
        )
        self.qc_table.verticalHeader().setVisible(False)
        self.qc_table.setSelectionBehavior(QTableWidget.SelectRows)
        self.qc_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.qc_table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(6, QHeaderView.ResizeToContents)
        self.qc_table.horizontalHeader().setSectionResizeMode(7, QHeaderView.Stretch)

        actions = ActionRow(card, alignment=Qt.AlignLeft)
        self.run_qc_btn = make_action_button("Run QC", variant="primary", parent=card)
        self.save_decisions_btn = make_action_button("Freeze decisions", parent=card)
        self.open_qc_figures_btn = make_action_button("Open QC figures", compact=True, parent=card)
        self.run_qc_btn.clicked.connect(self._start_qc_run)
        self.save_decisions_btn.clicked.connect(self._save_decisions)
        self.open_qc_figures_btn.clicked.connect(self._open_qc_figures_folder)
        actions.add_button(self.run_qc_btn)
        actions.add_button(self.save_decisions_btn)
        actions.add_button(self.open_qc_figures_btn)

        self.qc_summary_label = QLabel("Run QC to populate candidate outliers.", card)
        self.qc_summary_label.setWordWrap(True)
        self.qc_summary_label.setProperty("caption", True)

        card.content_layout.addWidget(actions)
        card.content_layout.addWidget(self.qc_summary_label)
        card.content_layout.addWidget(self.qc_table, 1)
        return card

    def _build_report_card(self) -> SectionCard:
        card = SectionCard("Report and figures", self, object_name="publication_workflow_report")
        card.set_compact(245)
        actions = ActionRow(card, alignment=Qt.AlignLeft)
        self.generate_report_btn = make_action_button("Generate report", variant="primary", parent=card)
        self.open_report_tool_btn = make_action_button("Open report tool", compact=True, parent=card)
        self.open_scalp_maps_btn = make_action_button("Scalp maps", compact=True, parent=card)
        self.open_loreta_btn = make_action_button("LORETA", compact=True, parent=card)
        self.generate_report_btn.clicked.connect(self._start_report_run)
        self.open_report_tool_btn.clicked.connect(lambda: self._open_host_tool("open_publication_report"))
        self.open_scalp_maps_btn.clicked.connect(lambda: self._open_host_tool("open_publication_maps"))
        self.open_loreta_btn.clicked.connect(lambda: self._open_host_tool("open_loreta_visualizer"))
        for button in (
            self.generate_report_btn,
            self.open_report_tool_btn,
            self.open_scalp_maps_btn,
            self.open_loreta_btn,
        ):
            actions.add_button(button)

        self.report_summary_label = QLabel(
            "Reports generated here use the frozen participant-level exclusions.",
            card,
        )
        self.report_summary_label.setWordWrap(True)
        self.report_summary_label.setProperty("caption", True)
        card.content_layout.addWidget(actions)
        card.content_layout.addWidget(self.report_summary_label)
        return card

    def _build_run_card(self) -> SectionCard:
        card = SectionCard("Run status", self, object_name="publication_workflow_run")
        card.set_compact(245)
        self.progress = QProgressBar(card)
        self.progress.setValue(0)
        self.log_box = QPlainTextEdit(card)
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(96)
        self.log_box.setProperty("logSurface", True)
        actions = ActionRow(card, alignment=Qt.AlignLeft)
        self.cancel_btn = make_action_button("Cancel", compact=True, parent=card)
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._cancel_run)
        actions.add_button(self.cancel_btn)
        actions.row_layout.addWidget(self.progress, 1)
        card.content_layout.addWidget(actions)
        card.content_layout.addWidget(self.log_box, 1)
        return card

    def _apply_button_icons(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        style = app.style()
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.run_qc_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.save_decisions_btn.setIcon(style.standardIcon(QStyle.SP_DialogSaveButton))
        self.open_qc_figures_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.generate_report_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.open_report_tool_btn.setIcon(style.standardIcon(QStyle.SP_FileDialogDetailedView))
        self.open_scalp_maps_btn.setIcon(style.standardIcon(QStyle.SP_ComputerIcon))
        self.open_loreta_btn.setIcon(style.standardIcon(QStyle.SP_DesktopIcon))
        self.cancel_btn.setIcon(style.standardIcon(QStyle.SP_BrowserStop))

    def refresh_workflow(self) -> None:
        self._project_root = self._resolve_project_root(str(self._project_root) if self._project_root else None)
        if self._project_root is None:
            self._state = None
            self.project_label.setText("Project: not loaded")
            self.conditions_label.setText("Conditions: 0")
            self.participants_label.setText("Participants: 0")
            self.output_label.setText("Output: not resolved")
            self.status_banner.set_text("Open a project before running the Publication Workflow.")
            self.status_banner.set_variant("warning")
            self._populate_steps(None)
            self._set_ready_controls(False)
            return

        state = load_workflow_state(self._project_root)
        try:
            root, excel_root, output_root = resolve_project_paths(self._project_root)
        except Exception as exc:
            self._state = update_step(
                state,
                STEP_DATA_READY,
                status="blocked",
                message=str(exc),
            )
            self._populate_steps(self._state)
            self.status_banner.set_text(str(exc))
            self.status_banner.set_variant("error")
            self._set_ready_controls(False)
            return

        self._conditions = discover_conditions(excel_root)
        selected_conditions = tuple(condition.name for condition in self._conditions)
        state = with_selected_conditions(state, selected_conditions)
        participants = self._participant_count(excel_root, selected_conditions)
        if self._conditions and participants:
            state = update_step(
                state,
                STEP_DATA_READY,
                status="complete",
                message=f"{len(self._conditions)} condition(s), {participants} participant(s).",
                artifacts=(relative_artifact(root, excel_root),),
            )
            self.status_banner.set_text("Project data are ready for QC review.")
            self.status_banner.set_variant("success")
        else:
            state = update_step(
                state,
                STEP_DATA_READY,
                status="blocked",
                message="No processed condition workbooks were found.",
                artifacts=(relative_artifact(root, excel_root),),
            )
            self.status_banner.set_text("No processed condition workbooks were found.")
            self.status_banner.set_variant("warning")

        workbook_path = output_root / REPORT_WORKBOOK_NAME
        qc_rows_loaded = self._load_qc_candidates(workbook_path)
        if qc_rows_loaded:
            state = update_step(
                state,
                STEP_QC_REVIEW,
                status="complete",
                message=f"{qc_rows_loaded} candidate outlier row(s) loaded.",
                artifacts=(relative_artifact(root, workbook_path),),
            )
        elif workbook_path.exists():
            state = update_step(
                state,
                STEP_QC_REVIEW,
                status="warning",
                message="QC workbook exists, but no IQR candidate outliers were found.",
                artifacts=(relative_artifact(root, workbook_path),),
            )
        else:
            state = update_step(
                state,
                STEP_QC_REVIEW,
                status="ready" if self._conditions else "blocked",
                message="Run QC to generate manual-review figures and candidate outliers.",
            )

        decisions = load_qc_decisions(self._project_root)
        if decisions:
            exclusions = excluded_participants(decisions)
            state = with_frozen_exclusions(state, exclusions)
            state = update_step(
                state,
                STEP_OUTLIER_DECISIONS,
                status="complete",
                message=f"{len(decisions)} decision row(s), {len(exclusions)} excluded participant(s).",
                artifacts=(relative_artifact(root, qc_decisions_path(root)),),
            )
            state = update_step(
                state,
                STEP_FREEZE_ANALYSIS_SET,
                status="complete",
                message=f"Frozen exclusions: {', '.join(exclusions) if exclusions else 'none'}.",
                artifacts=(relative_artifact(root, qc_decisions_path(root)),),
            )
            self._apply_saved_decisions(decisions)
        elif qc_rows_loaded:
            state = update_step(
                state,
                STEP_OUTLIER_DECISIONS,
                status="ready",
                message="Review candidate outliers and freeze decisions.",
            )
            state = update_step(
                state,
                STEP_FREEZE_ANALYSIS_SET,
                status="blocked",
                message="Freeze decisions before generating the publication report.",
            )

        report_artifacts = self._existing_report_artifacts(output_root)
        if report_artifacts:
            state = update_step(
                state,
                STEP_PUBLICATION_REPORT,
                status="complete",
                message=f"{len(report_artifacts)} report artifact(s) found.",
                artifacts=tuple(relative_artifact(root, path) for path in report_artifacts),
            )
            state = update_step(
                state,
                STEP_EXPORT_PACKAGE,
                status="complete",
                message="Report package is available.",
                artifacts=(relative_artifact(root, output_root),),
            )
        else:
            state = update_step(
                state,
                STEP_PUBLICATION_REPORT,
                status="ready" if self._conditions else "blocked",
                message="Generate report after QC decisions are frozen.",
            )
            state = update_step(
                state,
                STEP_EXPORT_PACKAGE,
                status="blocked",
                message="Generate a report package first.",
            )

        state = update_step(
            state,
            STEP_FIGURES,
            status="ready",
            message="Use the figure handoff buttons after the report is generated.",
        )
        self._state = state
        save_workflow_state(self._project_root, state)

        self.project_label.setText(f"Project: {root}")
        self.conditions_label.setText(
            "Conditions: " + (", ".join(selected_conditions) if selected_conditions else "none")
        )
        self.participants_label.setText(f"Participants: {participants}")
        self.output_label.setText(f"Output: {output_root}")
        self._populate_steps(state)
        self._set_ready_controls(bool(self._conditions))

    def _participant_count(self, excel_root: Path, selected_conditions: tuple[str, ...]) -> int:
        try:
            from Tools.Publication_Report.discovery import discover_workbooks

            return len(participant_ids(discover_workbooks(excel_root, selected_conditions)))
        except (OSError, RuntimeError, ValueError):
            logger.exception("publication_workflow_participant_count_failed")
            return 0

    def _load_qc_candidates(self, workbook_path: Path) -> int:
        self.qc_table.setRowCount(0)
        if not workbook_path.exists():
            self.qc_summary_label.setText("Run QC to populate candidate outliers.")
            return 0
        try:
            frame = pd.read_excel(workbook_path, sheet_name=QC_OUTLIER_VALUES_SHEET)
        except (OSError, ValueError, ImportError, KeyError) as exc:
            logger.info("publication_workflow_qc_sheet_unavailable", extra={"error": str(exc)})
            self.qc_summary_label.setText("QC sheet was not found in the current workbook.")
            return 0
        if frame.empty or "iqr_outlier" not in frame.columns:
            self.qc_summary_label.setText("No QC candidate rows found.")
            return 0
        flags = frame.loc[frame["iqr_outlier"].fillna(False).astype(bool)].copy()
        flags = flags.loc[flags.get("metric_source", "").astype(str).eq("summed_bca_uv")]
        if flags.empty:
            self.qc_summary_label.setText("No summed-BCA IQR outliers were found.")
            return 0
        flags = flags.sort_values(["participant_id", "condition", "roi", "metric_source"])
        self._populate_qc_table(flags)
        self.qc_summary_label.setText(
            f"{len(flags)} summed-BCA candidate outlier row(s). Review and freeze decisions."
        )
        return int(len(flags))

    def _populate_qc_table(self, frame: pd.DataFrame) -> None:
        self.qc_table.setRowCount(len(frame))
        for row_index, row in enumerate(frame.to_dict(orient="records")):
            combo = QComboBox(self.qc_table)
            combo.addItems(_DECISION_OPTIONS)
            combo.setCurrentText("watch")
            self.qc_table.setCellWidget(row_index, 0, combo)
            values = [
                _cell_text(row.get("participant_id")),
                _cell_text(row.get("condition")),
                _cell_text(row.get("roi")),
                _cell_text(row.get("metric_label") or row.get("metric_source")),
                _number_text(row.get("value")),
                _cell_text(row.get("outlier_direction")),
                "",
            ]
            for col_index, text in enumerate(values, start=1):
                item = QTableWidgetItem(text)
                if col_index != 7:
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.qc_table.setItem(row_index, col_index, item)
            self.qc_table.item(row_index, 1).setData(Qt.UserRole, row)
        self.qc_table.resizeRowsToContents()

    def _apply_saved_decisions(self, decisions: tuple[QCDecision, ...]) -> None:
        lookup = {
            _decision_key(decision.participant_id, decision.condition, decision.roi, decision.metric_source): decision
            for decision in decisions
        }
        for row_index in range(self.qc_table.rowCount()):
            item = self.qc_table.item(row_index, 1)
            payload = item.data(Qt.UserRole) if item is not None else {}
            if not isinstance(payload, dict):
                continue
            key = _decision_key(
                payload.get("participant_id"),
                payload.get("condition"),
                payload.get("roi"),
                payload.get("metric_source"),
            )
            decision = lookup.get(key)
            if decision is None:
                continue
            combo = self.qc_table.cellWidget(row_index, 0)
            if isinstance(combo, QComboBox):
                combo.setCurrentText(decision.decision)
            reason_item = self.qc_table.item(row_index, 7)
            if reason_item is not None:
                reason_item.setText(decision.reason)

    def _populate_steps(self, state: WorkflowState | None) -> None:
        steps = state.steps if state is not None else ()
        self.steps_table.setRowCount(len(steps))
        for row_index, step in enumerate(steps):
            for col_index, text in enumerate((step.label, step.status, step.message)):
                item = QTableWidgetItem(text)
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.steps_table.setItem(row_index, col_index, item)
        self.steps_table.resizeRowsToContents()

    def _set_ready_controls(self, ready: bool) -> None:
        for button in (
            self.run_qc_btn,
            self.save_decisions_btn,
            self.generate_report_btn,
            self.open_qc_figures_btn,
            self.open_output_btn,
        ):
            button.setEnabled(ready and self._thread is None)

    def _settings_manager(self):
        host = self._embedded_host()
        manager = getattr(host, "settings", None)
        if manager is not None and hasattr(manager, "get"):
            return manager
        if self._settings_fallback is None:
            self._settings_fallback = SettingsManager()
        return self._settings_fallback

    def _settings_report_rois(self) -> tuple[ReportRoi, ...]:
        manager = self._settings_manager()
        try:
            get_roi_pairs = getattr(manager, "get_roi_pairs", None)
            pairs = get_roi_pairs() if callable(get_roi_pairs) else []
        except (AttributeError, TypeError, ValueError, RuntimeError):
            logger.exception("publication_workflow_roi_settings_load_failed")
            pairs = []
        return report_rois_from_settings_pairs(pairs or []) or default_report_rois()

    def _build_report_request(self, *, mode: str) -> PublicationReportRequest:
        if self._project_root is None:
            raise RuntimeError("Open a project before running the Publication Workflow.")
        root, excel_root, output_root = resolve_project_paths(self._project_root)
        conditions = tuple(condition.name for condition in self._conditions)
        if not conditions:
            raise RuntimeError("No processed condition workbooks were found.")
        frozen = (
            self._state.frozen_excluded_subjects
            if self._state is not None
            else excluded_participants(load_qc_decisions(root))
        )
        output_options = (
            ReportOutputOptions(
                markdown=False,
                docx=False,
                workbook=True,
                audit_json=True,
                spectra=False,
                scalp_maps=False,
                individual_figures=False,
                qc_figures=True,
            )
            if mode == "qc"
            else ReportOutputOptions()
        )
        return PublicationReportRequest(
            project_root=root,
            excel_root=excel_root,
            output_root=output_root,
            selected_conditions=conditions,
            condition_labels={condition: condition for condition in conditions},
            report_label="Semantic categories",
            target_response_label="semantic categorization response",
            rois=self._settings_report_rois(),
            base_rate_roi=default_base_rate_roi(),
            manual_excluded_subjects=frozenset(),
            qc_excluded_subjects=frozenset() if mode == "qc" else frozenset(frozen),
            output_options=output_options,
        )

    def _start_qc_run(self) -> None:
        self._start_report_worker(mode="qc")

    def _start_report_run(self) -> None:
        if self._state is not None:
            frozen = ", ".join(self._state.frozen_excluded_subjects) or "none"
            self._append_log(f"Using frozen participant exclusions: {frozen}")
        self._start_report_worker(mode="report")

    def _start_report_worker(self, *, mode: str) -> None:
        if self._thread is not None:
            return
        try:
            request = self._build_report_request(mode=mode)
        except Exception as exc:
            show_error(self, "Publication Workflow", str(exc))
            return
        self._run_mode = mode
        self._last_generated_file_count = 0
        self.progress.setValue(0)
        self._append_log("Starting QC run..." if mode == "qc" else "Starting publication report run...")
        self.status_banner.set_text("Running...")
        self.status_banner.set_variant("info")
        if self._state is not None and self._project_root is not None:
            step = STEP_QC_REVIEW if mode == "qc" else STEP_PUBLICATION_REPORT
            self._state = update_step(self._state, step, status="running", message="Worker is running.")
            save_workflow_state(self._project_root, self._state)
            self._populate_steps(self._state)

        self._thread = QThread()
        self._worker = PublicationReportWorker(request)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.progress.connect(self.progress.setValue)
        self._worker.message.connect(self._append_log)
        self._worker.error.connect(self._on_worker_error)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.finished.connect(self._thread.quit)
        self._thread.finished.connect(self._cleanup_worker)
        self._set_busy_state(True)
        self._thread.start()

    def _cancel_run(self) -> None:
        if self._worker is not None:
            self._worker.cancel()
            self._append_log("Cancel requested.")

    def _on_worker_error(self, message: str) -> None:
        self._append_log(message)
        self.status_banner.set_text(message)
        self.status_banner.set_variant("error")
        show_error(self, "Publication Workflow error", message)
        if self._thread is not None:
            self._thread.quit()
        else:
            self._set_busy_state(False)

    def _on_worker_finished(self, result: object) -> None:
        if result is None:
            self.status_banner.set_text("Cancelled.")
            self.status_banner.set_variant("warning")
            return
        generated = list(getattr(result, "generated_files", []) or [])
        self._last_generated_file_count = len(generated)
        for path in generated:
            self._append_log(f"Generated: {path}")
        for warning in list(getattr(result, "warnings", []) or []):
            self._append_log(f"Warning: {warning}")
        self.progress.setValue(100)
        if self._run_mode == "qc":
            self.status_banner.set_text("QC review complete. Review and freeze decisions.")
            self.status_banner.set_variant("success")
        else:
            self.status_banner.set_text("Publication report complete.")
            self.status_banner.set_variant("success")

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_busy_state(False)
        self.refresh_workflow()

    def _set_busy_state(self, busy: bool) -> None:
        self._set_host_navigation_locked(busy)
        self.cancel_btn.setEnabled(busy)
        for button in (
            self.refresh_btn,
            self.open_output_btn,
            self.run_qc_btn,
            self.save_decisions_btn,
            self.open_qc_figures_btn,
            self.generate_report_btn,
            self.open_report_tool_btn,
            self.open_scalp_maps_btn,
            self.open_loreta_btn,
        ):
            button.setEnabled(not busy)
        if not busy:
            self._set_ready_controls(bool(self._conditions))

    def _save_decisions(self) -> None:
        if self._project_root is None:
            show_error(self, "Publication Workflow", "Open a project before freezing decisions.")
            return
        decisions: list[QCDecision] = []
        for row_index in range(self.qc_table.rowCount()):
            participant_item = self.qc_table.item(row_index, 1)
            payload = participant_item.data(Qt.UserRole) if participant_item is not None else {}
            if not isinstance(payload, dict):
                continue
            combo = self.qc_table.cellWidget(row_index, 0)
            decision = combo.currentText() if isinstance(combo, QComboBox) else "watch"
            reason_item = self.qc_table.item(row_index, 7)
            reason = reason_item.text().strip() if reason_item is not None else ""
            if decision == "exclude" and not reason:
                show_error(
                    self,
                    "Publication Workflow",
                    "Add a reason for every excluded participant before freezing decisions.",
                )
                return
            decisions.append(
                QCDecision(
                    participant_id=_cell_text(payload.get("participant_id")).upper(),
                    condition=_cell_text(payload.get("condition")),
                    roi=_cell_text(payload.get("roi")),
                    metric_source=_cell_text(payload.get("metric_source")),
                    metric_label=_cell_text(payload.get("metric_label")),
                    value=_optional_float(payload.get("value")),
                    lower_iqr_fence=_optional_float(payload.get("lower_iqr_fence")),
                    upper_iqr_fence=_optional_float(payload.get("upper_iqr_fence")),
                    outlier_direction=_cell_text(payload.get("outlier_direction")),
                    decision=decision,
                    reason=reason,
                )
            )
        path = save_qc_decisions(self._project_root, tuple(decisions))
        exclusions = excluded_participants(tuple(decisions))
        state = load_workflow_state(self._project_root)
        state = with_frozen_exclusions(state, exclusions)
        state = update_step(
            state,
            STEP_OUTLIER_DECISIONS,
            status="complete",
            message=f"{len(decisions)} decision row(s), {len(exclusions)} excluded participant(s).",
            artifacts=(relative_artifact(self._project_root, path),),
        )
        state = update_step(
            state,
            STEP_FREEZE_ANALYSIS_SET,
            status="complete",
            message=f"Frozen exclusions: {', '.join(exclusions) if exclusions else 'none'}.",
            artifacts=(relative_artifact(self._project_root, path),),
        )
        save_workflow_state(self._project_root, state)
        self._state = state
        self._populate_steps(state)
        self.report_summary_label.setText(
            f"Frozen participant exclusions: {', '.join(exclusions) if exclusions else 'none'}."
        )
        show_info(self, "Publication Workflow", "QC decisions were frozen for the next report run.")

    def _append_log(self, message: str) -> None:
        self.log_box.appendPlainText(message)

    def _embedded_host(self) -> QWidget | None:
        parent = self.parent()
        while parent is not None:
            if hasattr(parent, "sidebar") and callable(getattr(parent, "menuBar", None)):
                return parent
            parent = parent.parent()
        return None

    def _set_host_navigation_locked(self, locked: bool) -> None:
        if locked == self._host_navigation_locked:
            return
        host = self._embedded_host()
        if host is None:
            self._host_navigation_locked = False
            return
        from Main_App.gui.shell_status import _set_processing_navigation_locked

        if locked:
            if getattr(host, "_processing_navigation_states", None):
                self._host_navigation_locked = False
                return
            _set_processing_navigation_locked(host, True)
            self._host_navigation_locked = True
            return
        if self._host_navigation_locked:
            _set_processing_navigation_locked(host, False)
        self._host_navigation_locked = False

    def _open_host_tool(self, method_name: str) -> None:
        host = self._embedded_host()
        method = getattr(host, method_name, None)
        if callable(method):
            method()

    def _open_output_folder(self) -> None:
        if self._project_root is None:
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(workflow_output_root(self._project_root))))

    def _open_qc_figures_folder(self) -> None:
        if self._project_root is None:
            return
        folder = workflow_output_root(self._project_root) / "figures" / "qc"
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _existing_report_artifacts(self, output_root: Path) -> list[Path]:
        return [
            path
            for path in (
                output_root / REPORT_MARKDOWN_NAME,
                output_root / REPORT_DOCX_NAME,
                output_root / REPORT_WORKBOOK_NAME,
            )
            if path.exists()
        ]


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if pd.isna(value):
        return ""
    return str(value)


def _number_text(value: object) -> str:
    numeric = _optional_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.6g}"


def _optional_float(value: object) -> float | None:
    try:
        if value is None or str(value).strip() == "":
            return None
        if pd.isna(value):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _decision_key(
    participant_id: object,
    condition: object,
    roi: object,
    metric_source: object,
) -> tuple[str, str, str, str]:
    return (
        _cell_text(participant_id).strip().upper(),
        _cell_text(condition).strip(),
        _cell_text(roi).strip(),
        _cell_text(metric_source).strip(),
    )


__all__ = ("PublicationWorkflowWindow",)
