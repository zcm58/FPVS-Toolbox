The FPVSImageResizer allows the user to resize large amounts of 
images at once to the appropriate size and file extension to be used 
for FPVS experiments. GUI edits are allowed here but do not edit 
the processing code. 

Before broad manual inspection, run:

```powershell
python scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
```

This tool is a PySide6 based GUI. Please ensure that future updates to the image resizer tool respect this 
and suggest improvements to the GUI as needed.
