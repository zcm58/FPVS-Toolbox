import os
import glob
import re
from typing import List, Dict, Tuple

EXCEL_PID_REGEX = re.compile(
    r"(P\d+[A-Za-z]*|Sub\d+[A-Za-z]*|S\d+[A-Za-z]*)",
    re.IGNORECASE,
)


# Folders to ignore during scanning (case-insensitive)
IGNORED_FOLDERS = {".fif files", "loreta results"}


class ScanError(Exception):
    """Exception raised when scanning fails due to invalid folder or permissions."""
    pass


def scan_folder_simple(parent_folder: str) -> Tuple[List[str], List[str], Dict[str, Dict[str, str]]]:
    """
    Scans the given parent folder for subject Excel files and condition subfolders.

    Args:
        parent_folder: Path to the folder containing one subfolder per condition.

    Returns:
        subjects: sorted list of subject IDs (e.g., ["P01", "P02", ...])
        conditions: sorted list of condition names (folder names cleaned)
        subject_data: mapping {subject_id: {condition_name: full_file_path}}

    Raises:
        ScanError: if the folder is invalid or access is denied.
    """
    if not parent_folder or not os.path.isdir(parent_folder):
        raise ScanError(f"Invalid or missing parent folder: {parent_folder}")

    subjects_set = set()
    conditions_set = set()
    subject_data: Dict[str, Dict[str, str]] = {}

    # Pattern to match subject IDs in filenames (optional prefix + P<number>), before .xlsx
    pid_pattern = EXCEL_PID_REGEX

    try:
        for entry in os.listdir(parent_folder):
            entry_path = os.path.join(parent_folder, entry)
            if not os.path.isdir(entry_path):
                continue
            if entry.lower() in IGNORED_FOLDERS:
                continue

            # Clean the folder name: remove leading digits/hyphens/spaces
            condition_clean = re.sub(r'^\d+\s*[-_]*\s*', '', entry).strip()
            if not condition_clean:
                continue

            # Scan for .xlsx files in this condition folder
            pattern = os.path.join(entry_path, "*.xlsx")
            found = False
            for filepath in glob.glob(pattern):
                filename = os.path.basename(filepath)
                match = pid_pattern.search(filename)
                if not match:
                    continue
                pid = match.group(1).upper()
                subjects_set.add(pid)
                conditions_set.add(condition_clean)
                found = True

                # Initialize per-subject dict
                subject_data.setdefault(pid, {})
                # Store or overwrite
                subject_data[pid][condition_clean] = filepath

            # Skip empty conditions without raising
            # (up to caller to interpret missing data)
    except PermissionError as e:
        raise ScanError(f"Permission denied to access folder: {parent_folder}\n{e}")
    except Exception as e:
        raise ScanError(f"Error scanning folder '{parent_folder}': {e}")

    subjects = sorted(subjects_set)
    conditions = sorted(conditions_set)
    return subjects, conditions, subject_data
