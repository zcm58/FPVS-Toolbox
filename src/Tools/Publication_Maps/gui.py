"""Embedded PySide6 page for BCA scalp maps."""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QThread, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
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
    make_action_button,
    make_form_layout,
    show_error,
)
from Tools.Publication_Maps.excel_inputs import discover_conditions
from Tools.Publication_Maps.models import (
    ColorBounds,
    DEFAULT_BCA_HIGH_COLOR,
    DEFAULT_BCA_LOW_COLOR,
    PublicationMapRequest,
    PublicationMetric,
)
from Tools.Publication_Maps.worker import PublicationMapsWorker

logger = logging.getLogger(__name__)

SCALP_MAPS_OUTPUT_FOLDER = "4 - Scalp Maps"


class PublicationMapsWindow(QWidget):
    """Embedded tool page for Stats-selected BCA scalp maps."""

    def __init__(
        self,
        parent: QWidget | None = None,
        project_root: str | None = None,
        *,
        embedded: bool = True,
    ) -> None:
        super().__init__(parent)
        surface_size = SurfaceSize(width=1100, height=760)
        if not embedded:
            surface_size = SurfaceSize(width=1100, height=760, min_width=980)
        configure_window_surface(
            self,
            title="Scalp Maps",
            size=surface_size,
        )
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self._project_root = self._resolve_project_root(project_root)
        self._last_dir: Optional[Path] = None
        self._thread: QThread | None = None
        self._worker: PublicationMapsWorker | None = None
        self._busy = False
        self._host_navigation_locked = False
        self._settings_fallback: SettingsManager | None = None
        self.bca_low_color = DEFAULT_BCA_LOW_COLOR
        self.bca_high_color = DEFAULT_BCA_HIGH_COLOR
        self._conditions = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(8)

        layout.addWidget(self._build_input_group(), 0)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(8)
        layout.addLayout(body, 1)

        left_column = QVBoxLayout()
        left_column.setContentsMargins(0, 0, 0, 0)
        left_column.setSpacing(8)
        right_column = QVBoxLayout()
        right_column.setContentsMargins(0, 0, 0, 0)
        right_column.setSpacing(8)

        body.addLayout(left_column, 1)
        body.addLayout(right_column, 1)

        left_column.addWidget(self._build_conditions_group(), 1)
        right_column.addWidget(self._build_settings_group(), 0)
        right_column.addWidget(self._build_output_group(), 0)
        right_column.addWidget(self._build_run_group(), 1)

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
        group = SectionCard("Input data", object_name="publication_maps_input")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form = make_form_layout()

        self.input_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select Excel root folder",
        )
        self.input_root_row.setObjectName("publication_maps_input_root_row")
        self.input_root_edit = self.input_root_row.line_edit
        self.input_root_btn = self.input_root_row.button
        self.input_root_btn.clicked.connect(self._browse_input_root)

        self.refresh_btn = make_action_button("Refresh conditions", compact=True, parent=group)
        self.refresh_btn.clicked.connect(self._refresh_conditions)

        form.addRow("Excel root folder:", self.input_root_row)
        form.addRow("", self.refresh_btn)
        group.content_layout.addLayout(form)
        return group

    def _build_conditions_group(self) -> SectionCard:
        group = SectionCard("Conditions", object_name="publication_maps_conditions")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        self.conditions_list = QListWidget(group)
        self.conditions_list.itemChanged.connect(lambda _item: self._update_run_state())
        self.conditions_summary = QLabel("Selected conditions: 0 | Total files: 0")
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

    def _build_settings_group(self) -> SectionCard:
        group = SectionCard("BCA significant harmonics", object_name="publication_maps_settings")
        group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        form = make_form_layout()

        self.base_freq_value = QLabel(group)
        self.base_freq_value.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.bca_limit_value = QLabel(group)
        self.bca_limit_value.setTextInteractionFlags(Qt.TextSelectableByMouse)

        self.color_low_btn = QPushButton(group)
        self.color_low_btn.setFixedSize(20, 20)
        self.color_low_btn.setToolTip("Low BCA color")
        self.color_low_btn.clicked.connect(lambda: self._choose_bca_color("low"))

        self.color_high_btn = QPushButton(group)
        self.color_high_btn.setFixedSize(20, 20)
        self.color_high_btn.setToolTip("High BCA color")
        self.color_high_btn.clicked.connect(lambda: self._choose_bca_color("high"))

        self.fixed_bca_range_check = QCheckBox("Use fixed BCA range", group)
        self.fixed_bca_range_check.setToolTip(
            "When checked, every BCA scalp map uses the same colorbar range."
        )
        self.fixed_bca_range_check.setChecked(True)
        self.fixed_bca_range_check.stateChanged.connect(
            lambda _state: self._toggle_bca_range_controls()
        )

        self.bca_vmin_spin = QDoubleSpinBox(group)
        self.bca_vmin_spin.setDecimals(3)
        self.bca_vmin_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.bca_vmin_spin.setSingleStep(0.1)
        self.bca_vmin_spin.setSuffix(" BCA")
        self.bca_vmin_spin.setValue(0.0)

        self.bca_vmax_spin = QDoubleSpinBox(group)
        self.bca_vmax_spin.setDecimals(3)
        self.bca_vmax_spin.setRange(-1_000_000.0, 1_000_000.0)
        self.bca_vmax_spin.setSingleStep(0.1)
        self.bca_vmax_spin.setSuffix(" BCA")
        self.bca_vmax_spin.setValue(0.4)

        color_row = QWidget(group)
        color_layout = QHBoxLayout(color_row)
        color_layout.setContentsMargins(0, 0, 0, 0)
        color_layout.setSpacing(8)
        color_layout.addWidget(QLabel("Low", color_row))
        color_layout.addWidget(self.color_low_btn)
        color_layout.addSpacing(8)
        color_layout.addWidget(QLabel("High", color_row))
        color_layout.addWidget(self.color_high_btn)
        color_layout.addStretch(1)

        range_row = QWidget(group)
        range_layout = QHBoxLayout(range_row)
        range_layout.setContentsMargins(0, 0, 0, 0)
        range_layout.setSpacing(8)
        range_layout.addWidget(QLabel("Lower", range_row))
        range_layout.addWidget(self.bca_vmin_spin)
        range_layout.addSpacing(8)
        range_layout.addWidget(QLabel("Upper", range_row))
        range_layout.addWidget(self.bca_vmax_spin)
        range_layout.addStretch(1)

        form.addRow("Base frequency:", self.base_freq_value)
        form.addRow("BCA upper limit:", self.bca_limit_value)
        form.addRow("Color scale:", color_row)
        form.addRow("", self.fixed_bca_range_check)
        form.addRow("BCA range:", range_row)
        group.content_layout.addLayout(form)
        self._refresh_analysis_setting_labels()
        self._apply_bca_color_button_styles()
        self._toggle_bca_range_controls()
        return group

    def _build_output_group(self) -> SectionCard:
        group = SectionCard("Output", object_name="publication_maps_output")
        group.set_compact(245)
        form = make_form_layout()

        self.output_root_row = PathPickerRow(
            "Browse...",
            group,
            placeholder="Select output folder",
        )
        self.output_root_row.setObjectName("publication_maps_output_root_row")
        self.output_root_edit = self.output_root_row.line_edit
        self.output_root_btn = self.output_root_row.button
        self.output_root_btn.clicked.connect(self._browse_output_root)
        self.open_output_btn = make_action_button("Open", compact=True, parent=group)
        self.open_output_btn.clicked.connect(self._open_output_folder)
        self.output_root_row.row_layout.insertWidget(1, self.open_output_btn)
        form.addRow("Output folder:", self.output_root_row)
        group.content_layout.addLayout(form)

        self.export_png_check = QCheckBox("PNG", group)
        self.export_png_check.setChecked(True)
        self.export_svg_check = QCheckBox("SVG", group)
        self.export_svg_check.setChecked(True)
        self.paired_figures_check = QCheckBox("Also export paired condition figures", group)
        self.paired_figures_check.setToolTip(
            "When at least two conditions are selected, export side-by-side BCA scalp maps."
        )
        formats = ActionRow(group, alignment=Qt.AlignLeft, spacing=12)
        formats.row_layout.addWidget(self.export_png_check)
        formats.row_layout.addWidget(self.export_svg_check)
        group.content_layout.addWidget(formats)
        group.content_layout.addWidget(self.paired_figures_check)
        return group

    def _build_run_group(self) -> SectionCard:
        group = SectionCard("Run", object_name="publication_maps_run")
        group.set_compact(260)

        self.progress = QProgressBar(group)
        self.progress.setValue(0)
        self.status_label = StatusBanner("Ready.", group)
        self.status_label.setObjectName("publication_maps_status")
        self.run_btn = make_action_button("Run", variant="primary", parent=group)
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
        self.log_box.setMinimumHeight(100)
        self.log_box.setProperty("logSurface", True)

        group.content_layout.addWidget(row)
        group.content_layout.addWidget(self.status_label)
        group.content_layout.addWidget(self.log_box)
        return group

    def _apply_button_icons(self) -> None:
        style = QApplication.instance().style()
        self.input_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.refresh_btn.setIcon(style.standardIcon(QStyle.SP_BrowserReload))
        self.output_root_btn.setIcon(style.standardIcon(QStyle.SP_DirOpenIcon))
        self.open_output_btn.setIcon(style.standardIcon(QStyle.SP_DialogOpenButton))
        self.run_btn.setIcon(style.standardIcon(QStyle.SP_MediaPlay))
        self.cancel_btn.setIcon(style.standardIcon(QStyle.SP_BrowserStop))

    def _set_default_paths(self) -> None:
        excel_root = self._default_excel_root()
        if excel_root:
            self.input_root_edit.setText(str(excel_root))
        output_root = self._default_output_root()
        if output_root:
            self.output_root_edit.setText(str(output_root))

    def _default_excel_root(self) -> Path | None:
        if not self._project_root:
            return None
        proj = getattr(self.parent(), "currentProject", None)
        subfolders = getattr(proj, "subfolders", {}) if proj is not None else {}
        excel = subfolders.get("excel") if isinstance(subfolders, dict) else None
        if excel:
            path = Path(excel)
            return path if path.is_absolute() else self._project_root / path
        candidate = self._project_root / "1 - Excel Data Files"
        return candidate

    def _default_output_root(self) -> Path | None:
        if not self._project_root:
            return None
        proj = getattr(self.parent(), "currentProject", None)
        results_root = getattr(proj, "results_folder", self._project_root)
        results = Path(results_root)
        if not results.is_absolute():
            results = self._project_root / results
        return results / SCALP_MAPS_OUTPUT_FOLDER

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
            "Select output folder",
            str(self._default_browse_dir()),
        )
        if folder:
            self.output_root_edit.setText(folder)
            self._last_dir = Path(folder)
            self._update_run_state()

    def _default_browse_dir(self) -> Path:
        if self._last_dir and self._last_dir.exists():
            return self._last_dir
        excel_root = self._default_excel_root()
        if excel_root and excel_root.exists():
            return excel_root
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
        if hasattr(self, "paired_figures_check"):
            self.paired_figures_check.setEnabled(len(selected) >= 2 and not self._busy)

    def _update_run_state(self) -> None:
        self._refresh_analysis_setting_labels()
        self._update_condition_summary()
        ready = bool(self.input_root_edit.text().strip())
        ready = ready and bool(self.output_root_edit.text().strip())
        ready = ready and bool(self._selected_conditions())
        ready = ready and (self.export_png_check.isChecked() or self.export_svg_check.isChecked())
        self.run_btn.setEnabled(ready and self._thread is None and not self._busy)

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

    def _refresh_analysis_setting_labels(self) -> None:
        if not hasattr(self, "base_freq_value"):
            return
        self.base_freq_value.setText(f"{self._analysis_base_frequency_hz():g} Hz")
        self.bca_limit_value.setText(f"{self._analysis_bca_upper_limit_hz():g} Hz")

    def _apply_bca_color_button_styles(self) -> None:
        self.color_low_btn.setStyleSheet(f"background-color: {self.bca_low_color};")
        self.color_high_btn.setStyleSheet(f"background-color: {self.bca_high_color};")

    def _choose_bca_color(self, which: str) -> None:
        init = self.bca_low_color if which == "low" else self.bca_high_color
        color = QColorDialog.getColor(QColor(init), self)
        if not color.isValid():
            return
        if which == "low":
            self.bca_low_color = color.name()
        else:
            self.bca_high_color = color.name()
        self._apply_bca_color_button_styles()

    def _toggle_bca_range_controls(self) -> None:
        enabled = self.fixed_bca_range_check.isChecked() and not self._busy
        self.bca_vmin_spin.setEnabled(enabled)
        self.bca_vmax_spin.setEnabled(enabled)

    def _fixed_bca_range_is_valid(self) -> bool:
        return float(self.bca_vmax_spin.value()) > float(self.bca_vmin_spin.value())

    def _lockable_widgets(self) -> tuple[QWidget, ...]:
        return (
            self.input_root_row,
            self.refresh_btn,
            self.conditions_list,
            self.select_all_btn,
            self.select_none_btn,
            self.color_low_btn,
            self.color_high_btn,
            self.fixed_bca_range_check,
            self.bca_vmin_spin,
            self.bca_vmax_spin,
            self.output_root_row,
            self.export_png_check,
            self.export_svg_check,
            self.paired_figures_check,
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
        self.setProperty("publicationMapsBusy", busy)
        self._set_host_navigation_locked(busy)
        for widget in self._lockable_widgets():
            widget.setEnabled(not busy)

        self.run_btn.setEnabled(False)
        self.cancel_btn.setEnabled(busy)
        self._toggle_bca_range_controls()

        if not busy:
            self._update_run_state()

    def _collect_request(self) -> PublicationMapRequest:
        self._refresh_analysis_setting_labels()
        use_fixed_range = self.fixed_bca_range_check.isChecked()
        bounds = ColorBounds(
            auto_scale=not use_fixed_range,
            vmin=float(self.bca_vmin_spin.value()) if use_fixed_range else None,
            vmax=float(self.bca_vmax_spin.value()) if use_fixed_range else None,
            low_color=self.bca_low_color,
            high_color=self.bca_high_color,
        )
        return PublicationMapRequest(
            input_root=Path(self.input_root_edit.text().strip()),
            output_root=Path(self.output_root_edit.text().strip()),
            conditions=self._selected_conditions(),
            base_frequency_hz=self._analysis_base_frequency_hz(),
            max_frequency_hz=self._analysis_bca_upper_limit_hz(),
            color_bounds={PublicationMetric.BCA: bounds},
            export_png=self.export_png_check.isChecked(),
            export_svg=self.export_svg_check.isChecked(),
            export_paired_figures=(
                self.paired_figures_check.isChecked()
                and len(self._selected_conditions()) >= 2
            ),
            project_root=self._project_root,
        )

    def _start_run(self) -> None:
        if self._thread is not None:
            return
        if not self._selected_conditions():
            show_error(self, "Scalp Maps", "Select at least one condition.")
            return
        if self.fixed_bca_range_check.isChecked() and not self._fixed_bca_range_is_valid():
            show_error(
                self,
                "Scalp Maps",
                "The upper BCA range limit must be greater than the lower limit.",
            )
            return
        request = self._collect_request()
        self.log_box.clear()
        self.progress.setValue(0)
        self.status_label.set_text("Starting...")
        self.status_label.set_variant("info")

        self._thread = QThread()
        self._worker = PublicationMapsWorker(request)
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
        show_error(self, "Scalp Maps error", message)
        if self._thread is not None:
            self._thread.quit()
        else:
            self._set_busy_state(False)

    def _on_worker_finished(self, result: object) -> None:
        self.status_label.set_text("Complete.")
        self.status_label.set_variant("success")
        diagnostics = getattr(result, "diagnostics", [])
        for diagnostic in diagnostics:
            detail = f" ({diagnostic.detail})" if diagnostic.detail else ""
            prefix = f"[{diagnostic.level}]"
            location = " ".join(
                part for part in (diagnostic.condition, diagnostic.workbook) if part
            )
            self._append_log(f"{prefix} {location} {diagnostic.message}{detail}".strip())
        source_path = getattr(result, "source_workbook_path", None)
        if source_path:
            self._append_log(f"Source workbook: {source_path}")
        for path in getattr(result, "figure_paths", []):
            self._append_log(f"Figure: {path}")
        self.progress.setValue(100)

    def _cleanup_worker(self) -> None:
        if self._worker is not None:
            self._worker.deleteLater()
        if self._thread is not None:
            self._thread.deleteLater()
        self._worker = None
        self._thread = None
        self._set_busy_state(False)

    def _open_output_folder(self) -> None:
        path = self.output_root_edit.text().strip()
        if path:
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
