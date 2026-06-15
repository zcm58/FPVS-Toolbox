The Publication_Report directory owns the embedded **Publication Report** tool.
It generates a single-group report bundle after processing is complete and the
user manually runs the sidebar page.

Rules:

- Keep `runner.py` GUI-agnostic. It may read workbooks, write report artifacts,
  and emit progress callbacks, but it must not import or touch widgets.
- Keep `gui.py` as the PySide6 page only: gather settings, validate visible
  state, launch `PublicationReportWorker`, and surface progress/errors through
  shared Main App components.
- Workers must communicate by signals only and must not touch widgets.
- Preserve the default output folder `5 - Publication Report` and generated
  artifact names from `models.py`.
- Keep report tables additive. Do not change existing Stats, Scalp Maps, Plot
  Generator, or Individual Detectability schemas for report convenience.
- Keep `statistical_tests.py` scoped to Publication Report manuscript-review
  diagnostics: Shapiro-Wilk checks, paired/one-sample parametric and Wilcoxon
  tests, selected-test decisions, and Holm/Bonferroni export helpers.
- Reuse the locked Stats group-level significant-harmonics selector from
  `Tools.Stats.analysis.dv_policy_group_significant`; do not add nearest-column
  fallback, alternate oddball spacing, or new threshold rules here.
- The workflow is single-group only until native multi-group reporting is
  explicitly scoped.
- Figure generation is optional. The current implementation records requested
  figure families in the manifest and warning output; automated figure export is
  deferred to a later slice.
- Workbook outputs include semantic/color ratio summaries, planned ROI
  comparison diagnostics, lateralization contrasts, participant-first
  individual-detectability tables, Z-score report tables, and base-rate
  summaries. Treat new sheets as additive unless the user explicitly requests a
  schema change.
- Publication-ready table figures should follow the shared toolbox figure
  pattern. Use Great Tables for report-facing table layout where practical, but
  keep final PNG/SVG table exports table-only by default: no embedded table
  number, title, caption, prose description, source note, or methods text unless
  the user explicitly asks for those elements in the graphic. Use
  `Main_App.gui.typography` roles and `Main_App.gui.style_tokens` colors for
  fonts, weights, borders, and backgrounds. Export both SVG and 600-DPI PNG for
  final table figures, preserve text as vector text in SVG when possible, and
  verify dimensions, DPI metadata, and absence of caption/title text in the
  table-only assets.
- Do not run offscreen Qt workflows locally.

Focused checks:

```powershell
Get-ChildItem src\Tools\Publication_Report\*.py | ForEach-Object { .\.venv1\Scripts\python.exe -m py_compile $_.FullName }
.\.venv1\Scripts\python.exe -m pytest tests\publication_report\test_publication_report_runner.py -q
.\.venv1\Scripts\python.exe -m pytest tests\stats\analysis\test_fixed_predefined_harmonics.py tests\stats\io\test_stats_ready_export.py -q
.\.venv1\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv1\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```
