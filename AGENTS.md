# AGENTS.md

## Repo Purpose

FPVS Toolbox is a Windows-oriented PySide6 desktop application for preprocessing, cleaning, visualizing, and statistically analyzing EEG data from Fast Periodic Visual Stimulation experiments.

## Working Rules

- Think before coding: state assumptions, surface ambiguity, and ask when the safe interpretation is unclear.
- Prefer the smallest behavior-preserving change that solves the task.
- Touch only files required by the task; do not refactor adjacent code opportunistically.
- Preserve existing processing order, data formats, exports, and user workflows unless the task explicitly changes them.
- Prefer executable checks over broad reading. Run the relevant skill script or `python .agents/scripts/audit/agent_audit.py` first, then read only the focused docs needed for failures or context.
- Treat [ARCHITECTURE.md](ARCHITECTURE.md) as the repo map before structural changes; do not read every architecture page by default.
- Start with [docs/agent-index.md](docs/agent-index.md) when choosing skills, scripts, and focused tests.
- For non-trivial refactors, read the active execution plan first. Update architecture docs or the nearest scoped `AGENTS.md` when structure, ownership, boundaries, or workflows change; otherwise state why no doc update was needed.

## Non-Negotiables

- `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` have been retired. Do not recreate them; use purpose-based `Main_App` packages instead.
- Active EEG preprocessing imports should use `src/Main_App/processing/preprocess.py`; this is the current implementation owner.
- Active BDF loading imports should use `src/Main_App/io/load_utils.py`; it delegates to the current shared implementation while the Main App layout is migrated.
- Active Main App GUI imports should use `src/Main_App/gui/`; the main window shell, focused workflow helpers, reusable widgets, style tokens, update manager, and GUI presentation helpers live there.
- Active worker/process-runner imports should use `src/Main_App/workers/`.
- Active project model, project manager, project metadata, projects-root, and preprocessing-settings imports should use `src/Main_App/projects/`.
- Active runtime diagnostics imports should use `src/Main_App/diagnostics/`; repo-evaluation checks belong in `scripts/` or `.agents/skills/`, and manual project probes belong in `scripts/manual_diagnostics/`.
- Source Localization/eLORETA has been removed from active runtime. Do not add GUI, settings, tests, imports, quarantine-tree dependencies, or bundled `fsaverage` MRI template data unless the user explicitly scopes a restoration feature.
- Prefer thin adapters outside protected folders when legacy behavior must be reused.
- Use PySide6 for GUI work. Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports anywhere in repo code.
- Import `QAction` from `PySide6.QtGui` only.
- Do not block the UI thread. Long work must use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly; communicate with signals.
- All project I/O must use the active project root and preserve existing output formats.
- Use structured logging instead of `print` in production code.
- GUI changes need a pytest-qt smoke test or a documented manual smoke test.

## Skills

Repo-local skills live in `.agents/skills/`.

- `pyside6-gui-cleanup`: PySide6 widgets, layouts, dialogs, actions, status UX, workers, and theme cleanup.
- `legacy-boundary-review`: refactors near retired legacy paths, removed-feature boundaries, or historical API boundaries.
- `project-path-audit`: file dialogs, manifests, exports, imports, generated files, and project-root path discipline.
- `pytest-qt-smoke`: pytest-qt smoke coverage for changed PySide6 widgets, signals, and non-blocking UI behavior.
- `cleanup-generated-files`: generated build, cache, temp, and stale local data cleanup.

Run skill-local scripts before manual inspection when they apply:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use the script output to decide what to read next. If a script passes, do not scan broad folders just to confirm the same invariant manually.

## Useful Docs

- Architecture map: [ARCHITECTURE.md](ARCHITECTURE.md)
- Docs knowledge-base map: [docs/README.md](docs/README.md)
- Agent command index: [docs/agent-index.md](docs/agent-index.md)
- Active execution plans: [docs/exec-plans/active/](docs/exec-plans/active/)
- Technical debt tracker: [docs/exec-plans/tech-debt-tracker.md](docs/exec-plans/tech-debt-tracker.md)
- Main App target layout: [docs/architecture/main-app-target-layout.md](docs/architecture/main-app-target-layout.md)
- Module map: [docs/architecture/module-map.md](docs/architecture/module-map.md)
- Protected paths: [docs/architecture/protected-paths.txt](docs/architecture/protected-paths.txt)
- Test selection: [docs/quality/test-selection.md](docs/quality/test-selection.md)
- Verification gates: [docs/quality/verification-gates.md](docs/quality/verification-gates.md)
- Garbage collection: [docs/quality/garbage-collection.md](docs/quality/garbage-collection.md)
- GUI architecture: [docs/architecture/gui.md](docs/architecture/gui.md); canonical active import surface lives in `src/Main_App/gui/`.
- Diagnostics: [docs/architecture/diagnostics.md](docs/architecture/diagnostics.md); canonical runtime import surface lives in `src/Main_App/diagnostics/`.
- BDF loading contract: [docs/architecture/eeg-loading-contract.md](docs/architecture/eeg-loading-contract.md); canonical active import surface lives in `src/Main_App/io/load_utils.py`.
- Workers and threading: [docs/architecture/workers-threading.md](docs/architecture/workers-threading.md); canonical active import surface lives in `src/Main_App/workers/`.
- Project I/O: [docs/architecture/project-io.md](docs/architecture/project-io.md); canonical active import surface lives in `src/Main_App/projects/`.
- Preprocessing contract: [docs/architecture/preprocessing-contract.md](docs/architecture/preprocessing-contract.md); canonical active import surface lives in `src/Main_App/processing/preprocess.py`.
- Pre-ship checklist: [docs/reviews/pre_ship_checklist.md](docs/reviews/pre_ship_checklist.md)
- Legacy quarantine audit: [docs/legacy-quarantine-audit.md](docs/legacy-quarantine-audit.md)

## Standard Verification

Run the narrowest relevant checks first, then broaden when the change affects shared behavior.

```powershell
python .agents/scripts/audit/agent_audit.py
python -m pytest -q
ruff check .
mypy src --strict
```

If a gate cannot run locally, report the command, failure reason, and residual risk.

## Done Means

- Retired `Legacy_App` and `PySide6_App` paths are not recreated.
- Source Localization/eLORETA remains removed from active runtime unless explicitly restored as a new feature.
- PySide6-only GUI imports are preserved.
- UI work remains non-blocking.
- Project-path discipline is preserved.
- Errors are logged and surfaced without freezing the app.
- Tests or documented manual smoke checks cover changed behavior.
- Architecture or agent docs reflect any changed structure, or the handoff explains why no doc update was needed.
