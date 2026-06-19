# Figure Generation Standard

Use this page for FPVS Toolbox code, tests, docs, or agent work that creates,
edits, validates, or documents publication-oriented figure outputs.

## Output Contract

- Export publication figures as matching `.pdf` and `.png` files by default.
- Use `600 dpi` for `.png` outputs and for raster content embedded in generated
  PDFs.
- Use one single-page PDF per numbered figure or exported figure file.
- Do not add `.svg` as a publication default. SVG may be restored only for a
  narrowly scoped workflow that explicitly needs it.
- Choose the intended physical figure size before rendering. DPI is evaluated at
  final size, not after later scaling.
- Preserve generated source data, workbook rows, or reproducible code paths
  needed to verify the plotted values.

## Typography

Figure typography is separate from GUI typography.

- Use `src/Main_App/exports/figure_style.py` for shared figure constants and
  Matplotlib/PIL text helpers.
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

For figure-output changes, use the narrowest relevant non-GUI checks first:

```powershell
.\.venv1\Scripts\python.exe -m py_compile src\Main_App\exports\figure_style.py
.\.venv1\Scripts\python.exe -m pytest tests\audit\test_figure_style_contract.py -q
.\.venv1\Scripts\python.exe -m pytest tests\plot_generator\test_plot_generator_export_pdf_smoke.py tests\plot_generator\test_plot_generator_group_overlay_worker.py -q
.\.venv1\Scripts\python.exe -m pytest tests\publication_maps\test_bca_publication_maps.py -q
.\.venv1\Scripts\python.exe -m pytest tests\ratio_calculator\test_ratio_calculator_plots.py -q
.\.venv1\Scripts\python.exe -m pytest tests\processing\test_individual_detectability_core.py -q
.\.venv1\Scripts\python.exe -m pytest tests\loreta\test_demo_conditions.py tests\loreta\test_project_l2_mne_export.py -q
```

If `.venv1` is unavailable, use the local equivalent and report the
substitution. Do not run offscreen Qt workflows locally.
