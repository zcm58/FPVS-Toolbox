"""Participant pairing and manual exclusion helpers for the Ratio Calculator GUI."""

from __future__ import annotations

import re
from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt
from PySide6.QtWidgets import QMessageBox, QTableWidgetItem

from Main_App.gui.components import confirm, show_info

from .utils import parse_participant_id

PID_PATTERN = re.compile(r"^P\d+$", re.IGNORECASE)


class RatioParticipantsMixin:
    """GUI-only participant pairing, filtering, and exclusion behavior."""

    def _load_participants(self, silent: bool = False) -> bool:
        if self._loading_participants:
            return False
        self._loading_participants = True
        try:
            self._clear_participants()
            input_a = self.input_a_edit.text().strip()
            input_b = self.input_b_edit.text().strip()
            if not input_a or not input_b:
                if not silent:
                    self._set_status_message("Select both condition folders to load participants.")
                return False
            if not Path(input_a).is_dir() or not Path(input_b).is_dir():
                if not silent:
                    self._set_status_message("Select valid condition folders to load participants.")
                return False

            try:
                map_a = self._index_folder(Path(input_a))
                map_b = self._index_folder(Path(input_b))
            except Exception as exc:
                message = f"Unable to load participants: {exc}"
                if not silent:
                    self._set_status_message(message)
                else:
                    self._append_log(message)
                return False

            pids_a = sorted(map_a.keys())
            pids_b = sorted(map_b.keys())
            paired = sorted(set(pids_a).intersection(set(pids_b)))
            self._paired_participants = paired
            self._update_participant_counts(len(pids_a), len(pids_b), len(paired))

            if not paired:
                message = "No paired participants found between the folders."
                if not silent:
                    self._set_status_message(message)
                else:
                    self._append_log(message)
                self._update_exclusion_status()
                return False

            with QSignalBlocker(self.exclude_table):
                self.exclude_table.setRowCount(len(paired))
                for row, pid in enumerate(paired):
                    exclude_item = QTableWidgetItem()
                    exclude_item.setFlags(Qt.ItemIsEnabled | Qt.ItemIsUserCheckable)
                    exclude_item.setCheckState(Qt.Unchecked)
                    exclude_item.setTextAlignment(Qt.AlignCenter)
                    pid_item = QTableWidgetItem(pid)
                    pid_item.setFlags(Qt.ItemIsEnabled)
                    self.exclude_table.setItem(row, 0, exclude_item)
                    self.exclude_table.setItem(row, 1, pid_item)

            self._apply_participant_filter()
            self._update_exclusion_status()
            self._update_run_state()
            if not (self._thread and self._thread.isRunning()):
                self.status_label.set_text("Ready")
            return True
        finally:
            self._loading_participants = False

    def _index_folder(self, folder: Path) -> dict[str, Path]:
        if not folder.exists():
            raise ValueError(f"Folder not found: {folder}")
        mapping: dict[str, Path] = {}
        for file_path in sorted(folder.glob("*.xlsx")):
            if file_path.name.startswith("~$"):
                continue
            pid, _ = parse_participant_id(file_path.name)
            mapping[pid] = file_path
        return mapping

    def _set_all_exclusions(self, checked: bool) -> None:
        with QSignalBlocker(self.exclude_table):
            for row in range(self.exclude_table.rowCount()):
                if self.exclude_table.isRowHidden(row):
                    continue
                item = self.exclude_table.item(row, 0)
                if item is None:
                    continue
                item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
        self._update_exclusion_status()

    def _confirm_exclude_all(self) -> None:
        message = "Exclude all participants from group summaries? This will set Used = 0."
        if confirm(
            self,
            "Confirm exclusion",
            message,
            default=QMessageBox.No,
        ):
            self._set_all_exclusions(True)

    def _apply_participant_filter(self) -> None:
        query = self.participant_filter_edit.text().strip().lower()
        only_excluded = self.show_excluded_check.isChecked()
        for row in range(self.exclude_table.rowCount()):
            pid_item = self.exclude_table.item(row, 1)
            exclude_item = self.exclude_table.item(row, 0)
            if pid_item is None or exclude_item is None:
                continue
            text = pid_item.text().lower()
            matches_query = query in text
            matches_excluded = exclude_item.checkState() == Qt.Checked
            show = matches_query and (matches_excluded if only_excluded else True)
            self.exclude_table.setRowHidden(row, not show)

    def _collect_manual_exclusions(self) -> list[str]:
        manual_list: list[str] = []
        invalid: list[str] = []
        for row in range(self.exclude_table.rowCount()):
            exclude_item = self.exclude_table.item(row, 0)
            pid_item = self.exclude_table.item(row, 1)
            if exclude_item is None or pid_item is None:
                continue
            if exclude_item.checkState() == Qt.Checked:
                pid = pid_item.text().strip()
                if PID_PATTERN.match(pid):
                    manual_list.append(pid)
                else:
                    invalid.append(pid)
        if invalid:
            self._append_log(f"Invalid manual exclusions ignored: {invalid}")
            show_info(
                self,
                "Invalid exclusions",
                f"Ignored invalid manual exclusion entries: {', '.join(invalid)}",
            )
        return manual_list

    def _update_exclusion_status(self) -> None:
        paired_count = len(self._paired_participants)
        excluded_count = sum(
            1
            for row in range(self.exclude_table.rowCount())
            if self.exclude_table.item(row, 0)
            and self.exclude_table.item(row, 0).checkState() == Qt.Checked
        )
        used_count = max(paired_count - excluded_count, 0)
        self.exclusion_status.setText(
            f"Excluded: {excluded_count} / Paired: {paired_count} \u2192 Used: {used_count}"
        )
        if self.show_excluded_check.isChecked():
            self._apply_participant_filter()

    def _maybe_autoload_participants(self, force: bool = False) -> None:
        if force:
            self._paired_participants = []
        if self._paired_participants:
            return
        input_a = self.input_a_edit.text().strip()
        input_b = self.input_b_edit.text().strip()
        if not input_a or not input_b:
            self._clear_participants("Select both condition folders to load participants.")
            return
        if not Path(input_a).is_dir() or not Path(input_b).is_dir():
            self._clear_participants("Select valid condition folders to load participants.")
            return
        self._load_participants(silent=True)

    def _on_exclusion_item_changed(self, item: QTableWidgetItem) -> None:
        if item.column() != 0:
            return
        self._update_exclusion_status()

    def _update_participant_counts(self, count_a: int, count_b: int, count_paired: int) -> None:
        self.participant_counts.setText(f"A: {count_a} | B: {count_b} | Paired: {count_paired}")

    def _clear_participants(self, status_message: str | None = None) -> None:
        with QSignalBlocker(self.exclude_table):
            self.exclude_table.setRowCount(0)
        self._paired_participants = []
        self._update_participant_counts(0, 0, 0)
        self._update_exclusion_status()
        if status_message:
            self._set_status_message(status_message)

