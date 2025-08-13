from __future__ import annotations

"""Run per-file preprocessing in worker processes."""

import os
import time
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from multiprocessing import Queue, get_context
from pathlib import Path
from types import SimpleNamespace
from typing import Dict, List, Optional

from .mp_env import set_blas_threads_multiprocess


@dataclass(frozen=True)
class RunParams:
    project_root: Path
    data_files: List[Path]
    settings: Dict[str, object]
    event_map: Dict[str, int]
    save_folder: Path
    max_workers: Optional[int] = None


def _worker_init() -> None:
    set_blas_threads_multiprocess()


def _process_one_file(
    file_path: Path, settings: Dict[str, object], event_map: Dict[str, int], save_folder: Path
) -> Dict[str, object]:
    try:
        t0 = time.perf_counter()
        from Main_App.Legacy_App.load_utils import load_eeg_file  # type: ignore
        from Main_App.Legacy_App.eeg_preprocessing import perform_preprocessing  # type: ignore
        from Main_App.PySide6_App.adapters.post_export_adapter import (
            LegacyCtx,
            run_post_export,
        )
        import mne  # type: ignore

        stub = SimpleNamespace(log=lambda _m: None)
        raw = load_eeg_file(stub, str(file_path))
        if raw is None:
            raise RuntimeError("load_eeg_file returned None")
        raw_proc, _ = perform_preprocessing(
            raw_input=raw,
            params=settings,
            log_func=lambda _m: None,
            filename_for_log=file_path.name,
        )
        if raw_proc is None:
            raise RuntimeError("perform_preprocessing returned None")
        try:
            events, _ = mne.events_from_annotations(raw_proc)
        except Exception:
            events = mne.find_events(raw_proc, shortest_event=1)
        epochs_dict: Dict[str, List[mne.Epochs]] = {}
        for label, code in event_map.items():
            epochs = mne.Epochs(
                raw_proc,
                events,
                event_id={label: code},
                preload=True,
                baseline=None,
            )
            epochs_dict[label] = [epochs]
        ctx = LegacyCtx(
            preprocessed_data=epochs_dict,
            save_folder_path=SimpleNamespace(get=lambda: str(save_folder)),
            data_paths=[str(file_path)],
            settings=settings,
            log=lambda _m: None,
        )
        run_post_export(ctx, list(event_map.keys()))
        elapsed = time.perf_counter() - t0
        return {"status": "ok", "file": str(file_path), "elapsed_ms": int(elapsed * 1000)}
    except Exception as e:
        return {
            "status": "error",
            "file": str(file_path),
            "error": f"{e}",
            "trace": traceback.format_exc(),
        }


def run_project_parallel(params: RunParams, progress_queue: Optional[Queue] = None) -> None:
    files = list(params.data_files)
    if not files:
        if progress_queue:
            progress_queue.put({"type": "done", "count": 0})
        return
    maxw = params.max_workers or max(1, (os.cpu_count() or 2) - 1)
    ctx = get_context("spawn")
    with ProcessPoolExecutor(
        max_workers=maxw, mp_context=ctx, initializer=_worker_init
    ) as pool:
        futs = {
            pool.submit(
                _process_one_file, f, params.settings, params.event_map, params.save_folder
            ): f
            for f in files
        }
        completed = 0
        for fut in as_completed(futs):
            res = fut.result()
            completed += 1
            if progress_queue:
                progress_queue.put(
                    {
                        "type": "progress",
                        "completed": completed,
                        "total": len(files),
                        "result": res,
                    }
                )
        if progress_queue:
            progress_queue.put({"type": "done", "count": completed})

