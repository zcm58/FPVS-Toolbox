# Agent Index

Use this page before gathering broad context. Run the relevant command first, then read only the focused docs or files needed by the result.

## First Commands

```powershell
# PowerShell
.\.venv1\Scripts\Activate.ps1
python .agents/scripts/audit/agent_audit.py
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py

# Bash
source .venv1/bin/activate
python .agents/scripts/audit/agent_audit.py
python .agents/scripts/audit/agent_audit.py --check stats-structure
python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Skill Map

| Task | Skill | First script | Focused docs |
| --- | --- | --- | --- |
| PySide6 GUI, widgets, menus, workers, processing run orchestration, status UX | `pyside6-gui-cleanup` | `.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` | `docs/agent/architecture/gui.md`; canonical imports: `src/Main_App/gui/`, shared components through `Main_App.gui.components` |
| Qt workers, process runner, multiprocessing bridge | `pyside6-gui-cleanup` | `.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` | `docs/agent/architecture/workers-threading.md`; canonical import: `src/Main_App/workers/` |
| Main App package layout, ownership, or folder naming | `legacy-boundary-review` | `.agents/scripts/audit/agent_audit.py` | `docs/agent/architecture/main-app-target-layout.md`; completed context: `docs/agent/exec-plans/completed/main-app-refactor.md` and `docs/agent/exec-plans/completed/main-app-folder-retirement.md` |
| Runtime diagnostics, repo audits, or manual project probes | `project-path-audit` when paths are involved | `.agents/scripts/audit/agent_audit.py` | `docs/agent/architecture/diagnostics.md`; canonical runtime import: `src/Main_App/diagnostics/` |
| Stats package structure and analysis organization | `pyside6-gui-cleanup` | `.agents/scripts/audit/agent_audit.py --check stats-structure` | `docs/agent/architecture/statistics-tools.md` |
| Stats reporting summaries and legibility | `pyside6-gui-cleanup` | `.agents/scripts/audit/agent_audit.py --check stats-reporting-legibility` | `docs/agent/architecture/statistics-tools.md` |
| Legacy boundary and removed-feature status | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/legacy-boundaries.md` |
| EEG preprocessing ownership, processing entry points, processing order, or GUI processing route | `legacy-boundary-review` + `pyside6-gui-cleanup` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/preprocessing-contract.md`; canonical imports: `src/Main_App/processing/preprocess.py`, `src/Main_App/processing/processing.py` |
| FFT crop helper ownership or behavior | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/fft-crop-method.md` |
| Post-processing or Excel export behavior | `legacy-boundary-review`; add `pyside6-gui-cleanup` for GUI completion handling | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/post-processing-export-contract.md`; adapter: `src/Main_App/exports/post_export_adapter.py`; GUI wrapper: `src/Main_App/gui/post_export_workflows.py` |
| Main App processing mixin behavior | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/processing-mixin-contract.md` |
| BDF loading behavior, memmap paths, EXG typing | `legacy-boundary-review` + `project-path-audit` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/agent/architecture/eeg-loading-contract.md`; canonical import: `src/Main_App/io/load_utils.py` |
| Project paths, dialogs, imports, exports, manifests | `project-path-audit` | `.agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` | `docs/agent/architecture/project-io.md`; canonical import: `src/Main_App/projects/` |
| GUI smoke coverage | `pytest-qt-smoke` | update coverage only; do not run pytest-qt/offscreen locally | `docs/agent/quality/test-selection.md` |
| Entropy or garbage-collection cleanup | `cleanup-generated-files` | `python .agents/scripts/audit/agent_audit.py --check garbage-collection` | `docs/agent/quality/garbage-collection.md`; `docs/agent/exec-plans/tech-debt-tracker.md` |

## Installed Codex Skill Routing

The repo-local skills above are the default for FPVS Toolbox work. Use the
globally installed skills below only when their trigger is present and only
after applying `AGENTS.md`, `ARCHITECTURE.md`, the focused architecture page,
and the verification gates for the changed area.

| Task trigger | Installed skill | Repo-specific use | Still required |
| --- | --- | --- | --- |
| Reported bug, failing command, hung GUI test, performance regression, or "diagnose/debug" request | `diagnose` | Build a bounded feedback loop first: targeted pytest, `py_compile`, audit script, import probe, or visible/manual GUI smoke path. For GUI hangs, check unbounded waits, modal dialogs, thread completion, and timeout coverage before editing. | Do not run offscreen Qt. Keep any regression test at the real seam. Remove temporary instrumentation before handoff. |
| User asks for architecture/refactor opportunities, or a debugging result shows there is no good test seam | `improve-codebase-architecture` | Review current repo maps and focused docs, then propose small deepening candidates around actual FPVS modules such as `Main_App.gui.components`, `Main_App.workers`, `Main_App.projects`, `Tools.Stats`, or tool-specific processing seams. | Do not refactor while only producing an architecture review. Preserve retired-path and Source Localization boundaries. |
| Plan, execution plan, UX flow, or architecture proposal needs stress testing before implementation | `grill-me` | Ask one decision question at a time, but first answer any question discoverable from `ARCHITECTURE.md`, active exec plans, and focused docs. | Do not turn grilling into code changes. Record durable decisions in an exec plan or focused agent doc only when the task scope calls for it. |
| Three or more independent failures or independent docs/code slices can run in parallel | `dispatching-parallel-agents` | Split by non-overlapping subsystem, for example Stats reporting, Plot Generator path handling, and Main App GUI routing. Each worker must get file ownership, constraints, and expected verification. | Follow the active agent runtime's delegation policy. Do not use parallel work when failures share files or one result blocks the next step. |
| The user asks whether a skill exists, or the task needs a capability outside the repo-local and installed skill set | `find-skills` | Search for a capability only after confirming no repo-local skill already covers it. | Do not install or recommend a skill to bypass repo rules or verification gates. |
| User explicitly asks for visual polish, UX critique, or a new PySide6 surface | `impeccable`/`delight`, `ui-ux-pro-max`, or `frontend-design` | Use only as design critique or ideation. Translate output into PySide6, `Main_App.gui.components`, `theme.py`, `typography.py`, and existing FPVS workflows. | The PySide6-only rule, component-layer contract, card-within-card ban, no-offscreen Qt limit, and focused GUI checks override any web/mobile design advice. |

Do not use these installed skills for normal FPVS Toolbox work:

- `react-best-practices`, `composition-patterns`, and `react-view-transitions`:
  this repo has no active React or Next.js surface.
- `react-native-skills`: this repo is a Windows PySide6 desktop application,
  not a React Native or Expo app.
- `deploy-to-vercel`, `vercel-cli-with-tokens`, and `vercel-optimize`: the app
  ships through Windows packaging and GitHub Release installer flows, not
  Vercel deployment. Use `docs/agent/guides/development.md` and
  `scripts/packaging/` for release work.
- `web-design-guidelines`: user-facing MkDocs content is markdown under
  `docs/user`; there is no repo-owned web application UI to audit with this
  skill. Use `mkdocs build --strict` for docs-site validation.

## Script Layout

- `.agents/scripts/audit/`: repo invariant checks.
- `scripts/docs/`: docs publishing helpers.
- `.agents/scripts/smoke/`: agent-facing smoke checks.
- `scripts/migration/`: local data migration helpers.
- `scripts/debug/`: focused debugging probes.
- `scripts/manual_diagnostics/`: manual project/data investigation scripts.
- `scripts/packaging/`: release packaging definitions and installer/build inputs.

## Execution Plans

- Active refactor plans live in `docs/agent/exec-plans/active/`.
- Future plans live in `docs/agent/exec-plans/future/`; read them only when scoping or starting the matching effort.
- Known debt that is not yet active work lives in `docs/agent/exec-plans/tech-debt-tracker.md`.
- Plot Generator worker refactor is recorded in `docs/agent/exec-plans/completed/plot-generator-worker-refactor.md`; read it before changing `src/Tools/Plot_Generator/worker.py` or the extracted worker helper modules.
- Shared GUI surface migration is recorded in `docs/agent/exec-plans/completed/shared-gui-surface-migration.md`; read it before continuing tool-window migration patterns or validating the Ratio Calculator, Epoch/Average Preprocessing, Stats UI, Plot Generator, or Main App shell component adoption.
- Shared GUI component-layer consolidation is recorded in `docs/agent/exec-plans/completed/shared-gui-component-layer-updated.md`; read it before changing reusable GUI primitives, shared action/message/path/status patterns, or migrating tool windows to `Main_App.gui.components`.
- Ratio Calculator GUI refactor is recorded in `docs/agent/exec-plans/completed/ratio-calculator-gui-refactor.md`; read it before changing `src/Tools/Ratio_Calculator/gui.py` or the focused GUI mixins.
- Auto-update installer workflow implementation is recorded in `docs/agent/exec-plans/completed/auto-update-installer-workflow.md`; read it before changing `Main_App.updates`, `update_dialog.py`, `update_manager.py`, or packaging release scripts.
- Stats-ready pipeline export implementation is recorded in `docs/agent/exec-plans/completed/stats-ready-pipeline-exports.md`; read it before changing `Tools.Stats.io.stats_ready_export`, the `Export Stats-Ready Workbook` GUI action, Stats export workers, or external-statistics user docs.
- Read `docs/agent/exec-plans/completed/main-app-refactor.md` only when historical Main App refactor context is needed.
- Read `docs/agent/exec-plans/completed/main-app-folder-retirement.md` only when historical folder-retirement context is needed for retired `Legacy_App` or `PySide6_App` paths.
- Keep active plans current with phase status, touched areas, doc updates, verification commands, and decisions.
- Move finished plans to `docs/agent/exec-plans/completed/` when the tracked work is complete.

## Knowledge Base

- `docs/agent/README.md` is the docs directory map.
- `docs/agent/design-docs/` contains durable design beliefs.
- `docs/agent/product-specs/` contains durable user-facing behavior specs.
- `docs/agent/references/` contains external or copied reference material for agents.
- `docs/agent/generated/` contains generated reference artifacts and should not be edited by hand.

## Test Selection

- Component layer: `python -m pytest tests/gui/test_ui_components_smoke.py -q`
- Main window or PySide6 layout: update `tests/gui/test_main_window_layout_smoke.py` when useful, but do not run pytest-qt/offscreen locally.
- Project I/O: `python -m pytest tests/project_io/test_project_settings_roundtrip.py tests/project_io/test_project_results_layout.py -q`
- Plot generator: `python -m pytest tests/plot_generator -q` after worker,
  rendering, or output changes; use the nearest `tests/plot_generator/test_*`
  file first for narrower GUI-only edits.
- Ratio calculator: `python -m pytest tests/ratio_calculator/test_ratio_calculator_plots.py -q`
- Stats GUI/pipeline: `python -m pytest tests/stats/gui/test_stats_layout_smoke.py tests/stats/pipeline/test_stats_pipeline_smoke.py tests/stats/data/test_stats_project_context.py -q`
- Stats FullSNR regression: `python -m pytest tests/stats/analysis/test_full_snr_reference_equivalence.py -q`
- Stats-ready workbook export: `python -m pytest tests/stats/io/test_stats_ready_export.py -q`
- Stats reporting summaries: `python -m pytest tests/stats/analysis/test_summary_utils_mixed_model.py tests/stats/analysis/test_summary_utils_posthoc_directions.py tests/stats/reporting/test_lmm_reporting_exports.py -q`

## Reading Rule

Activate `.\.venv1` before running Python-based repo commands. Do not scan broad folders just to confirm invariants that a script already checks. Read focused architecture docs after a script fails, when the task changes that area, or when the user asks for design/context rather than code.
