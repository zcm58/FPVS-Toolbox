# ruff: noqa: F401,F403,F405
from .advanced_analysis_base import *  # noqa: F401,F403,F405
class AdvancedAnalysisFileOpsMixin:
        def add_source_files(self):
            """Prompt the user for EEG files and add them to the source list."""
    
            files = filedialog.askopenfilenames(
                title="Select EEG Files",
                filetypes=[("EEG files", "*.bdf")],
                parent=self,
            )
            if not files:
                return
            if self.debug_mode:
                logger.debug("Selected %d file(s): %s", len(files), files)
    
            added_count = 0
            for f_path in files:
                if f_path not in self.source_eeg_files:
                    self.source_eeg_files.append(f_path)
                    added_count += 1
    
            if self.debug_mode:
                logger.debug("%d new files will be added", added_count)
    
            if added_count > 0:
                self.source_eeg_files.sort()
                self._update_source_files_listbox()
                self.log(
                    f"Added {added_count} source file(s). Total: {len(self.source_eeg_files)}."
                )
    
        def remove_source_files(self):
            """Remove the files selected in the listbox from the source list."""
    
            selected_indices = self.source_files_listbox.curselection()
            if not selected_indices:
                self.log("No source files selected to remove.")
                return
            if self.debug_mode:
                logger.debug("Indices selected for removal: %s", selected_indices)
    
            removed_file_paths = [self.source_eeg_files[i] for i in selected_indices]
            self.source_eeg_files = [f for i, f in enumerate(self.source_eeg_files) if i not in selected_indices]
    
            if removed_file_paths:
                self._update_source_files_listbox()
                self.log(f"Removed {len(removed_file_paths)} file(s) from source list.")
                self._check_groups_for_removed_files(removed_file_paths)
                if self.debug_mode:
                    logger.debug("Removed file paths: %s", removed_file_paths)
    
        def _update_source_files_listbox(self):
            """Refresh the source files listbox to match ``self.source_eeg_files``."""
    
            self.source_files_listbox.delete(0, tk.END)
            for f_path in self.source_eeg_files:
                self.source_files_listbox.insert(tk.END, Path(f_path).name)
            if self.debug_mode:
                logger.debug("Source file listbox refreshed with %d entries", len(self.source_eeg_files))
    
        def _check_groups_for_removed_files(self, removed_paths: List[str]):
            """
            Updated to reflect user's snippet structure while retaining robust logic.
            Removes deleted EEG files from each group’s file_paths and their mapping sources.
            """
            if self.debug_mode:
                logger.debug("Checking groups for removed files: %s", removed_paths)
            updated_any = False  # Renamed from updated_any_group
            affected_indices = []  # Renamed from affected_group_indices
    
            for idx, group in enumerate(self.defined_groups):  # Using idx, group as per user snippet
                original_file_count = len(group['file_paths'])
                group['file_paths'] = [fp for fp in group['file_paths'] if fp not in removed_paths]
    
                if len(group['file_paths']) != original_file_count:
                    self.log(f"Group '{group['name']}' updated: removed files.")  # Using group['name']
                    updated_any = True
                    affected_indices.append(idx)  # Using affected_indices
                    group['config_saved'] = False
    
                    if 'condition_mappings' in group:
                        new_mappings_for_group = []
                        for mapping_rule in group['condition_mappings']:
                            original_sources_count = len(mapping_rule['sources'])
                            # Prune sources from this rule
                            mapping_rule['sources'] = [
                                src for src in mapping_rule['sources']
                                if src['file_path'] not in removed_paths
                            ]
    
                            if len(mapping_rule['sources']) != original_sources_count:
                                self.log(
                                    f"  Mapping '{mapping_rule['output_label']}' in group '{group['name']}' lost {original_sources_count - len(mapping_rule['sources'])} source(s).")
    
                            # Only keep the rule if it still has sources
                            if mapping_rule['sources']:
                                new_mappings_for_group.append(mapping_rule)
                            elif original_sources_count > 0:  # It had sources, now it doesn't
                                msg = (f"Mapping rule '{mapping_rule['output_label']}' in group "
                                       f"'{group['name']}' lost all its source files and was removed.")
                                self.log(f"Warning: {msg}")
                                CTkMessagebox.CTkMessagebox(
                                    title="Mapping Rule Removed",
                                    message=msg,
                                    icon="warning",
                                    master=self,
                                )
    
                        group['condition_mappings'] = new_mappings_for_group
                        if not group['condition_mappings']:
                            self.log(f"Group '{group['name']}' has no valid mapping rules left after file removal.")
            if updated_any:
                self._update_groups_listbox()
                if self.selected_group_index is not None and self.selected_group_index in affected_indices:
                    self._display_group_configuration()
                self._update_start_processing_button_state()
    
