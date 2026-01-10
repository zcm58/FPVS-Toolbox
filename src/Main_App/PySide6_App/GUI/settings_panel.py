from __future__ import annotations

from typing import Any, Dict

import config

from PySide6.QtCore import Signal, Slot
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QDialog,
    QTabWidget,
    QGroupBox,
    QGridLayout,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
)

from Main_App.Legacy_App.settings_manager import SettingsManager
from .roi_settings_editor import ROISettingsEditor
from ..config.projects_root import changeProjectsRoot
from ..Backend.project import Project
from ..Backend.preprocessing_settings import PREPROCESSING_DEFAULTS, normalize_preprocessing_settings


class SettingsPanel(QWidget):
    """Simple settings editor using PySide6 widgets."""

    settings_saved = Signal()
    settings_canceled = Signal()

    def __init__(self, controller, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self._build_ui()

    def _build_ui(self) -> None:
        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self.out_edit = QLineEdit()
        self.thr_edit = QLineEdit()
        form.addRow(QLabel("Output Folder"), self.out_edit)
        form.addRow(QLabel("Threshold"), self.thr_edit)

        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("OK")
        self.cancel_btn = QPushButton("Cancel")
        btn_row.addWidget(self.ok_btn)
        btn_row.addWidget(self.cancel_btn)
        layout.addLayout(btn_row)

        self.ok_btn.clicked.connect(self._on_ok)
        self.cancel_btn.clicked.connect(self._on_cancel)

    def _on_ok(self) -> None:
        values = {
            "output_folder": self.out_edit.text(),
            "threshold": self.thr_edit.text(),
        }
        if hasattr(self.controller, "save_settings"):
            self.controller.save_settings(values)
        self.settings_saved.emit()

    def _on_cancel(self) -> None:
        self.settings_canceled.emit()


class SettingsDialog(QDialog):
    """Dialog for editing application settings via :class:`SettingsManager`."""

    def __init__(
        self,
        manager: SettingsManager,
        parent: QWidget | None = None,
        project: Project | None = None,
    ) -> None:
        super().__init__(parent)
        self.manager = manager
        self.project = project
        self._project_cache: Dict[str, Any] | None = None
        self._loreta_tab_index: int = -1
        self._loreta_warning_shown: bool = False
        # Stub attributes for pruned settings to avoid AttributeError if referenced
        self.data_edit = None
        self.out_edit = None
        self.main_size_edit = None
        self.stats_size_edit = None
        self.resize_size_edit = None
        self.adv_size_edit = None
        self.cond_edit = None
        self.id_edit = None
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self._init_general_tab(self.tabs)
        preproc_tab = self._init_preproc_tab(self.tabs)
        self._preproc_tab_index = self.tabs.indexOf(preproc_tab)
        self._init_stats_tab(self.tabs)
        self._init_oddball_tab(self.tabs)
        self.loreta_tab = self._init_loreta_tab()
        self._loreta_tab_index = self.tabs.addTab(self.loreta_tab, "LORETA")
        self._last_tab_index = self.tabs.currentIndex()
        self._tab_change_guard = False
        self.tabs.currentChanged.connect(self._on_tab_changed)

        self.btn_changeRoot = QPushButton("Change Projects Root…", self)
        self.btn_changeRoot.clicked.connect(lambda: changeProjectsRoot(self))
        layout.addWidget(self.btn_changeRoot)

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(btn_box)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)

    # ------------------------------------------------------------------
    def _init_general_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        stim_default = (
            self._project_preprocessing().get("stim_channel", config.DEFAULT_STIM_CHANNEL)
            if self.project
            else self.manager.get("stim", "channel", config.DEFAULT_STIM_CHANNEL)
        )
        self.stim_edit = QLineEdit(stim_default)
        form.addRow(QLabel("Stim Channel"), self.stim_edit)

        debug_default = self.manager.get("debug", "enabled", "False").lower() == "true"
        self.debug_check = QCheckBox("Enable Debug")
        self.debug_check.setChecked(debug_default)
        form.addRow(QLabel("Debug Mode"), self.debug_check)

        tabs.addTab(tab, "General")

    # ------------------------------------------------------------------
    def _init_preproc_tab(self, tabs: QTabWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.group_preproc = QGroupBox("Preprocessing Parameters", tab)
        grid = QGridLayout(self.group_preproc)
        params = [
            "Low Pass (Hz):",
            "High Pass (Hz):",
            "Downsample (Hz):",
            "Epoch Start (s):",
            "Rejection Z-Thresh:",
            "Epoch End (s):",
            "Ref Chan 1:",
            "Ref Chan 2:",
            "Max Chan Idx Keep:",
            "Max Bad Chans (Flag):",
        ]
        self.preproc_edits: list[QLineEdit] = []
        for i, label_text in enumerate(params):
            row, col = divmod(i, 2)
            lbl = QLabel(label_text, self.group_preproc)
            edit = QLineEdit(self.group_preproc)
            self.preproc_edits.append(edit)
            grid.addWidget(lbl, row, col * 2)
            grid.addWidget(edit, row, col * 2 + 1)

        pre_keys = [
            ("preprocessing", "low_pass", str(PREPROCESSING_DEFAULTS["low_pass"]), "low_pass"),
            ("preprocessing", "high_pass", str(PREPROCESSING_DEFAULTS["high_pass"]), "high_pass"),
            ("preprocessing", "downsample", str(PREPROCESSING_DEFAULTS["downsample"]), "downsample"),
            ("preprocessing", "epoch_start", str(PREPROCESSING_DEFAULTS["epoch_start_s"]), "epoch_start_s"),
            ("preprocessing", "reject_thresh", str(PREPROCESSING_DEFAULTS["rejection_z"]), "rejection_z"),
            ("preprocessing", "epoch_end", str(PREPROCESSING_DEFAULTS["epoch_end_s"]), "epoch_end_s"),
            ("preprocessing", "ref_chan1", str(PREPROCESSING_DEFAULTS["ref_chan1"]), "ref_chan1"),
            ("preprocessing", "ref_chan2", str(PREPROCESSING_DEFAULTS["ref_chan2"]), "ref_chan2"),
            ("preprocessing", "max_idx_keep", str(PREPROCESSING_DEFAULTS["max_chan_idx_keep"]), "max_chan_idx_keep"),
            ("preprocessing", "max_bad_chans", str(PREPROCESSING_DEFAULTS["max_bad_chans"]), "max_bad_chans"),
        ]
        project_pp = self._project_preprocessing() if self.project else None
        for edit, (sec, opt, fallback, canonical) in zip(self.preproc_edits, pre_keys):
            if project_pp is not None:
                value = project_pp.get(canonical)
                edit.setText("" if value is None else str(value))
            else:
                edit.setText(self.manager.get(sec, opt, fallback))

        self.save_fif_check = QCheckBox("Save Preprocessed .fif", self.group_preproc)
        if project_pp is not None:
            self.save_fif_check.setChecked(bool(project_pp.get("save_preprocessed_fif", False)))
        else:
            self.save_fif_check.setChecked(
                self.manager.get("paths", "save_fif", "False").lower() == "true"
            )
        grid.addWidget(self.save_fif_check, 5, 0, 1, 4)

        layout.addWidget(self.group_preproc)
        layout.addStretch(1)
        tabs.addTab(tab, "Preprocessing")
        canonical_keys = [
            "low_pass",
            "high_pass",
            "downsample",
            "epoch_start_s",
            "rejection_z",
            "epoch_end_s",
            "ref_chan1",
            "ref_chan2",
            "max_chan_idx_keep",
            "max_bad_chans",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            edit.editingFinished.connect(
                lambda canon=canonical, field=edit: self._on_preproc_edit_finished(canon, field)
            )

        return tab

    # ------------------------------------------------------------------
    def _init_stats_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.base_freq_edit = QLineEdit(self.manager.get("analysis", "base_freq", "6.0"))
        form.addRow(QLabel("FPVS Base Frequency (Hz)"), self.base_freq_edit)

        self.bca_limit_edit = QLineEdit(self.manager.get("analysis", "bca_upper_limit", "16.8"))
        form.addRow(QLabel("BCA Harmonic Upper Limit"), self.bca_limit_edit)

        self.alpha_edit = QLineEdit(self.manager.get("analysis", "alpha", "0.05"))
        form.addRow(QLabel("Alpha value for ANOVA"), self.alpha_edit)

        self.harm_metric_combo = QComboBox()
        self.harm_metric_combo.addItems(["Z Score"])
        current_metric = self.manager.get("analysis", "harmonic_metric", "Z Score")
        idx = self.harm_metric_combo.findText(current_metric)
        if idx >= 0:
            self.harm_metric_combo.setCurrentIndex(idx)
        form.addRow(QLabel("Harmonic Detection Metric"), self.harm_metric_combo)

        self.harm_threshold_edit = QLineEdit(self.manager.get("analysis", "harmonic_threshold", "1.64"))
        form.addRow(QLabel("Harmonic Threshold"), self.harm_threshold_edit)

        self.roi_editor = ROISettingsEditor(self, self.manager.get_roi_pairs())
        form.addRow(QLabel("Regions of Interest"), self.roi_editor)

        add_btn = QPushButton("+ Add ROI")
        add_btn.clicked.connect(lambda: self.roi_editor.add_entry())
        form.addRow(add_btn)

        tabs.addTab(tab, "Stats")

    # ------------------------------------------------------------------
    def _init_oddball_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.oddball_freq_edit = QLineEdit(self.manager.get("analysis", "oddball_freq", "1.2"))
        form.addRow(QLabel("Oddball Frequency (Hz)"), self.oddball_freq_edit)

        self.harmonics_edit = QLineEdit(
            self.manager.get("loreta", "oddball_harmonics", "1.2,2.4,3.6,4.8,7.2,8.4,9.6,10.8")
        )
        form.addRow(QLabel("Oddball Harmonics"), self.harmonics_edit)

        tabs.addTab(tab, "Oddball")

    # ------------------------------------------------------------------
    def _init_loreta_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)

        self.mri_edit = QLineEdit(self.manager.get("loreta", "mri_path", ""))
        mri_row = self._with_browse(self.mri_edit)
        form.addRow(QLabel("MRI Directory"), mri_row)

        self.low_freq_edit = QLineEdit(self.manager.get("loreta", "loreta_low_freq", "1.1"))
        form.addRow(QLabel("Low Freq (Hz)"), self.low_freq_edit)

        self.high_freq_edit = QLineEdit(self.manager.get("loreta", "loreta_high_freq", "1.3"))
        form.addRow(QLabel("High Freq (Hz)"), self.high_freq_edit)

        self.snr_edit = QLineEdit(self.manager.get("loreta", "loreta_snr", "3.0"))
        form.addRow(QLabel("SNR"), self.snr_edit)

        self.thr_edit = QLineEdit(self.manager.get("loreta", "loreta_threshold", "0.3"))
        form.addRow(QLabel("Threshold"), self.thr_edit)

        self.t_start_edit = QLineEdit(self.manager.get("loreta", "time_window_start_ms", "-1000"))
        self.t_end_edit = QLineEdit(self.manager.get("loreta", "time_window_end_ms", "1000"))
        t_row = QWidget()
        t_layout = QHBoxLayout(t_row)
        t_layout.setContentsMargins(0, 0, 0, 0)
        t_layout.addWidget(self.t_start_edit)
        t_layout.addWidget(self.t_end_edit)
        form.addRow(QLabel("Time Window (ms)"), t_row)

        self.display_time_edit = QLineEdit(self.manager.get("visualization", "time_index_ms", "100"))
        form.addRow(QLabel("Display Time (ms)"), self.display_time_edit)

        auto_default = self.manager.get("loreta", "auto_oddball_localization", "False").lower() == "true"
        self.auto_loc_check = QCheckBox("Auto Oddball Localization")
        self.auto_loc_check.setChecked(auto_default)
        form.addRow(self.auto_loc_check)

        return tab

    @Slot(int)
    def _on_tab_changed(self, index: int) -> None:
        """
        Show a one-time warning when the LORETA tab is opened.
        The user must acknowledge the dialog before interacting with that tab.
        """
        if getattr(self, "_tab_change_guard", False):
            return

        previous = getattr(self, "_last_tab_index", 0)
        if (
            previous == getattr(self, "_preproc_tab_index", -1)
            and index != getattr(self, "_preproc_tab_index", -1)
        ):
            if not self._validate_preproc_fields():
                self._tab_change_guard = True
                self.tabs.setCurrentIndex(getattr(self, "_preproc_tab_index", 0))
                self._tab_change_guard = False
                self._last_tab_index = getattr(self, "_preproc_tab_index", 0)
                return

        if (
            index == getattr(self, "_loreta_tab_index", -1)
            and not getattr(self, "_loreta_warning_shown", False)
        ):
            self._loreta_warning_shown = True
            QMessageBox.warning(
                self,
                "LORETA Source Localization",
                (
                    "Warning: LORETA Source localization is not currently functional.\n\n"
                    "Changing these settings and/or attempting to use the LORETA module "
                    "is not recommended at this time."
                ),
                QMessageBox.Ok,
            )
        self._last_tab_index = index

    # ------------------------------------------------------------------
    def _with_browse(self, edit: QLineEdit) -> QWidget:
        container = QWidget()
        layout = QHBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit)
        btn = QPushButton("Browse")
        layout.addWidget(btn)
        btn.clicked.connect(lambda: self._browse_folder(edit))
        return container

    def _browse_folder(self, edit: QLineEdit) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Select Folder", edit.text() or "")
        if folder:
            edit.setText(folder)

    def _focus_invalid_preproc_field(self, message: str) -> None:
        msg_lower = message.lower()
        target_idx = None
        if "low-pass" in msg_lower or "'low_pass'" in msg_lower:
            target_idx = 0
        elif "high-pass" in msg_lower or "'high_pass'" in msg_lower:
            target_idx = 1
        if target_idx is not None and target_idx < len(self.preproc_edits):
            edit = self.preproc_edits[target_idx]
            edit.setFocus()
            edit.selectAll()

    def _validated_preproc_payload(self) -> Dict[str, Any] | None:
        try:
            return normalize_preprocessing_settings(self._collect_project_preprocessing_inputs())
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Settings", str(exc))
            self._focus_invalid_preproc_field(str(exc))
            return None

    def _validate_preproc_fields(self) -> bool:
        return self._validated_preproc_payload() is not None

    def _on_preproc_edit_finished(self, canonical: str, field: QLineEdit) -> None:  # noqa: ARG002
        if not self._validate_preproc_fields():
            field.setFocus()
            field.selectAll()

    # ------------------------------------------------------------------
    def _save(self) -> None:
        using_project = self.project is not None

        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return

        if not using_project:
            self.manager.set("stim", "channel", validated_preproc.get("stim_channel", self.stim_edit.text()))
        self.manager.set("analysis", "base_freq", self.base_freq_edit.text())
        self.manager.set("analysis", "oddball_freq", self.oddball_freq_edit.text())
        self.manager.set("analysis", "bca_upper_limit", self.bca_limit_edit.text())
        self.manager.set("analysis", "alpha", self.alpha_edit.text())
        self.manager.set("analysis", "harmonic_metric", self.harm_metric_combo.currentText())
        self.manager.set("analysis", "harmonic_threshold", self.harm_threshold_edit.text())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        pre_keys = [
            ("preprocessing", "low_pass", "low_pass"),
            ("preprocessing", "high_pass", "high_pass"),
            ("preprocessing", "downsample", "downsample"),
            ("preprocessing", "epoch_start", "epoch_start_s"),
            ("preprocessing", "reject_thresh", "rejection_z"),
            ("preprocessing", "epoch_end", "epoch_end_s"),
            ("preprocessing", "ref_chan1", "ref_chan1"),
            ("preprocessing", "ref_chan2", "ref_chan2"),
            ("preprocessing", "max_idx_keep", "max_chan_idx_keep"),
            ("preprocessing", "max_bad_chans", "max_bad_chans"),
        ]
        if not using_project:
            for _edit, (sec, opt, canonical) in zip(self.preproc_edits, pre_keys):
                value = validated_preproc.get(canonical, "")
                self.manager.set(sec, opt, str(value))
            self.manager.set("paths", "save_fif", str(bool(validated_preproc.get("save_preprocessed_fif", False))))
        else:
            try:
                normalized = self.project.update_preprocessing(validated_preproc)
                self._project_cache = normalized
                self.project.save()
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid Settings", str(exc))
                return
            except Exception as exc:  # pragma: no cover - disk I/O error path
                QMessageBox.critical(self, "Save Error", str(exc))
                return
        self.manager.set("loreta", "mri_path", self.mri_edit.text())
        self.manager.set("loreta", "loreta_low_freq", self.low_freq_edit.text())
        self.manager.set("loreta", "loreta_high_freq", self.high_freq_edit.text())
        self.manager.set("loreta", "oddball_harmonics", self.harmonics_edit.text())
        self.manager.set("loreta", "loreta_snr", self.snr_edit.text())
        self.manager.set("loreta", "loreta_threshold", self.thr_edit.text())
        self.manager.set("loreta", "time_window_start_ms", self.t_start_edit.text())
        self.manager.set("loreta", "time_window_end_ms", self.t_end_edit.text())
        self.manager.set("visualization", "time_index_ms", self.display_time_edit.text())
        self.manager.set("loreta", "auto_oddball_localization", str(self.auto_loc_check.isChecked()))

        prev_debug = self.manager.debug_enabled()
        self.manager.set("debug", "enabled", str(self.debug_check.isChecked()))
        self.manager.save()

        if not prev_debug and self.manager.debug_enabled():
            QMessageBox.information(
                self,
                "Debug Mode Enabled",
                "Debug mode enabled. Please close and reopen FPVS Toolbox for changes to take effect.",
            )

        try:
            from Tools.Stats.Legacy.stats_helpers import (
                load_rois_from_settings,
                apply_rois_to_modules,
            )
            from Tools.Stats.stats import StatsAnalysisWindow

            rois = load_rois_from_settings(self.manager)
            apply_rois_to_modules(rois)

            for window in StatsAnalysisWindow.get_instances():
                window.reload_rois(rois)
        except Exception:
            pass

        try:
            from config import update_target_frequencies

            update_target_frequencies(
                float(self.oddball_freq_edit.text()),
                float(self.bca_limit_edit.text()),
            )
        except Exception:
            pass

        self.accept()

    # ------------------------------------------------------------------
    def _project_preprocessing(self) -> Dict[str, Any]:
        if self.project is None:
            return {}
        if self._project_cache is None:
            try:
                self._project_cache = normalize_preprocessing_settings(self.project.preprocessing)
            except ValueError as exc:
                QMessageBox.warning(self, "Invalid Settings", str(exc))
                self._project_cache = normalize_preprocessing_settings({})
        return self._project_cache

    def _collect_project_preprocessing_inputs(self) -> Dict[str, Any]:
        values: Dict[str, Any] = {}
        canonical_keys = [
            "low_pass",
            "high_pass",
            "downsample",
            "epoch_start_s",
            "rejection_z",
            "epoch_end_s",
            "ref_chan1",
            "ref_chan2",
            "max_chan_idx_keep",
            "max_bad_chans",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            values[canonical] = edit.text()
        values["stim_channel"] = self.stim_edit.text()
        values["save_preprocessed_fif"] = self.save_fif_check.isChecked()
        return values
