"""Inspect one MFF event track and compare it with a selected Studio run."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import logging
import math
from pathlib import Path
import sys

from .egi_mff_events import MffDinInspection, read_mff_din_events


def compare_run(inspection: MffDinInspection, run_dir: Path) -> dict:
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
            "code": str(entry["code"]), "label": entry["label"], "backend_name": "egi_din", "status": "sent",
        }
        differences = [f"{key}={attempt[key]!r} (expected {value!r})"
                       for key, value in expected.items() if attempt[key] != value]
        if differences:
            problems.append(f"Studio log row {index + 1}: " + ", ".join(differences))
            break
    if len(attempts) != len(plan):
        problems.append(f"Studio scheduled {len(plan)} markers and logged {len(attempts)} attempts.")
    if len(inspection.events) != len(plan):
        problems.append(f"Studio scheduled {len(plan)} markers and the selected track has {len(inspection.events)}.")
    for index, (event, entry) in enumerate(zip(inspection.events, plan)):
        if event.studio_code != entry["code"]:
            problems.append(f"Recorded row {index + 1} ({event.source_code!r}) maps to "
                            f"{event.studio_code!r}; Studio expected {entry['code']}.")
            break
    result = {
        "run_id": spec["run_id"], "condition_id": spec["condition"]["condition_id"],
        "condition_name": spec["condition"]["name"], "roles_by_code": roles,
        "status": "mismatch" if problems else "ordered_marker_match", "differences": problems,
    }
    if not problems:
        times = [float(row["time_s"]) for row in attempts]
        if not all(math.isfinite(time) and time >= 0 for time in times):
            raise ValueError("Invalid Studio trigger timestamp.")
        # Align on the first event. The display PC and recorder have separate clocks.
        first_onset = inspection.events[0].onset_ns
        result["aligned_markers"] = [
            {
                "frame_index": entry["frame_index"], "role": entry["label"], "studio_code": entry["code"],
                "studio_time_s": time, "source_order": event.source_order, "mff_sample": event.sample,
                "mff_minus_studio_elapsed_ms": (event.onset_ns - first_onset) / 1e6 - (time - times[0]) * 1000,
            }
            for entry, time, event in zip(plan, times, inspection.events, strict=True)
        ]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mff", type=Path)
    parser.add_argument("--track", required=True, help="Exact Events_*.xml filename inside the MFF.")
    parser.add_argument("--map", dest="mappings", metavar="SOURCE=BYTE", action="append", default=[],
                        help="Reviewed, case-sensitive source identity and Studio byte. Repeat per identity.")
    parser.add_argument("--studio-run", type=Path, help="Matching per-run folder with runspec.json and trigger_log.csv.")
    args = parser.parse_args(argv)
    try:
        code_map = {}
        for item in args.mappings:
            source, separator, value = item.rpartition("=")
            if not separator or not source or source in code_map:
                raise ValueError(f"Invalid or duplicate source mapping: {item!r}")
            code_map[source] = int(value)
        result = read_mff_din_events(args.mff, track=args.track, code_map=code_map)
        report = asdict(result)
        report["source_to_studio"] = code_map
        comparison = compare_run(result, args.studio_run) if args.studio_run is not None else None
        if comparison is not None:
            report["comparison"] = comparison
        json.dump(report, sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
        return int(comparison is not None and comparison["status"] == "mismatch")
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        logging.getLogger(__name__).error("Cannot inspect DIN markers: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
