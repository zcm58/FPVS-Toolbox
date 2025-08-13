# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Process-based per-file runner.

- Spawns one subprocess per EEG file (Windows-safe via "spawn").
- Caps BLAS to 1 thread per worker to avoid oversubscription.
- Extracts events using the project's stim channel (e.g., "Status").
- Suppresses any legacy tkinter.messagebox calls inside workers.
- Calls the existing post-export adapter (no Legacy edits).
- Adds RAM-aware backpressure: staged submissions + system memory soft-cap.
"""

import logging
import atexit
import shutil
import tempfile
import os
import time
import traceback
import tempfile
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from dataclasses import dataclass
from multiprocessing import Queue, get_context
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Dict, List, Optional

import psutil  # soft memory cap
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
    # RAM backpressure (ratio of total system memory). None disables throttling.
    memory_soft_limit_ratio: Optional[float] = 0.85
    # How often to re-check memory when throttled
    memory_check_interval_s: float = 0.25


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

    # --- Memmap cleanup on worker exit ---
    from pathlib import Path
    base = Path(tempfile.gettempdir()) / "fpvs_memmap"
    pid_dir = base / f"pid_{os.getpid()}"
    pid_dir.mkdir(parents=True, exist_ok=True)

    def _cleanup_pid_dir() -> None:
        try:
            shutil.rmtree(pid_dir, ignore_errors=True)  # remove memmaps for this worker
        except Exception:
            pass

    atexit.register(_cleanup_pid_dir)


def _memmap_path_for_file(file_path: Path) -> Path:
    """Mirror the loader's deterministic per-PID memmap path for cleanup."""
    pid_dir = Path(tempfile.gettempdir()) / "fpvs_memmap" / f"pid_{os.getpid()}"
    pid_dir.mkdir(parents=True, exist_ok=True)
    return pid_dir / (file_path.stem + "_raw.dat")


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
        import gc

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

        # Free loader Raw ASAP
        del raw
        gc.collect()

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
                preload=False,
                baseline=None,
                decim=1,
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

        # Done with Raw/Epochs
        del raw_proc, epochs_dict
        gc.collect()

        # Attempt memmap cleanup for this file (safe if still open -> ignore)
        try:
            p = _memmap_path_for_file(file_path)
            if p.exists():
                p.unlink(missing_ok=True)  # type: ignore[arg-type]
            pid_dir = p.parent
            try:
                pid_dir.rmdir()  # remove if empty
            except OSError:
                pass
        except Exception:
            pass

        elapsed_ms = int((time.perf_counter() - t0) * 1000)
        return {"status": "ok", "file": str(file_path), "elapsed_ms": elapsed_ms}

    except Exception as e:  # pragma: no cover - worker error path
        return {
            "status": "error",
            "file": str(file_path),
            "error": f"{e}",
            "trace": traceback.format_exc(),
        }


def _memory_ok(limit_ratio: Optional[float]) -> bool:
    """Return True if system memory usage is below the soft cap."""
    if limit_ratio is None:
        return True
    vm = psutil.virtual_memory()
    return (vm.percent / 100.0) < float(limit_ratio)

def _scavenge_stale_memmaps() -> None:
    """Remove memmap PID folders for processes that are no longer alive."""
    try:
        from pathlib import Path
        import psutil
        base = Path(tempfile.gettempdir()) / "fpvs_memmap"
        if not base.exists():
            return
        for d in base.glob("pid_*"):
            try:
                pid = int(d.name.split("_", 1)[1])
            except Exception:
                continue
            if not psutil.pid_exists(pid):
                shutil.rmtree(d, ignore_errors=True)
        try:
            base.rmdir()  # remove root if empty
        except OSError:
            pass
    except Exception:
        pass


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

    completed = 0
    total = len(files)
    remaining = list(files)
    in_flight: dict = {}

    with ProcessPoolExecutor(
        max_workers=maxw,
        mp_context=ctx,
        initializer=_worker_init,
    ) as pool:

        def _submit_next_available() -> bool:
            """Submit one file if capacity and (if enabled) memory is OK."""
            nonlocal remaining
            if not remaining or len(in_flight) >= maxw:
                return False
            # Optional soft-cap on system RAM
            while not _memory_ok(getattr(params, "memory_soft_limit_ratio", None)):
                time.sleep(getattr(params, "memory_check_interval_s", 0.25))
            f = remaining.pop(0)
            fut = pool.submit(_process_one_file, f, params.settings, params.event_map, params.save_folder)
            in_flight[fut] = f
            return True

        # Prime pool
        while len(in_flight) < maxw and remaining:
            if not _submit_next_available():
                break

        # Drain
        while in_flight or remaining:
            if not in_flight and remaining:
                _submit_next_available()
                continue

            done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED, timeout=0.5)
            if not done:
                _submit_next_available()
                continue

            for fut in done:
                f = in_flight.pop(fut, None)
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {"status": "error", "file": str(f) if f else "unknown", "error": str(exc)}
                completed += 1
                if progress_queue:
                    progress_queue.put(
                        {"type": "progress", "completed": completed, "total": total, "result": res}
                    )

                _submit_next_available()

    # Final cleanup: remove any stale memmaps in the %TEMP% folder from previous runs
    _scavenge_stale_memmaps()

    if progress_queue:
        progress_queue.put({"type": "done", "count": completed})

        def _submit_next_available() -> bool:
            """Submit one file if below memory cap and capacity; return True if submitted."""
            nonlocal remaining
            if not remaining:
                return False
            if len(in_flight) >= maxw:
                return False
            # Soft-cap throttle: wait until memory OK
            while not _memory_ok(params.memory_soft_limit_ratio):
                time.sleep(params.memory_check_interval_s)
            f = remaining.pop(0)
            fut = pool.submit(_process_one_file, f, params.settings, params.event_map, params.save_folder)
            in_flight[fut] = f
            return True

        # Prime the pool
        while len(in_flight) < maxw and remaining:
            if not _submit_next_available():
                break

        while in_flight or remaining:
            if not in_flight and remaining:
                # No tasks running but some remaining: try to submit again (memory might have freed)
                _submit_next_available()
                continue

            done, _ = wait(in_flight.keys(), return_when=FIRST_COMPLETED, timeout=0.5)
            if not done:
                # Periodically try to top up submissions if memory allows
                _submit_next_available()
                continue

            for fut in done:
                f = in_flight.pop(fut, None)
                try:
                    res = fut.result()
                except Exception as exc:
                    res = {"status": "error", "file": str(f) if f else "unknown", "error": str(exc)}
                completed += 1
                if progress_queue:
                    progress_queue.put(
                        {"type": "progress", "completed": completed, "total": total, "result": res}
                    )
                # Try to submit another task after each completion
                _submit_next_available()

        if progress_queue:
            progress_queue.put({"type": "done", "count": completed})
