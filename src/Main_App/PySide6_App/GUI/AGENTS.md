This directory is the PySide6 GUI for the FPVS Toolbox.

# The GUI code should be kept separate from the functionality of the app.

# Instructions for Codex: 

Before broad manual inspection, run:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
```

Use the script result before manually scanning GUI imports or broad folders.

1. When adding new features, please try to keep the code modular and under 500 lines per file. 
2. Preserve the current PySide6 workflows unless a task explicitly changes behavior.
3. Do not add any reference to Tkinter, CustomTkinter, or CTkMessagebox in this directory. This is strictly a PySide6 GUI.
4. GUI processing should route through the PySide6 process runner; do not reintroduce a fallback that calls legacy preprocessing.


VERY IMPORTANT: **PySide6 Import Reminder**  
_When generating PySide6 code, always import `QAction` from `PySide6.QtGui` (e.g. `from PySide6.QtGui import QAction`), 
**not** from `PySide6.QtWidgets`, to avoid the “cannot import name 'QAction'” error._.
