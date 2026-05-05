# ARCHITECTURE.md

## Purpose

This file is the top-level map for agents working in FPVS Toolbox. Keep durable architecture details here or in linked docs, not in long prompts.

Use executable checks before broad reading:

```powershell
python scripts/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Read [docs/agent-index.md](docs/agent-index.md) for the compact skill/script/test map. Read the focused architecture pages below only when the task touches that area or a check reports a relevant issue.

## Execution Plans

Durable refactor and feature plans live under [docs/exec-plans](docs/exec-plans/). Read active plans before changing the areas they cover, then keep the plan's progress, decisions, and verification notes current as work lands. Future plans record approved ideas that are not active work yet; read them only when scoping or starting the matching effort.

Structural refactors must update this file, the relevant focused architecture page, or the nearest scoped `AGENTS.md` in the same PR when they change ownership, module boundaries, workflows, or verification expectations. If no architecture or agent doc changes are needed, record that in the PR handoff or active execution plan.

## Application Shape

FPVS Toolbox is a Windows-oriented desktop application built around PySide6 GUI entry points, processing backends, and analysis tools under `src/`.

Primary areas:

- `src/Main_App/PySide6_App/`: current PySide6 application shell, GUI, project management, processing controllers, and adapters. `GUI/main_window.py` has been appropriately downsized into the Main Window shell/coordinator; do not target it for further refactor unless the user explicitly scopes that work. New shell-specific GUI behavior should go into focused helper modules instead of growing `main_window.py`.
- `src/Main_App/gui/`: canonical Main App GUI import surface. It owns focused GUI workflow helpers such as project open/create/save orchestration, processing run start/stop/finalization, and post-export completion handling, and delegates remaining main-window, settings-panel, menu, sidebar, icon, style-token, and update-manager imports to the existing PySide6 GUI implementation.
- `src/Main_App/processing/`: canonical Main App processing import surface. It currently delegates preprocessing to the existing PySide6 backend implementation while the repo moves toward purpose-based Main App folders.
- `src/Main_App/io/`: canonical Main App I/O import surface. It currently delegates BDF loading to the existing shared implementation while the repo moves toward purpose-based Main App folders.
- `src/Main_App/projects/`: canonical Main App project import surface. It currently delegates project model, metadata, manager, projects-root, and preprocessing-settings behavior to existing implementations.
- `src/Main_App/workers/`: canonical Main App worker import surface. It currently delegates Qt worker and process-runner behavior to existing PySide6 and Performance implementations.
- `src/Main_App/diagnostics/`: canonical Main App runtime diagnostics import surface. It delegates preprocessing audit helpers and event-time lock reporting to existing implementations while keeping repo-evaluation scripts outside runtime code.
- `src/Main_App/Shared/`: current shared owners for cross-path behavior such as the canonical BDF loader, processing mixin, settings helpers, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Performance/`: process-runner and multiprocessing support for heavy processing.
- `src/Main_App/Legacy_App/`: temporary protected boundary for runtime-used legacy processing modules. Migrate callers toward clearer current-app modules or thin adapters before renaming or removing this designation.
- `src/Tools/`: standalone and integrated tools for preprocessing, plotting, ratios, statistics, image resizing, and detectability.
- `src/quarantine/`: quarantined legacy code retained for reference or compatibility checks.
- `tests/`: unit, integration, and pytest-qt smoke coverage.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities. These are not runtime toolbox APIs.
- `docs/`: user docs, statistical method docs, processing docs, and agent-facing verification notes.

Focused architecture pages:

- [GUI](docs/architecture/gui.md)
- [Diagnostics](docs/architecture/diagnostics.md)
- [Main App Target Layout](docs/architecture/main-app-target-layout.md)
- [Project I/O](docs/architecture/project-io.md)
- [Legacy Boundaries](docs/architecture/legacy-boundaries.md)
- [Workers And Threading](docs/architecture/workers-threading.md)
- [Statistics And Tools](docs/architecture/statistics-tools.md)
- [FFT Crop Method](docs/architecture/fft-crop-method.md)
- [Preprocessing Contract](docs/architecture/preprocessing-contract.md)
- [Post-Processing Export Contract](docs/architecture/post-processing-export-contract.md)
- [Processing Mixin Contract](docs/architecture/processing-mixin-contract.md)
- [BDF Loading Contract](docs/architecture/eeg-loading-contract.md)
- [Module Map](docs/architecture/module-map.md)
- [Protected Paths](docs/architecture/protected-paths.txt)

## Boundaries

- GUI code should orchestrate widgets, signals, and user feedback; processing logic belongs in backend, worker, or tool modules.
- Long-running EEG, plotting, export, and statistics work must run outside the UI thread.
- Legacy modules should be consumed through existing public APIs or thin adapters outside protected folders while runtime-used behavior is migrated out of the `Legacy_App` designation.
- Project-aware workflows should resolve files through the active project root and preserve existing generated formats.
- Source Localization/eLORETA has been removed from active runtime. Keep `src/Tools/SourceLocalization/**` empty of source files and do not add GUI, settings, tests, or quarantine-tree imports for it unless restoration is explicitly scoped as a new feature.

## Verification Strategy

Use focused checks for the changed area first.

- Skill-driven checks: run the matching `.agents/skills/*/scripts/*.py` wrapper before manual grep or broad document reading.
- GUI wiring or layout changes: pytest-qt smoke test for the changed widget or a documented manual smoke path.
- Processing or export changes: targeted unit tests around data format, processing order, and output paths.
- Legacy-boundary work: confirm protected paths remain unchanged with `git diff --name-only`.
- Agent invariants: run `python scripts/agent_audit.py`.
- Broad shared behavior: run `python -m pytest -q`, then lint/type checks where configured.

See [docs/quality/verification-gates.md](docs/quality/verification-gates.md) for the current command list and fallback reporting rules.
