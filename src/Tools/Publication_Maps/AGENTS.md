The Publication_Maps directory owns the embedded **Scalp Maps** tool. The
current implementation renders condition-level grand-average BCA, SNR, and
z-score scalp maps using the significant-harmonic list saved at processing
completion.

Rules:

- Included harmonics must come from the cache-only
  `Tools.Stats.analysis.canonical_harmonics.load_project_processing_harmonics`
  API. Scalp Maps must never calculate, substitute, or silently refresh the
  processing-time list. Missing or stale metadata is a hard, user-actionable
  reprocess/recalculate error.
- BCA summation and SNR averaging must use the exact selected `"{freq:.4f}_Hz"`
  columns, matching Stats behavior. Do not add nearest-column fallback.
- Z-score maps read the `Z Score` sheet, use the exact selected
  `"{freq:.4f}_Hz"` columns, and combine selected harmonics as
  `sum(z) / sqrt(K)` before the condition grand average.
- Keep workbook reading, metric aggregation, source-data export, and rendering
  in GUI-free modules. `gui.py` may gather settings and launch workers, but
  workers must not touch widgets.
- Preserve signed BCA values in exported source data. Rendered BCA values may
  clip negative values to the low color, and the source workbook must make that
  visible.
- Visible figure titles should be condition names only. Selected harmonics,
  subject counts, and cache/source provenance belong in exports and diagnostics.
- Single-condition and paired-condition figures should fit a standard US letter
  journal text width: 8.5-inch page minus 1-inch margins = 6.5 inches.
- Paired-condition figures are selected explicitly in the GUI with Condition A
  and Condition B combo boxes populated from the checked condition list.
- When BCA and SNR are selected, paired-condition export should render one
  combined figure: BCA on the first row, SNR on the second row, and, when
  selected, Z Score on the third row, with condition titles only above the first
  row.
- Paired-condition export is paired-only and is the GUI default: when it is
  enabled, render only the combined paired `.png` and `.pdf`, not individual
  condition figures.
- Default project input is the active project's Excel root. Default output is
  the selected folder, initially `<results root>/4 - Scalp Maps`.
- BCA color endpoints are user-selectable. The fixed BCA range is optional:
  it starts checked with a `0.0` to `0.4 BCA` range; unchecked maps
  auto-scale.
- SNR uses the same color endpoints. The fixed SNR range is optional: it starts
  checked with a `1.0` to `1.5 SNR` range; unchecked maps auto-scale.
- Shared BCA/SNR scalp-map color stops live in
  `src/Tools/Publication_Maps/colormaps.py`; edit the shared ramp there instead
  of introducing metric-specific copies in Scalp Maps renderers.
- The BCA colorbar label is `Baseline-corrected amplitude (µV)`. Figure fonts
  should use `Main_App.exports.figure_style`, not GUI typography roles or
  one-off Matplotlib defaults.
- The SNR colorbar label is `Signal to Noise Ratio`.
- Z-score maps render values below the configurable z threshold as white. The
  default threshold is `1.64`, and the upper z color limit is always automatic
  from the maximum z-score across the rendered z-score map pair.
- Do not run offscreen Qt workflows locally.

Focused local verification:

```powershell
python .agents/scripts/verify.py --scope publication-maps --tier focused
python .agents/scripts/verify.py --scope stats --tier focused
```

The second scope protects the shared processing-time harmonic contract. Qt
execution remains CI-only by default.
