"""Settings and persistence helpers for the Plot Generator GUI."""
from __future__ import annotations

import logging

from Main_App.projects.project import Project
from Main_App.projects.project_metadata import read_project_metadata


_LEGEND_LABELS_KEY_PATH = ("tools", "snr_plot", "legend_labels")
_PLOT_SETTINGS_KEY_PATH = ("tools", "snr_plot", "plot_settings")
_LEGEND_DEFAULT_A_PEAKS = "A-Peaks"
_LEGEND_DEFAULT_B_PEAKS = "B-Peaks"

logger = logging.getLogger(__name__)


def _settings_bool(value: object, fallback: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return fallback


def _settings_float(value: object, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


class PlotGeneratorSettingsMixin:
    """Project and legend settings helpers for PlotGeneratorWindow."""

    def _legend_peaks_default(self, condition_label: str, fallback: str) -> str:
        label = condition_label.strip()
        return f"{label} Peaks" if label else fallback

    def _legend_default_values(self) -> dict[str, str]:
        condition_a = self.condition_combo.currentText().strip()
        condition_b = self.condition_b_combo.currentText().strip()
        return {
            "condition_a_label": condition_a,
            "condition_b_label": condition_b,
            "a_peaks_label": self._legend_peaks_default(
                condition_a, _LEGEND_DEFAULT_A_PEAKS
            ),
            "b_peaks_label": self._legend_peaks_default(
                condition_b, _LEGEND_DEFAULT_B_PEAKS
            ),
        }

    def _legend_settings_payload(self) -> dict[str, object]:
        return {
            "custom_labels_enabled": self.legend_custom_check.isChecked(),
            "condition_a_label": self.legend_condition_a_edit.text(),
            "condition_b_label": self.legend_condition_b_edit.text(),
            "a_peaks_label": self.legend_a_peaks_edit.text(),
            "b_peaks_label": self.legend_b_peaks_edit.text(),
        }

    def _read_project_plot_settings(self) -> dict[str, object]:
        if self._project is None:
            return {}
        cursor: object = self._project.manifest
        for key in _PLOT_SETTINGS_KEY_PATH:
            if not isinstance(cursor, dict):
                return {}
            cursor = cursor.get(key, {})
        return dict(cursor) if isinstance(cursor, dict) else {}

    def _project_plot_settings_payload(self, *, include_paths: bool) -> dict[str, object]:
        payload: dict[str, object] = {
            "stem_color": self.stem_color,
            "stem_color_b": self.stem_color_b,
            "include_scalp_maps": self.scalp_check.isChecked(),
            "scalp_min": self.scalp_min_spin.value(),
            "scalp_max": self.scalp_max_spin.value(),
            "title_a_template": self.scalp_title_a_edit.text(),
            "title_b_template": self.scalp_title_b_edit.text(),
        }
        if include_paths:
            payload["input_folder"] = self.folder_edit.text()
            payload["output_folder"] = self.out_edit.text()
        return payload

    def _persist_project_plot_settings(self, *, include_paths: bool) -> bool:
        if self._project is None or self._ui_initializing:
            return False
        manifest = self._project.manifest
        cursor = manifest
        for key in _PLOT_SETTINGS_KEY_PATH:
            if key not in cursor or not isinstance(cursor.get(key), dict):
                cursor[key] = {}
            cursor = cursor[key]
        cursor.update(self._project_plot_settings_payload(include_paths=include_paths))
        try:
            self._project.save()
        except Exception as exc:
            self._append_log("Failed to save SNR plot settings to project.json.")
            logger.warning(
                "Failed to persist SNR plot settings.",
                exc_info=exc,
                extra={
                    "operation": "snr_plot_settings_persist",
                    "project_root": str(self._project.project_root),
                },
            )
            return False
        return True

    def _set_legend_text_auto(self, key: str, text: str) -> None:
        field = self._legend_fields[key]
        old_auto = self._legend_auto_values.get(key, "")
        should_update = (
            key not in self._legend_manual_overrides
            or not field.text().strip()
            or field.text() == old_auto
        )
        self._legend_auto_values[key] = text
        if should_update and field.text() != text:
            self._syncing_legend_defaults = True
            try:
                field.setText(text)
            finally:
                self._syncing_legend_defaults = False

    def _sync_legend_defaults_with_conditions(self) -> None:
        defaults = self._legend_default_values()
        for key, text in defaults.items():
            self._set_legend_text_auto(key, text)

    def _prefill_legend_defaults_if_empty(self) -> None:
        self._sync_legend_defaults_with_conditions()

    def _mark_legend_manual_override(self, key: str) -> None:
        if self._syncing_legend_defaults:
            return
        self._legend_manual_overrides.add(key)

    def _on_legend_condition_label_edited(self, condition_key: str) -> None:
        self._mark_legend_manual_override(condition_key)
        if condition_key == "condition_a_label":
            self._set_legend_text_auto(
                "a_peaks_label",
                self._legend_peaks_default(
                    self.legend_condition_a_edit.text(), _LEGEND_DEFAULT_A_PEAKS
                ),
            )
        else:
            self._set_legend_text_auto(
                "b_peaks_label",
                self._legend_peaks_default(
                    self.legend_condition_b_edit.text(), _LEGEND_DEFAULT_B_PEAKS
                ),
            )

    def _toggle_custom_legend_labels(self, checked: bool) -> None:
        self.legend_condition_a_edit.setEnabled(checked)
        self.legend_a_peaks_edit.setEnabled(checked)
        show_b = self.overlay_check.isChecked()
        self.legend_condition_b_edit.setEnabled(checked and show_b)
        self.legend_b_peaks_edit.setEnabled(checked and show_b)
        if checked:
            self._prefill_legend_defaults_if_empty()
        if not self._ui_initializing:
            self._persist_legend_settings()

    def _reset_legend_defaults(self) -> None:
        self._legend_manual_overrides.clear()
        defaults = self._legend_default_values()
        self.legend_custom_check.setChecked(False)
        self._syncing_legend_defaults = True
        try:
            self.legend_condition_a_edit.setText(defaults["condition_a_label"])
            self.legend_condition_b_edit.setText(defaults["condition_b_label"])
            self.legend_a_peaks_edit.setText(defaults["a_peaks_label"])
            self.legend_b_peaks_edit.setText(defaults["b_peaks_label"])
        finally:
            self._syncing_legend_defaults = False
        self._legend_auto_values = dict(defaults)
        self.legend_condition_a_edit.setEnabled(False)
        self.legend_condition_b_edit.setEnabled(False)
        self.legend_a_peaks_edit.setEnabled(False)
        self.legend_b_peaks_edit.setEnabled(False)
        if not self._ui_initializing:
            self._persist_legend_settings()

    def _load_legend_settings(self) -> None:
        if self._project is None and self._project_root:
            try:
                metadata = read_project_metadata(self._project_root)
            except Exception as exc:
                logger.warning(
                    "Failed to read project metadata for legend settings.",
                    exc_info=exc,
                    extra={
                        "operation": "snr_plot_project_metadata",
                        "project_root": str(self._project_root),
                    },
                )
            else:
                if metadata.parse_error:
                    self._append_log(
                        "Project settings could not be read (invalid JSON). Using defaults."
                    )
                    logger.warning(
                        "Invalid project.json detected; using defaults.",
                        extra={
                            "operation": "snr_plot_project_metadata",
                            "project_root": str(self._project_root),
                        },
                    )
            try:
                self._project = Project.load(self._project_root)
            except Exception as exc:
                self._append_log(
                    "Unable to load project settings. Legend label settings will not persist."
                )
                logger.warning(
                    "Failed to load project for legend settings.",
                    exc_info=exc,
                    extra={
                        "operation": "snr_plot_project_load",
                        "project_root": str(self._project_root),
                    },
                )
                self._project = None

        defaults = self._legend_default_values()
        labels: dict[str, object] = {}
        if self._project is not None:
            tools_section = self._project.manifest.get("tools", {})
            if isinstance(tools_section, dict):
                snr_section = tools_section.get("snr_plot", {})
                if isinstance(snr_section, dict):
                    labels = snr_section.get("legend_labels", {})
        if not isinstance(labels, dict):
            labels = {}
        self.legend_custom_check.setChecked(bool(labels.get("custom_labels_enabled", False)))
        loaded = {
            "condition_a_label": str(
                labels.get("condition_a_label", defaults["condition_a_label"])
            ),
            "condition_b_label": str(
                labels.get("condition_b_label", defaults["condition_b_label"])
            ),
            "a_peaks_label": str(labels.get("a_peaks_label", defaults["a_peaks_label"])),
            "b_peaks_label": str(labels.get("b_peaks_label", defaults["b_peaks_label"])),
        }
        self._syncing_legend_defaults = True
        try:
            self.legend_condition_a_edit.setText(loaded["condition_a_label"])
            self.legend_condition_b_edit.setText(loaded["condition_b_label"])
            self.legend_a_peaks_edit.setText(loaded["a_peaks_label"])
            self.legend_b_peaks_edit.setText(loaded["b_peaks_label"])
        finally:
            self._syncing_legend_defaults = False
        self._legend_auto_values = dict(defaults)
        self._legend_manual_overrides = {
            key for key, value in loaded.items() if value != defaults[key]
        }
        self._toggle_custom_legend_labels(self.legend_custom_check.isChecked())

    def _persist_legend_settings(self) -> None:
        if self._ui_initializing:
            return
        if self._project is None:
            logger.info(
                "Legend label settings changed without active project; skipping persistence.",
                extra={
                    "operation": "snr_plot_legend_persist",
                    "project_root": str(self._project_root) if self._project_root else None,
                },
            )
            return
        data = self._legend_settings_payload()
        manifest = self._project.manifest
        cursor = manifest
        for key in _LEGEND_LABELS_KEY_PATH:
            if key not in cursor or not isinstance(cursor.get(key), dict):
                cursor[key] = {}
            cursor = cursor[key]
        cursor.clear()
        cursor.update(data)
        try:
            self._project.save()
        except Exception as exc:
            self._append_log(
                "Failed to save legend label settings to project.json."
            )
            logger.warning(
                "Failed to persist legend label settings.",
                exc_info=exc,
                extra={
                    "operation": "snr_plot_legend_persist",
                    "project_root": str(self._project.project_root),
                },
            )
