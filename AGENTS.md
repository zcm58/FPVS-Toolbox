# AGENTS.md

## Repo Purpose

FPVS Toolbox is a Windows-oriented PySide6 desktop application for preprocessing, cleaning, visualizing, and statistically analyzing EEG data from Fast Periodic Visual Stimulation experiments.

## Working Rules

- Think before coding: state assumptions, surface ambiguity, and ask when the safe interpretation is unclear.
- Prefer the smallest behavior-preserving change that solves the task.
- Touch only files required by the task; do not refactor adjacent code opportunistically.
- Preserve existing processing order, data formats, exports, and user workflows unless the task explicitly changes them.
- Prefer executable checks over broad reading. Run the relevant skill script or `python scripts/agent_audit.py` first, then read only the focused docs needed for failures or context.
- Treat [ARCHITECTURE.md](ARCHITECTURE.md) as the repo map before structural changes; do not read every architecture page by default.
- Start with [docs/agent-index.md](docs/agent-index.md) when choosing skills, scripts, and focused tests.

## Non-Negotiables

- Do not edit `src/Main_App/Legacy_App/**` unless the user explicitly asks.
- Treat Source Localization as quarantined dead code. Do not revive `src/Tools/SourceLocalization/**` or `src/quarantine/Tools/LORETA/SourceLocalization/**` unless explicitly asked.
- Prefer thin adapters outside protected folders when legacy behavior must be reused.
- Use PySide6 for GUI work. Do not introduce CustomTkinter.
- Import `QAction` from `PySide6.QtGui` only.
- Do not block the UI thread. Long work must use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly; communicate with signals.
- All project I/O must use the active project root and preserve existing output formats.
- Use structured logging instead of `print` in production code.
- GUI changes need a pytest-qt smoke test or a documented manual smoke test.

## Skills

Repo-local skills live in `.agents/skills/`.

- `pyside6-gui-cleanup`: PySide6 widgets, layouts, dialogs, actions, status UX, workers, and theme cleanup.
- `legacy-boundary-review`: refactors near protected legacy code or legacy API boundaries.
- `project-path-audit`: file dialogs, manifests, exports, imports, generated files, and project-root path discipline.
- `pytest-qt-smoke`: pytest-qt smoke coverage for changed PySide6 widgets, signals, and non-blocking UI behavior.

Run skill-local scripts before manual inspection when they apply:

```powershell
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use the script output to decide what to read next. If a script passes, do not scan broad folders just to confirm the same invariant manually.

## Useful Docs

- Architecture map: [ARCHITECTURE.md](ARCHITECTURE.md)
- Agent command index: [docs/agent-index.md](docs/agent-index.md)
- Module map: [docs/architecture/module-map.md](docs/architecture/module-map.md)
- Protected paths: [docs/architecture/protected-paths.txt](docs/architecture/protected-paths.txt)
- Test selection: [docs/quality/test-selection.md](docs/quality/test-selection.md)
- Verification gates: [docs/quality/verification-gates.md](docs/quality/verification-gates.md)
- Pre-ship checklist: [docs/reviews/pre_ship_checklist.md](docs/reviews/pre_ship_checklist.md)
- Legacy quarantine audit: [docs/legacy-quarantine-audit.md](docs/legacy-quarantine-audit.md)

## Standard Verification

Run the narrowest relevant checks first, then broaden when the change affects shared behavior.

```powershell
python scripts/agent_audit.py
python -m pytest -q
ruff check .
mypy src --strict
```

If a gate cannot run locally, report the command, failure reason, and residual risk.

## Done Means

- Protected legacy modules remain untouched or the user explicitly approved the edit.
- Source Localization remains quarantined dead code unless explicitly restored.
- PySide6-only GUI imports are preserved.
- UI work remains non-blocking.
- Project-path discipline is preserved.
- Errors are logged and surfaced without freezing the app.
- Tests or documented manual smoke checks cover changed behavior.
