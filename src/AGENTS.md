Instructions for Codex: 

Before broad manual inspection, run the relevant executable check:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use those results to decide what to read next. Do not scan unrelated source folders when a skill script already proves the invariant.

If you are instructed to make edits in a specific directory that will not affect other directories, please review 
the AGENTS.md file in that directory for specific instructions. To save time, you do not have to review the AGENTS.md
file of other directories if your edits will not affect them. If your edits will affect other directories, please review 
the AGENTS.md file in each directory for specific instructions before making major edits. 

In general, the app GUI should not be altered significantly unless a new button or
toolbar option is needed when adding new features.

`src/main.py` is the launcher for the PySide6 application. Active Main App code
now belongs in purpose-based packages under `Main_App` such as `gui`,
`processing`, `projects`, `workers`, `io`, `diagnostics`, and `exports`.
Do not add new `PySide6_App` or `Legacy_App` imports or files.


When adding new features, please try to keep the code modular and under 500 lines per file. You are allowed to import
functions from other files into the main window shell where needed, but please do not add new functions to the main_window.py file.
Do not add Tkinter, CustomTkinter, or CTkMessagebox imports; the active UI toolkit is PySide6 only.
