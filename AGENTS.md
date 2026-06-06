# AGENTS.md

## Repo Purpose

FPVS Toolbox is a Windows-oriented PySide6 desktop application for preprocessing, cleaning, visualizing, and statistically analyzing EEG data from Fast Periodic Visual Stimulation experiments.

## Working Rules

- Think before coding: state assumptions, surface ambiguity, and ask when the safe interpretation is unclear.
- Prefer the smallest behavior-preserving change that solves the task.
- Touch only files required by the task; do not refactor adjacent code opportunistically.
- Preserve existing processing order, data formats, exports, and user workflows unless the task explicitly changes them.
- Prefer executable checks over broad reading. Activate `.\.venv1` first, then run the relevant skill script or `python .agents/scripts/audit/agent_audit.py` before reading only the focused docs needed for failures or context.
- Treat [ARCHITECTURE.md](ARCHITECTURE.md) as the repo map before structural changes; do not read every architecture page by default.
- Start with [docs/agent/agent-index.md](docs/agent/agent-index.md) when choosing skills, scripts, and focused tests.
- For non-trivial refactors, read the active execution plan first. Update architecture docs or the nearest scoped `AGENTS.md` when structure, ownership, boundaries, or workflows change; otherwise state why no doc update was needed.

## Non-Negotiables

- `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` have been retired. Do not recreate them; use purpose-based `Main_App` packages instead.
- Active EEG preprocessing imports should use `src/Main_App/processing/preprocess.py`; this is the current implementation owner.
- Active BDF loading imports should use `src/Main_App/io/load_utils.py`; it delegates to the current shared implementation while the Main App layout is migrated.
- Active Main App GUI imports should use `src/Main_App/gui/`; the main window shell, focused workflow helpers, reusable widgets, style tokens, update manager, and GUI presentation helpers live there.
- New or migrated GUI surfaces should start from `src/Main_App/gui/components/` for shared cards, buttons, forms, status banners, window/dialog shells, action rows, and message helpers before adding local UI primitives.
- Subsection headers should use `Main_App.gui.components.SubsectionHeaderLabel`; edit shared subsection-header font, weight, color, and padding in `src/Main_App/gui/widgets/labels.py`, not per-surface QSS.
- Avoid card-within-card GUI designs unless the user explicitly asks for that visual treatment. `SectionCard` should frame a top-level subsection; tab panes, splitters, setup areas, and other parent layout containers should stay visually flat when they contain section cards.
- Active worker/process-runner imports should use `src/Main_App/workers/`.
- Active project model, project manager, project metadata, projects-root, and preprocessing-settings imports should use `src/Main_App/projects/`.
- Active runtime diagnostics imports should use `src/Main_App/diagnostics/`; repo-evaluation checks belong in `scripts/` or `.agents/skills/`, and manual project probes belong in `scripts/manual_diagnostics/`.
- Source Localization/eLORETA has been removed from active runtime. Do not add GUI, settings, tests, imports, quarantine-tree dependencies, or bundled `fsaverage` MRI template data unless the user explicitly scopes a restoration feature.
- The new LORETA Visualizer work is a separate source-localization visualization branch under `src/Tools/LORETA_Visualizer/`, not a revival of `src/Tools/SourceLocalization/**`. Keep visualizer rendering, mesh helpers, payload adapters, demo data, and tool-local docs in that directory; preserve the boundary where future source-localization calculations produce prepared values and visualizer helpers bridge them into renderer payloads.
- The active preprocessing order is locked to match the Volfart et al. (2021) FPVS implementation decision: initial reference, drop reference channels, optional channel limit preserving stim, FIR filter, downsample, kurtosis/interpolation, final average reference. Do not reorder filtering and downsampling, change FIR duration scaling, or remove the order/version fingerprint guards unless the user explicitly requests a statistical-method change and updates `docs/agent/architecture/preprocessing-contract.md`, `docs/user/reference/methods-reporting-checklist.md`, and the focused processing-order tests.
- The Stats default group-level significant-harmonics method (Volfart/Retter/Rossion style) is locked behavior. It selects one common non-base oddball harmonic list from grand-averaged `FullFFT Amplitude (uV)` spectra across all scalp electrodes, using z > 1.64 against neighboring-bin noise. Neighboring noise is +/-10 FFT bins around the target after excluding target-1, target, target+1, then dropping the single minimum and single maximum finite amplitude values before computing mean and population SD. Do not change this selection, threshold, electrode scope, noise-window, min/max exclusion, exact-column requirement, or uniform application across participants, conditions, and ROIs unless the user explicitly requests a statistical-method change.
- Prefer thin adapters outside protected folders when legacy behavior must be reused.
- Use PySide6 for GUI work. Do not introduce Tkinter, CustomTkinter, or CTkMessagebox imports anywhere in repo code.
- Import `QAction` from `PySide6.QtGui` only.
- Do not block the UI thread. Long work must use `QThread` or `QRunnable` with `QThreadPool`.
- Workers must not touch widgets directly; communicate with signals.
- All project I/O must use the active project root and preserve existing output formats.
- Use structured logging instead of `print` in production code.
- Do not run offscreen Qt workflows in this repo. Do not set
  `QT_QPA_PLATFORM=offscreen`, do not run pytest-qt/offscreen GUI tests, and
  do not launch ad-hoc offscreen Qt scripts; they can freeze or hang
  indefinitely in this Windows environment.
