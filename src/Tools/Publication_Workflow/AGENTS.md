The Publication_Workflow directory owns the embedded **Publication Workflow**
orchestrator. It guides the user through QC, manual participant-level outlier
decisions, Publication Report generation, and figure handoff.

Rules:

- Keep durable workflow state in `state.py` and project-local artifacts under
  the active project root's `5 - Publication Report` folder.
- Keep `gui.py` as orchestration UI only: it may launch existing workers,
  display statuses, collect manual decisions, and open existing tools, but it
  must not duplicate Publication Report statistics or figure-rendering logic.
- Reuse `Tools.Publication_Report.runner` and `PublicationReportWorker` for
  report/QC computation.
- Manual outlier exclusions are participant-level only in v1.
- Automated IQR flags are candidate review rows only; they must not exclude
  data until the user freezes a decision.
- Workers must communicate by signals only and must not touch widgets.
- Generated paths must stay project-root local. Do not write workflow state to
  app settings or the repository root.
- Do not run offscreen Qt workflows locally.

Focused checks:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Tools\Publication_Workflow\*.py
.\.venv1\Scripts\python.exe -m pytest tests\publication_workflow\test_state.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```
