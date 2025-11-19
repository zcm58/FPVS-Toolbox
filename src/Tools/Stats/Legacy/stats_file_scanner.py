# Functions moved from stats.py for file browsing and scanning

import os
import glob
import re
import traceback
from tkinter import filedialog, messagebox

EXCEL_PID_REGEX = re.compile(
    r"(P\d+[A-Za-z]*|Sub\d+[A-Za-z]*|S\d+[A-Za-z]*)",
    re.IGNORECASE,
)

# Folders that should always be ignored when scanning for condition
# subdirectories.  Stored in lower case for case-insensitive matching.
IGNORED_FOLDERS = {".fif files", "loreta results"}


def browse_folder(self):
    current_folder = self.stats_data_folder_var.get()
    initial_dir = current_folder if os.path.isdir(current_folder) else os.path.expanduser("~")
    folder = filedialog.askdirectory(title="Select Parent Folder Containing Condition Subfolders",
                                     initialdir=initial_dir)
    if folder:
        self.stats_data_folder_var.set(folder)
        self.scan_folder()
    else:
        self.log_to_main_app("Folder selection cancelled.")


def scan_folder(self):
    """ Scans folder for PIDs and Conditions """
    parent_folder = self.stats_data_folder_var.get()
    if not parent_folder or not os.path.isdir(parent_folder):
        self.detected_info_var.set("Invalid parent folder selected.")
        self.update_condition_menus([])
        return

    self.log_to_main_app(f"Scanning parent folder: {parent_folder}")
    subjects_set = set()
    conditions_set = set()
    self.subject_data.clear()  # Clear previous data

    # Revised PID pattern:
    # Looks for an optional prefix of letters, then P (case-insensitive) followed by digits.
    # Captures the P and digits part.
    pid_pattern = EXCEL_PID_REGEX

    try:
        for item_name in os.listdir(parent_folder):  # These are expected to be condition subfolders
            item_path = os.path.join(parent_folder, item_name)
            if os.path.isdir(item_path):
                if item_name.lower() in IGNORED_FOLDERS:
                    self.log_to_main_app(f"  Skipping ignored folder '{item_name}'.")
                    continue
                condition_name_raw = item_name
                # Clean condition name (remove leading numbers/hyphens/spaces if any)
                condition_name = re.sub(r'^\d+\s*[-_]*\s*', '', condition_name_raw).strip()
                if not condition_name:
                    self.log_to_main_app(
                        f"  Skipping subfolder '{condition_name_raw}' due to empty name after cleaning.")
                    continue

                self.log_to_main_app(
                    f"  Processing Condition Subfolder: '{condition_name_raw}' as Condition: '{condition_name}'")

                files_in_subfolder = glob.glob(os.path.join(item_path, "*.xlsx"))
                found_files_for_condition = False
                for f_path in files_in_subfolder:
                    excel_filename = os.path.basename(f_path)
                    pid_match = pid_pattern.search(
                        excel_filename)  # Use search to find pattern anywhere before .xlsx

                    if pid_match:
                        pid = pid_match.group(1).upper()  # group(1) is (P\d+)
                        subjects_set.add(pid)
                        conditions_set.add(condition_name)
                        found_files_for_condition = True

                        if pid not in self.subject_data:
                            self.subject_data[pid] = {}

                        if condition_name in self.subject_data[pid]:
                            self.log_to_main_app(
                                f"    Warning: Duplicate Excel file found for Subject {pid}, Condition '{condition_name}'. Overwriting path from '{os.path.basename(self.subject_data[pid][condition_name])}' to '{excel_filename}'")
                        self.subject_data[pid][condition_name] = f_path
                        self.log_to_main_app(
                            f"      Found PID: {pid} in file: {excel_filename} for Condition: {condition_name}")
                    # else: # Optional: log files that don't match the PID pattern
                    # self.log_to_main_app(f"      File '{excel_filename}' does not match PID pattern. Skipping.")

                if not found_files_for_condition:
                    self.log_to_main_app(
                        f"    Warning: No Excel files matching PID pattern (e.g., SCP1_data.xlsx, P01_data.xlsx) found in subfolder '{condition_name_raw}'.")

    except PermissionError as e:
        self.log_to_main_app(f"!!! Permission Error scanning folder: {parent_folder}. {e}")
        messagebox.showerror("Scanning Error",
                             f"Permission denied accessing folder or its contents:\n{parent_folder}\n{e}")
        self.update_condition_menus([])
        return
    except Exception as e:
        self.log_to_main_app(f"!!! Error scanning folder structure: {e}\n{traceback.format_exc()}")
        messagebox.showerror("Scanning Error", f"An unexpected error occurred during scanning:\n{e}")
        self.update_condition_menus([])
        return

    self.subjects = sorted(list(subjects_set))
    self.conditions = sorted(list(conditions_set))

    if not self.conditions or not self.subjects:
        info_text = "Scan complete: No valid condition subfolders or subject Excel files (e.g., P01_data.xlsx, SCP1_data.xlsx) found with recognized PIDs."
        # messagebox.showwarning("Scan Results", info_text) # Can be noisy if expected
    else:
        info_text = f"Scan complete: Found {len(self.subjects)} subjects and {len(self.conditions)} conditions."

    self.log_to_main_app(info_text)
    if self.subjects: self.log_to_main_app(f"Detected Subjects (PIDs): {', '.join(self.subjects)}")
    if self.conditions: self.log_to_main_app(f"Detected Conditions: {', '.join(self.conditions)}")

    self.detected_info_var.set(info_text)
    self.update_condition_menus(self.conditions)

    # Reset pre-calculated data as new files are scanned
    self.all_subject_data.clear()
    self.rm_anova_results_data = None
    self.harmonic_check_results_data.clear()


def update_condition_menus(self, conditions_list):
    current_a = self.condition_A_var.get()
    display_list = conditions_list if conditions_list else ["(Scan Folder)"]
    if current_a not in display_list and display_list:
        self.condition_A_var.set(display_list[0])
    elif not display_list:
        self.condition_A_var.set("(Scan Folder)")
    if self.condA_menu: self.condA_menu.configure(values=display_list)  # Check if widget exists
    self.update_condition_B_options()


def update_condition_B_options(self, *args):
    cond_a = self.condition_A_var.get()
    valid_b = [c for c in self.conditions if c and c != cond_a]
    if not self.conditions:
        valid_b_display = ["(Scan Folder)"]
    elif not valid_b:
        valid_b_display = [
            "(No other conditions)" if cond_a and cond_a != "(Scan Folder)" else "(Select Condition A)"]
    else:
        valid_b_display = valid_b

    current_b = self.condition_B_var.get()
    if self.condB_menu: self.condB_menu.configure(values=valid_b_display)  # Check if widget exists
    if current_b not in valid_b_display or current_b == cond_a:
        self.condition_B_var.set(valid_b_display[0] if valid_b_display else "")
