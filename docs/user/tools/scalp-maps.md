# Scalp Maps

Use this page when you want publication-ready BCA or SNR scalp maps from
processed FPVS Toolbox Excel outputs.

The Scalp Maps tool opens from the main app sidebar as **Scalp Maps**. It reads
condition folders from `1 - Excel Data Files` and saves figures plus an audit
workbook to the selected output folder, initially `4 - Scalp Maps`.

## When to use it

Use this tool after the processing pipeline has created participant Excel
workbooks for each condition.

It is useful when you need:

- condition-level grand-average BCA and SNR scalp maps;
- one shared significant-harmonic list selected with the Statistics tool
  method;
- transparent SVG figures for PowerPoint, Illustrator, Inkscape, Affinity
  Designer, or similar figure-composition software;
- a selected pair of condition scalp maps on one figure;
- source data that documents exactly which values were plotted.

The current Scalp Maps tool generates BCA and SNR scalp maps. It does not
generate z-score scalp maps.

## Inputs

The input folder should be the project Excel root, usually
`1 - Excel Data Files`. Each condition should have its own folder containing
participant workbooks from the processing pipeline.

The tool reads:

- `FullFFT Amplitude (uV)` to select significant harmonics with the Statistics
  tool group-level harmonic-selection method;
- `BCA (uV)` to sum the selected harmonic amplitudes for each electrode;
- `SNR` to calculate the mean selected-harmonic SNR for each electrode.

Base frequency and the BCA upper frequency limit come from project settings, so
you do not need to re-enter them in this tool. Change those settings in the main
project settings if the analysis defaults are wrong.

## Significant harmonics

Scalp Maps uses the same group-level significant-harmonic policy as the
Statistics tool. The selected harmonic list is common across participants,
conditions, and scalp electrodes.

If a matching Statistics significant-harmonics cache is already saved for the
project, Scalp Maps can reuse it. If no matching cache is available, the tool
computes the selection using the same locked Statistics method.

Only exact selected frequency columns are used. The tool sums selected
`BCA (uV)` columns and averages selected `SNR` columns; it does not use
nearest-bin matching for plotted values.

## Color scale

Choose the metrics to export with the **BCA** and **SNR** checkboxes. Both
metrics start checked.

The default palette maps low values to blue and high values to red for both
metrics.

The fixed BCA range is checked by default with:

- lower limit: `0.0 BCA`;
- upper limit: `0.4 BCA`.

The fixed SNR range is checked by default with:

- lower limit: `1.0 SNR`;
- upper limit: `1.5 SNR`.

Keep the fixed range checked when you want all exported maps for that metric to
use the same colorbar. Uncheck it when each scalp map should auto-scale to its
own values.

Use the low and high color selectors if a journal, slide deck, or collaborator
requires a different palette.

## Paired condition figures

Check **Also export paired condition figures** when you want two scalp maps on
one figure. The paired controls let you choose **Condition A** and
**Condition B** from the checked condition list, following the same general
condition-pair layout as the SNR Plot Generator.

Keep both conditions checked in the Conditions list so the tool computes their
grand-average maps before building the paired figure.

## Output files

The output folder can contain:

- `.png` figures for direct manuscript or presentation use;
- transparent `.svg` figures for editing and figure composition;
- selected paired-condition `.png` and `.svg` figures when the paired option is
  enabled;
- `Publication_Scalp_Maps_Source_Data.xlsx`.

SVG files are saved without a white background so they can be placed over a
slide, panel background, or multipart figure design.

## Source workbook

The source workbook is the audit trail for the exported figures. It includes:

- one row per condition, participant, electrode, selected harmonic, source
  sheet, source column, metric, and raw value;
- grand-average values per condition and electrode;
- diagnostics for missing sheets, missing columns, missing montage electrodes,
  and rendering notes;
- parameters such as selected harmonics, output formats, color scaling, and
  cache source.

Use the workbook when you need to confirm how a plotted value was produced or
when you need source data for a manuscript supplement.
