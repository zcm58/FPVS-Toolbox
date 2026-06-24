# Feature Tour

Use this page when you want a quick map of the main FPVS Toolbox features and when to use each one.

This page lists the main FPVS Toolbox features and when to use each one.

## Core features

| Feature | What it does | When to use it | Main output |
|---|---|---|---|
| Project setup | Stores project, group, condition, and trigger configuration | At the start of every study | Project settings and folder structure |
| EEG processing pipeline | Loads `.bdf`, preprocesses, epochs, runs FFT, computes metrics | After project setup and before stats | Per-condition Excel files |
| Harmonic selection (Rossion) | Selects oddball harmonics to include in Summed BCA | When building ROI-level dependent variables | Summed BCA DV Definition export |
| RM-ANOVA | Tests within-subject condition/ROI effects | Balanced repeated-measures designs | ANOVA result tables |
| Mixed model | Models repeated measures with participant random intercept | When data may be slightly unbalanced or for flexible modeling | Mixed model fixed-effects table |
| Post-hoc tests | Finds specific condition pairs that differ within each ROI | After significant interaction effects | Pairwise comparison tables |
| Baseline vs zero tests | Tests whether a condition ROI response is above no-response baseline | Detectability checks | Baseline vs Zero workbook |
| Outliers and QC | Flags unusual values and separates flags from exclusions | Before final inferential reporting | Flagged and excluded participant reports |
| SNR Plot Generator | Builds publication-oriented SNR or BCA plots from processed Excel outputs | After processing when you need ROI or condition figures | Plot image files |
| Scalp Maps | Builds publication-ready BCA scalp maps with Statistics-selected significant harmonics | After processing when you need condition-level scalp figures | PNG/PDF scalp maps and source-data workbook |
| LORETA Visualizer | Displays an experimental 3D brain mesh with synthetic maps, beta L2-MNE cortical maps, and beta eLORETA volume maps | When reviewing source-visualization behavior and beta source maps after preprocessing and Stats export | Interactive viewport plus project-local source JSON |
| Ratio Calculator | Compares two condition folders and computes participant-level ratios | When a ratio between two processed conditions is part of the analysis | Ratio tables and plots |
| Sequence Figure | Builds a five-slot FPVS stimulus sequence illustration from manually selected images | When preparing methods figures for slides, posters, theses, or manuscripts | 600 DPI PNG plus PDF/SVG figure files |
| Image Resizer | Batch-resizes stimulus images and converts file formats | Before running an FPVS experiment that needs standardized image dimensions | Resized stimulus image folder |
| Epoch Averaging | Combines preprocessed epochs before post-processing | When multiple preprocessed files should contribute to one averaged response | Averaged files for downstream processing |
| Individual-level detectability tool | Creates participant-level topomap plus mini-spectrum figures | Participant-level reporting and diagnostics | Detectability figures |

## Typical order of use

1. Configure project and event map.
2. Run processing pipeline.
3. Confirm outputs in Excel.
4. Run harmonic selection and inferential statistics.
5. Generate QC reports, plots, ratios, or optional individual-level figures.

## Related docs

- [Processing Pipeline Overview](../study/processing-pipeline.md)
- [Statistical Analysis Overview](../results/statistical-analysis.md)
- [Output Files](../study/outputs-reference.md)
- [SNR Plot Generator](snr-plot-generator.md)
- [Scalp Maps](scalp-maps.md)
- [LORETA Visualizer](loreta-visualizer.md)
- [Ratio Calculator](ratio-calculator.md)
- [Sequence Figure](sequence-figure.md)
- [Image Resizer](image-resizer.md)
- [Epoch Averaging](epoch-averaging.md)
