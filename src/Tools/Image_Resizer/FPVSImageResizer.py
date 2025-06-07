# FPVSImageResizer.py

import os
import sys
import subprocess
import threading
import time

import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image, ImageOps

# layout constants
PAD_X = 8
PAD_Y = 8
CORNER_RADIUS = 8

# === Image processing logic ===
def process_images_in_folder(input_folder, output_folder,
                             target_width, target_height,
                             desired_ext, update_callback,
                             cancel_flag, overwrite_all=False):
    valid_exts = [".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff"]
    files = [f for f in os.listdir(input_folder)
             if os.path.isfile(os.path.join(input_folder, f))]
    total_files = len(files)
    processed = 0

    skip_details = []
    write_failures = []

    for file in files:
        if cancel_flag():
            update_callback("Processing cancelled.\n", processed, total_files)
            return skip_details, write_failures, processed

        file_path = os.path.join(input_folder, file)
        _, ext = os.path.splitext(file)
        ext = ext.lower()

        if ext == ".webp":
            skip_details.append((file, ".webp files are not compatible with PsychoPy and cannot be converted to .jpg, .jpeg, or .png."))
            processed += 1
            update_callback(f"Skipped {file} (unsupported: .webp)\n",
                            processed, total_files)
            continue

        if ext in valid_exts:
            try:
                with Image.open(file_path) as img:
                    img = ImageOps.exif_transpose(img)
                    orig_w, orig_h = img.size
                    scale = max(target_width / orig_w, target_height / orig_h)
                    new_size = (round(orig_w * scale), round(orig_h * scale))
                    resized = img.resize(new_size, Image.Resampling.LANCZOS)
                    left = (new_size[0] - target_width) // 2
                    top = (new_size[1] - target_height) // 2
                    final = resized.crop((left, top,
                                          left + target_width,
                                          top + target_height))
            except Exception as e:
                skip_details.append((file, f"Read error: {e}"))
                processed += 1
                update_callback(f"Could not read {file}: {e}\n",
                                processed, total_files)
                continue

            base, _ = os.path.splitext(file)
            new_name = f"{base} Resized.{desired_ext}"
            out_path = os.path.join(output_folder, new_name)

            if os.path.exists(out_path):
                if not overwrite_all:
                    skip_details.append((file, "File exists"))
                    processed += 1
                    update_callback(f"Skipped {file} (exists)\n",
                                    processed, total_files)
                    continue

            try:
                final.save(out_path)
                processed += 1
                update_callback(f"Processed {file} → {new_name}\n",
                                processed, total_files)
            except Exception as e:
                write_failures.append((file, str(e)))
                processed += 1
                update_callback(f"Error writing {file}: {e}\n",
                                processed, total_files)
        else:
            skip_details.append((file, "Unsupported format"))
            processed += 1
            update_callback(f"Skipped {file} (unsupported)\n",
                            processed, total_files)

    return skip_details, write_failures, processed


# === CustomTkinter UI ===

# Use the application's current appearance mode
ctk.set_default_color_theme("blue")


