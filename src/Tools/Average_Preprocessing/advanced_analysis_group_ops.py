# ruff: noqa: F401,F403,F405
from .advanced_analysis_base import *  # noqa: F401,F403,F405
class AdvancedAnalysisGroupOpsMixin:
        def create_new_group(self):
            """Prompt for details and create a new averaging group."""
    
            if self.debug_mode:
                logger.debug("Creating new averaging group")
    
            dlg_name = CTkInputDialog(title="New Averaging Group", text="Enter a name for this averaging group:")
            name = dlg_name.get_input()
            if not name or not name.strip():
                self.log("Group creation cancelled.")
                return
            name = name.strip()
            if self.debug_mode:
                logger.debug("Group name entered: %s", name)
            if any(g['name'] == name for g in self.defined_groups):
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message=f"A group named '{name}' already exists.",
                    icon="cancel",
                    master=self,
                )
                return
    
            id_dlg = CTkInputDialog(title="Event IDs to Average",
                                    text="Enter the event IDs to average within each participant,\nseparated by commas (e.g. 11,12):")
            id_str = id_dlg.get_input()
            if not id_str:
                self.log("Group creation cancelled (no IDs).")
                return
            if self.debug_mode:
                logger.debug("Event IDs input: %s", id_str)
            try:
                ids_to_average = [int(x.strip()) for x in id_str.split(",") if x.strip()]
            except ValueError:
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message="Enter only integers separated by commas.",
                    icon="cancel",
                    master=self,
                )
                return
            if self.debug_mode:
                logger.debug("Parsed event IDs: %s", ids_to_average)
            if not ids_to_average:
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message="Enter at least one event ID.",
                    icon="cancel",
                    master=self,
                )
                return
    
            if not self.source_eeg_files:
                CTkMessagebox.CTkMessagebox(
                    title="Error",
                    message="No EEG files selected. Add files first.",
                    icon="cancel",
                    master=self,
                )
                return
    
            mapping_rule = {'output_label': name, 'sources': []}
            for f_path in self.source_eeg_files:
                for event_id_val in ids_to_average:
                    mapping_rule['sources'].append({
                        'file_path': f_path,
                        'original_label': str(event_id_val),
                        'original_id': event_id_val
                    })
            if self.debug_mode:
                logger.debug("Mapping rule for group '%s': %s", name, mapping_rule)
    
            new_grp_data = {
                'name': name,
                'file_paths': list(self.source_eeg_files),
                'condition_mappings': [mapping_rule],
                'averaging_method': self.averaging_method_var.get(),
                'config_saved': True,
                'ui_mapping_rules': []
            }
            self.defined_groups.append(new_grp_data)
            if self.debug_mode:
                logger.debug("New group appended: %s", new_grp_data)
            self._update_groups_listbox()
            self.log(f"Created group '{name}' averaging IDs {ids_to_average} in all {len(self.source_eeg_files)} files.")
            if self.debug_mode:
                logger.debug("Group '%s' created with IDs %s", name, ids_to_average)
    
            new_group_idx = len(self.defined_groups) - 1
            self.groups_listbox.selection_clear(0, tk.END)
            self.groups_listbox.selection_set(new_group_idx)
            self.on_group_select(None)
            self._update_start_processing_button_state()
    
        def delete_selected_group(self):
            """Remove the currently selected averaging group."""
    
            if self.selected_group_index is None:
                self.log("No group selected to delete.")
                return
    
            group_name_to_delete = self.defined_groups[self.selected_group_index]['name']
            msg_box = CTkMessagebox.CTkMessagebox(
                title="Confirm Delete",
                message=f"Delete group '{group_name_to_delete}'?",
                icon="question",
                option_1="No",
                option_2="Yes",
                master=self,
            )
            if msg_box.get() == "Yes":
                del self.defined_groups[self.selected_group_index]
                self._update_groups_listbox()
                self.log(f"Deleted group: {group_name_to_delete}")
                self.selected_group_index = None
                self._clear_group_config_display()
                self._update_start_processing_button_state()
                if self.debug_mode:
                    logger.debug("Group '%s' deleted", group_name_to_delete)
    
        def rename_selected_group(self) -> None:
            """Prompt the user to rename the currently selected group."""
    
            if self.selected_group_index is None:
                self.log("No group selected to rename.")
                return
    
            current_name = self.defined_groups[self.selected_group_index]['name']
            dlg = CTkInputDialog(
                title="Rename Averaging Group",
                text=f"Enter a new name for '{current_name}':",
            )
            new_name = dlg.get_input()
            if not new_name or not new_name.strip():
                return
            new_name = new_name.strip()
    
            # ensure name is unique
            for i, grp in enumerate(self.defined_groups):
                if i != self.selected_group_index and grp['name'] == new_name:
                    CTkMessagebox.CTkMessagebox(
                        title="Error",
                        message=f"A group named '{new_name}' already exists.",
                        icon="cancel",
                        master=self,
                    )
                    return
    
            self.defined_groups[self.selected_group_index]['name'] = new_name
            self.defined_groups[self.selected_group_index]['config_saved'] = False
            self._update_groups_listbox()
            self._display_group_configuration()
            self.log(f"Renamed group to '{new_name}'.")
    
        def _update_groups_listbox(self):
            current_selection = self.groups_listbox.curselection()
    
            self.groups_listbox.delete(0, tk.END)
            for g_data in self.defined_groups:
                status_str = "" if g_data.get('config_saved', False) else " (Unsaved)"
                display_text = f"{g_data['name']} ({len(g_data['file_paths'])} files){status_str}"
                self.groups_listbox.insert(tk.END, display_text)
            if self.debug_mode:
                logger.debug("Groups listbox updated with %d groups", len(self.defined_groups))
    
            if current_selection and current_selection[0] < self.groups_listbox.size():
                self.groups_listbox.selection_set(current_selection[0])
                self.groups_listbox.activate(current_selection[0])
    
        def on_group_select(self, event: Optional[tk.Event] = None):
            selected_indices = self.groups_listbox.curselection()
            if not selected_indices:
                return
            if self.debug_mode:
                logger.debug("Group listbox selection changed: %s", selected_indices)
    
            newly_selected_idx = selected_indices[0]
            if self.selected_group_index != newly_selected_idx:
                self.selected_group_index = newly_selected_idx
                self.log(
                    f"Selected group: {self.defined_groups[newly_selected_idx]['name']}"
                )
    
            self._display_group_configuration()
            self.save_group_config_button.configure(
                state="normal" if not self.defined_groups[newly_selected_idx].get('config_saved', True) else "disabled"
            )
    
        def _clear_group_config_display(self):
            for widget in self.group_config_frame.winfo_children():
                widget.destroy()
            for widget in self.condition_mapping_frame.winfo_children():
                widget.destroy()
            ctk.CTkLabel(self.condition_mapping_frame, text="Select or create a group.") \
                .pack(padx=PAD_X, pady=PAD_Y)
            self.save_group_config_button.configure(state="disabled")
            self.averaging_method_var.set("Pool Trials")
    
        def _display_group_configuration(self):
            self._clear_group_config_display()
            idx = self.selected_group_index
            if idx is None or idx >= len(self.defined_groups):
                return
            if self.debug_mode:
                logger.debug("Displaying configuration for group index %s", idx)
    
            group_data = self.defined_groups[idx]
            ctk.CTkLabel(self.group_config_frame, text=f"Group Name: {group_data['name']}", font=ctk.CTkFont(weight="bold")) \
                .pack(anchor="w", padx=PAD_X, pady=PAD_Y)
    
            files_display_text = "\n".join(
                Path(fp).name for fp in group_data['file_paths']
            )
            if not files_display_text:
                files_display_text = "No files currently in this group."
            ctk.CTkLabel(self.group_config_frame, text="Files in this group:\n" + files_display_text, justify=tk.LEFT) \
                .pack(anchor="w", padx=PAD_X)
    
            for widget in self.condition_mapping_frame.winfo_children():
                widget.destroy()
    
            if group_data.get('condition_mappings'):
                mapping_rule = group_data['condition_mappings'][0]
                ctk.CTkLabel(self.condition_mapping_frame,
                             text=f"Averaging Rule: Output Label '{mapping_rule['output_label']}'",
                             font=ctk.CTkFont(weight="bold")) \
                    .pack(anchor="w", padx=PAD_X, pady=(PAD_Y, 0))
    
                ids_averaged = sorted(list(set(src['original_id'] for src in mapping_rule['sources'])))
                ctk.CTkLabel(self.condition_mapping_frame,
                             text=f"  Averages Event IDs: {', '.join(map(str, ids_averaged))} across all files in group.") \
                    .pack(anchor="w", padx=PAD_X)
            else:
                ctk.CTkLabel(self.condition_mapping_frame, text="No mapping rules defined for this group.") \
                    .pack(anchor="w", padx=PAD_X)
    
            self.averaging_method_var.set(group_data.get('averaging_method', 'Pool Trials'))
            self.save_group_config_button.configure(state="normal" if not group_data.get('config_saved') else "disabled")
    
        def _update_current_group_avg_method(self):
            idx = self.selected_group_index
            if idx is None:
                return
    
            group_data = self.defined_groups[idx]
            new_method = self.averaging_method_var.get()
            if group_data.get('averaging_method') != new_method:
                group_data['averaging_method'] = new_method
                group_data['config_saved'] = False
                self.log(f"Averaging method for '{group_data['name']}' changed to '{new_method}'. Needs re-saving.")
                if self.debug_mode:
                    logger.debug("Group '%s' averaging method set to %s", group_data['name'], new_method)
                self._update_groups_listbox()
                self._update_start_processing_button_state()
                self.save_group_config_button.configure(state="normal")
