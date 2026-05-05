In the backend directory, please ensure that only the functionality and the core logic of the FPVS Toolbox is
present. The GUI code should be kept out of this directory as much as possible and instead be placed in the GUI directory.

Before broad manual inspection, run relevant executable checks:

```powershell
python scripts/agent_audit.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use script output to decide what to read next.

`preprocess.py` is the active EEG preprocessing owner. Refactors may reorganize
files only when they preserve the documented pipeline order and verification in
`docs/architecture/preprocessing-contract.md`; do not route active runtime code
through the legacy `eeg_preprocessing.py` module.

[]: # 
[]: # The backend code should be modular and easy to read. 
[]: # 
[]: # The backend code should not be more than 500 lines per file. 
[]:
[]: # 
[]: # The backend code should not contain any GUI-related functionality.
[]: # 
[]: # The backend code should be designed to be easily testable and maintainable.
[]: # 
[]: # The backend code should not contain any hardcoded paths or filenames.
[]: # 
[]: # The backend code should be designed to be easily extensible for future updates.
[]: # 
[]: # 
