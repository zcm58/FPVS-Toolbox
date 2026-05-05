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
| PySide6 GUI, widgets, menus, workers, status UX | `pyside6-gui-cleanup` | `.agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` | `docs/architecture/gui.md` |
| Stats package structure and analysis organization | `pyside6-gui-cleanup` | `scripts/agent_audit.py --check stats-structure` | `docs/architecture/statistics-tools.md` |
| Stats reporting summaries and legibility | `pyside6-gui-cleanup` | `scripts/agent_audit.py --check stats-reporting-legibility` | `docs/architecture/statistics-tools.md` |
| Legacy boundary, quarantine, Source Localization status | `legacy-boundary-review` | `.agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` | `docs/architecture/legacy-boundaries.md` |
| Project paths, dialogs, imports, exports, manifests | `project-path-audit` | `.agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` | `docs/architecture/project-io.md` |
| GUI smoke coverage | `pytest-qt-smoke` | nearest focused pytest target | `docs/quality/test-selection.md` |

## Execution Plans

- Active refactor plans live in `docs/exec-plans/active/`.
- Read `docs/exec-plans/active/main-app-refactor.md` before non-trivial `Main_App` refactors.
- Keep active plans current with phase status, touched areas, doc updates, verification commands, and decisions.
- Move finished plans to `docs/exec-plans/completed/` when the tracked work is complete.

## Test Selection

- Component layer: `python -m pytest tests/test_ui_components_smoke.py -q`
- Main window or PySide6 layout: `python -m pytest tests/test_main_window_layout_smoke.py -q`
- Project I/O: `python -m pytest tests/test_project_settings_roundtrip.py tests/test_project_results_layout.py -q`
- Plot generator: `python -m pytest tests/test_plot_generator_gui.py -q`
- Ratio calculator: `python -m pytest tests/test_ratio_calculator_plots.py -q`
- Stats GUI/pipeline: `python -m pytest tests/test_stats_layout_smoke.py tests/test_stats_pipeline_smoke.py -q`
- Stats reporting summaries: `python -m pytest tests/test_summary_utils_mixed_model.py tests/test_summary_utils_posthoc_directions.py tests/test_lmm_reporting_exports.py -q`
- Source Localization availability shim: `python -m pytest tests/test_source_localization_import.py tests/test_source_localization_optional_smoke.py -q`

## Reading Rule

Do not scan broad folders just to confirm invariants that a script already checks. Read focused architecture docs after a script fails, when the task changes that area, or when the user asks for design/context rather than code.
