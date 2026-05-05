This directory contains the core functionality of the FPVS Toolbox. 
The GUI code should be kept separate from the functionality of the app.

Instructions for Codex: 

Run boundary checks before reading or editing broadly:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
```

This is active migration-boundary code. Targeted refactor edits are allowed, but they must preserve the processing pipeline, processing order, data formats, and exports exactly.

Processing should always occur on a separate thread from the GUI
so that it does not become unresponsive. 

**eeg_preprocessing.py is high-risk pipeline code. Edit only for a targeted migration/refactor task, and do not change preprocessing behavior.**

**post_process.py is high-risk export pipeline code. Edit only for a targeted migration/refactor task, and do not change metric calculation, output formats, filenames, sheet names, or export behavior.**

The main_app.py GUI should not be altered in any way unless given specific
instructions to do so.
