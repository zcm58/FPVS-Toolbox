""""Helper for running localization in a separate process."""

from __future__ import annotations

import traceback
from multiprocessing import Queue
from typing import Any, Tuple
import logging

from .logging_utils import QueueLogHandler


def run_localization_worker(
    fif_path: str,
    output_dir: str,
    *,
    queue: Queue,
    **kwargs: Any,
) -> Tuple[str, None]:
    """Run :func:`run_source_localization` in a separate process."""
    from .runner import run_source_localization

    def _log(msg: str) -> None:
        queue.put({"type": "log", "message": msg})

    def _progress(val: float) -> None:
        queue.put({"type": "progress", "value": val})

    handler = QueueLogHandler(queue)
    pkg_logger = logging.getLogger("Tools.SourceLocalization")
    pkg_logger.addHandler(handler)

    try:
        path, brain = run_source_localization(
            fif_path,
            output_dir,
            log_func=_log,
            progress_cb=_progress,
            show_brain=False,
            **kwargs,
        )
        queue.put({"type": "done", "stc_path": path})
        return path, brain
    except Exception as err:
        queue.put({"type": "error", "message": str(err), "trace": traceback.format_exc()})
        raise
    finally:
        pkg_logger.removeHandler(handler)
