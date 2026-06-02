The Publication_Maps directory owns the embedded **Scalp Maps** tool. The
current implementation is BCA-only: it renders condition-level grand-average
scalp maps from workbook `BCA (uV)` sheets after selecting significant harmonics
through the locked Stats group-level significant-harmonics path.

Rules:

- Do not add SNR or z-score map generation unless a new plan explicitly scopes
  those features.
- Significant harmonics must come from
  `Tools.Stats.analysis.dv_policy_group_significant.build_group_significant_harmonic_selection`.
  This preserves the Stats calculation and allows in-memory/project cache reuse.
- BCA summation must use the exact selected `"{freq:.4f}_Hz"` columns, matching
  Stats behavior. Do not add nearest-column fallback.
- Keep workbook reading, BCA aggregation, source-data export, and rendering in
  GUI-free modules. `gui.py` may gather settings and launch workers, but workers
  must not touch widgets.
- Preserve signed BCA values in exported source data. Rendered BCA values may
  clip negative values to the low color, and the source workbook must make that
  visible.
- Visible figure titles should be condition names only. Selected harmonics,
  subject counts, and cache/source provenance belong in exports and diagnostics.
- Single-condition and paired-condition figures should fit a standard US letter
  journal text width: 8.5-inch page minus 1-inch margins = 6.5 inches.
- Paired-condition figures are selected explicitly in the GUI with Condition A
  and Condition B combo boxes populated from the checked condition list.
- Default project input is the active project's Excel root. Default output is
  the selected folder, initially `<results root>/4 - Scalp Maps`.
- BCA color endpoints are user-selectable. The fixed BCA range is optional:
  it starts checked with a `0.0` to `0.4 BCA` range; unchecked maps
  auto-scale.
- The BCA colorbar label is `Baseline-corrected amplitude (µV)`. Figure fonts
  should use shared component typography roles, not one-off Matplotlib defaults.
- Do not run offscreen Qt workflows locally.

Focused checks:

```powershell
Get-ChildItem src\Tools\Publication_Maps\*.py | ForEach-Object { .\.venv\Scripts\python.exe -m py_compile $_.FullName }
.\.venv\Scripts\python.exe -m pytest tests\publication_maps -q
.\.venv\Scripts\python.exe -m pytest tests\stats\analysis\test_fixed_predefined_harmonics.py tests\stats\analysis\test_full_snr_reference_equivalence.py -q
.\.venv\Scripts\python.exe .agents\skills\pyside6-gui-cleanup\scripts\audit_gui_imports.py
.\.venv\Scripts\python.exe .agents\skills\project-path-audit\scripts\audit_hardcoded_paths.py
```
