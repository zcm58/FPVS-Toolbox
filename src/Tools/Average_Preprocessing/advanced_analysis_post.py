# ruff: noqa: F401,F403,F405
from .advanced_analysis_base import *  # noqa: F401,F403,F405
class AdvancedAnalysisPostMixin:
        def _extract_pid_for_group(self, group_data: Dict[str, Any]) -> str:
            """Return a participant identifier extracted from a group's first file."""
    
            if self.debug_mode:
                logger.debug("Extracting PID for group")
    
            file_paths = group_data.get('file_paths', [])
            if not file_paths:
                return "UnknownPID"
    
            base_name = Path(file_paths[0]).stem  # e.g., "mooney_P1"
    
            # Primary Regex (should capture "P1" from "mooney_P1" or "P1_mooney" etc.)
            pid_regex_primary = r"\b(P\d+|S\d+|Sub\d+)\b"  # Added S\d+ as common alternative
            match = re.search(pid_regex_primary, base_name, re.IGNORECASE)
            if match:
                return match.group(1).upper()  # e.g., "P1"
    
            # Fallback 1: Check for patterns like "name_P1" or "name_S1"
            # This is useful if the primary regex \b boundary fails for some reason with underscores
            if '_' in base_name:
                parts = base_name.split('_')
                for part in parts:  # Check all parts, e.g., last part or any part
                    if re.fullmatch(r"(P\d+|S\d+|Sub\d+)", part, re.IGNORECASE):
                        return part.upper()
    
            # Fallback 2: Original cleanup logic (less precise for getting "P1" from "mooneyP1")
            # This will turn "mooney_P1" into "mooneyP1" if above failed.
            cleaned_pid = re.sub(r"(_unamb|_ambig|_mid|_run\d*|_sess\d*|_task\w*|_eeg|_raw|_preproc|_ica).*", "", base_name,
                                 flags=re.IGNORECASE)
            cleaned_pid = re.sub(r"[^A-Za-z0-9_]", "", cleaned_pid)  # Allow underscore in initial cleaned version
    
            # If after initial cleanup, it still looks like "text_P1", try to get "P1"
            if '_' in cleaned_pid:
                parts = cleaned_pid.split('_')
                for part in parts:
                    if re.fullmatch(r"(P\d+|S\d+|Sub\d+)", part, re.IGNORECASE):
                        return part.upper()
    
            # Final cleanup if no P<number> pattern was extracted
            cleaned_pid_alphanum_only = re.sub(r"[^A-Za-z0-9]", "", cleaned_pid)
            result_pid = cleaned_pid_alphanum_only if cleaned_pid_alphanum_only else base_name
            if self.debug_mode:
                logger.debug("Extracted PID: %s", result_pid)
            return result_pid
    
        def save_groups_to_file(self) -> None:
            """Save ``self.defined_groups`` to a JSON file chosen by the user."""
    
            file_path = filedialog.asksaveasfilename(
                defaultextension=".json",
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                parent=self,
                title="Save Group Configuration",
            )
            if not file_path:
                return
    
            try:
                with open(file_path, "w", encoding="utf-8") as f:
                    json.dump(self.defined_groups, f, indent=2)
                self.log(f"Saved group configuration to {file_path}.")
            except Exception as e:  # pragma: no cover - display error to user
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"Failed to save configuration:\n{e}",
                    icon="cancel",
                    master=self,
                )
                if self.debug_mode:
                    logger.error("Failed to save config: %s", traceback.format_exc())
    
        def load_groups_from_file(self) -> None:
            """Load groups from a JSON file and refresh the UI."""
    
            file_path = filedialog.askopenfilename(
                filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
                parent=self,
                title="Load Group Configuration",
            )
            if not file_path:
                return
    
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
    
                if not isinstance(data, list) or not all(isinstance(g, dict) for g in data):
                    raise ValueError("Invalid configuration structure")
    
                required = {"name", "file_paths", "condition_mappings", "averaging_method", "config_saved"}
                for group in data:
                    if not required.issubset(group.keys()):
                        raise ValueError("Configuration missing required keys")
    
                self.defined_groups = data
                # Update source files based on union of all group file paths
                all_paths = {fp for g in self.defined_groups for fp in g.get("file_paths", [])}
                self.source_eeg_files = sorted(all_paths)
    
                self.selected_group_index = None
                self._update_source_files_listbox()
                self._update_groups_listbox()
                self._clear_group_config_display()
                self._update_start_processing_button_state()
                self.log(f"Loaded {len(self.defined_groups)} group(s) from {file_path}.")
            except Exception as e:  # pragma: no cover - display error to user
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"Failed to load configuration:\n{e}",
                    icon="cancel",
                    master=self,
                )
                if self.debug_mode:
                    logger.error("Failed to load config: %s", traceback.format_exc())
    
        def _on_close(self):
            if self.processing_thread and self.processing_thread.is_alive():
                msg_box = CTkMessagebox.CTkMessagebox(
                    title="Confirm Close",
                    message="Processing is ongoing. Stop and close?",
                    icon="question",
                    option_1="No",
                    option_2="Yes",
                    master=self,
                )
                if msg_box.get() == "Yes":
                    self.stop_processing()
                    self.after(1000, self._force_destroy)
                else:
                    return
            else:
                if self.debug_mode:
                    logger.debug("Window closed without active processing")
                self.destroy()
    
        def _force_destroy(self):
            if self.processing_thread and self.processing_thread.is_alive():
                self.log("Thread still active after timeout. Forcing close.")
                if self.debug_mode:
                    logger.debug("Force destroying window while thread active")
            self.destroy()
    
