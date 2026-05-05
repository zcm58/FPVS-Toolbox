This directory is a temporary migration boundary for older Main App modules.
Current active owners should live in `PySide6_App`, `Shared`, or `Performance`.

Instructions for Codex: 

Run boundary checks before reading or editing broadly:

```powershell
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
```

This is migration-boundary code. Targeted refactor edits are allowed, but they must preserve the processing pipeline, processing order, data formats, and exports exactly.

Processing should always occur on a separate thread from the GUI
so that it does not become unresponsive. 

**eeg_preprocessing.py is inactive legacy pipeline code. Active runtime preprocessing imports should use `src/Main_App/processing/preprocess.py`; do not route active callers back through this legacy module. Edit only for a targeted migration/deletion/wrapper task, and do not change preprocessing behavior.**

**post_process.py is high-risk export pipeline code. Edit only for a targeted migration/refactor task, and do not change metric calculation, output formats, filenames, sheet names, or export behavior.**

Legacy GUI files should not be revived unless the user explicitly scopes that
work.
