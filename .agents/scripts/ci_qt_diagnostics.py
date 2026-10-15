"""CI-only per-file Qt triage; the normal complete test suite remains required."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--shard", type=int, required=True)
    parser.add_argument("--shards", type=int, required=True)
    args = parser.parse_args()
    if not os.environ.get("GITHUB_ACTIONS") == "true":
        parser.error("This diagnostic executes Qt and is restricted to GitHub Actions.")
    if args.shards < 1 or not 0 <= args.shard < args.shards:
        parser.error("The shard must be within a positive shard count.")
    root = Path(__file__).resolve().parents[2]
    entries = [
        line.strip() for line in (root / "tests/qt_test_files.txt").read_text().splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    output = root / "build/qt-diagnostics" / str(args.shard)
    output.mkdir(parents=True, exist_ok=True)
    results = []
    for index, entry in enumerate(entries):
        if index % args.shards != args.shard:
            continue
        print(f"Running {entry}", flush=True)
        prefix = output / f"{index:03d}-{Path(entry).stem}"
        environment = dict(os.environ, FPVS_TEST_WATCHDOG_DIR=str(prefix.with_suffix(".watchdog")))
        with prefix.with_suffix(".log").open("w", encoding="utf-8") as log:
            try:
                result = subprocess.run(
                    [sys.executable, "-m", "pytest", "--allow-qt-tests", entry,
                     "-vv", "--capture=tee-sys",
                     f"--junitxml={prefix.with_suffix('.xml')}"],
                    cwd=root, env=environment, stdout=log, stderr=subprocess.STDOUT,
                    timeout=240,
                )
                returncode = result.returncode
            except subprocess.TimeoutExpired:
                log.write("\nPer-file diagnostic exceeded 240 seconds.\n")
                returncode = 124
        results.append({"file": entry, "returncode": returncode})
        (output / "results.json").write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"{entry}: exit {returncode}", flush=True)
    return int(any(row["returncode"] != 0 for row in results))


if __name__ == "__main__":
    raise SystemExit(main())
