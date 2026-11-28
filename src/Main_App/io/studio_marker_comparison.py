"""Compare recorded stimulus rows with a compiled Studio schedule and per-run send log."""

from __future__ import annotations

from collections.abc import Sequence
import csv
from itertools import pairwise
import json
import math
from pathlib import Path
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from .ant_cnt_events import AntCntEvent
    from .egi_mff_events import MffDinEvent


def _check_run_summary(summary: dict, spec: dict, attempts: list[dict], problems: list[str]) -> None:
    expected = {"run_id": spec["run_id"], "condition_id": spec["condition"]["condition_id"],
                "condition_name": spec["condition"]["name"]}
    if "project_id" in spec:
        expected["project_id"] = spec["project_id"]
    for key, value in expected.items():
        if summary.get(key) != value:
            problems.append(f"Studio run_summary.json disagrees with runspec.json on {key}.")
    rows = summary["trigger_log"]
    if not isinstance(rows, list):
        raise ValueError("Expected a trigger log in Studio run_summary.json.")
    if len(rows) != len(attempts):
        problems.append("Studio run_summary.json and trigger_log.csv contain different numbers of attempts.")
        return
    keys = ("trigger_index", "frame_index", "code", "label", "backend_name", "status")
    for index, (row, attempt) in enumerate(zip(rows, attempts)):
        csv_time = float(attempt["time_s"]) if attempt["time_s"] else None
        if (any(str(row[key]) != attempt[key] for key in keys)
                or csv_time != row.get("time_s")):
            problems.append(f"Studio trigger_log.csv row {index + 1} disagrees with run_summary.json.")
            break


def _check_recording_snapshot(
    metadata: dict, backend: str, sampling_rate_hz: int | None, problems: list[str],
) -> int | None:
    snapshot = metadata["recording"]
    if snapshot["effective_backend"] != backend:
        problems.append("Studio runtime metadata identifies a different output.")
        return None
    if backend != "ant_mylab_ttl":
        return None
    rate = snapshot["ant_sampling_rate_hz"]
    if type(rate) is not int or rate <= 0:
        raise ValueError("Invalid ANT sampling rate in Studio runtime metadata.")
    if rate != sampling_rate_hz:
        problems.append(f"Studio configured {rate} Hz, but the CNT records {sampling_rate_hz} Hz.")
    return rate


def _check_run_companions(
    run_dir: Path, spec: dict, attempts: list[dict], backend: str, sampling_rate_hz: int | None, problems: list[str],
) -> dict:
    summary_path = run_dir / "run_summary.json"
    evidence = {"run_summary_checked": summary_path.exists()}
    embedded_metadata = None
    if evidence["run_summary_checked"]:
        summary = json.loads(summary_path.read_text(encoding="utf-8-sig"))
        if not isinstance(summary, dict):
            raise ValueError("Expected an object in Studio run_summary.json.")
        _check_run_summary(summary, spec, attempts, problems)
        embedded_metadata = summary.get("runtime_metadata")
    metadata_path = run_dir / "runtime_metadata.json"
    metadata = embedded_metadata
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8-sig"))
        if not isinstance(metadata, dict):
            raise ValueError("Expected an object in Studio runtime_metadata.json.")
        if embedded_metadata is not None and embedded_metadata["recording"] != metadata["recording"]:
            problems.append("Studio run_summary.json and runtime_metadata.json identify different recording settings.")
    if metadata is not None:
        configured_rate = _check_recording_snapshot(metadata, backend, sampling_rate_hz, problems)
        if configured_rate is not None:
            evidence["studio_configured_rate_hz"] = configured_rate
    return evidence


