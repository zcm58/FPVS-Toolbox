"""ROI table and Settings refresh helpers for the Ratio Calculator GUI."""

from __future__ import annotations

import logging
from time import perf_counter

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTableWidgetItem

logger = logging.getLogger(__name__)


class RatioRoisMixin:
    """GUI-only ROI loading, table population, and refresh behavior."""

    def _rois_signature(self, rois: dict[str, list[str]]) -> tuple[tuple[str, tuple[str, ...]], ...]:
        return tuple((name, tuple(channels)) for name, channels in rois.items())

    def _refresh_rois(self) -> None:
        started = perf_counter()
        try:
            rois = self._roi_loader()
        except Exception as exc:
            elapsed_ms = int((perf_counter() - started) * 1000)
            logger.exception(
                "operation=refresh_rois project_root=%s elapsed_ms=%d error=%s",
                self._project_root,
                elapsed_ms,
                exc,
            )
            rois = {}

        self._active_roi_defs = rois
        self._roi_settings_signature = self._rois_signature(rois)
        self._populate_roi_table(rois)
        if not rois:
            self._set_status_message("No valid ROIs found in Settings. Update Settings or click Refresh.")
        self._update_run_state()

    def _sync_rois_if_changed(self) -> None:
        try:
            rois = self._roi_loader()
        except Exception as exc:
            logger.exception(
                "operation=sync_rois_if_changed project_root=%s error=%s",
                self._project_root,
                exc,
            )
            return
        new_signature = self._rois_signature(rois)
        if new_signature == self._roi_settings_signature:
            return
        self._active_roi_defs = rois
        self._roi_settings_signature = new_signature
        self._populate_roi_table(rois)
        self._append_log("ROI settings changed. Table refreshed from Settings.")
        self._update_run_state()

    def _populate_roi_table(self, rois: dict[str, list[str]]) -> None:
        self.roi_table.setRowCount(len(rois))
        for row, (roi, electrodes) in enumerate(rois.items()):
            roi_item = QTableWidgetItem(roi)
            roi_item.setFlags(roi_item.flags() & ~Qt.ItemIsEditable)
            electrodes_text = ", ".join(electrodes)
            elec_item = QTableWidgetItem(electrodes_text)
            elec_item.setToolTip(electrodes_text)
            elec_item.setFlags(elec_item.flags() & ~Qt.ItemIsEditable)
            self.roi_table.setItem(row, 0, roi_item)
            self.roi_table.setItem(row, 1, elec_item)

