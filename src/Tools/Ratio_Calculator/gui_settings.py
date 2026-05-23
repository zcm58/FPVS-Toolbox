"""Settings parsing and validation helpers for the Ratio Calculator GUI."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSignalBlocker

from .constants import RatioCalculatorSettings


class RatioSettingsMixin:
    """GUI-only settings parsing, run-label state, and validation behavior."""

    def _mark_label_a_dirty(self) -> None:
        self._label_a_dirty = True

    def _mark_label_b_dirty(self) -> None:
        self._label_b_dirty = True

    def _mark_run_label_dirty(self) -> None:
        self._run_label_dirty = True

    def _on_label_text_changed(self) -> None:
        self._update_run_label_default()

    def _update_run_label_default(self) -> None:
        if self._run_label_dirty:
            return
        label_a = self.label_a_edit.text().strip()
        label_b = self.label_b_edit.text().strip()
        if label_a and label_b:
            with QSignalBlocker(self.run_label_edit):
                self.run_label_edit.setText(f"{label_a} vs {label_b}")

    def _settings_from_ui(self) -> RatioCalculatorSettings:
        excluded = self._parse_excluded_freqs()
        return RatioCalculatorSettings(
            oddball_base_hz=self.oddball_spin.value(),
            sum_up_to_hz=self.sum_up_spin.value(),
            excluded_freqs_hz=excluded,
            palette_choice=self.palette_combo.currentText(),
            png_dpi=self.png_dpi_spin.value(),
            use_stable_ylims=self.use_stable_ylims_check.isChecked(),
            ylim_raw_sum_z=self._parse_ylim(self.ylim_raw_z_edit.text()),
            ylim_raw_sum_snr=self._parse_ylim(self.ylim_raw_snr_edit.text()),
            ylim_raw_sum_bca=self._parse_ylim(self.ylim_raw_bca_edit.text()),
            ylim_ratio_z=self._parse_ylim(self.ylim_ratio_z_edit.text()),
            ylim_ratio_snr=self._parse_ylim(self.ylim_ratio_snr_edit.text()),
            ylim_ratio_bca=self._parse_ylim(self.ylim_ratio_bca_edit.text()),
        )

    def _parse_excluded_freqs(self) -> set[float]:
        text = self.excluded_edit.text().strip()
        if not text:
            return set()
        freqs: set[float] = set()
        for part in text.split(","):
            part = part.strip()
            if not part:
                continue
            try:
                freqs.add(float(part))
            except ValueError:
                self._append_log(f"Invalid excluded frequency ignored: {part}")
        return freqs

    @staticmethod
    def _parse_ylim(text: str) -> Optional[tuple[float, float]]:
        raw = text.strip()
        if not raw:
            return None
        if raw.lower() == "auto":
            return None
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        if len(parts) != 2:
            return None
        try:
            low = float(parts[0])
            high = float(parts[1])
        except ValueError:
            return None
        return (low, high)

    def _ensure_output_dir(self, output_dir: str) -> tuple[bool, str | None]:
        if not output_dir:
            return False, "Select an output folder."
        out_path = Path(output_dir)
        try:
            out_path.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            return False, f"Unable to create output folder: {exc}"
        if not out_path.is_dir():
            return False, "Output folder path is not a directory."
        return True, None

    def _validate_inputs(self) -> list[str]:
        errors: list[str] = []
        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        output_dir = self.output_edit.text().strip()

        folder_a_valid = bool(input_a) and Path(input_a).is_dir()
        folder_b_valid = bool(input_b) and Path(input_b).is_dir()

        if not input_a:
            errors.append("Select a Condition A folder.")
        elif not folder_a_valid:
            errors.append("Condition A folder does not exist.")

        if not input_b:
            errors.append("Select a Condition B folder.")
        elif not folder_b_valid:
            errors.append("Condition B folder does not exist.")

        if folder_a_valid and folder_b_valid and Path(input_a).resolve() == Path(input_b).resolve():
            errors.append("Condition A and B folders must be different.")

        ok_out, out_err = self._ensure_output_dir(output_dir)
        if not ok_out and out_err:
            errors.append(out_err)

        folders_ready = folder_a_valid and folder_b_valid and Path(input_a).resolve() != Path(input_b).resolve()
        if folders_ready and not self._paired_participants:
            errors.append("Participants are not loaded.")

        if not self._active_roi_defs:
            errors.append("No valid ROIs are configured in Settings.")

        return errors

    def _set_validation_errors(self, errors: list[str]) -> None:
        if errors:
            self.validation_label.setText("\n".join(f"• {err}" for err in errors))
            self.validation_label.setVisible(True)
        else:
            self.validation_label.setText("")
            self.validation_label.setVisible(False)

