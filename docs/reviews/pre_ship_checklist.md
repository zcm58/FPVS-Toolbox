# Pre-Ship Checklist

Use this before handing off non-trivial changes.

- Run the relevant command from `docs/agent-index.md` before broad manual inspection.
- The diff is limited to the requested behavior and direct support files.
- Non-trivial refactors checked the relevant active plan in `docs/exec-plans/active/`.
- Protected legacy folders are unchanged unless explicitly approved.
- Source Localization remains quarantined dead code unless explicitly restored.
- GUI work uses PySide6 only and imports `QAction` from `PySide6.QtGui`.
- Long work is off the UI thread and workers do not touch widgets directly.
- Project file I/O uses the active project root and handles dialog Cancel paths.
- Existing data formats, filenames, sheet names, and processing order are preserved.
- Production diagnostics use logging rather than `print`.
- Targeted tests or smoke steps cover the changed behavior.
- Architecture docs or the nearest scoped `AGENTS.md` were updated for changed structure, ownership, boundaries, workflows, or verification expectations.
- If no doc update was needed, the handoff or active execution plan explains why.
- Any skipped verification is explained with residual risk.
