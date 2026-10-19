"""Compare five synthetic BioSemi recordings against an isolated Git baseline.

This opt-in diagnostic executes the real non-GUI processing/export route. It
does not run pytest or alter the active checkout. Generated recordings, baseline
sources and receipts stay below the explicitly selected work directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import subprocess
import sys
import time
import zipfile

LOG = logging.getLogger(__name__)
PARTICIPANTS = 5
SFREQ = 2048
DURATION_SECONDS = 80
BASELINE_PATHS = ("src/Main_App", "src/Tools", "src/config.py")


def _json_default(value):
    if isinstance(value, Path):
        return str(value)
    if hasattr(value, "tolist"):
        return value.tolist()
    if hasattr(value, "to_payload"):
        return value.to_payload()
    raise TypeError(type(value).__name__)


def _write_json(path: Path, value) -> None:
    path.write_text(json.dumps(value, indent=2, default=_json_default), encoding="utf-8")


def _sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _write_synthetic_bdf(path: Path, seed: int) -> dict:
    """Independently encode genuine 24-bit BDF samples (not a mocked reader)."""
    import numpy as np

    names = [f"A{i}" for i in range(1, 33)] + [f"B{i}" for i in range(1, 33)]
    names += ["EXG1", "EXG2", "Status"]
    times = np.arange(SFREQ * DURATION_SECONDS) / SFREQ
    rng = np.random.default_rng(seed)
    amplitude = rng.uniform(2, 15, (66, 1))
    phase = rng.uniform(-.5, .5, (66, 1))
    signal_uv = amplitude * np.sin(2 * np.pi * 2 * times + phase)
    signal_uv += rng.uniform(1, 8, (66, 1)) * np.sin(2 * np.pi * 8 * times)
    signal_uv += 3 * np.sin(2 * np.pi * .2 * times)
    signal_uv += rng.normal(scale=.4, size=signal_uv.shape)
    physical_min, physical_max = -262144, 262144
    digital_min, digital_max = -8388608, 8388607
    scale = (physical_max - physical_min) / (digital_max - digital_min)
    digital = np.rint((signal_uv - physical_min) / scale + digital_min).astype(np.int32)
    status = np.zeros(times.size, dtype=np.int32)
    # One condition onset followed by 129 oddball boundaries = 128 cycles.
    status[SFREQ] = 21
    samples = 2 * SFREQ + np.arange(129) * (SFREQ // 2)
    status[samples] = 55
    digital = np.vstack((digital, status))

    def field(value, width):
        text = str(value).encode("ascii")
        if len(text) > width:
            raise ValueError(f"BDF field exceeds {width} characters: {value}")
        return text.ljust(width, b" ")

    fixed = b"\xffBIOSEMI" + field("X X X X", 80) + field("Startdate 01-JAN-2026 X X X", 80)
    fixed += b"01.01.2600.00.00" + field((len(names) + 1) * 256, 8)
    fixed += field("24BIT", 44) + field(DURATION_SECONDS, 8) + field(1, 8) + field(len(names), 4)
    columns = [
        [field(name, 16) for name in names],
        [field("", 80) for _ in names],
        [field("uV" if name != "Status" else "", 8) for name in names],
        [field(physical_min if name != "Status" else digital_min, 8) for name in names],
        [field(physical_max if name != "Status" else digital_max, 8) for name in names],
        [field(digital_min, 8) for _ in names],
        [field(digital_max, 8) for _ in names],
        [field("", 80) for _ in names],
        [field(SFREQ, 8) for _ in names],
        [field("", 32) for _ in names],
    ]
    with path.open("wb") as stream:
        stream.write(fixed + b"".join(item for column in columns for item in column))
        for second in range(DURATION_SECONDS):
            block = digital[:, second * SFREQ:(second + 1) * SFREQ].reshape(-1)
            packed = np.column_stack((block & 255, (block >> 8) & 255, (block >> 16) & 255))
            stream.write(packed.astype(np.uint8).tobytes())
    return {"file": str(path), "sha256": _sha256(path), "seed": seed,
            "size_bytes": path.stat().st_size, "samples": len(times), "channels": len(names),
            "sampling_frequency_hz": SFREQ, "duration_seconds": DURATION_SECONDS,
            "condition_onset_sample": SFREQ, "oddball_boundary_samples": samples.tolist()}


def _settings(path: Path, project_root: Path) -> dict:
    return {
        "project_root": str(project_root),
        "hardware_platform": "biosemi", "hardware_confirmed": True,
        "electrode_montage": "biosemi64", "electrode_mapping_profile": "biosemi64_1020_ab_v1",
        "ref_channel1": "EXG1", "ref_channel2": "EXG2", "stim_channel": "Status",
        "max_idx_keep": 64, "downsample_rate": 128, "high_pass": 1.0, "low_pass": 40.0,
        "line_noise_filter_enabled": False, "kurtosis_screening_enabled": False,
        "reject_thresh": 0, "raw_signal_screening_enabled": False,
        "removed_electrode_detection_mode": "off", "auto_detect_removed_electrodes": False,
        "manual_removed_electrodes": [], "kurtosis_auto_interpolate_all": False,
        "enable_preprocessed_cache": False, "experimental_ram_preload": True,
        "event_id_map": {"Faces": 21},
        "_fpvs_participant_id_by_file": {str(path.resolve()): path.stem},
        "_fpvs_recording_id_by_file": {str(path.resolve()): path.stem},
        "_fpvs_processing_fingerprint": "bids-equivalence-synthetic-qc-off-v1",
        "_fpvs_processing_fingerprint_version": "diagnostic-v1",
    }


def _run_side(source_root: Path, work: Path, side: str) -> None:
    sys.path.insert(0, str(source_root / "src"))
    import mne
    import numpy as np
    from Main_App.io.load_utils import open_preflight_eeg_file
    from Main_App.processing.preflight_qc import _find_preflight_events
    from Main_App.processing.preflight_qc_plan import plan_preflight_qc_events
    from Main_App.projects import EXPECTED_CYCLES_SOURCE_MANUAL, FrequencyProtocol
    from Main_App.workers.process_runner import _run_full_pipeline_for_file
    from types import SimpleNamespace

    mne.set_log_level("ERROR")
    project_root = work / side
    project_root.mkdir(exist_ok=False)
    protocol = FrequencyProtocol.from_recurrence(
        8, 4, expected_analyzed_oddball_cycles=128,
        expected_analyzed_oddball_cycles_source=EXPECTED_CYCLES_SOURCE_MANUAL,
    )
    receipt = {"side": side, "source_root": str(source_root), "mne_version": mne.__version__,
               "participants": [], "qc_disabled": True}
    if side == "new":
        from Main_App.io.bids_import import prepare_bids_recording
    app = SimpleNamespace(log=lambda _message: None)
    for path in sorted((work / "recordings").glob("*.bdf")):
        settings = _settings(path, project_root)
        settings["frequency_protocol"] = protocol
        conversion = None
        if side == "new":
            started = time.perf_counter()
            imported = prepare_bids_recording(path, project_root=project_root, settings=settings)
            conversion = {
                "wall_seconds": time.perf_counter() - started,
                "conversion_seconds": imported.conversion_seconds,
                "reused": imported.reused,
                "dataset_root": str(imported.dataset_root),
                "bids_path": str(imported.bids_path),
                "manifest_path": str(imported.manifest_path),
            }
            conversion["native_bdf_sha256_preserved"] = _sha256(path) == _sha256(Path(str(imported.bids_path)))
            if not conversion["native_bdf_sha256_preserved"]:
                raise RuntimeError("BDF representation changed during BIDS import.")
            if imported.reused:
                raise RuntimeError("Cold conversion benchmark unexpectedly reused an import.")
        started = time.perf_counter()
        # Preflight resolves the same mandatory marker plan with optional QC off.
        with open_preflight_eeg_file(
            app, str(path), acquisition_settings=settings,
            electrode_mapping_profile=settings["electrode_mapping_profile"],
            electrode_montage=settings["electrode_montage"],
        ) as raw:
            events, source = _find_preflight_events(raw, stim_channel="Status")
            expected = np.array([[SFREQ, 0, 21],
                                 *[[2 * SFREQ + i * SFREQ // 2, 0, 55] for i in range(129)]])
            np.testing.assert_array_equal(events, expected)
            plan = plan_preflight_qc_events(
                events=events, event_map={"Faces": 21}, sfreq=SFREQ, n_times=raw.n_times,
                frequency_protocol=protocol,
            )
            if plan.unresolved_occurrences:
                raise RuntimeError(f"Synthetic marker plan needs review: {plan.unresolved_occurrences}")
            source_snapshot = {
                "data_sha256": hashlib.sha256(raw.get_data().tobytes()).hexdigest(),
                "events": events.tolist(), "event_source": source,
                "channel_names": raw.ch_names, "channel_types": raw.get_channel_types(),
                "sfreq": raw.info["sfreq"], "n_times": raw.n_times,
            }
        preflight_seconds = time.perf_counter() - started
        settings["_fpvs_preflight_event_plans_by_file"] = {str(path.resolve()): plan.to_payload()}
        started = time.perf_counter()
        result = _run_full_pipeline_for_file(
            path, settings, {"Faces": 21}, project_root / "1 - Excel Data Files", project_root,
        )
        elapsed = time.perf_counter() - started
        if result.get("status") != "ok" or result.get("source_derivative_status") != "complete":
            _write_json(work / f"{side}-failed.json", result)
            raise RuntimeError(f"{side} {path.name} failed: {result}")
        if result["audit"].get("raw_signal_screening_enabled") is not False:
            raise RuntimeError("Raw-signal QC was unexpectedly enabled.")
        if result["audit"].get("n_rejected") != 0:
            raise RuntimeError("Unexpected channel rejection with QC disabled.")
        item = {"participant": path.stem, "preflight_seconds": preflight_seconds,
                "processing_seconds": elapsed, "bids_conversion": conversion,
                "source_snapshot": source_snapshot, "result": result}
        receipt["participants"].append(item)
        _write_json(work / f"{side}-receipt.json", receipt)
        LOG.info("%s %s completed in %.3f s", side, path.stem, elapsed)


def _baseline(repo: Path, work: Path, ref: str) -> Path:
    baseline = work / "baseline-source"
    baseline.mkdir()
    archive = work / "baseline-source.zip"
    subprocess.run(["git", "archive", "--format=zip", f"--output={archive}", ref, *BASELINE_PATHS],
                   cwd=repo, check=True)
    with zipfile.ZipFile(archive) as container:
        container.extractall(baseline)
    return baseline


def _plain(value):
    """Make MNE metadata comparable without rounding scientific values."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(item) for item in value]
    if hasattr(value, "tolist"):
        return _plain(value.tolist())
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _differences(before, after, path="") -> list[dict]:
    import math

    if isinstance(before, dict) and isinstance(after, dict):
        result = []
        for key in sorted(before.keys() | after.keys()):
            if key not in before or key not in after:
                result.append({"field": f"{path}/{key}", "old": before.get(key), "new": after.get(key)})
            else:
                result.extend(_differences(before[key], after[key], f"{path}/{key}"))
        return result
    if isinstance(before, list) and isinstance(after, list):
        if len(before) != len(after):
            return [{"field": path + "/length", "old": len(before), "new": len(after)}]
        return [difference for i, (a, b) in enumerate(zip(before, after))
                for difference in _differences(a, b, f"{path}/{i}")]
    if isinstance(before, float) and isinstance(after, float) and math.isnan(before) and math.isnan(after):
        return []
    return [] if before == after else [{"field": path, "old": before, "new": after}]


