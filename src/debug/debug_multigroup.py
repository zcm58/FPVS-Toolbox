"""Inspect multigroup project discovery for a selected project folder."""

import argparse
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROJECT_ROOT = os.environ.get("FPVS_DEBUG_PROJECT_ROOT")

# Make sure src is on sys.path so imports work like in main.py
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Main_App.PySide6_App.Backend.project import Project  # noqa: E402
from Main_App.PySide6_App.Backend.processing_controller import discover_raw_files  # noqa: E402


def parse_args() -> Path:
    parser = argparse.ArgumentParser(
        description="Inspect group and raw-file discovery for an FPVS project directory."
    )
    parser.add_argument(
        "project_root",
        nargs="?",
        default=DEFAULT_PROJECT_ROOT,
        help="Path to the project directory. Defaults to FPVS_DEBUG_PROJECT_ROOT if set.",
    )
    args = parser.parse_args()
    if not args.project_root:
        parser.error(
            "project_root is required. Pass it on the command line or set FPVS_DEBUG_PROJECT_ROOT."
        )

    project_root = Path(args.project_root).expanduser().resolve()
    if not project_root.exists():
        parser.error(f"project_root does not exist: {project_root}")
    return project_root


def main() -> None:
    project_root = parse_args()

    print("=== Multigroup Debug ===")
    print(f"REPO_ROOT   : {REPO_ROOT}")
    print(f"PROJECT_ROOT: {project_root}")
    print()

    # 1) Load project and inspect groups as seen at runtime
    project = Project.load(project_root)

    print("Project.input_folder:", project.input_folder)
    print()

    print("Groups seen at runtime (project.groups):")
    if not getattr(project, "groups", None):
        print("  [NO GROUPS FOUND]")
    else:
        for name, info in project.groups.items():
            folder = info.get("raw_input_folder") if isinstance(info, dict) else None
            print(f"  - {name!r} -> {folder}")
    print()

    # 2) Discover raw files via discover_raw_files(project)
    raw_file_infos = discover_raw_files(project)
    print(f"discover_raw_files(...) found {len(raw_file_infos)} .bdf files")
    if not raw_file_infos:
        print("  [NO FILES RETURNED]")
        return

    # Per-group counts
    per_group_counts = {}
    for info in raw_file_infos:
        grp = info.group or "<NO GROUP>"
        per_group_counts[grp] = per_group_counts.get(grp, 0) + 1

    print("\nCounts per group:")
    for grp, count in per_group_counts.items():
        print(f"  group={grp!r}: {count} files")

    print("\nDetailed files:")
    for info in raw_file_infos:
        print(f"  group={info.group!r}, subject={info.subject_id!r}, path={info.path}")

if __name__ == "__main__":
    main()
