"""GUI-neutral lifecycle outcomes for publication scalp-map generation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from Tools.Publication_Maps.models import PublicationMapResult


class PublicationMapGenerationCancelled(RuntimeError):
    """Raised by cooperative checkpoints after a cancellation request."""


class PublicationMapsOutcomeStatus(str, Enum):
    """Terminal state reported by one worker batch."""

    SUCCESS = "success"
    CANCELLED = "cancelled"
    ERROR = "error"
    POST_PROCESSING_REQUIRED = "post_processing_required"


@dataclass(frozen=True)
class PublicationMapsWorkerOutcome:
    """One unambiguous terminal payload emitted for every worker batch."""

    status: PublicationMapsOutcomeStatus
    results: tuple[PublicationMapResult, ...] = ()
    message: str = ""
    project_root: str | None = None

    @classmethod
    def success(
        cls,
        results: tuple[PublicationMapResult, ...],
    ) -> PublicationMapsWorkerOutcome:
        return cls(status=PublicationMapsOutcomeStatus.SUCCESS, results=results)

    @classmethod
    def cancelled(cls) -> PublicationMapsWorkerOutcome:
        return cls(
            status=PublicationMapsOutcomeStatus.CANCELLED,
            message="Generation cancelled.",
        )

    @classmethod
    def error(cls, message: str) -> PublicationMapsWorkerOutcome:
        return cls(
            status=PublicationMapsOutcomeStatus.ERROR,
            message=str(message).strip() or "Scalp-map generation failed.",
        )

    @classmethod
    def post_processing_required(
        cls,
        *,
        reason: str,
        project_root: str | Path,
    ) -> PublicationMapsWorkerOutcome:
        return cls(
            status=PublicationMapsOutcomeStatus.POST_PROCESSING_REQUIRED,
            message=str(reason).strip(),
            project_root=str(Path(project_root).resolve(strict=False)),
        )


__all__ = (
    "PublicationMapGenerationCancelled",
    "PublicationMapsOutcomeStatus",
    "PublicationMapsWorkerOutcome",
)
