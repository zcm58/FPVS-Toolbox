import sys
from pathlib import Path

# ==== EDIT THESE TWO LINES BEFORE RUNNING ====
REPO_ROOT = Path(r"C:\Users\zackm\PycharmProjects\FPVS-Toolbox-Repo")
PROJECT_ROOT = Path(
    r"C:\Users\zackm\OneDrive - Mississippi State University\NERD\2 - Results\1 - FPVS Toolbox Projects\BC Luteal"
)
# =============================================

# Make sure src is on sys.path so imports work like in main.py
SRC_ROOT = REPO_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from Main_App.PySide6_App.Backend.project import Project
from Main_App.PySide6_App.Backend.processing_controller import discover_raw_files

def main() -> None:
    print("=== Multigroup Debug ===")
    print(f"REPO_ROOT   : {REPO_ROOT}")
    print(f"PROJECT_ROOT: {PROJECT_ROOT}")
    print()

    # 1) Load project and inspect groups as seen at runtime
    project = Project.load(PROJECT_ROOT)

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
