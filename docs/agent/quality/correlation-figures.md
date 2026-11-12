# Correlation Figure Recipe

Use this reusable format for prepared, participant-level score/response pairs.
It captures the approved combined and individual correlation-plot style.
The [figure standard](figure-generation.md) remains authoritative for typography
and export quality.

This is an executable rendering reference, not an implemented toolbox
correlational-analysis feature. It does not read EEG, discover datasets, select
harmonics, choose associations, exclude participants, run a permutation screen,
or define a multiple-testing family.

## Run the template

From the repository root, use the existing environment described in
[development setup](../guides/development.md):

~~~console
python docs/agent/references/correlation-figure-template/render.py --spec docs/agent/references/correlation-figure-template/example.json --output-dir "<chosen-results-folder>"
~~~

The supplied [spec](../references/correlation-figure-template/example.json) and
[CSV](../references/correlation-figure-template/example_points.csv) are synthetic.
They contain no ACR observations or study-specific exclusions. For real work,
copy the spec, provide the reviewed pairs and their analysis estimates, and
select the active project or user-requested results folder. Use `--overwrite`
only when replacing that named output set is intended.

The [renderer](../references/correlation-figure-template/render.py) creates:

- One combined figure for two or three panels.
- One individual figure per panel.
- Matching PNG/PDF pairs and a JSON receipt with source hashes, participants,
  exact estimates and output hashes.

One-panel input creates only the individual figure. Names are
`<stem>-combined`, `<stem>-<panel-id>` and `<stem>-receipt.json`.
The renderer writes only these names and never cleans unrelated files.

## Input contract

The CSV has one row per participant per panel:

| Field | Meaning |
| --- | --- |
| `panel` | ID from the spec, independent of the displayed label. |
| `participant` | Stable ID, unique within that panel. |
| `x` | Numeric symptom/behavioral score, in the declared score metric. |
| `y` | Numeric response, in the declared units. |

Use already matched, eligible pairs. Missing/nonfinite values, duplicate IDs,
constant variables, inconsistent counts and undeclared panels are errors.
The renderer does not silently drop observations or pool protocol eras.

The version-1 JSON spec defines `stem`, relative/absolute `data`, `data_sha256`,
a short `header`, `y_label`, `slope_unit`, `provenance`, and one to three `panels`.
Each panel supplies `id`, `label`, `x_label`, `n`, and a `spearman` object
containing full-precision `rho`, uncorrected `p`, and `p_method`.
An optional `q` also requires `family_size`, `correction_method` and
`correction_id` (`benjamini_hochberg` or `benjamini_yekutieli`). This ensures
the FDR label is not used for a Holm/Bonferroni adjusted p-value. Omit `q`
when it was not calculated; the plot then omits the adjusted-result line.

`data_sha256` hashes UTF-8 CSV text after removing an optional BOM and normalizing
line endings to LF. This makes the reference portable between Windows and Linux.
After upstream analysis has been rerun against the intended CSV, calculate it as:

~~~python
import hashlib
from pathlib import Path

path = Path("prepared_points.csv")
digest = hashlib.sha256(path.read_text(encoding="utf-8-sig").encode("utf-8")).hexdigest()
~~~

Changing this hash alone does not validate stale p/q values. Preserve upstream
analysis provenance. The renderer independently checks rho against the plotted
pairs but cannot establish the provenance of supplied p/q values.

Record the response definition, ROI electrodes, condition/protocol era, harmonic
list or selection fingerprint, score raw/T metric, sample/exclusion policy,
inference method and testing family in `provenance`. These details belong in the
receipt or accompanying methods, rather than a large footer. An omission-note
preference for one figure is not permission to silently change future cohorts.

For FPVS work, consume canonical exported responses with the exact accepted
harmonic list and fingerprint. Resolve participants/groups through the public
project dataset index upstream. Keep the plotting template independent of
workbook discovery and acquisition-specific behavior.

## Statistical labels

| Position | Display | Statistical meaning |
| --- | --- | --- |
| Upper right, inside axes | Spearman rho, uncorrected p, optional FDR q and family size | Supplied rank-correlation inference for exactly the plotted pairs. |
| Lower left, inside axes | Slope with units; `Linear p` | Ordinary least squares with an intercept; two-sided slope test. |
| On the fitted line | `Linear R²` | OLS explained variation in this sample, equal to Pearson r squared. |
| Shaded band | 95% CI for mean | Pointwise Student-t interval for the fitted conditional mean. It is not a prediction interval or a CI for rho. |

