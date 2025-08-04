"""Processing mixin for the PySide6 averaging window."""

from __future__ import annotations

from typing import Any, Dict, Optional

from PySide6.QtWidgets import QMessageBox
import logging

logger = logging.getLogger(__name__)


class AdvancedAnalysisProcessingMixin:
    """Validate configuration and handle starting/stopping processing."""

    defined_groups: list[dict]
    btn_start: Any

    def _update_start_processing_button_state(self) -> None:
        """Enable the start button only if all groups are valid and saved."""

        enabled = bool(
            self.defined_groups
            and all(
                g.get("config_saved") and g.get("file_paths") and g.get("condition_mappings")
                for g in self.defined_groups
            )
        )
        self.btn_start.setEnabled(enabled)

    def _validate_processing_setup(self) -> Optional[tuple[Dict[str, Any], str]]:
        """Basic validation before processing starts."""

        if not self.defined_groups:
            QMessageBox.warning(self, "Error", "No averaging groups defined.")
            return None
        return {}, ""

    def start_advanced_processing(self) -> None:  # pragma: no cover - placeholder
        """Start the averaging process (placeholder implementation)."""

        if self._validate_processing_setup() is None:
            return
        QMessageBox.information(
            self,
            "Processing",
            "Processing would start here in the full application.",
        )
        self.log("Processing started (stub).")

    def stop_processing(self) -> None:  # pragma: no cover - placeholder
        """Stop the averaging process (placeholder)."""

        self.log("Stop requested (stub).")
