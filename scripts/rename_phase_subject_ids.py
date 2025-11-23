"""Rename Excel files to normalize subject IDs for phase-aware stats.

This standalone script rewrites filenames from patterns like ``P2CGL_Angry_Results.xlsx``
into ``P2_CGL_Angry_Results.xlsx`` so that existing subject-ID regexes pick up
phase-agnostic identifiers (e.g., ``P2``) across phases.
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path
from typing import Iterable, List, Tuple

# Regex splits the subject ID into three groups:
#   prefix: the base subject token (e.g., P2, Sub3, S5)
#   suffix: trailing letters encoding group/phase (e.g., CGL, BCF)
#   rest:   anything following (may be empty or start with an underscore)
PATTERN = re.compile(r"^(?P<prefix>P\d+|Sub\d+|S\d+)(?P<suffix>[A-Za-z]+)(?P<rest>.*)$")

logger = logging.getLogger(__name__)


def iter_excel_files(root: Path, recursive: bool) -> Iterable[Path]:
    """Yield .xlsx files from ``root`` optionally traversing subdirectories."""
    if recursive:
        yield from root.rglob("*.xlsx")
    else:
        for path in root.iterdir():
            if path.is_file() and path.suffix.lower() == ".xlsx":
                yield path


def plan_renames(excel_roots: List[Path], recursive: bool) -> Tuple[List[Tuple[Path, Path]], int, int]:
    """Collect planned renames and return (plans, files_seen, files_matched)."""
    plans: List[Tuple[Path, Path]] = []
    files_seen = 0
    files_matched = 0

    for root in excel_roots:
        for path in iter_excel_files(root, recursive=recursive):
            if not path.is_file():
                continue

            files_seen += 1
            stem = path.stem
            match = PATTERN.match(stem)
            if not match:
                logger.debug("Skipping (pattern mismatch): '%s'", path)
                continue

            files_matched += 1
            prefix = match.group("prefix")
            suffix = match.group("suffix")
            rest = match.group("rest")

            normalized_prefix = f"{prefix}_{suffix}"
            # If the basename already starts with ``prefix_suffix``, the file is already
            # normalized and should be left untouched.
            if stem.startswith(normalized_prefix):
                continue

            new_stem = f"{prefix}_{suffix}{rest}"
            new_path = path.with_name(new_stem + path.suffix)

            if new_path != path:
                plans.append((path, new_path))

    return plans, files_seen, files_matched


def detect_collisions(plans: List[Tuple[Path, Path]]) -> int:
    """Return the number of collisions detected within planned renames."""
    collisions = 0
    targets: dict[Path, Path] = {}

    for old_path, new_path in plans:
        existing_source = targets.get(new_path)
        if existing_source and existing_source != old_path:
            collisions += 1
            logger.error(
                "Collision detected: '%s' and '%s' would map to '%s'",
                existing_source,
                old_path,
                new_path,
            )
            continue

        if new_path.exists() and new_path.resolve() != old_path.resolve():
            collisions += 1
            logger.error(
                "Collision detected: target '%s' already exists and differs from source '%s'",
                new_path,
                old_path,
            )
            continue

        targets[new_path] = old_path

    return collisions


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handler = logging.StreamHandler(sys.stdout)
    formatter = logging.Formatter("%(levelname)s: %(message)s")
    handler.setFormatter(formatter)
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers.clear()
    root_logger.addHandler(handler)


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Normalize phase/group codes in Excel filenames for FPVS Toolbox stats.",
    )
    parser.add_argument(
        "excel_roots",
        nargs="+",
        help="One or more directories containing Excel files to normalize.",
    )
    parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        default=False,
        help="Plan renames without applying changes.",
    )
    parser.add_argument(
        "--no-recursive",
        action="store_true",
        default=False,
        help="Do not descend into subdirectories (process only immediate .xlsx files).",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable debug logging.",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    configure_logging(args.verbose)

    excel_roots = [Path(root) for root in args.excel_roots]
    recursive = not args.no_recursive

    logger.info(
        "Starting phase subject ID rename. roots=%s dry_run=%s recursive=%s",
        excel_roots,
        args.dry_run,
        recursive,
    )

    for root in excel_roots:
        if not root.exists() or not root.is_dir():
            logger.error("Invalid root (not a directory): '%s'", root)
            return 1

    plans, files_seen, files_matched = plan_renames(excel_roots, recursive)
    collisions = detect_collisions(plans)

    if collisions:
        logger.info(
            "Completed rename. files_seen=%d, files_matched=%d, files_renamed=%d, collisions=%d",
            files_seen,
            files_matched,
            len(plans),
            collisions,
        )
        return 1

    if args.dry_run:
        for old_path, new_path in plans:
            logger.info("DRY-RUN: would rename '%s' -> '%s'", old_path, new_path)
    else:
        for old_path, new_path in plans:
            new_path.parent.mkdir(parents=True, exist_ok=True)
            old_path.rename(new_path)
            logger.info("Renamed '%s' -> '%s'", old_path, new_path)

    logger.info(
        "Completed rename. files_seen=%d, files_matched=%d, files_renamed=%d, collisions=%d",
        files_seen,
        files_matched,
        len(plans),
        collisions,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

# Example usage (Windows PowerShell):
# python -m scripts.rename_phase_subject_ids "C:\\Projects\\BC Follicular\\1 - Excel Data Files" "C:\\Projects\\BC Luteal\\1 - Excel Data Files" --dry-run
# python -m scripts.rename_phase_subject_ids "C:\\Projects\\BC Follicular\\1 - Excel Data Files" "C:\\Projects\\BC Luteal\\1 - Excel Data Files"
#
# This normalization ensures the Stats scanner extracts base IDs like P2, P7, or P10
# for all phases of the same subject, allowing Lela Mode to intersect subjects
# across phases without dropping them.