class FPVSImageResizerCTK(ctk.CTkToplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.title("FPVS Image_Resizer")
        self.geometry("800x600")
        self.cancel_requested = False
        self.input_folder = ""
        self.output_folder = ""
        self._build_ui()

    def _build_ui(self):
        # Title
        title = ctk.CTkLabel(
            self,
            text="FPVS Image_Resizer",
            font=ctk.CTkFont(size=18, weight="bold")
        )
        title.pack(pady=(PAD_Y, 0))

        # Folders card
        self.input_card = ctk.CTkFrame(self, corner_radius=CORNER_RADIUS, fg_color="#f7f9fc")
        self.input_card.pack(fill="x", padx=PAD_X, pady=(PAD_Y, 0))
        self.input_card.grid_columnconfigure(1, weight=1)

        ctk.CTkLabel(
            self.input_card,
            text="Folders",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, columnspan=2, sticky="w", padx=PAD_X, pady=(PAD_Y, 0))

        ctk.CTkButton(
            self.input_card, text="Select Input Folder",
            command=self._select_input
        ).grid(row=1, column=0, padx=PAD_X, pady=PAD_Y)
        self.in_lbl = ctk.CTkLabel(self.input_card, text="not selected", anchor="w")
        self.in_lbl.grid(row=1, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)

        ctk.CTkButton(
            self.input_card, text="Select Output Folder",
            command=self._select_output
        ).grid(row=2, column=0, padx=PAD_X, pady=PAD_Y)
        self.out_lbl = ctk.CTkLabel(self.input_card, text="not selected", anchor="w")
        self.out_lbl.grid(row=2, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)

        # Settings card
        self.settings_card = ctk.CTkFrame(self, corner_radius=CORNER_RADIUS, fg_color="#f7f9fc")
        self.settings_card.pack(fill="x", padx=PAD_X, pady=PAD_Y)
        self.settings_card.grid_columnconfigure(1, weight=1)
        self.settings_card.grid_columnconfigure(3, weight=1)

        ctk.CTkLabel(
            self.settings_card,
            text="Image Size & Format",
            font=ctk.CTkFont(size=14, weight="bold")
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=PAD_X, pady=(PAD_Y, 0))

        ctk.CTkLabel(self.settings_card, text="Width:")\
            .grid(row=1, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.width_entry = ctk.CTkEntry(self.settings_card, width=80)
        self.width_entry.insert(0, "512")
        self.width_entry.grid(row=1, column=1, sticky="we", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(self.settings_card, text="Height:")\
            .grid(row=1, column=2, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.height_entry = ctk.CTkEntry(self.settings_card, width=80)
        self.height_entry.insert(0, "512")
        self.height_entry.grid(row=1, column=3, sticky="we", padx=PAD_X, pady=PAD_Y)

        ctk.CTkLabel(self.settings_card, text="Ext:")\
            .grid(row=2, column=0, sticky="e", padx=PAD_X, pady=PAD_Y)
        self.ext_var = ctk.StringVar(value=".jpg")
        ctk.CTkOptionMenu(
            self.settings_card,
            variable=self.ext_var,
            values=[".jpg", ".png", ".bmp"]
        ).grid(row=2, column=1, padx=PAD_X, pady=PAD_Y)

        self.overwrite_var = ctk.BooleanVar(value=False)
        ctk.CTkCheckBox(
            self.settings_card,
            text="Overwrite existing images",
            variable=self.overwrite_var
        ).grid(row=3, column=0, columnspan=2, sticky="w", padx=PAD_X, pady=PAD_Y)

        ctk.CTkButton(
            self.settings_card, text="Reset Defaults",
            command=self._reset_defaults
        ).grid(row=2, column=3, padx=PAD_X, pady=PAD_Y)

        # Action bar
        action_bar = ctk.CTkFrame(self, fg_color="transparent")
        action_bar.pack(fill="x", padx=PAD_X, pady=(0, PAD_Y))

        self.start_btn = ctk.CTkButton(action_bar, text="Process", command=self._start)
        self.start_btn.pack(side="left", padx=(0, PAD_X))

        self.cancel_btn = ctk.CTkButton(
            action_bar, text="Cancel",
            command=self._cancel, state="disabled"
        )
        self.cancel_btn.pack(side="left", padx=(0, PAD_X))

        self.open_btn = ctk.CTkButton(
            action_bar, text="Open Folder",
            command=self._open_folder
        )
        self.open_btn.pack(side="left", padx=(PAD_X, 0))
        self.open_btn.pack_forget()

        self.time_lbl = ctk.CTkLabel(action_bar, text="Elapsed: 0s")
        self.time_lbl.pack(side="right", padx=(0, PAD_X))

        self.progress = ctk.CTkProgressBar(action_bar)
        self.progress.pack(side="right", fill="x", expand=True, padx=PAD_X)

        # Status log
        self.status = ctk.CTkTextbox(self, height=150, state="disabled")
        self.status.pack(fill="both", expand=True, padx=PAD_X, pady=(0, PAD_Y))

    def _select_input(self):
        folder = filedialog.askdirectory(title="Select Input Folder")
        if folder:
            self.input_folder = folder
            self.in_lbl.configure(text=os.path.basename(folder))

    def _select_output(self):
        if not self.input_folder:
            messagebox.showerror("Error", "Select an Input Folder first.")
            return
        folder = filedialog.askdirectory(title="Select Output Folder")
        if folder:
            # prevent same input/output
            if os.path.abspath(folder) == os.path.abspath(self.input_folder):
                messagebox.showerror(
                    "Error",
                    "Output folder cannot be the same as the input folder."
                )
                return
            self.output_folder = folder
            self.out_lbl.configure(text=os.path.basename(folder))

    def _reset_defaults(self):
        self.width_entry.delete(0, "end")
        self.width_entry.insert(0, "512")
        self.height_entry.delete(0, "end")
        self.height_entry.insert(0, "512")
        self.ext_var.set(".jpg")
        self.overwrite_var.set(False)
        self.time_lbl.configure(text="Elapsed: 0s")
        self.status.configure(state="normal")
        self.status.delete("0.0", "end")
        self.status.configure(state="disabled")

    def _cancel(self):
        self.cancel_requested = True
        self.cancel_btn.configure(state="disabled")

    def _start(self):
        try:
            w = int(self.width_entry.get())
            h = int(self.height_entry.get())
        except ValueError:
            messagebox.showerror("Error", "Width and Height must be integers.")
            return
        if not (self.input_folder and self.output_folder):
            messagebox.showerror("Error", "Select both Input and Output folders.")
            return
        # additional safety
        if os.path.abspath(self.output_folder) == os.path.abspath(self.input_folder):
            messagebox.showerror("Error", "Output folder cannot be the same as the input folder.")
            return

        self.cancel_requested = False
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")

        self.start_time = time.time()
        self.time_lbl.configure(text="Elapsed: 0s")

        threading.Thread(
            target=self._run,
            args=(w, h, self.ext_var.get().strip("."), self.overwrite_var.get()),
            daemon=True
        ).start()

    def _update(self, msg, processed, total):
        self.status.configure(state="normal")
        if msg:
            self.status.insert("end", msg)
            self.status.see("end")
        self.progress.set(processed / total if total else 0)
        if hasattr(self, 'start_time'):
            elapsed = time.time() - self.start_time
            if processed:
                eta = (elapsed / processed) * (total - processed)
                self.time_lbl.configure(
                    text=f"Elapsed: {int(elapsed)}s, ETA: {int(eta)}s")
            else:
                self.time_lbl.configure(text=f"Elapsed: {int(elapsed)}s")
        self.status.configure(state="disabled")

    def _run(self, width, height, ext, overwrite):
        skips, fails, done = process_images_in_folder(
            self.input_folder,
            self.output_folder,
            width, height,
            ext,
            update_callback=self._update,
            cancel_flag=lambda: self.cancel_requested,
            overwrite_all=overwrite
        )
        self.cancel_btn.configure(state="disabled")
        self.open_btn.pack(side="left", padx=PAD_X)

        summary = f"Done: processed {done} files.\n"
        if skips:
            summary += f"\nSkipped {len(skips)} files:\n"
            for f, r in skips:
                summary += f"  - {f}: {r}\n"
        if fails:
            summary += f"\nWrite failures {len(fails)} files:\n"
            for f, e in fails:
                summary += f"  - {f}: {e}\n"
        elapsed = int(time.time() - self.start_time)
        self.time_lbl.configure(text=f"Elapsed: {elapsed}s, ETA: 0s")

        messagebox.showinfo("Processing Summary", summary)

    def _open_folder(self):
        messagebox.showinfo("Reminder", "Please verify your images for quality.")
        if sys.platform.startswith("win"):
            os.startfile(self.output_folder)
        elif sys.platform == "darwin":
            subprocess.call(["open", self.output_folder])
        else:
            subprocess.call(["xdg-open", self.output_folder])


# Optional standalone launch
if __name__ == "__main__":
    import tkinter as tk
    root = tk.Tk()
    root.withdraw()
    FPVSImageResizerCTK(root)
    root.mainloop()