def _normal_path(path: Path, root: Path) -> str:
    value = path.relative_to(root).as_posix()
    value = re.sub(r"\.(spectra|metrics)\.[0-9a-f]{20}\.npz$", r".\1.CONTENT.npz", value)
    return re.sub(r"(fft_crop_.+)_\d+\.log$", r"\1_PID.log", value)


def _output_inventory(root: Path) -> dict[str, Path]:
    result = {}
    for path in root.rglob("*"):
        if not path.is_file() or any(part.startswith(".") for part in path.relative_to(root).parts):
            continue
        name = _normal_path(path, root)
        if name in result:
            raise RuntimeError(f"Multiple output artifacts map to {name}; inspect stale or duplicate outputs.")
        result[name] = path
    return result


def _normal_metadata(value, roots: tuple[Path, Path]):
    if isinstance(value, dict):
        return {key: _normal_metadata(item, roots) for key, item in value.items()}
    if isinstance(value, list):
        return [_normal_metadata(item, roots) for item in value]
    if isinstance(value, str):
        for root in roots:
            value = value.replace(str(root), "PROJECT").replace(root.as_posix(), "PROJECT")
    return value


def _known_provenance_difference(field: str) -> bool:
    """Narrow allowlist; unrecognized metadata differences fail the diagnostic."""
    leaf = field.rsplit("/", 1)[-1]
    return (
        leaf in {"fif_sha256", "sidecar_sha256", "preprocessed_raw_cache_version"}
        or "/file_id/" in field or "/meas_id/" in field
    )


