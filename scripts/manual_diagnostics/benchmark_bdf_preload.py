"""Compare disk and RAM BDF preloading with four real preprocessing workers.

This intentionally benchmarks loading and core preprocessing, without project
QC review, cache reuse, spectral exports, or workbook writing. It creates only
synthetic BioSemi64 recordings in a temporary directory.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ProcessPoolExecutor
import gc
import hashlib
import json
import os
from pathlib import Path
from statistics import median
import sys
import tempfile
from time import perf_counter, sleep

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from Main_App.io.eeg_geometry import BIOSEMI64_CHANNELS  # noqa: E402
from Main_App.io.load_utils import load_eeg_file  # noqa: E402
from Main_App.processing.preprocess import perform_preprocessing  # noqa: E402
from Main_App.Performance.mp_env import set_worker_thread_limits  # noqa: E402

SFREQ = 512
CHANNELS = (*BIOSEMI64_CHANNELS, "EXG1", "EXG2", "Status")


def _field(value: str, width: int) -> bytes:
    encoded = value.encode("ascii")
    if len(encoded) > width:
        raise ValueError(f"BDF header field too long: {value!r}")
    return encoded.ljust(width, b" ")


def _int24(values: np.ndarray) -> bytes:
    return np.asarray(values, dtype="<i4").view(np.uint8).reshape(-1, 4)[:, :3].tobytes()


def write_synthetic_bdf(path: Path, *, seconds: int, seed: int) -> None:
    """Write an uncompressed 24-bit BDF with 64 scalp, two refs, and Status."""
    n_channels = len(CHANNELS)
    with path.open("wb") as out:
        out.write(b"\xffBIOSEMI")
        out.write(_field("Synthetic", 80))
        out.write(_field("FPVS RAM benchmark", 80))
        out.write(_field("01.01.26", 8))
        out.write(_field("00.00.00", 8))
        out.write(_field(str(256 * (n_channels + 1)), 8))
        out.write(_field("24BIT", 44))
        out.write(_field(str(seconds), 8))
        out.write(_field("1", 8))
        out.write(_field(str(n_channels), 4))
        for width, values in (
            (16, CHANNELS),
            (80, ("" for _ in CHANNELS)),
            (8, ("uV" if name != "Status" else "" for name in CHANNELS)),
            (8, ("-262144" for _ in CHANNELS)),
            (8, ("262143" for _ in CHANNELS)),
            (8, ("-8388608" for _ in CHANNELS)),
            (8, ("8388607" for _ in CHANNELS)),
            (80, ("" for _ in CHANNELS)),
            (8, (str(SFREQ) for _ in CHANNELS)),
            (32, ("" for _ in CHANNELS)),
        ):
            for value in values:
                out.write(_field(value, width))

        sample = np.arange(SFREQ, dtype=np.float64) / SFREQ
        templates: list[list[bytes]] = []
        for index, _ in enumerate(CHANNELS[:-1]):
            variations = []
            for phase in range(7):
                values = 900 * np.sin(2 * np.pi * (9 + index % 5) * sample + phase + seed)
                values += 180 * np.sin(2 * np.pi * (17 + index % 7) * sample + phase / 3)
                variations.append(_int24(np.rint(values)))
            templates.append(variations)
        status = [_int24(np.full(SFREQ, 51 if phase == 0 else 0, dtype=np.int32))
                  for phase in range(7)]
        templates.append(status)
        for record in range(seconds):
            for channel in templates:
                out.write(channel[record % 7])


class _App:
    def log(self, _message: str, **_kwargs: object) -> None:
        pass


def _run_one(task: tuple[str, str, str]) -> dict[str, object]:
    path_str, mode, work_dir_str = task
    set_worker_thread_limits()
    path = Path(path_str)
    preload_path = Path(work_dir_str) / f"{path.stem}_{os.getpid()}_{mode}.dat"
    started = perf_counter()
    raw = load_eeg_file(
        _App(), str(path), ref_pair=("EXG1", "EXG2"), stim_channel="Status",
        electrode_mapping_profile="anatomical_labels", electrode_montage="biosemi64",
        **({"preload_in_memory": True} if mode == "ram" else {"preload_path": preload_path}),
    )
    if raw is None:
        raise RuntimeError(f"BDF load failed: {path}")
    loaded = perf_counter()
    params = {
        "downsample_rate": 256,
        "low_pass": 50.0,
        "high_pass": 0.5,
        "line_noise_filter_enabled": False,
        "reject_thresh": 3.0,
        "ref_channel1": "EXG1",
        "ref_channel2": "EXG2",
        "max_idx_keep": 64,
        "stim_channel": "Status",
        "electrode_montage": "biosemi64",
        "electrode_mapping_profile": "anatomical_labels",
        "kurtosis_auto_interpolate_all": True,
    }
    processed, _ = perform_preprocessing(raw, params, _App().log, path.name)
    if processed is None:
        raise RuntimeError(f"Preprocessing failed: {path}: {params.get('_fpvs_preprocessing_error')}")
    finished = perf_counter()
    digest = hashlib.sha256(memoryview(np.ascontiguousarray(processed._data))).hexdigest()
    result = {
        "file": path.name, "mode": mode,
        "load_seconds": round(loaded - started, 3),
        "preprocess_seconds": round(finished - loaded, 3),
        "total_seconds": round(finished - started, 3),
        "sha256": digest,
    }
    processed.close()
    del processed, raw
    gc.collect()
    if mode == "disk":
        preload_path.unlink()
    return result


def _warm_worker(_index: int) -> int:
    set_worker_thread_limits()
    sleep(0.2)
    return os.getpid()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=int, default=600)
    parser.add_argument("--rounds", type=int, default=2)
    args = parser.parse_args()
    if args.seconds < 2 or args.rounds < 1:
        parser.error("--seconds must be >= 2 and --rounds must be >= 1")
    with tempfile.TemporaryDirectory(prefix="fpvs_bdf_benchmark_") as temp:
        directory = Path(temp)
        files = [directory / f"synthetic_{index}.bdf" for index in range(4)]
        for index, path in enumerate(files):
            write_synthetic_bdf(path, seconds=args.seconds, seed=index)
        print(json.dumps({"seconds_per_file": args.seconds, "workers": 4,
                          "bdf_bytes_total": sum(path.stat().st_size for path in files)}), flush=True)
        results = []
        modes = ["disk", "ram"] * args.rounds
        with ProcessPoolExecutor(max_workers=4) as executor:
            if len(set(executor.map(_warm_worker, range(4)))) != 4:
                raise RuntimeError("Benchmark did not start four workers")
            for round_index, mode in enumerate(modes):
                if round_index % 4 in {2, 3}:
                    mode = "ram" if mode == "disk" else "disk"
                started = perf_counter()
                samples = list(executor.map(
                    _run_one, ((str(path), mode, temp) for path in files),
                ))
                wall_seconds = perf_counter() - started
                results.append({"mode": mode, "wall_seconds": round(wall_seconds, 3),
                                "workers": samples})
                print(json.dumps(results[-1]), flush=True)
        by_file: dict[str, set[str]] = {}
        for run in results:
            for sample in run["workers"]:
                by_file.setdefault(sample["file"], set()).add(sample["sha256"])
        if any(len(digests) != 1 for digests in by_file.values()):
            raise RuntimeError("Disk and RAM modes produced different preprocessed data")
        summary = {"identical_preprocessed_data": True}
        for mode in ("disk", "ram"):
            selected = [run for run in results if run["mode"] == mode]
            summary[mode] = {
                "median_batch_wall_seconds": round(median(run["wall_seconds"] for run in selected), 3),
                "median_worker_load_seconds": round(median(
                    sample["load_seconds"] for run in selected for sample in run["workers"]
                ), 3),
                "median_worker_preprocess_seconds": round(median(
                    sample["preprocess_seconds"] for run in selected for sample in run["workers"]
                ), 3),
            }
        summary["batch_wall_speedup_percent"] = round(
            100 * (1 - summary["ram"]["median_batch_wall_seconds"]
                   / summary["disk"]["median_batch_wall_seconds"]), 1
        )
        print(json.dumps({"summary": summary}), flush=True)


if __name__ == "__main__":
    main()
