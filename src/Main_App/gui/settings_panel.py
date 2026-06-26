from __future__ import annotations

from typing import Any, Dict

import config
import psutil

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QHBoxLayout,
    QComboBox,
    QDialog,
    QTabWidget,
    QGridLayout,
    QCheckBox,
    QMessageBox,
    QSizePolicy,
    QToolButton,
)

from Main_App.Shared.settings_manager import SettingsManager
from Main_App.Shared.roi_presets import (
    default_roi_name_keys,
    default_roi_presets,
    supported_roi_montages,
    validate_roi_montage,
)
from Main_App.workers.mp_env import get_ram_tier_recommendation
from Main_App.gui.components import (
    ActionRow,
    SectionCard,
    StatusBanner,
    SubsectionHeaderLabel,
    make_action_button,
    make_form_layout,
)
from Main_App.gui.icons import sidebar_icon
from Main_App.gui.roi_settings_editor import ROISettingsEditor
from Main_App.projects.projects_root import changeProjectsRoot
from Main_App.projects.project import Project
from Main_App.projects.preprocessing_settings import PREPROCESSING_DEFAULTS, normalize_preprocessing_settings


REMOVED_ELECTRODE_DETECTION_INFO_TEXT = (
    "In the development of FPVS Toolbox, this automatic detection method was "
    "designed to identify electrodes that needed to be physically removed prior "
    "to the start of a recording. In our lab, we were dealing with electrodes "
    "that would sometimes cause a CMS/DRL error, and I calibrated this detection "
    "method using real experimental data. This method was over 99% specific in "
    "removing the correct channels in our training data, but this method is "
    "intentionally very conservative and prioritizes avoiding false positive "
    "electrode removals. As a result, this method only detects around 60% of "
    "electrodes that were actually physically unplugged prior to recording, but "
    "when it does identify an electrode, it is correct 99.7% of the time."
)


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
        form = make_form_layout()
        layout.addLayout(form)

        self.out_edit = QLineEdit()
        self.thr_edit = QLineEdit()
        form.addRow(QLabel("Output Folder"), self.out_edit)
        form.addRow(QLabel("Threshold"), self.thr_edit)

        self.ok_btn = make_action_button("OK", variant="primary")
        self.cancel_btn = make_action_button("Cancel", variant="tertiary")
        btn_row = ActionRow(self, alignment=Qt.AlignLeft)
        btn_row.setObjectName("settings_panel_actions")
        btn_row.add_button(self.ok_btn)
        btn_row.add_button(self.cancel_btn)
        layout.addWidget(btn_row)

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
        self.host = parent
        self.manager = manager
        self.project = project
        self._project_cache: Dict[str, Any] | None = None
        self._custom_roi_presets_by_montage: dict[str, list[tuple[str, list[str]]]] = {}
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
        layout.addWidget(self.tabs, 1)

        preproc_tab = self._init_preproc_tab(self.tabs)
        self._preproc_tab_index = self.tabs.indexOf(preproc_tab)
        self._init_stats_tab(self.tabs)
        self._init_rois_tab(self.tabs)
        self._init_advanced_tab(self.tabs)
        self._last_tab_index = self.tabs.currentIndex()
        self._tab_change_guard = False
        self.tabs.currentChanged.connect(self._on_tab_changed)

    def _add_settings_footer(self, tab: QWidget, layout: QVBoxLayout, object_name: str) -> None:
        footer = QWidget(tab)
        footer.setObjectName(object_name)
        footer_layout = QVBoxLayout(footer)
        footer_layout.setContentsMargins(0, 0, 0, 0)
        footer_layout.setSpacing(8)

        change_root = make_action_button("Change Projects Root...", parent=footer)
        change_root.setObjectName(f"{object_name}_change_root")
        change_root.clicked.connect(lambda: changeProjectsRoot(self))
        footer_layout.addWidget(change_root)
        if not hasattr(self, "btn_changeRoot"):
            self.btn_changeRoot = change_root

        actions = ActionRow(footer, alignment=Qt.AlignRight)
        actions.setObjectName(f"{object_name}_actions")
        save_btn = make_action_button("Save", variant="primary", parent=actions)
        cancel_btn = make_action_button("Cancel", variant="secondary", parent=actions)
        save_btn.clicked.connect(self._save)
        cancel_btn.clicked.connect(self.reject)
        actions.add_button(save_btn)
        actions.add_button(cancel_btn)
        footer_layout.addWidget(actions)

        layout.addWidget(footer)

    # ------------------------------------------------------------------
    def _init_preproc_tab(self, tabs: QTabWidget) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        self.group_preproc = SectionCard(
            "Preprocessing Parameters",
            tab,
            object_name="preprocessing_parameters_card",
            content_layout=QGridLayout(),
        )
        grid = self.group_preproc.content_layout
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
            "Max Parallel Workers Override (0=Auto):",
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
            (
                "preprocessing",
                "max_parallel_workers",
                str(PREPROCESSING_DEFAULTS["max_parallel_workers_override"]),
                "max_parallel_workers_override",
            ),
        ]
        project_pp = self._project_preprocessing() if self.project else None
        for edit, (sec, opt, fallback, canonical) in zip(self.preproc_edits, pre_keys):
            if project_pp is not None:
                value = project_pp.get(canonical)
                edit.setText("" if value is None else str(value))
            else:
                edit.setText(self.manager.get(sec, opt, fallback))

        layout.addWidget(self.group_preproc)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_preproc_footer")
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
            "max_parallel_workers_override",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            edit.editingFinished.connect(
                lambda canon=canonical, field=edit: self._on_preproc_edit_finished(canon, field)
            )

        return tab

    # ------------------------------------------------------------------
    def _init_stats_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        analysis_group = SectionCard(
            "Analysis Defaults",
            tab,
            object_name="settings_stats_analysis_card",
        )
        analysis_form = make_form_layout()

        self.base_freq_edit = QLineEdit(self.manager.get("analysis", "base_freq", "6.0"))
        analysis_form.addRow(QLabel("FPVS base frequency (Hz):"), self.base_freq_edit)

        self.oddball_freq_edit = QLineEdit(str(config.DEFAULT_ODDBALL_FREQ))
        self.oddball_freq_edit.setReadOnly(True)
        self.oddball_freq_edit.setToolTip(
            "Locked at 1.2 Hz. Use BCA harmonic upper limit to choose how high harmonics are calculated."
        )
        analysis_form.addRow(QLabel("Oddball frequency (Hz):"), self.oddball_freq_edit)

        self.bca_limit_edit = QLineEdit(self.manager.get("analysis", "bca_upper_limit", "16.8"))
        analysis_form.addRow(QLabel("BCA harmonic upper limit:"), self.bca_limit_edit)

        self.alpha_edit = QLineEdit(self.manager.get("analysis", "alpha", "0.05"))
        analysis_form.addRow(QLabel("ANOVA alpha value:"), self.alpha_edit)
        analysis_group.content_layout.addLayout(analysis_form)
        layout.addWidget(analysis_group)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_stats_footer")

        tabs.addTab(tab, "Stats")

    # ------------------------------------------------------------------
    def _init_rois_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        current_montage = self.manager.get_roi_montage()
        self._custom_roi_presets_by_montage[current_montage] = self.manager.get_custom_roi_presets(
            current_montage
        )
        quick_add_group = SectionCard(
            "Quick Add",
            tab,
            object_name="settings_rois_quick_add_card",
        )
        quick_add_form = make_form_layout()

        self.roi_montage_combo = QComboBox(quick_add_group)
        self.roi_montage_combo.setObjectName("settings_rois_montage_combo")
        for montage_key, label in supported_roi_montages():
            self.roi_montage_combo.addItem(label, montage_key)
        montage_index = self.roi_montage_combo.findData(current_montage)
        if montage_index >= 0:
            self.roi_montage_combo.setCurrentIndex(montage_index)
        quick_add_form.addRow(QLabel("Electrode montage:", quick_add_group), self.roi_montage_combo)

        self.roi_preset_combo = QComboBox(quick_add_group)
        self.roi_preset_combo.setObjectName("settings_rois_preset_combo")
        quick_add_form.addRow(QLabel("Quick-add ROI:", quick_add_group), self.roi_preset_combo)

        self.roi_preset_electrodes_edit = QLineEdit(quick_add_group)
        self.roi_preset_electrodes_edit.setObjectName("settings_rois_preset_electrodes")
        self.roi_preset_electrodes_edit.setReadOnly(True)
        quick_add_form.addRow(QLabel("Electrodes:", quick_add_group), self.roi_preset_electrodes_edit)
        quick_add_group.content_layout.addLayout(quick_add_form)

        quick_add_actions = ActionRow(quick_add_group, alignment=Qt.AlignLeft)
        quick_add_actions.setObjectName("settings_rois_quick_add_actions")
        add_preset_btn = make_action_button("Add ROI", compact=True, parent=quick_add_group)
        add_preset_btn.setObjectName("settings_rois_add_preset")
        add_preset_btn.clicked.connect(self._add_selected_roi_preset)
        save_presets_btn = make_action_button("Save Custom Presets", compact=True, parent=quick_add_group)
        save_presets_btn.setObjectName("settings_rois_save_custom_presets")
        save_presets_btn.clicked.connect(self._save_roi_editor_as_custom_presets)
        quick_add_actions.add_button(add_preset_btn)
        quick_add_actions.add_button(save_presets_btn)
        quick_add_group.content_layout.addWidget(quick_add_actions)

        self.roi_preset_status = StatusBanner("", quick_add_group, variant="info")
        self.roi_preset_status.setObjectName("settings_rois_preset_status")
        self.roi_preset_status.setVisible(False)
        quick_add_group.content_layout.addWidget(self.roi_preset_status)

        self.roi_montage_combo.currentIndexChanged.connect(self._on_roi_montage_changed)
        self.roi_preset_combo.currentIndexChanged.connect(self._update_roi_preset_preview)

        roi_group = SectionCard(
            "Regions of Interest",
            tab,
            object_name="settings_rois_card",
        )
        roi_group.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_header = QWidget(roi_group)
        roi_header_layout = QHBoxLayout(roi_header)
        roi_header_layout.setContentsMargins(0, 0, 0, 0)
        roi_header_layout.setSpacing(8)
        roi_header_layout.addWidget(SubsectionHeaderLabel("ROI name", roi_header), 1)
        roi_header_layout.addWidget(SubsectionHeaderLabel("Electrodes", roi_header), 1)
        roi_header_layout.addSpacing(32)
        roi_group.content_layout.addWidget(roi_header)

        self.roi_editor = ROISettingsEditor(self, self.manager.get_roi_pairs())
        self.roi_editor.setObjectName("settings_rois_editor")
        self.roi_editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.roi_editor.scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        roi_group.content_layout.addWidget(self.roi_editor, 1)

        add_btn = make_action_button("+ Add ROI", compact=True, parent=roi_group)
        add_btn.setObjectName("settings_rois_add_roi")
        add_btn.clicked.connect(lambda: self.roi_editor.add_entry())
        roi_actions = ActionRow(roi_group, alignment=Qt.AlignLeft)
        roi_actions.setObjectName("settings_rois_actions")
        roi_actions.add_button(add_btn)
        roi_group.content_layout.addWidget(roi_actions)

        layout.addWidget(roi_group, 1)
        layout.addWidget(quick_add_group)
        self._add_settings_footer(tab, layout, "settings_rois_footer")
        self._refresh_roi_preset_combo()

        tabs.addTab(tab, "ROIs")

    # ------------------------------------------------------------------
    def _init_advanced_tab(self, tabs: QTabWidget) -> None:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        advanced_group = SectionCard(
            "Application Options",
            tab,
            object_name="settings_advanced_application_card",
        )
        advanced_form = make_form_layout()

        debug_default = self.manager.get("debug", "enabled", "False").lower() == "true"
        self.debug_check = QCheckBox("Enable Debug", advanced_group)
        self.debug_check.setObjectName("settings_enable_debug")
        self.debug_check.setChecked(debug_default)
        advanced_form.addRow(QLabel("Debug Mode", advanced_group), self.debug_check)

        self.beta_tools_check = QCheckBox("Enable Beta Tools", advanced_group)
        self.beta_tools_check.setObjectName("settings_enable_beta_tools")
        self.beta_tools_check.setChecked(self.manager.beta_tools_enabled())
        advanced_form.addRow(QLabel("Beta Tools", advanced_group), self.beta_tools_check)

        advanced_group.content_layout.addLayout(advanced_form)
        layout.addWidget(advanced_group)

        qc_group = SectionCard(
            "Processing QC",
            tab,
            object_name="settings_advanced_processing_qc_card",
        )
        qc_form = make_form_layout()
        if self.project is not None:
            qc_preproc = self._project_preprocessing()
            auto_detect_default = bool(
                qc_preproc.get(
                    "auto_detect_removed_electrodes",
                    PREPROCESSING_DEFAULTS["auto_detect_removed_electrodes"],
                )
            )
        else:
            auto_detect_default = (
                self.manager.get(
                    "preprocessing",
                    "auto_detect_removed_electrodes",
                    str(PREPROCESSING_DEFAULTS["auto_detect_removed_electrodes"]),
                ).lower()
                == "true"
            )
        self.removed_electrode_detection_mode_combo = QComboBox(qc_group)
        self.removed_electrode_detection_mode_combo.setObjectName(
            "settings_removed_electrode_detection_mode"
        )
        self.removed_electrode_detection_mode_combo.addItem("Off", False)
        self.removed_electrode_detection_mode_combo.addItem(
            "Conservative auto-detect",
            True,
        )
        self.removed_electrode_detection_mode_combo.setCurrentIndex(
            1 if auto_detect_default else 0
        )
        self.removed_electrode_detection_mode_combo.setToolTip(
            "Choose whether raw-channel QC should automatically mark "
            "high-confidence removed-electrode candidates. Manual removed-electrode "
            "metadata will take precedence when that mode is added."
        )

        self.removed_electrode_detection_info_button = QToolButton(qc_group)
        self.removed_electrode_detection_info_button.setObjectName(
            "settings_removed_electrode_detection_info"
        )
        self.removed_electrode_detection_info_button.setIcon(sidebar_icon("info", 16))
        self.removed_electrode_detection_info_button.setToolTip(
            "About conservative removed-electrode detection"
        )
        self.removed_electrode_detection_info_button.setCursor(Qt.PointingHandCursor)
        self.removed_electrode_detection_info_button.setProperty("compact", True)
        self.removed_electrode_detection_info_button.setProperty("iconButton", True)
        self.removed_electrode_detection_info_button.clicked.connect(
            self._show_removed_electrode_detection_info
        )

        removed_detection_row = QWidget(qc_group)
        removed_detection_row.setObjectName("settings_removed_electrode_detection_row")
        removed_detection_layout = QHBoxLayout(removed_detection_row)
        removed_detection_layout.setContentsMargins(0, 0, 0, 0)
        removed_detection_layout.setSpacing(8)
        removed_detection_layout.addWidget(self.removed_electrode_detection_mode_combo, 1)
        removed_detection_layout.addWidget(self.removed_electrode_detection_info_button)

        # Legacy compatibility for older helpers/tests that read the prior
        # checkbox attribute while the visible UI now uses a mode selector.
        self.auto_detect_removed_electrodes_check = QCheckBox(qc_group)
        self.auto_detect_removed_electrodes_check.setObjectName(
            "settings_auto_detect_removed_electrodes"
        )
        self.auto_detect_removed_electrodes_check.setChecked(auto_detect_default)
        self.auto_detect_removed_electrodes_check.hide()
        self.auto_detect_removed_electrodes_check.toggled.connect(
            self._set_removed_electrode_detection_enabled
        )
        self.removed_electrode_detection_mode_combo.currentIndexChanged.connect(
            self._sync_removed_electrode_detection_checkbox
        )
        qc_form.addRow(
            QLabel("Removed-electrode QC mode", qc_group),
            removed_detection_row,
        )
        qc_group.content_layout.addLayout(qc_form)
        layout.addWidget(qc_group)

        layout.addStretch(1)
        self._add_settings_footer(tab, layout, "settings_advanced_footer")

        tabs.addTab(tab, "Advanced")

    def _removed_electrode_detection_enabled(self) -> bool:
        return bool(self.removed_electrode_detection_mode_combo.currentData())

    def _set_removed_electrode_detection_enabled(self, enabled: bool) -> None:
        target_index = self.removed_electrode_detection_mode_combo.findData(bool(enabled))
        if target_index >= 0 and target_index != self.removed_electrode_detection_mode_combo.currentIndex():
            self.removed_electrode_detection_mode_combo.setCurrentIndex(target_index)

    def _sync_removed_electrode_detection_checkbox(self) -> None:
        enabled = self._removed_electrode_detection_enabled()
        if self.auto_detect_removed_electrodes_check.isChecked() == enabled:
            return
        self.auto_detect_removed_electrodes_check.blockSignals(True)
        try:
            self.auto_detect_removed_electrodes_check.setChecked(enabled)
        finally:
            self.auto_detect_removed_electrodes_check.blockSignals(False)

    def _show_removed_electrode_detection_info(self) -> None:
        QMessageBox.information(
            self,
            "Conservative Removed-Electrode Detection",
            REMOVED_ELECTRODE_DETECTION_INFO_TEXT,
        )

    def _current_roi_montage(self) -> str:
        return validate_roi_montage(str(self.roi_montage_combo.currentData()))

    def _custom_roi_presets(self, montage: str) -> list[tuple[str, list[str]]]:
        montage_key = validate_roi_montage(montage)
        if montage_key not in self._custom_roi_presets_by_montage:
            self._custom_roi_presets_by_montage[montage_key] = self.manager.get_custom_roi_presets(montage_key)
        return self._custom_roi_presets_by_montage[montage_key]

    def _roi_preset_items(self, montage: str) -> list[tuple[str, list[str], bool]]:
        montage_key = validate_roi_montage(montage)
        items: list[tuple[str, list[str], bool]] = []
        seen: set[str] = set()
        for preset in default_roi_presets(montage_key):
            items.append((preset.name, list(preset.electrodes), True))
            seen.add(preset.name.casefold())
        for name, electrodes in self._custom_roi_presets(montage_key):
            if name.casefold() not in seen:
                items.append((name, list(electrodes), False))
                seen.add(name.casefold())
        return items

    def _refresh_roi_preset_combo(self) -> None:
        montage = self._current_roi_montage()
        self.roi_preset_combo.blockSignals(True)
        self.roi_preset_combo.clear()
        for name, electrodes, is_default in self._roi_preset_items(montage):
            source = "Default" if is_default else "Custom"
            self.roi_preset_combo.addItem(f"{name} ({source})", (name, electrodes, is_default))
        self.roi_preset_combo.blockSignals(False)
        self._update_roi_preset_preview()

    def _selected_roi_preset(self) -> tuple[str, list[str], bool] | None:
        preset = self.roi_preset_combo.currentData()
        if not isinstance(preset, tuple) or len(preset) != 3:
            return None
        name, electrodes, is_default = preset
        if not isinstance(name, str) or not isinstance(electrodes, list) or not isinstance(is_default, bool):
            return None
        return name, electrodes, is_default

    def _set_roi_preset_status(self, text: str, variant: str = "info") -> None:
        self.roi_preset_status.set_variant(variant)
        self.roi_preset_status.set_text(text)
        self.roi_preset_status.setVisible(bool(text))

    def _update_roi_preset_preview(self) -> None:
        preset = self._selected_roi_preset()
        if preset is None:
            self.roi_preset_electrodes_edit.clear()
            return
        _name, electrodes, _is_default = preset
        self.roi_preset_electrodes_edit.setText(",".join(electrodes))

    def _on_roi_montage_changed(self) -> None:
        self._refresh_roi_preset_combo()
        self._set_roi_preset_status("")

    def _add_selected_roi_preset(self) -> None:
        preset = self._selected_roi_preset()
        if preset is None:
            self._set_roi_preset_status("No ROI preset is selected.", "warning")
            return
        name, electrodes, _is_default = preset
        result = self.roi_editor.add_or_update_entry(name, electrodes)
        action = "Updated" if result == "updated" else "Added"
        self._set_roi_preset_status(f"{action} {name}.", "success")

    def _save_roi_editor_as_custom_presets(self) -> None:
        montage = self._current_roi_montage()
        default_names = default_roi_name_keys(montage)
        custom_by_name = {
            name.casefold(): (name, list(electrodes))
            for name, electrodes in self._custom_roi_presets(montage)
        }
        changed = 0
        for name, electrodes in self.roi_editor.get_pairs():
            name_key = name.casefold()
            if name_key in default_names:
                continue
            candidate = (name, list(electrodes))
            if custom_by_name.get(name_key) != candidate:
                changed += 1
            custom_by_name[name_key] = candidate

        self._custom_roi_presets_by_montage[montage] = list(custom_by_name.values())
        self._refresh_roi_preset_combo()
        if changed:
            self._set_roi_preset_status("Custom ROI presets will be saved when you click Save.", "success")
        else:
            self._set_roi_preset_status("No new custom ROI presets found.", "info")

    def _on_tab_changed(self, index: int) -> None:
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

        self._last_tab_index = index

    # ------------------------------------------------------------------
    def _focus_invalid_preproc_field(self, message: str) -> None:
        msg_lower = message.lower()
        target_idx = None
        if "low-pass" in msg_lower or "'low_pass'" in msg_lower:
            target_idx = 0
        elif "high-pass" in msg_lower or "'high_pass'" in msg_lower:
            target_idx = 1
        elif "'max_parallel_workers_override'" in msg_lower:
            target_idx = 10
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

    def _confirm_parallel_worker_override(self, normalized: Dict[str, Any]) -> bool:
        override = int(normalized.get("max_parallel_workers_override", 0))
        if override <= 0:
            return True

        try:
            total_ram_bytes = int(psutil.virtual_memory().total)
        except Exception:
            return True

        _tier, recommended_cap, _ram_gib = get_ram_tier_recommendation(total_ram_bytes)
        if recommended_cap is None or override <= recommended_cap:
            return True

        message = (
            f"The maximum amount of workers recommended for your RAM tier is [{recommended_cap}]. "
            "Selecting a value higher than this could cause your system to become slow or "
            "completely unresponsive for a time. Do you wish to continue?"
        )
        choice = QMessageBox.question(
            self,
            "High Worker Count Warning",
            message,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if choice != QMessageBox.Yes:
            if len(self.preproc_edits) > 10:
                field = self.preproc_edits[10]
                field.setFocus()
                field.selectAll()
            return False
        return True

    # ------------------------------------------------------------------
    def _save(self) -> None:
        using_project = self.project is not None

        validated_preproc = self._validated_preproc_payload()
        if validated_preproc is None:
            return
        if not self._confirm_parallel_worker_override(validated_preproc):
            return

        if not using_project:
            self.manager.set("stim", "channel", config.DEFAULT_STIM_CHANNEL)
        self.manager.set("analysis", "base_freq", self.base_freq_edit.text())
        self.manager.set("analysis", "oddball_freq", str(config.DEFAULT_ODDBALL_FREQ))
        self.manager.set("analysis", "bca_upper_limit", self.bca_limit_edit.text())
        self.manager.set("analysis", "alpha", self.alpha_edit.text())
        self.manager.set_roi_montage(self._current_roi_montage())
        self.manager.set_roi_pairs(self.roi_editor.get_pairs())
        for montage_key, custom_presets in self._custom_roi_presets_by_montage.items():
            self.manager.set_custom_roi_presets(montage_key, custom_presets)
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
            ("preprocessing", "max_parallel_workers", "max_parallel_workers_override"),
        ]
        if not using_project:
            for _edit, (sec, opt, canonical) in zip(self.preproc_edits, pre_keys):
                value = validated_preproc.get(canonical, "")
                self.manager.set(sec, opt, str(value))
            self.manager.set(
                "preprocessing",
                "auto_detect_removed_electrodes",
                str(bool(validated_preproc.get("auto_detect_removed_electrodes"))),
            )
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
        prev_debug = self.manager.debug_enabled()
        prev_beta_tools = self.manager.beta_tools_enabled()
        self.manager.set("debug", "enabled", str(self.debug_check.isChecked()))
        self.manager.set_beta_tools_enabled(self.beta_tools_check.isChecked())
        self.manager.save()

        if not prev_debug and self.manager.debug_enabled():
            QMessageBox.information(
                self,
                "Debug Mode Enabled",
                "Debug mode enabled. Please close and reopen FPVS Toolbox for changes to take effect.",
            )
        if prev_beta_tools != self.manager.beta_tools_enabled():
            QMessageBox.information(
                self,
                "Tool Visibility Updated",
                "Please close and reopen FPVS Toolbox for your changes to take effect.",
            )

        try:
            from Tools.Stats.data.shared_rois import (
                load_rois_from_settings,
                apply_rois_to_modules,
            )

            rois = load_rois_from_settings(self.manager)
            apply_rois_to_modules(rois)

            host = getattr(self, "host", None) or self.parent()
            stats_page = getattr(host, "_stats_page", None)
            if stats_page is not None:
                refresh_rois = getattr(stats_page, "refresh_rois", None)
                if callable(refresh_rois):
                    refresh_rois()
        except Exception:
            pass

        try:
            from config import update_target_frequencies

            update_target_frequencies(
                config.DEFAULT_ODDBALL_FREQ,
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
            "max_parallel_workers_override",
        ]
        for edit, canonical in zip(self.preproc_edits, canonical_keys):
            values[canonical] = edit.text()
        values["auto_detect_removed_electrodes"] = self._removed_electrode_detection_enabled()
        values["stim_channel"] = config.DEFAULT_STIM_CHANNEL
        return values


class EmbeddedSettingsPage(SettingsDialog):
    """Settings editor used as a workspace page inside the main shell."""

    def __init__(
        self,
        manager: SettingsManager,
        host: QWidget,
        project: Project | None = None,
    ) -> None:
        super().__init__(manager, host, project)
        self.host = host
        self.setObjectName("embedded_settings_page")
        self.setWindowFlags(Qt.Widget)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def accept(self) -> None:
        self._return_to_home()

    def reject(self) -> None:
        self._return_to_home()

    def _return_to_home(self) -> None:
        host = getattr(self, "host", None)
        if host is None:
            return
        debug_label = getattr(host, "lbl_debug", None)
        if debug_label is not None:
            debug_label.setVisible(host.settings.debug_enabled())
        show_home_page = getattr(host, "show_home_page", None)
        if callable(show_home_page):
            show_home_page()