**Never square Spearman rho and label it linear R².** The linear and rank tests
can disagree, especially with ties or influential observations. Keep both
p-values explicitly associated with their methods. Do not imply that a small
rank-test p validates the straight-line fit.

Use the original, declared multiple-testing family. Do not recalculate q over
only the displayed or significant panels. A later user-defined family remains
an exploratory follow-up unless it was specified independently of the results.
Use full precision in inputs; round only the displayed text.

OLS, its conditional-mean interval, linear p and R² are calculated from the
plotted pairs. Their usual linear-model assumptions still apply. The template
does not choose a more suitable model, adjust covariates, establish causality,
or validate prediction.

## Visual template

- Arial through `Main_App.exports.figure_style`, 10-point axes, legends and
  annotations. Shared scientific typography stays independent of GUI styling.
- Blue points `#22779B`, orange fit `#A74D18`, pale band `#F5DAC5`,
  ink `#21333E`, light horizontal grid `#DFE5E8`; white background.
- Actual participant coordinates, without jitter, winsorization, smoothing,
  truncation or aesthetic exclusions.
- A short condition/ROI header and sample size. If panel counts differ, show
  the actual count inside each panel. Put full captions and methods outside
  the artwork.
- Statistics inside each panel, R² aligned with the line, no bottom statistics
  row. Avoid automatic significance stars or causal titles.
- Physical sizes: 6 x 4.2 inches for one panel, 8 x 4.2 for two,
  11.5 x 4.2 for three. Adapt the layout when the intended publication width
  differs; do not shrink lettering to force it to fit.
- Shared y limits across comparable panels and their individual exports.
  Optional `y_limits: [min, max]` must contain all points and confidence bands.
  Submit separate specs when response units/endpoints are not comparable.
- Optional panel `r2_fraction` (default 0.62) positions the line label within
  15%-85% of the observed x range. Move that label or adapt the layout when it
  overlaps observations; do not remove observations. Markers render above the
  line label so its background cannot hide a participant. Check that the
  label remains readable, and widen panels if necessary.

The script detects clipped text and annotations outside axes. It cannot
guarantee that every label avoids every point. Inspect all final figures.

## 600-dpi PNG and PDF

Export using the shared 600-dpi constant at the intended physical size.
At the template sizes, PNGs are 3600 x 2520, 4800 x 2520 or 6900 x 2520 pixels.
PNG metadata may report 599.9988 dpi due to storage rounding.

A vector PDF has no single intrinsic DPI. This reference deliberately embeds
the point and confidence-band layers at **600 effective dpi**, while preserving
text, axes and fitted lines as vectors. It sets `rasterized=True` on those two
graphical layers and saves the PDF with `dpi=600`. Merely adding a DPI label to
PDF metadata does not establish image resolution.

Effective image DPI is image pixels divided by its placement size in inches.
The [read-only verifier](../references/correlation-figure-template/verify_exports.py)
checks the image transformations, page/PNG dimensions, one-page structure,
searchable Arial text and PNG metadata:

~~~console
python docs/agent/references/correlation-figure-template/verify_exports.py --receipt "<chosen-results-folder>/synthetic-correlations-receipt.json"
~~~

The verifier needs Pillow and pypdf. Use the bundled document/PDF Python runtime
when those are not in the repo environment; this reference adds no application
dependency. It intentionally rejects a vector-only PDF for this explicit
raster-resolution contract, even though vector artwork is resolution-independent.

Render every exported PDF with Poppler and visually inspect it along with the
PNGs. Verify point counts, score/response units, line placement, sample size and
the two different p-value labels. Keep QA renderings outside the final results
folder. Do not run offscreen Qt; this reference uses Matplotlib Agg only.

## Possible future correlational-analysis tool

A future tool could reuse this presentation. It would separately need canonical
dataset discovery, verified score joins, declared ROI/condition/protocol cells,
explicit Pearson/Spearman and p-value choices, frozen testing families,
missingness/exclusion controls, and reproducible analysis receipts. Its GUI
would use the normal worker and project boundaries.

That tool is a future idea, not current functionality or an active implementation
plan. The rendering reference must not become an implicit analysis method,
replace Stats' harmonic selection, or broaden the existing Sensitivity Analysis
calculator.
