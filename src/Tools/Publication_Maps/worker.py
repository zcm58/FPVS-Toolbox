"""Qt worker for publication scalp-map generation."""

from __future__ import annotations

import logging
import threading
from collections.abc import Sequence
from dataclasses import replace

from PySide6.QtCore import QObject, Signal, Slot

from Tools.Publication_Maps.generation_outcome import (
    PublicationMapGenerationCancelled,
    PublicationMapsWorkerOutcome,
)
from Tools.Publication_Maps.metrics import (
    build_publication_map_result,
    verify_publication_workbooks_unchanged,
)
from Tools.Publication_Maps.models import (
    PublicationMapInputError,
    PublicationMapRequest,
    PublicationMapResult,
)
from Tools.Publication_Maps.output_contract import (
    PublicationArtifactTransaction,
    request_output_root,
)
from Tools.Publication_Maps.rendering import (
    render_group_comparison_figures,
    render_publication_figures,
    validate_group_comparison_project_groups,
    validate_group_comparison_requests,
)
from Tools.Stats.analysis.canonical_harmonics import (
    CanonicalHarmonicSelectionError,
)

logger = logging.getLogger(__name__)


class PublicationMapsWorker(QObject):
    """Build and atomically publish one or more group-scoped map requests."""

    progress = Signal(int)
    message = Signal(str)
    # Retained as a compatibility signal; every terminal state is now carried
    # by the single typed ``finished`` outcome instead of split signal paths.
    error = Signal(str)
    finished = Signal(object)

    def __init__(
        self,
        requests: PublicationMapRequest | Sequence[PublicationMapRequest],
    ) -> None:
        super().__init__()
        if isinstance(requests, PublicationMapRequest):
            normalized = (requests,)
        else:
            normalized = tuple(requests)
        if not normalized:
            raise ValueError("Scalp Maps requires at least one generation request.")
        baseline = replace(
            normalized[0],
            group_id=None,
            group_label=None,
            group_folder=None,
        )
        if any(
            replace(
                request,
                group_id=None,
                group_label=None,
                group_folder=None,
            )
            != baseline
            for request in normalized[1:]
        ):
            raise ValueError(
                "A Scalp Maps worker batch may differ only by canonical group."
            )
        group_ids = [
            str(request.group_id).casefold()
            for request in normalized
            if request.group_id is not None
        ]
        if len(normalized) > 1 and (
            len(group_ids) != len(normalized) or len(set(group_ids)) != len(group_ids)
        ):
            raise ValueError(
                "Multi-request Scalp Maps batches require unique canonical group IDs."
            )
        output_targets = [
            str(request_output_root(request).resolve(strict=False)).casefold()
            for request in normalized
        ]
        if len(set(output_targets)) != len(output_targets):
            raise ValueError(
                "Scalp Maps group requests require unique output directories."
            )
        self._group_comparison_enabled = validate_group_comparison_requests(normalized)
        self.requests = normalized
        self.request = normalized[0]
        self.outcome: PublicationMapsWorkerOutcome | None = None
        self._cancel_requested = threading.Event()

    @Slot()
    def run(self) -> None:
        outcome: PublicationMapsWorkerOutcome
        results: list[PublicationMapResult] = []
        batch_figure_paths = ()
        try:
            self._cancellation_checkpoint()
            if self._group_comparison_enabled:
                validate_group_comparison_project_groups(self.requests)
                self._cancellation_checkpoint()
            with PublicationArtifactTransaction(self.request) as transaction:
                for index, request in enumerate(self.requests):
                    self._cancellation_checkpoint()
                    transaction.ensure_request_target(request)
                    group_label = request.group_label or "Ungrouped dataset"
                    self._emit_phase_progress(index, 5)
                    self.message.emit(f"[{group_label}] Reading indexed workbooks...")
                    result = build_publication_map_result(
                        request,
                        cancel_check=self._cancellation_checkpoint,
                    )
                    self._cancellation_checkpoint()

                    if self._group_comparison_enabled:
                        results.append(result)
                        self._emit_phase_progress(index, 70)
                        self.message.emit(
                            f"[{group_label}] Comparison data staged in memory."
                        )
                        continue

                    self._emit_phase_progress(index, 55)
                    self.message.emit(f"[{group_label}] Rendering scalp maps...")
                    figure_paths = render_publication_figures(
                        result,
                        request,
                        cancel_check=self._cancellation_checkpoint,
                        transaction=transaction,
                    )
                    self._cancellation_checkpoint()
                    if not figure_paths:
                        raise PublicationMapInputError(
                            f"No renderable scalp-map figures were produced for "
                            f"{group_label}."
                        )

                    results.append(result)
                    self._emit_phase_progress(index, 95)
                    self.message.emit(f"[{group_label}] Figure output staged.")

                if self._group_comparison_enabled:
                    self._cancellation_checkpoint()
                    self.progress.emit(90)
                    self.message.emit(
                        "Rendering descriptive side-by-side group figure..."
                    )
                    batch_figure_paths = tuple(
                        render_group_comparison_figures(
                            tuple(results),
                            self.requests,
                            cancel_check=self._cancellation_checkpoint,
                            transaction=transaction,
                            _project_groups_validated=True,
                        )
                    )
                    if not batch_figure_paths:
                        raise PublicationMapInputError(
                            "No two-group comparison figures were produced."
                        )
                    self._cancellation_checkpoint()
                    self.progress.emit(96)
                    self.message.emit("Comparison figure output staged.")

                for result, request in zip(results, self.requests, strict=True):
                    verify_publication_workbooks_unchanged(
                        result.included_workbooks,
                        cancel_check=self._cancellation_checkpoint,
                    )
                self.message.emit("Publishing the complete Scalp Maps figure set...")
                transaction.commit(cancel_check=self._cancellation_checkpoint)

            self.progress.emit(100)
            outcome = PublicationMapsWorkerOutcome.success(
                tuple(results),
                batch_figure_paths=batch_figure_paths,
            )
        except PublicationMapGenerationCancelled:
            logger.info(
                "Scalp Maps generation cancelled before atomic publication.",
                extra={
                    "operation": "publication_maps_generate",
                    "input_root": str(self.request.input_root),
                    "output_root": str(self.request.output_root),
                    "group_count": len(self.requests),
                },
            )
            outcome = PublicationMapsWorkerOutcome.cancelled()
        except CanonicalHarmonicSelectionError as exc:
            project_root = self.request.project_root
            if project_root is None:
                outcome = PublicationMapsWorkerOutcome.error(str(exc))
            else:
                logger.warning(
                    "Scalp Maps requires refreshed project post-processing.",
                    extra={
                        "operation": "publication_maps_post_processing_required",
                        "project_root": str(project_root),
                    },
                )
                outcome = PublicationMapsWorkerOutcome.post_processing_required(
                    reason=str(exc),
                    project_root=project_root,
                )
        except Exception as exc:
            logger.exception(
                "publication_maps_worker_failed",
                extra={
                    "input_root": str(self.request.input_root),
                    "output_root": str(self.request.output_root),
                    "group_count": len(self.requests),
                },
            )
            outcome = PublicationMapsWorkerOutcome.error(str(exc))

        self.outcome = outcome
        self.finished.emit(outcome)

    @Slot()
    def cancel(self) -> None:
        self._cancel_requested.set()

    def _cancellation_checkpoint(self) -> None:
        if self._cancel_requested.is_set():
            raise PublicationMapGenerationCancelled("Generation cancelled.")

    def _emit_phase_progress(self, request_index: int, phase_percent: int) -> None:
        total = len(self.requests)
        overall = ((request_index * 100) + phase_percent) / total
        self.progress.emit(max(0, min(99, round(overall))))


__all__ = (
    "PublicationMapsWorker",
    "PublicationMapResult",
    "PublicationMapsWorkerOutcome",
)
