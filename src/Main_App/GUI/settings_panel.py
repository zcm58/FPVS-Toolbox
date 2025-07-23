from __future__ import annotations

from PySide6.QtCore import Signal, QSettings
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QFormLayout,
    QLineEdit,
    QPushButton,
    QLabel,
    QHBoxLayout,
    QDialog,
    QTabWidget,
    QGroupBox,
    QGridLayout,
    QComboBox,
    QCheckBox,
    QDialogButtonBox,
    QFileDialog,
    QMessageBox,
)

from Main_App.settings_manager import SettingsManager
from Main_App.GUI.roi_settings_editor import ROISettingsEditor


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

    def __init__(self, manager: SettingsManager, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.manager = manager
        self._build_ui()

    # ------------------------------------------------------------------
    # UI Construction
    # ------------------------------------------------------------------
    def _build_ui(self) -> None:
        self.setWindowTitle("Settings")
        layout = QVBoxLayout(self)

        tabs = QTabWidget()
        layout.addWidget(tabs)

        self._init_general_tab(tabs)
        self._init_preproc_tab(tabs)
        self._init_stats_tab(tabs)
        self._init_oddball_tab(tabs)
        self._init_loreta_tab(tabs)

        self.btn_changeRoot = QPushButton("Change Projects Root…", self)
        self.btn_changeRoot.clicked.connect(self.changeProjectsRoot)
        layout.addWidget(self.btn_changeRoot)

        btn_box = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        layout.addWidget(btn_box)
        btn_box.accepted.connect(self._save)
        btn_box.rejected.connect(self.reject)

    # ------------------------------------------------------------------
    def _init_general_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        form = QFormLayout(tab)

        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["System", "Dark", "Light"])
        self.mode_combo.setCurrentText(self.manager.get("appearance", "mode", "System"))
        form.addRow(QLabel("Appearance Mode"), self.mode_combo)

        self.data_edit = QLineEdit(self.manager.get("paths", "data_folder", ""))
        data_row = self._with_browse(self.data_edit)
        form.addRow(QLabel("Default Data Folder"), data_row)

        self.out_edit = QLineEdit(self.manager.get("paths", "output_folder", ""))
        out_row = self._with_browse(self.out_edit)
        form.addRow(QLabel("Default Output Folder"), out_row)

        self.main_size_edit = QLineEdit(self.manager.get("gui", "main_size", "750x920"))
        form.addRow(QLabel("Main Window Size (WxH)"), self.main_size_edit)

        self.stats_size_edit = QLineEdit(self.manager.get("gui", "stats_size", "700x650"))
        form.addRow(QLabel("Stats Window Size (WxH)"), self.stats_size_edit)

        self.resize_size_edit = QLineEdit(self.manager.get("gui", "resizer_size", "600x600"))
        form.addRow(QLabel("Image Resizer Size (WxH)"), self.resize_size_edit)

        self.adv_size_edit = QLineEdit(self.manager.get("gui", "advanced_size", "500x500"))
        form.addRow(QLabel("Advanced Analysis Size (WxH)"), self.adv_size_edit)

        self.stim_edit = QLineEdit(self.manager.get("stim", "channel", "Status"))
        form.addRow(QLabel("Stim Channel"), self.stim_edit)

        self.cond_edit = QLineEdit(self.manager.get("events", "labels", ""))
        form.addRow(QLabel("Default Conditions"), self.cond_edit)

        self.id_edit = QLineEdit(self.manager.get("events", "ids", ""))
        form.addRow(QLabel("Default IDs"), self.id_edit)

        debug_default = self.manager.get("debug", "enabled", "False").lower() == "true"
        self.debug_check = QCheckBox("Enable Debug")
        self.debug_check.setChecked(debug_default)
        form.addRow(QLabel("Debug Mode"), self.debug_check)

        tabs.addTab(tab, "General")

    # ------------------------------------------------------------------
    def _init_preproc_tab(self, tabs: QTabWidget) -> None:
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
            ("preprocessing", "low_pass", "0.1"),
            ("preprocessing", "high_pass", "50"),
            ("preprocessing", "downsample", "256"),
            ("preprocessing", "epoch_start", "-1"),
            ("preprocessing", "reject_thresh", "5"),
            ("preprocessing", "epoch_end", "125"),
            ("preprocessing", "ref_chan1", "EXG1"),
            ("preprocessing", "ref_chan2", "EXG2"),
            ("preprocessing", "max_idx_keep", "64"),
            ("preprocessing", "max_bad_chans", "10"),
        ]
        for edit, (sec, opt, fallback) in zip(self.preproc_edits, pre_keys):
            edit.setText(self.manager.get(sec, opt, fallback))

        self.save_fif_check = QCheckBox("Save Preprocessed .fif", self.group_preproc)
        self.save_fif_check.setChecked(
            self.manager.get("paths", "save_fif", "False").lower() == "true"
        )
        grid.addWidget(self.save_fif_check, 5, 0, 1, 4)

        layout.addWidget(self.group_preproc)
        layout.addStretch(1)
        tabs.addTab(tab, "Preprocessing")

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

        self.roi_editor = ROISettingsEditor(self, self.manager.get_roi_pairs())
        form.addRow(QLabel("Regions of Interest"), self.roi_editor)

        add_btn = QPushButton("+ Add ROI")
        add_btn.clicked.connect(self.roi_editor.add_entry)
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
    def _init_loreta_tab(self, tabs: QTabWidget) -> None:
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

        tabs.addTab(tab, "LORETA")

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

    # ------------------------------------------------------------------
    def changeProjectsRoot(self) -> None:
        settings = QSettings()
        root = QFileDialog.getExistingDirectory(
            self,
            "Select Projects Root Folder",
            settings.value("paths/projectsRoot", ""),
        )
        if not root:
            return
        settings.setValue("paths/projectsRoot", root)
        settings.sync()
        QMessageBox.information(
            self,
            "Projects Root Updated",
            f"New Projects Root: {root}",
        )

    # ------------------------------------------------------------------
    def _save(self) -> None:
        self.manager.set("appearance", "mode", self.mode_combo.currentText())
        self.manager.set("paths", "data_folder", self.data_edit.text())
        self.manager.set("paths", "output_folder", self.out_edit.text())
        self.manager.set("gui", "main_size", self.main_size_edit.text())
        self.manager.set("gui", "stats_size", self.stats_size_edit.text())
        self.manager.set("gui", "resizer_size", self.resize_size_edit.text())
        self.manager.set("gui", "advanced_size", self.adv_size_edit.text())
        self.manager.set("stim", "channel", self.stim_edit.text())
        self.manager.set("events", "labels", self.cond_edit.text())
        self.manager.set("events", "ids", self.id_edit.text())
        self.manager.set("analysis", "base_freq", self.base_freq_edit.text())
        self.manager.set("analysis", "oddball_freq", self.oddball_freq_edit.text())
        self.manager.set("analysis", "bca_upper_limit", self.bca_limit_edit.text())
        self.manager.set("analysis", "alpha", self.alpha_edit.text())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        pre_keys = [
            ("preprocessing", "low_pass"),
            ("preprocessing", "high_pass"),
            ("preprocessing", "downsample"),
            ("preprocessing", "epoch_start"),
            ("preprocessing", "reject_thresh"),
            ("preprocessing", "epoch_end"),
            ("preprocessing", "ref_chan1"),
            ("preprocessing", "ref_chan2"),
            ("preprocessing", "max_idx_keep"),
            ("preprocessing", "max_bad_chans"),
        ]
        for edit, (sec, opt) in zip(self.preproc_edits, pre_keys):
            self.manager.set(sec, opt, edit.text())
        self.manager.set("paths", "save_fif", str(self.save_fif_check.isChecked()))
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
            from Tools.Stats.stats_helpers import load_rois_from_settings, apply_rois_to_modules
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