def compare_studio_markers(
    events: Sequence[MffDinEvent | AntCntEvent],
    run_dir: Path,
    *,
    backend: str,
    recording_format: Literal["mff", "cnt"],
    sampling_rate_hz: int | None = None,
) -> dict:
    """Compare the complete track, compiled schedule and locally sent event rows."""
    spec = json.loads((run_dir / "runspec.json").read_text(encoding="utf-8-sig"))
    condition = spec["condition"]
    if not all(isinstance(value, str) and value.strip()
               for value in (spec["run_id"], condition["condition_id"], condition["name"])):
        raise ValueError("Expected a run ID, condition ID and condition name in Studio runspec.json.")
    plan = spec["trigger_events"]
    if not isinstance(plan, list) or not plan:
        raise ValueError("Select a Studio run with a nonempty trigger schedule.")
    roles = {}
    previous_frame = -1
    for index, entry in enumerate(plan):
        code, label, frame = entry["code"], entry["label"], entry["frame_index"]
        if type(code) is not int or not 1 <= code <= 255 or type(frame) is not int or frame < 0:
            raise ValueError("Invalid code or frame in the Studio trigger schedule.")
        if label not in ("oddball_onset", "condition_start"):
            raise ValueError(f"Unsupported marker role in the selected FPVS run: {label!r}")
        if (index == 0) != (label == "condition_start") or frame <= previous_frame:
            raise ValueError("The FPVS schedule needs one initial condition start and increasing marker frames.")
        if index == 0 and "trigger_code" in condition:
            if type(condition["trigger_code"]) is not int or code != condition["trigger_code"]:
                raise ValueError("The condition's trigger code disagrees with the scheduled start marker.")
        previous_frame = frame
        if roles.setdefault(code, label) != label:
            raise ValueError(f"Studio uses code {code} for multiple roles in this condition.")
    with (run_dir / "trigger_log.csv").open(encoding="utf-8-sig", newline="") as stream:
        log = csv.DictReader(stream, strict=True)
        required = {"trigger_index", "frame_index", "time_s", "label", "code", "backend_name", "status"}
        fields = log.fieldnames or []
        if not required.issubset(fields) or "run_id" in fields or len(fields) != len(set(fields)):
            raise ValueError("Select the per-run Studio trigger_log.csv.")
        attempts = list(log)
        if any(None in row or any(value is None for value in row.values()) for row in attempts):
            raise ValueError("Studio trigger_log.csv contains a row with the wrong number of fields.")
    problems = []
    evidence = _check_run_companions(run_dir, spec, attempts, backend, sampling_rate_hz, problems)
    # Studio's per-condition CSV retains the trigger counter shared by the session.
    first_index_text = attempts[0]["trigger_index"] if attempts else ""
    first_index = int(first_index_text) if first_index_text.isascii() and first_index_text.isdecimal() else 0
    for index, (entry, attempt) in enumerate(zip(plan, attempts)):
        expected = {
            "trigger_index": str(first_index + index), "frame_index": str(entry["frame_index"]),
            "code": str(entry["code"]), "label": entry["label"], "backend_name": backend, "status": "sent",
        }
        differences = [f"{key}={attempt[key]!r} (expected {value!r})"
                       for key, value in expected.items() if attempt[key] != value]
        if differences:
            problems.append(f"Studio log row {index + 1}: " + ", ".join(differences))
            break
    if len(attempts) != len(plan):
        problems.append(f"Studio scheduled {len(plan)} markers and logged {len(attempts)} attempts.")
    if len(events) != len(plan):
        source = "the selected track" if recording_format == "mff" else "the CNT stimulus comparison"
        problems.append(f"Studio scheduled {len(plan)} markers and {source} has {len(events)}.")
    for event, entry in zip(events, plan):
        if event.studio_code != entry["code"]:
            problems.append(f"Recorded row {event.source_order + 1} ({event.source_code!r}) maps to "
                            f"{event.studio_code!r}; Studio expected {entry['code']}.")
            break
    times = []
    if not problems:
        times = [float(row["time_s"]) for row in attempts]
        if not all(math.isfinite(time) and time >= 0 for time in times):
            raise ValueError("Invalid Studio trigger timestamp.")
        if any(later < earlier for earlier, later in pairwise(times)):
            problems.append("Studio trigger timestamps go backwards in send order.")
        elif not math.isfinite((times[-1] - times[0]) * 1000):
            raise ValueError("Studio trigger timestamp exceeds the supported elapsed-time range.")
        if any(later.onset_ns < earlier.onset_ns for earlier, later in pairwise(events)):
            problems.append("Recorded stimulus sample positions or sub-sample onsets go backwards in source order.")
    result = {
        "run_id": spec["run_id"], "condition_id": spec["condition"]["condition_id"],
        "condition_name": spec["condition"]["name"], "roles_by_code": roles,
        **evidence,
        "status": "mismatch" if problems else "ordered_marker_match", "differences": problems,
    }
    if not problems:
        # Align on the first event. The display PC and recorder have separate clocks.
        first_onset = events[0].onset_ns
        result["aligned_markers"] = [
            {
                "studio_trigger_index": first_index + index,
                "frame_index": entry["frame_index"], "role": entry["label"], "studio_code": entry["code"],
                "studio_time_s": time, "source_order": event.source_order, f"{recording_format}_sample": event.sample,
                f"{recording_format}_minus_studio_elapsed_ms": (event.onset_ns - first_onset) / 1e6 - (time - times[0]) * 1000,
            }
            for index, (entry, time, event) in enumerate(zip(plan, times, events, strict=True))
        ]
    return result
