# Agent Index

Use this page before gathering broad context. Run the relevant command first, then read only the focused docs or files needed by the result.

## First Commands

```powershell
python scripts/agent_audit.py
python scripts/agent_audit.py --check stats-structure
python scripts/agent_audit.py --check stats-reporting-legibility
python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py
python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py
python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py
```

## Skill Map

| Task | Skill | First script | Focused docs |
| --- | --- | --- | --- |
| PySide6 GUI, widgets, menus, workers, processing run orchestration, status UX | `pyside6-gui-cleanup` | `.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` | `docs/architecture/gui.md`; canonical import: `src/Main_App/gui/` |
| Qt workers, process runner, multiprocessing bridge | `pyside6-gui-cleanup` | `.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` | `docs/architecture/workers-threading.md`; canonical import: `src/Main_App/workers/` |
| Main App package layout, ownership, or folder naming | `legacy-boundary-review` | `scripts/agent_audit.py` | `docs/architecture/main-app-target-layout.md`; `docs/exec-plans/active/main-app-refactor.md`; `docs/exec-plans/active/main-app-folder-retirement.md` |
| Runtime diagnostics, repo audits, or manual project probes | `project-path-audit` when paths are involved | `scripts/agent_audit.py` | `docs/architecture/diagnostics.md`; canonical runtime import: `src/Main_App/diagnostics/` |
| Stats package structure and analysis organization | `pyside6-gui-cleanup` | `scripts/agent_audit.py --check stats-structure` | `docs/architecture/statistics-tools.md` |
| Stats reporting summaries and legibility | `pyside6-gui-cleanup` | `scripts/agent_audit.py --check stats-reporting-legibility` | `docs/architecture/statistics-tools.md` |
| Legacy boundary and removed-feature status | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/legacy-boundaries.md` |
| EEG preprocessing ownership, processing entry points, processing order, or GUI processing route | `legacy-boundary-review` + `pyside6-gui-cleanup` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/preprocessing-contract.md`; canonical imports: `src/Main_App/processing/preprocess.py`, `src/Main_App/processing/processing.py` |
| FFT crop helper ownership or behavior | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/fft-crop-method.md` |
| Post-processing or Excel export behavior | `legacy-boundary-review`; add `pyside6-gui-cleanup` for GUI completion handling | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/post-processing-export-contract.md`; adapter: `src/Main_App/exports/post_export_adapter.py`; GUI wrapper: `src/Main_App/gui/post_export_workflows.py` |
| Main App processing mixin behavior | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/processing-mixin-contract.md` |
| BDF loading behavior, memmap paths, EXG typing | `legacy-boundary-review` + `project-path-audit` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/eeg-loading-contract.md`; canonical import: `src/Main_App/io/load_utils.py` |
| Project paths, dialogs, imports, exports, manifests | `project-path-audit` | `.agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` | `docs/architecture/project-io.md`; canonical import: `src/Main_App/projects/` |
| GUI smoke coverage | `pytest-qt-smoke` | nearest focused pytest target | `docs/quality/test-selection.md` |

## Execution Plans

- Active refactor plans live in `docs/exec-plans/active/`.
- Future plans live in `docs/exec-plans/future/`; read them only when scoping or starting the matching effort.
- Known debt that is not yet active work lives in `docs/exec-plans/tech-debt-tracker.md`.
- Read `docs/exec-plans/active/main-app-refactor.md` before non-trivial `Main_App` refactors.
- Read `docs/exec-plans/active/main-app-folder-retirement.md` before touching `Legacy_App`, `PySide6_App`, or Main App package ownership.
- Keep active plans current with phase status, touched areas, doc updates, verification commands, and decisions.
- Move finished plans to `docs/exec-plans/completed/` when the tracked work is complete.

## Knowledge Base

- `docs/README.md` is the docs directory map.
- `docs/design-docs/` contains durable design beliefs.
- `docs/product-specs/` contains durable user-facing behavior specs.
- `docs/references/` contains external or copied reference material for agents.
- `docs/generated/` contains generated reference artifacts and should not be edited by hand.

## Test Selection

- Component layer: `python -m pytest tests/test_ui_components_smoke.py -q`
- Main window or PySide6 layout: `python -m pytest tests/test_main_window_layout_smoke.py -q`
- Project I/O: `python -m pytest tests/test_project_settings_roundtrip.py tests/test_project_results_layout.py -q`
- Plot generator: `python -m pytest tests/test_plot_generator_gui.py -q`
- Ratio calculator: `python -m pytest tests/test_ratio_calculator_plots.py -q`
- Stats GUI/pipeline: `python -m pytest tests/test_stats_layout_smoke.py tests/test_stats_pipeline_smoke.py -q`
- Stats reporting summaries: `python -m pytest tests/test_summary_utils_mixed_model.py tests/test_summary_utils_posthoc_directions.py tests/test_lmm_reporting_exports.py -q`

## Reading Rule

Do not scan broad folders just to confirm invariants that a script already checks. Read focused architecture docs after a script fails, when the task changes that area, or when the user asks for design/context rather than code.
