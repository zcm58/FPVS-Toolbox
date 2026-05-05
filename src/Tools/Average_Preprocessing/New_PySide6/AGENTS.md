In the New_PySide6 directory of the Average_Preprocessing tool, we are working on a new GUI using PySide6. 
Preserve the current PySide6 workflows unless a task explicitly changes behavior. Use only UI-agnostic helpers from
Tools/Average_Preprocessing/Legacy, such as processing core functions. Do not add Tkinter, CustomTkinter, or
CTkMessagebox imports.

Before broad manual inspection, run:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
```

Use script output to decide what to read next.
