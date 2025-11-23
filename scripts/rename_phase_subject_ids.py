"""Utility script to standardize phase subject IDs in Excel filenames.

Usage example:
    python -m scripts.rename_phase_subject_ids \
        "C:\\Path\\To\\BC Follicular\\1 - Excel Data Files" \
        "C:\\Path\\To\\BC Luteal\\1 - Excel Data Files" \
        --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
import re
from typing import Iterable, List, Tuple


OLD_FORMAT_PATTERN = re.compile(r"^(?P<base>(?:P\d+|Sub\d+|S\d+))(?P<suffix>[A-Za-z]+)$", re.IGNORECASE)
NEW_FORMAT_PATTERN = re.compile(r"^(?:P\d+|Sub\d+|S\d+)_", re.IGNORECASE)


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Batch-rename Excel files so subject IDs are phase-agnostic and "
            "group/phase info is placed after an underscore."
        )
    )
    parser.add_argument(
        "excel_roots",
        nargs="+",
        help="One or more Excel root folders to scan for .xlsx files.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show intended renames without modifying files.",
        default=False,
    )
    parser.add_argument(
        "--recursive",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Recurse into subdirectories (default: True).",
    )
    return parser.parse_args(argv)


def iter_excel_files(root: Path, recursive: bool) -> Iterable[Path]:
    if recursive:
        yield from root.rglob("*.xlsx")
    else:
        yield from root.glob("*.xlsx")


def plan_renames(excel_roots: List[Path], recursive: bool) -> Tuple[List[Tuple[Path, Path]], List[str], int]:
    planned: List[Tuple[Path, Path]] = []
    collisions: List[str] = []
    processed = 0
    target_to_source: dict[Path, Path] = {}

    for root in excel_roots:
        for file_path in iter_excel_files(root, recursive):
            processed += 1
            if not file_path.is_file():
                continue

            basename = file_path.stem

            if NEW_FORMAT_PATTERN.match(basename):
                logging.debug("Skipping already standardized file: %s", file_path)
                continue

            old_match = OLD_FORMAT_PATTERN.match(basename)
            if not old_match:
                logging.debug("Skipping non-matching filename: %s", file_path)
                continue

            base_id = old_match.group("base")
            suffix = old_match.group("suffix")
            new_basename = f"{base_id}_{suffix}"
            target_path = file_path.with_name(new_basename + file_path.suffix)

            if target_path in target_to_source and target_to_source[target_path] != file_path:
                collision_message = (
                    f"Collision detected: '{file_path}' and planned rename from "
                    f"'{target_to_source[target_path]}' would share the same target name '{target_path}'."
                )
                logging.error(collision_message)
                collisions.append(collision_message)
                continue

            if target_path.exists() and target_path.resolve() != file_path.resolve():
                collision_message = (
                    f"Collision detected: '{file_path}' and existing '{target_path}' would "
                    "share the same target name."
                )
                logging.error(collision_message)
                collisions.append(collision_message)
                continue

            planned.append((file_path, target_path))
            target_to_source[target_path] = file_path

    return planned, collisions, processed


def perform_renames(planned: List[Tuple[Path, Path]], dry_run: bool) -> int:
    renamed_count = 0
    for source, target in planned:
        if dry_run:
            logging.info("DRY-RUN: would rename '%s' -> '%s'", source, target)
            renamed_count += 1
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target)
        logging.info("Renamed '%s' -> '%s'", source, target)
        renamed_count += 1
    return renamed_count


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)

    excel_roots = [Path(root) for root in args.excel_roots]
    for root in excel_roots:
        if not root.exists() or not root.is_dir():
            logging.error("Provided root is not a directory: %s", root)
            return 1

    logging.info(
        "Starting phase subject ID rename. Roots=%s dry_run=%s recursive=%s",
        excel_roots,
        args.dry_run,
        args.recursive,
    )

    planned, collisions, processed = plan_renames(excel_roots, args.recursive)

    if collisions:
        logging.error("Collisions detected; aborting rename. Count=%d", len(collisions))
        return 1

    renamed = perform_renames(planned, args.dry_run)

    logging.info(
        "Completed rename. Files_processed=%d, Files_renamed=%d, Collisions=%d",
        processed,
        renamed,
        len(collisions),
    )
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(main())
