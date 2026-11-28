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
            )
            metadata_path = args.studio_run / "runtime_metadata.json"
            if metadata_path.is_file():
                snapshot = json.loads(metadata_path.read_text(encoding="utf-8-sig"))["recording"]
                if snapshot["effective_backend"] != "ant_mylab_ttl":
                    comparison["differences"].append("Studio runtime metadata identifies a different output.")
                else:
                    expected_rate = snapshot["ant_sampling_rate_hz"]
                    if type(expected_rate) is not int or expected_rate <= 0:
                        raise ValueError("Invalid ANT sampling rate in Studio runtime metadata.")
                    comparison["studio_configured_rate_hz"] = expected_rate
                    if expected_rate != inspection.sampling_rate_hz:
                        comparison["differences"].append(
                            f"Studio configured {expected_rate} Hz, but the CNT records {inspection.sampling_rate_hz} Hz."
                        )
                if comparison["differences"]:
                    comparison["status"] = "mismatch"
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
