"""Persist accepted frequency-domain QC decisions without blocking the GUI."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import logging
from pathlib import Path

from PySide6.QtCore import QObject, Signal, Slot

logger = logging.getLogger(__name__)


class FrequencyDomainQcDecisionWorker(QObject):
    """Save the existing review contract and return metadata for the GUI to apply."""

    finished = Signal(dict)

    def __init__(
        self,
        project_root: str | Path,
        report: Mapping[str, object],
        *,
        review_decisions: Mapping[str, object] | Sequence[Mapping[str, object]],
        manual_participant_reasons: Mapping[str, str],
        manual_recording_reasons: Mapping[str, str],
    ) -> None:
        super().__init__()
        self._project_root = Path(project_root)
        self._report = report
        self._review_decisions = review_decisions
        self._manual_participant_reasons = manual_participant_reasons
        self._manual_recording_reasons = manual_recording_reasons

    @Slot()
    def run(self) -> None:
        result: dict[str, object] = {
            "success": False, "tools": None, "error": "", "stale_error": "",
        }
        try:
            from Main_App.processing.frequency_domain_qc import (
                apply_frequency_domain_qc_decision,
            )

            apply_frequency_domain_qc_decision(
                self._project_root,
                self._report,
                review_decisions=self._review_decisions,
                manual_participant_reasons=self._manual_participant_reasons,
                manual_recording_reasons=self._manual_recording_reasons,
            )
            manifest = json.loads(
                (self._project_root / "project.json").read_text(encoding="utf-8")
            )
            tools = manifest.get("tools") if isinstance(manifest, dict) else None
            if not isinstance(tools, dict):
                raise ValueError("Saved project tools metadata is unavailable.")
            result.update(success=True, tools=tools)
        except Exception as exc:  # noqa: BLE001 - always release the owning thread
            logger.exception("frequency_domain_qc_decision_apply_failed")
            detail = str(exc).strip() or type(exc).__name__
            result["error"] = f"Frequency-domain QC decisions could not be saved: {detail}"
            try:
                from Main_App.processing.frequency_domain_qc import (
                    mark_frequency_domain_outputs_stale,
                )

                mark_frequency_domain_outputs_stale(
                    self._project_root,
                    reason="Frequency-domain QC review failed before post-processing resumed.",
                )
            except Exception as stale_exc:  # noqa: BLE001 - preserve the original failure
                logger.exception("frequency_domain_qc_decision_stale_status_failed")
                detail = str(stale_exc).strip() or type(stale_exc).__name__
                result["stale_error"] = f"Downstream stale status could not be saved: {detail}"
        finally:
            self.finished.emit(result)


__all__ = ["FrequencyDomainQcDecisionWorker"]
