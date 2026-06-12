# ARCHITECTURE.md

## Purpose

This file is the top-level map for agents working in FPVS Toolbox. Keep durable architecture details here or in linked docs, not in long prompts.

Use executable checks before broad reading:

```powershell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

Read [docs/agent/agent-index.md](docs/agent/agent-index.md) for the compact skill/script/test map. Read the focused architecture pages below only when the task touches that area or a check reports a relevant issue.

## Execution Plans

Durable refactor and feature plans live under [docs/agent/exec-plans](docs/agent/exec-plans/). Read active plans before changing the areas they cover, then keep the plan's progress, decisions, and verification notes current as work lands. Future plans record approved ideas that are not active work yet; read them only when scoping or starting the matching effort.

Structural refactors must update this file, the relevant focused architecture page, or the nearest scoped `AGENTS.md` in the same PR when they change ownership, module boundaries, workflows, or verification expectations. If no architecture or agent doc changes are needed, record that in the PR handoff or active execution plan.

## Knowledge Base

The docs tree is split into [docs/agent](docs/agent/) for agent-facing guidance and [docs/user](docs/user/) for MkDocs/user documentation. Agent guidance is indexed by [docs/agent/README.md](docs/agent/README.md). Keep root agent guidance compact and move durable agent details into focused docs such as `docs/agent/design-docs/`, `docs/agent/product-specs/`, `docs/agent/references/`, `docs/agent/quality/`, and `docs/agent/exec-plans/`.

## Application Shape

FPVS Toolbox is a Windows-oriented desktop application built around PySide6 GUI entry points, processing backends, and analysis tools under `src/`.

Primary areas:

- `src/Main_App/gui/`: canonical Main App GUI package. It owns the main-window shell/coordinator, focused GUI workflow helpers, reusable widgets, theme helpers, menu/sidebar/header helpers, icon/style-token/update-manager helpers, and GUI operation guards. `main_window.py` has been appropriately downsized; do not target it for further refactor unless the user explicitly scopes that work.
- `src/Main_App/gui/components/`: canonical shared component layer for new and migrated GUI surfaces. Prefer this import surface for shared cards, buttons, forms, status banners, window/dialog shells, action rows, and message helpers.
- `src/Main_App/exports/`: canonical Main App export adapter import surface. It owns post-export adapter behavior used by workers and the process runner while shared post-processing/workbook generation remains behavior-preserving.
- `src/Main_App/processing/`: canonical Main App processing package. It owns active EEG preprocessing, the stable `process_data` entry point, and processing-controller helpers.
- `src/Main_App/io/`: canonical Main App I/O import surface. It currently delegates BDF loading to the existing shared implementation while the repo moves toward purpose-based Main App folders.
- `src/Main_App/projects/`: canonical Main App project import surface. It owns the project model, project manager workflows, project metadata scanning, projects-root helpers, and preprocessing-settings normalization.
- `src/Main_App/workers/`: canonical Main App worker package for Qt workers, process-runner wrappers, and multiprocessing environment helpers.
- `src/Main_App/diagnostics/`: canonical Main App runtime diagnostics package for preprocessing audit helpers, event-time lock reporting, and runtime log routing. Repo-evaluation scripts stay in `scripts/` and `.agents/skills/`.
- `src/Main_App/Shared/`: current shared owners for cross-path behavior such as the canonical BDF loader, processing mixin, settings helpers, FFT crop helpers, and post-processing export behavior.
- `src/Main_App/Performance/`: process-runner and multiprocessing support for heavy processing.
- `src/Main_App/Legacy_App/`: retired historical package. Do not recreate it; active code belongs in purpose-based `Main_App` packages.
- `src/Main_App/PySide6_App/`: retired historical package designation. Do not recreate it; PySide6 runtime code now lives under purpose-based `Main_App` packages.
- `src/Tools/`: standalone and integrated tools for preprocessing, plotting, ratios, statistics, image resizing, detectability, and the new LORETA Visualizer.
- `src/Tools/LORETA_Visualizer/`: new embedded 3D source-visualization tool. Its renderer displays anatomical meshes and prepared source payloads only; future source-localization calculations must stay separate and pass through tool-local helper/adapters. See [LORETA Visualizer Architecture](src/Tools/LORETA_Visualizer/ARCHITECTURE.md).
- `src/Standalone_Scripts/`: developer-only scratch/manual scripts. Agents should not read these files, treat them as active architecture, or use them as implementation precedent unless the user explicitly asks about this folder.
- `src/quarantine/`: quarantined legacy code retained for reference or compatibility checks.
- `tests/`: unit, integration, and pytest-qt smoke coverage.
- `.agents/scripts/audit/`: repo-level agent invariant checks such as `agent_audit.py`.
- `scripts/docs/`: documentation publishing and maintenance helpers.
- `.agents/scripts/smoke/`: agent-facing smoke checks that are not pytest tests.
- `scripts/migration/`: one-off or repeatable local data migration helpers.
- `scripts/debug/`: focused debugging probes.
- `scripts/manual_diagnostics/`: developer-run project/data investigation utilities. These are not runtime toolbox APIs.
- `scripts/packaging/`: release packaging definitions and installer/build inputs.
- `docs/agent/`: agent-facing architecture, execution plans, quality gates, prompts, and implementation guidance.
- `docs/user/`: user-facing MkDocs source for study workflow, statistics, tools, and reference pages.

Focused architecture pages:

- [GUI](docs/agent/architecture/gui.md)
- [Diagnostics](docs/agent/architecture/diagnostics.md)
- [Main App Target Layout](docs/agent/architecture/main-app-target-layout.md)
- [Project I/O](docs/agent/architecture/project-io.md)
- [Legacy Boundaries](docs/agent/architecture/legacy-boundaries.md)
- [Workers And Threading](docs/agent/architecture/workers-threading.md)
- [Statistics And Tools](docs/agent/architecture/statistics-tools.md)
- [FFT Crop Method](docs/agent/architecture/fft-crop-method.md)
- [Preprocessing Contract](docs/agent/architecture/preprocessing-contract.md)
- [Post-Processing Export Contract](docs/agent/architecture/post-processing-export-contract.md)
- [Processing Mixin Contract](docs/agent/architecture/processing-mixin-contract.md)
- [BDF Loading Contract](docs/agent/architecture/eeg-loading-contract.md)
- [Module Map](docs/agent/architecture/module-map.md)
- [Protected Paths](docs/agent/architecture/protected-paths.txt)
- [LORETA Visualizer Tool Architecture](src/Tools/LORETA_Visualizer/ARCHITECTURE.md)

## Boundaries

- GUI code should orchestrate widgets, signals, and user feedback; processing logic belongs in backend, worker, or tool modules.
- Long-running EEG, plotting, export, and statistics work must run outside the UI thread.
- Historical legacy behavior should be consumed through existing current-app APIs or thin adapters in purpose-based packages. Do not add new `Legacy_App` or `PySide6_App` modules.
- Project-aware workflows should resolve files through the active project root and preserve existing generated formats.
- Source Localization/eLORETA has been removed from active runtime. Keep `src/Tools/SourceLocalization/**` empty of source files and do not add GUI, settings, tests, or quarantine-tree imports for it unless restoration is explicitly scoped as a new feature. The new `src/Tools/LORETA_Visualizer/` branch is a separate visualization tool, not a design continuation of the removed implementation; it must keep renderer logic separate from future calculation logic and must not bundle `fsaverage` MRI template data in active source or quarantine.
- The ignored repository-root `.fpvs_cache/` is the local MNE/fsaverage cache used by the LORETA Visualizer. Preserve it during routine cleanup unless the user explicitly requests cache removal.

## Verification Strategy

Use focused checks for the changed area first.

- Skill-driven checks: run the matching `.agents/skills/*/scripts/*.py` wrapper before manual grep or broad document reading.
- GUI wiring or layout changes: pytest-qt smoke test for the changed widget or a documented manual smoke path.
- Processing or export changes: targeted unit tests around data format, processing order, and output paths.
- Retired-path work: activate `.\.venv1`, then confirm `src/Main_App/Legacy_App/**` and `src/Main_App/PySide6_App/**` are not recreated with `git diff --name-only` and `python .agents/scripts/audit/agent_audit.py`.
- Agent invariants: activate `.\.venv1`, then run `python .agents/scripts/audit/agent_audit.py`.
- Broad shared behavior: activate `.\.venv1`, then run `python -m pytest -q` and lint checks where configured.

See [docs/agent/quality/verification-gates.md](docs/agent/quality/verification-gates.md) for the current command list and fallback reporting rules.
