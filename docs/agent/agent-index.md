# Agent Index

Use this page before gathering broad context. Pick the row that matches the
task, run the first command, then read only the focused docs or files needed by
the result.

## First Commands

Activate the repo environment before Python commands:

```powershell
.\.venv1\Scripts\Activate.ps1
```

| Task | First command |
| --- | --- |
| General repo invariant check | `python .agents/scripts/audit/agent_audit.py` |
| GUI, PySide6 imports, QAction, CustomTkinter/Tkinter boundaries | `python .agents/skills/pyside6-gui-cleanup/scripts/audit_gui_imports.py` |
| Retired paths, legacy boundaries, removed features | `python .agents/skills/legacy-boundary-review/scripts/audit_protected_edits.py` |
| Project paths, dialogs, exports, generated files | `python .agents/skills/project-path-audit/scripts/audit_hardcoded_paths.py` |
| Stats package structure | `python .agents/scripts/audit/agent_audit.py --check stats-structure` |
| Stats reporting size and legibility | `python .agents/scripts/audit/agent_audit.py --check stats-reporting-legibility` |
| Cache/temp/debt-marker cleanup | `python .agents/scripts/audit/agent_audit.py --check garbage-collection` |

## Skill Map

| Task | Skill | Focused docs |
| --- | --- | --- |
| PySide6 GUI, widgets, menus, workers, processing orchestration, status UX | `pyside6-gui-cleanup` | `docs/agent/architecture/gui.md`; `docs/agent/architecture/workers-threading.md` |
| Main App package layout, ownership, folder naming, retired package boundaries | `legacy-boundary-review` | `docs/agent/architecture/main-app-target-layout.md`; `docs/agent/architecture/legacy-boundaries.md` |
| EEG preprocessing ownership, entry points, or processing order | `legacy-boundary-review` + `pyside6-gui-cleanup` | `docs/agent/architecture/preprocessing-contract.md` |
| BDF loading, memmap paths, EXG typing | `legacy-boundary-review` + `project-path-audit` | `docs/agent/architecture/eeg-loading-contract.md` |
| Post-processing, FFT crop, or Excel export behavior | `legacy-boundary-review` | `docs/agent/architecture/post-processing-export-contract.md`; `docs/agent/architecture/fft-crop-method.md` |
| Project manifests, project roots, file dialogs, exports, imports | `project-path-audit` | `docs/agent/architecture/project-io.md` |
| Publication figure generation, `.png`/`.pdf` outputs, 600 dpi, figure typography | `project-path-audit` | `docs/agent/quality/figure-generation.md` |
| Stats analysis, GUI/pipeline structure, reporting, exports | `pyside6-gui-cleanup` plus focused Stats tests | `docs/agent/architecture/statistics-tools.md` |
| LORETA Visualizer, source visualization, or source-localization-adjacent rendering | `legacy-boundary-review` plus focused tool tests | `src/Tools/LORETA_Visualizer/AGENTS.md`; `src/Tools/LORETA_Visualizer/ARCHITECTURE.md` |
| Publication scalp maps and source-data exports | `pyside6-gui-cleanup` + `project-path-audit` | `src/Tools/Publication_Maps/AGENTS.md`; `docs/agent/architecture/statistics-tools.md` |
| Publication report workflow, source workbook, manuscript diagnostics, narrative, and embedded page | `pyside6-gui-cleanup` + `project-path-audit` | `src/Tools/Publication_Report/AGENTS.md`; `docs/agent/exec-plans/active/publication-report-workflow.md` |
| Publication-ready table PNG/SVG exports under a project root | `publication-table-export` + `project-path-audit` | `.agents/skills/publication-table-export/SKILL.md`; `docs/agent/architecture/statistics-tools.md` |
| GUI smoke coverage definitions | `pytest-qt-smoke` | `docs/agent/quality/test-selection.md`; do not run pytest-qt/offscreen locally |
| Generated files, temp folders, local caches | `cleanup-generated-files` | `docs/agent/quality/garbage-collection.md`; `docs/agent/exec-plans/tech-debt-tracker.md` |
| Plan pressure-testing, design interrogation, dependency-aware decision trees | `grillme` | Explore code first when the answer is discoverable locally; ask one question at a time |
| Web/frontend design skill requests outside normal FPVS PySide6 app work | `frontend-design`, `web-design-guidelines`, `emil-design-eng` | Use only when the user explicitly requests web/frontend design; normal FPVS Toolbox GUI work remains PySide6-first |

Repo-local skills and rules are the default for FPVS Toolbox work. Use
installed/global skills only when the user explicitly names them or the task is
outside the repo-local skill set; they do not override `AGENTS.md`,
`ARCHITECTURE.md`, `.venv1`, or the no-offscreen-Qt rule.

## Script Layout

- `.agents/scripts/audit/`: repo invariant checks.
- `.agents/scripts/smoke/`: agent-facing smoke checks, not default gates.
- `scripts/debug/`: focused debugging probes.
- `scripts/manual_diagnostics/`: developer-run project/data probes.
- `scripts/packaging/`: release packaging and installer inputs.
- `src/Standalone_Scripts/`: developer-only scratch/manual scripts. Do not read
  or use as architectural precedent unless the user explicitly asks.

## Execution Plans

- Active plans live in `docs/agent/exec-plans/active/`; read them before
  changing the covered area.
- Future plans live in `docs/agent/exec-plans/future/`; read them only when
  scoping or starting the matching work.
- Known debt lives in `docs/agent/exec-plans/tech-debt-tracker.md`.
- Completed plans are removed by default. Do not route routine work through
  completed plans or historical implementation logs unless the user explicitly
  asks for that context.

## Test Selection

- Component layer: `python -m pytest tests/gui/test_ui_components_smoke.py -q`
- Main window or PySide6 layout: update focused pytest-qt coverage when useful,
  but do not run pytest-qt/offscreen locally.
- Project I/O: `python -m pytest tests/project_io/test_project_settings_roundtrip.py tests/project_io/test_project_results_layout.py -q`
- Plot Generator: run the nearest `tests/plot_generator/test_*` file first;
  use `python -m pytest tests/plot_generator -q` after worker, rendering, or
  output changes.
- Publication Maps: `python -m pytest tests/publication_maps/test_bca_publication_maps.py -q`
- Publication Report: `python -m pytest tests/publication_report/test_publication_report_runner.py -q`
- Ratio Calculator: `python -m pytest tests/ratio_calculator/test_ratio_calculator_plots.py -q`
- Stats GUI/pipeline: `python -m pytest tests/stats/gui/test_stats_layout_smoke.py tests/stats/pipeline/test_stats_pipeline_smoke.py tests/stats/data/test_stats_project_context.py -q`
- Stats FullSNR regression: `python -m pytest tests/stats/analysis/test_full_snr_reference_equivalence.py -q`
- Stats-ready workbook export: `python -m pytest tests/stats/io/test_stats_ready_export.py -q`
- Stats reporting summaries: `python -m pytest tests/stats/analysis/test_summary_utils_mixed_model.py tests/stats/analysis/test_summary_utils_posthoc_directions.py tests/stats/reporting/test_lmm_reporting_exports.py -q`

## Reading Rule

Do not scan broad folders just to confirm invariants that a script already
checks. Read focused architecture docs after a script fails, when the task
changes that area, or when the user asks for design/context rather than code.
Exclude `src/Standalone_Scripts/**` from routine code search and context
gathering unless the user explicitly scopes that folder.
