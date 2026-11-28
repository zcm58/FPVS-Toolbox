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


def compare_studio_markers(
    events: Sequence[MffDinEvent | AntCntEvent],
    run_dir: Path,
    *,
    backend: str,
    recording_format: Literal["mff", "cnt"],
) -> dict:
    """Compare the complete track, compiled schedule and locally sent event rows."""
    spec = json.loads((run_dir / "runspec.json").read_text(encoding="utf-8-sig"))
    plan = spec["trigger_events"]
    if not isinstance(plan, list) or not plan:
        raise ValueError("Select a Studio run with a nonempty trigger schedule.")
    roles = {}
    for entry in plan:
        code, label, frame = entry["code"], entry["label"], entry["frame_index"]
        if type(code) is not int or not 1 <= code <= 255 or type(frame) is not int or frame < 0:
            raise ValueError("Invalid code or frame in the Studio trigger schedule.")
        if label not in ("oddball_onset", "condition_start"):
            raise ValueError(f"Unsupported marker role in the selected FPVS run: {label!r}")
        if roles.setdefault(code, label) != label:
            raise ValueError(f"Studio uses code {code} for multiple roles in this condition.")
    with (run_dir / "trigger_log.csv").open(encoding="utf-8-sig", newline="") as stream:
        log = csv.DictReader(stream, strict=True)
        required = {"trigger_index", "frame_index", "time_s", "label", "code", "backend_name", "status"}
        fields = log.fieldnames or []
        if not required.issubset(fields) or "run_id" in fields or len(fields) != len(set(fields)):
            raise ValueError("Select the per-run Studio trigger_log.csv.")
        attempts = list(log)
    problems = []
    for index, (entry, attempt) in enumerate(zip(plan, attempts)):
        expected = {
            "trigger_index": str(index), "frame_index": str(entry["frame_index"]),
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
        if any(later.sample < earlier.sample for earlier, later in pairwise(events)):
            problems.append("Recorded stimulus sample positions go backwards in source order.")
    result = {
        "run_id": spec["run_id"], "condition_id": spec["condition"]["condition_id"],
        "condition_name": spec["condition"]["name"], "roles_by_code": roles,
        "status": "mismatch" if problems else "ordered_marker_match", "differences": problems,
    }
    if not problems:
        # Align on the first event. The display PC and recorder have separate clocks.
        first_onset = events[0].onset_ns
        result["aligned_markers"] = [
            {
                "frame_index": entry["frame_index"], "role": entry["label"], "studio_code": entry["code"],
                "studio_time_s": time, "source_order": event.source_order, f"{recording_format}_sample": event.sample,
                f"{recording_format}_minus_studio_elapsed_ms": (event.onset_ns - first_onset) / 1e6 - (time - times[0]) * 1000,
            }
            for entry, time, event in zip(plan, times, events, strict=True)
        ]
    return result
