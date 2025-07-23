This directory is the NEW PySide6 GUI for the FPVS Toolbox. We want to replicate the functionality of the old 
customtkinter GUI, but with a more modern look and feel. 

# The GUI code should be kept separate from the functionality of the app.

# Instructions for Codex: 

1. When adding new features, please try to keep the code modular and under 500 lines per file. 
2. The functionality of this PySide6 GUI must exactly mirror the customtkinter GUI. 
3. Before making a change to this directory, please review the legacy customtkinter GUI code to ensure it matches.
4. Do not add any reference to tkinter or customtkinter in this directory. This is strictly a PySide6 GUI.


VERY IMPORTANT: **PySide6 Import Reminder**  
_When generating PySide6 code, always import `QAction` from `PySide6.QtGui` (e.g. `from PySide6.QtGui import QAction`), 
**not** from `PySide6.QtWidgets`, to avoid the “cannot import name 'QAction'” error._.