# -*- coding: utf-8 -*-
from __future__ import annotations
"""
Process-based per-file runner.

- Spawns one subprocess per EEG file (Windows-safe via "spawn").
- Caps BLAS to 1 thread per worker to avoid oversubscription.
- Uses the PySide6 loader + preprocessing backend (no direct Legacy deps).
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
from concurrent.futures import ProcessPoolExecutor, FIRST_COMPLETED, wait
from dataclasses import dataclass
from multiprocessing import Queue, get_context, Event
from pathlib import Path
from types import ModuleType, SimpleNamespace
from typing import Dict, List, Optional

from Main_App.PySide6_App.Backend import preprocess as backend_preprocess

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
    from pathlib import Path as _Path
    base = _Path(tempfile.gettempdir()) / "fpvs_memmap"
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


def _make_error_result(
    file_path: Path,
    stage: str,
    exc: Exception,
    start_time: Optional[float] = None,
) -> Dict[str, object]:
    """
    Build a structured error payload for a single-file run.
    """
    elapsed_ms: Optional[int] = None
    if start_time is not None:
        try:
            elapsed_ms = int((time.perf_counter() - start_time) * 1000)
        except Exception:
            elapsed_ms = None

    tb = traceback.format_exc()
    tb_lines = tb.strip().splitlines()
    traceback_head = "\n".join(tb_lines[:6])

    logger.error(
        "file_processing_error",
        extra={
            "file": str(file_path),
            "stage": stage,
            "error": str(exc),
            "elapsed_ms": elapsed_ms,
        },
    )

    payload: Dict[str, object] = {
        "status": "error",
        "file": str(file_path),
        "stage": stage,
        "error": str(exc),
        "trace": tb,
        "traceback_head": traceback_head,
    }
    if elapsed_ms is not None:
        payload["elapsed_ms"] = elapsed_ms
    return payload


def _run_full_pipeline_for_file(
    file_path: Path,
    settings: Dict[str, object],
    event_map: Dict[str, int],
    save_folder: Path,
) -> Dict[str, object]:
    """
    Canonical single-file pipeline using the PySide6 backend.

    Pipeline order (must not change):
      load → preproc audit (before) → preprocessing → events → epochs →
      post_export → preproc audit (after) → cleanup.
    """
    t0 = time.perf_counter()
    stage = "load"
    try:
        # Debug sentinel so we know this worker path is being used
        print(
            f"[SENTINEL] process_runner _run_full_pipeline_for_file running for "
            f"{file_path.name}"
        )

        # Lazy imports (inside worker only)
        from Main_App.PySide6_App.Backend.loader import load_eeg_file  # type: ignore
        from Main_App.PySide6_App.adapters.post_export_adapter import (  # type: ignore
            LegacyCtx,
            run_post_export,
        )
        import gc
        import mne  # type: ignore

        # Quiet noisy MNE INFO logs in worker processes (e.g., repeated
        # "Using data from preloaded Raw..." lines) while preserving
        # WARNING/ERROR messages.
        try:
            set_level = getattr(mne, "set_log_level", None)
            if callable(set_level):
                set_level("WARNING")
            else:
                from mne.utils import set_log_level as _set_log_level  # type: ignore
                _set_log_level("WARNING")
        except Exception:
            # If MNE changes its API, fail silently; core behavior is unaffected.
            pass

        # Minimal logger-compatible stub for loader
        class _App:
            def log(self, msg: str) -> None:  # pragma: no cover - informational
                logger.info(msg)

        # Resolve reference pair for loader so EXG policy keeps the right pair as EEG
        ref_ch1 = settings.get("ref_channel1") or settings.get("ref_ch1") or "EXG1"
        ref_ch2 = settings.get("ref_channel2") or settings.get("ref_ch2") or "EXG2"
        ref_pair = (str(ref_ch1), str(ref_ch2))

        # 1) Load
        stage = "load"
        raw = load_eeg_file(_App(), str(file_path), ref_pair=ref_pair)
        if raw is None:
            raise RuntimeError("load_eeg_file returned None")

        # 2) Preproc audit (before)
        stage = "preprocess"
        audit_before = backend_preprocess.begin_preproc_audit(
            raw,
            settings,
            file_path.name,
        )

        # 3) Preprocessing via PySide6 backend (handles:
        #    initial EXG ref -> drop EXGs -> channel limit keeping stim ->
        #    downsample -> filter -> kurtosis/interp -> final avg ref)
        raw_proc, n_rejected = backend_preprocess.perform_preprocessing(
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

        # 4) Events — prefer explicit stim channel (BioSemi 'Status')
        stage = "events"
        stim = (
            settings.get("stim_channel")
            or settings.get("stim")
            or "Status"
        )
        events_source = "stim"
        try:
            # Use the configured stim channel when available
            events = mne.find_events(
                raw_proc,
                stim_channel=stim,
                shortest_event=1,
            )  # type: ignore[arg-type]
        except Exception:
            # Fallback to annotations if present
            events, _ = mne.events_from_annotations(raw_proc)
            events_source = "annotations"

        # If there are no events at all, this is a true failure.
        if events.size == 0:
            raise RuntimeError(
                f"No events found for {file_path.name} (source='{events_source}', stim='{stim}')"
            )

        events_info = {
            "stim_channel": stim,
            "n_events": int(len(events)),
            "source": events_source,
        }

        # 5) Epochs per label/code (tolerant of missing runs)
        stage = "epochs"
        tmin = float(settings.get("epoch_start", -1.0))
        tmax = float(settings.get("epoch_end", 1.0))

        # Which event codes are actually present in this recording?
        have_codes = {int(c) for c in events[:, 2].tolist()}

        epochs_dict: Dict[str, List[object]] = {}
        total_epochs = 0

        for label, code in event_map.items():
            code_int = int(code)

            if code_int not in have_codes:
                # Participant simply never saw this condition/run.
                msg = (
                    f"[AUDIT WARNING] {file_path.name}: label='{label}' code={code_int} "
                    f"has 0 matching events; skipping epochs for this label."
                )
                logger.warning(msg)
                print(msg)
                epochs_dict[label] = []  # keep key present but with no runs
                continue

            # Create epochs for codes that are present; allow MNE to warn instead of raise.
            # Keep preload=False for memory reasons.
            epochs = mne.Epochs(
                raw_proc,
                events,
                event_id={label: code_int},
                tmin=tmin,
                tmax=tmax,
                preload=False,
                baseline=None,
                decim=1,
                verbose=False,
                on_missing="warn",
            )

            # MNE requires that bad epochs be dropped (or preload=True) before len(epochs)
            # is called when preload=False. We do not change any reject/flat configuration
            # here; drop_bad() will simply apply any existing thresholds and mark that
            # the bad-epoch decision has been made.
            epochs.drop_bad()

            # For audit: how many raw events had this code, and how many epochs remain.
            n_events_for_code = int((events[:, 2] == code_int).sum())
            n_ep = len(epochs)

            logger.info(
                "[AUDIT DEBUG] %s: label='%s' code=%s events_for_code=%d "
                "epochs_after_drop_bad=%d",
                file_path.name,
                label,
                code_int,
                n_events_for_code,
                n_ep,
            )

            if n_ep == 0:
                # Code exists in the event array but epoch window / rejection yielded no data.
                msg = (
                    f"[AUDIT WARNING] {file_path.name}: label='{label}' code={code_int} "
                    f"produced 0 epochs after epoching; skipping this label."
                )
                logger.warning(msg)
                print(msg)
                epochs_dict[label] = []
                continue

            epochs_dict[label] = [epochs]
            total_epochs += n_ep

        # If no epochs at all were created for any label, this is a real failure
        if total_epochs == 0:
            raise RuntimeError(
                f"No epochs created for any configured labels in {file_path.name}. "
                f"Check event_map, epoch window (tmin={tmin}, tmax={tmax}), and triggers."
            )

        # 6) Post-export (delegates to Legacy post_process via adapter)
        stage = "export"
        ctx = LegacyCtx(
            preprocessed_data=epochs_dict,
            save_folder_path=SimpleNamespace(get=lambda: str(save_folder)),
            data_paths=[str(file_path)],
            settings=settings,
            log=logger.info,
        )
        fif_written = run_post_export(ctx, list(event_map.keys()))

        # 7) Preproc audit (after)
        stage = "audit"
        audit_after, problems = backend_preprocess.finalize_preproc_audit(
            audit_before,
            raw_proc,
            settings,
            file_path.name,
            events_info=events_info,
            fif_written=fif_written,
            n_rejected=n_rejected,
        )

        # Developer-only audit debug: summarize final preprocessing state when a
        # reference pair was requested in the settings. Uses the new audit payload
        # schema from backend_preprocess.finalize_preproc_audit.
        ref_expected = [
            ch
            for ch in (
                settings.get("ref_channel1"),
                settings.get("ref_channel2"),
            )
            if ch
        ]

        if ref_expected:
            fields = {
                "ref_expected": tuple(ref_expected),
                "ref_chans": audit_after.get("ref_chans"),
                "sfreq": audit_after.get("sfreq"),
                "lowpass": audit_after.get("lowpass"),
                "highpass": audit_after.get("highpass"),
                "n_channels": audit_after.get("n_channels"),
                "stim": audit_after.get("stim_channel"),
                "n_events": audit_after.get("n_events"),
                "n_rejected": audit_after.get("n_rejected"),
                "fif_written": audit_after.get("fif_written"),
            }

            parts = [f"file={file_path.name}"]
            parts.extend(
                f"{key}={value}"
                for key, value in fields.items()
                if value is not None
            )
            if problems:
                parts.append(f"problems={problems}")

            print("[AUDIT DEBUG] " + " ".join(parts))

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
        return {
            "status": "ok",
            "file": str(file_path),
            "stage": "done",
            "elapsed_ms": elapsed_ms,
            "audit": audit_after,
            "problems": problems,
            "events_info": events_info,
            "post_export_ok": bool(fif_written),
        }
    except Exception as e:  # pragma: no cover - worker error path
        return _make_error_result(
            file_path=file_path,
            stage=stage,
            exc=e,
            start_time=t0,
        )



def _process_one_file(
    file_path: Path,
    settings: Dict[str, object],
    event_map: Dict[str, int],
    save_folder: Path,
) -> Dict[str, object]:
    """
    Execute the processing steps for a single file using the PySide6 backend.

    This is the worker entry point used by multiprocessing. It delegates to
    _run_full_pipeline_for_file so the same pipeline can be reused by other callers.
    """
    return _run_full_pipeline_for_file(file_path, settings, event_map, save_folder)


def _memory_ok(limit_ratio: Optional[float]) -> bool:
    """Return True if system memory usage is below the soft cap."""
    if limit_ratio is None:
        return True
    vm = psutil.virtual_memory()
    return (vm.percent / 100.0) < float(limit_ratio)


def _scavenge_stale_memmaps() -> None:
    """Remove memmap PID folders for processes that are no longer alive."""
    try:
        from pathlib import Path as _Path
        import psutil as _psutil
        base = _Path(tempfile.gettempdir()) / "fpvs_memmap"
        if not base.exists():
            return
        for d in base.glob("pid_*"):
            try:
                pid = int(d.name.split("_", 1)[1])
            except Exception:
                continue
            if not _psutil.pid_exists(pid):
                shutil.rmtree(d, ignore_errors=True)
        try:
            base.rmdir()  # remove root if empty
        except OSError:
            pass
    except Exception:
        pass


def run_project_parallel(
    params: RunParams,
    progress_queue: Optional[Queue] = None,
    cancel_event: Optional[Event] = None,
) -> None:
    """
    Submit one process per file and report progress via an optional Queue.

    Queue messages:
      - {"type":"progress","completed":int,"total":int,"result":{...}}
      - {"type":"done","count":int,"cancelled":bool, ...}
    """
    files = list(params.data_files)
    if not files:
        if progress_queue:
            progress_queue.put({"type": "done", "count": 0, "cancelled": False})
        return

    maxw = params.max_workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = get_context("spawn")

    completed = 0
    total = len(files)
    remaining = list(files)
    in_flight: Dict[object, Path] = {}

    # Batch-level stats for n_rejected (number of channels interpolated per file)
    total_rejected = 0
    files_with_audit = 0

    cancelled = False

    def _cancelled() -> bool:
        nonlocal cancelled
        if cancel_event is not None and cancel_event.is_set():
            cancelled = True
        return cancelled

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
            if _cancelled():
                return False

            # Optional soft-cap on system RAM
            while not _memory_ok(getattr(params, "memory_soft_limit_ratio", None)):
                time.sleep(getattr(params, "memory_check_interval_s", 0.25))

            f = remaining.pop(0)
            fut = pool.submit(
                _process_one_file,
                f,
                params.settings,
                params.event_map,
                params.save_folder,
            )
            in_flight[fut] = f
            return True

        # Prime pool
        while len(in_flight) < maxw and remaining:
            if not _submit_next_available():
                break

        # Drain
        while in_flight or remaining:
            if not in_flight:
                if _cancelled():
                    break
                if not _submit_next_available():
                    # Nothing could be submitted (likely due to cancellation).
                    if _cancelled() or not remaining:
                        break
                    time.sleep(0.05)
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
                    res = {
                        "status": "error",
                        "file": str(f) if f else "unknown",
                        "error": str(exc),
                    }

                # Accumulate per-file rejected-channel counts when available
                if isinstance(res, dict) and res.get("status") == "ok":
                    audit = res.get("audit") or {}
                    if isinstance(audit, dict):
                        n_rejected = audit.get("n_rejected")
                        if isinstance(n_rejected, (int, float)):
                            total_rejected += int(n_rejected)
                            files_with_audit += 1

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

            if _cancelled():
                if in_flight or remaining:
                    for fut in list(in_flight.keys()):
                        if not fut.done():
                            fut.cancel()
                break

            _submit_next_available()

    # Final cleanup: remove any stale memmaps in the %TEMP% folder from previous runs
    _scavenge_stale_memmaps()

    # Batch-level summary: average number of channels rejected per file.
    avg_rejected: Optional[float] = None
    if files_with_audit:
        avg_rejected = total_rejected / files_with_audit
        logger.info(
            "batch_summary average_rejected_channels_per_file=%.2f "
            "files_with_audit=%d total_rejected=%d",
            avg_rejected,
            files_with_audit,
            total_rejected,
        )

    if progress_queue:
        done_msg: Dict[str, object] = {
            "type": "done",
            "count": completed,
        }
        if cancelled:
            done_msg["cancelled"] = True
        else:
            done_msg["cancelled"] = False

        if avg_rejected is not None:
            done_msg.update(
                {
                    "avg_rejected": avg_rejected,
                    "total_rejected": total_rejected,
                    "files_with_audit": files_with_audit,
                }
            )
        progress_queue.put(done_msg)

