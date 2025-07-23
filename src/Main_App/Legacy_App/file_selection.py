# -*- coding: utf-8 -*-
"""Mixin used by the GUI to choose EEG files and output folders.
It opens standard selection dialogs, stores the chosen paths and
updates progress details before processing starts."""
import os
import glob
from tkinter import filedialog, messagebox

class FileSelectionMixin:
    def select_save_folder(self):
        folder = filedialog.askdirectory(title="Select Parent Folder for Excel Output")
        if folder:
            self.save_folder_path.set(folder)
            self.log(f"Output folder: {folder}")
        else:
            self.log("Save folder selection cancelled.")

    def update_select_button_text(self):
        """Update the label on the Select EEG File… button to match the current mode."""
        if self.file_mode.get() == "Single":
            self.select_button.configure(text="Select EEG File…")
        else:
            self.select_button.configure(text="Select Folder…")

    def select_data_source(self):
        self.data_paths = []
        # Always operate on BDF files regardless of any UI setting
        self.file_type.set(".BDF")
        file_ext = "*.bdf"
        file_type_desc = ".BDF"
        try:
            if self.file_mode.get() == "Single":
                ftypes = [(f"{file_type_desc} files", file_ext)]

                file_path = filedialog.askopenfilename(title="Select EEG File", filetypes=ftypes)
                if file_path:
                    self.data_paths = [file_path]
                    self.log(f"Selected file: {os.path.basename(file_path)}")
                else:
                    self.log("No file selected.")
            else:
                folder = filedialog.askdirectory(title=f"Select Folder with {file_type_desc} Files")
                if folder:
                    search_path = os.path.join(folder, file_ext)
                    found_files = sorted(glob.glob(search_path))
                    if found_files:
                        self.data_paths = found_files
                        self.log(f"Selected folder: {folder}, Found {len(found_files)} '{file_ext}' file(s).")
                    else:
                        self.log(f"No '{file_ext}' files found in {folder}.")
                        messagebox.showwarning("No Files Found", f"No '{file_type_desc}' files found in:\n{folder}")
                else:
                    self.log("No folder selected.")
        except Exception as e:
            self.log(f"Error selecting data: {e}")
            messagebox.showerror("Selection Error", f"Error during selection:\n{e}")

        self._max_progress = len(self.data_paths) if self.data_paths else 1
        self.progress_bar.set(0)
