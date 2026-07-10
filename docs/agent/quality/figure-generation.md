# Figure Generation Standard

Use this page for FPVS Toolbox code, tests, docs, or agent work that creates,
edits, validates, or documents publication-oriented figure outputs.

## Output Contract

- Export publication figures as matching `.pdf` and `.png` files by default.
- Use `600 dpi` for `.png` outputs and for raster content embedded in generated
  PDFs.
- Use one single-page PDF per numbered figure or exported figure file.
- Do not add `.svg` as a general publication-figure default. The retained
  publication-table exporter is the narrow exception: table-only assets use
  SVG plus 600-DPI PNG so text remains editable and the raster output remains
  manuscript-ready.
- Choose the intended physical figure size before rendering. DPI is evaluated at
  final size, not after later scaling.
- Preserve generated source data, workbook rows, or reproducible code paths
  needed to verify the plotted values.

## Typography

Figure typography is separate from GUI typography.

- Use `src/Main_App/exports/figure_style.py` for shared figure constants and
  Matplotlib/PIL text helpers.
- Publication tables use the separate GUI-neutral
  `src/Main_App/exports/table_style.py` contract. They must not import GUI
  typography or GUI style tokens.
- Do not import GUI typography helpers, `Main_App.gui.typography`, or
  `Main_App.gui.components.matplotlib_font_kwargs` from figure renderers.
- Use Arial for all figure text.
- Axis labels, tick labels, legends, and annotations are 10 pt.
- Panel labels are uppercase, 12 pt, and bold.
- Small secondary labels are no smaller than 7 pt.
- Superscripts and subscripts are no smaller than 7 pt.
- Keep full captions and manuscript figure titles outside the artwork unless a
  tool has a specific scientific reason for a short internal condition label.

## FPVS Figure Rules

- Frequency spectra and response plots must label frequency in Hz and response
  units explicitly, for example `SNR` or `Baseline-corrected amplitude (uV)`.
- Stimulation frequencies and harmonics should be marked consistently and must
  not rely on color alone.
- Scalp-map figures being directly compared should share color limits unless a
  scientific reason for different limits is clear and documented.
- Scalp maps need color bars with units and clear zero/threshold handling.
- Source-map visualizer figures must display already-computed payload values
  only. Renderer code must not compute inverse solutions, z-scores, cluster
  masks, lateralization statistics, or source-localization values.
- Do not smooth, interpolate, resample, selectively mask, or alter data for
  appearance unless the scientific transformation is explicitly scoped and
  documented.

## Verification

For figure-output changes, run the shared figure contract and then the affected
tool scope:

```powershell
python .agents/scripts/verify.py --scope figures --tier focused
python .agents/scripts/verify.py --scope <affected-tool> --tier focused
```

The driver selects `.venv1` or `.venv`, checks changed renderers explicitly,
and keeps registered Qt tests out of local execution. Document a visible/manual
smoke path for GUI-owned figure actions.
