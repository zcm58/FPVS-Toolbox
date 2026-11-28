"""Read native ANT eego CNT events and optionally verify one Studio condition."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys

from .ant_cnt_events import read_ant_cnt_events
from .studio_marker_comparison import compare_studio_markers


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cnt", type=Path, help="Original ANT .cnt with its same-basename companion files.")
    parser.add_argument("--studio-run", type=Path, help="Per-run Studio folder with runspec.json and trigger_log.csv.")
    args = parser.parse_args(argv)
    try:
        inspection = read_ant_cnt_events(args.cnt)
        report = asdict(inspection)
        matched = True
        if args.studio_run is not None:
            # Retain unknown markers for comparison, so a missing mapping cannot silently pass.
            candidates = tuple(event for event in inspection.events if event.kind != "recorder")
            comparison = compare_studio_markers(
                candidates, args.studio_run, backend="ant_mylab_ttl", recording_format="cnt",
                sampling_rate_hz=inspection.sampling_rate_hz,
            )
            aligned = comparison.get("aligned_markers")
            if aligned:
                first, last = aligned[0]["cnt_sample"], aligned[-1]["cnt_sample"]
                boundary = next((s for s in inspection.timing_break_samples if first < s <= last), None)
                if boundary is not None:
                    comparison["elapsed_time_discontinuous_from_sample"] = boundary
                    for row in aligned:
                        if row["cnt_sample"] >= boundary:
                            row["cnt_minus_studio_elapsed_ms"] = None
            report["comparison"] = comparison
            matched = comparison["status"] == "ordered_marker_match"
        json.dump(report, sys.stdout, ensure_ascii=True, indent=2)
        sys.stdout.write("\n")
        return 0 if matched else 1
    except (OSError, ValueError, KeyError, TypeError, csv.Error) as exc:
        logging.getLogger(__name__).error("Cannot inspect ANT TTL markers: %s", exc)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
