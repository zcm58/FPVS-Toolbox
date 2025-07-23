import customtkinter as ctk

class ROISettingsEditor:
    def __init__(self, parent, initial_pairs):
        self.parent = parent
        self.entries = []
        self.scroll = ctk.CTkScrollableFrame(parent, label_text="")
        self.scroll.grid_columnconfigure(0, weight=1)
        self.scroll.grid_columnconfigure(1, weight=1)
        for name, electrodes in initial_pairs:
            self.add_entry(name, ','.join(electrodes))
        if not initial_pairs:
            self.add_entry()

    def add_entry(self, name="", electrodes=""):
        frame = ctk.CTkFrame(self.scroll, fg_color="transparent")
        frame.pack(fill="x", pady=1, padx=1)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_columnconfigure(1, weight=1)
        name_entry = ctk.CTkEntry(frame, placeholder_text="ROI Name")
        name_entry.insert(0, name)
        name_entry.grid(row=0, column=0, sticky="ew", padx=(0,5))
        elec_entry = ctk.CTkEntry(frame, placeholder_text="Electrodes comma sep")
        elec_entry.insert(0, electrodes)
        elec_entry.grid(row=0, column=1, sticky="ew", padx=(0,5))
        btn = ctk.CTkButton(frame, text="✕", width=28, command=lambda f=frame: self.remove_entry(f))
        btn.grid(row=0, column=2, sticky="e")
        self.entries.append({'frame': frame, 'name': name_entry, 'elec': elec_entry, 'button': btn})

    def remove_entry(self, frame):
        for i, ent in enumerate(self.entries):
            if ent['frame'] is frame:
                if frame.winfo_exists():
                    frame.destroy()
                self.entries.pop(i)
                break
        if not self.entries:
            self.add_entry()

    def get_pairs(self):
        pairs = []
        for ent in self.entries:
            name = ent['name'].get().strip()
            electrodes = [e.strip().upper() for e in ent['elec'].get().split(',') if e.strip()]
            if name and electrodes:
                pairs.append((name, electrodes))
        return pairs

    def set_pairs(self, pairs):
        for ent in self.entries:
            if ent['frame'].winfo_exists():
                ent['frame'].destroy()
        self.entries.clear()
        for name, electrodes in pairs:
            self.add_entry(name, ','.join(electrodes))
        if not pairs:
            self.add_entry()