def _compare(work: Path) -> dict:
    import mne
    import numpy as np

    roots = (work / "old", work / "new")
    inventories = [_output_inventory(root) for root in roots]
    files = []
    failures = []
    for name in sorted(inventories[0].keys() | inventories[1].keys()):
        if name not in inventories[0] or name not in inventories[1]:
            failures.append({"file": name, "error": "Output present in only one pipeline."})
            continue
        before, after = inventories[0][name], inventories[1][name]
        entry = {"file": name, "old_sha256": _sha256(before), "new_sha256": _sha256(after),
                 "metadata_differences": [], "arrays_compared": 0, "numeric_values_compared": 0,
                 "max_absolute_difference": 0.0}
        entry["byte_identical"] = entry["old_sha256"] == entry["new_sha256"]
        if before.suffix == ".npz":
            with np.load(before, allow_pickle=False) as left, np.load(after, allow_pickle=False) as right:
                if left.files != right.files:
                    failures.append({"file": name, "error": "NPZ member names/order differ."})
                for key in left.files:
                    if key not in right.files:
                        continue
                    a, b = left[key], right[key]
                    entry["arrays_compared"] += 1
                    if a.dtype != b.dtype or a.shape != b.shape:
                        failures.append({"file": name, "array": key, "error": "Shape/dtype differs."})
                        continue
                    numeric = np.issubdtype(a.dtype, np.number)
                    equal = np.array_equal(a, b, equal_nan=True) if numeric else np.array_equal(a, b)
                    if numeric:
                        entry["numeric_values_compared"] += a.size
                        finite = np.isfinite(a) & np.isfinite(b)
                        if finite.any():
                            delta = float(np.max(np.abs(a[finite].astype(float) - b[finite].astype(float))))
                            entry["max_absolute_difference"] = max(entry["max_absolute_difference"], delta)
                    if not equal:
                        failures.append({"file": name, "array": key, "error": "Array values differ."})
        elif before.suffix == ".fif":
            with mne.io.read_raw_fif(before, preload=True, verbose=False) as left, \
                    mne.io.read_raw_fif(after, preload=True, verbose=False) as right:
                a, b = left.get_data(), right.get_data()
                entry["arrays_compared"] = 1
                entry["numeric_values_compared"] = a.size
                if a.shape != b.shape or not np.array_equal(a, b, equal_nan=True):
                    failures.append({"file": name, "error": "FIF signal values differ."})
                if a.shape == b.shape:
                    entry["max_absolute_difference"] = float(np.max(np.abs(a - b)))
                left_meta = {"info": _plain(dict(left.info)), "first_samp": left.first_samp,
                             "annotations": _plain(left.annotations.__getstate__())}
                right_meta = {"info": _plain(dict(right.info)), "first_samp": right.first_samp,
                              "annotations": _plain(right.annotations.__getstate__())}
                entry["metadata_differences"] = _differences(left_meta, right_meta)
        elif before.suffix in {".json", ".fpvs"}:
            left = _normal_metadata(json.loads(before.read_text(encoding="utf-8")), roots)
            right = _normal_metadata(json.loads(after.read_text(encoding="utf-8")), roots)
            entry["metadata_differences"] = _differences(left, right)
        elif before.suffix == ".log":
            # Log filenames contain process IDs; each line begins with wall time.
            def strip_time(text):
                return re.sub(r"(?m)^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d,\d{3} ", "", text)
            left = strip_time(_normal_metadata(before.read_text(encoding="utf-8"), roots))
            right = strip_time(_normal_metadata(after.read_text(encoding="utf-8"), roots))
            if left != right:
                failures.append({"file": name, "error": "Log content differs after timestamp normalization."})
            entry["normalization"] = "Process ID in filename and wall-clock timestamp prefix only."
        elif not entry["byte_identical"]:
            failures.append({"file": name, "error": "Unrecognized output differs."})
        for difference in entry["metadata_differences"]:
            difference["provenance_only"] = _known_provenance_difference(difference["field"])
            if not difference["provenance_only"]:
                failures.append({"file": name, **difference})
        files.append(entry)
    old = json.loads((work / "old-receipt.json").read_text(encoding="utf-8"))
    new = json.loads((work / "new-receipt.json").read_text(encoding="utf-8"))
    for left, right in zip(old["participants"], new["participants"], strict=True):
        if left.get("source_snapshot") != right.get("source_snapshot"):
            failures.append({"participant": left["participant"], "error": "Imported signal/event/channel identity differs."})
        for field in ("audit", "events_info", "geometry"):
            differences = _differences(left["result"][field], right["result"][field])
            failures.extend({"participant": left["participant"], "result_field": field, **item}
                            for item in differences if not _known_provenance_difference(item["field"]))
    conversions = [{"participant": item["participant"], **item["bids_conversion"]} for item in new["participants"]]
    receipt = {
        "passed": not failures, "baseline_commit": json.loads((work / "inputs.json").read_text())["baseline_commit"],
        "participants": len(old["participants"]), "qc_disabled": True, "files_compared": len(files),
        "arrays_compared": sum(item["arrays_compared"] for item in files),
        "numeric_values_compared": sum(item["numeric_values_compared"] for item in files),
        "max_absolute_difference": max(item["max_absolute_difference"] for item in files),
        "byte_identical_files": sum(item["byte_identical"] for item in files),
        "conversion_timings": conversions,
        "conversion_seconds_total": sum(item["conversion_seconds"] for item in conversions),
        "conversion_wall_seconds_total": sum(item["wall_seconds"] for item in conversions),
        "old_processing_seconds_total": sum(item["processing_seconds"] for item in old["participants"]),
        "new_processing_seconds_total": sum(item["processing_seconds"] for item in new["participants"]),
        "new_import_artifacts": [str(path.relative_to(roots[1])) for path in (roots[1] / ".fpvs_cache").rglob("*") if path.is_file()],
        "files": files, "failures": failures,
        "limitations": ["Synthetic BDF fixture, not a vendor-recorded hardware qualification.",
                        "All optional QC disabled; interpolation behavior is not exercised.",
                        "Only per-recording processing outputs; no group Stats or GUI workflows.",
                        "Import caches are new artifacts and inventoried separately from scientific outputs."],
    }
    _write_json(work / "comparison.json", receipt)
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", required=True, type=Path,
                        help="New diagnostic directory; no existing data are removed or overwritten.")
    parser.add_argument("--baseline-ref", default="da14edaa")
    parser.add_argument("--run-side", choices=("old", "new"), help=argparse.SUPPRESS)
    parser.add_argument("--source-root", type=Path, help=argparse.SUPPRESS)
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--compare-only", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    work = args.work_dir.resolve()
    if args.compare_only:
        result = _compare(work)
        LOG.info("Comparison passed=%s; files=%s; receipt=%s", result["passed"], result["files_compared"], work / "comparison.json")
        return 0 if result["passed"] else 1
    if args.run_side:
        _run_side(args.source_root.resolve(), work, args.run_side)
        return 0
    repo = Path(__file__).resolve().parents[2]
    work.mkdir(parents=True, exist_ok=False)
    (work / "recordings").mkdir()
    baseline_ref = subprocess.check_output(["git", "rev-parse", args.baseline_ref], cwd=repo, text=True).strip()
    recordings = [_write_synthetic_bdf(work / "recordings" / f"P{i:02d}.bdf", 20261019 + i)
                  for i in range(1, PARTICIPANTS + 1)]
    _write_json(work / "inputs.json", {"baseline_commit": baseline_ref, "recordings": recordings,
                                      "settings": _settings(Path("P01.bdf"), Path("PROJECT"))})
    baseline = _baseline(repo, work, baseline_ref)
    env = dict(os.environ, PYTHONNOUSERSITE="1", OPENBLAS_NUM_THREADS="1", MKL_NUM_THREADS="1",
               OMP_NUM_THREADS="1")
    for side, source in (("old", baseline), ("new", repo)):
        if side == "new" and args.baseline_only:
            break
        with (work / f"{side}.log").open("w", encoding="utf-8") as log:
            subprocess.run([sys.executable, str(Path(__file__).resolve()), "--work-dir", str(work),
                            "--run-side", side, "--source-root", str(source)],
                           cwd=source, env=env, stdout=log, stderr=subprocess.STDOUT, check=True)
    if not args.baseline_only:
        result = _compare(work)
        if not result["passed"]:
            LOG.error("Comparison failed; inspect %s", work / "comparison.json")
            return 1
    LOG.info("Diagnostic evidence: %s", work)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
