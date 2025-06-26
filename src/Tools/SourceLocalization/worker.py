"""Helper for running localization in a separate process."""

from __future__ import annotations

from multiprocessing import Queue
from typing import Any
import logging

from .logging_utils import QueueLogHandler


def run_localization_worker(
    fif_path: str,
    output_dir: str,
    *,
    queue: Queue,
    **kwargs: Any,
) -> tuple[str, None]:
    """Run :func:`run_source_localization` in a separate process.

    Additional keyword arguments such as ``time_window`` (specified in
    milliseconds) are forwarded to :func:`run_source_localization`.
    """

    from .runner import run_source_localization

    def _log(msg: str) -> None:
        queue.put({"type": "log", "message": msg})

    def _progress(val: float) -> None:
        queue.put({"type": "progress", "value": val})

    handler = QueueLogHandler(queue)
    pkg_logger = logging.getLogger("Tools.SourceLocalization")
    pkg_logger.addHandler(handler)

    try:
        return run_source_localization(
            fif_path,
            output_dir,
            log_func=_log,
            progress_cb=_progress,
            show_brain=False,
            **kwargs,
        )
    finally:
        pkg_logger.removeHandler(handler)

__all__ = ["run_localization_worker"]

