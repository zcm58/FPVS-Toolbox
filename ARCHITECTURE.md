# ARCHITECTURE.md

## Purpose

This file is the top-level map for agents working in FPVS Toolbox. Keep durable architecture details here or in linked docs, not in long prompts.

Use executable checks before broad reading:

```powershell
python scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Read [docs/agent-index.md](docs/agent-index.md) for the compact skill/script/test map. Read the focused architecture pages below only when the task touches that area or a check reports a relevant issue.

## Execution Plans

Durable refactor and feature plans live under [docs/exec-plans](docs/exec-plans/). Read active plans before changing the areas they cover, then keep the plan's progress, decisions, and verification notes current as work lands. Future plans record approved ideas that are not active work yet; read them only when scoping or starting the matching effort.

Structural refactors must update this file, the relevant focused architecture page, or the nearest scoped `AGENTS.md` in the same PR when they change ownership, module boundaries, workflows, or verification expectations. If no architecture or agent doc changes are needed, record that in the PR handoff or active execution plan.

## Knowledge Base

The repo knowledge base lives in [docs](docs/) and is indexed by [docs/README.md](docs/README.md). Keep root agent guidance compact and move durable details into focused docs such as `docs/design-docs/`, `docs/product-specs/`, `docs/references/`, `docs/quality/`, and `docs/exec-plans/`.

## Application Shape

FPVS Toolbox is a Windows-oriented desktop application built around PySide6 GUI entry points, processing backends, and analysis tools under `src/`.

Primary areas:

- `src/Main_App/gui/`: canonical Main App GUI package. It owns the main-window shell/coordinator, focused GUI workflow helpers, reusable widgets, theme helpers, menu/sidebar/header helpers, icon/style-token/update-manager helpers, and GUI operation guards. `main_window.py` has been appropriately downsized; do not target it for further refactor unless the user explicitly scopes that work.
- `src/Main_App/exports/`: canonical Main App export adapter import surface. It owns post-export adapter behavior used by workers and the process runner while shared post-processing/workbook generation remains behavior-preserving.
- `src/Main_App/processing/`: canonical Main App processing package. It owns active EEG preprocessing, the stable `process_data` entry point, and processing-controller helpers.
- `src/Main_App/io/`: canonical Main App I/O import surface. It currently delegates BDF loading to the existing shared implementation while the repo moves toward purpose-based Main App folders.
- `src/Main_App/projects/`: canonical Main App project import surface. It owns the project model, project manager workflows, project metadata scanning, projects-root helpers, and preprocessing-settings normalization.
- `src/Main_App/workers/`: canonical Main App worker package for Qt workers, process-runner wrappers, and multiprocessing environment helpers.
- `src/Main_App/diagnostics/`: canonical Main App runtime diagnostics package for preprocessing audit helpers and event-time lock reporting. Repo-evaluation scripts stay in `scripts/` and `.agents/skills/`.
- `src/Main_App/Shared/`: current shared owners for cross-path behavior such as the canonical BDF loader, processing mixin, settings helpers, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Performance/`: process-runner and multiprocessing support for heavy processing.
- `src/Main_App/Legacy_App/`: retired historical package. Do not recreate it; active code belongs in purpose-based `Main_App` packages.
- `src/Main_App/PySide6_App/`: retired historical package designation. Do not recreate it; PySide6 runtime code now lives under purpose-based `Main_App` packages.
- `src/Tools/`: standalone and integrated tools for preprocessing, plotting, ratios, statistics, image resizing, and detectability.
- `src/quarantine/`: quarantined legacy code retained for reference or compatibility checks.
- `tests/`: unit, integration, and pytest-qt smoke coverage.
- `scripts/audit/`: repo-level invariant checks such as `agent_audit.py`.
- `scripts/docs/`: documentation publishing and maintenance helpers.
- `scripts/smoke/`: developer-run smoke checks that are not pytest tests.
- `scripts/migration/`: one-off or repeatable local data migration helpers.
- `scripts/debug/`: focused debugging probes.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities. These are not runtime toolbox APIs.
- `scripts/packaging/`: release packaging definitions and installer/build inputs.
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
- Historical legacy behavior should be consumed through existing current-app APIs or thin adapters in purpose-based packages. Do not add new `Legacy_App` or `PySide6_App` modules.
- Project-aware workflows should resolve files through the active project root and preserve existing generated formats.
- Source Localization/eLORETA has been removed from active runtime. Keep `src/Tools/SourceLocalization/**` empty of source files and do not add GUI, settings, tests, or quarantine-tree imports for it unless restoration is explicitly scoped as a new feature. Do not bundle `fsaverage` MRI template data in active source or quarantine.

## Verification Strategy

Use focused checks for the changed area first.

- Skill-driven checks: run the matching `.agents/skills/*/scripts/*.py` wrapper before manual grep or broad document reading.
- GUI wiring or layout changes: pytest-qt smoke test for the changed widget or a documented manual smoke path.
- Processing or export changes: targeted unit tests around data format, processing order, and output paths.
- Retired-path work: confirm `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` are not recreated with `git diff --name-only` and `python scripts/audit/agent_audit.py`.
- Agent invariants: run `python scripts/audit/agent_audit.py`.
- Broad shared behavior: run `python -m pytest -q`, then lint/type checks where configured.

See [docs/quality/verification-gates.md](docs/quality/verification-gates.md) for the current command list and fallback reporting rules.
