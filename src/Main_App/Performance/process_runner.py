# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Process-based per-file runner.

- Spawns one subprocess per EEG file (Windows-safe via "spawn").
- Caps BLAS to 1 thread per worker to avoid oversubscription.
- Extracts events using the project's stim channel (e.g., "Status").
- Suppresses any legacy tkinter.messagebox calls inside workers.
- Calls the existing post-export adapter (no Legacy edits).
"""

import logging
import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import Queue, get_context
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Dict, List, Optional

from .mp_env import set_blas_threads_multiprocess

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RunParams:
    project_root: Path
    data_files: List[Path]
    settings: Dict[str, object]
    event_map: Dict[str, int]  # {label: code}
    save_folder: Path
    max_workers: Optional[int] = None


def _worker_init() -> None:
    """Configure per-process environment and stub GUI popups."""
    set_blas_threads_multiprocess()

    # Subprocesses must never show blocking dialogs (legacy may use tkinter.messagebox).
    import sys  # local to keep worker clean

    tk = ModuleType("tkinter")
    msg = ModuleType("tkinter.messagebox")

    def _noop(*_a, **_k) -> None:
        return None

    msg.showerror = _noop
    msg.showwarning = _noop
    msg.showinfo = _noop
    msg.askyesno = lambda *_a, **_k: False  # type: ignore[assignment]
    tk.messagebox = msg  # type: ignore[attr-defined]
    tk.END = "end"       # some legacy code references tkinter.END

    # Register stubs
    sys.modules.setdefault("tkinter", tk)
    sys.modules["tkinter.messagebox"] = msg


def _process_one_file(
    file_path: Path,
    settings: Dict[str, object],
    event_map: Dict[str, int],
    save_folder: Path,
) -> Dict[str, object]:
    """
    Execute the legacy processing steps for a single file.

    Returns a small dict with status/progress. Heavy data stays within the process.
    """
    try:
        t0 = time.perf_counter()

        # Lazy imports (inside worker only)
        from Main_App.Legacy_App.load_utils import load_eeg_file  # type: ignore
        from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing  # type: ignore
        from Main_App.PySide6_App.adapters.post_export_adapter import (  # type: ignore
            LegacyCtx,
            run_post_export,
        )
        import mne  # type: ignore

        # Minimal logger-compatible stub for legacy functions
        class _App:
            def log(self, msg: str) -> None:  # pragma: no cover - informational
                logger.info(msg)

        # 1) Load + preprocess (match legacy order)
        raw = load_eeg_file(_App(), str(file_path))
        if raw is None:
            raise RuntimeError("load_eeg_file returned None")

        raw_proc, _meta = perform_preprocessing(  # signatures per legacy module
            raw_input=raw,
            params=settings,
            log_func=logger.info,
            filename_for_log=file_path.name,
        )
        if raw_proc is None:
            raise RuntimeError("perform_preprocessing returned None")

        # 2) Events — prefer explicit stim channel (BioSemi 'Status')
        stim = (
            settings.get("stim_channel")
            or settings.get("stim")
            or "Status"
        )
        try:
            # Use the configured stim channel when available
            events = mne.find_events(raw_proc, stim_channel=stim, shortest_event=1)  # type: ignore[arg-type]
        except Exception:
            # Fallback to annotations if present
            events, _ = mne.events_from_annotations(raw_proc)

        # Clear message if requested event IDs aren’t present
        have_codes = set(int(c) for c in events[:, 2].tolist())
        missing = [int(code) for code in event_map.values() if int(code) not in have_codes]
        if missing:
            raise RuntimeError(
                f"Missing event codes {missing} in {file_path.name} (stim='{stim}')"
            )

        # 3) Epochs per label/code (match GUI epoch window when provided)
        tmin = float(settings.get("epoch_start", -1.0))
        tmax = float(settings.get("epoch_end", 1.0))
        epochs_dict: Dict[str, List[object]] = {}
        for label, code in event_map.items():
            epochs = mne.Epochs(
                raw_proc,
                events,
                event_id={label: code},
                tmin=tmin,
                tmax=tmax,
                preload=True,
                baseline=None,
                verbose=False,
            )
            epochs_dict[label] = [epochs]

        # 4) Post-export (delegates to Legacy post_process)
        ctx = LegacyCtx(
            preprocessed_data=epochs_dict,
            save_folder_path=SimpleNamespace(get=lambda: str(save_folder)),
            data_paths=[str(file_path)],
            settings=settings,
            log=logger.info,
        )
        run_post_export(ctx, list(event_map.keys()))

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {"status": "ok", "file": str(file_path), "elapsed_ms": elapsed_ms}

    except Exception as e:  # pragma: no cover - worker error path
        return {
            "status": "error",
            "file": str(file_path),
            "error": f"{e}",
            "trace": traceback.format_exc(),
        }


def run_project_parallel(params: RunParams, progress_queue: Optional[Queue] = None) -> None:
    """
    Submit one process per file and report progress via an optional Queue.

    Queue messages:
      - {"type":"progress","completed":int,"total":int,"result":{...}}
      - {"type":"done","count":int}
    """
    files = list(params.data_files)
    if not files:
        if progress_queue:
            progress_queue.put({"type": "done", "count": 0})
        return

    maxw = params.max_workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = get_context("spawn")

    with ProcessPoolExecutor(
        max_workers=maxw,
        mp_context=ctx,
        initializer=_worker_init,
    ) as pool:
        futures = {
            pool.submit(
                _process_one_file,
                f,
                params.settings,
                params.event_map,
                params.save_folder,
            ): f
            for f in files
        }

        completed = 0
        total = len(futures)
        for fut in as_completed(futures):
            res = fut.result()
            completed += 1
            if progress_queue:
                progress_queue.put(
                    {
                        "type": "progress",
                        "completed": completed,
                        "total": total,
                        "result": res,
                    }
                )

        if progress_queue:
            progress_queue.put({"type": "done", "count": completed})
