"""Inspect one MFF event track and compare it with a selected Studio run."""

from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
import json
import logging
from pathlib import Path
import sys

from .egi_mff_events import MffDinInspection, read_mff_din_events
from .studio_marker_comparison import compare_studio_markers


def compare_run(inspection: MffDinInspection, run_dir: Path) -> dict:
    """Compare the complete selected EGI track with this Studio run."""
    return compare_studio_markers(inspection.events, run_dir, backend="egi_din", recording_format="mff")


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
