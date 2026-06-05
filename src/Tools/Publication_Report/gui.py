"""Embedded PySide6 page for publication report generation."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QSizePolicy,
    QStyle,
    QVBoxLayout,
    QWidget,
)

import config
from Main_App import SettingsManager
from Main_App.gui.components import (
    ActionRow,
    PathPickerRow,
    SectionCard,
    StatusBanner,
    SurfaceSize,
    configure_window_surface,
    confirm,
    make_action_button,
    make_form_layout,
    show_error,
)
from Tools.Publication_Report.discovery import discover_conditions, resolve_project_paths
from Tools.Publication_Report.models import (
    PUBLICATION_REPORT_OUTPUT_FOLDER,
    PublicationReportRequest,
    ReportOutputOptions,
    ReportRoi,
    default_base_rate_roi,
    default_report_rois,
    report_rois_from_settings_pairs,
)
from Tools.Publication_Report.worker import PublicationReportWorker

logger = logging.getLogger(__name__)


class PublicationReportWindow(QWidget):
    """Embedded tool page for manually generating publication report bundles."""

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
        configure_window_surface(
            self,
            title="Publication Report",
            size=surface_size,
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Path | None = None
        self._thread: QThread | None = None
        self._worker: PublicationReportWorker | None = None
        self._busy = False
        self._host_navigation_locked = False
        self._last_generated_file_count = 0
        self._settings_fallback: SettingsManager | None = None
        self._conditions = []
        self._default_rois = self._settings_report_rois()
        self._default_base_rate_roi = default_base_rate_roi()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_input_group(), 0)

        body = QGridLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setHorizontalSpacing(8)
        body.setVerticalSpacing(8)
        body.setColumnStretch(0, 1)
        body.setColumnStretch(1, 1)
        body.setRowStretch(0, 0)
        body.setRowStretch(1, 0)
        body.setRowStretch(2, 1)
        layout.addLayout(body, 1)

        body.addWidget(self._build_conditions_group(), 0, 0)
        body.addWidget(self._build_labels_group(), 0, 1)
        body.addWidget(self._build_roi_group(), 1, 0)
        body.addWidget(self._build_output_group(), 1, 1)
        body.addWidget(self._build_run_group(), 2, 0, 1, 2)

        self._apply_button_icons()
        self._set_default_paths()
        self._refresh_conditions()
        self._update_run_state()

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
        proj = getattr(self.parent(), "currentProject", None)
        if proj and hasattr(proj, "project_root"):
            root = Path(proj.project_root)
            if root.exists():
                return root
        return None

    def _build_input_group(self) -> SectionCard:
        group = SectionCard("Input data", object_name="publication_report_input")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form = make_form_layout()

        self.input_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select Excel root folder",
        )
        self.input_root_row.setObjectName("publication_report_input_root_row")
        self.input_root_edit = self.input_root_row.line_edit
        self.input_root_btn = self.input_root_row.button
        self.input_root_btn.clicked.connect(self._browse_input_root)

        self.output_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select publication report output folder",
        )
        self.output_root_row.setObjectName("publication_report_output_root_row")
        self.output_root_edit = self.output_root_row.line_edit
        self.output_root_btn = self.output_root_row.button
        self.output_root_btn.clicked.connect(self._browse_output_root)
        self.open_output_btn = make_action_button("Open", compact=True, parent=group)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        self.output_root_row.row_layout.insertWidget(1, self.open_output_btn)

        self.refresh_btn = make_action_button("Refresh conditions", compact=True, parent=group)
        self.refresh_btn.clicked.connect(self._refresh_conditions)

        form.addRow("Excel root folder:", self.input_root_row)
        form.addRow("Output folder:", self.output_root_row)
        form.addRow("", self.refresh_btn)
        group.content_layout.addLayout(form)
        return group

    def _build_conditions_group(self) -> SectionCard:
        group = SectionCard("Conditions", object_name="publication_report_conditions")
        group.set_compact(310)

        self.conditions_list = QListWidget(group)
        self.conditions_list.setMinimumHeight(140)
        self.conditions_list.setMaximumHeight(210)
        self.conditions_list.itemChanged.connect(lambda _item: self._update_run_state())
        self.conditions_summary = QLabel("Selected conditions: 0 | Total files: 0", group)
        self.conditions_summary.setProperty("caption", True)

        buttons = ActionRow(group, alignment=Qt.AlignLeft, spacing=6)
        self.select_all_btn = make_action_button("Select all", compact=True, parent=group)
        self.select_none_btn = make_action_button("Select none", compact=True, parent=group)
        self.select_all_btn.clicked.connect(lambda: self._set_all_conditions(True))
        self.select_none_btn.clicked.connect(lambda: self._set_all_conditions(False))
        buttons.add_button(self.select_all_btn)
        buttons.add_button(self.select_none_btn)

        group.content_layout.addWidget(self.conditions_list)
        group.content_layout.addWidget(buttons)
        group.content_layout.addWidget(self.conditions_summary)
        return group

    def _build_labels_group(self) -> SectionCard:
        group = SectionCard("Report labels", object_name="publication_report_labels")
        group.set_compact(310)
        form = make_form_layout()

        self.report_label_edit = QLineEdit(group)
        self.report_label_edit.setText("Semantic categories")
        self.report_label_edit.textChanged.connect(lambda _text: self._update_run_state())

        self.target_response_edit = QLineEdit(group)
        self.target_response_edit.setText("semantic categorization response")
        self.target_response_edit.textChanged.connect(lambda _text: self._update_run_state())

        self.base_freq_spin = QDoubleSpinBox(group)
        self.base_freq_spin.setDecimals(3)
        self.base_freq_spin.setRange(0.001, 1000.0)
        self.base_freq_spin.setSingleStep(0.1)
        self.base_freq_spin.setSuffix(" Hz")
        self.base_freq_spin.setValue(self._analysis_base_frequency_hz())

        self.bca_limit_spin = QDoubleSpinBox(group)
        self.bca_limit_spin.setDecimals(3)
        self.bca_limit_spin.setRange(0.001, 1000.0)
        self.bca_limit_spin.setSingleStep(1.0)
        self.bca_limit_spin.setSuffix(" Hz")
        self.bca_limit_spin.setValue(self._analysis_bca_upper_limit_hz())

        form.addRow("Report label:", self.report_label_edit)
        form.addRow("Target response:", self.target_response_edit)
        form.addRow("Base rate:", self.base_freq_spin)
        form.addRow("BCA upper limit:", self.bca_limit_spin)
        group.content_layout.addLayout(form)
        return group

    def _build_roi_group(self) -> SectionCard:
        group = SectionCard("ROIs", object_name="publication_report_rois")
        group.set_compact(330)
        form = make_form_layout()
        self.roi_checks: dict[str, QCheckBox] = {}
        self.roi_edits: dict[str, QLineEdit] = {}

        for roi in self._default_rois:
            check = QCheckBox(roi.name, group)
            check.setChecked(roi.selected)
            check.toggled.connect(lambda _checked: self._update_run_state())
            edit = QLineEdit(", ".join(roi.electrodes), group)
            edit.textChanged.connect(lambda _text: self._update_run_state())
            self.roi_checks[roi.name] = check
            self.roi_edits[roi.name] = edit
            row = self._check_edit_row(group, check, edit)
            form.addRow(f"{roi.role}:", row)

        self.base_rate_check = QCheckBox(self._default_base_rate_roi.name, group)
        self.base_rate_check.setChecked(True)
        self.base_rate_check.toggled.connect(lambda _checked: self._update_run_state())
        self.base_rate_edit = QLineEdit(", ".join(self._default_base_rate_roi.electrodes), group)
        self.base_rate_edit.textChanged.connect(lambda _text: self._update_run_state())
        form.addRow("base-rate:", self._check_edit_row(group, self.base_rate_check, self.base_rate_edit))
        group.content_layout.addLayout(form)
        return group

    def _check_edit_row(
        self,
        parent: QWidget,
        check: QCheckBox,
        edit: QLineEdit,
    ) -> QWidget:
        row = QWidget(parent)
        layout = QHBoxLayout(row)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)
        layout.addWidget(check, 0)
        layout.addWidget(edit, 1)
        return row

    def _build_output_group(self) -> SectionCard:
        group = SectionCard("Outputs", object_name="publication_report_outputs")
        group.set_compact(330)

        self.markdown_check = QCheckBox("Markdown", group)
        self.markdown_check.setChecked(True)
        self.docx_check = QCheckBox("Word .docx", group)
        self.docx_check.setChecked(True)
        self.workbook_check = QCheckBox("Excel source workbook", group)
        self.workbook_check.setChecked(True)

        self.spectra_check = QCheckBox("ROI spectra figures", group)
        self.spectra_check.setChecked(True)
        self.scalp_maps_check = QCheckBox("Scalp-map figures", group)
        self.scalp_maps_check.setChecked(True)
        self.individual_figures_check = QCheckBox("Individual detectability figures", group)
        self.individual_figures_check.setChecked(True)

        for check in (
            self.markdown_check,
            self.docx_check,
            self.workbook_check,
            self.spectra_check,
            self.scalp_maps_check,
            self.individual_figures_check,
        ):
            check.toggled.connect(lambda _checked: self._update_run_state())
            group.content_layout.addWidget(check)
        return group

    def _build_run_group(self) -> SectionCard:
        group = SectionCard("Run", object_name="publication_report_run")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.progress = QProgressBar(group)
        self.progress.setValue(0)
        self.status_label = StatusBanner("Ready.", group)
        self.status_label.setObjectName("publication_report_status")
        self.status_label.hide()

        self.run_btn = make_action_button("Generate Report", variant="primary", parent=group)
        self.cancel_btn = make_action_button("Cancel", compact=True, parent=group)
        self.cancel_btn.setEnabled(False)
        self.run_btn.clicked.connect(self._start_run)
        self.cancel_btn.clicked.connect(self._cancel_run)

        row = ActionRow(group, alignment=Qt.AlignLeft)
        row.add_button(self.run_btn)
        row.add_button(self.cancel_btn)
        row.row_layout.addWidget(self.progress, 1)

        self.log_box = QPlainTextEdit(group)
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(130)
        self.log_box.setProperty("logSurface", True)

        group.content_layout.addWidget(row)
        group.content_layout.addWidget(self.status_label)
        group.content_layout.addWidget(self.log_box, 1)
        return group

    def _apply_button_icons(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        style = app.style()
        self.input_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.output_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.run_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.cancel_btn.setIcon(style.standardIcon(QStyle.SP_BrowserStop))

    def _set_default_paths(self) -> None:
        if not self._project_root:
            return
        try:
            _root, excel_root, output_root = resolve_project_paths(self._project_root)
        except Exception:
            excel_root = self._project_root / "1 - Excel Data Files"
            output_root = self._project_root / PUBLICATION_REPORT_OUTPUT_FOLDER
        self.input_root_edit.setText(str(excel_root))
        self.output_root_edit.setText(str(output_root))

    def _browse_input_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Excel root folder",
            str(self._default_browse_dir()),
        )
        if folder:
            self.input_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._refresh_conditions()

    def _browse_output_root(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self,
            "Select publication report output folder",
            str(self._default_browse_dir()),
        )
        if folder:
            self.output_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._update_run_state()

    def _default_browse_dir(self) -> Path:
        if self._last_dir and self._last_dir.exists():
            return self._last_dir
        input_text = self.input_root_edit.text().strip()
        if input_text and Path(input_text).exists():
            return Path(input_text)
        return self._project_root or Path.home()

    def _refresh_conditions(self) -> None:
        root_text = self.input_root_edit.text().strip()
        root = Path(root_text) if root_text else Path()
        self._conditions = discover_conditions(root) if root_text else []
        self.conditions_list.blockSignals(True)
        try:
            self.conditions_list.clear()
            for condition in self._conditions:
                item = QListWidgetItem(f"{condition.name} ({len(condition.files)})")
                item.setData(Qt.UserRole, condition.name)
                item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
                item.setCheckState(Qt.Checked)
                self.conditions_list.addItem(item)
        finally:
            self.conditions_list.blockSignals(False)
        self._update_condition_summary()
        self._update_run_state()

    def _set_all_conditions(self, checked: bool) -> None:
        self.conditions_list.blockSignals(True)
        try:
            for index in range(self.conditions_list.count()):
                item = self.conditions_list.item(index)
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        finally:
            self.conditions_list.blockSignals(False)
        self._update_condition_summary()
        self._update_run_state()

    def _selected_conditions(self) -> tuple[str, ...]:
        selected: list[str] = []
        for index in range(self.conditions_list.count()):
            item = self.conditions_list.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(str(item.data(Qt.UserRole)))
        return tuple(selected)

    def _update_condition_summary(self) -> None:
        selected = set(self._selected_conditions())
        total_files = sum(len(condition.files) for condition in self._conditions if condition.name in selected)
        self.conditions_summary.setText(
            f"Selected conditions: {len(selected)} | Total files: {total_files}"
        )

    def _settings_manager(self):
        host = self._embedded_host()
        manager = getattr(host, "settings", None)
        if manager is not None and hasattr(manager, "get"):
            return manager
        parent = self.parent()
        manager = getattr(parent, "settings", None)
        if manager is not None and hasattr(manager, "get"):
            return manager
        if self._settings_fallback is None:
            self._settings_fallback = SettingsManager()
        return self._settings_fallback

    def _analysis_setting_float(self, key: str, fallback: float) -> float:
        manager = self._settings_manager()
        try:
            return float(manager.get("analysis", key, str(fallback)))
        except (TypeError, ValueError):
            return float(fallback)

    def _analysis_base_frequency_hz(self) -> float:
        return self._analysis_setting_float("base_freq", 6.0)

    def _analysis_bca_upper_limit_hz(self) -> float:
        return self._analysis_setting_float(
            "bca_upper_limit",
            float(config.DEFAULT_BCA_UPPER_LIMIT),
        )

    def _settings_report_rois(self) -> tuple[ReportRoi, ...]:
        manager = self._settings_manager()
        try:
            get_roi_pairs = getattr(manager, "get_roi_pairs", None)
            pairs = get_roi_pairs() if callable(get_roi_pairs) else []
        except Exception:
            logger.exception("publication_report_roi_settings_load_failed")
            pairs = []
        return report_rois_from_settings_pairs(pairs or []) or default_report_rois()

    def _parse_electrodes(self, text: str) -> tuple[str, ...]:
        return tuple(part.strip() for part in text.split(",") if part.strip())

    def _selected_rois(self) -> tuple[ReportRoi, ...]:
        rois: list[ReportRoi] = []
        defaults = {roi.name: roi for roi in self._default_rois}
        for name, check in self.roi_checks.items():
            default = defaults[name]
            electrodes = self._parse_electrodes(self.roi_edits[name].text())
            rois.append(
                ReportRoi(
                    name=name,
                    electrodes=electrodes,
                    role=default.role,
                    selected=check.isChecked(),
                )
            )
        return tuple(rois)

    def _selected_base_rate_roi(self) -> ReportRoi | None:
        return ReportRoi(
            name=self._default_base_rate_roi.name,
            electrodes=self._parse_electrodes(self.base_rate_edit.text()),
            role=self._default_base_rate_roi.role,
            selected=self.base_rate_check.isChecked(),
        )

    def _stats_exclusion_sets(self) -> tuple[frozenset[str], frozenset[str]]:
        stats_page = getattr(self._embedded_host(), "_stats_page", None)
        manual = {
            str(pid).strip().upper()
            for pid in getattr(stats_page, "manual_excluded_pids", set()) or set()
            if str(pid).strip()
        }
        qc_excluded: set[str] = set()
        reports = getattr(stats_page, "_pipeline_run_reports", {}) or {}
        for report in reports.values():
            for violation in getattr(report, "required_exclusions", []) or []:
                participant_id = getattr(violation, "participant_id", "")
                if str(participant_id).strip():
                    qc_excluded.add(str(participant_id).strip().upper())
        return frozenset(manual), frozenset(qc_excluded)

    def _collect_request(self) -> PublicationReportRequest:
        manual_excluded, qc_excluded = self._stats_exclusion_sets()
        return PublicationReportRequest(
            project_root=self._project_root or Path.cwd(),
            excel_root=Path(self.input_root_edit.text().strip()),
            output_root=Path(self.output_root_edit.text().strip()),
            selected_conditions=self._selected_conditions(),
            condition_labels={condition: condition for condition in self._selected_conditions()},
            report_label=self.report_label_edit.text().strip() or "Publication report",
            target_response_label=(
                self.target_response_edit.text().strip() or "condition response"
            ),
            rois=self._selected_rois(),
            base_rate_roi=self._selected_base_rate_roi(),
            manual_excluded_subjects=manual_excluded,
            qc_excluded_subjects=qc_excluded,
            base_frequency_hz=float(self.base_freq_spin.value()),
            bca_upper_limit_hz=float(self.bca_limit_spin.value()),
            output_options=ReportOutputOptions(
                markdown=self.markdown_check.isChecked(),
                docx=self.docx_check.isChecked(),
                workbook=self.workbook_check.isChecked(),
                audit_json=True,
                spectra=self.spectra_check.isChecked(),
                scalp_maps=self.scalp_maps_check.isChecked(),
                individual_figures=self.individual_figures_check.isChecked(),
            ),
        )

    def _lockable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.input_root_row,
            self.output_root_row,
            self.refresh_btn,
            self.conditions_list,
            self.select_all_btn,
            self.select_none_btn,
            self.report_label_edit,
            self.target_response_edit,
            self.base_freq_spin,
            self.bca_limit_spin,
            *self.roi_checks.values(),
            *self.roi_edits.values(),
            self.base_rate_check,
            self.base_rate_edit,
            self.markdown_check,
            self.docx_check,
            self.workbook_check,
            self.spectra_check,
            self.scalp_maps_check,
            self.individual_figures_check,
        )

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

    def _set_busy_state(self, busy: bool) -> None:
        self._busy = busy
        self.setProperty("publicationReportBusy", busy)
        self._set_host_navigation_locked(busy)
        for widget in self._lockable_widgets():
            widget.setEnabled(not busy)
        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(busy)
        if not busy:
            self._update_run_state()

    def _update_run_state(self) -> None:
        self._update_condition_summary()
        has_path = bool(self.input_root_edit.text().strip()) and bool(self.output_root_edit.text().strip())
        has_conditions = bool(self._selected_conditions())
        has_label = bool(self.report_label_edit.text().strip()) and bool(
            self.target_response_edit.text().strip()
        )
        has_roi = any(check.isChecked() for check in self.roi_checks.values())
        has_output = (
            self.markdown_check.isChecked()
            or self.docx_check.isChecked()
            or self.workbook_check.isChecked()
        )
        self.run_btn.setEnabled(
            has_path
            and has_conditions
            and has_label
            and has_roi
            and has_output
            and self._thread is None
            and not self._busy
        )

    def _start_run(self) -> None:
        if self._thread is not None:
            return
        if not self._selected_conditions():
            show_error(self, "Publication Report", "Select at least one condition.")
            return
        if not any(check.isChecked() for check in self.roi_checks.values()):
            show_error(self, "Publication Report", "Select at least one report ROI.")
            return
        request = self._collect_request()
        self._last_generated_file_count = 0
        self.log_box.clear()
        self.progress.setValue(0)
        self.status_label.show()
        self.status_label.set_text("Starting...")
        self.status_label.set_variant("info")

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

    def _append_log(self, message: str) -> None:
        self.log_box.appendPlainText(message)
        self.status_label.set_text(message)

    def _on_worker_error(self, message: str) -> None:
        self._append_log(message)
        self.status_label.set_variant("error")
        show_error(self, "Publication Report error", message)
        if self._thread is not None:
            self._thread.quit()
        else:
            self._set_busy_state(False)

    def _on_worker_finished(self, result: object) -> None:
        if result is None:
            self.status_label.set_text("Cancelled.")
            self.status_label.set_variant("warning")
            return
        self.status_label.set_text("Complete.")
        self.status_label.set_variant("success")
        generated = list(getattr(result, "generated_files", []) or [])
        self._last_generated_file_count = len(generated)
        for path in generated:
            self._append_log(f"Generated: {path}")
        warnings = list(getattr(result, "warnings", []) or [])
        for warning in warnings:
            self._append_log(f"Warning: {warning}")
        self.progress.setValue(100)

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_busy_state(False)
        if self._last_generated_file_count > 0:
            self._prompt_open_output_folder()
        self._last_generated_file_count = 0

    def _prompt_open_output_folder(self) -> None:
        if confirm(
            self,
            "Finished",
            "Publication report files have been generated. View output folder?",
        ):
            self._open_output_folder()

    def _open_output_folder(self) -> None:
        path = self.output_root_edit.text().strip()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
