# Figure Generation Standard

Use this page for FPVS Toolbox code, tests, docs, or agent work that creates,
edits, validates, or documents scientific figure exports. Apply the defaults
below to new general-purpose figures and tools. FPVS Studio uses the same
editorial and raster quality defaults.

## Output Contract

- Export publication figures as matching `.pdf` and `.png` files by default.
- Render `.png` exports and generated raster layers embedded in PDFs at
  **600 DPI or higher**. Evaluate resolution at the intended placed size.
- Use one single-page PDF per numbered figure or exported figure file.
- Keep SVG in the existing Sequence Figure export and publication-table
  workflows. Publication tables use SVG plus 600-DPI PNG. General-purpose
  publication figures use PDF plus PNG.
- Choose the placed size first. The FPVS 600-DPI floor is an export policy.
  Report native image detail separately when a source tile is too small for
  its placed dimensions. Enlarging the output raster adds no source detail.
- Retain editable text and linework in vector exports. Embed TrueType fonts
  where the format supports them. Use the target venue's format and size when
  it specifies them.
- Preserve generated source data, workbook rows, or reproducible code paths
  needed to verify the plotted values.

## Layout and Typography Defaults

Plan for 89 mm single-column or 183 mm double-column placement. Use the
double-column width for wide FPVS stimulus strips. Set type and strokes at the
placed size. The default type sizes are 7 pt for a title, 6 pt for axis and
legend labels, and 5 pt for ticks and essential notes. Use 8 pt bold lowercase
panel letters when a multipart figure needs them. Use consistent dark
sans-serif lettering on white. Prefer Arial or Helvetica and use the bundled
sans-serif for renderers that need portable font assets. Use roughly
0.25–1 pt strokes and retain meaningful tick marks and units.
[Nature panel and typography guidance](https://research-figure-guide.nature.com/figures/building-and-exporting-figure-panels/) ·
[Nature line weight guidance](https://research-figure-guide.nature.com/figures/extended-data-formatting-guidelines/#line-weights)

Center a short title when it identifies the condition or comparison. Omit
subtitles, repeated headings, routine status text, and decorative marks.
Keep only text needed to read the figure, such as rates, units, comparison
keys, and scientific annotations. Put captions, detailed methods and
provenance outside the artwork. Favor compact margins and place a short
legend below the plot when it preserves useful width. Use colored swatches
with dark labels. Keep series distinguishable through position, shape, or
line style and verify legibility in grayscale.
[Nature figure specifications](https://research-figure-guide.nature.com/figures/preparing-figures-our-specifications/)

## Retained Toolbox Profiles

- Figure typography is separate from GUI typography. Existing Elsevier-style
  renderers use the shared constants and Matplotlib/PIL text helpers in
  `src/Main_App/exports/figure_style.py`. Keep that profile when reproducing
  those outputs. Adopt a different profile within the affected tool or
  exporter when the work calls for it.
- Use `Main_App.exports.figure_style.FIGURE_EXPORT_DPI` for the shared raster
  export floor when adding a renderer.
- Publication tables use the separate GUI-neutral
  `src/Main_App/exports/table_style.py` contract. They must not import GUI
  typography or GUI style tokens.
- Do not import GUI typography helpers, `Main_App.gui.typography`, or
  `Main_App.gui.components.matplotlib_font_kwargs` from figure renderers.
- The retained Elsevier profile uses Arial and 10 pt axis labels, ticks,
  legends, and annotations. Panel letters use 12 pt bold uppercase. Small
  scientific labels and superscripts or subscripts have a 7 pt minimum.
- Follow existing tool-specific format and geometry requirements, including the
  [Sequence Figure contract](../../../src/Tools/Sequence_Figure/AGENTS.md).

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

## Correlation Plot Template

Use the [correlation figure recipe](correlation-figures.md) and its runnable,
synthetic example for combined or individual score/response scatterplots.
It preserves in-panel statistics, linear R squared on the fitted line, and
explicit 600-dpi PDF graphical layers alongside vector text. The recipe keeps
Spearman inference distinct from OLS/Pearson statistics and does not select
associations or redefine testing families.

## Verification

For figure-output changes, run the shared figure contract and then the affected
tool scope:

```console
python .agents/scripts/verify.py --scope figures --tier focused
python .agents/scripts/verify.py --scope <affected-tool> --tier focused
```

The driver selects `.venv1` or `.venv`, checks changed renderers explicitly,
and keeps registered Qt tests out of local execution. Document a visible/manual
smoke path for GUI-owned figure actions.

Inspect the exported files at placed size for clipping, label collisions,
legibility, correct units and faithful data. Verify the raster dimensions and
DPI together. For vector output, check that text remains editable and that
embedded raster layers preserve their intended resolution.