- GUI changes need non-GUI checks plus a documented visible/manual smoke path.
  Use `py_compile`, `ruff`, GUI import audits, and agent audits locally; leave
  pytest-qt/offscreen GUI targets for explicit user-approved environments only.

## Skills

Repo-local skills live in `.agents/skills/`.

- `pyside6-gui-cleanup`: PySide6 widgets, layouts, dialogs, actions, status UX, workers, and theme cleanup.
- `legacy-boundary-review`: refactors near retired legacy paths, removed-feature boundaries, or historical API boundaries.
- `project-path-audit`: file dialogs, manifests, exports, imports, generated files, and project-root path discipline.
- `pytest-qt-smoke`: maintain pytest-qt smoke coverage definitions, but do not run pytest-qt/offscreen GUI tests locally unless the user explicitly approves a safe visible test environment.
- `cleanup-generated-files`: generated build, cache, temp, and stale local data cleanup.

Run skill-local scripts before manual inspection when they apply:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Use the script output to decide what to read next. If a script passes, do not scan broad folders just to confirm the same invariant manually.

Globally installed Codex skills are secondary to these repo-local rules. Use
`docs/agent/agent-index.md` for the narrow list that applies here; do not route
normal FPVS Toolbox work through React, Vercel, React Native, or web-app skills
unless the repo gains that scoped surface in the task being performed. Global
skills never replace `.\.venv1`, repo-local audits, no-offscreen Qt limits, or
the focused verification gates below.

## Useful Docs

- Architecture map: [ARCHITECTURE.md](ARCHITECTURE.md)
- Docs knowledge-base map: [docs/agent/README.md](docs/agent/README.md)
- Agent command index: [docs/agent/agent-index.md](docs/agent/agent-index.md)
- Active execution plans: [docs/agent/exec-plans/active/](docs/agent/exec-plans/active/)
- Technical debt tracker: [docs/agent/exec-plans/tech-debt-tracker.md](docs/agent/exec-plans/tech-debt-tracker.md)
- Main App target layout: [docs/agent/architecture/main-app-target-layout.md](docs/agent/architecture/main-app-target-layout.md)
- Module map: [docs/agent/architecture/module-map.md](docs/agent/architecture/module-map.md)
- Protected paths: [docs/agent/architecture/protected-paths.txt](docs/agent/architecture/protected-paths.txt)
- Test selection: [docs/agent/quality/test-selection.md](docs/agent/quality/test-selection.md)
- Verification gates: [docs/agent/quality/verification-gates.md](docs/agent/quality/verification-gates.md)
- Garbage collection: [docs/agent/quality/garbage-collection.md](docs/agent/quality/garbage-collection.md)
- GUI architecture: [docs/agent/architecture/gui.md](docs/agent/architecture/gui.md); canonical active import surface lives in `src/Main_App/gui/`.
- Diagnostics: [docs/agent/architecture/diagnostics.md](docs/agent/architecture/diagnostics.md); canonical runtime import surface lives in `src/Main_App/diagnostics/`.
- BDF loading contract: [docs/agent/architecture/eeg-loading-contract.md](docs/agent/architecture/eeg-loading-contract.md); canonical active import surface lives in `src/Main_App/io/load_utils.py`.
- Workers and threading: [docs/agent/architecture/workers-threading.md](docs/agent/architecture/workers-threading.md); canonical active import surface lives in `src/Main_App/workers/`.
- Project I/O: [docs/agent/architecture/project-io.md](docs/agent/architecture/project-io.md); canonical active import surface lives in `src/Main_App/projects/`.
- Preprocessing contract: [docs/agent/architecture/preprocessing-contract.md](docs/agent/architecture/preprocessing-contract.md); canonical active import surface lives in `src/Main_App/processing/preprocess.py`.
- Pre-ship checklist: [docs/agent/reviews/pre_ship_checklist.md](docs/agent/reviews/pre_ship_checklist.md)
- Legacy quarantine audit: [docs/agent/architecture/legacy-quarantine-audit.md](docs/agent/architecture/legacy-quarantine-audit.md)
- LORETA Visualizer tool docs: [src/Tools/LORETA_Visualizer/AGENTS.md](src/Tools/LORETA_Visualizer/AGENTS.md) and [src/Tools/LORETA_Visualizer/ARCHITECTURE.md](src/Tools/LORETA_Visualizer/ARCHITECTURE.md)

## Standard Verification

Run the narrowest relevant checks first, then broaden when the change affects shared behavior.

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python -m pytest -q
ruff check .
```

For GUI changes, skip offscreen pytest-qt targets locally and report the
manual/visible smoke path instead. If any other gate cannot run locally, report
the command, failure reason, and residual risk.

## Done Means

- Retired `Legacy_App` and `PySide6_App` paths are not recreated.
- Source Localization/eLORETA remains removed from active runtime unless explicitly restored as a new feature.
- New LORETA Visualizer work preserves rendering/calculation separation and does not use retired Source Localization code as precedent.
- PySide6-only GUI imports are preserved.
- UI work remains non-blocking.
- Project-path discipline is preserved.
- Errors are logged and surfaced without freezing the app.
- Non-GUI checks or documented visible/manual smoke checks cover changed behavior.
- Architecture or agent docs reflect any changed structure, or the handoff explains why no doc update was needed.
