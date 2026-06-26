from __future__ import annotations

from typing import Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from Main_App.processing.removed_electrode_detection import (
    normalize_manual_removed_electrodes_map,
    parse_electrode_list,
)


class ManualRemovedElectrodesDialog(QDialog):
    """Modal editor for participant-level manually removed electrode metadata."""

    def __init__(
        self,
        participant_ids: Sequence[str],
        manual_removed_electrodes: Mapping[str, Sequence[str]] | None = None,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Manual Removed Electrodes")
        self.setObjectName("manual_removed_electrodes_dialog")
        self.resize(620, 420)

        normalized = normalize_manual_removed_electrodes_map(
            dict(manual_removed_electrodes or {})
        )
        pids = _ordered_participant_ids(participant_ids, normalized)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        prompt = QLabel(
            "Enter electrodes that were physically removed before recording.",
            self,
        )
        prompt.setWordWrap(True)
        layout.addWidget(prompt)

        self.table = QTableWidget(len(pids), 2, self)
        self.table.setObjectName("manual_removed_electrodes_table")
        self.table.setHorizontalHeaderLabels(["PID", "Removed electrodes"])
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(
            0,
            QHeaderView.ResizeToContents,
        )
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        for row, pid in enumerate(pids):
            pid_item = QTableWidgetItem(pid)
            pid_item.setFlags(pid_item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, 0, pid_item)
            electrodes = normalized.get(pid) or _casefold_lookup(normalized, pid)
            self.table.setItem(row, 1, QTableWidgetItem(", ".join(electrodes)))

        layout.addWidget(self.table, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.Save | QDialogButtonBox.Cancel,
            parent=self,
        )
        buttons.setObjectName("manual_removed_electrodes_actions")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def manual_removed_electrodes(self) -> dict[str, list[str]]:
        """Return all PID entries from the editable table."""
        values: dict[str, list[str]] = {}
        for row in range(self.table.rowCount()):
            pid_item = self.table.item(row, 0)
            electrodes_item = self.table.item(row, 1)
            pid = pid_item.text().strip() if pid_item else ""
            if not pid:
                continue
            electrodes = parse_electrode_list(
                electrodes_item.text() if electrodes_item else ""
            )
            values[pid] = electrodes
        return values


def _casefold_lookup(
    values: Mapping[str, Sequence[str]],
    key: str,
) -> list[str]:
    key_folded = key.casefold()
    for candidate, electrodes in values.items():
        if candidate.casefold() == key_folded:
            return list(electrodes)
    return []


def _ordered_participant_ids(
    participant_ids: Sequence[str],
    manual_removed_electrodes: Mapping[str, Sequence[str]],
) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for source in (participant_ids, tuple(manual_removed_electrodes)):
        for raw_pid in source:
            pid = str(raw_pid or "").strip()
            if not pid:
                continue
            key = pid.casefold()
            if key in seen:
                continue
            seen.add(key)
            ordered.append(pid)
    return sorted(ordered, key=_participant_sort_key)


def _participant_sort_key(value: str) -> tuple[str, int, str]:
    prefix = "".join(ch for ch in value if not ch.isdigit()).casefold()
    digits = "".join(ch for ch in value if ch.isdigit())
    number = int(digits) if digits else -1
    return prefix, number, value.casefold()


__all__ = ["ManualRemovedElectrodesDialog"]
